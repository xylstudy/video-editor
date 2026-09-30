import json

from config import settings
from config.analysis_cache import load_analysis, save_analysis
from prompts.material_prompts import build_video_analysis_prompt


def test_analysis_cache_is_content_addressed_and_removes_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "ENABLE_ANALYSIS_CACHE", True)
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"same-media-content")
    payload = {
        "description": "山路",
        "source_path": "E:/private/original.mp4",
        "nested": {"frame_path": "E:/private/frame.jpg", "score": 9},
    }

    saved = save_analysis(
        "material_video", media, payload,
        model="vision-demo", prompt_version="2.0.0",
    )
    loaded, digest = load_analysis(
        "material_video", media,
        model="vision-demo", prompt_version="2.0.0",
    )

    assert saved is not None and saved.is_file()
    assert len(digest) == 64
    assert loaded == {"description": "山路", "nested": {"score": 9}}
    assert "private" not in saved.read_text(encoding="utf-8")

    missed, _ = load_analysis(
        "material_video", media,
        model="vision-demo", prompt_version="3.0.0",
    )
    assert missed is None


def test_material_video_prompt_is_topic_independent():
    first = build_video_analysis_prompt("mat_1", "雪山旅行", 10, "0秒、5秒")
    second = build_video_analysis_prompt("mat_1", "城市夜景", 10, "0秒、5秒")

    assert first == second
    assert "不同任务复用" in first
