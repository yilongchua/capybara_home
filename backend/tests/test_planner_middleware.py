"""Tests for planner middleware plan-approval pause behavior."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.middlewares.planner_middleware import (
    ClarificationOption,
    PlannerClarification,
    PlannerMiddleware,
    PlannerOutput,
    _ensure_research_clarifications,
)


def _runtime(*, auto_mode: bool = False, plan_behavior: str = "plan_foreground") -> SimpleNamespace:
    return SimpleNamespace(context={"auto_mode": auto_mode, "plan_behavior": plan_behavior, "mode": "plan"})


def _planner(monkeypatch) -> PlannerMiddleware:
    middleware = PlannerMiddleware(
        requested_model=None,
        max_plan_steps=8,
        dag_enabled=True,
        handoffs_config=SimpleNamespace(enabled=False),
        sprint_contracts_config=SimpleNamespace(enabled=False),
    )

    def _fake_invoke(_prompt: str) -> tuple[PlannerOutput, str]:
        return (
            PlannerOutput(
                title="Research Plan",
                summary="Research and synthesize findings.",
                objective="Deliver a structured report.",
                domain="generic",
                todos=[
                    {
                        "id": "todo-1",
                        "content": "Research current status",
                        "depends_on": [],
                        "rationale": "Gather facts.",
                    },
                    {
                        "id": "todo-2",
                        "content": "Write synthesis report",
                        "depends_on": ["todo-1"],
                        "rationale": "Deliver output.",
                    },
                ],
            ),
            "test-model",
        )

    monkeypatch.setattr(middleware, "_invoke_planner", _fake_invoke)
    monkeypatch.setattr(
        "src.agents.middlewares.planner_middleware._looks_like_direct_answer_request",
        lambda _prompt: False,
    )
    return middleware


def test_plan_foreground_draft_pauses_before_lead_model(monkeypatch) -> None:
    middleware = _planner(monkeypatch)
    state = {"messages": [HumanMessage(content="Analyze the Iran conflict")]}
    update = middleware.before_model(state, _runtime())
    assert update is not None
    assert update.get("jump_to") == "end"
    assert update["plan"]["status"] == "draft"
    assert update["plan"].get("awaiting_execution_approval") is True


def test_auto_mode_approves_plan_and_still_pauses_before_execution(monkeypatch) -> None:
    middleware = _planner(monkeypatch)
    state = {"messages": [HumanMessage(content="Analyze the Iran conflict")]}
    update = middleware.before_model(state, _runtime(auto_mode=True))
    assert update is not None
    assert update.get("jump_to") == "end"
    assert update["plan"]["status"] == "approved"
    assert update["plan"].get("approved_at")


def test_research_clarifications_normalize_recommended_first_and_option_count() -> None:
    output = PlannerOutput(
        domain="research",
        clarifications=[
            PlannerClarification(
                question="Which timeframe should we use?",
                options=[
                    ClarificationOption(label="Last 3 years"),
                    ClarificationOption(label="Last 12 months"),
                    ClarificationOption(label="Since 2020"),
                    ClarificationOption(label="This quarter"),
                    ClarificationOption(label="Too many"),
                ],
            )
        ],
    )

    clarifications = _ensure_research_clarifications("Research AI trends", output)

    assert len(clarifications) >= 1
    options = clarifications[0].options
    assert 2 <= len(options) <= 4
    assert options[0].recommended is True


def test_plan_mode_replans_even_with_prior_ai_messages(monkeypatch) -> None:
    middleware = _planner(monkeypatch)
    state = {
        "messages": [
            HumanMessage(content="Initial request"),
            AIMessage(content="Prior assistant response"),
            HumanMessage(content="Come up with a plan for this implementation."),
        ]
    }
    update = middleware.before_model(state, _runtime())
    assert update is not None
    assert update.get("jump_to") == "end"
    assert update["plan"]["status"] == "draft"
