"""Read durable task usage events. Never infer historical charges from today's rates."""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

import vse  # noqa: F401
from app_config import STORAGE_ROOT
from config.usage_tracking import tracking_scope


def task_usage_scope(task_id, project_id, user_id, stage):
    from model_runtime import get_user_model_env
    try:
        env = get_user_model_env(user_id)
        prices = json.loads(env.get("VIDEOCLAW_MODEL_PRICES", "[]"))
    except Exception:
        prices = []
    root = STORAGE_ROOT / "users" / str(user_id) / "projects" / str(project_id) / "tasks" / str(task_id)
    return tracking_scope(root / "metrics", stage, prices, execution=True)


def _records(directory):
    for path in directory.glob("*.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(item, dict):
                yield item
        except (OSError, ValueError):
            continue


def _cost(event):
    usage, price = event.get("usage") or {}, event.get("price")
    if not price or any(usage.get(k) is None for k in ("prompt_tokens", "completion_tokens")):
        return None
    try:
        incoming, outgoing = int(usage["prompt_tokens"]), int(usage["completion_tokens"])
        cached = usage.get("cached_input_tokens") or 0
        cached = max(0, min(incoming, int(cached)))
        normal = Decimal(str(price["input"]))
        cached_rate = Decimal(str(price.get("cached_input") if price.get("cached_input") is not None else price["input"]))
        output = Decimal(str(price["output"]))
        amount = (Decimal(incoming - cached) * normal + Decimal(cached) * cached_rate + Decimal(outgoing) * output) / Decimal(1_000_000)
        if not amount.is_finite() or amount < 0 or price.get("currency") not in {"CNY", "USD"}:
            return None
        return price["currency"], amount
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None


def _summarize(events):
    models = [e for e in events if e.get("kind") == "model"]
    tools = [e for e in events if e.get("kind") == "tool"]
    tokens = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_input_tokens"):
        values = [(e.get("usage") or {}).get(key) for e in models]
        known = [v for v in values if isinstance(v, int) and not isinstance(v, bool) and v >= 0]
        tokens[key] = sum(known) if known or not models else None
    reported = sum((e.get("usage") or {}).get("total_tokens") is not None for e in models)
    priced, costs, bases = 0, defaultdict(Decimal), defaultdict(set)
    for event in models:
        cost = _cost(event)
        if cost:
            currency, amount = cost
            costs[currency] += amount
            bases[currency].add((event.get("price") or {}).get("source", "configured"))
            if (event.get("usage") or {}).get("cached_input_tokens") is None and (event.get("price") or {}).get("cached_input") is not None:
                bases[currency].add("cache_breakdown_unknown")
            priced += 1
    return {
        "model_calls": len(models), "model_requests": len({e.get("request_id") for e in models}),
        "retries": len(models) - len({e.get("request_id") for e in models}),
        "failed_model_calls": sum(e.get("status") == "failed" for e in models),
        "active_model_calls": sum(e.get("status") == "running" for e in models),
        "mock_calls": sum(e.get("kind") == "mock" for e in events),
        "tool_calls": len(tools), "failed_tool_calls": sum(e.get("status") == "failed" for e in tools),
        "tokens": tokens, "usage_reported_calls": reported, "unreported_usage_calls": len(models) - reported,
        "priced_calls": priced, "unpriced_calls": len(models) - priced,
        "cost_status": "not_used" if not models else "complete" if priced == len(models) else "partial" if priced else "unpriced",
        "costs": [{"currency": currency, "amount": float(amount), "basis": sorted(bases[currency])}
                  for currency, amount in sorted(costs.items())],
    }


def read_task_usage(root: Path, evaluation_path: Path | None = None):
    directory = root / "metrics"
    events, sessions = list(_records(directory / "events")), list(_records(directory / "sessions"))
    if not events and not sessions:
        usage = {}
        if evaluation_path:
            try:
                report = json.loads(evaluation_path.read_text(encoding="utf-8"))
                usage = report.get("llm_usage") or {}
            except (OSError, ValueError):
                pass
        return {"source": "legacy" if usage else "not_recorded", "model_calls": usage.get("attempts"),
                "tool_calls": None, "tokens": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
                "cost_status": "unavailable", "costs": [], "stages": [], "models": [], "tools": [],
                "notice": "历史任务未记录完整用量事件；保留已有 Token 汇总，费用和工具次数无法准确追溯。"}
    result = _summarize(events)
    grouped = defaultdict(list)
    by_model = defaultdict(list)
    for event in events:
        grouped[event.get("stage", "pipeline")].append(event)
        if event.get("kind") == "model":
            by_model[event.get("model", "unknown")].append(event)
    tools = Counter(e.get("name", "unknown") for e in events if e.get("kind") == "tool")
    result.update(source="events", stages=[{"stage": key, **_summarize(values)} for key, values in sorted(grouped.items())],
                  models=[{"model": key, **_summarize(values)} for key, values in sorted(by_model.items())],
                  tools=[{"name": key, "calls": value} for key, value in tools.most_common()],
                  active_runtime_seconds=round(sum(s.get("duration_seconds", 0) for s in sessions if s.get("execution")), 3),
                  notice="Token 来自接口返回；费用为模型调用估算，不含本机渲染、电费及其他外部服务收费。工具按实际执行的叶子操作计数。")
    return result
