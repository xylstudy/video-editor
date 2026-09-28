from dataclasses import dataclass, field
from typing import Optional
from models.video_structure import (
    ShotType, TransitionType, ShotInfo, PackagingStyle, BGMInfo,
)


@dataclass
class StoryboardFrame:
    index: int
    shot_type: ShotType
    duration: float

    start_time: float = 0
    end_time: float = 0
    purpose: str = ""

    source_material_id: str = ""
    material_id: str = ""
    is_generated: bool = False
    fill_strategy: str = ""
    gap_fill_strategy: str = ""
    gap_filled: bool = False

    visual_description: str = ""
    visual_content: str = ""
    subtitle_text: str = ""
    voiceover_text: str = ""
    text_card_content: str = ""
    text_card_style: dict = field(default_factory=dict)
    text_card_config: Optional[dict] = None

    transition_in: TransitionType = TransitionType.CUT
    transition: TransitionType = TransitionType.CUT
    emotion: str = ""
    camera_movement: str = ""
    camera_note: str = ""
    shot_size: str = ""
    composition: str = ""
    motion_effect: str = ""
    packaging_note: str = ""
    rhythm_intensity: float = 0.5

    has_face: bool = False
    bgm_sync: bool = False

    ken_burns_config: Optional[dict] = None
    speed_change: Optional[float] = None

    # ===== 前景/背景合成（Planner 决策） =====
    fg_source_id: str = ""             # 前景抠图的素材 ID（独立于 background）
    bg_source_id: str = ""             # 背景素材 ID（独立于 material_id）
    composite_mode: str = "none"       # "none" / "fg_overlay" / "fg_reveal" / "pip"
                                        #   none: 只显示背景
                                        #   fg_overlay: 前景直接叠在背景上
                                        #   fg_reveal: 前景以揭示动画出现
                                        #   pip: 画中画

    # ===== 字幕自由配置 =====
    subtitle_config: dict = field(default_factory=dict)
    # 支持的 key:
    #   fontSize, verticalAlign(bottom/top/center), marginFromEdge,
    #   offsetX, color, textAlign, maxWidthPercent, fontWeight,
    #   letterSpacing, background, padding, fontFamily, lineHeight

    # ===== 扩展：渲染控制 =====
    render_component: str = "auto"          # "auto" / "text_card" / "ken_burns" / "custom:{name}" / "code:{...}"
    custom_render_config: dict = field(default_factory=dict)  # 透传给渲染组件的任意配置
    layers: list[dict] = field(default_factory=list)           # 多图层叠加，每层独立配置
    canvas_width: int = 1080
    canvas_height: int = 1920

    # ===== FFmpeg 粗剪控制 =====
    ffmpeg_segment: dict = field(default_factory=dict)  # {trim_start, trim_end, speed, reverse, ...}

    # ===== 结构迁移可溯源（Reference Gene → Material → Skill → Adaptation） =====
    structure_function: str = ""     # 本镜头承担的 Gene 结构功能（hook/establishing/...）
    gene_shot_index: int = -1        # 对应参考 Gene 的 shot_gene index（-1 为自由发挥）
    skill_refs: list[str] = field(default_factory=list)   # 本镜头用到的 Skill reference 名
    adaptation: dict = field(default_factory=dict)        # {preserved, reason, original_function}

    def __post_init__(self):
        if not self.material_id and self.source_material_id:
            self.material_id = self.source_material_id
        if not self.source_material_id and self.material_id:
            self.source_material_id = self.material_id
        if self.transition_in == TransitionType.CUT and self.transition != TransitionType.CUT:
            self.transition_in = self.transition
        if not self.purpose and self.visual_description:
            self.purpose = self.visual_description
        if not self.visual_content and self.visual_description:
            self.visual_content = self.visual_description
        if not self.visual_description and self.visual_content:
            self.visual_description = self.visual_content
        if not self.fill_strategy and self.gap_fill_strategy:
            self.fill_strategy = self.gap_fill_strategy

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "shot_type": self.shot_type.value,
            "duration": self.duration,
            "purpose": self.purpose,
            "source_material_id": self.source_material_id or self.material_id,
            "is_generated": self.is_generated,
            "fill_strategy": self.fill_strategy or self.gap_fill_strategy,
            "visual_description": self.visual_description or self.visual_content,
            "subtitle_text": self.subtitle_text,
            "voiceover_text": self.voiceover_text,
            "text_card_content": self.text_card_content,
            "transition_in": (self.transition_in or self.transition).value,
            "emotion": self.emotion,
            "camera_movement": self.camera_movement or self.camera_note,
            "shot_size": self.shot_size,
            "composition": self.composition,
            "has_face": self.has_face,
            "bgm_sync": self.bgm_sync,
            "motion_effect": self.motion_effect,
            "gap_filled": self.gap_filled,
            # 前景/背景合成
            "fg_source_id": self.fg_source_id,
            "bg_source_id": self.bg_source_id,
            "composite_mode": self.composite_mode,
            # 字幕配置
            "subtitle_config": self.subtitle_config,
            # 扩展字段
            "render_component": self.render_component,
            "custom_render_config": self.custom_render_config,
            "layers": self.layers,
            "canvas_width": self.canvas_width,
            "canvas_height": self.canvas_height,
            "ffmpeg_segment": self.ffmpeg_segment,
            "structure_function": self.structure_function,
            "gene_shot_index": self.gene_shot_index,
            "skill_refs": self.skill_refs,
            "adaptation": self.adaptation,
        }


