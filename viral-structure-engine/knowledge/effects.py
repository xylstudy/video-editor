"""Extract individual visual effects from recorded observations, without an LLM."""
import json
import math
import re
from collections import defaultdict

from models.knowledge import KnowledgeEntry, KnowledgeType

EFFECT_EXTRACTION_VERSION = "observed-effects-v1"

EFFECTS = {
    "sticker_face": ("卡通五官贴纸", "贴纸", "给物体添加眼睛、嘴巴，形成拟人化表情。"),
    "sticker_stars": ("头顶手绘反应贴纸", "贴纸", "将手绘反应符号叠在主体头顶，随主体移动；具体形状与情绪以原片为准。"),
    "sticker_anger": ("怒气涂鸦贴纸", "贴纸", "用弹出的手绘怒气符号强调主体反应。"),
    "sticker_arrow": ("指示箭头贴纸", "贴纸", "用箭头引导视线，突出画面里的关键物体。"),
    "sticker_pop": ("弹入文字贴纸", "贴纸", "用缩放弹入的文字或标志短暂打断节奏，强化视觉记忆。"),
    "sticker_doodle": ("主体跟随手绘贴纸", "贴纸", "将手绘符号叠在指定主体旁，按记录的路径运动。"),
    "subject_clone": ("主体复制增殖", "主体合成", "复制主体并改变位置和尺度，形成涌出、堆积的超现实画面。"),
    "subject_echo": ("主体多层残影", "主体合成", "叠加主体的多份残影，通过位移与透明度衰减强化运动轨迹。"),
    "torn_paper_outline": ("主体撕纸描边", "贴纸", "沿主体轮廓添加不规则白色撕纸边，突出主体与背景的分离。"),
    "subject_outline": ("主体描边", "主体合成", "围绕主体轮廓添加描边，突出画面重点。"),
    "grid_overlay": ("九宫格线叠层", "画面叠层", "在实拍画面上叠加九宫格线，强调构图与节奏停顿。"),
    "floating_music_ui": ("跨镜头音乐播放器", "UI叠层", "让音乐播放器浮层跨越镜头持续存在，建立统一的音乐视角。"),
    "foreground_silhouette": ("前景剪影叠加", "主体合成", "叠加前景剪影，与背景主体形成尺度或意象关系。"),
    "glitch_reveal": ("RGB故障叠层", "画面叠层", "短暂叠加色差和故障块，制造电子故障式的画面揭示。"),
    "film_grain": ("胶片颗粒", "画面叠层", "通过颗粒和噪点统一实拍画面的胶片质感。"),
    "search_cta_card": ("搜索引导界面卡", "UI叠层", "用搜索界面呈现收尾关键词，形成视觉收束与行动引导。"),
}
TRANSITIONS = {"cut", "fade", "dissolve", "whip", "occlusion_wipe", "slice_wipe", "black_dip", "mask", "wipe", "zoom_in", "zoom_out"}


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _effect_key(event):
    kind = str(event.get("type") or event.get("effect_type") or "").lower()
    if not kind or kind in TRANSITIONS or event.get("anchor") == "transition" and kind != "glitch_reveal":
        return None
    text = json.dumps([event.get("subject"), event.get("parameters")], ensure_ascii=False).lower()
    if kind in {"tracked_doodle", "doodle_pop", "sticker", "sticker_overlay", "animated_sticker", "sticker_pop", "arrow_sticker"}:
        if re.search("cursor|arrow|箭头|光标", text) or kind == "arrow_sticker":
            return "sticker_arrow"
        if re.search("星|晕眩|眩晕|star|dizzy", text):
            return "sticker_stars"
        if re.search("眼睛|嘴巴|五官|表情|eyes|mouth|face", text):
            return "sticker_face"
        if re.search("怒气|爆炸|anger", text):
            return "sticker_anger"
        if re.search("pop_in|scale_grow|停.*字|文字|弹入", text) or kind == "sticker_pop":
            return "sticker_pop"
        return "sticker_doodle"
    if kind in {"subject_echo", "echo_stack"}:
        return "subject_clone" if re.search("spawn_origin|increasing|涌出|增殖|堆积", text) else "subject_echo"
    if kind in {"cutout_outline", "torn_paper_frame"}:
        return "torn_paper_outline" if kind == "torn_paper_frame" or re.search("torn|撕纸", text) else "subject_outline"
    if kind == "grid_memory" or re.search("3x3|九宫格", text):
        return "grid_overlay"
    if kind in EFFECTS:
        return kind
    if kind in {"film_grain_dust", "grain"}:
        return "film_grain"
    # Keep an observed but unsupported effect inspectable; never turn it into
    # a different, supposedly supported effect or discard its source evidence.
    return "observed_" + re.sub(r"[^a-z0-9_]+", "_", kind)[:50]


