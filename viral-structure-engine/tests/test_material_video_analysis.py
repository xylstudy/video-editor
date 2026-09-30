import asyncio
import json

from agents.material_manager import MaterialManagerAgent
from models.material import MaterialQuality, MaterialType


class FakeVideoTools:
    def get_video_info(self, _path):
        return {"duration": 20.0, "width": 1920, "height": 1080}

    def extract_frame(self, _path, timestamp):
        return f"frame_{timestamp:.2f}.jpg"


class FakeVisionLLM:
    def __init__(self):
        self.image_call = None

    async def chat_with_images(self, prompt, paths, response_format=""):
        self.image_call = {"prompt": prompt, "paths": paths, "response_format": response_format}
        return json.dumps({
            "content_segments": [{"start": 0, "end": 10, "description": "山路行进"}],
            "highlight_clips": [{"start": 2, "end": 5, "description": "转弯见山"}],
            "overall_assessment": {"quality": "high", "audio_to_keep": "ambient"},
            "emotion_label": "探索",
            "tags": ["山路", "旅行"],
            "overall_vlog_value": "high",
        }, ensure_ascii=False)

    def parse_json(self, response):
        return json.loads(response)


def test_video_material_uploads_representative_frames_and_maps_schema():
    llm = FakeVisionLLM()
    manager = MaterialManagerAgent(llm, video=FakeVideoTools())

    analysis = asyncio.run(manager._analyze_video_material("mat_1", "demo.mp4", "山野旅行"))
    item = manager.build_material_item("mat_1", MaterialType.VIDEO, "demo.mp4", analysis)

    assert llm.image_call is not None
    assert len(llm.image_call["paths"]) == 5
    assert llm.image_call["response_format"] == "json"
    assert item.description == "山路行进"
    assert item.quality == MaterialQuality.HIGH
    assert item.content_segments == analysis["content_segments"]
    assert item.has_usable_audio is True
    assert item.vlog_value == "high"
    assert item.metadata["sampled_frame_times"] == analysis["_sampled_frame_times"]
