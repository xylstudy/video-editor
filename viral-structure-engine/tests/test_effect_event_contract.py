import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.planner import PlannerAgent
from agents.reviewer import ReviewerAgent
from models.gene import build_gene
from models.video_structure import EffectEvent
from prompts.analyst_prompts import build_shot_analysis_prompt
from prompts.planner_prompts import build_scheme_generate_prompt
from run_pipeline_e2e import (
    apply_material_diversity_contract,
    apply_reference_effect_contract,
    require_unique_material_capacity,
)
from tools.render_components import resolve_render_component
from tools.video_tools import VideoTools


def _frame(index: int, material_id: str = "") -> dict:
    return {
        "index": index,
        "duration": 1.0,
        "shot_type": "daily_moment",
        "source_material_id": material_id,
        "render_component": "auto",
    }


def test_effect_event_parsing_is_tolerant_and_serializable():
    event = EffectEvent.from_dict(
        {
            "type": "tracked_doodle",
            "start_offset": "bad",
            "end_offset": "0.7",
            "confidence": "0.85",
            "position": [1, 2],
        },
        default_id="effect-1",
    )

    assert event.id == "effect-1"
    assert event.start_offset == 0.0
    assert event.end_offset == 0.7
    assert event.confidence == 0.85
    assert event.position == {}
    assert event.to_dict()["type"] == "tracked_doodle"


def test_gene_promotes_shot_effect_to_absolute_track():
    gene = build_gene(
        [
            {
                "start_time": 2.0,
                "end_time": 4.0,
                "structure_role": {"primary_function": "hook"},
                "effect_events": [
                    {
                        "id": "fold-1",
                        "type": "panel_fold_reveal",
                        "start_offset": 0.2,
                        "end_offset": 0.8,
                        "priority": "high",
                    }
                ],
            }
        ],
        {},
        duration=4.0,
    )

    assert gene.shot_genes[0].effect_events[0]["id"] == "fold-1"
    track = next(item for item in gene.effect_tracks if item["id"] == "fold-1")
    assert track["start"] == 2.2
    assert track["end"] == 2.8


def test_planner_preserves_effect_traceability_fields():
    planner = object.__new__(PlannerAgent)
    scheme = planner.build_scheme(
        {
            "target_duration": 1.0,
            "storyboard": [
                {
                    **_frame(0, "m0"),
                    "effect_event_ids": ["fold-1"],
                    "effect_mapping": {
                        "fold-1": {
                            "status": "mapped",
                            "component": "custom:panel_fold_reveal",
                        }
                    },
                }
            ],
        },
        target_topic="city",
    )

    payload = scheme.to_dict()["storyboard"][0]
    assert payload["effect_event_ids"] == ["fold-1"]
    assert payload["effect_mapping"]["fold-1"]["status"] == "mapped"


def test_reference_effect_contract_maps_or_records_degradation():
    scheme = {"target_duration": 2.0, "storyboard": [_frame(0)]}
    gene = {
        "duration": 2.0,
        "shot_genes": [
            {
                "effect_events": [
                    {"id": "fold", "type": "panel_fold_reveal", "priority": "high"},
                    {"id": "outline", "type": "cutout_outline", "priority": "high"},
                ]
            }
        ],
    }

    result = apply_reference_effect_contract(scheme, gene)
    frame = result["storyboard"][0]
    assert frame["render_component"] == "custom:panel_fold_reveal"
    assert frame["effect_mapping"]["fold"]["status"] == "mapped"
    assert frame["effect_mapping"]["outline"]["status"] == "degraded"
    assert result["render_hints"]["effect_contract"]["coverage"] == 1.0

    resolved, fallback = resolve_render_component(
        "custom:panel_fold_reveal", {}, dynamic_enabled=False
    )
    assert resolved == "custom:panel_fold_reveal"
    assert fallback is False


def test_material_diversity_detects_inventory_shortfall_for_montage():
    frames = [_frame(index, f"m{index % 8}") for index in range(24)]
    inventory = {"items": [{"id": f"m{index}"} for index in range(8)]}

    result = apply_material_diversity_contract({"storyboard": frames}, inventory)
    diversity = result["render_hints"]["material_diversity"]

    assert diversity["recommended_unique"] == 24
    assert diversity["available_shortfall"] == 16
    assert diversity["pass"] is False
    assert result["render_hints"]["material_shortfall"]["additional_unique_segments_needed"] == 16


def test_unique_material_capacity_blocks_before_planning():
    inventory = {"items": [{"id": f"m{index}"} for index in range(15)]}

    with pytest.raises(ValueError, match="还缺 9 条"):
        require_unique_material_capacity(inventory, 24)

    assert require_unique_material_capacity(inventory, 15) == 15


def test_material_diversity_and_reviewer_gate_pass_healthy_plan():
    frames = [_frame(index, f"m{index}") for index in range(10)]
    inventory = {"items": [{"id": f"m{index}"} for index in range(10)]}
    scheme = apply_material_diversity_contract({"storyboard": frames}, inventory)
    scheme["render_hints"]["effect_contract"] = {
        "coverage": 1.0,
        "unresolved": [],
    }

    review = ReviewerAgent.apply_contract_gates({"pass": True}, scheme)

    assert scheme["render_hints"]["material_diversity"]["pass"] is True
    assert review["pass"] is True
    assert review["workflow_status"] == "approved"


def test_reviewer_gate_blocks_missing_materials():
    frames = [_frame(index, f"m{index % 2}") for index in range(12)]
    inventory = {"items": [{"id": "m0"}, {"id": "m1"}]}
    scheme = apply_material_diversity_contract({"storyboard": frames}, inventory)

    review = ReviewerAgent.apply_contract_gates({"pass": True}, scheme)

    assert review["pass"] is False
    assert review["force_iterate"] is True
    assert "material_diversity" in review["contract_failures"]
    assert review["quality_gates"]["material_diversity"]["available_shortfall"] > 0


def test_prompts_require_observed_and_mapped_effect_events():
    analysis_prompt = build_shot_analysis_prompt(0, 0.0, 1.0, 1.0, visual_samples_only=True)
    planner_prompt = build_scheme_generate_prompt("{}", "{}", "city", "", "", gene_json="{}")

    assert "effect_events" in analysis_prompt
    assert "match_cut_to_next" in analysis_prompt
    assert "effect_event_ids" in planner_prompt
    assert "effect_mapping" in planner_prompt
    assert "素材禁止重复使用" in planner_prompt


def test_multiframe_sampling_stays_inside_shot_boundaries():
    assert VideoTools.shot_sample_ratios(1.2, 5) == [0.08, 0.28, 0.5, 0.72, 0.92]
    assert VideoTools.shot_sample_ratios(0.3, 5) == [0.12, 0.5, 0.88]
    assert all(0.0 < value < 1.0 for value in VideoTools.shot_sample_ratios(2.0, 7))
