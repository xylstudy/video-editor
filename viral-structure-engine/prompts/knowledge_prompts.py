def build_knowledge_extract_prompt(
    video_structure_json: str,
    category: str,
    duration: float,
) -> str:
    return f"""你是一位Vlog内容研究专家，负责从具体案例中提炼可复用的创作知识。

【爆款Vlog分析结果】
{video_structure_json}

视频品类：{category}
时长：{duration}秒

请从以下维度提炼知识条目：
- 结构模板
- Hook技法
- 节奏模式
- 情绪设计
- 包装风格
- 独立特效（effect_type）：贴纸属于特效。卡通五官、星星/怒气涂鸦、文字弹入、箭头、撕纸描边、主体残影等须分别提炼，不能只写入包装组合。

特效条目必须有分析结果中的原始证据。structured_data 保留 effect_key、evidence（镜头索引、绝对起止秒、主体、位置、运动路径、遮罩方式、parameters）。同一种效果的重复出现合并为多条 evidence；不同贴纸手法分别入库。未观察到的效果不要补造。

{{
  "knowledge_entries": [
    {{
      "type": "structure_template/hook_technique/rhythm_pattern/emotion_design/packaging_style/effect_type",
      "title": "知识标题",
      "content": "自然语言描述（200字以内）",
      "structured_data": {{}},
      "tags": ["品类标签", "风格标签"],
      "applicable_vlog_types": ["适用类型"],
      "best_when": "最佳使用条件",
      "confidence": 0.0,
      "source_summary": "来源视频的一句话信息"
    }}
  ]
}}"""


def build_knowledge_retrieve_prompt(
    target_topic: str,
    target_info: str,
    material_summary: str,
    user_preferences: str,
    candidate_entries: str,
) -> str:
    return f"""你是一位Vlog创作顾问，负责从知识库中为新的创作任务找到最相关的参考知识。

【新的Vlog创作需求】
主题：{target_topic}
详情：{target_info}
素材概况：{material_summary}
用户偏好：{user_preferences}

【候选知识条目】
{candidate_entries}

请选出最相关的3-5条知识：

{{
  "selected_entries": [
    {{
      "knowledge_id": "条目ID",
      "title": "知识标题",
      "relevance_score": 0.0,
      "why_relevant": "为什么相关",
      "how_to_apply": "如何应用",
      "caution": "注意事项"
    }}
  ],
  "overall_strategy": "整体创作策略（3-5句话）"
}}"""
