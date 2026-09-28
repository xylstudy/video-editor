import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills.router import SkillRouter, SkillReference
from skills.analytics import aggregate_skill_evaluations
from skills.registry import SkillRegistry
from skills.verifier import verify_skill_usage
from models.gene import ShotGene, StructureGene
from prompts.planner_prompts import build_scheme_generate_prompt, _format_skill_context
from prompts.reviewer_prompts import build_review_prompt


def _gene_with_functions(*functions):
    return StructureGene(source_id="v1", shot_genes=[
        ShotGene(index=i, function=f) for i, f in enumerate(functions)
    ])


class _FakeSemanticLLM:
    def __init__(self, response="NONE", error=None):
        self.response = response
        self.error = error
        self.prompts = []

    async def chat(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.response


def test_stage_routing_hook_only():
    """Case 2：规划 hook 阶段时，只加载 hook.md，不加载 transition/subtitle。"""
    router = SkillRouter()
    assert router.route_for_stage("hook") == ["hook"]
    assert "transition" not in router.route_for_stage("hook")
    assert "subtitle" not in router.route_for_stage("hook")


def test_stage_routing_transition():
    router = SkillRouter()
    assert router.route_for_stage("transition") == ["transition"]


def test_gene_routing_hook_only():
    """Case 2：Gene 只含 hook 时，只加载 structure-adaptation + hook，不带转场/字幕。"""
    router = SkillRouter()
    plan = router.route_for_gene(_gene_with_functions("hook"))
    assert plan.references[0] == "structure-adaptation"  # 结构迁移必然适配
    assert "hook" in plan.references
    assert "transition" not in plan.references
    assert "subtitle" not in plan.references


def test_gene_routing_establishing_material_matching():
    """Case 3：存在 establishing 镜头 → 强制加载 material-matching（功能级素材迁移）。"""
    router = SkillRouter()
    plan = router.route_for_gene(_gene_with_functions("establishing", "climax"))
    assert "material-matching" in plan.references
    assert "structure-adaptation" in plan.references
    assert "emotion" in plan.references  # climax 触发情绪
    assert "rhythm" in plan.references   # climax 触发节奏


def test_reference_content_loaded():
    router = SkillRouter()
    hook = router.load_reference("hook")
    assert hook  # 非空
    # 每个 reference 都有 适用条件 / 不适用条件 / 推荐策略
    assert "适用" in hook or "不适用" in hook or "推荐" in hook


def test_skill_meta_priority():
    """Case 4：Skill 元信息声明了优先级，Gene 高于 Skill。"""
    router = SkillRouter()
    meta = router.load_skill_meta()
    assert "Gene" in meta.get("priority", "")
    assert "Skill" in meta.get("priority", "")


def test_registry_versions_and_route_decisions():
    registry = SkillRegistry()
    assert registry.get("hook").version == "1.0.0"
    assert registry.is_active("hook")
    plan = SkillRouter().route_for_gene(_gene_with_functions("hook"))
    decision = next(item for item in plan.to_dict()["decisions"] if item["skill_id"] == "hook")
    assert decision["skill_version"] == "1.0.0"
    assert decision["selected_by"] == "deterministic_rule"
    assert decision["routing_weight"] == 1.0
    assert any("hook" in trigger for trigger in decision["triggers"])


def test_hybrid_route_keeps_rules_and_adds_semantic_skills():
    llm = _FakeSemanticLLM("hook, transition, subtitle")
    plan = asyncio.run(SkillRouter().route_hybrid(
        [_gene_with_functions("hook")],
        context="用户希望结尾加文字卡，并使用有节奏的段落转场。",
        llm=llm,
    ))
    assert plan.routing_mode == "hybrid"
    assert plan.semantic_routing_attempted
    # Deterministic results are mandatory and cannot be removed by the LLM.
    assert "structure-adaptation" in plan.references
    assert "hook" in plan.references
    # Semantic routing may add active references not covered by the Gene rule.
    assert "transition" in plan.references
    assert "subtitle" in plan.references
    hook = next(decision for decision in plan.decisions if decision.skill_id == "hook")
    transition = next(decision for decision in plan.decisions if decision.skill_id == "transition")
    assert hook.selected_by == "deterministic_rule+llm_semantic"
    assert transition.selected_by == "llm_semantic"
    assert "为前 3 秒" in llm.prompts[0]  # Registry description is exposed, not full Markdown.


def test_hybrid_route_degrades_to_deterministic_on_llm_failure():
    llm = _FakeSemanticLLM(error=RuntimeError("router unavailable"))
    plan = asyncio.run(SkillRouter().route_hybrid(
        [_gene_with_functions("climax")],
        context="旅行视频高潮段落",
        llm=llm,
    ))
    assert plan.routing_mode == "hybrid_fallback_deterministic"
    assert "RuntimeError" in plan.semantic_routing_error
    assert "emotion" in plan.references
    assert "rhythm" in plan.references


def test_skill_trace_does_not_confuse_selected_with_declared_or_verified():
    plan = SkillRouter().route_for_gene(_gene_with_functions("hook"))
    scheme = {
        "skill_refs_used": ["hook"],
        "storyboard": [
            {
                "index": 0,
                "shot_type": "hook",
                "structure_function": "hook",
                "duration": 2.0,
                "material_id": "mat_001",
                "subtitle_text": "三秒看完杭州",
                "skill_refs": ["hook"],
            },
            {
                "index": 1,
                "shot_type": "daily_moment",
                "duration": 3.5,
                "material_id": "mat_002",
            },
        ],
    }
    trace = verify_skill_usage(
        scheme,
        plan,
        {"items": [{"id": "mat_001"}, {"id": "mat_002"}]},
    )
    assert "hook" in trace["selected_skill_refs"]
    assert "hook" in trace["loaded_skill_refs"]
    assert "hook" in trace["declared_skill_refs"]
    assert "hook" in trace["verified_skill_refs"]
    # structure-adaptation is selected by the default route, but the Planner
    # did not declare it. It must not be falsely reported as used.
    assert "structure-adaptation" in trace["selected_skill_refs"]
    assert "structure-adaptation" not in trace["declared_skill_refs"]
    assert "structure-adaptation" not in trace["verified_skill_refs"]


def test_skill_analytics_is_observational_not_auto_routing():
    path = Path(__file__).resolve().parent / "fixtures" / "skill_evaluation_trace.json"
    report = aggregate_skill_evaluations([path], min_samples=2)
    row = report["skill_reports"][0]
    assert row["selected_count"] == 1
    assert row["verified_rate"] == 1.0
    assert row["recommendation"] == "insufficient_samples_keep_deterministic_route"
    assert "does not prove" in report["interpretation"]


def test_skill_cannot_override_gene_in_prompt():
    """Case 4：Planner prompt 的决策优先级把 Gene 硬约束置于 Skill 之上。"""
    p = build_scheme_generate_prompt(
        skeleton_json="{}", inventory_json="[]", target_topic="t", target_info="i",
        preferences="{}", gene_json='{"shot_genes":[]}', skill_context=[SkillReference("hook", "内容")],
    )
    assert "决策优先级" in p
    assert "Reference Gene" in p and "Editing Skill" in p
    assert "不覆盖 Gene" in p
    assert "Structure Transfer" in p


def test_format_skill_context():
    """按需加载：只有传入的 Skill 才进 prompt，且带明确的 reference 标题。"""
    refs = [{"name": "hook", "content": "hook 内容"}, {"name": "rhythm", "content": "rhythm 内容"}]
    out = _format_skill_context(refs)
    assert "===== Skill 参考：hook.md =====" in out
    assert "===== Skill 参考：rhythm.md =====" in out
    # 字符串直接透传
    assert _format_skill_context("raw string") == "raw string"
    # 空 -> 空
    assert _format_skill_context(None) == ""


def test_gene_section_in_prompt():
    """Case 1：Gene 始终进入 Planner prompt 作为核心约束（无 gene 时不注入）。"""
    p_no_gene = build_scheme_generate_prompt("{}", "[]", "t", "i", "{}", gene_json="", skill_context=None)
    assert "参考视频结构基因" not in p_no_gene
    p_with_gene = build_scheme_generate_prompt(
        "{}", "[]", "t", "i", "{}",
        gene_json='{"source_id":"v1"}', skill_context=None,
    )
    assert "结构基因" in p_with_gene
    assert "参考视频结构基因" in p_with_gene


def test_reviewer_two_groups():
    """Case 6：Reviewer prompt 同时区分 Fidelity 与 Quality。"""
    p = build_review_prompt(
        "源结构摘要", '{"storyboard":[]}', "素材覆盖", gene_json='{"source_id":"v1"}',
    )
    assert "Gene / Structure Fidelity" in p
    assert "Adaptation / Editing Quality" in p
    assert "feedback_type" in p
    assert "fidelity" in p and "quality" in p
    assert '"suggestions"' in p and '"category"' in p


if __name__ == "__main__":
    test_stage_routing_hook_only()
    test_stage_routing_transition()
    test_gene_routing_hook_only()
    test_gene_routing_establishing_material_matching()
    test_reference_content_loaded()
    test_skill_meta_priority()
    test_registry_versions_and_route_decisions()
    test_hybrid_route_keeps_rules_and_adds_semantic_skills()
    test_hybrid_route_degrades_to_deterministic_on_llm_failure()
    test_skill_trace_does_not_confuse_selected_with_declared_or_verified()
    test_skill_analytics_is_observational_not_auto_routing()
    test_skill_cannot_override_gene_in_prompt()
    test_format_skill_context()
    test_gene_section_in_prompt()
    test_reviewer_two_groups()
    print("All skill tests passed!")
