"""Middleware that generates follow-up questions after the model produces a final response.

Fires exclusively in ``after_model`` — only when the last AIMessage contains no tool
calls (i.e. the model is returning a visible answer to the user rather than calling
a tool).  The generated questions are stored in ``state["suggested_questions"]`` so
the frontend can surface them as quick-reply chips or a "you might also ask" panel.

Disabled by default; enable via ``question_generation.enabled: true`` in config.yaml.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from src.config.question_generation_config import get_question_generation_config
from src.models import create_chat_model

logger = logging.getLogger(__name__)


class QuestionGenerationState(AgentState):
    suggested_questions: NotRequired[list[str] | None]


def _last_ai_message(messages: list[Any]) -> AIMessage | None:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return msg
    return None


def _is_final_response(msg: AIMessage) -> bool:
    """Return True when the AIMessage is a user-visible final answer (no tool calls)."""
    return not bool(getattr(msg, "tool_calls", None))


def _extract_text(msg: AIMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts)
    return str(content)


def _last_user_message(messages: list[Any]) -> str:
    from langchain_core.messages import HumanMessage

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) and not getattr(msg, "name", None):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                return " ".join(parts)
    return ""


def _parse_questions(raw: str) -> list[str]:
    """Extract numbered lines from LLM output, stripping the leading number+dot."""
    questions: list[str] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip leading "1." / "1)" / "-" markers
        cleaned = re.sub(r"^[\d]+[.)]\s*", "", line).strip()
        cleaned = re.sub(r"^[-*]\s*", "", cleaned).strip()
        if cleaned:
            questions.append(cleaned)
    return questions


class QuestionGenerationMiddleware(AgentMiddleware[QuestionGenerationState]):
    """Generate follow-up questions after each final model response.

    Only fires when ``question_generation.enabled = true`` in config.yaml.
    Results are stored in ``state["suggested_questions"]``.
    """

    state_schema = QuestionGenerationState

    def _build_prompt(self, state: QuestionGenerationState) -> str | None:
        cfg = get_question_generation_config()
        messages = state.get("messages") or []
        last_ai = _last_ai_message(messages)
        if last_ai is None or not _is_final_response(last_ai):
            return None

        assistant_response = _extract_text(last_ai)[: cfg.max_response_chars]
        user_message = _last_user_message(messages)[: cfg.max_response_chars]

        return cfg.prompt_template.format(
            count=cfg.count,
            user_message=user_message,
            assistant_response=assistant_response,
        )

    def _generate_sync(self, prompt: str) -> list[str]:
        cfg = get_question_generation_config()
        model = create_chat_model(name=cfg.model_name, thinking_enabled=False)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                if hasattr(model, "invoke"):
                    response = pool.submit(model.invoke, prompt).result(timeout=cfg.timeout_seconds)
                else:
                    response = pool.submit(asyncio.run, model.ainvoke(prompt)).result(timeout=cfg.timeout_seconds)
            return _parse_questions(str(response.content))[: cfg.count]
        except Exception:
            logger.exception("question_generation: sync generation failed")
            return []

    async def _generate_async(self, prompt: str) -> list[str]:
        cfg = get_question_generation_config()
        model = create_chat_model(name=cfg.model_name, thinking_enabled=False)
        try:
            response = await asyncio.wait_for(model.ainvoke(prompt), timeout=cfg.timeout_seconds)
            return _parse_questions(str(response.content))[: cfg.count]
        except Exception:
            logger.exception("question_generation: async generation failed")
            return []

    @override
    def after_model(
        self,
        state: QuestionGenerationState,
        runtime: Runtime,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        if not get_question_generation_config().enabled:
            return None
        prompt = self._build_prompt(state)
        if prompt is None:
            return None
        questions = self._generate_sync(prompt)
        if not questions:
            return None
        logger.debug("question_generation: generated %d questions", len(questions))
        return {"suggested_questions": questions}

    @override
    async def aafter_model(
        self,
        state: QuestionGenerationState,
        runtime: Runtime,  # noqa: ARG002
    ) -> dict[str, Any] | None:
        if not get_question_generation_config().enabled:
            return None
        prompt = self._build_prompt(state)
        if prompt is None:
            return None
        questions = await self._generate_async(prompt)
        if not questions:
            return None
        logger.debug("question_generation: generated %d questions", len(questions))
        return {"suggested_questions": questions}
