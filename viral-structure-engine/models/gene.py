"""结构基因模型 — Reference-guided 迁移的核心中间表示。

与 VideoStructure（记录原片内容）不同，Gene 只表达"结构功能"：
迁移时复制的是"这个位置承担什么功能、什么节奏、什么情绪、和上一镜什么关系、
对画面有什么功能性要求"，而不是机械复制原片里的具体物体。

设计原则（贯穿整个系统）：
  Gene 决定"迁移什么"（本次参考视频专属，硬约束为主）
  Skill 决定"怎么迁移好"（跨任务复用，软策略为主）
  优先级：用户显式要求 > Reference Gene > Editing Skill > 模型自由发挥
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ConstraintKind(str, Enum):
    HARD = "hard"       # 硬约束：迁移时必须保持，否则结构失真
    SOFT = "soft"       # 软偏好：尽量保持，可用 Skill / 素材条件放宽


@dataclass
class GeneConstraint:
    """一条可迁移的结构约束。kind 区分硬约束 / 软偏好。"""
    description: str = ""
    kind: str = ConstraintKind.SOFT.value
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "kind": self.kind,
            "rationale": self.rationale,
        }


@dataclass
class ShotGene:
    """单个镜头位置的"结构功能基因"——不描述物体，只描述功能。"""

    index: int = 0                     # 在 Gene 内的顺序
    source_shot_index: int = -1        # 对应原片镜头下标（溯源）
    function: str = ""                 # 语义功能：hook / establishing / daily_moment / climax / closing / transition / info
    shot_type: str = ""                # 与 ShotType 对齐的类型标签

    semantic_role: str = ""            # 语义角色（一句话，功能视角）
    rhythm_role: str = ""              # 节奏角色：fast_cut / beat_sync / breather / build_up / climax / resolve
    emotion_role: str = ""             # 情绪角色：这个位置应该给观众什么情绪
    relation_to_previous: str = ""     # 与上一镜关系：continue / contrast / expand / callback / cutaway
    visual_requirement: str = ""       # 功能性画面要求（宽景/地标/特写/人像…），而非"拍同一个东西"

    duration_ratio: float = 0.0        # 占全片时长的比例
    importance: str = "medium"         # critical / high / medium / low

    hard_constraints: list[str] = field(default_factory=list)
    soft_preferences: list[str] = field(default_factory=list)
    effect_events: list[dict] = field(default_factory=list)
    match_cut_to_next: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "source_shot_index": self.source_shot_index,
            "function": self.function,
            "shot_type": self.shot_type,
            "semantic_role": self.semantic_role,
            "rhythm_role": self.rhythm_role,
            "emotion_role": self.emotion_role,
            "relation_to_previous": self.relation_to_previous,
            "visual_requirement": self.visual_requirement,
            "duration_ratio": self.duration_ratio,
            "importance": self.importance,
            "hard_constraints": self.hard_constraints,
            "soft_preferences": self.soft_preferences,
            "effect_events": self.effect_events,
            "match_cut_to_next": self.match_cut_to_next,
        }


@dataclass
class StructureGene:
    """整条参考视频的结构基因——决定本次迁移要保持的骨架。"""

    source_id: str = ""
    source_path: str = ""
    duration: float = 0.0
    structure_type: str = ""
    narrative_type: str = ""
    hook_strategy: str = ""
    overall_emotion: str = ""
    rhythm_pattern: str = ""
    climax_position_ratio: float = 0.0
    emotion_arc: list[dict] = field(default_factory=list)
    shot_genes: list[ShotGene] = field(default_factory=list)
    hard_constraints: list[str] = field(default_factory=list)
    soft_preferences: list[str] = field(default_factory=list)
    migration_notes: str = ""
    reference_cut_points: list[float] = field(default_factory=list)
    effect_tracks: list[dict] = field(default_factory=list)
    packaging_signature: dict = field(default_factory=dict)
    source_aspect_ratio: str = ""

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_path": self.source_path,
            "duration": self.duration,
            "structure_type": self.structure_type,
            "narrative_type": self.narrative_type,
            "hook_strategy": self.hook_strategy,
            "overall_emotion": self.overall_emotion,
            "rhythm_pattern": self.rhythm_pattern,
            "climax_position_ratio": self.climax_position_ratio,
            "emotion_arc": self.emotion_arc,
            "shot_genes": [g.to_dict() for g in self.shot_genes],
            "hard_constraints": self.hard_constraints,
            "soft_preferences": self.soft_preferences,
            "migration_notes": self.migration_notes,
            "reference_cut_points": self.reference_cut_points,
            "effect_tracks": self.effect_tracks,
            "packaging_signature": self.packaging_signature,
            "source_aspect_ratio": self.source_aspect_ratio,
        }

    # ---- 便捷查询 ----

    def critical_shots(self) -> list[ShotGene]:
        """返回 importance == critical 的镜头，Planner 必须优先保持。"""
        return [g for g in self.shot_genes if g.importance == "critical"]

    def hard_constraint_text(self) -> str:
        return "\n".join(f"- [硬] {c}" for c in self.hard_constraints)

    def soft_preference_text(self) -> str:
        return "\n".join(f"- [软] {c}" for c in self.soft_preferences)


# ===== Gene 构建：把 Analyst 的逐镜头分析 + 结构分析映射为结构功能基因 =====

_FUNCTION_ALIASES = {
    "hook": "hook",
    "scene_establish": "establishing",
    "establishing": "establishing",
    "daily_moment": "daily_moment",
    "emotion_peak": "climax",
    "climax": "climax",
    "persona_expression": "persona",
    "persona": "persona",
    "info_card": "info",
    "closing_moment": "closing",
    "closing": "closing",
    "transition": "transition",
    "pain_point": "pain_point",
    "product": "product",
    "usage": "usage",
    "comparison": "comparison",
}

# 功能 → 默认视觉要求（功能性，而非物体）。迁移时按"功能"找替代素材。
_FUNCTION_VISUAL_REQUIREMENT = {
    "hook": "强视觉冲击 / 悬念 / 高信息密度的画面，用于前 3 秒抓注意力",
    "establishing": "宽景 / 地标 / 环境交代，让观众知道'这是在哪/什么场景'",
    "daily_moment": "信息量中等的过程/日常画面，作为叙事填充",
    "climax": "视觉最美 / 最有感染力 / 最震撼的画面，配合情绪高点",
    "persona": "人物状态 / 表情 / 反应 / 互动，增加人格感",
    "info": "文字信息卡 / 关键信息呈现",
    "closing": "情绪落点 / 余韵 / 感悟感画面",
    "transition": "信息量低、连接两个段落的过渡画面",
}

# 功能 → 默认节奏角色
_FUNCTION_RHYTHM_ROLE = {
    "hook": "fast_cut",
    "establishing": "breather",
    "daily_moment": "breather",
    "climax": "climax",
    "persona": "build_up",
    "info": "breather",
    "closing": "resolve",
    "transition": "fast_cut",
}


def _constraint_kind_from_importance(importance: str) -> str:
    if importance in ("critical", "high"):
        return ConstraintKind.HARD.value
    return ConstraintKind.SOFT.value


def build_gene(
    shot_analyses: list[dict],
    structure_analysis: dict,
    source_id: str = "",
    source_path: str = "",
    duration: float = 0.0,
    effect_tracks: list[dict] | None = None,
    source_aspect_ratio: str = "",
    reference_cut_points: list[float] | None = None,
) -> StructureGene:
    """纯函数：把逐镜头分析 + 全局结构分析映射为 StructureGene。

    不依赖 LLM / 视频工具，便于单测与离线复用。
    """
    sa = structure_analysis or {}
    rhythm = sa.get("rhythm_analysis", {}) or {}
    hook = sa.get("hook_strategy", {}) or {}
    st = sa.get("structure_type", {}) or {}
    packaging = sa.get("packaging_analysis", {}) or {}
    effect_tracks = list(effect_tracks or sa.get("effect_tracks", []) or [])

    shot_genes: list[ShotGene] = []
    total_shots = max(len(shot_analyses), 1)

    for i, a in enumerate(shot_analyses):
        role = a.get("structure_role", {}) or {}
        primary = role.get("primary_function", "") or a.get("shot_type", "")
        function = _FUNCTION_ALIASES.get(primary, "daily_moment")

        # importance：hook / climax / closing 默认高重要度
        if function == "hook":
            importance = "critical"
        elif function in ("climax", "establishing"):
            importance = "high"
        elif function == "closing":
            importance = "high"
        else:
            importance = "medium"

        hard, soft = [], []
        if function == "hook":
            hard.append("保留 Hook 结构：前 3 秒必须有强抓注意力镜头")
        if function == "climax":
            hard.append("保留情绪高点位置与功能，高潮镜头不可缺失")
        if function == "establishing":
            soft.append("场景建立功能应保留，可用宽景/地标等同类功能素材替代")

        emotion = a.get("emotion", "") or ""
        tech = a.get("technique", {}) or {}

        raw_effects = a.get("effect_events", []) or []
        normalized_effects = []
        shot_start = _safe_float(a.get("start_time"))
        shot_end = _safe_float(a.get("end_time"), shot_start)
        shot_duration = max(0.0, shot_end - shot_start)
        for event_index, raw_event in enumerate(raw_effects):
            if not isinstance(raw_event, dict):
                continue
            event = dict(raw_event)
            event_id = str(event.get("id") or f"shot_{i:03d}_effect_{event_index:02d}")
            start_offset = min(
                shot_duration,
                max(0.0, _safe_float(event.get("start_offset"))),
            )
            raw_end = event.get("end_offset", shot_duration)
            end_offset = min(
                shot_duration,
                max(start_offset, _safe_float(raw_end, shot_duration)),
            )
            event.update({
                "id": event_id,
                "start_offset": round(start_offset, 3),
                "end_offset": round(end_offset, 3),
                "anchor": str(event.get("anchor") or "frame"),
                "priority": str(event.get("priority") or "medium"),
            })
            normalized_effects.append(event)
            effect_tracks.append({
                **event,
                "start": round(shot_start + start_offset, 3),
                "end": round(shot_start + end_offset, 3),
                "source_shot_index": i,
            })

        shot_genes.append(ShotGene(
            index=i,
            source_shot_index=i,
            function=function,
            shot_type=primary or function,
            semantic_role=role.get("reasoning", "") or a.get("one_sentence_summary", ""),
            rhythm_role=_FUNCTION_RHYTHM_ROLE.get(function, "breather"),
            emotion_role=emotion,
            relation_to_previous=(
                "contrast" if i > 0 and emotion and emotion != shot_analyses[i - 1].get("emotion", "")
                else "continue"
            ),
            visual_requirement=_FUNCTION_VISUAL_REQUIREMENT.get(function, ""),
            duration_ratio=(shot_end - shot_start) / duration if duration else 0.0,
            importance=importance,
            hard_constraints=hard,
            soft_preferences=soft + ([tech.get("camera_movement", "")] if tech.get("camera_movement") else []),
            effect_events=normalized_effects,
            match_cut_to_next=dict(a.get("match_cut_to_next") or {}),
        ))

    deduped_tracks: list[dict] = []
    seen_track_keys: set[tuple] = set()
    for track in effect_tracks:
        if not isinstance(track, dict):
            continue
        key = (
            str(track.get("id") or ""),
            str(track.get("type") or ""),
            round(_safe_float(track.get("start")), 3),
            round(_safe_float(track.get("end")), 3),
        )
        if key in seen_track_keys:
            continue
        seen_track_keys.add(key)
        deduped_tracks.append(track)
    effect_tracks = deduped_tracks

    hard_constraints = [
        f"保持 {len(shot_genes)} 镜的结构骨架与顺序",
        f"保持高潮位置约为全片 {rhythm.get('climax_position_percent', 0)}% 处",
    ]
    if reference_cut_points is None:
        reference_cut_points = [
            float(item.get("end_time", 0) or 0)
            for item in shot_analyses[:-1]
            if isinstance(item, dict) and float(item.get("end_time", 0) or 0) > 0
        ]
    reference_cut_points = sorted({round(float(value), 3) for value in reference_cut_points if float(value) > 0})
    expected_shot_count = len(reference_cut_points) + 1 if reference_cut_points else len(shot_genes)
    hard_constraints[0] = f"Preserve the {expected_shot_count}-shot structure and ordering"
    signature_effects = [
        item for item in effect_tracks
        if isinstance(item, dict) and item.get("priority", "high") in {"critical", "high"}
    ]
    if reference_cut_points:
        hard_constraints.append("Preserve the relative positions of the reference cut points and beat sync")
    if signature_effects:
        hard_constraints.append("Transfer all critical/high effect_tracks as signature packaging")

    if hook.get("method"):
        hard_constraints.append(f"保持 Hook 策略：{hook['method']}")

    soft_preferences = [
        f"节奏模式接近：{rhythm.get('pattern', '')}",
        f"整体情绪基调：{sa.get('overall_emotion', '')}",
    ]

    return StructureGene(
        source_id=source_id,
        source_path=source_path,
        duration=duration,
        structure_type=st.get("category", ""),
        narrative_type=sa.get("narrative_type", ""),
        hook_strategy=hook.get("method", ""),
        overall_emotion=sa.get("overall_emotion", ""),
        rhythm_pattern=rhythm.get("pattern", ""),
        climax_position_ratio=rhythm.get("climax_position_percent", 0.0),
        emotion_arc=sa.get("emotion_arc", []) or [],
        shot_genes=shot_genes,
        hard_constraints=hard_constraints,
        soft_preferences=soft_preferences,
        reference_cut_points=reference_cut_points,
        effect_tracks=effect_tracks,
        packaging_signature={
            "title_cards": packaging.get("title_cards", []) or [],
            "transitions_used": packaging.get("transitions_used", []) or [],
            "stickers_effects": packaging.get("stickers_effects", ""),
            "color_grade": packaging.get("color_grade", ""),
            "color_grade_detail": packaging.get("color_grade_detail", ""),
        },
        source_aspect_ratio=source_aspect_ratio,
        migration_notes="结构功能迁移，非内容复制：按'功能/节奏/情绪'迁移，而非复制原片物体。",
    )
