import json
import logging
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from pydantic import ConfigDict, ValidationError, create_model

from config.llm_client import LLMTools

logger = logging.getLogger(__name__)


TOOL_DESCRIPTIONS = {
    "get_video_info": "Read a video's duration, resolution and frame rate.",
    "detect_scenes": "Detect scene changes in a reference video.",
    "extract_frame": "Extract one frame from a video at the requested time.",
    "extract_audio": "Extract the audio track from a video.",
    "transcribe_audio": "Transcribe an audio file into text.",
    "detect_face": "Detect the primary face and its image region.",
    "analyze_shot": "Analyse a video shot's visual, audio and structural role.",
    "analyze_structure": "Summarise a video's overall narrative and rhythm structure.",
    "analyze_image": "Analyse an image material for Vlog suitability.",
    "analyze_video_material": "Analyse a video material and identify useful clips.",
    "analyze_text": "Analyse text material for its message and emotional tone.",
    "check_gaps": "Find storyboard shots without suitable source material.",
    "extract_skeleton": "Extract a transferable structure from the reference analysis.",
    "generate_scheme": "Generate a storyboard from the structure and material inventory.",
    "iterate_scheme": "Revise a storyboard according to review feedback.",
    "plan_fill_strategy": "Plan how to fill missing storyboard material.",
    "crop_material": "Crop an image material to the requested region.",
    "apply_ken_burns": "Apply a Ken Burns motion effect to an image.",
    "generate_text_card": "Render a text card clip for a storyboard gap.",
    "apply_speed_change": "Change the playback speed of a video material.",
    "generate_subtitle_overlay": "Overlay a subtitle on a video material.",
    "analyze_scheme": "Choose a rendering approach for each storyboard frame.",
    "generate_component": "Generate a custom React and Remotion component.",
    "compile_components": "Compile the generated dynamic rendering components.",
    "render_with_remotion": "Render the storyboard with Remotion.",
    "render_fallback": "Render a fallback video by joining clips with FFmpeg.",
    "review_scheme": "Score storyboard fidelity, pacing and material coverage.",
    "extract_knowledge": "Extract reusable editing knowledge from a video structure.",
    "retrieve_knowledge": "Select relevant knowledge entries for a target Vlog.",
    "done": "Finish the current Agent task and return a short summary.",
}


class AgentRole(str, Enum):
    SUPERVISOR = "supervisor"
    ANALYST = "analyst"
    PLANNER = "planner"
    MATERIAL_MANAGER = "material_manager"
    CREATIVE = "creative"
    ASSEMBLER = "assembler"
    REVIEWER = "reviewer"
    KNOWLEDGE = "knowledge"
    RENDERER = "renderer"


@dataclass
class AgentStep:
    step_index: int
    thought: str = ""
    action: str = ""
    action_input: dict = field(default_factory=dict)
    observation: str = ""
    is_final: bool = False


@dataclass
class AgentResult:
    success: bool = True
    data: Any = None
    message: str = ""
    steps: list[AgentStep] = field(default_factory=list)


