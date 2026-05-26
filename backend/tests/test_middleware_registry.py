"""Tests for middleware registry ordering and validation."""

from __future__ import annotations

import pytest

from src.agents.lead_agent import agent as lead_agent_module
from src.config.app_config import AppConfig
from src.config.model_config import ModelConfig
from src.config.sandbox_config import SandboxConfig


def _make_app_config(*, supports_vision: bool = False) -> AppConfig:
    return AppConfig(
        models=[
            ModelConfig(
                name="default-model",
                display_name="default-model",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="default-model",
                supports_thinking=False,
                supports_vision=supports_vision,
            )
        ],
        sandbox=SandboxConfig(use="src.sandbox.local:LocalSandboxProvider"),
    )


def test_registry_sorted_with_clarification_last(monkeypatch):
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: _make_app_config(supports_vision=True))
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda _: None)

    registry = lead_agent_module._build_middleware_registry(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
        model_name="default-model",
    )
    ordered = lead_agent_module._topological_sort_middleware_specs(registry)
    names = [spec.name for spec in ordered]

    assert names[-1] == "clarification"
    assert names.index("thread_data") < names.index("steering")
    assert names.index("steering") < names.index("uploads")
    assert names.index("thread_data") < names.index("sandbox")
    assert names.index("plan_execution_gate") < names.index("permissions")
    assert names.index("metrics") < names.index("clarification")


def test_registry_raises_for_unknown_dependency():
    spec = lead_agent_module.MiddlewareSpec(name="a", factory=lambda: None, after={"missing"})
    with pytest.raises(ValueError, match="unknown middleware 'missing'"):
        lead_agent_module._topological_sort_middleware_specs([spec])


def test_registry_detects_dependency_cycle():
    specs = [
        lead_agent_module.MiddlewareSpec(name="a", factory=lambda: None, after={"b"}),
        lead_agent_module.MiddlewareSpec(name="b", factory=lambda: None, after={"a"}),
    ]
    with pytest.raises(ValueError, match="dependency cycle detected"):
        lead_agent_module._topological_sort_middleware_specs(specs)


def test_registry_priority_tie_breaks_before_alphabet():
    # Without priority, alphabetical order would put "alpha" before "zulu".
    # Setting zulu.priority=-1 must push zulu ahead.
    specs = [
        lead_agent_module.MiddlewareSpec(name="alpha", factory=lambda: None),
        lead_agent_module.MiddlewareSpec(name="zulu", factory=lambda: None, priority=-1),
    ]
    ordered = lead_agent_module._topological_sort_middleware_specs(specs)
    assert [spec.name for spec in ordered] == ["zulu", "alpha"]


def test_registry_clarification_always_last_even_with_new_siblings(monkeypatch):
    """Guardrail: ClarificationMiddleware must stay last so it can interrupt after every other hook."""
    monkeypatch.setattr(lead_agent_module, "get_app_config", lambda: _make_app_config())
    monkeypatch.setattr(lead_agent_module, "_create_summarization_middleware", lambda: None)
    monkeypatch.setattr(lead_agent_module, "_create_todo_list_middleware", lambda _: None)

    registry = lead_agent_module._build_middleware_registry(
        {"configurable": {"is_plan_mode": True, "subagent_enabled": True}},
        model_name="default-model",
    )
    ordered = lead_agent_module._topological_sort_middleware_specs(registry)
    names = [spec.name for spec in ordered]
    assert names[-1] == "clarification", (
        f"clarification must be the last middleware; got {names[-1]}. Full order: {names}"
    )
