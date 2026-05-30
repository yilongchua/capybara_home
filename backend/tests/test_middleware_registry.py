"""Tests for middleware registry ordering and validation."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.agents.work_agent import agent as work_agent_module
from src.config.app_config import AppConfig
from src.config.model_config import ModelConfig
from src.config.sandbox_config import SandboxConfig


def _make_registry_ctx(*, is_plan_mode: bool, is_work_mode: bool) -> work_agent_module._RegistryContext:
    return work_agent_module._RegistryContext(
        is_plan_mode=is_plan_mode,
        is_work_mode=is_work_mode,
        subagent_enabled=False,
        max_concurrent_subagents=1,
        max_primary_per_turn=1,
        model_name="default-model",
        agent_name=None,
        model_config=None,
        router=Mock(),
    )


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
    monkeypatch.setattr(work_agent_module, "get_app_config", lambda: _make_app_config(supports_vision=True))
    monkeypatch.setattr(work_agent_module, "_create_summarization_middleware", lambda: None)
    monkeypatch.setattr(work_agent_module, "_create_todo_list_middleware", lambda _: None)

    registry = work_agent_module._build_middleware_registry(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
        model_name="default-model",
    )
    ordered = work_agent_module.topological_sort_middleware_specs(registry)
    names = [spec.name for spec in ordered]

    assert names[-1] == "clarification"
    assert names.index("thread_data") < names.index("steering")
    assert names.index("steering") < names.index("uploads")
    assert names.index("thread_data") < names.index("sandbox")
    assert names.index("plan_execution_gate") < names.index("permissions")
    assert names.index("metrics") < names.index("clarification")


def test_registry_raises_for_unknown_dependency():
    spec = work_agent_module.MiddlewareSpec(name="a", factory=lambda: None, after={"missing"})
    with pytest.raises(ValueError, match="unknown middleware 'missing'"):
        work_agent_module.topological_sort_middleware_specs([spec])


def test_registry_detects_dependency_cycle():
    specs = [
        work_agent_module.MiddlewareSpec(name="a", factory=lambda: None, after={"b"}),
        work_agent_module.MiddlewareSpec(name="b", factory=lambda: None, after={"a"}),
    ]
    with pytest.raises(ValueError, match="dependency cycle detected"):
        work_agent_module.topological_sort_middleware_specs(specs)


def test_registry_priority_tie_breaks_before_alphabet():
    # Without priority, alphabetical order would put "alpha" before "zulu".
    # Setting zulu.priority=-1 must push zulu ahead.
    specs = [
        work_agent_module.MiddlewareSpec(name="alpha", factory=lambda: None),
        work_agent_module.MiddlewareSpec(name="zulu", factory=lambda: None, priority=-1),
    ]
    ordered = work_agent_module.topological_sort_middleware_specs(specs)
    assert [spec.name for spec in ordered] == ["zulu", "alpha"]


def test_registry_clarification_always_last_even_with_new_siblings(monkeypatch):
    """Guardrail: ClarificationMiddleware must stay last so it can interrupt after every other hook."""
    monkeypatch.setattr(work_agent_module, "get_app_config", lambda: _make_app_config())
    monkeypatch.setattr(work_agent_module, "_create_summarization_middleware", lambda: None)
    monkeypatch.setattr(work_agent_module, "_create_todo_list_middleware", lambda _: None)

    registry = work_agent_module._build_middleware_registry(
        {"configurable": {"is_plan_mode": True, "subagent_enabled": True}},
        model_name="default-model",
    )
    ordered = work_agent_module.topological_sort_middleware_specs(registry)
    names = [spec.name for spec in ordered]
    assert names[-1] == "clarification", (
        f"clarification must be the last middleware; got {names[-1]}. Full order: {names}"
    )


def test_plan_followup_factory_skips_in_work_mode():
    """Work-mode runs should not instantiate PlanFollowupMiddleware (#19)."""
    ctx = _make_registry_ctx(is_plan_mode=False, is_work_mode=True)
    assert work_agent_module._create_plan_followup(ctx) is None


def test_plan_followup_factory_enabled_in_plan_mode():
    ctx = _make_registry_ctx(is_plan_mode=True, is_work_mode=False)
    middleware = work_agent_module._create_plan_followup(ctx)
    assert middleware is not None
    assert middleware.__class__.__name__ == "PlanFollowupMiddleware"


def test_trajectory_wraps_inner_middlewares(monkeypatch):
    """#28: TrajectoryMiddleware must be the OUTERMOST wrap_*_call wrapper.

    Spec order = wrap order: the spec appearing first in the topologically
    sorted list is the outermost wrapper. `trajectory` declares only
    `after={"thread_data"}`, so it must land before middlewares that wrap
    model/tool calls (model_timeout, retry, subagent_limit, ...).
    """
    monkeypatch.setattr(work_agent_module, "get_app_config", lambda: _make_app_config())
    monkeypatch.setattr(work_agent_module, "_create_summarization_middleware", lambda: None)
    monkeypatch.setattr(work_agent_module, "_create_todo_list_middleware", lambda _: None)

    registry = work_agent_module._build_middleware_registry(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
        model_name="default-model",
    )
    ordered = work_agent_module.topological_sort_middleware_specs(registry)
    names = [spec.name for spec in ordered]

    trajectory_idx = names.index("trajectory")
    for inner in ("model_timeout", "retry", "subagent_limit", "tool_result_truncation"):
        assert trajectory_idx < names.index(inner), (
            f"trajectory must wrap {inner}; got trajectory at {trajectory_idx} and {inner} at {names.index(inner)}"
        )


def test_work_mode_middleware_list_omits_plan_followup(monkeypatch):
    """#19 end-to-end: factories that gate on `is_plan_mode` must not produce a PlanFollowupMiddleware in work mode."""
    monkeypatch.setattr(work_agent_module, "get_app_config", lambda: _make_app_config())

    registry = work_agent_module._build_middleware_registry(
        {"configurable": {"is_plan_mode": False, "subagent_enabled": False}},
        model_name="default-model",
    )
    # Only invoke factories tied to `_create_plan_followup` to keep the test
    # focused on #19 without instantiating unrelated middlewares.
    plan_followup_spec = next(spec for spec in registry if spec.name == "plan_followup")
    assert plan_followup_spec.factory() is None
