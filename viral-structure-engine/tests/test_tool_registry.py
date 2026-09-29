import pytest
from pydantic import ValidationError

from agents.analyst import AnalystAgent
from agents.assembler import AssemblerAgent
from agents.creative import CreativeAgent
from agents.knowledge_agent import KnowledgeAgent
from agents.material_manager import MaterialManagerAgent
from agents.planner import PlannerAgent
from agents.renderer import RendererAgent
from agents.reviewer import ReviewerAgent


def _tool_agents():
    return [
        AnalystAgent(None),
        AssemblerAgent(None),
        CreativeAgent(None),
        KnowledgeAgent(None),
        MaterialManagerAgent(None),
        PlannerAgent(None),
        RendererAgent(None),
        ReviewerAgent(None),
    ]


def test_registered_tools_expose_mcp_compatible_metadata():
    for agent in _tool_agents():
        definitions = agent.list_tools()
        assert definitions
        for tool in definitions:
            assert set(tool) == {"name", "description", "inputSchema"}
            assert tool["name"]
            assert tool["description"]
            assert tool["inputSchema"]["type"] == "object"
            assert tool["inputSchema"]["additionalProperties"] is False


def test_tool_schema_rejects_undeclared_arguments():
    tool = AnalystAgent(None).tools["detect_scenes"]

    assert tool.validate_arguments({"video_path": "demo.mp4"}) == {
        "video_path": "demo.mp4",
        "threshold": 0.3,
    }
    with pytest.raises(ValidationError):
        tool.validate_arguments({"video_path": "demo.mp4", "unexpected": True})
