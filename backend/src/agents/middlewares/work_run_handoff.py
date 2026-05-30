"""Helpers for transitioning an approved plan into a fresh Work Mode run."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from src.agents.background import submit_background_task
from src.agents.common.handoff import parse_plan_md
from src.agents.middlewares.todo_dag_middleware import _materialize_ready_ids, normalize_todo_nodes
from src.config.handoffs_config import get_handoffs_config
from src.sandbox.path_mapping import replace_virtual_path

logger = logging.getLogger(__name__)

_HANDOFF_GUARD = threading.Lock()
# Maps thread_id → monotonic timestamp when the handoff was started. We use
# a dict (not a set) so a poisoned thread_id can't permanently block re-handoffs
# if the daemon dies before its `finally` cleanup runs (process restart,
# SIGKILL, blocking import). Entries older than `_IN_FLIGHT_HANDOFF_TTL_SECONDS`
# are treated as stale and overwritten on a fresh spawn attempt.
_IN_FLIGHT_HANDOFFS: dict[str, float] = {}
_IN_FLIGHT_HANDOFF_TTL_SECONDS = 300.0  # 5 minutes
_VALID_TARGET_ENDPOINTS = {"primary", "helper"}


def _in_flight_handoff_present(thread_id: str, *, now: float | None = None) -> bool:
    """Caller must hold `_HANDOFF_GUARD`."""
    started_at = _IN_FLIGHT_HANDOFFS.get(thread_id)
    if started_at is None:
        return False
    current = now if now is not None else time.monotonic()
    if current - started_at >= _IN_FLIGHT_HANDOFF_TTL_SECONDS:
        # Stale entry — assume the prior daemon died and let a fresh spawn through.
        _IN_FLIGHT_HANDOFFS.pop(thread_id, None)
        return False
    return True


def _run_awaitable_in_worker(value: Any, loop: asyncio.AbstractEventLoop | None) -> Any:
    """Resolve SDK awaitables on the worker's persistent event loop."""
    if not hasattr(value, "__await__"):
        return value
    if loop is None:
        return asyncio.run(value)
    return loop.run_until_complete(value)


def _validate_canonical_todo_graph(parsed_graph: dict[str, Any]) -> dict[str, Any]:
    raw_nodes = parsed_graph.get("nodes") if isinstance(parsed_graph, dict) else None
    if not isinstance(raw_nodes, list):
        raise ValueError("canonical plan todo_graph.nodes must be a list")
    for node in raw_nodes:
        if not isinstance(node, dict):
            raise ValueError("canonical plan todo_graph.nodes must contain objects only")
        target_endpoint = node.get("target_endpoint")
        if target_endpoint is not None and str(target_endpoint).strip() not in _VALID_TARGET_ENDPOINTS:
            raise ValueError(f"invalid target_endpoint for todo {node.get('id')!r}: {target_endpoint!r}")
    nodes = normalize_todo_nodes(raw_nodes)
    return {
        **parsed_graph,
        "nodes": nodes,
        "ready_ids": _materialize_ready_ids(nodes),
    }


