"""
统一的 Remotion 渲染封装。

负责：
- 收集素材并复制到临时目录
- 启动本地 HTTP 服务供 Remotion（Chrome）加载素材
- 生成 input props 文件
- 调用 npx remotion render
- 清理临时文件

Chrome 禁止通过 file:// 协议加载本地媒体，因此必须通过本地 HTTP 服务暴露素材。
"""

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
from copy import deepcopy
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from config import settings

logger = logging.getLogger(__name__)

REMOTION_DIR = Path(__file__).resolve().parent.parent / "remotion"
DEFAULT_COMPOSITION = "VideoScheme"
DEFAULT_TIMEOUT = 1800  # 30 分钟


class _SilentHandler(SimpleHTTPRequestHandler):
    """不输出访问日志的 HTTP 请求处理器，并补充常见媒体 MIME 类型。"""

    _MIME_MAP = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".aac": "audio/aac",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(kwargs.pop("directory")), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def guess_type(self, path):
        _, ext = os.path.splitext(path)
        return self._MIME_MAP.get(ext.lower()) or super().guess_type(path)


def _find_free_port() -> int:
    """自动寻找本机空闲 TCP 端口。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _normalize_materials(material_items: list[Any]) -> list[dict[str, str]]:
    """
    把传入的素材列表统一转换为 {'id': str, 'path': str} 的字典列表。
    支持：对象（有 id/path 属性）、字典、{'items': [...]} 的容器。
    """
    if material_items is None:
        return []

    # 如果传入的是 inventory 对象，先取它的 items/materials 属性
    if hasattr(material_items, "items"):
        material_items = material_items.items
    elif hasattr(material_items, "materials"):
        material_items = material_items.materials

    result = []
    for m in material_items:
        if isinstance(m, dict):
            mid = m.get("id", "")
            mpath = m.get("path", "")
        else:
            mid = getattr(m, "id", "")
            mpath = getattr(m, "path", "")

        if mid and mpath:
            result.append({"id": str(mid), "path": str(mpath)})
        else:
            logger.warning(f"跳过无效素材: id={mid}, path={mpath}")

    return result


def _scheme_to_dict(scheme: Any) -> dict:
    """把 VideoScheme 对象或字典统一转成字典。"""
    if isinstance(scheme, dict):
        return scheme
    if hasattr(scheme, "to_dict"):
        return scheme.to_dict()
    raise TypeError(f"scheme 必须是 dict 或带有 to_dict() 的对象，实际为 {type(scheme)}")


def _safe_props_filename(input_props: dict) -> str:
    """生成一个稳定的临时 props 文件名。"""
    storyboard = input_props.get("scheme", {}).get("storyboard", [])
    return f"input_props_{abs(hash(json.dumps(storyboard, sort_keys=True)))}.json"


def _fallback_custom_video_components(scheme: dict, materials: list[dict[str, str]]) -> dict:
    """Use the video-aware auto renderer when an image-only custom effect receives video."""
    result = deepcopy(scheme)
    video_safe_custom_components = {
        "custom:split_screen_burst",
        "custom:beat_montage",
        "custom:hero_push_in",
        "custom:cinematic_grain",
        "custom:neon_light_rays",
        "custom:floating_music_ui",
        "custom:search_cta_card",
        "custom:echo_stack",
        "custom:doodle_pop",
        "custom:sticker_doodle",
        "custom:torn_paper_frame",
        "custom:grid_memory",
        "custom:panel_fold_reveal",
    }
    video_ids = {
        item["id"]
        for item in materials
        if Path(item["path"]).suffix.lower() in {".mp4", ".mov", ".webm", ".avi", ".mkv"}
    }
    for frame in result.get("storyboard", []):
        component = str(frame.get("render_component") or "auto")
        if not component.startswith("custom:"):
            continue
        if component in video_safe_custom_components:
            continue
        config = frame.get("custom_render_config") or {}
        referenced = {
            frame.get("source_material_id"),
            frame.get("fg_source_id"),
            frame.get("bg_source_id"),
            *(config.get("source_material_ids") or []),
            *(config.get("material_ids") or []),
        }
        if any(material_id in video_ids for material_id in referenced if material_id):
            frame["render_component"] = "auto"
            frame["render_fallback"] = {
                "from": component,
                "reason": "custom component is image-only while the selected material is video",
            }
    return result


def render_with_remotion(
    scheme: Any,
    material_items: list[Any],
    output_path: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    composition: str = DEFAULT_COMPOSITION,
) -> str | None:
    """
    使用 Remotion 渲染视频。

    Args:
        scheme: 视频方案，可以是 dict 或 VideoScheme 对象。
        material_items: 素材列表，可以是 dict 列表、MaterialItem 对象列表或 inventory 对象。
        output_path: 最终视频输出路径。
        timeout: Remotion 渲染超时时间（秒），默认 1800。
        composition: Remotion composition 名称，默认 "VideoScheme"。

    Returns:
        渲染成功返回输出路径，失败返回 None。
    """
    if not REMOTION_DIR.exists():
        logger.warning(f"Remotion 项目目录不存在: {REMOTION_DIR}")
        return None

    scheme_dict = _scheme_to_dict(scheme)
    materials = _normalize_materials(material_items)
    scheme_dict = _fallback_custom_video_components(scheme_dict, materials)

    media_root = None
    run_temp_root = None
    process_temp_root = None
    httpd = None
    httpd_thread = None
    props_file = None

    try:
        # 1) 在项目盘创建隔离临时目录，避免 Windows 系统盘空间不足。
        temp_parent = REMOTION_DIR / ".render-tmp"
        temp_parent.mkdir(parents=True, exist_ok=True)
        # tempfile.mkdtemp() can inherit restrictive ACLs in some Windows shells;
        # explicit project-local directories remain writable by the render process.
        run_temp_root = temp_parent / f"vse_remotion_{uuid4().hex}"
        process_temp_root = temp_parent / f"remotion_process_{uuid4().hex}"
        run_temp_root.mkdir()
        process_temp_root.mkdir()
        media_root = run_temp_root
        material_map: dict[str, str] = {}
        for m in materials:
            src = Path(m["path"])
            if not src.exists():
                logger.warning(f"素材文件不存在，跳过: {src}")
                continue
            ext = src.suffix.lower() or ".jpg"
            dst = media_root / f"{m['id']}{ext}"
            shutil.copy2(src, dst)
            material_map[m["id"]] = f"/{m['id']}{ext}"

        if not material_map:
            logger.warning("没有可渲染的素材，取消 Remotion 渲染")
            return None

        # 2) 启动本地 HTTP 服务
        port = _find_free_port()
        httpd = ThreadingHTTPServer(("127.0.0.1", port), lambda *args, **kwargs: _SilentHandler(*args, directory=media_root, **kwargs))
        httpd_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        httpd_thread.start()
        logger.info(f"素材 HTTP 服务已启动: http://127.0.0.1:{port} ({len(material_map)} 个素材)")

        # 3) 生成 input props
        http_map = {mid: f"http://127.0.0.1:{port}{path}" for mid, path in material_map.items()}
        input_props = {"scheme": scheme_dict, "material_map": http_map}
        props_file = REMOTION_DIR / _safe_props_filename(input_props)
        props_file.write_text(json.dumps(input_props, ensure_ascii=False), encoding="utf-8")

        # 4) 调用 Remotion CLI
        output_path_obj = Path(output_path)
        output_path_obj.parent.mkdir(parents=True, exist_ok=True)
        entry = (REMOTION_DIR / "src/index.ts").resolve().as_posix()
        npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
        cmd = [
            npx_cmd, "remotion", "render",
            entry, composition, str(output_path_obj),
            f"--props={props_file}",
            "--overwrite",
            "--log=verbose",
            "--timeout=120000",
            "--concurrency=1",
        ]

        logger.info(f"Remotion 渲染命令: {' '.join(cmd)}")
        render_env = os.environ.copy()
        # 仅影响本次子进程；Remotion/esbuild/Chromium 的临时文件不会写入 C 盘。
        render_env["TEMP"] = str(process_temp_root)
        render_env["TMP"] = str(process_temp_root)
        result = subprocess.run(
            cmd,
            cwd=str(REMOTION_DIR),
            capture_output=True,
            text=False,
            timeout=timeout,
            env=render_env,
        )

        if result.returncode == 0:
            size_mb = output_path_obj.stat().st_size / 1024 / 1024
            logger.info(f"Remotion 渲染完成: {output_path} ({size_mb:.1f}MB)")
            return str(output_path_obj)

        # 失败时保存完整 stderr 日志
        full_stderr = result.stderr.decode("utf-8", errors="replace")
        log_dir = settings.RUNS_DIR / "remotion_errors"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = __import__("time").strftime("%Y%m%d_%H%M%S")
        err_path = log_dir / f"remotion_error_{ts}.log"
        err_path.write_text(full_stderr, encoding="utf-8")
        logger.error(f"Remotion 渲染失败，日志已保存: {err_path}")
        logger.error(f"Remotion stderr (尾段): {full_stderr[-800:]}")
        return None

    except subprocess.TimeoutExpired:
        logger.error(f"Remotion 渲染超时（>{timeout}s）")
        return None
    except FileNotFoundError:
        logger.error("npx 未找到，请确认已安装 Node.js 并在 PATH 中")
        return None
    except Exception as e:
        logger.exception(f"Remotion 渲染异常: {e}")
        return None
    finally:
        if props_file is not None:
            props_file.unlink(missing_ok=True)
        if httpd is not None:
            httpd.shutdown()
        if run_temp_root is not None:
            shutil.rmtree(run_temp_root, ignore_errors=True)
        if process_temp_root is not None:
            shutil.rmtree(process_temp_root, ignore_errors=True)