def extract_effect_entries(report: dict, source_filename: str) -> list[KnowledgeEntry]:
    """Merge shot observations and global tracks, preserving the richer evidence."""
    observations = {}

    def add(raw, shot=None, source="effect_tracks"):
        if not isinstance(raw, dict):
            return
        shot = shot or {}
        start = raw.get("start", raw.get("start_time"))
        end = raw.get("end", raw.get("end_time"))
        if start is None:
            start = _number(shot.get("start_time")) + _number(raw.get("start_offset"))
        if end is None:
            end = _number(shot.get("start_time")) + _number(raw.get("end_offset"), _number(shot.get("end_time")) - _number(shot.get("start_time")))
        start, end = max(0, _number(start)), _number(end)
        total = _number(report.get("duration"))
        if total:
            end = min(end, total)
        if end <= start:
            return
        event = {**raw, "start_time": start, "end_time": end,
                 "shot_index": raw.get("source_shot_index", shot.get("shot_index", shot.get("index"))),
                 "evidence_source": source}
        identity = raw.get("id") or (str(raw.get("type")), event["shot_index"], round(start, 2), round(end, 2))
        previous = observations.get(identity, {})
        merged = {**previous, **{key: value for key, value in event.items() if value is not None and value != "" and value != [] and value != {}}}
        merged["parameters"] = {**(previous.get("parameters") or {}), **(event.get("parameters") or {})}
        observations[identity] = merged

    for event in report.get("effect_tracks") or []:
        add(event)
    for key in ("shots", "raw_shot_analyses"):
        for shot in report.get(key) or []:
            for event in shot.get("effect_events") or []:
                add(event, shot, key)
    grouped = defaultdict(list)
    for event in observations.values():
        key = _effect_key(event)
        if key:
            grouped[key].append(event)
    entries = []
    for key, evidence in grouped.items():
        title, category, instruction = EFFECTS.get(key, ("待归类画面特效", "待归类", "查看原片中的真实效果，保留参数以便补充对应实现。"))
        evidence.sort(key=lambda item: item["start_time"])
        representative = max(evidence, key=lambda item: _number(item.get("confidence"), .6))
        subjects = list(dict.fromkeys(str(item["subject"]) for item in evidence if item.get("subject")))
        entries.append(KnowledgeEntry(
            type=KnowledgeType.EFFECT_TYPE, title=title,
            content=instruction + (f"参考对象：{'、'.join(subjects[:3])}。" if subjects else ""),
            structured_data={"id": key, "effect_key": key, "category": category,
                             "extraction_version": EFFECT_EXTRACTION_VERSION,
                             "source_duration": _number(report.get("duration")),
                             "demo_mode": "reconstruction", "evidence": evidence,
                             "position": representative.get("position", {}),
                             "motion_path": representative.get("motion_path", []),
                             "mask_mode": representative.get("mask_mode", "none"),
                             "parameters": representative.get("parameters", {}),
                             "requires_subject_mask": any(item.get("mask_mode") == "subject_cutout" for item in evidence)},
            tags=["特效", category, title, key],
            best_when=instruction, confidence=max(_number(item.get("confidence"), .6) for item in evidence),
            source_summary=f"来源：参考视频《{source_filename}》中的{title}，共 {len(evidence)} 处已定位记录。",
        ))
    return entries


def effect_example_windows(entry: dict) -> list[dict]:
    """Short, non-overlapping windows around the effect, never invented timings."""
    data = entry.get("structured_data") or {}
    total = _number(data.get("source_duration"))
    windows = []
    for evidence in sorted(data.get("evidence") or [], key=lambda item: _number(item.get("start_time"))):
        if evidence.get("start_time") is None or evidence.get("end_time") is None:
            continue
        begin, end = _number(evidence["start_time"]), _number(evidence["end_time"])
        if begin < 0 or end <= begin or total and begin >= total:
            continue
        start = max(0, begin - .35)
        stop = max(start + 1.5, min(start + 6, end + .5))
        if total:
            stop = min(stop, total)
        if windows and start <= windows[-1]["start"] + windows[-1]["duration"]:
            stop = min(windows[-1]["start"] + 6, max(stop, windows[-1]["start"] + windows[-1]["duration"]))
            windows[-1]["duration"] = stop - windows[-1]["start"]
        elif len(windows) < 3 and stop - start >= .2:
            windows.append({"start": start, "duration": stop - start})
    return windows
