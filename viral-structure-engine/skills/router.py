"""Skill 路由 — 渐进式披露的剪辑知识加载器。

职责边界（与 Gene 严格区分）：
  Gene  当前参考视频专属，决定"迁移什么结构"，硬约束为主。
  Skill 跨任务长期复用，帮助 Planner 判断"在用户素材条件下怎么把结构剪好"，软策略为主。

优先级：用户显式要求 > Reference Gene > Editing Skill > 模型自由发挥。

本模块提供：
  - 确定性场景触发（stage / shot function → reference 文件），无需 LLM，可单测。
  - LLM 语义补充（route_hybrid），只增加候选，不能覆盖确定性结果。
  - LLM 调用失败时自动降级为纯确定性路由。
  - references/*.md 的按需加载。

暂不引入 RAG / 向量库 / 复杂检索。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from skills.registry import SkillDefinition, SkillRegistry

SKILLS_ROOT = Path(__file__).resolve().parent


@dataclass
class SkillReference:
    """一个已加载的 reference 文件。"""
    name: str
    content: str

    def to_dict(self) -> dict:
        return {"name": self.name, "content": self.content}


@dataclass
class SkillRouteDecision:
    """One auditable Skill-routing decision for a planning run."""

    skill_id: str
    version: str = "unregistered"
    selected: bool = True
    selected_by: str = "deterministic_rule"
    triggers: list[str] = field(default_factory=list)
    priority: int = 0
    routing_weight: float = 1.0

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "skill_version": self.version,
            "selected": self.selected,
            "selected_by": self.selected_by,
            "triggers": list(self.triggers),
            "priority": self.priority,
            "routing_weight": self.routing_weight,
        }


@dataclass
class SkillPlan:
    """一次规划任务要加载哪些 reference，以及为什么。"""
    skill: str = "video-editing"
    references: list[str] = field(default_factory=list)
    triggers: dict = field(default_factory=dict)  # ref name -> 触发原因
    decisions: list[SkillRouteDecision] = field(default_factory=list)
    routing_mode: str = "deterministic"
    semantic_routing_attempted: bool = False
    semantic_routing_error: str = ""

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "references": self.references,
            "triggers": self.triggers,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "routing_mode": self.routing_mode,
            "semantic_routing_attempted": self.semantic_routing_attempted,
            "semantic_routing_error": self.semantic_routing_error,
        }


class SkillRouter:
    """确定性场景路由 + reference 按需加载。"""

    # 规划阶段 → reference 文件名（不含 .md）
    STAGE_TO_REFS: dict[str, list[str]] = {
        "hook": ["hook"],
        "opening": ["hook"],
        "rhythm": ["rhythm"],
        "pacing": ["rhythm"],
        "transition": ["transition"],
        "emotion": ["emotion"],
        "material_matching": ["material-matching"],
        "material": ["material-matching"],
        "structure_adaptation": ["structure-adaptation"],
        "adaptation": ["structure-adaptation"],
        "subtitle": ["subtitle"],
        "packaging": ["subtitle"],
    }

    # 镜头功能 → reference（结构功能触发）
    SHOT_FUNCTION_TO_REFS: dict[str, list[str]] = {
        "hook": ["hook"],
        "establishing": ["material-matching", "structure-adaptation"],
        "scene_establish": ["material-matching", "structure-adaptation"],
        "climax": ["emotion", "rhythm"],
        "emotion_peak": ["emotion", "rhythm"],
        "transition": ["transition"],
        "closing": ["emotion", "subtitle"],
        "info": ["subtitle"],
        "persona": ["emotion"],
        "daily_moment": ["rhythm", "emotion"],
    }

    def __init__(self, skill: str = "video-editing", root: Optional[Path] = None):
        self.skill = skill
        self.skill_dir = (root or SKILLS_ROOT) / skill
        self._ref_cache: dict[str, str] = {}
        self._last_semantic_error = ""
        self.registry = SkillRegistry(skill=skill, root=root)

    def _definition(self, name: str) -> SkillDefinition | None:
        return self.registry.get(name[:-3] if name.endswith(".md") else name)

    def _is_routable(self, name: str) -> bool:
        """Respect explicitly inactive registry entries.

        A missing registry entry remains routable for backward compatibility
        with custom Skill directories, but is labelled ``unregistered`` in the
        trace rather than silently pretending to be versioned.
        """
        definition = self._definition(name)
        return definition is None or definition.status == "active"

    # ---- reference 文件操作 ----

    def reference_path(self, name: str) -> Path:
        # 允许传 "hook" 或 "hook.md"
        name = name[:-3] if name.endswith(".md") else name
        return self.skill_dir / "references" / f"{name}.md"

    def list_references(self) -> list[str]:
        ref_dir = self.skill_dir / "references"
        if not ref_dir.exists():
            return []
        return sorted(p.stem for p in ref_dir.glob("*.md"))

    def load_reference(self, name: str) -> str:
        name = name[:-3] if name.endswith(".md") else name
        if name not in self._ref_cache:
            p = self.reference_path(name)
            self._ref_cache[name] = p.read_text(encoding="utf-8") if p.exists() else ""
        return self._ref_cache[name]

    def load_skill_meta(self) -> dict:
        """解析 SKILL.md 的轻量元信息（名称 / 定位 / 使用时机 / 路由规则）。"""
        p = self.skill_dir / "SKILL.md"
        if not p.exists():
            return {"skill": self.skill, "name": self.skill, "description": "", "references": self.list_references()}
        text = p.read_text(encoding="utf-8")
        meta: dict = {"skill": self.skill, "references": self.list_references()}
        # 简单的 frontmatter（name: / description: / when_to_use: / priority:）
        for key in ("name", "description", "when_to_use", "priority"):
            m = re.search(rf"^{key}:\s*(.+)$", text, flags=re.MULTILINE)
            if m:
                meta[key] = m.group(1).strip()
        return meta

    # ---- 确定性路由 ----

    def route_for_stage(self, stage: str) -> list[str]:
        """按规划阶段确定要加载的 reference。"""
        return [reference for reference in self.STAGE_TO_REFS.get(stage, []) if self._is_routable(reference)]

    def route_for_shot(self, shot_function: str) -> list[str]:
        """按镜头结构功能确定要加载的 reference。"""
        references = self.SHOT_FUNCTION_TO_REFS.get(shot_function, ["rhythm", "emotion"])
        return [reference for reference in references if self._is_routable(reference)]

    def _add_reference(
        self,
        plan: SkillPlan,
        reference: str,
        trigger: str,
        selected_by: str,
    ) -> None:
        """Add one auditable decision while preserving all route evidence."""
        reference = reference[:-3] if reference.endswith(".md") else reference
        if not self._is_routable(reference):
            return

        existing = next(
            (decision for decision in plan.decisions if decision.skill_id == reference),
            None,
        )
        if existing is None:
            definition = self._definition(reference)
            plan.references.append(reference)
            plan.decisions.append(SkillRouteDecision(
                skill_id=reference,
                version=definition.version if definition else "unregistered",
                selected_by=selected_by,
                triggers=[trigger] if trigger else [],
                priority=definition.priority if definition else 0,
                routing_weight=definition.routing_weight if definition else 1.0,
            ))
            plan.triggers[reference] = trigger
            return

        if trigger and trigger not in existing.triggers:
            existing.triggers.append(trigger)
        route_sources = existing.selected_by.split("+") if existing.selected_by else []
        if selected_by and selected_by not in route_sources:
            route_sources.append(selected_by)
            existing.selected_by = "+".join(route_sources)
        plan.triggers[reference] = "；".join(existing.triggers)

    def route_for_genes(self, genes: Iterable) -> SkillPlan:
        """Merge deterministic decisions for one or more reference Genes."""
        merged = SkillPlan(skill=self.skill)
        for gene in genes:
            current = self.route_for_gene(gene)
            for decision in current.decisions:
                triggers = decision.triggers or [current.triggers.get(decision.skill_id, "")]
                for trigger in triggers:
                    self._add_reference(
                        merged,
                        decision.skill_id,
                        trigger,
                        decision.selected_by,
                    )
        return merged

    def route_for_gene(self, gene) -> SkillPlan:
        """给定 StructureGene，确定性汇总需要加载的 reference。"""
        plan = SkillPlan(skill=self.skill)

        # 结构迁移必然涉及适配；保持它在列表首位，便于 Prompt 解释优先级。
        self._add_reference(
            plan,
            "structure-adaptation",
            "结构迁移默认需要把 Gene 适配到用户素材",
            "deterministic_rule",
        )

        functions = set()
        shot_genes = getattr(gene, "shot_genes", []) or []
        for g in shot_genes:
            fn = getattr(g, "function", "")
            if fn:
                functions.add(fn)

        for fn in sorted(functions):
            refs = self.route_for_shot(fn)
            for r in refs:
                self._add_reference(
                    plan,
                    r,
                    f"Gene 含 {fn} 镜头功能",
                    "deterministic_rule",
                )

        # 存在 establishing 类功能 → 强制 material-matching（功能级素材迁移）
        if any(f in ("establishing", "scene_establish") for f in functions):
            self._add_reference(
                plan,
                "material-matching",
                "存在场景建立镜头，需功能级素材匹配",
                "deterministic_rule",
            )

        return plan

    async def route_hybrid(self, genes, context: str, llm) -> SkillPlan:
        """Combine mandatory deterministic routing with semantic additions.

        The semantic route may only add active references.  It cannot remove
        or override a Gene-driven decision, so an LLM failure safely degrades
        to the deterministic plan.
        """
        gene_list = list(genes) if isinstance(genes, (list, tuple)) else [genes]
        plan = self.route_for_genes(gene for gene in gene_list if gene is not None)
        if llm is None or not context.strip():
            return plan

        plan.semantic_routing_attempted = True
        semantic_context = (
            f"{context.strip()}\n\n"
            f"确定性规则已经选择：{', '.join(plan.references) or '无'}。"
            "语义路由只能补充确有必要的 Skill，不要为了覆盖全部能力而多选。"
        )
        semantic_refs = await self.route_by_llm(semantic_context, llm)
        if self._last_semantic_error:
            plan.routing_mode = "hybrid_fallback_deterministic"
            plan.semantic_routing_error = self._last_semantic_error
            return plan

        plan.routing_mode = "hybrid"
        for reference in semantic_refs:
            self._add_reference(
                plan,
                reference,
                "LLM 根据用户需求、Gene 与素材上下文判断相关",
                "llm_semantic",
            )
        return plan

    def collect(self, names: list[str]) -> list[SkillReference]:
        """批量加载 reference，返回 [{name, content}]。"""
        out: list[SkillReference] = []
        seen = set()
        for n in names:
            key = n[:-3] if n.endswith(".md") else n
            if key in seen:
                continue
            if not self._is_routable(key):
                continue
            seen.add(key)
            out.append(SkillReference(name=key, content=self.load_reference(key)))
        return out

    # ---- LLM 语义补充（混合路由第二层）----

    async def route_by_llm(self, context: str, llm) -> list[str]:
        """用 Registry 描述和任务上下文判断要补充哪些 reference。"""
        available = [name for name in self.list_references() if self._is_routable(name)]
        # Learned weights are a soft semantic-routing preference only.  Gene
        # rules have already run and cannot be removed by this ordering.
        available.sort(
            key=lambda name: (
                -((self._definition(name).priority if self._definition(name) else 0)
                  * (self._definition(name).routing_weight if self._definition(name) else 1.0)),
                name,
            )
        )
        descriptions = []
        for name in available:
            definition = self._definition(name)
            description = definition.description if definition else ""
            weight = definition.routing_weight if definition else 1.0
            descriptions.append(f"- {name} [routing_weight={weight:.3f}]: {description}")
        prompt = (
            "你是剪辑知识路由助手。根据用户目标、Reference Gene 和素材摘要，"
            "从下列 Skill 元数据中选择确实相关的一项或多项。"
            "只返回 Skill ID，使用英文逗号分隔；没有需要补充的则返回 NONE，"
            "不要解释，不要选择列表外的 ID。\n\n"
            f"可选 Skill：\n{chr(10).join(descriptions)}\n\n当前上下文：\n{context}"
        )
        self._last_semantic_error = ""
        try:
            # Reasoning-capable providers may spend their token budget before
            # emitting the tiny final ID list. Starting at 128 caused several
            # duplicate requests through the client's length retry ladder.
            resp = await llm.chat(prompt, temperature=0.0, max_tokens=4096)
            if not isinstance(resp, str) or resp.strip().upper() == "NONE":
                return []
            # Providers occasionally wrap the requested IDs in JSON, bullets,
            # or code fences. Match only known IDs and preserve catalog order.
            return [
                name for name in available
                if re.search(rf"(?<![\w-]){re.escape(name)}(?:\.md)?(?![\w-])", resp)
            ]
        except Exception as exc:
            self._last_semantic_error = f"{type(exc).__name__}: {exc}"
            return []
