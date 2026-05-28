"""Tests for PlanEvaluatorMiddleware."""

from __future__ import annotations

import json
from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from src.agents.middlewares.plan_evaluator_middleware import (
    PlanEvaluatorMiddleware,
    _precheck_nodes,
)
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


def _make_middleware(**overrides):
    kwargs = {"router": _router(), "requested_model": "primary"}
    kwargs.update(overrides)
    return PlanEvaluatorMiddleware(**kwargs)


def _base_state(*, plan_evaluated=False, plan_extra: dict | None = None, nodes: list | None = None):
    plan = {"title": "Test Plan", "summary": "Do stuff", "domain": "generic", "acceptance_criteria": []}
    if plan_extra:
        plan.update(plan_extra)
    return {
        "messages": [HumanMessage(content="Build a thing")],
        "plan": plan,
        "todo_graph": {
            "nodes": nodes or [
                {"id": "todo-1", "content": "Research the topic", "status": "pending", "depends_on": []},
                {"id": "todo-2", "content": "Write summary", "status": "pending", "depends_on": ["todo-1"]},
            ],
            "ready_ids": ["todo-1"],
        },
        "plan_evaluated": plan_evaluated,
    }


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


def test_skips_when_already_evaluated():
    middleware = _make_middleware()
    state = _base_state(plan_evaluated=True)
    assert middleware.before_model(state, _runtime()) is None


def test_skips_when_no_todo_graph():
    middleware = _make_middleware()
    state = {"plan": {"title": "Test"}, "plan_evaluated": False}
    assert middleware.before_model(state, _runtime()) is None


def test_skips_when_no_plan():
    middleware = _make_middleware()
    state = {"todo_graph": {"nodes": [], "ready_ids": []}, "plan_evaluated": False}
    assert middleware.before_model(state, _runtime()) is None


# ---------------------------------------------------------------------------
# Pre-checks (no LLM call required)
# ---------------------------------------------------------------------------


def test_precheck_passes_clean_plan():
    nodes = [
        {"id": "todo-1", "content": "A", "depends_on": []},
        {"id": "todo-2", "content": "B", "depends_on": ["todo-1"]},
    ]
    cleaned, fixes, fatal = _precheck_nodes(nodes)
    assert fatal is False
    assert fixes == []
    assert [n["id"] for n in cleaned] == ["todo-1", "todo-2"]


def test_precheck_drops_dangling_deps():
    nodes = [
        {"id": "todo-1", "content": "A", "depends_on": ["does-not-exist"]},
        {"id": "todo-2", "content": "B", "depends_on": ["todo-1", "ghost"]},
    ]
    cleaned, fixes, fatal = _precheck_nodes(nodes)
    assert fatal is False
    assert any("dangling" in f for f in fixes)
    assert cleaned[0]["depends_on"] == []
    assert cleaned[1]["depends_on"] == ["todo-1"]


def test_precheck_renumbers_bad_ids():
    nodes = [
        {"id": "plan-1", "content": "A", "depends_on": []},
        {"id": "plan-2", "content": "B", "depends_on": ["plan-1"]},
    ]
    cleaned, fixes, fatal = _precheck_nodes(nodes)
    assert fatal is False
    assert any("renumbered" in f for f in fixes)
    assert [n["id"] for n in cleaned] == ["todo-1", "todo-2"]
    assert cleaned[1]["depends_on"] == ["todo-1"]


def test_precheck_detects_cycle():
    nodes = [
        {"id": "todo-1", "content": "A", "depends_on": ["todo-2"]},
        {"id": "todo-2", "content": "B", "depends_on": ["todo-1"]},
    ]
    _cleaned, _fixes, fatal = _precheck_nodes(nodes)
    assert fatal is True


def test_precheck_cycle_short_circuits_llm(monkeypatch):
    """Cycles must skip the LLM call entirely."""
    call_count = {"n": 0}

    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            call_count["n"] += 1
            return SimpleNamespace(content='{"ok": true}')

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware()
    state = _base_state(nodes=[
        {"id": "todo-1", "content": "A", "depends_on": ["todo-2"]},
        {"id": "todo-2", "content": "B", "depends_on": ["todo-1"]},
    ])
    result = middleware.before_model(state, _runtime())
    assert result == {"plan_evaluated": True}
    assert call_count["n"] == 0


