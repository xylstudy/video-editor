from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger(__name__)


class OutputManager:
    """管理每次 Pipeline 运行的输出目录结构

    目录结构：
        data/runs/{run_id}/
            run_info.json
            pipeline_summary.json
            01_analyst/  ...
            02_material/ ...
            03_planner/  ...
            04_creative/ ...
            05_assembler/...
            06_reviewer/ ...
            logs/        ...
    """

    def __init__(self, run_id: str | None = None):
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir: Path = settings.RUNS_DIR / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"输出目录: {self.run_dir}")

    # ── 目录路径 ──────────────────────────────────────────

    def stage_dir(self, stage: str) -> Path:
        p = self.run_dir / stage
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ── 保存方法 ──────────────────────────────────────────

    def save_json(self, stage: str, filename: str, data: Any) -> Path:
        path = self.stage_dir(stage) / filename
        if hasattr(data, "to_dict"):
            data = data.to_dict()
        elif hasattr(data, "model_dump"):
            data = data.model_dump()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"  [{stage}] 已保存: {filename}")
        # Refresh once final evaluation evidence changes.  This hook is best
        # effort: experience learning must never fail the generation task.
        if stage == "evaluation" and filename in {"report.json", "skill_evaluation.json"}:
            self._refresh_skill_experience()
        return path

    def save_text(self, stage: str, filename: str, content: str) -> Path:
        path = self.stage_dir(stage) / filename
        path.write_text(content, encoding="utf-8")
        return path

    def save_binary(self, stage: str, filename: str, content: bytes) -> Path:
        path = self.stage_dir(stage) / filename
        path.write_bytes(content)
        return path

    def copy_to(self, stage: str, src_path: str, dest_name: str | None = None) -> Path | None:
        src = Path(src_path)
        if not src.exists():
            return None
        dest = self.stage_dir(stage) / (dest_name or src.name)
        shutil.copy2(str(src), str(dest))
        logger.info(f"  [{stage}] 已拷贝: {dest.name}")
        return dest

    # ── 运行信息 ──────────────────────────────────────────

    def save_run_info(self, **kwargs) -> Path:
        info = {"run_id": self.run_id, "timestamp": datetime.now().isoformat()}
        info.update(kwargs)
        return self.save_json("", "run_info.json", info)

    def save_pipeline_summary(self, state: dict) -> Path:
        scheme = state.get("scheme")
        review = state.get("review_result", {})
        summary = {
            "status": state.get("status", "completed"),
            "target_topic": state.get("target_topic", ""),
            "phase": state.get("phase", ""),
            "iteration": state.get("iteration", 0),
            "is_complete": state.get("is_complete", False),
            "scheme": scheme.to_dict() if hasattr(scheme, "to_dict") else scheme,
            "rendered_video_path": state.get("rendered_video_path", ""),
            "review_result": review,
            "error_count": len(state.get("errors", [])),
            "errors": state.get("errors", []),
            "log_count": len(state.get("logs", [])),
        }
        path = self.save_json("", "pipeline_summary.json", summary)
        self._refresh_skill_experience()
        return path

    def _refresh_skill_experience(self) -> None:
        """Keep Run/Decision Experience in sync with the latest artifacts."""
        try:
            from skills.experience import safe_capture_run_experiences

            safe_capture_run_experiences(
                self.run_dir,
                db_path=settings.DATA_DIR / "skill_experiences.sqlite3",
            )
        except Exception:
            # Import/path errors are also non-fatal for the primary pipeline.
            logger.exception("Skill experience refresh failed for run %s", self.run_id)

    def append_log(self, stage: str, log_entry: dict) -> None:
        """追加一条 Agent 日志到 logs/agent_logs.jsonl"""
        logs_dir = self.stage_dir("logs")
        path = logs_dir / "agent_logs.jsonl"
        entry = {"stage": stage, "timestamp": datetime.now().isoformat(), **log_entry}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
