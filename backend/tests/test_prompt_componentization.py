"""Tests for componentized prompt rendering, progressive skill prompt section, and SOUL.md injection."""

from __future__ import annotations

import pytest

from src.agents.lead_agent import prompt as prompt_module
from src.config.agents_config import load_agent_soul
from src.config.app_config import AppConfig, set_app_config
from src.config.model_config import ModelConfig
from src.config.prompt_config import PromptConfig, set_prompt_config
from src.config.sandbox_config import SandboxConfig
from src.config.skills_config import SkillsConfig


def _make_app_config(progressive_disclosure: bool) -> AppConfig:
    return AppConfig(
        models=[
            ModelConfig(
                name="default-model",
                display_name="default-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="default-model",
                supports_thinking=False,
            )
        ],
        sandbox=SandboxConfig(use="src.sandbox.local:LocalSandboxProvider"),
        skills=SkillsConfig(progressive_disclosure=progressive_disclosure),
    )


def test_componentized_and_legacy_prompt_both_render(monkeypatch):
    monkeypatch.setattr(prompt_module, "_get_memory_context", lambda agent_name=None: "")
    monkeypatch.setattr(prompt_module, "get_agent_soul", lambda _: "")
    monkeypatch.setattr(prompt_module, "get_skills_prompt_section", lambda _: "")

    set_prompt_config(PromptConfig(componentized=True))
    componentized = prompt_module._build_prompt(False, 3, None, None)
    assert "<thinking_style>" in componentized
    assert "<critical_reminders>" in componentized

    set_prompt_config(PromptConfig(componentized=False))
    legacy = prompt_module._build_prompt(False, 3, None, None)
    assert "<thinking_style>" in legacy
    assert "<critical_reminders>" in legacy


def test_skills_prompt_section_uses_progressive_instructions(monkeypatch):
    set_app_config(_make_app_config(progressive_disclosure=True))
    monkeypatch.setattr(
        prompt_module,
        "load_skills",
        lambda enabled_only=True: [
            type(
                "SkillStub",
                (),
                {
                    "name": "excel",
                    "description": "Spreadsheet automation",
                    "paths": ["**/*.xlsx"],
                    "get_container_file_path": lambda self, base="/mnt/skills": f"{base}/excel/SKILL.md",
                },
            )()
        ],
    )

    section = prompt_module.get_skills_prompt_section()
    assert "full skill bodies are loaded progressively" in section
    assert "<paths>**/*.xlsx</paths>" in section


# ---------------------------------------------------------------------------
# SOUL.md tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent_root(tmp_path):
    """Return a tmp_path-rooted Paths instance with an `agents/research` subdirectory."""
    agent_dir = tmp_path / "agents" / "research"
    agent_dir.mkdir(parents=True)
    return tmp_path


def _make_paths(base_dir):
    from src.config.paths import Paths
    return Paths(base_dir=str(base_dir))


def test_load_agent_soul_returns_content_when_file_exists(agent_root, monkeypatch):
    (agent_root / "agents" / "research" / "SOUL.md").write_text("You are a meticulous research agent.")
    monkeypatch.setattr("src.config.agents_config.get_paths", lambda: _make_paths(agent_root))
    assert load_agent_soul("research") == "You are a meticulous research agent."


def test_load_agent_soul_returns_none_when_file_absent(agent_root, monkeypatch):
    monkeypatch.setattr("src.config.agents_config.get_paths", lambda: _make_paths(agent_root))
    assert load_agent_soul("research") is None


def test_load_agent_soul_returns_none_for_whitespace_only_file(agent_root, monkeypatch):
    (agent_root / "agents" / "research" / "SOUL.md").write_text("   \n\n  ")
    monkeypatch.setattr("src.config.agents_config.get_paths", lambda: _make_paths(agent_root))
    assert load_agent_soul("research") is None


def test_load_agent_soul_strips_surrounding_whitespace(agent_root, monkeypatch):
    (agent_root / "agents" / "research" / "SOUL.md").write_text("\n\nBe precise.\n\n")
    monkeypatch.setattr("src.config.agents_config.get_paths", lambda: _make_paths(agent_root))
    assert load_agent_soul("research") == "Be precise."


def test_load_agent_soul_none_agent_name_reads_base_dir(tmp_path, monkeypatch):
    # When agent_name is None, the loader checks base_dir/SOUL.md (global soul)
    (tmp_path / "SOUL.md").write_text("Global soul content.")
    monkeypatch.setattr("src.config.agents_config.get_paths", lambda: _make_paths(tmp_path))
    assert load_agent_soul(None) == "Global soul content."


def test_get_agent_soul_wraps_content_in_xml_tags(monkeypatch):
    monkeypatch.setattr("src.agents.lead_agent.prompt.load_agent_soul", lambda name: "Be precise.")
    result = prompt_module.get_agent_soul("research")
    assert "<soul>" in result
    assert "Be precise." in result
    assert "</soul>" in result


def test_get_agent_soul_returns_empty_string_when_no_soul(monkeypatch):
    monkeypatch.setattr("src.agents.lead_agent.prompt.load_agent_soul", lambda name: None)
    assert prompt_module.get_agent_soul("research") == ""


def test_build_componentized_prompt_contains_soul(monkeypatch):
    monkeypatch.setattr(prompt_module, "_get_memory_context", lambda agent_name=None: "")
    monkeypatch.setattr(prompt_module, "get_agent_soul", lambda name: "<soul>\nBe precise.\n</soul>")
    monkeypatch.setattr(prompt_module, "get_skills_prompt_section", lambda _: "")
    set_prompt_config(PromptConfig(componentized=True))
    result = prompt_module._build_prompt(False, 3, "research", None)
    assert "Be precise." in result


def test_build_legacy_prompt_contains_soul(monkeypatch):
    monkeypatch.setattr(prompt_module, "_get_memory_context", lambda agent_name=None: "")
    monkeypatch.setattr(prompt_module, "get_agent_soul", lambda name: "<soul>\nBe methodical.\n</soul>")
    monkeypatch.setattr(prompt_module, "get_skills_prompt_section", lambda _: "")
    set_prompt_config(PromptConfig(componentized=False))
    result = prompt_module._build_prompt(False, 3, "research", None)
    assert "Be methodical." in result


def test_build_prompt_has_no_soul_block_when_absent(monkeypatch):
    monkeypatch.setattr(prompt_module, "_get_memory_context", lambda agent_name=None: "")
    monkeypatch.setattr(prompt_module, "get_agent_soul", lambda name: "")
    monkeypatch.setattr(prompt_module, "get_skills_prompt_section", lambda _: "")
    set_prompt_config(PromptConfig(componentized=True))
    result = prompt_module._build_prompt(False, 3, None, None)
    assert "<soul>" not in result
