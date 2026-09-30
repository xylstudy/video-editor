import asyncio
import json

from agents.analyst import AnalystAgent


class FakeVisionLLM:
    def __init__(self):
        self.image_call = None

    async def chat_with_images(self, prompt, paths, response_format=""):
        self.image_call = {
            "prompt": prompt,
            "paths": paths,
            "response_format": response_format,
        }
        return json.dumps({
            "one_sentence_summary": "mountain road",
            "content": {"main_subject": "road", "people_count": 0},
            "audio": {"has_speech": False},
            "technique": {"camera_movement": "pan"},
            "structure_role": {"primary_function": "scene_establish"},
            "emotion": "calm",
            "audio_video_match": "no_audio",
        })

    def parse_json(self, response):
        return json.loads(response)


class FakeFaceTools:
    def has_face(self, _path):
        return False


def test_analyst_uses_ordered_frames_instead_of_inline_video(tmp_path):
    frames = []
    for index in range(3):
        path = tmp_path / f"frame_{index}.jpg"
        path.write_bytes(b"frame")
        frames.append(str(path))
    llm = FakeVisionLLM()
    analyst = AnalystAgent(llm, face=FakeFaceTools())

    result = asyncio.run(analyst._analyze_shot(
        shot_index=0,
        start_time=0.0,
        end_time=3.0,
        total_duration=10.0,
        video_path="unused.mp4",
        frame_paths=frames,
    ))

    assert llm.image_call is not None
    assert llm.image_call["paths"] == frames
    assert llm.image_call["response_format"] == "json"
    assert "不包含可直接收听的音频" in llm.image_call["prompt"]
    assert result["has_face"] is False
