"""Tests for WorkModeMiddleware — phase looping, auto-cycle, and SSE emission."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stubs for heavy deps that must not be imported during unit testing
# ---------------------------------------------------------------------------

# Stub out src.client so _run_plan_mode_rerun can be imported without
# pulling in the full CapyHomeClient dependency tree.
_stub_client_module = types.ModuleType("src.client")
_stub_client_module.CapyHomeClient = MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("src.client", _stub_client_module)


from src.agents.middlewares.work_mode_middleware import (  # noqa: E402
    WorkModeMiddleware,
    _MAX_AUTO_ADAPTATION_ATTEMPTS,
    _create_work_mode,
    _spawn_plan_rerun,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runtime(
    *,
    thread_id: str = "thread-1",
    auto_mode: bool = False,
    model_name: str | None = None,
    extra_context: dict | None = None,
) -> SimpleNamespace:
    context = {
        "thread_id": thread_id,
        "auto_mode": auto_mode,
        "model_name": model_name,
    }
    if extra_context:
        context.update(extra_context)
    return SimpleNamespace(
        context=context
    )


def _node(
    todo_id: str,
    content: str = "Task",
    status: str = "pending",
    depends_on: list[str] | None = None,
    subagent_type: str | None = None,
) -> dict:
    node: dict = {"id": todo_id, "content": content, "status": status}
    if depends_on:
        node["depends_on"] = depends_on
    if subagent_type:
        node["subagent_type"] = subagent_type
    return node


def _state(
    *,
    nodes: list[dict] | None = None,
    dreamy_mode: bool = False,
    complexity_tier: str | None = None,
    phase_execution: dict | None = None,
) -> dict:
    state: dict = {}
    if nodes is not None:
        state["todo_graph"] = {"nodes": nodes}
    if dreamy_mode:
        state["dreamy_mode"] = True
    if complexity_tier:
        state["complexity_tier"] = complexity_tier
    if phase_execution is not None:
        state["phase_execution"] = phase_execution
    return state


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class TestCreateWorkMode:
    def test_returns_none_when_not_work_mode(self):
        ctx = SimpleNamespace(is_work_mode=False)
        assert _create_work_mode(ctx) is None

    def test_returns_middleware_when_work_mode(self):
        ctx = SimpleNamespace(is_work_mode=True)
        result = _create_work_mode(ctx)
        assert isinstance(result, WorkModeMiddleware)

    def test_returns_none_when_attr_missing(self):
        ctx = SimpleNamespace()
        assert _create_work_mode(ctx) is None


# ---------------------------------------------------------------------------
# Dreamy mode guard
# ---------------------------------------------------------------------------

class TestDreamyModeGuard:
    def test_returns_none_when_dreamy_mode(self):
        mw = WorkModeMiddleware()
        emitted = []

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ):
            result = mw.before_model(_state(dreamy_mode=True), _runtime())

        assert result is None
        assert emitted == []


# ---------------------------------------------------------------------------
# No plan (no nodes)
# ---------------------------------------------------------------------------

class TestNoPlan:
    def test_returns_none_when_no_todo_graph(self):
        mw = WorkModeMiddleware()
        emitted = []

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ):
            result = mw.before_model(_state(), _runtime())

        assert result is None

    def test_returns_none_when_empty_nodes(self):
        mw = WorkModeMiddleware()
        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ):
            result = mw.before_model(_state(nodes=[]), _runtime())
        assert result is None


# ---------------------------------------------------------------------------
# Complexity escalation (no plan + complexity_tier="complex")
# ---------------------------------------------------------------------------

class TestComplexityEscalation:
    def test_emits_complexity_escalation_sse(self):
        mw = WorkModeMiddleware()
        emitted = []

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ):
            result = mw.before_model(
                _state(complexity_tier="complex"), _runtime()
            )

        assert result is None
        assert any(e.get("type") == "complexity_escalation" for e in emitted)

    def test_spawns_plan_rerun_when_auto_mode(self):
        mw = WorkModeMiddleware()
        spawned: list[dict] = []

        def fake_spawn(**kwargs):
            spawned.append(kwargs)

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._spawn_plan_rerun",
            side_effect=fake_spawn,
        ):
            mw.before_model(
                _state(complexity_tier="complex"),
                _runtime(auto_mode=True, thread_id="t-esc"),
            )

        assert len(spawned) == 1
        assert spawned[0]["thread_id"] == "t-esc"

    def test_no_spawn_when_auto_mode_false(self):
        mw = WorkModeMiddleware()
        spawned: list[dict] = []

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._spawn_plan_rerun",
            side_effect=lambda **kw: spawned.append(kw),
        ):
            mw.before_model(
                _state(complexity_tier="complex"),
                _runtime(auto_mode=False),
            )

        assert spawned == []


# ---------------------------------------------------------------------------
# Phase instruction injection (happy path)
# ---------------------------------------------------------------------------

class TestPhaseInstructionInjection:
    def test_injects_instruction_for_first_ready_todo(self):
        mw = WorkModeMiddleware()
        emitted = []
        nodes = [_node("t1", "Write tests", status="pending")]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            result = mw.before_model(_state(nodes=nodes), _runtime())

        assert result is not None
        msgs = result.get("messages", [])
        assert len(msgs) == 1
        assert msgs[0].name == "work_mode_instruction"
        assert "Write tests" in msgs[0].content
        assert "Do NOT output any text" in msgs[0].content

    def test_emits_phase_started_sse(self):
        mw = WorkModeMiddleware()
        emitted = []
        nodes = [_node("t1", "Deploy service", status="pending")]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            mw.before_model(_state(nodes=nodes), _runtime())

        started = [e for e in emitted if e.get("type") == "phase_started"]
        assert len(started) == 1
        assert started[0]["todo_id"] == "t1"
        assert started[0]["content"] == "Deploy service"

    def test_includes_subagent_hint_when_subagent_type_set(self):
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Research topic", status="pending", subagent_type="researcher")]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            result = mw.before_model(_state(nodes=nodes), _runtime())

        assert result is not None
        content = result["messages"][0].content
        assert "researcher" in content

    def test_skips_completed_todos(self):
        mw = WorkModeMiddleware()
        nodes = [
            _node("t1", "First", status="completed"),
            _node("t2", "Second", status="pending"),
        ]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1", "t2"],
        ):
            result = mw.before_model(_state(nodes=nodes), _runtime())

        assert result is not None
        # Must target t2, not the completed t1
        assert "Second" in result["messages"][0].content

    def test_emits_phase_completed_for_newly_completed_todos(self):
        mw = WorkModeMiddleware()
        # Simulate previous cycle where t1 was pending
        mw._completed_before = frozenset()
        nodes = [
            _node("t1", "First", status="completed"),
            _node("t2", "Second", status="pending"),
        ]
        emitted = []

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t2"],
        ):
            mw.before_model(_state(nodes=nodes), _runtime())

        completed_events = [e for e in emitted if e.get("type") == "phase_completed"]
        assert len(completed_events) == 1
        assert completed_events[0]["todo_id"] == "t1"

    def test_switches_to_reconcile_instruction_after_repeat_threshold(self):
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Analyze code", status="pending")]
        phase_execution: dict | None = None

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            for i in range(1, 6):
                result = mw.before_model(_state(nodes=nodes, phase_execution=phase_execution), _runtime())
                assert result is not None
                assert "Execute the following task now" in result["messages"][0].content
                assert result["phase_execution"]["last_instruction_kind"] == "task"
                assert result["phase_execution"]["repeat_counts"]["t1"] == i
                phase_execution = result["phase_execution"]

            result = mw.before_model(_state(nodes=nodes, phase_execution=phase_execution), _runtime())
            assert result is not None
            content = result["messages"][0].content
            assert "Reconcile todo state now for todo id 't1' only." in content
            assert "Do not call other tools in this turn." in content
            assert result["phase_execution"]["last_instruction_kind"] == "reconcile"
            assert result["phase_execution"]["forced_reconcile_done"]["t1"] is True

            phase_execution = result["phase_execution"]
            result = mw.before_model(_state(nodes=nodes, phase_execution=phase_execution), _runtime())
            assert result is not None
            assert "Execute the following task now" in result["messages"][0].content
            assert result["phase_execution"]["last_instruction_kind"] == "task"

    def test_forces_reconcile_after_dangling_write_todos_event(self):
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Analyze code", status="pending")]
        phase_execution: dict | None = None
        runtime = _runtime(
            extra_context={
                "_phase_a_runtime_events": [
                    {
                        "source": "dangling_tool_call_middleware",
                        "event": "todo_update_dangling",
                        "tool_name": "write_todos",
                    }
                ]
            }
        )
        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            result = mw.before_model(_state(nodes=nodes, phase_execution=phase_execution), runtime)
        assert result is not None
        assert result["phase_execution"]["last_instruction_kind"] == "reconcile"
        assert "Reconcile todo state now for todo id 't1' only." in result["messages"][0].content


# ---------------------------------------------------------------------------
# All phases complete
# ---------------------------------------------------------------------------

class TestAllPhasesComplete:
    def test_returns_none_when_all_completed(self):
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Task", status="completed")]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=[],
        ):
            result = mw.before_model(_state(nodes=nodes), _runtime())

        assert result is None


# ---------------------------------------------------------------------------
# Plan adaptation
# ---------------------------------------------------------------------------

class TestPlanAdaptation:
    def test_emits_plan_adapted_sse_when_no_ready_pending(self):
        """Nodes exist but none are ready (e.g., all blocked) — emits plan_adapted SSE."""
        mw = WorkModeMiddleware()
        emitted = []
        nodes = [_node("t1", "Blocked task", status="blocked")]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=[],
        ):
            result = mw.before_model(_state(nodes=nodes), _runtime())

        adapted = [e for e in emitted if e.get("type") == "plan_adapted"]
        assert len(adapted) == 1
        assert result is not None
        assert result["phase_execution"]["plan_adapted"] is True

    def test_increments_adaptation_attempts(self):
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Task", status="blocked")]
        pe = {"adaptation_attempts": 1}

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=[],
        ):
            result = mw.before_model(_state(nodes=nodes, phase_execution=pe), _runtime())

        assert result is not None
        assert result["phase_execution"]["adaptation_attempts"] == 2

    def test_spawns_plan_rerun_when_auto_mode_and_under_limit(self):
        mw = WorkModeMiddleware()
        spawned: list[dict] = []
        nodes = [_node("t1", "Task", status="blocked")]
        pe = {"adaptation_attempts": 0}

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=[],
        ), patch(
            "src.agents.middlewares.work_mode_middleware._spawn_plan_rerun",
            side_effect=lambda **kw: spawned.append(kw),
        ):
            mw.before_model(
                _state(nodes=nodes, phase_execution=pe),
                _runtime(auto_mode=True, thread_id="t-adapt"),
            )

        assert len(spawned) == 1
        assert spawned[0]["thread_id"] == "t-adapt"

    def test_no_spawn_when_adaptation_limit_reached(self):
        mw = WorkModeMiddleware()
        spawned: list[dict] = []
        nodes = [_node("t1", "Task", status="blocked")]
        pe = {"adaptation_attempts": _MAX_AUTO_ADAPTATION_ATTEMPTS}

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=[],
        ), patch(
            "src.agents.middlewares.work_mode_middleware._spawn_plan_rerun",
            side_effect=lambda **kw: spawned.append(kw),
        ):
            mw.before_model(
                _state(nodes=nodes, phase_execution=pe),
                _runtime(auto_mode=True),
            )

        assert spawned == []

    def test_adaptation_limit_constant_is_two(self):
        assert _MAX_AUTO_ADAPTATION_ATTEMPTS == 2


# ---------------------------------------------------------------------------
# Bug 1 regression: in_progress node must not trigger plan_adapted
# ---------------------------------------------------------------------------

class TestInProgressNodeDoesNotTriggerAdaptation:
    def test_no_plan_adapted_when_todo_is_in_progress(self):
        """An in_progress todo with no pending_ready should wait, not fire plan_adapted."""
        mw = WorkModeMiddleware()
        emitted = []
        # One node is actively running; _materialize_ready_ids includes it but
        # pending_ready will filter it out — pending_nodes must also exclude it.
        nodes = [_node("t1", "Running task", status="in_progress")]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            result = mw.before_model(_state(nodes=nodes), _runtime())

        adapted_events = [e for e in emitted if e.get("type") == "plan_adapted"]
        assert adapted_events == [], "plan_adapted must not fire when a todo is in_progress"
        assert result is None

    def test_no_plan_adapted_when_mix_of_in_progress_and_blocked(self):
        """in_progress + blocked nodes: plan is not stuck, just waiting."""
        mw = WorkModeMiddleware()
        emitted = []
        nodes = [
            _node("t1", "Running", status="in_progress"),
            _node("t2", "Waiting", status="blocked"),
        ]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            result = mw.before_model(_state(nodes=nodes), _runtime())

        adapted_events = [e for e in emitted if e.get("type") == "plan_adapted"]
        assert adapted_events == []
        assert result is None


# ---------------------------------------------------------------------------
# Bug 2 regression: first-cycle seeding suppresses spurious phase_completed
# ---------------------------------------------------------------------------

class TestFirstCycleSeeding:
    def test_no_phase_completed_on_first_cycle_for_preexisting_completions(self):
        """On the very first call, already-completed todos must NOT emit phase_completed."""
        mw = WorkModeMiddleware()
        assert mw._completed_before is None  # fresh instance

        emitted = []
        # t1 was completed before this run started (e.g., resumed thread).
        nodes = [
            _node("t1", "Already done", status="completed"),
            _node("t2", "Next task", status="pending"),
        ]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t2"],
        ):
            mw.before_model(_state(nodes=nodes), _runtime())

        completed_events = [e for e in emitted if e.get("type") == "phase_completed"]
        assert completed_events == [], "pre-existing completions must not re-emit phase_completed on first cycle"

    def test_phase_completed_emitted_on_second_cycle_for_new_completion(self):
        """After seeding, a todo completing DURING execution IS detected correctly."""
        mw = WorkModeMiddleware()
        nodes_cycle1 = [
            _node("t1", "First", status="pending"),
        ]
        nodes_cycle2 = [
            _node("t1", "First", status="completed"),
            _node("t2", "Second", status="pending"),
        ]

        writer_calls: list[dict] = []

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: writer_calls.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            # Cycle 1: t1 is pending, seeds _completed_before = frozenset()
            mw.before_model(_state(nodes=nodes_cycle1), _runtime())

        writer_calls.clear()

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: writer_calls.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t2"],
        ):
            # Cycle 2: t1 is now completed — should emit phase_completed
            mw.before_model(_state(nodes=nodes_cycle2), _runtime())

        completed_events = [e for e in writer_calls if e.get("type") == "phase_completed"]
        assert len(completed_events) == 1
        assert completed_events[0]["todo_id"] == "t1"
