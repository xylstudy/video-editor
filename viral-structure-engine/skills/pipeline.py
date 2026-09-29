"""Command-line operations for the complete Skill learning lifecycle.

Examples:
  python -m skills.pipeline ingest
  python -m skills.pipeline mine --min-samples 10
  python -m skills.pipeline experiment-create --candidate ID --dataset cases.json
  python -m skills.pipeline experiment-record --experiment ID --case case-1 --variant baseline --result result.json
  python -m skills.pipeline experiment-analyse --experiment ID
  python -m skills.pipeline promote --candidate ID --experiment EXP_ID
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from config import settings
from skills.experience import capture_run_experiences
from skills.experiments import ExperimentRepository, FixedTaskSet, analyse_experiment
from skills.lifecycle import PromotionPolicy, RoutingWeightLearner, SkillLifecycleManager
from skills.mining import IncrementalSkillMiner


DEFAULT_DATABASE = settings.DATA_DIR / "skill_experiences.sqlite3"
DEFAULT_SKILL_DIR = Path(__file__).resolve().parent / "video-editing"


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def ingest(runs_root: Path, database: Path) -> dict[str, Any]:
    completed: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    if not runs_root.is_dir():
        return {"ingested": completed, "failed": [{"run": str(runs_root), "error": "runs_root_not_found"}]}
    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        if not (run_dir / "pipeline_summary.json").is_file():
            continue
        try:
            completed.append(capture_run_experiences(run_dir, database))
        except Exception as exc:
            failed.append({"run": run_dir.name, "error": f"{type(exc).__name__}: {exc}"})
    return {"ingested": completed, "failed": failed}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Skill 经验发现、实验、晋升与回滚工具")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--skill-dir", type=Path, default=DEFAULT_SKILL_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_parser = sub.add_parser("ingest", help="扫描历史 run 并抽取经验")
    ingest_parser.add_argument("--runs-root", type=Path, default=settings.RUNS_DIR)

    mine = sub.add_parser("mine", help="归一化、增量聚合并生成候选")
    mine.add_argument("--min-samples", type=int, default=10)
    mine.add_argument("--limit", type=int, default=1000)

    run_all = sub.add_parser("run-all", help="采集 + 挖掘；可选自动晋升已通过实验的候选")
    run_all.add_argument("--runs-root", type=Path, default=settings.RUNS_DIR)
    run_all.add_argument("--min-samples", type=int, default=10)
    run_all.add_argument("--auto-promote", action="store_true")

    create = sub.add_parser("experiment-create", help="基于固定任务集创建配对 A/B 实验")
    create.add_argument("--candidate", required=True)
    create.add_argument("--dataset", type=Path, required=True)
    create.add_argument("--min-pairs", type=int, default=10)
    create.add_argument("--kind", choices=["paired_ab", "ablation"], default="paired_ab")

    record = sub.add_parser("experiment-record", help="写入一个 case/variant 的结果")
    record.add_argument("--experiment", required=True)
    record.add_argument("--case", required=True)
    record.add_argument("--variant", choices=["baseline", "candidate"], required=True)
    record.add_argument("--result", type=Path, required=True)

    analyse = sub.add_parser("experiment-analyse", help="分析已记录的配对 A/B 结果")
    analyse.add_argument("--experiment", required=True)

    promote = sub.add_parser("promote", help="按策略门禁晋升候选 Skill")
    promote.add_argument("--candidate", required=True)
    promote.add_argument("--experiment", required=True)
    promote.add_argument("--min-samples", type=int, default=10)
    promote.add_argument("--force", action="store_true", help="仅限人工紧急处置；绕过策略门禁")

    rollback = sub.add_parser("rollback", help="回滚到已归档 Skill 版本")
    rollback.add_argument("--skill", required=True)
    rollback.add_argument("--version", required=True)

    weights = sub.add_parser("learn-weights", help="保守更新语义路由权重")
    weights.add_argument("--min-samples", type=int, default=10)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    database: Path = args.database
    if args.command == "ingest":
        _print(ingest(args.runs_root, database))
    elif args.command == "mine":
        _print(IncrementalSkillMiner(database, min_samples=args.min_samples).process_pending(args.limit))
    elif args.command == "run-all":
        ingestion = ingest(args.runs_root, database)
        mining = IncrementalSkillMiner(database, min_samples=args.min_samples).process_pending()
        promoted: list[dict[str, Any]] = []
        if args.auto_promote:
            manager = SkillLifecycleManager(
                database, args.skill_dir,
                PromotionPolicy(min_observational_samples=args.min_samples),
            )
            promoted = manager.auto_promote_eligible()
        _print({"ingestion": ingestion, "mining": mining, "promoted": promoted})
    elif args.command == "experiment-create":
        repo = ExperimentRepository(database)
        _print(repo.create(
            args.candidate, FixedTaskSet.load(args.dataset), kind=args.kind,
            thresholds={"min_pairs": args.min_pairs},
        ))
    elif args.command == "experiment-record":
        result = json.loads(args.result.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError("experiment result JSON must be an object")
        ExperimentRepository(database).record(args.experiment, args.case, args.variant, result)
        _print({"recorded": True, "experiment_id": args.experiment, "case_id": args.case, "variant": args.variant})
    elif args.command == "experiment-analyse":
        _print(analyse_experiment(ExperimentRepository(database), args.experiment))
    elif args.command == "promote":
        manager = SkillLifecycleManager(
            database, args.skill_dir,
            PromotionPolicy(min_observational_samples=args.min_samples),
        )
        _print(manager.promote(args.candidate, args.experiment, force=args.force))
    elif args.command == "rollback":
        _print(SkillLifecycleManager(database, args.skill_dir).rollback(args.skill, args.version))
    elif args.command == "learn-weights":
        _print(RoutingWeightLearner(database, args.skill_dir / "registry.json", args.min_samples).learn())


if __name__ == "__main__":
    main()
