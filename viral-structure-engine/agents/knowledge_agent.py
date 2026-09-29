import json
import logging
from datetime import datetime
from pathlib import Path

from agents.base import AgentRole, BaseAgent
from prompts.knowledge_prompts import (
    build_knowledge_extract_prompt,
    build_knowledge_retrieve_prompt,
)
from models.knowledge import KnowledgeEntry, KnowledgeType
from models.trace import KNOWLEDGE_EXTRACT_PROMPT_VERSION

logger = logging.getLogger(__name__)


class KnowledgeAgent(BaseAgent):
    def __init__(self, llm=None):
        super().__init__(llm)
        self.role = AgentRole.KNOWLEDGE
        self.register_tools({
            "extract_knowledge": self.extract_knowledge,
            "retrieve_knowledge": self.retrieve_knowledge,
        })

    def _build_observe_prompt(self, state: dict, history: list) -> str:
        task_desc = state.get("task_description", "提炼视频结构知识")
        return f"任务：{task_desc}\n已执行 {len(history)} 步"

    async def extract_knowledge(
        self, video_structure_json: str, category: str, duration: float,
        trace_path: Path | None = None,
    ) -> list[KnowledgeEntry]:
        """从视频结构分析中提炼知识条目。

        trace_path 非 None 时，把提炼轨迹（prompt 版本、输入规模、产出条目）写到该文件。
        """
        prompt = build_knowledge_extract_prompt(
            video_structure_json, category, duration
        )
        result = await self.llm.chat(
            prompt, system="你是一位Vlog内容研究专家。请严格按照JSON格式输出。",
            response_format="json",
        )
        data = self.llm.parse_json(result)

        entries = []
        for i, entry_data in enumerate(data.get("knowledge_entries", [])):
            entry = KnowledgeEntry(
                id=f"k_{i}",
                type=KnowledgeType(entry_data["type"]),
                title=entry_data["title"],
                content=entry_data["content"],
                structured_data=entry_data.get("structured_data", {}),
                tags=entry_data.get("tags", []),
                applicable_vlog_types=entry_data.get("applicable_vlog_types", []),
                best_when=entry_data.get("best_when", ""),
                confidence=entry_data.get("confidence", 0.0),
                source_summary=entry_data.get("source_summary", ""),
            )
            entries.append(entry)

        if trace_path is not None:
            self._save_extract_trace(trace_path, video_structure_json, entries)

        return entries

    def _save_extract_trace(self, trace_path: Path, input_json: str,
                            entries: list[KnowledgeEntry]) -> None:
        """把本次知识提炼的轨迹落盘，供溯源与效果统计。"""
        try:
            trace = {
                "prompt_version": KNOWLEDGE_EXTRACT_PROMPT_VERSION,
                "model": getattr(self.llm, "model", ""),
                "llm_client": "LLMTools",
                "input_size_chars": len(input_json),
                "entry_count": len(entries),
                "entries": [e.to_dict() for e in entries],
                "created_at": datetime.now().isoformat(),
            }
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.write_text(
                json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(f"知识提炼轨迹已保存: {trace_path}")
        except Exception as e:
            # 轨迹保存失败不影响提炼结果
            logger.warning(f"知识提炼轨迹保存失败: {e}")

    async def retrieve_knowledge(
        self,
        target_topic: str,
        target_info: str,
        material_summary: str,
        user_preferences: str,
        candidate_entries: str,
    ) -> dict:
        prompt = build_knowledge_retrieve_prompt(
            target_topic, target_info, material_summary,
            user_preferences, candidate_entries,
        )
        result = await self.llm.chat(
            prompt, system="你是一位Vlog创作顾问。请严格按照JSON格式输出。",
            response_format="json",
        )
        return self.llm.parse_json(result)
