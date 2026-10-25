import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import insight_cache
import knowledge_sync
import learning_materials
import learning_service
import queue_manager
from config import settings
from db_models import Gene, LearningJob, Material, MaterialType, Project, Task, TaskStatus, TaskType, User
from routers import insights, tasks


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    db = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(db)
    storage = tmp_path / "storage"
    for module in (learning_service, queue_manager, knowledge_sync, learning_materials):
        monkeypatch.setattr(module, "engine", db)
    for module in (learning_service, insight_cache, insights):
        monkeypatch.setattr(module, "STORAGE_ROOT", storage)
    monkeypatch.setattr(settings, "KNOWLEDGE_DB_DIR", tmp_path / "knowledge")
    knowledge_sync._gene_locks.clear()
    with Session(db) as session:
        user = User(username="automatic-learning", hashed_password="x")
        session.add(user); session.commit(); session.refresh(user)
        project = Project(user_id=user.id, name="actual task source")
        session.add(project); session.commit(); session.refresh(project)
        task = Task(project_id=project.id, type=TaskType.END_TO_END, workflow_stage="render")
        session.add(task); session.commit(); session.refresh(task)
        video_path = tmp_path / "new-reference.mp4"
        video_path.write_bytes(b"reference-video-bytes")
        material = Material(project_id=project.id, type=MaterialType.VIDEO, filename=video_path.name, storage_path=str(video_path))
        material.set_metadata({"role": "reference"})
        session.add(material); session.commit()
        ids = (task.id, project.id, user.id)
    report = {
        "duration": 2, "shot_count": 2, "source_path": str(video_path),
        "vlog_meta": {"structure_type": "递进", "overall_emotion": "期待", "hook_method": "视觉冲击"},
        "shots": [{"index": i, "start_time": i, "end_time": i + 1, "duration": 1, "shot_type": "hook" if i == 0 else "closing", "emotion": "期待", "transition_in": "cut"} for i in range(2)],
        "raw_shot_analyses": [{"shot_index": i, "start_time": i, "end_time": i + 1} for i in range(2)],
        "raw_structure_analysis": {"script_structure": [{"index": 0, "purpose": "开场", "duration_hint": 2}]},
    }

    async def pipeline(**kwargs):
        root = storage / "users" / str(ids[2]) / "projects" / str(ids[1]) / "tasks" / str(ids[0])
        (root / "analysis").mkdir(parents=True)
        (root / "analysis/reference_report.json").write_text(json.dumps(report), encoding="utf-8")
        (root / "output").mkdir()
        output = root / "output/final_video.mp4"
        output.write_bytes(b"completed-render")
        return str(output)

    async def broadcast(*args, **kwargs):
        pass

    def prepare(gene_id, user_id, project_id, expected_materials=None):
        assert project_id == ids[1] and user_id == ids[2]
        with Session(db) as session:
            assert Path(session.get(Gene, gene_id).video_path).read_bytes() == b"reference-video-bytes"

    monkeypatch.setattr(queue_manager, "run_pipeline", pipeline)
    monkeypatch.setattr(queue_manager.ws_manager, "broadcast", broadcast)
    monkeypatch.setattr(learning_materials, "prepare_example_materials", prepare)
    monkeypatch.setattr(knowledge_sync, "_render_demo_entries", lambda entries: {"demos_available": len(entries), "demo_failures": [], "teaching_demos_rendered": len(entries), "teaching_demos_existing": 0, "teaching_demo_failures": []})
    return db, storage, ids


def test_successful_task_automatically_creates_all_assets_and_insight_snapshot(lifecycle):
    db, storage, ids = lifecycle
    asyncio.run(queue_manager.TaskQueue()._execute_item(queue_manager.QueueItem(*ids)))
    with Session(db) as session:
        task = session.get(Task, ids[0])
        job = session.exec(select(LearningJob)).one()
        assert task.status == TaskStatus.SUCCESS and job.status == "pending"
        job_id = job.id
    asyncio.run(learning_service.process_learning_job(job_id))
    asyncio.run(learning_service.process_learning_job(job_id))
    with Session(db) as session:
        job = session.get(LearningJob, job_id)
        assert job.status == "completed"
        assert all(value["status"] == "done" for value in job.steps.values())
        assert job.result["knowledge_count"] == job.result["editing_examples"] == job.result["source_examples"] == 5
        assert len(session.exec(select(Gene)).all()) == 1
        assert job.attempts == 1
        assert tasks.task_learning(ids[0], current_user=session.get(User, ids[2]), session=session)["status"] == "completed"
        with pytest.raises(HTTPException) as denied:
            tasks.task_learning(ids[0], current_user=User(id=999, username="other", hashed_password="x"), session=session)
        assert denied.value.status_code == 404
    cached = insight_cache.read_cached_insights(ids[2])
    assert cached["sample_size"] == 1
    assert (storage / "users" / str(ids[2]) / "insights/report.html").is_file()
    assert len(json.loads((settings.KNOWLEDGE_DB_DIR / "knowledge.json").read_text(encoding="utf-8"))) == 5


