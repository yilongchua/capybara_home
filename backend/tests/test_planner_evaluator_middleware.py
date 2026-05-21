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


def _runtime(*, auto_mode: bool = False):
    return SimpleNamespace(context={"thread_id": "thread-1", "model_name": "primary", "auto_mode": auto_mode})


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
        "thread_data": {
            "workspace_path": str(tmp_path / "workspace"),
            "outputs_path": str(tmp_path / "outputs"),
            "uploads_path": str(tmp_path / "uploads"),
            "mounted_path": None,
        },
    }
    update = middleware.before_model(state, _runtime())
    assert update is not None
    assert update["plan"]["title"] == "Build feature"
    assert len(update["todo_graph"]["nodes"]) == 2
    assert update["complexity_tier"] in {"moderate", "complex"}
    assert update["plan_evaluated"] is False
    assert (tmp_path / "workspace" / "plan.md").exists()
    versioned = list((tmp_path / "workspace" / "plans").glob("plan-*.md"))
    assert versioned
    assert update["plan"]["status"] == "draft"
    assert isinstance(update["plan"].get("plan_id"), str)


def test_planner_uses_original_request_when_latest_human_is_synthetic(monkeypatch, tmp_path: Path):
    captured: dict[str, str] = {}

    class _Model:
        def invoke(self, prompt):
            captured["prompt"] = prompt
            return SimpleNamespace(
                content=(
                    '{"title":"Implement migration","summary":"Do backend work","todos":['
                    '{"id":"todo-1","content":"Implement migration","depends_on":[]}'
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
    original = "Implement a backend migration for the billing workflow."
    state = {
        "messages": [
            HumanMessage(content=original),
            HumanMessage(content="Generate a detailed structured plan for the previous user request. Work Mode detected this request is too complex for direct execution."),
        ],
        "thread_data": {"workspace_path": str(tmp_path)},
    }

    update = middleware.before_model(state, _runtime())

    assert update is not None
    assert original in captured["prompt"]
    assert "previous user request" not in captured["prompt"].split("User request:", 1)[1]
    handoff = next(msg for msg in update["messages"] if getattr(msg, "name", "") == "planner_handoff")
    assert f"Original request: {original}" in handoff.content


def test_planner_skips_direct_answer_comparison_without_llm(monkeypatch, tmp_path: Path):
    def _fail_create_chat_model(**kwargs):  # noqa: ARG001
        raise AssertionError("direct-answer bypass should not call planner LLM")

    monkeypatch.setattr("src.agents.middlewares.planner_middleware.create_chat_model", _fail_create_chat_model)
    middleware = PlannerMiddleware(
        router=_router(),
        requested_model="primary",
        max_plan_steps=PlannerConfig().max_plan_steps,
        dag_enabled=True,
        handoffs_config=HandoffsConfig(enabled=True, dir=".handoffs"),
        sprint_contracts_config=SprintContractsConfig(enabled=True, min_todos_trigger=2),
    )
    state = {
        "messages": [HumanMessage(content="Compare espresso, pour-over, AeroPress, and moka pot for taste, cost, learning curve, and convenience.")],
        "thread_data": {"workspace_path": str(tmp_path)},
    }

    update = middleware.before_model(state, _runtime())

    assert update == {"complexity_tier": "moderate"}


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
            "outputs_path": str(tmp_path / "outputs"),
            "uploads_path": str(tmp_path / "uploads"),
            "mounted_path": None,
        },
    }
    update = middleware.before_model(state, _runtime())
    assert update is not None
    assert "/workspace/plans/plan-" in str(update["plan"]["plan_path"])
    assert str(update["plan"]["latest_alias_path"]).endswith("/workspace/plan.md")
    assert (workspace / "plan.md").exists()
    versioned = list((workspace / "plans").glob("plan-*.md"))
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
            "clarification_index": 0,
            "clarification_answers": [],
            "clarifications": [
                {
                    "question": "What years should this cover?",
                    "options": [
                        {"label": "2024 to 2026", "recommended": True},
                        {"label": "Last 12 months", "recommended": False},
                    ],
                }
            ],
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


def test_planner_auto_mode_clarification_resolution_spawns_work_handoff(tmp_path: Path, monkeypatch):
    spawn_calls: list[dict] = []
    monkeypatch.setattr(
        "src.agents.middlewares.planner_middleware.spawn_work_mode_handoff",
        lambda **kwargs: spawn_calls.append(kwargs),
    )
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
            "clarification_index": 0,
            "clarification_answers": [],
            "clarifications": [
                {
                    "question": "Which islands best match your pace?",
                    "options": [
                        {"label": "Santorini & Crete", "recommended": True},
                        {"label": "Rhodes only", "recommended": False},
                    ],
                }
            ],
            "clarification_question": "Which islands best match your pace?",
            "awaiting_execution_approval": True,
        },
        "messages": [
            HumanMessage(content="Plan Greece trip"),
            ToolMessage(content="[Auto Mode] Selected: Santorini & Crete", tool_call_id="tc-1", name="ask_clarification"),
        ],
        "thread_data": {"workspace_path": str(tmp_path)},
    }
    runtime = _runtime(auto_mode=True)
    runtime.context["plan_behavior"] = "plan_foreground"
    update = middleware.before_model(state, runtime)
    assert update is not None
    assert update["plan"]["clarification_pending"] is False
    assert update["plan"]["status"] == "approved"
    assert update["plan"].get("execution_handoff_started") is not True
    assert update["plan"].get("execution_handoff_failed") is False
    assert len(spawn_calls) == 1


