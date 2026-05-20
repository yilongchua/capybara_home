"""Core behavior tests for task tool orchestration."""

import importlib
from enum import Enum
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.subagents.config import SubagentConfig

# Use module import so tests can patch the exact symbols referenced inside task_tool().
task_tool_module = importlib.import_module("src.tools.builtins.task_tool")


class FakeSubagentStatus(Enum):
    # Match production enum values so branch comparisons behave identically.
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


def _make_runtime() -> SimpleNamespace:
    # Minimal ToolRuntime-like object; task_tool only reads these three attributes.
    return SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": "local"},
            "thread_data": {
                "workspace_path": "/tmp/workspace",
                "uploads_path": "/tmp/uploads",
                "outputs_path": "/tmp/outputs",
            },
        },
        context={"thread_id": "thread-1"},
        config={"metadata": {"model_name": "ark-model", "trace_id": "trace-1"}},
    )


def _make_subagent_config() -> SubagentConfig:
    return SubagentConfig(
        name="general-purpose",
        description="General helper",
        system_prompt="Base system prompt",
        max_turns=50,
        timeout_seconds=10,
    )


def _make_result(
    status: FakeSubagentStatus,
    *,
    ai_messages: list[dict] | None = None,
    result: str | None = None,
    error: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        ai_messages=ai_messages or [],
        result=result,
        error=error,
    )


def test_task_tool_returns_error_for_unknown_subagent(monkeypatch):
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: None)
    monkeypatch.setattr(task_tool_module, "get_subagent_names", lambda: ["general-purpose", "source-researcher"])

    result = task_tool_module.task_tool.func(
        runtime=None,
        description="执行任务",
        prompt="do work",
        subagent_type="general-purpose",
        tool_call_id="tc-1",
    )

    assert result.startswith("Error: Unknown subagent type")
    assert "source-researcher" in result


@pytest.mark.parametrize(
    "subagent_type",
    [
        "source-researcher",
        "docs-explorer",
        "comparison-dimension-researcher",
        "synthesis-reviewer",
    ],
)
def test_task_tool_accepts_registered_research_subagents(monkeypatch, subagent_type):
    config = SubagentConfig(
        name=subagent_type,
        description=f"{subagent_type} helper",
        system_prompt="Research subagent prompt",
        max_turns=5,
        timeout_seconds=10,
    )
    runtime = _make_runtime()
    events = []
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            captured["prompt"] = prompt
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda name: config if name == subagent_type else None)
    monkeypatch.setattr(task_tool_module, "get_skills_prompt_section", lambda: "")
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="research complete"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.time, "sleep", lambda _: None)
    monkeypatch.setattr("src.tools.get_available_tools", lambda **kwargs: [])

    output = task_tool_module.task_tool.func(
        runtime=runtime,
        description="research task",
        prompt="research one dimension",
        subagent_type=subagent_type,
        tool_call_id="tc-research",
    )

    assert output == "Task Succeeded. Result: research complete"
    assert captured["prompt"] == "research one dimension"
    assert captured["executor_kwargs"]["config"].name == subagent_type
    non_trace_events = [e for e in events if e.get("type") != "trace_event.v1"]
    assert non_trace_events[0]["type"] == "task_started"
    assert non_trace_events[0]["description"] == "research task"
    assert non_trace_events[0]["subagent_type"] == subagent_type
    assert non_trace_events[0]["group_title"] == f"{subagent_type}: research task"


