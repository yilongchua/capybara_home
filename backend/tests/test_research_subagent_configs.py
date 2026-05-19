"""Tests for built-in research subagent configurations."""

from src.subagents.builtins import BUILTIN_SUBAGENTS
from src.subagents.registry import get_subagent_config, get_subagent_names, list_subagents

RESEARCH_SUBAGENTS = {
    "source-researcher",
    "docs-explorer",
    "comparison-dimension-researcher",
    "synthesis-reviewer",
}


def test_research_subagents_are_registered():
    names = set(get_subagent_names())

    assert RESEARCH_SUBAGENTS.issubset(names)


def test_registry_returns_research_subagent_configs():
    configs = {config.name: config for config in list_subagents()}

    for name in RESEARCH_SUBAGENTS:
        assert name in configs
        assert configs[name].description
        assert configs[name].system_prompt
        assert configs[name].model == "inherit"


def test_source_researcher_has_external_research_guidance():
    config = get_subagent_config("source-researcher")

    assert config is not None
    assert "web_search" in (config.tools or [])
    assert "task" in (config.disallowed_tools or [])
    assert "Source status" in config.system_prompt
    assert "If web_search fails once" in config.system_prompt


def test_docs_explorer_is_local_corpus_only():
    config = get_subagent_config("docs-explorer")

    assert config is not None
    assert set(config.tools or []) == {"ls", "read_file", "bash"}
    assert "web_search" in (config.disallowed_tools or [])
    assert "/mnt/user-data/workspace/.docs" in config.system_prompt
    assert "Do not infer facts" in config.system_prompt


def test_comparison_dimension_researcher_is_dimension_scoped():
    config = get_subagent_config("comparison-dimension-researcher")

    assert config is not None
    assert "web_search" in (config.tools or [])
    assert "recall" in (config.tools or [])
    assert "Compare only the assigned dimension" in config.system_prompt
    assert "Per-option findings" in config.system_prompt


def test_synthesis_reviewer_is_read_only_quality_gate():
    config = get_subagent_config("synthesis-reviewer")

    assert config is not None
    assert set(config.tools or []) == {"ls", "read_file"}
    assert "web_search" in (config.disallowed_tools or [])
    assert "Verdict" in config.system_prompt
    assert "Missing coverage" in config.system_prompt


def test_research_subagents_are_public_builtins():
    for name in RESEARCH_SUBAGENTS:
        assert BUILTIN_SUBAGENTS[name].name == name
