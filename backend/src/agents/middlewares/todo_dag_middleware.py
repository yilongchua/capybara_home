"""DAG-capable todo middleware for plan mode."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal, NotRequired, TypedDict, cast, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class TodoDagState(AgentState):
    todo_graph: NotRequired[dict | None]
    todos: NotRequired[list[dict[str, str]] | None]
    clarifications: NotRequired[list[dict[str, Any]] | None]


class TodoNodeInput(TypedDict, total=False):
    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "blocked"]
    depends_on: list[str]
    owner: Literal["lead", "subagent"]
    subagent_type: str | None
    target_endpoint: Literal["primary", "helper"] | None
    tool_budget: int | None
    kind: str | None
    artifact_type: str | None


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
            if dep in graph and not dfs(dep):
                return False
        stack.remove(node_id)
        return True

    return all(dfs(node_id) for node_id in graph)


def find_dangling_deps(nodes: list[dict[str, Any]]) -> dict[str, list[str]]:
    ids = {str(node.get("id")) for node in nodes if isinstance(node, dict) and str(node.get("id") or "").strip()}
    dangling: dict[str, list[str]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        missing = [
            str(dep).strip()
            for dep in (node.get("depends_on") or [])
            if str(dep).strip() and str(dep).strip() not in ids
        ]
        if missing:
            dangling[node_id] = missing
    return dangling


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


def collect_clarification_blocked_todo_ids(clarifications: list[dict[str, Any]] | None) -> set[str]:
    """Todo ids gated by at least one pending clarification.

    A clarification's ``blocks`` list names todo ids whose readiness depends
    on the answer. While the clarification is in ``pending`` status, those
    todos must NOT appear in ``ready_ids`` even if their dependency chain
    is otherwise satisfied. Once the clarification flips to ``answered``,
    the gate releases automatically on the next recompute.
    """
    blocked: set[str] = set()
    if not clarifications:
        return blocked
    for entry in clarifications:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("status") or "pending") != "pending":
            continue
        for tid in entry.get("blocks") or []:
            tid_s = str(tid).strip()
            if tid_s:
                blocked.add(tid_s)
    return blocked


def compute_effective_ready_ids(
    nodes: list[dict[str, Any]] | None,
    clarifications: list[dict[str, Any]] | None,
) -> list[str]:
    """Ready ids minus those gated by pending clarifications."""
    if not nodes:
        return []
    base = _materialize_ready_ids(nodes)
    blocked = collect_clarification_blocked_todo_ids(clarifications)
    if not blocked:
        return base
    return [tid for tid in base if tid not in blocked]


def normalize_todo_nodes(raw_todos: list[TodoNodeInput]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_todos):
        content = str(raw.get("content", "")).strip()
        if not content:
            # Be permissive with malformed tool payloads so the run can continue.
            fallback = str(raw.get("id") or "").strip()
            content = fallback or f"Todo {index + 1}"
        if not content:
            content = f"Todo {index + 1}"
        node_id = str(raw.get("id") or _slugify(content, index))
        base_id = node_id
        suffix = 2
        while node_id in seen:
            node_id = f"{base_id}-{suffix}"
            suffix += 1
        seen.add(node_id)
        status = raw.get("status") or "pending"
        if status not in {"pending", "in_progress", "completed", "blocked"}:
            status = "pending"
        depends_on = [str(dep) for dep in (raw.get("depends_on") or []) if str(dep).strip()]
        rationale = str(raw.get("rationale") or "").strip()
        node: dict[str, Any] = {
            "id": node_id,
            "content": content,
            "status": status,
            "depends_on": depends_on,
            "owner": raw.get("owner") or "lead",
            "subagent_type": raw.get("subagent_type"),
            "target_endpoint": raw.get("target_endpoint"),
            "tool_budget": raw.get("tool_budget"),
        }
        for key in ("kind", "artifact_type"):
            value = str(raw.get(key) or "").strip()
            if value:
                node[key] = value
        if rationale:
            node["rationale"] = rationale
        # Preserve planner-side rich fields so downstream consumers (plan
        # evaluator, plan.md handoff, work-mode prompt) can read them without
        # having to plumb a parallel store.
        objective = str(raw.get("objective") or "").strip()
        if objective:
            node["objective"] = objective
        failure_fallback = str(raw.get("failure_fallback") or "").strip()
        if failure_fallback:
            node["failure_fallback"] = failure_fallback
        completion_requirement = str(raw.get("completion_requirement") or "").strip()
        if completion_requirement:
            node["completion_requirement"] = completion_requirement
        steps = raw.get("steps")
        if isinstance(steps, list) and steps:
            node["steps"] = [dict(step) if isinstance(step, dict) else step for step in steps]
        nodes.append(node)

    ids = {node["id"] for node in nodes}
    for node in nodes:
        node["depends_on"] = [dep for dep in node["depends_on"] if dep in ids and dep != node["id"]]
    if not _is_acyclic(nodes):
        raise ValueError("Todo dependency graph contains a cycle.")
    return nodes


def _clone_todo_node(node: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(node)
    steps = node.get("steps")
    if isinstance(steps, list):
        cloned["steps"] = [dict(step) if isinstance(step, dict) else step for step in steps]
    return cloned


def merge_todo_nodes(existing_nodes: list[dict[str, Any]], raw_updates: list[TodoNodeInput]) -> list[dict[str, Any]]:
    """Patch todo graph by id and append unseen ids as new nodes."""
    merged: list[dict[str, Any]] = [_clone_todo_node(node) for node in existing_nodes if isinstance(node, dict) and str(node.get("id") or "").strip()]
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
        for key in ("owner", "subagent_type", "target_endpoint", "tool_budget", "rationale", "kind", "artifact_type"):
            if key in raw:
                target[key] = raw.get(key)
        # Rich fields: preserve unless the patch explicitly sets a new value.
        # An explicit empty string clears the field; an explicit non-empty
        # value overwrites; a missing key leaves the existing value alone.
        for key in ("objective", "failure_fallback", "completion_requirement"):
            if key in raw:
                value = str(raw.get(key) or "").strip()
                if value:
                    target[key] = value
                else:
                    target.pop(key, None)
        if "steps" in raw:
            steps = raw.get("steps")
            if isinstance(steps, list) and steps:
                target["steps"] = [dict(step) if isinstance(step, dict) else step for step in steps]
            else:
                target.pop("steps", None)

    for idx, raw in enumerate(raw_updates):
        raw_id = str(raw.get("id") or "").strip()
        if raw_id and raw_id in by_id:
            _patch_existing(merged[by_id[raw_id]], raw)
            continue

        content = str(raw.get("content", "")).strip()
        if not content:
            content = raw_id or f"Todo {len(merged) + idx + 1}"
        status = _valid_status(raw.get("status")) or "pending"
        candidate: dict[str, Any] = {
            "id": raw_id or _slugify(content, len(merged) + idx),
            "content": content,
            "status": status,
            "depends_on": [str(dep).strip() for dep in (raw.get("depends_on") or []) if str(dep).strip()],
            "owner": raw.get("owner") or "lead",
            "subagent_type": raw.get("subagent_type"),
            "target_endpoint": raw.get("target_endpoint"),
            "tool_budget": raw.get("tool_budget"),
        }
        for key in ("kind", "artifact_type"):
            value = str(raw.get(key) or "").strip()
            if value:
                candidate[key] = value
        rationale = str(raw.get("rationale") or "").strip()
        if rationale:
            candidate["rationale"] = rationale
        objective = str(raw.get("objective") or "").strip()
        if objective:
            candidate["objective"] = objective
        failure_fallback = str(raw.get("failure_fallback") or "").strip()
        if failure_fallback:
            candidate["failure_fallback"] = failure_fallback
        completion_requirement = str(raw.get("completion_requirement") or "").strip()
        if completion_requirement:
            candidate["completion_requirement"] = completion_requirement
        steps = raw.get("steps")
        if isinstance(steps, list) and steps:
            candidate["steps"] = [dict(step) if isinstance(step, dict) else step for step in steps]
        base_id = str(raw_id or candidate["id"])
        next_id = base_id
        suffix = 2
        while next_id in by_id:
            next_id = f"{base_id}-{suffix}"
            suffix += 1
        candidate["id"] = next_id
        if next_id != base_id:
            logger.debug(
                "merge_todo_nodes: id collision on %r → %r (content=%r). Two distinct todos share a slug — consider re-titling one.",
                base_id,
                next_id,
                content[:80],
            )
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


def _todos_in_messages(messages: list[Any]) -> bool:
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                if tool_call.get("name") == "write_todos":
                    return True
    return False


class TodoDagMiddleware(AgentMiddleware[TodoDagState]):
    """Adds DAG-aware `write_todos` and a plan-mode todo prompt."""

    state_schema = TodoDagState

    def __init__(self, system_prompt: str | None = None):
        super().__init__()
        self._system_prompt = system_prompt or (
            "Use `write_todos` for complex work. Prefer dependency-aware todos via "
            "`depends_on` so ready tasks can be identified deterministically."
        )

    @override
    def wrap_model_call(self, request: ModelRequest, handler) -> ModelCallResult:
        if request.system_message is not None:
            new_system_content = [*request.system_message.content_blocks, {"type": "text", "text": f"\n\n{self._system_prompt}"}]
        else:
            new_system_content = [{"type": "text", "text": self._system_prompt}]
        new_system_message = SystemMessage(content=cast("list[str | dict[str, str]]", new_system_content))
        return handler(request.override(system_message=new_system_message))

    @override
    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelCallResult:
        if request.system_message is not None:
            new_system_content = [*request.system_message.content_blocks, {"type": "text", "text": f"\n\n{self._system_prompt}"}]
        else:
            new_system_content = [{"type": "text", "text": self._system_prompt}]
        new_system_message = SystemMessage(content=cast("list[str | dict[str, str]]", new_system_content))
        return await handler(request.override(system_message=new_system_message))

    def _build_reminder(self, state: TodoDagState, effective_ready_ids: list[str]) -> HumanMessage | None:
        graph = state.get("todo_graph") or {}
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        if not isinstance(nodes, list) or not nodes:
            return None
        messages = state.get("messages") or []
        if _todos_in_messages(messages):
            return None
        # Don't stack reminders: skip if one was already injected in the last ~3 turns.
        # Check both names so that a config-flip from DAG to list mode (or back)
        # mid-thread doesn't cause both middlewares to inject simultaneously.
        recent = messages[-6:] if len(messages) >= 6 else messages
        if any(isinstance(m, HumanMessage) and getattr(m, "name", None) in {"todo_reminder", "todo_dag_reminder"} for m in recent):
            return None
        # Surface clarification-gated todos so the agent sees why some todos
        # are not ready even though their deps are satisfied.
        blocked_by_clarif = collect_clarification_blocked_todo_ids(state.get("clarifications"))
        clarif_note = ""
        if blocked_by_clarif:
            clarif_note = f"\nBlocked by pending clarifications: {sorted(blocked_by_clarif)}"
        return HumanMessage(
            name="todo_dag_reminder",
            content=(
                "<system_reminder>\n"
                "Todo DAG remains active. Keep statuses current using `write_todos`.\n"
                f"Ready todos: {effective_ready_ids}{clarif_note}\n"
                "</system_reminder>"
            ),
        )

    def _recompute_state(self, state: TodoDagState) -> dict[str, Any] | None:
        """Recompute effective ready_ids on every before_model.

        Clarification answers and todo-status changes both invalidate the
        previously-stored ``ready_ids``; recomputing here keeps state in
        sync without requiring every mutating site to remember to do so.
        """
        graph = state.get("todo_graph") or {}
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        if not isinstance(nodes, list) or not nodes:
            return None
        effective = compute_effective_ready_ids(nodes, state.get("clarifications"))
        update: dict[str, Any] = {}
        existing_ready = list(graph.get("ready_ids") or []) if isinstance(graph, dict) else []
        if effective != existing_ready:
            new_graph = dict(graph) if isinstance(graph, dict) else {}
            new_graph["nodes"] = nodes
            new_graph["ready_ids"] = effective
            new_graph["updated_at"] = _utc_now_iso()
            update["todo_graph"] = new_graph
        reminder = self._build_reminder(state, effective)
        if reminder is not None:
            update["messages"] = [reminder]
        return update or None

    @override
    def before_model(self, state: TodoDagState, runtime: Runtime) -> dict[str, Any] | None:  # noqa: ARG002
        return self._recompute_state(state)

    @override
    async def abefore_model(self, state: TodoDagState, runtime: Runtime) -> dict[str, Any] | None:
        return self._recompute_state(state)
