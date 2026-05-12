"""Shared handoff rendering and syncing helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.sandbox.path_mapping import replace_virtual_path


def render_plan_md(
    title: str,
    summary: str,
    nodes: list[dict[str, Any]],
    *,
    domain: str = "generic",
    plan_id: str | None = None,
    status: str | None = None,
    created_at: str | None = None,
    objective: str | None = None,
    assumptions: list[str] | None = None,
    constraints: list[str] | None = None,
    risks: list[dict[str, str]] | None = None,
    acceptance_criteria: list[str] | None = None,
) -> str:
    completed = sum(1 for n in nodes if str(n.get("status") or "") == "completed")
    total = len(nodes)
    frontmatter_title = title.replace('"', '\\"')

    assumption_lines = [f"- {item}" for item in (assumptions or []) if str(item).strip()]
    constraint_lines = [f"- {item}" for item in (constraints or []) if str(item).strip()]
    risk_lines = []
    for risk in risks or []:
        if not isinstance(risk, dict):
            continue
        risk_text = str(risk.get("risk") or "").strip()
        mitigation_text = str(risk.get("mitigation") or "").strip()
        if not risk_text and not mitigation_text:
            continue
        if risk_text and mitigation_text:
            risk_lines.append(f"- Risk: {risk_text}\n  Mitigation: {mitigation_text}")
        elif risk_text:
            risk_lines.append(f"- Risk: {risk_text}")
        else:
            risk_lines.append(f"- Mitigation: {mitigation_text}")
    acceptance_lines = [f"- {item}" for item in (acceptance_criteria or []) if str(item).strip()]

    todo_lines = []
    for node in nodes:
        status = str(node.get("status") or "pending")
        content = str(node.get("content") or "").strip()
        if not content:
            continue
        check = "x" if status == "completed" else " "
        deps = [str(dep).strip() for dep in (node.get("depends_on") or []) if str(dep).strip()]
        rationale = str(node.get("rationale") or "").strip() or "Required to progress the implementation safely."
        todo_id = str(node.get("id") or "").strip() or "todo"
        todo_lines.append(f"- [{check}] **{todo_id}**: {content}")
        todo_lines.append(f"  - Rationale: {rationale}")
        if deps:
            todo_lines.append(f"  - Depends on: {', '.join(deps)}")
    todos_block = "\n".join(todo_lines) if todo_lines else "- [ ] **todo-1**: Complete the user request end-to-end.\n  - Rationale: Required baseline delivery step."

    dag_lines = []
    for node in nodes:
        todo_id = str(node.get("id") or "").strip()
        if not todo_id:
            continue
        deps = [str(dep).strip() for dep in (node.get("depends_on") or []) if str(dep).strip()]
        if deps:
            dag_lines.append(f"- {todo_id} <- {', '.join(deps)}")
        else:
            dag_lines.append(f"- {todo_id} <- ROOT")
    dag_block = "\n".join(dag_lines) if dag_lines else "- todo-1 <- ROOT"

    objective_text = (objective or summary or "Deliver the requested outcome end-to-end.").strip()
    assumptions_block = "\n".join(assumption_lines) if assumption_lines else "- No additional assumptions were provided."
    constraints_block = "\n".join(constraint_lines) if constraint_lines else "- Work within the current thread context and available tools."
    risks_block = "\n".join(risk_lines) if risk_lines else "- Risk: Scope ambiguity\n  Mitigation: Validate assumptions before execution."
    acceptance_block = "\n".join(acceptance_lines) if acceptance_lines else "- All planned steps are completed and verified."

    return (
        "---\n"
        "plan_version: 3\n"
        f'plan_id: "{(plan_id or "").strip()}"\n'
        f'domain: "{domain}"\n'
        f'title: "{frontmatter_title}"\n'
        f'status: "{(status or "draft").strip()}"\n'
        f'created_at: "{(created_at or "unknown").strip()}"\n'
        f"total_todos: {total}\n"
        f"completed_todos: {completed}\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Objective\n"
        f"{objective_text}\n\n"
        "## Summary\n"
        f"{(summary or objective_text).strip()}\n\n"
        "## Assumptions\n"
        f"{assumptions_block}\n\n"
        "## Constraints\n"
        f"{constraints_block}\n\n"
        "## Phased Implementation Steps\n"
        f"{todos_block}\n\n"
        "## Risks & Mitigations\n"
        f"{risks_block}\n\n"
        "## Acceptance Criteria\n"
        f"{acceptance_block}\n\n"
        "## Execution DAG\n"
        f"{dag_block}\n"
    )


def render_sprint_contract_md(nodes: list[dict[str, Any]]) -> str:
    scope_lines = []
    status_lines = []
    for node in nodes:
        content = str(node.get("content") or "").strip()
        if not content:
            continue
        status = str(node.get("status") or "pending")
        scope_lines.append(f"- {content}")
        status_lines.append(f"- [{status}] {content}")
    scope_block = "\n".join(scope_lines) if scope_lines else "- Complete the user request end-to-end."
    status_block = "\n".join(status_lines) if status_lines else "- [pending] Complete the user request end-to-end."
    return (
        "# Sprint Contract\n\n"
        "## Scope\n"
        f"{scope_block}\n\n"
        "## Done Criteria\n"
        "- All todos marked completed\n"
        "- Final answer includes outcomes and artifacts\n\n"
        "## Todo Status\n"
        f"{status_block}\n"
    )


def _extract_nodes_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    graph = state.get("todo_graph") or {}
    graph_nodes = graph.get("nodes") if isinstance(graph, dict) else None
    if isinstance(graph_nodes, list) and graph_nodes:
        return [node for node in graph_nodes if isinstance(node, dict)]

    raw_todos = state.get("todos") or []
    nodes: list[dict[str, Any]] = []
    if isinstance(raw_todos, list):
        for index, todo in enumerate(raw_todos):
            if not isinstance(todo, dict):
                continue
            content = str(todo.get("content") or "").strip()
            if not content:
                continue
            nodes.append(
                {
                    "id": f"todo-{index + 1}",
                    "content": content,
                    "status": str(todo.get("status") or "pending"),
                    "depends_on": [],
                }
            )
    return nodes


def _write_if_changed(path: str, content: str) -> bool:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else None
    if existing == content:
        return False
    target.write_text(content, encoding="utf-8")
    return True


def _can_resolve_write_path(path: str, thread_data: dict[str, Any] | None) -> bool:
    # Virtual sandbox paths require thread_data to resolve to a physical location.
    if path.startswith("/mnt/") and not thread_data:
        return False
    return True


def sync_handoff_files_from_state(state: dict[str, Any]) -> list[str]:
    """Sync plan/sprint handoff files from in-memory todo state.

    Returns list of file paths that changed.
    """
    plan = state.get("plan") or {}
    if not isinstance(plan, dict):
        return []

    # thread_data is required to translate virtual /mnt/... paths to physical
    # thread-scoped directories. Without it, writes would target the literal /mnt
    # mountpoint which is read-only in most runtime environments.
    thread_data = state.get("thread_data")

    title = str(plan.get("title") or "Execution Plan")
    summary = str(plan.get("summary") or "")
    domain = str(plan.get("domain") or "generic")
    nodes = _extract_nodes_from_state(state)
    if not nodes:
        return []

    changed: list[str] = []
    plan_path = plan.get("plan_path")
    if isinstance(plan_path, str) and plan_path.strip():
        if not _can_resolve_write_path(plan_path, thread_data):
            return []
        physical = replace_virtual_path(plan_path, thread_data)
        if _write_if_changed(
            physical,
            render_plan_md(
                title,
                summary,
                nodes,
                domain=domain,
                plan_id=str(plan.get("plan_id") or "").strip() or None,
                status=str(plan.get("status") or "").strip() or None,
                created_at=str(plan.get("created_at") or "").strip() or None,
                objective=str(plan.get("objective") or "").strip() or None,
                assumptions=plan.get("assumptions") if isinstance(plan.get("assumptions"), list) else None,
                constraints=plan.get("constraints") if isinstance(plan.get("constraints"), list) else None,
                risks=plan.get("risks") if isinstance(plan.get("risks"), list) else None,
                acceptance_criteria=plan.get("acceptance_criteria") if isinstance(plan.get("acceptance_criteria"), list) else None,
            ),
        ):
            changed.append(plan_path)

    latest_alias_path = plan.get("latest_alias_path")
    if isinstance(latest_alias_path, str) and latest_alias_path.strip():
        if not _can_resolve_write_path(latest_alias_path, thread_data):
            return changed
        physical_alias = replace_virtual_path(latest_alias_path, thread_data)
        if _write_if_changed(
            physical_alias,
            render_plan_md(
                title,
                summary,
                nodes,
                domain=domain,
                plan_id=str(plan.get("plan_id") or "").strip() or None,
                status=str(plan.get("status") or "").strip() or None,
                created_at=str(plan.get("created_at") or "").strip() or None,
                objective=str(plan.get("objective") or "").strip() or None,
                assumptions=plan.get("assumptions") if isinstance(plan.get("assumptions"), list) else None,
                constraints=plan.get("constraints") if isinstance(plan.get("constraints"), list) else None,
                risks=plan.get("risks") if isinstance(plan.get("risks"), list) else None,
                acceptance_criteria=plan.get("acceptance_criteria") if isinstance(plan.get("acceptance_criteria"), list) else None,
            ),
        ):
            changed.append(latest_alias_path)

    sprint_contract_path = plan.get("sprint_contract_path")
    if isinstance(sprint_contract_path, str) and sprint_contract_path.strip():
        if not _can_resolve_write_path(sprint_contract_path, thread_data):
            return changed
        physical = replace_virtual_path(sprint_contract_path, thread_data)
        if _write_if_changed(physical, render_sprint_contract_md(nodes)):
            changed.append(sprint_contract_path)

    return changed
