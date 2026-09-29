from typing import Any, TypedDict


class ViralEngineState(TypedDict):
    """所有 Agent 共享的工作记忆 — 不是流水线传送带，是共享黑板"""

    # ===== 用户输入 =====
    sample_videos: list[str]
    user_materials: list[dict]
    target_topic: str
    target_info: dict
    user_preferences: dict

    # ===== Vlog 专属输入 =====
    domain: str
    vlog_style_preference: str
    narrative_type_hint: str
    persona_config: dict

    # ===== 共享工作区（Agent 按需读写） =====
    source_structures: list
    source_genes: list        # Analyst 输出的 StructureGene（Reference Gene，Planner 核心输入）
    material_inventory: Any
    scheme: Any
    knowledge_refs: list
    skill_refs: list          # 当前方案中由 Planner 声明使用的 Editing Skill reference 名
    skill_plan: dict          # 首轮混合路由决策；后续 Reviewer 回环复用，避免语义结果漂移
    skill_trace: dict         # selected/loaded/declared/verified + outcome trace
    gap_report: dict
    generated_materials: list
    rendered_video_path: str
    review_result: dict
    output_dir: str   # runs/{run_id}/ 完整路径
    run_id: str        # 供各节点创建 OutputManager

    # ===== Agent 通信区 =====
    current_task: dict
    last_result: dict

    # ===== 流程控制 =====
    phase: str
    iteration: int
    max_iterations: int
    is_complete: bool
    errors: list[str]
    logs: list[dict]
