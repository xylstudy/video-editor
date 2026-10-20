import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.gene import build_gene
from models.scheme import VideoScheme
from agents.analyst import AnalystAgent
from agents.planner import PlannerAgent
from run_pipeline_e2e import (
    apply_reference_effect_contract,
    build_local_fallback_scheme,
    infer_source_aspect_ratio,
    load_local_reference_profile,
)
from tools.render_components import resolve_render_component


def _frame(index: int) -> dict:
    return {
        "index": index,
        "duration": 1.0,
        "transition_in": "cut",
        "render_component": "auto",
        "custom_render_config": {},
    }


def test_gene_preserves_explicit_reference_timing_and_packaging():
    gene = build_gene(
        shot_analyses=[],
        structure_analysis={
            "packaging_analysis": {
                "title_cards": [{"type": "search_cta_card"}],
                "stickers_effects": "floating player",
            }
        },
        duration=17.467,
        reference_cut_points=[3.033, 6.9, 14.533],
        source_aspect_ratio="3:4",
        effect_tracks=[{"start": 0, "end": 4.067, "type": "floating_music_ui", "priority": "critical"}],
    )

    payload = gene.to_dict()
    assert payload["reference_cut_points"] == [3.033, 6.9, 14.533]
    assert payload["source_aspect_ratio"] == "3:4"
    assert payload["packaging_signature"]["title_cards"][0]["type"] == "search_cta_card"
    assert payload["effect_tracks"][0]["type"] == "floating_music_ui"


def test_reference_contract_maps_timing_canvas_and_signature_effects():
    scheme = {
        "target_duration": 10.0,
        "storyboard": [_frame(index) for index in range(4)],
    }
    gene = {
        "duration": 10.0,
        "source_aspect_ratio": "3:4",
        "reference_cut_points": [2.0, 5.0, 8.0],
        "effect_tracks": [
            {"start": 0, "end": 2, "type": "floating_music_ui", "priority": "critical"},
            {"start": 5, "end": 5.2, "type": "slice_wipe", "priority": "critical"},
            {"start": 8, "end": 10, "type": "search_cta_card", "priority": "critical", "parameters": {"query": "城市漫游"}},
        ],
    }

    result = apply_reference_effect_contract(scheme, gene)

    assert [frame["duration"] for frame in result["storyboard"]] == [2.0, 3.0, 3.0, 2.0]
    assert result["canvas_width"] == 1080
    assert result["canvas_height"] == 1440
    assert all(frame["canvas_height"] == 1440 for frame in result["storyboard"])
    assert result["storyboard"][2]["transition_in"] == "slice_wipe"
    assert result["storyboard"][3]["render_component"] == "custom:search_cta_card"
    assert result["storyboard"][3]["custom_render_config"]["query"] == "城市漫游"
    assert [track["type"] for track in result["effect_tracks"]] == [
        "floating_music_ui",
        "slice_wipe",
        "search_cta_card",
    ]


def test_known_reference_profile_and_components_are_available():
    profile = load_local_reference_profile({"source_path": "C:/tmp/8f2daa39f11c8136b5668566facd25d8.mp4"})
    assert profile["source_aspect_ratio"] == "3:4"
    assert len(profile["reference_cut_points"]) == 11
    assert {item["type"] for item in profile["effect_tracks"]} >= {
        "floating_music_ui",
        "glitch_reveal",
        "slice_wipe",
        "black_dip",
        "search_cta_card",
    }

    for component in ("custom:floating_music_ui", "custom:search_cta_card"):
        resolved, fallback = resolve_render_component(component, {}, dynamic_enabled=False)
        assert resolved == component
        assert fallback is False


def test_video_scheme_serializes_effect_tracks():
    scheme = VideoScheme(effect_tracks=[{"type": "black_dip", "start": 1, "end": 1.2}])
    assert scheme.to_dict()["effect_tracks"][0]["type"] == "black_dip"


def test_analyst_keeps_observed_shot_times_without_vlm_reanalysis():
    analyst = object.__new__(AnalystAgent)
    structure = analyst.build_video_structure(
        video_path="C:/tmp/unprofiled-reference.mp4",
        duration=5.5,
        width=720,
        height=960,
        shot_analyses=[
            {
                "start_time": 1.25,
                "end_time": 3.75,
                "structure_role": {"primary_function": "hook"},
                "content": {},
                "technique": {},
                "audio": {},
            }
        ],
        structure_analysis={},
    )

    assert structure.shots[0].start_time == 1.25
    assert structure.shots[0].end_time == 3.75
    assert structure.shots[0].duration == 2.5
    assert structure.aspect_ratio == "3:4"


