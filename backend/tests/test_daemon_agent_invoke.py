"""Tests for async agent invocation from sync daemon threads."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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
