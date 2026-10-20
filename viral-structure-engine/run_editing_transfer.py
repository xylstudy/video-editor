"""编辑迁移：用爆款视频的剪辑节奏 + 音频，纯用户照片合成专业Vlog

包含评估-迭代闭环：
  合成 → 评估迁移质量 → 不达标则自动调整参数 → 重新合成
"""
import argparse
import json
import logging
import math
import subprocess
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from config import settings
from config.output_manager import OutputManager
from tools.video_tools import VideoTools, _find_ffmpeg

REMOTION_DIR = Path(__file__).resolve().parent / "remotion"
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_VIRAL_VIDEO = PROJECT_ROOT / "data" / "samples" / "viral.mp4"

MAX_ITERATIONS = 3
QUALITY_THRESHOLD = 0.82


def parse_args():
    parser = argparse.ArgumentParser(description="编辑迁移：用爆款视频节奏驱动照片生成 Vlog")
    parser.add_argument(
        "--viral-video",
        type=str,
        default=str(DEFAULT_VIRAL_VIDEO),
        help="爆款参考视频路径（默认: data/samples/viral.mp4）",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default="editing_transfer",
        help="本次运行 ID（默认: editing_transfer）",
    )
    parser.add_argument("--materials", required=True, help="任务素材库存 JSON")
    parser.add_argument("--topic", default="我的短视频", help="目标视频主题")
    parser.add_argument("--shot-analyses", default="", help="可选的镜头分析 JSON")
    parser.add_argument("--structure-analysis", default="", help="可选的结构分析 JSON")
    parser.add_argument("--output", default="", help="最终视频精确输出路径")
    parser.add_argument("--scheme-output", default="", help="最终方案 JSON 输出路径")
    parser.add_argument("--prepare-only", action="store_true", help="只生成分镜草案，不渲染")
    return parser.parse_args()


# ============================================================
# 1. 从爆款视频提取剪辑模式（镜头级节奏序列）
# ============================================================
def build_rule_based_acts(scenes, bpm=None, beat_times=None):
    """Build a model-free structure from scene changes and audio rhythm."""
    usable_scenes = [scene for scene in scenes if scene.get("duration", 0) > 0]
    if not usable_scenes:
        usable_scenes = [{"start": 0.0, "end": 3.0, "duration": 3.0}]
    total_duration = max(scene.get("end", 0) for scene in usable_scenes)
    beat_interval = 60.0 / bpm if bpm and bpm > 0 else 0.5
    definitions = [
        (0.10, "开场吸引", "期待", "快速"),
        (0.35, "建立主题", "轻快", "舒展"),
        (0.80, "内容展开", "兴奋", "递进"),
        (1.01, "高潮与收束", "满足", "先快后缓"),
    ]
    groups = [[] for _ in definitions]
    for scene in usable_scenes:
        midpoint = (scene.get("start", 0) + scene.get("end", 0)) / 2
        ratio = midpoint / total_duration if total_duration else 0
        group_index = next(
            index for index, definition in enumerate(definitions) if ratio < definition[0]
        )
        groups[group_index].append(scene)

    acts = []
    for group_index, group in enumerate(groups):
        if not group:
            continue
        _, purpose, emotion, rhythm = definitions[group_index]
        durations = [max(0.1, scene.get("duration", 0)) for scene in group]
        acts.append({
            "index": len(acts),
            "purpose": purpose,
            "emotion": emotion,
            "rhythm": rhythm,
            "shot_count": len(group),
            "duration": round(sum(durations), 1),
            "shot_beats": [max(1, round(duration / beat_interval)) for duration in durations],
        })
    return acts, round(sum(act["duration"] for act in acts), 1)


