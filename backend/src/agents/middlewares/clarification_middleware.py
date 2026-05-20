"""Middleware for intercepting clarification requests and presenting them to the user."""

import logging
from collections.abc import Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.graph import END
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

logger = logging.getLogger(__name__)

_AUTO_MODE_CTX_KEY = "_clarification_auto_mode"


class ClarificationMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    auto_mode: bool


class ClarificationMiddleware(AgentMiddleware[ClarificationMiddlewareState]):
    """Intercepts clarification tool calls and interrupts execution to present questions to the user.

    When the model calls the `ask_clarification` tool, this middleware:
    1. Intercepts the tool call before execution
    2. Extracts the clarification question and metadata
    3. Formats a user-friendly message
    4. Returns a Command that interrupts execution and presents the question
    5. Waits for user response before continuing

    This replaces the tool-based approach where clarification continued the conversation flow.
    """

    state_schema = ClarificationMiddlewareState

    @override
    def before_model(self, state: ClarificationMiddlewareState, runtime: Runtime) -> dict | None:
        """Cache auto_mode flag in runtime context so wrap_tool_call can read it.

        Reads from config.configurable first (embedded-client/frontend config),
        then runtime.context (React stream path), falls back to state.auto_mode
        (persisted value), then defaults to False.
        """
        runtime_config = getattr(runtime, "config", None)
        configurable = (runtime_config or {}).get("configurable") or {} if runtime_config else {}
        ctx = getattr(runtime, "context", None)
        auto_mode = bool(
            configurable.get(
                "auto_mode",
                (ctx or {}).get("auto_mode", state.get("auto_mode", False)),
            )
        )
        if ctx is not None:
            ctx[_AUTO_MODE_CTX_KEY] = auto_mode
        return None

    @override
    async def abefore_model(self, state: ClarificationMiddlewareState, runtime: Runtime) -> dict | None:
        return self.before_model(state, runtime)

    def _format_clarification_message(self, args: dict) -> str:
        """Format the clarification arguments into a user-friendly message.

        Args:
            args: The tool call arguments containing clarification details

        Returns:
            Formatted message string
        """
        question = args.get("question", "")
        clarification_type = args.get("clarification_type", "missing_info")
        context = args.get("context")
        options = args.get("options", [])

        # Type-specific icons
        type_icons = {
            "missing_info": "❓",
            "ambiguous_requirement": "🤔",
            "approach_choice": "🔀",
            "risk_confirmation": "⚠️",
            "suggestion": "💡",
        }

        icon = type_icons.get(clarification_type, "❓")

        # Build the message naturally
        message_parts = []

        # Add icon and question together for a more natural flow
        if context:
            # If there's context, present it first as background
            message_parts.append(f"{icon} {context}")
            message_parts.append(f"\n{question}")
        else:
            # Just the question with icon
            message_parts.append(f"{icon} {question}")

        # Add options in a cleaner format
        if options and len(options) > 0:
            message_parts.append("")  # blank line for spacing
            for i, option in enumerate(options, 1):
                if isinstance(option, dict):
                    label = str(option.get("label") or "").strip()
                    description = str(option.get("description") or "").strip()
                    recommended = bool(option.get("recommended"))
                    rendered_label = label or str(option).strip()
                    prefix = " (Recommended)" if recommended else ""
                    if description:
                        message_parts.append(f"  {i}. {rendered_label}{prefix} — {description}")
                    else:
                        message_parts.append(f"  {i}. {rendered_label}{prefix}")
                else:
                    message_parts.append(f"  {i}. {option}")

        return "\n".join(message_parts)

    def _get_recommended_label(self, args: dict) -> str | None:
        """Return the label of the first recommended option, or None."""
        for option in args.get("options") or []:
            if isinstance(option, dict) and option.get("recommended"):
                return str(option.get("label") or "")
        options = args.get("options") or []
        if options and isinstance(options[0], dict):
            return str(options[0].get("label") or "")
        return None

    def _handle_clarification(self, request: ToolCallRequest) -> Command:
        """Handle clarification request.

        In normal mode: interrupts execution and surfaces the question to the user.
        In auto_mode: injects the recommended answer and continues without interrupting.
        """
        args = request.tool_call.get("args", {})
        question = args.get("question", "")
        tool_call_id = request.tool_call.get("id", "")

        # Check auto_mode flag from runtime context (set in before_model)
        context = getattr(request.runtime, "context", None) or {}
        auto_mode = bool(context.get(_AUTO_MODE_CTX_KEY, False))

        if auto_mode:
            recommended = self._get_recommended_label(args)
            if recommended:
                logger.info("Auto mode: auto-selecting '%s' for clarification: %s", recommended, question)
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                content=f"[Auto Mode] Selected: {recommended}",
                                tool_call_id=tool_call_id,
                                name="ask_clarification",
                            )
                        ]
                    }
                )
            logger.info("Auto mode: no recommended option found for clarification '%s'; interrupting", question)

        logger.info("Intercepted clarification request: %s", question)
        formatted_message = self._format_clarification_message(args)

        tool_message = ToolMessage(
            content=formatted_message,
            tool_call_id=tool_call_id,
            name="ask_clarification",
        )

        # Note: We don't add an extra AIMessage here - the frontend will detect
        # and display ask_clarification tool messages directly
        return Command(
            update={"messages": [tool_message]},
            goto=END,
        )

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept ask_clarification tool calls and interrupt execution (sync version).

        Args:
            request: Tool call request
            handler: Original tool execution handler

        Returns:
            Command that interrupts execution with the formatted clarification message
        """
        # Check if this is an ask_clarification tool call
        if request.tool_call.get("name") != "ask_clarification":
            # Not a clarification call, execute normally
            return handler(request)

        return self._handle_clarification(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept ask_clarification tool calls and interrupt execution (async version).

        Args:
            request: Tool call request
            handler: Original tool execution handler (async)

        Returns:
            Command that interrupts execution with the formatted clarification message
        """
        # Check if this is an ask_clarification tool call
        if request.tool_call.get("name") != "ask_clarification":
            # Not a clarification call, execute normally
            return await handler(request)

        return self._handle_clarification(request)
