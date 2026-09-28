"""Skill trace and scheme-level compliance verification.

The verifier intentionally checks only observable contract compliance.  It
does not claim that a Skill caused a better video; that requires controlled
experiments and human/outcome data.  Its job is to distinguish:

selected -> loaded -> declared -> verified
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


TRACE_VERSION = "1.0"


def _dedupe(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        return converted if isinstance(converted, dict) else {}
    return {}


def _frames(scheme: Any) -> list[dict[str, Any]]:
    data = _as_dict(scheme)
    frames = data.get("storyboard", [])
    return [frame for frame in frames if isinstance(frame, dict)] if isinstance(frames, list) else []


def _skill_refs_from_scheme(scheme: Any) -> list[str]:
    data = _as_dict(scheme)
    declared = data.get("declared_skill_refs") or data.get("skill_refs_used") or []
    refs: list[Any] = list(declared) if isinstance(declared, list) else []
    for frame in _frames(data):
        frame_refs = frame.get("skill_refs", [])
        if isinstance(frame_refs, list):
            refs.extend(frame_refs)
    return _dedupe(refs)


def _route_decision_dicts(route_plan: Any) -> list[dict[str, Any]]:
    if route_plan is None:
        return []
    if hasattr(route_plan, "to_dict"):
        route_plan = route_plan.to_dict()
    if not isinstance(route_plan, dict):
        return []
    decisions = route_plan.get("decisions", [])
    return [dict(item) for item in decisions if isinstance(item, dict)]


def initialise_skill_trace(scheme: Any, route_plan: Any = None) -> dict[str, Any]:
    """Attach selected/loaded/declared fields without inventing usage.

    Router selection means a reference was relevant and loaded into the
    Planner context.  It must never be rewritten as "declared" or "verified"
    merely because the Planner omitted its own `skill_refs` output.
    """
    decisions = _route_decision_dicts(route_plan)
    selected = _dedupe(item.get("skill_id") for item in decisions if item.get("selected", True))
    if not selected and isinstance(route_plan, dict):
        selected = _dedupe(route_plan.get("references", []))
    declared = _skill_refs_from_scheme(scheme)

    # VideoScheme is a dataclass in normal runtime; keep dict support for
    # confirmed Web storyboards and unit tests.
    target = scheme if not isinstance(scheme, dict) else None
    if target is not None:
        target.selected_skill_refs = selected
        target.loaded_skill_refs = list(selected)
        target.declared_skill_refs = declared
        # Backward-compatible field: it now means model-declared use, not
        # "anything selected by the router".
        target.skill_refs_used = list(declared)
        target.verified_skill_refs = []
    else:
        scheme["selected_skill_refs"] = selected
        scheme["loaded_skill_refs"] = list(selected)
        scheme["declared_skill_refs"] = declared
        scheme["skill_refs_used"] = list(declared)
        scheme["verified_skill_refs"] = []

    return {
        "schema_version": TRACE_VERSION,
        "route_decisions": decisions,
        "selected_skill_refs": selected,
        "loaded_skill_refs": list(selected),
        "declared_skill_refs": declared,
        "verified_skill_refs": [],
        "verification": [],
        "outcomes": {},
        "effect_interpretation": "trace_only_not_causal",
    }


def _check(name: str, passed: bool | None, detail: str) -> dict[str, Any]:
    status = "passed" if passed is True else "failed" if passed is False else "not_applicable"
    return {"name": name, "status": status, "passed": passed, "detail": detail}


def _function(frame: dict[str, Any]) -> str:
    return str(frame.get("structure_function") or frame.get("shot_type") or "").strip().lower()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rule_checks(skill_id: str, frames: list[dict[str, Any]], inventory: dict[str, Any] | None) -> list[dict[str, Any]]:
    functions = [_function(frame) for frame in frames]
    durations = [_safe_float(frame.get("duration"), 0.0) for frame in frames]
    first = frames[0] if frames else {}

    if skill_id == "hook":
        hook_indexes = [index for index, function in enumerate(functions) if function == "hook"]
        hook_in_opening = bool(hook_indexes and sum(durations[:hook_indexes[0]]) < 3.0)
        first_three_frames = 0
        elapsed = 0.0
        for duration in durations:
            if elapsed >= 3.0:
                break
            first_three_frames += 1
            elapsed += duration
        visual_or_caption = bool(
            first.get("material_id") or first.get("source_material_id")
            or first.get("visual_description") or first.get("visual_content")
            or first.get("subtitle_text") or first.get("text_card_content")
        )
        return [
            _check("hook_first_shot", hook_in_opening, "存在位于前 3 秒的 hook 镜头"),
            _check(
                "hook_fast_opening",
                bool(_safe_float(first.get("duration")) <= 2.5 or first_three_frames >= 2),
                "首镜不超过 2.5 秒，或前 3 秒至少有两个镜头",
            ),
            _check("hook_has_visual_or_caption", visual_or_caption, "首镜具备素材、视觉描述或字幕信息"),
        ]

    if skill_id == "rhythm":
        nonzero = [round(duration, 2) for duration in durations if duration > 0]
        has_variation = len(set(nonzero)) >= 2 if len(nonzero) >= 2 else None
        has_climax = any(function == "climax" for function in functions)
        return [
            _check("rhythm_has_variation", has_variation, "至少存在两种镜头时长，避免机械等长"),
            _check("rhythm_climax_present", has_climax if "climax" in functions else None, "若 Gene 需要高潮，方案中保留 climax 镜头"),
        ]

    if skill_id == "emotion":
        labeled = [frame for frame in frames if str(frame.get("emotion", "")).strip()]
        climax_frames = [frame for frame in frames if _function(frame) == "climax"]
        climax_labeled = all(str(frame.get("emotion", "")).strip() for frame in climax_frames) if climax_frames else None
        return [
            _check("emotion_labels_present", bool(labeled) if frames else False, "方案中至少存在情绪标记"),
            _check("emotion_climax_present", climax_labeled, "若存在高潮镜头，则高潮镜头有情绪标记"),
        ]

    if skill_id == "transition":
        transitions = [str(frame.get("transition_in") or frame.get("transition") or "cut") for frame in frames]
        valid = all(bool(value.strip()) for value in transitions) if transitions else False
        varied = len(set(transitions)) >= 2 if len(transitions) >= 3 else None
        return [
            _check("transition_values_valid", valid, "每个镜头具备非空转场值"),
            _check("transition_not_all_identical", varied, "三个及以上镜头时转场不应全部相同"),
        ]

    if skill_id == "subtitle":
        info_frames = [frame for frame in frames if _function(frame) == "info"]
        text_for_info = all(
            str(frame.get("subtitle_text") or frame.get("text_card_content") or "").strip()
            for frame in info_frames
        ) if info_frames else None
        all_texts = [str(frame.get("subtitle_text", "")).strip() for frame in frames if frame.get("subtitle_text")]
        lengths_valid = all(1 <= len(text) <= 80 for text in all_texts) if all_texts else None
        return [
            _check("info_has_text", text_for_info, "信息镜头具备字幕或文字卡"),
            _check("subtitle_text_length_valid", lengths_valid, "字幕长度位于 1 到 80 字符之间"),
        ]

    if skill_id == "material-matching":
        items = [] if not isinstance(inventory, dict) else inventory.get("items", inventory.get("materials", []))
        known_ids = {str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")}
        referenced_ids = {
            str(frame.get("material_id") or frame.get("source_material_id"))
            for frame in frames
            if frame.get("material_id") or frame.get("source_material_id")
        }
        references_valid = referenced_ids.issubset(known_ids) if known_ids else None
        gap_frames = [
            frame for frame in frames
            if frame.get("gap_filled") or frame.get("is_generated") or frame.get("fill_strategy") or frame.get("gap_fill_strategy")
        ]
        adaptations_explained = all(
            isinstance(frame.get("adaptation"), dict) and bool(frame.get("adaptation", {}).get("reason"))
            for frame in gap_frames
        ) if gap_frames else None
        return [
            _check("referenced_material_exists", references_valid, "所有引用的素材 ID 均存在于当前库存"),
            _check("functional_adaptation_when_needed", adaptations_explained, "存在补全/替代时记录适配原因"),
        ]

    if skill_id == "structure-adaptation":
        adapted = [frame for frame in frames if isinstance(frame.get("adaptation"), dict) and frame.get("adaptation")]
        explained = all(
            bool(frame["adaptation"].get("preserved")) and bool(frame["adaptation"].get("reason"))
            for frame in adapted
        ) if adapted else None
        return [
            _check("adaptation_trace", explained, "发生结构适配时记录 preserved 与 reason"),
        ]

    return []


def verify_skill_usage(scheme: Any, route_plan: Any = None, inventory: Any = None) -> dict[str, Any]:
    """Verify observable scheme compliance for selected and declared Skills."""
    trace = initialise_skill_trace(scheme, route_plan)
    frames = _frames(scheme)
    inventory_dict = _as_dict(inventory) if inventory is not None else None
    declared = set(trace["declared_skill_refs"])
    verification: list[dict[str, Any]] = []
    verified: list[str] = []

    for decision in trace["route_decisions"]:
        skill_id = decision.get("skill_id", "")
        if not skill_id:
            continue
        if skill_id not in declared:
            verification.append({
                "skill_id": skill_id,
                "skill_version": decision.get("skill_version", "unregistered"),
                "status": "not_declared",
                "compliance_score": None,
                "checks": [],
                "detail": "Skill 被 Router 选中并加载，但 Planner 未在方案中声明使用。",
            })
            continue
        checks = _rule_checks(skill_id, frames, inventory_dict)
        applicable = [item for item in checks if item["passed"] is not None]
        passed_count = sum(1 for item in applicable if item["passed"] is True)
        score = round(passed_count / len(applicable), 3) if applicable else None
        if score is None:
            status = "not_applicable"
        elif score == 1.0:
            status = "verified"
        elif score > 0.0:
            status = "partially_verified"
        else:
            status = "violated"
        if status == "verified":
            verified.append(skill_id)
        verification.append({
            "skill_id": skill_id,
            "skill_version": decision.get("skill_version", "unregistered"),
            "status": status,
            "compliance_score": score,
            "checks": checks,
            "detail": "仅验证方案中可观察的规则遵循，不代表该 Skill 因果性提升了结果。",
        })

    trace["verification"] = verification
    trace["verified_skill_refs"] = verified
    if isinstance(scheme, dict):
        scheme["verified_skill_refs"] = verified
        scheme["skill_evaluation"] = trace
    else:
        scheme.verified_skill_refs = verified
        scheme.skill_evaluation = trace
    return trace


def attach_skill_outcomes(
    trace: dict[str, Any],
    *,
    reviewer: dict[str, Any] | None = None,
    render_review: dict[str, Any] | None = None,
    run_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach observable outcomes while explicitly avoiding causal claims."""
    reviewer = reviewer if isinstance(reviewer, dict) else {}
    render_review = render_review if isinstance(render_review, dict) else {}
    run_evaluation = run_evaluation if isinstance(run_evaluation, dict) else {}
    visual = render_review.get("visual_review") if isinstance(render_review.get("visual_review"), dict) else {}
    trace["outcomes"] = {
        "reviewer": {
            "passed": reviewer.get("pass"),
            "total_score": reviewer.get("total_score"),
            "scores": reviewer.get("scores", {}),
            "fidelity": reviewer.get("fidelity", {}),
            "quality": reviewer.get("quality", {}),
        },
        "render_review": {
            "status": render_review.get("status"),
            "visual_score": visual.get("total_score"),
            "technical": render_review.get("technical", {}),
        },
        "run_evaluation": {
            "success": run_evaluation.get("success"),
            "score": run_evaluation.get("score"),
        },
    }
    trace["effect_interpretation"] = (
        "observational_trace_only: outcomes are correlated with selected Skills; "
        "use controlled A/B or ablation runs before claiming causal improvement"
    )
    return trace
