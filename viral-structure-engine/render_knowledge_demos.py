# -*- coding: utf-8 -*-
"""批量渲染知识库技法的演示视频。

为 knowledge.json 中每个知识条目渲染一段独立演示短片（Remotion TechniqueDemo 合成），
输出到 web/backend/storage/knowledge_demos/{entry_id}.mp4，供 Web 端知识库卡片播放。

用法：
    python render_knowledge_demos.py              # 渲染全部（跳过已存在）
    python render_knowledge_demos.py --only k_0   # 只渲染指定条目
    python render_knowledge_demos.py --force      # 全部重渲
    python render_knowledge_demos.py --built-in   # 仅补齐内置技法，不处理个人知识
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

VSE_DIR = Path(__file__).resolve().parent
REMOTION_DIR = VSE_DIR / "remotion"
KNOWLEDGE_JSON = VSE_DIR / "data" / "knowledge_db" / "knowledge.json"
DEMO_OUT_DIR = VSE_DIR.parent / "web" / "backend" / "storage" / "knowledge_demos"

REVEAL_IDS = {"float_up", "scale_burst", "tilt_3d", "glow_fade", "parallax", "split", "blur_in"}
SUBTITLE_IDS = {"typewriter", "neon_sign", "gradient_bar", "scale_bounce", "slide_crop", "letter_fall", "wave", "cinematic"}

# 无 structured_data.id 的抽象剪辑原则 → 演示类型映射
ABSTRACT_TECHNIQUE_MAP = {
    "前3秒抓眼球": ("montage", "hook"),
    "音乐卡点": ("beat", "beat"),
    "5段式情绪设计": ("emotion_arc", "emotion_arc"),
    "前景背景分离": ("reveal", "float_up"),
    "速度对比": ("effect", "speed_ramp_slow"),
    "转场不做重复": ("variety", "variety"),
    "胶片质感": ("effect", "film_grain_dust"),
}


def demo_spec(entry: dict) -> tuple[str, str]:
    """根据知识条目推断 (kind, tech_id)。"""
    etype = entry.get("type", "")
    sd_id = (entry.get("structured_data") or {}).get("id", "")

    # 用户分析报告自动归纳出的五类知识，映射到对应的教学型合成，
    # 避免全部回退为无关的字幕动画。
    if etype == "structure_template":
        return "emotion_arc", "structure_arc"
    if etype == "hook_technique":
        return "montage", "hook"
    if etype == "rhythm_pattern":
        return "beat", "beat"
    if etype == "emotion_design":
        return "emotion_arc", "emotion_arc"
    if etype == "transition_type":
        return "transition", sd_id or "cut"
    if etype == "effect_type":
        return "effect", sd_id or "film_grain"
    if etype == "packaging_style":
        return "packaging", sd_id or "douyin_travel_fast"
    # editing_technique
    if sd_id in REVEAL_IDS:
        return "reveal", sd_id
    if sd_id in SUBTITLE_IDS:
        return "subtitle", sd_id
    return ABSTRACT_TECHNIQUE_MAP.get(entry.get("title", ""), ("subtitle", "scale_bounce"))


def render_one(entry: dict, timeout: int = 600) -> tuple[bool, str]:
    kind, tech_id = demo_spec(entry)
    props = {"kind": kind, "tech_id": tech_id, "title": entry.get("title", "")}
    props_file = REMOTION_DIR / f"demo_props_{entry['id']}.json"
    props_file.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")

    out_path = DEMO_OUT_DIR / f"{entry['id']}.mp4"
    DEMO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
    cmd = [
        npx_cmd, "remotion", "render",
        str((REMOTION_DIR / "src/index.ts").resolve().as_posix()),
        "TechniqueDemo",
        str(out_path),
        f"--props={props_file}",
        "--overwrite",
        "--log=error",
    ]
    try:
        result = subprocess.run(cmd, cwd=str(REMOTION_DIR), capture_output=True, timeout=timeout)
        if result.returncode == 0 and out_path.exists():
            return True, f"{out_path.stat().st_size / 1024:.0f}KB"
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")
        return False, stderr[-400:]
    except subprocess.TimeoutExpired:
        return False, f"渲染超时（>{timeout}s）"
    finally:
        props_file.unlink(missing_ok=True)


def _source_fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def render_source_demo(
    entry: dict,
    source_video: Path,
    output_path: Path,
    timeout: int = 180,
) -> tuple[bool, str]:
    """Create a short example from the actual reference video behind a user gene."""
    from tools.video_tools import _find_ffmpeg

    if not source_video.is_file():
        return False, f"源视频不存在: {source_video}"
    kind = entry.get("type", "")
    start_by_type = {
        "structure_template": 0.0,
        "hook_technique": 0.0,
        "rhythm_pattern": 2.0,
        "emotion_design": 5.0,
        "packaging_style": 8.0,
    }
    start = start_by_type.get(kind, 0.0)
    duration = 3.0 if kind == "hook_technique" else 5.0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _find_ffmpeg(), "-y", "-ss", str(start), "-i", str(source_video),
        "-t", str(duration), "-an",
        "-vf", "scale=540:960:force_original_aspect_ratio=increase,crop=540:960",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(VSE_DIR),
            capture_output=True,
            timeout=timeout,
        )
        # Very short references do not have an eight-second packaging window.
        # Retry from the beginning so every extracted knowledge item still
        # receives a clip from the user's actual video.
        if (result.returncode != 0 or not output_path.is_file()) and start > 0:
            output_path.unlink(missing_ok=True)
            retry_cmd = list(cmd)
            retry_cmd[retry_cmd.index("-ss") + 1] = "0"
            result = subprocess.run(
                retry_cmd,
                cwd=str(VSE_DIR),
                capture_output=True,
                timeout=timeout,
            )
        if result.returncode == 0 and output_path.is_file() and output_path.stat().st_size > 0:
            meta_path = output_path.with_suffix(output_path.suffix + ".source.json")
            meta_path.write_text(
                json.dumps({
                    "entry_id": entry.get("id"),
                    "source_video": str(source_video.resolve()),
                    "source_fingerprint": _source_fingerprint(source_video),
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True, f"{output_path.stat().st_size / 1024:.0f}KB"
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")
        return False, stderr[-400:]
    except subprocess.TimeoutExpired:
        return False, f"渲染超时（>{timeout}s）"


def select_demo_entries(entries: list[dict], only: str | None = None, built_in: bool = False) -> list[dict]:
    """Keep built-in teaching renders separate from source-specific personal clips."""
    return [
        entry for entry in entries
        if (not only or entry.get("id") == only)
        and (not built_in or re.fullmatch(r"k_\d+", str(entry.get("id", ""))))
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="只渲染指定条目 id（如 k_0）")
    parser.add_argument("--force", action="store_true", help="已存在也重渲")
    parser.add_argument("--built-in", action="store_true", help="仅渲染内置技法（k_数字），保留个人知识的源视频示例")
    args = parser.parse_args()

    entries = json.loads(KNOWLEDGE_JSON.read_text(encoding="utf-8"))
    if isinstance(entries, dict):
        entries = list(entries.get("entries", entries).values())

    DEMO_OUT_DIR.mkdir(parents=True, exist_ok=True)

    todo = []
    for e in select_demo_entries(entries, only=args.only, built_in=args.built_in):
        out = DEMO_OUT_DIR / f"{e['id']}.mp4"
        if out.is_file() and out.stat().st_size > 0 and not args.force:
            continue
        todo.append(e)

    print(f"共 {len(entries)} 条知识，待渲染 {len(todo)} 条")
    if args.built_in:
        if not todo:
            print("内置技法演示已齐全，无需渲染")
            return
        plan_path = REMOTION_DIR / f"demo_batch_{uuid4().hex}.json"
        plan_path.write_text(json.dumps({
            "output_dir": str(DEMO_OUT_DIR.resolve()),
            "entries": [
                {"id": entry["id"], "title": entry.get("title", ""),
                 "kind": demo_spec(entry)[0], "tech_id": demo_spec(entry)[1]}
                for entry in todo
            ],
        }, ensure_ascii=False), encoding="utf-8")
        try:
            result = subprocess.run(
                ["node", str(REMOTION_DIR / "render-knowledge-demos.mjs"), str(plan_path)],
                cwd=str(REMOTION_DIR),
            )
            if result.returncode:
                sys.exit(result.returncode)
        finally:
            plan_path.unlink(missing_ok=True)
        return
    ok, fail = 0, []
    t0 = time.time()
    for i, e in enumerate(todo, 1):
        kind, tech_id = demo_spec(e)
        t1 = time.time()
        success, info = render_one(e)
        cost = time.time() - t1
        if success:
            ok += 1
            print(f"[{i}/{len(todo)}] OK  {e['id']} {e['title']} ({kind}/{tech_id}) {info} {cost:.0f}s", flush=True)
        else:
            fail.append(e["id"])
            print(f"[{i}/{len(todo)}] FAIL {e['id']} {e['title']}: {info}", flush=True)

    print(f"\n完成：成功 {ok}，失败 {len(fail)}，耗时 {time.time() - t0:.0f}s")
    if fail:
        print("失败条目:", ", ".join(fail))
        sys.exit(1)


if __name__ == "__main__":
    main()
