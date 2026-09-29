import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import pipeline_runner
import queue_manager
import gene_sync
from db_models import (
    Gene,
    GeneStatus,
    Material,
    MaterialType,
    PipelineMode,
    Project,
    ProjectCreate,
    Task,
    TaskCreate,
    TaskStatus,
    TaskType,
    User,
)
from routers import projects, tasks
from routers import insights, stats
from config import settings as vse_settings


def make_session():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    session = Session(test_engine)
    user = User(id=1, username="pipeline-user", hashed_password="x")
    session.add(user)
    session.commit()
    return session, user


def test_task_contexts_never_share_mutable_paths(tmp_path):
    first = pipeline_runner.TaskRunContext.create(tmp_path / "task-1")
    second = pipeline_runner.TaskRunContext.create(tmp_path / "task-2")

    first.material_inventory.write_text("[]", encoding="utf-8")

    assert first.material_inventory != second.material_inventory
    assert first.final_video != second.final_video
    assert not second.material_inventory.exists()


def test_reference_replacement_is_detected_by_content(tmp_path):
    old_video = tmp_path / "reference.mp4"
    new_video = tmp_path / "uploaded-again.mp4"
    old_video.write_bytes(b"old-reference")
    new_video.write_bytes(b"new-reference")

    assert not pipeline_runner.files_match(old_video, new_video)

    new_video.write_bytes(old_video.read_bytes())
    assert pipeline_runner.files_match(old_video, new_video)


def test_gene_report_is_split_inside_task_directory(tmp_path):
    source = tmp_path / "gene-report.json"
    source.write_text(
        json.dumps({
            "source_video": "reference.mp4",
            "raw_shot_analyses": [{"start_time": 0, "end_time": 1}],
            "raw_structure_analysis": {"script_structure": [{"index": 0}]},
        }),
        encoding="utf-8",
    )
    context = pipeline_runner.TaskRunContext.create(tmp_path / "task")

    pipeline_runner.prepare_analysis_report(source, context)

    shots = json.loads(context.shot_analyses.read_text(encoding="utf-8"))
    assert shots[0]["shot_index"] == 0
    assert context.reference_report.parent == context.analysis_dir
    assert context.video_structure.parent == context.analysis_dir


def test_task_report_syncs_once_to_gene_library_and_insights(tmp_path, monkeypatch):
    session, user = make_session()
    project = Project(name="night city", user_id=user.id, pipeline_mode=PipelineMode.AGENT_PIPELINE)
    session.add(project)
    session.commit()
    session.refresh(project)
    video_path = tmp_path / "reference.mp4"
    video_path.write_bytes(b"video")
    video = Material(
        project_id=project.id,
        type=MaterialType.VIDEO,
        filename=video_path.name,
        storage_path=str(video_path),
    )
    session.add(video)
    session.commit()
    session.refresh(video)

    analysis_dir = tmp_path / "task" / "analysis"
    analysis_dir.mkdir(parents=True)
    report_path = analysis_dir / "reference_report.json"
    report_path.write_text(json.dumps({
        "source_path": str(video_path),
        "duration": 15.0,
        "shot_count": 1,
        "vlog_meta": {
            "structure_type": "递进展开型",
            "narrative_type": "timeline",
            "overall_emotion": "期待",
            "hook_method": "视觉冲击",
        },
        "shots": [{
            "index": 0,
            "start_time": 0,
            "end_time": 1,
            "duration": 1,
            "shot_type": "scene_establish",
            "emotion": "期待",
            "transition_in": "cut",
        }],
        "raw_shot_analyses": [{"shot_index": 0, "start_time": 0, "end_time": 1}],
        "raw_structure_analysis": {"script_structure": [{"index": 0}]},
    }, ensure_ascii=False), encoding="utf-8")
    frames = analysis_dir / "frames"
    frames.mkdir()
    (frames / "shot_000.jpg").write_bytes(b"frame")

    kwargs = {
        "task_id": 9,
        "project_id": project.id,
        "user_id": user.id,
        "video": video,
        "report_path": report_path,
        "db_engine": session.get_bind(),
        "storage_root": tmp_path / "storage",
    }
    first_id = gene_sync.sync_task_reference_gene(**kwargs)
    second_id = gene_sync.sync_task_reference_gene(**kwargs)

    genes = session.exec(select(Gene)).all()
    session.refresh(project)
    assert first_id == second_id == project.gene_id
    assert len(genes) == 1
    assert genes[0].status == GeneStatus.DONE
    assert genes[0].shot_count == 1
    assert Path(genes[0].video_path).read_bytes() == b"video"
    assert (Path(genes[0].report_path).parent / "frames" / "shot_000.jpg").is_file()
    stored = json.loads(Path(genes[0].report_path).read_text(encoding="utf-8"))
    assert stored["source_path"] == str(Path(genes[0].video_path).resolve())

    monkeypatch.setattr(insights, "STORAGE_ROOT", tmp_path / "storage")
    mined, videos = insights._run_mining(user.id)
    assert mined["sample_size"] == 1
    assert len(videos) == 1


