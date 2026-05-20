"""Tests for async agent invocation from sync daemon threads."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from src.agents.middlewares.daemon_agent_invoke import invoke_agent_async
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

    monkeypatch.setattr("src.client.CapybaraClient", lambda **kwargs: mock_client)
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

    monkeypatch.setattr("src.client.CapybaraClient", lambda **kwargs: mock_client)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    _run_background_followup(
        thread_id="thread-abc",
        job_id="job-1",
        requested_model_name=None,
        summary_prompt="Summarize progress.",
    )

    mock_agent.invoke.assert_not_called()
    mock_agent.ainvoke.assert_awaited_once()
