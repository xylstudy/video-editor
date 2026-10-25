from render_knowledge_demos import demo_spec, select_demo_entries
from personal_knowledge_demos import personal_demo_props, render_personal_teaching_demos
import personal_knowledge_demos
import json
import pytest
from effect_reconstruction import DemoUnavailable
from pathlib import Path


def test_builtin_batch_does_not_replace_personal_source_clips():
    entries = [
        {"id": "k_0"},
        {"id": "k_51"},
        {"id": "k_u3_personal"},
        {"id": "k_u3_8f2d_effect_contract"},
    ]
    assert select_demo_entries(entries, built_in=True) == entries[:2]
    assert select_demo_entries(entries, only="k_51", built_in=True) == [entries[1]]
    assert select_demo_entries(entries, only="k_u3_personal") == [entries[2]]
    assert select_demo_entries(entries, only="k_u3_personal", built_in=True) == []


def test_personal_knowledge_types_use_matching_teaching_demos():
    assert demo_spec({"type": "structure_template", "structured_data": {}}) == (
        "emotion_arc",
        "structure_arc",
    )
    assert demo_spec({"type": "hook_technique", "structured_data": {}}) == (
        "montage",
        "hook",
    )
    assert demo_spec({"type": "rhythm_pattern", "structured_data": {}}) == (
        "beat",
        "beat",
    )
    assert demo_spec({"type": "emotion_design", "structured_data": {}}) == (
        "emotion_arc",
        "emotion_arc",
    )
    assert demo_spec({"type": "packaging_style", "structured_data": {}}) == (
        "packaging",
        "douyin_travel_fast",
    )


def _test_materials(tmp_path):
    materials = []
    for index in range(6):
        path = tmp_path / f"source-{index}.mp4"
        path.write_bytes(f"actual-video-placeholder-{index}".encode())
        materials.append({"path": str(path), "role": "视觉钩子" if index == 2 else f"场景{index}"})
    return materials


def test_single_frame_recipe_executes_rhythm_and_explicit_effects(tmp_path):
    materials = _test_materials(tmp_path)
    rhythm = personal_demo_props({"type": "rhythm_pattern"}, materials)
    assert sum(clip["duration"] for clip in rhythm["edited"]) == 360
    assert len({clip["duration"] for clip in rhythm["edited"]}) > 1
    assert "baseline" not in rhythm
    assert len({clip["src"] for clip in rhythm["edited"]}) == 6
    hook = personal_demo_props({"type": "hook_technique"}, materials)
    assert hook["edited"][0]["src"] == personal_knowledge_demos._asset_name(materials[2])
    assert hook["edited"][0]["motion"] == "punch"
    packaging = personal_demo_props({"type": "packaging_style", "structured_data": {"effect_tracks": [{"type": "floating_music_ui"}, {"type": "glitch_reveal"}, {"type": "slice_wipe"}]}}, materials)
    assert packaging["music_ui"]
    assert {clip["transition"] for clip in packaging["edited"]} >= {"glitch", "slice_wipe"}
    assert packaging["audio"].endswith(".wav")
    playful = personal_demo_props({"type": "packaging_style", "structured_data": {"stickers_effects": "小狗怒气涂鸦、撕纸画框、动态重影"}}, materials)
    assert {clip["effect"] for clip in playful["edited"]} >= {"doodle", "paper", "echo"}
    assert playful['edited'][0]['effect'] == 'doodle'
    music_hook = personal_demo_props({"type": "hook_technique", "structured_data": {"detail": "开场叠加音乐播放器UI与胶片颗粒"}}, materials)
    assert music_hook["music_ui"] and music_hook["film"]


def test_missing_real_materials_do_not_fall_back_to_card_animations(tmp_path, monkeypatch):
    monkeypatch.setattr(personal_knowledge_demos, "DEMO_OUT_DIR", tmp_path)
    monkeypatch.setattr(personal_knowledge_demos, "_material_candidates", lambda entry: [])
    result = render_personal_teaching_demos([{"id": "k_u3_missing", "type": "hook_technique"}])
    assert result["teaching_demo_failures"] == []
    assert result['teaching_demo_pending'][0]['id'] == 'k_u3_missing'
    assert list(tmp_path.glob("*.teaching.mp4")) == []


