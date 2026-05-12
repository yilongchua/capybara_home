"""Tests for phase-gated tool disclosure middleware."""

from types import SimpleNamespace

from langchain_core.messages import ToolMessage

from src.agents.middlewares.tool_disclosure_middleware import ToolDisclosureMiddleware
from src.config.tool_disclosure_config import ToolDisclosureConfig


def _request(tool_name: str, state: dict | None = None):
    return SimpleNamespace(
        tool_call={"name": tool_name, "id": f"tc-{tool_name}", "args": {}},
        state=state or {},
        runtime=SimpleNamespace(context={"thread_id": "thread-1"}),
    )


def test_tool_disclosure_blocks_disallowed_tool():
    middleware = ToolDisclosureMiddleware(
        ToolDisclosureConfig(
            enabled=True,
            default_phase="generator",
            phase_tools={"planner": [], "generator": ["read_file"], "evaluator": []},
        )
    )
    request = _request("bash", state={"plan": {"title": "Plan"}})
    result = middleware.wrap_tool_call(request, lambda _: ToolMessage(content="ok", tool_call_id="tc-bash", name="bash"))
    assert isinstance(result, ToolMessage)
    assert "tool_disclosure_blocked" in str(result.content)


def test_tool_disclosure_allows_tool_in_phase_allowlist():
    middleware = ToolDisclosureMiddleware(
        ToolDisclosureConfig(
            enabled=True,
            default_phase="generator",
            phase_tools={"planner": [], "generator": ["read_file"], "evaluator": []},
        )
    )
    request = _request("read_file", state={"plan": {"title": "Plan"}})
    result = middleware.wrap_tool_call(request, lambda _: ToolMessage(content="ok", tool_call_id="tc-read_file", name="read_file"))
    assert isinstance(result, ToolMessage)
    assert str(result.content) == "ok"
