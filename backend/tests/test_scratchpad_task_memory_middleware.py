"""Tests for scratchpad + task-memory middleware."""

from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from src.agents.middlewares.scratchpad_task_memory_middleware import ScratchpadTaskMemoryMiddleware
from src.config.handoffs_config import HandoffsConfig
from src.config.scratchpad_config import ScratchpadConfig
from src.config.task_memory_config import TaskMemoryConfig


def _runtime():
    return SimpleNamespace(context={"thread_id": "thread-1"})


def test_scratchpad_and_task_memory_updates_and_writes_artifact(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "src.agents.middlewares.scratchpad_task_memory_middleware.get_handoffs_config",
        lambda: HandoffsConfig(enabled=True, dir=".handoffs"),
    )
    middleware = ScratchpadTaskMemoryMiddleware(
        scratchpad_config=ScratchpadConfig(enabled=True, max_entries=10, max_chars_per_entry=120, artifact_file="scratchpad.md"),
        task_memory_config=TaskMemoryConfig(enabled=True, max_facts_per_task=2, retention_turns=10),
    )
    state = {
        "messages": [AIMessage(content="Final answer delivered.")],
        "todo_graph": {"nodes": [{"id": "todo-1", "content": "Implement feature", "status": "completed"}], "ready_ids": []},
        "thread_data": {"workspace_path": str(tmp_path)},
    }
    update = middleware.after_model(state, _runtime())
    assert update is not None
    assert update["scratchpad"]
    assert "todo-1" in update["task_memory"]
    artifact = tmp_path / ".handoffs" / "scratchpad.md"
    assert artifact.exists()
    assert "todo-1" in artifact.read_text(encoding="utf-8")


def test_scratchpad_compacts_entries(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "src.agents.middlewares.scratchpad_task_memory_middleware.get_handoffs_config",
        lambda: HandoffsConfig(enabled=False, dir=".handoffs"),
    )
    middleware = ScratchpadTaskMemoryMiddleware(
        scratchpad_config=ScratchpadConfig(enabled=True, max_entries=1, max_chars_per_entry=64, artifact_file="scratchpad.md"),
        task_memory_config=TaskMemoryConfig(enabled=False),
    )
    state = {
        "messages": [AIMessage(content="second message")],
        "scratchpad": [{"ts": "2026-01-01T00:00:00Z", "source": "assistant", "text": "first message"}],
        "thread_data": {"workspace_path": str(tmp_path)},
    }
    update = middleware.after_model(state, _runtime())
    assert update is not None
    assert len(update["scratchpad"]) == 1
    assert update["scratchpad"][0]["text"] == "second message"
