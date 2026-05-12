"""Inject queued one-shot steering intent from thread state into model turns."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict, override
from uuid import uuid4

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.agents.steering_queue_store import claim_next_steering_intent


class SteeringIntent(TypedDict, total=False):
    intent_id: str
    message: str
    created_at: str


class SteeringMiddlewareState(AgentState):
    steering_context: NotRequired[str | None]
    pending_steering_intents: NotRequired[list[SteeringIntent] | None]


def _normalize_intents(raw: Any) -> list[SteeringIntent]:
    if not isinstance(raw, list):
        return []

    normalized: list[SteeringIntent] = []
    for candidate in raw:
        if not isinstance(candidate, dict):
            continue
        message = candidate.get("message")
        if not isinstance(message, str):
            continue
        stripped = message.strip()
        if not stripped:
            continue
        intent_id = candidate.get("intent_id")
        if not isinstance(intent_id, str) or not intent_id.strip():
            intent_id = str(uuid4())
        created_at = candidate.get("created_at")
        if not isinstance(created_at, str) or not created_at.strip():
            created_at = datetime.now(UTC).isoformat()
        normalized.append(
            {
                "intent_id": intent_id.strip(),
                "message": stripped,
                "created_at": created_at.strip(),
            }
        )
    return normalized


def _legacy_intent(raw: Any) -> SteeringIntent | None:
    if not isinstance(raw, str):
        return None
    message = raw.strip()
    if not message:
        return None
    return {
        "intent_id": f"legacy-{uuid4()}",
        "message": message,
        "created_at": datetime.now(UTC).isoformat(),
    }


class SteeringMiddleware(AgentMiddleware[SteeringMiddlewareState]):
    """Inject one pending steering intent per model turn and consume only that intent."""

    state_schema = SteeringMiddlewareState

    @override
    def before_model(self, state: SteeringMiddlewareState, runtime: Runtime) -> dict | None:
        context = getattr(runtime, "context", None) or {}
        thread_id = str(context.get("thread_id") or "").strip()
        queued_intent = claim_next_steering_intent(thread_id) if thread_id else None
        if queued_intent is not None:
            reminder = HumanMessage(
                name="steering_reminder",
                content=(
                    "<system_reminder>\n"
                    "External steering context for this turn:\n"
                    f"{queued_intent['message']}\n"
                    "</system_reminder>"
                )
            )
            return {
                "messages": [reminder],
                "steering_context": None,
            }

        legacy_raw = state.get("steering_context")
        pending = _normalize_intents(state.get("pending_steering_intents"))
        legacy = _legacy_intent(legacy_raw)
        if legacy is not None:
            pending.append(legacy)

        if not pending:
            if isinstance(legacy_raw, str):
                return {"steering_context": None, "pending_steering_intents": []}
            return None

        current = pending[0]
        remaining = pending[1:]
        reminder = HumanMessage(
            name="steering_reminder",
            content=(
                "<system_reminder>\n"
                "External steering context for this turn:\n"
                f"{current['message']}\n"
                "</system_reminder>"
            )
        )
        return {
            "messages": [reminder],
            "steering_context": None,
            "pending_steering_intents": remaining,
        }

    @override
    async def abefore_model(self, state: SteeringMiddlewareState, runtime: Runtime) -> dict | None:
        return self.before_model(state, runtime)
