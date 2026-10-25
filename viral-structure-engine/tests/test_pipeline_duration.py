import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run_pipeline_e2e import (
    build_preferences,
    infer_target_duration,
    normalize_storyboard_duration,
)


def test_explicit_topic_duration_wins_over_reference():
    assert infer_target_duration("15秒城市夜游短片", 73.8) == 15
    assert infer_target_duration("a 12 sec city reel", 30) == 12


def test_reference_duration_is_the_default():
    assert infer_target_duration("城市夜游短片", 15) == 15


def test_storyboard_duration_is_scaled_to_exact_target():
    scheme = {
        "target_duration": 41,
        "storyboard": [{"duration": 3}, {"duration": 5}, {"duration": 2}],
    }

    normalized = normalize_storyboard_duration(scheme, 15)

    assert normalized["target_duration"] == 15
    assert sum(frame["duration"] for frame in normalized["storyboard"]) == 15


def test_short_video_preferences_do_not_request_long_form_output():
    preferences = build_preferences("15秒城市夜游短片", 15)
    assert preferences["shot_count_target"] == "6-10个分镜"
    assert preferences["total_duration_guide"] == "严格控制为 15 秒"


def test_reference_shot_count_preserves_fast_cut_structure():
    preferences = build_preferences("俏皮生活手账", 23.7, reference_shot_count=22)
    assert preferences["shot_count_target"] == "22个分镜"
    assert preferences["total_duration_guide"] == "严格控制为 23.7 秒"
    assert "禁止重复" in preferences["material_usage"]