def test_stats_counts_successful_end_to_end_tasks_with_enum_storage(tmp_path, monkeypatch):
    session, user = make_session()
    project = Project(name="complete", user_id=user.id)
    session.add(project)
    session.commit()
    session.refresh(project)
    session.add(Task(
        project_id=project.id,
        type=TaskType.END_TO_END,
        status=TaskStatus.SUCCESS,
        progress=100,
    ))
    session.commit()
    monkeypatch.setattr(stats, "VSE_KNOWLEDGE_DB", tmp_path / "missing.json")

    payload = stats.get_stats(current_user=user, session=session)

    assert payload["works"] == 1


def test_lightweight_inventory_matches_editing_engine_contract(tmp_path):
    photo_path = tmp_path / "新品主图.jpg"
    photo_path.write_bytes(b"image")
    photo = Material(
        project_id=1,
        type=MaterialType.IMAGE,
        filename=photo_path.name,
        storage_path=str(photo_path),
    )
    output = tmp_path / "task" / "inventory.json"

    pipeline_runner.write_lightweight_inventory([photo], output)

    inventory = json.loads(output.read_text(encoding="utf-8"))
    assert inventory["items"][0]["id"] == "mat_000"
    assert inventory["materials"] == inventory["items"]


def test_editing_transfer_explicitly_disables_model_credentials(tmp_path, monkeypatch):
    context = pipeline_runner.TaskRunContext.create(tmp_path / "task")
    context.material_inventory.write_text('{"items": []}', encoding="utf-8")
    video_path = tmp_path / "reference.mp4"
    video_path.write_bytes(b"video")
    video = Material(
        project_id=1,
        type=MaterialType.VIDEO,
        filename="reference.mp4",
        storage_path=str(video_path),
    )
    captured = {}

    async def fake_run_command(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env_overrides"]
        context.scheme.write_text('{"storyboard": []}', encoding="utf-8")

    monkeypatch.setattr(pipeline_runner, "run_command", fake_run_command)
    result = asyncio.run(pipeline_runner._run_editing_transfer(
        7, video, "产品展示", context, "python", lambda *args: None
    ))

    assert result == str(context.scheme)
    assert captured["env"]["VISION_API_KEY"] == ""
    assert captured["env"]["TEXT_API_KEY"] == ""
    assert str(context.material_inventory) in captured["cmd"]
    assert str(context.final_video) in captured["cmd"]
    assert "--prepare-only" in captured["cmd"]


def test_project_keeps_selected_gene_for_report_reuse(tmp_path, monkeypatch):
    session, user = make_session()
    video_path = tmp_path / "gene.mp4"
    report_path = tmp_path / "report.json"
    video_path.write_bytes(b"video")
    report_path.write_text("{}", encoding="utf-8")
    gene = Gene(
        user_id=user.id,
        title="reference",
        status=GeneStatus.DONE,
        video_path=str(video_path),
        report_path=str(report_path),
    )
    session.add(gene)
    session.commit()
    session.refresh(gene)
    monkeypatch.setattr(projects, "get_project_dir", lambda *_: tmp_path / "project")

    project = projects.create_project(
        ProjectCreate(
            name="reuse",
            topic="产品展示",
            pipeline_mode=PipelineMode.EDITING_TRANSFER,
            gene_id=gene.id,
        ),
        current_user=user,
        session=session,
    )

    assert project.gene_id == gene.id
    material = session.exec(select(Material).where(Material.project_id == project.id)).one()
    assert Path(material.storage_path).is_file()


def test_task_material_requirements_follow_task_type(monkeypatch):
    session, user = make_session()
    project = Project(
        name="video-only",
        user_id=user.id,
        pipeline_mode=PipelineMode.EDITING_TRANSFER,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    session.add(Material(
        project_id=project.id,
        type=MaterialType.VIDEO,
        filename="reference.mp4",
        storage_path="reference.mp4",
    ))
    session.commit()
    queued = []
    monkeypatch.setattr(tasks.queue, "enqueue", lambda *args: queued.append(args))

    task = tasks.create_task(
        project.id,
        TaskCreate(type=TaskType.ANALYZE_VIDEO),
        current_user=user,
        session=session,
    )
    assert task.type == TaskType.ANALYZE_VIDEO
    assert queued

    with pytest.raises(HTTPException) as exc:
        tasks.create_task(
            project.id,
            TaskCreate(type=TaskType.END_TO_END),
            current_user=user,
            session=session,
        )
    assert exc.value.status_code == 400


def test_end_to_end_editing_route_runs_without_any_model_config(tmp_path, monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        user = User(username="no-api-user", hashed_password="x")
        session.add(user)
        session.commit()
        session.refresh(user)
        project = Project(
            name="local-edit",
            topic="新品发布",
            user_id=user.id,
            pipeline_mode=PipelineMode.EDITING_TRANSFER,
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        session.add(Material(
            project_id=project.id,
            type=MaterialType.VIDEO,
            filename="reference.mp4",
            storage_path=str(tmp_path / "reference.mp4"),
        ))
        session.add(Material(
            project_id=project.id,
            type=MaterialType.IMAGE,
            filename="product.jpg",
            storage_path=str(tmp_path / "product.jpg"),
        ))
        task = Task(project_id=project.id, type=TaskType.END_TO_END)
        session.add(task)
        session.commit()
        session.refresh(task)
        ids = task.id, project.id, user.id

    async def fake_editing(task_id, video, topic, context, python_exe, emit_progress):
        inventory = json.loads(context.material_inventory.read_text(encoding="utf-8"))
        assert inventory["items"][0]["id"] == "mat_000"
        context.scheme.write_text('{"title": "draft", "storyboard": []}', encoding="utf-8")
        return str(context.scheme)

    monkeypatch.setattr(pipeline_runner, "engine", test_engine)
    monkeypatch.setattr(pipeline_runner, "STORAGE_ROOT", tmp_path / "storage")
    monkeypatch.setattr(pipeline_runner, "_get_effective_model_env", lambda _: {})
    monkeypatch.setattr(pipeline_runner, "_run_editing_transfer", fake_editing)

    result = asyncio.run(pipeline_runner.run_pipeline(*ids, lambda *args: None))

    assert json.loads(Path(result).read_text(encoding="utf-8"))["title"] == "draft"


def test_storyboard_can_be_edited_then_confirmed(tmp_path, monkeypatch):
    session, user = make_session()
    project = Project(name="storyboard", user_id=user.id)
    session.add(project)
    session.commit()
    session.refresh(project)
    task = Task(
        project_id=project.id,
        type=TaskType.END_TO_END,
        status=TaskStatus.AWAITING_CONFIRMATION,
        progress=70,
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    monkeypatch.setattr(tasks, "STORAGE_ROOT", tmp_path)
    root = tmp_path / "users" / str(user.id) / "projects" / str(project.id) / "tasks" / str(task.id)
    scheme_path = root / "output" / "scheme.json"
    inventory_path = root / "analysis" / "material_inventory.json"
    scheme_path.parent.mkdir(parents=True)
    inventory_path.parent.mkdir(parents=True)
    scheme_path.write_text(json.dumps({
        "title": "初稿",
        "target_duration": 3,
        "storyboard": [
            {"index": 0, "material_id": "mat_000", "duration": 1, "subtitle_text": "一", "transition": "cut"},
            {"index": 1, "material_id": "mat_001", "duration": 2, "subtitle_text": "二", "transition": "fade"},
        ],
    }), encoding="utf-8")
    inventory_path.write_text(json.dumps({"items": [
        {"id": "mat_000", "path": str(tmp_path / "one.jpg"), "description": "第一张"},
        {"id": "mat_001", "path": str(tmp_path / "two.jpg"), "description": "第二张"},
    ]}), encoding="utf-8")
    task.scheme_path = str(scheme_path)
    session.add(task)
    session.commit()

    draft = tasks.get_storyboard(task.id, current_user=user, session=session)
    updated = tasks.update_storyboard(
        task.id,
        {
            "title": "确认稿",
            "revision": draft["revision"],
            "storyboard": [
                {**draft["storyboard"][1], "duration": 2.5, "subtitle_text": "新的第二镜"},
                {**draft["storyboard"][0], "duration": 1.5, "transition": "dissolve"},
            ],
        },
        current_user=user,
        session=session,
    )

    assert updated["title"] == "确认稿"
    assert updated["target_duration"] == 4.0
    assert updated["storyboard"][0]["material_id"] == "mat_001"
    assert updated["revision"] == 1

    queued = []
    monkeypatch.setattr(tasks.queue, "enqueue", lambda *args: queued.append(args))
    confirmed = tasks.confirm_storyboard(task.id, current_user=user, session=session)

    assert confirmed.status == TaskStatus.PENDING
    assert confirmed.workflow_stage == "render"
    assert confirmed.progress == 70
    assert queued == [(task.id, project.id, user.id)]


def test_storyboard_rejects_unknown_material(tmp_path, monkeypatch):
    session, user = make_session()
    project = Project(name="storyboard", user_id=user.id)
    session.add(project)
    session.commit()
    session.refresh(project)
    task = Task(project_id=project.id, type=TaskType.END_TO_END, status=TaskStatus.AWAITING_CONFIRMATION)
    session.add(task)
    session.commit()
    session.refresh(task)
    monkeypatch.setattr(tasks, "STORAGE_ROOT", tmp_path)
    root = tmp_path / "users" / str(user.id) / "projects" / str(project.id) / "tasks" / str(task.id)
    scheme_path = root / "output" / "scheme.json"
    inventory_path = root / "analysis" / "material_inventory.json"
    scheme_path.parent.mkdir(parents=True)
    inventory_path.parent.mkdir(parents=True)
    scheme_path.write_text(json.dumps({"title": "初稿", "storyboard": [
        {"index": 0, "material_id": "mat_000", "duration": 1, "transition": "cut"}
    ]}), encoding="utf-8")
    inventory_path.write_text('{"items": [{"id": "mat_000", "path": "one.jpg"}]}', encoding="utf-8")
    task.scheme_path = str(scheme_path)
    session.add(task)
    session.commit()
    draft = tasks.get_storyboard(task.id, current_user=user, session=session)

    with pytest.raises(HTTPException) as exc:
        tasks.update_storyboard(
            task.id,
            {"title": "初稿", "revision": draft["revision"], "storyboard": [
                {**draft["storyboard"][0], "material_id": "not-owned"}
            ]},
            current_user=user,
            session=session,
        )
    assert exc.value.status_code == 422


def test_queue_pauses_for_confirmation_then_completes_render(tmp_path, monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        user = User(username="queue-user", hashed_password="x")
        session.add(user)
        session.commit()
        session.refresh(user)
        project = Project(name="queue-project", user_id=user.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        task = Task(project_id=project.id, type=TaskType.END_TO_END)
        session.add(task)
        session.commit()
        session.refresh(task)
        ids = task.id, project.id, user.id

    scheme_path = tmp_path / "scheme.json"
    scheme_path.write_text("{}", encoding="utf-8")
    video_path = tmp_path / "final.mp4"

    async def fake_broadcast(*_args, **_kwargs):
        return None

    async def prepare_pipeline(**_kwargs):
        return str(scheme_path)

    monkeypatch.setattr(queue_manager, "engine", test_engine)
    monkeypatch.setattr(queue_manager.ws_manager, "broadcast", fake_broadcast)
    monkeypatch.setattr(queue_manager, "run_pipeline", prepare_pipeline)
    worker = queue_manager.TaskQueue()
    item = queue_manager.QueueItem(task_id=ids[0], project_id=ids[1], user_id=ids[2])
    asyncio.run(worker._execute_item(item))

    with Session(test_engine) as session:
        prepared = session.get(Task, ids[0])
        assert prepared.status == TaskStatus.AWAITING_CONFIRMATION
        assert prepared.scheme_path == str(scheme_path)
        prepared.workflow_stage = "render"
        prepared.status = TaskStatus.PENDING
        session.add(prepared)
        session.commit()

    async def render_pipeline(**_kwargs):
        video_path.write_bytes(b"video")
        return str(video_path)

    monkeypatch.setattr(queue_manager, "run_pipeline", render_pipeline)
    asyncio.run(worker._execute_item(item))

    with Session(test_engine) as session:
        rendered = session.get(Task, ids[0])
        assert rendered.status == TaskStatus.SUCCESS
        assert rendered.result_path == str(video_path)
        assert rendered.progress == 100


def test_agent_render_uses_same_run_and_model_for_final_review(tmp_path, monkeypatch):
    context = pipeline_runner.TaskRunContext.create(tmp_path / "task")
    context.scheme.write_text('{"storyboard":[{"material_id":"a"}]}', encoding="utf-8")
    context.material_inventory.write_text('{"items":[{"id":"a"}]}', encoding="utf-8")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"reference")
    video = Material(
        project_id=1, type=MaterialType.VIDEO,
        filename=reference.name, storage_path=str(reference),
    )
    captured = {}
    engine_dir = tmp_path / "engine"
    monkeypatch.setattr(pipeline_runner, "VSE_DIR", engine_dir)

    async def fake_run_command(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env_overrides"]
        context.final_video.write_bytes(b"rendered")
        report_path = engine_dir / "data" / "runs" / "web_task_42" / "evaluation" / "report.json"
        report_path.parent.mkdir(parents=True)
        report_path.write_text('{"phase":"completed"}', encoding="utf-8")

    monkeypatch.setattr(pipeline_runner, "run_command", fake_run_command)
    result = asyncio.run(pipeline_runner._run_storyboard_render(
        video, context.scheme, context, "python", lambda *args: None,
        evaluation_run_id="web_task_42",
        model_env={"TEXT_API_KEY": "test-key"},
    ))
    assert result == str(context.final_video)
    assert captured["cmd"][captured["cmd"].index("--run-id") + 1] == "web_task_42"
    assert str(context.video_structure) in captured["cmd"]
    assert captured["env"]["TEXT_API_KEY"] == "test-key"


def test_agent_prepare_failure_still_writes_evaluation(tmp_path, monkeypatch):
    monkeypatch.setattr(vse_settings, "RUNS_DIR", tmp_path / "runs")
    context = pipeline_runner.TaskRunContext.create(tmp_path / "task")
    project = Project(name="failed-plan", topic="旅行", user_id=1, pipeline_mode=PipelineMode.AGENT_PIPELINE)

    with pytest.raises(RuntimeError, match="视频结构分析结果未生成"):
        asyncio.run(pipeline_runner._run_agent_pipeline(
            42, project, context, "python", lambda *args: None, {},
        ))

    report = json.loads((tmp_path / "runs" / "web_task_42" / "evaluation" / "report.json").read_text(encoding="utf-8"))
    assert report["phase"] == "failed"
    assert report["success"] is False
    assert report["execution"]["error_count"] == 1


def test_agent_task_failing_before_planning_writes_report(tmp_path, monkeypatch):
    session, user = make_session()
    project = Project(name="early-failure", user_id=user.id, pipeline_mode=PipelineMode.AGENT_PIPELINE)
    session.add(project)
    session.commit()
    session.refresh(project)
    task = Task(project_id=project.id, type=TaskType.END_TO_END)
    session.add(task)
    session.commit()
    session.refresh(task)

    async def failed_pipeline(**kwargs):
        raise RuntimeError("material analysis failed")

    async def fake_broadcast(*args, **kwargs):
        return None

    monkeypatch.setattr(vse_settings, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(queue_manager, "engine", session.get_bind())
    monkeypatch.setattr(queue_manager, "run_pipeline", failed_pipeline)
    monkeypatch.setattr(queue_manager.ws_manager, "broadcast", fake_broadcast)
    worker = queue_manager.TaskQueue()
    asyncio.run(worker._execute_item(queue_manager.QueueItem(
        task_id=task.id, project_id=project.id, user_id=user.id,
    )))

    report = json.loads((tmp_path / "runs" / f"web_task_{task.id}" / "evaluation" / "report.json").read_text(encoding="utf-8"))
    assert report["phase"] == "failed"
    assert report["success"] is False
    assert report["execution"]["error_count"] == 1


def test_evaluation_report_is_scoped_to_task_owner(tmp_path, monkeypatch):
    session, user = make_session()
    project = Project(name="agent-report", user_id=user.id, pipeline_mode=PipelineMode.AGENT_PIPELINE)
    session.add(project)
    session.commit()
    session.refresh(project)
    task = Task(project_id=project.id, type=TaskType.END_TO_END)
    session.add(task)
    session.commit()
    session.refresh(task)

    monkeypatch.setattr(tasks, "VSE_DIR", tmp_path)
    report_path = tmp_path / "data" / "runs" / f"web_task_{task.id}" / "evaluation" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text('{"phase":"completed","score":91}', encoding="utf-8")

    assert tasks.get_task_evaluation(task.id, current_user=user, session=session)["score"] == 91
    with pytest.raises(HTTPException) as exc:
        tasks.get_task_evaluation(
            task.id,
            current_user=User(id=user.id + 1, username="other", hashed_password="x"),
            session=session,
        )
    assert exc.value.status_code == 404
