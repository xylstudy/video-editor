"""Render a confirmed storyboard without invoking any LLM."""
import argparse
import asyncio
import json
import logging
import subprocess
import time
from pathlib import Path

from tools.remotion_renderer import render_with_remotion
from tools.video_tools import _find_ffmpeg
from tools.render_components import resolve_render_component
from config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="渲染已确认的分镜方案")
    parser.add_argument("--scheme", required=True, help="分镜方案 JSON")
    parser.add_argument("--materials", required=True, help="素材库存 JSON")
    parser.add_argument("--output", required=True, help="最终视频输出路径")
    parser.add_argument("--reference-video", default="", help="用于提取原视频音频的参考视频")
    parser.add_argument("--reference-structure", default="", help="用于评审确认后分镜的参考结构 JSON")
    parser.add_argument("--run-id", default="", help="Web Agent 任务的运行 ID，用于生成最终评测报告")
    return parser.parse_args()


def load_inventory(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return data.get("items", data.get("materials", []))


def extract_reference_audio(reference_video: str, output_dir: Path) -> str:
    audio_path = output_dir / "reference_audio.aac"
    subprocess.run(
        [
            _find_ffmpeg(),
            "-y",
            "-i",
            reference_video,
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(audio_path),
        ],
        capture_output=True,
        check=True,
    )
    return str(audio_path)


def main():
    args = parse_args()
    render_started = time.perf_counter()
    def record_evaluation(video_path=None, error=None):
        if not args.run_id:
            return
        from evaluation.web_run import finalize_web_run
        report = asyncio.run(finalize_web_run(
            args.run_id, args.scheme, args.materials, video_path,
            reference_structure_path=args.reference_structure or None,
            render_error=error,
            render_duration_seconds=round(time.perf_counter() - render_started, 3),
        ))
        logger.info("Agent 评测: score=%.2f success=%s", report["score"], report["success"])

    try:
        scheme_path = Path(args.scheme).resolve()
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        scheme = json.loads(scheme_path.read_text(encoding="utf-8"))
        if not settings.ENABLE_DYNAMIC_COMPONENTS:
            for frame in scheme.get("storyboard", []):
                frame["render_component"], _ = resolve_render_component(
                    frame.get("render_component", "auto"),
                    frame.get("custom_render_config", {}),
                    dynamic_enabled=False,
                )
        materials = load_inventory(args.materials)
        if not materials:
            raise RuntimeError("素材库存为空，无法渲染")

        bgm = scheme.get("bgm", {})
        if bgm.get("audio_path") == "_viral_audio":
            if not args.reference_video or not Path(args.reference_video).is_file():
                raise RuntimeError("该分镜需要参考视频音频，但参考视频不存在")
            audio_path = extract_reference_audio(args.reference_video, output_path.parent)
            materials.append({"id": "_viral_audio", "path": audio_path})

        logger.info("开始渲染已确认分镜: %s 个镜头", len(scheme.get("storyboard", [])))
        result = render_with_remotion(scheme, materials, str(output_path), timeout=600)
        if not result:
            raise RuntimeError("Remotion 渲染失败")
    except Exception as exc:
        try:
            record_evaluation(error=str(exc))
        except Exception:
            logger.exception("渲染失败，且 Agent 评测报告生成失败")
        raise

    logger.info("渲染完成: %s", result)
    try:
        record_evaluation(video_path=result)
    except Exception:
        logger.exception("视频已生成，但 Agent 评测报告生成失败")


if __name__ == "__main__":
    main()
