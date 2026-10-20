"""Decode the restored built-in demos and save a local validation manifest."""
import json
import re
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
entries = json.loads((ROOT / "viral-structure-engine/data/knowledge_db/knowledge.json").read_text(encoding="utf-8"))
entries = [entry for entry in entries if re.fullmatch(r"k_\d+", entry["id"])]
results = []

for entry in entries:
    video_path = ROOT / "web/backend/storage/knowledge_demos" / f"{entry['id']}.mp4"
    assert video_path.is_file() and video_path.stat().st_size > 0, entry["id"]
    cap = cv2.VideoCapture(str(video_path))
    assert cap.isOpened(), f"Cannot open {entry['id']}"
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    expected_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    decoded = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if entry["id"] in {"k_15", "k_27", "k_34", "k_42"} and decoded == expected_frames // 2:
            encoded_ok, image = cv2.imencode(".png", frame)
            assert encoded_ok
            image.tofile(str(ROOT / "data" / f"system-demo-{entry['id']}-frame.png"))
        decoded += 1
    cap.release()
    assert (width, height) == (540, 960), (entry["id"], width, height)
    assert fps > 0 and decoded == expected_frames and decoded > 0, (entry["id"], expected_frames, decoded)
    results.append({"id": entry["id"], "title": entry["title"], "frames": decoded, "duration": round(decoded / fps, 3), "width": width, "height": height, "size": video_path.stat().st_size})

report = {"validated": len(results), "total_frames_decoded": sum(item["frames"] for item in results), "demos": results}
(ROOT / "data/system-demos-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in report.items() if key != "demos"}, ensure_ascii=False))