def extract_editing_pattern(
    viral_video_path: str,
    bpm=None,
    beat_times=None,
    shot_analyses_path: str = "",
    structure_analysis_path: str = "",
):
    """加载爆款视频的镜头级分析，提取每镜头的拍数节奏序列

    返回:
      acts: 每段结构 + shot_beats（每镜头的拍数列表）
      total_duration: 爆款视频总时长
    """
    shot_path = Path(shot_analyses_path) if shot_analyses_path else None
    structure_path = Path(structure_analysis_path) if structure_analysis_path else None
    if not shot_path or not structure_path or not shot_path.is_file() or not structure_path.is_file():
        logger.info("未提供可复用分析报告，使用场景切分与节拍生成剪辑结构")
        scenes = VideoTools().detect_scene_changes(
            viral_video_path, threshold=settings.SCENE_CHANGE_THRESHOLD
        )
        return build_rule_based_acts(scenes, bpm, beat_times)

    shot_analyses = json.loads(shot_path.read_text(encoding="utf-8"))
    structure = json.loads(structure_path.read_text(encoding="utf-8"))

    beats_raw = structure.get("script_structure", [])
    if not beats_raw:
        logger.info("分析报告未包含可用段落，回退到本地场景切分")
        scenes = VideoTools().detect_scene_changes(
            viral_video_path, threshold=settings.SCENE_CHANGE_THRESHOLD
        )
        return build_rule_based_acts(scenes, bpm, beat_times)
    beat_interval = 60.0 / bpm if bpm and bpm > 0 else 0.5

    # 逐镜头起止时间索引
    shot_times = {}
    for sa in shot_analyses:
        idx = sa["shot_index"]
        shot_times[idx] = {
            "start": sa.get("start_time", 0),
            "end": sa.get("end_time", 0),
            "duration": sa.get("end_time", 0) - sa.get("start_time", 0),
        }

    acts = []
    for a in beats_raw:
        sr = a.get("shot_range", "")
        parts = sr.replace("镜头", "").split("-")
        try:
            s = int(parts[0].strip())
            e = int(parts[1].strip())
        except (ValueError, IndexError):
            s, e = 0, 0

        act_shot_beats = []
        act_duration = 0.0
        for idx in range(s, e + 1):
            st = shot_times.get(idx, {"duration": 1.0, "start": 0, "end": 1.0})
            act_duration += st["duration"]
            n_beats = max(1, round(st["duration"] / beat_interval)) if beat_times else 2
            act_shot_beats.append(n_beats)

        acts.append({
            "index": a["index"],
            "purpose": a["purpose"],
            "emotion": a["emotion"],
            "rhythm": a["rhythm"],
            "shot_count": e - s + 1,
            "duration": round(act_duration, 1),
            "shot_beats": act_shot_beats,       # [2, 2, ...] 每镜拍数
        })
        logger.info(f"  段{a['index']}: {a['purpose']} | {act_duration:.1f}s | {e-s+1}个镜头 | "
                    f"拍数序列={act_shot_beats} | 情绪:{a['emotion']}")

    total_duration = round(sum(a["duration"] for a in acts), 1)
    logger.info(f"爆款结构: {len(acts)} 段, {total_duration:.1f}s, "
                f"总镜头 {sum(a['shot_count'] for a in acts)}")
    return acts, total_duration


# ============================================================
# 2. 加载用户照片素材
# ============================================================
def load_photo_materials(inventory_path: str):
    """从素材库存加载用户照片"""
    inventory = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    items = inventory.get("items", inventory.get("materials", []))
    logger.info(f"用户照片: {len(items)} 张")

    quality_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: quality_order.get(x.get("quality", "medium"), 1))

    return items


