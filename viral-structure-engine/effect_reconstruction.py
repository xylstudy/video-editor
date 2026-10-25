"""Build focused effect demonstrations on independent, clean task footage."""
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


class DemoUnavailable(ValueError):
    """An honest pending state, rather than a substitute reference excerpt."""


SUPPORTED_EFFECTS = {
    'sticker_face', 'sticker_stars', 'sticker_anger', 'sticker_arrow',
    'sticker_pop', 'sticker_doodle', 'torn_paper_outline', 'subject_outline',
    'subject_clone', 'subject_echo', 'grid_overlay', 'floating_music_ui',
    'foreground_silhouette', 'glitch_reveal', 'film_grain', 'search_cta_card',
}
MASK_EFFECTS = {'torn_paper_outline', 'subject_outline', 'subject_clone', 'subject_echo'}


def _frame(cap):
    ok, frame = cap.read()
    if not ok:
        raise DemoUnavailable('独立素材无法解码，等待有效视频素材')
    height, width = frame.shape[:2]
    scale = max(540 / width, 960 / height)
    frame = cv2.resize(frame, (round(width * scale), round(height * scale)))
    y, x = (frame.shape[0] - 960) // 2, (frame.shape[1] - 540) // 2
    return frame[y:y + 960, x:x + 540]


def _object_region(frame, mode):
    if mode == 'head':
        return (108, 144, 324, 576), None
    if mode == 'face':
        return (54, 190, 380, 500), None
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    red = (((hsv[:, :, 0] < 13) | (hsv[:, :, 0] > 155)) & (hsv[:, :, 1] > 185) & (hsv[:, :, 2] > 35)).astype('uint8') * 255
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    count, labels, stats, centers = cv2.connectedComponentsWithStats(red)
    candidates = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if 1200 < area < 540 * 960 * .4 and min(w, h) > 25 and x > 3 and y > 3 and x + w < 537 and y + h < 957:
            distance = ((centers[index][0] / 540 - .5) ** 2 + (centers[index][1] / 960 - .5) ** 2)
            candidates.append((area / (1 + distance * 10), index))
    if not candidates:
        return (108, 192, 324, 576), None
    index = max(candidates)[1]
    x, y, w, h, _ = stats[index]
    return (int(x), int(y), int(w), int(h)), (labels == index).astype('uint8') * 255


@lru_cache(maxsize=48)
def _analyze(path, size, mtime, mode):
    cap = cv2.VideoCapture(path)
    try:
        first = _frame(cap)
        box, red_mask = _object_region(first, mode)
        source_start = 0
        if mode == 'object':
            options = []
            if red_mask is not None:
                options.append((np.count_nonzero(red_mask), 0, first, box, red_mask))
            for seconds in [.5, 1., 1.5, 2.]:
                cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
                candidate = _frame(cap)
                candidate_box, candidate_mask = _object_region(candidate, mode)
                if candidate_mask is not None:
                    options.append((np.count_nonzero(candidate_mask), round(seconds * cap.get(cv2.CAP_PROP_FPS)), candidate, candidate_box, candidate_mask))
            if options:
                _, source_start, first, box, red_mask = max(options, key=lambda option: option[0])
                cap.set(cv2.CAP_PROP_POS_FRAMES, source_start + 1)
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 1)
        x, y, w, h = box
        roi = np.zeros((960, 540), np.uint8)
        roi[y:y + h, x:x + w] = 255
        gray = cv2.cvtColor(first, cv2.COLOR_BGR2GRAY)
        points = cv2.goodFeaturesToTrack(gray, maxCorners=100, qualityLevel=.015, minDistance=7, mask=roi)
        tracks, dx, dy, valid = [], 0., 0., 0
        fps = max(1, cap.get(cv2.CAP_PROP_FPS))
        for frame_index in range(120):
            if frame_index:
                current = _frame(cap)
                next_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
                if points is not None and len(points) >= 4:
                    next_points, status, _ = cv2.calcOpticalFlowPyrLK(gray, next_gray, points, None)
                    good = status.reshape(-1) == 1
                    if good.sum() >= 4:
                        delta = np.median((next_points - points).reshape(-1, 2)[good], axis=0)
                        dx = float(np.clip(dx + delta[0], -100, 100))
                        dy = float(np.clip(dy + delta[1], -120, 120))
                        points = next_points[good].reshape(-1, 1, 2)
                        valid += 1
                gray = next_gray
                if frame_index % 12 == 0:
                    shifted = np.zeros_like(roi)
                    bx, by = int(np.clip(x + dx, 0, 539)), int(np.clip(y + dy, 0, 959))
                    shifted[by:min(960, by + h), bx:min(540, bx + w)] = 255
                    points = cv2.goodFeaturesToTrack(gray, maxCorners=100, qualityLevel=.015, minDistance=7, mask=shifted)
            if frame_index % 3 == 0:
                tracks.append({'frame': round(frame_index / fps * 30), 'x': round((x + w / 2 + dx) / 540, 5),
                               'y': round((y + (h * .08 if mode == 'head' else h / 2) + dy) / 960, 5),
                               'width': round(w / 540, 5), 'height': round(h / 960, 5)})
        return {'tracks': tracks, 'source_start': source_start, 'tracking_method': 'sparse_optical_flow' if valid >= 20 else 'fixed_anchor',
                'tracking_valid_frames': valid, 'box': box, 'first': first, 'red_mask': red_mask}
    finally:
        cap.release()


