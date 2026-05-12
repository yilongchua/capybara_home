"""Bound the wall-clock duration of a single LLM call.

Without this, a slow local model (or a model that gets stuck mid-completion)
keeps the run pinned in `model_call_start` indefinitely. We saw this in
run-c0425b71bd, where the 4th model call took 232s and the agent's next
tool_call (write_todos) was never able to finish before the run was killed
hours later. This middleware caps each model call by stage and converts a
hang into a structured failure that the agent loop can react to.

Trajectory event: `model_call_timeout`. Run-time event (drained by
TrajectoryMiddleware on the next `before/after_model`):
    {"source": "model_timeout_middleware", "stage": "...", "timeout_s": N}

On timeout we replace the model call result with a single AIMessage carrying
a system-warning style content. The agent picks that up in its next iteration
and ProgressGuard can terminate the run if the loop fails to make progress.
"""

from __future__ import annotations

import asyncio
import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.routing_config import RoutingTimeoutsConfig, get_routing_config

logger = logging.getLogger(__name__)

# Detected by TrajectoryMiddleware to emit a first-class `model_call_timeout`
# event. Keep this string stable — auditing tools and tests grep for it.
TIMEOUT_MESSAGE_FINGERPRINT = "[model_timeout]"


def _stage_for(request: ModelRequest) -> str | None:
    """Pick a per-call stage label so timeouts can scale with the work involved.

    Resolution order:
    1. Explicit `runtime.context["stage"]` — set by callers that know which stage
       they're in (e.g. PlannerMiddleware when it gains a wrap-style hook).
    2. Heuristic from request.messages — synthesis cycles (last message is a
       tool result) need a longer budget than a first-pass generator turn,
       because the model has just received tool output to digest.

    Falls back to None (uses `default`) when no signal is available.
    """
    runtime = getattr(request, "runtime", None)
    context = getattr(runtime, "context", None) or {}
    if isinstance(context, dict):
        stage = context.get("stage")
        if isinstance(stage, str) and stage:
            return stage

    messages = getattr(request, "messages", None) or []
    if not messages:
        return "generator"
    last = messages[-1]
    last_type = getattr(last, "type", None) or getattr(last, "role", None)
    if last_type == "tool":
        return "synthesis"
    if last_type == "human":
        # Fresh user prompt — first-pass reasoning before any tools have run.
        ai_count = sum(1 for m in messages if (getattr(m, "type", None) or getattr(m, "role", None)) == "ai")
        return "generator" if ai_count == 0 else "synthesis"
    return "generator"


def _last_tool_payload_chars(request: ModelRequest) -> int:
    """Approximate size of the most recent ToolMessage block in the request."""
    messages = getattr(request, "messages", None) or []
    total = 0
    for msg in reversed(messages):
        msg_type = getattr(msg, "type", None) or getattr(msg, "role", None)
        if msg_type != "tool":
            break
        content = getattr(msg, "content", "") or ""
        if isinstance(content, str):
            total += len(content)
    return total


def _timeout_message(stage: str | None, timeout_s: int, request: ModelRequest | None = None) -> AIMessage:
    label = stage or "default"
    # Tailor the recovery hint to what the model was likely doing. A plain
    # "stop or retry briefly" prompt (the original message) was shown by
    # thread-cd90decb to dead-end the run because synthesis had no obvious
    # next step. Steering toward write_file / smaller chunks gives the model
    # a concrete escape hatch.
    if stage == "synthesis":
        tool_chars = _last_tool_payload_chars(request) if request is not None else 0
        hint = (
            "The previous tool batch returned ~"
            f"{tool_chars} characters of content that could not be summarized in one pass. "
            "Recover by writing the answer incrementally: call `write_file` to "
            "save partial findings to `/mnt/user-data/outputs/<topic>.md`, then "
            "process the next chunk in your next turn. Do not re-issue the same "
            "tool calls."
        )
    elif stage == "generator":
        hint = "The first reasoning pass did not complete in time. Reply with a single concrete tool call (smallest viable next step) or `ask_clarification` if the request is ambiguous. Do not retry the same prompt."
    elif stage == "planner":
        hint = "Planner timed out. Skip planning and proceed with a minimal single-tool first action (e.g. one web_search), or stop."
    else:
        hint = "Reply with a brief next step (or stop) — do not retry the same prompt."
    return AIMessage(content=(f"{TIMEOUT_MESSAGE_FINGERPRINT}\n<system_warning>\nModel call exceeded the {label} stage timeout of {timeout_s}s and was cancelled.\n{hint}\n</system_warning>"))


class ModelTimeoutMiddleware(AgentMiddleware[AgentState]):
    """Cap wall-clock duration of LLM invocations per stage."""

    def __init__(self, config: RoutingTimeoutsConfig | None = None):
        super().__init__()
        self._config = config or get_routing_config().timeouts

    @override
    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        if not self._config.enabled:
            return await handler(request)

        stage = _stage_for(request)
        timeout_s = self._config.for_stage(stage)
        try:
            return await asyncio.wait_for(handler(request), timeout=timeout_s)
        except TimeoutError:
            append_runtime_event(
                request.runtime,
                {
                    "source": "model_timeout_middleware",
                    "stage": stage or "default",
                    "timeout_s": timeout_s,
                },
            )
            logger.warning("Model call timed out after %ss (stage=%s)", timeout_s, stage)
            return ModelResponse(result=[_timeout_message(stage, timeout_s, request)])

    @override
    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        # Sync path is not used by langgraph-server-async paths but is required
        # by the middleware contract for embedded clients. Falls back to the
        # raw handler — sync timeouts cannot be enforced cooperatively without
        # threading, which is out of scope here.
        return handler(request)

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        if not self._config.enabled:
            return await handler(request)

        tool_name = str(request.tool_call.get("name") or "unknown")
        tool_call_id = str(request.tool_call.get("id") or "")
        timeout_s = self._config.for_tool(tool_name)
        try:
            return await asyncio.wait_for(handler(request), timeout=timeout_s)
        except TimeoutError:
            append_runtime_event(
                request.runtime,
                {
                    "source": "tool_timeout_middleware",
                    "tool": tool_name,
                    "tool_call_id": tool_call_id,
                    "timeout_s": timeout_s,
                },
            )
            logger.warning("Tool call %s timed out after %ss (id=%s)", tool_name, timeout_s, tool_call_id)
            return ToolMessage(
                content=(f"{TIMEOUT_MESSAGE_FINGERPRINT}\nTool `{tool_name}` exceeded the {timeout_s}s timeout and was cancelled. Try a different approach or skip this step."),
                tool_call_id=tool_call_id,
                name=tool_name,
            )

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        # Sync path: pass-through. Tool timeouts are enforced on the async path
        # which is what langgraph-server uses.
        return handler(request)
