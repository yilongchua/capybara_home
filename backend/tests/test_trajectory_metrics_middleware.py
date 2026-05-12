"""Tests for trajectory and metrics middlewares."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage

from src.agents.middlewares.metrics_middleware import MetricsMiddleware, get_metrics_snapshot, reset_metrics_snapshot
from src.agents.middlewares.trajectory_middleware import TrajectoryMiddleware
from src.config.metrics_config import MetricsConfig, set_metrics_config
from src.config.paths import Paths
from src.config.trajectory_config import TrajectoryConfig, set_trajectory_config


def test_trajectory_file_contains_required_events(monkeypatch, tmp_path: Path):
    set_trajectory_config(TrajectoryConfig(enabled=True, file_prefix="test-trajectory"))
    monkeypatch.setattr("src.agents.middlewares.trajectory_middleware.get_paths", lambda: Paths(base_dir=tmp_path))

    middleware = TrajectoryMiddleware()
    runtime = SimpleNamespace(context={"thread_id": "thread-1"})
    state = {"messages": [AIMessage(content="hello")]}

    before_agent = middleware.before_agent(state, runtime) or {}
    state.update(before_agent)
    middleware.before_model(state, runtime)
    middleware.after_model(state, runtime)

    request = SimpleNamespace(
        tool_call={"name": "read_file", "id": "tc-1", "args": {"path": "/tmp/a"}},
        state=state,
        runtime=runtime,
    )
    middleware.wrap_tool_call(request, lambda _: ToolMessage(content="ok", tool_call_id="tc-1", name="read_file"))

    trajectory_path = Path(state["trajectory"]["file_path"])
    assert trajectory_path.exists()
    events = [json.loads(line) for line in trajectory_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    event_names = {event["event"] for event in events}
    assert {"before_agent", "before_model", "after_model", "tool_call_start", "tool_call_end"}.issubset(event_names)


def test_metrics_collects_primary_endpoint_labels():
    set_metrics_config(MetricsConfig(enabled=True))
    reset_metrics_snapshot()
    middleware = MetricsMiddleware()
    runtime = SimpleNamespace(context={"thread_id": "thread-1"})
    state = {"messages": [AIMessage(content="hello")]}
    middleware.before_model(state, runtime)
    middleware.after_model(state, runtime)

    request = SimpleNamespace(
        tool_call={"name": "read_file", "id": "tc-1", "args": {"path": "/tmp/a"}},
        runtime=runtime,
    )
    middleware.wrap_tool_call(request, lambda _: ToolMessage(content="ok", tool_call_id="tc-1", name="read_file"))

    snapshot = get_metrics_snapshot()
    assert any("endpoint=primary" in key for key in snapshot)
    assert any("lead_agent.before_model" in key for key in snapshot)
    assert any("lead_agent.tool_call.start" in key for key in snapshot)


def test_trajectory_calls_fsync_when_enabled(monkeypatch, tmp_path: Path):
    set_trajectory_config(TrajectoryConfig(enabled=True, file_prefix="test-trajectory", fsync=True))
    monkeypatch.setattr("src.agents.middlewares.trajectory_middleware.get_paths", lambda: Paths(base_dir=tmp_path))
    calls: list[int] = []
    monkeypatch.setattr("src.agents.middlewares.trajectory_middleware.os.fsync", lambda fileno: calls.append(fileno))

    middleware = TrajectoryMiddleware()
    runtime = SimpleNamespace(context={"thread_id": "thread-1"})
    state = {"messages": [AIMessage(content="hello")]}
    middleware.before_agent(state, runtime)

    assert len(calls) >= 1


def test_trajectory_skips_fsync_when_disabled(monkeypatch, tmp_path: Path):
    set_trajectory_config(TrajectoryConfig(enabled=True, file_prefix="test-trajectory", fsync=False))
    monkeypatch.setattr("src.agents.middlewares.trajectory_middleware.get_paths", lambda: Paths(base_dir=tmp_path))
    calls: list[int] = []
    monkeypatch.setattr("src.agents.middlewares.trajectory_middleware.os.fsync", lambda fileno: calls.append(fileno))

    middleware = TrajectoryMiddleware()
    runtime = SimpleNamespace(context={"thread_id": "thread-1"})
    state = {"messages": [AIMessage(content="hello")]}
    middleware.before_agent(state, runtime)

    assert calls == []