def _cutout(analysis, material, asset_dir):
    frame, red_mask = analysis['first'], analysis['red_mask']
    if red_mask is None:
        raise DemoUnavailable('尚未得到可靠的主体抠像，不能用整幅画面替代主体描边或残影')
    x, y, w, h = analysis['box']
    pad = max(10, round(min(w, h) * .16))
    left, top = max(1, x - pad), max(1, y - pad)
    right, bottom = min(539, x + w + pad), min(959, y + h + pad)
    mask = np.zeros((960, 540), np.uint8)
    mask[top:bottom, left:right] = cv2.GC_PR_BGD
    mask[red_mask > 0] = cv2.GC_PR_FGD
    core = cv2.erode(red_mask, np.ones((7, 7), np.uint8))
    mask[core > 0] = cv2.GC_FGD
    cv2.setRNGSeed(731)
    cv2.grabCut(frame, mask, None, np.zeros((1, 65)), np.zeros((1, 65)), 2, cv2.GC_INIT_WITH_MASK)
    alpha = np.isin(mask, [cv2.GC_FGD, cv2.GC_PR_FGD]).astype('uint8') * 255
    ratio = np.count_nonzero(alpha) / alpha.size
    if not .005 < ratio < .4:
        raise DemoUnavailable('主体抠像质量不足，效果示例待补齐')
    contours, _ = cv2.findContours(alpha, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour = max(contours, key=cv2.contourArea)
    alpha[:] = 0
    cv2.drawContours(alpha, [contour], -1, 255, cv2.FILLED)
    bx, by, bw, bh = cv2.boundingRect(contour)
    # Keep a transparent margin for the paper edge and cutout compositing.
    bx, by = max(0, bx - 16), max(0, by - 16)
    bw, bh = min(540 - bx, bw + 32), min(960 - by, bh + 32)
    rgba = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = alpha
    rgba = rgba[by:by + bh, bx:bx + bw]
    stat = Path(material['path']).stat()
    name = hashlib.sha256(f"{material['path']}:{stat.st_size}:{stat.st_mtime_ns}:subject-v3".encode()).hexdigest()[:24] + '.subject.png'
    asset_dir.mkdir(parents=True, exist_ok=True)
    target = asset_dir / name
    if not target.is_file():
        cv2.imencode('.png', rgba)[1].tofile(str(target))
    return {'src': name, 'box': {'x': bx / 540, 'y': by / 960, 'width': bw / 540, 'height': bh / 960},
            'method': 'color_seeded_grabcut_freeze', 'alpha_coverage': round(ratio, 5)}


def focused_effect_props(entry, materials, asset_name, asset_dir):
    data = entry.get('structured_data') or {}
    key = data.get('effect_key') or data.get('id')
    if key not in SUPPORTED_EFFECTS:
        raise DemoUnavailable('该技法尚无重建实现，保留原片参考，效果示例待实现')
    clean = [item for item in materials if item.get('origin') == 'task_materials']
    if not clean:
        raise DemoUnavailable('缺少独立实拍素材，不能用参考原片充当效果示例')
    pattern = r'dog|cat|pet|狗|猫' if key in {'sticker_stars', 'sticker_anger', 'sticker_doodle'} else r'cherr|fruit|apple|樱桃|水果|苹果' if key in MASK_EFFECTS | {'sticker_face'} else r'drink|juice|pour|饮|果汁' if key == 'sticker_arrow' else r'city|street|cycl|bus|街|城市'
    # Prefer isolated fruit footage over hands slicing a fruit when both exist.
    preference = r'fresh.*apple|整.*苹果' if key == 'sticker_face' else r'cherr|樱桃'
    ranked = sorted(enumerate(clean), key=lambda pair: (not bool(re.search(pattern, pair[1].get('role', ''), re.I)),
                    not bool(re.search(preference, pair[1].get('role', ''), re.I)), pair[0]))
    material = ranked[0][1]
    stat = Path(material['path']).stat()
    mode = 'head' if key in {'sticker_stars', 'sticker_anger', 'sticker_doodle'} else 'face' if key == 'sticker_face' else 'object'
    analysis = _analyze(material['path'], stat.st_size, stat.st_mtime_ns, mode)
    atomic = {'key': key, 'parameters': data.get('parameters') or {}, 'tracks': analysis['tracks'], 'source_start': analysis['source_start'],
              'tracking_method': analysis['tracking_method'], 'tracking_valid_frames': analysis['tracking_valid_frames']}
    if key in MASK_EFFECTS:
        atomic['cutout'] = _cutout(analysis, material, asset_dir)
    subtitle = '定格主体抠像合成' if key in MASK_EFFECTS else '独立素材上的技法重建'
    clip = {'src': asset_name(material), 'duration': 120, 'role': material.get('role', ''), 'effect': 'atomic',
            'transition': 'cut', 'motion': 'none', 'playback_rate': 1, 'atomic': atomic}
    return {'title': entry.get('title', '特效重建示例'), 'knowledge_type': 'effect_type', 'duration_frames': 120,
            'reference_recut': False, 'reconstructed': True, 'edited': [clip], 'technique': subtitle,
            'grade': 'original', 'film': False, 'music_ui': False, 'subtitle': False, 'black_dip': False,
            'search_cta': False, 'audio': 'demo-beat-120bpm.wav',
            'source': '使用独立实拍素材重新制作，只演示当前技法；' + subtitle}
