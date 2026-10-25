import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from config import settings
from config.output_manager import OutputManager
from evaluation.run_evaluator import evaluate_run, evaluate_runs
from evaluation import run_evaluator
from evaluation.web_run import finalize_web_run
from evaluation.video_review import review_rendered_video
import run_storyboard_render
import main as engine_main


FIXTURES = Path(__file__).parent / "fixtures" / "evaluation"


def test_scheme_fingerprint_ignores_post_review_metadata():
    base = {"title": "demo", "storyboard": [{"index": 0, "duration": 2.0}]}
    enriched = {
        **base,
        "review_notes": ["reviewed"],
        "skill_evaluation": {"outcomes": {"reviewer": {"passed": True}}},
    }

    assert run_evaluator.scheme_fingerprint(base) == run_evaluator.scheme_fingerprint(enriched)


def test_reviewer_normalises_ten_point_output_to_percentage():
    from agents.reviewer import ReviewerAgent

    scores = {
        name: {"score": 6, "weight": 99, "reason": "ok"}
        for name in ReviewerAgent.SCORE_WEIGHTS
    }
    result = ReviewerAgent._normalise_review({
        "scores": scores,
        "fidelity": {"overall": 4},
        "quality": {"overall": 7},
        "total_score": 6.4,
        "pass": True,
        "force_iterate": False,
    })

    assert result["total_score"] == 60.0
    assert result["fidelity"]["overall"] == 40.0
    assert result["quality"]["overall"] == 70.0
    assert result["pass"] is False
    assert all(
        result["scores"][name]["weight"] == weight
        for name, weight in ReviewerAgent.SCORE_WEIGHTS.items()
    )


def test_material_coverage_counts_rendered_composite_and_custom_sources():
    scheme = {
        "storyboard": [
            {
                "source_material_id": "a",
                "fg_source_id": "b",
                "render_component": "custom:beat_montage",
                "custom_render_config": {"source_material_ids": ["a", "c"]},
            }
        ]
    }
    inventory = {"items": [{"id": value} for value in ("a", "b", "c")]}

    ratio, detail = run_evaluator._coverage(scheme, inventory)

    assert ratio == 1.0
    assert detail == "3/3 user materials used"


def _real_video(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is required for media evaluation")
    subprocess.run(
        [
            ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
            "color=c=black:s=160x90:d=2", "-c:v", "mpeg4", "-q:v", "5", str(path),
        ],
        check=True, capture_output=True, timeout=30,
    )


def test_evaluator_accepts_decodable_video_and_rejects_fake_mp4(tmp_path):
    run_dir = tmp_path / "complete"
    shutil.copytree(FIXTURES / "complete", run_dir)
    fake = evaluate_run(run_dir)
    assert fake["success"] is False
    assert fake["execution"]["video_valid"] is False
    assert fake["score"] < 100

    _real_video(run_dir / "output.mp4")
    report = evaluate_run(run_dir)
    assert report["success"] is True, [c for c in report["checks"] if not c["passed"]]
    assert report["media"]["duration_seconds"] == pytest.approx(2.0, abs=0.1)
    assert report["quality"]["material_coverage"] == 1.0
    assert report["score"] == 100.0


def test_evaluator_requires_review_artifact_and_current_scheme(tmp_path):
    run_dir = tmp_path / "complete"
    shutil.copytree(FIXTURES / "complete", run_dir)
    _real_video(run_dir / "output.mp4")
    (run_dir / "reviewer" / "review_result.json").unlink()
    missing = evaluate_run(run_dir)
    assert missing["success"] is False
    assert next(c for c in missing["checks"] if c["name"] == "review_artifact")["passed"] is False

    review_path = run_dir / "reviewer" / "review_result.json"
    review_path.write_text(
        json.dumps({"pass": True, "total_score": 91, "scheme_fingerprint": "stale"}),
        encoding="utf-8",
    )
    stale = evaluate_run(run_dir)
    assert stale["success"] is False
    assert stale["quality"]["review_current"] is False


def test_declared_agent_stage_must_have_successful_record(tmp_path):
    run_dir = tmp_path / "complete"
    shutil.copytree(FIXTURES / "complete", run_dir)
    _real_video(run_dir / "output.mp4")
    info_path = run_dir / "run_info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info["expected_stages"] = ["analyst", "material", "planner", "renderer", "assembler", "reviewer", "creative"]
    info_path.write_text(json.dumps(info), encoding="utf-8")

    report = evaluate_run(run_dir)
    assert report["success"] is False
    assert report["execution"]["missing_stages"] == ["creative"]


def test_evaluator_does_not_treat_completion_as_success():
    report = evaluate_run(FIXTURES / "completed_without_quality")
    assert report["success"] is False
    assert report["quality"]["review_pass"] is False
    assert report["quality"]["review_accepted"] is False
    assert report["execution"]["video_valid"] is False


def test_cli_quality_gate_rejects_failed_run_even_with_high_score(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "run_evaluator", "--run-dir", str(FIXTURES / "complete"), "--min-score", "70",
    ])
    with pytest.raises(SystemExit) as exc:
        run_evaluator.main()
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["success"] is False


