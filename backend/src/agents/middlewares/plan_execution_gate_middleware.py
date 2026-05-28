"""Gate execution tools while plan is still draft or awaiting clarifications.

Primary defense: ``PhaseToolFilterMiddleware`` hides execution tools from the
LLM's tool catalog while a plan is in draft, so the LLM never sees them. This
middleware is the *backstop*: if a custom agent re-exposes those tools, or
if the phase filter is misconfigured, the runtime block here still prevents
content-gathering before plan approval.

For the search tools (``web_search`` etc.), when the runtime block fires we
also invoke an LLM classifier — using the chat-selected model — to distinguish
*scope-clarifying* from *content-gathering* queries. Scope queries are let
through; content queries are blocked with a clear message.
"""

from __future__ import annotations

import logging
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.agents.middlewares.message_selection import extract_text, original_user_prompt
from src.agents.middlewares.runtime_events import append_runtime_event
from src.models import create_chat_model, resolve_model_name

logger = logging.getLogger(__name__)

_ALLOWED_WHEN_DRAFT = {
    "ask_user_for_clarification",
    "write_todos",
    "recall",
}

_ALLOWED_IN_PLAN_MODE = _ALLOWED_WHEN_DRAFT | {
    "bash",
    "ls",
    "read_file",
    "view_image",
}

# Tools that should NEVER run while plan is draft unless the classifier
# determines they are scope-clarifying. The classifier acts as a backstop in
# case PhaseToolFilterMiddleware is misconfigured and re-exposes them.
_SCOPE_GATED_TOOLS: frozenset[str] = frozenset(
    {
        "web_search",
        "query_knowledge_vault",
        "search_internal_documents",
    }
)

_BASH_MUTATION_TOKENS = (
    ">",
    ">>",
    "tee ",
    " rm ",
    " mv ",
    " cp ",
    " chmod ",
    " chown ",
    " sed -i",
    " perl -pi",
    " git apply",
    " git commit",
    " git add",
    " touch ",
    " mkdir ",
    " install ",
)


def _is_read_only_tool(tool_name: str) -> bool:
    return tool_name.startswith("read_") or tool_name.startswith("list_") or tool_name.startswith("get_")


def _is_plan_mode(runtime: Any) -> bool:
    context = getattr(runtime, "context", None) or {}
    raw = context.get("current_mode") or context.get("mode") or ("plan" if context.get("is_plan_mode") else "")
    return str(raw).strip().lower() == "plan"


def _is_plan_safe_bash(command: str) -> bool:
    lowered = f" {command.lower()} "
    return not any(token in lowered for token in _BASH_MUTATION_TOKENS)


class PlanExecutionGateState(AgentState):
    plan: dict[str, Any] | None


def _normalize_plan_status(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"draft", "approved", "executing", "completed"}:
        return value
    return "draft"


_CLASSIFIER_PROMPT_TEMPLATE = (
    "User asked: {user_prompt}\n"
    "Agent is in Plan Mode (plan not yet approved) and wants to call "
    "{tool_name} with: {query!r}.\n"
    "Is this query (a) scope-narrowing/clarifying — e.g., asking about "
    "taxonomy, definitions, available sources, or which sub-topic to focus "
    "on — or (b) content-gathering for the research itself, restating the "
    "user's topic as keywords?\n"
    'Respond with one word only: "scope" or "content".'
)


