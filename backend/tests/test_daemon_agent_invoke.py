"""Tests for async agent invocation from sync daemon threads."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.agents.middlewares import work_run_handoff
from src.agents.middlewares.daemon_agent_invoke import invoke_agent_async, invoke_client_agent_async
from src.agents.middlewares.pro_followup_middleware import _run_background_followup
from src.agents.middlewares.work_run_handoff import _run_work_mode_handoff


def test_invoke_agent_async_uses_ainvoke():
    agent = MagicMock()
    agent.ainvoke = AsyncMock(return_value={"ok": True})
    agent.invoke = MagicMock()

    result = invoke_agent_async(
        agent,
        {"messages": []},
        config={"configurable": {"thread_id": "t1"}},
        context={"thread_id": "t1"},
    )

    assert result == {"ok": True}
    agent.ainvoke.assert_awaited_once()
    agent.invoke.assert_not_called()


def test_run_work_mode_handoff_uses_async_invoke(monkeypatch):
    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": []})
    mock_agent.invoke = MagicMock()

    mock_client = MagicMock()
    mock_client._get_runnable_config.return_value = {"configurable": {}}
    mock_client._agent = mock_agent

    monkeypatch.setattr("src.client.CapyHomeClient", lambda **kwargs: mock_client)
    monkeypatch.setattr(
        "src.agents.middlewares.work_run_handoff.spawn_title_handoff_if_missing",
        lambda **kwargs: None,
    )
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _run_work_mode_handoff(
        thread_id="thread-abc",
        requested_model_name=None,
        auto_mode=False,
        original_user_request="hello",
        delay_seconds=0,
    )

    mock_agent.invoke.assert_not_called()
    mock_agent.ainvoke.assert_awaited_once()


def test_work_handoff_update_state_payload_has_no_title_key(monkeypatch):
    """#15: work-handoff `update_state` payloads must contain only `plan`.

    The title-handoff writes the top-level `title` key; the work-handoff writes
    only `plan`. The contract is documented in `work_run_handoff.py`. If a
    future change bundles `title` into the work-handoff payload, two daemons
    would target the same key and the original concurrency race could surface.
    This test pins the contract at the call site.
    """
    captured: list[dict] = []

    class _Threads:
        def get_state(self, _thread_id):
            return {"values": {"plan": {"status": "approved", "title": "Plan title"}}}

        def update_state(self, _thread_id, payload):
            captured.append(payload)

    class _LGClient:
        threads = _Threads()

    monkeypatch.setattr("langgraph_sdk.get_client", lambda url=None: _LGClient())

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": []})
    mock_client = MagicMock()
    mock_client._get_runnable_config.return_value = {"configurable": {}}
    mock_client._agent = mock_agent
    monkeypatch.setattr("src.client.CapyHomeClient", lambda **kwargs: mock_client)
    monkeypatch.setattr(
        "src.agents.middlewares.work_run_handoff.spawn_title_handoff_if_missing",
        lambda **kwargs: None,
    )
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _run_work_mode_handoff(
        thread_id="thread-contract",
        requested_model_name=None,
        auto_mode=False,
        original_user_request="hello",
        delay_seconds=0,
    )

    assert captured, "expected at least one update_state call from the work handoff"
    for payload in captured:
        assert "title" not in payload, (
            f"work-handoff update_state payload must not include 'title' "
            f"(disjoint-key contract); got {payload!r}"
        )
        assert set(payload.keys()) <= {"plan"}, (
            f"work-handoff update_state payload should only carry 'plan'; got keys {list(payload.keys())!r}"
        )


def test_work_mode_handoff_spawn_cleans_guard_when_submit_fails(monkeypatch):
    work_run_handoff._IN_FLIGHT_HANDOFFS.clear()

    monkeypatch.setattr(work_run_handoff, "submit_background_task", lambda *args, **kwargs: False)
    work_run_handoff.spawn_work_mode_handoff(
        thread_id="thread-start-fails",
        requested_model_name=None,
        auto_mode=False,
    )

    assert "thread-start-fails" not in work_run_handoff._IN_FLIGHT_HANDOFFS


def test_worker_awaitable_helper_reuses_persistent_loop():
    async def loop_id():
        return id(asyncio.get_running_loop())

    loop = asyncio.new_event_loop()
    try:
        first = work_run_handoff._run_awaitable_in_worker(loop_id(), loop)
        second = work_run_handoff._run_awaitable_in_worker(loop_id(), loop)
    finally:
        loop.close()

    assert first == second


def test_run_background_followup_uses_async_invoke(monkeypatch):
    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": []})
    mock_agent.invoke = MagicMock()

    mock_client = MagicMock()
    mock_client._get_runnable_config.return_value = {"configurable": {}}
    mock_client._agent = mock_agent

    monkeypatch.setattr("src.client.CapyHomeClient", lambda **kwargs: mock_client)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _run_background_followup(
        thread_id="thread-abc",
        job_id="job-1",
        requested_model_name=None,
        summary_prompt="Summarize progress.",
    )

    mock_agent.invoke.assert_not_called()
    mock_agent.ainvoke.assert_awaited_once()


def test_invoke_client_agent_async_retries_with_async_checkpointer(monkeypatch):
    sync_agent = MagicMock()
    sync_agent.ainvoke = AsyncMock(side_effect=NotImplementedError("The SqliteSaver does not support async methods."))

    async_agent = MagicMock()
    async_agent.ainvoke = AsyncMock(return_value={"messages": ["ok"]})

    class _FakeAsyncCheckpointerCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

    class _FakeClient:
        def __init__(self):
            self._checkpointer = "sync-checkpointer"
            self._agent = sync_agent
            self._agent_config_key = "original-key"
            self.ensure_calls = 0

        def reset_agent(self):
            self._agent = None
            self._agent_config_key = None

        def _ensure_agent(self, _config):
            self.ensure_calls += 1
            if self._checkpointer == "sync-checkpointer":
                self._agent = sync_agent
                self._agent_config_key = "sync-key"
            else:
                self._agent = async_agent
                self._agent_config_key = "async-key"

    client = _FakeClient()
    monkeypatch.setattr("src.agents.checkpointer.async_provider.make_checkpointer", lambda: _FakeAsyncCheckpointerCtx())

    result = invoke_client_agent_async(
        client,
        {"messages": []},
        config={"configurable": {"thread_id": "t1"}},
        context={"thread_id": "t1"},
    )

    assert result == {"messages": ["ok"]}
    sync_agent.ainvoke.assert_awaited_once()
    async_agent.ainvoke.assert_awaited_once()
    assert client._checkpointer == "sync-checkpointer"
    assert client._agent is sync_agent
    assert client._agent_config_key == "sync-key"