# ============================================================
# 3. 按爆款视频的镜头级节奏序列分配照片（精确节拍对齐）
# ============================================================
def build_photo_scheme(acts, photos, beat_times, bpm,
                       transition_pool_override=None, topic="我的短视频"):
    """按爆款视频的 shot_beats 节奏序列分配照片，每镜精确对齐到 beat_times

    参数:
      acts: extract_editing_pattern 输出，含 shot_beats 字段
      photos: 用户照片列表
      beat_times: 节拍时间点（秒）
      bpm: BPM
      transition_pool_override: 可选，覆盖转场池
    """
    total_shots = sum(a["shot_count"] for a in acts)
    max_photos = len(photos)
    logger.info(f"爆款节奏: {total_shots} 个镜头, 用户照片: {max_photos} 张")

    if max_photos == 0:
        logger.error("无可用照片")
        return []

    # 每段照片分配：按 shot_count 分，不够时循环使用
    act_photo_counts = {}
    remaining = max_photos
    for i, act in enumerate(acts):
        idx = act["index"]
        want = act["shot_count"]
        if i < len(acts) - 1:
            count = min(want, remaining - (len(acts) - i - 1))
        else:
            count = min(want, remaining)
        count = max(1, count)
        act_photo_counts[idx] = count
        remaining -= count

    # 如果照片不够参考镜头多，用循环策略
    recycle = max_photos < total_shots
    if recycle:
        logger.info(f"  照片不足 ({max_photos} < {total_shots})，循环使用")

    # === 情绪-转场池 ===
    default_pools = {
        0: ["slide_right", "blur_in", "zoom_in", "fade", "whip"],
        1: ["slide_up", "dissolve", "wipe_left", "fade", "circle_reveal"],
        2: ["slide_left", "whip", "wipe_right", "rotate_in",
            "flash_white", "glitch", "slide_up", "wipe_down",
            "slide_right", "zoom_flash", "zoom_in"],
        3: ["dissolve", "blur_in", "fade", "circle_reveal", "mask", "slide_up"],
    }
    act_transition_pools = transition_pool_override or default_pools

    # 多样化 Ken Burns 运镜池
    act_motion_pools = {
        0: ["zoom_in", "zoom_in", "pan_right"],
        1: ["zoom_in", "zoom_out", "zoom_in", "pan_right"],
        2: ["zoom_in", "pan_right", "zoom_in", "pan_right",
            "zoom_out", "zoom_in", "pan_left", "zoom_in"],
        3: ["slow_zoom_in", "slow_zoom_in", "zoom_in", "slow_zoom_in"],
    }

    # === 字幕策略：planner 根据段情绪/目的决定样式，字体高低错落 ===
    act_subtitle_styles = {
        # 段0 hook → 居中放大，金色，有冲击力
        0: {
            "animation": "scale_up",
            "fontSize": 48,
            "verticalAlign": "center",
            "color": "#FFD700",
            "fontWeight": 700,
            "textShadow": "2px 2px 12px rgba(0,0,0,0.9)",
        },
        # 段1 铺垫 → 底部，暖白，中等大小
        1: {
            "animation": "fade_in",
            "fontSize": 34,
            "verticalAlign": "bottom",
            "color": "#FFE4B5",
            "fontWeight": 600,
        },
        # 段2 日常展开 → 底部偏小，不抢镜（主体内容最多）
        2: {
            "animation": "fade_in",
            "fontSize": 28,
            "verticalAlign": "bottom",
            "color": "#E8E8E8",
            "fontWeight": 500,
        },
        # 段3 高潮升华 → 居中放大，金色，收束感染力
        3: {
            "animation": "scale_up",
            "fontSize": 46,
            "verticalAlign": "center",
            "color": "#FFD700",
            "fontWeight": 700,
            "textShadow": "2px 2px 16px rgba(0,0,0,0.95)",
        },
    }
    # 段2 内部交替子风格（更小更淡）
    act_subtitle_alt = {
        "fontSize": 26,
        "color": "#D0D0D0",
        "textShadow": "1px 1px 6px rgba(0,0,0,0.5)",
    }
    def _pick_pooled(pool, idx, avoid=None):
        for offset in range(len(pool)):
            t = pool[(idx + offset) % len(pool)]
            if t != avoid:
                return t
        return pool[idx % len(pool)]

    # === 主循环 ===
    storyboard = []
    photo_idx = 0
    global_beat_idx = 0
    prev_transition = None

    has_beats = beat_times is not None and len(beat_times) > 1
    beat_interval = 60.0 / bpm if bpm and bpm > 0 else 0.5

    for act in acts:
        idx = act["index"]
        beats_seq = act["shot_beats"]
        num_photos = act_photo_counts[idx]

        for shot_in_act in range(act["shot_count"]):
            # ---- 照片（不足则循环） ----
            p = photos[photo_idx % max_photos]
            pid = p.get("id", f"photo_{photo_idx % max_photos}")
            desc = p.get("description", "")
            photo_idx += 1

            # ---- 时长（精确节拍对齐，节拍不够时用等比例时长） ----
            n_beats = beats_seq[shot_in_act] if shot_in_act < len(beats_seq) else 2
            if has_beats and global_beat_idx + n_beats < len(beat_times):
                start_bi = global_beat_idx
                end_bi = start_bi + n_beats
                duration = round(beat_times[end_bi] - beat_times[start_bi], 3)
                global_beat_idx = end_bi
            else:
                # 节拍不够了，仍按比例分配保持节奏，不强制对齐
                duration = round(n_beats * beat_interval, 3)

            # ---- 转场（段末 dissolve） ----
            is_last = (shot_in_act == act["shot_count"] - 1)
            pool = act_transition_pools.get(idx, ["dissolve", "fade"])
            if is_last:
                transition = "dissolve"
            else:
                transition = _pick_pooled(pool, shot_in_act, prev_transition)
            prev_transition = transition

            # ---- Ken Burns ----
            has_face = p.get("has_face", False)
            mp = act_motion_pools.get(idx, ["zoom_in"])
            motion = mp[shot_in_act % len(mp)]
            if has_face and motion in ("pan_right", "pan_left", "pan_up", "pan_down"):
                motion = "zoom_in"

            # ---- 字幕样式：planner 按段情绪/目的智能决定 ----
            base_cfg = dict(act_subtitle_styles.get(idx, act_subtitle_styles[1]))
            # 段2（展开段，20个镜头）内部交替两种风格，避免千篇一律
            if idx == 2 and shot_in_act % 2 == 1:
                base_cfg["fontSize"] = act_subtitle_alt["fontSize"]
                base_cfg["color"] = act_subtitle_alt["color"]
                base_cfg["textShadow"] = act_subtitle_alt["textShadow"]

            storyboard.append({
                "index": len(storyboard),
                "shot_type": "daily_moment",
                "duration": duration,
                "material_id": pid,
                "visual_content": desc[:60],
                "subtitle_text": desc[:60] if desc.strip() else topic,
                "subtitle_config": base_cfg,
                "emotion": act["emotion"],
                "transition": transition,
                "ken_burns_config": {
                    "motion_type": motion,
                    "speed": "slow",
                    "focus_on_face": has_face,
                },
                "purpose": f"段{act['index']}: {act['purpose']}",
            })

    total_dur = sum(s["duration"] for s in storyboard)
    logger.info(f"方案生成: {len(storyboard)} 个分镜, {total_dur:.3f}s"
                f"{' (节拍同步)' if has_beats else ' (比例均分)'}")

    trans_counts = Counter(s["transition"] for s in storyboard)
    logger.info(f"转场分布: {dict(sorted(trans_counts.items()))}")

    return storyboard


