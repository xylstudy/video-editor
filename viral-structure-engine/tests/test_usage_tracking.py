import asyncio
import json

import httpx
import pytest

from config.llm_client import LLMTools
from config.usage_tracking import child_environment, instrument_tools, tracked_tool, tracking_scope


def events(root):
    return [json.loads(p.read_text(encoding="utf-8")) for p in (root / "events").glob("*.json")]


def mock_provider(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))


@pytest.mark.asyncio
async def test_paid_truncated_response_and_format_retry_are_all_recorded(tmp_path, monkeypatch):
    replies = [
        httpx.Response(400, json={"error": "unsupported format"}),
        httpx.Response(200, json={"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                                 "choices": [{"finish_reason": "length", "message": {"content": "{"}}]}),
        httpx.Response(200, json={"usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150,
                                           "prompt_cache_hit_tokens": 40},
                                 "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}),
    ]
    mock_provider(monkeypatch, lambda request: replies.pop(0))
    price = {"host": "metrics.example.test", "model": "test-model", "input": 2, "output": 6,
             "cached_input": .5, "currency": "CNY", "source": "configured"}
    with tracking_scope(tmp_path, "planning", [price]):
        llm = LLMTools(api_key="must-not-be-persisted", base_url="https://metrics.example.test/v1", model="test-model")
        assert await llm.chat("private prompt", response_format="json") == "{}"
    recorded = events(tmp_path)
    assert len(recorded) == 3
    assert len({e["request_id"] for e in recorded}) == 1
    assert sum((e['usage']['total_tokens'] or 0) for e in recorded) == 270
    assert all(e['price']['input'] == 2 for e in recorded)
    saved = "\n".join(p.read_text(encoding='utf-8') for p in tmp_path.rglob('*.json'))
    assert 'must-not-be-persisted' not in saved and 'private prompt' not in saved


@pytest.mark.asyncio
async def test_parallel_task_contexts_do_not_mix_and_missing_usage_stays_unknown(tmp_path, monkeypatch):
    mock_provider(monkeypatch, lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}))
    async def call(name):
        with tracking_scope(tmp_path / name, name):
            await asyncio.sleep(0)
            env = child_environment("video_analysis")
            assert env['VIDEOCLAW_USAGE_DIR'] == str(tmp_path / name)
            await LLMTools(api_key="secret", base_url="https://example.test", model=name).chat("x")
    await asyncio.gather(call('task-a'), call('task-b'))
    for name in ('task-a', 'task-b'):
        recorded = events(tmp_path / name)
        assert len(recorded) == 1 and recorded[0]['model'] == name
        assert recorded[0]['usage']['total_tokens'] is None
        assert recorded[0]['price'] is None


@pytest.mark.asyncio
async def test_tool_adapters_and_nested_media_calls_are_not_double_counted(tmp_path):
    @instrument_tools
    class Media:
        def frame(self):
            return "frame"

        def frames(self):
            return [self.frame(), self.frame()]

    @tracked_tool('agent.extract_frames')
    async def adapter():
        return await asyncio.to_thread(Media().frames)

    with tracking_scope(tmp_path, 'analysis'):
        assert len(await adapter()) == 2
    recorded = events(tmp_path)
    assert len(recorded) == 2
    assert all(e['name'] == 'Media.frame' for e in recorded)


def test_failed_tool_is_recorded_without_arguments(tmp_path):
    @tracked_tool('failing')
    def fail(secret):
        raise ValueError(secret)
    with tracking_scope(tmp_path, 'render'):
        with pytest.raises(ValueError):
            fail('private-secret')
    assert events(tmp_path)[0]['status'] == 'failed'
    assert 'private-secret' not in json.dumps(events(tmp_path))
