import json
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import database
import model_runtime
from config.usage_tracking import ModelAttempt, tracked_tool, tracking_scope
from db_models import ModelConfigurationCreate, ModelConfigurationUpdate, Project, Task, TaskType, User
from routers import models, tasks
from task_usage import read_task_usage


def test_cache_pricing_multiple_currencies_and_missing_prices_are_explicit(tmp_path):
    prices = [{"host": "example.test", "model": "priced", "input": 2, "output": 6,
               "cached_input": .5, "currency": "CNY", "source": "configured"}]
    with tracking_scope(tmp_path / 'metrics', 'analysis', prices):
        a = ModelAttempt('priced', 'https://example.test/v1', 'request-1', 1)
        a.response({'prompt_tokens': 1000000, 'completion_tokens': 100000,
                    'prompt_cache_hit_tokens': 400000}, 200)
        a.finish()
        b = ModelAttempt('unknown', 'https://example.test/v1', 'request-2', 1)
        b.response({'prompt_tokens': 20, 'completion_tokens': 10}, 200)
        b.finish()
        c = ModelAttempt('deepseek-flash', 'https://api.deepseek.com/v1', 'request-3', 1)
        c.response({'prompt_tokens': 1000000, 'completion_tokens': 0, 'prompt_cache_hit_tokens': 0}, 200)
        c.finish()
    report = read_task_usage(tmp_path)
    assert report['tokens']['total_tokens'] == 2100030
    assert report['model_calls'] == 3 and report['tool_calls'] == 0
    assert report['cost_status'] == 'partial' and report['unpriced_calls'] == 1
    costs = {c['currency']: c for c in report['costs']}
    assert costs['CNY']['amount'] == pytest.approx(2)
    assert costs['USD']['amount'] == pytest.approx(.3)
    assert 'official_peak_reference' in costs['USD']['basis']
    assert len(report['stages']) == 1 and len(report['models']) == 3


def test_historical_usage_does_not_invent_cost_or_tool_counts(tmp_path):
    legacy = tmp_path / 'evaluation.json'
    legacy.write_text(json.dumps({'llm_usage': {'total_tokens': 123, 'attempts': 4}}))
    report = read_task_usage(tmp_path / 'task', legacy)
    assert report['source'] == 'legacy' and report['tokens']['total_tokens'] == 123
    assert report['tool_calls'] is None and report['costs'] == []
    assert report['cost_status'] == 'unavailable'


def test_price_snapshot_and_prepare_render_learning_all_remain_in_one_task(tmp_path):
    price = {'host': 'example.test', 'model': 'm', 'input': 1, 'output': 1, 'currency': 'CNY', 'source': 'configured'}
    for stage in ('material_analysis', 'storyboard_render', 'asset_learning'):
        with tracking_scope(tmp_path / 'metrics', stage, [price]):
            event = ModelAttempt('m', 'https://example.test', stage, 1)
            event.response({'prompt_tokens': 100, 'completion_tokens': 20}, 200)
            event.finish()
            tracked_tool('tool.' + stage)(lambda: None)()
    price['input'] = 1000000
    report = read_task_usage(tmp_path)
    assert report['model_calls'] == 3 and report['tool_calls'] == 3
    assert report['costs'][0]['amount'] == pytest.approx(.00036)
    assert len(report['stages']) == 3


def session_with_users():
    db = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(db)
    session = Session(db)
    alice, bob = User(username='usage-alice', hashed_password='x'), User(username='usage-bob', hashed_password='x')
    session.add_all([alice, bob]); session.commit(); session.refresh(alice); session.refresh(bob)
    return db, session, alice, bob


def test_usage_endpoint_enforces_ownership_and_returns_no_internal_paths(tmp_path, monkeypatch):
    db, session, alice, bob = session_with_users()
    project = Project(user_id=alice.id, name='usage project')
    session.add(project); session.commit(); session.refresh(project)
    task = Task(project_id=project.id, type=TaskType.ANALYZE_VIDEO)
    session.add(task); session.commit(); session.refresh(task)
    monkeypatch.setattr(tasks, 'STORAGE_ROOT', tmp_path)
    monkeypatch.setattr(tasks, 'VSE_DIR', tmp_path / 'engine')
    with pytest.raises(HTTPException) as error:
        tasks.task_usage(task.id, bob, session)
    assert error.value.status_code == 404
    report = tasks.task_usage(task.id, alice, session)
    assert report['source'] == 'not_recorded'
    assert str(tmp_path) not in json.dumps(report)
    session.close(); db.dispose()


def test_model_rates_roundtrip_and_user_environment_excludes_other_users(monkeypatch):
    db, session, alice, bob = session_with_users()
    monkeypatch.setattr(model_runtime, 'engine', db)
    config = models.create_model(ModelConfigurationCreate(display_name='priced model', model_id='m',
        endpoint_url='https://example.test/v1', input_price_per_million=2, output_price_per_million=6,
        price_currency='CNY'), alice, session)
    assert config.input_price_per_million == 2
    env = model_runtime.get_user_model_env(alice.id)
    assert json.loads(env['VIDEOCLAW_MODEL_PRICES'])[0]['output'] == 6
    assert json.loads(model_runtime.get_user_model_env(bob.id)['VIDEOCLAW_MODEL_PRICES']) == []
    with pytest.raises(HTTPException):
        models.update_model(config.id, ModelConfigurationUpdate(input_price_per_million=None), alice, session)
    session.close(); db.dispose()


def test_price_migration_preserves_existing_config_and_is_repeatable(monkeypatch):
    db = create_engine('sqlite://', poolclass=StaticPool)
    with db.begin() as conn:
        conn.execute(text('CREATE TABLE modelconfiguration (id INTEGER PRIMARY KEY, model_id VARCHAR)'))
        conn.execute(text("INSERT INTO modelconfiguration VALUES (1, 'old-model')"))
    monkeypatch.setattr(database, 'engine', db)
    database._migrate_model_price_columns()
    database._migrate_model_price_columns()
    with db.connect() as conn:
        assert conn.execute(text('SELECT model_id, price_currency, input_price_per_million FROM modelconfiguration')).one() == ('old-model', 'CNY', None)


@pytest.mark.asyncio
async def test_worker_subprocess_records_usage_in_the_same_task(tmp_path):
    from pipeline_runner import VSE_DIR, run_command
    script = (
        "from config.usage_tracking import ModelAttempt; "
        "a=ModelAttempt('test-model','https://example.test','child-request',1); "
        "a.response({'prompt_tokens':2,'completion_tokens':3},200); a.finish()"
    )
    with tracking_scope(tmp_path / 'metrics', 'workflow_prepare'):
        await run_command([sys.executable, '-c', script], VSE_DIR, lambda *args: None,
                          'video_analysis', 0, 10)
    result = read_task_usage(tmp_path)
    assert result['model_calls'] == 1 and result['tokens']['total_tokens'] == 5
    assert result['stages'][0]['stage'] == 'video_analysis'
