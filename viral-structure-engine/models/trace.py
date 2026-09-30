"""分析轨迹模型 — 记录 LLM 分析推理过程，而不仅是结论。

与基因报告（analysis_result.json）互补：报告回答"分析出了什么"，
轨迹回答"怎么分析出来的"（用了哪些帧、传了什么上下文、模型/prompt 版本等）。

提示词内容变更时，请同步 bump 下方对应的 *_PROMPT_VERSION 常量，
旧轨迹文件仍带着旧版本号，可追溯。
"""
from dataclasses import dataclass, field
from datetime import datetime

# ===== Prompt 版本号 =====
ANALYST_PROMPT_VERSION = "analyst_prompts_v2_multiframe"
STRUCTURE_PROMPT_VERSION = "structure_analysis_prompts_v1"
KNOWLEDGE_EXTRACT_PROMPT_VERSION = "knowledge_extract_v1"

# structure_input_summary 落盘时的单字段长度上限（完整数据已在分析结果 JSON 中）
STRUCTURE_INPUT_MAX_CHARS = 3000


@dataclass
class ShotTrace:
    """单镜头推理轨迹：这一帧画面是怎么被判断出来的。"""

    index: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    frame_paths: list[str] = field(default_factory=list)   # 用了哪几帧
    motion_intensity: float = 0.0                          # 预处理量化数据
    color_stats: dict = field(default_factory=dict)
    prev_context_summary: str = ""                         # 传给 LLM 的上一镜头摘要
    analysis: dict = field(default_factory=dict)           # LLM 返回的原始分析
    model: str = ""
    prompt_version: str = ""

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "frame_paths": self.frame_paths,
            "motion_intensity": self.motion_intensity,
            "color_stats": self.color_stats,
            "prev_context_summary": self.prev_context_summary,
            "analysis": self.analysis,
            "model": self.model,
            "prompt_version": self.prompt_version,
        }


@dataclass
class AnalysisTrace:
    """整段视频的分析轨迹：从预处理到逐镜头推理再到全局结构合成。"""

    video_path: str = ""
    duration: float = 0.0
    resolution: list = field(default_factory=list)
    scene_count: int = 0
    scene_threshold: float = 0.3
    audio_summary: dict = field(default_factory=dict)
    shots: list[ShotTrace] = field(default_factory=list)
    structure_input_summary: str = ""                      # 喂给结构分析的镜头摘要（截断）
    structure_analysis: dict = field(default_factory=dict)
    versions: dict = field(default_factory=dict)           # {model, prompt_version, llm_client}
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "video_path": self.video_path,
            "duration": self.duration,
            "resolution": self.resolution,
            "scene_count": self.scene_count,
            "scene_threshold": self.scene_threshold,
            "audio_summary": self.audio_summary,
            "shots": [s.to_dict() for s in self.shots],
            "structure_input_summary": self.structure_input_summary,
            "structure_analysis": self.structure_analysis,
            "versions": self.versions,
            "created_at": self.created_at,
        }


def make_shot_trace(index=0, start_time=0.0, end_time=0.0, analysis=None,
                    frame_paths=None, motion_intensity=0.0, color_stats=None,
                    prev_context_summary="", model="",
                    prompt_version=ANALYST_PROMPT_VERSION) -> ShotTrace:
    """构造单镜头轨迹，对所有可选字段做 None 容错。"""
    return ShotTrace(
        index=index or 0,
        start_time=start_time or 0.0,
        end_time=end_time or 0.0,
        frame_paths=list(frame_paths or []),
        motion_intensity=motion_intensity or 0.0,
        color_stats=dict(color_stats or {}),
        prev_context_summary=prev_context_summary or "",
        analysis=dict(analysis or {}),
        model=model or "",
        prompt_version=prompt_version or "",
    )


def make_analysis_trace(video_path="", duration=0.0, resolution=None, scene_count=0,
                        scene_threshold=0.3, audio_summary=None, shots=None,
                        structure_input_summary="", structure_analysis=None,
                        versions=None) -> AnalysisTrace:
    """构造整段视频分析轨迹。structure_input_summary 超长时截断。"""
    summary = structure_input_summary or ""
    if len(summary) > STRUCTURE_INPUT_MAX_CHARS:
        summary = summary[:STRUCTURE_INPUT_MAX_CHARS] + f"...（截断，原长 {len(structure_input_summary)} 字符）"
    return AnalysisTrace(
        video_path=video_path or "",
        duration=duration or 0.0,
        resolution=list(resolution or []),
        scene_count=scene_count or 0,
        scene_threshold=scene_threshold,
        audio_summary=dict(audio_summary or {}),
        shots=list(shots or []),
        structure_input_summary=summary,
        structure_analysis=dict(structure_analysis or {}),
        versions=dict(versions or {}),
        created_at=datetime.now().isoformat(),
    )
