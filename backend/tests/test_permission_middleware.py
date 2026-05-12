"""Tests for permission middleware policy outcomes."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.middlewares.permission_middleware import PermissionMiddleware
from src.config.permissions_config import PermissionsConfig


def _request(tool_name: str, args: dict | None = None):
    return SimpleNamespace(
        tool_call={"name": tool_name, "id": "tc-1", "args": args or {}},
        runtime=SimpleNamespace(context={}),
        state={},
    )


def _handler(_: object) -> ToolMessage:
    return ToolMessage(content="ok", tool_call_id="tc-1", name="bash")


def test_allow_rule_executes_handler():
    middleware = PermissionMiddleware(
        PermissionsConfig(
            allow=["bash(git status)"],
            deny=[],
            ask=[],
            default_mode="ask",
        )
    )
    result = middleware.wrap_tool_call(_request("bash", {"command": "git status"}), _handler)
    assert isinstance(result, ToolMessage)
    assert result.content == "ok"


def test_deny_rule_returns_error_tool_message():
    middleware = PermissionMiddleware(
        PermissionsConfig(
            allow=[],
            deny=["bash(rm -rf *)"],
            ask=[],
            default_mode="auto",
        )
    )
    result = middleware.wrap_tool_call(_request("bash", {"command": "rm -rf /tmp/foo"}), _handler)
    assert isinstance(result, ToolMessage)
    assert "[permission_denied]" in str(result.content)


def test_ask_rule_returns_interrupt_command():
    middleware = PermissionMiddleware(
        PermissionsConfig(
            allow=[],
            deny=[],
            ask=["bash(docker *)"],
            default_mode="auto",
        )
    )
    result = middleware.wrap_tool_call(_request("bash", {"command": "docker ps"}), _handler)
    assert isinstance(result, Command)
    messages = result.update.get("messages", [])
    assert len(messages) == 1
    assert getattr(messages[0], "name", "") == "permission_ask"


def test_default_ask_mode_applies_when_no_match():
    middleware = PermissionMiddleware(
        PermissionsConfig(
            allow=[],
            deny=[],
            ask=[],
            default_mode="ask",
        )
    )
    result = middleware.wrap_tool_call(_request("write_file", {"path": "/tmp/a.txt"}), _handler)
    assert isinstance(result, Command)
