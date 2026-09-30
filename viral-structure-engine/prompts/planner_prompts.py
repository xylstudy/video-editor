import json

from config.motion_catalog import build_motion_catalog_prompt


def build_skeleton_extract_prompt(
    structure_summary: str,
    target_topic: str,
    target_info: str,
    structure_analysis: str = "",
) -> str:
    extra = ""
    if structure_analysis:
        sa = json.loads(structure_analysis) if isinstance(structure_analysis, str) else structure_analysis
        acts = sa.get("script_structure", [])
        rhythm = sa.get("rhythm_analysis", {})
        packaging = sa.get("packaging_analysis", {})
        hook = sa.get("hook_strategy", {})
        st = sa.get("structure_type", {})
        audio_info = sa.get("audio_analysis", {})

        acts_text = "\n".join(
            f"  段落{a['index']}: {a['purpose']} ({a.get('shot_range', '?')}) | 情绪:{a['emotion']} 节奏:{a['rhythm']}"
            for a in acts
        )
        extra = f"""
【5段式脚本结构】
{acts_text}

【节奏分析】
  模式: {rhythm.get('pattern', '?')} | 高潮位置: {rhythm.get('climax_position_percent', '?')}%
  BPM范围: {rhythm.get('estimated_bpm_range', '?')} | 开场3秒镜头数: {rhythm.get('front_3s_shot_count', '?')}
  BGM风格: {rhythm.get('bgm_style_guess', '?')}

【音频分析】（整轨）
  BPM: {audio_info.get('bpm', '?')} | 整体情绪: {audio_info.get('overall_mood', '?')}
  音画配合模式: {audio_info.get('audio_video_match_pattern', '?')}
  能量变化: {audio_info.get('energy_description', '?')}

【包装风格】
  字幕位置: {packaging.get('subtitle_position', '?')} | 调色: {packaging.get('color_grade_detail', '?')}
  标题卡: {packaging.get('title_cards', [])}

【Hook策略】
  方式: {hook.get('method', '?')} | {hook.get('effectiveness', '')}

【结构类型】
  类型: {st.get('category', '?')} | 特征: {st.get('core_characteristics', '')}

【关键技法】
{chr(10).join('  - ' + t for t in sa.get('key_techniques', []))}
"""

    return f"""你是一位Vlog结构迁移专家。你的任务是从一条爆款Vlog的结构分析结果中，提取出可迁移的"结构骨架"——这个骨架不依赖原始内容，只依赖结构模式本身。

【爆款Vlog结构分析】
{structure_summary}
{extra}
【新Vlog信息】
主题：{target_topic}
详情：{target_info}

请提取结构骨架——保留结构模式，去除具体内容。骨架要足够抽象以适用于新内容，又要足够具体以指导剪辑。

注意：音频分析结果已包含在结构分析中。骨架需要保留原始视频的 **音画配合模式**（如BPM范围、能量曲线形状、高潮位置），使迁移后的视频可以匹配合适的音频风格。

{{
  "structure_type": "结构类型",
  "narrative_type": "叙事类型",
  "script_template": [
    {{
      "index": 0,
      "purpose": "段落目的",
      "suggested_duration_ratio": 0.0,
      "emotion": "情绪基调",
      "rhythm": "快/中/慢",
      "content_template": "内容描述模板（用占位符代替具体内容）"
    }}
  ],
  "rhythm_template": {{
    "pattern": "节奏模式",
    "climax_position_ratio": 0.0,
    "front_3s_shot_count_hint": 0,
    "bpm_style_hint": "BPM风格提示"
  }},
  "packaging_template": {{
    "subtitle": {{
      "position": "位置",
      "animation": "动画风格",
      "style": "样式描述"
    }},
    "transitions": ["偏好的转场类型"],
    "color_grade_hint": "调色风格提示"
  }},
  "hook_template": {{
    "method": "hook方式",
    "strategy_description": "策略描述"
  }},
  "key_techniques_preserved": ["要保留的技法标签"],
  "migration_notes": "迁移时需要特别注意的事项",
  "audio_template": {{
    "bpm_range": "匹配的BPM范围",
    "energy_curve_shape": "能量曲线形状描述",
    "climax_position_ratio": 0.0,
    "audio_video_relationship": "音画关系（跟随/对比/卡点/氛围铺底）"
  }}
}}"""