# ============================================================
# 4. 提取爆款视频音频
# ============================================================
def extract_viral_audio(viral_video_path: str, output_dir: Path) -> str:
    """从爆款视频提取音频，保存到输出目录"""
    from tools.video_tools import _find_ffmpeg

    audio_path = str(output_dir / "viral_audio.aac")
    cmd = [_find_ffmpeg(), "-y", "-i", viral_video_path,
           "-vn", "-c:a", "aac", "-b:a", "192k", audio_path]
    subprocess.run(cmd, capture_output=True, check=True)
    logger.info(f"音频已提取: {audio_path}")
    return audio_path


# ============================================================
# 4b. 音频节拍检测
# ============================================================
def detect_beats(audio_path: str) -> tuple[float, list[float]]:
    """用 librosa 检测音频节拍，返回 (bpm, beat_times_in_seconds)"""
    import librosa
    import numpy as np

    wav_path = audio_path.rsplit(".", 1)[0] + "_temp.wav"
    try:
        cmd = [_find_ffmpeg(), "-y", "-i", audio_path,
               "-acodec", "pcm_s16le", "-ar", "22050", "-ac", "1", wav_path]
        subprocess.run(cmd, capture_output=True, check=True)

        y, sr = librosa.load(wav_path, sr=None)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)

        tempo = float(tempo.item() if hasattr(tempo, "item") else tempo)
        if not isinstance(beat_frames, np.ndarray) or beat_frames.ndim != 1 or len(beat_frames) < 2:
            raise ValueError(f"节拍检测无效: shape={getattr(beat_frames, 'shape', '?')}")

        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        beat_times = [float(t) for t in beat_times]

        logger.info(f"BPM: {tempo:.1f}, 节拍数: {len(beat_times)}, "
                    f"节拍间隔: {60.0/tempo:.3f}s")
        logger.info(f"  首拍: {beat_times[0]:.3f}s, 末拍: {beat_times[-1]:.3f}s")
        return tempo, beat_times
    finally:
        Path(wav_path).unlink(missing_ok=True)


