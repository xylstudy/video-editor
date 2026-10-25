"""Executable, full-frame footage examples derived from each knowledge entry."""
import hashlib
import json
import math
import re
import subprocess
import sqlite3
import wave
from pathlib import Path
from uuid import uuid4

import numpy as np
from render_knowledge_demos import DEMO_OUT_DIR, REMOTION_DIR
from effect_reconstruction import DemoUnavailable

DEMO_VERSION = "personal-effect-v3"
EFFECT_DEMO_VERSION = "personal-effect-v4"

def demo_version(entry):
    return EFFECT_DEMO_VERSION if entry.get("type") == "effect_type" else DEMO_VERSION
ROOT = REMOTION_DIR.parent.parent
SUPPORTED_TYPES = {"structure_template", "hook_technique", "rhythm_pattern", "emotion_design", "packaging_style", "effect_type"}


def _short(value, limit=38):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def reference_materials(video: Path, report_path: Path):
    """Extract non-overlapping real shot ranges; do not substitute stock or cards."""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report = {}
    ranges = []
    for shot in report.get("shots") or report.get("raw_shot_analyses") or []:
        start = float(shot.get("start_time", shot.get("start", 0)) or 0)
        end = float(shot.get("end_time", shot.get("end", 0)) or 0)
        if end - start >= .2 and (not ranges or start >= ranges[-1]["start"] + ranges[-1]["duration"] - .01):
            ranges.append({"path": str(video), "start": start, "duration": min(6, end - start),
                           "role": _short(shot.get("visual_description") or (shot.get("content") or {}).get("main_subject") or f"来源镜头 {len(ranges) + 1}", 20),
                           "origin": "reference_shots"})
    if len(ranges) < 2 and video.is_file():
        import cv2
        cap = cv2.VideoCapture(str(video))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps if fps else 0
        cap.release()
        count = min(6, int(total / .3))
        if count >= 2:
            ranges = [{"path": str(video), "start": index * total / count, "duration": min(6, total / count),
                       "role": f"来源片段 {index + 1}", "origin": "reference_shots"} for index in range(count)]
    if len(ranges) > 6:
        ranges = [ranges[index] for index in np.linspace(0, len(ranges) - 1, 6, dtype=int)]
    return ranges


def _material_candidates(entry):
    """Resolve this gene's own manifest/source; never choose by a known filename."""
    source = entry.get("__source_video_path")
    if not source:
        derivation = entry.get("derivation") or {}
        db_path = ROOT / "web/backend/app.db"
        if not db_path.is_file():
            return []
        with sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True) as connection:
            row = connection.execute("SELECT video_path FROM gene WHERE id=? AND user_id=?",
                                     (derivation.get("source_gene_id"), derivation.get("source_user_id"))).fetchone()
        source = row[0] if row else None
    if not source or not Path(source).is_file():
        return []
    video = Path(source)
    manifest_path = video.parent / "example_materials/manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        key = "effect_materials" if entry.get("type") == "effect_type" and manifest.get("effect_materials") else "materials"
        return [item for item in manifest.get(key, [])
                if item.get("origin") == "task_materials" and Path(item["path"]).is_file()]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _asset_name(material):
    path = Path(material["path"])
    stat = path.stat()
    key = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{material.get('start', 0)}:{material.get('duration', 6)}:540x960-30-6s-v2"
    if material.get("fit") == "contain":
        key += ":contain"
    return hashlib.sha256(key.encode()).hexdigest()[:24] + ".mp4"


