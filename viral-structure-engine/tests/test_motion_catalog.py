import shutil
from uuid import uuid4

from config.motion_catalog import (
    ADVANCED_MOTION_COMPONENTS,
    ADVANCED_TRANSITIONS,
    build_motion_catalog_prompt,
)
from tools import remotion_renderer


def test_motion_catalog_exposes_stable_recipes():
    assert len(ADVANCED_MOTION_COMPONENTS) == 12
    assert {"beat_montage", "parallax_photo", "kinetic_warp"} <= set(ADVANCED_MOTION_COMPONENTS)
    assert {"zoom_through", "liquid_warp", "chromatic_aberration"} == set(ADVANCED_TRANSITIONS)


def test_motion_catalog_prompt_marks_components_as_builtin():
    prompt = build_motion_catalog_prompt()
    assert '"custom:beat_montage"' in prompt
    assert 'need_new_component=false' in prompt
    assert "source_material_ids" in prompt


def test_renderer_falls_back_only_for_image_only_custom_components_with_video():
    scheme = {
        "storyboard": [
            {"source_material_id": "video", "render_component": "custom:fade_out_glow"},
            {"source_material_id": "video", "render_component": "custom:beat_montage"},
            {
                "source_material_id": "video",
                "render_component": "custom:split_screen_burst",
                "custom_render_config": {"source_material_ids": ["video", "video_2"]},
            },
        ]
    }
    rendered = remotion_renderer._fallback_custom_video_components(
        scheme,
        [
            {"id": "video", "path": "clip.mp4"},
            {"id": "video_2", "path": "clip-2.mp4"},
        ],
    )

    assert rendered["storyboard"][0]["render_component"] == "auto"
    assert rendered["storyboard"][0]["render_fallback"]["from"] == "custom:fade_out_glow"
    assert rendered["storyboard"][1]["render_component"] == "custom:beat_montage"
    assert rendered["storyboard"][2]["render_component"] == "custom:split_screen_burst"
    assert scheme["storyboard"][0]["render_component"] == "custom:fade_out_glow"


def test_remotion_renderer_uses_project_local_temp(monkeypatch):
    test_root = remotion_renderer.REMOTION_DIR / ".test-tmp" / f"motion-{uuid4().hex}"
    test_root.mkdir(parents=True)
    material = test_root / "material.jpg"
    material.write_bytes(b"test")
    output = test_root / "out.mp4"
    captured = {}

    class Result:
        returncode = 0
        stderr = b""

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs["env"]
        output.write_bytes(b"rendered")
        return Result()

    monkeypatch.setattr(remotion_renderer.subprocess, "run", fake_run)
    try:
        result = remotion_renderer.render_with_remotion(
            {
                "storyboard": [
                    {"index": 0, "duration": 1, "source_material_id": "photo"}
                ]
            },
            [{"id": "photo", "path": str(material)}],
            str(output),
        )

        expected_parent = str(remotion_renderer.REMOTION_DIR / ".render-tmp")
        assert result == str(output)
        assert captured["env"]["TEMP"].startswith(expected_parent)
        assert captured["env"]["TMP"] == captured["env"]["TEMP"]
        assert not remotion_renderer.Path(captured["env"]["TEMP"]).exists()
    finally:
        shutil.rmtree(test_root, ignore_errors=True)
