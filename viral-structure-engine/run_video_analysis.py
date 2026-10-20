"""视频分析：GLM-4.6V 多模态（画面+音频）逐镜头分析 + 结构分析"""
import argparse
import asyncio
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from config.llm_client import LLMTools
from config import settings
from config.output_manager import OutputManager
from tools.video_tools import VideoTools
from tools.face_tools import FaceTools
from tools.audio_tools import AudioTools
from agents.analyst import AnalystAgent

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_VIDEO_PATH = PROJECT_ROOT / "data" / "samples" / "viral.mp4"


def parse_args():
    parser = argparse.ArgumentParser(description="视频分析：GLM-4.6V 多模态逐镜头分析 + 结构分析")
    parser.add_argument(
        "--video",
        type=str,
        default=str(DEFAULT_VIDEO_PATH),
        help="待分析的爆款视频路径（默认: data/samples/viral.mp4）",
    )
    parser.add_argument(
        "--topic",
        type=str,
        default="北京旅行Vlog",
        help="目标视频主题（默认: 北京旅行Vlog）",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default="video_analysis_demo",
        help="运行 ID / 输出目录名（默认: video_analysis_demo）",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    video_path = args.video
    target_topic = args.topic

    # 输出目录
    out = OutputManager(run_id=args.run_id)
    logger.info(f"输出目录: {out.run_dir}")

    # GLM-4.6V：多模态分析（画面+音频）
    vision_llm = LLMTools(
        api_key=settings.VISION_API_KEY,
        base_url=settings.VISION_BASE_URL,
        model=settings.VISION_MODEL_ID,
    )

    # 工具
    video_tools = VideoTools()
    face_tools = FaceTools()
    audio_tools = AudioTools()

    analyst = AnalystAgent(vision_llm, video_tools, face_tools, audio_tools)

    # ===== 1. 视频基本信息 =====
    logger.info("=" * 60)
    logger.info("1. 获取视频信息")
    info = video_tools.get_video_info(video_path)
    logger.info(f"   时长: {info['duration']:.1f}s | 分辨率: {info['width']}x{info['height']} | {info['fps']}fps")
    out.save_json("analyst", "video_info.json", info)

    # ===== 2. 场景切分 =====
    logger.info("=" * 60)
    logger.info("2. 镜头切分")
    scenes = video_tools.detect_scene_changes(video_path)
    logger.info(f"   检测到 {len(scenes)} 个镜头")
    out.save_json("analyst", "scenes.json", scenes)

    # ===== 3. 音频提取（用于转写） =====
    transcript = ""
    try:
        audio_path = video_tools.extract_audio(video_path)
        transcript = audio_tools.transcribe(audio_path)
        logger.info(f"   转写完成: {len(transcript)} 字")
    except Exception as e:
        logger.debug(f"音频转写跳过: {e}")

    # ===== 4. 逐镜头分析（Qwen3-OMNI-Flash 画面+音频） =====
    logger.info("=" * 60)
    logger.info("4. 逐镜头分析 (GLM-4.6V 画面+音频)")
    shot_analyses = []
    prev_desc = ""
    total_shots = len(scenes)
    fail_count = 0

    for i, scene in enumerate(scenes):
        motion = video_tools.compute_shot_motion(video_path, scene["start"], scene["end"])
        # 提取多帧做色彩统计（保留预处理数据辅助分析）
        frames = video_tools.extract_multiple_frames(video_path, [scene], frames_per_shot=5)
        color = video_tools.compute_color_stats(frames.get(0, []))

        try:
            analysis = await analyst._analyze_shot(
                shot_index=i, start_time=scene["start"], end_time=scene["end"],
                total_duration=info["duration"], prev_frame_desc=prev_desc,
                video_path=video_path,
                motion_intensity=motion,
                color_stats=color,
            )
            analysis["start_time"] = scene["start"]
            analysis["end_time"] = scene["end"]
            analysis["motion_intensity"] = motion
            analysis["color_stats"] = color
            shot_analyses.append(analysis)
            prev_desc = analysis.get("one_sentence_summary", "")
            role = analysis.get("structure_role", {})
            audio_info = analysis.get("audio", {})
            audio_note = f" 音频:语速={audio_info.get('speech_pace','?')} BGM={audio_info.get('bgm_style','?')}" if audio_info else ""
            logger.info(f"   [{i+1}/{total_shots}] {scene['start']:.1f}s-{scene['end']:.1f}s "
                        f"→ {role.get('primary_function', '?')}: {analysis.get('one_sentence_summary', '')[:40]}{audio_note}")
        except Exception as e:
            logger.info(f"   [{i+1}/{total_shots}] {scene['start']:.1f}s-{scene['end']:.1f}s → 失败: {e}")
            fail_count += 1

    out.save_json("analyst", "shot_analyses.json", shot_analyses)
    logger.info(f"   完成: {len(shot_analyses)}/{total_shots} 个镜头 (失败 {fail_count})")

    # ===== 5. 节奏数据（基于镜头切分，非 LLM） =====
    rhythm_data = video_tools.compute_rhythm_data(scenes, info["duration"])
    logger.info(f"   平均镜头时长: {rhythm_data['avg_shot_duration']:.2f}s")

    # ===== 6. 全局结构分析（GLM-4.6V 文本模式） =====
    logger.info("=" * 60)
    logger.info("5. 全局结构分析 (GLM-4.6V，基于含音频感知的镜头分析)")

    shot_text = json.dumps(shot_analyses, ensure_ascii=False)
    structure = await analyst._analyze_structure(
        duration=info["duration"], width=info["width"], height=info["height"],
        shot_count=len(shot_analyses), shot_analyses_text=shot_text,
        transcript=transcript,
        rhythm_data=rhythm_data,
    )
    out.save_json("analyst", "structure_analysis.json", structure)
    logger.info(f"   结构类型: {structure.get('structure_type', {}).get('category', '?')}")

    # ===== 7. 构建视频结构 =====
    video_structure = analyst.build_video_structure(
        video_path, info["duration"], info["width"], info["height"],
        shot_analyses, structure, transcript,
    )
    out.save_json("analyst", "video_structure.json", video_structure.to_dict())
    logger.info(f"   分镜数: {len(video_structure.shots)}")

    # ===== 8. 汇总 =====
    logger.info("=" * 60)
    logger.info("分析完成!")
    logger.info(f"输出目录: {out.run_dir}")
    logger.info(f"镜头: {len(shot_analyses)}/{total_shots} 个")
    logger.info(f"结构: {structure.get('structure_type', {}).get('category', '?')}")
    logger.info(f"叙事: {structure.get('narrative_type', '?')}")


if __name__ == "__main__":
    asyncio.run(main())
