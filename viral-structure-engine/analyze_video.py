import argparse
import asyncio
import json
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from prompts.analyst_prompts import (
    build_shot_analysis_prompt as build_current_shot_analysis_prompt,
    build_structure_analysis_prompt as build_current_structure_analysis_prompt,
)

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_VIDEO_PATH = PROJECT_ROOT / "data" / "samples" / "viral.mp4"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "output" / "analysis_result.json"

# 结构化事件前缀：Web 后端逐行读取子进程 stdout，借此解析分析进度。
# 普通 print 保持人类可读，事件行保持机器可解析，两者互不干扰。
EVENT_PREFIX = "__GENE_EVENT__"


def sample_shot_times(start_time: float, end_time: float) -> list[float]:
    """Return ordered samples that expose motion and within-shot effects."""
    start = max(0.0, float(start_time))
    end = max(start, float(end_time))
    duration = end - start
    if duration <= 0:
        return [start]
    ratios = (0.12, 0.5, 0.88) if duration < 0.6 else (0.08, 0.28, 0.5, 0.72, 0.92)
    upper = max(start, end - min(0.01, duration / 10))
    return [round(min(upper, start + duration * ratio), 3) for ratio in ratios]


def _emit(event_type: str, **data):
    """输出一条结构化进度事件（单行 JSON），供 Web 后端解析展示。"""
    payload = {"type": event_type, **data}
    print(f"{EVENT_PREFIX}{json.dumps(payload, ensure_ascii=False)}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description="爆款 Vlog 单视频结构分析")
    parser.add_argument(
        "--video",
        type=str,
        default=str(DEFAULT_VIDEO_PATH),
        help="待分析的爆款视频路径（默认: data/samples/viral.mp4）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT_PATH),
        help="分析结果输出路径（默认: data/output/analysis_result.json）",
    )
    return parser.parse_args()


async def analyze_video():
    args = parse_args()

    from config.llm_client import LLMTools
    from tools.video_tools import VideoTools
    from tools.face_tools import FaceTools
    from tools.audio_tools import AudioTools
    from agents.analyst import AnalystAgent
    from config import settings
    from models.trace import (
        ANALYST_PROMPT_VERSION, STRUCTURE_PROMPT_VERSION,
        make_shot_trace, make_analysis_trace,
    )

    llm = LLMTools(
        api_key=settings.VISION_API_KEY,
        base_url=settings.VISION_BASE_URL,
        model=settings.VISION_MODEL_ID,
    )
    video = VideoTools()
    face = FaceTools()
    audio = AudioTools()
    analyst = AnalystAgent(llm, video, face, audio)

    video_path = args.video

    print("=" * 70)
    print("爆款结构迁移引擎 — Analyst Agent 单视频分析")
    print("=" * 70)
    print(f"视频路径: {video_path}")

    if not Path(video_path).exists():
        print(f"错误: 文件不存在: {video_path}")
        return

    try:
        info = video.get_video_info(video_path)
        print(f"\n[视频基本信息]:")
        print(f"   分辨率: {info['width']}x{info['height']}")
        print(f"   帧率: {info['fps']:.2f} fps")
        print(f"   时长: {info['duration']:.2f} 秒")
        print(f"   总帧数: {info['total_frames']}")
        _emit("video_info", width=info["width"], height=info["height"],
              fps=round(info["fps"], 2), duration=round(info["duration"], 2),
              total_frames=info["total_frames"])
    except Exception as e:
        print(f"获取视频信息失败: {e}")
        _emit("error", stage="video_info", message=str(e))
        return

    try:
        scenes = video.detect_scene_changes(
            video_path, threshold=settings.SCENE_CHANGE_THRESHOLD
        )
        print(f"\n[镜头切分结果]:")
        print(f"   检测到 {len(scenes)} 个镜头")
        for i, s in enumerate(scenes):
            print(f"   镜头 {i+1}: {s['start']:.1f}s → {s['end']:.1f}s (时长 {s['duration']:.1f}s)")
        _emit("scenes", count=len(scenes),
              shots=[{"start": round(s["start"], 2), "end": round(s["end"], 2),
                      "duration": round(s["duration"], 2)} for s in scenes])
    except Exception as e:
        print(f"镜头切分失败: {e}")
        scenes = [{"start": 0.0, "end": info["duration"], "duration": info["duration"]}]
        _emit("scenes", count=1, shots=[{"start": 0.0, "end": round(info["duration"], 2),
              "duration": round(info["duration"], 2)}], fallback=True)

    transcript = ""
    try:
        print(f"\n🎤 提取音频中...")
        audio_path = video.extract_audio(video_path)
        print(f"   音频提取完成: {audio_path}")
        try:
            transcript = audio.transcribe(audio_path)
            print(f"   语音转写完成: {len(transcript)} 字")
            _emit("audio", status="ok", transcript_chars=len(transcript))
        except Exception as e:
            print(f"   语音转写失败 (whisper 可能未安装): {e}")
            _emit("audio", status="skipped", message=f"语音转写跳过: {e}")
    except Exception as e:
        print(f"   音频提取失败: {e}")
        _emit("audio", status="skipped", message=f"音频提取失败: {e}")

    # 关键帧保存目录：从 --output 路径推导（基因场景下即 gene 目录）
    frames_dir = Path(args.output).parent / "frames"

    print(f"\n[逐镜头分析] (共 {len(scenes)} 个镜头, 将调用 DeepSeek)...")
    shot_analyses = []
    shot_traces = []  # 分析轨迹：记录每帧画面的推理上下文
    for i, scene in enumerate(scenes):
        prev_desc = shot_analyses[-1].get("one_sentence_summary", "") if shot_analyses else ""
        print(f"\n   ▶ 分析镜头 {i+1}/{len(scenes)} ({scene['start']:.1f}s-{scene['end']:.1f}s)...")
        _emit("shot_start", index=i, total=len(scenes),
              start=round(scene["start"], 2), end=round(scene["end"], 2))

        extracted_frames = []
        saved_frames = []
        try:
            frames_dir.mkdir(parents=True, exist_ok=True)
            for sample_index, sample_time in enumerate(sample_shot_times(scene["start"], scene["end"])):
                extracted = str(video.extract_frame(video_path, sample_time))
                extracted_frames.append(extracted)
                saved_path = frames_dir / f"shot_{i:03d}_{sample_index:02d}.jpg"
                shutil.copy2(extracted, saved_path)
                saved_frames.append(str(saved_path))
            if saved_frames:
                # Keep the historical thumbnail name for the current frontend.
                shutil.copy2(saved_frames[len(saved_frames) // 2], frames_dir / f"shot_{i:03d}.jpg")
            has_face = any(face.has_face(path) for path in extracted_frames)
        except Exception as e:
            print(f"      多帧抽取失败: {e}")
            has_face = False

        prompt = build_current_shot_analysis_prompt(
            i, scene["start"], scene["end"], info["duration"], prev_desc,
            visual_samples_only=True,
        )
        if extracted_frames:
            response = await llm.chat_with_images(prompt, extracted_frames, response_format="json")
        else:
            response = await llm.chat(prompt, response_format="json")
        frame_paths = saved_frames or extracted_frames
        try:
            result = llm.parse_json(response)
            result["has_face"] = has_face
            result["start_time"] = scene["start"]
            result["end_time"] = scene["end"]
            shot_analyses.append(result)
            shot_traces.append(make_shot_trace(
                index=i, start_time=scene["start"], end_time=scene["end"],
                analysis=result, frame_paths=frame_paths,
                prev_context_summary=prev_desc,
                model=getattr(llm, "model", ""),
            ))

            sf = result.get("structure_role", {})
            print(f"      功能: {sf.get('primary_function', '?')} | 情绪: {result.get('emotion', '?')}")
            print(f"      摘要: {result.get('one_sentence_summary', '')[:60]}")
            _emit("shot_result", index=i, total=len(scenes),
                  start=round(scene["start"], 2), end=round(scene["end"], 2),
                  function=sf.get("primary_function", ""),
                  emotion=result.get("emotion", ""),
                  summary=result.get("one_sentence_summary", ""),
                  has_face=has_face, frame=frame_name)
        except Exception as e:
            print(f"      解析失败: {e}")
            shot_analyses.append({
                "shot_index": i,
                "start_time": scene["start"],
                "end_time": scene["end"],
                "has_face": has_face,
                "one_sentence_summary": "分析失败",
            })
            shot_traces.append(make_shot_trace(
                index=i, start_time=scene["start"], end_time=scene["end"],
                analysis={"_error": str(e)}, frame_paths=frame_paths,
                prev_context_summary=prev_desc,
                model=getattr(llm, "model", ""),
            ))
            _emit("shot_failed", index=i, total=len(scenes), message=str(e),
                  start=round(scene["start"], 2), end=round(scene["end"], 2),
                  frame=frame_name)

    print(f"\n📊 全局结构分析 (调用 DeepSeek)...")
    _emit("structure_start", total_shots=len(shot_analyses))
    shot_text = json.dumps(shot_analyses, ensure_ascii=False)
    prompt = build_current_structure_analysis_prompt(
        info["duration"], info["width"], info["height"],
        len(shot_analyses), shot_text, transcript,
    )
    response = await llm.chat(prompt, response_format="json")
    try:
        structure = llm.parse_json(response)
    except Exception as e:
        print(f"结构分析解析失败: {e}")
        structure = {}
    st = structure.get("structure_type", {}) if isinstance(structure, dict) else {}
    _emit("structure_done",
          category=st.get("category", ""),
          narrative_type=structure.get("narrative_type", "") if isinstance(structure, dict) else "",
          overall_emotion=structure.get("overall_emotion", "") if isinstance(structure, dict) else "",
          overall_summary=structure.get("overall_summary", "") if isinstance(structure, dict) else "")

    print(f"\n💾 保存分析轨迹...")
    trace = make_analysis_trace(
        video_path=str(video_path), duration=info["duration"],
        resolution=[info["width"], info["height"]],
        scene_count=len(scenes), scene_threshold=settings.SCENE_CHANGE_THRESHOLD,
        audio_summary={"transcript_chars": len(transcript), "transcribed": bool(transcript)},
        shots=shot_traces,
        structure_input_summary=shot_text,
        structure_analysis=structure if isinstance(structure, dict) else {},
        versions={
            "model": getattr(llm, "model", ""),
            "prompt_version": f"{ANALYST_PROMPT_VERSION}+{STRUCTURE_PROMPT_VERSION}",
            "llm_client": "LLMTools",
        },
    )
    trace_path = Path(args.output).parent / "analysis_trace.json"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(
        json.dumps(trace.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"   分析轨迹已保存至: {trace_path.resolve()}")

    print(f"\n[组装 VideoStructure 对象]...")
    video_structure = analyst.build_video_structure(
        video_path, info["duration"], info["width"], info["height"],
        shot_analyses, structure, transcript,
    )

    print(f"\n" + "=" * 70)
    print("分析结果摘要")
    print("=" * 70)

    print(f"\n【视频元信息】")
    print(f"  时长: {video_structure.duration:.1f}s")
    print(f"  分辨率: {video_structure.resolution}")
    print(f"  镜头数: {len(video_structure.shots)}")

    print(f"\n【结构摘要】")
    print(f"  {video_structure.structure_summary or '（无）'}")

    print(f"\n【Hook 策略】")
    print(f"  方法: {video_structure.vlog_meta.hook_method or '（无）'}")
    print(f"  详情: {video_structure.hook_summary or '（无）'}")

    print(f"\n【Vlog 元信息】")
    print(f"  叙事类型: {video_structure.vlog_meta.narrative_type or '（无）'}")
    print(f"  结构类型: {video_structure.vlog_meta.structure_type or '（无）'}")
    print(f"  整体情绪: {video_structure.vlog_meta.overall_emotion or '（无）'}")

    print(f"\n【关键技法】")
    for t in video_structure.key_techniques:
        print(f"  • {t}")

    print(f"\n【镜头列表 ({len(video_structure.shots)} 个)】")
    for s in video_structure.shots:
        print(f"  镜头 {s.index+1}: {s.shot_type.value} | {s.visual_description[:30] if s.visual_description else '（无描述）'} | 情绪: {s.emotion or '?'} | 人脸: {'有' if s.has_face else '无'}")

    result = {
        "source_path": video_structure.source_path,
        "duration": video_structure.duration,
        "resolution": list(video_structure.resolution),
        "shot_count": len(video_structure.shots),
        "structure_summary": video_structure.structure_summary,
        "hook_summary": video_structure.hook_summary,
        "key_techniques": video_structure.key_techniques,
        "vlog_meta": video_structure.vlog_meta.to_dict() if hasattr(video_structure.vlog_meta, "to_dict") else {},
        "shots": [s.to_dict() if hasattr(s, "to_dict") else {} for s in video_structure.shots],
        "raw_structure_analysis": structure,
        "raw_shot_analyses": shot_analyses,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n💾 完整分析结果已保存至: {output_path.resolve()}")
    _emit("done", output=str(output_path.resolve()), shot_count=len(video_structure.shots))


def _legacy_build_shot_analysis_prompt(shot_index, start_time, end_time, total_duration, prev_frame_desc):
    prev_context = f"前一帧内容：{prev_frame_desc}" if prev_frame_desc else "这是视频的第一个镜头。"
    return f"""你是一位有8年经验的短视频内容分析师，专门研究抖音和小红书爆款Vlog的画面语言。你能从一帧画面中读出拍摄意图、情绪信息和结构作用。

【输入信息】
这是一条Vlog视频的第{shot_index + 1}个镜头的关键帧。
该镜头时间：{start_time:.1f}s - {end_time:.1f}s（时长 {end_time - start_time:.1f}s）
视频总时长：{total_duration:.1f}s
{prev_context}

请按以下三步分析这帧画面：

=== 第一步：画面内容识别 ===
- 画面中的主体是什么？从以下选项中选择最匹配的：人物特写 / 人物中景 / 美食 / 风景 / 建筑 / 街道 / 室内环境 / 物品特写 / 文字卡 / 黑场/白场 / 动物 / 其他
- 如果有人物：有几人？是正面/侧面/背影？表情大致如何（开心/平静/专注/惊喜/其他）？在做什么动作？
- 场景环境：室内还是室外？地点类型是什么（家/咖啡厅/餐厅/街道/景区/公园/办公室/商场/车内/其他）？
- 色调和光影：整体偏暖还是偏冷？是自然光还是人工光？光影质量如何（柔和/强烈/逆光/阴天/黄昏/夜景）？
- 画面中有没有文字信息？如果有，大致内容是什么？

=== 第二步：拍摄技法判断 ===
- 景别：特写（脸/手/物品局部）/ 近景（胸部以上）/ 中景（半身或膝上）/ 全景（全身或完整场景）/ 远景（大范围环境）
- 构图：居中构图 / 三分法 / 对角线 / 框架构图 / 大面积留白 / 对称 / 俯拍 / 仰拍
- 运镜推断（结合画面模糊程度和构图特点）：固定镜头 / 推镜头 / 拉镜头 / 平移 / 跟随 / 手持晃动 / 无法判断
- 画面质感：高清干净 / 有轻微噪点 / 有胶片感 / 有明显滤镜 / 有光斑或虚化 / 画面模糊或过曝

=== 第三步：Vlog结构功能判断 ===
这个镜头在Vlog叙事中最可能承担什么功能？只选一个主功能：

- hook吸引：画面有强烈的视觉冲击力或悬念感，出现在视频开头，目的是抓住观众注意力
- 场景建立：展示地点、环境、空间，让观众知道"这是在哪"，通常用于Vlog的开头或场景切换处
- 日常铺展：展示做事的过程、日常生活的片段，信息量中等，节奏中等，是Vlog的"填充内容"
- 情绪高点：整条Vlog中视觉最美、最有感染力、最震撼或最温暖的画面，通常配合BGM高潮
- 人物表达：重点展示人物的状态、情绪、反应或与他人的互动，Vlog中增加"人格感"的关键
- 信息传递：画面中有明确的文字信息（字幕卡、标题、价格、地址等），起到传递信息而非叙事的作用
- 收尾定格：视频结尾的画面，通常带有情绪落点、感悟感或温暖感，给观众一个"收束"的感觉
- 过渡连接：内容信息量低，主要起连接两个不同段落的过渡作用，如空镜、模糊转场画面

请严格按以下JSON格式回答，不要添加任何其他文字：

{{
  "shot_index": {shot_index},
  "content": {{
    "main_subject": "主体描述（一句话）",
    "people_count": 0,
    "people_description": "人物描述（无人物则为空字符串）",
    "scene_type": "场景类型",
    "indoor_outdoor": "indoor/outdoor/unknown",
    "color_temperature": "warm/cool/neutral",
    "light_quality": "描述光影质量",
    "has_text_in_frame": false,
    "text_content": "画面中的文字（无则为空）"
  }},
  "technique": {{
    "shot_size": "close_up/medium_close/medium/medium_long/long",
    "composition": "构图方式",
    "camera_movement": "推断的运镜",
    "visual_quality": "画面质感描述"
  }},
  "structure_role": {{
    "primary_function": "hook/scene_establish/daily_moment/emotion_peak/persona_expression/info_card/closing_moment/transition",
    "confidence": 0.0,
    "reasoning": "一句话说明判断依据"
  }},
  "emotion": "这个镜头传递的核心情绪（一个词，如：活力/平静/温馨/震撼/期待/好奇/治愈/热血/忧郁/欢乐）",
  "one_sentence_summary": "一句话描述这个镜头的画面和作用"
}}"""


def _legacy_build_structure_analysis_prompt(duration, width, height, shot_count, shot_analyses_text, transcript):
    transcript_section = (
        f"以下是视频的完整语音转写文本（旁白/口播/对话）：\n{transcript}"
        if transcript
        else "该视频无语音内容或语音转写为空。"
    )

    return f"""你是一位抖音Vlog赛道的资深编导，看过上万条爆款Vlog，对Vlog的结构模式、节奏设计、情绪曲线有深入研究。你正在对一条Vlog做全面的结构拆解，这个拆解结果将被用于"结构迁移"——把这条视频的成功方法论迁移到新内容上。

【视频基础信息】
总时长：{duration:.1f}秒
分辨率：{width}x{height}
镜头总数：{shot_count}个

【逐镜头分析结果】（按时间顺序）
{shot_analyses_text}

【语音转写】
{transcript_section}

请完成以下六个分析任务，每个任务都是结构迁移的关键依据：

========================================
任务一：脚本段落结构
========================================
将视频按叙事逻辑划分为3-7个段落。Vlog的段落不是随机切分的，而是按叙事节奏来划分——每个段落有明确的叙事目的。

对每个段落标注：
- 段落目的
- 对应的镜头范围（镜头序号）
- 该段的文案/旁白概要
- 建议时长
- 情绪基调（一个词）
- 节奏特征（快/中/慢）

========================================
任务二：节奏结构分析
========================================
1. 节奏曲线关键节点：列出6-10个时间点，每个标注节奏强度（0-1）和设计意图
2. 节奏模式判断
3. 高潮位置：在总时长的百分之多少处？
4. 前3秒节奏：前3秒有几个镜头？每秒切几刀？
5. BGM推断：从画面切换节奏推断BGM的大概风格和BPM范围

========================================
任务三：包装结构分析
========================================
1. 字幕风格
2. 标题/文字卡
3. 转场方式
4. 滤镜/调色风格
5. 其他视觉元素

========================================
任务四：Hook策略分析
========================================
详细分析前3秒的hook策略

========================================
任务五：整体结构模式分类
========================================

========================================
任务六：关键技法提取
========================================
列出3-6个最核心的剪辑或拍摄技法标签

请严格按以下JSON格式输出，不要添加任何其他文字：

{{
  "script_structure": [
    {{
      "index": 0,
      "purpose": "hook/人设展示/场景铺展/情绪递进/高潮爆发/价值输出/CTA互动",
      "shot_range": "镜头X - 镜头Y",
      "content_summary": "该段的文案/旁白概要",
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
    "bgm_style_guess": "BGM风格推测"
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
    "color_grade_detail": "调色风格的详细描述",
    "stickers_effects": "贴纸和特效描述（无则为空字符串）"
  }},
  "hook_strategy": {{
    "method": "悬念提问/视觉冲击/金句开头/反差对比/声音吸引/直接展示结果",
    "detail": "具体手法描述",
    "effectiveness": "这个hook的效果评估（一句话）",
    "connection_to_body": "hook和后面内容的衔接是否自然"
  }},
  "structure_type": {{
    "category": "悬念前置型/情绪递进型/节奏卡点型/日常流水型/对比反转型/故事叙事型",
    "reasoning": "为什么归为此类",
    "core_characteristics": "这个结构模式的核心特征（2-3句话）"
  }},
  "key_techniques": [
    "技法标签1：具体含义",
    "技法标签2：具体含义"
  ],
  "narrative_type": "timeline/emotion/event",
  "persona_type": "voiceover/talking_head/back_figure/hands_only/mixed/no_persona",
  "persona_ratio": 0.0,
  "empty_shot_count": 0,
  "overall_emotion": "整条Vlog的情绪基调（一个词）",
  "overall_summary": "50字以内的整体结构总结"
}}"""


if __name__ == "__main__":
    asyncio.run(analyze_video())