def test_planner_clears_clarification_pending_after_auto_mode_selection(tmp_path: Path):
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
            "clarification_index": 0,
            "clarification_answers": [],
            "clarifications": [
                {
                    "question": "Which islands best match your pace?",
                    "options": [
                        {"label": "Santorini & Crete", "recommended": True},
                        {"label": "Rhodes only", "recommended": False},
                    ],
                }
            ],
            "clarification_question": "Which islands best match your pace?",
            "awaiting_execution_approval": True,
        },
        "messages": [
            HumanMessage(content="Plan Greece trip"),
            ToolMessage(content="[Auto Mode] Selected: Santorini & Crete", tool_call_id="tc-1", name="ask_clarification"),
        ],
        "thread_data": {"workspace_path": str(tmp_path)},
    }
    update = middleware.before_model(state, _runtime(auto_mode=True))
    assert update is not None
    assert update["plan"]["clarification_pending"] is False
    assert update["plan"]["status"] == "approved"
    assert update["plan"]["awaiting_execution_approval"] is False
    assert isinstance(update["plan"]["approved_at"], str)


def test_evaluator_defers_when_todos_incomplete(tmp_path: Path):
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
    assert update is None


def test_evaluator_marks_plan_passed_on_llm_pass(monkeypatch, tmp_path: Path):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content="VERDICT: PASS\nCRITIQUE: Looks good.")

    monkeypatch.setattr("src.agents.middlewares.evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    workspace = tmp_path / "workspace"
    plans = workspace / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    plan_file = plans / "plan-20260521-000000-sample.md"
    plan_file.write_text("# Plan", encoding="utf-8")
    alias_file = workspace / "plan.md"
    alias_file.write_text("# Plan", encoding="utf-8")
    middleware = EvaluatorMiddleware(
        router=_router(),
        requested_model="primary",
        max_attempts=EvaluatorConfig().max_attempts,
        handoffs_config=HandoffsConfig(enabled=True, dir=".handoffs"),
    )
    state = {
        "plan": {
            "title": "Plan",
            "summary": "Summary",
            "plan_path": "/mnt/user-data/workspace/plans/plan-20260521-000000-sample.md",
            "latest_alias_path": "/mnt/user-data/workspace/plan.md",
        },
        "eval_attempts": 0,
        "todo_graph": {"nodes": [{"id": "todo-1", "status": "completed"}]},
        "messages": [AIMessage(content="Final answer")],
        "thread_data": {"workspace_path": str(workspace)},
    }
    update = middleware.after_model(state, _runtime())
    assert update is not None
    assert update["plan"]["evaluation_status"] == "passed"
    assert (workspace / ".handoffs" / "report.md").exists()


def test_evaluator_resolves_virtual_plan_path(monkeypatch, tmp_path: Path):
    class _Model:
        def invoke(self, prompt):  # noqa: ARG002
            return SimpleNamespace(content="VERDICT: PASS\nCRITIQUE: Looks good.")

    monkeypatch.setattr("src.agents.middlewares.evaluator_middleware.create_chat_model", lambda **kwargs: _Model())
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    plans = workspace / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "plan-20260521-000000-sample.md").write_text("# Plan", encoding="utf-8")
    (workspace / "plan.md").write_text("# Plan", encoding="utf-8")
    middleware = EvaluatorMiddleware(
        router=_router(),
        requested_model="primary",
        max_attempts=EvaluatorConfig().max_attempts,
        handoffs_config=HandoffsConfig(enabled=True, dir=".handoffs"),
    )
    state = {
        "plan": {
            "title": "Plan",
            "summary": "Summary",
            "plan_path": "/mnt/user-data/workspace/plans/plan-20260521-000000-sample.md",
            "latest_alias_path": "/mnt/user-data/workspace/plan.md",
        },
        "eval_attempts": 0,
        "todo_graph": {"nodes": [{"id": "todo-1", "status": "completed"}]},
        "messages": [AIMessage(content="Final answer")],
        "thread_data": {
            "workspace_path": str(workspace),
            "outputs_path": str(tmp_path / "outputs"),
            "uploads_path": str(tmp_path / "uploads"),
            "mounted_path": None,
        },
    }
    update = middleware.after_model(state, _runtime())
    assert update is not None
    assert update["plan"]["evaluation_status"] == "passed"
