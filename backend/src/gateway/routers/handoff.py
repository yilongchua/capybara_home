"""Thread handoff API for deterministic workspace fork packages."""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agents.middlewares.handoff_sync import ensure_plan_state, render_plan_md
from src.config.paths import get_paths
from src.sandbox.path_mapping import replace_virtual_path, to_virtual_path

router = APIRouter(prefix="/api", tags=["handoff"])
logger = logging.getLogger(__name__)

_HANDOFF_DIR = ".handoff"
_MAX_RECENT_MESSAGES = 12
_MAX_RECENT_USER_MESSAGES = 8
_ANALYSE_DIR = ".analyse"
_ANALYSE_FILE_NAMES = (
    "index.md",
    "repo_overview.md",
    "repo_overview.previous.md",
    "failed_files.md",
    "created_files.md",
    "directory_tree.md",
    "file_catalog.md",
)


def _langgraph_url() -> str:
    return os.getenv("CAPYBARA_LANGGRAPH_URL") or os.getenv("LANGGRAPH_URL") or "http://localhost:2024"


def _extract_status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _extract_graph_id(raw: Any) -> str | None:
    if isinstance(raw, dict):
        graph_id = raw.get("graph_id")
        if isinstance(graph_id, str) and graph_id.strip():
            return graph_id.strip()
        metadata = raw.get("metadata")
        if isinstance(metadata, dict):
            nested = metadata.get("graph_id")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def _is_missing_graph_id_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "no assigned graph id" in message


def _is_ambiguous_update_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "ambiguous update" in message and "as_node" in message


class HandoffResponse(BaseModel):
    new_thread_id: str
    handoff_root_virtual_path: str
    prefill: str
    copied_file_count: int | None = Field(default=None)
    package_manifest_virtual_path: str | None = Field(default=None)


