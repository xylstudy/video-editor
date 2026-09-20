import json
import logging
from typing import Optional

from agents.base import BaseAgent, AgentRole, AgentResult
from prompts.reviewer_prompts import build_review_prompt

logger = logging.getLogger(__name__)


class ReviewerAgent(BaseAgent):
    def __init__(self, llm):
        super().__init__(llm)
        self.role = AgentRole.REVIEWER
        self.system_prompt = """你是一位严苛但公正的Vlog结构迁移审核专家。

你同时评价两类指标：
1. Gene/Structure Fidelity —— 迁移得"像不像"Reference（hook结构、镜头/时长关系、节奏曲线、情绪弧线、高潮/Ending位置、核心镜头功能是否保持）
2. Adaptation/Editing Quality —— 在当前素材上"剪得好不好"（素材匹配是否合理、是否强行模仿、转场是否匹配、节奏是否自然、情绪是否连贯、字幕包装是否合理、素材覆盖）

两类问题反馈性质不同：fidelity 问题要回 Planner 恢复 Gene 结构；quality 问题要在不破坏 Gene 的前提下优化剪辑。

审核标准：
- Vlog生死在前3秒，hook不行后面全白搭
- 需要"呼吸感"——不能全程快切也不能全程慢
- 情绪一致性比内容丰富度更重要
- 最怕"假"和"刻意"
- 文字卡在Vlog中完全合法
- 每个用户素材都必须被用到

工具列表：
- review_scheme: 对方案做双维度（Fidelity + Quality）评估
- done: 任务完成"""

        self.register_tools({
            "review_scheme": self._review_scheme,
            "done": self._done,
        })

    def _build_observe_prompt(self, state: dict, history: list) -> str:
        task = state.get("current_task", {})
        parts = [f"任务：{task.get('task_description', '审核方案')}"]
        scheme = state.get("scheme")
        if scheme:
            sb = getattr(scheme, "storyboard", [])
            parts.append(f"方案：{len(sb)}个分镜")
        parts.append(f"已执行 {len(history)} 步")
        return "\n".join(parts)

    async def _review_scheme(self, source_structure_summary: str, scheme_json: str,
                              material_coverage_desc: str,
                              material_list_desc: str = "",
                              transition_summary: str = "",
                              gene_json: str = "") -> dict:
        prompt = build_review_prompt(
            source_structure_summary, scheme_json, material_coverage_desc,
            material_list_desc=material_list_desc,
            transition_summary=transition_summary,
            gene_json=gene_json,
        )
        response = await self.llm.chat(prompt, response_format="json")
        return self.llm.parse_json(response)

    async def _done(self, summary: str) -> dict:
        return {"status": "done", "summary": summary}
