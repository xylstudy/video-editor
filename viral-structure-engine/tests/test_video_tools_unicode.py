import sys
import uuid
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.video_tools import VideoTools, _imread, _imwrite


def test_imwrite_supports_unicode_paths():
    temp_root = Path(__file__).parent / f"_unicode_output_{uuid.uuid4().hex}"
    output = temp_root / "中文目录" / "关键帧.jpg"
    image = np.zeros((24, 32, 3), dtype=np.uint8)

    try:
        _imwrite(str(output), image)

        decoded = cv2.imdecode(np.fromfile(output, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert output.is_file()
        assert decoded.shape == (24, 32, 3)
    finally:
        if output.exists():
            output.unlink()
        if output.parent.exists():
            output.parent.rmdir()
        if temp_root.exists():
            temp_root.rmdir()


def test_imread_supports_unicode_paths():
    temp_root = Path(__file__).parent / f"_unicode_input_{uuid.uuid4().hex}"
    output = temp_root / "中文目录" / "关键帧.jpg"
    image = np.full((24, 32, 3), 127, dtype=np.uint8)

    try:
        _imwrite(str(output), image)
        decoded = _imread(str(output))

        assert decoded is not None
        assert decoded.shape == (24, 32, 3)
    finally:
        if output.exists():
            output.unlink()
        if output.parent.exists():
            output.parent.rmdir()
        if temp_root.exists():
            temp_root.rmdir()


def test_scene_threshold_uses_normalized_frame_difference():
    temp_root = Path(__file__).parent / f"_scene_output_{uuid.uuid4().hex}"
    temp_root.mkdir(parents=True)
    video_path = temp_root / "scene-test.mp4"
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        10.0,
        (64, 48),
    )
    assert writer.isOpened()
    for value in (0, 1, 255):
        frame = np.full((48, 64, 3), value, dtype=np.uint8)
        for _ in range(10):
            writer.write(frame)
    writer.release()

    try:
        scenes = VideoTools(str(temp_root)).detect_scene_changes(str(video_path), threshold=0.3)

        # The tiny 0 -> 1 change must not count as a cut; 1 -> 255 must.
        assert len(scenes) == 2
        assert scenes[0]["end"] == 2.0
    finally:
        if video_path.exists():
            video_path.unlink()
        if temp_root.exists():
            temp_root.rmdir()