# ---------------------------------------------------------------------------
# LLM happy path
# ---------------------------------------------------------------------------


def test_marks_evaluated_on_llm_ok(monkeypatch):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content='{"ok": true}')

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware()
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result["plan_evaluated"] is True
    assert result.get("plan_eval_attempts") == 1
    # OK path does not touch the graph.
    assert "todo_graph" not in result


def test_marks_evaluated_on_issues_without_revision(monkeypatch):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(
                content='{"ok": false, "issues": ["Missing final step"], "advice": "Add a delivery step."}'
            )

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware(max_attempts=1)
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result["plan_evaluated"] is True
    # No revision → graph unchanged.
    assert "todo_graph" not in result


# ---------------------------------------------------------------------------
# Patch contract
# ---------------------------------------------------------------------------


def test_patch_modify_preserves_untouched_rich_fields(monkeypatch):
    """A `modify` op that only touches `depends_on` must not strip rich fields."""
    plan_extra = {
        "todos": [
            {
                "id": "todo-1",
                "content": "Research",
                "depends_on": [],
                "objective": "Phase 1 objective",
                "failure_fallback": "fallback A",
                "steps": [{"description": "search", "completion_requirement": "20 results"}],
            },
            {
                "id": "todo-2",
                "content": "Write summary",
                "depends_on": [],
                "objective": "Phase 2 objective",
                "failure_fallback": "fallback B",
            },
        ],
    }
    nodes = [
        {
            "id": "todo-1",
            "content": "Research",
            "status": "pending",
            "depends_on": [],
            "objective": "Phase 1 objective",
            "failure_fallback": "fallback A",
            "steps": [{"description": "search", "completion_requirement": "20 results"}],
        },
        {
            "id": "todo-2",
            "content": "Write summary",
            "status": "pending",
            "depends_on": [],
            "objective": "Phase 2 objective",
            "failure_fallback": "fallback B",
        },
    ]

    response = {
        "ok": False,
        "issues": ["Write should depend on Research"],
        "advice": "Add a depends_on link.",
        "patch": [{"op": "modify", "id": "todo-2", "fields": {"depends_on": ["todo-1"]}}],
    }

    # Track sequential responses so we can have the second call return ok.
    responses = [json.dumps(response), '{"ok": true}']

    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content=responses.pop(0))

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware(max_attempts=3)
    state = _base_state(plan_extra=plan_extra, nodes=nodes)
    result = middleware.before_model(state, _runtime())

    new_nodes = result["todo_graph"]["nodes"]
    todo2 = next(n for n in new_nodes if n["id"] == "todo-2")
    assert todo2["depends_on"] == ["todo-1"]
    assert todo2["objective"] == "Phase 2 objective"
    assert todo2["failure_fallback"] == "fallback B"
    # todo-1 untouched.
    todo1 = next(n for n in new_nodes if n["id"] == "todo-1")
    assert todo1["objective"] == "Phase 1 objective"
    assert todo1["steps"]


def test_patch_modify_that_strips_rich_field_is_rejected(monkeypatch):
    nodes = [
        {
            "id": "todo-1",
            "content": "Research",
            "status": "pending",
            "depends_on": [],
            "objective": "Original objective",
            "failure_fallback": "fallback A",
        },
    ]
    response = {
        "ok": False,
        "issues": ["restructure"],
        "advice": "rewrite",
        "patch": [{"op": "modify", "id": "todo-1", "fields": {"failure_fallback": ""}}],
    }

    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content=json.dumps(response))

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware(max_attempts=1)
    state = _base_state(nodes=nodes)
    result = middleware.before_model(state, _runtime())
    # Rejected → graph unchanged.
    assert "todo_graph" not in result
    assert result["plan_evaluated"] is True


