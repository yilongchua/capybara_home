"""Unit tests for the JSON-driven tool loader (Phase 1 contract)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain.tools import BaseTool, tool

from src.tools.loader import (
    POLICY_ATTR,
    ToolDefinitionError,
    build_structured_tool,
    get_tool_policy,
    load_external_policy,
    load_tool_definitions,
    schema_drift_report,
)
from src.tools.schema import ToolDefinition


@tool("echo_fixture", parse_docstring=True)
def echo_fixture_tool(message: str, count: int = 1) -> str:
    """Echo the message back the given number of times.

    Args:
        message: Text to echo.
        count: How many times to repeat the message.
    """
    return " ".join([message] * count)


# Re-exposed at module scope so resolve_variable can find it via dotted path.
HANDLER_PATH = f"{__name__}:echo_fixture_tool"


def _make_defn(**overrides) -> ToolDefinition:
    payload = {
        "name": "echo_fixture",
        "description": "Repeat a message N times.",
        "handler": HANDLER_PATH,
        "parameters": {
            "type": "object",
            "required": ["message"],
            "properties": {
                "message": {"type": "string", "description": "Text to echo."},
                "count": {"type": "integer", "description": "How many times to repeat."},
            },
        },
    }
    payload.update(overrides)
    return ToolDefinition.model_validate(payload)


def test_load_tool_definitions_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_tool_definitions(tmp_path / "missing.json") == []


def test_load_tool_definitions_malformed_json_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid", encoding="utf-8")
    with pytest.raises(ToolDefinitionError):
        load_tool_definitions(bad)


def test_load_tool_definitions_rejects_non_array(tmp_path: Path) -> None:
    f = tmp_path / "obj.json"
    f.write_text(json.dumps({"name": "x"}), encoding="utf-8")
    with pytest.raises(ToolDefinitionError):
        load_tool_definitions(f)


def test_load_tool_definitions_round_trip(tmp_path: Path) -> None:
    defn = _make_defn()
    target = tmp_path / "internal_tools.json"
    target.write_text(json.dumps([defn.model_dump()]), encoding="utf-8")
    loaded = load_tool_definitions(target)
    assert len(loaded) == 1
    assert loaded[0].name == "echo_fixture"
    assert loaded[0].handler == HANDLER_PATH


def test_build_structured_tool_overrides_description() -> None:
    defn = _make_defn(description="New description from JSON.")
    built = build_structured_tool(defn)
    assert isinstance(built, BaseTool)
    assert built.name == "echo_fixture"
    assert built.description == "New description from JSON."
    # Policy is attached for downstream middlewares.
    assert getattr(built, POLICY_ATTR) is defn
    assert get_tool_policy(built) is defn


def test_build_structured_tool_invokes_handler() -> None:
    built = build_structured_tool(_make_defn())
    result = built.invoke({"message": "hi", "count": 3})
    assert result == "hi hi hi"


def test_build_structured_tool_name_mismatch_raises() -> None:
    defn = _make_defn(name="not_the_handler_name")
    with pytest.raises(ToolDefinitionError):
        build_structured_tool(defn)


def test_build_structured_tool_rejects_non_basetool() -> None:
    # Point at a regular function, not a @tool-decorated one.
    defn = _make_defn(handler="json:loads")
    with pytest.raises(ToolDefinitionError):
        build_structured_tool(defn)


def test_schema_drift_report_clean_for_aligned_defn() -> None:
    defn = _make_defn()
    built = build_structured_tool(defn)
    assert schema_drift_report(defn, built) == []


def test_schema_drift_report_flags_extra_json_arg() -> None:
    defn = _make_defn(
        parameters={
            "type": "object",
            "required": ["message"],
            "properties": {
                "message": {"type": "string"},
                "count": {"type": "integer"},
                "ghost": {"type": "string"},
            },
        }
    )
    built = build_structured_tool(defn)
    drift = schema_drift_report(defn, built)
    assert any("ghost" in line for line in drift)


def test_schema_drift_report_flags_missing_json_arg() -> None:
    defn = _make_defn(
        parameters={
            "type": "object",
            "required": ["message"],
            "properties": {
                "message": {"type": "string"},
            },
        }
    )
    built = build_structured_tool(defn)
    drift = schema_drift_report(defn, built)
    assert any("count" in line for line in drift)


def test_load_external_policy_defaults_when_missing(tmp_path: Path) -> None:
    policy = load_external_policy(tmp_path / "absent.json")
    assert policy.mcp_servers == []
    assert policy.cli_bridges == []


def test_load_external_policy_parses_entries(tmp_path: Path) -> None:
    target = tmp_path / "external_tools.json"
    target.write_text(
        json.dumps(
            {
                "mcp_servers": [
                    {"name": "filesystem", "mode": ["work"], "phase": ["approved"]}
                ],
                "cli_bridges": [],
            }
        ),
        encoding="utf-8",
    )
    policy = load_external_policy(target)
    assert len(policy.mcp_servers) == 1
    assert policy.mcp_servers[0].name == "filesystem"
    assert policy.mcp_servers[0].mode == ["work"]
