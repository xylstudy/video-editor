"""Machine-readable Editing Skill registry.

Markdown references contain the human-readable guidance.  This module keeps
the routing, version and verification contract separate so a run can explain
which version of a Skill was selected and why.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SKILLS_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class SkillDefinition:
    """A versioned, machine-readable contract for one Skill reference."""

    id: str
    version: str = "1.0.0"
    status: str = "active"
    priority: int = 0
    routing_weight: float = 1.0
    applicable_stages: tuple[str, ...] = ()
    applicable_shot_functions: tuple[str, ...] = ()
    validation_rules: tuple[str, ...] = ()
    description: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SkillDefinition":
        return cls(
            id=str(value.get("id", "")).strip(),
            version=str(value.get("version", "1.0.0")).strip() or "1.0.0",
            status=str(value.get("status", "active")).strip() or "active",
            priority=int(value.get("priority", 0) or 0),
            routing_weight=float(value.get("routing_weight", 1.0) or 1.0),
            applicable_stages=tuple(str(x) for x in value.get("applicable_stages", []) if str(x).strip()),
            applicable_shot_functions=tuple(
                str(x) for x in value.get("applicable_shot_functions", []) if str(x).strip()
            ),
            validation_rules=tuple(str(x) for x in value.get("validation_rules", []) if str(x).strip()),
            description=str(value.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "status": self.status,
            "priority": self.priority,
            "routing_weight": self.routing_weight,
            "applicable_stages": list(self.applicable_stages),
            "applicable_shot_functions": list(self.applicable_shot_functions),
            "validation_rules": list(self.validation_rules),
            "description": self.description,
        }


class SkillRegistry:
    """Loads the local registry without making routing dependent on an LLM."""

    def __init__(self, skill: str = "video-editing", root: Path | None = None):
        self.skill = skill
        self.skill_dir = (root or SKILLS_ROOT) / skill
        self.path = self.skill_dir / "registry.json"
        self._definitions = self._load()

    def _load(self) -> dict[str, SkillDefinition]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid Skill registry: {self.path} ({exc})") from exc
        items = data.get("skills", []) if isinstance(data, dict) else []
        definitions: dict[str, SkillDefinition] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            definition = SkillDefinition.from_dict(item)
            if not definition.id:
                continue
            if definition.id in definitions:
                raise ValueError(f"duplicate Skill id in registry: {definition.id}")
            definitions[definition.id] = definition
        return definitions

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self._definitions.get(skill_id)

    def is_active(self, skill_id: str) -> bool:
        definition = self.get(skill_id)
        return definition is not None and definition.status == "active"

    def active_ids(self) -> list[str]:
        return [skill_id for skill_id, definition in self._definitions.items() if definition.status == "active"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "definitions": [definition.to_dict() for definition in self._definitions.values()],
        }