def test_prepared_run_is_ready_but_not_final(tmp_path):
    run_dir = tmp_path / "prepared"
    shutil.copytree(FIXTURES / "complete", run_dir)
    (run_dir / "pipeline_summary.json").write_text(
        json.dumps({"status": "awaiting_confirmation", "errors": [], "rendered_video_path": ""}),
        encoding="utf-8",
    )
    report = evaluate_run(run_dir)
    assert report["ready_for_render"] is True
    assert report["success"] is False
    aggregate = evaluate_runs([run_dir])
    assert aggregate["pending_count"] == 1
    assert aggregate["success_rate"] is None

    with (run_dir / "logs" / "agent_logs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"stage": "planner", "llm_usage": {"mock_requests": 1}}) + "\n")
    mocked = evaluate_run(run_dir)
    assert mocked["ready_for_render"] is False
    assert mocked["llm_usage"]["mock_requests"] == 1


def test_web_finalizer_reviews_confirmed_scheme_and_records_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RUNS_DIR", tmp_path / "runs")
    out = OutputManager("web_task_42")
    out.save_run_info(user_materials_count=2, execution_mode="plan_render")
    scheme = {"target_topic": "旅行", "target_duration": 2, "storyboard": [
        {"index": 0, "material_id": "a", "duration": 1},
        {"index": 1, "material_id": "b", "duration": 1},
    ]}
    inventory = {"items": [{"id": "a"}, {"id": "b"}]}
    scheme_path = tmp_path / "confirmed.json"
    inventory_path = tmp_path / "inventory.json"
    structure_path = tmp_path / "reference.json"
    video_path = tmp_path / "rendered.mp4"
    scheme_path.write_text(json.dumps(scheme), encoding="utf-8")
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    structure_path.write_text('{"shots":[]}', encoding="utf-8")
    _real_video(video_path)
    for stage in ("material", "planner", "renderer"):
        out.append_log(stage, {"success": True})

    from agents.reviewer import ReviewerAgent
    simulate_mock = {"enabled": False}

    async def fake_review(
        self, source_structure_summary: str, scheme_json: str,
        material_coverage_desc: str, material_list_desc: str = "",
        transition_summary: str = "", gene_json: str = "",
    ):
        assert json.loads(scheme_json)["storyboard"][0]["material_id"] == "a"
        if simulate_mock["enabled"]:
            self.llm._record_mock()
        return {"pass": True, "total_score": 92}

    monkeypatch.setattr(ReviewerAgent, "_review_scheme", fake_review)
    report = asyncio.run(finalize_web_run(
        "web_task_42", scheme_path, inventory_path, video_path,
        reference_structure_path=structure_path, model_config={"VISION_API_KEY": ""},
    ))
    assert report["success"] is True, json.loads(
        (out.run_dir / "pipeline_summary.json").read_text(encoding="utf-8")
    )["errors"]
    assert report["quality"]["review_current"] is True
    assert json.loads((out.run_dir / "evaluation" / "report.json").read_text(encoding="utf-8"))["success"] is True
    assert json.loads((out.run_dir / "planner" / "scheme_final.json").read_text(encoding="utf-8")) == scheme

    simulate_mock["enabled"] = True
    mocked = asyncio.run(finalize_web_run(
        "web_task_42", scheme_path, inventory_path, video_path,
        reference_structure_path=structure_path, model_config={"VISION_API_KEY": ""},
    ))
    assert mocked["success"] is False
    assert mocked["quality"]["review_pass"] is False
    assert mocked["llm_usage"]["mock_requests"] == 1

    failed = asyncio.run(finalize_web_run(
        "web_task_42", scheme_path, inventory_path, None,
        render_error="Remotion failed",
    ))
    assert failed["phase"] == "failed"
    assert failed["success"] is False
    assert failed["execution"]["error_count"] == 1


def test_render_review_keeps_timed_evidence_and_uses_vision_result(tmp_path, monkeypatch):
    video_path = tmp_path / "rendered.mp4"
    _real_video(video_path)
    scheme = {"target_topic": "旅行", "target_duration": 2, "storyboard": [
        {"index": 0, "duration": 1, "material_id": "a", "purpose": "开场 Hook"},
        {"index": 1, "duration": 1, "material_id": "b", "purpose": "收尾"},
    ]}

    from config.llm_client import LLMTools
    received = {}

    async def fake_images(self, prompt, image_paths, **kwargs):
        received["prompt"] = prompt
        received["paths"] = image_paths
        self._usage["requests"] += 1
        self._usage["attempts"] += 1
        self._usage["responses"] += 1
        return json.dumps({
            "scores": {"hook_delivery": {"score": 8, "reason": "开场画面完整"}},
            "total_score": 86,
            "pass": True,
            "summary": "成片与分镜基本一致",
            "limitations": ["代表帧无法完整判断音画同步"],
            "issues": [{"category": "subtitle", "severity": "low", "description": "字幕较小", "evidence_times": [0.5], "suggestion": "增大字号"}],
            "highlights": ["开场清晰"],
        })

    monkeypatch.setattr(LLMTools, "chat_with_images", fake_images)
    review, usage = asyncio.run(review_rendered_video(
        video_path, scheme, {"duration": 2, "gene": {}}, tmp_path / "render_reviewer",
        model_config={"VISION_API_KEY": "key", "VISION_BASE_URL": "http://localhost:1/v1", "VISION_MODEL_ID": "vision-test"},
    ))
    assert review["status"] == "completed"
    assert review["visual_review"]["total_score"] == 86
    assert review["technical"]["full_decode_valid"] is True
    assert review["evidence"]["shots"][0]["frames"][0]["path"].startswith("frames/")
    assert received["paths"]
    assert usage["requests"] == 1


def test_confirmed_render_script_finalizes_both_success_and_failure(tmp_path, monkeypatch):
    scheme = tmp_path / "scheme.json"
    inventory = tmp_path / "inventory.json"
    output = tmp_path / "output.mp4"
    scheme.write_text('{"storyboard":[{"material_id":"a"}]}', encoding="utf-8")
    inventory.write_text('{"items":[{"id":"a"}]}', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "run_storyboard_render.py", "--scheme", str(scheme),
        "--materials", str(inventory), "--output", str(output),
        "--run-id", "web_task_42", "--reference-structure", str(tmp_path / "reference.json"),
    ])
    calls = []

    async def fake_finalize(*args, **kwargs):
        calls.append((args, kwargs))
        return {"score": 100, "success": kwargs.get("render_error") is None}

    from evaluation import web_run
    monkeypatch.setattr(web_run, "finalize_web_run", fake_finalize)

    def fake_render(*args, **kwargs):
        output.write_bytes(b"video")
        return str(output)

    monkeypatch.setattr(run_storyboard_render, "render_with_remotion", fake_render)
    run_storyboard_render.main()
    assert calls[-1][0][0] == "web_task_42"
    assert calls[-1][0][3] == str(output)

    monkeypatch.setattr(run_storyboard_render, "render_with_remotion", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="Remotion 渲染失败"):
        run_storyboard_render.main()
    assert calls[-1][1]["render_error"] == "Remotion 渲染失败"


def test_graph_failure_persists_evaluation(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RUNS_DIR", tmp_path / "runs")

    class BrokenGraph:
        async def ainvoke(self, _state):
            raise RuntimeError("planner crashed")

    monkeypatch.setattr(engine_main, "build_graph", lambda: BrokenGraph())
    with pytest.raises(RuntimeError, match="planner crashed"):
        asyncio.run(engine_main.run_pipeline([], [], "旅行", run_id="broken_graph"))

    report = json.loads((tmp_path / "runs" / "broken_graph" / "evaluation" / "report.json").read_text(encoding="utf-8"))
    assert report["phase"] == "failed"
    assert report["success"] is False
    assert report["execution"]["error_count"] == 1