def _clear_existing_handoffs(workspace_root: Path) -> None:
    handoff_root = workspace_root / _HANDOFF_DIR
    if not handoff_root.exists():
        return
    for item in handoff_root.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def _extract_state_values(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        values = raw.get("values")
        if isinstance(values, dict):
            return values
        return raw
    values = getattr(raw, "values", None)
    if isinstance(values, dict):
        return values
    return {}


def _message_type(message: Any) -> str:
    raw = getattr(message, "type", None)
    if isinstance(raw, str):
        return raw
    if isinstance(message, dict):
        raw = message.get("type")
        if isinstance(raw, str):
            return raw
        role = message.get("role")
        if isinstance(role, str):
            role_lower = role.lower()
            if role_lower == "user":
                return "human"
            if role_lower == "assistant":
                return "ai"
            return role_lower
    return ""


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                block_type = str(block.get("type") or "")
                if block_type == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        return "\n".join(part.strip() for part in parts if part and part.strip())
    return ""


def _message_text(message: Any) -> str:
    if isinstance(message, dict):
        return _extract_text(message.get("content")).strip()
    return _extract_text(getattr(message, "content", "")).strip()


def _normalized_messages(messages: Any) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        return []
    normalized: list[dict[str, str]] = []
    for index, message in enumerate(messages):
        msg_type = _message_type(message)
        text = _message_text(message)
        if msg_type not in {"human", "ai", "system"} or not text:
            continue
        normalized.append(
            {
                "id": str(getattr(message, "id", None) or message.get("id", f"msg-{index}") if isinstance(message, dict) else f"msg-{index}"),
                "type": msg_type,
                "text": text,
            }
        )
    return normalized


def _select_recent_messages(messages: list[dict[str, str]], limit: int = _MAX_RECENT_MESSAGES) -> list[dict[str, str]]:
    return messages[-limit:] if len(messages) > limit else messages


def _recent_user_messages(messages: list[dict[str, str]], limit: int = _MAX_RECENT_USER_MESSAGES) -> list[str]:
    items = [message["text"] for message in messages if message["type"] == "human" and message["text"].strip()]
    return items[-limit:] if len(items) > limit else items


def _thread_data_for_thread(thread_id: str) -> dict[str, str]:
    paths = get_paths()
    paths.ensure_thread_dirs(thread_id)
    return {
        "workspace_path": str(paths.sandbox_work_dir(thread_id)),
        "uploads_path": str(paths.sandbox_uploads_dir(thread_id)),
        "outputs_path": str(paths.sandbox_outputs_dir(thread_id)),
    }


def _extract_nodes_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    graph = state.get("todo_graph")
    if isinstance(graph, dict):
        nodes = graph.get("nodes")
        if isinstance(nodes, list):
            normalized = [node for node in nodes if isinstance(node, dict)]
            if normalized:
                return normalized

    todos = state.get("todos")
    if not isinstance(todos, list):
        return []
    nodes: list[dict[str, Any]] = []
    for index, todo in enumerate(todos):
        if not isinstance(todo, dict):
            continue
        content = str(todo.get("content") or "").strip()
        if not content:
            continue
        nodes.append(
            {
                "id": str(todo.get("id") or f"todo-{index + 1}"),
                "content": content,
                "status": str(todo.get("status") or "pending"),
                "depends_on": todo.get("depends_on") if isinstance(todo.get("depends_on"), list) else [],
            }
        )
    return nodes


def _collect_workspace_artifacts(state: dict[str, Any], thread_data: dict[str, str]) -> list[str]:
    paths: list[str] = []
    for artifact in state.get("artifacts") or []:
        if not isinstance(artifact, str):
            continue
        normalized = artifact.strip()
        if not normalized:
            continue
        physical = replace_virtual_path(normalized, thread_data)
        if physical.startswith(thread_data["workspace_path"]):
            paths.append(normalized)
    return list(dict.fromkeys(paths))


def _collect_runtime_artifacts(state: dict[str, Any]) -> list[str]:
    artifacts: list[str] = []
    for artifact in state.get("handoff_artifacts") or []:
        if not isinstance(artifact, str):
            continue
        normalized = artifact.strip()
        if normalized:
            artifacts.append(normalized)
    return list(dict.fromkeys(artifacts))


def _collect_analysis_artifacts(workspace_root: Path, thread_data: dict[str, str]) -> list[str]:
    analyse_root = workspace_root / _ANALYSE_DIR
    if not analyse_root.exists() or not analyse_root.is_dir():
        return []

    paths: list[str] = []
    for name in _ANALYSE_FILE_NAMES:
        candidate = analyse_root / name
        if not candidate.exists() or not candidate.is_file():
            continue
        virtual = to_virtual_path(str(candidate), thread_data)
        if virtual:
            paths.append(virtual)
    return paths


def _current_status_summary(plan: dict[str, Any], nodes: list[dict[str, Any]], artifacts: list[str]) -> str:
    status = str(plan.get("status") or "draft").strip() or "draft"
    completed = sum(1 for node in nodes if str(node.get("status") or "").strip() == "completed")
    total = len(nodes)
    if total == 0:
        return f"Plan status is `{status}`. No explicit todos are tracked yet."
    return f"Plan status is `{status}` with {completed}/{total} todos complete and {len(artifacts)} tracked workspace artifact(s)."


def _render_plan_for_handoff(state: dict[str, Any], thread_data: dict[str, str]) -> str:
    state_for_plan = dict(state)
    state_for_plan["thread_data"] = thread_data
    plan = ensure_plan_state(state_for_plan) or {}
    nodes = _extract_nodes_from_state(state_for_plan)
    artifacts = _collect_workspace_artifacts(state_for_plan, thread_data)
    runtime_artifacts = _collect_runtime_artifacts(state_for_plan)
    evaluator_findings: list[str] = []
    if isinstance(plan.get("latest_evaluator_report"), str) and plan["latest_evaluator_report"].strip():
        evaluator_findings.append(plan["latest_evaluator_report"].strip())
    elif isinstance(plan.get("evaluation_status"), str) and plan["evaluation_status"].strip():
        evaluator_findings.append(f"Evaluation status: {plan['evaluation_status'].strip()}")

    return render_plan_md(
        str(plan.get("title") or state.get("title") or "Execution Plan"),
        str(plan.get("summary") or "Living execution record for the current thread."),
        nodes,
        domain=str(plan.get("domain") or "generic"),
        plan_id=str(plan.get("plan_id") or "").strip() or None,
        status=str(plan.get("status") or "").strip() or None,
        created_at=str(plan.get("created_at") or "").strip() or None,
        objective=str(plan.get("objective") or "").strip() or None,
        assumptions=plan.get("assumptions") if isinstance(plan.get("assumptions"), list) else None,
        constraints=plan.get("constraints") if isinstance(plan.get("constraints"), list) else None,
        risks=plan.get("risks") if isinstance(plan.get("risks"), list) else None,
        acceptance_criteria=plan.get("acceptance_criteria") if isinstance(plan.get("acceptance_criteria"), list) else None,
        current_status=_current_status_summary(plan, nodes, artifacts),
        file_changes=artifacts,
        runtime_artifacts=runtime_artifacts,
        evaluator_findings=evaluator_findings,
        execution_notes=[],
        last_synced_at=_utc_now_iso(),
    )


def _read_plan_content(state: dict[str, Any], thread_data: dict[str, str]) -> str:
    plan = state.get("plan")
    if isinstance(plan, dict):
        for key in ("latest_alias_path", "plan_path"):
            candidate = plan.get(key)
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            try:
                physical = Path(replace_virtual_path(candidate, thread_data))
                if physical.exists():
                    return physical.read_text(encoding="utf-8")
            except OSError:
                continue
    return _render_plan_for_handoff(state, thread_data)


def _build_project_status(
    state: dict[str, Any],
    plan: dict[str, Any],
    nodes: list[dict[str, Any]],
    artifacts: list[str],
    runtime_artifacts: list[str],
    analysis_artifacts: list[str],
) -> str:
    completed = [node for node in nodes if str(node.get("status") or "") == "completed"]
    pending = [node for node in nodes if str(node.get("status") or "") != "completed"]
    next_step = pending[0]["content"] if pending else "Review the copied workspace and continue from the completed plan."
    lines = [
        "# Project Status",
        "",
        f"- Thread title: {str(state.get('title') or plan.get('title') or 'Untitled')}",
        f"- Current status: {str(plan.get('status') or 'draft')}",
        f"- Todos completed: {len(completed)}/{len(nodes)}",
        f"- Workspace artifacts tracked: {len(artifacts)}",
        f"- Runtime artifacts tracked: {len(runtime_artifacts)}",
        f"- Analysis artifacts available: {len(analysis_artifacts)}",
        "",
        "## Done",
    ]
    if completed:
        lines.extend(f"- {str(node.get('content') or '').strip()}" for node in completed[:10])
    else:
        lines.append("- No explicit completed todos yet.")
    lines.extend(["", "## In Progress / Remaining"])
    if pending:
        lines.extend(f"- [{str(node.get('status') or 'pending')}] {str(node.get('content') or '').strip()}" for node in pending[:12])
    else:
        lines.append("- No remaining tracked todos.")
    lines.extend(["", "## Latest Notable Files"])
    if artifacts:
        lines.extend(f"- `{artifact}`" for artifact in artifacts[:20])
    else:
        lines.append("- No tracked workspace files yet.")
    lines.extend(["", "## Analysis Outputs"])
    if analysis_artifacts:
        lines.extend(f"- `{artifact}`" for artifact in analysis_artifacts[:20])
    else:
        lines.append("- No `.analyse` outputs were found in this workspace snapshot.")
    lines.extend(["", "## Next", f"- {next_step}", ""])
    return "\n".join(lines)


def _build_conversation_context(state: dict[str, Any], plan: dict[str, Any], recent_user_messages: list[str]) -> str:
    assumptions = plan.get("assumptions") if isinstance(plan.get("assumptions"), list) else []
    constraints = plan.get("constraints") if isinstance(plan.get("constraints"), list) else []
    clarifications = plan.get("clarifications") if isinstance(plan.get("clarifications"), list) else []
    lines = [
        "# Conversation Context",
        "",
        "## Objective",
        str(plan.get("objective") or plan.get("summary") or state.get("title") or "Continue the thread accurately from this handoff."),
        "",
        "## Working Summary",
        str(plan.get("summary") or "No formal summary is available yet."),
        "",
        "## Key Decisions And Preferences",
    ]
    if assumptions:
        lines.extend(f"- {str(item).strip()}" for item in assumptions if str(item).strip())
    if constraints:
        lines.extend(f"- Constraint: {str(item).strip()}" for item in constraints if str(item).strip())
    if not assumptions and not constraints:
        lines.append("- No formal assumptions or constraints were captured in plan state.")
    lines.extend(["", "## Recent User Intent"])
    if recent_user_messages:
        lines.extend(f"- {message}" for message in recent_user_messages[-6:])
    else:
        lines.append("- No recent user messages were available.")
    lines.extend(["", "## Outstanding Clarifications"])
    if clarifications:
        for clarification in clarifications[:8]:
            if isinstance(clarification, dict):
                question = str(clarification.get("question") or "").strip()
                if question:
                    lines.append(f"- {question}")
    elif isinstance(plan.get("clarification_question"), str) and plan["clarification_question"].strip():
        lines.append(f"- {plan['clarification_question'].strip()}")
    else:
        lines.append("- No outstanding clarification prompts were captured.")
    lines.append("")
    return "\n".join(lines)


def _build_recent_messages(messages: list[dict[str, str]]) -> str:
    lines = [
        "# Recent Messages",
        "",
        "Curated recent human and assistant messages with low-signal/tool noise removed.",
        "",
    ]
    if not messages:
        lines.append("- No recent messages were available.")
        lines.append("")
        return "\n".join(lines)
    for message in messages:
        role = "User" if message["type"] == "human" else "Assistant" if message["type"] == "ai" else "System"
        lines.extend([f"## {role}", message["text"], ""])
    return "\n".join(lines)


def _build_memory(state: dict[str, Any], plan: dict[str, Any], recent_user_messages: list[str]) -> str:
    lines = [
        "# Memory",
        "",
        "## Stable Thread Facts",
        f"- Thread title: {str(state.get('title') or plan.get('title') or 'Untitled')}",
        f"- Primary objective: {str(plan.get('objective') or plan.get('summary') or 'Continue the active work accurately.')}",
        f"- Current plan status: {str(plan.get('status') or 'draft')}",
    ]
    if isinstance(plan.get("constraints"), list):
        lines.extend(f"- Constraint: {str(item).strip()}" for item in plan["constraints"] if str(item).strip())
    if recent_user_messages:
        lines.extend(["", "## Remember These User Requests"])
        lines.extend(f"- {message}" for message in recent_user_messages[-5:])
    lines.append("")
    return "\n".join(lines)


def _build_artifacts(
    artifacts: list[str],
    runtime_artifacts: list[str],
    analysis_artifacts: list[str],
    plan_virtual_path: str,
) -> str:
    lines = [
        "# Artifacts",
        "",
        "## Core Plan Artifact",
        f"- `{plan_virtual_path}`",
        "",
        "## Workspace Artifacts",
    ]
    if artifacts:
        lines.extend(f"- `{artifact}`" for artifact in artifacts[:40])
    else:
        lines.append("- No tracked workspace artifacts.")
    lines.extend(["", "## Runtime Artifacts"])
    if runtime_artifacts:
        lines.extend(f"- `{artifact}`" for artifact in runtime_artifacts[:40])
    else:
        lines.append("- No runtime artifacts recorded.")
    lines.extend(["", "## Analysis Artifacts"])
    if analysis_artifacts:
        lines.extend(f"- `{artifact}`" for artifact in analysis_artifacts[:40])
    else:
        lines.append("- No `.analyse` artifacts recorded.")
    lines.append("")
    return "\n".join(lines)


def _build_open_items(plan: dict[str, Any], nodes: list[dict[str, Any]]) -> str:
    lines = [
        "# Open Items",
        "",
        "## Remaining Todos",
    ]
    remaining = [node for node in nodes if str(node.get("status") or "") != "completed"]
    if remaining:
        lines.extend(f"- [{str(node.get('status') or 'pending')}] {str(node.get('content') or '').strip()}" for node in remaining[:20])
    else:
        lines.append("- No remaining todos are currently tracked.")
    lines.extend(["", "## Risks / Follow-Up"])
    risks = plan.get("risks") if isinstance(plan.get("risks"), list) else []
    if risks:
        for risk in risks[:10]:
            if not isinstance(risk, dict):
                continue
            risk_text = str(risk.get("risk") or "").strip()
            mitigation = str(risk.get("mitigation") or "").strip()
            if risk_text and mitigation:
                lines.append(f"- {risk_text} | Mitigation: {mitigation}")
            elif risk_text:
                lines.append(f"- {risk_text}")
    elif isinstance(plan.get("clarification_question"), str) and plan["clarification_question"].strip():
        lines.append(f"- Clarify: {plan['clarification_question'].strip()}")
    else:
        lines.append("- No explicit open risks were captured.")
    lines.append("")
    return "\n".join(lines)


def _list_workspace_files(workspace_root: Path) -> list[Path]:
    if not workspace_root.exists():
        return []
    return sorted([path for path in workspace_root.rglob("*") if path.is_file()], key=lambda path: str(path.relative_to(workspace_root)))


def _build_workspace_manifest(workspace_root: Path) -> str:
    files = _list_workspace_files(workspace_root)
    lines = [
        "# Workspace Manifest",
        "",
        f"- Workspace root: `{workspace_root}`",
        f"- File count: {len(files)}",
        "",
    ]
    if not files:
        lines.append("- No files found in workspace snapshot.")
        lines.append("")
        return "\n".join(lines)
    for path in files:
        relative = path.relative_to(workspace_root)
        suffix = path.suffix or "<none>"
        lines.append(f"- `{relative.as_posix()}` | {path.stat().st_size} bytes | {suffix}")
    lines.append("")
    return "\n".join(lines)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_index(
    handoff_id: str,
    source_thread_id: str,
    new_thread_id: str,
    analysis_artifacts: list[str],
) -> str:
    analysis_lines = (
        [
            "## Analysis Companion",
            "Read the derived `/mnt/user-data/workspace/.analyse` files when you need repo summaries, catalogs, or failure manifests.",
            *[f"- `{artifact}`" for artifact in analysis_artifacts[:10]],
            "",
        ]
        if analysis_artifacts
        else []
    )
    return "\n".join(
        [
            "# Handoff Package",
            "",
            f"- Handoff id: `{handoff_id}`",
            f"- Source thread: `{source_thread_id}`",
            f"- Forked thread: `{new_thread_id}`",
            "",
            "## Read This First",
            "1. Read `project_status.md` for the active state of work.",
            "2. Read `conversation_context.md` and `memory.md` to recover goals, decisions, and constraints.",
            "3. Read `plan.md` as the execution source of truth before continuing implementation.",
            "4. Use `recent_messages.md` only when exact recent wording matters.",
            "",
            "## Package Contents",
            "- [project_status.md](project_status.md)",
            "- [conversation_context.md](conversation_context.md)",
            "- [recent_messages.md](recent_messages.md)",
            "- [plan.md](plan.md)",
            "- [memory.md](memory.md)",
            "- [workspace_manifest.md](workspace_manifest.md)",
            "- [artifacts.md](artifacts.md)",
            "- [open_items.md](open_items.md)",
            "- [handoff_manifest.json](handoff_manifest.json)",
            "",
            *analysis_lines,
        ]
    )


def _copy_workspace_snapshot(source_workspace: Path, dest_workspace: Path) -> int:
    dest_workspace.mkdir(parents=True, exist_ok=True)
    copied = 0
    if not source_workspace.exists():
        return copied
    for item in source_workspace.iterdir():
        target = dest_workspace / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True, symlinks=True)
            copied += sum(1 for path in target.rglob("*") if path.is_file())
        else:
            shutil.copy2(item, target)
            copied += 1
    return copied


