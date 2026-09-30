def build_review_prompt(
    source_structure_summary: str,
    scheme_json: str,
    material_coverage_desc: str,
    material_list_desc: str = "",
    transition_summary: str = "",
    gene_json: str = "",
) -> str:
    """Reference-guided 审核：同时评价两类指标。

    1) Gene / Structure Fidelity —— 迁移得"像不像" Reference（结构是否保持）
    2) Adaptation / Editing Quality —— 在当前素材上"剪得好不好"（适配是否合理）

    两类问题反馈性质不同：fidelity 问题要回 Planner 恢复 Gene 结构；
    quality 问题要在不破坏 Gene 的前提下优化剪辑。
    """
    gene_section = f"""
━━━━━━━━━━━━━━━━━━━━━━━━
零、参考视频结构基因（Gene —— 结构保真的唯一基准）
━━━━━━━━━━━━━━━━━━━━━━━━
{gene_json}
""" if gene_json else ""

    return f"""你是一位严苛但公正的 Vlog 结构迁移审核专家。你审核的不是"视频好不好看"，而是：

  迁移得"像不像" Reference（Gene 结构保真），以及"像了之后在当前素材上剪得好不好"（适配质量）。

━━━━━━━━━━━━━━━━━━━━━━━━
一、原始爆款的结构模式（含基因）
━━━━━━━━━━━━━━━━━━━━━━━━
{source_structure_summary}
{gene_section}
━━━━━━━━━━━━━━━━━━━━━━━━
二、新Vlog方案
━━━━━━━━━━━━━━━━━━━━━━━━
{scheme_json}

━━━━━━━━━━━━━━━━━━━━━━━━
三、素材覆盖情况
━━━━━━━━━━━━━━━━━━━━━━━━
{material_coverage_desc}

━━━━━━━━━━━━━━━━━━━━━━━━
四、用户素材清单（每个都必须用上）
━━━━━━━━━━━━━━━━━━━━━━━━
{material_list_desc}

━━━━━━━━━━━━━━━━━━━━━━━━
五、镜头切换情况
━━━━━━━━━━━━━━━━━━━━━━━━
{transition_summary}

请从两组维度评估。

=== A 组：Gene / Structure Fidelity（迁移得像不像 Reference）===

维度 A1：Hook 结构保持（weight 1.5）★★★
  前 3 秒是否保持 Reference 的 hook 结构（悬念/冲击/金句）？开场的结构功能是否被迁移。

维度 A2：镜头数量 / 时长关系（weight 1.0）
  镜头数与时长比例是否合理继承了 Reference 的节奏骨架。

维度 A3：节奏曲线接近度（weight 1.0）
  快慢交替、高潮位置、节奏模式是否接近 Reference 的 rhythm_pattern / climax_position_ratio。

维度 A4：情绪弧线保持（weight 1.2）★★
  情绪起点→递进→高潮→回落→余韵是否沿 Reference 的情绪弧走。

维度 A5：高潮 / Ending 关键结构位置（weight 1.2）★★
  高潮与收尾的关键结构位置是否与 Reference 一致。

维度 A6：核心镜头功能迁移（weight 1.2）★★
  establishing / climax / closing 等核心镜头功能是否被迁移，而非被丢弃或替换成无关内容。

=== B 组：Adaptation / Editing Quality（在当前素材上剪得好不好）===

维度 B1：素材匹配合理性（weight 1.2）★★★
  用户素材是否按"功能/情绪"合理匹配到各镜头；是否出现为了模仿原片而强行使用不合适素材。

维度 B2：转场是否符合场景（weight 0.8）
  转场是否与画面内容、情绪、节奏匹配（高潮用冲击转场、收尾用柔和转场）。

维度 B3：节奏自然度（weight 1.0）
  快慢是否自然，有无"呼吸感"，是否全程快切或全程慢。

维度 B4：情绪连贯性（weight 1.0）
  情绪是否连贯，有无情绪断裂或刻意煽情。

维度 B5：字幕 / 包装合理性（weight 0.8）
  字幕是否有且差异化、位置不遮挡关键画面、调色/包装风格统一。

维度 B6：素材覆盖率（weight 1.2）★★★
  每个用户素材是否都被用到（一镜多图/拼贴/画中画也算）；有无漏素材或重复用清单外素材。

────────────────────────

请把上述观察归并为下面固定的 10 个评分维度，每个维度给出 0-10 分和一句话理由。
fidelity 与 quality 只做 overall 汇总，不要再次展开重复子维度。所有 reason 不超过
40 个汉字，issues/highlights 各最多 2 条，suggestions 最多 3 条，总输出不超过 4000 tokens。

{{
  "scores": {{
    "structure_fidelity": {{"score": 0, "weight": 1.0, "reason": "一句话理由"}},
    "hook_appeal": {{"score": 0, "weight": 1.5, "reason": "一句话理由"}},
    "content_adaptation": {{"score": 0, "weight": 1.0, "reason": "一句话理由"}},
    "rhythm": {{"score": 0, "weight": 1.0, "reason": "一句话理由"}},
    "emotion_coherence": {{"score": 0, "weight": 1.2, "reason": "一句话理由"}},
    "gap_filling_quality": {{"score": 0, "weight": 1.0, "reason": "一句话理由"}},
    "packaging_consistency": {{"score": 0, "weight": 0.8, "reason": "一句话理由"}},
    "completeness": {{"score": 0, "weight": 0.5, "reason": "一句话理由"}},
    "subtitle_quality": {{"score": 0, "weight": 0.8, "reason": "一句话理由"}},
    "material_coverage": {{"score": 0, "weight": 1.2, "reason": "一句话理由"}}
  }},
  "fidelity": {{
    "overall": 0,
    "issues": ["结构保真相关问题1", "问题2"]
  }},
  "quality": {{
    "overall": 0,
    "issues": ["适配质量相关问题1", "问题2"]
  }},
  "total_score": 0,
  "pass": false,
  "force_iterate": false,
  "feedback_type": "fidelity/quality/mixed",
  "top_3_issues": ["问题1", "问题2"],
  "top_3_highlights": ["亮点1", "亮点2"],
  "suggestions": [
    {{
      "category": "fidelity/quality",
      "target_dimension": "维度名称",
      "current_problem": "当前问题",
      "suggested_change": "建议修改",
      "priority": "high/medium/low"
    }}
  ],
  "one_line_verdict": "一句话总评"
}}

计分口径：scores 中每项是 0-10 分；fidelity.overall、quality.overall 和 total_score
全部是 0-100 分。total_score 必须按 scores 的权重计算百分制加权平均，禁止输出 0-10 的小数。
total_score >= 75 且不存在必须迭代的问题时 pass=true，否则 pass=false。

判定口径：
- 若主要问题是"结构没迁移过来"（hook 丢了/高潮位置错了/核心功能被换掉）→ feedback_type="fidelity"。
- 若结构基本像 Reference，但素材匹配/转场/情绪连贯/字幕包装剪得不好 → feedback_type="quality"。
- 两者都有 → "mixed"。

重要：只输出 JSON，不要包含任何解释文字，不要使用 markdown 代码块，直接输出纯 JSON。"""
