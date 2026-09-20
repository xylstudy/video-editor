import logging
from pathlib import Path
from typing import Any

from agents.base import BaseAgent, AgentRole, AgentResult
from config import settings

logger = logging.getLogger(__name__)


class AssemblerAgent(BaseAgent):
    def __init__(self, llm):
        super().__init__(llm)
        self.role = AgentRole.ASSEMBLER
        self.system_prompt = """你是Vlog合成师。你的工作是把编导制定的方案和准备好的素材，合成一条完整的Vlog视频。

工具列表：
- render_with_remotion: 用 Remotion 渲染完整视频（支持转场、字幕、Ken Burns 等）
- render_fallback: 如果 Remotion 不可用，用 FFmpeg 简单拼接
- done: 任务完成"""

        self.register_tools({
            "render_with_remotion": self._render_with_remotion,
            "render_fallback": self._render_fallback,
            "done": self._done,
        })

    def _build_observe_prompt(self, state: dict, history: list) -> str:
        scheme = state.get("scheme")
        parts = [f"任务：{state.get('current_task', {}).get('task_description', '合成视频')}"]
        if scheme:
            sb = getattr(scheme, "storyboard", [])
            parts.append(f"方案：{len(sb)}个分镜，目标{getattr(scheme, 'target_duration', 60)}秒")
        parts.append(f"已执行 {len(history)} 步")
        return "\n".join(parts)

    def _get_output_path(self, state: dict, suffix: str = "") -> str:
        scheme = state.get("scheme")
        title = "vlog"
        if scheme:
            title = getattr(scheme, "title", "") or title
        title = title.strip() or "vlog"
        # 清理 Windows 非法字符
        for ch in '\\/:*?"<>|':
            title = title.replace(ch, "_")
        if suffix:
            title = f"{title}_{suffix}"
        return str(settings.OUTPUT_DIR / f"{title}.mp4")

    async def _render_with_remotion(self, output_path: str = "") -> dict:
        """用 Remotion 渲染完整视频。"""
        from tools.remotion_renderer import render_with_remotion

        # 从 state 取 scheme 和 inventory（self._tool_results 在覆写的 execute 中为空）
        state = getattr(self, "_state", {})
        scheme = state.get("scheme")
        inventory = state.get("material_inventory")

        if not scheme:
            return {"success": False, "error": "没有方案可渲染"}

        output = output_path or self._get_output_path(state)
        result_path = render_with_remotion(scheme, inventory, output)

        if result_path:
            return {"success": True, "output_path": result_path, "method": "remotion"}
        return {"success": False, "error": "Remotion 渲染失败", "fallback": True}

    async def _render_fallback(self, output_path: str = "") -> dict:
        """如果 Remotion 不可用，用 FFmpeg 拼接素材。"""
        from tools.video_tools import VideoTools

        state = getattr(self, "_state", {})
        scheme = state.get("scheme")
        inventory = state.get("material_inventory")

        if not scheme:
            return {"success": False, "error": "没有可用的方案"}

        material_map = {}
        if inventory:
            items = getattr(inventory, "items", getattr(inventory, "materials", []))
            for m in items:
                mid = getattr(m, "id", "")
                mpath = getattr(m, "path", "")
                if mid and mpath:
                    material_map[mid] = mpath

        scheme_dict = scheme.to_dict() if hasattr(scheme, "to_dict") else scheme
        storyboard = scheme_dict.get("storyboard", [])
        clip_paths = []
        for frame in storyboard:
            mid = frame.get("material_id") or frame.get("source_material_id", "")
            if mid and mid in material_map:
                clip_paths.append(material_map[mid])

        if not clip_paths:
            return {"success": False, "error": "没有可拼接的素材"}

        output = output_path or self._get_output_path(state, suffix="fallback")
        try:
            video = VideoTools()
            merged = video.concat_clips(clip_paths)
            import shutil
            shutil.copy2(merged, output)
            return {"success": True, "output_path": output, "method": "ffmpeg_fallback"}
        except Exception as e:
            logger.exception(f"FFmpeg 回退渲染失败: {e}")
            return {"success": False, "error": str(e)}

    async def _done(self, summary: str) -> dict:
        return {"status": "done", "summary": summary}

    async def execute(self, state: dict) -> AgentResult:
        """覆写基类的 execute，先用 Remotion 渲染，失败则回退 FFmpeg。"""
        self._step_history = []
        self._tool_results = {}
        self._state = state

        output_path = self._get_output_path(state)

        # 尝试 Remotion
        render_result = await self._render_with_remotion(output_path)
        if render_result.get("success"):
            return AgentResult(
                success=True,
                data={"rendered_video_path": render_result["output_path"]},
                message=f"Remotion 渲染完成: {render_result['output_path']}",
            )

        # Remotion 失败，回退到 FFmpeg
        if render_result.get("fallback"):
            logger.warning("Remotion 不可用，回退到 FFmpeg 拼接")
            fallback_result = await self._render_fallback()
            if fallback_result.get("success"):
                return AgentResult(
                    success=True,
                    data={"rendered_video_path": fallback_result["output_path"]},
                    message=f"FFmpeg 拼接完成: {fallback_result['output_path']}",
                )
            return AgentResult(
                success=False,
                data={},
                message=fallback_result.get("error", "渲染失败"),
            )

        return AgentResult(
            success=False,
            data={},
            message=render_result.get("error", "渲染失败"),
        )
