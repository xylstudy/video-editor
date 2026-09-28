"""Offline, non-causal aggregation of per-run Skill evaluation artifacts.

This module answers operational questions such as "how often was hook routed,
declared and verified?"  It deliberately does *not* learn routing weights or
claim a Skill caused a score change.  Those require labelled routing sets and
controlled A/B or ablation experiments.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


def _read_trace(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def discover_skill_evaluations(runs_root: str | Path) -> list[Path]:
    """Find final per-run traces below an OutputManager runs directory."""
    root = Path(runs_root)
    if not root.is_dir():
        return []
    return sorted(root.glob("*/evaluation/skill_evaluation.json"))


def aggregate_skill_evaluations(paths: Iterable[str | Path], min_samples: int = 10) -> dict[str, Any]:
    """Aggregate trace/compliance/outcome association by Skill id and version."""
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    run_count = 0
    for raw_path in paths:
        trace = _read_trace(Path(raw_path))
        if trace is None:
            continue
        run_count += 1
        selected = set(trace.get("selected_skill_refs", []))
        loaded = set(trace.get("loaded_skill_refs", []))
        declared = set(trace.get("declared_skill_refs", []))
        verified = set(trace.get("verified_skill_refs", []))
        verification = {
            item.get("skill_id"): item
            for item in trace.get("verification", [])
            if isinstance(item, dict) and item.get("skill_id")
        }
        reviewer = (trace.get("outcomes") or {}).get("reviewer", {})
        reviewer = reviewer if isinstance(reviewer, dict) else {}

        for decision in trace.get("route_decisions", []):
            if not isinstance(decision, dict):
                continue
            skill_id = str(decision.get("skill_id", "")).strip()
            if not skill_id or skill_id not in selected:
                continue
            version = str(decision.get("skill_version", "unregistered"))
            bucket = buckets.setdefault((skill_id, version), {
                "skill_id": skill_id,
                "skill_version": version,
                "selected_count": 0,
                "loaded_count": 0,
                "declared_count": 0,
                "verified_count": 0,
                "not_declared_count": 0,
                "compliance_scores": [],
                "reviewer_scores": [],
                "reviewer_passes": [],
                "triggers": set(),
            })
            bucket["selected_count"] += 1
            bucket["loaded_count"] += int(skill_id in loaded)
            bucket["declared_count"] += int(skill_id in declared)
            bucket["verified_count"] += int(skill_id in verified)
            detail = verification.get(skill_id, {})
            if detail.get("status") == "not_declared":
                bucket["not_declared_count"] += 1
            score = detail.get("compliance_score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                bucket["compliance_scores"].append(float(score))
            score = reviewer.get("total_score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                bucket["reviewer_scores"].append(float(score))
            if isinstance(reviewer.get("passed"), bool):
                bucket["reviewer_passes"].append(reviewer["passed"])
            for trigger in decision.get("triggers", []):
                if isinstance(trigger, str) and trigger:
                    bucket["triggers"].add(trigger)

    rows: list[dict[str, Any]] = []
    for bucket in buckets.values():
        selected_count = bucket["selected_count"]
        compliance_scores = bucket.pop("compliance_scores")
        reviewer_scores = bucket.pop("reviewer_scores")
        reviewer_passes = bucket.pop("reviewer_passes")
        triggers = sorted(bucket.pop("triggers"))
        declared_rate = bucket["declared_count"] / selected_count if selected_count else None
        verified_rate = bucket["verified_count"] / selected_count if selected_count else None
        compliance_mean = mean(compliance_scores) if compliance_scores else None
        sample_note = (
            "insufficient_samples_keep_deterministic_route"
            if selected_count < min_samples
            else "enough_observational_samples_for_manual_review"
        )
        rows.append({
            **bucket,
            "declared_rate": round(declared_rate, 3) if declared_rate is not None else None,
            "verified_rate": round(verified_rate, 3) if verified_rate is not None else None,
            "mean_compliance_score": round(compliance_mean, 3) if compliance_mean is not None else None,
            "mean_associated_reviewer_score": round(mean(reviewer_scores), 3) if reviewer_scores else None,
            "associated_reviewer_pass_rate": round(sum(reviewer_passes) / len(reviewer_passes), 3)
            if reviewer_passes else None,
            "triggers": triggers,
            "recommendation": sample_note,
        })

    rows.sort(key=lambda item: (-item["selected_count"], item["skill_id"], item["skill_version"]))
    return {
        "schema_version": "1.0",
        "run_count": run_count,
        "skill_reports": rows,
        "interpretation": (
            "Observational aggregation only. It measures routing/declaration/compliance and associated outcomes; "
            "it does not prove a Skill caused score improvement or automatically change routing weights."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="汇总多次运行的 Skill 路由与遵循度证据")
    parser.add_argument("--runs-root", required=True, help="data/runs 目录")
    parser.add_argument("--output", default="", help="可选 JSON 报告输出路径")
    parser.add_argument("--min-samples", type=int, default=10, help="给出人工复核建议所需的最小样本量")
    args = parser.parse_args()
    paths = discover_skill_evaluations(args.runs_root)
    report = aggregate_skill_evaluations(paths, min_samples=max(1, args.min_samples))
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
