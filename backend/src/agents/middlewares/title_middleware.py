"""Middleware for automatic thread title generation."""

import asyncio
import logging
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config, get_stream_writer
from langgraph.runtime import Runtime

from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.title_config import get_title_config
from src.models import create_chat_model

logger = logging.getLogger(__name__)


def _extract_text(content: Any) -> str:
    """Safely extract a plain string from a LangChain response content.

    LangChain models may return content as a plain string OR as a list of
    content-block dicts (e.g. ``[{"type": "text", "text": "Hello"}]``).
    Using ``str()`` on a list produces a Python repr like ``"[{...}]"`` which
    is not a usable title — this helper normalises both cases.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text") or block.get("content") or ""
                if text and isinstance(text, str):
                    parts.append(text)
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return str(content) if content else ""


class TitleMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    title: NotRequired[str | None]


class TitleMiddleware(AgentMiddleware[TitleMiddlewareState]):
    """Automatically generate a title for the thread after the first user message.

    Flow (async path):
      1. ``aafter_model`` returns the fallback title immediately so the
         LangGraph checkpoint is not blocked.
      2. A background asyncio task calls the LLM to produce the real title.
         When done it:
         a. Writes the real title to ``self._generated_title``.
         b. Pushes a ``title_update`` custom event so the frontend sidebar
            updates without a reload.
      3. ``aafter_agent`` (async; called at the very end of the run, after the
         checkpoint lock is released) awaits the background task (configurable timeout) and
         returns ``{"title": real_title}`` so the correct title is persisted.
         ``after_agent`` (sync fallback) returns whatever was stored by then.

    This avoids the 409 Conflict that would occur if we tried to PATCH
    thread state while the run is still holding the checkpoint lock.
    """

    state_schema = TitleMiddlewareState
    _DREAMY_TITLE_PREFIX = "✨ "

    def __init__(self, model_name: str | None = None):
        super().__init__()
        self._model_name = model_name
        # Per-run state — keyed by run start time to prevent cross-run leakage.
        self._generated_title: str | None = None
        self._title_bg_task: asyncio.Task[None] | None = None

    def _should_generate_title(self, state: TitleMiddlewareState) -> bool:
        config = get_title_config()
        if not config.enabled:
            return False
        if state.get("title"):
            return False
        messages = state.get("messages", [])
        if len(messages) < 2:
            return False

        def _is_real_human(m: Any) -> bool:
            return m.type == "human" and not getattr(m, "name", None)

        user_messages = [m for m in messages if _is_real_human(m)]
        assistant_messages = [m for m in messages if m.type == "ai"]
        return len(user_messages) == 1 and len(assistant_messages) >= 1

    def _prepare_generation(self, state: TitleMiddlewareState) -> tuple[str, str, str, int]:
        config = get_title_config()
        messages = state.get("messages", [])

        def _is_real_human(m: Any) -> bool:
            return m.type == "human" and not getattr(m, "name", None)

        user_msg_content = next((m.content for m in messages if _is_real_human(m)), "")
        assistant_msg_content = next((m.content for m in messages if m.type == "ai"), "")
        user_msg = _extract_text(user_msg_content)
        assistant_msg = _extract_text(assistant_msg_content)
        prompt = config.prompt_template.format(
            max_words=config.max_words,
            user_msg=user_msg[:500],
            assistant_msg=assistant_msg[:500],
        )
        return prompt, user_msg, assistant_msg, config.max_chars

    @staticmethod
    def _preview(value: str, max_chars: int = 220) -> str:
        text = value.strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    @staticmethod
    def _normalize_title(content: str, max_chars: int) -> str:
        title = content.strip().strip('"').strip("'")
        if len(title) > max_chars:
            return title[:max_chars]
        return title

    @staticmethod
    def _fallback_title(user_msg: str, max_chars: int) -> str:
        fallback_chars = min(max_chars, 50)
        if len(user_msg) > fallback_chars:
            return user_msg[:fallback_chars].rstrip() + "..."
        return user_msg if user_msg else "New Conversation"

    @staticmethod
    def _is_dreamy_mode(runtime: Runtime) -> bool:
        context = getattr(runtime, "context", None)
        if not isinstance(context, dict):
            return False
        return bool(context.get("dreamy_mode", False))

    def _format_title(self, title: str, is_dreamy: bool) -> str:
        if not title:
            return title
        if not is_dreamy:
            return title
        if title.startswith(self._DREAMY_TITLE_PREFIX):
            return title
        return f"{self._DREAMY_TITLE_PREFIX}{title}"

    async def _generate_title(self, state: TitleMiddlewareState) -> str | None:
        """Call the LLM and return a normalized title.

        Returns None on LLM timeout or the fallback string on other failures.
        """
        config = get_title_config()
        prompt, user_msg, _, max_chars = self._prepare_generation(state)
        try:
            model = create_chat_model(name=self._model_name, thinking_enabled=False)
            response = await asyncio.wait_for(
                model.ainvoke(prompt),
                timeout=config.generation_timeout_seconds,
            )
            raw = _extract_text(response.content)
            return self._normalize_title(raw, max_chars)
        except TimeoutError:
            logger.debug("Title LLM timed out; keeping fallback title")
            return None
        except Exception as exc:
            logger.debug("Title LLM call failed, using fallback: %s", exc)
            return self._fallback_title(user_msg, config.max_chars)

    @override
    def after_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Sync path: return fallback title immediately — no LLM call."""
        if not self._should_generate_title(state):
            return None
        _, user_msg, _, max_chars = self._prepare_generation(state)
        fallback = self._fallback_title(user_msg, max_chars)
        fallback = self._format_title(fallback, self._is_dreamy_mode(runtime))
        return {"title": fallback}

    @override
    async def aafter_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Async path: checkpoint fallback instantly; generate real title in the background."""
        if not self._should_generate_title(state):
            return None

        # Reset per-run state so a previous run's title doesn't leak into this one.
        self._generated_title = None
        self._title_bg_task = None

        prompt, user_msg, _, max_chars = self._prepare_generation(state)
        is_dreamy = self._is_dreamy_mode(runtime)
        fallback = self._fallback_title(user_msg, max_chars)
        fallback = self._format_title(fallback, is_dreamy)

        # Capture context-bound objects before the task runs.
        writer = get_stream_writer()
        try:
            cfg = get_config()
            thread_id: str | None = (cfg.get("configurable") or {}).get("thread_id")
        except Exception:
            thread_id = None

        model_name = self._model_name
        dreamy_prefix = self._DREAMY_TITLE_PREFIX

        append_runtime_event(
            runtime,
            {
                "source": "title_middleware",
                "event": "title_generation_start",
                "phase": "title_generation_start",
                "title_model": model_name,
                "user_message_preview": self._preview(user_msg),
                "title_prompt_preview": self._preview(prompt),
            },
        )

        async def _bg() -> None:
            title = await self._generate_title(state)
            if not title:
                return
            if is_dreamy and not title.startswith(dreamy_prefix):
                title = f"{dreamy_prefix}{title}"

            # Store for aafter_agent to persist via normal state return.
            self._generated_title = title

            # Push live update to the open SSE stream (best-effort).
            try:
                writer({"type": "title_update", "title": title, "thread_id": thread_id})
            except Exception:
                pass

        self._title_bg_task = asyncio.create_task(_bg())

        # Return the fallback immediately so LangGraph checkpoints without delay.
        return {"title": fallback}

    @override
    def after_agent(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Sync fallback: return whatever title the background task stored (if done)."""
        title = self._generated_title
        if title:
            return {"title": title}
        return None

    @override
    async def aafter_agent(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Async path: await the background LLM task (up to config timeout) so even short
        dreamy design-phase runs capture the real title before checkpointing.
        """
        config = get_title_config()
        if self._title_bg_task and not self._title_bg_task.done():
            if config.await_generated_title_timeout_seconds > 0:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._title_bg_task),
                        timeout=config.await_generated_title_timeout_seconds,
                    )
                except (TimeoutError, Exception):
                    pass

        title = self._generated_title
        self._generated_title = None
        self._title_bg_task = None
        if title:
            return {"title": title}
        return None
