from types import SimpleNamespace

import pytest

from tools.ffmpeg_renderer import FFMpegRenderer


def test_zoom_transitions_map_to_supported_xfade(tmp_path):
    renderer = FFMpegRenderer(work_dir=str(tmp_path))
    storyboard = [
        SimpleNamespace(transition_in="cut"),
        SimpleNamespace(transition_in="zoom_in"),
        SimpleNamespace(transition_in="zoom_out"),
    ]

    assert renderer._get_transition(storyboard, 1) == "fade"
    assert renderer._get_transition(storyboard, 2) == "fade"


def test_expected_concat_duration_accounts_for_transition_overlap(tmp_path):
    renderer = FFMpegRenderer(work_dir=str(tmp_path))
    storyboard = [
        SimpleNamespace(duration=10.0, transition_in="cut"),
        SimpleNamespace(duration=5.6, transition_in="fade"),
    ]

    assert renderer._expected_concat_duration(storyboard) == pytest.approx(15.4)
