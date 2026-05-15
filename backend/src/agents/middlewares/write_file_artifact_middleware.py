"""Middleware that auto-registers write_file outputs as thread artifacts.

When the agent writes a file to /mnt/user-data/workspace/, this middleware
upgrades the plain ToolMessage return into a Command that also merges the
file path into thread_state.artifacts via the merge_artifacts reducer.

Without this, the file appears in the sidebar only while the tool call is
streaming (via message-group.tsx auto-select) but is lost from the artifacts
list on page refresh because thread.values.artifacts is never populated.
"""

from __future__ import annotations

from fnmatch import fnmatch
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

_WORKSPACE_PREFIX = f"{VIRTUAL_PATH_PREFIX}/workspace/"
_LEGACY_OUTPUTS_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs/"
_WATCHED_TOOLS = frozenset({"write_file", "str_replace"})


class WriteFileArtifactMiddleware(AgentMiddleware[AgentState]):
    """Promotes successful write_file/str_replace calls in the outputs directory
    into artifact state updates so files persist across page refreshes."""

    def _extract_path_and_content(self, request: ToolCallRequest) -> tuple[str, str | None]:
        args = request.tool_call.get("args") or {}
        if not isinstance(args, dict):
            return "", None
        raw_path = str(args.get("path") or "")
        normalized_path = raw_path
        if raw_path.startswith(_LEGACY_OUTPUTS_PREFIX):
            normalized_path = _WORKSPACE_PREFIX + raw_path[len(_LEGACY_OUTPUTS_PREFIX) :]
        return normalized_path, args.get("content") if isinstance(args.get("content"), str) else None

    def _is_blocking_failure(self, path: str) -> bool:
        cfg = get_quality_gate_config()
        if cfg.block_on_failure:
            return True
        for pattern in cfg.blocking_path_patterns:
            pat = str(pattern or "").strip()
            if not pat:
                continue
            if fnmatch(path, pat) or pat in path:
                return True
        return False

    def _quality_gate_precheck(self, request: ToolCallRequest) -> tuple[Command | None, bool]:
        cfg = get_quality_gate_config()
        if not cfg.enabled:
            return None, False

        path, content = self._extract_path_and_content(request)
        if not path.startswith(_WORKSPACE_PREFIX):
            return None, False
        if content is None:
            return None, False

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
            ), False

        state = request.state or {}
        qg_state = (state.get("quality_gate") or {}) if isinstance(state, dict) else {}
        current_passes = int(qg_state.get("repair_passes") or 0) if isinstance(qg_state, dict) else 0
        next_passes = current_passes + 1
        is_blocking = self._is_blocking_failure(path)

        append_runtime_event(
            getattr(request, "runtime", None),
            {
                "source": "quality_gate_middleware",
                "quality_gate_status": "failed",
                "quality_gate_fail_reasons": check.reasons,
                "repair_passes": next_passes,
            },
        )

        if is_blocking and current_passes < cfg.max_repair_passes:
            repair_focus_by_pass = {
                1: "duplicate table rows only",
                2: "heading numbering consistency only",
                3: "repeated long sections + required sections only",
            }
            focused_repair_scope = repair_focus_by_pass.get(
                next_passes,
                "remaining unresolved quality-gate failures only",
            )
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "QUALITY_GATE_FAILED: Report artifact failed deterministic checks. "
                                f"Reasons={check.reasons}. "
                                f"Repair pass {next_passes}/{cfg.max_repair_passes}. "
                                f"Do a focused repair on {focused_repair_scope}. "
                                "Work section-by-section/part-by-part and avoid rewriting the entire document unless the document is very small. "
                                "After this focused repair, retry write_file."
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
            ), True

        warning_message = (
            "QUALITY_GATE_WARNING_NON_BLOCKING: Report artifact failed deterministic checks. "
            f"Reasons={check.reasons}. "
            "Continuing with fail-forward mode so primary deliverables are not blocked."
        )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=warning_message,
                        tool_call_id=str(request.tool_call.get("id") or ""),
                    )
                ],
                "quality_gate": {
                    "status": "failed",
                    "fail_reasons": check.reasons,
                    "repair_passes": next_passes,
                    "checked_path": path,
                }
            }
        ), False

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        precheck, is_blocking = self._quality_gate_precheck(request)
        if isinstance(precheck, Command):
            # Short-circuit only for blocking quality-gate failures.
            if is_blocking and precheck.update and precheck.update.get("messages"):
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
        if path.startswith(_LEGACY_OUTPUTS_PREFIX):
            path = _WORKSPACE_PREFIX + path[len(_LEGACY_OUTPUTS_PREFIX) :]
        if not path.startswith(_WORKSPACE_PREFIX):
            return result

        quality_update = {}
        precheck_messages = []
        if isinstance(precheck, Command) and precheck.update:
            quality_update = precheck.update.get("quality_gate") or {}
            precheck_messages = list(precheck.update.get("messages") or [])

        return Command(
            update={
                "artifacts": [path],
                "quality_gate": quality_update or {"status": "passed", "fail_reasons": [], "checked_path": path},
                "messages": [*precheck_messages, result],
            }
        )

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        return handler(request)
