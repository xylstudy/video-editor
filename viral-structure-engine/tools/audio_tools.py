import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


from config.usage_tracking import instrument_tools


@instrument_tools
class AudioTools:
    def __init__(self, model_size: Optional[str] = None):
        self.model_size = model_size or "base"
        self.model = None

    def _load_model(self):
        if self.model is None:
            try:
                import whisper
                self.model = whisper.load_model(self.model_size)
            except ImportError:
                logger.warning("whisper not installed. Install with: pip install openai-whisper")
                raise

    def transcribe(self, audio_path: str, language: str = "zh") -> str:
        self._load_model()
        return self.model.transcribe(audio_path, language=language)["text"]

    def transcribe_with_timestamps(self, audio_path: str, language: str = "zh") -> list[dict]:
        self._load_model()
        result = self.model.transcribe(audio_path, language=language)
        return [{"start": seg["start"], "end": seg["end"], "text": seg["text"].strip()}
                for seg in result.get("segments", [])]

    def detect_bpm(self, audio_path: str) -> float:
        """检测音频 BPM，依赖 librosa；失败时返回 0"""
        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=None)
            if len(y) < sr:  # less than 1 second
                return 0.0
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            return round(float(tempo), 1)
        except ImportError:
            logger.warning("librosa not installed, BPM detection skipped")
            return 0.0
        except Exception as e:
            logger.debug(f"BPM detection failed: {e}")
            return 0.0

    def detect_beats(self, audio_path: str) -> dict:
        """检测音频精确节拍位置，返回 bpm + beat_times + beat_count"""
        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=None)
            if len(y) < sr:  # less than 1 second
                return {"bpm": 0.0, "beat_times": [], "beat_count": 0}
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
            return {
                "bpm": round(float(tempo), 1),
                "beat_times": [round(t, 2) for t in beat_times],
                "beat_count": len(beat_times),
            }
        except ImportError:
            logger.warning("librosa not installed, beat detection skipped")
            return {"bpm": 0.0, "beat_times": [], "beat_count": 0}
        except Exception as e:
            logger.debug(f"Beat detection failed: {e}")
            return {"bpm": 0.0, "beat_times": [], "beat_count": 0}

    def compute_key_transitions(self, beat_times: list[float], bpm: float = 0) -> list[dict]:
        """从节拍点中筛选关键转场候选（每 4 拍）

        返回 key_transitions 列表，每个包含 time 和 intensity 字段。
        """
        if not beat_times:
            return []
        key_transitions = []
        for i in range(0, len(beat_times), 4):
            beat_in_group = (i // 4) % 4
            intensity = 0.5 + beat_in_group * 0.15  # 0.5, 0.65, 0.8, 0.95
            key_transitions.append({
                "time": beat_times[i],
                "intensity": round(min(intensity, 1.0), 2),
                "beat_index": i,
            })
        return key_transitions

    def analyze_audio_segments(self, audio_path: str, whisper_segments: list[dict] | None = None) -> dict:
        """分析音频分段：人声/静音/音乐 比例和分布

        结合 librosa RMS 能量检测和 Whisper 时间戳分段：
        - Whisper 分段覆盖区域 → speech
        - 高能量且非 speech → music
        - 低能量 → silence
        """
        result = {
            "bpm": self.detect_bpm(audio_path),
            "segments": [],
            "speech_ratio": 0.0,
            "silence_ratio": 0.0,
            "music_ratio": 0.0,
        }

        try:
            import librosa
            y, sr = librosa.load(audio_path, sr=None)
            duration = len(y) / sr
            if duration < 0.5:
                return result

            # RMS energy per frame
            hop_length = 512
            frame_length = 2048
            rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
            times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)
            rms_normalized = rms / (np.max(rms) + 1e-10)

            # Build speech mask from whisper segments
            speech_mask = np.zeros(len(times), dtype=bool)
            if whisper_segments:
                for seg in whisper_segments:
                    start_t, end_t = seg["start"], seg["end"]
                    speech_mask |= (times >= start_t) & (times <= end_t)

            silence_threshold = 0.05
            # Classify each frame
            speech_count, silence_count, music_count = 0, 0, 0
            segments = []
            current_type = None
            current_start = 0.0

            for i, t in enumerate(times):
                if speech_mask[i]:
                    frame_type = "speech"
                elif rms_normalized[i] < silence_threshold:
                    frame_type = "silence"
                else:
                    frame_type = "music"

                if frame_type != current_type:
                    if current_type is not None and t > current_start:
                        segments.append({
                            "start": round(current_start, 2),
                            "end": round(t, 2),
                            "type": current_type,
                        })
                    current_type = frame_type
                    current_start = t

            # Last segment
            if current_type is not None and duration > current_start:
                segments.append({
                    "start": round(current_start, 2),
                    "end": round(duration, 2),
                    "type": current_type,
                })

            # Count ratios
            for seg in segments:
                seg_dur = seg["end"] - seg["start"]
                if seg["type"] == "speech":
                    speech_count += seg_dur
                elif seg["type"] == "silence":
                    silence_count += seg_dur
                else:
                    music_count += seg_dur

            total = speech_count + silence_count + music_count
            if total > 0:
                result["speech_ratio"] = round(speech_count / total, 3)
                result["silence_ratio"] = round(silence_count / total, 3)
                result["music_ratio"] = round(music_count / total, 3)
            result["segments"] = segments

        except ImportError:
            logger.warning("librosa not installed, audio segment analysis skipped")
        except Exception as e:
            logger.debug(f"Audio segment analysis failed: {e}")

        return result
