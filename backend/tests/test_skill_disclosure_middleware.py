"""Tests for progressive skill disclosure middleware."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from src.agents.middlewares.skill_disclosure_middleware import SkillDisclosureMiddleware
from src.config.app_config import AppConfig, set_app_config
from src.config.model_config import ModelConfig
from src.config.sandbox_config import SandboxConfig
from src.config.skills_config import SkillsConfig
from src.skills.types import Skill


def _make_skill(tmp_path: Path, name: str, body: str, paths: list[str] | None = None) -> Skill:
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(body, encoding="utf-8")
    return Skill(
        name=name,
        description=f"{name} description",
        license=None,
        skill_dir=skill_dir,
        skill_file=skill_file,
        relative_path=Path(name),
        category="public",
        enabled=True,
        paths=paths,
    )


def _set_app_config(*, progressive: bool = True, budget: int = 25000, matcher: bool = True) -> None:
    set_app_config(
        AppConfig(
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
            skills=SkillsConfig(
                progressive_disclosure=progressive,
                active_body_token_budget=budget,
                matcher_trigger_enabled=matcher,
            ),
        )
    )


def test_explicit_skill_activation_injects_active_skills(monkeypatch, tmp_path: Path):
    _set_app_config(progressive=True, budget=5000)
    skill = _make_skill(tmp_path, "excel", "# Excel skill\nsteps")
    monkeypatch.setattr("src.agents.middlewares.skill_disclosure_middleware.load_skills", lambda enabled_only=True: [skill])

    middleware = SkillDisclosureMiddleware()
    state = {"messages": [HumanMessage(content="Please use /excel for this task")]}
    result = middleware.before_model(state, SimpleNamespace(context={"thread_id": "t1"}))

    assert result is not None
    messages = result.get("messages", [])
    assert messages
    assert "active_skills" == messages[0].name
    assert "<name>excel</name>" in messages[0].content


def test_matcher_activation_uses_uploaded_paths(monkeypatch, tmp_path: Path):
    _set_app_config(progressive=True, budget=5000, matcher=True)
    skill = _make_skill(tmp_path, "spreadsheet", "# Spreadsheet skill", paths=["**/*.csv"])
    monkeypatch.setattr("src.agents.middlewares.skill_disclosure_middleware.load_skills", lambda enabled_only=True: [skill])

    middleware = SkillDisclosureMiddleware()
    state = {
        "messages": [HumanMessage(content="Summarize uploaded files")],
        "uploaded_files": [{"path": "/mnt/user-data/uploads/report.csv"}],
    }
    result = middleware.before_model(state, SimpleNamespace(context={"thread_id": "t1"}))

    assert result is not None
    assert result.get("messages")
    assert "<name>spreadsheet</name>" in result["messages"][0].content


def test_budget_keeps_most_recent_skill(monkeypatch, tmp_path: Path):
    _set_app_config(progressive=True, budget=1000)
    s1 = _make_skill(tmp_path, "one", "A" * 6000)
    s2 = _make_skill(tmp_path, "two", "B" * 400)
    monkeypatch.setattr("src.agents.middlewares.skill_disclosure_middleware.load_skills", lambda enabled_only=True: [s1, s2])

    middleware = SkillDisclosureMiddleware()
    state = {
        "messages": [HumanMessage(content="Use /two for this run")],
        "skill_disclosure": {"active": {"one": 1}, "turn": 1, "last_injected_hash": ""},
    }
    result = middleware.before_model(state, SimpleNamespace(context={"thread_id": "t1"}))

    assert result is not None
    content = result["messages"][0].content
    # tiny budget should keep the most recent/smallest viable activation
    assert "<name>two</name>" in content
