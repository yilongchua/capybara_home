"""Tests for planner and evaluator middlewares."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.middlewares.evaluator_middleware import EvaluatorMiddleware
from src.agents.middlewares.planner_middleware import PlannerMiddleware
from src.config.app_config import AppConfig
from src.config.evaluator_config import EvaluatorConfig
from src.config.handoffs_config import HandoffsConfig
from src.config.model_config import ModelConfig
from src.config.planner_config import PlannerConfig
from src.config.routing_config import RoutingConfig
from src.config.sandbox_config import SandboxConfig
from src.config.sprint_contracts_config import SprintContractsConfig
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
    cfg.routing = RoutingConfig(stages={"planner": "primary", "evaluator": "primary"}, fallback="primary")
    return ModelRouter(app_config=cfg)


def _runtime():
    return SimpleNamespace(context={"thread_id": "thread-1", "model_name": "primary"})


def test_planner_creates_plan_todos_and_handoffs(monkeypatch, tmp_path: Path):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(
                content=(
                    '{"title":"Build feature","summary":"Do work","todos":['
                    '{"id":"todo-1","content":"Build feature core","depends_on":[]},'
                    '{"id":"todo-2","content":"Write tests","depends_on":["todo-1"]}'
                    "]}"
                )
            )

    monkeypatch.setattr("src.agents.middlewares.planner_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = PlannerMiddleware(
        router=_router(),
        requested_model="primary",
        max_plan_steps=PlannerConfig().max_plan_steps,
        dag_enabled=True,
        handoffs_config=HandoffsConfig(enabled=True, dir=".handoffs"),
        sprint_contracts_config=SprintContractsConfig(enabled=True, min_todos_trigger=2),
    )
    state = {
        "messages": [HumanMessage(content="Please build this feature.")],
        "thread_data": {"workspace_path": str(tmp_path)},
    }
    update = middleware.before_model(state, _runtime())
    assert update is not None
    assert update["plan"]["title"] == "Build feature"
    assert len(update["todo_graph"]["nodes"]) == 2
    assert update["complexity_tier"] in {"moderate", "complex"}
    assert update["plan_evaluated"] is False
    assert (tmp_path / ".handoffs" / "plan.md").exists()
    assert (tmp_path / ".handoffs" / "sprint_contract.md").exists()
    assert update["plan"]["status"] == "draft"
    assert isinstance(update["plan"].get("plan_id"), str)


def test_planner_writes_versioned_plan_and_latest_alias(monkeypatch, tmp_path: Path):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(
                content=(
                    '{"title":"Audit platform","summary":"Stabilize planner workflow","todos":['
                    '{"id":"todo-1","content":"Audit current behavior","depends_on":[]}'
                    "]}"
                )
            )

    monkeypatch.setattr("src.agents.middlewares.planner_middleware.create_chat_model", lambda **kwargs: _Model())
    outputs = tmp_path / "outputs"
    workspace = tmp_path / "workspace"
    middleware = PlannerMiddleware(
        router=_router(),
        requested_model="primary",
        max_plan_steps=PlannerConfig().max_plan_steps,
        dag_enabled=True,
        handoffs_config=HandoffsConfig(enabled=True, dir=".handoffs"),
        sprint_contracts_config=SprintContractsConfig(enabled=True, min_todos_trigger=2),
    )
    state = {
        "messages": [HumanMessage(content="Please audit this workflow.")],
        "thread_data": {
            "workspace_path": str(workspace),
            "outputs_path": str(outputs),
            "uploads_path": str(tmp_path / "uploads"),
            "mounted_path": None,
        },
    }
    update = middleware.before_model(state, _runtime())
    assert update is not None
    assert "/outputs/plans/plan-" in str(update["plan"]["plan_path"])
    assert str(update["plan"]["latest_alias_path"]).endswith("/outputs/plan.md")
    assert (outputs / "plan.md").exists()
    versioned = list((outputs / "plans").glob("plan-*.md"))
    assert versioned, "versioned plan file must be written"


def test_planner_marks_research_ambiguity_as_clarification_pending(monkeypatch, tmp_path: Path):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(
                content=(
                    '{"title":"AI Trends Report","summary":"Research AI trends","domain":"research","todos":['
                    '{"id":"todo-1","content":"Research AI trends","depends_on":[]},'
                    '{"id":"todo-2","content":"Write report","depends_on":["todo-1"]}'
                    "],\"requires_clarification\":false,\"clarifications\":[]}"
                )
            )

    monkeypatch.setattr("src.agents.middlewares.planner_middleware.create_chat_model", lambda **kwargs: _Model())
    middleware = PlannerMiddleware(
        router=_router(),
        requested_model="primary",
        max_plan_steps=PlannerConfig().max_plan_steps,
        dag_enabled=True,
        handoffs_config=HandoffsConfig(enabled=True, dir=".handoffs"),
        sprint_contracts_config=SprintContractsConfig(enabled=True, min_todos_trigger=2),
    )
    state = {
        "messages": [HumanMessage(content="Create a comprehensive AI trends report.")],
        "thread_data": {"workspace_path": str(tmp_path)},
    }
    update = middleware.before_model(state, _runtime())
    assert update is not None
    assert update["plan"]["clarification_pending"] is True
    assert update["plan"]["clarification_question"]
    names = [getattr(msg, "name", "") for msg in update["messages"]]
    assert "planner_clarification_required" in names


def test_planner_clears_clarification_pending_after_user_answer(tmp_path: Path):
    middleware = PlannerMiddleware(
        router=_router(),
        requested_model="primary",
        max_plan_steps=PlannerConfig().max_plan_steps,
        dag_enabled=True,
        handoffs_config=HandoffsConfig(enabled=True, dir=".handoffs"),
        sprint_contracts_config=SprintContractsConfig(enabled=True, min_todos_trigger=2),
    )
    state = {
        "plan": {
            "plan_id": "plan-1",
            "status": "draft",
            "clarification_pending": True,
            "clarification_question": "What years should this cover?",
        },
        "messages": [
            HumanMessage(content="Create AI trends report"),
            ToolMessage(content="What years should this cover?", tool_call_id="tc-1", name="ask_clarification"),
            HumanMessage(content="Use 2024 to 2026."),
        ],
        "thread_data": {"workspace_path": str(tmp_path)},
    }
    update = middleware.before_model(state, _runtime())
    assert update is not None
    assert update["plan"]["clarification_pending"] is False
    assert isinstance(update["plan"]["clarification_answered_at"], str)


def test_evaluator_pre_verifier_injects_feedback_when_todos_incomplete(tmp_path: Path):
    middleware = EvaluatorMiddleware(
        router=_router(),
        requested_model="primary",
        max_attempts=EvaluatorConfig().max_attempts,
        handoffs_config=HandoffsConfig(enabled=True, dir=".handoffs"),
    )
    state = {
        "plan": {"title": "Plan", "summary": "Summary"},
        "eval_attempts": 0,
        "todo_graph": {"nodes": [{"id": "todo-1", "status": "pending"}]},
        "messages": [AIMessage(content="I am done")],
        "thread_data": {"workspace_path": str(tmp_path)},
    }
    update = middleware.after_model(state, _runtime())
    assert update is not None
    assert update["eval_attempts"] == 1
    assert "evaluator_feedback" == update["messages"][0].name


def test_evaluator_marks_plan_passed_on_llm_pass(monkeypatch, tmp_path: Path):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content="VERDICT: PASS\nCRITIQUE: Looks good.")

    monkeypatch.setattr("src.agents.middlewares.evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    plan_file = tmp_path / ".handoffs" / "plan.md"
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text("# Plan", encoding="utf-8")
    middleware = EvaluatorMiddleware(
        router=_router(),
        requested_model="primary",
        max_attempts=EvaluatorConfig().max_attempts,
        handoffs_config=HandoffsConfig(enabled=True, dir=".handoffs"),
    )
    state = {
        "plan": {"title": "Plan", "summary": "Summary", "plan_path": str(plan_file)},
        "eval_attempts": 0,
        "todo_graph": {"nodes": [{"id": "todo-1", "status": "completed"}]},
        "messages": [AIMessage(content="Final answer")],
        "thread_data": {"workspace_path": str(tmp_path)},
    }
    update = middleware.after_model(state, _runtime())
    assert update is not None
    assert update["plan"]["evaluation_status"] == "passed"
    assert (tmp_path / ".handoffs" / "report.md").exists()


def test_evaluator_resolves_virtual_plan_path(monkeypatch, tmp_path: Path):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content="VERDICT: PASS\nCRITIQUE: Looks good.")

    monkeypatch.setattr("src.agents.middlewares.evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    outputs = tmp_path / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "plan.md").write_text("# Plan", encoding="utf-8")
    middleware = EvaluatorMiddleware(
        router=_router(),
        requested_model="primary",
        max_attempts=EvaluatorConfig().max_attempts,
        handoffs_config=HandoffsConfig(enabled=True, dir=".handoffs"),
    )
    state = {
        "plan": {"title": "Plan", "summary": "Summary", "plan_path": "/mnt/user-data/outputs/plan.md"},
        "eval_attempts": 0,
        "todo_graph": {"nodes": [{"id": "todo-1", "status": "completed"}]},
        "messages": [AIMessage(content="Final answer")],
        "thread_data": {
            "workspace_path": str(tmp_path),
            "outputs_path": str(outputs),
            "uploads_path": str(tmp_path / "uploads"),
            "mounted_path": None,
        },
    }
    update = middleware.after_model(state, _runtime())
    assert update is not None
    assert update["plan"]["evaluation_status"] == "passed"
