import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills.candidates import CandidateRepository, CandidateValidator
from skills.experience import ExperienceRepository, capture_run_experiences
from skills.experiments import ExperimentRepository, FixedTaskSet, analyse_experiment, run_paired_experiment
from skills.lifecycle import PromotionPolicy, RoutingWeightLearner, SkillLifecycleManager
from skills.mining import IncrementalSkillMiner
from config import settings
from config.output_manager import OutputManager


def _write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_run(root: Path, run_id: str, score: float = 86.0, declared: bool = True) -> Path:
    run = root / run_id
    _write(run / "run_info.json", {"run_id": run_id, "video_type": "travel_vlog"})
    _write(run / "pipeline_summary.json", {"status": "completed", "is_complete": True})
    _write(run / "analyst/gene.json", {
        "structure_type": "three_act", "hook_strategy": "visual_hook", "rhythm_pattern": "fast",
        "shot_genes": [{"function": "hook"}, {"function": "climax"}],
    })
    _write(run / "material/inventory.json", {"items": [
        {"id": "private-material-id", "type": "video", "description": "运动风景，含人物"},
    ]})
    scheme = {
        "target_category": "travel_vlog", "target_platform": "抖音", "target_duration": 30,
        "storyboard": [
            {"structure_function": "hook", "duration": 1.2, "material_id": "private-material-id", "subtitle_text": "出发"},
            {"structure_function": "climax", "duration": 3.0, "material_id": "private-material-id"},
        ],
    }
    _write(run / "planner/scheme_final.json", scheme)
    selected = ["hook"]
    _write(run / "evaluation/skill_evaluation.json", {
        "selected_skill_refs": selected, "loaded_skill_refs": selected,
        "declared_skill_refs": selected if declared else [], "verified_skill_refs": selected if declared else [],
        "route_decisions": [{"skill_id": "hook", "skill_version": "1.0.0", "selected_by": "deterministic_rule", "triggers": ["Gene hook"]}],
        "verification": [{"skill_id": "hook", "status": "verified" if declared else "not_declared", "compliance_score": 1.0 if declared else None}],
    })
    _write(run / "reviewer/review_result.json", {"pass": True, "total_score": score})
    _write(run / "render_reviewer/render_review.json", {"status": "passed", "technical": {"passed": True}})
    _write(run / "evaluation/report.json", {"success": True, "score": score})
    return run


def _skill_dir(root: Path) -> Path:
    skill_dir = root / "video-editing"
    _write(skill_dir / "registry.json", {
        "schema_version": "1.0", "skill": "video-editing", "skills": [{
            "id": "hook", "version": "1.0.0", "status": "active", "priority": 90,
            "routing_weight": 1.0, "applicable_stages": ["planning"],
            "applicable_shot_functions": ["hook"], "validation_rules": ["hook_first_shot"],
            "description": "old hook",
        }],
    })
    (skill_dir / "references").mkdir(parents=True, exist_ok=True)
    (skill_dir / "references/hook.md").write_text("# old hook\n", encoding="utf-8")
    return skill_dir


def test_extraction_is_idempotent_and_does_not_store_media_path(tmp_path):
    run = _make_run(tmp_path / "runs", "run-001")
    database = tmp_path / "experience.sqlite3"
    first = capture_run_experiences(run, database)
    second = capture_run_experiences(run, database)
    assert first["decision_count"] == second["decision_count"] == 1
    repository = ExperienceRepository(database)
    decisions = repository.all_decisions()
    assert len(decisions) == 1
    encoded = json.dumps(decisions, ensure_ascii=False)
    assert "private-material-id" not in encoded
    assert "structural_features_only" in (run / "experience/run_experience.json").read_text(encoding="utf-8")
    IncrementalSkillMiner(database, min_samples=10).process_pending()
    capture_run_experiences(run, database)
    assert repository.pending() == []


