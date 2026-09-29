import json
import logging
from pathlib import Path
from typing import Optional

from agents.base import BaseAgent, AgentRole, AgentResult
from prompts.material_prompts import (
    build_image_analysis_prompt,
    build_video_analysis_prompt,
    build_text_analysis_prompt,
    build_gap_check_prompt,
)
from models.material import MaterialItem, MaterialGap, MaterialInventory, MaterialType, MaterialQuality
from models.video_structure import ShotType
from tools.video_tools import VideoTools
from tools.face_tools import FaceTools

logger = logging.getLogger(__name__)


class MaterialManagerAgent(BaseAgent):
    def __init__(self, llm, video: Optional[VideoTools] = None,
                 face: Optional[FaceTools] = None):
        super().__init__(llm)
        self.role = AgentRole.MATERIAL_MANAGER
        self.video = video or VideoTools()
        self.face = face or FaceTools()
        self.system_prompt = """你是一位Vlog素材管家，负责素材入库分析和缺口识别。

能力一：素材入库 — 对用户上传的图片/视频/文本做内容理解、质量评估、标签分类
能力二：缺口识别 — 检查方案的分镜表，判断哪些有素材、哪些是缺口

工具列表：
- analyze_image: 分析单张图片的内容、质量、Vlog适用性
- analyze_video_material: 分析一段视频素材，提取高光片段
- analyze_text: 分析文本素材的金句、情绪
- check_gaps: 检查方案中哪些分镜缺少合适的素材
- done: 任务完成"""

        self.register_tools({
            "analyze_image": self._analyze_image,
            "analyze_video_material": self._analyze_video_material,
            "analyze_text": self._analyze_text,
            "check_gaps": self._check_gaps,
            "done": self._done,
        })

    def _build_observe_prompt(self, state: dict, history: list) -> str:
        task = state.get("current_task", {})
        desc = task.get("task_description", "")
        inv = state.get("material_inventory")
        if inv:
            items = getattr(inv, "items", getattr(inv, "materials", []))
            gaps = getattr(inv, "gaps", [])
            desc += f"\n当前素材库：{len(items)}个素材，{len(gaps)}个缺口"
        return f"任务：{desc}\n已执行 {len(history)} 步"

    async def _analyze_image(self, material_id: str, image_path: str,
                              target_topic: str, topic_description: str = "") -> dict:
        prompt = build_image_analysis_prompt(material_id, target_topic, topic_description)
        response = await self.llm.chat_with_images(prompt, [image_path], response_format="json")
        result = self.llm.parse_json(response)
        try:
            result["has_face"] = self.face.has_face(image_path)
            if result["has_face"]:
                result["main_face_region"] = self.face.get_main_face_region(image_path)
        except Exception:
            result["has_face"] = False
        return result

    async def _analyze_video_material(self, material_id: str, video_path: str,
                                       target_topic: str) -> dict:
        info = self.video.get_video_info(video_path)
        frames = []
        for t in [i * 2 for i in range(int(info["duration"] / 2) + 1)]:
            try:
                fp = self.video.extract_frame(video_path, t)
                frames.append(f"{t}s: (frame at {fp})")
            except Exception:
                continue
        prompt = build_video_analysis_prompt(material_id, target_topic,
                                             info["duration"], "\n".join(frames[:20]))
        response = await self.llm.chat(prompt, response_format="json")
        result = self.llm.parse_json(response)
        result["_video_info"] = info
        return result

    async def _analyze_text(self, target_topic: str, text_content: str) -> dict:
        prompt = build_text_analysis_prompt(target_topic, text_content)
        response = await self.llm.chat(prompt, response_format="json")
        return self.llm.parse_json(response)

    async def _check_gaps(self, scheme_summary: str, inventory_summary: str) -> dict:
        prompt = build_gap_check_prompt(scheme_summary, inventory_summary, "")
        response = await self.llm.chat(prompt, response_format="json")
        return self.llm.parse_json(response)

    async def _done(self, summary: str) -> dict:
        return {"status": "done", "summary": summary}

    def build_material_item(self, mat_id: str, mat_type: MaterialType, path: str,
                             analysis: dict) -> MaterialItem:
        quality_map = {"high": MaterialQuality.HIGH, "medium": MaterialQuality.MEDIUM,
                       "low": MaterialQuality.LOW, "unusable": MaterialQuality.UNUSABLE}
        q = quality_map.get(analysis.get("quality", {}).get("overall", "medium"), MaterialQuality.MEDIUM)

        if mat_type == MaterialType.IMAGE:
            content = analysis.get("content", {})
            return MaterialItem(
                id=mat_id, type=mat_type, path=path,
                description=analysis.get("one_sentence_summary", content.get("main_subject", "")),
                main_subject=content.get("main_subject", ""),
                tags=analysis.get("tags", []), quality=q,
                has_face=analysis.get("has_face", False),
                face_count=content.get("people_count", 0),
                emotion_label=analysis.get("emotion_label", ""),
            )
        elif mat_type == MaterialType.VIDEO:
            info = analysis.get("_video_info", {})
            return MaterialItem(
                id=mat_id, type=mat_type, path=path,
                description=analysis.get("description", ""),
                tags=analysis.get("tags", []), quality=q,
                duration=info.get("duration", 0),
                width=info.get("width", 0), height=info.get("height", 0),
                emotion_label=analysis.get("emotion_label", ""),
                highlight_clips=analysis.get("highlight_clips", []),
            )
        else:
            return MaterialItem(
                id=mat_id, type=mat_type, path=path,
                description=analysis.get("description", ""),
                tags=analysis.get("tags", []), quality=q,
                emotion_label=analysis.get("emotion", ""),
            )