def test_example_failure_is_retried_without_losing_successful_video_or_duplicate_knowledge(lifecycle, monkeypatch):
    db, _, ids = lifecycle
    asyncio.run(queue_manager.TaskQueue()._execute_item(queue_manager.QueueItem(*ids)))
    with Session(db) as session:
        job_id = session.exec(select(LearningJob)).one().id
    successful_renderer = knowledge_sync._render_demo_entries
    monkeypatch.setattr(knowledge_sync, "_render_demo_entries", lambda entries: {"demos_available": 5, "teaching_demo_failures": [entries[0]["id"]]})
    asyncio.run(learning_service.process_learning_job(job_id))
    with Session(db) as session:
        job = session.get(LearningJob, job_id)
        assert job.status == "retrying" and job.steps["examples"]["status"] == "failed"
        assert session.get(Task, ids[0]).status == TaskStatus.SUCCESS
        assert job.result["knowledge_count"] == 5
    monkeypatch.setattr(knowledge_sync, "_render_demo_entries", successful_renderer)
    asyncio.run(learning_service.process_learning_job(job_id))
    with Session(db) as session:
        assert session.get(LearningJob, job_id).status == "completed"
        assert len(session.exec(select(Gene)).all()) == 1
    assert len(json.loads((settings.KNOWLEDGE_DB_DIR / "knowledge.json").read_text(encoding="utf-8"))) == 5


def test_interrupted_learning_is_recovered_on_startup(lifecycle, monkeypatch):
    db, _, ids = lifecycle
    asyncio.run(queue_manager.TaskQueue()._execute_item(queue_manager.QueueItem(*ids)))
    with Session(db) as session:
        job = session.exec(select(LearningJob)).one()
        job.status = "running"
        session.add(job); session.commit()

    async def idle():
        await asyncio.Event().wait()

    monkeypatch.setattr(learning_service, "_worker_loop", idle)
    async def restart():
        learning_service.start_learning_worker()
        with Session(db) as session:
            assert session.exec(select(LearningJob)).one().status == "pending"
        await learning_service.stop_learning_worker()
    asyncio.run(restart())


def test_material_changes_cannot_silently_learn_from_another_reference(lifecycle):
    db, _, ids = lifecycle
    asyncio.run(queue_manager.TaskQueue()._execute_item(queue_manager.QueueItem(*ids)))
    with Session(db) as session:
        job = session.exec(select(LearningJob)).one()
        Path(job.inputs["reference"]["path"]).write_bytes(b"different video")
        job_id = job.id
    asyncio.run(learning_service.process_learning_job(job_id))
    with Session(db) as session:
        job = session.get(LearningJob, job_id)
        assert job.status == "retrying" and job.steps["gene"]["status"] == "failed"
        assert session.exec(select(Gene)).all() == []
        assert session.get(Task, ids[0]).status == TaskStatus.SUCCESS


def _add_sticker_observations(report):
    report['raw_shot_analyses'][0]['effect_events'] = [
        {'id': 'stars', 'type': 'tracked_doodle', 'subject': '狗头', 'start_offset': .1, 'end_offset': .8,
         'position': {'x': .4, 'y': .3}, 'motion_path': [{'progress': 0, 'x': .4}, {'progress': 1, 'x': .5}],
         'parameters': {'style': '晕眩星形'}, 'confidence': .95},
        {'id': 'arrow', 'type': 'tracked_doodle', 'start_offset': .2, 'end_offset': .6,
         'parameters': {'shape': 'cursor_arrow'}, 'confidence': .8},
    ]
    return report


