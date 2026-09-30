"""Run the travel dataset through the real LangGraph CLI sequentially.

Model credentials can be loaded from the Web backend's encrypted per-user
configuration. Secret values are injected only into each child process and
are never printed or persisted in the batch report.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIR = PROJECT_ROOT / "viral-structure-engine"
ENGINE_MAIN = ENGINE_DIR / "main.py"
DEFAULT_DATASET = ENGINE_DIR / "data" / "datasets" / "travel_vlog_batch_v1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_result(results: list[dict[str, Any]], item: dict[str, Any]) -> None:
    """Replace one case result in-place, or append it when first observed."""
    case_id = item.get("case_id")
    for index, previous in enumerate(results):
        if previous.get("case_id") == case_id:
            results[index] = item
            return
    results.append(item)


def update_report_counts(report: dict[str, Any]) -> None:
    """Refresh aggregate counters across all cases accumulated in the report."""
    results = report.get("results") or []
    report["recorded_case_count"] = len(results)
    report["pipeline_complete_count"] = sum(
        bool(item.get("pipeline_complete")) for item in results
    )
    report["passed_count"] = sum(bool(item.get("evaluation_passed")) for item in results)
    report["rejected_count"] = sum(
        item.get("batch_status") == "completed_but_rejected" for item in results
    )
    report["incomplete_count"] = sum(
        item.get("batch_status") == "incomplete" for item in results
    )
    # Compatibility alias: completion is not the same as quality acceptance.
    report["completed_count"] = report["pipeline_complete_count"]
    report["failed_process_count"] = sum(item.get("returncode", 0) != 0 for item in results)


def web_model_env(user_id: int) -> dict[str, str]:
    backend_dir = PROJECT_ROOT / "web" / "backend"
    sys.path.insert(0, str(backend_dir))
    try:
        from model_runtime import get_user_model_env
    finally:
        sys.path.pop(0)

    model_env = get_user_model_env(user_id)
    missing = [
        purpose
        for purpose, flag in (
            ("vision", "VISION_CONFIGURED"),
            ("text", "TEXT_CONFIGURED"),
        )
        if model_env.get(flag) != "1"
    ]
    if missing:
        raise RuntimeError(
            f"Web user {user_id} has no default enabled {'/'.join(missing)} model configuration"
        )
    return model_env


def result_summary(case: dict[str, Any], returncode: int, result_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    # A failed forced rerun may leave the previous successful output file in
    # place.  Never mix that stale payload into the new failed attempt.
    if returncode == 0 and result_path.is_file():
        try:
            result = load_json(result_path)
        except (OSError, json.JSONDecodeError):
            result = {}
    evaluation = result.get("evaluation") if isinstance(result.get("evaluation"), dict) else {}
    usage = evaluation.get("llm_usage") if isinstance(evaluation.get("llm_usage"), dict) else {}
    workflow_terminal = bool(result.get("is_complete"))
    rendered_video_path = str(result.get("rendered_video_path") or "").strip()
    # This runner executes the final-generation CLI, so reaching a terminal
    # graph state without a rendered artifact is not an end-to-end completion.
    pipeline_complete = workflow_terminal and bool(rendered_video_path)
    evaluation_passed = evaluation.get("success") is True
    if returncode != 0:
        batch_status = "process_failed"
    elif evaluation_passed:
        batch_status = "passed"
    elif pipeline_complete:
        batch_status = "completed_but_rejected"
    else:
        batch_status = "incomplete"
    return {
        "case_id": case["case_id"],
        "target_topic": case["target_topic"],
        "returncode": returncode,
        "status": result.get("status", "process_failed" if returncode else "unknown"),
        "phase": result.get("phase"),
        # Pipeline completion and quality acceptance are intentionally separate:
        # a rendered video may exist while the evaluator still rejects the run.
        "batch_status": batch_status,
        "pipeline_complete": pipeline_complete,
        "is_complete": pipeline_complete,
        "workflow_terminal": workflow_terminal,
        "rendered_video_path": rendered_video_path,
        "run_id": result.get("run_id", ""),
        "run_dir": result.get("output_dir", ""),
        "evaluation_score": evaluation.get("score"),
        "evaluation_success": evaluation.get("success"),
        "evaluation_passed": evaluation_passed,
        "llm_requests": usage.get("requests"),
        "llm_attempts": usage.get("attempts"),
        "llm_mock_requests": usage.get("mock_requests"),
        "llm_total_tokens": usage.get("total_tokens"),
        "error_count": result.get("error_count"),
        "result_path": str(result_path.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the 20-case travel dataset sequentially")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--web-user-id", type=int, help="load encrypted model config for this Web user")
    parser.add_argument("--limit", type=int, default=0, help="run only the first N cases")
    parser.add_argument("--case", action="append", dest="case_ids", help="run a case id; repeatable")
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument(
        "--process-retries",
        type=int,
        default=2,
        help="retry a failed case process this many times (default: 2)",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=20.0,
        help="base seconds between case-process retries (default: 20)",
    )
    parser.add_argument(
        "--enable-dynamic-components",
        action="store_true",
        help="allow costly LLM-generated TSX components; disabled for batch stability by default",
    )
    parser.add_argument("--force", action="store_true", help="rerun cases already marked complete")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    batch_path = args.dataset / "batch_manifest.json"
    batch = load_json(batch_path)
    cases = list(batch.get("cases") or [])
    if args.case_ids:
        requested = set(args.case_ids)
        cases = [case for case in cases if case.get("case_id") in requested]
        missing = requested - {case.get("case_id") for case in cases}
        if missing:
            raise RuntimeError(f"Unknown case ids: {sorted(missing)}")
    if args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        raise RuntimeError("No cases selected")

    model_env: dict[str, str] = {}
    if args.web_user_id is not None:
        model_env = web_model_env(args.web_user_id)
    child_env = os.environ.copy()
    child_env.update(model_env)
    child_env["ENABLE_DYNAMIC_COMPONENTS"] = "1" if args.enable_dynamic_components else "0"

    report_path = args.dataset / "batch_run_report.json"
    try:
        previous_report = load_json(report_path) if report_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        previous_report = {}
    previous_results = previous_report.get("results")
    if not isinstance(previous_results, list):
        previous_results = []
    report: dict[str, Any] = {
        "schema_version": "1.1",
        "dataset_id": batch.get("dataset_id"),
        "created_at": previous_report.get("created_at") or previous_report.get("started_at") or datetime.now().isoformat(),
        "last_run_started_at": datetime.now().isoformat(),
        "selected_case_count": len(cases),
        "selected_case_ids": [case["case_id"] for case in cases],
        "credential_source": "web_encrypted_config" if args.web_user_id is not None else "engine_environment",
        "web_user_id": args.web_user_id,
        "max_iterations": args.max_iterations,
        "dynamic_components_enabled": args.enable_dynamic_components,
        "results": previous_results,
    }

    for index, case in enumerate(cases, start=1):
        case_dir = Path(case["materials_json"]).resolve().parent
        result_path = case_dir / "pipeline_result.json"
        if not args.force and result_path.is_file():
            previous = load_json(result_path)
            previous_evaluation = (
                previous.get("evaluation")
                if isinstance(previous.get("evaluation"), dict)
                else {}
            )
            if previous.get("is_complete") and previous_evaluation.get("success") is True:
                print(f"[skip {index}/{len(cases)}] {case['case_id']} already passed", flush=True)
                upsert_result(report["results"], result_summary(case, 0, result_path))
                continue

        command = [
            sys.executable,
            str(ENGINE_MAIN),
            "--topic",
            case["target_topic"],
            "--samples",
            case["reference_video"],
            "--materials",
            case["materials_json"],
            "--output",
            str(result_path),
            "--max-iterations",
            str(args.max_iterations),
        ]
        print(f"[run {index}/{len(cases)}] {case['case_id']} - {case['target_topic']}", flush=True)
        if args.dry_run:
            upsert_result(report["results"], {"case_id": case["case_id"], "status": "dry_run"})
            continue

        completed = None
        attempt_count = 0
        for attempt in range(args.process_retries + 1):
            attempt_count = attempt + 1
            completed = subprocess.run(command, cwd=ENGINE_DIR, env=child_env, check=False)
            if completed.returncode == 0:
                break
            if attempt < args.process_retries:
                delay = args.retry_delay * (attempt + 1)
                print(
                    f"[retry {attempt + 1}/{args.process_retries}] "
                    f"{case['case_id']} failed with exit {completed.returncode}; "
                    f"waiting {delay:.1f}s",
                    flush=True,
                )
                time.sleep(delay)

        assert completed is not None
        summary = result_summary(case, completed.returncode, result_path)
        summary["process_attempt_count"] = attempt_count
        upsert_result(report["results"], summary)
        report["updated_at"] = datetime.now().isoformat()
        update_report_counts(report)
        save_json(report_path, report)

    report["last_run_finished_at"] = datetime.now().isoformat()
    update_report_counts(report)
    save_json(report_path, report)
    print(json.dumps({
        "report": str(report_path.resolve()),
        "selected": len(cases),
        "pipeline_completed": report["pipeline_complete_count"],
        "passed": report["passed_count"],
        "rejected": report["rejected_count"],
        "failed_processes": report["failed_process_count"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["failed_process_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
