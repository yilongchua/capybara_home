"""Tests for PlanEvaluatorMiddleware."""

from __future__ import annotations

import json
from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from src.agents.middlewares.plan_evaluator_middleware import PlanEvaluatorMiddleware
from src.config.app_config import AppConfig
from src.config.model_config import ModelConfig
from src.config.routing_config import RoutingConfig
from src.config.sandbox_config import SandboxConfig
from src.models.router import ModelRouter


def _router() -> ModelRouter:
    cfg = AppConfig(
        models=[
            ModelConfig(
                name="primary",
                display_name="primary",
                description=None,
                use="langchain_openai:ChatOpenAI",
                model="primary",
                supports_thinking=True,
            )
        ],
        sandbox=SandboxConfig(use="src.sandbox.local:LocalSandboxProvider"),
    )
    cfg.routing = RoutingConfig(stages={"planner": "primary"}, fallback="primary")
    return ModelRouter(app_config=cfg)


def _runtime():
    return SimpleNamespace(context={"thread_id": "thread-1"})


def _make_middleware():
    return PlanEvaluatorMiddleware(router=_router(), requested_model="primary")


def _base_state(*, plan_evaluated=False):
    return {
        "messages": [HumanMessage(content="Build a thing")],
        "plan": {"title": "Test Plan", "summary": "Do stuff"},
        "todo_graph": {
            "nodes": [
                {"id": "todo-1", "content": "Research the topic", "status": "pending", "depends_on": []},
                {"id": "todo-2", "content": "Write summary", "status": "pending", "depends_on": ["todo-1"]},
            ],
            "ready_ids": ["todo-1"],
        },
        "plan_evaluated": plan_evaluated,
    }


def test_skips_when_already_evaluated():
    middleware = _make_middleware()
    state = _base_state(plan_evaluated=True)
    result = middleware.before_model(state, _runtime())
    assert result is None


def test_skips_when_no_todo_graph():
    middleware = _make_middleware()
    state = {
        "plan": {"title": "Test"},
        "plan_evaluated": False,
    }
    result = middleware.before_model(state, _runtime())
    assert result is None


def test_skips_when_no_plan():
    middleware = _make_middleware()
    state = {
        "todo_graph": {"nodes": [], "ready_ids": []},
        "plan_evaluated": False,
    }
    result = middleware.before_model(state, _runtime())
    assert result is None


def test_marks_evaluated_on_llm_ok(monkeypatch):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content='{"ok": true}')

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware()
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result == {"plan_evaluated": True}


def test_marks_evaluated_on_issues_without_revision(monkeypatch):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content='{"ok": false, "issues": ["Missing final step"], "revised_todos": null}')

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware()
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result == {"plan_evaluated": True}


def test_applies_revised_todos_when_provided(monkeypatch):
    revised = [
        {"id": "todo-1", "content": "Research the topic", "status": "pending", "depends_on": []},
        {"id": "todo-2", "content": "Write summary", "status": "pending", "depends_on": ["todo-1"]},
        {"id": "todo-3", "content": "Final delivery", "status": "pending", "depends_on": ["todo-2"]},
    ]

    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content=json.dumps({"ok": False, "issues": ["Missing final step"], "revised_todos": revised}))

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware()
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result is not None
    assert result["plan_evaluated"] is True
    assert len(result["todo_graph"]["nodes"]) == 3
    assert result["todo_graph"]["nodes"][2]["id"] == "todo-3"


def test_marks_evaluated_on_timeout(monkeypatch):
    import time

    class _SlowModel:
        def invoke(self, prompt):  # noqa: ARG002
            time.sleep(10)  # Will be killed by timeout
            return SimpleNamespace(content='{"ok": true}')

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _SlowModel())
    middleware = PlanEvaluatorMiddleware(router=_router(), requested_model="primary", timeout_seconds=0.05)
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result == {"plan_evaluated": True}


def test_marks_evaluated_on_invalid_json(monkeypatch):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content="This is not JSON")

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware()
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result == {"plan_evaluated": True}


def test_marks_evaluated_on_llm_exception(monkeypatch):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            raise RuntimeError("API down")

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware()
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result == {"plan_evaluated": True}
