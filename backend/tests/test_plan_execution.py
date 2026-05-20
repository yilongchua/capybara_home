"""Tests for plan execution and clarification helpers."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, ToolMessage

from src.agents.middlewares.plan_execution import (
    all_clarifications_resolved,
    apply_clarification_progress,
    handoff_already_started,
    has_answer_for_current_question,
    should_spawn_work_handoff,
)


def _plan_with_two_clarifications() -> dict:
    return {
        "plan_id": "plan-1",
        "status": "draft",
        "clarification_pending": True,
        "clarification_index": 0,
        "clarification_answers": [],
        "clarifications": [
            {
                "question": "What timeframe should the research cover?",
                "options": [
                    {"label": "Last 12 months", "recommended": True},
                    {"label": "Last 3 years", "recommended": False},
                ],
            },
            {
                "question": "Which AI trend scope should be prioritized?",
                "options": [
                    {"label": "Cross-industry global trends", "recommended": True},
                    {"label": "Industry-specific trends", "recommended": False},
                ],
            },
        ],
        "clarification_question": "What timeframe should the research cover?",
    }


def test_has_answer_for_current_question_matches_option_label():
    plan = _plan_with_two_clarifications()
    messages = [
        HumanMessage(name="planner_clarification_required", content="Question: timeframe"),
        HumanMessage(content="Last 12 months"),
    ]
    assert has_answer_for_current_question(plan, messages) is True


def test_apply_clarification_progress_advances_to_second_question():
    plan = _plan_with_two_clarifications()
    messages = [
        HumanMessage(name="planner_clarification_required", content="Question: timeframe"),
        HumanMessage(content="Last 12 months"),
    ]
    progress = apply_clarification_progress(plan, messages)
    assert progress is not None
    updated = progress["plan"]
    assert updated["clarification_pending"] is True
    assert updated["clarification_index"] == 1
    assert len(updated["clarification_answers"]) == 1
    assert progress.get("messages")


def test_apply_clarification_progress_finishes_all_questions():
    plan = {
        **_plan_with_two_clarifications(),
        "clarification_index": 1,
        "clarification_answers": [
            {
                "question": "What timeframe should the research cover?",
                "selected_label": "Last 12 months",
                "answered_at": "2026-01-01T00:00:00Z",
            }
        ],
        "clarification_question": "Which AI trend scope should be prioritized?",
    }
    messages = [
        HumanMessage(name="planner_clarification_required", content="Question: scope"),
        ToolMessage(content="[Auto Mode] Selected: Cross-industry global trends", tool_call_id="tc-1", name="ask_clarification"),
    ]
    progress = apply_clarification_progress(plan, messages)
    assert progress is not None
    updated = progress["plan"]
    assert updated["clarification_pending"] is False
    assert updated["clarification_resolved"] is True
    assert len(updated["clarification_answers"]) == 2
    assert all_clarifications_resolved(updated) is True


def test_should_spawn_work_handoff_requires_approved_and_not_started():
    plan = {"status": "approved", "clarification_pending": False, "execution_handoff_started": False}
    assert should_spawn_work_handoff(plan, plan_behavior="plan_foreground", plan_status="approved") is True
    assert handoff_already_started({**plan, "execution_handoff_started": True}) is True
    assert (
        should_spawn_work_handoff(
            {**plan, "execution_handoff_started": True},
            plan_behavior="plan_foreground",
            plan_status="approved",
        )
        is False
    )