def test_task_completion_automatically_learns_stickers_with_matching_examples(lifecycle):
    db, storage, ids = lifecycle
    asyncio.run(queue_manager.TaskQueue()._execute_item(queue_manager.QueueItem(*ids)))
    report_path = storage / 'users' / str(ids[2]) / 'projects' / str(ids[1]) / 'tasks' / str(ids[0]) / 'analysis/reference_report.json'
    report_path.write_text(json.dumps(_add_sticker_observations(json.loads(report_path.read_text(encoding='utf-8')))), encoding='utf-8')
    with Session(db) as session:
        job_id = session.exec(select(LearningJob)).one().id
    asyncio.run(learning_service.process_learning_job(job_id))
    with Session(db) as session:
        job = session.get(LearningJob, job_id)
        assert job.status == 'completed'
        assert job.result['knowledge_count'] == job.result['editing_examples'] == 7
    entries = json.loads((settings.KNOWLEDGE_DB_DIR / 'knowledge.json').read_text(encoding='utf-8'))
    stickers = [entry for entry in entries if entry['type'] == 'effect_type']
    assert len(stickers) == 2 and all('贴纸' in entry['tags'] for entry in stickers)
    assert all(entry['derivation']['source_user_id'] == ids[2] for entry in stickers)


def test_existing_gene_backfills_effects_idempotently_and_updates_evidence(lifecycle):
    db, _, ids = lifecycle
    asyncio.run(queue_manager.TaskQueue()._execute_item(queue_manager.QueueItem(*ids)))
    with Session(db) as session:
        job_id = session.exec(select(LearningJob)).one().id
    asyncio.run(learning_service.process_learning_job(job_id))
    store_path = settings.KNOWLEDGE_DB_DIR / 'knowledge.json'
    original = json.loads(store_path.read_text(encoding='utf-8'))
    with Session(db) as session:
        gene = session.exec(select(Gene)).one()
        gene_id, report_path = gene.id, Path(gene.report_path)
    report = _add_sticker_observations(json.loads(report_path.read_text(encoding='utf-8')))
    report_path.write_text(json.dumps(report), encoding='utf-8')
    result = asyncio.run(knowledge_sync.extract_gene_knowledge(gene_id, ids[2], render_demos=False))
    assert result['added'] == 2 and result['existing'] == 5
    second = asyncio.run(knowledge_sync.extract_gene_knowledge(gene_id, ids[2], render_demos=False))
    assert second['added'] == second['updated'] == 0 and second['existing'] == 7 and second['skipped']
    before_update = json.loads(store_path.read_text(encoding='utf-8'))
    assert [entry for entry in before_update if entry['type'] != 'effect_type'] == original
    report['raw_shot_analyses'][0]['effect_events'][0]['position']['x'] = .8
    report_path.write_text(json.dumps(report), encoding='utf-8')
    updated = asyncio.run(knowledge_sync.extract_gene_knowledge(gene_id, ids[2], render_demos=False))
    assert updated['added'] == 0 and updated['updated'] == 1 and updated['existing'] == 7
    final = json.loads(store_path.read_text(encoding='utf-8'))
    assert {entry['id'] for entry in final} == {entry['id'] for entry in before_update}
    stars = next(entry for entry in final if entry['structured_data'].get('effect_key') == 'sticker_stars')
    assert stars['structured_data']['position']['x'] == .8
    with pytest.raises(RuntimeError, match='does not belong'):
        asyncio.run(knowledge_sync.extract_gene_knowledge(gene_id, 999, render_demos=False))


def test_unsupported_effect_examples_remain_visible_as_pending_without_fake_success(lifecycle, monkeypatch):
    db, _, ids = lifecycle
    asyncio.run(queue_manager.TaskQueue()._execute_item(queue_manager.QueueItem(*ids)))
    with Session(db) as session:
        job_id = session.exec(select(LearningJob)).one().id
    monkeypatch.setattr(knowledge_sync, '_render_demo_entries', lambda entries: {
        'demos_available': len(entries), 'demo_failures': [], 'teaching_demos_rendered': len(entries) - 1,
        'teaching_demos_existing': 0, 'teaching_demo_failures': [],
        'teaching_demo_pending': [{'id': entries[0]['id'], 'reason': '尚无重建实现'}]})
    asyncio.run(learning_service.process_learning_job(job_id))
    with Session(db) as session:
        job = session.get(LearningJob, job_id)
        assert job.status == 'completed' and job.attempts == 1
        assert job.steps['examples']['status'] == 'partial'
        assert job.result['editing_examples'] == 4 and len(job.result['pending_examples']) == 1
        assert job.steps['insights']['status'] == 'done'
