"""Parity tests for the JSON-driven tool path.

Notes on the surface area:
- Legacy `BUILTIN_TOOLS` mixes 4 first-party builtins (present_files,
  ask_user_for_clarification, recall, write_todos) with 3 community tools
  (web_search, knowledge-vault search/save). Sandbox tools
  (bash/ls/read_file/write_file/str_replace) are sourced separately from
  `config.yaml`'s `tools:` section.
- `internal_tools.json` consolidates the first-party builtins + sandbox tools.
  Community tools stay in config.yaml (Phase 3 scope).
- Both paths feed into `get_available_tools`; community tools come from
  `loaded_tools` regardless of flag.
"""

from __future__ import annotations

import pytest

from src.config import get_app_config
from src.tools.tools import (
    BUILTIN_TOOLS,
    _build_builtin_tools_from_json,
    get_available_tools,
)

# First-party (non-community) builtins that exist in both paths.
FIRST_PARTY_NAMES = {"present_files", "ask_user_for_clarification", "recall", "write_todos"}
SANDBOX_NAMES = {"bash", "ls", "read_file", "write_file", "str_replace"}
COMMUNITY_NAMES = {"web_search", "query_knowledge_vault", "save_to_knowledge_vault"}


@pytest.fixture(autouse=True)
def _reset_json_flag():
    config = get_app_config()
    original = getattr(config, "json_driven_tools", False)
    yield
    config.json_driven_tools = original


def _names(tools) -> set[str]:
    return {tool.name for tool in tools}


def test_json_builtin_subset_includes_first_party_and_sandbox() -> None:
    tools = _names(_build_builtin_tools_from_json(subagent_enabled=False, supports_vision=False))
    assert FIRST_PARTY_NAMES.issubset(tools)
    assert SANDBOX_NAMES.issubset(tools)
    # Community tools without a JSON entry are carried over from BUILTIN_TOOLS,
    # so flipping the flag doesn't shrink the catalog.
    assert COMMUNITY_NAMES.issubset(tools)


def test_json_builtin_excludes_vision_and_subagent_by_default() -> None:
    tools = _names(_build_builtin_tools_from_json(subagent_enabled=False, supports_vision=False))
    assert "view_image" not in tools
    assert "task" not in tools


def test_json_builtin_includes_task_when_subagent_enabled() -> None:
    tools = _names(_build_builtin_tools_from_json(subagent_enabled=True, supports_vision=False))
    assert "task" in tools


def test_json_builtin_includes_view_image_when_vision_supported() -> None:
    tools = _names(_build_builtin_tools_from_json(subagent_enabled=False, supports_vision=True))
    assert "view_image" in tools


def test_get_available_tools_flag_off_uses_legacy_path() -> None:
    config = get_app_config()
    config.json_driven_tools = False
    tools = _names(get_available_tools(include_mcp=False, subagent_enabled=False))
    for legacy in BUILTIN_TOOLS:
        assert legacy.name in tools


def test_get_available_tools_flag_on_keeps_all_legacy_surface() -> None:
    config = get_app_config()
    config.json_driven_tools = True
    tools = _names(get_available_tools(include_mcp=False, subagent_enabled=False))
    # First-party builtins, community tools (from config.yaml), and sandbox tools
    # should all appear in the JSON-driven catalog.
    for legacy in BUILTIN_TOOLS:
        assert legacy.name in tools, f"Missing in JSON path: {legacy.name}"
    assert SANDBOX_NAMES.issubset(tools)


def test_get_available_tools_descriptions_overridden_when_flag_on() -> None:
    config = get_app_config()
    config.json_driven_tools = True
    by_name = {t.name: t for t in get_available_tools(include_mcp=False, subagent_enabled=False)}
    # `recall` was a one-line description in the docstring; JSON expands it.
    assert by_name["recall"].description.startswith("Search long-term memory")
    # Sandbox `bash` description now comes from JSON, not the docstring.
    assert "thread sandbox" in by_name["bash"].description.lower()


def test_get_available_tools_descriptions_unchanged_when_flag_off() -> None:
    config = get_app_config()
    config.json_driven_tools = False
    by_name = {t.name: t for t in get_available_tools(include_mcp=False, subagent_enabled=False)}
    # Legacy path keeps the docstring-derived description; recall's was one sentence.
    assert "long-term memory" in by_name["recall"].description.lower()
