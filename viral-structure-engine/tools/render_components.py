"""Deterministic component resolution shared by graph and direct rendering."""

from __future__ import annotations

from typing import Any


STABLE_CUSTOM_COMPONENTS = {
    "focus_blur_resolve",
    "kinetic_warp",
    "mask_reveal_up",
    "rgb_glitch_text",
    "broll_stack",
    "split_screen_burst",
    "parallax_photo",
    "polaroid_collage",
    "beat_montage",
    "hero_push_in",
    "cinematic_grain",
    "neon_light_rays",
}


def resolve_render_component(
    component: str,
    config: dict[str, Any] | None,
    *,
    dynamic_enabled: bool,
) -> tuple[str, bool]:
    """Return a stable component and whether an unknown custom value fell back."""
    value = str(component or "auto")
    if dynamic_enabled or not value.startswith("custom:"):
        return value, False
    name = value.removeprefix("custom:")
    if name in STABLE_CUSTOM_COMPONENTS:
        return value, False

    config = config if isinstance(config, dict) else {}
    source_ids = config.get("source_material_ids", config.get("material_ids", []))
    if isinstance(source_ids, list) and len([item for item in source_ids if item]) >= 2:
        return "custom:beat_montage", True
    return "auto", True
