"""Global write_todos tool for DAG-aware todo updates."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.middlewares.handoff_sync import ensure_plan_state, sync_handoff_files_from_state
from src.agents.middlewares.runtime_events import append_runtime_event


class TodoNodeInput(TypedDict, total=False):
    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "blocked"]
    depends_on: list[str]
    owner: Literal["lead", "subagent"]
    subagent_type: str | None
    target_endpoint: Literal["primary", "helper"] | None
    tool_budget: int | None


class _TodoToolState(TypedDict, total=False):
    plan: NotRequired[dict | None]
    plan_history: NotRequired[list[dict[str, Any]] | None]
    todo_graph: NotRequired[dict | None]
    todos: NotRequired[list[dict[str, str]] | None]


_REJECTED_DRAFT_COMPLETION = "draft_completion_blocked"
_REJECTED_COMPLETED_PLAN_MUTATION = "completed_plan_frozen"
_VALIDATION_FAILED = "validation_failed"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _slugify(content: str, index: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", content.lower()).strip("-")
    if not base:
        base = f"todo-{index + 1}"
    return base[:48]


def _is_acyclic(nodes: list[dict[str, Any]]) -> bool:
    graph = {node["id"]: list(node.get("depends_on") or []) for node in nodes}
    visited: set[str] = set()
    stack: set[str] = set()

    def dfs(node_id: str) -> bool:
        if node_id in stack:
            return False
        if node_id in visited:
            return True
        visited.add(node_id)
        stack.add(node_id)
        for dep in graph.get(node_id, []):
            if dep not in graph:
                return False
            if not dfs(dep):
                return False
        stack.remove(node_id)
        return True

    return all(dfs(node_id) for node_id in graph)


def _materialize_ready_ids(nodes: list[dict[str, Any]]) -> list[str]:
    by_id = {node["id"]: node for node in nodes}
    ready: list[str] = []
    for node in nodes:
        if node["status"] in {"completed", "blocked"}:
            continue
        deps = list(node.get("depends_on") or [])
        if all(by_id.get(dep, {}).get("status") == "completed" for dep in deps):
            ready.append(node["id"])
    return ready


def merge_todo_nodes(existing_nodes: list[dict[str, Any]], raw_updates: list[TodoNodeInput]) -> list[dict[str, Any]]:
    """Patch todo graph by id and append unseen ids as new nodes."""
    merged: list[dict[str, Any]] = [dict(node) for node in existing_nodes if isinstance(node, dict) and str(node.get("id") or "").strip()]
    by_id = {str(node["id"]): idx for idx, node in enumerate(merged)}

    def _valid_status(value: Any) -> str | None:
        status = str(value or "").strip()
        if status in {"pending", "in_progress", "completed", "blocked"}:
            return status
        return None

    def _patch_existing(target: dict[str, Any], raw: TodoNodeInput) -> None:
        if "content" in raw:
            content = str(raw.get("content") or "").strip()
            if content:
                target["content"] = content
        if "status" in raw:
            status = _valid_status(raw.get("status"))
            if status:
                target["status"] = status
        if "depends_on" in raw:
            deps = [str(dep).strip() for dep in (raw.get("depends_on") or []) if str(dep).strip()]
            target["depends_on"] = deps
        for key in ("owner", "subagent_type", "target_endpoint", "tool_budget"):
            if key in raw:
                target[key] = raw.get(key)

    for idx, raw in enumerate(raw_updates):
        raw_id = str(raw.get("id") or "").strip()
        if raw_id and raw_id in by_id:
            _patch_existing(merged[by_id[raw_id]], raw)
            continue

        content = str(raw.get("content", "")).strip()
        if not content:
            content = raw_id or f"Todo {len(merged) + idx + 1}"
        status = _valid_status(raw.get("status")) or "pending"
        candidate = {
            "id": raw_id or _slugify(content, len(merged) + idx),
            "content": content,
            "status": status,
            "depends_on": [str(dep).strip() for dep in (raw.get("depends_on") or []) if str(dep).strip()],
            "owner": raw.get("owner") or "lead",
            "subagent_type": raw.get("subagent_type"),
            "target_endpoint": raw.get("target_endpoint"),
            "tool_budget": raw.get("tool_budget"),
        }
        base_id = str(raw_id or candidate["id"])
        next_id = base_id
        suffix = 2
        while next_id in by_id:
            next_id = f"{base_id}-{suffix}"
            suffix += 1
        candidate["id"] = next_id
        if not raw_id and next_id.startswith("todo-"):
            candidate["id"] = _slugify(content, len(merged) + idx)
            dedup_base = candidate["id"]
            dedup_suffix = 2
            while candidate["id"] in by_id:
                candidate["id"] = f"{dedup_base}-{dedup_suffix}"
                dedup_suffix += 1
        merged.append(candidate)
        by_id[str(candidate["id"])] = len(merged) - 1

    ids = {str(node["id"]) for node in merged}
    for node in merged:
        deps = [str(dep).strip() for dep in (node.get("depends_on") or []) if str(dep).strip()]
        node["depends_on"] = [dep for dep in deps if dep in ids and dep != node["id"]]
        if _valid_status(node.get("status")) is None:
            node["status"] = "pending"
        if not str(node.get("content") or "").strip():
            node["content"] = str(node["id"])
        node["owner"] = node.get("owner") or "lead"

    if not _is_acyclic(merged):
        raise ValueError("Todo dependency graph contains a cycle.")
    return merged


def _legacy_todos(nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"content": str(node["content"]), "status": str(node["status"])} for node in nodes]


def _build_reject_command(*, tool_call_id: str, reason_code: str, message: str) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=f"[todo_update_rejected:{reason_code}] {message}",
                    tool_call_id=tool_call_id,
                )
            ],
            "todo_last_error_code": reason_code,
            "todo_last_error_message": message,
        }
    )


@tool("write_todos")
def write_todos_tool(
    runtime: ToolRuntime[ContextT, _TodoToolState],
    todos: list[TodoNodeInput],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Create and update todo items, including dependency-aware DAG fields.

    Args:
        todos: List of todo updates. Existing items are patched by ``id``.
            New items are appended when ``id`` is new or omitted.
    """
    state = runtime.state or {} if runtime else {}
    plan = state.get("plan") if isinstance(state, dict) else None
    plan_status = str(plan.get("status") or "").strip().lower() if isinstance(plan, dict) else ""
    mode = str((getattr(runtime, "context", None) or {}).get("mode") or "").strip().lower() if runtime is not None else ""
    if plan_status == "completed":
        if runtime is not None:
            append_runtime_event(
                runtime,
                {"source": "write_todos_tool", "event": "todo_update_rejected", "reason_code": _REJECTED_COMPLETED_PLAN_MUTATION, "mode": mode, "plan_status": plan_status},
            )
        return _build_reject_command(
            tool_call_id=tool_call_id,
            reason_code=_REJECTED_COMPLETED_PLAN_MUTATION,
            message="Plan is completed and todo mutations are frozen. Start an explicit re-plan to modify todos.",
        )

    # Work Mode is allowed to progress a draft plan — including marking todos
    # completed — so the agent can iterate on plan.md without being blocked by
    # the Execute Plan UI gate. The block remains in Plan Mode, where the user
    # is reviewing a frozen proposal before approval.
    if plan_status == "draft" and mode == "plan":
        blocked_completed = [str(item.get("id") or "").strip() for item in todos if str(item.get("status") or "").strip().lower() == "completed"]
        blocked_completed = [todo_id for todo_id in blocked_completed if todo_id]
        if blocked_completed:
            if runtime is not None:
                append_runtime_event(
                    runtime,
                    {"source": "write_todos_tool", "event": "todo_update_rejected", "reason_code": _REJECTED_DRAFT_COMPLETION, "mode": mode, "plan_status": plan_status, "blocked_ids": blocked_completed},
                )
            return _build_reject_command(
                tool_call_id=tool_call_id,
                reason_code=_REJECTED_DRAFT_COMPLETION,
                message=(
                    "Draft plan cannot mark todos completed. "
                    f"Blocked ids: {', '.join(blocked_completed)}. "
                    "In plan mode, use pending/in_progress/blocked and update structure; complete todos after plan approval in work mode."
                ),
            )

    existing_nodes_raw = ((state.get("todo_graph") or {}).get("nodes") if isinstance(state, dict) else None)
    existing_nodes = existing_nodes_raw if isinstance(existing_nodes_raw, list) else []
    try:
        merged_nodes = merge_todo_nodes(existing_nodes, todos)
    except ValueError as exc:
        if runtime is not None:
            append_runtime_event(
                runtime,
                {
                    "source": "write_todos_tool",
                    "event": "todo_update_validation_failed",
                    "reason_code": _VALIDATION_FAILED,
                    "mode": mode,
                    "plan_status": plan_status,
                    "error": str(exc),
                },
            )
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            f"[todo_update_validation_failed:{_VALIDATION_FAILED}] {exc}\n"
                            "Double check write_todos schema. Example:\n"
                            "{\"todos\":[{\"id\":\"todo-1\",\"status\":\"in_progress\"}]}"
                        ),
                        tool_call_id=tool_call_id,
                    )
                ],
                "todo_last_error_code": _VALIDATION_FAILED,
                "todo_last_error_message": str(exc),
            }
        )
    ready_ids = _materialize_ready_ids(merged_nodes)
    update_payload = {
        "todo_graph": {
            "nodes": merged_nodes,
            "ready_ids": ready_ids,
            "updated_at": _utc_now_iso(),
        },
        "todos": _legacy_todos(merged_nodes),
        "messages": [
            ToolMessage(
                content=f"Updated todo graph with {len(merged_nodes)} item(s); ready={ready_ids}",
                tool_call_id=tool_call_id,
            )
        ],
        "todo_last_error_code": None,
        "todo_last_error_message": None,
    }
    if runtime is not None:
        merged_state = dict(runtime.state or {})
        merged_state.update(
            {
                "todo_graph": update_payload["todo_graph"],
                "todos": update_payload["todos"],
            }
        )
        ensured_plan = ensure_plan_state(merged_state)
        if ensured_plan is not None:
            update_payload["plan"] = ensured_plan
            existing_history = [item for item in (merged_state.get("plan_history") or []) if isinstance(item, dict)]
            plan_id = str(ensured_plan.get("plan_id") or "").strip()
            if plan_id and not any(str(item.get("plan_id") or "").strip() == plan_id for item in existing_history):
                update_payload["plan_history"] = [
                    *existing_history,
                    {
                        "plan_id": plan_id,
                        "title": ensured_plan.get("title"),
                        "path": ensured_plan.get("plan_path"),
                        "created_at": ensured_plan.get("created_at"),
                        "status": ensured_plan.get("status"),
                    },
                ][-40:]
        sync_handoff_files_from_state(merged_state)
    return Command(update=update_payload)
