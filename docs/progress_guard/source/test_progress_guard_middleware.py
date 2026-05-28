"""Tests for ProgressGuard warn-first behavior."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.middlewares.progress_guard_middleware import ProgressGuardMiddleware
from src.agents.middlewares.retry_policy_middleware import RETRY_PROGRESS_GUARD_KEY
from src.config.progress_guard_config import ProgressGuardConfig


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(context={"thread_id": "thread-1", "model_name": "default-model"})


def test_warns_after_no_progress_threshold(tmp_path: Path):
    middleware = ProgressGuardMiddleware(
        ProgressGuardConfig(
            enabled=True,
            terminate_on_stall=False,
            no_progress_turn_threshold=3,
            conversation_inactivity_turn_threshold=10,
            cyclic_tool_result_threshold=10,
        )
    )
    state = {
        "messages": [AIMessage(content="done")],
        "thread_data": {"outputs_path": str(tmp_path / "outputs")},
    }
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)

    first = middleware.after_model(state, _runtime()) or {}
    state["progress_guard"] = first.get("progress_guard")
    second = middleware.after_model(state, _runtime()) or {}
    state["progress_guard"] = second.get("progress_guard")
    third = middleware.after_model(state, _runtime()) or {}
    state["progress_guard"] = third.get("progress_guard")
    fourth = middleware.after_model(state, _runtime()) or {}

    assert "progress_guard" in fourth
    assert fourth["progress_guard"]["no_progress_turns"] >= 3
    warning_messages = fourth.get("messages", [])
    assert warning_messages
    assert "ProgressGuard warning" in warning_messages[0].content


def test_resets_no_progress_when_outputs_change(tmp_path: Path):
    middleware = ProgressGuardMiddleware(
        ProgressGuardConfig(
            enabled=True,
            terminate_on_stall=False,
            no_progress_turn_threshold=50,
            conversation_inactivity_turn_threshold=10,
            cyclic_tool_result_threshold=10,
        )
    )
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "messages": [AIMessage(content="done")],
        "thread_data": {"outputs_path": str(outputs_dir)},
    }

    first = middleware.after_model(state, _runtime()) or {}
    state["progress_guard"] = first.get("progress_guard")

    # No change -> increment
    second = middleware.after_model(state, _runtime()) or {}
    assert second["progress_guard"]["no_progress_turns"] >= 1
    state["progress_guard"] = second["progress_guard"]

    # Change outputs -> reset
    (outputs_dir / "new.txt").write_text("hello", encoding="utf-8")
    third = middleware.after_model(state, _runtime()) or {}
    assert third["progress_guard"]["no_progress_turns"] == 0


def test_tool_only_turn_with_todo_graph_change_counts_as_activity(tmp_path: Path):
    middleware = ProgressGuardMiddleware(
        ProgressGuardConfig(
            enabled=True,
            terminate_on_stall=False,
            no_progress_turn_threshold=50,
            conversation_inactivity_turn_threshold=10,
            cyclic_tool_result_threshold=10,
        )
    )
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "messages": [
            HumanMessage(content="execute the plan"),
            AIMessage(content=""),
        ],
        "thread_data": {"outputs_path": str(outputs_dir)},
        "todo_graph": {"nodes": [{"id": "todo-1", "status": "pending"}]},
    }
    first = middleware.after_model(state, _runtime()) or {}
    state["progress_guard"] = first.get("progress_guard")

    state["messages"] = [
        HumanMessage(content="execute the plan"),
        AIMessage(content="", tool_calls=[{"name": "write_todos", "args": {}, "id": "tc-1"}]),
        ToolMessage(content="updated todos", name="write_todos", tool_call_id="tc-1"),
    ]
    state["todo_graph"] = {"nodes": [{"id": "todo-1", "status": "completed"}]}
    second = middleware.after_model(state, _runtime()) or {}

    assert second["progress_guard"]["no_progress_turns"] == 0
    assert second["progress_guard"]["inactivity_turns"] == 0


def test_terminate_on_stall_sets_jump_to_end(tmp_path: Path):
    middleware = ProgressGuardMiddleware(
        ProgressGuardConfig(
            enabled=True,
            terminate_on_stall=True,
            no_progress_turn_threshold=3,
            conversation_inactivity_turn_threshold=10,
            cyclic_tool_result_threshold=10,
        )
    )
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "messages": [AIMessage(content="done")],
        "thread_data": {"outputs_path": str(outputs_dir)},
    }
    first = middleware.after_model(state, _runtime()) or {}
    state["progress_guard"] = first.get("progress_guard")
    second = middleware.after_model(state, _runtime()) or {}
    state["progress_guard"] = second.get("progress_guard")
    third = middleware.after_model(state, _runtime()) or {}
    state["progress_guard"] = third.get("progress_guard")
    fourth = middleware.after_model(state, _runtime()) or {}
    warnings = [m.content for m in fourth.get("messages", [])]
    assert any("stopped run" in content for content in warnings)
    assert fourth.get("jump_to") == "end"


def test_retry_turn_does_not_increment_no_progress(tmp_path: Path):
    runtime = _runtime()
    middleware = ProgressGuardMiddleware(
        ProgressGuardConfig(
            enabled=True,
            terminate_on_stall=False,
            no_progress_turn_threshold=10,
            conversation_inactivity_turn_threshold=10,
            cyclic_tool_result_threshold=10,
        )
    )
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "messages": [AIMessage(content="done")],
        "thread_data": {"outputs_path": str(outputs_dir)},
    }
    first = middleware.after_model(state, runtime) or {}
    state["progress_guard"] = first.get("progress_guard")
    second = middleware.after_model(state, runtime) or {}
    state["progress_guard"] = second.get("progress_guard")
    baseline_turns = second["progress_guard"]["no_progress_turns"]
    runtime.context[RETRY_PROGRESS_GUARD_KEY] = True
    third = middleware.after_model(state, runtime) or {}
    assert third["progress_guard"]["no_progress_turns"] == baseline_turns


def test_progress_guard_calibration_fixture_meets_gate():
    payload = json.loads(Path("tests/evals/fixtures/progress_guard_calibration.json").read_text(encoding="utf-8"))
    fp_rate = payload["false_positives"] / payload["legitimate_runs"]
    tp_rate = payload["true_positives"] / payload["runaway_runs"]
    assert fp_rate < 0.01
    assert tp_rate >= 0.70


def test_terminate_on_repeated_cyclic_tool_results(tmp_path: Path):
    middleware = ProgressGuardMiddleware(
        ProgressGuardConfig(
            enabled=True,
            terminate_on_stall=False,
            no_progress_turn_threshold=50,
            conversation_inactivity_turn_threshold=50,
            cyclic_tool_result_threshold=3,
            terminate_on_cyclic_tool_results=True,
            cyclic_tool_result_hard_limit=4,
        )
    )
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "messages": [ToolMessage(content="same-tool-output", name="bash", tool_call_id="tc-1")],
        "thread_data": {"outputs_path": str(outputs_dir)},
    }

    # Seed and increment cyclic counter across identical tool-result turns
    first = middleware.after_model(state, _runtime()) or {}
    state["progress_guard"] = first.get("progress_guard")
    second = middleware.after_model(state, _runtime()) or {}
    state["progress_guard"] = second.get("progress_guard")
    third = middleware.after_model(state, _runtime()) or {}
    state["progress_guard"] = third.get("progress_guard")
    fourth = middleware.after_model(state, _runtime()) or {}
    state["progress_guard"] = fourth.get("progress_guard")
    fifth = middleware.after_model(state, _runtime()) or {}

    warnings = [m.content for m in fifth.get("messages", [])]
    assert any("cyclic tool results reached" in content for content in warnings)
    assert fifth.get("jump_to") == "end"


def test_resets_progress_guard_state_on_new_real_user_message(tmp_path: Path):
    runtime = _runtime()
    middleware = ProgressGuardMiddleware(
        ProgressGuardConfig(
            enabled=True,
            terminate_on_stall=False,
            no_progress_turn_threshold=3,
            conversation_inactivity_turn_threshold=10,
            cyclic_tool_result_threshold=10,
        )
    )
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "messages": [AIMessage(content="done"), HumanMessage(content="analyse repo A")],
        "thread_data": {"outputs_path": str(outputs_dir)},
    }
    first = middleware.after_model(state, runtime) or {}
    state["progress_guard"] = first.get("progress_guard")
    second = middleware.after_model(state, runtime) or {}
    assert second["progress_guard"]["no_progress_turns"] >= 1

    # New user message should reset counters for fresh turn budget.
    state["progress_guard"] = second["progress_guard"]
    state["messages"] = [AIMessage(content="done"), HumanMessage(content="analyse repo B")]
    third = middleware.after_model(state, runtime) or {}
    assert third["progress_guard"]["no_progress_turns"] == 0
