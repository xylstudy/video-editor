"""快速端到端流程：利用现有分析 + 新素材 + 剪辑手法学识 → 生成方案 → Remotion 渲染"""
import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from config.llm_client import LLMTools
from config import settings
from config.output_manager import OutputManager
from agents.planner import PlannerAgent
from agents.reviewer import ReviewerAgent
from knowledge.techniques_loader import get_summary
from models.gene import build_gene
from skills.router import SkillRouter
from skills.verifier import (
    attach_skill_outcomes,
    initialise_skill_trace,
    verify_skill_usage,
)

PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args():
    parser = argparse.ArgumentParser(description="快速端到端结构迁移 Pipeline")
    parser.add_argument(
        "--struct",
        type=str,
        required=True,
        help="视频结构分析结果路径",
    )
    parser.add_argument(
        "--struct-analysis",
        type=str,
        required=True,
        help="结构分析详细结果路径",
    )
    parser.add_argument(
        "--photo-dir",
        type=str,
        default="",
        help="用户照片素材目录；未传 --inventory 时使用",
    )
    parser.add_argument(
        "--inventory",
        type=str,
        default="",
        help="已分析的素材库存 JSON",
    )
    parser.add_argument(
        "--topic",
        type=str,
        default="我的短视频",
        help="目标视频主题",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default="pipeline_e2e_techniques",
        help="本次运行 ID（默认: pipeline_e2e_techniques）",
    )
    parser.add_argument(
        "--knowledge-context",
        type=str,
        default="",
        help="当前用户个人知识 JSON；由 Web 后端按用户过滤后传入",
    )
    parser.add_argument("--output", type=str, default="", help="最终视频精确输出路径")
    parser.add_argument("--scheme-output", type=str, default="", help="最终方案 JSON 输出路径")
    parser.add_argument("--prepare-only", action="store_true", help="只生成分镜草案，不渲染")
    return parser.parse_args()


