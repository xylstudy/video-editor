"""Evidence-based review of a rendered video.

This module intentionally does not replace the storyboard Reviewer.  It
collects evidence from the *rendered MP4* first, then optionally asks a vision
model to assess the evidence against the confirmed storyboard.  The saved
result can therefore be inspected again without re-running a model call.
"""

from __future__ import annotations

import json
import logging
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from config import settings

logger = logging.getLogger(__name__)

RENDER_REVIEW_VERSION = "1.0"
MAX_REVIEW_SHOTS = 12
BLACK_LUMA_THRESHOLD = 8.0
FREEZE_DIFF_THRESHOLD = 1.2


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ffmpeg_path() -> str:
    try:
        from tools.video_tools import _find_ffmpeg
        return _find_ffmpeg()
    except (ImportError, RuntimeError):
        return "ffmpeg"


def _write_frame(path: Path, frame: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".jpg", frame)
    if not ok:
        raise ValueError(f"无法编码评测帧: {path}")
    encoded.tofile(str(path))


def _contiguous_ranges(samples: list[tuple[float, bool]], minimum_seconds: float) -> list[dict[str, float]]:
    """Turn sampled boolean signals into human-readable time ranges."""
    ranges: list[dict[str, float]] = []
    start: float | None = None
    last: float | None = None
    interval = samples[1][0] - samples[0][0] if len(samples) > 1 else 0.5
    for timestamp, active in samples:
        if active and start is None:
            start = timestamp
        if not active and start is not None:
            end = last if last is not None else timestamp
            if end - start + interval >= minimum_seconds:
                ranges.append({"start": round(start, 2), "end": round(end + interval, 2)})
            start = None
        last = timestamp
    if start is not None and last is not None and last - start + interval >= minimum_seconds:
        ranges.append({"start": round(start, 2), "end": round(last + interval, 2)})
    return ranges


