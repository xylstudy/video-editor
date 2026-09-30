"""
FFmpeg 渲染器 — 根据方案数据生成高质量视频：
- Ken Burns 运镜（zoompan）处理静态图片
- 前景/背景合成（overlay）
- 逐分镜字幕配置（drawtext）
- 分镜间转场（xfade）
- BGM 叠加（参考视频音频）

Windows 注意事项：
- fontfile 和 textfile 必须用相对路径（Windows 驱动冒号 : 破坏 filter 解析）
- 所有 filter 表达式不用 if/lte/min，否则 imageio_ffmpeg 构建崩溃
"""
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from config import settings
from models.scheme import VideoScheme, StoryboardFrame
from models.material import MaterialInventory

logger = logging.getLogger(__name__)

_FFMPEG_PATH: Optional[str] = None


def _find_ffmpeg() -> str:
    global _FFMPEG_PATH
    if _FFMPEG_PATH:
        return _FFMPEG_PATH
    try:
        import imageio_ffmpeg
        _FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
        return _FFMPEG_PATH
    except (ImportError, RuntimeError, FileNotFoundError):
        pass
    _FFMPEG_PATH = "ffmpeg"
    return _FFMPEG_PATH


class FFMpegRenderer:
    """基于方案数据的 FFmpeg 渲染器"""

    TRANSITION_MAP = {
        "cut": None,
        "fade": "fade",
        "dissolve": "fade",
        "fadeblack": "fadeblack",
        "fadewhite": "fadewhite",
        "slide": "slideleft",
        "slide_left": "slideleft",
        "slide_right": "slideright",
        "slide_up": "slideup",
        "slide_down": "slidedown",
        "wipe_left": "wipeleft",
        "wipe_right": "wiperight",
        "wipe_up": "wipeup",
        "wipe_down": "wipedown",
        "whip": "fade",
        "glitch": "fade",
        # xfade has no "zoompan" transition. Use a widely supported fade;
        # zoom motion itself is already rendered inside each segment.
        "zoom_in": "fade",
        "zoom_out": "fade",
        "flash_white": "fadewhite",
        "flash_black": "fadeblack",
        "blur_in": "fade",
        "rotate_in": "fade",
        "mask": "fade",
        "circle_reveal": "circleopen",
        "zoom_flash": "fade",
        "spin": "fade",
        "zoom_heavy": "fade",
        "light_leak": "fade",
        "freeze_frame": "fade",
        "flip_3d": "fade",
        "radial_wipe": "fade",
        "none": None,
    }

    FONT_NAME = "simhei.ttf"
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}

    def __init__(self, work_dir: Optional[str] = None):
        self.work_dir = Path(work_dir or settings.TEMP_DIR)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg = _find_ffmpeg()

        # 所有 ffmpeg 子进程的工作目录
        self.ff_cwd = self.work_dir / "ffmpeg_render"
        self.ff_cwd.mkdir(parents=True, exist_ok=True)

        # 复制字体到工作目录（避免 filter 中 Windows 冒号路径问题）
        self._setup_font()

        # 单分镜输出目录
        self.segments_dir = self.ff_cwd / "segs"
        self.segments_dir.mkdir(exist_ok=True)

    def _setup_font(self):
        """复制中文字体到工作目录，供 drawtext 使用"""
        font_candidates = [
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/msyh.ttf",
            "C:/Windows/Fonts/msyhbd.ttf",
        ]
        self.font_path = None
        for fp in font_candidates:
            if Path(fp).exists():
                dst = self.ff_cwd / self.FONT_NAME
                shutil.copy2(fp, dst)
                self.font_path = self.FONT_NAME  # 相对路径
                logger.debug(f"  字体已复制: {fp} → {dst}")
                return

        # 找不到字体就 fallback
        logger.warning("  [FFmpeg] 未找到中文字体，字幕将使用默认字体")

    # ======================== 公开接口 ========================

    def render(
        self,
        scheme: VideoScheme,
        inventory: MaterialInventory,
        audio_path: Optional[str] = None,
    ) -> Optional[str]:
        """渲染完整视频"""
        material_map = self._build_material_map(inventory)

        # Step 1: 渲染每个分镜
        logger.info(f"  [FFmpeg] 渲染 {len(scheme.storyboard)} 个分镜...")
        segments = []
        rendered_frames = []
        for i, frame in enumerate(scheme.storyboard):
            seg = self._render_segment(frame, material_map, i)
            if seg:
                segments.append(seg)
                rendered_frames.append(frame)
            else:
                logger.warning(f"  [FFmpeg] 分镜 {i} 渲染失败，跳过")

        if not segments:
            logger.error("  [FFmpeg] 没有可渲染的片段")
            return None

        # Step 2: 带转场拼接
        logger.info(f"  [FFmpeg] 拼接 {len(segments)} 个片段（含转场）...")
        concat_path = self._concat_segments(segments, rendered_frames)
        if not concat_path:
            logger.warning("  [FFmpeg] 转场拼接失败，降级为无转场顺序拼接")
            concat_path = self._concat_simple(segments)
        elif len(segments) > 1:
            expected_duration = self._expected_concat_duration(rendered_frames)
            actual_duration = self._probe_duration(concat_path)
            if (
                expected_duration > 0
                and actual_duration > 0
                and actual_duration < expected_duration * 0.9
            ):
                logger.warning(
                    "  [FFmpeg] 转场拼接时长异常: %.2fs < %.2fs，降级为顺序拼接",
                    actual_duration,
                    expected_duration,
                )
                concat_path = self._concat_simple(segments)
        if not concat_path:
            logger.error("  [FFmpeg] 分镜拼接失败")
            self._cleanup(segments, None)
            return None

        # Step 3: 叠加音频
        import re
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', scheme.title or 'vlog')
        output_path = str(settings.OUTPUT_DIR / f"{safe_title}.mp4")
        if audio_path and Path(audio_path).exists():
            logger.info(f"  [FFmpeg] 叠加音频: {Path(audio_path).name}")
            self._add_audio(concat_path, audio_path, scheme.audio_config, output_path)
        else:
            shutil.copy2(concat_path, output_path)

        # 清理
        self._cleanup(segments, concat_path)
        size_mb = Path(output_path).stat().st_size / 1024 / 1024
        logger.info(f"  [FFmpeg] [OK] 渲染完成: {size_mb:.1f}MB → {output_path}")
        return output_path

    # ======================== 素材查找 ========================

    def _build_material_map(self, inventory: MaterialInventory) -> dict:
        m = {}
        if inventory:
            for item in getattr(inventory, "items", getattr(inventory, "materials", [])):
                mid = getattr(item, "id", "")
                path = getattr(item, "path", "")
                if mid and path:
                    m[mid] = path
        return m

    def _find_material(self, material_id: str, material_map: dict) -> Optional[str]:
        if not material_id:
            return None
        return material_map.get(material_id)

    def _is_video(self, media_path: str) -> bool:
        return Path(media_path).suffix.lower() in self.VIDEO_EXTENSIONS

    def _media_input_args(self, media_path: str) -> list[str]:
        if self._is_video(media_path):
            # Loop short clips when a storyboard frame is longer than the
            # source. Unlike image inputs, video inputs do not support -loop.
            return ["-stream_loop", "-1", "-i", media_path]
        return ["-loop", "1", "-i", media_path]

    # ======================== 单分镜渲染 ========================

    def _render_segment(
        self, frame: StoryboardFrame, material_map: dict, index: int
    ) -> Optional[str]:
        output = str(self.segments_dir / f"seg_{index:03d}.mp4")
        duration = frame.duration
        if duration <= 0:
            return None

        fps = 30
        width = getattr(frame, "canvas_width", 1080)
        height = getattr(frame, "canvas_height", 1920)
        total_frames = max(int(duration * fps), 1)

        bg_id = frame.bg_source_id or frame.source_material_id or frame.material_id
        bg_path = self._find_material(bg_id, material_map)
        if not bg_path or not Path(bg_path).exists():
            logger.warning(f"  分镜 {index}: 素材 {bg_id} 不存在")
            return None

        fg_path = None
        if frame.fg_source_id and frame.composite_mode not in ("none", ""):
            fg_path = self._find_material(frame.fg_source_id, material_map)
            if fg_path and not Path(fg_path).exists():
                fg_path = None

        if fg_path and frame.composite_mode in ("fg_overlay", "fg_reveal", "pip"):
            return self._render_with_overlay(
                bg_path, fg_path, frame, output,
                duration, width, height, fps, total_frames,
            )
        else:
            return self._render_single(
                bg_path, frame, output,
                duration, width, height, fps, total_frames,
            )

    def _render_single(
        self, media_path: str, frame: StoryboardFrame,
        output: str, duration: float, width: int, height: int,
        fps: int, total_frames: int,
    ) -> Optional[str]:
        """Render one image or video with deterministic framing and text."""
        if self._is_video(media_path):
            filters = [
                f"scale={width}:{height}:force_original_aspect_ratio=increase",
                f"crop={width}:{height}",
                "setsar=1",
                f"fps={fps}",
            ]
        else:
            filters = [self._build_zoompan(frame, width, height, total_frames)]

        color_f = self._get_color_filter(frame)
        if color_f:
            filters.append(color_f)

        sub_f = self._build_subtitle_filter(frame, width, height)
        if sub_f:
            filters.append(sub_f)

        layer_fs = self._build_layer_filters(frame, width, height)
        filters.extend(layer_fs)

        return self._run_ffmpeg([
            self.ffmpeg, "-y",
            *self._media_input_args(media_path),
            "-vf", ",".join(filters),
            "-t", str(duration),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "fast", "-crf", "22", "-an",
            output,
        ], output)

    def _render_with_overlay(
        self, bg_path: str, fg_path: str, frame: StoryboardFrame,
        output: str, duration: float, width: int, height: int,
        fps: int, total_frames: int,
    ) -> Optional[str]:
        """背景 + 前景叠加 + 字幕"""
        # Overlay inputs may independently be images or videos. Normalize both
        # through scale/crop; input looping is selected by media type below.
        bg_zp = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps}[bg]"
        )

        # 前景处理
        if frame.composite_mode == "pip":
            fg_part = f"[1]scale={width//3}:-1[fg];[bg][fg]overlay=W-w-20:H-h-20:format=auto"
        elif frame.composite_mode == "fg_reveal":
            fg_part = (
                f"[1]format=rgba,scale={width}:-1,"
                f"fade=in:st=0:d=1.0:alpha=1[fg];"
                f"[bg][fg]overlay=0:(H-h)/2:format=auto"
            )
        else:
            # fg_overlay: 居中叠加
            fg_part = (
                f"[1]format=rgba,scale={width}:-1[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto"
            )

        # 字幕 + 文字层追加到 filter_complex
        sub_f = self._build_subtitle_filter(frame, width, height)
        if sub_f:
            fg_part = f"{fg_part},{sub_f}"
        layer_fs = self._build_layer_filters(frame, width, height)
        for lf in layer_fs:
            fg_part = f"{fg_part},{lf}"

        return self._run_ffmpeg([
            self.ffmpeg, "-y",
            *self._media_input_args(bg_path),
            *self._media_input_args(fg_path),
            "-filter_complex", f"{bg_zp};{fg_part}",
            "-t", str(duration),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "fast", "-crf", "22", "-an",
            output,
        ], output)

    # ======================== 拼接 + 转场 ========================

    def _concat_segments(self, segments: list[str], storyboard: list) -> Optional[str]:
        if len(segments) == 1:
            return segments[0]

        # Keep fallback duration close to the storyboard target. Every xfade
        # overlaps adjacent clips, so long transitions accumulate a large
        # duration loss on multi-shot videos.
        td = 0.2
        filter_parts = []
        prev_label = "0"
        # xfade 吃掉了 duration 秒的重叠，实际时长 = 原始和 - 每次转场的 transition_duration
        actual_duration = getattr(storyboard[0], "duration", 3.0) if storyboard else 0

        for i in range(1, len(segments)):
            seg_dur = getattr(storyboard[i], "duration", 3.0)
            transition = self._get_transition(storyboard, i)
            label = f"f{i:02d}"

            if transition is None:
                local_td = 0.04  # "cut" → 1帧转场，视觉上等同硬切
                trans = "fade"
            else:
                local_td = td
                trans = transition

            offset = max(actual_duration - local_td, 0)
            filter_parts.append(
                f"[{prev_label}][{i}]xfade=transition={trans}:"
                f"duration={local_td:.2f}:offset={offset:.2f}[{label}]"
            )
            prev_label = label
            # 每次 xfade 减少 local_td 秒的总时长
            actual_duration = actual_duration + seg_dur - local_td

        if not filter_parts:
            return self._concat_simple(segments)

        output = str(self.segments_dir / "concat.mp4")
        inputs = []
        for seg in segments:
            inputs.extend(["-i", seg])

        cmd = [
            self.ffmpeg, "-y", *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "fast", "-crf", "22",
            "-map", f"[{prev_label}]", "-an",
            output,
        ]
        return self._run_ffmpeg(cmd, output)

    def _expected_concat_duration(self, storyboard: list) -> float:
        """Return expected xfade output duration for already-rendered frames."""
        if not storyboard:
            return 0.0
        duration = float(getattr(storyboard[0], "duration", 0.0) or 0.0)
        for index, frame in enumerate(storyboard[1:], start=1):
            overlap = 0.04 if self._get_transition(storyboard, index) is None else 0.2
            duration += float(getattr(frame, "duration", 0.0) or 0.0) - overlap
        return max(duration, 0.0)

    def _probe_duration(self, media_path: str) -> float:
        """Probe duration without depending on a separately installed ffprobe."""
        try:
            completed = subprocess.run(
                [self.ffmpeg, "-i", media_path],
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return 0.0
        stderr = completed.stderr.decode("utf-8", errors="replace")
        match = __import__("re").search(
            r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)",
            stderr,
        )
        if not match:
            return 0.0
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    def _concat_simple(self, segments: list[str]) -> str:
        output = str(self.segments_dir / "concat.mp4")
        filelist = self.segments_dir / "concat_list.txt"
        with open(filelist, "w", encoding="utf-8") as f:
            for seg in segments:
                f.write(f"file '{seg}'\n")
        cmd = [
            self.ffmpeg, "-y", "-f", "concat", "-safe", "0",
            "-i", str(filelist), "-c", "copy", output,
        ]
        return self._run_ffmpeg(cmd, output)

    def _get_transition(self, storyboard: list, seg_index: int) -> Optional[str]:
        if seg_index >= len(storyboard):
            return None
        frame = storyboard[seg_index]
        tr = getattr(frame, "transition_in", None) or getattr(frame, "transition", None)
        if not tr:
            return None
        tr_str = tr.value if hasattr(tr, "value") else str(tr)
        return self.TRANSITION_MAP.get(tr_str)

    # ======================== 音频叠加 ========================

    def _add_audio(
        self, video_path: str, audio_path: str,
        audio_config: dict, output_path: str,
    ):
        volume = audio_config.get("volume", 0.3)
        do_loop = audio_config.get("loop", False)

        # 获取音频和视频的时长
        probe_v = subprocess.run(
            [self.ffmpeg, "-i", video_path],
            capture_output=True, timeout=15,
        )
        stderr_v = probe_v.stderr.decode("utf-8", errors="replace")
        dur_match_v = __import__("re").search(r"Duration: (\d+):(\d+):(\d+\.\d+)", stderr_v)

        probe_a = subprocess.run(
            [self.ffmpeg, "-i", audio_path],
            capture_output=True, timeout=15,
        )
        stderr_a = probe_a.stderr.decode("utf-8", errors="replace")
        dur_match_a = __import__("re").search(r"Duration: (\d+):(\d+):(\d+\.\d+)", stderr_a)

        video_sec = 0.0
        if dur_match_v:
            h, m, s = dur_match_v.groups()
            video_sec = int(h) * 3600 + int(m) * 60 + float(s)

        audio_sec = 0.0
        if dur_match_a:
            h, m, s = dur_match_a.groups()
            audio_sec = int(h) * 3600 + int(m) * 60 + float(s)

        has_audio = ": Audio:" in stderr_v or ": audio:" in stderr_v

        # 音频比视频短且 loop=True → 循环音频
        audio_input = audio_path
        if do_loop and audio_sec > 0 and video_sec > audio_sec:
            audio_input = audio_path
            loop_count = int(video_sec / audio_sec) + 1
        else:
            loop_count = 1

        if loop_count > 1:
            # 用 a 循环 + 截断到视频长度
            cmd = [
                self.ffmpeg, "-y",
                "-i", video_path,
                "-stream_loop", str(loop_count), "-i", audio_path,
            ]
            if has_audio:
                cmd.extend([
                    "-filter_complex",
                    f"[1:a]volume={volume}[a];[0:a][a]amix=inputs=2:duration=first:dropout_transition=2[outa]",
                    "-map", "0:v", "-map", "[outa]",
                ])
            else:
                cmd.extend([
                    "-filter_complex",
                    f"[1:a]volume={volume}[a]",
                    "-map", "0:v", "-map", "[a]",
                ])
            cmd.extend([
                "-c:v", "copy", "-c:a", "aac",
                "-shortest", output_path,
            ])
        else:
            if has_audio:
                cmd = [
                    self.ffmpeg, "-y",
                    "-i", video_path,
                    "-i", audio_path,
                    "-filter_complex",
                    f"[1:a]volume={volume}[a];[0:a][a]amix=inputs=2:duration=first:dropout_transition=2[outa]",
                    "-map", "0:v", "-map", "[outa]",
                    "-c:v", "copy", "-c:a", "aac",
                    "-shortest", output_path,
                ]
            else:
                cmd = [
                    self.ffmpeg, "-y",
                    "-i", video_path,
                    "-i", audio_path,
                    "-filter_complex",
                    f"[1:a]volume={volume}[a]",
                    "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac",
                    "-shortest", output_path,
                ]
        self._run_ffmpeg(cmd, output_path)

    # ======================== 滤镜辅助 ========================

    def _build_zoompan(self, frame: StoryboardFrame, width: int, height: int,
                       total_frames: int) -> str:
        """Ken Burns zoompan filter — 使用简单表达式避免 if/lte/min 崩溃"""
        zoom_rate = self._get_zoom_rate(frame, total_frames)

        st = getattr(frame, "shot_type", None)
        st_str = st.value if hasattr(st, "value") else str(st or "")

        # 判断是否平移（基于构图或景别）
        cam = (getattr(frame, "camera_movement", "") or "").lower()
        comp = (getattr(frame, "composition", "") or "").lower()

        if "pan" in cam or "平移" in cam or "水平" in comp:
            # 水平平移：zoom_level + x 偏移
            return (
                f"zoompan=z=zoom+{zoom_rate:.5f}:"
                f"d={total_frames}:s={width}x{height}:"
                f"x=min(x+1,iw-iw/zoom)"
            )
        elif st_str == "info_card":
            # 信息卡：不缩放
            return f"zoompan=z=1:d={total_frames}:s={width}x{height}"
        else:
            return f"zoompan=z=zoom+{zoom_rate:.5f}:d={total_frames}:s={width}x{height}"

    def _get_zoom_rate(self, frame: StoryboardFrame, total_frames: int) -> float:
        """计算每帧的 zoom 增量"""
        st = getattr(frame, "shot_type", None)
        st_str = st.value if hasattr(st, "value") else str(st or "")
        if st_str == "emotion_peak":
            zoom_end = 1.15
        elif st_str == "hook":
            zoom_end = 1.10
        elif st_str == "closing":
            zoom_end = 1.05
        elif st_str == "info_card":
            zoom_end = 1.0
        else:
            zoom_end = 1.06
        return (zoom_end - 1.0) / max(total_frames, 1)

    def _build_layer_filters(
        self, frame: StoryboardFrame, width: int, height: int
    ) -> list[str]:
        """从 frame.layers 构建 drawtext 滤镜（支持多个文字层）"""
        filters = []
        layers = getattr(frame, "layers", [])
        if not layers or not self.font_path:
            return filters

        for i, layer in enumerate(layers):
            if layer.get("type") != "text":
                continue
            content = layer.get("content", "")
            if not content:
                continue

            style = layer.get("style", {})
            font_size = style.get("fontSize", 36)
            color = style.get("color", "#FFFFFF")
            stroke_color = style.get("strokeColor", "")
            stroke_width = style.get("strokeWidth", 0)

            text_file = self.segments_dir / f"layer_{i}_{id(frame)}.txt"
            text_file.write_text(content, encoding="utf-8")
            sub_rel = f"segs/layer_{i}_{id(frame)}.txt"

            parts = [
                f"drawtext=textfile={sub_rel}",
                f"fontfile={self.font_path}",
                f"fontsize={font_size}",
                f"fontcolor={color}",
                "x=(w-text_w)/2",
                "y=(h-text_h)/2",
            ]
            if stroke_color and stroke_width > 0:
                parts.append(f"bordercolor={stroke_color}")
                parts.append(f"borderw={stroke_width}")

            filters.append(":".join(parts))

        return filters

    def _build_subtitle_filter(
        self, frame: StoryboardFrame, width: int, height: int
    ) -> Optional[str]:
        """生成 drawtext 滤镜字符串（使用相对路径）"""
        text = frame.subtitle_text
        if not text:
            return None
        cfg = getattr(frame, "subtitle_config", {}) or {}
        if isinstance(cfg, dict):
            font_size = cfg.get("fontSize", 36)
            v_align = cfg.get("verticalAlign", "bottom")
            color = cfg.get("color", "#ffffff")
            text_align = cfg.get("textAlign", "center")
            margin = cfg.get("marginFromEdge", 80)
            offset_x = cfg.get("offsetX", 0)
        else:
            font_size, v_align, color, text_align, margin, offset_x = 36, "bottom", "#ffffff", "center", 80, 0

        # 写字幕文件到工作目录（相对路径）
        sub_file = self.segments_dir / f"sub_{id(frame)}.txt"
        sub_file.write_text(text, encoding="utf-8")

        # 用文件名（不含路径）作为 textfile 值 — 因为 ffmpeg 的 cwd 是 self.ff_cwd
        sub_rel = f"segs/sub_{id(frame)}.txt"

        # 位置
        if text_align == "left":
            x = f"20+{offset_x}"
        elif text_align == "right":
            x = f"w-tw-20+{offset_x}"
        else:
            x = f"(w-tw)/2+{offset_x}"

        if v_align == "top":
            y = str(margin)
        elif v_align == "center":
            y = "(h-text_h)/2"
        else:
            y = f"h-{margin}"

        parts = [
            f"drawtext=textfile={sub_rel}",
        ]
        if self.font_path:
            parts.append(f"fontfile={self.font_path}")
        parts.extend([
            f"fontsize={font_size}",
            f"fontcolor={color}",
            f"x={x}", f"y={y}",
            "bordercolor=black@0.6", "borderw=2",
            "shadowcolor=black@0.4", "shadowx=2", "shadowy=2",
        ])
        return ":".join(parts)

    def _get_color_filter(self, frame: StoryboardFrame) -> Optional[str]:
        emotion = (getattr(frame, "emotion", "") or "").strip()
        if emotion in ("温馨", "治愈", "温暖"):
            return "colorbalance=rs=.1:gs=-.05:bs=-.1"
        elif emotion in ("平静", "日常"):
            return "eq=saturation=0.85:brightness=0.02"
        elif emotion in ("震撼", "活力", "热血"):
            return "eq=saturation=1.3:contrast=1.1"
        elif emotion in ("忧郁", "怀旧"):
            return "colorbalance=rs=-.05:gs=.05:bs=.1,hue=H=10"
        return None

    # ======================== 工具方法 ========================

    def _run_ffmpeg(self, cmd: list, output: str) -> Optional[str]:
        try:
            result = subprocess.run(
                cmd, cwd=str(self.ff_cwd),
                capture_output=True, text=False, timeout=120,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace")
                # 只保留最后 200 字符（跳过编译信息）
                lines = stderr.splitlines()
                tail = "\n".join(l for l in lines if "lib" not in l and "  --" not in l)[-300:]
                logger.warning(f"  FFmpeg 失败 (ret={result.returncode}): {tail}")
                return None
            return output
        except subprocess.TimeoutExpired:
            logger.warning(f"  FFmpeg 超时 (120s): {output}")
            return None
        except Exception as e:
            logger.warning(f"  FFmpeg 异常: {e}")
            return None

    def _cleanup(self, segments: list, concat_path: Optional[str]):
        import os
        for seg in segments:
            try:
                os.unlink(seg)
            except Exception:
                pass
        for f in self.segments_dir.glob("sub_*.txt"):
            try:
                os.unlink(str(f))
            except Exception:
                pass
        for f in self.segments_dir.glob("layer_*.txt"):
            try:
                os.unlink(str(f))
            except Exception:
                pass
