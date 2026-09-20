import logging
from typing import Optional

from agents.base import BaseAgent, AgentRole, AgentResult
from prompts.creative_prompts import build_fill_strategy_prompt, build_text_card_content_prompt
from tools.video_tools import VideoTools
from tools.face_tools import FaceTools

logger = logging.getLogger(__name__)


class CreativeAgent(BaseAgent):
    def __init__(self, llm, video: Optional[VideoTools] = None,
                 face: Optional[FaceTools] = None):
        super().__init__(llm)
        self.role = AgentRole.CREATIVE
        self.video = video or VideoTools()
        self.face = face or FaceTools()
        self.system_prompt = """你是一位Vlog创意补全专家。当Vlog方案存在素材缺口时，你用最低成本产出最好的补全方案。

工具列表：
- plan_fill_strategy: 用LLM规划补全策略
- crop_material: 裁切素材的指定区域
- apply_ken_burns: 对图片做动态效果
- generate_text_card: 生成文字卡视频片段
- apply_speed_change: 变速处理
- generate_subtitle_overlay: 叠加创意字幕
- done: 任务完成

Vlog补全核心原则：
- 文字卡在Vlog中完全被接受
- Ken Burns让静态照片"活"起来
- 有脸的素材优先保留给hook和高潮"""

        self.register_tools({
            "plan_fill_strategy": self._plan_fill_strategy,
            "crop_material": self._crop_material,
            "apply_ken_burns": self._apply_ken_burns,
            "generate_text_card": self._generate_text_card,
            "apply_speed_change": self._apply_speed_change,
            "generate_subtitle_overlay": self._generate_subtitle_overlay,
            "done": self._done,
        })

    def _build_observe_prompt(self, state: dict, history: list) -> str:
        task = state.get("current_task", {})
        parts = [f"任务：{task.get('task_description', '')}"]
        inv = state.get("material_inventory")
        if inv:
            gaps = [g for g in (getattr(inv, "gaps", []) or []) if not getattr(g, "is_filled", False)]
            parts.append(f"未补全缺口：{len(gaps)}个")
        parts.append(f"已执行 {len(history)} 步")
        return "\n".join(parts)

    async def _plan_fill_strategy(self, gaps_desc: str, materials_desc: str, style_guide: str) -> dict:
        prompt = build_fill_strategy_prompt("", "", gaps_desc, materials_desc, style_guide)
        response = await self.llm.chat(prompt, response_format="json")
        return self.llm.parse_json(response)

    async def _crop_material(self, image_path: str, region: list[int]) -> dict:
        new_path = self.video.crop_image(image_path, tuple(region))
        return {"new_path": new_path, "strategy": "素材裁切复用"}

    async def _apply_ken_burns(self, image_path: str, motion_type: str = "zoom_in",
                                speed: str = "slow", focus_on_face: bool = False,
                                duration: float = 3.0) -> dict:
        focus_region = None
        if focus_on_face:
            try:
                focus_region = self.face.get_main_face_region(image_path)
            except Exception:
                pass
        new_path = self.video.apply_ken_burns(image_path, motion_type, speed, focus_region, duration)
        return {"new_path": new_path, "strategy": "Ken Burns"}

    async def _generate_text_card(self, text: str, bg_color: str = "black",
                                   font_style: str = "", text_color: str = "white",
                                   animation: str = "fade_in", duration: float = 3.0) -> dict:
        new_path = self.video.generate_text_card(text, bg_color, font_style, text_color, animation, duration)
        return {"new_path": new_path, "strategy": "文字卡替代"}

    async def _apply_speed_change(self, video_path: str, factor: float) -> dict:
        new_path = self.video.apply_speed_change(video_path, factor)
        return {"new_path": new_path, "strategy": f"变速{factor}x"}

    async def _generate_subtitle_overlay(self, video_path: str, subtitle_text: str) -> dict:
        new_path = self.video.overlay_subtitle(video_path, {"text": subtitle_text})
        return {"new_path": new_path, "strategy": "字幕叠加"}

    async def _done(self, summary: str) -> dict:
        return {"status": "done", "summary": summary}
