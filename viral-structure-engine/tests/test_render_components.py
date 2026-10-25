from tools.render_components import resolve_render_component


def test_stable_custom_component_is_kept_when_dynamic_generation_is_disabled():
    value, fallback = resolve_render_component(
        "custom:beat_montage", {"source_material_ids": ["a", "b"]}, dynamic_enabled=False,
    )
    assert value == "custom:beat_montage"
    assert fallback is False


def test_unknown_multi_source_component_falls_back_to_stable_montage():
    value, fallback = resolve_render_component(
        "custom:hero_montage", {"source_material_ids": ["a", "b"]}, dynamic_enabled=False,
    )
    assert value == "custom:beat_montage"
    assert fallback is True


def test_unknown_single_source_component_falls_back_to_auto():
    value, fallback = resolve_render_component(
        "custom:invented", {"source_material_ids": ["a"]}, dynamic_enabled=False,
    )
    assert value == "auto"
    assert fallback is True
