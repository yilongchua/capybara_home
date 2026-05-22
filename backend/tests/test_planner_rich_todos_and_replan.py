"""Tests for rich todo schema (objective/steps/completion/fallback) and in-place re-plan."""

from __future__ import annotations

import json
from types import SimpleNamespace

from langchain_core.messages import HumanMessage

from src.agents.middlewares.handoff_sync import render_plan_md
from src.agents.middlewares.planner_middleware import (
    PlannerMiddleware,
    PlannerOutput,
    _normalize_todo_steps,
    _parse_plan_response,
)


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context={"mode": "plan", "auto_mode": False, "plan_behavior": "plan_foreground"})


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
                summary="Identify top restaurants",
                objective="Produce a candidate list",
                domain="research",
                todos=[
                    {
                        "id": "todo-1",
                        "content": "Identify restaurants",
                        "depends_on": [],
                        "objective": "Find 10 candidates",
                        "completion_requirement": "top10.md contains 10 entries",
                        "failure_fallback": "Fallback to prior knowledge with label",
                        "steps": [
                            {
                                "description": "Web search candidates",
                                "subagent_types": ["source-researcher"],
                                "tools": ["web_search"],
                                "output_artifact_path": "/mnt/user-data/workspace/candidates.md",
                                "completion_requirement": ">= 15 entries",
                            }
                        ],
                    },
                ],
            ),
            "test-model",
        )

    monkeypatch.setattr(middleware, "_invoke_planner", _fake_invoke)
    monkeypatch.setattr(
        "src.agents.middlewares.planner_middleware._classify_complexity",
        lambda _prompt: "complex",
    )
    monkeypatch.setattr(
        "src.agents.middlewares.planner_middleware._looks_like_direct_answer_request",
        lambda _prompt: False,
    )
    return middleware


def test_normalize_todo_steps_handles_missing_field() -> None:
    assert _normalize_todo_steps(None) == []
    assert _normalize_todo_steps("not-a-list") == []
    assert _normalize_todo_steps([]) == []


def test_normalize_todo_steps_skips_invalid_entries() -> None:
    steps = _normalize_todo_steps(
        [
            "string-entry-skipped",
            {"description": ""},
            {"description": "ok step", "subagent_types": ["x"], "tools": ["web_search"]},
        ]
    )
    assert len(steps) == 1
    assert steps[0]["description"] == "ok step"
    assert steps[0]["subagent_types"] == ["x"]


def test_parse_plan_response_captures_rich_fields() -> None:
    raw = json.dumps(
        {
            "title": "Restaurant Finder",
            "domain": "research",
            "todos": [
                {
                    "id": "todo-1",
                    "content": "Search candidates",
                    "objective": "Find 10 restaurants",
                    "completion_requirement": "top10.md exists",
                    "failure_fallback": "Use prior knowledge",
                    "steps": [
                        {
                            "description": "web search",
                            "subagent_types": ["source-researcher"],
                            "tools": ["web_search"],
                            "output_artifact_path": "/mnt/user-data/workspace/candidates.md",
                            "completion_requirement": ">= 15 entries",
                        }
                    ],
                }
            ],
        }
    )
    output = _parse_plan_response(raw, max_steps=8)
    assert len(output.todos) == 1
    todo = output.todos[0]
    assert todo["objective"] == "Find 10 restaurants"
    assert todo["completion_requirement"] == "top10.md exists"
    assert todo["failure_fallback"] == "Use prior knowledge"
    assert len(todo["steps"]) == 1
    assert todo["steps"][0]["tools"] == ["web_search"]


def test_render_plan_md_includes_rich_todo_sections() -> None:
    nodes = [
        {
            "id": "todo-1",
            "content": "Search restaurants",
            "status": "pending",
            "objective": "Find 10",
            "completion_requirement": "top10.md exists",
            "failure_fallback": "Use prior knowledge",
            "steps": [
                {
                    "description": "web search",
                    "subagent_types": ["source-researcher"],
                    "tools": ["web_search"],
                    "output_artifact_path": "/mnt/user-data/workspace/candidates.md",
                    "completion_requirement": "15 entries",
                }
            ],
        }
    ]
    md = render_plan_md("Restaurant Plan", "Find 10 restaurants", nodes)
    assert "Objective: Find 10" in md
    assert "Steps:" in md
    assert "1. web search" in md
    assert "Subagent: source-researcher" in md
    assert "Tools: web_search" in md
    assert "/mnt/user-data/workspace/candidates.md" in md
    assert "Done when: top10.md exists" in md
    assert "On failure: Use prior knowledge" in md


def test_render_plan_md_handles_legacy_nodes_without_rich_fields() -> None:
    """Plans created before the rich-todo migration must still render."""
    nodes = [{"id": "todo-1", "content": "Old todo", "status": "pending"}]
    md = render_plan_md("Old Plan", "Legacy", nodes)
    assert "Old todo" in md
    # Rich sections should be absent — not crash.
    assert "Objective:" not in md
    assert "On failure:" not in md


def test_replan_preserves_plan_id_and_bumps_revision(monkeypatch) -> None:
    middleware = _planner(monkeypatch)
    existing_plan = {
        "plan_id": "plan-existing",
        "status": "draft",
        "revision": 1,
        "human_messages_at_plan": 1,
    }
    state = {
        "plan": existing_plan,
        "messages": [
            HumanMessage(content="Initial request"),
            HumanMessage(content="Now focus on Asian crystals only"),
        ],
    }
    update = middleware.before_model(state, _runtime())
    assert update is not None
    assert update["plan"]["plan_id"] == "plan-existing"
    assert update["plan"]["revision"] == 2
    assert update["plan"]["human_messages_at_plan"] == 2


def test_no_replan_without_new_user_message(monkeypatch) -> None:
    middleware = _planner(monkeypatch)
    existing_plan = {
        "plan_id": "plan-existing",
        "status": "draft",
        "revision": 0,
        "human_messages_at_plan": 1,
    }
    state = {
        "plan": existing_plan,
        "messages": [HumanMessage(content="Initial request")],  # same count
    }
    update = middleware.before_model(state, _runtime())
    # No new HumanMessage → planner does not re-run.
    assert update is None


def test_replan_blocked_when_clarification_pending(monkeypatch) -> None:
    middleware = _planner(monkeypatch)
    existing_plan = {
        "plan_id": "plan-existing",
        "status": "draft",
        "clarification_pending": True,
        "revision": 0,
        "human_messages_at_plan": 1,
    }
    state = {
        "plan": existing_plan,
        "messages": [
            HumanMessage(content="Initial request"),
            HumanMessage(content="Changed my mind"),  # new HumanMessage exists
        ],
    }
    update = middleware.before_model(state, _runtime())
    # Even though a new HumanMessage exists, clarification takes precedence —
    # planner does NOT re-run because plan.clarification_pending=True.
    # apply_clarification_progress will handle the answer if it matches an option.
    # Otherwise no payload is emitted.
    assert update is None or "plan" not in (update or {})


def test_replan_capped_at_max_revisions(monkeypatch) -> None:
    middleware = _planner(monkeypatch)
    existing_plan = {
        "plan_id": "plan-existing",
        "status": "draft",
        "revision": 5,  # at cap
        "human_messages_at_plan": 1,
    }
    state = {
        "plan": existing_plan,
        "messages": [HumanMessage(content="A"), HumanMessage(content="B")],
    }
    update = middleware.before_model(state, _runtime())
    assert update is None