def test_planner_model_keeps_renderable_packaging_fields():
    planner = object.__new__(PlannerAgent)
    scheme = planner.build_scheme(
        {
            "title": "effect transfer",
            "target_duration": 2,
            "storyboard": [{"index": 0, "duration": 2, "shot_type": "hook"}],
            "packaging": {
                "color_grade": "film_retro",
                "title_cards": [{"type": "search_cta_card"}],
                "transitions_used": [{"type": "slice_wipe"}],
                "stickers_effects": "floating player",
                "subtitle_style": {"position": "center", "animation": "fade_in"},
            },
            "effect_tracks": [{"type": "floating_music_ui", "start": 0, "end": 2}],
        },
        target_topic="city",
    )

    payload = scheme.to_dict()
    assert payload["packaging"]["color_grade"] == "film_retro"
    assert payload["packaging"]["title_cards"][0]["type"] == "search_cta_card"
    assert payload["packaging"]["transitions_used"][0]["type"] == "slice_wipe"
    assert payload["packaging"]["subtitle_style"]["position"] == "center"
    assert payload["effect_tracks"][0]["type"] == "floating_music_ui"


def test_local_fallback_builds_reference_shot_count_from_real_materials():
    scheme = build_local_fallback_scheme(
        target_topic="city trip",
        target_duration=10,
        inventory={"items": [
            {"id": "a", "description": "street"},
            {"id": "b", "description": "airport"},
            {"id": "c", "description": "station"},
            {"id": "d", "description": "park"},
        ]},
        gene={
            "duration": 10,
            "source_id": "ref",
            "reference_cut_points": [2, 5, 8],
            "shot_genes": [{"function": "hook"}, {"function": "climax"}, {"function": "closing"}],
            "effect_tracks": [{"type": "black_dip", "start": 5, "end": 5.2}],
            "packaging_signature": {"color_grade": "film_retro"},
        },
    )

    assert len(scheme["storyboard"]) == 4
    assert [frame["duration"] for frame in scheme["storyboard"]] == [2.0, 3.0, 3.0, 2.0]
    assert len({frame["source_material_id"] for frame in scheme["storyboard"]}) == 4
    assert scheme["render_hints"]["planner_fallback"] is True
    assert scheme["packaging"]["color_grade"] == "film_retro"


def test_infers_source_aspect_ratio_from_resolution():
    assert infer_source_aspect_ratio({"resolution": [720, 960]}) == "3:4"
    assert infer_source_aspect_ratio({"resolution": [1920, 1080]}) == "16:9"
    assert infer_source_aspect_ratio({"aspect_ratio": "1:1", "resolution": [720, 960]}) == "1:1"


def test_fallback_maps_observed_packaging_effects_to_renderable_components():
    descriptions = [
        "红苹果水珠特写", "切苹果", "果汁倒入玻璃杯", "城市自行车", "红色跑车", "夜间游乐场光轨"
    ]
    scheme = build_local_fallback_scheme(
        target_topic="red apple city",
        target_duration=24,
        inventory={"items": [
            {"id": f"m{i}", "description": descriptions[i % len(descriptions)]}
            for i in range(24)
        ]},
        gene={
            "duration": 24,
            "reference_cut_points": list(range(1, 24)),
            "shot_genes": [
                {"function": "hook", "semantic_role": "红苹果视觉冲击"},
                *[{"function": "transition", "semantic_role": "过渡"} for _ in range(14)],
                {"function": "transition", "semantic_role": "全黑暗场过渡"},
                *[{"function": "daily_moment", "semantic_role": "城市生活"} for _ in range(3)],
                {"function": "climax", "semantic_role": "静物高潮"},
                *[{"function": "daily_moment", "semantic_role": "生活细节"} for _ in range(3)],
                {"function": "info", "semantic_role": "搜索卡片"},
            ],
            "packaging_signature": {"stickers_effects": "镜头9叠影；镜头10怒气爆炸；镜头13白色撕纸描边"},
        },
    )
    frames = scheme["storyboard"]
    assert frames[0]["render_component"] == "custom:hero_push_in"
    assert frames[9]["render_component"] == "custom:echo_stack"
    assert frames[10]["render_component"] == "custom:doodle_pop"
    assert frames[13]["render_component"] == "custom:torn_paper_frame"
    assert frames[15]["transition_in"] == "flash_black"
    assert frames[19]["render_component"] == "custom:grid_memory"
    assert frames[-1]["render_component"] == "custom:search_cta_card"
    assert any(track["type"] == "black_dip" for track in scheme["effect_tracks"])


def test_reference_contract_degrades_grid_overlay_to_split_screen_component():
    scheme = {
        "target_duration": 4.0,
        "storyboard": [
            {**_frame(index), "source_material_id": f"m{index}"}
            for index in range(4)
        ],
    }
    gene = {
        "duration": 4.0,
        "shot_genes": [
            {},
            {},
            {
                "effect_events": [{
                    "id": "grid-event",
                    "type": "other",
                    "parameters": {"grid": "3x3", "overlay": "full_frame"},
                }],
            },
            {},
        ],
    }

    result = apply_reference_effect_contract(scheme, gene)
    frame = result["storyboard"][2]

    assert frame["render_component"] == "custom:split_screen_burst"
    assert frame["custom_render_config"]["source_material_ids"] == ["m0", "m1", "m2", "m3"]
    assert frame["effect_mapping"]["grid-event"]["status"] == "degraded"
    assert result["render_hints"]["effect_contract"]["coverage"] == 1.0
    assert result["render_hints"]["effect_contract"]["unresolved"] == []
