import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import cv2

logger = logging.getLogger(__name__)


def _opencv_safe_path(source: Path) -> Path:
    """Return an ASCII path for OpenCV APIs that cannot open Unicode paths."""
    try:
        str(source).encode("ascii")
        return source
    except UnicodeEncodeError:
        target_dir = Path(tempfile.gettempdir()) / "video_claw_opencv"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        if not target.exists() or target.stat().st_size != source.stat().st_size:
            shutil.copyfile(source, target)
        return target


def _imwrite(image_path: str, image) -> None:
    target = Path(image_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(target.suffix or ".jpg", image)
    if not ok:
        raise ValueError(f"Cannot encode image: {image_path}")
    encoded.tofile(str(target))


from config.usage_tracking import instrument_tools


@instrument_tools
class FaceTools:
    def __init__(self):
        self.face_cascade = None

        # OpenCV 5.0 的首批 Python wheel 不再提供传统的
        # cv2.CascadeClassifier。人脸检测只是素材分析的增强项，不能因此
        # 阻断整条素材入库链路；在接口不可用时安全降级为“未检测到人脸”。
        cascade_factory = getattr(cv2, "CascadeClassifier", None)
        cascade_dir = getattr(getattr(cv2, "data", None), "haarcascades", "")
        if not callable(cascade_factory) or not cascade_dir:
            logger.warning(
                "当前 OpenCV %s 不提供 Haar Cascade 人脸检测，已禁用该增强项",
                getattr(cv2, "__version__", "unknown"),
            )
            return

        cascade_source = Path(cascade_dir) / "haarcascade_frontalface_default.xml"
        if not cascade_source.is_file():
            logger.warning("Haar Cascade 模型文件不存在，已禁用人脸检测增强项")
            return

        cascade = cascade_factory(str(_opencv_safe_path(cascade_source)))
        if cascade.empty():
            logger.warning("Haar Cascade 模型加载失败，已禁用人脸检测增强项")
            return

        self.face_cascade = cascade

    @staticmethod
    def _imread(image_path: str):
        return cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)

    def detect(self, image_path: str) -> list[dict]:
        if self.face_cascade is None:
            return []

        img = self._imread(image_path)
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

        img_area = img.shape[0] * img.shape[1]
        return [{"bbox": (int(x), int(y), int(w), int(h)), "confidence": 0.95, "area_ratio": (w * h) / img_area}
                for x, y, w, h in faces]

    def has_face(self, image_path: str) -> bool:
        return len(self.detect(image_path)) > 0

    def get_main_face_region(self, image_path: str) -> Optional[tuple]:
        faces = self.detect(image_path)
        if not faces:
            return None
        main = max(faces, key=lambda r: r["area_ratio"])
        return main["bbox"]

    def get_face_crop(self, image_path: str, expand_ratio: float = 1.5) -> str:
        img = self._imread(image_path)
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")

        h_img, w_img = img.shape[:2]
        faces = self.detect(image_path)

        if not faces:
            out = str(Path(image_path).parent / f"crop_{Path(image_path).name}")
            _imwrite(out, img)
            return out

        main = max(faces, key=lambda r: r["area_ratio"])
        x, y, w, h = main["bbox"]
        cx, cy = x + w // 2, y + h // 2
        new_size = max(w, h) * expand_ratio

        x1 = max(0, int(cx - new_size // 2))
        y1 = max(0, int(cy - new_size // 2))
        x2 = min(w_img, int(cx + new_size // 2))
        y2 = min(h_img, int(cy + new_size // 2))

        crop = img[y1:y2, x1:x2]
        out = str(Path(image_path).parent / f"crop_{Path(image_path).name}")
        _imwrite(out, crop)
        return out