def _format_skill_context(skill_context) -> str:
    """把 SkillRouter.collect() 的结果（[{name, content}]）或已拼接字符串，格式化为 prompt 片段。"""
    if not skill_context:
        return ""
    if isinstance(skill_context, str):
        return skill_context
    blocks = []
    for ref in skill_context:
        name = ref.get("name", "") if isinstance(ref, dict) else getattr(ref, "name", "")
        content = ref.get("content", "") if isinstance(ref, dict) else getattr(ref, "content", "")
        blocks.append(f"===== Skill 参考：{name}.md =====\n{content}")
    return "\n\n".join(blocks)


def build_scheme_generate_prompt(
    skeleton_json: str,
    inventory_json: str,
    target_topic: str,
    target_info: str,
    preferences: str,
    material_type_hint: str = "",
    audio_data: str = "",                    # Analyst 的音频分析结果
    gene_json: str = "",                     # Reference Gene（本次要迁移的结构，硬约束为主）
    skill_context=None,                      # 按需加载的 Editing Skill（[{name, content}] 或字符串）
) -> str:
    material_note = ""
    if material_type_hint:
        material_note = f"\n【素材类型说明】\n{material_type_hint}\n请合理混合使用视频素材（type: video）和图片素材（type: image）。视频片段可直接使用，图片需做 Ken Burns 运镜。高潮段落优先用视频素材。"

    gene_section = ""
    if gene_json:
        gene_section = f"""
【参考视频结构基因（Reference Gene — 本次迁移的核心约束）】
{gene_json}
"""
    skill_section = _format_skill_context(skill_context)
    if skill_section:
        skill_section = f"\n【按需加载的剪辑 Skill（决定「怎么剪好」，不替代 Gene）】\n{skill_section}\n"

    audio_section = ""
    if audio_data:
        try:
            ad = json.loads(audio_data) if isinstance(audio_data, str) else audio_data
        except Exception:
            ad = {}

        bpm = ad.get("bpm", 0)
        beat_count = ad.get("beat_count", 0)
        beat_times = ad.get("beat_times", [])
        key_transitions = ad.get("key_transitions", [])
        mood_segments = ad.get("mood_segments", [])
        overall_mood = ad.get("overall_mood", "")
        energy_curve = ad.get("energy_curve", [])

        mood_text = "\n".join(
            f"    {m.get('start', 0):.1f}s-{m.get('end', 0):.1f}s: {m.get('mood', '?')} (能量={m.get('energy', 0.5)})"
            for m in mood_segments
        ) if mood_segments else "    (无详细情绪分段)"

        key_trans_text = ", ".join(
            f"{kt.get('time', 0):.1f}s@{kt.get('intensity', 0.5):.1f}"
            for kt in (key_transitions or [])[:12]
        ) if key_transitions else ""

        audio_section = f"""
【参考视频音频特征】（重要：音频是方案的结构性驱动力，不是可选项）
{json.dumps(ad, ensure_ascii=False, indent=2)[:800]}

请将以下四个音频维度作为结构决策的核心依据：

**维度1 — 节奏感知镜头时长（BPM → Pacing）**
根据 BPM={bpm} 决定分镜时长：
- BPM > 120: 平均分镜 2-3 秒（快节奏），对齐节拍切割
- BPM 90-120: 平均分镜 3-4 秒（中速），在 key_transitions 切换
- BPM < 90: 平均分镜 4-6 秒（舒缓），在重拍处切换
关键转场位：{key_trans_text or '(自动检测)'}

**维度2 — 能量匹配转场选择（Energy → Transition）**
将音频能量划分为三段：
- 入场（能量<0.4）: → dissolve / fade / blur_in 柔和过渡
- 中段（能量0.4-0.7）: → slide / zoom_in / zoom_flash 增强节奏
- 高潮（能量>0.7）: → whip / zoom_heavy / spin / glitch 冲击感
每个分镜的 transition_in 必须匹配所在段落的能量等级。

**维度3 — 音频情绪对齐情绪弧（Mood → Emotion Arc）**
音频情绪分段：
{mood_text}
整体情绪基调：{overall_mood or '(未指定)'}

确保每个分镜的 emotion 字段与对应时间段的音频 mood 对齐。
情绪弧应当从起始情绪出发，沿音频情绪变化编排。
当音频情绪为"高亢/激昂/震撼"时，分镜应使用大字幕+金色/亮色+scale_up动画。
当音频情绪为"平静/柔和/低沉"时，分镜应使用小字幕+柔色+淡入动画。

**维度4 — 节奏驱动 Ken Burns 强度（Beat → Motion）**
在 {beat_count} 个节拍点上做运镜决策：
- 短镜（≤3s）: ken_burns speed=fast，在节拍点做 zoom_in 切换
- 中镜（3-5s）: ken_burns speed=medium，节拍点做 zoom_in/pan 交替
- 长镜（>5s）: ken_burns speed=slow，在 key_transitions 做大幅 motion_type 变化
相邻镜头 motion_type 不得相同（zoom_in/zoom_out/pan_left/pan_right/focus_scan 交替使用）。

以上四个维度必须同时作用于方案中每个 storyboard 分镜的 duration、transition_in、emotion、ken_burns_config 字段。"""

    capabilities_section = """
=== 系统能力手册：渲染系统完整能力清单 ===

以下是你制定方案时可以调用的所有系统能力。请仔细阅读并在“故事板”中充分利用这些能力，做出详细、多样化、可执行的设计。

---

【转场效果（共 23 种）】

每个分镜的 transition_in 字段可选以下值，根据镜头类型和节奏选择最佳匹配：

类型             | 中文名       | 最适合场景                         | 避免场景
cut              | 硬切         | 任意场景，节奏快速切换             |
fade             | 淡入淡出     | 开场，收尾，慢节奏段落             |
dissolve         | 溶解         | 回忆闪回，时间流逝，梦幻感         |
zoom_in          | 放大入场     | 特写，人物出场，细节强调           |
zoom_out         | 缩小入场     | 全景展示，空间介绍                 |
flash_white      | 闪白         | 快节奏卡点，场景切换               |
flash_black      | 闪黑         | 结束感，夜间场景切换               |
flip_3d          | 3D翻转       | 创意段落，时空转换                  | 日常叙述段落
radial_wipe      | 径向擦除     | 焦点引入，圆形揭示转场             |
slide            | 左滑入       | 平行场景切换，推进叙事             |
slide_right      | 右滑入       | 返回，回顾，倒叙                   |
slide_up         | 上滑入       | 向上运动，轻快过渡                 |
slide_down       | 下滑入       | 向下俯视，降落感                   |
wipe_left        | 左擦除       | 前后对比，地点切换                 |
wipe_right       | 右擦除       | 时间推进，线性叙事                 |
blur_in          | 模糊清晰     | 梦境，回忆，唯美段落               |
rotate_in        | 旋转入场     | 创意转场，活泼段落                 |
whip             | 甩镜头       | 城市街拍，连续动作，抖音热门       |
circle_reveal    | 圆形展开     | 聚光灯效果，焦点引入               |
zoom_flash       | 缩放闪光     | 音乐卡点，高潮入场，快剪           |
glitch           | 故障抖动     | 科技感，城市霓虹                   | 温馨/浪漫段落
spin             | 360度旋转    | 创意转场，城市全景切换             |
zoom_heavy       | 重度缩放     | 爆点入场，音乐鼓点卡点             |
light_leak       | 彩色漏光     | 复古胶片感，日落段落               |
freeze_frame     | 冻结帧+RGB   | 瞬间定格，节奏马停                 |

【镜头类型 → 推荐转场】

- hook（开场钩子）: 推荐 zoom_heavy / zoom_flash / whip / flash_white · 避免 dissolve / fade
- scene_establish（场景建立）: 推荐 fade / blur_in / zoom_out / slide · 避免 glitch / freeze_frame
- daily_moment（日常片段）: 推荐 cut / slide / fade / zoom_in
- emotion_peak（情绪高潮）: 推荐 zoom_flash / zoom_heavy / whip / spin · 避免 dissolve / fade
- transition（转场镜头）: 推荐 whip / slide / spin / glitch / flash_white
- closing（收尾）: 推荐 fade / dissolve / blur_in / flash_black · 避免 glitch / zoom_heavy
- persona（人物表达）: 推荐 zoom_in / fade / blur_in / circle_reveal · 避免 glitch / freeze_frame
- info_card（信息卡）: 推荐 cut / slide_up / fade · 避免 glitch / spin

【节奏 → 转场密度】

- 节奏“快”（快剪）: 密集转场，推荐 cut / whip / flash_white / zoom_flash / glitch
- 节奏“中”（适中）: 适度转场，推荐 slide / zoom_in / fade / spin / light_leak
- 节奏“慢”（舒缓）: 稀疏转场，推荐 fade / dissolve / blur_in / circle_reveal

---

【内置渲染组件（共 14 种）】

每个分镜的 render_component 字段可选以下值：

1. "auto" — 系统自动推断（根据素材类型自动选 text_card / 视频直出 / Ken Burns）
2. "text_card" — 全屏文字卡，支持动画: fade_in（淡入）/ slide_in（滑入）/ typewriter（打字机+光标闪烁）
3. "ken_burns" — 图片运镜（见下方 Ken Burns 参数详解）
4. "custom:photo_collage" — 多图拼贴：一次展示多张图片的拼贴布局
5. "custom:montage" — 快节奏蒙太奇：图片快速切换，适合情绪堆叠
6. "custom:collage" — 创意拼贴画：不规则布局的艺术感拼贴
7. "custom:fast_montage" — 更快速的蒙太奇，适合快节奏段落
8. "custom:slow_life_montage" — 慢生活蒙太奇，适合舒缓节奏
9. "custom:fg_overlay_animation" — 前景叠层动画，带淡入/上浮效果
10. "custom:cinematic_text_reveal" — 电影感文字揭示，适合标题/金句
11. "custom:fade_out_glow" — 淡出发光效果，适合情绪结尾
12. "custom:color_graded_ken_burns" — 带调色的 Ken Burns 运镜
13. "custom:film_grain_ken_burns" — 带胶片颗粒的 Ken Burns
14. "custom:blue_tinted_ken_burns" — 蓝色调 Ken Burns，适合夜景/沉思

注：系统还会自动根据分镜情绪叠加 FilmGrain 胶片颗粒（温馨/治愈 → 胶片质感，震撼/热血 → 强烈颗粒感）。

---

【Ken Burns 运镜参数】

当 render_component = "ken_burns" 或使用图片时，通过 custom_render_config 控制运镜：
- motion_type: "zoom_in"（拉近）/ "zoom_out"（拉远）/ "pan_left"（左移）/ "pan_right"（右移）/ "focus_scan"（聚焦扫视）
- speed: "slow"（慢速, 最大缩放 1.15x）/ "medium"（中速, 1.3x）/ "fast"（快速, 1.45x）
- focus_on_face: true/false（是否聚焦人脸）

建议：相邻镜头使用不同的 motion_type 组合，避免视觉重复。短镜（<=3s）用 fast 速度制造快切感。

---

【前景/背景合成（共 4 种模式）】

通过 composite_mode 字段控制前景/背景素材的合成方式：
- "none": 无前景叠加，只显示背景
- "fg_overlay": 前景直接居中半透明叠加在背景上（opacity 0.85）
- "fg_reveal": 前景以淡入+上浮动画出现（0->60px 位移），适合“揭示/亮相”效果
- "pip": 画中画，前景缩小到右下角 1/3 大小，带圆角+阴影，适合同时展示两个内容

额外效果：当分镜情绪为温馨/治愈/怀旧时，系统会自动叠加 FilmGrain 胶片颗粒覆盖层。

---

【字幕完整配置（每镜独立控制）】

每个分镜的 subtitle_config 支持以下字段。全片应保持字体、主色与安全区统一，
只有 Hook 或高潮需要强调时才改变字号或动画：

| 字段           | 类型     | 默认值        | 可选值
| fontSize      | number  | 42           | 24~80（大字号适合高潮/金句，小字号适合叙述）
| verticalAlign | string  | "bottom"     | "bottom" / "top" / "center"
| color         | string  | "#ffffff"    | 任意十六进制色
| textAlign     | string  | "center"     | "left" / "center" / "right"
| marginFromEdge| number  | 80           | 20~200
| offsetX       | number  | 0            | -200~200（水平偏移）
| animation     | string  | "fade_in"    | "fade_in"（淡入）/ "scale_up"（缩放进入）/ "none"（无动画）
| wordHighlight | boolean | false        | true=逐词高亮（TikTok 风格，当前词变绿色）
| background    | string  | 无           | "rgba(0,0,0,0.3)" 等半透明背景
| padding       | string  | 无           | 有背景时的内边距，如"8px 16px"
| fontWeight    | number  | 600          | 400~900
| letterSpacing | number  | 0            | 0~8（字间距）
| fontFamily    | string  | 默认中文字体  | 自定义字体族

设计建议：
- 开场/信息卡用大字号（56~72）+ center 对齐
- 叙述段落用标准字号（36~42）+ bottom 定位
- 高潮用醒目颜色（如 #FFD700 金色）+ 大字 + scale_up 动画
- 情感细腻处用小字号 + top 定位 + 淡出
- 关键金句开启逐词高亮（wordHighlight: true）

---

【额外覆盖文字层（layers）】

每镜可以在 layers 字段中放置额外的文字层（独立于字幕），支持动画：
- animation: "fade_in" / "scale_in"（缩放入场）/ "slide_up"（上浮）/ "none"
- fontSize / color / strokeColor / strokeWidth（描边）

可用于标题、标注、水印等叠加文字。

---

总结：系统能力是可选工具箱，不是效果清单。只使用服务于 Reference Gene、素材内容和叙事目的的能力，优先保证结构保真、节奏自然、包装一致和渲染稳定。
"""

    advanced_motion_section = build_motion_catalog_prompt()

    return f"""你是一位Vlog编导，正在把参考视频的**结构基因（Gene）**迁移到用户素材上，生成完整剪辑方案。

{gene_section}
【结构骨架】
{skeleton_json}

【可用素材】
{inventory_json}
{material_note}
{audio_section}
{skill_section}
【新Vlog信息】
主题：{target_topic}
详情：{target_info}
创作偏好：{preferences}

{capabilities_section}

{advanced_motion_section}

【决策优先级（务必遵守）】
1. 用户显式要求（创作偏好中的明确指示）
2. Reference Gene 的硬约束（hard_constraints / importance=critical 的镜头功能）
3. Editing Skill 的剪辑策略（帮助你"怎么剪好"，但不覆盖 Gene）
4. 模型自由发挥（仅在前三者都未约束的细节上）

【核心原则：Structure Transfer，不是 Content Copy】
- 迁移的是"镜头功能 / 节奏 / 情绪 / 结构关系"，不是复制原片的物体。
- Gene 某镜头要求 establishing（场景建立）但没有航拍素材时，不要因找不到"航拍"而失败：
  结合 material-matching / structure-adaptation Skill，用"宽景 / 地标 / 环境交代"等**相同功能**的素材替代。
- 每个分镜在 storyboard 中写清 structure_function（本镜承担的 Gene 功能）、gene_shot_index（对应 Gene 镜头下标）、
  skill_refs（用到的 Skill reference 名）、adaptation（若做了功能替代/结构适配，写 preserved / reason / original_function）。

【关键设计要求】

=== 0. 素材使用要求 ===
分镜总数必须控制在 5~10 个。当 Reference Gene 超过 10 个镜头时，按相邻镜头的结构功能、情绪和节奏合并，不要逐镜头机械展开。
输出必须简洁：visual_description、voiceover_text 和 adaptation.reason 各不超过 40 个中文字；未使用的可选数组/对象使用空值，不要输出解释性长文。
可用素材列表中的 **每一个素材都必须被用到** —— 这是硬性要求，审核会逐一核对。
- 具体怎么用（一镜一图、多图拼贴、前景叠层、画中画），由你根据素材特点和爆款结构 **自行创意决定**
- 可以通过 `layers` 字段在一镜中叠加多张素材，也可以通过 `composite_mode` 做合成
- 你决定分镜数量和每镜的内容组织方式，只要最终所有素材都被用上即可

=== 1. 前景/背景合成必须使用（Critical）===
你的素材中包含普通照片和已经抠出前景的照片（带 fg_ 前缀）。**至少 1/3 的分镜必须使用前景/背景合成**（composite_mode 不为 "none"）。
- 使用什么作为 **背景**（source_material_id = 原始照片）
- 是否叠加 **前景抠图**（fg_source_id = 另一张照片的前景）
- 合成方式（composite_mode）：
  - "none": 只显示背景，无前景叠加
  - "fg_overlay": 前景直接叠在背景上（静止）
  - "fg_reveal": 前景以揭示动画出现（浮入/缩放/模糊等）
  - "pip": 画中画效果
- **多图拼贴**：除了前景叠加，还可以在 `layers` 字段中列出额外的素材 ID，实现一镜多图效果。适用于展示系列照片（如美食合集、风景拼贴）。
- 充分利用 fg_source_id 字段引用抠图素材，把人物/建筑合成到不同的背景照片上

创意提示：把人物/建筑从一张照片抠到另一张照片的背景上，创造"穿越"感。利用 `layers` 做多图拼贴来覆盖更多素材。

=== 2. 字幕配置应保持统一（Critical）===
全片使用统一的字体、主色和安全区，最多设置 1 种强调样式。只有 Hook 或高潮需要强调时才改变字号或动画。
- 入场动画: "fade_in"（淡入）/ "scale_up"（缩放进入）/ "none"（无动画）
- 可开启逐词高亮 wordHighlight: true（当前词变绿色，TikTok 风格）
- 可根据段落情绪切换垂直位置: 叙述段用 bottom，情绪段用 center，文艺段用 top
- 高潮段落使用大号（56~72）+ 金色/亮色 + scale_up 动画
- 平静叙述用小号（32~38）+ bottom + 淡入
- 字幕以可读性和包装一致性优先，不为展示能力而堆叠效果

=== 3. 转场服从 Reference 节奏（Critical）===
优先使用 cut / fade / dissolve，整片通常控制在 1-3 种转场。只有 Gene 明确存在冲击点时才使用一次强调转场；不得为了多样化堆叠 whip、spin、zoom_flash 等效果。

=== 4. 渲染组件以稳定和必要性为先（Critical）===
默认使用 auto；只有内置组件无法表达 Gene 功能时才使用 custom: 组件，且必须说明必要性。
- 纯文字表达/金句 → "text_card"（配合 typewriter/slide_in/fade_in 三种动画变体）
- 多图展示 → "custom:photo_collage" / "custom:collage"
- 快节奏堆叠 → "custom:montage" / "custom:fast_montage"
- 慢节奏生活感 → "custom:slow_life_montage"
- 单图运镜 → "ken_burns"（指定不同的 motion_type 和 speed 组合）
- 前景叠层 → "custom:fg_overlay_animation"
- 情绪结尾 → "custom:fade_out_glow"
- 调色/胶片质感 → "custom:color_graded_ken_burns" / "custom:film_grain_ken_burns" / "custom:blue_tinted_ken_burns"

=== 5. 音频整合（Audio Integration）===
如果提供了参考音频，必须：
- 在方案顶层指定 audio_source_id = 参考视频的 ID
- 设置 audio_config = {{ "volume": 0.3, "loop": true }}
- 分镜时长和情绪序列必须适配音频的能量曲线
- 高潮分镜对齐音频的高潮点

请生成完整的视频方案。每个分镜都需要包含上述合成决策，但不要为了差异化牺牲 Reference 结构保真、节奏自然度和包装一致性。

重要：只输出 JSON，不要包含任何解释文字，不要使用 markdown 代码块，直接输出纯 JSON。

{{
  "title": "Vlog标题",
  "target_duration": 秒数,
  "structure_type": "结构类型",
  "gene_refs": ["参考 Gene 的 source_id"],
  "skill_refs_used": ["本次实际用到的 Skill reference 名"],
  "adaptation_log": [
    {{"gene_shot_index": 0, "original_function": "establishing", "adapted_to": "宽景地标照", "reason": "无航拍素材，功能级替代"}}
  ],
  "canvas_width": 1080,
  "canvas_height": 1920,
  "render_hints": {{
    "visual_mood": "整体视觉氛围",
    "custom_effects_needed": []
  }},
  "audio_source_id": "参考视频ID（如果有音频分析）",
  "audio_config": {{
    "volume": 0.3,
    "loop": true,
    "trim_before": 0,
    "trim_after": null
  }},
  "storyboard": [
    {{
      "index": 0,
      "shot_type": "hook/scene_establish/daily_moment/emotion_peak/persona_expression/info_card/closing_moment/transition",
      "duration": 秒数,
      "source_material_id": "背景素材ID",
      "fg_source_id": "前景抠图素材ID（可选，留空则无前景）",
      "composite_mode": "none/fg_overlay/fg_reveal/pip",
      "visual_description": "画面描述（含合成后的效果描述）",
      "subtitle_text": "字幕文案",
      "subtitle_config": {{
        "fontSize": 42,
        "verticalAlign": "bottom",
        "color": "#ffffff",
        "textAlign": "center",
        "marginFromEdge": 80,
        "offsetX": 0,
        "animation": "fade_in",
        "wordHighlight": false,
        "background": null,
        "fontWeight": 600
      }},
      "voiceover_text": "旁白文案",
      "transition_in": "cut/fade/dissolve/zoom_in/zoom_out/slide/whip/glitch/flash_white/zoom_flash/zoom_heavy/spin/blur_in/rotate_in/circle_reveal/light_leak/freeze_frame/slide_up/slide_down/slide_right/wipe_left/wipe_right/flash_black",
      "emotion": "情绪标签",
      "camera_movement": "运镜",
      "shot_size": "close_up/medium/long",
      "composition": "构图",
      "has_face": false,
      "bgm_sync": false,
      "render_component": "auto",
      "layers": [],
      "canvas_width": 1080,
      "canvas_height": 1920,
      "ffmpeg_segment": {{}},
      "structure_function": "本镜头承担的 Gene 功能（hook/establishing/daily_moment/climax/persona/info/closing/transition）",
      "gene_shot_index": -1,
      "skill_refs": ["用到的 Skill reference 名，如 material-matching"],
      "adaptation": {{
        "preserved": true,
        "reason": "是否/为何做了功能级替代或结构适配",
        "original_function": "原 Gene 功能（若适配了则填写）"
      }}
    }}
  ],
  "packaging": {{
    "subtitle_style": {{
      "font_family": "sans-serif",
      "position": "bottom",
      "animation": "none"
    }},
    "color_grade": "调色风格",
    "transition_frequency": "sparse/moderate/frequent"
  }},
  "total_duration": 秒数
}}"""
def build_scheme_iterate_prompt(
    original_scheme_json: str,
    review_result_json: str,
    inventory_json: str,
    gene_json: str = "",
    skill_context=None,
) -> str:
    try:
        original_payload = json.loads(original_scheme_json)
        original_storyboard_count = len(original_payload.get("storyboard") or [])
    except (TypeError, json.JSONDecodeError):
        original_storyboard_count = 0
    count_constraint = (
        f"当前方案有 {original_storyboard_count} 个分镜。迭代后必须保持在 "
        f"{max(3, original_storyboard_count - 2)}~{min(10, original_storyboard_count + 2)} 个；"
        "不得把整个方案压缩为 1~2 个长镜头。"
        if original_storyboard_count else "迭代后保持 5~10 个可执行分镜。"
    )
    gene_section = f"\n【参考视频结构基因（迭代中仍必须保持的硬约束）】\n{gene_json}\n" if gene_json else ""
    skill_names = []
    for item in skill_context or []:
        if isinstance(item, dict) and item.get("name"):
            skill_names.append(str(item["name"]))
    skill_section = (
        f"\n【本轮继续遵守的剪辑 Skill】\n{', '.join(skill_names)}\n"
        if skill_names else ""
    )

    return f"""你是一位Vlog编导，正在根据审核反馈迭代优化Vlog方案。参考以下系统能力做优化。
{gene_section}
【当前方案】
{original_scheme_json}

【审核反馈】
{review_result_json}

【可用素材】
{inventory_json}
{skill_section}
【系统能力参考】
系统支持基础转场、稳定镜头配方、前景合成和字幕配置。本轮只修复审核指出的问题，不要为展示能力增加无关效果。

【决策优先级】用户显式要求 > Reference Gene > Editing Skill > 模型自由发挥。
审核反馈会区分两类问题：
- fidelity（迁移得不像 Reference）：结构/节奏/情绪/高潮位置/镜头功能未保持 → 优先恢复 Gene 结构。
- quality（像 Reference 但剪得不好）：素材匹配/转场/情绪连贯/字幕包装问题 → 在不破坏 Gene 结构的前提下优化。

请根据审核反馈优化方案。保持结构骨架（Gene 硬约束）不变，但必须检查并修正以下方面：
0. **镜头数量保护**：{count_constraint}
1. **素材覆盖率**：检查哪些素材还未被使用，创造性地安排进合适的镜头里。必须覆盖所有素材
2. **字幕包装一致性**：统一字体、主色与位置，仅在 Hook/高潮做必要强调
3. **转场自然度**：优先 cut/fade/dissolve，通常控制在 1-3 种，服从 Reference 节奏
4. **渲染稳定性**：默认使用 auto，自定义组件仅在不可替代时使用
5. **前景/背景合成**：只有内容关系需要时才使用，不设置数量指标
6. 节奏微调（镜头时长、顺序）
7. 包装优化（字幕、转场、调色）
8. 每个分镜补全 structure_function / gene_shot_index / skill_refs / adaptation 溯源字段

不要重写完整方案，只输出有变化的增量补丁。代码会在本地把补丁合并回当前方案。
只输出紧凑 JSON，不要输出 Markdown 或解释性文字；每个文本字段不超过 40 个中文字。
未需要的修改数组输出空数组。输出格式：
{{
  "top_level_changes": {{
    "title": "仅在需要修改时出现",
    "packaging": {{}}
  }},
  "storyboard_updates": [
    {{
      "index": 0,
      "changes": {{
        "duration": 3.0,
        "structure_function": "hook",
        "source_material_id": "material_id",
        "transition_in": "cut",
        "subtitle_text": "简短字幕"
      }}
    }}
  ],
  "storyboard_insertions": [
    {{"after_index": 0, "frame": {{"duration": 3.0, "source_material_id": "material_id", "structure_function": "daily_moment"}}}}
  ],
  "storyboard_removals": [],
  "change_summary": ["修复的审核问题"]
}}
"""