def _load_canonical_plan_overrides(values: dict[str, Any]) -> dict[str, Any]:
    """Read plan.md from disk and parse it for a canonical handoff override.

    Returns ``{"plan": ..., "todo_graph": ...}`` when the on-disk plan.md is in
    the canonical format (``plan_version >= 5``). Returns an empty dict when
    the file is missing, the parse returns ``None`` (older format), or any
    error occurs — callers should fall back to checkpointed state silently in
    that case.

    Honoring user edits to plan.md between plan approval and work handoff is
    the core purpose of this function. Without it, the work agent silently
    consumes the stale checkpointed plan and ignores manual edits.
    """
    plan = values.get("plan") if isinstance(values, dict) else None
    if not isinstance(plan, dict):
        return {}
    thread_data = values.get("thread_data") if isinstance(values, dict) else None
    virtual_path = str(plan.get("latest_alias_path") or "").strip()
    if not virtual_path:
        # Fall back to the conventional location when the plan dict doesn't
        # carry the alias path (older plans / partial state).
        workspace_path = (thread_data or {}).get("workspace_path") if isinstance(thread_data, dict) else None
        if not workspace_path:
            return {}
        physical_path = Path(workspace_path) / "plan.md"
    else:
        physical_path = Path(replace_virtual_path(virtual_path, thread_data))
    try:
        text = physical_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("Could not read plan.md for canonical handoff (%s): %s", physical_path, exc)
        return {}
    try:
        parsed = parse_plan_md(text)
    except ValueError as exc:
        logger.warning("plan.md failed canonical parse for thread handoff: %s", exc)
        return {}
    if parsed is None:
        return {}
    parsed_plan, parsed_graph = parsed
    try:
        parsed_graph = _validate_canonical_todo_graph(parsed_graph)
    except ValueError as exc:
        logger.warning("plan.md failed canonical todo validation for thread handoff: %s", exc)
        return {}
    # Carry forward fields that only the runtime knows about so we don't
    # accidentally clobber them with frontmatter defaults.
    for key in (
        "plan_path",
        "latest_alias_path",
        "execution_requested_at",
        "approved_at",
        "execution_handoff_started",
        "execution_handoff_started_at",
    ):
        if plan.get(key) is not None:
            parsed_plan.setdefault(key, plan[key])
    logger.info(
        "Loaded canonical plan.md overrides for handoff (todos=%d, status=%s)",
        len(parsed_graph.get("nodes") or []),
        parsed_plan.get("status"),
    )
    return {"plan": parsed_plan, "todo_graph": parsed_graph}


def _langgraph_url() -> str:
    return os.getenv("CAPYBARA_LANGGRAPH_URL") or os.getenv("LANGGRAPH_URL") or "http://localhost:2024"


def _normalize_title(raw: object) -> str:
    return str(raw or "").strip()


def _derive_title_from_state(values: dict) -> str:
    title = _normalize_title(values.get("title"))
    if title:
        return title
    plan = values.get("plan")
    if isinstance(plan, dict):
        plan_title = _normalize_title(plan.get("title"))
        if plan_title:
            return plan_title
    return "New Conversation"


def _run_title_handoff_if_missing(*, thread_id: str, delay_seconds: float) -> None:
    from langgraph_sdk import get_client

    time.sleep(delay_seconds)
    loop = asyncio.new_event_loop()
    try:
        client = get_client(url=_langgraph_url())
        state = client.threads.get_state(thread_id)
        # Async SDK methods are awaited at call sites in routers; here we are in
        # a daemon thread, so resolve awaitables on one loop for the worker.
        state = _run_awaitable_in_worker(state, loop)
        values = state.get("values") if isinstance(state, dict) else getattr(state, "values", {}) or {}
        current_title = _normalize_title(values.get("title")) if isinstance(values, dict) else ""
        if current_title:
            return
        fallback_title = _derive_title_from_state(values if isinstance(values, dict) else {})
        # Thread may still be near a checkpoint boundary; retry briefly on conflict.
        # CONTRACT (see code-review #15): this writer touches ONLY the top-level
        # `title` state key. The work-handoff writer touches ONLY the `plan` key.
        # Disjoint keys → no collision even when both run concurrently. Do NOT
        # add `plan` or other keys to this payload without revisiting the race.
        # Exponential backoff (Handoff #6): the original fixed 0.4s sleep kept
        # hammering the SDK on throttle. 0.4s → 0.8s → 1.6s spaces retries out.
        backoff_seconds = 0.4
        for attempt in range(4):
            try:
                result = client.threads.update_state(thread_id, {"title": fallback_title})
                _run_awaitable_in_worker(result, loop)
                return
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(backoff_seconds)
                backoff_seconds *= 2
    except Exception:
        logger.exception("Automatic title handoff failed for thread %s", thread_id)
    finally:
        loop.close()


