"""Resume metadata middleware."""

from __future__ import annotations

from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.config.resume_config import ResumeConfig, get_resume_config


class ResumeState(AgentState):
    """State subset for resume metadata updates."""

    todo_graph: NotRequired[dict | None]
    deferred_task_calls: NotRequired[list[dict] | None]
    handoff_artifacts: NotRequired[list[str] | None]
    resume_meta: NotRequired[dict | None]
    retry_meta: NotRequired[dict | None]


class ResumeStateMiddleware(AgentMiddleware[ResumeState]):
    """Maintains resume continuity markers in thread state."""

    state_schema = ResumeState

    def __init__(self, config: ResumeConfig | None = None):
        super().__init__()
        self._config = config or get_resume_config()

    def _extract_last_completed_todo(self, state: ResumeState) -> str | None:
        graph = state.get("todo_graph") or {}
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        if not isinstance(nodes, list):
            return None
        completed_ids = [str(node.get("id")) for node in nodes if isinstance(node, dict) and node.get("status") == "completed" and node.get("id")]
        return completed_ids[-1] if completed_ids else None

    def _extract_in_progress_todo_ids(self, state: ResumeState) -> list[str]:
        graph = state.get("todo_graph") or {}
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        if not isinstance(nodes, list):
            return []
        return [str(n["id"]) for n in nodes if isinstance(n, dict) and n.get("status") == "in_progress" and n.get("id")]

    def _extract_retry_counts(self, state: ResumeState) -> dict[str, int]:
        retry_meta = state.get("retry_meta") or {}
        attempts = retry_meta.get("attempts_by_tool_call") if isinstance(retry_meta, dict) else None
        if not isinstance(attempts, dict):
            return {}
        return {str(k): int(v) for k, v in attempts.items() if isinstance(v, int)}

    def _extract_running_subagent_ids(self, state: ResumeState) -> list[str]:
        deferred = state.get("deferred_task_calls") or []
        return [str(item["id"]) for item in deferred if isinstance(item, dict) and item.get("id") and item.get("status") not in {"completed", "failed", "timed_out"}]

    @override
    def after_model(self, state: ResumeState, runtime: Runtime) -> dict | None:
        if not self._config.enabled:
            return None

        current = dict(state.get("resume_meta") or {})
        graph = state.get("todo_graph") or {}
        ready_ids = graph.get("ready_ids") if isinstance(graph, dict) else []
        checkpoint_id = None
        runtime_context = getattr(runtime, "context", None) or {}
        if isinstance(runtime_context.get("checkpoint_id"), str):
            checkpoint_id = runtime_context.get("checkpoint_id")
        elif isinstance(current.get("last_checkpoint_id"), str):
            checkpoint_id = current.get("last_checkpoint_id")

        updated = {
            "last_checkpoint_id": checkpoint_id,
            "last_completed_todo_id": self._extract_last_completed_todo(state),
            "pending_ready_ids": [str(item) for item in ready_ids] if isinstance(ready_ids, list) else [],
            "deferred_task_calls_count": len(state.get("deferred_task_calls") or []),
            "handoff_refs": list(dict.fromkeys([str(path) for path in (state.get("handoff_artifacts") or []) if str(path)])),
            "in_progress_todo_ids": self._extract_in_progress_todo_ids(state),
            "retry_counts": self._extract_retry_counts(state),
            "running_subagent_ids": self._extract_running_subagent_ids(state),
        }
        if updated == current:
            return None
        return {"resume_meta": updated}

    @override
    async def aafter_model(self, state: ResumeState, runtime: Runtime) -> dict | None:
        return self.after_model(state, runtime)
