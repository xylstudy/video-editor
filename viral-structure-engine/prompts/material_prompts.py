MATERIAL_VIDEO_PROMPT_VERSION = "2.0.0"


def build_image_analysis_prompt(
    material_id: str,
    target_topic: str,
    topic_description: str,
) -> str:
    return f"""你是一位短视频素材管理专家，负责评估用户上传的图片在Vlog创作中的价值。

【背景信息】
用户要制作的Vlog主题：{target_topic}
主题描述：{topic_description}
素材ID：{material_id}

【你的任务】
分析这张图片，回答以下问题：

=== 第一步：内容识别 ===
- 主体内容是什么？
- 有没有人物？如果有：几个人？什么状态？
- 场景是什么？
- 画面给你的整体感觉是什么？

=== 第二步：Vlog适用性评估 ===
这张图最适合放在Vlog的什么位置？

=== 第三步：质量评估 ===
画质、构图、光影、是否需要后期处理

=== 第四步：情绪和标签 ===

请严格按以下JSON格式回答：

{{
  "material_id": "{material_id}",
  "content": {{
    "main_subject": "主体描述",
    "people_count": 0,
    "people_description": "人物描述（无人物则为空）",
    "scene_type": "场景类型",
    "atmosphere": "画面整体感觉"
  }},
  "vlog_applicability": [
    {{
      "position": "hook/scene_establish/daily_moment/emotion_peak/persona_expression/info_card/closing",
      "confidence": 0.0,
      "reasoning": "为什么适合这个位置"
    }}
  ],
  "quality": {{
    "overall": "high/medium/low",
    "resolution": "high/medium/low",
    "composition": "good/okay/needs_crop/poor",
    "light": "golden_hour/soft/sufficient/dim/backlit/artificial",
    "needs_processing": false,
    "suggested_processing": ["处理建议"]
  }},
  "emotion_label": "情绪标签",
  "tags": ["标签1", "标签2", "标签3"],
  "best_as_hook_subtitle": "如果用作hook，可以配什么字幕？（不超过15字）",
  "overall_vlog_value": "high/medium/low"
}}"""


def build_video_analysis_prompt(
    material_id: str,
    target_topic: str,
    duration: float,
    frame_descriptions: str,
) -> str:
    return f"""你是一位短视频素材管理专家，擅长从一段原始视频素材中快速提取Vlog可用的高光片段。

【分析边界】
只提取素材本身可观察到的内容、质量、情绪、运动和可用时间段，不要根据目标主题猜测画面内容。
具体主题匹配由后续 Planner 单独完成，因此这份素材基因应能被不同任务复用。

【素材信息】
素材ID：{material_id}
视频时长：{duration:.1f}秒

以下是该视频的关键帧描述：
{frame_descriptions}

请完成以下分析：

=== 第一步：内容段落划分 ===
=== 第二步：高光片段提取（最多5个） ===
=== 第三步：整体评估 ===

请严格按以下JSON格式回答：

{{
  "material_id": "{material_id}",
  "total_duration": {duration},
  "content_segments": [
    {{
      "index": 0,
      "start": 0.0,
      "end": 0.0,
      "description": "内容描述",
      "stability": "stable/slight_shake/heavy_shake",
      "density": "high/medium/low"
    }}
  ],
  "highlight_clips": [
    {{
      "start": 0.0,
      "end": 0.0,
      "duration": 0.0,
      "description": "内容描述",
      "why_valuable": "为什么有价值",
      "suggested_vlog_role": "hook/scene_establish/daily_moment/emotion_peak/persona_expression/closing",
      "confidence": 0.0
    }}
  ],
  "overall_assessment": {{
    "quality": "high/medium/low",
    "has_usable_clips": true,
    "usable_clip_count": 0,
    "audio_to_keep": "none/ambient/voice/music",
    "problem_segments": [
      {{"start": 0.0, "end": 0.0, "reason": "问题原因"}}
    ]
  }},
  "emotion_label": "整段视频的情绪标签",
  "tags": ["标签1", "标签2"],
  "overall_vlog_value": "high/medium/low"
}}"""


def build_text_analysis_prompt(
    target_topic: str,
    text_content: str,
) -> str:
    return f"""你是一位Vlog文案策划师，擅长从用户随手写的文字中提取Vlog创作的灵感和素材。

【背景信息】
Vlog主题：{target_topic}
用户提供的文字素材：
---
{text_content}
---

请分析这段文字：

1. 核心信息：最核心的1-3个信息点是什么？
2. 可用的金句/名场面：有没有可以用作旁白、字幕、标题的句子？
3. 情绪基调：这段文字传递的主要情绪是什么？
4. Vlog位置建议：如果这段文字要出现在Vlog中，最适合什么位置？
5. 标签：3-5个标签

请严格按以下JSON格式回答：

{{
  "key_points": ["信息点1", "信息点2"],
  "golden_quotes": [
    {{"quote": "金句原文", "usage": "建议使用方式（旁白/字幕/标题/文字卡）"}}
  ],
  "emotion": "情绪基调",
  "suggested_vlog_position": "开头/中间/结尾/贯穿全片",
  "tags": ["标签1", "标签2", "标签3"],
  "overall_value": "high/medium/low"
}}"""


def build_gap_check_prompt(
    scheme_json: str,
    inventory_json: str,
    topic: str,
) -> str:
    return f"""你是一位Vlog素材缺口分析专家。请分析以下Vlog方案和可用素材，识别出存在素材缺口的分镜。

一个"缺口"是指：方案中的某个分镜没有对应的可用素材，或者素材质量不足以支持该分镜的需求。

【Vlog方案】
{scheme_json}

【可用素材清单】
{inventory_json}

【Vlog主题】
{topic}

请对每个分镜判断是否有缺口，并按优先级排序：

{{
  "gaps": [
    {{
      "slot_index": 0,
      "shot_type": "hook/scene_establish/...",
      "required_duration": 秒数,
      "description": "缺口描述",
      "priority": 1-5（越高越需要补）,
      "gap_type": "missing素材缺失/quality质量不足/emotion情绪不匹配/face缺少人脸"
    }}
  ],
  "critical_gaps_count": 0,
  "total_gaps_count": 0,
  "can_assemble": true,
  "summary": "缺口概况总结"
}}"""