def spawn_title_handoff_if_missing(*, thread_id: str, delay_seconds: float = 0.6, thread_name_suffix: str = "") -> None:
    worker = threading.Thread(
        target=_run_title_handoff_if_missing,
        kwargs={"thread_id": thread_id, "delay_seconds": delay_seconds},
        name=f"title-handoff-{str(thread_id or '')[:8]}{thread_name_suffix}",
        daemon=True,
    )
    worker.start()


def _handoff_context_message(original_user_request: str | None, clarification_block: str) -> list[Any]:
    from langchain_core.messages import HumanMessage

    messages: list[Any] = []
    if original_user_request and original_user_request.strip():
        messages.append(
            HumanMessage(
                name="work_handoff_context",
                content=f"<work_handoff_context>\nOriginal request: {original_user_request.strip()}\n</work_handoff_context>",
            )
        )
    if clarification_block.strip():
        messages.append(
            HumanMessage(
                name="clarification_resolved",
                content=f"<clarification_resolved>\n{clarification_block.strip()}\n</clarification_resolved>",
            )
        )
    return messages


def _read_thread_values(client: Any, thread_id: str, *, loop: asyncio.AbstractEventLoop | None = None) -> dict[str, Any]:
    state = client.threads.get_state(thread_id)
    state = _run_awaitable_in_worker(state, loop)
    raw_values = state.get("values") if isinstance(state, dict) else getattr(state, "values", {}) or {}
    return raw_values if isinstance(raw_values, dict) else {}


def _run_work_mode_handoff(
    *,
    thread_id: str,
    requested_model_name: str | None,
    auto_mode: bool,
    original_user_request: str | None,
    delay_seconds: float,
) -> None:
    from langgraph_sdk import get_client

    from src.agents.middlewares.daemon_agent_invoke import invoke_client_agent_async
    from src.agents.middlewares.plan_execution import (
        format_clarification_context_for_work,
        mark_handoff_failed,
        mark_handoff_succeeded,
    )
    from src.client import CapyHomeClient

    time.sleep(delay_seconds)
    loop = asyncio.new_event_loop()
    try:
        lg_client = get_client(url=_langgraph_url())
        # Ensure the thread has a visible title before work execution begins.
        spawn_title_handoff_if_missing(thread_id=thread_id, thread_name_suffix="-pre-work")
        handoff_cfg = get_handoffs_config()
        max_attempts = 1 + int(handoff_cfg.work_handoff_retry_attempts)
        recursion_limit = int(handoff_cfg.work_handoff_recursion_limit)
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            values: dict[str, Any] = {}
            client = None
            try:
                try:
                    values = _read_thread_values(lg_client, thread_id, loop=loop)
                except Exception:
                    logger.debug("Could not read thread state before work handoff for %s", thread_id, exc_info=True)
                client = CapyHomeClient(
                    model_name=requested_model_name,
                    thinking_enabled=True,
                    subagent_enabled=True,
                    plan_mode=False,
                    auto_mode=auto_mode,
                )
                config = client._get_runnable_config(  # noqa: SLF001
                    thread_id,
                    model_name=requested_model_name,
                    thinking_enabled=True,
                    subagent_enabled=True,
                    auto_mode=auto_mode,
                    mode="work",
                    current_turn_text=original_user_request or "",
                    original_user_request=original_user_request or "",
                )
                config["recursion_limit"] = recursion_limit
                config["configurable"].update(
                    {
                        "current_mode": "work",
                        "mode": "work",  # legacy alias; remove after step 8
                        "is_plan_mode": False,  # legacy dual-write; remove after step 8
                        "background_followup": False,
                        "plan_behavior": "work_interactive",
                    }
                )
                clarification_block = ""
                if isinstance(values, dict):
                    plan = values.get("plan")
                    if isinstance(plan, dict):
                        clarification_block = format_clarification_context_for_work(plan)
                handoff_messages = _handoff_context_message(original_user_request, clarification_block)
                invoke_state: dict[str, Any] = {"messages": handoff_messages}
                # Canonical plan.md handoff: if the on-disk plan.md was edited by
                # the user between approval and now, honor those edits by parsing
                # the file and overriding plan + todo_graph in the new run's input.
                invoke_state.update(_load_canonical_plan_overrides(values))
                invoke_client_agent_async(
                    client,
                    invoke_state,
                    config=config,
                    context={
                        "thread_id": thread_id,
                        "current_mode": "work",
                        "mode": "work",  # legacy alias; remove after step 8
                        "is_plan_mode": False,  # legacy dual-write; remove after step 8
                        "background_followup": False,
                        "plan_behavior": "work_interactive",
                        "model_name": requested_model_name,
                        "auto_mode": auto_mode,
                        "current_turn_text": original_user_request or "",
                        "original_user_request": original_user_request or "",
                    },
                )
                try:
                    latest_values = _read_thread_values(lg_client, thread_id, loop=loop)
                except Exception:
                    latest_values = values
                plan = latest_values.get("plan") if isinstance(latest_values, dict) else None
                if isinstance(plan, dict):
                    # CONTRACT (see code-review #15): payload contains ONLY the
                    # top-level `plan` key. The title-handoff writer touches
                    # ONLY `title`. Disjoint keys → no collision. plan.md is
                    # rendered from `plan["title"]` (planner-set), not the
                    # top-level `state["title"]`, so the title handoff has no
                    # influence on plan.md output.
                    try:
                        result = lg_client.threads.update_state(thread_id, {"plan": mark_handoff_succeeded(plan)})
                        _run_awaitable_in_worker(result, loop)
                    except Exception:
                        logger.exception("Failed to persist successful work handoff for thread %s", thread_id)
                return
            except Exception as exc:
                last_error = exc
                logger.exception(
                    "Automatic work-mode handoff attempt %s/%s failed for thread %s",
                    attempt,
                    max_attempts,
                    thread_id,
                )
                if attempt < max_attempts:
                    time.sleep(0.8)
                    continue
                break
            finally:
                if client is not None:
                    close = getattr(client, "close", None)
                    if callable(close):
                        close()

        if last_error is not None:
            exc = last_error
            logger.exception("Automatic work-mode handoff failed for thread %s", thread_id)
            try:
                values = _read_thread_values(lg_client, thread_id, loop=loop)
            except Exception:
                values = {}
            plan = values.get("plan") if isinstance(values, dict) else None
            if isinstance(plan, dict):
                try:
                    result = lg_client.threads.update_state(
                        thread_id,
                        {"plan": mark_handoff_failed(plan, error=str(exc))},
                    )
                    _run_awaitable_in_worker(result, loop)
                except Exception:
                    logger.exception("Failed to persist failed work handoff for thread %s", thread_id)
    finally:
        loop.close()