def test_task_tool_emits_running_and_completed_events(monkeypatch):
    config = _make_subagent_config()
    runtime = _make_runtime()
    events = []
    runtime_events = []
    captured = {}
    get_available_tools = MagicMock(return_value=["tool-a", "tool-b"])

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            captured["prompt"] = prompt
            captured["task_id"] = task_id
            return task_id or "generated-task-id"

    # Simulate two polling rounds: first running (with one message), then completed.
    responses = iter(
        [
            _make_result(FakeSubagentStatus.RUNNING, ai_messages=[{"id": "m1", "content": "phase-1"}]),
            _make_result(
                FakeSubagentStatus.COMPLETED,
                ai_messages=[{"id": "m1", "content": "phase-1"}, {"id": "m2", "content": "phase-2"}],
                result="all done",
            ),
        ]
    )

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_skills_prompt_section", lambda: "Skills Appendix")
    monkeypatch.setattr(task_tool_module, "get_background_task_result", lambda _: next(responses))
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module, "append_runtime_event", lambda _runtime, event: runtime_events.append(event))
    monkeypatch.setattr(task_tool_module.time, "sleep", lambda _: None)
    # task_tool lazily imports from src.tools at call time, so patch that module-level function.
    monkeypatch.setattr("src.tools.get_available_tools", get_available_tools)

    output = task_tool_module.task_tool.func(
        runtime=runtime,
        description="运行子任务",
        prompt="collect diagnostics",
        subagent_type="general-purpose",
        tool_call_id="tc-123",
        max_turns=7,
    )

    assert output == "Task Succeeded. Result: all done"
    assert captured["prompt"] == "collect diagnostics"
    assert captured["task_id"] == "tc-123"
    assert captured["executor_kwargs"]["thread_id"] == "thread-1"
    assert captured["executor_kwargs"]["parent_model"] == "ark-model"
    assert captured["executor_kwargs"]["config"].max_turns == 7
    assert "Skills Appendix" in captured["executor_kwargs"]["config"].system_prompt

    get_available_tools.assert_called_once_with(model_name="ark-model", groups=None, subagent_enabled=False)

    event_types = [e["type"] for e in events if e.get("type") != "trace_event.v1"]
    assert event_types == ["task_started", "task_running", "task_running", "task_completed"]
    non_trace_events = [e for e in events if e.get("type") != "trace_event.v1"]
    assert non_trace_events[-1]["result"] == "all done"
    assert non_trace_events[0]["group_title"] == "general-purpose: 运行子任务"
    assert non_trace_events[1]["description"] == "运行子任务"
    assert non_trace_events[1]["subagent_type"] == "general-purpose"
    assert non_trace_events[-1]["group_title"] == "general-purpose: 运行子任务"
    assert [e["event"] for e in runtime_events] == [
        "task_started",
        "task_running",
        "task_running",
        "task_completed",
    ]
    assert all(isinstance(e.get("trace_event"), dict) for e in runtime_events)
    assert all(e.get("trace_already_streamed") is True for e in runtime_events)


def test_task_tool_forwards_parent_agent_tool_groups(monkeypatch):
    config = _make_subagent_config()
    runtime = _make_runtime()
    runtime.config["metadata"]["agent_name"] = "restricted"
    get_available_tools = MagicMock(return_value=[])
    captured = {}

    class DummyExecutor:
        def __init__(self, **kwargs):
            captured["executor_kwargs"] = kwargs

        def execute_async(self, prompt, task_id=None):
            return task_id or "generated-task-id"

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(task_tool_module, "SubagentExecutor", DummyExecutor)
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_skills_prompt_section", lambda: "")
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: lambda _: None)
    monkeypatch.setattr(task_tool_module.time, "sleep", lambda _: None)
    monkeypatch.setattr("src.tools.get_available_tools", get_available_tools)
    monkeypatch.setattr(
        "src.config.agents_config.load_agent_config",
        lambda name: SimpleNamespace(name=name, tool_groups=["file:read"]),
    )

    output = task_tool_module.task_tool.func(
        runtime=runtime,
        description="restricted task",
        prompt="read only",
        subagent_type="general-purpose",
        tool_call_id="tc-restricted",
    )

    assert output == "Task Succeeded. Result: done"
    get_available_tools.assert_called_once_with(model_name="ark-model", groups=["file:read"], subagent_enabled=False)
    assert captured["executor_kwargs"]["thread_id"] == "thread-1"


def test_task_tool_returns_failed_message(monkeypatch):
    config = _make_subagent_config()
    events = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_skills_prompt_section", lambda: "")
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.FAILED, error="subagent crashed"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.time, "sleep", lambda _: None)
    monkeypatch.setattr("src.tools.get_available_tools", lambda **kwargs: [])

    output = task_tool_module.task_tool.func(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="do fail",
        subagent_type="general-purpose",
        tool_call_id="tc-fail",
    )

    assert output == "Task failed. Error: subagent crashed"
    non_trace_events = [e for e in events if e.get("type") != "trace_event.v1"]
    assert non_trace_events[-1]["type"] == "task_failed"
    assert non_trace_events[-1]["error"] == "subagent crashed"
    assert non_trace_events[-1]["description"] == "执行任务"
    assert non_trace_events[-1]["subagent_type"] == "general-purpose"
    assert non_trace_events[-1]["group_title"] == "general-purpose: 执行任务"


def test_task_tool_raises_timed_out_error(monkeypatch):
    config = _make_subagent_config()
    events = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_skills_prompt_section", lambda: "")
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.TIMED_OUT, error="timeout"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.time, "sleep", lambda _: None)
    monkeypatch.setattr("src.tools.get_available_tools", lambda **kwargs: [])

    with pytest.raises(TimeoutError, match="Task timed out. Error: timeout"):
        task_tool_module.task_tool.func(
            runtime=_make_runtime(),
            description="执行任务",
            prompt="do timeout",
            subagent_type="general-purpose",
            tool_call_id="tc-timeout",
        )

    non_trace_events = [e for e in events if e.get("type") != "trace_event.v1"]
    assert non_trace_events[-1]["type"] == "task_timed_out"
    assert non_trace_events[-1]["error"] == "timeout"
    assert non_trace_events[-1]["description"] == "执行任务"


