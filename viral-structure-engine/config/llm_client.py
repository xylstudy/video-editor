from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Some OpenAI-compatible providers reject response_format even though their
# endpoint shape is otherwise compatible. Remember that capability per
# process so every new Agent client does not repeat the same failing request.
_RESPONSE_FORMAT_UNSUPPORTED: set[str] = set()


class LLMEmptyResponseError(RuntimeError):
    """The provider returned a successful response without final content."""


class LLMTools:
    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model: str = "kimi-2.6",
    ):
        self.api_key = api_key or settings.MOONSHOT_API_KEY
        self.base_url = (base_url or settings.MOONSHOT_BASE_URL).rstrip("/")
        self.model = model
        self._usage = {
            "requests": 0,
            "attempts": 0,
            "responses": 0,
            "mock_requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self._usage_fields: set[str] = set()
        self.chat_url = (
            self.base_url
            if self.base_url.endswith("/chat/completions")
            else f"{self.base_url}/chat/completions"
        )

    def usage_snapshot(self) -> dict:
        """Return provider-reported token totals and actual request attempts."""
        result = dict(self._usage)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if key not in self._usage_fields:
                result[key] = None
        result["retries"] = max(0, result["attempts"] - result["requests"])
        result["model"] = self.model
        return result

    def _record_mock(self) -> None:
        self._usage["mock_requests"] += 1

    def _can_call_without_key(self) -> bool:
        return urlparse(self.chat_url).hostname in {"localhost", "127.0.0.1", "::1"}

    async def chat(
        self,
        prompt: str,
        system: str = "",
        response_format: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self.chat_messages(
            messages,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def chat_messages(
        self,
        messages: list[dict],
        response_format: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Send a multi-turn conversation to the configured chat endpoint."""
        if not self.api_key and not self._can_call_without_key():
            logger.warning("No API key configured, returning mock response")
            self._record_mock()
            return self._mock_response(json.dumps(messages, ensure_ascii=False))

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format == "json":
            body["response_format"] = {"type": "json_object"}

        return await self._post(body)

    async def chat_with_video(
        self,
        prompt: str,
        video_path: str,
        system: str = "",
        response_format: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """发送视频+音频到多模态模型（如 Qwen3-OMNI-Flash），模型可同时看画面和听声音"""
        if not self.api_key and not self._can_call_without_key():
            logger.warning("No API key configured, returning mock response")
            self._record_mock()
            return self._mock_response(prompt)

        p = Path(video_path)
        if not p.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        ext = p.suffix.lower()
        mime = f"video/{ext.lstrip('.')}" if ext != ".mp4" else "video/mp4"

        content_parts = [
            {"type": "text", "text": prompt},
            {
                "type": "video_url",
                "video_url": {"url": f"data:{mime};base64,{b64}"},
            },
        ]

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content_parts})

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format == "json":
            body["response_format"] = {"type": "json_object"}

        return await self._post(body)

    async def chat_with_images(
        self,
        prompt: str,
        image_paths: list[str],
        system: str = "",
        response_format: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        if not self.api_key and not self._can_call_without_key():
            logger.warning("No API key configured, returning mock response")
            self._record_mock()
            return self._mock_response(prompt)

        content_parts = [{"type": "text", "text": prompt}]
        for img_path in image_paths:
            p = Path(img_path)
            if not p.exists():
                logger.warning(f"Image not found: {img_path}")
                continue
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            ext = p.suffix.lower()
            mime = "image/png" if ext == ".png" else "image/jpeg"
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content_parts})

        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format == "json":
            body["response_format"] = {"type": "json_object"}

        return await self._post(body)

    async def _post(self, body: dict) -> str:
        self._usage["requests"] += 1
        if self.chat_url in _RESPONSE_FORMAT_UNSUPPORTED:
            body.pop("response_format", None)
        last_error: Exception | None = None
        max_attempts = 10
        for attempt in range(max_attempts):
            try:
                # Ignore stale process proxy variables. The web app stores an
                # explicit model endpoint, and routing it through an unrelated
                # localhost proxy makes both chatbot and workflow calls fail.
                async with httpx.AsyncClient(
                    timeout=settings.LLM_TIMEOUT,
                    trust_env=False,
                ) as client:
                    headers = {"Content-Type": "application/json"}
                    if self.api_key:
                        headers["Authorization"] = f"Bearer {self.api_key}"
                    self._usage["attempts"] += 1
                    resp = await client.post(self.chat_url, headers=headers, json=body)
                    if resp.status_code == 400 and "response_format" in body:
                        logger.warning("response_format not supported, retrying without it")
                        _RESPONSE_FORMAT_UNSUPPORTED.add(self.chat_url)
                        del body["response_format"]
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    self._usage["responses"] += 1
                    usage = data.get("usage") or {}
                    if not isinstance(usage, dict):
                        usage = {}
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        value = usage.get(key)
                        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                            self._usage[key] += value
                            self._usage_fields.add(key)
                    choice = data["choices"][0]
                    message = choice.get("message") or {}
                    content = message.get("content") or ""
                    finish_reason = choice.get("finish_reason", "unknown")
                    completion_details = usage.get("completion_tokens_details") or {}
                    reasoning_tokens = completion_details.get("reasoning_tokens", 0)
                    current_limit = int(body.get("max_tokens") or 4096)
                    # A non-empty answer can still be a truncated JSON object.
                    # Never pass it to an Agent when the provider explicitly
                    # reports a length stop; retry atomically with more room.
                    if finish_reason == "length":
                        if current_limit < 16384:
                            next_limit = min(16384, current_limit * 2)
                            logger.warning(
                                "LLM 正文因长度上限被截断，max_tokens %s -> %s 后重试",
                                current_limit,
                                next_limit,
                            )
                            body["max_tokens"] = next_limit
                            continue
                        raise LLMEmptyResponseError(
                            "模型输出在 max_tokens=16384 时仍被截断，拒绝下传不完整结果"
                        )
                    if content.strip():
                        return content
                    raise LLMEmptyResponseError(
                        "模型返回空正文"
                        f" (finish_reason={finish_reason}, "
                        f"reasoning_tokens={reasoning_tokens}, max_tokens={current_limit})"
                    )
            except LLMEmptyResponseError:
                raise
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429:
                    if attempt >= max_attempts - 1:
                        raise
                    retry_after = e.response.headers.get("Retry-After", "").strip()
                    try:
                        wait = max(1.0, min(300.0, float(retry_after)))
                    except ValueError:
                        # Exponential backoff sends fewer doomed requests and
                        # covers providers with minute-level cooldown windows.
                        wait = min(60.0, 5.0 * (2 ** attempt))
                    logger.warning(f"Rate limited (429), waiting {wait}s before retry")
                    await asyncio.sleep(wait)
                    continue
                logger.warning(f"LLM call attempt {attempt + 1} failed: {e}")
                if attempt >= 5:
                    raise
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                logger.warning(f"LLM call attempt {attempt + 1} failed (network): {e}")
                await asyncio.sleep(3)
                if attempt >= 5:
                    raise
            except Exception as e:
                last_error = e
                logger.warning(f"LLM call attempt {attempt + 1} failed: {e}")
                if attempt >= 5:
                    raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("LLM request exhausted retries without a response")

    def parse_json(self, text: str) -> dict:
        import re
        # 移除 BOM 和不可见控制字符（保留换行空格）
        text = text.strip()
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        # 修复 DeepSeek 偶发的编码问题
        text = text.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        # 查找并提取 JSON 对象（丢弃前后非 JSON 文本）
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            text = text[brace_start:brace_end + 1]
        # 尝试标准解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 尝试修复常见问题后重试
        text = re.sub(r",\s*}", "}", text)
        text = re.sub(r",\s*]", "]", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 最后手段：输出原始字节诊断
        raw = text.encode("utf-8")
        raise json.JSONDecodeError(
            f"JSON 解析失败，前200字符: {text[:200]} (hex: {raw[:100].hex()})",
            text, 0,
        )

    def _mock_response(self, prompt: str) -> str:
        return json.dumps({
            "note": "mock response — no LLM API configured",
            "message": "Set ZHIPU_API_KEY in .env file to use real LLM",
        })