def spawn_work_mode_handoff(
    *,
    thread_id: str,
    requested_model_name: str | None,
    auto_mode: bool,
    original_user_request: str | None = None,
    delay_seconds: float = 1.0,
    thread_name_suffix: str = "",
) -> None:
    """Spawn a daemon that starts a fresh Work Mode run on the same thread."""

    with _HANDOFF_GUARD:
        if _in_flight_handoff_present(thread_id):
            logger.info("Skipping duplicate work-mode handoff for thread %s", thread_id)
            return
        _IN_FLIGHT_HANDOFFS[thread_id] = time.monotonic()

    def _run_with_cleanup() -> None:
        try:
            _run_work_mode_handoff(
                thread_id=thread_id,
                requested_model_name=requested_model_name,
                auto_mode=auto_mode,
                original_user_request=original_user_request,
                delay_seconds=delay_seconds,
            )
        finally:
            with _HANDOFF_GUARD:
                _IN_FLIGHT_HANDOFFS.pop(thread_id, None)

    safe_thread_id = str(thread_id or "")[:8]
    submitted = submit_background_task(
        f"work-mode-handoff-{safe_thread_id}{thread_name_suffix}",
        _run_with_cleanup,
    )
    if not submitted:
        with _HANDOFF_GUARD:
            _IN_FLIGHT_HANDOFFS.pop(thread_id, None)
        logger.warning("Could not submit work-mode handoff for thread %s; background executor is full", thread_id)
