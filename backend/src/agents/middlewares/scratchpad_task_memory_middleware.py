"""Scratchpad and task-scoped episodic memory middleware."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.config.handoffs_config import get_handoffs_config
from src.config.scratchpad_config import ScratchpadConfig, get_scratchpad_config
from src.config.task_memory_config import TaskMemoryConfig, get_task_memory_config


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content)


class ScratchpadTaskMemoryState(AgentState):
    """State subset for scratchpad/task memory updates."""

    scratchpad: NotRequired[list[dict] | None]
    task_memory: NotRequired[dict[str, list[dict]] | None]
    todo_graph: NotRequired[dict | None]
    messages: NotRequired[list[Any] | None]
    thread_data: NotRequired[dict | None]
    handoff_artifacts: NotRequired[list[str] | None]


class ScratchpadTaskMemoryMiddleware(AgentMiddleware[ScratchpadTaskMemoryState]):
    """Maintains compact run scratchpad and task-scoped episodic facts."""

    state_schema = ScratchpadTaskMemoryState

    def __init__(
        self,
        scratchpad_config: ScratchpadConfig | None = None,
        task_memory_config: TaskMemoryConfig | None = None,
    ):
        super().__init__()
        self._scratchpad_config = scratchpad_config or get_scratchpad_config()
        self._task_memory_config = task_memory_config or get_task_memory_config()

    def _collect_new_completed_todos(self, state: ScratchpadTaskMemoryState, task_memory: dict[str, list[dict]]) -> list[tuple[str, str]]:
        graph = state.get("todo_graph") or {}
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        if not isinstance(nodes, list):
            return []

        completed: list[tuple[str, str]] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("status") != "completed":
                continue
            todo_id = str(node.get("id") or "").strip()
            if not todo_id:
                continue
            if todo_id in task_memory and task_memory[todo_id]:
                continue
            content = str(node.get("content") or todo_id).strip()
            completed.append((todo_id, content))
        return completed

    def _write_scratchpad_artifact(self, state: ScratchpadTaskMemoryState, entries: list[dict]) -> str | None:
        handoffs_cfg = get_handoffs_config()
        if not handoffs_cfg.enabled:
            return None
        thread_data = state.get("thread_data") or {}
        workspace_path = thread_data.get("workspace_path")
        if not isinstance(workspace_path, str) or not workspace_path:
            return None
        root = Path(workspace_path) / handoffs_cfg.dir
        root.mkdir(parents=True, exist_ok=True)
        path = root / self._scratchpad_config.artifact_file
        lines = ["# Scratchpad", ""]
        for entry in entries:
            ts = str(entry.get("ts") or "")
            source = str(entry.get("source") or "note")
            text = str(entry.get("text") or "")
            lines.append(f"- [{ts}] ({source}) {text}")
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)

    @override
    def after_model(self, state: ScratchpadTaskMemoryState, runtime: Runtime) -> dict | None:  # noqa: ARG002
        if not self._scratchpad_config.enabled and not self._task_memory_config.enabled:
            return None

        updates: dict[str, Any] = {}
        scratchpad = list(state.get("scratchpad") or [])
        task_memory = dict(state.get("task_memory") or {})

        completed = self._collect_new_completed_todos(state, task_memory)
        if self._task_memory_config.enabled:
            for todo_id, content in completed:
                facts = list(task_memory.get(todo_id) or [])
                facts.append(
                    {
                        "ts": _utc_now_iso(),
                        "fact": f"Completed todo `{todo_id}`: {content}",
                    }
                )
                task_memory[todo_id] = facts[-self._task_memory_config.max_facts_per_task :]

            # `retention_turns` is repurposed here as "max number of todo buckets
            # retained at once"; earliest-inserted keys are dropped when the cap is
            # exceeded. Keep name in sync with config semantics if you rename the field.
            if len(task_memory) > self._task_memory_config.retention_turns:
                keys = list(task_memory.keys())
                drop_count = len(task_memory) - self._task_memory_config.retention_turns
                for key in keys[:drop_count]:
                    task_memory.pop(key, None)

            updates["task_memory"] = task_memory

        if self._scratchpad_config.enabled:
            now = _utc_now_iso()
            for todo_id, content in completed:
                scratchpad.append(
                    {
                        "ts": now,
                        "source": "todo",
                        "text": f"Completed `{todo_id}` — {content}",
                    }
                )

            messages = state.get("messages", []) or []
            if messages:
                last = messages[-1]
                if getattr(last, "type", None) == "ai" and not getattr(last, "tool_calls", None):
                    text = _extract_text(getattr(last, "content", "")).strip()
                    if text:
                        clipped = text[: self._scratchpad_config.max_chars_per_entry]
                        if not scratchpad or scratchpad[-1].get("text") != clipped:
                            scratchpad.append(
                                {
                                    "ts": now,
                                    "source": "assistant",
                                    "text": clipped,
                                }
                            )

            scratchpad = scratchpad[-self._scratchpad_config.max_entries :]
            updates["scratchpad"] = scratchpad

            artifact_path = self._write_scratchpad_artifact(state, scratchpad)
            if artifact_path:
                updates["handoff_artifacts"] = [artifact_path]

        return updates or None

    @override
    async def aafter_model(self, state: ScratchpadTaskMemoryState, runtime: Runtime) -> dict | None:
        return self.after_model(state, runtime)
