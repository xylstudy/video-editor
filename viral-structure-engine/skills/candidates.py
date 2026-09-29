"""Candidate Skill generation, deduplication and conflict validation."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(conditions: dict[str, Any], action: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical({"conditions": conditions, "action": action}).encode("utf-8")).hexdigest()


def _tokens(value: Any) -> set[str]:
    return set(re.findall(r"[\w\-]+", _canonical(value).lower()))


def _similarity(left: Any, right: Any) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a or b else 1.0


class CandidateRepository:
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
                CREATE TABLE IF NOT EXISTS skill_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    target_skill_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_candidate_status ON skill_candidates(status);
                CREATE INDEX IF NOT EXISTS idx_candidate_target ON skill_candidates(target_skill_id);
                """
            )

    def save(self, candidate: dict[str, Any], validation: dict[str, Any] | None = None) -> None:
        candidate = dict(candidate)
        candidate.setdefault("created_at", _now())
        candidate["updated_at"] = _now()
        fingerprint = candidate.get("fingerprint") or _fingerprint(candidate.get("conditions", {}), candidate.get("action", {}))
        candidate["fingerprint"] = fingerprint
        with self.connect() as db:
            db.execute(
                "INSERT INTO skill_candidates(candidate_id,target_skill_id,status,fingerprint,payload_json,validation_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET "
                "status=excluded.status,payload_json=excluded.payload_json,validation_json=excluded.validation_json,updated_at=excluded.updated_at",
                (
                    candidate["candidate_id"], candidate["target_skill_id"], candidate.get("status", "draft"),
                    fingerprint, _canonical(candidate), _canonical(validation or {}),
                    candidate["created_at"], candidate["updated_at"],
                ),
            )

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT payload_json FROM skill_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        query, params = "SELECT payload_json FROM skill_candidates", ()
        if status:
            query += " WHERE status=?"
            params = (status,)
        query += " ORDER BY updated_at DESC"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def update_status(self, candidate_id: str, status: str, **extra: Any) -> dict[str, Any]:
        candidate = self.get(candidate_id)
        if candidate is None:
            raise KeyError(f"candidate not found: {candidate_id}")
        candidate.update(extra)
        candidate["status"] = status
        self.save(candidate)
        return candidate


