import json
import logging
from typing import Optional

from agents.base import BaseAgent, AgentRole, AgentResult
from prompts.planner_prompts import (
    build_skeleton_extract_prompt,
    build_scheme_generate_prompt,
    build_scheme_iterate_prompt,
)
from models.scheme import VideoScheme, StoryboardFrame
from models.video_structure import ShotType, TransitionType

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    def __init__(self, llm):
        super().__init__(llm)
        self.role = AgentRole.PLANNER
        self.system_prompt = """你是一位Vlog赛道金牌编导，专长是"结构迁移"——把爆款Vlog的成功结构方法论迁移到新内容上。

工具列表：
- extract_skeleton: 从爆款分析中提取可迁移的结构骨架
- generate_scheme: 基于骨架+新内容+素材+音频分析生成完整方案（含前景/背景合成决策和字幕配置）
- iterate_scheme: 根据审核反馈修改方案
- done: 任务完成"""

        self.register_tools({
            "extract_skeleton": self._extract_skeleton,
            "generate_scheme": self._generate_scheme,
            "iterate_scheme": self._iterate_scheme,
            "done": self._done,
        })

    def _build_observe_prompt(self, state: dict, history: list) -> str:
        task = state.get("current_task", {})
        parts = [f"任务：{task.get('task_description', '')}"]
        ss = state.get("source_structures", [])
        if ss:
            parts.append(f"爆款结构：{ss[0].structure_summary[:100] if hasattr(ss[0], 'structure_summary') else '已分析'}")
            # 显示音频分析是否可用
            if hasattr(ss[0], 'bgm') and ss[0].bgm:
                bgm = ss[0].bgm
                parts.append(f"音频分析：BPM={bgm.bpm} 风格={bgm.style} 情绪={bgm.mood}")
        inv = state.get("material_inventory")
        if inv:
            items = getattr(inv, "items", getattr(inv, "materials", []))
            parts.append(f"素材：{len(items)}个")
        review = state.get("review_result", {})
        if review:
            parts.append(f"审核反馈：总分{review.get('total_score')}")
        parts.append(f"已执行 {len(history)} 步")
        return "\n".join(parts)

    async def _extract_skeleton(self, structure_summary: str, target_topic: str, target_info: str,
                                 structure_analysis: str = "") -> dict:
        prompt = build_skeleton_extract_prompt(structure_summary, target_topic, target_info, structure_analysis)
        for attempt in range(3):
            try:
                response = await self.llm.chat(
                    prompt,
                    response_format="json",
                    temperature=0.2,
                    max_tokens=16384,
                )
                return self.llm.parse_json(response)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"骨架解析失败 (尝试 {attempt+1}/3): {e}")
                if attempt == 2:
                    raise
        raise RuntimeError("骨架提取失败")

    async def _generate_scheme(self, skeleton_json: str, inventory_json: str,
                                target_topic: str, target_info: str, preferences: str,
                                material_type_hint: str = "",
                                audio_data: str = "",
                                gene_json: str = "",
                                skill_context=None) -> dict:
        # 渐进式披露：不再把全部剪辑手法摘要注入，改为按需加载 Skill reference。
        prompt = build_scheme_generate_prompt(skeleton_json, inventory_json,
                                               target_topic, target_info, preferences,
                                               material_type_hint,
                                               audio_data=audio_data,
                                               gene_json=gene_json,
                                               skill_context=skill_context)
        for attempt in range(3):
            try:
                response = await self.llm.chat(prompt, response_format="json", max_tokens=16384)
                return self.llm.parse_json(response)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"方案解析失败 (尝试 {attempt+1}/3): {e}")
                if attempt == 2:
                    raise
        raise RuntimeError("方案生成失败")

    async def _iterate_scheme(self, scheme_json: str, review_json: str, inventory_json: str,
                              gene_json: str = "", skill_context=None) -> dict:
        prompt = build_scheme_iterate_prompt(scheme_json, review_json, inventory_json,
                                             gene_json=gene_json, skill_context=skill_context)
        for attempt in range(3):
            try:
                response = await self.llm.chat(prompt, response_format="json", max_tokens=16384)
                return self.llm.parse_json(response)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"方案迭代解析失败 (尝试 {attempt+1}/3): {e}")
                if attempt == 2:
                    raise
        raise RuntimeError("方案迭代失败")

    async def _done(self, summary: str) -> dict:
        return {"status": "done", "summary": summary}

    def build_scheme(self, scheme_data: dict, target_topic: str, iteration: int = 0) -> VideoScheme:
        shot_map = {
            "hook": ShotType.HOOK, "cta": ShotType.CTA, "transition": ShotType.TRANSITION,
            "scene_establish": ShotType.SCENE_ESTABLISH, "daily_moment": ShotType.DAILY_MOMENT,
            "emotion_peak": ShotType.EMOTION_PEAK, "persona": ShotType.PERSONA_EXPRESSION,
            "info_card": ShotType.INFO_CARD, "closing": ShotType.CLOSING_MOMENT,
        }
        trans_map = {
            "cut": TransitionType.CUT, "fade": TransitionType.FADE,
            "dissolve": TransitionType.DISSOLVE,
            "zoom_in": TransitionType.ZOOM_IN, "zoom_out": TransitionType.ZOOM_OUT,
            "flash_white": TransitionType.FLASH_WHITE,
            "flash_black": TransitionType.FLASH_BLACK,
            "slide": TransitionType.SLIDE, "slide_left": TransitionType.SLIDE_LEFT,
            "slide_right": TransitionType.SLIDE_RIGHT, "slide_up": TransitionType.SLIDE_UP,
            "slide_down": TransitionType.SLIDE_DOWN,
            "wipe_left": TransitionType.WIPE_LEFT, "wipe_right": TransitionType.WIPE_RIGHT,
            "wipe_up": TransitionType.WIPE_UP, "wipe_down": TransitionType.WIPE_DOWN,
            "blur_in": TransitionType.BLUR_IN, "rotate_in": TransitionType.ROTATE_IN,
            "whip": TransitionType.WHIP, "mask": TransitionType.MASK,
            "circle_reveal": TransitionType.CIRCLE_REVEAL,
            "zoom_flash": TransitionType.ZOOM_FLASH, "glitch": TransitionType.GLITCH,
            "spin": TransitionType.SPIN, "zoom_heavy": TransitionType.ZOOM_HEAVY,
            "light_leak": TransitionType.LIGHT_LEAK,
            "freeze_frame": TransitionType.FREEZE_FRAME,
            "flip_3d": TransitionType.FLIP_3D, "radial_wipe": TransitionType.RADIAL_WIPE,
            "zoom_through": TransitionType.ZOOM_THROUGH,
            "liquid_warp": TransitionType.LIQUID_WARP,
            "chromatic_aberration": TransitionType.CHROMATIC_ABERRATION,
            "none": TransitionType.NONE,
        }

        frames = []
        for i, fd in enumerate(scheme_data.get("storyboard", [])):
            frames.append(StoryboardFrame(
                index=i, start_time=0, end_time=0,
                duration=fd.get("duration", 3.0),
                purpose=fd.get("visual_description", ""),
                shot_type=shot_map.get(fd.get("shot_type", ""), ShotType.DAILY_MOMENT),
                visual_content=fd.get("visual_description", ""),
                material_id=fd.get("source_material_id", ""),
                subtitle_text=fd.get("subtitle_text", ""),
                voiceover_text=fd.get("voiceover_text", ""),
                transition=trans_map.get(fd.get("transition_in", "cut"), TransitionType.CUT),
                emotion=fd.get("emotion", ""),
                has_face=fd.get("has_face", False),
                # 前景/背景合成（Planner 决策）
                fg_source_id=fd.get("fg_source_id", ""),
                bg_source_id=fd.get("bg_source_id", ""),
                composite_mode=fd.get("composite_mode", "none"),
                # 字幕自由配置
                subtitle_config=fd.get("subtitle_config", {}),
                # 扩展字段
                render_component=fd.get("render_component", "auto"),
                custom_render_config=fd.get("custom_render_config", {}),
                layers=fd.get("layers", []),
                canvas_width=fd.get("canvas_width", 1080),
                canvas_height=fd.get("canvas_height", 1920),
                ffmpeg_segment=fd.get("ffmpeg_segment", {}),
                # 结构迁移可溯源
                structure_function=fd.get("structure_function", ""),
                gene_shot_index=fd.get("gene_shot_index", -1),
                skill_refs=fd.get("skill_refs", []),
                adaptation=fd.get("adaptation", {}),
            ))

        return VideoScheme(
            id=f"scheme_{iteration}",
            title=scheme_data.get("title", ""),
            target_topic=target_topic,
            target_duration=scheme_data.get("target_duration", 60.0),
            structure_type=scheme_data.get("structure_type", ""),
            storyboard=frames,
            version=iteration + 1,
            status="draft" if iteration == 0 else "revised",
            canvas_width=scheme_data.get("canvas_width", 1080),
            canvas_height=scheme_data.get("canvas_height", 1920),
            render_hints=scheme_data.get("render_hints", {}),
            # 结构迁移可溯源
            gene_refs=scheme_data.get("gene_refs", []),
            selected_skill_refs=scheme_data.get("selected_skill_refs", []),
            loaded_skill_refs=scheme_data.get("loaded_skill_refs", []),
            declared_skill_refs=scheme_data.get(
                "declared_skill_refs", scheme_data.get("skill_refs_used", [])
            ),
            verified_skill_refs=scheme_data.get("verified_skill_refs", []),
            skill_refs_used=scheme_data.get("skill_refs_used", []),
            skill_evaluation=scheme_data.get("skill_evaluation", {}),
            adaptation_log=scheme_data.get("adaptation_log", []),
            # 音频配置
            audio_source_id=scheme_data.get("audio_source_id", ""),
            audio_config=scheme_data.get("audio_config", {}),
        )