@dataclass
class VideoScheme:
    id: str = ""
    title: str = ""
    target_topic: str = ""
    target_category: str = "vlog"
    target_duration: float = 60.0
    target_platform: str = "抖音"
    structure_type: str = ""
    narrative_type: str = ""
    hook_strategy: str = ""
    overall_emotion: str = ""
    storyboard: list[StoryboardFrame] = field(default_factory=list)
    packaging: PackagingStyle = field(default_factory=PackagingStyle)
    bgm: BGMInfo = field(default_factory=BGMInfo)
    script_blocks: list[dict] = field(default_factory=list)
    emotion_arc: list[dict] = field(default_factory=list)
    source_structure_ids: list[str] = field(default_factory=list)
    material_ids: list[str] = field(default_factory=list)
    gap_ids: list[str] = field(default_factory=list)
    # 本方案生成时注入参考的知识/手法 id 列表（供 reviewer 关联与效果统计）
    knowledge_refs: list[str] = field(default_factory=list)
    # ===== 结构迁移可溯源 =====
    gene_refs: list[str] = field(default_factory=list)         # 参考 Gene 的 source_id 列表
    # Skill trace has four deliberately different meanings.  Do not collapse
    # selected (router relevance) into declared/verified (actual compliance).
    selected_skill_refs: list[str] = field(default_factory=list)
    loaded_skill_refs: list[str] = field(default_factory=list)
    declared_skill_refs: list[str] = field(default_factory=list)
    verified_skill_refs: list[str] = field(default_factory=list)
    # Backward-compatible alias for model-declared use.  Older artifacts may
    # only contain this field, so readers should treat it as `declared`.
    skill_refs_used: list[str] = field(default_factory=list)
    skill_evaluation: dict = field(default_factory=dict)
    adaptation_log: list[dict] = field(default_factory=list)   # 结构适配决策记录
    color_grade: str = ""
    filter_style: str = ""

    iteration: int = 0
    version: int = 1
    status: str = "draft"
    review_scores: Optional[dict] = None
    total_score: float = 0.0
    passed_review: bool = False
    review_notes: list[str] = field(default_factory=list)
    change_log: list[dict] = field(default_factory=list)
    render_path: Optional[str] = None
    render_config: dict = field(default_factory=dict)

    # ===== 音频分析（Analyst 输出） =====
    audio_analysis: dict = field(default_factory=dict)
    # 结构: {
    #   "source_video": "参考视频路径",
    #   "duration": 33.1,
    #   "bpm": 120,
    #   "energy_curve": [{"time": 0, "energy": 0.3}, ...],
    #   "mood_segments": [{"start": 0, "end": 10, "mood": "...", "energy": "...", "instruments": "..."}],
    #   "climax_points": [{"time": 25.0, "type": "drop/crescendo/silence_break"}],
    #   "audio_video_match_pattern": "跟随/对比/卡点/氛围铺底",
    #   "overall_mood": "治愈/燃/轻松/怀旧/活力",
    #   "recommended_volume": 0.3,
    #   "extracted_path": "音频文件路径"
    # }

    # ===== 音频源配置（Planner 决策） =====
    audio_source_id: str = ""            # 使用哪个参考视频的音频
    audio_config: dict = field(default_factory=dict)
    # 结构: { "volume": 0.3, "loop": true, "trim_before": 0, "trim_after": null }
    render_pipeline: str = "remotion"    # "remotion" / "ffmpeg" / "hybrid"
    render_hints: dict = field(default_factory=dict)  # 对 Renderer Agent 的提示

    # ===== 画布尺寸（Planner 传入） =====
    canvas_width: int = 1080
    canvas_height: int = 1920

    # ===== FFmpeg 粗剪时间线 =====
    ffmpeg_timeline: list[dict] = field(default_factory=list)  # 粗剪指令序列

    def get_duration(self) -> float:
        return sum(frame.duration for frame in self.storyboard)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "target_topic": self.target_topic,
            "target_category": self.target_category,
            "target_duration": self.target_duration,
            "target_platform": self.target_platform,
            "structure_type": self.structure_type,
            "narrative_type": self.narrative_type,
            "hook_strategy": self.hook_strategy,
            "overall_emotion": self.overall_emotion,
            "storyboard": [f.to_dict() for f in self.storyboard],
            "packaging": self.packaging.to_dict(),
            "bgm": self.bgm.to_dict(),
            "script_blocks": self.script_blocks,
            "emotion_arc": self.emotion_arc,
            "knowledge_refs": self.knowledge_refs,
            "gene_refs": self.gene_refs,
            "selected_skill_refs": self.selected_skill_refs,
            "loaded_skill_refs": self.loaded_skill_refs,
            "declared_skill_refs": self.declared_skill_refs,
            "verified_skill_refs": self.verified_skill_refs,
            "skill_refs_used": self.skill_refs_used,
            "skill_evaluation": self.skill_evaluation,
            "adaptation_log": self.adaptation_log,
            "iteration": self.iteration,
            "version": self.version,
            "status": self.status,
            "review_scores": self.review_scores,
            "total_score": self.total_score,
            "passed_review": self.passed_review,
            "actual_duration": self.get_duration(),
            # 音频分析
            "audio_analysis": self.audio_analysis,
            "audio_source_id": self.audio_source_id,
            "audio_config": self.audio_config,
            # 扩展字段
            "canvas_width": self.canvas_width,
            "canvas_height": self.canvas_height,
            "render_pipeline": self.render_pipeline,
            "render_hints": self.render_hints,
            "ffmpeg_timeline": self.ffmpeg_timeline,
        }
