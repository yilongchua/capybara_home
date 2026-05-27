"""Declarative permission middleware for tool invocations."""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.permissions_config import PermissionDefaultMode, PermissionsConfig, get_permissions_config

_RULE_RE = re.compile(r"^(?P<tool>[^()]+?)(?:\((?P<arg>.*)\))?$")
_TODO_BYPASS_RE = re.compile(
    r"\b(mark|set|update)\b.{0,40}\btodo-\d+\b.{0,40}\b(completed|done)\b",
    flags=re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class ParsedRule:
    tool_pattern: str
    arg_pattern: str | None


def _parse_rule(raw_rule: str) -> ParsedRule | None:
    text = raw_rule.strip()
    if not text:
        return None
    match = _RULE_RE.match(text)
    if not match:
        return None
    tool_pattern = match.group("tool").strip()
    arg_pattern = match.group("arg")
    if arg_pattern is not None:
        arg_pattern = arg_pattern.strip()
    return ParsedRule(tool_pattern=tool_pattern, arg_pattern=arg_pattern or None)


def _serialize_tool_args(args: Any) -> str:
    if isinstance(args, dict):
        for key in ("command", "path", "file_path", "query", "prompt", "description"):
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return json.dumps(args, sort_keys=True, ensure_ascii=False)
    if args is None:
        return ""
    return str(args)


def _matches(rule: ParsedRule, tool_name: str, args_text: str) -> bool:
    if not fnmatch.fnmatchcase(tool_name, rule.tool_pattern):
        return False
    if rule.arg_pattern is None:
        return True
    return fnmatch.fnmatchcase(args_text, rule.arg_pattern)


def _is_literal(pattern: str) -> bool:
    """Return True when the pattern has no fnmatch metachars (pure tool name)."""
    return not any(ch in pattern for ch in "*?[")


def _index_rules(rules: list[ParsedRule]) -> tuple[dict[str, list[ParsedRule]], list[ParsedRule]]:
    """Split rules into a literal-name dispatcher + a wildcard fallback list.

    Literal tool patterns (``bash``, ``web_search``) are grouped by tool name for
    O(1) lookup. Wildcarded patterns (``bash_*``, ``*``) keep linear scanning but
    are only consulted after the literal bucket misses. In practice the literal
    bucket catches almost every rule, so tool-call permission checks shift from
    O(N_rules) to O(1) plus the wildcard tail.
    """
    by_name: dict[str, list[ParsedRule]] = {}
    wildcard: list[ParsedRule] = []
    for rule in rules:
        if _is_literal(rule.tool_pattern):
            by_name.setdefault(rule.tool_pattern, []).append(rule)
        else:
            wildcard.append(rule)
    return by_name, wildcard


def _candidate_rules(
    index: tuple[dict[str, list[ParsedRule]], list[ParsedRule]],
    tool_name: str,
) -> list[ParsedRule]:
    literal_map, wildcard = index
    return literal_map.get(tool_name, []) + wildcard


class PermissionMiddleware(AgentMiddleware[AgentState]):
    """Apply config-driven allow/deny/ask permission policy for tools."""

    def __init__(self, config: PermissionsConfig | None = None) -> None:
        super().__init__()
        cfg = config or get_permissions_config()
        allow_rules = [r for rule in cfg.allow if (r := _parse_rule(rule))]
        deny_rules = [r for rule in cfg.deny if (r := _parse_rule(rule))]
        ask_rules = [r for rule in cfg.ask if (r := _parse_rule(rule))]
        self._allow_index = _index_rules(allow_rules)
        self._deny_index = _index_rules(deny_rules)
        self._ask_index = _index_rules(ask_rules)
        self._default_mode: PermissionDefaultMode = cfg.default_mode

    def _resolve_decision(self, request: ToolCallRequest) -> str:
        tool_name = request.tool_call.get("name", "")
        args_text = _serialize_tool_args(request.tool_call.get("args", {}))

        if tool_name == "ask_user_for_clarification":
            return "allow"

        for rule in _candidate_rules(self._deny_index, tool_name):
            if _matches(rule, tool_name, args_text):
                return "deny"
        for rule in _candidate_rules(self._allow_index, tool_name):
            if _matches(rule, tool_name, args_text):
                return "allow"
        for rule in _candidate_rules(self._ask_index, tool_name):
            if _matches(rule, tool_name, args_text):
                return "ask"

        if self._default_mode == "auto":
            return "allow"
        if self._default_mode == "ask":
            return "ask"
        # "plan" currently behaves as ask in Phase A.
        return "ask"

    def _is_todo_bypass_attempt(self, request: ToolCallRequest) -> bool:
        tool_name = str(request.tool_call.get("name") or "")
        if tool_name != "bash":
            return False
        args_text = _serialize_tool_args(request.tool_call.get("args", {}))
        return bool(_TODO_BYPASS_RE.search(args_text))

    def _build_ask_command(self, request: ToolCallRequest) -> Command:
        tool_name = request.tool_call.get("name", "tool")
        args_text = _serialize_tool_args(request.tool_call.get("args", {}))
        snippet = args_text[:200] + ("..." if len(args_text) > 200 else "")
        message = (
            "⚠️ Permission confirmation required.\n"
            f"Tool: `{tool_name}`\n"
            f"Request: `{snippet}`\n"
            "Reply with your preferred action and I will continue."
        )
        # Use a distinct tool name so frontends and ClarificationMiddleware do not
        # conflate a permission prompt with a model-initiated ask_user_for_clarification call.
        tool_message = ToolMessage(
            content=message,
            tool_call_id=request.tool_call.get("id", ""),
            name="permission_ask",
        )
        return Command(update={"messages": [tool_message]}, goto=END)

    def _build_deny_message(self, request: ToolCallRequest) -> ToolMessage:
        tool_name = request.tool_call.get("name", "tool")
        args_text = _serialize_tool_args(request.tool_call.get("args", {}))
        snippet = args_text[:200] + ("..." if len(args_text) > 200 else "")
        return ToolMessage(
            content=(
                "[permission_denied] Tool execution blocked by permission policy.\n"
                f"Tool: `{tool_name}`\n"
                f"Request: `{snippet}`"
            ),
            tool_call_id=request.tool_call.get("id", ""),
            name=tool_name,
        )

    def _apply_policy(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        if self._is_todo_bypass_attempt(request):
            return ToolMessage(
                content=(
                    "[permission_denied] Todo completion must be recorded via `write_todos`.\n"
                    "Do not use shell commands to mark todos completed. "
                    "Call `write_todos` with explicit todo ids and statuses. "
                    "If the tool is unexpectedly unavailable, report the intended status updates in plain text."
                ),
                tool_call_id=request.tool_call.get("id", ""),
                name=request.tool_call.get("name", "tool"),
            )
        decision = self._resolve_decision(request)
        append_runtime_event(
            request.runtime,
            {
                "source": "permission_middleware",
                "tool": request.tool_call.get("name"),
                "decision": decision,
            },
        )
        if decision == "allow":
            return handler(request)
        if decision == "deny":
            return self._build_deny_message(request)
        return self._build_ask_command(request)

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        return self._apply_policy(request, handler)

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        async def async_handler(req: ToolCallRequest) -> ToolMessage | Command:
            return await handler(req)

        return await self._aapply_policy(request, async_handler)

    async def _aapply_policy(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        if self._is_todo_bypass_attempt(request):
            return ToolMessage(
                content=(
                    "[permission_denied] Todo completion must be recorded via `write_todos`.\n"
                    "Do not use shell commands to mark todos completed. "
                    "Call `write_todos` with explicit todo ids and statuses. "
                    "If the tool is unexpectedly unavailable, report the intended status updates in plain text."
                ),
                tool_call_id=request.tool_call.get("id", ""),
                name=request.tool_call.get("name", "tool"),
            )
        decision = self._resolve_decision(request)
        append_runtime_event(
            request.runtime,
            {
                "source": "permission_middleware",
                "tool": request.tool_call.get("name"),
                "decision": decision,
            },
        )
        if decision == "allow":
            return await handler(request)
        if decision == "deny":
            return self._build_deny_message(request)
        return self._build_ask_command(request)