class CandidateValidator:
    """Schema, duplicate and same-condition contradiction checks."""

    def __init__(self, repository: CandidateRepository | None = None, duplicate_threshold: float = 0.92):
        self.repository = repository
        self.duplicate_threshold = duplicate_threshold

    def validate(self, candidate: dict[str, Any], others: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        for key in ("candidate_id", "target_skill_id", "description", "conditions", "action", "instructions", "validation_rules", "evidence"):
            if candidate.get(key) in (None, "", [], {}):
                errors.append({"code": "missing_field", "detail": f"缺少必填字段: {key}"})
        if not isinstance(candidate.get("instructions"), list) or not all(isinstance(item, str) and item.strip() for item in candidate.get("instructions", [])):
            errors.append({"code": "invalid_instructions", "detail": "instructions 必须是非空字符串列表"})
        if not isinstance(candidate.get("validation_rules"), list) or not candidate.get("validation_rules"):
            errors.append({"code": "not_verifiable", "detail": "候选 Skill 必须给出至少一条可观察验证规则"})

        peers = list(others if others is not None else (self.repository.list() if self.repository else []))
        fingerprint = candidate.get("fingerprint") or _fingerprint(candidate.get("conditions", {}), candidate.get("action", {}))
        for peer in peers:
            if peer.get("candidate_id") == candidate.get("candidate_id"):
                continue
            peer_fingerprint = peer.get("fingerprint") or _fingerprint(peer.get("conditions", {}), peer.get("action", {}))
            similarity = _similarity(
                {"conditions": candidate.get("conditions"), "action": candidate.get("action")},
                {"conditions": peer.get("conditions"), "action": peer.get("action")},
            )
            if fingerprint == peer_fingerprint or similarity >= self.duplicate_threshold:
                errors.append({"code": "duplicate", "detail": f"与候选 {peer.get('candidate_id')} 重复或高度相似"})
                continue
            same_context = _canonical(candidate.get("conditions", {})) == _canonical(peer.get("conditions", {}))
            if same_context and candidate.get("target_skill_id") == peer.get("target_skill_id") and candidate.get("action") != peer.get("action"):
                warnings.append({
                    "code": "condition_action_conflict",
                    "detail": f"与候选 {peer.get('candidate_id')} 在相同条件下给出不同动作，必须通过 A/B 实验裁决",
                })
        return {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
            "fingerprint": fingerprint,
            "checked_at": _now(),
        }


class CandidateGenerator:
    """Turn a statistically eligible aggregate into an auditable draft."""

    RULES_BY_SKILL = {
        "hook": ["hook_first_shot", "hook_fast_opening", "hook_has_visual_or_caption"],
        "rhythm": ["rhythm_has_variation", "rhythm_climax_present"],
        "transition": ["transition_values_valid", "transition_not_all_identical"],
        "subtitle": ["info_has_text", "subtitle_text_length_valid"],
        "material-matching": ["referenced_material_exists", "functional_adaptation_when_needed"],
        "emotion": ["emotion_labels_present", "emotion_climax_present"],
        "structure-adaptation": ["adaptation_trace"],
    }

    def generate(self, group: dict[str, Any]) -> dict[str, Any]:
        skill_id = str(group["decision_type"])
        conditions = group.get("conditions", {})
        action = group.get("action", {})
        short_hash = hashlib.sha256(_canonical({"skill": skill_id, "conditions": conditions, "action": action}).encode("utf-8")).hexdigest()[:10]
        instructions = [f"当 {key}={value} 时纳入判断。" for key, value in sorted(conditions.items())]
        instructions.extend(f"将 {key} 设置或约束为 {value}。" for key, value in sorted(action.items()))
        candidate = {
            "schema_version": "1.0",
            "candidate_id": f"candidate-{skill_id}-{short_hash}",
            "target_skill_id": skill_id,
            "status": "draft",
            "description": f"从已验证的 {skill_id} 决策经验中归纳的条件化剪辑策略。",
            "conditions": conditions,
            "action": action,
            "instructions": instructions,
            "negative_constraints": ["不满足适用条件时不得机械套用", "不得覆盖用户显式要求或 Gene 硬约束"],
            "validation_rules": self.RULES_BY_SKILL.get(skill_id, ["scheme_action_observable"]),
            "evidence": {
                "group_key": group.get("group_key"),
                "sample_count": group.get("sample_count", 0),
                "run_count": group.get("run_count", 0),
                "verified_rate": group.get("verified_rate"),
                "success_rate": group.get("success_rate"),
                "mean_quality_score": group.get("mean_quality_score"),
                "observational_lift": group.get("observational_lift"),
                "causal_claim": False,
            },
            "created_at": _now(),
        }
        candidate["fingerprint"] = _fingerprint(conditions, action)
        return candidate


def candidate_markdown(candidate: dict[str, Any]) -> str:
    conditions = "\n".join(f"- `{key}` = `{value}`" for key, value in candidate.get("conditions", {}).items()) or "- 无"
    instructions = "\n".join(f"{index}. {text}" for index, text in enumerate(candidate.get("instructions", []), 1))
    constraints = "\n".join(f"- {text}" for text in candidate.get("negative_constraints", []))
    rules = "\n".join(f"- `{rule}`" for rule in candidate.get("validation_rules", []))
    return (
        f"# {candidate.get('target_skill_id')}\n\n{candidate.get('description', '')}\n\n"
        f"## 适用条件\n\n{conditions}\n\n## 执行步骤\n\n{instructions}\n\n"
        f"## 禁止事项\n\n{constraints}\n\n## 可观察验证\n\n{rules}\n"
    )
