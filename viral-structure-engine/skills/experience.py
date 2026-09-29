"""Completed-run experience extraction and SQLite persistence.

The learning store deliberately keeps compact structural/material features,
not user media bytes or absolute media paths.  Every run produces one
``RunExperience`` and zero or more decision-level experiences.  Upserts make
the collector safe to call several times while a run is being finalised.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


logger = logging.getLogger(__name__)
SCHEMA_VERSION = "1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _first_json(run_dir: Path, names: Iterable[str]) -> Any:
    for name in names:
        value = _read_json(run_dir / name)
        if value is not None:
            return value
    return None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_id(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _duration_bucket(value: Any) -> str:
    seconds = _number(value)
    if seconds <= 15:
        return "short_0_15s"
    if seconds <= 45:
        return "medium_16_45s"
    if seconds <= 90:
        return "long_46_90s"
    return "extra_long_90s_plus"


def _material_gene(inventory: dict[str, Any]) -> dict[str, Any]:
    items = inventory.get("items", inventory.get("materials", []))
    items = items if isinstance(items, list) else []
    type_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    motion_count = face_count = landscape_count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        material_type = str(item.get("type") or item.get("media_type") or "unknown").lower()
        type_counts[material_type] = type_counts.get(material_type, 0) + 1
        raw_tags = item.get("tags", [])
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]
        text = " ".join(
            str(item.get(key, "")) for key in ("description", "scene", "subject", "camera_movement")
        ).lower()
        tags = [str(tag).strip().lower() for tag in raw_tags if str(tag).strip()]
        for tag in tags[:12]:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        joined = f"{text} {' '.join(tags)}"
        motion_count += int(any(word in joined for word in ("motion", "moving", "运动", "移动", "航拍")))
        face_count += int(bool(item.get("has_face")) or any(word in joined for word in ("person", "face", "人物", "人像")))
        landscape_count += int(any(word in joined for word in ("landscape", "scenery", "风景", "建筑", "地标")))
    return {
        "count": len(items),
        "type_counts": dict(sorted(type_counts.items())),
        "top_tags": [name for name, _ in sorted(tag_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:12]],
        "has_motion_material": motion_count > 0,
        "has_face_material": face_count > 0,
        "has_landscape_material": landscape_count > 0,
    }


def _gene_summary(gene: dict[str, Any]) -> dict[str, Any]:
    shot_genes = gene.get("shot_genes", []) if isinstance(gene, dict) else []
    functions = [
        str(item.get("function", "")).lower()
        for item in shot_genes if isinstance(item, dict) and item.get("function")
    ]
    return {
        "structure_type": str(gene.get("structure_type", "")),
        "narrative_type": str(gene.get("narrative_type", "")),
        "hook_strategy": str(gene.get("hook_strategy", "")),
        "overall_emotion": str(gene.get("overall_emotion", "")),
        "rhythm_pattern": str(gene.get("rhythm_pattern", "")),
        "shot_functions": functions,
        "shot_count": len(functions),
        "climax_position_bucket": round(_number(gene.get("climax_position_ratio")), 1),
    }


def _scheme_action(skill_id: str, scheme: dict[str, Any]) -> dict[str, Any]:
    frames = [item for item in scheme.get("storyboard", []) if isinstance(item, dict)]
    durations = [_number(item.get("duration")) for item in frames]
    functions = [str(item.get("structure_function") or item.get("shot_type") or "").lower() for item in frames]
    first = frames[0] if frames else {}
    if skill_id == "hook":
        return {
            "opening_material_function": functions[0] if functions else "",
            "first_shot_duration": durations[0] if durations else 0.0,
            "subtitle_in_first_shot": bool(first.get("subtitle_text") or first.get("text_card_content")),
            "bgm_sync_in_first_shot": bool(first.get("bgm_sync")),
        }
    if skill_id == "rhythm":
        return {
            "shot_count": len(frames),
            "mean_shot_duration": round(sum(durations) / len(durations), 2) if durations else 0.0,
            "opening_three_durations": [round(value, 1) for value in durations[:3]],
            "has_duration_variation": len({round(value, 1) for value in durations}) >= 2,
        }
    if skill_id == "transition":
        transitions = [str(item.get("transition_in") or item.get("transition") or "cut") for item in frames]
        return {"transition_sequence": transitions[:12], "transition_types": sorted(set(transitions))}
    if skill_id == "subtitle":
        texts = [str(item.get("subtitle_text") or item.get("text_card_content") or "") for item in frames]
        return {
            "subtitle_frame_count": sum(bool(text) for text in texts),
            "opening_has_subtitle": bool(texts and texts[0]),
            "mean_subtitle_length": round(sum(map(len, filter(None, texts))) / max(1, sum(bool(x) for x in texts)), 1),
        }
    if skill_id == "material-matching":
        return {
            "used_material_count": len({item.get("material_id") or item.get("source_material_id") for item in frames} - {None, ""}),
            "generated_frame_count": sum(bool(item.get("is_generated")) for item in frames),
            "gap_filled_count": sum(bool(item.get("gap_filled") or item.get("fill_strategy")) for item in frames),
        }
    if skill_id == "emotion":
        return {
            "emotion_sequence": [str(item.get("emotion", "")) for item in frames if item.get("emotion")][:12],
            "climax_count": functions.count("climax"),
            "overall_emotion": str(scheme.get("overall_emotion", "")),
        }
    if skill_id == "structure-adaptation":
        return {
            "structure_sequence": functions[:20],
            "adaptation_count": sum(bool(item.get("adaptation")) for item in frames),
            "target_structure_type": str(scheme.get("structure_type", "")),
        }
    return {"structure_sequence": functions[:20], "shot_count": len(frames)}


def _outcome(review: dict[str, Any], render: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    visual = render.get("visual_review", {}) if isinstance(render.get("visual_review"), dict) else {}
    reviewer_score = review.get("total_score")
    run_score = report.get("score")
    quality_score = _number(reviewer_score, _number(run_score, 0.0))
    if 0 < quality_score <= 1:
        quality_score *= 100
    return {
        "quality_score": round(quality_score, 3),
        "reviewer_passed": review.get("pass") is True,
        "run_success": report.get("success") is True,
        "render_status": str(render.get("status", "not_available")),
        "visual_score": visual.get("total_score"),
        "technical_passed": (render.get("technical") or {}).get("passed") if isinstance(render.get("technical"), dict) else None,
    }


class ExperienceExtractor:
    """Build privacy-minimised experiences from one run directory."""

    def extract(self, run_dir: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        run_dir = Path(run_dir)
        run_id = run_dir.name
        run_info = _first_json(run_dir, ("run_info.json",)) or {}
        summary = _first_json(run_dir, ("pipeline_summary.json",)) or {}
        scheme = _first_json(run_dir, ("planner/scheme_final.json", "planner/scheme.json", "planner/scheme_v0.json")) or {}
        gene = _first_json(run_dir, ("analyst/gene.json", "analyst/structure_gene.json")) or {}
        inventory = _first_json(run_dir, ("material/inventory.json",)) or {}
        trace = _first_json(run_dir, ("evaluation/skill_evaluation.json",)) or scheme.get("skill_evaluation", {}) or {}
        review = _first_json(run_dir, ("reviewer/review_result.json",)) or summary.get("review_result", {}) or {}
        render = _first_json(run_dir, ("render_reviewer/render_review.json",)) or {}
        report = _first_json(run_dir, ("evaluation/report.json",)) or {}
        source_timestamp = str(run_info.get("timestamp") or summary.get("timestamp") or "")
        conditions = {
            "video_type": str(scheme.get("target_category") or run_info.get("video_type") or "vlog"),
            "target_platform": str(scheme.get("target_platform", "")),
            "target_duration_bucket": _duration_bucket(scheme.get("target_duration")),
            "gene": _gene_summary(gene),
            "material_gene": _material_gene(inventory if isinstance(inventory, dict) else {}),
        }
        outcomes = _outcome(review if isinstance(review, dict) else {}, render if isinstance(render, dict) else {}, report if isinstance(report, dict) else {})
        run_experience = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "captured_at": source_timestamp,
            "status": str(summary.get("status") or ("completed" if report.get("success") else "unknown")),
            "conditions": conditions,
            "outcome": outcomes,
            "skill_ids": list(trace.get("selected_skill_refs", [])) if isinstance(trace, dict) else [],
            "privacy": "structural_features_only_no_media_bytes_or_absolute_paths",
        }
        verification_by_id = {
            str(item.get("skill_id")): item
            for item in trace.get("verification", []) if isinstance(item, dict) and item.get("skill_id")
        } if isinstance(trace, dict) else {}
        selected = set(trace.get("selected_skill_refs", [])) if isinstance(trace, dict) else set()
        loaded = set(trace.get("loaded_skill_refs", [])) if isinstance(trace, dict) else set()
        declared = set(trace.get("declared_skill_refs", [])) if isinstance(trace, dict) else set()
        verified = set(trace.get("verified_skill_refs", [])) if isinstance(trace, dict) else set()
        decisions: list[dict[str, Any]] = []
        for route in trace.get("route_decisions", []) if isinstance(trace, dict) else []:
            if not isinstance(route, dict) or not route.get("skill_id"):
                continue
            skill_id = str(route["skill_id"])
            decision = {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "skill_id": skill_id,
                "skill_version": str(route.get("skill_version", "unregistered")),
                "decision_type": skill_id,
                "conditions": conditions,
                "action": _scheme_action(skill_id, scheme if isinstance(scheme, dict) else {}),
                "execution": {
                    "selected": skill_id in selected,
                    "loaded": skill_id in loaded,
                    "declared": skill_id in declared,
                    "verified": skill_id in verified,
                    "verification_status": verification_by_id.get(skill_id, {}).get("status", "unknown"),
                    "compliance_score": verification_by_id.get(skill_id, {}).get("compliance_score"),
                },
                "outcome": outcomes,
                "route_evidence": {
                    "selected_by": route.get("selected_by", "unknown"),
                    "triggers": route.get("triggers", []),
                },
                "captured_at": source_timestamp,
            }
            # Stable across draft/final refreshes.  The same run/Skill row is
            # updated as more evidence arrives instead of becoming two fake
            # independent samples merely because the user edited the scheme.
            decision["experience_id"] = _stable_id("decision", {"run_id": run_id, "skill_id": skill_id})
            decisions.append(decision)
        return run_experience, decisions


class ExperienceRepository:
    """SQLite store used by extraction, incremental mining and weight learning."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _init_schema(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS run_experiences (
                    run_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decision_experiences (
                    experience_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    decision_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    normalized_json TEXT,
                    mining_status TEXT NOT NULL DEFAULT 'pending',
                    rejection_reason TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_decision_mining_status ON decision_experiences(mining_status);
                CREATE INDEX IF NOT EXISTS idx_decision_skill ON decision_experiences(skill_id);
                """
            )

    def upsert(self, run: dict[str, Any], decisions: Iterable[dict[str, Any]]) -> None:
        now = _now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO run_experiences(run_id,payload_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                (run["run_id"], _canonical(run), now),
            )
            for item in decisions:
                db.execute(
                    "INSERT INTO decision_experiences(experience_id,run_id,skill_id,decision_type,payload_json,updated_at) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(experience_id) DO UPDATE SET "
                    "payload_json=excluded.payload_json,updated_at=excluded.updated_at,"
                    "normalized_json=CASE WHEN decision_experiences.payload_json=excluded.payload_json THEN decision_experiences.normalized_json ELSE NULL END,"
                    "mining_status=CASE WHEN decision_experiences.payload_json=excluded.payload_json THEN decision_experiences.mining_status ELSE 'pending' END,"
                    "rejection_reason=CASE WHEN decision_experiences.payload_json=excluded.payload_json THEN decision_experiences.rejection_reason ELSE '' END",
                    (item["experience_id"], item["run_id"], item["skill_id"], item["decision_type"], _canonical(item), now),
                )

    def pending(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload_json FROM decision_experiences WHERE mining_status='pending' ORDER BY updated_at LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def mark_mined(self, experience_id: str, normalized: dict[str, Any], status: str = "mined", reason: str = "") -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE decision_experiences SET normalized_json=?,mining_status=?,rejection_reason=?,updated_at=? WHERE experience_id=?",
                (_canonical(normalized), status, reason, _now(), experience_id),
            )

    def all_decisions(self, skill_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT payload_json FROM decision_experiences"
        params: tuple[Any, ...] = ()
        if skill_id:
            query += " WHERE skill_id=?"
            params = (skill_id,)
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


def capture_run_experiences(run_dir: str | Path, db_path: str | Path | None = None) -> dict[str, Any]:
    """Extract, persist and export inspectable per-run experience artifacts."""
    run_dir = Path(run_dir)
    run, decisions = ExperienceExtractor().extract(run_dir)
    experience_dir = run_dir / "experience"
    experience_dir.mkdir(parents=True, exist_ok=True)
    (experience_dir / "run_experience.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (experience_dir / "decision_experiences.json").write_text(
        json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    repository = ExperienceRepository(db_path or run_dir.parent / "skill_experiences.sqlite3")
    repository.upsert(run, decisions)
    return {"run_id": run["run_id"], "decision_count": len(decisions), "database": str(repository.path)}


def safe_capture_run_experiences(run_dir: str | Path, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Best-effort hook: learning must never make the production run fail."""
    try:
        return capture_run_experiences(run_dir, db_path=db_path)
    except Exception:
        logger.exception("Skill experience capture failed for %s", run_dir)
        return None
