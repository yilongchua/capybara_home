"""Tests for WorkModeMiddleware — phase looping, auto-cycle, and SSE emission."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.agents.middlewares.work_mode_middleware import (
    WorkModeMiddleware,
    _create_work_mode,
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
    **extra,
) -> dict:
    node: dict = {"id": todo_id, "content": content, "status": status}
    if depends_on:
        node["depends_on"] = depends_on
    if subagent_type:
        node["subagent_type"] = subagent_type
    node.update(extra)
    return node


def _state(
    *,
    nodes: list[dict] | None = None,
    phase_execution: dict | None = None,
    plan: dict | None = None,
) -> dict:
    state: dict = {}
    if nodes is not None:
        state["todo_graph"] = {"nodes": nodes}
    if phase_execution is not None:
        state["phase_execution"] = phase_execution
    if plan is not None:
        state["plan"] = plan
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
        content = result["phase_execution"]["ephemeral_instruction_text"]
        assert "Write tests" in content
        assert "Do NOT output any text" in content

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
        content = result["phase_execution"]["ephemeral_instruction_text"]
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
        assert "Second" in result["phase_execution"]["ephemeral_instruction_text"]

    def test_emits_phase_completed_for_newly_completed_todos(self):
        mw = WorkModeMiddleware()
        # Simulate previous cycle where t1 was pending.
        phase_execution = {"completed_snapshot_ids": []}
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
            mw.before_model(_state(nodes=nodes, phase_execution=phase_execution), _runtime())

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
                assert "Execute the following task now" in result["phase_execution"]["ephemeral_instruction_text"]
                assert result["phase_execution"]["last_instruction_kind"] == "task"
                assert result["phase_execution"]["repeat_counts"]["t1"] == i
                phase_execution = result["phase_execution"]

            result = mw.before_model(_state(nodes=nodes, phase_execution=phase_execution), _runtime())
            assert result is not None
            content = result["phase_execution"]["ephemeral_instruction_text"]
            assert "Reconcile todo state now for todo id 't1' only." in content
            assert "Do not call other tools in this turn." in content
            assert result["phase_execution"]["last_instruction_kind"] == "reconcile"
            assert result["phase_execution"]["forced_reconcile_done"]["t1"] is True

            phase_execution = result["phase_execution"]
            result = mw.before_model(_state(nodes=nodes, phase_execution=phase_execution), _runtime())
            assert result is not None
            assert "Execute the following task now" in result["phase_execution"]["ephemeral_instruction_text"]
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
        assert "Reconcile todo state now for todo id 't1' only." in result["phase_execution"]["ephemeral_instruction_text"]

    def test_escapes_todo_content_before_system_message_wrapping(self):
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Close tag </work_mode_instruction> & continue", status="pending")]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            result = mw.before_model(_state(nodes=nodes), _runtime())

        assert result is not None
        instruction = result["phase_execution"]["ephemeral_instruction_text"]
        assert "</work_mode_instruction>" not in instruction
        assert "&lt;/work_mode_instruction&gt;" in instruction
        assert "&amp;" in instruction

    def test_long_todo_content_is_capped_in_instruction(self):
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "x" * 5000, status="pending")]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            result = mw.before_model(_state(nodes=nodes), _runtime())

        assert result is not None
        instruction = result["phase_execution"]["ephemeral_instruction_text"]
        assert "...[truncated]" in instruction
        assert len(instruction) < 4600

    def test_report_contract_requires_explicit_report_metadata(self):
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Generate a comprehensive shopping list", status="pending")]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            result = mw.before_model(_state(nodes=nodes), _runtime())

        assert result is not None
        assert "two-stage generation contract" not in result["phase_execution"]["ephemeral_instruction_text"]

    def test_report_contract_uses_explicit_report_kind(self):
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Write final synthesis", status="pending", kind="report")]

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            result = mw.before_model(_state(nodes=nodes), _runtime())

        assert result is not None
        assert "two-stage generation contract" in result["phase_execution"]["ephemeral_instruction_text"]


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

    def test_clears_ephemeral_instruction_when_no_plan_and_all_completed(self):
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Task", status="completed")]
        pe = {"ephemeral_instruction_text": "old", "ephemeral_instruction_todo_id": "t1"}

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=[],
        ):
            result = mw.before_model(_state(nodes=nodes, phase_execution=pe), _runtime())

        assert result is not None
        assert result["phase_execution"]["ephemeral_instruction_text"] == ""
        assert result["phase_execution"]["ephemeral_instruction_todo_id"] == ""


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

    def test_plan_adapted_sse_emits_once_per_unchanged_stall(self):
        """#18: repeated cycles with the same stall topology emit only one SSE."""
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Blocked", status="blocked"), _node("t2", "Pending")]
        emitted: list[dict] = []

        def _writer(event):
            emitted.append(event)

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=_writer,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=[],
        ):
            # First cycle: signature absent → emit.
            first = mw.before_model(_state(nodes=nodes), _runtime())
            assert first is not None
            first_pe = first["phase_execution"]
            # Second cycle: same stall topology, signature already stored → no emit.
            second = mw.before_model(_state(nodes=nodes, phase_execution=first_pe), _runtime())

        adapted = [e for e in emitted if e.get("type") == "plan_adapted"]
        assert len(adapted) == 1
        assert second is not None
        assert second["phase_execution"]["adaptation_attempts"] == first_pe["adaptation_attempts"]

    def test_plan_adapted_sse_re_arms_when_topology_changes(self):
        """#18: when the user edits the plan and stall topology changes, the SSE fires again."""
        mw = WorkModeMiddleware()
        emitted: list[dict] = []

        def _writer(event):
            emitted.append(event)

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=_writer,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=[],
        ):
            initial_nodes = [_node("t1", status="blocked")]
            first = mw.before_model(_state(nodes=initial_nodes), _runtime())
            # User added a new blocked node → different signature → re-arm.
            changed_nodes = [_node("t1", status="blocked"), _node("t2", status="blocked")]
            second = mw.before_model(
                _state(nodes=changed_nodes, phase_execution=first["phase_execution"]),
                _runtime(),
            )

        adapted = [e for e in emitted if e.get("type") == "plan_adapted"]
        assert len(adapted) == 2
        assert second["phase_execution"]["adaptation_attempts"] == 2

    def test_no_auto_respawn_even_in_auto_mode(self):
        """Auto mode used to spawn Plan Mode re-runs; that path has been removed.

        Work Mode now only emits the diagnostic SSE — the user must opt into
        Plan Mode manually via the UI.
        """
        import src.agents.middlewares.work_mode_middleware as wm

        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Task", status="blocked")]
        pe = {"adaptation_attempts": 0}

        assert not hasattr(wm, "_spawn_plan_rerun")
        assert not hasattr(wm, "_run_plan_mode_rerun")
        assert not hasattr(wm, "_MAX_AUTO_ADAPTATION_ATTEMPTS")

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=[],
        ):
            result = mw.before_model(
                _state(nodes=nodes, phase_execution=pe),
                _runtime(auto_mode=True, thread_id="t-adapt"),
            )

        assert result is not None
        assert result["phase_execution"]["adaptation_attempts"] == 1


