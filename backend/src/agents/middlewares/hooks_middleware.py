"""Command-only lifecycle hooks middleware (Phase B v1)."""

from __future__ import annotations

import fnmatch
import logging
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.hooks_config import HookCommandConfig, HooksConfig, get_hooks_config

logger = logging.getLogger(__name__)


class HooksMiddlewareState(AgentState):
    hooks_state: NotRequired[dict | None]
    artifacts: NotRequired[list[str] | None]
    handoff_artifacts: NotRequired[list[str] | None]


class HooksMiddleware(AgentMiddleware[HooksMiddlewareState]):
    """Executes command handlers on lifecycle events."""

    state_schema = HooksMiddlewareState

    def __init__(self, config: HooksConfig | None = None):
        super().__init__()
        self._config = config or get_hooks_config()

    @staticmethod
    def _match(hook: HookCommandConfig, candidate: str) -> bool:
        if not hook.matcher:
            return True
        return fnmatch.fnmatchcase(candidate, hook.matcher)

    def _run_command(
        self,
        runtime: Runtime,
        hook: HookCommandConfig,
        event: str,
        candidate: str,
        state: dict | None = None,
    ) -> tuple[int, str]:
        thread_data: dict | None = None
        if isinstance(state, dict):
            td = state.get("thread_data")
            if isinstance(td, dict):
                thread_data = td
        if thread_data is None:
            runtime_state = getattr(runtime, "state", None) or {}
            td = runtime_state.get("thread_data") if isinstance(runtime_state, dict) else None
            if isinstance(td, dict):
                thread_data = td
        workspace_path = thread_data.get("workspace_path") if isinstance(thread_data, dict) else None
        cwd = Path(workspace_path) if isinstance(workspace_path, str) and workspace_path else None
        # `shell=True` is intentional: hook commands are authored by the
        # operator in `config.yaml`/extensions and routinely use shell
        # features (pipes, `&&`, variable expansion). The risk surface here
        # is config-trust: the config source MUST remain operator-owned
        # (not editable via unauthenticated Gateway endpoints). If config
        # ingestion ever broadens, switch this to `shlex.split` + shell=False
        # for commands that don't need a shell.
        completed = subprocess.run(
            hook.command,
            shell=True,  # noqa: S602 — see comment above; config is operator-trusted
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=hook.timeout_seconds,
            check=False,
        )
        stderr = (completed.stderr or "").strip()
        append_runtime_event(
            runtime,
            {
                "source": "hooks_middleware",
                "event": event,
                "candidate": candidate,
                "command": hook.command,
                "exit_code": completed.returncode,
                "stderr": stderr[:400],
            },
        )
        return completed.returncode, stderr

    def _run_event(
        self,
        runtime: Runtime,
        hooks: list[HookCommandConfig],
        event: str,
        candidate: str,
        state: dict | None = None,
    ) -> tuple[bool, str | None]:
        for hook in hooks:
            if not self._match(hook, candidate):
                continue
            code, stderr = self._run_command(runtime, hook, event, candidate, state=state)
            if code == 2:
                return False, stderr or "Blocked by hook policy."
            if code != 0:
                # Non-blocking warning per design (exit codes other than 0/2).
                # Trajectory already recorded via append_runtime_event; also log.
                logger.warning(
                    "Hook %s on `%s` exited %s: %s",
                    event,
                    candidate,
                    code,
                    stderr[:200] if stderr else "(no stderr)",
                )
        return True, None

    @override
    def before_agent(self, state: HooksMiddlewareState, runtime: Runtime) -> dict | None:
        if not self._config.SessionStart:
            return None
        allowed, reason = self._run_event(runtime, self._config.SessionStart, "SessionStart", "session", state=state)
        if allowed:
            return None
        return {
            "messages": [
                ToolMessage(
                    content=f"[hook_blocked] SessionStart blocked: {reason}",
                    tool_call_id="hook-session-start",
                    name="hooks",
                )
            ]
        }

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]) -> ToolMessage | Command:
        tool_name = str(request.tool_call.get("name") or "unknown")
        req_state = getattr(request, "state", None)
        allowed, reason = self._run_event(request.runtime, self._config.PreToolUse, "PreToolUse", tool_name, state=req_state)
        if not allowed:
            return ToolMessage(
                content=f"[hook_blocked] PreToolUse blocked `{tool_name}`: {reason}",
                tool_call_id=request.tool_call.get("id", ""),
                name=tool_name,
            )
        result = handler(request)
        self._run_event(request.runtime, self._config.PostToolUse, "PostToolUse", tool_name, state=req_state)
        return result

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]) -> ToolMessage | Command:
        tool_name = str(request.tool_call.get("name") or "unknown")
        req_state = getattr(request, "state", None)
        allowed, reason = self._run_event(request.runtime, self._config.PreToolUse, "PreToolUse", tool_name, state=req_state)
        if not allowed:
            return ToolMessage(
                content=f"[hook_blocked] PreToolUse blocked `{tool_name}`: {reason}",
                tool_call_id=request.tool_call.get("id", ""),
                name=tool_name,
            )
        result = await handler(request)
        self._run_event(request.runtime, self._config.PostToolUse, "PostToolUse", tool_name, state=req_state)
        return result

    @override
    def after_model(self, state: HooksMiddlewareState, runtime: Runtime) -> dict | None:
        # Skip entirely when neither file-event hook is configured.
        if not self._config.FileChanged and not self._config.FileRemoved:
            return None
        hooks_state = dict(state.get("hooks_state") or {})
        observed_files = set(hooks_state.get("observed_files") or [])
        current_files = set((state.get("artifacts") or []) + (state.get("handoff_artifacts") or []))

        # Skip checkpoint write when nothing actually changed.
        if current_files == observed_files:
            return None

        added = sorted(current_files - observed_files)
        removed = sorted(observed_files - current_files)
        for path in added:
            if self._config.FileChanged:
                self._run_event(runtime, self._config.FileChanged, "FileChanged", path, state=state)
        for path in removed:
            if self._config.FileRemoved:
                self._run_event(runtime, self._config.FileRemoved, "FileRemoved", path, state=state)
        return {"hooks_state": {"observed_files": sorted(current_files)}}

    @override
    async def aafter_model(self, state: HooksMiddlewareState, runtime: Runtime) -> dict | None:
        return self.after_model(state, runtime)
