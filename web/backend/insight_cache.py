"""Persist user-scoped insights when learning finishes, with freshness checks."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from app_config import STORAGE_ROOT


def fingerprint(user_id: int) -> str:
    root = STORAGE_ROOT / "users" / str(user_id) / "genes"
    rows = [(str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file() and (p.name == "report.json" or p.suffix == ".mp4")]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def read_cached_insights(user_id: int) -> dict | None:
    path = STORAGE_ROOT / "users" / str(user_id) / "insights" / "snapshot.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("fingerprint") == fingerprint(user_id):
            return cached["payload"]
    except (OSError, ValueError, KeyError):
        pass
    return None


def refresh_user_insights(user_id: int) -> dict:
    from routers.insights import _run_mining, _response_payload
    from insight_report import generate_report

    before = fingerprint(user_id)
    mined, videos = _run_mining(user_id)
    if not mined or not videos:
        raise RuntimeError("没有可用于统计洞察的有效基因分析报告")
    payload = _response_payload(mined, videos)
    directory = STORAGE_ROOT / "users" / str(user_id) / "insights"
    directory.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    temporary = directory / f"snapshot-{token}.tmp"
    temporary_report = directory / f"report-{token}.html"
    try:
        generate_report(mined, videos, temporary_report)
        if fingerprint(user_id) != before:
            raise RuntimeError("生成洞察时基因库已更新，将自动重试")
        temporary.write_text(json.dumps({"fingerprint": before, "payload": payload}, ensure_ascii=False), encoding="utf-8")
        temporary_report.replace(directory / "report.html")
        temporary.replace(directory / "snapshot.json")
    finally:
        temporary.unlink(missing_ok=True)
        temporary_report.unlink(missing_ok=True)
    return {"sample_size": payload["sample_size"], "insight_count": len(payload["insights"]), "generated_at": payload["generated_at"]}