def test_output_manager_automatically_refreshes_experience(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    runs_dir = data_dir / "runs"
    run = _make_run(runs_dir, "run-auto")
    monkeypatch.setattr(settings, "DATA_DIR", data_dir)
    monkeypatch.setattr(settings, "RUNS_DIR", runs_dir)
    manager = OutputManager("run-auto")
    manager.save_json("evaluation", "report.json", {"success": True, "score": 88})
    assert (run / "experience/run_experience.json").is_file()
    assert len(ExperienceRepository(data_dir / "skill_experiences.sqlite3").all_decisions()) == 1


def test_incremental_mining_filters_bad_data_and_generates_candidate(tmp_path):
    database = tmp_path / "experience.sqlite3"
    capture_run_experiences(_make_run(tmp_path / "runs", "run-001", 84), database)
    capture_run_experiences(_make_run(tmp_path / "runs", "run-002", 90), database)
    capture_run_experiences(_make_run(tmp_path / "runs", "run-bad", 95, declared=False), database)
    miner = IncrementalSkillMiner(database, min_samples=2)
    result = miner.process_pending()
    assert result["accepted"] == 2
    assert result["rejected"] == 1
    assert result["rejection_reasons"]["not_declared"] == 1
    assert len(result["candidates_created"]) == 1
    candidate = CandidateRepository(database).get(result["candidates_created"][0])
    assert candidate["status"] == "needs_experiment"
    assert candidate["evidence"]["sample_count"] == 2
    # No new rows means incremental processing does not count old data twice.
    again = miner.process_pending()
    assert again["pending_processed"] == 0
    assert miner.groups()[0]["sample_count"] == 2


def test_candidate_duplicate_and_conflict_checks(tmp_path):
    repo = CandidateRepository(tmp_path / "db.sqlite3")
    base = {
        "candidate_id": "c1", "target_skill_id": "hook", "status": "draft",
        "description": "hook", "conditions": {"rhythm": "fast"},
        "action": {"first_shot_duration": "very_short"}, "instructions": ["shorten"],
        "validation_rules": ["hook_first_shot"], "evidence": {"sample_count": 10},
    }
    repo.save(base)
    duplicate = dict(base, candidate_id="c2")
    assert CandidateValidator(repo).validate(duplicate)["valid"] is False
    conflict = dict(base, candidate_id="c3", action={"first_shot_duration": "long"})
    result = CandidateValidator(repo).validate(conflict)
    assert result["valid"] is True
    assert result["warnings"][0]["code"] == "condition_action_conflict"


def test_paired_ab_promotion_rollback_and_weight_learning(tmp_path):
    database = tmp_path / "experience.sqlite3"
    capture_run_experiences(_make_run(tmp_path / "runs", "run-001", 84), database)
    capture_run_experiences(_make_run(tmp_path / "runs", "run-002", 90), database)
    mined = IncrementalSkillMiner(database, min_samples=2).process_pending()
    candidate_id = mined["candidates_created"][0]

    task_set = FixedTaskSet([{"case_id": "case-a"}, {"case_id": "case-b"}], version="fixed-v1")
    experiments = ExperimentRepository(database)
    experiment = experiments.create(candidate_id, task_set, thresholds={
        "min_pairs": 2, "min_quality_lift": 2, "min_win_rate": 0.5,
    })

    async def executor(case, variant):
        return {
            "quality_score": 82 if variant == "candidate" else 72,
            "latency_seconds": 10, "cost": 1,
        }

    report = asyncio.run(run_paired_experiment(experiments, experiment["experiment_id"], executor))
    assert report["decision"] == "promote"
    assert analyse_experiment(experiments, experiment["experiment_id"])["paired_case_count"] == 2

    skill_dir = _skill_dir(tmp_path / "skills")
    manager = SkillLifecycleManager(
        database, skill_dir, PromotionPolicy(min_observational_samples=2),
    )
    promoted = manager.promote(candidate_id, experiment["experiment_id"])
    assert promoted["to_version"] == "1.0.1"
    registry = json.loads((skill_dir / "registry.json").read_text(encoding="utf-8"))
    assert registry["skills"][0]["source_candidate_id"] == candidate_id
    assert registry["skills"][0]["description"] == "old hook"
    promoted_markdown = (skill_dir / "references/hook.md").read_text(encoding="utf-8")
    assert promoted_markdown.startswith("# old hook")
    assert "数据学习规则 1.0.1" in promoted_markdown
    assert (skill_dir / "versions/hook/1.0.0/definition.json").is_file()

    rolled_back = manager.rollback("hook", "1.0.0")
    assert rolled_back["to_version"] == "1.0.0"
    assert (skill_dir / "references/hook.md").read_text(encoding="utf-8") == "# old hook\n"

    weights = RoutingWeightLearner(database, skill_dir / "registry.json", min_samples=2).learn()
    assert weights["updates"]["hook"]["new"] > 1.0
    weighted_registry = json.loads((skill_dir / "registry.json").read_text(encoding="utf-8"))
    assert weighted_registry["skills"][0]["routing_weight"] > 1.0