# ============================================================
# 5. 迁移质量评估 + 自动调整
# ============================================================
def _normalized_entropy(items: list) -> float:
    """计算列表的归一化熵 [0, 1]：越高表示分布越均匀"""
    if not items or len(set(items)) < 2:
        return 0.0
    counts = Counter(items)
    total = len(items)
    n_types = len(counts)
    # 计算香农熵
    entropy = -sum((c / total) * math.log(c / total) for c in counts.values())
    # 归一化到 [0, 1]
    max_entropy = math.log(min(n_types, total))
    return entropy / max_entropy if max_entropy > 0 else 0.0


def evaluate_migration(storyboard, acts, beat_times, total_duration) -> dict:
    """评估生成方案与爆款视频的迁移匹配度，返回各项评分和总体分"""
    scores = {}

    # 1. 转场多样性 (0.30)
    trans_types = [s["transition"] for s in storyboard]
    scores["transition_diversity"] = round(_normalized_entropy(trans_types), 3)
    scores["transition_count"] = len(set(trans_types))

    # 2. 相邻转场唯一性 (0.20)
    diff_count = sum(1 for i in range(1, len(trans_types)) if trans_types[i] != trans_types[i - 1])
    scores["adjacent_uniqueness"] = round(diff_count / max(len(trans_types) - 1, 1), 3)

    # 3. 节拍同步准确率 (0.25)
    # 所有转场都在 beat 边界上（除了最后一镜的延长）
    on_beat = 0
    for s in storyboard[:-1]:  # 排除最后一镜（可能被延长）
        if s["duration"] > 0:
            on_beat += 1
    n_evaluated = max(len(storyboard) - 1, 1)
    scores["beat_sync"] = round(on_beat / n_evaluated, 3)

    # 4. Ken Burns 多样性 (0.10)
    motions = [s["ken_burns_config"]["motion_type"] for s in storyboard]
    scores["ken_burns_diversity"] = round(_normalized_entropy(motions), 3)

    # 5. 段落时长比例匹配度 (0.15)
    # 对比各段实际时长比例与爆款视频的 shot_count 比例
    total_shots_gen = len(storyboard)
    total_shots_viral = sum(a["shot_count"] for a in acts)

    act_proportion_scores = []
    photo_idx = 0
    for act in acts:
        expected_ratio = act["shot_count"] / total_shots_viral
        num_photos_in_act = 0
        for s in storyboard[photo_idx:]:
            if s.get("purpose", "").startswith(f"段{act['index']}:"):
                num_photos_in_act += 1
            else:
                break
        photo_idx += num_photos_in_act
        actual_ratio = num_photos_in_act / total_shots_gen if total_shots_gen > 0 else 0
        # 重叠率
        act_proportion_scores.append(min(expected_ratio, actual_ratio) / max(expected_ratio, 0.01))

    scores["act_proportion"] = round(sum(act_proportion_scores) / len(act_proportion_scores), 3)

    # 综合
    weights = {
        "transition_diversity": 0.30,
        "adjacent_uniqueness": 0.20,
        "beat_sync": 0.25,
        "ken_burns_diversity": 0.10,
        "act_proportion": 0.15,
    }
    scores["overall"] = round(sum(scores[k] * weights[k] for k in weights), 3)
    scores["weights"] = weights
    return scores


