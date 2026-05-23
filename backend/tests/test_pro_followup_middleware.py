"""Tests for PlanFollowupMiddleware background-failure surfacing (P5)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_runtime(thread_id: str = "thread-xyz", *, mode: str = "work") -> SimpleNamespace:
    return SimpleNamespace(context={"thread_id": thread_id, "mode": mode})


class TestPlanFollowupFailureSurfacing:
    def setup_method(self):
        # Clear the shared failure dict before each test for isolation.

        import src.agents.middlewares.pro_followup_middleware as mod

        self._mod = mod
        with mod._failed_jobs_lock:
            mod._failed_jobs.clear()

    def test_run_background_followup_records_failure(self):
        """_run_background_followup must record the error in _failed_jobs on exception."""
        import sys
        import types

        mod = self._mod

        # CapyHomeClient is imported locally inside the function (from src.client import …).
        # Inject a lightweight stub so we don't pull in the full src.client dep tree.
        mock_client_instance = MagicMock()
        mock_client_instance._get_runnable_config.return_value = {"configurable": {}}
        mock_client_instance._ensure_agent.return_value = None
        mock_client_instance._agent.invoke.side_effect = RuntimeError("model unavailable")

        mock_client_cls = MagicMock(return_value=mock_client_instance)
        stub_module = types.ModuleType("src.client")
        stub_module.CapyHomeClient = mock_client_cls  # type: ignore[attr-defined]

        original = sys.modules.get("src.client")
        sys.modules["src.client"] = stub_module
        try:
            with patch("src.agents.middlewares.pro_followup_middleware.time.sleep"):
                mod._run_background_followup(
                    thread_id="thread-fail",
                    job_id="job-001",
                    requested_model_name=None,
                    summary_prompt="continue...",
                )
        finally:
            if original is not None:
                sys.modules["src.client"] = original
            else:
                sys.modules.pop("src.client", None)

        with mod._failed_jobs_lock:
            assert "thread-fail" in mod._failed_jobs
            job_id, error_msg = mod._failed_jobs["thread-fail"]
        assert job_id == "job-001"
        assert "model unavailable" in error_msg

    def test_before_model_emits_sse_for_failed_job_and_clears_entry(self):
        """before_model must emit SSE for any recorded failure and remove the entry."""
        mod = self._mod

        # Pre-populate a failure entry.
        with mod._failed_jobs_lock:
            mod._failed_jobs["thread-xyz"] = ("job-002", "something went wrong")

        emitted = []

        def fake_writer(event):
            emitted.append(event)

        with patch(
            "src.agents.middlewares.pro_followup_middleware.get_stream_writer",
            return_value=fake_writer,
        ):
            middleware = mod.PlanFollowupMiddleware()
            runtime = _make_runtime("thread-xyz")
            middleware.before_model({}, runtime)

        assert len(emitted) == 1
        evt = emitted[0]
        assert evt["type"] == "background_followup_failed"
        assert evt["job_id"] == "job-002"
        assert "something went wrong" in evt["error"]

        # Entry must be consumed so it isn't replayed on the next turn.
        with mod._failed_jobs_lock:
            assert "thread-xyz" not in mod._failed_jobs

    def test_before_model_does_not_emit_when_no_failure(self):
        """before_model must not emit SSE when no failure is recorded for the thread."""
        mod = self._mod
        emitted = []

        with patch(
            "src.agents.middlewares.pro_followup_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ):
            middleware = mod.PlanFollowupMiddleware()
            runtime = _make_runtime("thread-clean")
            middleware.before_model({}, runtime)

        assert not emitted

    def test_failed_jobs_isolation_across_threads(self):
        """Failures for one thread must not appear when querying a different thread."""
        mod = self._mod
        with mod._failed_jobs_lock:
            mod._failed_jobs["thread-A"] = ("job-A", "error A")

        emitted = []
        with patch(
            "src.agents.middlewares.pro_followup_middleware.get_stream_writer",
            return_value=lambda e: emitted.append(e),
        ):
            middleware = mod.PlanFollowupMiddleware()
            runtime = _make_runtime("thread-B")  # different thread
            middleware.before_model({}, runtime)

        assert not emitted
        # thread-A entry must still be present (not consumed by thread-B's call)
        with mod._failed_jobs_lock:
            assert "thread-A" in mod._failed_jobs

    def test_before_model_disables_background_deepen_without_plan_context(self):
        """Plan mode without plan/todo context must not advertise background deepening."""
        mod = self._mod
        middleware = mod.PlanFollowupMiddleware()
        runtime = _make_runtime("thread-no-plan")

        result = middleware.before_model({}, runtime)

        assert result is not None
        assert result["execution_intent"]["mode"] == "work"
        assert result["execution_intent"]["allow_background_deepen"] is False

    def test_after_model_skips_background_followup_without_plan_context(self):
        """Terminal work-mode answers should not spawn deepening jobs when no plan/todos exist."""
        mod = self._mod
        middleware = mod.PlanFollowupMiddleware()
        runtime = _make_runtime("thread-no-plan")
        state = {
            "messages": [
                SimpleNamespace(type="human", content="Check if drive is mounted."),
                SimpleNamespace(type="ai", content="Yes", tool_calls=[]),
            ]
        }

        with (
            patch("src.agents.middlewares.pro_followup_middleware.threading.Thread") as mock_thread,
            patch("src.agents.middlewares.pro_followup_middleware.get_config", return_value={"metadata": {}}),
        ):
            result = middleware.after_model(state, runtime)

        assert result is None
        mock_thread.assert_not_called()

    def test_after_model_uses_latest_real_user_prompt_not_synthetic_reminder(self):
        mod = self._mod
        middleware = mod.PlanFollowupMiddleware()
        runtime = _make_runtime("thread-followup")
        state = {
            "plan": {"status": "completed"},
            "todo_graph": {"nodes": [{"id": "todo-1", "status": "completed"}]},
            "messages": [
                SimpleNamespace(type="human", content="Find good bubble tea near town."),
                SimpleNamespace(type="human", name="todo_reminder", content="<system_reminder> Todo DAG remains active. </system_reminder>"),
                SimpleNamespace(type="ai", content="Here are two nearby options.", tool_calls=[]),
            ],
        }

        with (
            patch("src.agents.middlewares.pro_followup_middleware.threading.Thread") as mock_thread,
            patch("src.agents.middlewares.pro_followup_middleware.get_config", return_value={"metadata": {}}),
        ):
            result = middleware.after_model(state, runtime)

        assert result is not None
        kwargs = mock_thread.call_args.kwargs["kwargs"]
        assert "Find good bubble tea near town." in kwargs["summary_prompt"]
        assert "<system_reminder>" not in kwargs["summary_prompt"]

    def test_after_model_requires_completed_plan_and_todos(self):
        mod = self._mod
        middleware = mod.PlanFollowupMiddleware()
        runtime = _make_runtime("thread-incomplete")
        state = {
            "plan": {"status": "executing"},
            "todo_graph": {"nodes": [{"id": "todo-1", "status": "in_progress"}]},
            "messages": [
                SimpleNamespace(type="human", content="Investigate this."),
                SimpleNamespace(type="ai", content="Partial answer", tool_calls=[]),
            ],
        }

        with patch("src.agents.middlewares.pro_followup_middleware.threading.Thread") as mock_thread:
            result = middleware.after_model(state, runtime)

        assert result is None
        mock_thread.assert_not_called()