def _prefill_message(handoff_root_virtual_path: str) -> str:
    return (
        f"Continue from the handoff package at {handoff_root_virtual_path}.\n"
        "Read `index.md` first, then `project_status.md`, `conversation_context.md`, and `plan.md` before continuing."
    )


def _build_handoff_package(source_thread_id: str, new_thread_id: str, state_values: dict[str, Any]) -> tuple[str, str | None, str]:
    thread_data = _thread_data_for_thread(source_thread_id)
    workspace_root = Path(thread_data["workspace_path"])
    _clear_existing_handoffs(workspace_root)
    handoff_id = f"handoff-{_utc_now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    handoff_root = workspace_root / _HANDOFF_DIR / handoff_id
    handoff_root.mkdir(parents=True, exist_ok=True)
    created_at = _utc_now_iso()

    state_for_plan = dict(state_values)
    state_for_plan["thread_data"] = thread_data
    plan = ensure_plan_state(state_for_plan) or {}
    nodes = _extract_nodes_from_state(state_for_plan)
    normalized_messages = _normalized_messages(state_for_plan.get("messages"))
    recent_messages = _select_recent_messages(normalized_messages)
    recent_user_messages = _recent_user_messages(normalized_messages)
    workspace_artifacts = _collect_workspace_artifacts(state_for_plan, thread_data)
    runtime_artifacts = _collect_runtime_artifacts(state_for_plan)
    analysis_artifacts = _collect_analysis_artifacts(workspace_root, thread_data)

    plan_md = _read_plan_content(state_for_plan, thread_data)
    plan_virtual_path = f"/mnt/user-data/workspace/{_HANDOFF_DIR}/{handoff_id}/plan.md"

    files_to_write: dict[str, str] = {
        "index.md": _build_index(handoff_id, source_thread_id, new_thread_id, analysis_artifacts),
        "project_status.md": _build_project_status(
            state_for_plan,
            plan,
            nodes,
            workspace_artifacts,
            runtime_artifacts,
            analysis_artifacts,
        ),
        "conversation_context.md": _build_conversation_context(state_for_plan, plan, recent_user_messages),
        "recent_messages.md": _build_recent_messages(recent_messages),
        "plan.md": plan_md,
        "memory.md": _build_memory(state_for_plan, plan, recent_user_messages),
        "artifacts.md": _build_artifacts(
            workspace_artifacts,
            runtime_artifacts,
            analysis_artifacts,
            plan_virtual_path,
        ),
        "open_items.md": _build_open_items(plan, nodes),
    }

    for filename, content in files_to_write.items():
        _write_text(handoff_root / filename, content)

    handoff_root_virtual_path = to_virtual_path(str(handoff_root), thread_data) or f"/mnt/user-data/workspace/{_HANDOFF_DIR}/{handoff_id}"
    copied_prefill = _prefill_message(handoff_root_virtual_path)

    manifest_path = handoff_root / "handoff_manifest.json"
    manifest_virtual_path = to_virtual_path(str(manifest_path), thread_data)
    manifest_payload = {
        "handoff_id": handoff_id,
        "created_at": created_at,
        "source_thread_id": source_thread_id,
        "new_thread_id": new_thread_id,
        "handoff_root_virtual_path": handoff_root_virtual_path,
        "prefill": copied_prefill,
        "files": sorted([*files_to_write.keys(), "handoff_manifest.json", "workspace_manifest.md"]),
    }
    _write_text(manifest_path, json.dumps(manifest_payload, indent=2, sort_keys=True))

    workspace_manifest_content = _build_workspace_manifest(workspace_root)
    _write_text(handoff_root / "workspace_manifest.md", workspace_manifest_content)

    return handoff_root_virtual_path, manifest_virtual_path, created_at


