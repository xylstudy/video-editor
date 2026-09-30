import json
import logging
from typing import Optional

from agents.base import BaseAgent, AgentRole, AgentResult
from prompts.reviewer_prompts import build_review_prompt

logger = logging.getLogger(__name__)


class ReviewerAgent(BaseAgent):
    SCORE_WEIGHTS = {
        "structure_fidelity": 1.0,
        "hook_appeal": 1.5,
        "content_adaptation": 1.0,
        "rhythm": 1.0,
        "emotion_coherence": 1.2,
        "gap_filling_quality": 1.0,
        "packaging_consistency": 0.8,
        "completeness": 0.5,
        "subtitle_quality": 0.8,
        "material_coverage": 1.2,
    }

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
        for attempt in range(2):
            retry_instruction = ""
            if attempt:
                retry_instruction = """

上一次回答不是完整合法 JSON。请重新输出紧凑 JSON：不得使用 Markdown；
每个 reason 不超过 40 个汉字；issues/highlights 各最多 2 条；suggestions 最多 3 条；
必须闭合所有括号，并将总输出控制在 4000 tokens 内。
"""
            response = await self.llm.chat(
                prompt + retry_instruction,
                response_format="json",
                max_tokens=4096,
            )
            try:
                return self._normalise_review(self.llm.parse_json(response))
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Reviewer JSON 解析失败 (%d/2): %s", attempt + 1, exc)
                if attempt:
                    raise
        raise RuntimeError("Reviewer JSON 解析失败")

    @classmethod
    def _normalise_review(cls, review: dict) -> dict:
        """Make the 10-point dimensions and 100-point totals deterministic."""
        scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
        weighted_sum = 0.0
        weight_sum = 0.0
        for name, expected_weight in cls.SCORE_WEIGHTS.items():
            item = scores.get(name)
            if not isinstance(item, dict):
                continue
            raw_score = item.get("score")
            if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
                continue
            score = max(0.0, min(10.0, float(raw_score)))
            item["score"] = int(score) if score.is_integer() else round(score, 2)
            item["weight"] = expected_weight
            weighted_sum += score * expected_weight
            weight_sum += expected_weight

        if weight_sum:
            total_score = round(weighted_sum / weight_sum * 10, 1)
        else:
            raw_total = review.get("total_score", 0)
            total_score = float(raw_total) if isinstance(raw_total, (int, float)) else 0.0
            if 0 <= total_score <= 10:
                total_score *= 10
            total_score = round(max(0.0, min(100.0, total_score)), 1)
        review["total_score"] = total_score

        for section_name in ("fidelity", "quality"):
            section = review.get(section_name)
            if not isinstance(section, dict):
                continue
            value = section.get("overall")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = float(value)
                if 0 <= value <= 10:
                    value *= 10
                section["overall"] = round(max(0.0, min(100.0, value)), 1)

        review["pass"] = bool(total_score >= 75 and not review.get("force_iterate", False))
        return review

    async def _done(self, summary: str) -> dict:
        return {"status": "done", "summary": summary}
