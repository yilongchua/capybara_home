"""Tests for hooks middleware command handlers."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import ToolMessage

from src.agents.middlewares.hooks_middleware import HooksMiddleware
from src.config.hooks_config import HookCommandConfig, HooksConfig


def _runtime():
    return SimpleNamespace(context={"thread_id": "thread-1"}, state={})


def test_pretool_exit_code_2_blocks_tool_call():
    middleware = HooksMiddleware(
        HooksConfig(
            PreToolUse=[HookCommandConfig(command="exit 2", matcher="bash", timeout_seconds=2)],
        )
    )
    request = SimpleNamespace(
        tool_call={"name": "bash", "id": "tc-1", "args": {"command": "echo hi"}},
        runtime=_runtime(),
    )
    result = middleware.wrap_tool_call(request, lambda _: ToolMessage(content="ok", tool_call_id="tc-1", name="bash"))
    assert isinstance(result, ToolMessage)
    assert "hook_blocked" in str(result.content)


def test_filechanged_updates_observed_state():
    middleware = HooksMiddleware(HooksConfig(FileChanged=[HookCommandConfig(command="exit 0", matcher="*", timeout_seconds=2)]))
    state = {"artifacts": ["/mnt/user-data/outputs/a.txt"], "handoff_artifacts": []}
    update = middleware.after_model(state, _runtime())
    assert update is not None
    assert update["hooks_state"]["observed_files"] == ["/mnt/user-data/outputs/a.txt"]
