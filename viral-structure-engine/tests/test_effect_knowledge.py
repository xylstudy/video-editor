from pathlib import Path

import pytest
import cv2
import numpy as np

from knowledge.effects import extract_effect_entries, effect_example_windows
from personal_knowledge_demos import _asset_name, personal_demo_props
from render_knowledge_demos import source_demo_window
from effect_reconstruction import DemoUnavailable


def test_stickers_are_individual_effects_and_keep_rich_observations():
    events = [
        {"id": "eyes", "type": "tracked_doodle", "subject": "樱桃", "parameters": {"style": "眼睛和嘴巴"}},
        {"id": "stars", "type": "tracked_doodle", "subject": "狗头", "parameters": {"style": "晕眩星形", "count": 3}},
        {"id": "arrow", "type": "tracked_doodle", "parameters": {"shape": "cursor_arrow"}},
        {"id": "stop", "type": "tracked_doodle", "parameters": {"appear": "pop_in"}},
        {"id": "paper", "type": "cutout_outline", "parameters": {"border_style": "torn_paper_white"}},
    ]
    for index, event in enumerate(events):
        event.update(start_offset=index * .5, end_offset=index * .5 + .4, position={"x": .47, "y": .32},
                     motion_path=[{"progress": 0, "x": .5}, {"progress": 1, "x": .4}], confidence=.9)
    report = {"duration": 8, "effect_tracks": [{"id": "stars", "type": "tracked_doodle", "start": 2.5, "end": 2.9, "subject": "狗头"}],
              "raw_shot_analyses": [{"shot_index": 3, "start_time": 2, "end_time": 5, "effect_events": events}]}
    entries = extract_effect_entries(report, "actual-reference.mp4")
    by_key = {entry.structured_data['effect_key']: entry for entry in entries}
    assert set(by_key) == {'sticker_face', 'sticker_stars', 'sticker_arrow', 'sticker_pop', 'torn_paper_outline'}
    assert all(entry.type.value == 'effect_type' and '贴纸' in entry.tags for entry in entries)
    stars = by_key['sticker_stars'].structured_data
    assert len(stars['evidence']) == 1  # global track and raw shot describe one event
    assert stars['evidence'][0]['start_time'] == 2.5
    assert stars['parameters']['count'] == 3
    assert stars['position'] == {'x': .47, 'y': .32}
    assert len(stars['motion_path']) == 2


def test_compositing_requirements_are_preserved_and_camera_motion_is_not_a_sticker():
    report = {'duration': 5, 'shots': [{'index': 1, 'start_time': 1, 'end_time': 3, 'effect_events': [
        {'type': 'subject_echo', 'id': 'clone', 'start_offset': 0, 'end_offset': .9, 'mask_mode': 'subject_cutout', 'parameters': {'spawn_origin': 'hole', 'echo_count': 6}},
        {'type': 'subject_echo', 'id': 'trail', 'start_offset': 1, 'end_offset': 2, 'parameters': {'opacity_decay': .85}},
        {'type': 'other', 'id': 'grid', 'start_offset': 0, 'end_offset': 1, 'parameters': {'grid': '3x3'}},
        {'type': 'whip', 'start_offset': 0, 'end_offset': 1},
        {'type': 'occlusion_wipe', 'anchor': 'transition', 'start_offset': 0, 'end_offset': 1},
        {'type': 'custom_hologram', 'start_offset': 0, 'end_offset': 1},
    ]}]}
    entries = {entry.structured_data['effect_key']: entry for entry in extract_effect_entries(report, 'source.mp4')}
    assert set(entries) == {'subject_clone', 'subject_echo', 'grid_overlay', 'observed_custom_hologram'}
    assert entries['subject_clone'].structured_data['requires_subject_mask']
    assert entries['subject_clone'].structured_data['parameters']['echo_count'] == 6
    assert not any('贴纸' in entry.tags for entry in entries.values())
    assert entries['observed_custom_hologram'].structured_data['demo_mode'] == 'reconstruction'
    assert extract_effect_entries({'raw_structure_analysis': {'packaging_analysis': {'stickers_effects': '无贴纸'}}}, 'no-effects.mp4') == []


def test_source_windows_remain_reference_only_and_cannot_become_effect_examples(tmp_path):
    data = {'effect_key': 'sticker_stars', 'category': '贴纸', 'source_duration': 12,
            'evidence': [{'start_time': 9.4, 'end_time': 10.3}, {'start_time': 10.5, 'end_time': 11.1}]}
    entry = {'type': 'effect_type', 'title': '晕眩星星贴纸', 'structured_data': data}
    windows = effect_example_windows(entry)
    assert len(windows) == 1 and windows[0]['start'] == pytest.approx(9.05)
    assert windows[0]['start'] + windows[0]['duration'] <= 12
    assert source_demo_window(entry) == windows[0]
    source = tmp_path / 'reference.mp4'
    source.write_bytes(b'video')
    material = {'path': str(source), **windows[0], 'origin': 'reference_shots', 'role': entry['title'], 'fit': 'contain'}
    with pytest.raises(DemoUnavailable, match='独立'):
        personal_demo_props(entry, [material])
    assert _asset_name(material) != _asset_name({**material, 'fit': 'cover'})
    with pytest.raises(ValueError):
        personal_demo_props({'type': 'effect_type', 'structured_data': {}}, [])


def _clean_video(tmp_path):
    path = tmp_path / 'cherries.mp4'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 30, (270, 480))
    for index in range(180):
        frame = np.full((480, 270, 3), (180, 100, 40), np.uint8)
        cv2.circle(frame, (110 + index // 8, 235), 32, (15, 20, 230), -1)
        cv2.circle(frame, (103 + index // 8, 225), 5, (80, 80, 255), -1)
        writer.write(frame)
    writer.release()
    return {'path': str(path), 'origin': 'task_materials', 'role': 'cherries.mp4'}


def test_reconstruction_has_a_real_operation_on_clean_footage_and_subject_alpha(tmp_path, monkeypatch):
    import personal_knowledge_demos
    monkeypatch.setattr(personal_knowledge_demos, 'DEMO_OUT_DIR', tmp_path / 'demos')
    material = _clean_video(tmp_path)
    keys = ['sticker_face', 'sticker_stars', 'sticker_arrow', 'sticker_pop', 'torn_paper_outline', 'subject_echo', 'subject_clone']
    for key in keys:
        props = personal_demo_props({'type': 'effect_type', 'structured_data': {'effect_key': key}}, [material])
        assert props['reconstructed'] and not props['reference_recut']
        clip = props['edited'][0]
        assert clip['effect'] == 'atomic' and clip['atomic']['key'] == key
        assert clip['duration'] == 120 and clip['playback_rate'] == 1
        assert clip['atomic']['tracking_valid_frames'] > 20
        if key in {'torn_paper_outline', 'subject_echo', 'subject_clone'}:
            cutout = clip['atomic']['cutout']
            image = cv2.imdecode(np.fromfile(tmp_path / 'demos/footage_assets' / cutout['src'], dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            assert image.shape[2] == 4 and np.any(image[:, :, 3] == 0) and np.any(image[:, :, 3] > 0)
            assert cutout['alpha_coverage'] < .2  # a foreground subject, never the whole frame
    with pytest.raises(DemoUnavailable, match='尚无重建'):
        personal_demo_props({'type': 'effect_type', 'structured_data': {'effect_key': 'unknown_hologram'}}, [material])