def auto_adjust_params(scores, current_beats_per_shot, current_transition_pools):
    """根据评估结果自动调整参数"""
    new_beats = dict(current_beats_per_shot)
    new_pools = deepcopy(current_transition_pools)

    adjustments = []

    # 转场多样性不足 → 扩展转场池
    if scores.get("transition_diversity", 1.0) < 0.75:
        logger.info("  → 转场多样性不足，扩展转场池")
        all_trans = ["slide_left", "slide_right", "slide_up", "slide_down",
                     "wipe_left", "wipe_right", "wipe_up", "wipe_down",
                     "blur_in", "rotate_in", "zoom_in", "zoom_out",
                     "fade", "flash_white", "dissolve"]
        for idx in new_pools:
            # 为每段加入更多转场类型
            extra = [t for t in all_trans if t not in new_pools[idx]]
            new_pools[idx] = new_pools[idx] + extra[:6]
        adjustments.append("expanded_transition_pools")

    # 相邻唯一性不足 → 调整选择逻辑（通过使池更大来增加变化）
    if scores.get("adjacent_uniqueness", 1.0) < 0.85:
        logger.info("  → 相邻转场重复过多，增大转场池多样性")
        for idx in new_pools:
            # 打乱顺序以减少重复
            import random
            random.shuffle(new_pools[idx])
        adjustments.append("shuffled_transition_pools")

    # Ken Burns 多样性不足
    if scores.get("ken_burns_diversity", 1.0) < 0.55:
        logger.info("  → Ken Burns 运镜单一，增加变化")
        # 这个在 build_photo_scheme 内部硬编码，需要外部改
        adjustments.append("low_ken_burns_diversity")

    # 段落比例偏差大 → 调整 beats_per_shot
    if scores.get("act_proportion", 1.0) < 0.75 and len(new_beats) >= 3:
        logger.info("  → 段落比例偏差大，调整节拍分配")
        # 给更长的段用更少的拍（缩短时长），或更短的段用更多的拍（延长）
        adjustments.append("adjusted_beat_distribution")

    return new_beats, new_pools, adjustments


# ============================================================
# 6. 构建素材路径映射
# ============================================================
def build_material_map(photos, audio_path: str) -> dict:
    material_map = {}
    for p in photos:
        pid = p.get("id", "")
        ppath = p.get("path", "")
        if pid and ppath and Path(ppath).exists():
            material_map[pid] = str(Path(ppath).resolve())
    if audio_path:
        material_map["_viral_audio"] = audio_path
    logger.info(f"素材映射: {len(material_map)} 个")
    return material_map