def test_task_tool_polling_safety_timeout(monkeypatch):
    config = _make_subagent_config()
    # Keep max_poll_count small for test speed: (1 + 60) // 5 = 12
    config.timeout_seconds = 1
    events = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_skills_prompt_section", lambda: "")
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.RUNNING, ai_messages=[]),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.time, "sleep", lambda _: None)
    monkeypatch.setattr("src.tools.get_available_tools", lambda **kwargs: [])

    with pytest.raises(TimeoutError, match="Task polling timed out"):
        task_tool_module.task_tool.func(
            runtime=_make_runtime(),
            description="执行任务",
            prompt="never finish",
            subagent_type="general-purpose",
            tool_call_id="tc-safety-timeout",
        )

    non_trace_events = [e for e in events if e.get("type") != "trace_event.v1"]
    assert non_trace_events[0]["type"] == "task_started"
    assert non_trace_events[-1]["type"] == "task_timed_out"


def test_cleanup_called_on_completed(monkeypatch):
    """Verify cleanup_background_task is called when task completes."""
    config = _make_subagent_config()
    events = []
    cleanup_calls = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_skills_prompt_section", lambda: "")
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.COMPLETED, result="done"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.time, "sleep", lambda _: None)
    monkeypatch.setattr("src.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )

    output = task_tool_module.task_tool.func(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="complete task",
        subagent_type="general-purpose",
        tool_call_id="tc-cleanup-completed",
    )

    assert output == "Task Succeeded. Result: done"
    assert cleanup_calls == ["tc-cleanup-completed"]


def test_cleanup_called_on_failed(monkeypatch):
    """Verify cleanup_background_task is called when task fails."""
    config = _make_subagent_config()
    events = []
    cleanup_calls = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_skills_prompt_section", lambda: "")
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.FAILED, error="error"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.time, "sleep", lambda _: None)
    monkeypatch.setattr("src.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )

    output = task_tool_module.task_tool.func(
        runtime=_make_runtime(),
        description="执行任务",
        prompt="fail task",
        subagent_type="general-purpose",
        tool_call_id="tc-cleanup-failed",
    )

    assert output == "Task failed. Error: error"
    assert cleanup_calls == ["tc-cleanup-failed"]


def test_cleanup_called_on_timed_out(monkeypatch):
    """Verify cleanup_background_task is called when task times out."""
    config = _make_subagent_config()
    events = []
    cleanup_calls = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_skills_prompt_section", lambda: "")
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.TIMED_OUT, error="timeout"),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.time, "sleep", lambda _: None)
    monkeypatch.setattr("src.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )

    with pytest.raises(TimeoutError, match="Task timed out. Error: timeout"):
        task_tool_module.task_tool.func(
            runtime=_make_runtime(),
            description="执行任务",
            prompt="timeout task",
            subagent_type="general-purpose",
            tool_call_id="tc-cleanup-timedout",
        )

    assert cleanup_calls == ["tc-cleanup-timedout"]


def test_cleanup_not_called_on_polling_safety_timeout(monkeypatch):
    """Verify cleanup_background_task is NOT called on polling safety timeout.

    This prevents race conditions where the background task is still running
    but the polling loop gives up. The cleanup should happen later when the
    executor completes and sets a terminal status.
    """
    config = _make_subagent_config()
    # Keep max_poll_count small for test speed: (1 + 60) // 5 = 12
    config.timeout_seconds = 1
    events = []
    cleanup_calls = []

    monkeypatch.setattr(task_tool_module, "SubagentStatus", FakeSubagentStatus)
    monkeypatch.setattr(
        task_tool_module,
        "SubagentExecutor",
        type("DummyExecutor", (), {"__init__": lambda self, **kwargs: None, "execute_async": lambda self, prompt, task_id=None: task_id}),
    )
    monkeypatch.setattr(task_tool_module, "get_subagent_config", lambda _: config)
    monkeypatch.setattr(task_tool_module, "get_skills_prompt_section", lambda: "")
    monkeypatch.setattr(
        task_tool_module,
        "get_background_task_result",
        lambda _: _make_result(FakeSubagentStatus.RUNNING, ai_messages=[]),
    )
    monkeypatch.setattr(task_tool_module, "get_stream_writer", lambda: events.append)
    monkeypatch.setattr(task_tool_module.time, "sleep", lambda _: None)
    monkeypatch.setattr("src.tools.get_available_tools", lambda **kwargs: [])
    monkeypatch.setattr(
        task_tool_module,
        "cleanup_background_task",
        lambda task_id: cleanup_calls.append(task_id),
    )

    with pytest.raises(TimeoutError, match="Task polling timed out"):
        task_tool_module.task_tool.func(
            runtime=_make_runtime(),
            description="执行任务",
            prompt="never finish",
            subagent_type="general-purpose",
            tool_call_id="tc-no-cleanup-safety-timeout",
        )

    # cleanup should NOT be called because the task is still RUNNING
    assert cleanup_calls == []
