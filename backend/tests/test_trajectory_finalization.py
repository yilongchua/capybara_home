"""Tests covering trajectory finalization + timeout fingerprint detection.

Regression for run-c0425b71bd: trajectory ended at `tool_call_start` for
write_todos because the run was abandoned mid-tool-call. The new try/finally
guarantees a `tool_call_end` event is always written.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, ToolMessage

from src.agents.middlewares.model_timeout_middleware import TIMEOUT_MESSAGE_FINGERPRINT
from src.agents.middlewares.trajectory_middleware import TrajectoryMiddleware
from src.config.paths import Paths
from src.config.trajectory_config import TrajectoryConfig, set_trajectory_config


def _read_events(state, tmp_path: Path | None = None) -> list[dict]:
    if "trajectory" in state and "file_path" in state["trajectory"]:
        path = Path(state["trajectory"]["file_path"])
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif tmp_path is not None:
        # Middleware creates separate files per event (state not updated).
        # Read all jsonl files and merge, sorted by timestamp in filename.
        all_events: list[dict] = []
        for f in sorted(tmp_path.rglob("*.jsonl")):
            all_events.extend(
                json.loads(line)
                for line in f.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        all_events.sort(key=lambda e: e.get("ts", 0))
        return all_events
    else:
        path = Path(state["trajectory"]["file_path"])
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_after_agent_event_is_emitted(monkeypatch, tmp_path: Path):
    set_trajectory_config(TrajectoryConfig(enabled=True, file_prefix="t"))
    monkeypatch.setattr("src.agents.middlewares.trajectory_middleware.get_paths", lambda: Paths(base_dir=tmp_path))

    middleware = TrajectoryMiddleware()
    runtime = SimpleNamespace(context={"thread_id": "th-1"})
    state: dict = {"messages": [AIMessage(content="hi")]}

    state.update(middleware.before_agent(state, runtime) or {})
    state.update(middleware.after_agent(state, runtime) or {})

    events = _read_events(state)
    names = [e["event"] for e in events]
    assert "after_agent" in names
    assert names[-1] == "after_agent"


def test_model_call_timeout_event_is_emitted(monkeypatch, tmp_path: Path):
    set_trajectory_config(TrajectoryConfig(enabled=True, file_prefix="t"))
    monkeypatch.setattr("src.agents.middlewares.trajectory_middleware.get_paths", lambda: Paths(base_dir=tmp_path))

    middleware = TrajectoryMiddleware()
    runtime = SimpleNamespace(context={"thread_id": "th-1"})
    state = {"messages": []}
    request = SimpleNamespace(state=state, runtime=runtime, messages=[])

    async def handler(_req):
        return ModelResponse(result=[AIMessage(content=f"{TIMEOUT_MESSAGE_FINGERPRINT}\nstuff")])

    asyncio.run(middleware.awrap_model_call(request, handler))

    events = _read_events(state, tmp_path)
    names = [e["event"] for e in events]
    assert "model_call_start" in names
    assert "model_call_timeout" in names
    assert "model_call_end" in names
    end_event = next(e for e in events if e["event"] == "model_call_end")
    assert end_event["payload"]["timed_out"] is True


def test_tool_call_end_emitted_even_on_handler_exception(monkeypatch, tmp_path: Path):
    """The bug we are guarding against: tool_call_start without tool_call_end."""
    set_trajectory_config(TrajectoryConfig(enabled=True, file_prefix="t"))
    monkeypatch.setattr("src.agents.middlewares.trajectory_middleware.get_paths", lambda: Paths(base_dir=tmp_path))

    middleware = TrajectoryMiddleware()
    runtime = SimpleNamespace(context={"thread_id": "th-1"})
    state = {"messages": []}
    request = SimpleNamespace(
        tool_call={"name": "write_todos", "id": "tc-x"},
        state=state,
        runtime=runtime,
    )

    async def handler(_req):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(middleware.awrap_tool_call(request, handler))

    events = _read_events(state, tmp_path)
    names = [e["event"] for e in events]
    assert names.count("tool_call_start") == 1
    assert names.count("tool_call_end") == 1, "tool_call_end must be emitted via finally"
    end = next(e for e in events if e["event"] == "tool_call_end")
    assert end["payload"]["error"] is not None
    assert "boom" in end["payload"]["error"]


def test_tool_call_timeout_event_detection(monkeypatch, tmp_path: Path):
    set_trajectory_config(TrajectoryConfig(enabled=True, file_prefix="t"))
    monkeypatch.setattr("src.agents.middlewares.trajectory_middleware.get_paths", lambda: Paths(base_dir=tmp_path))

    middleware = TrajectoryMiddleware()
    runtime = SimpleNamespace(context={"thread_id": "th-1"})
    state = {"messages": []}
    request = SimpleNamespace(
        tool_call={"name": "web_search", "id": "tc-x"},
        state=state,
        runtime=runtime,
    )

    async def handler(_req):
        # Simulates ModelTimeoutMiddleware injecting a synthetic tool message.
        return ToolMessage(
            content=f"{TIMEOUT_MESSAGE_FINGERPRINT}\ntimed out",
            tool_call_id="tc-x",
            name="web_search",
        )

    asyncio.run(middleware.awrap_tool_call(request, handler))
    events = _read_events(state, tmp_path)
    names = [e["event"] for e in events]
    assert "tool_call_timeout" in names
    end = next(e for e in events if e["event"] == "tool_call_end")
    assert end["payload"]["timed_out"] is True