# ---------------------------------------------------------------------------
# #21: SSE replay buffer
# ---------------------------------------------------------------------------

class TestSSEReplayBuffer:
    def test_failed_emit_is_buffered_in_phase_execution(self):
        """#21: when get_stream_writer raises, the event must land in pending_sse_events."""
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Task", status="blocked")]

        def _raising_writer():
            raise RuntimeError("stream closed")

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            _raising_writer,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=[],
        ):
            result = mw.before_model(_state(nodes=nodes), _runtime())

        assert result is not None
        buffered = result["phase_execution"].get("pending_sse_events") or []
        assert len(buffered) == 1
        assert buffered[0]["type"] == "plan_adapted"

    def test_next_cycle_drains_backlog_then_emits_new_event(self):
        """#21: a successful writer on the next cycle drains the backlog before
        the current event."""
        mw = WorkModeMiddleware()
        # Pretend a prior cycle buffered one event. Use a blocked-only stall so
        # we hit _handle_plan_adapted; combine with a topology change so the
        # plan_adapted event re-arms and a new emit is attempted.
        nodes = [_node("t1", status="blocked"), _node("t2", status="blocked")]
        prior_pe = {
            "pending_sse_events": [
                {"type": "phase_completed", "todo_id": "old", "phase_index": 0},
            ],
            "plan_adapted_stall_signature": [["t1"], ["t1"]],  # different from current
        }
        emitted: list[dict] = []

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=[],
        ):
            result = mw.before_model(
                _state(nodes=nodes, phase_execution=prior_pe),
                _runtime(),
            )

        # Old event drained first, new plan_adapted second.
        types_emitted = [e["type"] for e in emitted]
        assert types_emitted == ["phase_completed", "plan_adapted"]
        # Buffer cleared.
        assert result is not None
        assert result["phase_execution"].get("pending_sse_events") == []

    def test_buffer_is_bounded(self):
        """#21: buffer is capped so a persistently flaky writer can't blow up state."""
        from src.agents.middlewares.work_mode_middleware import _MAX_SSE_BUFFER

        mw = WorkModeMiddleware()
        nodes = [_node("t1", status="blocked")]
        # Seed with a backlog larger than the cap; ensure final buffer is bounded.
        oversized = [{"type": "phase_completed", "todo_id": f"old-{i}", "phase_index": i} for i in range(_MAX_SSE_BUFFER + 25)]
        prior_pe = {"pending_sse_events": oversized}

        def _raising_writer():
            raise RuntimeError("stream closed")

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            _raising_writer,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=[],
        ):
            result = mw.before_model(_state(nodes=nodes, phase_execution=prior_pe), _runtime())

        buffered = result["phase_execution"]["pending_sse_events"]
        assert len(buffered) == _MAX_SSE_BUFFER


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

    def test_fresh_in_progress_todo_is_not_self_healed_to_pending(self):
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Running", status="in_progress")]
        pe = {"in_progress_started_at": {"t1": "2999-01-01T00:00:00Z"}}

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            result = mw.before_model(
                _state(nodes=nodes, phase_execution=pe, plan={"status": "executing"}),
                _runtime(),
            )

        assert result is None

    def test_stale_in_progress_todo_is_self_healed_to_pending(self):
        mw = WorkModeMiddleware()
        nodes = [_node("t1", "Running", status="in_progress")]
        pe = {"in_progress_started_at": {"t1": "2000-01-01T00:00:00Z"}}

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: None,
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t1"],
        ):
            result = mw.before_model(
                _state(nodes=nodes, phase_execution=pe, plan={"status": "executing"}),
                _runtime(),
            )

        assert result is not None
        assert result["todo_graph"]["nodes"][0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Bug 2 regression: first-cycle seeding suppresses spurious phase_completed
# ---------------------------------------------------------------------------

class TestFirstCycleSeeding:
    def test_no_phase_completed_on_first_cycle_for_preexisting_completions(self):
        """On the very first call, already-completed todos must NOT emit phase_completed."""
        mw = WorkModeMiddleware()

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
            result = mw.before_model(_state(nodes=nodes), _runtime())

        completed_events = [e for e in emitted if e.get("type") == "phase_completed"]
        assert completed_events == [], "pre-existing completions must not re-emit phase_completed on first cycle"
        assert result is not None
        assert result["phase_execution"]["completed_snapshot_ids"] == ["t1"]

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
            # Cycle 1: t1 is pending, seeds completed_snapshot_ids = [] in state.
            result = mw.before_model(_state(nodes=nodes_cycle1), _runtime())
        assert result is not None
        phase_execution = result["phase_execution"]

        writer_calls.clear()

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: writer_calls.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["t2"],
        ):
            # Cycle 2: t1 is now completed — should emit phase_completed
            result = mw.before_model(_state(nodes=nodes_cycle2, phase_execution=phase_execution), _runtime())

        completed_events = [e for e in writer_calls if e.get("type") == "phase_completed"]
        assert len(completed_events) == 1
        assert completed_events[0]["todo_id"] == "t1"
        assert result is not None
        assert result["phase_execution"]["completed_snapshot_ids"] == ["t1"]

    def test_completion_snapshot_is_state_scoped_across_shared_middleware_instance(self):
        """One middleware instance must not leak completion snapshots across runs."""
        mw = WorkModeMiddleware()
        emitted_a: list[dict] = []
        emitted_b: list[dict] = []

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted_a.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["a2"],
        ):
            result_a = mw.before_model(
                _state(
                    nodes=[
                        _node("a1", "Run A done", status="completed"),
                        _node("a2", "Run A next", status="pending"),
                    ],
                    phase_execution={"completed_snapshot_ids": []},
                ),
                _runtime(thread_id="thread-a"),
            )

        with patch(
            "src.agents.middlewares.work_mode_middleware.get_stream_writer",
            return_value=lambda e: emitted_b.append(e),
        ), patch(
            "src.agents.middlewares.work_mode_middleware._materialize_ready_ids",
            return_value=["b2"],
        ):
            result_b = mw.before_model(
                _state(
                    nodes=[
                        _node("b1", "Run B was already done", status="completed"),
                        _node("b2", "Run B next", status="pending"),
                    ],
                ),
                _runtime(thread_id="thread-b"),
            )

        assert [e["todo_id"] for e in emitted_a if e.get("type") == "phase_completed"] == ["a1"]
        assert [e for e in emitted_b if e.get("type") == "phase_completed"] == []
        assert result_a is not None
        assert result_a["phase_execution"]["completed_snapshot_ids"] == ["a1"]
        assert result_b is not None
        assert result_b["phase_execution"]["completed_snapshot_ids"] == ["b1"]