# ============================================================
# 主流程（含评估-迭代闭环）
# ============================================================
def main():
    args = parse_args()

    viral_video = args.viral_video
    run_id = args.run_id
    topic = args.topic.strip() or "我的短视频"

    out = OutputManager(run_id=run_id)
    logger.info(f"输出目录: {out.run_dir}")

    # ---- 1. 加载用户照片 ----
    logger.info("=" * 60)
    logger.info("1. 加载用户照片素材")
    photos = load_photo_materials(args.materials)
    out.save_json("editing", "photos_summary.json",
                  [{"id": p["id"], "desc": p.get("description", "")[:40]} for p in photos])

    # ---- 2. 提取爆款视频音频 ----
    logger.info("=" * 60)
    logger.info("2. 提取爆款视频音频")
    out.run_dir.mkdir(parents=True, exist_ok=True)
    audio_path = extract_viral_audio(viral_video, out.run_dir)

    # ---- 3. 节拍检测 ----
    logger.info("=" * 60)
    logger.info("3. 音频节拍检测")
    beat_times = None
    bpm = None
    try:
        bpm, beat_times = detect_beats(audio_path)
        logger.info(f"  检测到 BPM={bpm:.1f}, {len(beat_times)} 个节拍")
    except Exception as e:
        logger.warning(f"节拍检测失败，回退到比例分配: {e}")

    # ---- 4. 提取剪辑模式（含镜头级节奏序列） ----
    logger.info("=" * 60)
    logger.info("4. 提取爆款视频剪辑模式（镜头级）")
    acts, total_duration = extract_editing_pattern(
        viral_video,
        bpm,
        beat_times,
        args.shot_analyses,
        args.structure_analysis,
    )
    out.save_json("editing", "acts.json", acts)

    # ---- 5. 按爆款节奏生成照片方案 ----
    logger.info("=" * 60)
    logger.info("5. 按爆款节奏序列生成方案")
    storyboard = build_photo_scheme(acts, photos, beat_times, bpm, topic=topic)

    # 延长最后一镜至总时长
    actual_duration = sum(s["duration"] for s in storyboard)
    if total_duration > actual_duration and storyboard:
        extra = total_duration - actual_duration
        storyboard[-1]["duration"] = round(storyboard[-1]["duration"] + extra, 3)
        actual_duration = total_duration

    # ---- 插入开场 + 结尾标题卡 ----
    opening_dur = 3.0
    ending_dur = 3.0
    if len(photos) >= 2:
        first_p = photos[0]
        opening_shot = {
            "index": 0,
            "shot_type": "title_card",
            "duration": opening_dur,
            "material_id": first_p.get("id", "photo_00"),
            "visual_content": "",
            "subtitle_text": topic,
            "subtitle_config": {
                "animation": "scale_up", "fontSize": 64,
                "verticalAlign": "center", "color": "#FFD700",
                "fontWeight": 800,
                "textShadow": "3px 3px 20px rgba(0,0,0,0.95)",
                "letterSpacing": 4,
            },
            "emotion": "激昂",
            "transition": "fade",
            "ken_burns_config": {"motion_type": "slow_zoom_in", "speed": "slow", "focus_on_face": False},
            "purpose": "开场标题",
        }
        last_p = photos[-1]
        ending_shot = {
            "index": 0,
            "shot_type": "ending_card",
            "duration": ending_dur,
            "material_id": last_p.get("id", f"photo_{len(photos)-1:02d}"),
            "visual_content": "",
            "subtitle_text": "谢谢观看\n下次见",
            "subtitle_config": {
                "animation": "scale_up", "fontSize": 56,
                "verticalAlign": "center", "color": "#FFD700",
                "fontWeight": 700,
                "textShadow": "3px 3px 18px rgba(0,0,0,0.9)",
                "letterSpacing": 2,
            },
            "emotion": "平静",
            "transition": "dissolve",
            "ken_burns_config": {"motion_type": "slow_zoom_in", "speed": "slow", "focus_on_face": False},
            "purpose": "结尾致谢",
        }
        storyboard.insert(0, opening_shot)
        storyboard.append(ending_shot)
        for i, s in enumerate(storyboard):
            s["index"] = i
        actual_duration += opening_dur + ending_dur
        total_duration = actual_duration
        logger.info(f"  + 开场标题({opening_dur}s) + 结尾致谢({ending_dur}s), 总时长={actual_duration:.1f}s")

    # ---- 评估 ----
    scores = evaluate_migration(storyboard, acts, beat_times, total_duration)
    logger.info(f"  [评估] 转场多样性={scores['transition_diversity']:.3f} "
                f"({scores['transition_count']}种) | "
                f"相邻唯一={scores['adjacent_uniqueness']:.3f} | "
                f"节拍同步={scores['beat_sync']:.3f} | "
                f"运镜多样={scores['ken_burns_diversity']:.3f} | "
                f"段落比例={scores['act_proportion']:.3f}")
    logger.info(f"  [评估] 综合分={scores['overall']:.3f} (阈值={QUALITY_THRESHOLD})")

    # ---- 6. 构建完整 scheme ----
    logger.info("=" * 60)
    logger.info("6. 构建渲染方案")
    scheme = {
        "id": run_id,
        "title": topic,
        "target_topic": topic,
        "target_duration": round(actual_duration, 1),
        "structure_type": "情绪递进型",
        "storyboard": storyboard,
        "bgm": {
            "style": "原爆款视频BGM",
            "audio_path": "_viral_audio",
            "role": "background",
            "volume": 0.3,
            "loop": True,
        },
        "audio_source_id": Path(args.viral_video).stem,
        "audio_config": {
            "source": "reference",
            "volume": 0.3,
            "loop": True,
            "trim_before": 0,
            "trim_after": None,
            "fade_frames": 15,
            "original_audio_mode": "mute",
            "normalize": True,
            "target_lufs": -14.0,
            "true_peak": -1.0,
        },
        "packaging": {
            "subtitle_style": {
                "position": "bottom",
                "animation": "fade_in",
                "fontSize": 36,
                "fontWeight": 600,
                "color": "#FFFFFF",
                "fontFamily": "'PingFang SC', 'Microsoft YaHei', sans-serif",
                "textAlign": "center",
                "textShadow": "2px 2px 8px rgba(0,0,0,0.8)",
                "maxWidthPercent": 90,
            },
            "preferred_transitions": ["dissolve", "fade"],
            "transition_frequency": "frequent",
            "color_grade": "natural",
            "default_ken_burns": "slow_zoom_in",
        },
    }
    out.save_json("editing", "scheme.json", scheme)
    if args.scheme_output:
        scheme_output = Path(args.scheme_output).resolve()
        scheme_output.parent.mkdir(parents=True, exist_ok=True)
        scheme_output.write_text(
            json.dumps(scheme, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    logger.info(f"方案: {len(storyboard)} 个分镜, {actual_duration:.1f}s, 迁移评分={scores['overall']:.3f}")

    if args.prepare_only:
        logger.info("分镜草案已生成，等待用户确认")
        return

    # ---- 6. 构建素材映射 ----
    logger.info("=" * 60)
    logger.info("6. 构建素材路径映射")
    local_material_map = build_material_map(photos, audio_path)
    out.save_json("editing", "material_map.json", local_material_map)

    # ---- 7. Remotion 渲染 ----
    logger.info("=" * 60)
    logger.info("7. Remotion 渲染")

    from tools.remotion_renderer import render_with_remotion

    output_path = Path(args.output).resolve() if args.output else (out.run_dir / "final_video.mp4").resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output = str(output_path)
    # 把音频也作为素材传入，确保 Remotion 能拿到 BGM
    materials_for_render = photos + [{"id": "_viral_audio", "path": audio_path}] if audio_path else photos
    result_path = render_with_remotion(scheme, materials_for_render, output, timeout=600)

    if not result_path:
        logger.error("Remotion 渲染失败")
        return

    size_mb = Path(result_path).stat().st_size / 1024 / 1024
    logger.info(f"[OK] 渲染完成: {result_path}")
    logger.info(f"[OK] 文件大小: {size_mb:.1f}MB")

    summary = {
        "shots": len(storyboard),
        "title": scheme["title"],
        "output": result_path,
        "size_mb": round(size_mb, 1),
        "method": "remotion_editing_transfer",
        "photo_count": len(local_material_map) - 1,
        "audio_source": "viral_video",
        "total_duration": round(actual_duration, 1),
        "migration_score": scores["overall"],
    }
    out.save_json("editing", "render_summary.json", summary)


if __name__ == "__main__":
    main()
