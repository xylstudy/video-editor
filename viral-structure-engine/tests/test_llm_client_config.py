import asyncio

import httpx

from config import llm_client
from config.llm_client import LLMTools


def test_llm_client_accepts_base_or_full_chat_url():
    base = LLMTools(api_key="key", base_url="https://example.com/v1/", model="demo")
    full = LLMTools(
        api_key="key",
        base_url="https://example.com/v1/chat/completions",
        model="demo",
    )

    assert base.chat_url == "https://example.com/v1/chat/completions"
    assert full.chat_url == "https://example.com/v1/chat/completions"


def test_only_local_endpoints_may_run_without_api_key():
    local = LLMTools(api_key="", base_url="http://127.0.0.1:11434/v1", model="demo")
    remote = LLMTools(api_key="", base_url="https://example.com/v1", model="demo")

    assert local._can_call_without_key() is True
    assert remote._can_call_without_key() is False


def test_llm_usage_records_provider_tokens(monkeypatch):
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    }))
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", lambda **kwargs: original_client(transport=transport))
    client = LLMTools(api_key="test-key", base_url="https://example.com/v1", model="test-model")

    assert asyncio.run(client.chat("test")) == "ok"
    assert client.usage_snapshot() == {
        "requests": 1,
        "attempts": 1,
        "responses": 1,
        "mock_requests": 0,
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": 14,
        "retries": 0,
        "model": "test-model",
    }