def personal_demo_props(entry, materials):
    """Show a finished edit, with explicit operations and honest source provenance."""
    if entry.get("type") == "effect_type":
        from effect_reconstruction import focused_effect_props
        return focused_effect_props(entry, materials, _asset_name, DEMO_OUT_DIR / "footage_assets")
    if len(materials) < 2:
        raise DemoUnavailable("独立实拍素材不足，保留原片参考，等待补齐效果示例素材")
    materials = materials[:6]
    count = len(materials)
    if len({_asset_name(item) for item in materials}) != count:
        raise ValueError("同组演示中不重复使用素材")
    kind = entry.get("type")
    data = entry.get("structured_data") or {}
    text = json.dumps(data, ensure_ascii=False).lower()
    duration = count * 60
    order = list(range(count))
    lengths = [duration // count] * count
    labels = [item.get("role", "") for item in materials]
    technique = "镜头组织"
    motion = "none"
    if kind == "hook_technique":
        hero = next((i for i, label in enumerate(labels) if "钩子" in label or "符号" in label), count - 1)
        order = [hero] + [i for i in order if i != hero]
        lengths = [24, 36] + [max(30, (duration - 60) // (count - 2))] * (count - 2) if count > 2 else [24, duration - 24]
        technique = "强画面前置 · 前三秒抓眼"
        motion = "punch"
    elif kind == "rhythm_pattern":
        curve = (data.get("rhythm_analysis") or {}).get("curve_points") or []
        intensities = [float(point.get("intensity", .5)) for point in curve]
        weights = (1.25 - np.interp(np.linspace(0, len(intensities) - 1, count), np.arange(len(intensities)), intensities)
                   if intensities else np.array([1, .5, 1.5, 1, 4, 4])[:count])
        lengths = [max(15, round(value / sum(weights) * duration / 15) * 15) for value in weights]
        technique = "鼓点切镜 · 快慢反差 · 留出呼吸"
    elif kind == "emotion_design":
        lively = bool(re.search("轻快|活力|热烈|欢乐", text))
        lengths = ([30, 45, 30, 60, 75, 120] if lively else [75, 45, 45, 45, 60, 90])[:count]
        lengths = [max(15, round(value / sum(lengths) * duration / 15) * 15) for value in lengths]
        technique = f"{_short(data.get('overall_emotion') or '情绪递进', 16)} · {'轻快短切' if lively else '舒缓叠化'} · 留白收束"
        motion = "drift"
    elif kind == "structure_template":
        stages = data.get("script_structure") or []
        if stages:
            weights = [max(.2, float(stage.get("duration_hint") or 1)) for stage in stages]
            weights = np.interp(np.linspace(0, len(weights) - 1, count), np.arange(len(weights)), weights)
            lengths = [max(15, round(value / sum(weights) * duration / 15) * 15) for value in weights]
        else:
            lengths = [30, 45, 45, 60, 75, 105] if count == 6 else lengths
        technique = _short(" → ".join(str(stage.get("purpose", "")) for stage in stages), 58) or "开场 → 场景 → 细节 → 高潮 → 收束"
    else:
        technique = "实拍画面上的包装效果"
    lengths[-1] += duration - sum(lengths)
    # A source asset contains 180 frames; no clip may read past it.
    for index in range(count):
        overflow = max(0, lengths[index] - 180)
        lengths[index] -= overflow
        for other in range(count):
            if other != index:
                extra = min(overflow, 180 - lengths[other])
                lengths[other] += extra
                overflow -= extra
    reference_recut = all(item.get("origin") == "reference_shots" for item in materials)
    if reference_recut:
        raise DemoUnavailable("参考原片不能充当效果示例，请提供独立实拍素材")
    # Only independent task footage may receive reconstructed overlays.
    packaging = kind == "packaging_style" and not reference_recut
    music_ui = not reference_recut and kind in {"packaging_style", "hook_technique"} and bool(re.search("播放器|勿扰|music_ui|ui浮层", text))
    doodle = packaging and bool(re.search("怒气|涂鸦|手绘卡通", text))
    paper = packaging and bool(re.search("撕纸", text))
    echo = packaging and bool(re.search("叠影|重影", text))
    glitch = packaging and bool(re.search("glitch|故障", text))
    slices = packaging and bool(re.search("slice_wipe|切片|百叶", text))
    film = not reference_recut and bool(re.search("film|胶片|颗粒|忧郁|怅然|伤感", text))
    grade = "original" if reference_recut else "film" if film else "fresh" if re.search("japanese_fresh|红色|轻快", text) else "cinematic" if "cinematic" in text else "warm"
    subtitle = packaging and bool(re.search("底部.*(短字幕|短句|黄色)|字幕.*串联", text))
    black_dip = packaging and bool(re.search("black_dip|暗场|黑场", text))
    edited = []
    used_effects = set()
    for position, index in enumerate(order):
        effect = ""
        if packaging:
            if doodle and "doodle" not in used_effects and (re.search("贴纸|狗|dog|pet", labels[index], re.I) or position == min(2, count - 1)):
                effect = "doodle"
            elif paper and "paper" not in used_effects and (re.search("细节|动作|drink|pour|bottle|apple", labels[index], re.I) or position == min(3, count - 1)):
                effect = "paper"
            elif echo and position == 1:
                effect = "echo"
            used_effects.add(effect)
        edited.append({"src": _asset_name(materials[index]), "duration": lengths[position], "role": labels[index], "effect": effect,
                       "playback_rate": 6 / min(6, max(.2, float(materials[index].get("source_duration") or materials[index].get("duration") or 6))) if reference_recut else 1,
                       "motion": motion if kind != "hook_technique" or position == 0 else "none",
                       "transition": "glitch" if glitch and position == 1 else "slice_wipe" if slices and position == min(4, count - 1) else "dissolve" if kind == "emotion_design" and not re.search("轻快|活力|热烈|欢乐", text) and position else "cut"})
    if packaging and used_effects - {""}:
        # A teaching clip should open on the demonstrated effect, rather than
        # making the viewer wait through an ordinary establishing shot.
        edited.sort(key=lambda clip: {"doodle": 0, "paper": 1, "echo": 2}.get(clip["effect"], 3))
    effect_labels = [label for enabled, label in [(music_ui, "跨镜头音乐 UI"), ("doodle" in used_effects, "趣味涂鸦"), ("paper" in used_effects, "撕纸画框"), ("echo" in used_effects, "动态重影"), (any(clip["transition"] == "glitch" for clip in edited), "RGB 故障转场"), (any(clip["transition"] == "slice_wipe" for clip in edited), "切片转场"), (film, "胶片色调")] if enabled]
    if packaging and effect_labels:
        technique = " · ".join(effect_labels)
    elif kind == "packaging_style" and reference_recut:
        technique = "原片应用 · " + (" / ".join(str(track.get("type", "")) for track in data.get("effect_tracks", [])[:3]) or "场景衔接与画面包装")
    return {
        "title": _short(entry.get("title")), "knowledge_type": kind, "duration_frames": duration,
        "reference_recut": reference_recut,
        "edited": edited, "technique": technique, "grade": grade, "film": film, "music_ui": music_ui,
        "subtitle": subtitle, "black_dip": black_dip,
        "search_cta": packaging and bool(re.search("search_cta|搜索", text)),
        "audio": "demo-beat-120bpm.wav",
        "source": "来源参考片的实际应用片段；原有包装保留" if reference_recut else "使用本次任务实拍素材重新制作的技法示例；示例鼓点 120 BPM",
    }


def _prepare_assets(materials, asset_dir):
    from tools.video_tools import _find_ffmpeg
    asset_dir.mkdir(parents=True, exist_ok=True)
    for material in materials:
        output = asset_dir / _asset_name(material)
        if output.is_file() and output.stat().st_size > 0:
            continue
        temporary = output.with_name(f"{output.stem}.{uuid4().hex}.partial.mp4")
        try:
            import cv2
            cap = cv2.VideoCapture(material["path"])
            fps = cap.get(cv2.CAP_PROP_FPS)
            source_duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps if fps else 0
            cap.release()
            start = max(0, float(material.get("start", 0)))
            selected = min(6, float(material.get("duration", 6)), source_duration - start)
            if selected <= 0:
                raise RuntimeError("实拍素材没有可用的视频帧")
            framing = "scale=540:960:force_original_aspect_ratio=decrease,pad=540:960:(ow-iw)/2:(oh-ih)/2" if material.get("fit") == "contain" else "scale=540:960:force_original_aspect_ratio=increase,crop=540:960"
            filters = f"setpts={6 / selected:.8f}*(PTS-STARTPTS),{framing},fps=30"
            result = subprocess.run([_find_ffmpeg(), "-y", "-ss", str(start), "-t", str(selected), "-i", material["path"], "-t", "6", "-an", "-vf", filters, "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", str(temporary)], capture_output=True, timeout=180)
            if result.returncode or not temporary.is_file() or not temporary.stat().st_size:
                raise RuntimeError(f"素材预处理失败：{Path(material['path']).name}")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    beat_path = asset_dir / "demo-beat-120bpm.wav"
    if not beat_path.is_file():
        rate, seconds = 44100, 12
        audio = np.zeros(rate * seconds)
        rng = np.random.default_rng(17)
        for beat in range(seconds * 2):
            start = round(beat * .5 * rate)
            t = np.arange(round(.25 * rate)) / rate
            kick = np.sin(2 * math.pi * (48 * t + 20 * (.07 * (1 - np.exp(-t / .07))))) * np.exp(-t * 22)
            audio[start:start + len(kick)] += .45 * kick
            if beat % 2:
                audio[start:start + len(t)] += .11 * rng.normal(size=len(t)) * np.exp(-t * 40)
        with wave.open(str(beat_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes((np.clip(audio, -1, 1) * 22000).astype("<i2").tobytes())


def render_personal_teaching_demos(entries, force=False):
    """Replace diagram videos with real edited footage; preserve reference clips."""
    DEMO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    asset_dir = DEMO_OUT_DIR / "footage_assets"
    todo, existing, failed, all_materials, pending = [], 0, [], {}, []
    for entry in entries:
        entry_id = entry.get("id", "")
        if not re.fullmatch(r"k_u\d+_[A-Za-z0-9_]+", entry_id) or entry.get("type") not in SUPPORTED_TYPES:
            continue
        materials = _material_candidates(entry)
        try:
            props = personal_demo_props(entry, materials)
        except DemoUnavailable as error:
            pending.append({"id": entry_id, "reason": str(error)})
            (DEMO_OUT_DIR / f"{entry_id}.teaching.json").write_text(json.dumps({
                "mode": demo_version(entry), "status": "pending", "reason": str(error)
            }, ensure_ascii=False), encoding="utf-8")
            continue
        except (ValueError, OSError):
            failed.append(entry_id)
            continue
        fingerprint = hashlib.sha256(json.dumps([demo_version(entry), props, entry.get("structured_data"), entry.get("content")], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        output = DEMO_OUT_DIR / f"{entry_id}.teaching.mp4"
        metadata = DEMO_OUT_DIR / f"{entry_id}.teaching.json"
        try:
            current = json.loads(metadata.read_text(encoding="utf-8")).get("fingerprint") == fingerprint
        except (OSError, ValueError):
            current = False
        if output.is_file() and output.stat().st_size > 0 and current and not force:
            existing += 1
        else:
            todo.append({"id": entry_id, "title": props["title"], "input_props": props, "fingerprint": fingerprint,
                         "mode": demo_version(entry), "render_token": uuid4().hex, "materials": materials})
            all_materials.update({_asset_name(item): item for item in materials})
    if todo:
        _prepare_assets(list(all_materials.values()), asset_dir)
        plan_path = REMOTION_DIR / f"demo_batch_{uuid4().hex}.json"
        plan_path.write_text(json.dumps({"output_dir": str(DEMO_OUT_DIR.resolve()), "asset_dir": str(asset_dir.resolve()), "personal": True, "entries": todo}, ensure_ascii=False), encoding="utf-8")
        try:
            subprocess.run(["node", str(REMOTION_DIR / "render-knowledge-demos.mjs"), str(plan_path)], cwd=str(REMOTION_DIR), timeout=max(600, len(todo) * 180), check=False)
        finally:
            plan_path.unlink(missing_ok=True)
        for item in todo:
            try:
                metadata = json.loads((DEMO_OUT_DIR / f"{item['id']}.teaching.json").read_text(encoding="utf-8"))
                if metadata.get("render_token") != item["render_token"]:
                    raise ValueError("render did not complete")
            except (OSError, ValueError):
                failed.append(item["id"])
    return {"teaching_demos_rendered": len(todo) - sum(item["id"] in failed for item in todo), "teaching_demos_existing": existing, "teaching_demo_failures": failed, "teaching_demo_pending": pending}
