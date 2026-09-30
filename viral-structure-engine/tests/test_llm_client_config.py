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


def test_rate_limit_honors_retry_after(monkeypatch):
    calls = 0
    waits = []

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "17"}, request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}, request=request)

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", lambda **kwargs: original_client(transport=transport))

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(llm_client.asyncio, "sleep", fake_sleep)
    client = LLMTools(api_key="test-key", base_url="https://rate-limit.example/v1", model="test-model")

    assert asyncio.run(client.chat("test")) == "ok"
    assert waits == [17.0]
    assert client.usage_snapshot()["attempts"] == 2


def test_response_format_rejection_is_cached_for_endpoint(monkeypatch):
    requests = []

    def handler(request):
        payload = __import__("json").loads(request.content)
        requests.append(payload)
        if "response_format" in payload:
            return httpx.Response(400, json={"error": "unsupported"}, request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]}, request=request)

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", lambda **kwargs: original_client(transport=transport))
    endpoint = "https://format-cache.example/v1"

    first = LLMTools(api_key="test-key", base_url=endpoint, model="test-model")
    second = LLMTools(api_key="test-key", base_url=endpoint, model="test-model")
    assert asyncio.run(first.chat("test", response_format="json")) == "{}"
    assert asyncio.run(second.chat("test", response_format="json")) == "{}"

    assert len(requests) == 3
    assert "response_format" in requests[0]
    assert "response_format" not in requests[1]
    assert "response_format" not in requests[2]


def test_nonempty_length_truncated_response_is_retried(monkeypatch):
    requests = []

    def handler(request):
        payload = __import__("json").loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(200, json={
                "choices": [{
                    "message": {"content": '{"partial":'},
                    "finish_reason": "length",
                }],
            }, request=request)
        return httpx.Response(200, json={
            "choices": [{
                "message": {"content": '{"complete": true}'},
                "finish_reason": "stop",
            }],
        }, request=request)

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", lambda **kwargs: original_client(transport=transport))
    client = LLMTools(api_key="test-key", base_url="https://truncated.example/v1", model="test-model")

    assert asyncio.run(client.chat("test", max_tokens=4096)) == '{"complete": true}'
    assert [request["max_tokens"] for request in requests] == [4096, 8192]
    assert client.usage_snapshot()["attempts"] == 2
