"""Fixed-dataset paired A/B and Skill ablation experiments.

The platform is executor-agnostic: production may call the real planner and
renderer, while unit tests can inject a deterministic executor.  Both
variants always use the same case ids and evaluation contract.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class FixedTaskSet:
    """Versioned test-set manifest; media may be referenced but is not copied."""

    def __init__(self, cases: list[dict[str, Any]], version: str = "1.0"):
        if not cases:
            raise ValueError("fixed task set must contain at least one case")
        seen: set[str] = set()
        self.cases: list[dict[str, Any]] = []
        for index, raw in enumerate(cases):
            case = dict(raw)
            case_id = str(case.get("case_id") or f"case-{index + 1:03d}")
            if case_id in seen:
                raise ValueError(f"duplicate experiment case_id: {case_id}")
            seen.add(case_id)
            case["case_id"] = case_id
            self.cases.append(case)
        self.version = version

    @classmethod
    def load(cls, path: str | Path) -> "FixedTaskSet":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
            raise ValueError("task-set manifest must contain a cases list")
        return cls(data["cases"], str(data.get("version", "1.0")))

    def fingerprint(self) -> str:
        return hashlib.sha256(_canonical({"version": self.version, "cases": self.cases}).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "version": self.version, "fingerprint": self.fingerprint(), "cases": self.cases}


class ExperimentRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _init_schema(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS skill_experiments (
                    experiment_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    dataset_fingerprint TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    report_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skill_experiment_trials (
                    experiment_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    variant TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(experiment_id,case_id,variant)
                );
                """
            )

    def create(
        self,
        candidate_id: str,
        task_set: FixedTaskSet,
        *,
        kind: str = "paired_ab",
        thresholds: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dataset_hash = task_set.fingerprint()
        experiment_id = "exp_" + hashlib.sha256(f"{candidate_id}:{dataset_hash}:{kind}".encode()).hexdigest()[:16]
        config = {
            "candidate_id": candidate_id,
            "kind": kind,
            "dataset": task_set.to_dict(),
            "thresholds": {
                "min_pairs": 10,
                "min_quality_lift": 2.0,
                "min_win_rate": 0.6,
                "max_latency_regression_ratio": 0.25,
                "max_cost_regression_ratio": 0.25,
                **(thresholds or {}),
            },
        }
        now = _now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO skill_experiments(experiment_id,candidate_id,dataset_fingerprint,kind,status,config_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(experiment_id) DO NOTHING",
                (experiment_id, candidate_id, dataset_hash, kind, "created", _canonical(config), now, now),
            )
        return {"experiment_id": experiment_id, **config}

    def record(self, experiment_id: str, case_id: str, variant: str, result: dict[str, Any]) -> None:
        if variant not in {"baseline", "candidate"}:
            raise ValueError("variant must be baseline or candidate")
        experiment = self.get(experiment_id)
        if experiment is None:
            raise KeyError(f"experiment not found: {experiment_id}")
        allowed_cases = {item["case_id"] for item in experiment["config"]["dataset"]["cases"]}
        if case_id not in allowed_cases:
            raise ValueError(f"case_id is not in the fixed task set: {case_id}")
        try:
            float(result["quality_score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("experiment result requires numeric quality_score") from exc
        with self.connect() as db:
            db.execute(
                "INSERT INTO skill_experiment_trials(experiment_id,case_id,variant,result_json,created_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(experiment_id,case_id,variant) DO UPDATE SET result_json=excluded.result_json,created_at=excluded.created_at",
                (experiment_id, case_id, variant, _canonical(result), _now()),
            )
            db.execute("UPDATE skill_experiments SET status='running',updated_at=? WHERE experiment_id=?", (_now(), experiment_id))

    def get(self, experiment_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM skill_experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
        if not row:
            return None
        return {
            "experiment_id": row["experiment_id"], "candidate_id": row["candidate_id"],
            "status": row["status"], "config": json.loads(row["config_json"]),
            "report": json.loads(row["report_json"]) if row["report_json"] else None,
        }

    def trials(self, experiment_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT case_id,variant,result_json FROM skill_experiment_trials WHERE experiment_id=? ORDER BY case_id,variant",
                (experiment_id,),
            ).fetchall()
        return [{"case_id": row["case_id"], "variant": row["variant"], **json.loads(row["result_json"])} for row in rows]

    def save_report(self, experiment_id: str, report: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE skill_experiments SET status='completed',report_json=?,updated_at=? WHERE experiment_id=?",
                (_canonical(report), _now(), experiment_id),
            )


def _metric(result: dict[str, Any], name: str) -> float:
    try:
        return float(result.get(name, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def analyse_experiment(repository: ExperimentRepository, experiment_id: str) -> dict[str, Any]:
    experiment = repository.get(experiment_id)
    if experiment is None:
        raise KeyError(f"experiment not found: {experiment_id}")
    by_case: dict[str, dict[str, dict[str, Any]]] = {}
    for row in repository.trials(experiment_id):
        by_case.setdefault(row.pop("case_id"), {})[row.pop("variant")] = row
    pairs = [(case_id, values["baseline"], values["candidate"]) for case_id, values in by_case.items() if set(values) >= {"baseline", "candidate"}]
    quality_deltas = [_metric(candidate, "quality_score") - _metric(baseline, "quality_score") for _, baseline, candidate in pairs]
    latency_ratios = [
        (_metric(candidate, "latency_seconds") - _metric(baseline, "latency_seconds")) / max(_metric(baseline, "latency_seconds"), 1e-9)
        for _, baseline, candidate in pairs
    ]
    cost_ratios = [
        (_metric(candidate, "cost") - _metric(baseline, "cost")) / max(_metric(baseline, "cost"), 1e-9)
        for _, baseline, candidate in pairs
    ]
    thresholds = experiment["config"]["thresholds"]
    pair_count = len(pairs)
    quality_lift = mean(quality_deltas) if quality_deltas else 0.0
    win_rate = sum(delta > 0 for delta in quality_deltas) / pair_count if pair_count else 0.0
    latency_regression = mean(latency_ratios) if latency_ratios else 0.0
    cost_regression = mean(cost_ratios) if cost_ratios else 0.0
    if pair_count < int(thresholds["min_pairs"]):
        decision, reason = "inconclusive", "配对样本不足"
    elif quality_lift < float(thresholds["min_quality_lift"]) or win_rate < float(thresholds["min_win_rate"]):
        decision, reason = "reject", "质量提升或胜率未达到门槛"
    elif latency_regression > float(thresholds["max_latency_regression_ratio"]) or cost_regression > float(thresholds["max_cost_regression_ratio"]):
        decision, reason = "reject", "时延或成本回退超过门槛"
    else:
        decision, reason = "promote", "质量、胜率、时延和成本门槛均通过"
    report = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "candidate_id": experiment["candidate_id"],
        "paired_case_count": pair_count,
        "mean_quality_lift": round(quality_lift, 4),
        "candidate_win_rate": round(win_rate, 4),
        "mean_latency_regression_ratio": round(latency_regression, 4),
        "mean_cost_regression_ratio": round(cost_regression, 4),
        "decision": decision,
        "reason": reason,
        "thresholds": thresholds,
        "analysed_at": _now(),
    }
    repository.save_report(experiment_id, report)
    return report


async def run_paired_experiment(
    repository: ExperimentRepository,
    experiment_id: str,
    executor: Callable[[dict[str, Any], str], Any],
) -> dict[str, Any]:
    """Execute baseline and candidate on every fixed case.

    ``executor(case, variant)`` must return quality_score and may return
    latency_seconds, cost and arbitrary diagnostic fields.
    """
    experiment = repository.get(experiment_id)
    if experiment is None:
        raise KeyError(f"experiment not found: {experiment_id}")
    for case in experiment["config"]["dataset"]["cases"]:
        # Stable counter-balanced ordering avoids always warming one variant.
        variants = ["baseline", "candidate"]
        if int(hashlib.sha256(case["case_id"].encode()).hexdigest(), 16) % 2:
            variants.reverse()
        for variant in variants:
            result = executor(case, variant)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                raise TypeError("experiment executor must return a dict")
            repository.record(experiment_id, case["case_id"], variant, result)
            await asyncio.sleep(0)
    return analyse_experiment(repository, experiment_id)
