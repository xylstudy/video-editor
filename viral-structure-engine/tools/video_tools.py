import logging
import subprocess
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config import settings

logger = logging.getLogger(__name__)

# 自动查找 ffmpeg（通过 imageio_ffmpeg 或 PATH）
_FFMPEG_PATH: str | None = None


def _imwrite(image_path: str, image) -> None:
    """Write an image through NumPy so Windows Unicode paths work reliably."""
    target = Path(image_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    extension = target.suffix or ".jpg"
    ok, encoded = cv2.imencode(extension, image)
    if not ok:
        raise ValueError(f"Cannot encode image: {image_path}")
    encoded.tofile(str(target))


def _imread(image_path: str):
    """Read an image through NumPy so Windows Unicode paths work reliably."""
    try:
        encoded = np.fromfile(str(Path(image_path)), dtype=np.uint8)
    except OSError:
        return None
    if encoded.size == 0:
        return None
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR)


def _find_ffmpeg() -> str:
    global _FFMPEG_PATH
    if _FFMPEG_PATH:
        return _FFMPEG_PATH
    # 优先尝试 imageio_ffmpeg 捆绑的二进制
    try:
        import imageio_ffmpeg
        _FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
        return _FFMPEG_PATH
    except (ImportError, RuntimeError, FileNotFoundError):
        pass
    # 回退到 PATH 中的 ffmpeg
    _FFMPEG_PATH = "ffmpeg"
    return _FFMPEG_PATH


