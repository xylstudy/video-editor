import json
import logging
from pathlib import Path
from typing import Optional

from agents.base import BaseAgent, AgentRole, AgentResult, AgentStep
from prompts.analyst_prompts import build_shot_analysis_prompt, build_structure_analysis_prompt
from models.video_structure import (
    VideoStructure, ShotInfo, ShotType, TransitionType,
    RhythmPoint, PackagingStyle, SubtitleStyle, BGMInfo, VlogMeta,
)
from models.gene import build_gene as build_gene_from_analyses
from tools.video_tools import VideoTools
from tools.face_tools import FaceTools
from tools.audio_tools import AudioTools

logger = logging.getLogger(__name__)


class AnalystAgent(BaseAgent):
    def __init__(self, llm, video: Optional[VideoTools] = None,
                 face: Optional[FaceTools] = None, audio: Optional[AudioTools] = None):
        super().__init__(llm)
        self.role = AgentRole.ANALYST
        self.video = video or VideoTools()
        self.face = face or FaceTools()
        self.audio = audio or AudioTools()
        self.system_prompt = """你是一位短视频内容分析师，专门研究抖音和小红书爆款Vlog。你可以调用以下工具来分析一个爆款视频。
每个工具函数都有文档说明用途。你接到任务后，自主决定分析步骤和深度。

工具列表：
- get_video_info: 获取视频基础信息（时长、分辨率、帧率）
- detect_scenes: 镜头切分，检测场景变化点
- extract_frame: 抽取指定时间的关键帧
- extract_audio: 抽取音频轨
- transcribe_audio: 语音转写
- detect_face: 人脸检测
- analyze_frame: 用LLM分析单帧画面内容、技法、结构功能
- analyze_structure: 用LLM做全局结构分析（需要先完成analyze_frame）
- done: 任务完成，返回分析结果"""

        self.register_tools({
            "get_video_info": self._get_video_info,
            "detect_scenes": self._detect_scenes,
            "extract_frame": self._extract_frame,
            "extract_audio": self._extract_audio,
            "transcribe_audio": self._transcribe_audio,
            "detect_face": self._detect_face,
            "analyze_shot": self._analyze_shot,
            "analyze_structure": self._analyze_structure,
            "done": self._done,
        })

    def _build_observe_prompt(self, state: dict, history: list) -> str:
        task = state.get("current_task", {})
        ctx = task.get("context", {})
        video_path = ctx.get("video_path", state.get("sample_videos", [""])[0])
        return f"""任务：{task.get('task_description', '分析爆款Vlog')}
视频路径：{video_path}
已执行 {len(history)} 步"""

    async def _get_video_info(self, video_path: str) -> dict:
        return self.video.get_video_info(video_path)

    async def _detect_scenes(self, video_path: str, threshold: float = 0.3) -> list:
        return self.video.detect_scene_changes(video_path, threshold)

    async def _extract_frame(self, video_path: str, time_sec: float) -> str:
        return self.video.extract_frame(video_path, time_sec)

    async def _extract_audio(self, video_path: str) -> str:
        return self.video.extract_audio(video_path)

    async def _transcribe_audio(self, audio_path: str, language: str = "zh") -> str:
        return self.audio.transcribe(audio_path, language)

    async def _detect_face(self, image_path: str) -> dict:
        return {"has_face": self.face.has_face(image_path),
                "region": self.face.get_main_face_region(image_path)}

    async def _analyze_shot(self, shot_index: int, start_time: float, end_time: float,
                             total_duration: float, prev_frame_desc: str = "",
                             video_path: str = "",
                             motion_intensity: float = 0.0,
                             color_stats: dict | None = None,
                             frame_paths: list[str] | None = None) -> dict:
        """Analyse ordered representative frames from one shot.

        OpenAI-compatible vision endpoints commonly accept ``image_url`` but
        not inline ``video_url`` payloads.  Multiple ordered frames preserve
        motion/context cues while remaining portable across providers.
        """
        frames = [str(path) for path in (frame_paths or []) if Path(path).is_file()]
        if not frames:
            shot_duration = max(0.0, end_time - start_time)
            sample_times = [
                min(max(total_duration - 0.05, 0.0), start_time + shot_duration * ratio)
                for ratio in (0.1, 0.5, 0.9)
            ]
            for sample_time in sample_times:
                try:
                    frames.append(str(self.video.extract_frame(video_path, sample_time)))
                except Exception:
                    continue
        if not frames:
            raise RuntimeError(f"shot {shot_index} has no representative frames")
        has_face = any(self.face.has_face(frame_path) for frame_path in frames)

        prompt = build_shot_analysis_prompt(
            shot_index, start_time, end_time,
            total_duration, prev_frame_desc,
            motion_intensity=motion_intensity,
            color_stats=color_stats,
            visual_samples_only=True,
        )

        # 重试 2 次：先用 json 格式，失败后降级为普通格式
        for attempt in range(2):
            fmt = "json" if attempt == 0 else ""
            response = await self.llm.chat_with_images(prompt, frames, response_format=fmt)
            try:
                result = self.llm.parse_json(response)
                result["has_face"] = has_face
                return result
            except Exception:
                if attempt == 0:
                    logger.warning(f"Qwen3 JSON 解析失败 (shot {shot_index})，降级重试...")
                else:
                    logger.warning(f"Qwen3 第2次重试也失败 (shot {shot_index})，返回默认值")
                    return {
                        "one_sentence_summary": f"镜头{shot_index}: {start_time:.1f}s-{end_time:.1f}s",
                        "content": {"main_subject": f"镜头{shot_index}", "people_count": 0},
                        "audio": {},
                        "technique": {"camera_movement": "", "shot_size": "", "composition": ""},
                        "structure_role": {"primary_function": "daily_moment", "reasoning": ""},
                        "emotion": "neutral",
                        "audio_video_match": "unknown",
                        "has_face": has_face,
                    }

    async def _analyze_structure(self, duration: float, width: int, height: int,
                                  shot_count: int, shot_analyses_text: str,
                                  transcript: str = "",
                                  rhythm_data: dict | None = None,
                                  audio_data: dict | None = None) -> dict:
        prompt = build_structure_analysis_prompt(
            duration, width, height, shot_count,
            shot_analyses_text, transcript,
            rhythm_data=rhythm_data,
            audio_data=audio_data,
        )
        response = await self.llm.chat(prompt, response_format="json")
        return self.llm.parse_json(response)

    async def _done(self, summary: str) -> dict:
        return {"status": "done", "summary": summary}

    def build_gene(self, video_path: str, duration: float,
                   shot_analyses: list[dict], structure_analysis: dict) -> "StructureGene":
        """把逐镜头分析 + 结构分析映射为 StructureGene（结构功能基因）。

        纯映射，不调用 LLM；迁移的核心输入，先于 Planner 生成。
        """
        from models.gene import StructureGene
        return build_gene_from_analyses(
            shot_analyses=shot_analyses,
            structure_analysis=structure_analysis,
            source_id=str(Path(video_path).stem),
            source_path=str(video_path),
            duration=duration,
        )

    def build_video_structure(self, video_path: str, duration: float, width: int, height: int,
                               shot_analyses: list[dict], structure_analysis: dict,
                               transcript: str = "") -> VideoStructure:
        shot_type_map = {
            "hook": ShotType.HOOK, "scene_establish": ShotType.SCENE_ESTABLISH,
            "daily_moment": ShotType.DAILY_MOMENT, "emotion_peak": ShotType.EMOTION_PEAK,
            "persona_expression": ShotType.PERSONA_EXPRESSION, "info_card": ShotType.INFO_CARD,
            "closing_moment": ShotType.CLOSING_MOMENT, "transition": ShotType.TRANSITION,
        }
        shots = []
        for i, a in enumerate(shot_analyses):
            st = shot_type_map.get(a.get("structure_role", {}).get("primary_function", ""), ShotType.DAILY_MOMENT)
            tech = a.get("technique", {})
            content = a.get("content", {})
            audio = a.get("audio", {})

            # 从 Qwen3 的音频分析推导 audio_type
            has_speech = audio.get("has_speech", False)
            has_bgm = audio.get("has_bgm", False)
            if has_speech and has_bgm:
                audio_type = "speech_music"
            elif has_speech:
                audio_type = "speech"
            elif has_bgm:
                audio_type = "music"
            else:
                audio_type = "silence"

            shots.append(ShotInfo(
                index=i, start_time=0, end_time=0, duration=0, shot_type=st,
                visual_description=content.get("main_subject", ""),
                camera_movement=tech.get("camera_movement", ""),
                shot_size=tech.get("shot_size", ""),
                composition=tech.get("composition", ""),
                color_mood=content.get("color_temperature", ""),
                emotion=a.get("emotion", ""),
                structure_purpose=a.get("structure_role", {}).get("reasoning", ""),
                has_face=a.get("has_face", False),
                motion_intensity=a.get("motion_intensity", 0.0),
                color_stats=a.get("color_stats", {}),
                audio_type=audio_type,
                bgm_sync=a.get("audio_video_match", "") in ("perfect", "good"),
            ))

        sa = structure_analysis
        structure = VideoStructure(
            source_id=str(Path(video_path).stem),
            source_path=video_path,
            duration=duration,
            resolution=(width, height),
            shots=shots,
            full_transcript=transcript,
            hook_summary=sa.get("hook_strategy", {}).get("detail", ""),
            structure_summary=sa.get("overall_summary", ""),
            key_techniques=sa.get("key_techniques", []),
        )

        rhythm = sa.get("rhythm_analysis", {})
        structure.rhythm_curve = [
            RhythmPoint(time=p["time"], intensity=p["intensity"], note=p.get("note", ""))
            for p in rhythm.get("curve_points", [])
        ]

        packaging = sa.get("packaging_analysis", {})
        structure.packaging = PackagingStyle(
            subtitle_style=SubtitleStyle(
                font_family=packaging.get("subtitle_font_guess", ""),
                position=packaging.get("subtitle_position", "bottom"),
                animation=packaging.get("subtitle_animation", "none"),
            ),
            color_grade=packaging.get("color_grade", ""),
        )

        st = sa.get("structure_type", {})
        structure.vlog_meta = VlogMeta(
            narrative_type=sa.get("narrative_type", ""),
            structure_type=st.get("category", ""),
            overall_emotion=sa.get("overall_emotion", ""),
            hook_method=sa.get("hook_strategy", {}).get("method", ""),
        )

        # 提取音频全轨分析
        audio_analysis = sa.get("audio_analysis", {})
        if audio_analysis:
            structure.audio_analysis = audio_analysis

        # 提取结构基因（结构功能迁移的核心输入）
        structure.gene = self.build_gene(video_path, duration, shot_analyses, structure_analysis)

        return structure
