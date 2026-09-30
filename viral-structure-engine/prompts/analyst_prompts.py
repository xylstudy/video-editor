def build_shot_analysis_prompt(
    shot_index: int,
    start_time: float,
    end_time: float,
    total_duration: float,
    prev_frame_desc: str = "",
    motion_intensity: float = 0.0,
    color_stats: dict | None = None,
    visual_samples_only: bool = False,
) -> str:
    """Build a shot prompt for either native video or representative frames."""
    prev_context = f"前一镜头内容：{prev_frame_desc}" if prev_frame_desc else "这是视频的第一个镜头。"

    color_block = ""
    if color_stats:
        dom = color_stats.get("dominant_colors", [])
        dom_str = ", ".join(dom[:3]) if dom else "无"
        color_block = f"""- 色调均值: {color_stats.get('hue_mean', 0):.0f}° | 饱和度: {color_stats.get('saturation_mean', 0):.2f} | 明度: {color_stats.get('value_mean', 0):.2f}
- 主色调: {dom_str}"""

    media_note = (
        "你收到的是按时间顺序抽取的多帧画面，不包含可直接收听的音频。"
        "请根据多帧差异判断运镜，不要臆测语音、BGM或环境音；音频字段使用未知/无音频。"
        if visual_samples_only
        else "你收到了一段视频片段（含音频），需要同时从画面和声音两个维度分析。"
    )

    return f"""你是一位有8年经验的**爆款短视频**内容分析师，专门研究抖音和小红书上百万播放的Vlog。{media_note}

【输入信息】
这是Vlog的第{shot_index + 1}个镜头。
时间：{start_time:.1f}s - {end_time:.1f}s（时长 {end_time - start_time:.1f}s）
视频总时长：{total_duration:.1f}s
{prev_context}

【预处理数据】
- 运动强度: {motion_intensity:.2f}（0=完全静止, 1=剧烈运动/手持晃动）
{color_block}

请同时从**画面**和**声音**两个维度分析这段视频：

=== 第一步：画面内容识别（看） ===
- 主体是什么？从以下选：人物特写 / 人物中景 / 美食 / 风景 / 建筑 / 街道 / 室内环境 / 物品特写 / 文字卡 / 黑场/白场 / 动物 / 其他
- 人物情况：几人？正面/侧面/背影？表情（开心/平静/专注/惊喜/其他）？在做什么？
- 场景：室内/室外？地点类型（家/咖啡厅/餐厅/街道/景区/公园/办公室/商场/车内/其他）？
- 色调光影：暖还是冷？自然光还是人工光？光影质量（柔和/强烈/逆光/阴天/黄昏/夜景）？
- 画面中有无文字信息？

=== 第二步：音频内容识别（仅在输入确实包含音频时判断） ===
- **语音/旁白**：有人在说话吗？语速如何（快/中/慢）？语气语调是？（兴奋/平静/温柔/激动/幽默/严肃）？说话内容大概是什么？
- **背景音乐**：有BGM吗？风格（流行/电子/钢琴/吉他/鼓点/节奏感强/舒缓/无）？情绪匹配（和画面一致还是反差）？
- **环境音**：有什么环境音效（城市噪音/自然声/人群/交通/风声/水声/点击声/其他）？
- **整体听感**：这段音频在短视频中起什么作用（烘托情绪/提供信息/制造节奏/吸引注意力）？

=== 第三步：拍摄技法判断 ===
- 景别：特写 / 近景 / 中景 / 全景 / 远景
- 构图：居中 / 三分法 / 对角线 / 框架构图 / 留白 / 对称 / 俯拍 / 仰拍
- 运镜（你现在能看到连续画面，准确判断）：固定镜头 / 推 / 拉 / 平移 / 跟随 / 手持晃动 / 摇镜
- 画面质感：高清干净 / 有噪点 / 胶片感 / 滤镜 / 虚化 / 模糊或过曝

=== 第四步：Vlog结构功能判断 ===
这个镜头在爆款Vlog叙事中最可能承担什么功能？只选一个主功能：

- hook吸引：强烈视觉冲击或悬念，开头抓注意力
- 场景建立：展示地点环境，让观众知道"这是在哪"
- 日常铺展：展示做事过程，信息量中等，是Vlog的"填充内容"
- 情绪高点：视觉最美、最有感染力、最震撼或最温暖的画面，通常配合BGM高潮
- 人物表达：展示人物状态、情绪、反应或互动，增加"人格感"
- 信息传递：文字信息（字幕卡、标题、价格、地址等）
- 收尾定格：结尾画面，情绪落点、感悟感
- 过渡连接：信息量低，连接两个不同段落

请严格按以下JSON格式回答，不要添加任何其他文字：

{{
  "shot_index": {shot_index},
  "content": {{
    "main_subject": "主体描述（一句话）",
    "people_count": 0,
    "people_description": "人物描述（无则为空）",
    "scene_type": "场景类型",
    "indoor_outdoor": "indoor/outdoor/unknown",
    "color_temperature": "warm/cool/neutral",
    "light_quality": "光影质量描述"
  }},
  "audio": {{
    "has_speech": false,
    "speech_content": "旁白/对话内容概要（无则为空）",
    "speech_tone": "语气语调（兴奋/平静/温柔/激动/幽默/严肃/无）",
    "speech_pace": "语速（快/中/慢/无）",
    "has_bgm": false,
    "bgm_style": "BGM风格描述",
    "bgm_emotion": "BGM传递的情绪",
    "environment_sound": "环境音描述",
    "audio_role": "音频在镜头中的作用（烘托情绪/提供信息/制造节奏/吸引注意/无特别作用）"
  }},
  "technique": {{
    "shot_size": "close_up/medium_close/medium/medium_long/long",
    "composition": "构图方式",
    "camera_movement": "运镜方式",
    "visual_quality": "画面质感描述"
  }},
  "structure_role": {{
    "primary_function": "hook/scene_establish/daily_moment/emotion_peak/persona_expression/info_card/closing_moment/transition",
    "confidence": 0.0,
    "reasoning": "一句话说明判断依据（结合画面和音频）"
  }},
  "emotion": "核心情绪（一个词，如：活力/平静/温馨/震撼/期待/好奇/治愈/热血/忧郁/欢乐/燃/感动）",
  "audio_video_match": "音画配合度（perfect/good/neutral/poor/无音频）",
  "one_sentence_summary": "一句话描述这个镜头的画面+音频综合效果"
}}"""


