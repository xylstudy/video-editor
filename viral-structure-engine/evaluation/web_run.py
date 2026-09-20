"""Finish the Web task's evaluation after the confirmed storyboard is rendered."""

from __future__ import annotations

import json
import time
from pathlib import Path

from config.output_manager import OutputManager
from evaluation.run_evaluator import evaluate_run, scheme_fingerprint


async def finalize_web_run(
    run_id: str,
    scheme_path: str | Path,
    inventory_path: str | Path,
    video_path: str | Path | None,
    reference_structure_path: str | Path | None = None,
    render_error: str | None = None,
    render_duration_seconds: float | None = None,
    model_config: dict[str, str] | None = None,
) -> dict:
    """Persist the *confirmed* scheme, reviewer result and final evaluation.

    Rendering remains useful when the LLM reviewer is unavailable: its failure
    is recorded in the report, while the caller can still return the video.
    """
    out = OutputManager(run_id=run_id)
    errors = [render_error] if render_error else []
    scheme: dict = {}
    inventory: dict = {}
    try:
        scheme = json.loads(Path(scheme_path).read_text(encoding="utf-8"))
        if not isinstance(scheme, dict):
            raise ValueError("confirmed scheme is not a JSON object")
        out.save_json("planner", "scheme_final.json", scheme)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"确认分镜读取失败: {exc}")

    try:
        loaded = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
        inventory = {"items": loaded} if isinstance(loaded, list) else loaded
        if not isinstance(inventory, dict):
            raise ValueError("inventory is not a JSON object or list")
        out.save_json("material", "inventory.json", inventory)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"素材清单读取失败: {exc}")

    rendered = bool(video_path and not render_error)
    out.append_log("assembler", {
        "success": rendered,
        "path": str(video_path or ""),
        "error": render_error or "",
        "duration_seconds": render_duration_seconds,
    })

    review: dict = {}
    render_review: dict = {}
    if rendered and scheme and inventory:
        review_started = time.perf_counter()
        llm = None
        try:
            from agents.reviewer import ReviewerAgent
            from config import settings
            from config.llm_client import LLMTools

            if not reference_structure_path or not Path(reference_structure_path).is_file():
                raise FileNotFoundError("参考视频结构分析结果不存在")
            structure = json.loads(Path(reference_structure_path).read_text(encoding="utf-8"))
            items = inventory.get("items", inventory.get("materials", []))
            storyboard = scheme.get("storyboard", [])
            used_ids = {
                frame.get("material_id") or frame.get("source_material_id")
                for frame in storyboard if isinstance(frame, dict)
            }
            coverage = (
                f"分镜: {len(storyboard)}\n素材总数: {len(items)}\n"
                f"已使用素材数: {len(used_ids - {None, ''})}"
            )
            material_list = "\n".join(
                f"[{item.get('id', '')}] ({item.get('type', '')}) {str(item.get('description', ''))[:60]}"
                for item in items if isinstance(item, dict)
            )
            transitions = "\n".join(
                f"分镜{frame.get('index', index)}: {frame.get('transition_in') or frame.get('transition', 'cut')}"
                for index, frame in enumerate(storyboard) if isinstance(frame, dict)
            )
            llm = LLMTools(
                api_key=(model_config or {}).get("TEXT_API_KEY", settings.TEXT_API_KEY),
                base_url=(model_config or {}).get("TEXT_BASE_URL", settings.TEXT_BASE_URL),
                model=(model_config or {}).get("TEXT_MODEL_ID", settings.TEXT_MODEL_ID),
            )
            review = await ReviewerAgent(llm)._review_scheme(
                json.dumps(structure, ensure_ascii=False),
                json.dumps(scheme, ensure_ascii=False),
                coverage,
                material_list_desc=material_list,
                transition_summary=transitions,
            )
            if llm.usage_snapshot()["mock_requests"]:
                raise RuntimeError("Reviewer 使用了模型未配置时的 mock 响应")
            if not isinstance(review, dict):
                raise ValueError("reviewer returned a non-object result")
            review["scheme_fingerprint"] = scheme_fingerprint(scheme)
            out.save_json("reviewer", "review_result.json", review)
            out.append_log("reviewer", {
                "success": True,
                "passed": review.get("pass") is True,
                "score": review.get("total_score"),
                "duration_seconds": round(time.perf_counter() - review_started, 3),
                "llm_usage": llm.usage_snapshot(),
            })
        except Exception as exc:
            errors.append(f"Reviewer 评审失败: {exc}")
            review = {}
            out.append_log("reviewer", {
                "success": False,
                "error": str(exc),
                "duration_seconds": round(time.perf_counter() - review_started, 3),
                "llm_usage": llm.usage_snapshot() if llm else None,
            })

    # This is a separate review of the rendered MP4.  It keeps technical
    # evidence and visual-model feedback distinct from the storyboard
    # Reviewer above, whose input is only the scheme text and material list.
    if rendered and scheme:
        render_review_started = time.perf_counter()
        render_usage = None
        try:
            from evaluation.video_review import review_rendered_video

            if not reference_structure_path or not Path(reference_structure_path).is_file():
                raise FileNotFoundError("参考视频结构分析结果不存在")
            reference_structure = json.loads(Path(reference_structure_path).read_text(encoding="utf-8"))
            render_review, render_usage = await review_rendered_video(
                video_path, scheme, reference_structure,
                out.stage_dir("render_reviewer"), model_config=model_config,
            )
            render_review["scheme_fingerprint"] = scheme_fingerprint(scheme)
            out.save_json("render_reviewer", "render_review.json", render_review)
            out.append_log("render_reviewer", {
                # The stage itself succeeded when it saved a report.  A
                # skipped/failed visual model remains diagnostic so a useful
                # rendered video is not discarded solely for that reason.
                "success": True,
                "review_status": render_review.get("status"),
                "score": (render_review.get("visual_review") or {}).get("total_score"),
                "duration_seconds": round(time.perf_counter() - render_review_started, 3),
                "llm_usage": render_usage,
            })
        except Exception as exc:
            render_review = {"status": "failed", "reason": f"成片评测初始化失败: {exc}"}
            out.save_json("render_reviewer", "render_review.json", render_review)
            out.append_log("render_reviewer", {
                "success": True,
                "review_status": "failed",
                "error": str(exc),
                "duration_seconds": round(time.perf_counter() - render_review_started, 3),
                "llm_usage": render_usage,
            })

    if not review:
        review = {"pass": False, "status": "not_run", "reason": errors[-1] if errors else "review unavailable"}
        out.save_json("reviewer", "review_result.json", review)

    out.save_pipeline_summary({
        "status": "completed" if rendered else "failed",
        "target_topic": scheme.get("target_topic", ""),
        "phase": "complete" if rendered else "render_failed",
        "iteration": 0,
        "is_complete": rendered,
        "scheme": scheme or None,
        "rendered_video_path": str(video_path) if rendered else "",
        "review_result": review,
        "errors": errors,
        "logs": [],
    })
    report = evaluate_run(out.run_dir)
    out.save_json("evaluation", "report.json", report)
    return report
