"""Shared plan rendering and runtime artifact syncing helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.agents.middlewares._fs_utils import write_if_changed
from src.sandbox.path_mapping import replace_virtual_path, to_virtual_path

_DEFAULT_PLAN_SUMMARY = "Living execution record for the current thread."
_RUNTIME_DIR = ".runtime"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def slugify_plan_title(title: str) -> str:
    """Single source of truth for plan-title slugification.

    Used by both `handoff_sync` (canonical plan.md path) and `planner_middleware`
    (versioned plan-N.md path). The planner site previously had a regex-based
    duplicate; collapsed here.
    """
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in title)
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed[:48] or "execution-plan"


def versioned_plan_filename(title: str, created_at: datetime) -> str:
    stamp = created_at.strftime("%Y%m%d-%H%M%S")
    return f"plan-{stamp}-{slugify_plan_title(title)}.md"


# Backwards-compatible private aliases for in-module callers.
_slugify_title = slugify_plan_title
_versioned_plan_filename = versioned_plan_filename


def _message_type(message: Any) -> str:
    raw = getattr(message, "type", None)
    if isinstance(raw, str):
        return raw
    if isinstance(message, dict):
        raw = message.get("type")
        if isinstance(raw, str):
            return raw
    return ""


def _message_has_tool_calls(message: Any) -> bool:
    raw = getattr(message, "tool_calls", None)
    if raw:
        return True
    if isinstance(message, dict):
        return bool(message.get("tool_calls"))
    return False


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


def _latest_human_text(state: dict[str, Any]) -> str:
    for message in reversed(state.get("messages") or []):
        if _message_type(message) != "human":
            continue
        text = _extract_text(getattr(message, "content", message.get("content", "") if isinstance(message, dict) else "")).strip()
        if text:
            return text
    return ""


def _title_from_user_prompt(prompt: str) -> str:
    line = " ".join(prompt.strip().split())
    if not line:
        return "Execution Plan"
    if len(line) <= 72:
        return line
    return line[:69].rstrip() + "..."


def resolve_plan_root(thread_data: dict[str, Any] | None) -> str | None:
    if not isinstance(thread_data, dict):
        return None
    workspace_path = thread_data.get("workspace_path")
    if isinstance(workspace_path, str) and workspace_path.strip():
        return workspace_path
    return None


def get_runtime_root(workspace_path: str | None, runtime_dir: str = _RUNTIME_DIR) -> Path | None:
    if not workspace_path:
        return None
    return Path(workspace_path) / runtime_dir


def get_runtime_artifact_path(workspace_path: str | None, filename: str, runtime_dir: str = _RUNTIME_DIR) -> str | None:
    root = get_runtime_root(workspace_path, runtime_dir=runtime_dir)
    if root is None:
        return None
    return str(root / filename)


def ensure_plan_state(state: dict[str, Any]) -> dict[str, Any] | None:
    existing = dict(state.get("plan") or {})
    thread_data = state.get("thread_data")
    plan_root = resolve_plan_root(thread_data)
    if plan_root is None:
        return existing or None

    created_at_raw = str(existing.get("created_at") or "").strip()
    created_at_dt = datetime.now(UTC)
    if created_at_raw:
        try:
            created_at_dt = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    created_at = created_at_raw or created_at_dt.isoformat()

    latest_user = _latest_human_text(state)
    title = str(existing.get("title") or "").strip() or _title_from_user_prompt(latest_user)
    summary = str(existing.get("summary") or "").strip() or _DEFAULT_PLAN_SUMMARY
    objective = str(existing.get("objective") or "").strip() or summary
    plan_id = str(existing.get("plan_id") or "").strip() or f"plan-{uuid4().hex[:10]}"
    status = str(existing.get("status") or "").strip() or "draft"

    plan_path = str(existing.get("plan_path") or "").strip()
    latest_alias_path = str(existing.get("latest_alias_path") or "").strip()
    if not plan_path:
        versioned_plan_file = Path(plan_root) / "plans" / _versioned_plan_filename(title, created_at_dt)
        plan_path = to_virtual_path(str(versioned_plan_file), thread_data) or str(versioned_plan_file)
    if not latest_alias_path:
        latest_plan_alias_file = Path(plan_root) / "plan.md"
        latest_alias_path = to_virtual_path(str(latest_plan_alias_file), thread_data) or str(latest_plan_alias_file)

    ensured = {
        **existing,
        "plan_id": plan_id,
        "status": status,
        "title": title,
        "summary": summary,
        "objective": objective,
        "created_at": created_at,
        "plan_path": plan_path,
        "latest_alias_path": latest_alias_path,
    }
    state["plan"] = ensured
    return ensured


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


def _is_plan_artifact(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized.endswith("/plan.md"):
        return True
    if "/plans/" in normalized and "/plan-" in normalized and normalized.endswith(".md"):
        return True
    return False


def _is_runtime_artifact(path: str) -> bool:
    return "/.runtime/" in path.replace("\\", "/")


def _collect_file_changes(state: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    excluded = {
        str(plan.get("plan_path") or "").strip(),
        str(plan.get("latest_alias_path") or "").strip(),
        str(plan.get("evaluator_report_path") or "").strip(),
    }
    files: list[str] = []
    for path in state.get("artifacts") or []:
        if not isinstance(path, str):
            continue
        normalized = path.strip()
        if not normalized or normalized in excluded or _is_plan_artifact(normalized) or _is_runtime_artifact(normalized):
            continue
        files.append(normalized)
    return list(dict.fromkeys(files))


def _collect_runtime_artifacts(state: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    runtime_paths: list[str] = []
    for path in state.get("handoff_artifacts") or []:
        if not isinstance(path, str):
            continue
        normalized = path.strip()
        if not normalized or _is_plan_artifact(normalized):
            continue
        if _is_runtime_artifact(normalized) or normalized == str(plan.get("evaluator_report_path") or "").strip():
            runtime_paths.append(normalized)
    return list(dict.fromkeys(runtime_paths))


def _collect_execution_notes(state: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for message in reversed(state.get("messages") or []):
        if _message_type(message) != "ai" or _message_has_tool_calls(message):
            continue
        content = _extract_text(getattr(message, "content", message.get("content", "") if isinstance(message, dict) else "")).strip()
        if not content:
            continue
        condensed = " ".join(content.split())
        if condensed:
            notes.append(condensed[:320])
        if len(notes) >= 2:
            break
    notes.reverse()
    return notes


def _normalize_plan_status(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"draft", "approved", "executing", "completed"}:
        return value
    return "draft"


def _current_status_line(nodes: list[dict[str, Any]], plan: dict[str, Any], file_changes: list[str]) -> str:
    total = len(nodes)
    completed = sum(1 for node in nodes if str(node.get("status") or "") == "completed")
    status = _normalize_plan_status(plan.get("status"))
    if total == 0:
        return f"Plan status: `{status}`."
    if status == "draft":
        if completed >= total:
            return (
                f"Plan status: `{status}`. All {completed}/{total} todos are marked done in the graph, "
                "but execution was not approved — use Execute Plan before treating work as complete."
            )
        if completed > 0:
            return (
                f"Plan status: `{status}`. {completed}/{total} todos marked done, but the plan is still draft "
                "(execution tools remain blocked until approval)."
            )
        return f"Plan status: `{status}`. Waiting for Execute Plan approval before running execution tools."
    if status in {"approved", "executing"} and completed >= total:
        return f"Plan status: `{status}`. In progress: {completed}/{total} todos marked complete."
    if status == "completed" and completed >= total:
        return f"Plan status: `{status}`. Execution complete with {completed}/{total} todos done."
    if completed >= total:
        return f"Plan status: `{status}`. All {completed}/{total} todos marked complete."
    if completed > 0:
        return f"Plan status: `{status}`. Progress: {completed}/{total} todos complete and {len(file_changes)} tracked file change(s)."
    return f"Plan status: `{status}`. Execution has not completed any todos yet."


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
    current_status: str | None = None,
    file_changes: list[str] | None = None,
    runtime_artifacts: list[str] | None = None,
    evaluator_findings: list[str] | None = None,
    clarifications: list[dict[str, Any]] | None = None,
    clarification_answers: list[dict[str, str]] | None = None,
    last_synced_at: str | None = None,
    include_frontmatter: bool = True,
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
    status_lines = []
    for node in nodes:
        node_status = str(node.get("status") or "pending")
        content = str(node.get("content") or "").strip()
        if not content:
            continue
        check = "x" if node_status == "completed" else " "
        deps = [str(dep).strip() for dep in (node.get("depends_on") or []) if str(dep).strip()]
        rationale = str(node.get("rationale") or "").strip() or "Required to progress the implementation safely."
        todo_id = str(node.get("id") or "").strip() or "todo"
        todo_lines.append(f"- [{check}] **{todo_id}**: {content}")
        todo_lines.append(f"  - Status: {node_status}")
        todo_lines.append(f"  - Rationale: {rationale}")
        # Rich todo annotations — render only when present so legacy plans
        # without these fields stay clean. See planner_middleware._normalize_todo_steps.
        objective_text = str(node.get("objective") or "").strip()
        if objective_text:
            todo_lines.append(f"  - Objective: {objective_text}")
        steps = node.get("steps") or []
        if isinstance(steps, list) and steps:
            todo_lines.append("  - Steps:")
            for idx, step in enumerate(steps, start=1):
                if not isinstance(step, dict):
                    continue
                step_description = str(step.get("description") or "").strip()
                if not step_description:
                    continue
                todo_lines.append(f"    {idx}. {step_description}")
                subagents = step.get("subagent_types") or []
                if isinstance(subagents, list) and subagents:
                    todo_lines.append(f"       - Subagent: {', '.join(str(s) for s in subagents if s)}")
                else:
                    todo_lines.append("       - Subagent: lead agent")
                tools = step.get("tools") or []
                if isinstance(tools, list) and tools:
                    todo_lines.append(f"       - Tools: {', '.join(str(t) for t in tools if t)}")
                output_path = step.get("output_artifact_path")
                if output_path:
                    todo_lines.append(f"       - Output: `{output_path}`")
                step_done_when = str(step.get("completion_requirement") or "").strip()
                if step_done_when:
                    todo_lines.append(f"       - Done when: {step_done_when}")
        todo_done_when = str(node.get("completion_requirement") or "").strip()
        if todo_done_when:
            todo_lines.append(f"  - Done when: {todo_done_when}")
        failure_fallback = str(node.get("failure_fallback") or "").strip()
        if failure_fallback:
            todo_lines.append(f"  - On failure: {failure_fallback}")
        if deps:
            todo_lines.append(f"  - Depends on: {', '.join(deps)}")
        status_lines.append(f"- [{node_status}] {todo_id}: {content}")
    todos_block = "\n".join(todo_lines) if todo_lines else "- [ ] **todo-1**: Complete the user request end-to-end.\n  - Status: pending\n  - Rationale: Required baseline delivery step."
    todo_status_block = "\n".join(status_lines) if status_lines else "- [pending] todo-1: Complete the user request end-to-end."

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
    file_changes_block = "\n".join(f"- `{item}`" for item in (file_changes or [])) or "- No tracked workspace file changes yet."
    runtime_artifacts_block = "\n".join(f"- `{item}`" for item in (runtime_artifacts or [])) or "- No runtime artifacts recorded."
    evaluator_block = "\n".join(f"- {item}" for item in (evaluator_findings or [])) or "- No evaluator findings recorded."
    clarification_lines = []
    for clarification in (clarifications or []):
        if not isinstance(clarification, dict):
            continue
        q = str(clarification.get("question") or "").strip()
        if not q:
            continue
        opts = clarification.get("options") or []
        option_texts = [f"    - {o.get('label')}" + (" (recommended)" if o.get('recommended') else "") for o in opts if isinstance(o, dict) and o.get("label")]
        matched_answer = ""
        for ans in (clarification_answers or []):
            if isinstance(ans, dict) and str(ans.get("question") or "").strip() == q:
                matched_answer = str(ans.get("selected_label") or ans.get("answer") or "").strip()
        answer_line = f"  - **User choice**: {matched_answer}" if matched_answer else "  - **User choice**: *(pending)*"
        clarification_lines.append(f"- **{q}**")
        clarification_lines.append(answer_line)
        if option_texts:
            clarification_lines.append("  - Options considered:")
            clarification_lines.extend(option_texts)
    clarifications_block = "\n".join(clarification_lines) if clarification_lines else "- No clarifications were raised during planning."
    current_status_text = current_status or "Plan status is not yet available."
    last_synced = last_synced_at or (created_at or "unknown").strip()

    plan_status_label = _normalize_plan_status(status)
    body = (
        f"# {title}\n\n"
        f"**Plan status:** `{plan_status_label}`\n\n"
        "## Objective\n"
        f"{objective_text}\n\n"
        "## Current Status\n"
        f"{current_status_text}\n\n"
        "## Summary\n"
        f"{(summary or objective_text).strip()}\n\n"
        "## Assumptions\n"
        f"{assumptions_block}\n\n"
        "## Constraints\n"
        f"{constraints_block}\n\n"
        "## Execution Discipline\n"
        "- Treat this plan as the single source of truth for execution.\n"
        "- Keep todo status, file changes, and outcomes aligned with the latest run state.\n"
        "- Update this document through background sync after meaningful execution progress.\n\n"
        "## Phased Implementation Steps\n"
        f"{todos_block}\n\n"
        "## Todo Status Snapshot\n"
        f"{todo_status_block}\n\n"
        "## File Changes\n"
        f"{file_changes_block}\n\n"
        "## Runtime Artifacts\n"
        f"{runtime_artifacts_block}\n\n"
        "## Evaluator Findings\n"
        f"{evaluator_block}\n\n"
        "## Clarifications\n"
        f"{clarifications_block}\n\n"
        "## Risks & Mitigations\n"
        f"{risks_block}\n\n"
        "## Acceptance Criteria\n"
        f"{acceptance_block}\n\n"
        "## Execution DAG\n"
        f"{dag_block}\n"
    )

    if not include_frontmatter:
        return body

    # Legacy v4 frontmatter — superseded by the canonical v5 frontmatter
    # written via ``serialize_plan_md`` in ``common/handoff.py``. Callers that
    # use ``serialize_plan_md`` pass ``include_frontmatter=False`` to compose
    # the canonical frontmatter with this body. The v4 fallback is kept for
    # direct calls that bypass the canonical serializer.
    return (
        "---\n"
        "plan_version: 4\n"
        f'plan_id: "{(plan_id or "").strip()}"\n'
        f'domain: "{domain}"\n'
        f'title: "{frontmatter_title}"\n'
        f'status: "{_normalize_plan_status(status)}"\n'
        f'created_at: "{(created_at or "unknown").strip()}"\n'
        f'last_synced_at: "{last_synced}"\n'
        f"total_todos: {total}\n"
        f"completed_todos: {completed}\n"
        "---\n\n"
        + body
    )


def _write_if_changed(path: str, content: str) -> bool:
    """Deprecated alias for `_fs_utils.write_if_changed`. Kept so external
    callers in this module remain unchanged while the helper lives in
    `_fs_utils`."""
    return write_if_changed(path, content)


def _can_resolve_write_path(path: str, thread_data: dict[str, Any] | None) -> bool:
    if path.startswith("/mnt/") and not thread_data:
        return False
    return True


def sync_handoff_files_from_state(state: dict[str, Any]) -> list[str]:
    """Sync living plan files from in-memory thread state.

    Returns list of virtual or physical plan paths that changed.
    """
    plan = ensure_plan_state(state)
    if not isinstance(plan, dict):
        return []

    thread_data = state.get("thread_data")
    nodes = _extract_nodes_from_state(state)
    if not nodes:
        return []

    title = str(plan.get("title") or "Execution Plan")
    summary = str(plan.get("summary") or _DEFAULT_PLAN_SUMMARY)
    domain = str(plan.get("domain") or "generic")
    file_changes = _collect_file_changes(state, plan)
    runtime_artifacts = _collect_runtime_artifacts(state, plan)
    evaluator_findings = []
    latest_eval = str(plan.get("latest_evaluator_report") or "").strip()
    if latest_eval:
        evaluator_findings.append(latest_eval)
    elif str(plan.get("evaluation_status") or "").strip():
        evaluator_findings.append(f"Evaluation status: {plan['evaluation_status']}")

    clarifications_raw = plan.get("clarifications") if isinstance(plan.get("clarifications"), list) else None
    clarification_answers_raw = plan.get("clarification_answers") if isinstance(plan.get("clarification_answers"), list) else None
    last_synced = str(plan.get("last_synced_at") or "").strip() or str(plan.get("created_at") or "").strip() or None
    canonical_plan: dict[str, Any] = {
        "plan_id": str(plan.get("plan_id") or "").strip(),
        "title": title,
        "status": str(plan.get("status") or "").strip(),
        "domain": domain,
        "target_mode": str(plan.get("target_mode") or "work"),
        "created_at": str(plan.get("created_at") or "").strip(),
        "last_synced_at": last_synced or "",
        "objective": str(plan.get("objective") or "").strip(),
        "summary": summary,
        "assumptions": plan.get("assumptions") if isinstance(plan.get("assumptions"), list) else [],
        "constraints": plan.get("constraints") if isinstance(plan.get("constraints"), list) else [],
        "risks": plan.get("risks") if isinstance(plan.get("risks"), list) else [],
        "acceptance_criteria": plan.get("acceptance_criteria") if isinstance(plan.get("acceptance_criteria"), list) else [],
        "clarifications": clarifications_raw or [],
        "clarification_answers": clarification_answers_raw or [],
        "clarification_pending": bool(plan.get("clarification_pending", False)),
        "clarification_resolved": bool(plan.get("clarification_resolved", False)),
    }
    canonical_graph: dict[str, Any] = {
        "nodes": nodes,
        "ready_ids": list((state.get("todo_graph") or {}).get("ready_ids") or []),
    }

    def _render_body(_plan: dict, _nodes: list[dict]) -> str:
        return render_plan_md(
            title,
            summary,
            _nodes,
            domain=domain,
            plan_id=canonical_plan["plan_id"] or None,
            status=canonical_plan["status"] or None,
            created_at=canonical_plan["created_at"] or None,
            objective=canonical_plan["objective"] or None,
            assumptions=canonical_plan["assumptions"] or None,
            constraints=canonical_plan["constraints"] or None,
            risks=canonical_plan["risks"] or None,
            acceptance_criteria=canonical_plan["acceptance_criteria"] or None,
            current_status=_current_status_line(_nodes, plan, file_changes),
            file_changes=file_changes,
            runtime_artifacts=runtime_artifacts,
            evaluator_findings=evaluator_findings,
            clarifications=clarifications_raw,
            clarification_answers=clarification_answers_raw,
            last_synced_at=last_synced,
            include_frontmatter=False,
        )

    from src.agents.common.handoff import serialize_plan_md  # local import to avoid module-load cycle

    plan_md = serialize_plan_md(canonical_plan, canonical_graph, body_renderer=_render_body)

    changed: list[str] = []
    for key in ("plan_path", "latest_alias_path"):
        path = plan.get(key)
        if not isinstance(path, str) or not path.strip():
            continue
        if not _can_resolve_write_path(path, thread_data):
            continue
        physical = replace_virtual_path(path, thread_data)
        if _write_if_changed(physical, plan_md):
            changed.append(path)

    return changed
