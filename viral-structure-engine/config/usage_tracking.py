"""Task-scoped usage events, shared with subprocesses without storing prompts or keys."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import inspect
import json
import logging
import os
from pathlib import Path
import time
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger(__name__)
_context = ContextVar("task_usage", default=None)
_tool_parent = ContextVar("task_tool_parent", default=None)


def current_context():
    active = _context.get()
    if active is not None:
        return active
    directory = os.getenv("VIDEOCLAW_USAGE_DIR")
    if not directory:
        return None
    try:
        prices = json.loads(os.getenv("VIDEOCLAW_MODEL_PRICES", "[]"))
    except ValueError:
        prices = []
    return {"directory": directory, "stage": os.getenv("VIDEOCLAW_USAGE_STAGE", "pipeline"),
            "prices": prices if isinstance(prices, list) else []}


def write_record(context, category, identifier, payload):
    if not context:
        return
    temporary = None
    try:
        directory = Path(context["directory"]) / category
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{identifier}.json"
        temporary = directory / f"{identifier}.{uuid4().hex}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(target)
    except (OSError, TypeError, ValueError):
        # Accounting failure must not turn a paid, successful model call into a retry.
        logger.warning("Could not persist a task usage record", exc_info=True)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


@contextmanager
def tracking_scope(directory, stage, prices=None, *, execution=False):
    previous = current_context()
    context = {"directory": str(directory), "stage": stage,
               "prices": prices if prices is not None else (previous or {}).get("prices", [])}
    token = _context.set(context)
    identifier, started = uuid4().hex, time.perf_counter()
    record = {"stage": stage, "execution": execution, "status": "running",
              "started_at": datetime.now(timezone.utc).isoformat()}
    write_record(context, "sessions", identifier, record)
    try:
        yield context
    except BaseException:
        record["status"] = "failed"
        raise
    else:
        record["status"] = "completed"
    finally:
        record.update(duration_seconds=round(time.perf_counter() - started, 4),
                      finished_at=datetime.now(timezone.utc).isoformat())
        write_record(context, "sessions", identifier, record)
        _context.reset(token)


def child_environment(stage):
    context = current_context()
    if not context:
        return {}
    return {"VIDEOCLAW_USAGE_DIR": context["directory"], "VIDEOCLAW_USAGE_STAGE": stage,
            "VIDEOCLAW_MODEL_PRICES": json.dumps(context["prices"], ensure_ascii=False)}


def price_for(model, endpoint, context):
    host = urlparse(endpoint).hostname or ""
    matches = [price for price in (context or {}).get("prices", [])
               if isinstance(price, dict) and price.get("model") == model and price.get("host") == host]
    if matches:
        signatures = {tuple(p.get(key) for key in ("input", "output", "cached_input", "currency")) for p in matches}
        return dict(matches[0]) if len(signatures) == 1 else None
    # Verified 2026-10-26. Peak rates are an explicit reference upper estimate,
    # not a promise about a customer's discounted/off-peak provider invoice.
    if host == "api.deepseek.com":
        if model in {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}:
            rates = (0.3, 1.2, 0.006)
        elif model == "deepseek-v4-pro":
            rates = (1.32, 3.96, 0.044)
        else:
            return None
        return {"input": rates[0], "output": rates[1], "cached_input": rates[2], "currency": "USD",
                "source": "official_peak_reference", "as_of": "2026-10-26",
                "source_url": "https://api-docs.deepseek.com/quick_start/pricing/"}
    return None


def normalize_usage(usage):
    usage = usage if isinstance(usage, dict) else {}
    def count(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    prompt = count(usage.get("prompt_tokens", usage.get("input_tokens")))
    completion = count(usage.get("completion_tokens", usage.get("output_tokens")))
    total = count(usage.get("total_tokens"))
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    details = details if isinstance(details, dict) else {}
    cached = count(usage.get("prompt_cache_hit_tokens", details.get("cached_tokens")))
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total,
            "cached_input_tokens": cached}


class ModelAttempt:
    def __init__(self, model, endpoint, request_id, attempt):
        self.context = current_context()
        self.id, self.started = uuid4().hex, time.perf_counter()
        self.data = {"kind": "model", "request_id": request_id, "attempt": attempt,
                     "model": model, "stage": (self.context or {}).get("stage", "pipeline"),
                     "status": "running", "started_at": datetime.now(timezone.utc).isoformat(),
                     "price": price_for(model, endpoint, self.context), "usage": normalize_usage({})}
        write_record(self.context, "events", self.id, self.data)

    def response(self, usage, http_status):
        self.data.update(usage=normalize_usage(usage), http_status=http_status,
                         status="completed" if 200 <= http_status < 300 else "failed")

    def finish(self):
        if self.data["status"] == "running":
            self.data["status"] = "failed"
        self.data["duration_seconds"] = round(time.perf_counter() - self.started, 4)
        self.data["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_record(self.context, "events", self.id, self.data)


@contextmanager
def _tool_span(name):
    context = current_context()
    if not context:
        yield
        return
    parent, span = _tool_parent.get(), {"children": 0}
    token = _tool_parent.set(span)
    started, status = time.perf_counter(), "completed"
    try:
        yield
    except BaseException:
        status = "failed"
        raise
    finally:
        _tool_parent.reset(token)
        if parent is not None:
            parent["children"] += 1
        # Count actual leaf operations, not both an Agent adapter and the same
        # underlying media call. Independent sibling calls are all counted.
        if not span["children"]:
            identifier = uuid4().hex
            write_record(context, "events", identifier, {
                "kind": "tool", "name": name, "stage": context["stage"], "status": status,
                "duration_seconds": round(time.perf_counter() - started, 4),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })


def tracked_tool(name):
    def decorate(function):
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def asynchronous(*args, **kwargs):
                with _tool_span(name):
                    return await function(*args, **kwargs)
            return asynchronous
        @wraps(function)
        def synchronous(*args, **kwargs):
            with _tool_span(name):
                return function(*args, **kwargs)
        return synchronous
    return decorate


def instrument_tools(cls):
    for name, function in list(vars(cls).items()):
        if not name.startswith("_") and inspect.isfunction(function):
            setattr(cls, name, tracked_tool(f"{cls.__name__}.{name}")(function))
    return cls
