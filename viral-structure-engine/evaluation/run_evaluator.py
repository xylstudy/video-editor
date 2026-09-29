"""Offline evaluation of recorded planning, rendering and review runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any


REPORT_VERSION = "2.1"


def _read_json(path: Path) -> tuple[Any, str | None]:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle), None
    except FileNotFoundError:
        return None, f"missing: {path.name}"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"invalid JSON: {path.name} ({exc})"


def _read_logs(path: Path) -> tuple[list[dict[str, Any]], list[datetime]]:
    if not path.is_file():
        return [], []
    entries: list[dict[str, Any]] = []
    timestamps: list[datetime] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        entries.append(entry)
        timestamp = entry.get("timestamp")
        if isinstance(timestamp, str):
            try:
                timestamps.append(datetime.fromisoformat(timestamp))
            except ValueError:
                pass
    return entries, timestamps


def _check(name: str, passed: bool, weight: float, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "weight": weight, "detail": detail}


def _resolve_video_path(value: Any, run_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else run_dir / path


def scheme_fingerprint(scheme: dict[str, Any]) -> str:
    encoded = json.dumps(scheme, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _coverage(scheme: dict[str, Any] | None, inventory: dict[str, Any] | None) -> tuple[float | None, str]:
    if not isinstance(scheme, dict) or not isinstance(inventory, dict):
        return None, "scheme or inventory unavailable"
    materials = inventory.get("items", inventory.get("materials", []))
    storyboard = scheme.get("storyboard", [])
    if not isinstance(materials, list) or not isinstance(storyboard, list):
        return None, "invalid scheme or inventory structure"
    material_ids = {str(item.get("id")) for item in materials if isinstance(item, dict) and item.get("id")}
    if not material_ids:
        return None, "no user materials to cover"
    used_ids = {
        str(frame.get("material_id") or frame.get("source_material_id"))
        for frame in storyboard
        if isinstance(frame, dict) and (frame.get("material_id") or frame.get("source_material_id"))
    }
    used = material_ids & used_ids
    return len(used) / len(material_ids), f"{len(used)}/{len(material_ids)} user materials used"


def _probe_video(path: Path | None) -> dict[str, Any]:
    """Require a video stream, positive duration and a full-stream decode."""
    result: dict[str, Any] = {
        "valid": False, "full_decode_valid": False, "duration_seconds": None,
        "width": None, "height": None, "has_audio": None,
    }
    try:
        if path is None or not path.is_file() or path.stat().st_size == 0:
            return {**result, "detail": "missing or empty rendered video"}
    except OSError as exc:
        return {**result, "detail": f"video cannot be read: {exc}"}
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        return {**result, "detail": "ffprobe or ffmpeg unavailable"}
    try:
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if probe.returncode != 0:
            return {**result, "detail": f"ffprobe failed: {probe.stderr.strip()[:200]}"}
        metadata = json.loads(probe.stdout)
        stream = next((s for s in metadata.get("streams", []) if s.get("codec_type") == "video"), None)
        duration = float(metadata.get("format", {}).get("duration") or 0)
        if not stream or duration <= 0:
            return {**result, "detail": "video stream or duration missing"}
        decoded = subprocess.run(
            [ffmpeg, "-v", "error", "-xerror", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if decoded.returncode != 0:
            return {**result, "detail": f"video stream cannot be fully decoded: {decoded.stderr.strip()[:200]}"}
        return {
            "valid": True,
            "full_decode_valid": True,
            "duration_seconds": round(duration, 3),
            "width": stream.get("width"),
            "height": stream.get("height"),
            "has_audio": any(item.get("codec_type") == "audio" for item in metadata.get("streams", [])),
            "detail": "video stream fully decoded",
        }
    except (OSError, TypeError, ValueError, subprocess.TimeoutExpired) as exc:
        return {**result, "detail": f"media probe failed: {exc}"}


def _latest_scheme(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    final = root / "planner" / "scheme_final.json"
    if final.is_file():
        value, error = _read_json(final)
        return (value if isinstance(value, dict) else None), error
    candidates = sorted((root / "planner").glob("scheme_v*.json"))
    if not candidates:
        return None, "missing: scheme_final.json or scheme_v*.json"
    value, error = _read_json(candidates[-1])
    return (value if isinstance(value, dict) else None), error


def evaluate_run(run_dir: str | Path) -> dict[str, Any]:
    """Evaluate one saved run without calling a model or changing the run."""
    root = Path(run_dir)
    summary, summary_error = _read_json(root / "pipeline_summary.json")
    info, info_error = _read_json(root / "run_info.json")
    scheme, scheme_error = _latest_scheme(root)
    inventory, inventory_error = _read_json(root / "material" / "inventory.json")
    review, review_error = _read_json(root / "reviewer" / "review_result.json")
    render_review, render_review_error = _read_json(root / "render_reviewer" / "render_review.json")
    summary = summary if isinstance(summary, dict) else {}
    info = info if isinstance(info, dict) else {}
    inventory = inventory if isinstance(inventory, dict) else None
    review = review if isinstance(review, dict) else None
    render_review = render_review if isinstance(render_review, dict) else None

    phase = summary.get("status", "missing")
    prepared = phase == "awaiting_confirmation"
    entries, timestamps = _read_logs(root / "logs" / "agent_logs.jsonl")
    stages = [entry["stage"] for entry in entries if isinstance(entry.get("stage"), str)]
    successful_stages = {
        entry["stage"] for entry in entries
        if isinstance(entry.get("stage"), str) and entry.get("success") is not False and entry.get("status") != "failed"
    }
    declared_stages = info.get("expected_stages")
    if isinstance(declared_stages, list) and all(isinstance(stage, str) for stage in declared_stages):
        expected = set(declared_stages)
    else:
        expected = {"planner", "renderer", "assembler", "reviewer"}
        if info.get("sample_videos"):
            expected.add("analyst")
        if info.get("user_materials_count", 0):
            expected.add("material")
    if prepared:
        expected.difference_update({"assembler", "reviewer", "render_reviewer"})
    missing_stages = sorted(expected - successful_stages)

    errors = summary.get("errors", [])
    errors = errors if isinstance(errors, list) else [str(errors)]
    failed_stages = [entry.get("stage") for entry in entries if entry.get("success") is False or entry.get("status") == "failed"]
    output_path = _resolve_video_path(summary.get("rendered_video_path"), root)
    media = _probe_video(output_path) if not prepared else {"valid": False, "duration_seconds": None, "detail": "render pending"}
    target_duration = scheme.get("target_duration") if scheme else None
    try:
        target_duration = float(target_duration)
    except (TypeError, ValueError):
        target_duration = None
    duration_ok = bool(
        target_duration and target_duration > 0 and media["duration_seconds"]
        and abs(media["duration_seconds"] - target_duration) <= max(1.0, target_duration * 0.1)
    )
    coverage_ratio, coverage_detail = _coverage(scheme, inventory)
    usage_entries = [entry["llm_usage"] for entry in entries if isinstance(entry.get("llm_usage"), dict)]
    llm_usage = {}
    for key in ("requests", "attempts", "responses", "mock_requests", "prompt_tokens", "completion_tokens", "total_tokens"):
        values = [usage[key] for usage in usage_entries if isinstance(usage.get(key), int) and not isinstance(usage[key], bool)]
        llm_usage[key] = sum(values) if values else None
    llm_usage["models"] = sorted({usage["model"] for usage in usage_entries if isinstance(usage.get("model"), str)})
    review_pass = bool(review and review.get("pass") is True)
    reviewed_fingerprint = review.get("scheme_fingerprint") if review else None
    review_current = bool(review_pass and (not reviewed_fingerprint or (scheme and reviewed_fingerprint == scheme_fingerprint(scheme))))
    raw_score = review.get("total_score") if review else None
    review_score = float(raw_score) if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool) else None
    items = inventory.get("items", inventory.get("materials")) if inventory else None
    artifacts_ok = bool(
        scheme and isinstance(scheme.get("storyboard"), list) and scheme["storyboard"]
        and isinstance(items, list) and items
    )
    artifact_detail = "; ".join(x for x in (scheme_error, inventory_error) if x)
    if not artifact_detail:
        artifact_detail = "scheme and inventory loaded" if artifacts_ok else "storyboard or inventory is empty or invalid"
    review_artifact_ok = review is not None and review_error is None and review_score is not None and isinstance(review.get("pass"), bool)
    render_status = render_review.get("status") if render_review else None
    render_visual = render_review.get("visual_review") if render_review else None
    render_visual = render_visual if isinstance(render_visual, dict) else None
    raw_render_score = render_visual.get("total_score") if render_visual else None
    render_score = float(raw_render_score) if isinstance(raw_render_score, (int, float)) and not isinstance(raw_render_score, bool) else None
    render_current = bool(
        render_review and scheme and render_review.get("scheme_fingerprint") == scheme_fingerprint(scheme)
    )
    render_review_summary = None
    if render_review:
        render_review_summary = {
            "status": render_status,
            "score": render_score,
            "summary": render_visual.get("summary") if render_visual else None,
            "issues": render_visual.get("issues", []) if render_visual else [],
            "limitations": render_visual.get("limitations", []) if render_visual else [],
            "technical": render_review.get("technical", {}),
            "reason": render_review.get("reason"),
        }

    checks = [
        _check("pipeline_summary", summary_error is None and bool(summary), 10, summary_error or phase),
        _check("run_info", info_error is None and bool(info), 5, info_error or "run metadata loaded"),
        _check("agent_stage_coverage", not missing_stages, 20, "all expected stages succeeded" if not missing_stages else f"missing or failed: {', '.join(missing_stages)}"),
        _check("structured_artifacts", artifacts_ok, 20, artifact_detail),
        _check("pipeline_errors", not errors and not failed_stages, 10, "no recorded errors" if not errors and not failed_stages else f"{len(errors)} error(s), {len(failed_stages)} failed stage(s)"),
    ]
    if not prepared:
        checks.extend([
            _check("review_artifact", review_artifact_ok, 5, review_error or ("review loaded" if review_artifact_ok else "review score or pass flag missing")),
            _check("review_pass", review_current, 15, f"review score: {review_score if review_score is not None else 'N/A'}; current scheme: {review_current}"),
            _check("media_output", bool(media["valid"]), 10, media["detail"]),
            _check("video_duration", duration_ok, 5, f"expected {target_duration}, rendered {media['duration_seconds']} seconds"),
        ])
        # Render review is a quality diagnostic until its scores are calibrated
        # against a human-labelled benchmark.  It therefore contributes to the
        # report score but is intentionally not a hard success gate.
        # Historical runs predate rendered-video review; do not retroactively
        # penalise them for an artifact that did not exist yet.
        render_review_present = render_review is not None or (
            render_review_error is not None and not render_review_error.startswith("missing:")
        )
        if render_review_present:
            render_review_ok = bool(render_review and render_status in {"completed", "skipped"})
            render_detail = render_review_error or (
                f"status: {render_status}; visual score: {render_score if render_score is not None else 'N/A'}"
            )
            checks.append(_check("render_review_artifact", render_review_ok, 5, render_detail))
            if render_status == "completed":
                checks.append(_check("render_review_current", render_current, 5, "confirmed scheme fingerprint matches" if render_current else "render review is stale"))
    if coverage_ratio is not None:
        checks.append(_check("material_coverage", coverage_ratio >= 0.8, 10, coverage_detail))
    if usage_entries:
        checks.append(_check("model_execution", not llm_usage["mock_requests"], 5, f"{llm_usage['mock_requests'] or 0} mock response(s)"))

    weight = sum(item["weight"] for item in checks)
    score = round(sum(item["weight"] for item in checks if item["passed"]) / weight * 100, 2) if weight else 0.0
    critical = {"pipeline_summary", "run_info", "agent_stage_coverage", "structured_artifacts", "pipeline_errors", "review_artifact", "review_pass", "media_output", "video_duration", "model_execution"}
    complete = phase == "completed" and all(item["passed"] for item in checks if item["name"] in critical)
    duration_seconds = round((max(timestamps) - min(timestamps)).total_seconds(), 3) if len(timestamps) >= 2 else None
    stage_durations: dict[str, float] = {}
    stage_attempts: dict[str, int] = {}
    for entry in entries:
        stage = entry.get("stage")
        if not isinstance(stage, str):
            continue
        stage_attempts[stage] = stage_attempts.get(stage, 0) + 1
        elapsed = entry.get("duration_seconds")
        if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and elapsed >= 0:
            stage_durations[stage] = round(stage_durations.get(stage, 0) + elapsed, 3)
    return {
        "schema_version": REPORT_VERSION,
        "run_id": root.name,
        "run_dir": str(root),
        "evaluated_at": datetime.now().isoformat(),
        "phase": phase,
        "success": complete,
        "ready_for_render": prepared and all(item["passed"] for item in checks if item["name"] in {"pipeline_summary", "run_info", "agent_stage_coverage", "structured_artifacts", "pipeline_errors", "model_execution"}),
        "score": score,
        "quality": {
            "review_score": review_score,
            "review_pass": review_pass,
            "review_current": review_current,
            "material_coverage": coverage_ratio,
            "render_review_status": render_status,
            "render_review_score": render_score,
            "render_review_current": render_current if render_status == "completed" else None,
        },
        "execution": {
            "stages_seen": stages,
            "missing_stages": missing_stages,
            "failed_stages": failed_stages,
            "stage_attempts": stage_attempts,
            "stage_durations_seconds": stage_durations,
            "duration_seconds": duration_seconds,
            "error_count": len(errors),
            "video_valid": bool(media["valid"]),
        },
        "media": media,
        "render_review": render_review_summary,
        "llm_usage": llm_usage,
        "checks": checks,
    }


def evaluate_runs(run_dirs: list[str | Path]) -> dict[str, Any]:
    reports = [evaluate_run(path) for path in run_dirs]
    completed = [report for report in reports if report["phase"] != "awaiting_confirmation"]
    durations = [report["execution"]["duration_seconds"] for report in completed if report["execution"]["duration_seconds"] is not None]
    return {
        "schema_version": REPORT_VERSION,
        "evaluated_at": datetime.now().isoformat(),
        "run_count": len(reports),
        "pending_count": len(reports) - len(completed),
        "success_rate": round(sum(report["success"] for report in completed) / len(completed), 4) if completed else None,
        "average_score": round(mean(report["score"] for report in completed), 2) if completed else None,
        "average_duration_seconds": round(mean(durations), 3) if durations else None,
        "reports": reports,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate recorded multi-agent pipeline runs")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--run-dir")
    target.add_argument("--runs-dir")
    parser.add_argument("--output")
    parser.add_argument("--min-score", type=float, help="Require all final runs to pass and meet this score")
    args = parser.parse_args()
    if args.run_dir:
        report: dict[str, Any] = evaluate_run(args.run_dir)
        reports = [report]
    else:
        root = Path(args.runs_dir)
        if not root.is_dir():
            parser.error(f"run directory does not exist: {root}")
        run_dirs = sorted(path for path in root.iterdir() if path.is_dir() and ((path / "run_info.json").exists() or (path / "pipeline_summary.json").exists() or (path / "planner").exists()))
        report = evaluate_runs(run_dirs)
        reports = report["reports"]
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    if args.min_score is not None and (not reports or any(item["phase"] != "awaiting_confirmation" and (not item["success"] or item["score"] < args.min_score) for item in reports)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