@router.post(
    "/threads/{thread_id}/handoff",
    response_model=HandoffResponse,
    summary="Create thread handoff package and fork workspace",
    description="Create a deterministic handoff package under workspace/.handoff, fork the current workspace into a new thread, and return launch metadata for the frontend.",
)
async def create_thread_handoff(thread_id: str) -> HandoffResponse:
    try:
        from langgraph_sdk import get_client

        client = get_client(url=_langgraph_url())
        source_thread = await client.threads.get(thread_id)
        source_graph_id = _extract_graph_id(source_thread)
        source_state = await client.threads.get_state(thread_id)
        source_values = _extract_state_values(source_state)

        if source_graph_id:
            new_thread = await client.threads.create(graph_id=source_graph_id)
        else:
            new_thread = await client.threads.create()
        new_thread_id = str(new_thread["thread_id"])

        source_thread_data = _thread_data_for_thread(thread_id)
        dest_thread_data = _thread_data_for_thread(new_thread_id)

        title = str(source_values.get("title") or source_values.get("plan", {}).get("title") if isinstance(source_values.get("plan"), dict) else source_values.get("title") or "").strip()
        if title:
            try:
                await client.threads.update_state(
                    new_thread_id,
                    {
                        "title": f"Handoff · {title}",
                    },
                )
            except Exception as exc:
                if _is_missing_graph_id_error(exc) or _is_ambiguous_update_error(exc):
                    logger.warning(
                        "Skipping handoff title state update for thread %s due to state-update precondition on new thread %s: %s",
                        thread_id,
                        new_thread_id,
                        exc,
                    )
                else:
                    raise

        handoff_root_virtual_path, manifest_virtual_path, created_at = _build_handoff_package(thread_id, new_thread_id, source_values)

        copied_file_count = _copy_workspace_snapshot(
            Path(source_thread_data["workspace_path"]),
            Path(dest_thread_data["workspace_path"]),
        )

        handoff_meta_payload = {
            "handoff_meta": {
                "source_thread_id": thread_id,
                "handoff_root_virtual_path": handoff_root_virtual_path,
                "package_manifest_virtual_path": manifest_virtual_path,
                "created_at": created_at,
            }
        }
        try:
            await client.threads.update_state(
                new_thread_id,
                handoff_meta_payload,
            )
        except Exception as exc:
            if _is_missing_graph_id_error(exc) or _is_ambiguous_update_error(exc):
                logger.warning(
                    "Falling back to metadata update for thread %s due to state-update precondition on new thread %s: %s",
                    thread_id,
                    new_thread_id,
                    exc,
                )
                try:
                    await client.threads.update(
                        new_thread_id,
                        metadata=handoff_meta_payload["handoff_meta"],
                    )
                except Exception:
                    logger.warning("Fallback metadata update failed for handoff thread %s", new_thread_id)
            else:
                raise

        return HandoffResponse(
            new_thread_id=new_thread_id,
            handoff_root_virtual_path=handoff_root_virtual_path,
            prefill=_prefill_message(handoff_root_virtual_path),
            copied_file_count=copied_file_count,
            package_manifest_virtual_path=manifest_virtual_path,
        )
    except HTTPException:
        raise
    except Exception as exc:
        status_code = _extract_status_code(exc)
        if status_code == 404:
            raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.") from exc
        raise HTTPException(status_code=502, detail=f"Failed to create handoff: {exc}") from exc