class VideoTools:
    def __init__(self, work_dir: Optional[str] = None):
        self.work_dir = work_dir or str(settings.TEMP_DIR)

    def get_video_info(self, video_path: str) -> dict:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        cap.release()

        return {"width": width, "height": height, "fps": fps, "total_frames": total_frames, "duration": duration}

    def detect_scene_changes(self, video_path: str, threshold: float = 0.3) -> list[dict]:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        scenes = []
        prev_frame = None
        frame_idx = 0
        scene_start = 0.0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % int(fps) == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.resize(gray, (160, 90))

                if prev_frame is not None:
                    # absdiff.mean() is in [0, 255], while the configured
                    # threshold is a normalized ratio in [0, 1]. Comparing
                    # the raw value to 0.3 incorrectly marks almost every
                    # one-second sample as a new scene.
                    diff = cv2.absdiff(gray, prev_frame).mean() / 255.0
                    if diff > threshold:
                        scene_end = frame_idx / fps
                        scenes.append({"start": scene_start, "end": scene_end, "duration": scene_end - scene_start})
                        scene_start = scene_end

                prev_frame = gray
            frame_idx += 1

        cap.release()
        total_duration = frame_idx / fps
        scenes.append({"start": scene_start, "end": total_duration, "duration": total_duration - scene_start})
        return scenes

    def extract_frame(self, video_path: str, time_sec: float) -> str:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        target_frame = int(time_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()
        cap.release()

        if not ret:
            raise ValueError(f"Cannot extract frame at {time_sec}s")

        stem = Path(video_path).stem
        output_path = str(Path(self.work_dir) / f"frame_{stem}_{int(time_sec * 10)}.jpg")
        _imwrite(output_path, frame)
        return output_path

    def extract_audio(self, video_path: str) -> str:
        stem = Path(video_path).stem
        output_path = str(Path(self.work_dir) / f"{stem}_audio.wav")
        cmd = [_find_ffmpeg(), "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", output_path]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path

    def extract_multiple_frames(self, video_path: str, scenes: list[dict], frames_per_shot: int = 3) -> dict[int, list[str]]:
        """抽取每个镜头的多帧图像（头/中/尾）"""
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        result: dict[int, list[str]] = {}

        for shot_idx, scene in enumerate(scenes):
            start, end = scene["start"], scene["end"]
            duration = end - start
            paths = []

            for i in range(frames_per_shot):
                t = start + (duration * i) / max(frames_per_shot - 1, 1)
                if t > end:
                    t = end - 0.01
                target_frame = max(0, int(t * fps))
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                ret, frame = cap.read()
                if not ret:
                    continue
                stem = Path(video_path).stem
                output = str(Path(self.work_dir) / f"frame_{stem}_s{shot_idx}_{i}.jpg")
                _imwrite(output, frame)
                paths.append(output)

            if not paths:
                paths = [self.extract_frame(video_path, (start + end) / 2)]
            result[shot_idx] = paths

        cap.release()
        return result

    def compute_shot_motion(self, video_path: str, scene_start: float, scene_end: float, num_samples: int = 10) -> float:
        """计算镜头内的运动强度 [0, 1]，基于帧间灰度差均值"""
        duration = scene_end - scene_start
        if duration <= 0:
            return 0.0

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)

        sample_times = [
            scene_start + (duration * i) / (num_samples - 1)
            for i in range(num_samples)
        ]
        # Filter to within bounds
        sample_times = [t for t in sample_times if scene_start <= t < scene_end]

        diffs = []
        prev = None
        for t in sample_times:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(t * fps)))
            ret, frame = cap.read()
            if not ret:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (160, 90))
            if prev is not None:
                diffs.append(cv2.absdiff(gray, prev).mean())
            prev = gray

        cap.release()
        if not diffs:
            return 0.0
        return min(float(sum(diffs) / len(diffs)) / 30.0, 1.0)

    def compute_color_stats(self, image_paths: list[str]) -> dict:
        """计算一组图像帧的 HSV 统计和主色调"""
        h_vals, s_vals, v_vals = [], [], []
        all_pixels = []

        for img_path in image_paths:
            img = _imread(img_path)
            if img is None:
                continue
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            h_vals.extend(hsv[:, :, 0].flatten())
            s_vals.extend(hsv[:, :, 1].flatten())
            v_vals.extend(hsv[:, :, 2].flatten())
            all_pixels.append(img)

        if not h_vals:
            return {
                "hue_mean": 0, "hue_std": 0, "saturation_mean": 0, "saturation_std": 0,
                "value_mean": 0, "value_std": 0, "dominant_colors": [],
            }

        h_arr, s_arr, v_arr = np.array(h_vals), np.array(s_vals), np.array(v_vals)
        result = {
            "hue_mean": round(float(np.mean(h_arr)), 1),
            "hue_std": round(float(np.std(h_arr)), 1),
            "saturation_mean": round(float(np.mean(s_arr)), 3),
            "saturation_std": round(float(np.std(s_arr)), 3),
            "value_mean": round(float(np.mean(v_arr)), 3),
            "value_std": round(float(np.std(v_arr)), 3),
        }

        # Dominant colors via OpenCV k-means
        try:
            all_pixels_flat = np.concatenate([p.reshape(-1, 3) for p in all_pixels])
            all_pixels_flat = all_pixels_flat[::10]  # subsample 1/10
            if len(all_pixels_flat) >= 30:
                px = all_pixels_flat.astype(np.float32)
                criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
                _, labels, centers = cv2.kmeans(px, 3, None, criteria, 5, cv2.KMEANS_RANDOM_CENTERS)
                counts = [int(np.sum(labels.flatten() == i)) for i in range(3)]
                sorted_indices = sorted(range(3), key=lambda i: -counts[i])
                result["dominant_colors"] = [
                    f"#{int(centers[i][2]):02x}{int(centers[i][1]):02x}{int(centers[i][0]):02x}"
                    for i in sorted_indices
                ]
        except Exception:
            result["dominant_colors"] = []

        return result

    def compute_rhythm_data(self, scenes: list[dict], total_duration: float) -> dict:
        """从镜头切分结果计算节奏特征数据"""
        shot_durations = [s["duration"] for s in scenes]

        if not shot_durations:
            return {
                "shot_count": 0, "shot_durations": [], "avg_shot_duration": 0,
                "min_shot_duration": 0, "max_shot_duration": 0, "std_shot_duration": 0,
                "front_3s_cuts": 0, "first_shot_duration": 0, "cut_frequency_per_10s": [],
            }

        arr = np.array(shot_durations)

        # Cuts in first 3 seconds
        front_3s_cuts = sum(1 for s in scenes if s["start"] < 3.0)

        # Cut frequency per 10-second segment
        num_segments = max(1, int(np.ceil(total_duration / 10)))
        cut_freq = []
        for seg_idx in range(num_segments):
            seg_start = seg_idx * 10
            seg_end = min((seg_idx + 1) * 10, total_duration)
            cuts = sum(1 for s in scenes if seg_start <= s["start"] < seg_end)
            cut_freq.append(cuts)

        return {
            "shot_count": len(scenes),
            "shot_durations": [round(d, 2) for d in shot_durations],
            "avg_shot_duration": round(float(np.mean(arr)), 2),
            "min_shot_duration": round(float(np.min(arr)), 2),
            "max_shot_duration": round(float(np.max(arr)), 2),
            "std_shot_duration": round(float(np.std(arr)), 2),
            "front_3s_cuts": front_3s_cuts,
            "first_shot_duration": round(shot_durations[0], 2),
            "cut_frequency_per_10s": cut_freq,
        }

    def apply_ken_burns(self, image_path: str, motion_type: str = "zoom_in", speed: str = "slow",
                        focus_region: Optional[tuple] = None, duration: float = 3.0) -> str:
        stem = Path(image_path).stem
        output_path = str(Path(self.work_dir) / f"kenburns_{stem}_{int(duration)}.mp4")
        fps = 25
        total_frames = int(duration * fps)

        # zoom 幅度：slow 整体变焦 0.2x，fast 变焦 0.4x
        zoom_range = 0.20 if speed == "slow" else 0.40
        zoom_step = zoom_range / total_frames

        if motion_type == "zoom_in":
            # 从 1.0 缓慢放大到 1.0 + zoom_range
            expr = f"zoompan=z='min(zoom+{zoom_step},1.0+{zoom_range})':d={total_frames}:s=1080x1920:fps={fps}"
        elif motion_type == "zoom_out":
            # 从 1.0 + zoom_range 缓慢缩回到 1.0
            expr = f"zoompan=z='max(zoom-{zoom_step},1.0)':d={total_frames}:s=1080x1920:fps={fps}"
            # zoompan 无法预设初始 zoom，用 scale 先放大再 zoom_out
            import math
            initial_scale = 1.0 + zoom_range
            expr = f"scale=iw*{initial_scale}:ih*{initial_scale}:flags=lanczos,zoompan=z='max(zoom-{zoom_step},1.0)':d={total_frames}:s=1080x1920:fps={fps}"
        elif motion_type == "pan_right":
            # 从左向右平移
            pan_pixels = 300 if speed == "slow" else 600
            step = pan_pixels / total_frames
            expr = f"zoompan=z='1.1':x='min(x+{step},iw-iw/1.1)':y=0:d={total_frames}:s=1080x1920:fps={fps}"
        elif motion_type == "pan_left":
            pan_pixels = 300 if speed == "slow" else 600
            step = pan_pixels / total_frames
            expr = f"zoompan=z='1.1':x='max(x-{step},0)':y=0:d={total_frames}:s=1080x1920:fps={fps}"
        elif motion_type == "pan_up":
            pan_pixels = 200 if speed == "slow" else 400
            step = pan_pixels / total_frames
            expr = f"zoompan=z='1.1':y='max(y-{step},0)':x=0:d={total_frames}:s=1080x1920:fps={fps}"
        elif motion_type == "pan_down":
            pan_pixels = 200 if speed == "slow" else 400
            step = pan_pixels / total_frames
            expr = f"zoompan=z='1.1':y='min(y+{step},ih-ih/1.1)':x=0:d={total_frames}:s=1080x1920:fps={fps}"
        else:
            # 静态，无运镜
            expr = f"zoompan=z='1.0':d={total_frames}:s=1080x1920:fps={fps}"

        cmd = [_find_ffmpeg(), "-y", "-loop", "1", "-i", image_path, "-vf", expr,
               "-c:v", "libx264", "-t", str(duration), "-pix_fmt", "yuv420p", output_path]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path

    def generate_text_card(self, text: str, bg_color: str = "black", font_style: str = "",
                           text_color: str = "white", animation: str = "fade_in",
                           duration: float = 3.0) -> str:
        output_path = str(Path(self.work_dir) / f"textcard_{abs(hash(text))}_{int(duration)}.mp4")
        escaped = self._escape_drawtext(text)
        drawtext = f"drawtext=text='{escaped}':fontcolor={text_color}:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2"
        if font_style:
            drawtext += f":fontfile={font_style}"

        cmd = [_find_ffmpeg(), "-y", "-f", "lavfi", "-i", f"color=c={bg_color}:s=1080x1920:d={duration}",
               "-vf", drawtext, "-c:v", "libx264", "-t", str(duration), "-pix_fmt", "yuv420p", output_path]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path

    def apply_speed_change(self, video_path: str, factor: float) -> str:
        stem = Path(video_path).stem
        output_path = str(Path(self.work_dir) / f"speed_{stem}_{factor}.mp4")
        cmd = [_find_ffmpeg(), "-y", "-i", video_path, "-vf", f"setpts={1/factor}*PTS",
               "-af", f"atempo={min(factor, 2.0)}", output_path]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path

    def apply_reverse(self, video_path: str) -> str:
        stem = Path(video_path).stem
        output_path = str(Path(self.work_dir) / f"reverse_{stem}.mp4")
        cmd = [_find_ffmpeg(), "-y", "-i", video_path, "-vf", "reverse", "-af", "areverse", output_path]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path

    def extract_shot_clip(self, video_path: str, start: float, end: float, shot_index: int = 0) -> str:
        """提取镜头 clip（含音频），用于 Qwen3-OMNI 多模态逐镜头分析"""
        dur = end - start
        if dur <= 0.3:
            # 太短的镜头扩展到 0.3s，避免 API 400 错误
            dur = 0.3
            start = max(0, start - 0.15)
        output_path = str(Path(self.work_dir) / f"shot_{shot_index:03d}_{int(start)}_{int(end)}.mp4")
        # 用 libx264 重新编码确保兼容性 + 带音频
        cmd = [_find_ffmpeg(), "-y", "-i", video_path,
               "-ss", str(max(0, start)), "-t", str(dur),
               "-c:v", "libx264", "-c:a", "aac",
               "-pix_fmt", "yuv420p", output_path]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path

    def extract_highlight_clip(self, video_path: str, start: float, end: float) -> str:
        stem = Path(video_path).stem
        output_path = str(Path(self.work_dir) / f"clip_{stem}_{int(start)}_{int(end)}.mp4")
        cmd = [_find_ffmpeg(), "-y", "-i", video_path, "-ss", str(start), "-t", str(end - start),
               "-c:v", "libx264", "-c:a", "aac", output_path]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path

    def concat_clips(self, clip_paths: list[str], transitions: list[str] | None = None,
                     transition_duration: float = 0.5) -> str:
        output_path = str(Path(self.work_dir) / "concat_output.mp4")
        if len(clip_paths) == 1:
            import shutil
            shutil.copy2(clip_paths[0], output_path)
            return output_path

        # 写入 concat demuxer file list（避免逐个拼接 + 解决中文路径问题）
        filelist_path = Path(self.work_dir) / "concat_filelist.txt"
        with open(filelist_path, "w", encoding="utf-8") as f:
            for cp in clip_paths:
                f.write(f"file '{cp}'\n")

        cmd = [_find_ffmpeg(), "-y", "-f", "concat", "-safe", "0",
               "-i", str(filelist_path), "-c", "copy", output_path]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            stderr_str = result.stderr.decode("utf-8", errors="replace")[:300] if result.stderr else "unknown error"
            raise RuntimeError(f"拼接失败: {stderr_str}")

        logger.info(f"  拼接完成 → {output_path}")
        return output_path

    @staticmethod
    def _escape_drawtext(text: str) -> str:
        """转义 drawtext text= 内联参数中的特殊字符"""
        return text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")

    def overlay_subtitle(self, video_path: str, subtitle_config: dict) -> str:
        stem = Path(video_path).stem
        output_path = str(Path(self.work_dir) / f"sub_{stem}.mp4")
        text = subtitle_config.get("text", "")
        escaped = self._escape_drawtext(text)
        drawtext = f"drawtext=text='{escaped}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=h-th-80"
        cmd = [_find_ffmpeg(), "-y", "-i", video_path, "-vf", drawtext, "-c:v", "libx264", "-c:a", "aac", output_path]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_path

    def crop_image(self, image_path: str, region: tuple[int, int, int, int]) -> str:
        img = _imread(image_path)
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")
        x, y, w, h = region
        crop = img[y:y+h, x:x+w]
        stem = Path(image_path).stem
        output_path = str(Path(self.work_dir) / f"crop_{stem}.jpg")
        _imwrite(output_path, crop)
        return output_path