def test_patch_add_appends_new_todo(monkeypatch):
    """`add` op should append a final-delivery todo."""
    responses = [
        json.dumps({
            "ok": False,
            "issues": ["Missing delivery step"],
            "advice": "Append a final delivery todo.",
            "patch": [
                {
                    "op": "add",
                    "after_id": "todo-2",
                    "todo": {
                        "id": "todo-3",
                        "content": "Deliver final summary",
                        "depends_on": ["todo-2"],
                    },
                }
            ],
        }),
        '{"ok": true}',
    ]

    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content=responses.pop(0))

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware(max_attempts=3)
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    nodes = result["todo_graph"]["nodes"]
    assert len(nodes) == 3
    assert nodes[2]["id"] == "todo-3"
    assert nodes[2]["depends_on"] == ["todo-2"]


def test_patch_remove_drops_todo(monkeypatch):
    responses = [
        json.dumps({
            "ok": False,
            "issues": ["Filler step"],
            "advice": "Remove the filler.",
            "patch": [{"op": "remove", "id": "todo-2"}],
        }),
        '{"ok": true}',
    ]

    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content=responses.pop(0))

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware(max_attempts=3)
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    nodes = result["todo_graph"]["nodes"]
    assert [n["id"] for n in nodes] == ["todo-1"]


# ---------------------------------------------------------------------------
# Re-eval loop / max_attempts
# ---------------------------------------------------------------------------


def test_reeval_loop_terminates_on_ok(monkeypatch):
    """First call returns issues + patch, second call returns ok → 2 attempts, ok decision."""
    responses = [
        json.dumps({
            "ok": False,
            "issues": ["Missing dep"],
            "advice": "Add dep.",
            "patch": [{"op": "modify", "id": "todo-2", "fields": {"depends_on": ["todo-1"]}}],
        }),
        '{"ok": true}',
    ]
    call_count = {"n": 0}

    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            call_count["n"] += 1
            return SimpleNamespace(content=responses.pop(0))

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware(max_attempts=3)
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert call_count["n"] == 2
    assert result["plan_eval_attempts"] == 2
    assert "todo_graph" in result


def test_reeval_loop_hits_max_attempts(monkeypatch):
    """Persistent issues → cap on attempts, plan still committed."""
    persistent = json.dumps({
        "ok": False,
        "issues": ["still broken"],
        "advice": "rewrite",
        "patch": [{"op": "modify", "id": "todo-2", "fields": {"depends_on": ["todo-1"]}}],
    })

    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content=persistent)

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware(max_attempts=2)
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result["plan_eval_attempts"] == 2
    assert result["plan_evaluated"] is True


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_marks_evaluated_on_timeout(monkeypatch):
    import time

    class _SlowModel:
        def invoke(self, prompt):  # noqa: ARG002
            time.sleep(10)
            return SimpleNamespace(content='{"ok": true}')

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _SlowModel())
    middleware = _make_middleware(timeout_seconds=0.05, max_attempts=1)
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result["plan_evaluated"] is True
    assert "todo_graph" not in result


def test_marks_evaluated_on_invalid_json(monkeypatch):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content="This is not JSON")

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware(max_attempts=1)
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result["plan_evaluated"] is True
    assert "todo_graph" not in result


def test_marks_evaluated_on_llm_exception(monkeypatch):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            raise RuntimeError("API down")

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware(max_attempts=1)
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result["plan_evaluated"] is True


# ---------------------------------------------------------------------------
# Legacy revised_todos contract (back-compat)
# ---------------------------------------------------------------------------


def test_legacy_revised_todos_still_applies(monkeypatch):
    revised = [
        {"id": "todo-1", "content": "Research the topic", "status": "pending", "depends_on": []},
        {"id": "todo-2", "content": "Write summary", "status": "pending", "depends_on": ["todo-1"]},
        {"id": "todo-3", "content": "Final delivery", "status": "pending", "depends_on": ["todo-2"]},
    ]

    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content=json.dumps({"ok": False, "issues": ["Missing final"], "revised_todos": revised}))

    monkeypatch.setattr("src.agents.middlewares.plan_evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = _make_middleware(max_attempts=1)
    state = _base_state()
    result = middleware.before_model(state, _runtime())
    assert result["plan_evaluated"] is True
    assert len(result["todo_graph"]["nodes"]) == 3
    assert result["todo_graph"]["nodes"][2]["id"] == "todo-3"
