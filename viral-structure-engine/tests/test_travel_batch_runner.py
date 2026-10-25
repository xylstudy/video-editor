from pathlib import Path

from agents.planner import PlannerAgent, apply_scheme_patch
from models.video_structure import ShotType
from run_pipeline_e2e import (
    apply_render_decisions,
    build_fallback_render_decisions,
    build_material_type_hint,
)


def test_planner_scheme_records_replan_iteration():
    scheme = PlannerAgent(None).build_scheme(
        {"scheme_title": "test", "storyboard": []},
        target_topic="travel vlog",
        iteration=2,
    )

    assert scheme.iteration == 2


def test_planner_preserves_shot_aliases_and_motion_design():
    scheme = PlannerAgent(None).build_scheme(
        {
            "storyboard": [
                {
                    "shot_type": "persona_expression",
                    "duration": 2.5,
                    "camera_movement": "handheld_follow",
                    "shot_size": "medium_close_up",
                    "composition": "off_center",
                    "motion_effect": "speed_ramp",
                    "rhythm_intensity": 0.8,
                    "ken_burns_config": {"motion_type": "pan_left"},
                    "speed_change": 1.25,
                },
                {"shot_type": "closing_moment", "duration": 2},
                {"shot_type": "climax", "duration": 2},
                {"shot_type": "establishing", "duration": 2},
            ]
        },
        target_topic="travel vlog",
    )

    assert [frame.shot_type for frame in scheme.storyboard] == [
        ShotType.PERSONA_EXPRESSION,
        ShotType.CLOSING_MOMENT,
        ShotType.EMOTION_PEAK,
        ShotType.SCENE_ESTABLISH,
    ]
    first = scheme.storyboard[0].to_dict()
    assert first["camera_movement"] == "handheld_follow"
    assert first["shot_size"] == "medium_close_up"
    assert first["composition"] == "off_center"
    assert first["motion_effect"] == "speed_ramp"
    assert first["rhythm_intensity"] == 0.8
    assert first["ken_burns_config"] == {"motion_type": "pan_left"}
    assert first["speed_change"] == 1.25


def test_material_hint_reflects_real_inventory_types():
    video_hint = build_material_type_hint({"items": [{"type": "video"}, {"type": "video"}]})
    mixed_hint = build_material_type_hint({"items": [{"type": "video"}, {"type": "image"}]})

    assert "全部为视频素材" in video_hint
    assert "不要按静态照片方案" in video_hint
    assert "1 个视频和 1 张图片" in mixed_hint


def test_renderer_component_config_is_written_back():
    scheme = {
        "storyboard": [
            {
                "index": 0,
                "render_component": "auto",
                "custom_render_config": {"subtitle_animation": "fade_in"},
            }
        ]
    }

    apply_render_decisions(
        scheme,
        [
            {
                "index": 0,
                "render_component": "custom:hero_push_in",
                "custom_render_config": {"intensity": 0.75, "push_direction": "in"},
            }
        ],
    )

    frame = scheme["storyboard"][0]
    assert frame["render_component"] == "custom:hero_push_in"
    assert frame["custom_render_config"] == {
        "subtitle_animation": "fade_in",
        "intensity": 0.75,
        "push_direction": "in",
    }


def test_renderer_timeout_fallback_uses_planner_motion_design():
    decisions = build_fallback_render_decisions(
        {
            "storyboard": [
                {"index": 0, "shot_type": "hook", "motion_effect": "zoom_heavy"},
                {"index": 1, "shot_type": "persona", "motion_effect": "film_grain"},
                {"index": 2, "shot_type": "emotion_peak", "motion_effect": "zoom_flash"},
                {"index": 3, "shot_type": "closing", "motion_effect": "blur_in"},
            ]
        }
    )

    assert [item["render_component"] for item in decisions] == [
        "custom:hero_push_in",
        "custom:cinematic_grain",
        "custom:kinetic_warp",
        "custom:focus_blur_resolve",
    ]


def test_batch_report_upserts_case_results():
    from scripts.run_travel_batch import update_report_counts, upsert_result

    results = [{"case_id": "case_01", "evaluation_passed": True, "returncode": 0}]
    upsert_result(results, {"case_id": "case_01", "evaluation_passed": False, "returncode": 0})
    upsert_result(results, {"case_id": "case_02", "evaluation_passed": True, "returncode": 0})

    assert len(results) == 2
    assert results[0]["evaluation_passed"] is False

    report = {"results": results}
    update_report_counts(report)
    assert report["recorded_case_count"] == 2
    assert report["passed_count"] == 1


def test_failed_rerun_does_not_reuse_stale_success_file(tmp_path: Path):
    from scripts.run_travel_batch import result_summary

    stale_result = tmp_path / "pipeline_result.json"
    stale_result.write_text(
        '{"status":"completed","is_complete":true,'
        '"evaluation":{"success":true,"score":100}}',
        encoding="utf-8",
    )

    summary = result_summary(
        {"case_id": "case_01", "target_topic": "test"},
        returncode=1,
        result_path=stale_result,
    )

    assert summary["batch_status"] == "process_failed"
    assert summary["pipeline_complete"] is False
    assert summary["evaluation_passed"] is False


def test_terminal_state_without_video_is_not_pipeline_complete(tmp_path: Path):
    from scripts.run_travel_batch import result_summary

    result_path = tmp_path / "pipeline_result.json"
    result_path.write_text(
        '{"status":"completed","phase":"complete","is_complete":true,'
        '"rendered_video_path":"","errors":["planning failed"]}',
        encoding="utf-8",
    )

    summary = result_summary(
        {"case_id": "case_08", "target_topic": "test"},
        returncode=0,
        result_path=result_path,
    )

    assert summary["workflow_terminal"] is True
    assert summary["pipeline_complete"] is False
    assert summary["batch_status"] == "incomplete"


def test_replan_patch_updates_inserts_removes_and_reindexes():
    original = {
        "title": "v0",
        "storyboard": [
            {"index": 0, "duration": 2, "subtitle_text": "a"},
            {"index": 1, "duration": 2, "subtitle_text": "b"},
            {"index": 2, "duration": 2, "subtitle_text": "c"},
        ],
    }
    patch = {
        "top_level_changes": {"title": "v1", "unknown": "ignored"},
        "storyboard_updates": [{"index": 0, "changes": {"duration": 3}}],
        "storyboard_removals": [1],
        "storyboard_insertions": [
            {"after_index": 0, "frame": {"duration": 1, "subtitle_text": "new"}},
        ],
    }

    revised = apply_scheme_patch(original, patch)

    assert revised["title"] == "v1"
    assert "unknown" not in revised
    assert [frame["index"] for frame in revised["storyboard"]] == [0, 1, 2]
    assert [frame["subtitle_text"] for frame in revised["storyboard"]] == ["a", "new", "c"]
    assert revised["storyboard"][0]["duration"] == 3
    assert original["storyboard"][0]["duration"] == 2
