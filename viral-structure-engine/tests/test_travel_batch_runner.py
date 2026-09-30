from pathlib import Path

from agents.planner import PlannerAgent, apply_scheme_patch


def test_planner_scheme_records_replan_iteration():
    scheme = PlannerAgent(None).build_scheme(
        {"scheme_title": "test", "storyboard": []},
        target_topic="travel vlog",
        iteration=2,
    )

    assert scheme.iteration == 2


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
