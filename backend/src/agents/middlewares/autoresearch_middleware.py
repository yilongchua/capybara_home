"""Middleware to turn autoresearch chat commands into scheduled jobs."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from src.control_plane.service import get_control_plane_service

_AUTORESEARCH_WITH_TOPIC_RE = re.compile(
    r"^\s*autoresearch\s*-\s*(?P<topic>.+?)\s*$",
    re.IGNORECASE,
)
_AUTORESEARCH_TRIGGER_RE = re.compile(r"^\s*autoresearch\s*$", re.IGNORECASE)


def _extract_last_human_text(messages: list) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                text_parts = [str(part.get("text", "")) for part in content if isinstance(part, dict)]
                return " ".join(text_parts).strip()
            return str(content).strip()
    return ""


def _message_text(msg: object) -> str:
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts = [str(part.get("text", "")) for part in content if isinstance(part, dict)]
        return " ".join(text_parts).strip()
    return str(content).strip()


def _is_autoresearch_command(text: str) -> bool:
    normalized = text.strip()
    return bool(_AUTORESEARCH_TRIGGER_RE.match(normalized) or _AUTORESEARCH_WITH_TOPIC_RE.match(normalized))


def _collect_recent_context(messages: list, *, max_messages: int = 8) -> list[str]:
    lines: list[str] = []
    for msg in messages:
        text = _message_text(msg)
        if not text or _is_autoresearch_command(text):
            continue
        role = "assistant" if isinstance(msg, AIMessage) else "user"
        lines.append(f"{role}: {text}")
    if len(lines) <= max_messages:
        return lines
    return lines[-max_messages:]


def _derive_topic(messages: list, explicit_topic: str | None) -> str:
    topic = (explicit_topic or "").strip()
    if topic:
        return topic

    for msg in reversed(messages):
        if not isinstance(msg, HumanMessage):
            continue
        text = _message_text(msg)
        if not text or _is_autoresearch_command(text):
            continue
        line = re.split(r"[\r\n]+", text, maxsplit=1)[0].strip()
        if line:
            return line[:180].rstrip(" ,.;:")
    return "current workspace research focus"


def _derive_endpoint_goal(topic: str, context_lines: list[str]) -> str:
    context_summary = " ".join(context_lines)
    if len(context_summary) > 600:
        context_summary = f"{context_summary[:597].rstrip()}..."
    base = (
        f"Deliver a complete, evidence-backed research brief for {topic}, "
        "including key facts, current developments, risks, and actionable next steps."
    )
    if context_summary:
        return f"{base} Align conclusions with this chat context: {context_summary}"
    return base


class AutoresearchMiddleware(AgentMiddleware[AgentState]):
    """Intercepts autoresearch commands and creates scheduled vault autoresearch jobs."""

    def __init__(self) -> None:
        super().__init__()
        # Set to True when wrap_model_call handles an autoresearch command so
        # after_agent skips the redundant record_workspace_activity call.
        self._autoresearch_triggered: bool = False

    def _handle_autoresearch(
        self,
        *,
        request: ModelRequest,
        explicit_topic: str | None = None,
    ) -> ModelResponse:
        service = get_control_plane_service()
        runtime = getattr(request, "runtime", None)
        thread_id = (getattr(runtime, "context", None) or {}).get("thread_id") if runtime else None
        messages = list(getattr(request, "messages", []))
        topic = _derive_topic(messages, explicit_topic)
        context_lines = _collect_recent_context(messages)
        endpoint_goal = _derive_endpoint_goal(topic, context_lines)

        # Record as activity so the inactivity guard does not immediately pause the new job.
        service.record_workspace_activity(thread_id=thread_id, message=f"autoresearch - {topic}")

        template_id = "knowledge-vault-autoresearch-loop"
        templates = {tmpl.id for tmpl in service.list_templates()}
        if template_id not in templates:
            message = (
                "Autoresearch is unavailable because the knowledge vault templates are disabled. "
                "Set `knowledge_vault.enabled: true` in config and restart CapyHome."
            )
            return ModelResponse(result=[AIMessage(content=message)])

        try:
            result = service.start_autoresearch_objective(
                topic=topic,
                endpoint_goal=endpoint_goal,
                thread_id=thread_id,
                bootstrap=True,
                summary=f"Autoresearch bootstrap: {topic}",
            )
            objective = result["objective"]
            run = result["bootstrap_run"]
        except Exception as exc:
            return ModelResponse(
                result=[
                    AIMessage(
                        content=(
                            "Autoresearch command was detected, but scheduling failed.\n\n"
                            f"Reason: {exc}"
                        )
                    )
                ]
            )

        response = (
            f"Autoresearch scheduled for `{topic}`.\n\n"
            f"- Daily schedule: `{result['scheduled_time']}`\n"
            f"- Scheduler job id: `{objective.scheduler_job_id or '-'}`\n"
            f"- Bootstrap run id: `{run.id if run is not None else '-'}`\n\n"
            f"- Objective id: `{objective.objective_id}`\n\n"
            "It will pause itself if there is no new workspace activity for 24 hours."
        )
        return ModelResponse(result=[AIMessage(content=response)])

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        # Skip if wrap_model_call already recorded activity for this autoresearch
        # command — _handle_autoresearch calls record_workspace_activity itself to
        # prevent the inactivity guard from pausing the newly created job before it
        # even runs. Recording it again here would be a duplicate write.
        if self._autoresearch_triggered:
            return None

        thread_id = (getattr(runtime, "context", None) or {}).get("thread_id")
        messages = state.get("messages", [])
        text = _extract_last_human_text(messages)
        if not text:
            return None
        # Track general workspace activity for autoresearch inactivity gating.
        get_control_plane_service().record_workspace_activity(thread_id=thread_id, message=text)
        return None

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        self._autoresearch_triggered = False
        text = _extract_last_human_text(request.messages)
        if not text:
            return handler(request)
        match = _AUTORESEARCH_WITH_TOPIC_RE.match(text)
        trigger_only = _AUTORESEARCH_TRIGGER_RE.match(text)
        if not match and not trigger_only:
            return handler(request)
        topic = match.group("topic").strip() if match else None
        self._autoresearch_triggered = True
        return self._handle_autoresearch(request=request, explicit_topic=topic)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        self._autoresearch_triggered = False
        text = _extract_last_human_text(request.messages)
        if not text:
            return await handler(request)
        match = _AUTORESEARCH_WITH_TOPIC_RE.match(text)
        trigger_only = _AUTORESEARCH_TRIGGER_RE.match(text)
        if not match and not trigger_only:
            return await handler(request)
        topic = match.group("topic").strip() if match else None
        self._autoresearch_triggered = True
        return self._handle_autoresearch(request=request, explicit_topic=topic)