class PlanExecutionGateMiddleware(AgentMiddleware[PlanExecutionGateState]):
    """Prevents execution tool usage until draft plans are explicitly approved.

    Acts as a runtime backstop for ``PhaseToolFilterMiddleware``: if a custom
    agent reintroduces the hidden execution tools, this layer still blocks them
    while a plan is in draft. For scope-gated search tools, an LLM classifier
    (the chat-selected model) decides scope vs. content per call so genuine
    scope discovery is not punished.
    """

    state_schema = PlanExecutionGateState

    def __init__(self, requested_model: str | None = None) -> None:
        super().__init__()
        # The chat-selected model the user picked in the UI; honored
        # unconditionally per the single-model invariant.
        self._requested_model = requested_model
        # Cache scope/content judgments per tool_call_id so sync + async
        # wrappers don't double-judge the same call.
        self._classifier_cache: dict[str, str] = {}

    def _build_block_command(self, request: ToolCallRequest, message: str) -> Command:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=message,
                        tool_call_id=request.tool_call.get("id", ""),
                        name=request.tool_call.get("name", "tool"),
                    )
                ]
            },
        )

    def _extract_latest_user_prompt(self, state: dict[str, Any]) -> str:
        messages = state.get("messages") if isinstance(state, dict) else None
        if not isinstance(messages, list):
            return ""
        prompt = original_user_prompt(messages)
        if prompt and prompt.strip():
            return prompt.strip()
        for msg in reversed(messages):
            if getattr(msg, "type", None) == "human":
                return extract_text(getattr(msg, "content", "")).strip()
        return ""

    def _classify_scope_intent(
        self,
        *,
        request: ToolCallRequest,
        user_prompt: str,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> str:
        """Classify a search query as ``"scope"`` or ``"content"``.

        Fail-closed: any exception returns ``"content"`` so the gate blocks
        the call. An observability event is emitted so the failure is
        actionable.
        """
        call_id = str(request.tool_call.get("id") or "")
        cached = self._classifier_cache.get(call_id)
        if cached is not None:
            return cached
        query = str(tool_args.get("query") or "").strip()
        try:
            model_name = resolve_model_name(self._requested_model)
            model = create_chat_model(name=model_name, thinking_enabled=False)
            content = _CLASSIFIER_PROMPT_TEMPLATE.format(
                user_prompt=user_prompt or "(no prior user prompt available)",
                tool_name=tool_name,
                query=query,
            )
            response = model.invoke([HumanMessage(content=content)])
            raw = response.content if hasattr(response, "content") else str(response)
            text = (raw[0]["text"] if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "text" in raw[0] else str(raw))
            verdict = "scope" if "scope" in str(text).lower() else "content"
        except Exception as exc:
            logger.warning("scope classifier failed for tool=%s: %s", tool_name, exc)
            append_runtime_event(
                request.runtime,
                {
                    "source": "plan_execution_gate",
                    "decision": "scope_classifier_failed",
                    "tool": tool_name,
                    "error": str(exc),
                },
            )
            verdict = "content"
        if call_id:
            self._classifier_cache[call_id] = verdict
        append_runtime_event(
            request.runtime,
            {
                "source": "plan_execution_gate",
                "decision": "scope_classifier",
                "tool": tool_name,
                "verdict": verdict,
                "query_preview": query[:120],
            },
        )
        return verdict

    def _maybe_block(self, request: ToolCallRequest) -> Command | None:
        state = request.state if isinstance(getattr(request, "state", None), dict) else {}
        if not state:
            runtime_obj = getattr(request, "runtime", None)
            state = getattr(runtime_obj, "state", {}) if isinstance(getattr(runtime_obj, "state", None), dict) else {}
        plan = state.get("plan") if isinstance(state, dict) else None
        tool_name = str(request.tool_call.get("name") or "")
        tool_args = request.tool_call.get("args") or {}
        in_plan_mode = _is_plan_mode(request.runtime)

        has_plan = isinstance(plan, dict)
        plan_status = _normalize_plan_status(plan.get("status")) if has_plan else "draft"
        # Scope-vs-content classification is a Plan-Mode-only concern. In Work
        # Mode the user has committed to an execution intent; if a draft plan
        # still exists, the draft-plan branch below already blocks execution
        # tools with a clearer "approve the plan" message, so running the
        # classifier first would only waste a model call.
        if tool_name in _SCOPE_GATED_TOOLS and in_plan_mode:
            user_prompt = self._extract_latest_user_prompt(state)
            verdict = self._classify_scope_intent(
                request=request,
                user_prompt=user_prompt,
                tool_name=tool_name,
                tool_args=tool_args,
            )
            if verdict == "scope":
                return None
            return self._build_block_command(
                request,
                (
                    "[plan_gate] Plan Mode allows scope-clarifying search only. "
                    f"`{tool_name}` looks like content gathering for execution; refine "
                    "plan.md or answer the pending clarification before approval, or "
                    "narrow the query to scope discovery (taxonomy, definitions, sources). "
                    "(This block is a backstop — the phase filter should normally have "
                    "hidden this tool from the catalog.)"
                ),
            )

        if in_plan_mode:
            if tool_name == "bash":
                command = str(tool_args.get("command") or "")
                if _is_plan_safe_bash(command):
                    return None
                return self._build_block_command(
                    request,
                    (
                        "[plan_gate] Plan Mode allows bash only for read-only investigation. "
                        "Use inspection commands such as rg, ls, cat, sed -n, pytest, or git status; do not mutate files or state."
                    ),
                )
            if tool_name in _ALLOWED_IN_PLAN_MODE or _is_read_only_tool(tool_name):
                return None
            return self._build_block_command(
                request,
                (
                    "[plan_gate] You are still in Plan Mode. Do not execute the work yet. "
                    "Refine `plan.md`, update todos, gather read-only scope context, or ask clarification instead."
                ),
            )

        if not isinstance(plan, dict):
            return None

        if plan_status != "draft":
            return None

        clarification_pending = bool(plan.get("clarification_pending"))

        if clarification_pending and tool_name != "ask_user_for_clarification":
            question = str(plan.get("clarification_question") or "Please answer the pending clarification before execution.")
            return self._build_block_command(
                request,
                (
                    "[plan_gate] Clarification is required before plan execution. "
                    "Call `ask_user_for_clarification` first.\n"
                    f"Pending question: {question}"
                ),
            )

        if tool_name in _ALLOWED_WHEN_DRAFT or _is_read_only_tool(tool_name):
            return None

        plan_id = str(plan.get("plan_id") or "").strip()
        plan_hint = f" Plan ID: {plan_id}." if plan_id else ""
        return self._build_block_command(
            request,
            (
                "[plan_gate] Plan is still draft. Execution tools are blocked until explicit plan approval "
                f"via the Execute Plan action in the UI (or enable auto-mode).{plan_hint} "
                "Do not substitute training-data answers for blocked research tools."
            ),
        )

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        blocked = self._maybe_block(request)
        if blocked is not None:
            return blocked
        return handler(request)

    @override
    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        blocked = self._maybe_block(request)
        if blocked is not None:
            return blocked
        return await handler(request)
