import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from config.motion_catalog import build_motion_catalog_prompt

from agents.base import BaseAgent, AgentRole, AgentResult, AgentStep

logger = logging.getLogger(__name__)

REMOTION_DIR = Path(__file__).resolve().parent.parent / "remotion"
DYNAMIC_DIR = REMOTION_DIR / "src" / "dynamic"


class RendererAgent(BaseAgent):
    """渲染决策 Agent。

    职责：
    1. 逐分镜决定渲染方式（内置组件 / LLM 生成组件）
    2. 生成缺失的自定义 React 组件
    3. 编译动态组件并注册
    4. 输出完整的渲染计划（写入 scheme 的 render_component 等字段）
    """

    def __init__(self, llm):
        super().__init__(llm)
        self.role = AgentRole.CREATIVE  # 复用 creative 角色类型
        self.system_prompt = """你是一位Vlog渲染工程师（Renderer Agent）。你的工作是把编导（Planner）给出的方案转化成可执行的渲染计划。

你有两个核心能力：

能力一：匹配内置组件
  内置组件列表（直接用）：
  - text_card: 全屏文字卡，支持打字机/淡入/滑入动画
  - ken_burns: 图片缩放/平移效果（zoom_in/zoom_out/pan_left/pan_right）
  - subtitles: 字幕叠加层
  - transitions: cut/fade/dissolve/slide/zoom_in/zoom_out/flash_white

能力二：生成自定义组件
  当现有组件无法满足需求时，你写 React/Remotion 组件代码。
  规则：
  - 必须用 TypeScript + React + Remotion hooks
  - props 通过 custom_render_config 传递
  - 组件文件保存在 remotion/src/dynamic/comp_{name}.tsx
  - 编译后自动注册，方案中用 "custom:{name}" 引用

工具列表：
- analyze_scheme: 分析方案，逐分镜判断渲染策略
- generate_component: 为某个分镜生成自定义 React 组件代码
- compile_components: 编译所有动态组件
- done: 任务完成"""

        self.register_tools({
            "analyze_scheme": self._analyze_scheme,
            "generate_component": self._generate_component,
            "compile_components": self._compile_components,
            "done": self._done,
        })

    def _build_observe_prompt(self, state: dict, history: list) -> str:
        scheme = state.get("scheme")
        task = state.get("current_task", {})
        parts = [f"任务：{task.get('task_description', '渲染决策')}"]
        if scheme:
            sb = getattr(scheme, "storyboard", [])
            parts.append(f"方案：{len(sb)} 个分镜")
            # 统计已分配渲染策略的
            assigned = sum(1 for f in sb if getattr(f, "render_component", "auto") != "auto")
            parts.append(f"已分配渲染策略：{assigned}/{len(sb)}")
        parts.append(f"已执行 {len(history)} 步")
        return "\n".join(parts)

    async def _analyze_scheme(self, scheme_json: str, material_summary: str) -> dict:
        """分析方案中每个分镜的渲染需求，判断哪些适合内置组件、哪些需要自定义"""
        # 加载系统可用特效列表
        techniques_hint = ""
        try:
            from knowledge.techniques_loader import get_summary
            techniques_hint = get_summary()
        except Exception:
            pass

        motion_catalog = build_motion_catalog_prompt()

        prompt = f"""你是一个Vlog渲染策略分析专家。

请分析以下方案中每个分镜的渲染需求，并判断用什么方式渲染。

【方案】
{scheme_json}

【素材概况】
{material_summary}

【系统可用剪辑手法】
{techniques_hint}

{motion_catalog}

对每个分镜，判断：
1. render_component: 用什么渲染（"auto"让系统自动推断 / "text_card" / "ken_burns" / "custom:xxx" 需要自定义组件）
2. custom_render_config: 如果是自定义组件，需要透传什么配置
3. 是否需要生成新组件（need_new_component: true 时，描述清楚要做什么效果）

输出格式：
{{
  "frame_decisions": [
    {{
      "index": 0,
      "render_component": "auto",
      "need_new_component": false,
      "new_component_spec": {{}},
      "custom_render_config": {{}},
      "reasoning": "选择理由"
    }}
  ],
  "summary": "整体渲染策略说明"
}}"""
        response = await self.llm.chat(prompt, system=self.system_prompt, response_format="json", max_tokens=16384)
        return self.llm.parse_json(response)

    async def _generate_component(
        self,
        component_name: str,
        spec_json: str,
        frame_json: str,
    ) -> dict:
        """为某个分镜生成自定义 React 组件代码"""
        prompt = f"""你是一位 React/Remotion 组件开发专家。请根据以下规格生成一个 Vlog 渲染组件。

【组件名称】
{component_name}

【规格说明】
{spec_json}

【对应分镜数据】
{frame_json}

生成要求：
1. TypeScript + React + Remotion 4.x
2. 使用 `import` 导入，组件用 `export default`
3. 可用的 Remotion API：useCurrentFrame, useVideoConfig, interpolate, Easing, AbsoluteFill, Img, OffthreadVideo, Audio, Sequence, spring, random
4. props 类型通过 Record<string, any> 或具体接口
5. 样式用 React.CSSProperties 对象（style={{}}）
6. 宽高 1080x1920 竖屏
7. 考虑中文内容（font-family: 'PingFang SC', 'Microsoft YaHei'）

回复格式：
{{
  "component_code": "完整的组件代码（包含 import 和 export default）",
  "file_name": "comp_{component_name}.tsx",
  "render_config": {{"分镜需要的 custom_render_config 配置"}},
  "test_tips": "如何验证这个组件"
}}"""
        response = await self.llm.chat(prompt, system=self.system_prompt, response_format="json")
        result = self.llm.parse_json(response)

        # 把生成的代码写入文件
        code = result.get("component_code", "")
        file_name = result.get("file_name", f"comp_{component_name}.tsx")
        if code:
            DYNAMIC_DIR.mkdir(parents=True, exist_ok=True)
            file_path = DYNAMIC_DIR / file_name
            file_path.write_text(code, encoding="utf-8")
            logger.info(f"生成动态组件: {file_path}")
            result["file_path"] = str(file_path)

        return result

    async def _compile_components(self) -> dict:
        """编译所有动态组件"""
        DYNAMIC_DIR.mkdir(parents=True, exist_ok=True)

        # 找所有 .tsx
        tsx_files = sorted(DYNAMIC_DIR.glob("comp_*.tsx"))
        if not tsx_files:
            return {"compiled_count": 0, "message": "没有需要编译的组件"}

        # 逐个编译
        success = 0
        errors = []
        for f in tsx_files:
            try:
                ok = await self._esbuild_compile(f)
                if ok:
                    success += 1
                else:
                    errors.append(str(f.name))
            except Exception as e:
                errors.append(f"{f.name}: {e}")

        # 生成 index.ts
        await self._regenerate_index(tsx_files)

        return {
            "compiled_count": success,
            "total": len(tsx_files),
            "errors": errors,
            "message": f"{success}/{len(tsx_files)} 编译成功",
        }

    async def _esbuild_compile(self, tsx_path: Path) -> bool:
        js_path = tsx_path.with_suffix(".js")
        cmd = [
            "npx.cmd" if sys.platform == "win32" else "npx",
            "esbuild",
            str(tsx_path.resolve()),
            "--bundle",
            f"--outfile={js_path.resolve()}",
            "--format=esm",
            "--platform=browser",
            "--jsx=automatic",
            "--external:remotion",
            "--external:react",
            "--external:react-dom",
        ]
        try:
            result = subprocess.run(
                cmd, cwd=str(REMOTION_DIR),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.error(f"esbuild 编译失败 {tsx_path.name}: {result.stderr[:300]}")
                return False
            logger.info(f"编译完成: {tsx_path.name}")
            return True
        except Exception as e:
            logger.error(f"esbuild 异常: {e}")
            return False

    async def _regenerate_index(self, tsx_files: list[Path]):
        lines = [
            "// 自动生成 — Renderer Agent 管理，不要手动编辑",
            'import { registerComponent } from "../components/registry";',
            "",
        ]
        for f in tsx_files:
            stem = f.stem
            lines.append(f'import {{ default as Comp_{stem} }} from "./{stem}";')
        lines.append("")
        for f in tsx_files:
            stem = f.stem
            name = stem.replace("comp_", "", 1) if stem.startswith("comp_") else stem
            lines.append(
                f'registerComponent("{name}", Comp_{stem} as unknown as React.FC<Record<string, unknown>>);'
            )
        lines.append("")
        (DYNAMIC_DIR / "index.ts").write_text("\n".join(lines), encoding="utf-8")

    async def _done(self, summary: str) -> dict:
        return {"status": "done", "summary": summary}
