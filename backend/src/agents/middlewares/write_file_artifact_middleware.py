"""Middleware that auto-registers write_file outputs as thread artifacts.

When the agent writes a file to /mnt/user-data/outputs/, this middleware
upgrades the plain ToolMessage return into a Command that also merges the
file path into thread_state.artifacts via the merge_artifacts reducer.

Without this, the file appears in the sidebar only while the tool call is
streaming (via message-group.tsx auto-select) but is lost from the artifacts
list on page refresh because thread.values.artifacts is never populated.
"""

from __future__ import annotations

from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.agents.middlewares.runtime_events import append_runtime_event
from src.agents.report_quality import check_report_quality
from src.config.paths import VIRTUAL_PATH_PREFIX
from src.config.quality_gate_config import get_quality_gate_config

_OUTPUTS_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs/"
_WATCHED_TOOLS = frozenset({"write_file", "str_replace"})


class WriteFileArtifactMiddleware(AgentMiddleware[AgentState]):
    """Promotes successful write_file/str_replace calls in the outputs directory
    into artifact state updates so files persist across page refreshes."""

    def _extract_path_and_content(self, request: ToolCallRequest) -> tuple[str, str | None]:
        args = request.tool_call.get("args") or {}
        if not isinstance(args, dict):
            return "", None
        return str(args.get("path") or ""), args.get("content") if isinstance(args.get("content"), str) else None

    def _quality_gate_precheck(self, request: ToolCallRequest) -> Command | None:
        cfg = get_quality_gate_config()
        if not cfg.enabled:
            return None

        path, content = self._extract_path_and_content(request)
        if not path.startswith(_OUTPUTS_PREFIX):
            return None
        if content is None:
            return None

        check = check_report_quality(path, content)
        if check.ok:
            return Command(
                update={
                    "quality_gate": {
                        "status": "passed",
                        "fail_reasons": [],
                        "checked_path": path,
                    },
                }
            )

        state = request.state or {}
        qg_state = (state.get("quality_gate") or {}) if isinstance(state, dict) else {}
        current_passes = int(qg_state.get("repair_passes") or 0) if isinstance(qg_state, dict) else 0
        next_passes = current_passes + 1

        append_runtime_event(
            getattr(request, "runtime", None),
            {
                "source": "quality_gate_middleware",
                "quality_gate_status": "failed",
                "quality_gate_fail_reasons": check.reasons,
                "repair_passes": next_passes,
            },
        )

        if current_passes < cfg.max_repair_passes:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "QUALITY_GATE_FAILED: Report artifact failed deterministic checks. "
                                f"Reasons={check.reasons}. "
                                "Do a focused repair only (dedupe table rows, fix heading numbering, remove repeated blocks, ensure Executive Summary + >=4 sections), then retry write_file."
                            ),
                            tool_call_id=str(request.tool_call.get("id") or ""),
                        )
                    ],
                    "quality_gate": {
                        "status": "failed",
                        "fail_reasons": check.reasons,
                        "repair_passes": next_passes,
                        "checked_path": path,
                    },
                }
            )

        return Command(
            update={
                "quality_gate": {
                    "status": "failed",
                    "fail_reasons": check.reasons,
                    "repair_passes": next_passes,
                    "checked_path": path,
                }
            }
        )

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        precheck = self._quality_gate_precheck(request)
        if isinstance(precheck, Command):
            # If precheck contains a ToolMessage, we short-circuit to force a focused repair pass.
            if precheck.update and precheck.update.get("messages"):
                return precheck

        result = await handler(request)

        tool_name = str(request.tool_call.get("name") or "")
        if tool_name not in _WATCHED_TOOLS:
            return result

        if not isinstance(result, ToolMessage):
            return result

        content = result.content
        if not isinstance(content, str) or content != "OK":
            return result

        args = request.tool_call.get("args") or {}
        path = str(args.get("path") or "") if isinstance(args, dict) else ""
        if not path.startswith(_OUTPUTS_PREFIX):
            return result

        quality_update = {}
        if isinstance(precheck, Command) and precheck.update:
            quality_update = precheck.update.get("quality_gate") or {}

        return Command(
            update={
                "artifacts": [path],
                "quality_gate": quality_update or {"status": "passed", "fail_reasons": [], "checked_path": path},
                "messages": [result],
            }
        )

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        return handler(request)