def infer_target_duration(topic: str, reference_duration: float = 0) -> float:
    """Prefer an explicit duration in the topic, then the reference duration."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:秒|s(?:ec(?:ond)?s?)?\b)", topic, re.IGNORECASE)
    if match:
        return max(1.0, min(600.0, float(match.group(1))))
    if reference_duration > 0:
        return max(1.0, min(600.0, float(reference_duration)))
    return 45.0


def normalize_storyboard_duration(scheme_data: dict, target_duration: float) -> dict:
    """Scale model-proposed shot durations to an exact, deterministic total."""
    frames = scheme_data.get("storyboard", [])
    if not frames or target_duration <= 0:
        return scheme_data

    durations = [max(0.2, float(frame.get("duration", 3.0))) for frame in frames]
    total = sum(durations)
    if total <= 0:
        return scheme_data

    scaled = [max(0.2, round(value * target_duration / total, 3)) for value in durations]
    scaled[-1] = round(scaled[-1] + target_duration - sum(scaled), 3)
    if scaled[-1] < 0.2:
        deficit = round(0.2 - scaled[-1], 3)
        scaled[-1] = 0.2
        for index in range(len(scaled) - 2, -1, -1):
            available = max(0.0, scaled[index] - 0.2)
            taken = min(available, deficit)
            scaled[index] = round(scaled[index] - taken, 3)
            deficit = round(deficit - taken, 3)
            if deficit <= 0:
                break

    for frame, duration in zip(frames, scaled):
        frame["duration"] = duration
    scheme_data["target_duration"] = round(sum(scaled), 3)
    return scheme_data


def build_material_type_hint(inventory: dict) -> str:
    """Describe the real inventory instead of forcing a photo-only style."""
    items = inventory.get("items") or inventory.get("materials") or []
    counts: dict[str, int] = {}
    for item in items:
        material_type = str(item.get("type") or "unknown").lower()
        counts[material_type] = counts.get(material_type, 0) + 1

    video_count = counts.get("video", 0)
    image_count = counts.get("image", 0) + counts.get("photo", 0)
    if video_count and image_count:
        return (
            f"素材包含 {video_count} 个视频和 {image_count} 张图片。"
            "视频优先保留原始运动，图片再按叙事需要使用 Ken Burns；不要给所有镜头套同一种运动。"
        )
    if video_count:
        return (
            f"全部为视频素材（共 {video_count} 个）。优先利用素材自身的运动、构图和动作节点，"
            "不要按静态照片方案统一套 Ken Burns。"
        )
    if image_count:
        return (
            f"全部为静态图片素材（共 {image_count} 张）。根据每个镜头的功能选择不同的推、拉、平移或静止，"
            "不要机械轮换效果。"
        )
    return "请根据素材清单中的真实类型、运动信息和构图逐镜决定剪辑方式。"


def apply_render_decisions(scheme_dict: dict, frame_decisions: list[dict]) -> dict:
    """Write Renderer decisions back without dropping component settings."""
    decisions_map = {decision.get("index"): decision for decision in frame_decisions}
    for frame in scheme_dict.get("storyboard", []):
        decision = decisions_map.get(frame.get("index"))
        if not decision:
            continue
        if decision.get("render_component"):
            frame["render_component"] = decision["render_component"]
        if isinstance(decision.get("custom_render_config"), dict):
            existing = frame.get("custom_render_config") or {}
            frame["custom_render_config"] = {
                **existing,
                **decision["custom_render_config"],
            }
    return scheme_dict


def apply_reference_effect_contract(scheme_dict: dict, gene: dict) -> dict:
    """Apply reference timing and signature effects after probabilistic planning.

    The Planner may describe the right mood while omitting the concrete render
    fields. This deterministic pass keeps high-priority Gene evidence intact.
    """
    if not isinstance(scheme_dict, dict) or not isinstance(gene, dict):
        return scheme_dict
    storyboard = scheme_dict.get("storyboard")
    if not isinstance(storyboard, list) or not storyboard:
        return scheme_dict

    target_duration = float(
        scheme_dict.get("target_duration")
        or sum(float(frame.get("duration", 0) or 0) for frame in storyboard if isinstance(frame, dict))
        or gene.get("duration", 0)
        or 1
    )
    reference_duration = float(gene.get("duration", 0) or target_duration or 1)
    scale = target_duration / reference_duration if reference_duration > 0 else 1.0

    if str(gene.get("source_aspect_ratio", "")) == "3:4":
        scheme_dict["canvas_width"] = 1080
        scheme_dict["canvas_height"] = 1440
        for frame in storyboard:
            if isinstance(frame, dict):
                frame["canvas_width"] = 1080
                frame["canvas_height"] = 1440

    cut_points = [
        float(value) * scale for value in gene.get("reference_cut_points", [])
        if isinstance(value, (int, float)) and 0 < float(value) < reference_duration
    ]
    if len(cut_points) == len(storyboard) - 1:
        boundaries = [0.0, *cut_points, target_duration]
        for index, frame in enumerate(storyboard):
            if isinstance(frame, dict):
                frame["duration"] = round(max(0.1, boundaries[index + 1] - boundaries[index]), 3)

    mapped_tracks = []
    for track in gene.get("effect_tracks", []) or []:
        if not isinstance(track, dict) or track.get("priority", "high") not in {"critical", "high"}:
            continue
        mapped = dict(track)
        mapped["start"] = round(float(track.get("start", 0) or 0) * scale, 3)
        mapped["end"] = round(float(track.get("end", track.get("start", 0)) or 0) * scale, 3)
        mapped_tracks.append(mapped)
    existing_tracks = [
        dict(track) for track in (scheme_dict.get("effect_tracks") or [])
        if isinstance(track, dict)
    ]
    if mapped_tracks:
        seen = {
            (str(track.get("type", "")), float(track.get("start", 0) or 0), float(track.get("end", 0) or 0))
            for track in mapped_tracks
        }
        mapped_tracks.extend(
            track for track in existing_tracks
            if (
                str(track.get("type", "")),
                float(track.get("start", 0) or 0),
                float(track.get("end", 0) or 0),
            ) not in seen
        )
        scheme_dict["effect_tracks"] = mapped_tracks
    else:
        scheme_dict["effect_tracks"] = existing_tracks

    def frame_starts() -> list[float]:
        starts, cursor = [], 0.0
        for item in storyboard:
            starts.append(cursor)
            cursor += float(item.get("duration", 0) or 0) if isinstance(item, dict) else 0.0
        return starts

    starts = frame_starts()
    transition_map = {
        "glitch_reveal": "glitch",
        "slice_wipe": "slice_wipe",
        "black_dip": "flash_black",
    }
    for track in mapped_tracks:
        effect_type = str(track.get("type", ""))
        if effect_type == "floating_music_ui":
            track.setdefault("component", "floating_music_ui")
            continue
        target_index = min(range(len(starts)), key=lambda index: abs(starts[index] - float(track.get("start", 0))))
        frame = storyboard[target_index]
        if not isinstance(frame, dict):
            continue
        if effect_type in transition_map:
            frame["transition_in"] = transition_map[effect_type]
            frame["motion_effect"] = effect_type
        elif effect_type == "search_cta_card":
            frame["render_component"] = "custom:search_cta_card"
            frame["custom_render_config"] = {
                **(frame.get("custom_render_config") or {}),
                **(track.get("parameters") or {}),
            }
            frame["shot_type"] = "info_card"
            frame["motion_effect"] = "structured_search_cta"

    component_map = {
        "push_in": ("custom:hero_push_in", "mapped"),
        "tracked_doodle": ("custom:doodle_pop", "degraded"),
        "subject_echo": ("custom:echo_stack", "degraded"),
        "cutout_outline": ("custom:torn_paper_frame", "degraded"),
        "panel_fold_reveal": ("custom:panel_fold_reveal", "mapped"),
    }
    event_transition_map = {
        "occlusion_wipe": "slice_wipe",
        "flash_white": "flash_white",
        "black_dip": "flash_black",
        "whip": "whip",
        "match_cut": "cut",
        "stop_motion": "freeze_frame",
        "speed_ramp": "cut",
    }
    mapped_count = 0
    degraded_count = 0
    unresolved: list[str] = []
    shot_genes = gene.get("shot_genes", []) or []
    for frame_index, frame in enumerate(storyboard):
        if not isinstance(frame, dict):
            continue
        gene_index = frame.get("gene_shot_index", frame_index)
        if not isinstance(gene_index, int) or gene_index < 0 or gene_index >= len(shot_genes):
            gene_index = frame_index
        shot_gene = shot_genes[gene_index] if gene_index < len(shot_genes) else {}
        events = shot_gene.get("effect_events", []) if isinstance(shot_gene, dict) else []
        event_ids = list(frame.get("effect_event_ids") or [])
        event_mapping = dict(frame.get("effect_mapping") or {})
        for event in events or []:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get("id") or f"shot_{gene_index:03d}_effect_{len(event_ids):02d}")
            if event_id not in event_ids:
                event_ids.append(event_id)
            effect_type = str(event.get("type") or "")
            current = event_mapping.get(event_id) if isinstance(event_mapping.get(event_id), dict) else {}
            status = str(current.get("status") or "")
            component = str(current.get("component") or "")
            reason = str(current.get("reason") or "")

            if not status and effect_type in component_map:
                component, status = component_map[effect_type]
                reason = (
                    "subject mask unavailable; using frame-level fallback"
                    if status == "degraded"
                    else "mapped from reference effect event"
                )
                if frame.get("render_component") in (None, "", "auto") or status == "mapped":
                    frame["render_component"] = component
                    frame["custom_render_config"] = {
                        **(frame.get("custom_render_config") or {}),
                        **(event.get("parameters") or {}),
                        "position": event.get("position") or {},
                        "motion_path": event.get("motion_path") or [],
                        "effect_event_id": event_id,
                    }
            elif not status and effect_type in event_transition_map:
                component = event_transition_map[effect_type]
                frame["transition_in"] = component
                frame["motion_effect"] = effect_type
                status = (
                    "mapped"
                    if effect_type not in {"match_cut", "speed_ramp", "stop_motion"}
                    else "degraded"
                )
                reason = (
                    "mapped to executable transition"
                    if status == "mapped"
                    else "semantic/temporal behavior preserved without subject-aware matching"
                )
            elif (
                status in {"", "unresolved"}
                and effect_type == "other"
                and str((event.get("parameters") or {}).get("grid") or "").lower() in {"2x2", "3x3"}
            ):
                component = "custom:split_screen_burst"
                status = "degraded"
                reason = "grid overlay preserved with the executable 2x2 split-screen component"
                nearby_ids: list[str] = []
                for nearby_index in range(max(0, frame_index - 2), min(len(storyboard), frame_index + 2)):
                    material_id = str(storyboard[nearby_index].get("source_material_id") or "")
                    if material_id and material_id not in nearby_ids:
                        nearby_ids.append(material_id)
                frame["render_component"] = component
                frame["custom_render_config"] = {
                    **(frame.get("custom_render_config") or {}),
                    **(event.get("parameters") or {}),
                    "source_material_ids": nearby_ids[:4],
                    "effect_event_id": event_id,
                }
            elif not status:
                fallback = str(event.get("fallback_type") or "")
                status = "degraded" if fallback else "unresolved"
                component = fallback
                reason = "using declared fallback" if fallback else "no executable component is registered"

            event_mapping[event_id] = {
                **current,
                "status": status,
                "component": component,
                "reason": reason,
            }
            if status == "mapped":
                mapped_count += 1
            elif status == "degraded":
                degraded_count += 1
            else:
                unresolved.append(event_id)
        frame["effect_event_ids"] = event_ids
        frame["effect_mapping"] = event_mapping

    total_events = mapped_count + degraded_count + len(unresolved)
    render_hints = dict(scheme_dict.get("render_hints") or {})
    render_hints["effect_contract"] = {
        "total": total_events,
        "mapped": mapped_count,
        "degraded": degraded_count,
        "unresolved": unresolved,
        "coverage": round((mapped_count + degraded_count) / total_events, 3) if total_events else 1.0,
        "full_fidelity_coverage": round(mapped_count / total_events, 3) if total_events else 1.0,
    }
    scheme_dict["render_hints"] = render_hints
    return scheme_dict


def apply_audio_contract(scheme_dict: dict, gene: dict | None = None) -> dict:
    """Make the reference soundtrack explicit and mute clip audio by default.

    Visual material audio is deliberately excluded from the default mix.  A
    future voice/ambient selector can opt individual clips back in without
    making today's output depend on whichever source file happens to contain
    a loud audio track.
    """
    if not isinstance(scheme_dict, dict):
        return scheme_dict
    gene = gene if isinstance(gene, dict) else {}
    config = dict(scheme_dict.get("audio_config") or {})
    source = str(config.get("source") or "reference").lower()
    config.setdefault("source", source)
    config.setdefault("volume", 0.3)
    config.setdefault("loop", True)
    config.setdefault("trim_before", 0)
    config.setdefault("trim_after", None)
    config.setdefault("fade_frames", 15)
    config.setdefault("original_audio_mode", "mute")
    config.setdefault("normalize", True)
    config.setdefault("target_lufs", -14.0)
    config.setdefault("true_peak", -1.0)
    scheme_dict["audio_config"] = config

    if source == "reference":
        bgm = dict(scheme_dict.get("bgm") or {})
        if not bgm.get("audio_path"):
            bgm["audio_path"] = "_viral_audio"
        bgm.setdefault("volume", config["volume"])
        bgm.setdefault("loop", config["loop"])
        bgm.setdefault("trim_before", config["trim_before"])
        bgm.setdefault("trim_after", config["trim_after"])
        scheme_dict["bgm"] = bgm
        if not scheme_dict.get("audio_source_id"):
            scheme_dict["audio_source_id"] = str(gene.get("source_id") or "reference")
    return scheme_dict


def apply_material_diversity_contract(
    scheme_dict: dict,
    inventory: dict,
    gene: dict | None = None,
) -> dict:
    """Measure material variety and expose a deterministic expansion request."""
    if not isinstance(scheme_dict, dict):
        return scheme_dict
    storyboard = [item for item in (scheme_dict.get("storyboard") or []) if isinstance(item, dict)]
    items = (inventory or {}).get("items", (inventory or {}).get("materials", []))
    available_ids = {
        str(item.get("id")) for item in items
        if isinstance(item, dict) and item.get("id")
    }
    used_ids = [
        str(frame.get("source_material_id") or "")
        for frame in storyboard
        if frame.get("source_material_id")
    ]
    counts = {material_id: used_ids.count(material_id) for material_id in sorted(set(used_ids))}
    unique_used = len(counts)
    shot_count = len(storyboard)
    # Every storyboard shot must have its own source material. A different
    # segment from the same file is still the same source and is not allowed.
    recommended_unique = shot_count
    available_shortfall = max(0, recommended_unique - len(available_ids))
    overused = {material_id: count for material_id, count in counts.items() if count > 1}
    longest_run = 0
    current_run = 0
    previous = None
    for material_id in used_ids:
        current_run = current_run + 1 if material_id == previous else 1
        longest_run = max(longest_run, current_run)
        previous = material_id

    gene = gene if isinstance(gene, dict) else {}
    requirements = []
    for shot_gene in gene.get("shot_genes", []) or []:
        if not isinstance(shot_gene, dict):
            continue
        if shot_gene.get("importance") not in {"critical", "high"} and not shot_gene.get("effect_events"):
            continue
        requirements.append({
            "shot_index": shot_gene.get("index"),
            "function": shot_gene.get("function", ""),
            "visual_requirement": shot_gene.get("visual_requirement", ""),
            "importance": shot_gene.get("importance", "medium"),
            "effect_types": [
                event.get("type") for event in shot_gene.get("effect_events", [])
                if isinstance(event, dict) and event.get("type")
            ],
        })

    pass_diversity = (
        available_shortfall == 0
        and len(used_ids) == shot_count
        and unique_used == shot_count
        and not overused
        and longest_run <= 1
    )
    render_hints = dict(scheme_dict.get("render_hints") or {})
    render_hints["material_diversity"] = {
        "shot_count": shot_count,
        "available": len(available_ids),
        "assigned_shot_count": len(used_ids),
        "unique_used": unique_used,
        "recommended_unique": recommended_unique,
        "available_shortfall": available_shortfall,
        "reuse_counts": counts,
        "overused": overused,
        "longest_consecutive_run": longest_run,
        "pass": pass_diversity,
    }
    render_hints["material_requirements"] = requirements
    if not pass_diversity:
        render_hints["material_shortfall"] = {
            "additional_unique_segments_needed": max(
                available_shortfall,
                recommended_unique - unique_used,
            ),
            "reason": "every shot requires a unique source material; reuse is forbidden",
        }
    scheme_dict["render_hints"] = render_hints
    return scheme_dict


def require_unique_material_capacity(inventory: dict, required_shots: int) -> int:
    """Reject a run before planning when one unique source per shot is impossible."""
    items = (inventory or {}).get("items", (inventory or {}).get("materials", []))
    available_ids = {
        str(item.get("id")) for item in items
        if isinstance(item, dict) and item.get("id")
    }
    required_shots = max(0, int(required_shots or 0))
    if required_shots and len(available_ids) < required_shots:
        missing = required_shots - len(available_ids)
        raise ValueError(
            f"素材禁止重复使用：{required_shots} 个分镜至少需要 {required_shots} 条不同素材，"
            f"当前只有 {len(available_ids)} 条，还缺 {missing} 条"
        )
    return len(available_ids)


def build_local_fallback_scheme(
    *,
    target_topic: str,
    target_duration: float,
    inventory: dict,
    gene: dict,
) -> dict:
    """Build a complete storyboard when the text model returns truncated JSON.

    The fallback intentionally follows the reference timing/effect contract and
    assigns every analyzed material at most once.
    """
    items = inventory.get("items") or inventory.get("materials") or []
    items = [item for item in items if isinstance(item, dict) and item.get("id")]
    cut_points = [
        float(value)
        for value in gene.get("reference_cut_points", [])
        if isinstance(value, (int, float)) and float(value) > 0
    ]
    reference_duration = float(gene.get("duration", 0) or target_duration or 1)
    scale = target_duration / reference_duration if reference_duration > 0 else 1.0
    boundaries = [0.0, *[value * scale for value in cut_points], target_duration]
    shot_count = max(1, len(boundaries) - 1)
    if len(items) < shot_count:
        raise ValueError(
            f"素材禁止重复使用：{shot_count} 个分镜至少需要 {shot_count} 条不同素材，"
            f"当前只有 {len(items)} 条，还缺 {shot_count - len(items)} 条"
        )
    shot_genes = gene.get("shot_genes", []) or []

    function_to_type = {
        "hook": "hook",
        "establishing": "scene_establish",
        "daily_moment": "daily_moment",
        "climax": "emotion_peak",
        "persona": "persona_expression",
        "info_card": "info_card",
        "closing": "closing_moment",
    }
    packaging_signature = gene.get("packaging_signature", {}) or {}
    packaging_text = " ".join(
        str(packaging_signature.get(key) or "")
        for key in ("stickers_effects", "color_grade_detail")
    )
    usage_counts = {str(item.get("id")): 0 for item in items}
    semantic_groups = (
        (("苹果", "水果", "果实", "车厘子", "制作", "果汁"), ("苹果", "水果", "果实", "草莓", "切", "水珠", "冲洗")),
        (("果汁", "饮品", "瓶", "倒", "购物"), ("果汁", "饮品", "液体", "瓶", "玻璃杯", "冰块")),
        (("骑", "自行车", "出行", "街景", "街头"), ("骑", "自行车", "道路", "城市", "街")),
        (("车", "跑车", "踏板", "车尾"), ("跑车", "车身", "车库", "轮毂", "尾灯")),
        (("气球", "乐园", "角色", "人偶", "童趣"), ("气球", "人物", "红色", "霓虹")),
        (("暗", "黑", "神秘", "游乐", "高潮"), ("夜间", "光轨", "灯", "旋转", "深色")),
    )

    def choose_material(shot_gene: dict) -> dict:
        if not items:
            return {}
        intent = " ".join(
            str(shot_gene.get(key) or "")
            for key in ("semantic_role", "visual_requirement", "emotion_role", "function")
        )
        scored = []
        unused_items = [
            item for item in items
            if usage_counts.get(str(item.get("id")), 0) == 0
        ]
        for order, item in enumerate(unused_items):
            description = " ".join(
                str(item.get(key) or "")
                for key in ("description", "scene_type", "semantic_summary", "semantic_tags")
            )
            score = 0.0
            for intent_terms, material_terms in semantic_groups:
                if any(term in intent for term in intent_terms):
                    score += 3.0 * sum(term in description for term in material_terms)
            if shot_gene.get("function") == "hook" and any(term in description for term in ("特写", "红苹果", "水珠")):
                score += 4.0
            if shot_gene.get("function") == "climax" and any(term in description for term in ("光轨", "红色", "果汁")):
                score += 3.0
            score -= order * 0.001
            scored.append((score, item))
        selected = max(scored, key=lambda pair: pair[0])[1]
        selected_id = str(selected.get("id"))
        usage_counts[selected_id] = usage_counts.get(selected_id, 0) + 1
        return selected

    storyboard = []
    effect_tracks: list[dict] = []
    cursor = 0.0
    for index in range(shot_count):
        gene_index = min(
            len(shot_genes) - 1,
            int(index * len(shot_genes) / shot_count),
        ) if shot_genes else -1
        shot_gene = shot_genes[gene_index] if gene_index >= 0 else {}
        material = choose_material(shot_gene)
        function = str(shot_gene.get("function") or ("hook" if index == 0 else "daily_moment"))
        if index == shot_count - 1:
            function = "closing"
        duration = round(max(0.1, boundaries[index + 1] - boundaries[index]), 3)
        frame = {
            "index": index,
            "duration": duration,
            "shot_type": function_to_type.get(function, "daily_moment"),
            "purpose": shot_gene.get("semantic_role") or function,
            "structure_function": function,
            "gene_shot_index": gene_index,
            "source_material_id": material.get("id", ""),
            "visual_description": material.get("description") or material.get("semantic_summary") or function,
            "transition_in": "cut",
            "render_component": "auto",
            "custom_render_config": {},
            "motion_effect": "reference_timing_fallback",
            "adaptation": {
                "preserved": True,
                "reason": "Text planner output was truncated; preserved reference timing locally",
                "original_function": function,
            },
        }

        semantic_role = str(shot_gene.get("semantic_role") or "")
        if index == 0:
            frame["render_component"] = "custom:hero_push_in"
            frame["custom_render_config"] = {
                "accent_color": "#E60012",
                "intensity": 0.92,
                "zoom_from": 1.0,
                "zoom_to": 1.24,
            }
            frame["motion_effect"] = "fast_push_in"
        elif index == 9 and any(term in packaging_text for term in ("重影", "叠影")):
            frame["render_component"] = "custom:echo_stack"
            frame["custom_render_config"] = {"accent_color": "#E60012", "echo_count": 3}
            frame["motion_effect"] = "layered_echo"
        elif index == 10 and any(term in packaging_text for term in ("怒气", "爆炸")):
            frame["render_component"] = "custom:doodle_pop"
            frame["custom_render_config"] = {"accent_color": "#FFD400", "symbol": "!!"}
            frame["motion_effect"] = "comic_doodle_pop"
        elif index == 13 and any(term in packaging_text for term in ("撕纸", "描边")):
            frame["render_component"] = "custom:torn_paper_frame"
            frame["custom_render_config"] = {"accent_color": "#FFFFFF", "border_width": 18}
            frame["motion_effect"] = "torn_paper_outline"
        elif "全黑" in semantic_role or "暗场" in semantic_role:
            frame["transition_in"] = "flash_black"
            frame["motion_effect"] = "black_dip"
            effect_tracks.append({
                "start": round(cursor, 3),
                "end": round(min(target_duration, cursor + min(0.18, duration)), 3),
                "type": "black_dip",
                "component": "black_dip",
                "priority": "high",
                "parameters": {},
            })
        elif function == "climax":
            frame["render_component"] = "custom:grid_memory"
            frame["custom_render_config"] = {
                "accent_color": "#E60012",
                "source_material_ids": [item.get("id") for item in items[:4] if item.get("id")],
            }
            frame["motion_effect"] = "grid_freeze_memory"
        elif function == "transition" and index in {4, 6, 12, 16}:
            frame["transition_in"] = "whip" if index in {6, 16} else "zoom_flash"
            frame["motion_effect"] = "fast_motion_bridge"
        elif function == "establishing" and index >= max(1, shot_count - 7):
            frame["transition_in"] = "slice_wipe"
            frame["motion_effect"] = "location_reveal"
        elif function in {"closing", "info"} or index == shot_count - 1:
            frame["render_component"] = "custom:search_cta_card"
            frame["custom_render_config"] = {
                "query": "红苹果城市活力广告",
                "platform": "抖音",
            }
            frame["shot_type"] = "info_card"
            frame["motion_effect"] = "structured_search_cta"

        storyboard.append(frame)
        cursor += duration

    return {
        "title": target_topic or "参考结构迁移短片",
        "target_topic": target_topic,
        "target_duration": target_duration,
        "structure_type": gene.get("structure_type", ""),
        "narrative_type": gene.get("narrative_type", ""),
        "hook_strategy": gene.get("hook_strategy", ""),
        "overall_emotion": gene.get("overall_emotion", ""),
        "storyboard": storyboard,
        "packaging": packaging_signature,
        "effect_tracks": [*(gene.get("effect_tracks", []) or []), *effect_tracks],
        "gene_refs": [gene.get("source_id")] if gene.get("source_id") else [],
        "adaptation_log": [
            {
                "mode": "local_reference_contract_fallback",
                "reason": "text planner output truncated",
                "shot_count": shot_count,
            }
        ],
        "render_hints": {
            "planner_fallback": True,
            "preserve_effect_tracks": True,
            "editing_grammar": "高密度硬切为主，红色物体匹配切换，段落节点用甩镜、暗场和网格定格",
            "signature_techniques": ["red_color_match_cut", "doodle_pop", "torn_paper_outline", "grid_memory"],
        },
    }


def infer_source_aspect_ratio(struct: dict) -> str:
    """Return a stable small-integer aspect ratio from analyzed video metadata."""
    explicit = str(struct.get("aspect_ratio") or "").strip()
    if explicit:
        return explicit
    resolution = struct.get("resolution")
    if not isinstance(resolution, (list, tuple)) or len(resolution) != 2:
        return ""
    try:
        width, height = int(resolution[0]), int(resolution[1])
    except (TypeError, ValueError):
        return ""
    if width <= 0 or height <= 0:
        return ""
    ratio = Fraction(width, height).limit_denominator(20)
    return f"{ratio.numerator}:{ratio.denominator}"


def build_fallback_render_decisions(scheme_dict: dict) -> list[dict]:
    """Derive stable render choices from Planner intent when Renderer is unavailable."""
    decisions: list[dict] = []
    for frame in scheme_dict.get("storyboard", []):
        component = frame.get("render_component") or "auto"
        motion = str(frame.get("motion_effect") or "").lower()
        shot_type = str(frame.get("shot_type") or "")
        config = dict(frame.get("custom_render_config") or {})

        if component == "auto":
            if shot_type == "hook" and ("zoom" in motion or "推" in motion):
                component = "custom:hero_push_in"
                config.update({"intensity": 0.72, "push_direction": "in"})
            elif shot_type == "emotion_peak" or "zoom_flash" in motion:
                component = "custom:kinetic_warp"
                config.update({"intensity": 0.9, "shake": True})
            elif "film_grain" in motion or "胶片" in motion:
                component = "custom:cinematic_grain"
                config.update({"grain": 0.2})
            elif "模糊" in motion or "blur" in motion:
                component = "custom:focus_blur_resolve"
                config.update({"intensity": 0.55})

        decisions.append({
            "index": frame.get("index"),
            "render_component": component,
            "custom_render_config": config,
            "reasoning": "Renderer unavailable; derived from Planner motion intent",
        })
    return decisions


def build_preferences(topic: str, target_duration: float = 45.0) -> dict:
    subject = topic.strip() or "短视频"
    shot_count = "6-10个分镜" if target_duration <= 20 else "12-16个分镜"
    return {
        "style": f"贴合“{subject}”的创意短视频风格",
        "shot_count_target": shot_count,
        "total_duration_guide": f"严格控制为 {target_duration:g} 秒",
        "material_usage": "每个分镜必须使用不同的 source_material_id，同一素材在全片中禁止重复",
        "note": "根据参考视频的结构、节奏与情绪曲线安排运镜和转场。",
    }


def load_local_reference_profile(struct: dict) -> dict:
    """Load a checked-in local observation profile without calling a VLM."""
    if os.getenv("DISABLE_LOCAL_REFERENCE_PROFILE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        logger.info("Local reference profile disabled for this run")
        return {}
    source_path = str(struct.get("source_path") or struct.get("source_video") or "")
    profile_path = PROJECT_ROOT / "data/reference_profiles" / f"{Path(source_path).stem}.json"
    try:
        return json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


async def build_skill_context(
    struct: dict,
    struct_analysis: dict,
    *,
    llm=None,
    target_topic: str = "",
    inventory: dict | None = None,
    preferences: dict | None = None,
) -> tuple[str, dict, list]:
    """Build the same hybrid Skill plan used by the LangGraph path.

    The Web path receives a precomputed reference report instead of a
    ``StructureGene`` object.  Rebuild the compact Gene locally so web planning
    can keep deterministic Gene routing and add bounded semantic routing.
    """
    source_path = str(struct.get("source_path") or struct.get("source_video") or "")
    local_profile = load_local_reference_profile(struct)
    shot_analyses = struct.get("raw_shot_analyses", struct.get("shots", []))
    if not isinstance(shot_analyses, list):
        shot_analyses = []
    if not isinstance(struct_analysis, dict):
        struct_analysis = {}
    if local_profile.get("packaging_signature"):
        struct_analysis = dict(struct_analysis)
        struct_analysis["packaging_analysis"] = {
            **(struct_analysis.get("packaging_analysis", {}) or {}),
            **local_profile["packaging_signature"],
        }
        struct_analysis["effect_tracks"] = local_profile.get("effect_tracks", [])
    gene = build_gene(
        shot_analyses=shot_analyses,
        structure_analysis=struct_analysis,
        source_id=str(struct.get("source_fingerprint") or struct.get("source_video") or "reference"),
        source_path=source_path,
        duration=float(struct.get("duration", 0) or 0),
        effect_tracks=(
            local_profile.get("effect_tracks", [])
            or (struct.get("effect_tracks", []) if isinstance(struct.get("effect_tracks", []), list) else [])
        ),
        source_aspect_ratio=str(local_profile.get("source_aspect_ratio") or infer_source_aspect_ratio(struct)),
        reference_cut_points=local_profile.get("reference_cut_points"),
    )
    router = SkillRouter()
    raw_items = (inventory or {}).get("items", (inventory or {}).get("materials", []))
    compact_items = []
    for item in raw_items[:40] if isinstance(raw_items, list) else []:
        if not isinstance(item, dict):
            continue
        compact_items.append({
            key: item.get(key)
            for key in (
                "id", "type", "description", "scene_type", "shot_scale",
                "camera_motion", "motion_intensity", "emotion_tags",
                "semantic_tags", "suitable_functions", "quality_score",
            )
            if item.get(key) not in (None, "", [], {})
        })
    raw_preferences = preferences or {}
    compact_preferences = {
        key: raw_preferences.get(key)
        for key in (
            "style", "duration", "shot_count_target", "total_duration_guide",
            "material_usage", "narrative_type", "vlog_style_preference", "note",
        )
        if raw_preferences.get(key) not in (None, "", [], {})
    }
    gene_for_routing = dict(gene.to_dict())
    gene_for_routing.pop("source_path", None)
    routing_context = json.dumps({
        "target_topic": target_topic,
        "user_preferences": compact_preferences,
        "reference_gene": gene_for_routing,
        "material_summary": {
            "item_count": len(raw_items) if isinstance(raw_items, list) else 0,
            "items": compact_items,
        },
    }, ensure_ascii=False, default=str)[:12000]
    plan = (
        await router.route_hybrid([gene], routing_context, llm)
        if llm is not None
        else router.route_for_gene(gene)
    )
    skill_context = [reference.to_dict() for reference in router.collect(plan.references)]
    return json.dumps(gene.to_dict(), ensure_ascii=False), plan.to_dict(), skill_context


async def main():
    args = parse_args()

    run_id = args.run_id
    out = OutputManager(run_id=run_id)
    logger.info(f"输出目录: {out.run_dir}")
    run_logs: list[dict] = []
    errors: list[str] = []
    stage_started = time.perf_counter()
    previous_usage: dict = {}

    def record_stage(stage: str, **details) -> None:
        nonlocal stage_started, previous_usage
        now = time.perf_counter()
        entry = {"stage": stage, "duration_seconds": round(now - stage_started, 3), **details}
        stage_started = now
        if stage in {"planner", "renderer", "reviewer"}:
            current_usage = llm.usage_snapshot()
            entry["llm_usage"] = {
                key: (current_usage[key] - (previous_usage.get(key) or 0) if isinstance(current_usage.get(key), int) else None)
                for key in ("requests", "attempts", "responses", "mock_requests", "prompt_tokens", "completion_tokens", "total_tokens")
            }
            entry["llm_usage"]["model"] = current_usage["model"]
            previous_usage = current_usage
        run_logs.append(entry)
        out.append_log(stage, entry)

    # ===== 1. 加载现有视频结构分析 =====
    logger.info("=" * 60)
    logger.info("1. 加载视频结构分析")
    struct_path = Path(args.struct)
    struct = json.loads(struct_path.read_text(encoding="utf-8"))
    out.save_json("analyst", "reference_structure.json", struct)
    record_stage("analyst", reused=True, shot_count=len(struct.get("shots", [])))
    target_duration = infer_target_duration(args.topic, float(struct.get("duration", 0) or 0))
    logger.info(f"   视频: {struct.get('source_video', '?')}")
    logger.info(f"   时长: {struct.get('duration', 0):.1f}s, 镜头: {len(struct.get('shots', []))}")

    struct_analysis_path = Path(args.struct_analysis)
    struct_analysis = json.loads(struct_analysis_path.read_text(encoding="utf-8")) if struct_analysis_path.exists() else {}

    # ===== 2. 加载素材 =====
    logger.info("=" * 60)
    logger.info("2. 加载用户素材")
    if args.inventory:
        inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
        inventory.setdefault("items", inventory.get("materials", []))
    elif args.photo_dir:
        photo_dir = Path(args.photo_dir)
        photo_paths = sorted([
            p for p in photo_dir.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")
        ])
        inventory = {
            "items": [
                {"id": f"mat_{i:03d}", "path": str(p.resolve()), "type": "image", "description": p.stem[:40]}
                for i, p in enumerate(photo_paths)
            ]
        }
    else:
        raise ValueError("必须传入 --inventory 或 --photo-dir")
    inventory["materials"] = inventory["items"]
    reference_shot_count = int(struct.get("shot_count") or len(struct.get("shots", [])) or 0)
    require_unique_material_capacity(inventory, reference_shot_count)
    out.save_run_info(
        target_topic=args.topic,
        sample_videos=[],  # Web flow receives a precomputed structure artifact.
        user_materials_count=len(inventory["items"]),
        execution_mode="plan_render",
        expected_stages=["analyst", "material", "planner", "renderer", "assembler", "reviewer", "render_reviewer"],
    )
    out.save_json("material", "inventory.json", inventory)
    record_stage("material", item_count=len(inventory["items"]))
    logger.info(f"   共 {len(inventory['items'])} 张照片")

    # ===== 3. 按 Gene 注入 Editing Skill，生成方案 =====
    logger.info("=" * 60)
    logger.info("3. 编导生成方案 (DeepSeek + 按需 Editing Skill)")

    techniques = get_summary()
    logger.info(f"   可用剪辑手法摘要 {len(techniques)} 行")
    # 打印部分学识预览
    for line in techniques.split("\n")[:6]:
        logger.info(f"   {line}")

    llm = LLMTools(
        api_key=settings.TEXT_API_KEY,
        base_url=settings.TEXT_BASE_URL,
        model=settings.TEXT_MODEL_ID,
    )
    planner = PlannerAgent(llm)

    structure_summary = json.dumps(struct, ensure_ascii=False)
    structure_analysis_json = json.dumps(struct_analysis, ensure_ascii=False)

    skeleton = await planner._extract_skeleton(structure_summary, args.topic, "", structure_analysis=structure_analysis_json)
    out.save_json("planner", "skeleton.json", skeleton)
    logger.info(f"   骨架: {skeleton.get('structure_type', '?')}")

    inv_json = json.dumps(inventory, ensure_ascii=False)
    preferences_data = build_preferences(args.topic, target_duration)
    reference_profile = load_local_reference_profile(struct)
    profile_cut_points = reference_profile.get("reference_cut_points", [])
    if isinstance(profile_cut_points, list) and profile_cut_points:
        preferences_data["shot_count_target"] = f"{len(profile_cut_points) + 1}个分镜"
        preferences_data["reference_timing_mode"] = "严格按参考切点的相对位置迁移"
    if args.knowledge_context:
        context_path = Path(args.knowledge_context)
        if context_path.exists():
            try:
                personal_entries = json.loads(context_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("个人知识上下文读取失败: %s", exc)
                personal_entries = []
            if personal_entries:
                # 控制 prompt 体积；优先采用最近写入文件尾部的个人知识。
                preferences_data["personal_knowledge"] = [
                    {
                        "id": entry.get("id", ""),
                        "type": entry.get("type", ""),
                        "title": entry.get("title", ""),
                        "content": entry.get("content", ""),
                        "tags": entry.get("tags", []),
                        "best_when": entry.get("best_when", ""),
                    }
                    for entry in personal_entries[-20:]
                ]
                logger.info("   注入当前用户个人知识 %d 条", len(preferences_data["personal_knowledge"]))
    gene_json, skill_plan, skill_context = await build_skill_context(
        struct,
        struct_analysis,
        llm=llm,
        target_topic=args.topic,
        inventory=inventory,
        preferences=preferences_data,
    )
    out.save_json("planner", "skill_routing.json", skill_plan)
    logger.info(
        "   Skill 路由模式: %s；按需加载: %s",
        skill_plan.get("routing_mode", "deterministic"),
        skill_plan.get("references") or "无",
    )
    if skill_plan.get("semantic_routing_error"):
        logger.warning(
            "   Skill 语义路由失败，已降级为确定性结果: %s",
            skill_plan["semantic_routing_error"],
        )
    preferences = json.dumps(preferences_data, ensure_ascii=False)

    # manually inject techniques into the generate call
    try:
        scheme_data = await planner._generate_scheme(
            json.dumps(skeleton, ensure_ascii=False), inv_json,
            args.topic, "", preferences,
            material_type_hint=build_material_type_hint(inventory),
            gene_json=gene_json,
            skill_context=skill_context,
        )
    except (RuntimeError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Planner 输出不可用，按本地参考特效契约生成草案: %s", exc)
        try:
            fallback_gene = json.loads(gene_json) if gene_json else {}
        except (TypeError, json.JSONDecodeError):
            fallback_gene = {}
        scheme_data = build_local_fallback_scheme(
            target_topic=args.topic,
            target_duration=target_duration,
            inventory=inventory,
            gene=fallback_gene,
        )
    normalize_storyboard_duration(scheme_data, target_duration)
    try:
        gene_contract = json.loads(gene_json) if gene_json else {}
    except (TypeError, json.JSONDecodeError):
        gene_contract = {}
    apply_reference_effect_contract(scheme_data, gene_contract)
    apply_audio_contract(scheme_data, gene_contract)
    apply_material_diversity_contract(scheme_data, inventory, gene_contract)
    diversity = (scheme_data.get("render_hints") or {}).get("material_diversity") or {}
    if not diversity.get("pass", False):
        missing = max(
            int(diversity.get("available_shortfall", 0) or 0),
            int(diversity.get("shot_count", 0) or 0) - int(diversity.get("unique_used", 0) or 0),
        )
        raise ValueError(
            "素材禁止重复使用：Planner 方案包含重复或缺失的 source_material_id；"
            f"需要补充或重新匹配 {max(0, missing)} 条素材"
        )
    out.save_json("planner", "scheme_raw.json", scheme_data)

    scheme = planner.build_scheme(scheme_data, args.topic, iteration=0)
    # Router selection is not usage evidence. Preserve selected/loaded/
    # declared/verified separately before a user can edit the storyboard.
    initialise_skill_trace(scheme, skill_plan)
    skill_trace = verify_skill_usage(scheme, skill_plan, inventory)
    out.save_json("evaluation", "skill_evaluation.json", skill_trace)
    out.save_json("planner", "scheme.json", scheme)
    out.save_json("planner", "scheme_v0.json", scheme)
    record_stage("planner", frame_count=len(scheme.storyboard))
    logger.info(f"   方案: {scheme.title}, {len(scheme.storyboard)} 个分镜, {scheme.target_duration}s")

    for f in scheme.storyboard:
        logger.info(f"   [{f.index}] {f.shot_type.value:20s} | {f.duration:.1f}s | {f.visual_content[:50] if f.visual_content else ''}")

    # ===== 4. 渲染决策 =====
    logger.info("=" * 60)
    logger.info("4. 渲染决策")

    from agents.renderer import RendererAgent
    renderer = RendererAgent(llm)

    scheme_json = json.dumps(scheme.to_dict() if hasattr(scheme, "to_dict") else scheme_data, ensure_ascii=False)
    try:
        decisions = await renderer._analyze_scheme(scheme_json, f"{len(inventory['items'])} 个素材")
    except (TimeoutError, RuntimeError, ValueError) as exc:
        logger.warning("Renderer 决策不可用，按 Planner 逐镜意图降级: %s", exc)
        decisions = {
            "frame_decisions": build_fallback_render_decisions(scheme.to_dict()),
            "fallback": True,
            "reason": str(exc),
        }
    out.save_json("renderer", "render_decisions.json", decisions)
    record_stage("renderer", decision_count=len(decisions.get("frame_decisions", [])))

    frame_decisions = decisions.get("frame_decisions", [])
    for d in frame_decisions:
        logger.info(f"   [{d.get('index', '?')}] render: {d.get('render_component', 'auto')[:20]} | {d.get('reasoning', '')[:60]}")

    # ===== 5. Remotion 渲染 =====
    logger.info("=" * 60)
    logger.info("5. Remotion 渲染最终视频")

    scheme_dict = scheme.to_dict() if hasattr(scheme, "to_dict") else scheme_data
    # 将决策写回 scheme
    apply_render_decisions(scheme_dict, frame_decisions)
    out.save_json("planner", "scheme_final.json", scheme_dict)

    if args.scheme_output:
        scheme_output = Path(args.scheme_output).resolve()
        scheme_output.parent.mkdir(parents=True, exist_ok=True)
        scheme_output.write_text(
            json.dumps(scheme_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if args.prepare_only:
        out.save_pipeline_summary({
            "status": "awaiting_confirmation",
            "target_topic": args.topic,
            "phase": "planning",
            "iteration": 0,
            "is_complete": False,
            "scheme": scheme,
            "rendered_video_path": "",
            "review_result": {},
            "errors": errors,
            "logs": run_logs,
        })
        from evaluation.run_evaluator import evaluate_run
        out.save_json("evaluation", "report.json", evaluate_run(out.run_dir))
        logger.info("分镜草案已生成，等待用户确认")
        return

    from tools.remotion_renderer import render_with_remotion
    from run_storyboard_render import extract_reference_audio, normalize_output_audio

    output_path = Path(args.output).resolve() if args.output else (out.run_dir / "final_video.mp4").resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output = str(output_path)
    render_materials = list(inventory["items"])
    bgm = dict(scheme_dict.get("bgm") or {})
    audio_config = dict(scheme_dict.get("audio_config") or {})
    if bgm.get("audio_path") == "_viral_audio":
        reference_video = str(struct.get("source_path") or struct.get("source_video") or "")
        if not reference_video or not Path(reference_video).is_file():
            raise RuntimeError("方案要求使用参考视频音轨，但结构文件中的参考视频不存在")
        audio_path = extract_reference_audio(reference_video, output_path.parent)
        render_materials.append({"id": "_viral_audio", "path": audio_path})

    result_path = render_with_remotion(scheme_dict, render_materials, output, timeout=600)
    if result_path:
        normalize_output_audio(Path(result_path), audio_config)

    render_review: dict = {}
    if result_path:
        size_mb = Path(result_path).stat().st_size / 1024 / 1024
        logger.info(f"   [OK] 渲染完成: {result_path}")
        logger.info(f"   [OK] 大小: {size_mb:.1f}MB")
        record_stage("assembler", success=True, output_path=str(result_path))
    else:
        logger.error("   Remotion 渲染失败")
        errors.append("Remotion 渲染失败")
        record_stage("assembler", success=False)

    # ===== 6. 方案质量评审与运行评测 =====
    logger.info("6. Reviewer 方案质量评审")
    review: dict = {}
    try:
        material_list = [
            f"[{item.get('id', '')}] ({item.get('type', '')}) {item.get('description', '')[:60]}"
            for item in inventory["items"]
        ]
        used_ids = {
            str(frame.get("material_id") or frame.get("source_material_id"))
            for frame in scheme_dict.get("storyboard", [])
            if frame.get("material_id") or frame.get("source_material_id")
        }
        coverage = (
            f"分镜: {len(scheme_dict.get('storyboard', []))}\n"
            f"素材总数: {len(inventory['items'])}\n"
            f"已使用素材数: {len(used_ids)}"
        )
        transition_summary = "\n".join(
            f"分镜{frame.get('index', 0)}: {frame.get('transition_in', frame.get('transition', 'cut'))}"
            for frame in scheme_dict.get("storyboard", [])
        )
        reviewer = ReviewerAgent(llm)
        review = await reviewer._review_scheme(
            json.dumps(struct, ensure_ascii=False),
            json.dumps(scheme_dict, ensure_ascii=False),
            coverage,
            material_list_desc="\n".join(material_list),
            transition_summary=transition_summary,
        )
        review = reviewer.apply_contract_gates(review, scheme_dict)
        from evaluation.run_evaluator import scheme_fingerprint
        review["scheme_fingerprint"] = scheme_fingerprint(scheme_dict)
        attach_skill_outcomes(skill_trace, reviewer=review)
        scheme.skill_evaluation = skill_trace
        out.save_json("evaluation", "skill_evaluation.json", skill_trace)
        out.save_json("planner", "scheme_final.json", scheme)
        out.save_json("reviewer", "review_result.json", review)
        record_stage(
            "reviewer",
            score=review.get("total_score"),
            passed=bool(review.get("pass")),
        )
    except Exception as exc:
        logger.warning("Reviewer 评审失败: %s", exc)
        errors.append(f"Reviewer 评审失败: {exc}")
        record_stage("reviewer", success=False, error=str(exc))

    # ===== 7. 成片证据评测 =====
    # Keep it separate from the storyboard Reviewer: this stage inspects the
    # actual MP4 and only treats visual-model findings as diagnostics until
    # their thresholds have been calibrated with human-labelled videos.
    if result_path:
        render_review_started = time.perf_counter()
        try:
            from evaluation.run_evaluator import scheme_fingerprint
            from evaluation.video_review import review_rendered_video

            render_review, render_usage = await review_rendered_video(
                result_path, scheme_dict, struct, out.stage_dir("render_reviewer"),
            )
            render_review["scheme_fingerprint"] = scheme_fingerprint(scheme_dict)
            out.save_json("render_reviewer", "render_review.json", render_review)
            render_log = {
                "stage": "render_reviewer",
                "success": True,
                "review_status": render_review.get("status"),
                "score": (render_review.get("visual_review") or {}).get("total_score"),
                "duration_seconds": round(time.perf_counter() - render_review_started, 3),
                "llm_usage": render_usage,
            }
            run_logs.append(render_log)
            out.append_log("render_reviewer", render_log)
        except Exception as exc:
            logger.warning("成片评测失败: %s", exc)
            render_review = {"status": "failed", "reason": str(exc)}
            render_log = {
                "stage": "render_reviewer",
                "success": True,
                "review_status": "failed",
                "error": str(exc),
                "duration_seconds": round(time.perf_counter() - render_review_started, 3),
            }
            run_logs.append(render_log)
            out.save_json("render_reviewer", "render_review.json", {"status": "failed", "reason": str(exc)})
            out.append_log("render_reviewer", render_log)

    final_state = {
        "status": "completed" if result_path else "failed",
        "target_topic": args.topic,
        "phase": "complete",
        "iteration": 0,
        "is_complete": bool(result_path),
        "scheme": scheme,
        "rendered_video_path": str(result_path or ""),
        "review_result": review,
        "errors": errors,
        "logs": run_logs,
    }
    out.save_pipeline_summary(final_state)
    try:
        from evaluation.run_evaluator import evaluate_run
        evaluation = evaluate_run(out.run_dir)
        out.save_json("evaluation", "report.json", evaluation)
        attach_skill_outcomes(
            skill_trace,
            reviewer=review,
            render_review=render_review,
            run_evaluation=evaluation,
        )
        scheme.skill_evaluation = skill_trace
        out.save_json("planner", "scheme_final.json", scheme)
        out.save_json("evaluation", "skill_evaluation.json", skill_trace)
        logger.info("   评测得分: %.2f | success=%s", evaluation["score"], evaluation["success"])
    except Exception as exc:
        logger.warning("运行评测报告生成失败: %s", exc)

    logger.info("=" * 60)
    logger.info("端到端流程完成")


if __name__ == "__main__":
    asyncio.run(main())