def test_arbitrary_source_counts_and_distinct_reference_ranges(tmp_path):
    from personal_knowledge_demos import reference_materials
    materials = _test_materials(tmp_path)
    for count in range(2, 7):
        for kind in ("structure_template", "hook_technique", "rhythm_pattern", "emotion_design", "packaging_style"):
            props = personal_demo_props({"type": kind}, materials[:count])
            assert len(props["edited"]) == count
            assert sum(clip["duration"] for clip in props["edited"]) == props["duration_frames"]
            assert all(0 < clip["duration"] <= 180 for clip in props["edited"])
    report = tmp_path / 'report.json'
    report.write_text(json.dumps({'shots': [{'start_time': i, 'end_time': i + 1} for i in range(6)]}))
    ranges = reference_materials(Path(materials[0]['path']), report)
    with pytest.raises(DemoUnavailable, match='参考原片'):
        personal_demo_props({'type': 'packaging_style', 'structured_data': {'effect_tracks': [{'type': 'floating_music_ui'}]}}, ranges)


def test_knowledge_details_control_timing_and_emotion_instead_of_fixed_template(tmp_path):
    materials = _test_materials(tmp_path)
    def rhythm(intensities):
        return personal_demo_props({'type': 'rhythm_pattern', 'structured_data': {'rhythm_analysis': {'curve_points': [{'intensity': value} for value in intensities]}}}, materials)
    assert [c['duration'] for c in rhythm([.1, .9])['edited']] != [c['duration'] for c in rhythm([.9, .1])['edited']]
    calm = personal_demo_props({'type': 'emotion_design', 'structured_data': {'overall_emotion': '治愈伤感'}}, materials)
    lively = personal_demo_props({'type': 'emotion_design', 'structured_data': {'overall_emotion': '轻快'}}, materials)
    assert calm['film'] and not lively['film']
    assert calm['edited'][1]['transition'] == 'dissolve'
    assert lively['edited'][1]['transition'] == 'cut'


def test_personal_teaching_renders_are_separate_and_refresh_when_content_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(personal_knowledge_demos, "DEMO_OUT_DIR", tmp_path)
    monkeypatch.setattr(personal_knowledge_demos, "REMOTION_DIR", tmp_path)
    materials = _test_materials(tmp_path)
    monkeypatch.setattr(personal_knowledge_demos, "_material_candidates", lambda entry: materials)
    monkeypatch.setattr(personal_knowledge_demos, "_prepare_assets", lambda *args: None)
    calls = []

    def render(command, **kwargs):
        plan = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        calls.append(plan)
        for item in plan["entries"]:
            (tmp_path / f"{item['id']}.teaching.mp4").write_bytes(b"real edited footage")
            (tmp_path / f"{item['id']}.teaching.json").write_text(json.dumps({"fingerprint": item["fingerprint"], "mode": item["mode"], "render_token": item["render_token"]}))

    monkeypatch.setattr(personal_knowledge_demos.subprocess, "run", render)
    clip = tmp_path / "k_u3_example.mp4"
    clip.write_bytes(b"original source video")
    entry = {"id": "k_u3_example", "type": "hook_technique", "content": "红色装置开场"}
    assert render_personal_teaching_demos([entry])["teaching_demos_rendered"] == 1
    assert render_personal_teaching_demos([entry])["teaching_demos_existing"] == 1
    assert len(calls) == 1
    entry["content"] = "第一视角开场"
    assert render_personal_teaching_demos([entry])["teaching_demos_rendered"] == 1
    assert len(calls) == 2
    assert clip.read_bytes() == b"original source video"
    assert list(tmp_path.glob("demo_batch_*.json")) == []
    # A failed forced render must not be counted as successful due to old metadata.
    monkeypatch.setattr(personal_knowledge_demos.subprocess, "run", lambda *args, **kwargs: None)
    assert render_personal_teaching_demos([entry], force=True)["teaching_demo_failures"] == [entry["id"]]


def test_multiple_ranges_from_one_source_are_all_prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(personal_knowledge_demos, 'DEMO_OUT_DIR', tmp_path)
    monkeypatch.setattr(personal_knowledge_demos, 'REMOTION_DIR', tmp_path)
    source = _test_materials(tmp_path)[0]
    ranges = [{**source, 'start': index, 'duration': 1, 'origin': 'reference_shots'} for index in range(3)]
    monkeypatch.setattr(personal_knowledge_demos, '_material_candidates', lambda entry: ranges)
    prepared = []
    monkeypatch.setattr(personal_knowledge_demos, '_prepare_assets', lambda materials, directory: prepared.extend(materials))
    monkeypatch.setattr(personal_knowledge_demos.subprocess, 'run', lambda *args, **kwargs: None)
    render_personal_teaching_demos([{'id': 'k_u3_ranges', 'type': 'packaging_style'}])
    assert prepared == []  # reference ranges cannot be substituted for reconstructed examples
