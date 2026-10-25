from agents.planner import PlannerAgent
from models.video_structure import BGMInfo
from run_pipeline_e2e import apply_audio_contract


def test_reference_audio_contract_is_explicit_and_deterministic():
    scheme = {"bgm": {}, "audio_config": {}}

    apply_audio_contract(scheme, {"source_id": "reference-123"})

    assert scheme["audio_source_id"] == "reference-123"
    assert scheme["bgm"]["audio_path"] == "_viral_audio"
    assert scheme["audio_config"] == {
        "source": "reference",
        "volume": 0.3,
        "loop": True,
        "trim_before": 0,
        "trim_after": None,
        "fade_frames": 15,
        "original_audio_mode": "mute",
        "normalize": True,
        "target_lufs": -14.0,
        "true_peak": -1.0,
    }


def test_custom_audio_source_is_not_replaced_by_reference():
    scheme = {
        "bgm": {"audio_path": "custom-track"},
        "audio_config": {"source": "custom", "volume": 0.5},
    }

    apply_audio_contract(scheme, {"source_id": "reference-123"})

    assert scheme["bgm"]["audio_path"] == "custom-track"
    assert scheme["audio_config"]["volume"] == 0.5
    assert "audio_source_id" not in scheme


def test_bgm_info_serializes_render_fields():
    bgm = BGMInfo(
        audio_path="_viral_audio",
        volume=0.25,
        loop=False,
        trim_before=12,
        trim_after=120,
    )

    assert bgm.to_dict() == {
        "style": "",
        "bpm": 0,
        "mood": "",
        "beat_points": [],
        "role": "background",
        "reference_track": "",
        "audio_path": "_viral_audio",
        "volume": 0.25,
        "loop": False,
        "trim_before": 12,
        "trim_after": 120,
    }


def test_planner_keeps_audio_fields_in_video_scheme():
    scheme = PlannerAgent.build_scheme(
        None,
        {
            "title": "audio",
            "target_duration": 3,
            "storyboard": [],
            "bgm": {
                "audio_path": "_viral_audio",
                "volume": 0.2,
                "loop": False,
                "trim_before": 3,
                "trim_after": 60,
            },
            "audio_source_id": "reference-123",
            "audio_config": {"source": "reference", "volume": 0.2},
        },
        "topic",
    ).to_dict()

    assert scheme["bgm"]["audio_path"] == "_viral_audio"
    assert scheme["bgm"]["volume"] == 0.2
    assert scheme["bgm"]["loop"] is False
    assert scheme["audio_source_id"] == "reference-123"
    assert scheme["audio_config"]["source"] == "reference"
