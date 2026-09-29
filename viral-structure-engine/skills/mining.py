"""Normalisation and incremental mining of decision experiences."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from skills.candidates import CandidateGenerator, CandidateRepository, CandidateValidator
from skills.experience import ExperienceRepository


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _group_key(decision_type: str, conditions: dict[str, Any], action: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical([decision_type, conditions, action]).encode("utf-8")).hexdigest()[:20]
    return f"group_{digest}"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ExperienceNormalizer:
    """Reduce noisy run details into reusable condition/action signatures."""

    ALIASES = {
        "travel vlog": "travel_vlog", "旅行vlog": "travel_vlog", "旅游vlog": "travel_vlog",
        "douyin": "抖音", "tiktok": "抖音", "人物": "person", "人像": "person",
    }

    @classmethod
    def _text(cls, value: Any) -> str:
        text = str(value or "").strip().lower()
        return cls.ALIASES.get(text, text)

    @staticmethod
    def _bucket_number(key: str, value: float) -> Any:
        if "duration" in key:
            if value <= 1.5:
                return "very_short"
            if value <= 3:
                return "short"
            if value <= 6:
                return "medium"
            return "long"
        if "score" in key:
            return round(value / 5) * 5
        return round(value, 1)

    def _normalise_value(self, key: str, value: Any) -> Any:
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, (int, float)):
            return self._bucket_number(key, float(value))
        if isinstance(value, str):
            return self._text(value)
        if isinstance(value, list):
            normalised = [self._normalise_value(key, item) for item in value[:20]]
            return normalised if "sequence" in key or "opening" in key else sorted(set(map(str, normalised)))
        if isinstance(value, dict):
            return {str(k): self._normalise_value(str(k), v) for k, v in sorted(value.items())}
        return str(value)

    def normalize(self, experience: dict[str, Any]) -> dict[str, Any]:
        raw_conditions = experience.get("conditions", {})
        gene = raw_conditions.get("gene", {}) if isinstance(raw_conditions, dict) else {}
        material = raw_conditions.get("material_gene", {}) if isinstance(raw_conditions, dict) else {}
        # Do not use topic, run id or material ids.  These features should
        # describe a reusable situation rather than memorise one project.
        conditions = {
            "video_type": self._text(raw_conditions.get("video_type", "")),
            "target_platform": self._text(raw_conditions.get("target_platform", "")),
            "target_duration_bucket": self._text(raw_conditions.get("target_duration_bucket", "")),
            "structure_type": self._text(gene.get("structure_type", "")),
            "hook_strategy": self._text(gene.get("hook_strategy", "")),
            "rhythm_pattern": self._text(gene.get("rhythm_pattern", "")),
            "shot_functions": sorted(set(self._text(item) for item in gene.get("shot_functions", []) if item)),
            "has_motion_material": bool(material.get("has_motion_material")),
            "has_face_material": bool(material.get("has_face_material")),
            "has_landscape_material": bool(material.get("has_landscape_material")),
            "material_count_bucket": "few" if _number(material.get("count")) < 5 else "medium" if _number(material.get("count")) < 15 else "many",
        }
        conditions = {key: value for key, value in conditions.items() if value not in ("", [], None)}
        action = {
            str(key): self._normalise_value(str(key), value)
            for key, value in sorted((experience.get("action") or {}).items())
        }
        outcome = experience.get("outcome", {})
        execution = experience.get("execution", {})
        return {
            "experience_id": experience.get("experience_id"),
            "run_id": experience.get("run_id"),
            "skill_id": experience.get("skill_id"),
            "decision_type": experience.get("decision_type"),
            "conditions": conditions,
            "action": action,
            "quality_score": _number(outcome.get("quality_score")),
            "success": bool(outcome.get("reviewer_passed") or outcome.get("run_success")),
            "verified": bool(execution.get("verified")),
            "compliance_score": _number(execution.get("compliance_score")),
        }


class IncrementalSkillMiner:
    """Process only new/changed experiences, then materialise group statistics."""

    def __init__(
        self,
        database: str | Path,
        *,
        min_samples: int = 10,
        min_verified_rate: float = 0.7,
        min_success_rate: float = 0.6,
        min_quality_score: float = 70.0,
    ):
        self.experiences = ExperienceRepository(database)
        self.candidates = CandidateRepository(database)
        self.normalizer = ExperienceNormalizer()
        self.min_samples = max(1, min_samples)
        self.min_verified_rate = min_verified_rate
        self.min_success_rate = min_success_rate
        self.min_quality_score = min_quality_score
        self._init_schema()

    def _init_schema(self) -> None:
        with self.experiences.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS experience_groups (
                    group_key TEXT PRIMARY KEY,
                    decision_type TEXT NOT NULL,
                    conditions_json TEXT NOT NULL,
                    action_json TEXT NOT NULL,
                    sample_count INTEGER NOT NULL,
                    run_count INTEGER NOT NULL,
                    verified_rate REAL NOT NULL,
                    success_rate REAL NOT NULL,
                    mean_quality_score REAL NOT NULL,
                    observational_lift REAL,
                    member_ids_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    @staticmethod
    def _reject_reason(experience: dict[str, Any]) -> str:
        execution = experience.get("execution", {})
        if not execution.get("selected"):
            return "not_selected"
        if not execution.get("loaded"):
            return "not_loaded"
        if not execution.get("declared"):
            return "not_declared"
        if not execution.get("verified"):
            return "not_verified"
        if not experience.get("action"):
            return "empty_action"
        if _number((experience.get("outcome") or {}).get("quality_score")) <= 0:
            return "missing_quality_outcome"
        return ""

    def process_pending(self, limit: int = 1000) -> dict[str, Any]:
        pending = self.experiences.pending(limit=limit)
        accepted = rejected = 0
        reasons: dict[str, int] = defaultdict(int)
        for experience in pending:
            reason = self._reject_reason(experience)
            normalised = self.normalizer.normalize(experience)
            if reason:
                rejected += 1
                reasons[reason] += 1
                self.experiences.mark_mined(experience["experience_id"], normalised, status="rejected", reason=reason)
            else:
                accepted += 1
                self.experiences.mark_mined(experience["experience_id"], normalised)
        groups = self._rebuild_groups()
        candidates = self._generate_candidates(groups)
        return {
            "pending_processed": len(pending),
            "accepted": accepted,
            "rejected": rejected,
            "rejection_reasons": dict(reasons),
            "group_count": len(groups),
            "candidates_created": candidates,
        }

    def _normalised_rows(self) -> list[dict[str, Any]]:
        with self.experiences.connect() as db:
            rows = db.execute(
                "SELECT normalized_json FROM decision_experiences WHERE mining_status='mined' AND normalized_json IS NOT NULL"
            ).fetchall()
        return [json.loads(row["normalized_json"]) for row in rows]

    def _rebuild_groups(self) -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        metadata: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {}
        for row in self._normalised_rows():
            key = _group_key(row["decision_type"], row["conditions"], row["action"])
            buckets[key].append(row)
            metadata[key] = (row["decision_type"], row["conditions"], row["action"])

        groups: list[dict[str, Any]] = []
        for key, members in buckets.items():
            decision_type, conditions, action = metadata[key]
            qualities = [row["quality_score"] for row in members]
            groups.append({
                "group_key": key,
                "decision_type": decision_type,
                "conditions": conditions,
                "action": action,
                "sample_count": len(members),
                "run_count": len({row["run_id"] for row in members}),
                "verified_rate": sum(bool(row["verified"]) for row in members) / len(members),
                "success_rate": sum(bool(row["success"]) for row in members) / len(members),
                "mean_quality_score": sum(qualities) / len(qualities),
                "member_ids": [row["experience_id"] for row in members],
            })

        # Observational comparison is useful for discovery, but is explicitly
        # not treated as causal evidence for promotion.
        context_buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for group in groups:
            context_buckets[(group["decision_type"], _canonical(group["conditions"]))].append(group)
        for peers in context_buckets.values():
            for group in peers:
                other = [item for item in peers if item["group_key"] != group["group_key"]]
                if other:
                    total = sum(item["sample_count"] for item in other)
                    baseline = sum(item["mean_quality_score"] * item["sample_count"] for item in other) / total
                    group["observational_lift"] = round(group["mean_quality_score"] - baseline, 3)
                else:
                    group["observational_lift"] = None

        with self.experiences.connect() as db:
            db.execute("DELETE FROM experience_groups")
            for group in groups:
                db.execute(
                    "INSERT INTO experience_groups(group_key,decision_type,conditions_json,action_json,sample_count,run_count,"
                    "verified_rate,success_rate,mean_quality_score,observational_lift,member_ids_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        group["group_key"], group["decision_type"], _canonical(group["conditions"]), _canonical(group["action"]),
                        group["sample_count"], group["run_count"], group["verified_rate"], group["success_rate"],
                        group["mean_quality_score"], group["observational_lift"], _canonical(group["member_ids"]),
                    ),
                )
        return groups

    def _eligible(self, group: dict[str, Any]) -> bool:
        return (
            group["sample_count"] >= self.min_samples
            and group["run_count"] >= min(3, self.min_samples)
            and group["verified_rate"] >= self.min_verified_rate
            and group["success_rate"] >= self.min_success_rate
            and group["mean_quality_score"] >= self.min_quality_score
        )

    def _generate_candidates(self, groups: list[dict[str, Any]]) -> list[str]:
        generator = CandidateGenerator()
        created: list[str] = []
        # Only the strongest observed action for one condition becomes a
        # candidate; alternatives stay as evidence for a later A/B test.
        best: dict[tuple[str, str], dict[str, Any]] = {}
        for group in groups:
            if not self._eligible(group):
                continue
            key = (group["decision_type"], _canonical(group["conditions"]))
            if key not in best or group["mean_quality_score"] > best[key]["mean_quality_score"]:
                best[key] = group
        for group in best.values():
            candidate = generator.generate(group)
            existing = self.candidates.get(candidate["candidate_id"])
            validation = CandidateValidator(self.candidates).validate(candidate)
            if not validation["valid"] and not existing:
                continue
            candidate["status"] = "needs_experiment" if validation["valid"] else existing.get("status", "draft")
            candidate["validation"] = validation
            self.candidates.save(candidate, validation)
            created.append(candidate["candidate_id"])
        return created

    def groups(self) -> list[dict[str, Any]]:
        with self.experiences.connect() as db:
            rows = db.execute("SELECT * FROM experience_groups ORDER BY sample_count DESC, group_key").fetchall()
        return [{
            "group_key": row["group_key"], "decision_type": row["decision_type"],
            "conditions": json.loads(row["conditions_json"]), "action": json.loads(row["action_json"]),
            "sample_count": row["sample_count"], "run_count": row["run_count"],
            "verified_rate": row["verified_rate"], "success_rate": row["success_rate"],
            "mean_quality_score": row["mean_quality_score"], "observational_lift": row["observational_lift"],
        } for row in rows]