def build_structure_analysis_prompt(
    duration: float,
    width: int,
    height: int,
    shot_count: int,
    shot_analyses_text: str,
    transcript: str,
    rhythm_data: dict | None = None,
    audio_data: dict | None = None,
) -> str:
    """结构分析 prompt — 基于逐镜头分析结果（含音频感知），用 Qwen3-OMNI-Flash 做文本分析"""
    transcript_section = (
        f"以下是视频的完整语音转写文本（旁白/口播/对话）：\n{transcript}"
        if transcript
        else "该视频无语音内容或语音转写为空。"
    )

    rhythm_block = ""
    if rhythm_data and rhythm_data.get("shot_count", 0) > 0:
        rhythm_block = f"""
【节奏分析数据】（基于镜头切分的客观数值）
- 平均镜头时长: {rhythm_data['avg_shot_duration']:.1f}s
- 最短镜头: {rhythm_data['min_shot_duration']:.1f}s | 最长镜头: {rhythm_data['max_shot_duration']:.1f}s
- 镜头时长标准差: {rhythm_data['std_shot_duration']:.2f}
- 前3秒镜头数: {rhythm_data['front_3s_cuts']} 个
- 首个镜头时长: {rhythm_data['first_shot_duration']:.1f}s
- {''.join(f'第{i*10+1}-{min((i+1)*10, int(duration))}秒: {c}个镜头  ' for i, c in enumerate(rhythm_data.get('cut_frequency_per_10s', [])))}"""
    audio_block = ""
    if audio_data:
        bpm = audio_data.get("bpm", "?")
        if isinstance(bpm, (int, float)):
            bpm_str = f"{bpm:.0f}"
        else:
            bpm_str = str(bpm)
        segments = audio_data.get("segments", [])
        seg_summary = ", ".join(
            f"{s['type']}: {s['start']:.0f}s-{s['end']:.0f}s"
            for s in segments[:8]
        )
        speech_r = audio_data.get("speech_ratio", "?")
        silence_r = audio_data.get("silence_ratio", "?")
        music_r = audio_data.get("music_ratio", "?")
        audio_block = f"""- BPM: {bpm_str}
    - 人声占比: {speech_r} | 静音占比: {silence_r} | 音乐占比: {music_r}
    - 分段: {seg_summary}
    - 能量分布: 共 {len(segments)} 个音频段"""




    return f"""你是一位抖音Vlog赛道的资深编导，看过上万条爆款短视频。你正在对一条Vlog做**结构拆解**，结果将用于"结构迁移"——把这条视频的成功方法论迁移到新内容上。

注意：你收到的逐镜头分析已经包含了音频感知信息（语速、语气、BGM风格、环境音等），请充分利用这些音画结合的分析来做全局判断。

【视频基础信息】
总时长：{duration:.1f}秒 | 分辨率：{width}x{height} | 镜头总数：{shot_count}个

【逐镜头分析结果（含音频感知）】（按时间顺序）
{shot_analyses_text}

【语音转写】
{transcript_section}
{rhythm_block}

【音频客观数据】（基于 ffmpeg/librosa 的声学分析）
{audio_block}

请完成以下七个分析任务，每个任务都是结构迁移的关键依据：

========================================
任务一：脚本段落结构
========================================
将视频按叙事逻辑划分为3-7个段落。每个段落有明确的叙事目的。

标注：段落目的、镜头范围、内容概要、建议时长、情绪基调、节奏特征。

特别注意：爆款短视频的段落划分常依赖**音画配合**——BGM变化点、语速转折、高潮段落的音画同步等。

========================================
任务二：节奏结构分析（重点利用音频信息）
========================================
1. 节奏曲线关键节点：6-10个时间点，每个标注强度（0-1）和设计意图
2. 节奏模式判断（快-慢-快/慢-快-慢/持续递增/全程卡点/平稳-爆发）
3. 高潮位置：在总时长的百分之多少处？
4. BGM推断：从语速、BGM风格和画面切换节奏综合推断BGM风格和BPM范围
5. 音频节奏和画面节奏的配合关系

========================================
任务三：包装结构分析
========================================
1. 字幕风格（字体、颜色、位置、动画、密度）
2. 标题/文字卡
3. 转场方式
4. 滤镜/调色风格
5. 其他视觉元素（贴纸、特效）

========================================
任务四：Hook策略分析
========================================
详细分析前3秒的hook策略——画面+声音如何配合抓住注意力

========================================
任务五：整体结构模式分类
========================================
从以下选：悬念前置型/情绪递进型/节奏卡点型/日常流水型/对比反转型/故事叙事型

========================================
任务六：关键技法提取
========================================
3-6个最核心的剪辑或拍摄技法标签，重点标注**音画配合技巧**

========================================
任务七：整轨音频结构分析（新增 — 输出到 audio_analysis 字段）
========================================
基于逐镜头分析中的音频信息（语速、BGM风格、环境音、情绪），综合推断整条视频的音频结构：

1. **整体音频特征**
   - 音乐风格（流行/电子/钢琴/中国风/摇滚/爵士/无BGM）
   - BPM范围（低<80 / 中80-120 / 高>120）
   - 整体情绪基调（治愈/燃/轻松/怀旧/活力/悬疑/温馨）
   - 音画配合模式（"跟随": BGM情绪跟随画面变化 / "对比": 音画反差 / "卡点": 踩点剪辑 / "氛围铺底": BGM一直铺底）

2. **能量曲线**（描述整条视频中音频能量的变化趋势，6-10个点）
   - 每个点：time位置 + energy强度(0-1) + 发生了什么（BGM变化/人声开始/静音/高潮）

3. **情绪分段**
   - 音频在时间线上分为几段不同情绪？
   - 每段：起止时间、情绪标签、音乐特征（乐器/节奏/音量）、和画面的配合方式

4. **高潮点**
   - 音频的"爆点"在什么位置？多少个？
   - 类型：drop/渐强/crescendo/静音爆发/人声高潮
   - 这些点对应画面上什么内容？

5. **可迁移性评估**
   - 这段音频是否适合迁移到其他视频？为什么？
   - 如果用来做新视频的BGM，需要注意什么？

请严格按以下JSON格式输出，不要添加任何其他文字：

{{
  "script_structure": [
    {{
      "index": 0,
      "purpose": "hook/人设展示/场景铺展/情绪递进/高潮爆发/价值输出/CTA互动",
      "shot_range": "镜头X - 镜头Y",
      "content_summary": "该段内容概要（含音频特征）",
      "duration_hint": 秒数,
      "emotion": "情绪基调",
      "rhythm": "快/中/慢"
    }}
  ],
  "rhythm_analysis": {{
    "curve_points": [
      {{"time": 0.0, "intensity": 0.0, "note": "设计意图说明"}}
    ],
    "pattern": "快-慢-快/慢-快-慢/持续递增/全程卡点/平稳-爆发",
    "climax_position_percent": 0,
    "front_3s_shot_count": 0,
    "estimated_bpm_range": "低-高",
    "bgm_style_guess": "BGM风格推测",
    "audio_visual_rhythm_match": "音画节奏配合评语"
  }},
  "packaging_analysis": {{
    "subtitle_font_guess": "推测的字体类型",
    "subtitle_color_and_stroke": "颜色和描边描述",
    "subtitle_position": "top/bottom/center",
    "subtitle_animation": "none/fade_in/typewriter/bounce/slide_in",
    "subtitle_density": "每秒大约X字",
    "title_cards": [
      {{"position_in_timeline": "大概在X秒处", "content": "文字卡内容", "style": "样式描述"}}
    ],
    "transitions_used": [
      {{"between": "镜头X到镜头Y", "type": "转场类型"}}
    ],
    "color_grade": "japanese_fresh/film_retro/cinematic/vivid/b_w/natural",
    "color_grade_detail": "调色风格详细描述",
    "stickers_effects": "贴纸和特效描述（无则为空）"
  }},
  "hook_strategy": {{
    "method": "悬念提问/视觉冲击/金句开头/反差对比/声音吸引/直接展示结果",
    "detail": "具体手法描述（含音画配合方式）",
    "effectiveness": "这个hook的效果评估（一句话）",
    "connection_to_body": "hook和后面内容的衔接是否自然"
  }},
  "structure_type": {{
    "category": "悬念前置型/情绪递进型/节奏卡点型/日常流水型/对比反转型/故事叙事型",
    "reasoning": "为什么归为此类",
    "core_characteristics": "核心特征（2-3句话）"
  }},
  "key_techniques": [
    "技法标签1：具体含义",
    "技法标签2：具体含义"
  ],
  "audio_analysis": {{
    "bpm": 0,
    "overall_mood": "音频整体情绪",
    "bgm_style": "音乐风格描述",
    "audio_video_match_pattern": "跟随/对比/卡点/氛围铺底",
    "energy_curve": [
      {{"time": 0.0, "energy": 0.0, "event": "发生了什么"}}
    ],
    "mood_segments": [
      {{"start": 0.0, "end": 0.0, "mood": "情绪", "energy": "低/中/高", "instruments": "乐器/节奏描述"}}
    ],
    "climax_points": [
      {{"time": 0.0, "type": "drop/crescendo/silence_break/vocal_climax"}}
    ],
    "energy_description": "一句话描述能量变化趋势",
    "migratability": "这段音频是否适合迁移到其他视频，以及注意事项"
  }},
  "narrative_type": "timeline/emotion/event",
  "persona_type": "voiceover/talking_head/back_figure/hands_only/mixed/no_persona",
  "persona_ratio": 0.0,
  "empty_shot_count": 0,
  "overall_emotion": "整条Vlog的情绪基调（一个词）",
  "overall_summary": "50字以内的整体结构总结"
}}"""
