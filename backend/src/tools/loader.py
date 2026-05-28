"""Loader that hydrates BaseTool instances from the per-mode tool catalogs.

Each JSON entry in `internal_tools_plan.json` / `internal_tools_work.json`
resolves to an existing langchain BaseTool (the `@tool`-decorated function
exported from src.tools.builtins or src.sandbox.tools). The loader rewrites
the tool's `description` (and per-argument descriptions where the field names
match) so the LLM-facing contract is sourced from JSON.

The `mode` and `phase` axes are resolved up-front at catalog-file selection
time (see `src/tools/tools.py`), so the policy fields on each entry are kept
on the wrapped tool via `_capyhome_policy` for diagnostics and the audit tool
only — runtime middleware no longer re-checks them.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain.tools import BaseTool

from src.reflection import resolve_variable
from src.tools.schema import ExternalPolicy, ToolDefinition

logger = logging.getLogger(__name__)

POLICY_ATTR = "_capyhome_policy"


class ToolDefinitionError(ValueError):
    """Raised when a JSON entry cannot be turned into a usable BaseTool."""


def load_tool_definitions(path: Path | str) -> list[ToolDefinition]:
    """Parse a tool catalog JSON file into ToolDefinition objects.

    Returns an empty list when the file is missing — callers fall back to the
    legacy in-code BUILTIN_TOOLS list. Raises ToolDefinitionError on a malformed
    file so the failure is loud (we want JSON edits to fail fast in tests).
    """
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolDefinitionError(f"Invalid JSON in {file_path}: {exc}") from exc
    if not isinstance(raw, list):
        raise ToolDefinitionError(f"{file_path} must contain a JSON array of tool entries")
    return [ToolDefinition.model_validate(entry) for entry in raw]


def load_external_policy(path: Path | str) -> ExternalPolicy:
    """Parse external_tools.json into an ExternalPolicy object."""
    file_path = Path(path)
    if not file_path.exists():
        return ExternalPolicy()
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolDefinitionError(f"Invalid JSON in {file_path}: {exc}") from exc
    return ExternalPolicy.model_validate(raw)


def _apply_arg_descriptions(tool: BaseTool, defn: ToolDefinition) -> None:
    """Copy per-argument descriptions from JSON into the tool's args_schema.

    Only fields that exist on the args_schema are touched; JSON parameters
    that have no matching arg are flagged in the drift validator instead.
    """
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is None or not hasattr(args_schema, "model_fields"):
        return
    fields = args_schema.model_fields  # type: ignore[attr-defined]
    for arg_name, arg_spec in defn.parameters.properties.items():
        description = arg_spec.get("description")
        if not isinstance(description, str) or arg_name not in fields:
            continue
        fields[arg_name].description = description
    if hasattr(args_schema, "model_rebuild"):
        try:
            args_schema.model_rebuild(force=True)
        except Exception:  # pragma: no cover - defensive, never fatal
            logger.debug("Could not rebuild args_schema for tool '%s'", defn.name)


def build_structured_tool(defn: ToolDefinition) -> BaseTool:
    """Resolve `defn.handler` to a BaseTool and apply JSON-sourced metadata."""
    tool = resolve_variable(defn.handler)
    if not isinstance(tool, BaseTool):
        raise ToolDefinitionError(
            f"Handler '{defn.handler}' for tool '{defn.name}' did not resolve to a langchain BaseTool "
            f"(got {type(tool).__name__}). Use @tool to decorate the handler.",
        )
    if tool.name != defn.name:
        raise ToolDefinitionError(
            f"JSON tool name '{defn.name}' disagrees with handler tool name '{tool.name}'. "
            "Either rename the JSON entry or the decorated function — they must match.",
        )
    tool.description = defn.description
    _apply_arg_descriptions(tool, defn)
    setattr(tool, POLICY_ATTR, defn)
    return tool


def get_tool_policy(tool: BaseTool) -> ToolDefinition | None:
    """Return the policy attached by build_structured_tool, if any."""
    policy = getattr(tool, POLICY_ATTR, None)
    return policy if isinstance(policy, ToolDefinition) else None


def schema_drift_report(defn: ToolDefinition, tool: BaseTool) -> list[str]:
    """Return a list of human-readable drift errors between JSON and handler.

    Empty list means the JSON parameters and the handler's args_schema agree
    on field names and required-ness. Used by tests/test_tool_schema_sync.py.
    """
    errors: list[str] = []
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is None or not hasattr(args_schema, "model_fields"):
        return [f"{defn.name}: handler has no args_schema; cannot validate"]

    fields = args_schema.model_fields  # type: ignore[attr-defined]
    # Strip langchain-injected runtime parameters from the comparison —
    # tool_call_id and runtime are not LLM-visible.
    injected = {"tool_call_id", "runtime"}
    handler_args = {name for name in fields if name not in injected}
    json_args = set(defn.parameters.properties.keys())

    missing_in_json = handler_args - json_args
    extra_in_json = json_args - handler_args
    if missing_in_json:
        errors.append(
            f"{defn.name}: handler accepts args not described in JSON: {sorted(missing_in_json)}",
        )
    if extra_in_json:
        errors.append(
            f"{defn.name}: JSON declares args the handler does not accept: {sorted(extra_in_json)}",
        )

    json_required = set(defn.parameters.required)
    handler_required = {
        name
        for name, field in fields.items()
        if name not in injected and field.is_required()
    }
    only_json_required = json_required - handler_required
    only_handler_required = handler_required - json_required
    if only_json_required:
        errors.append(
            f"{defn.name}: JSON marks args required that the handler treats as optional: {sorted(only_json_required)}",
        )
    if only_handler_required:
        errors.append(
            f"{defn.name}: handler marks args required that the JSON treats as optional: {sorted(only_handler_required)}",
        )

    return errors


def filter_mcp_tools_by_policy(
    tools: list[BaseTool],
    policy: ExternalPolicy,
    *,
    mode: str | None = None,
    phase: str | None = None,
    subagent: bool = False,
) -> list[BaseTool]:
    """Apply external_tools.json MCP policy to a cached MCP tool list.

    Policy is keyed by server name. We match by looking for ``<server_name>__``
    or ``<server_name>:`` prefixes on the tool name (langchain-mcp-adapters
    convention) or the optional explicit ``name_prefix`` declared in policy.
    Tools whose server has no policy entry pass through unchanged so adding
    a new MCP server doesn't silently drop its tools.
    """
    if not policy.mcp_servers:
        return tools

    def _matches(tool: BaseTool, server_name: str, name_prefix: str | None) -> bool:
        tool_name = getattr(tool, "name", "") or ""
        candidates = {f"{server_name}__", f"{server_name}:", f"{server_name}."}
        if name_prefix:
            candidates.add(name_prefix)
        return any(tool_name.startswith(c) for c in candidates)

    kept: list[BaseTool] = []
    for tool in tools:
        applicable_policies = [
            entry
            for entry in policy.mcp_servers
            if _matches(tool, entry.name, entry.name_prefix)
        ]
        if not applicable_policies:
            kept.append(tool)
            continue
        # If any matching server policy admits this tool for the current
        # mode/phase/subagent, keep it. Multiple policies for the same prefix
        # are treated as union, which lines up with how mcp servers are listed.
        admitted = False
        for entry in applicable_policies:
            if mode and mode not in entry.mode:
                continue
            if phase and phase not in entry.phase:
                continue
            if subagent and not entry.subagent_visible:
                continue
            admitted = True
            break
        if admitted:
            kept.append(tool)
    return kept


