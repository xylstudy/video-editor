"""Content-addressed cache for expensive media understanding results."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from config import settings


SCHEMA_VERSION = "1.0"
_PATH_KEYS = {"path", "source_path", "video_path", "extracted_path", "frame_path"}


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)[:80]


def _cache_path(kind: str, media_sha256: str, model: str, prompt_version: str) -> Path:
    identity = json.dumps(
        {"model": model, "prompt_version": prompt_version},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    variant = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return (
        settings.DATA_DIR
        / "cache"
        / "media_analysis"
        / _safe_component(kind)
        / media_sha256[:2]
        / f"{media_sha256}_{variant}.json"
    )


def _without_paths(value: Any) -> Any:
    """Remove filesystem locations while retaining reusable semantic facts."""
    if isinstance(value, dict):
        return {
            key: _without_paths(item)
            for key, item in value.items()
            if key not in _PATH_KEYS and not key.endswith("_path")
        }
    if isinstance(value, list):
        return [_without_paths(item) for item in value]
    return value


def load_analysis(
    kind: str,
    media_path: str | Path,
    *,
    model: str,
    prompt_version: str,
) -> tuple[dict[str, Any] | None, str]:
    media_sha256 = file_sha256(media_path)
    if not settings.ENABLE_ANALYSIS_CACHE:
        return None, media_sha256
    path = _cache_path(kind, media_sha256, model, prompt_version)
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None, media_sha256
    if not isinstance(envelope, dict) or envelope.get("schema_version") != SCHEMA_VERSION:
        return None, media_sha256
    payload = envelope.get("payload")
    return (payload if isinstance(payload, dict) else None), media_sha256


def save_analysis(
    kind: str,
    media_path: str | Path,
    payload: dict[str, Any],
    *,
    model: str,
    prompt_version: str,
    media_sha256: str = "",
) -> Path | None:
    if not settings.ENABLE_ANALYSIS_CACHE:
        return None
    digest = media_sha256 or file_sha256(media_path)
    path = _cache_path(kind, digest, model, prompt_version)
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "media_sha256": digest,
        "model": model,
        "prompt_version": prompt_version,
        "payload": _without_paths(payload),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path