def inspect_rendered_video(video_path: str | Path, sample_interval: float = 0.5) -> dict[str, Any]:
    """Decode the complete video stream and collect lightweight visual QA.

    Black/freeze detection is deliberately diagnostic instead of a hard gate:
    text cards and intentional pause shots are valid Vlog editing techniques.
    """
    path = Path(video_path)
    result: dict[str, Any] = {
        "valid": False,
        "full_decode_valid": False,
        "duration_seconds": None,
        "width": None,
        "height": None,
        "fps": None,
        "has_audio": None,
        "audio_silent": None,
        "black_segments": [],
        "freeze_segments": [],
        "sample_count": 0,
        "issues": [],
    }
    if not path.is_file() or path.stat().st_size == 0:
        result["issues"].append({"type": "missing_video", "detail": "渲染视频不存在或为空"})
        return result

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        result["issues"].append({"type": "unreadable_video", "detail": "OpenCV 无法打开视频"})
        return result
    fps = _safe_float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = frame_count / fps if fps > 0 else 0.0
    result.update({
        "duration_seconds": round(duration, 3) if duration > 0 else None,
        "width": width or None,
        "height": height or None,
        "fps": round(fps, 3) if fps > 0 else None,
    })

    # Cap sampling so a long video does not make evaluation disproportionate.
    effective_interval = max(sample_interval, duration / 120 if duration else sample_interval)
    timestamps = np.arange(0, max(duration, 0.001), effective_interval).tolist()
    black_samples: list[tuple[float, bool]] = []
    freeze_samples: list[tuple[float, bool]] = []
    previous_gray: np.ndarray | None = None
    for timestamp in timestamps:
        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY)
        black_samples.append((timestamp, float(gray.mean()) < BLACK_LUMA_THRESHOLD))
        diff = float(cv2.absdiff(gray, previous_gray).mean()) if previous_gray is not None else math.inf
        freeze_samples.append((timestamp, diff < FREEZE_DIFF_THRESHOLD))
        previous_gray = gray
    cap.release()

    result["sample_count"] = len(black_samples)
    result["black_segments"] = _contiguous_ranges(black_samples, minimum_seconds=1.0)
    result["freeze_segments"] = _contiguous_ranges(freeze_samples, minimum_seconds=2.0)
    for segment in result["black_segments"]:
        result["issues"].append({"type": "possible_black_screen", "detail": "疑似黑屏", **segment})
    for segment in result["freeze_segments"]:
        result["issues"].append({"type": "possible_freeze_frame", "detail": "疑似长时间静帧", **segment})

    # ffmpeg reads every video frame, catching corrupt tails that first-frame
    # probing cannot see.  Audio presence is metadata only; silent videos may
    # be intentional and are not treated as a technical failure.
    ffmpeg = _ffmpeg_path()
    try:
        decoded = subprocess.run(
            [ffmpeg, "-v", "error", "-xerror", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"],
            capture_output=True, text=True, timeout=180, check=False,
        )
        result["full_decode_valid"] = decoded.returncode == 0
        if decoded.returncode != 0:
            result["issues"].append({"type": "full_decode_failed", "detail": decoded.stderr.strip()[:240] or "FFmpeg 全片解码失败"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["issues"].append({"type": "full_decode_unavailable", "detail": str(exc)})

    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)],
                capture_output=True, text=True, timeout=30, check=False,
            )
            if probe.returncode == 0:
                streams = json.loads(probe.stdout).get("streams", [])
                result["has_audio"] = any(stream.get("codec_type") == "audio" for stream in streams)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass

    result["valid"] = bool(duration > 0 and width > 0 and height > 0 and result["full_decode_valid"])
    if result["has_audio"] is False:
        result["issues"].append({"type": "no_audio_track", "detail": "成片未检测到音轨"})
    elif result["has_audio"] is True:
        try:
            volume = subprocess.run(
                [ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"],
                capture_output=True, text=True, timeout=180, check=False,
            )
            output = f"{volume.stdout}\n{volume.stderr}"
            result["audio_silent"] = "mean_volume: -inf" in output
            if result["audio_silent"]:
                result["issues"].append({"type": "silent_audio", "detail": "检测到音轨但全片近似静音"})
        except (OSError, subprocess.TimeoutExpired):
            pass
    return result


def _shot_windows(scheme: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    cursor = 0.0
    for ordinal, frame in enumerate(scheme.get("storyboard", [])):
        if not isinstance(frame, dict):
            continue
        planned_duration = max(0.1, _safe_float(frame.get("duration"), 3.0))
        start = _safe_float(frame.get("start_time"), cursor)
        # Some historical schemes contain default 0 start_time for every shot.
        if ordinal and start <= cursor - 0.01:
            start = cursor
        end = _safe_float(frame.get("end_time"), start + planned_duration)
        if end <= start:
            end = start + planned_duration
        cursor = end
        if start >= duration:
            break
        windows.append({
            "storyboard_index": frame.get("index", ordinal),
            "start": round(max(0.0, start), 3),
            "end": round(min(duration, end), 3),
            "purpose": frame.get("purpose") or frame.get("visual_description") or frame.get("visual_content") or "",
            "structure_function": frame.get("structure_function", ""),
            "material_id": frame.get("material_id") or frame.get("source_material_id") or "",
            "subtitle_text": frame.get("subtitle_text") or frame.get("text_card_content") or "",
            "transition": frame.get("transition_in") or frame.get("transition") or "cut",
        })
    return windows


def collect_render_evidence(video_path: str | Path, scheme: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    """Save representative frames aligned to storyboard time windows."""
    technical = inspect_rendered_video(video_path)
    evidence: dict[str, Any] = {"technical": technical, "shots": []}
    if not technical["valid"] or not technical["duration_seconds"]:
        return evidence
    path = Path(video_path)
    frame_dir = Path(output_dir) / "frames"
    windows = _shot_windows(scheme, float(technical["duration_seconds"]))
    if len(windows) > MAX_REVIEW_SHOTS:
        indices = sorted({round(i * (len(windows) - 1) / (MAX_REVIEW_SHOTS - 1)) for i in range(MAX_REVIEW_SHOTS)})
        windows = [windows[i] for i in indices]
        evidence["sampling_note"] = f"已从 {len(scheme.get('storyboard', []))} 个分镜均匀抽取 {len(windows)} 个评测镜头"
    cap = cv2.VideoCapture(str(path))
    for ordinal, shot in enumerate(windows):
        start, end = shot["start"], max(shot["start"] + 0.01, shot["end"])
        samples = [start + (end - start) * ratio for ratio in (0.15, 0.5, 0.85)]
        frames: list[dict[str, Any]] = []
        for position, timestamp in enumerate(samples):
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            filename = f"shot_{ordinal:03d}_{position}_{timestamp:.2f}.jpg"
            destination = frame_dir / filename
            _write_frame(destination, frame)
            frames.append({"time": round(timestamp, 3), "path": str(destination), "role": ("start", "middle", "end")[position]})
        evidence["shots"].append({**shot, "frames": frames})
    cap.release()
    return evidence


def build_render_review_prompt(reference_structure: dict[str, Any], scheme: dict[str, Any], evidence: dict[str, Any]) -> str:
    shot_context = []
    for shot in evidence.get("shots", []):
        shot_context.append({key: shot.get(key) for key in (
            "storyboard_index", "start", "end", "purpose", "structure_function", "material_id", "subtitle_text", "transition",
        )})
    reference = {
        "duration": reference_structure.get("duration"),
        "structure_type": reference_structure.get("structure_type"),
        "gene": reference_structure.get("gene", {}),
        "rhythm_pattern": reference_structure.get("rhythm_pattern"),
        "emotion_curve": reference_structure.get("emotion_curve"),
    }
    return f"""你是短视频成片质检 Reviewer。你将看到按时间顺序提供的成片代表帧；每 3 张依次对应一个分镜的开头、中间、结尾。

不要评价它是否与参考视频画面相同：用户素材本来就不同。请评估实际成片是否兑现了确认分镜，并在结构层面保持参考视频的 Hook、节奏和情绪功能。

参考结构：{json.dumps(reference, ensure_ascii=False)}
确认方案摘要：{json.dumps({'target_topic': scheme.get('target_topic'), 'target_duration': scheme.get('target_duration'), 'hook_strategy': scheme.get('hook_strategy')}, ensure_ascii=False)}
抽帧镜头上下文：{json.dumps(shot_context, ensure_ascii=False)}
技术检测结果：{json.dumps(evidence.get('technical', {}), ensure_ascii=False)}

逐项从 0-10 打分并说明依据：hook_delivery、shot_plan_alignment、material_fit、pacing_transition、visual_continuity、subtitle_legibility、packaging_consistency。
只报告能从代表帧、镜头时序和技术检测中得到支持的结论；无法确认音画、节奏或字幕可读性时必须写明限制。问题必须给出 evidence_times（秒）。

只输出 JSON：
{{
  "scores": {{"hook_delivery": {{"score": 0, "reason": ""}}, "shot_plan_alignment": {{"score": 0, "reason": ""}}, "material_fit": {{"score": 0, "reason": ""}}, "pacing_transition": {{"score": 0, "reason": ""}}, "visual_continuity": {{"score": 0, "reason": ""}}, "subtitle_legibility": {{"score": 0, "reason": ""}}, "packaging_consistency": {{"score": 0, "reason": ""}}}},
  "total_score": 0,
  "pass": false,
  "summary": "",
  "limitations": [""],
  "issues": [{{"category": "", "severity": "high/medium/low", "description": "", "evidence_times": [0.0], "suggestion": ""}}],
  "highlights": [""]
}}"""


async def review_rendered_video(
    video_path: str | Path,
    scheme: dict[str, Any],
    reference_structure: dict[str, Any],
    output_dir: str | Path,
    model_config: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Collect render evidence and optionally run the configured vision model."""
    evidence = collect_render_evidence(video_path, scheme, output_dir)
    technical = evidence["technical"]
    review: dict[str, Any] = {
        "schema_version": RENDER_REVIEW_VERSION,
        "status": "not_run",
        "technical": technical,
        "evidence": {"shots": evidence.get("shots", []), "sampling_note": evidence.get("sampling_note", "")},
        "visual_review": None,
    }
    def public_result() -> tuple[dict[str, Any], dict[str, Any] | None]:
        # The report is returned through an authenticated HTTP endpoint.  Keep
        # time evidence but never disclose absolute server filesystem paths.
        for shot in review["evidence"]["shots"]:
            for frame in shot.get("frames", []):
                frame["path"] = f"frames/{Path(frame['path']).name}"
        return review, None

    if not technical["valid"]:
        review.update({"status": "failed", "reason": "成片技术检测未通过，未调用视觉模型"})
        return public_result()
    config = model_config or {}
    api_key = config.get("VISION_API_KEY", settings.VISION_API_KEY)
    base_url = config.get("VISION_BASE_URL", settings.VISION_BASE_URL)
    model = config.get("VISION_MODEL_ID", settings.VISION_MODEL_ID)
    if not api_key:
        review.update({"status": "skipped", "reason": "未配置视觉模型，已保存技术检查与抽帧证据"})
        return public_result()
    frame_paths = [frame["path"] for shot in evidence.get("shots", []) for frame in shot.get("frames", [])]
    if not frame_paths:
        review.update({"status": "failed", "reason": "未能提取可供视觉评审的代表帧"})
        return public_result()
    from config.llm_client import LLMTools
    llm = LLMTools(api_key=api_key, base_url=base_url, model=model)
    try:
        response = await llm.chat_with_images(
            build_render_review_prompt(reference_structure, scheme, evidence), frame_paths, response_format="json",
        )
        if llm.usage_snapshot()["mock_requests"]:
            raise RuntimeError("成片 Reviewer 使用了 mock 响应")
        visual = llm.parse_json(response)
        if not isinstance(visual, dict):
            raise ValueError("视觉 Reviewer 未返回 JSON 对象")
        review.update({"status": "completed", "visual_review": visual})
    except Exception as exc:
        review.update({"status": "failed", "reason": f"视觉 Reviewer 失败: {exc}"})
    usage = llm.usage_snapshot()
    review["model"] = usage["model"]
    for shot in review["evidence"]["shots"]:
        for frame in shot.get("frames", []):
            frame["path"] = f"frames/{Path(frame['path']).name}"
    return review, usage