@dataclass(frozen=True)
class ToolDefinition:
    """A locally executable tool with MCP-compatible public metadata."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Awaitable[Any]] = field(repr=False, compare=False)
    arguments_model: Any = field(repr=False, compare=False)

    @classmethod
    def from_handler(
        cls,
        name: str,
        handler: Callable[..., Awaitable[Any]],
        description: str | None = None,
    ) -> "ToolDefinition":
        """Create a strict JSON Schema from a typed tool-handler signature."""
        signature = inspect.signature(handler)
        fields: dict[str, tuple[Any, Any]] = {}
        for parameter in signature.parameters.values():
            if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
                raise TypeError(f"Tool {name} cannot use variadic parameter {parameter.name}")
            annotation = parameter.annotation
            if annotation is inspect.Parameter.empty:
                annotation = Any
            default = ... if parameter.default is inspect.Parameter.empty else parameter.default
            fields[parameter.name] = (annotation, default)

        arguments_model = create_model(
            f"{''.join(part.title() for part in name.split('_'))}Arguments",
            __config__=ConfigDict(extra="forbid"),
            **fields,
        )
        input_schema = arguments_model.model_json_schema()
        input_schema["additionalProperties"] = False
        return cls(
            name=name,
            description=(
                description
                or TOOL_DESCRIPTIONS.get(name)
                or inspect.getdoc(handler)
                or f"Execute {name.replace('_', ' ')}."
            ).strip(),
            input_schema=input_schema,
            handler=handler,
            arguments_model=arguments_model,
        )

    def public_definition(self) -> dict[str, Any]:
        """Expose the name, description and inputSchema used by MCP tools."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }

    def validate_arguments(self, arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ValueError("action_input must be a JSON object")
        return self.arguments_model.model_validate(arguments).model_dump()


class BaseAgent(ABC):
    role: AgentRole
    system_prompt: str = ""
    tools: dict[str, ToolDefinition]

    def __init__(self, llm: Optional[LLMTools] = None):
        self.llm = llm or LLMTools()
        self.tools = {}
        self._step_history: list[AgentStep] = []
        self._tool_results: dict[str, Any] = {}

    def register_tools(
        self,
        handlers: dict[str, Callable[..., Awaitable[Any]]],
        descriptions: dict[str, str] | None = None,
    ) -> None:
        """Register this Agent's allow-listed tools with strict JSON schemas."""
        descriptions = descriptions or {}
        self.tools = {
            name: ToolDefinition.from_handler(name, handler, descriptions.get(name))
            for name, handler in handlers.items()
        }

    def list_tools(self) -> list[dict[str, Any]]:
        """Return MCP-shaped name/description/inputSchema definitions."""
        return [tool.public_definition() for tool in self.tools.values()]

    @abstractmethod
    def _build_observe_prompt(self, state: dict, history: list[AgentStep]) -> str:
        ...

    async def execute(self, state: dict) -> AgentResult:
        self._step_history = []
        self._tool_results = {}
        max_steps = 15

        for step_idx in range(max_steps):
            observe_prompt = self._build_observe_prompt(state, self._step_history)
            tool_list = json.dumps(self.list_tools(), ensure_ascii=False, indent=2)

            decision_prompt = f"""当前任务上下文：
{observe_prompt}

可用工具：
{tool_list}

已执行的步骤：
{self._format_history()}

请决定下一步。如果任务已完成，请使用 "done" 工具。
用JSON格式输出你的思考过程：
{{
  "thought": "你当前对任务状态的分析和下一步判断",
  "action": "要调用的工具名，或 'done'",
  "action_input": {{"参数名": "参数值"}},
  "is_final": false
}}"""

            try:
                response = await self.llm.chat(
                    decision_prompt,
                    system=self.system_prompt,
                    response_format="json",
                )
                decision = self.llm.parse_json(response)
            except Exception as e:
                logger.error(f"Agent {self.role} decision error: {e}")
                break

            thought = decision.get("thought", "")
            action = decision.get("action", "")
            action_input = decision.get("action_input", {})
            is_final = decision.get("is_final", False)

            # 输出 Agent 步骤进度
            if is_final or action == "done":
                logger.info(f"  [{self.role.value}] [OK] {thought[:80]}")
            else:
                inp_summary = json.dumps(action_input, ensure_ascii=False)[:60]
                logger.info(f"  [{self.role.value}] → {action}({inp_summary})")

            step = AgentStep(
                step_index=step_idx,
                thought=thought,
                action=action,
                action_input=action_input,
                is_final=is_final,
            )

            if is_final or action == "done":
                step.observation = f"任务完成: {action_input.get('summary', '')}"
                self._step_history.append(step)
                return AgentResult(
                    success=True,
                    data=self._tool_results,
                    message=action_input.get("summary", ""),
                    steps=self._step_history,
                )

            tool = self.tools.get(action)
            if tool is None:
                step.observation = f"错误：未知工具 '{action}'"
                self._step_history.append(step)
                continue

            try:
                validated_input = tool.validate_arguments(action_input)
                result = await tool.handler(**validated_input)
                summary = str(result)[:500]
                step.observation = summary
                self._tool_results[f"step_{step_idx}_{action}"] = result
            except (ValidationError, ValueError) as e:
                step.observation = f"工具参数校验失败: {e}"
                logger.warning(f"Tool {action} argument validation failed: {e}")
            except Exception as e:
                step.observation = f"工具执行失败: {e}"
                logger.warning(f"Tool {action} failed: {e}")

            self._step_history.append(step)

        return AgentResult(
            success=False,
            data=self._tool_results,
            message="超过最大步骤数",
            steps=self._step_history,
        )

    def _format_history(self) -> str:
        lines = []
        for s in self._step_history:
            lines.append(f"  步骤{s.step_index}: {s.action} → {s.observation[:100]}")
        return "\n".join(lines) if lines else "  尚无步骤"

    def _get_tool_result(self, key: str) -> Any:
        return self._tool_results.get(key)
