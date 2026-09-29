"""Policy-gated Skill promotion, rollback and routing-weight learning."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from skills.candidates import CandidateRepository, CandidateValidator, candidate_markdown
from skills.experience import ExperienceRepository
from skills.experiments import ExperimentRepository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(value, encoding="utf-8")
    os.replace(temp, path)


def _next_patch(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version or "")
    if not match:
        return "1.0.0"
    major, minor, patch = map(int, match.groups())
    return f"{major}.{minor}.{patch + 1}"


@dataclass
class PromotionPolicy:
    min_observational_samples: int = 10
    require_valid_candidate: bool = True
    require_controlled_experiment: bool = True


class SkillLifecycleManager:
    def __init__(
        self,
        database: str | Path,
        skill_dir: str | Path,
        policy: PromotionPolicy | None = None,
    ):
        self.database = Path(database)
        self.skill_dir = Path(skill_dir)
        self.registry_path = self.skill_dir / "registry.json"
        self.reference_dir = self.skill_dir / "references"
        self.archive_dir = self.skill_dir / "versions"
        self.audit_path = self.skill_dir / "lifecycle_audit.jsonl"
        self.candidates = CandidateRepository(database)
        self.experiments = ExperimentRepository(database)
        self.policy = policy or PromotionPolicy()

    def _registry(self) -> dict[str, Any]:
        if not self.registry_path.is_file():
            return {"schema_version": "1.0", "skill": self.skill_dir.name, "skills": []}
        data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
            raise ValueError(f"invalid registry: {self.registry_path}")
        return data

    def _audit(self, event: str, **payload: Any) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"timestamp": _now(), "event": event, **payload}, ensure_ascii=False) + "\n")

    def check_promotion(self, candidate_id: str, experiment_id: str | None) -> dict[str, Any]:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            return {"eligible": False, "reasons": ["candidate_not_found"]}
        # Re-run validation at release time so a candidate that became a
        # duplicate/conflict after it was mined cannot silently go live.
        validation = CandidateValidator(self.candidates).validate(candidate)
        reasons: list[str] = []
        if self.policy.require_valid_candidate and not validation["valid"]:
            reasons.append("candidate_validation_failed")
        if int((candidate.get("evidence") or {}).get("sample_count", 0)) < self.policy.min_observational_samples:
            reasons.append("insufficient_observational_samples")
        experiment = self.experiments.get(experiment_id) if experiment_id else None
        if self.policy.require_controlled_experiment:
            if not experiment or not experiment.get("report"):
                reasons.append("controlled_experiment_missing")
            elif experiment["candidate_id"] != candidate_id:
                reasons.append("experiment_candidate_mismatch")
            elif experiment["report"].get("decision") != "promote":
                reasons.append(f"experiment_decision_{experiment['report'].get('decision', 'unknown')}")
        return {"eligible": not reasons, "reasons": reasons, "validation": validation, "experiment": experiment}

    def promote(self, candidate_id: str, experiment_id: str | None, *, force: bool = False) -> dict[str, Any]:
        gate = self.check_promotion(candidate_id, experiment_id)
        if not gate["eligible"] and not force:
            raise ValueError("candidate promotion blocked: " + ", ".join(gate["reasons"]))
        candidate = self.candidates.get(candidate_id)
        assert candidate is not None
        registry = self._registry()
        target = candidate["target_skill_id"]
        current = next((item for item in registry["skills"] if item.get("id") == target), None)
        old_version = str(current.get("version", "0.0.0")) if current else "0.0.0"
        new_version = _next_patch(old_version) if current else "1.0.0"
        reference = self.reference_dir / f"{target}.md"
        current_reference_text = reference.read_text(encoding="utf-8") if reference.is_file() else ""

        if current:
            archive = self.archive_dir / target / old_version
            _atomic_json(archive / "definition.json", current)
            if current_reference_text:
                _atomic_text(archive / "reference.md", current_reference_text)

        learned_rule = {
            "version": new_version,
            "conditions": candidate.get("conditions", {}),
            "action": candidate.get("action", {}),
            "source_candidate_id": candidate_id,
            "source_experiment_id": experiment_id,
        }
        if current:
            definition = dict(current)
            definition.update({
                "version": new_version,
                "status": "active",
                "validation_rules": sorted(set(current.get("validation_rules", [])) | set(candidate.get("validation_rules", []))),
                "learned_rules": [*(current.get("learned_rules", []) or []), learned_rule],
                "source_candidate_id": candidate_id,
                "source_experiment_id": experiment_id,
            })
        else:
            definition = {
                "id": target,
                "version": new_version,
                "status": "active",
                "priority": 50,
                "routing_weight": 1.0,
                "applicable_stages": ["planning"],
                "applicable_shot_functions": [],
                "validation_rules": candidate.get("validation_rules", []),
                "description": candidate.get("description", ""),
                "learned_rules": [learned_rule],
                "source_candidate_id": candidate_id,
                "source_experiment_id": experiment_id,
            }
        if current:
            registry["skills"] = [definition if item.get("id") == target else item for item in registry["skills"]]
        else:
            registry["skills"].append(definition)
        _atomic_json(self.registry_path, registry)
        generated = candidate_markdown(candidate)
        if current_reference_text:
            generated = generated.replace(f"# {target}", f"## 数据学习规则 {new_version}", 1)
            generated = current_reference_text.rstrip() + "\n\n---\n\n" + generated
        _atomic_text(reference, generated)
        self.candidates.update_status(
            candidate_id, "promoted", promoted_version=new_version,
            promoted_at=_now(), experiment_id=experiment_id,
        )
        self._audit("promote", candidate_id=candidate_id, skill_id=target, from_version=old_version, to_version=new_version, force=force)
        return {"skill_id": target, "from_version": old_version, "to_version": new_version, "candidate_id": candidate_id}

    def auto_promote_eligible(self) -> list[dict[str, Any]]:
        promoted: list[dict[str, Any]] = []
        for candidate in self.candidates.list(status="needs_experiment"):
            with self.experiments.connect() as db:
                rows = db.execute(
                    "SELECT experiment_id FROM skill_experiments WHERE candidate_id=? AND status='completed' ORDER BY updated_at DESC",
                    (candidate["candidate_id"],),
                ).fetchall()
            for row in rows:
                gate = self.check_promotion(candidate["candidate_id"], row["experiment_id"])
                if gate["eligible"]:
                    promoted.append(self.promote(candidate["candidate_id"], row["experiment_id"]))
                    break
        return promoted

    def rollback(self, skill_id: str, version: str) -> dict[str, Any]:
        archive = self.archive_dir / skill_id / version
        definition_path = archive / "definition.json"
        if not definition_path.is_file():
            raise FileNotFoundError(f"archived Skill version not found: {skill_id}@{version}")
        restored = json.loads(definition_path.read_text(encoding="utf-8"))
        registry = self._registry()
        current = next((item for item in registry["skills"] if item.get("id") == skill_id), None)
        if current:
            current_version = str(current.get("version", "unknown"))
            current_archive = self.archive_dir / skill_id / current_version
            _atomic_json(current_archive / "definition.json", current)
            current_reference = self.reference_dir / f"{skill_id}.md"
            if current_reference.is_file():
                _atomic_text(current_archive / "reference.md", current_reference.read_text(encoding="utf-8"))
            registry["skills"] = [restored if item.get("id") == skill_id else item for item in registry["skills"]]
        else:
            current_version = "missing"
            registry["skills"].append(restored)
        _atomic_json(self.registry_path, registry)
        archived_reference = archive / "reference.md"
        if archived_reference.is_file():
            _atomic_text(self.reference_dir / f"{skill_id}.md", archived_reference.read_text(encoding="utf-8"))
        source_candidate = (current or {}).get("source_candidate_id")
        if source_candidate and self.candidates.get(source_candidate):
            self.candidates.update_status(source_candidate, "rolled_back", rolled_back_at=_now(), rollback_to=version)
        self._audit("rollback", skill_id=skill_id, from_version=current_version, to_version=version)
        return {"skill_id": skill_id, "from_version": current_version, "to_version": version}


class RoutingWeightLearner:
    """Learn conservative weights from accumulated evidence.

    Weights only influence semantic-candidate ordering.  They never disable a
    deterministic Gene rule, so sparse or biased data cannot break the hard
    workflow path.
    """

    def __init__(self, database: str | Path, registry_path: str | Path, min_samples: int = 10):
        self.experiences = ExperienceRepository(database)
        self.experiments = ExperimentRepository(database)
        # Ensures the join target exists even when weight learning is the
        # first lifecycle command executed against a fresh database.
        self.candidates = CandidateRepository(database)
        self.registry_path = Path(registry_path)
        self.min_samples = max(1, min_samples)

    def learn(self) -> dict[str, Any]:
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        updates: dict[str, Any] = {}
        for definition in registry.get("skills", []):
            skill_id = definition.get("id")
            rows = self.experiences.all_decisions(skill_id)
            eligible = [row for row in rows if (row.get("execution") or {}).get("loaded")]
            old = float(definition.get("routing_weight", 1.0))
            if len(eligible) < self.min_samples:
                updates[skill_id] = {"old": old, "new": old, "samples": len(eligible), "reason": "insufficient_samples"}
                continue
            successes = sum(
                bool((row.get("execution") or {}).get("verified"))
                and float((row.get("outcome") or {}).get("quality_score", 0) or 0) >= 70
                for row in eligible
            )
            posterior = (successes + 2) / (len(eligible) + 4)  # Beta(2,2) smoothing
            learned = max(0.5, min(1.5, posterior / 0.5))
            # A completed controlled experiment is stronger than observational
            # evidence, but its influence is capped to keep updates reversible.
            with self.experiments.connect() as db:
                reports = db.execute(
                    "SELECT report_json FROM skill_experiments e JOIN skill_candidates c ON e.candidate_id=c.candidate_id "
                    "WHERE c.target_skill_id=? AND e.status='completed' AND e.report_json IS NOT NULL",
                    (skill_id,),
                ).fetchall()
            for report_row in reports:
                report = json.loads(report_row["report_json"])
                if report.get("decision") == "promote":
                    learned += min(0.2, max(0.0, float(report.get("mean_quality_lift", 0))) / 50)
                elif report.get("decision") == "reject":
                    learned -= 0.15
            learned = round(max(0.5, min(1.5, learned)), 3)
            definition["routing_weight"] = learned
            updates[skill_id] = {"old": old, "new": learned, "samples": len(eligible), "successes": successes}
        _atomic_json(self.registry_path, registry)
        return {"updated_at": _now(), "updates": updates}
