"""Extended SummarizationMiddleware with pre-compression hook dispatch and skill rescue.

Two enhancements over the base SummarizationMiddleware:

1. **BeforeSummarizationHook dispatch** — callables registered via the
   ``before_summarization`` constructor argument are fired synchronously before
   any messages are removed from state.  The primary use-case is
   ``memory_flush_hook``, which captures about-to-be-compressed messages into
   long-term memory before they disappear.

2. **Skill-message rescue** — SkillDisclosureMiddleware injects skill bodies as
   ``HumanMessage(name="active_skills", ...)`` blocks into the conversation.
   When these blocks land in the to-be-summarized window they would be
   permanently lost, forcing the agent to re-activate skills mid-task.  This
   middleware identifies such messages and moves the most recent N of them to
   the preserved set before summarization runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from langchain.agents import AgentState
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import AnyMessage, HumanMessage, RemoveMessage
from langgraph.config import get_config
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime

from src.agents.memory.compaction_archive import append_compaction_entry
from src.agents.middlewares.runtime_events import append_runtime_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hook protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SummarizationEvent:
    """Context passed to each BeforeSummarizationHook."""

    messages_to_summarize: tuple[AnyMessage, ...]
    preserved_messages: tuple[AnyMessage, ...]
    thread_id: str | None
    agent_name: str | None
    runtime: Runtime
    state: AgentState | None = None


@runtime_checkable
class BeforeSummarizationHook(Protocol):
    """Callable invoked before messages are compressed out of state."""

    def __call__(self, event: SummarizationEvent) -> None: ...


# ---------------------------------------------------------------------------
# Thread / agent resolution helpers
# ---------------------------------------------------------------------------


def _resolve_thread_id(runtime: Runtime) -> str | None:
    ctx = getattr(runtime, "context", None) or {}
    thread_id = ctx.get("thread_id")
    if thread_id is None:
        try:
            cfg = get_config()
            thread_id = (cfg.get("configurable") or {}).get("thread_id")
        except RuntimeError:
            pass
    return thread_id


def _resolve_agent_name(runtime: Runtime) -> str | None:
    ctx = getattr(runtime, "context", None) or {}
    agent_name = ctx.get("agent_name")
    if agent_name is None:
        try:
            cfg = get_config()
            agent_name = (cfg.get("configurable") or {}).get("agent_name")
        except RuntimeError:
            pass
    return agent_name


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class CapybaraSummarizationMiddleware(SummarizationMiddleware):
    """SummarizationMiddleware extended with hook dispatch and skill-message rescue."""

    def __init__(
        self,
        *args,
        before_summarization: list[BeforeSummarizationHook] | None = None,
        preserve_recent_skill_count: int = 5,
        preserve_recent_skill_tokens: int = 25_000,
        preserve_user_anchor_count: int = 1,
        **kwargs,
    ) -> None:
        # Capture trigger tuples before super().__init__ may raise a ValueError
        # for fractional thresholds. _detect_trigger_type reads _trigger_tuples
        # (our owned list) instead of the base-class trigger_config attribute,
        # whose internal format differs from raw tuples and causes "unknown" logs.
        _trigger = kwargs.get("trigger", None)
        if _trigger is None:
            self._trigger_tuples: list[tuple] = []
        elif isinstance(_trigger, list):
            self._trigger_tuples = [t for t in _trigger if isinstance(t, tuple)]
        elif isinstance(_trigger, tuple):
            self._trigger_tuples = [_trigger]
        else:
            self._trigger_tuples = []
        super().__init__(*args, **kwargs)
        self._before_summarization_hooks: list[BeforeSummarizationHook] = before_summarization or []
        self._preserve_recent_skill_count = max(0, preserve_recent_skill_count)
        self._preserve_recent_skill_tokens = max(0, preserve_recent_skill_tokens)
        self._preserve_user_anchor_count = max(0, preserve_user_anchor_count)
        self._last_trigger_type: str = "manual"
        # Threshold / observed values for the most recent trigger detection,
        # captured so the compaction trajectory event can carry "why now":
        # `trigger=tokens, threshold=8000, observed=8421` etc. Defaults indicate
        # "no detection ran yet" — overwritten by _detect_trigger_type.
        self._last_trigger_threshold: int | float | None = None
        self._last_trigger_observed: int | float | None = None
        self._last_summary_quality: str = "model"
        self._last_summary_source: str = "model"
        self._last_summary_error: str | None = None
        self._summary_state_snapshot: AgentState | None = None

    # ------------------------------------------------------------------
    # Override entry points
    # ------------------------------------------------------------------

    @staticmethod
    def _should_force_compaction(state: AgentState, runtime: Runtime) -> bool:
        context = getattr(runtime, "context", None) or {}
        if isinstance(context, dict) and context.get("force_compaction") is True:
            return True
        if isinstance(state, dict) and state.get("force_compaction_once") is True:
            return True
        return False

    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._maybe_summarize(state, runtime)

    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return await self._amaybe_summarize(state, runtime)

    # ------------------------------------------------------------------
    # Core summarization flow (sync + async)
    # ------------------------------------------------------------------

    def _maybe_summarize(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = state["messages"]
        self._ensure_message_ids(messages)

        total_tokens = self.token_counter(messages)
        self._emit_context_tokens_event(runtime, total_tokens, len(messages))
        force_compaction = self._should_force_compaction(state, runtime)
        if not force_compaction and not self._should_summarize(messages, total_tokens):
            return None

        cutoff_index = self._determine_cutoff_index(messages)
        if force_compaction and cutoff_index <= 0 and len(messages) > 1:
            cutoff_index = max(1, len(messages) - 1)
        if cutoff_index <= 0:
            return None

        to_summarize, preserved = self._partition_with_skill_rescue(messages, cutoff_index)
        self._last_trigger_type = "manual" if force_compaction else self._detect_trigger_type(messages, total_tokens)
        self._fire_hooks(state, to_summarize, preserved, runtime)
        self._summary_state_snapshot = state
        summary = self._create_summary(to_summarize)
        self._record_compaction_event(
            runtime=runtime,
            summary=summary,
            compressed_count=len(to_summarize),
            kept_count=len(preserved),
        )
        self._summary_state_snapshot = None
        new_messages = self._build_new_messages(summary)

        updates: dict = {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *new_messages,
                *preserved,
            ]
        }
        if force_compaction:
            updates["force_compaction_once"] = False
        return updates

    async def _amaybe_summarize(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = state["messages"]
        self._ensure_message_ids(messages)

        total_tokens = self.token_counter(messages)
        self._emit_context_tokens_event(runtime, total_tokens, len(messages))
        force_compaction = self._should_force_compaction(state, runtime)
        if not force_compaction and not self._should_summarize(messages, total_tokens):
            return None

        cutoff_index = self._determine_cutoff_index(messages)
        if force_compaction and cutoff_index <= 0 and len(messages) > 1:
            cutoff_index = max(1, len(messages) - 1)
        if cutoff_index <= 0:
            return None

        to_summarize, preserved = self._partition_with_skill_rescue(messages, cutoff_index)
        self._last_trigger_type = "manual" if force_compaction else self._detect_trigger_type(messages, total_tokens)
        self._fire_hooks(state, to_summarize, preserved, runtime)
        self._summary_state_snapshot = state
        summary = await self._acreate_summary(to_summarize)
        self._record_compaction_event(
            runtime=runtime,
            summary=summary,
            compressed_count=len(to_summarize),
            kept_count=len(preserved),
        )
        self._summary_state_snapshot = None
        new_messages = self._build_new_messages(summary)

        updates: dict = {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *new_messages,
                *preserved,
            ]
        }
        if force_compaction:
            updates["force_compaction_once"] = False
        return updates

    # ------------------------------------------------------------------
    # Skill rescue
    # ------------------------------------------------------------------

    def _is_failed_summary(self, summary: str) -> bool:
        normalized = summary.strip()
        if not normalized:
            return True
        return normalized.lower().startswith("error generating summary:")

    @staticmethod
    def _looks_like_empty_context_summary(summary: str) -> bool:
        normalized = summary.strip().lower()
        if not normalized:
            return False
        markers = (
            "no prior context",
            "no prior conversation",
            "awaiting initial prompt",
            "session is fresh",
            "no artifacts, file paths, commands",
        )
        return any(marker in normalized for marker in markers)

    @staticmethod
    def _has_substantive_context(messages: list[AnyMessage]) -> bool:
        for msg in messages:
            content = str(getattr(msg, "content", "")).strip()
            if not content:
                continue
            if isinstance(msg, HumanMessage) and getattr(msg, "name", None) == "active_skills":
                continue
            lowered = content.lower()
            if "/mnt/" in lowered or ".md" in lowered or "write file" in lowered:
                return True
            if len(content) > 80:
                return True
        return False

    def _deterministic_fallback_summary(self, messages: list[AnyMessage]) -> str:
        state = self._summary_state_snapshot or {}
        todos_block = "- No todo graph available."
        todo_graph = state.get("todo_graph") if isinstance(state, dict) else None
        if isinstance(todo_graph, dict):
            nodes = todo_graph.get("nodes")
            if isinstance(nodes, list) and nodes:
                lines: list[str] = []
                for node in nodes[:10]:
                    if not isinstance(node, dict):
                        continue
                    todo_id = str(node.get("id") or "todo").strip()
                    content = str(node.get("content") or "").strip() or "Untitled task"
                    status = str(node.get("status") or "pending").strip()
                    lines.append(f"- [{status}] {todo_id}: {content}")
                if lines:
                    todos_block = "\n".join(lines)

        artifacts = state.get("artifacts") if isinstance(state, dict) else None
        artifact_lines: list[str] = []
        if isinstance(artifacts, list):
            artifact_lines = [f"- {str(path)}" for path in artifacts[-8:] if isinstance(path, str)]
        artifacts_block = "\n".join(artifact_lines) if artifact_lines else "- No recent artifacts."

        latest_user = ""
        latest_ai = ""
        for msg in reversed(messages):
            if not latest_user and isinstance(msg, HumanMessage):
                latest_user = str(getattr(msg, "content", "")).strip()
            if not latest_ai and getattr(msg, "type", None) == "ai":
                latest_ai = str(getattr(msg, "content", "")).strip()
            if latest_user and latest_ai:
                break
        latest_user = latest_user[:280] if latest_user else "N/A"
        latest_ai = latest_ai[:280] if latest_ai else "N/A"

        return (
            "[summary_quality:fallback]\n"
            "[summary_source:deterministic_state]\n"
            "Model summarization failed; generated deterministic fallback summary.\n\n"
            "## Latest Intent\n"
            f"- User: {latest_user}\n"
            f"- Assistant: {latest_ai}\n\n"
            "## Todo Snapshot\n"
            f"{todos_block}\n\n"
            "## Artifact Snapshot\n"
            f"{artifacts_block}\n"
        )

    def _create_summary(self, messages: list[AnyMessage]) -> str:  # type: ignore[override]
        try:
            summary = super()._create_summary(messages)
        except Exception as exc:  # noqa: BLE001
            summary = f"Error generating summary: {exc}"
            self._last_summary_error = str(exc)
        if self._looks_like_empty_context_summary(summary) and self._has_substantive_context(messages):
            self._last_summary_error = "summary_quality_guard: empty-context summary contradicted by conversation state"
            self._last_summary_quality = "fallback"
            self._last_summary_source = "deterministic_state"
            return self._deterministic_fallback_summary(messages)
        if self._is_failed_summary(summary):
            self._last_summary_quality = "fallback"
            self._last_summary_source = "deterministic_state"
            if self._last_summary_error is None and summary.strip():
                self._last_summary_error = summary.strip()
            return self._deterministic_fallback_summary(messages)
        self._last_summary_quality = "model"
        self._last_summary_source = "model"
        self._last_summary_error = None
        return summary

    async def _acreate_summary(self, messages: list[AnyMessage]) -> str:  # type: ignore[override]
        try:
            summary = await super()._acreate_summary(messages)
        except Exception as exc:  # noqa: BLE001
            summary = f"Error generating summary: {exc}"
            self._last_summary_error = str(exc)
        if self._looks_like_empty_context_summary(summary) and self._has_substantive_context(messages):
            self._last_summary_error = "summary_quality_guard: empty-context summary contradicted by conversation state"
            self._last_summary_quality = "fallback"
            self._last_summary_source = "deterministic_state"
            return self._deterministic_fallback_summary(messages)
        if self._is_failed_summary(summary):
            self._last_summary_quality = "fallback"
            self._last_summary_source = "deterministic_state"
            if self._last_summary_error is None and summary.strip():
                self._last_summary_error = summary.strip()
            return self._deterministic_fallback_summary(messages)
        self._last_summary_quality = "model"
        self._last_summary_source = "model"
        self._last_summary_error = None
        return summary

    def _partition_with_skill_rescue(
        self,
        messages: list[AnyMessage],
        cutoff_index: int,
    ) -> tuple[list[AnyMessage], list[AnyMessage]]:
        """Standard partition then rescue recently-injected skill blocks."""
        to_summarize, preserved = self._partition_messages(messages, cutoff_index)

        if not to_summarize:
            return to_summarize, preserved

        try:
            rescued, remaining = self._rescue_skill_messages(to_summarize)
        except Exception:
            logger.exception("Skill rescue during summarization failed; using default partition")
            rescued, remaining = [], to_summarize

        try:
            anchors, remaining = self._rescue_user_anchor_messages(remaining)
        except Exception:
            logger.exception("User-anchor rescue during summarization failed; using default remaining set")
            anchors = []

        rescue_bundle = [*anchors, *rescued]
        if not rescue_bundle:
            return to_summarize, preserved

        return remaining, rescue_bundle + preserved

    def _rescue_user_anchor_messages(
        self,
        messages: list[AnyMessage],
    ) -> tuple[list[AnyMessage], list[AnyMessage]]:
        """Keep earliest non-skill user message(s) as continuity anchors."""
        if self._preserve_user_anchor_count <= 0 or not messages:
            return [], messages

        anchor_indices: list[int] = []
        for i, msg in enumerate(messages):
            if not isinstance(msg, HumanMessage):
                continue
            if getattr(msg, "name", None) == "active_skills":
                continue
            content = str(getattr(msg, "content", "")).strip()
            if not content:
                continue
            anchor_indices.append(i)
            if len(anchor_indices) >= self._preserve_user_anchor_count:
                break

        if not anchor_indices:
            return [], messages

        anchor_set = set(anchor_indices)
        anchors = [messages[i] for i in anchor_indices]
        remaining = [msg for i, msg in enumerate(messages) if i not in anchor_set]
        return anchors, remaining

    def _rescue_skill_messages(
        self,
        messages: list[AnyMessage],
    ) -> tuple[list[AnyMessage], list[AnyMessage]]:
        """Separate the most recent active_skills blocks from *messages*.

        SkillDisclosureMiddleware injects ``HumanMessage(name="active_skills", ...)``
        blocks.  We walk the list newest-first, rescue up to
        ``preserve_recent_skill_count`` distinct blocks within the token budget,
        and return (rescued, remaining).
        """
        skill_indices: list[int] = []
        token_total = 0

        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if not isinstance(msg, HumanMessage):
                continue
            if getattr(msg, "name", None) != "active_skills":
                continue

            msg_tokens = self.token_counter([msg])
            if token_total + msg_tokens > self._preserve_recent_skill_tokens:
                continue

            skill_indices.append(i)
            token_total += msg_tokens

            if len(skill_indices) >= self._preserve_recent_skill_count:
                break

        if not skill_indices:
            return [], messages

        rescue_set = set(skill_indices)
        rescued = [messages[i] for i in sorted(skill_indices)]
        remaining = [msg for i, msg in enumerate(messages) if i not in rescue_set]
        return rescued, remaining

    # ------------------------------------------------------------------
    # Hook dispatch
    # ------------------------------------------------------------------

    def _detect_trigger_type(self, messages: list[AnyMessage], total_tokens: int) -> str:
        """Return the canonical trigger kind that fired this compaction.

        Side effects: populates `self._last_trigger_threshold` and
        `self._last_trigger_observed` so the compaction event can record the
        threshold and the observed value that crossed it. The pre-Phase-1
        version returned the bare string "unknown" when no trigger matched —
        which made forensic debugging impossible (see thread-cd90decb finding
        #7). The new contract: every return is a member of a small enum
        {tokens, messages, fraction, threshold_unmet, manual} and threshold/
        observed are set whenever applicable.
        """
        trigger_tuples = getattr(self, "_trigger_tuples", [])
        # Default observed = current state, threshold = None
        self._last_trigger_observed = total_tokens
        self._last_trigger_threshold = None
        if not trigger_tuples:
            # No declarative trigger configured: caller invoked summarization
            # directly (e.g. via memory_flush_hook). Tag as "manual" rather
            # than the dead-end "unknown".
            return "manual"
        for t in trigger_tuples:
            if not isinstance(t, tuple) or len(t) != 2:
                continue
            kind, threshold = t
            if kind == "tokens" and total_tokens >= threshold:
                self._last_trigger_threshold = threshold
                self._last_trigger_observed = total_tokens
                return "tokens"
            if kind == "messages" and len(messages) >= threshold:
                self._last_trigger_threshold = threshold
                self._last_trigger_observed = len(messages)
                return "messages"
            if kind == "fraction":
                self._last_trigger_threshold = threshold
                self._last_trigger_observed = total_tokens
                return "fraction"
        # All triggers configured but none crossed — caller still chose to
        # compact (e.g. forced via _should_summarize override). Distinct from
        # "manual" because triggers WERE configured and just didn't fire.
        return "threshold_unmet"

    def _emit_context_tokens_event(self, runtime: Runtime, token_count: int, message_count: int) -> None:
        append_runtime_event(
            runtime,
            {
                "source": "summarization_middleware",
                "event": "context_tokens",
                "thread_id": _resolve_thread_id(runtime),
                "token_count": token_count,
                "message_count": message_count,
            },
        )

    def _record_compaction_event(
        self,
        *,
        runtime: Runtime,
        summary: str,
        compressed_count: int,
        kept_count: int,
    ) -> None:
        thread_id = _resolve_thread_id(runtime)
        payload = {
            "event": "compaction",
            "thread_id": thread_id,
            "messages_compressed": compressed_count,
            "messages_kept": kept_count,
            "trigger": self._last_trigger_type,
            "trigger_threshold": self._last_trigger_threshold,
            "trigger_observed": self._last_trigger_observed,
            "summary_quality": self._last_summary_quality,
            "summary_source": self._last_summary_source,
            "summary_error": self._last_summary_error,
        }
        append_runtime_event(
            runtime,
            {
                "source": "summarization_middleware",
                **payload,
            },
        )
        if thread_id:
            try:
                append_compaction_entry(
                    thread_id,
                    {
                        "trigger": self._last_trigger_type,
                        "trigger_threshold": self._last_trigger_threshold,
                        "trigger_observed": self._last_trigger_observed,
                        "messages_compressed": compressed_count,
                        "messages_kept": kept_count,
                        "summary_text": summary,
                        "summary_quality": self._last_summary_quality,
                        "summary_source": self._last_summary_source,
                        "summary_error": self._last_summary_error,
                        "model_used": str(getattr(getattr(self, "model", None), "model_name", "") or ""),
                    },
                )
            except Exception:
                logger.exception("Failed to persist compaction archive for thread %s", thread_id)

    def _fire_hooks(self, *args) -> None:
        if len(args) == 3:
            state: AgentState | None = None
            to_summarize, preserved, runtime = args
        elif len(args) == 4:
            state, to_summarize, preserved, runtime = args
        else:
            raise TypeError("_fire_hooks expects (to_summarize, preserved, runtime) or (state, to_summarize, preserved, runtime)")

        if not self._before_summarization_hooks:
            return

        event = SummarizationEvent(
            messages_to_summarize=tuple(to_summarize),
            preserved_messages=tuple(preserved),
            thread_id=_resolve_thread_id(runtime),
            agent_name=_resolve_agent_name(runtime),
            runtime=runtime,
            state=state,
        )

        for hook in self._before_summarization_hooks:
            try:
                hook(event)
            except Exception:
                hook_name = getattr(hook, "__name__", None) or type(hook).__name__
                logger.exception("before_summarization hook %r failed", hook_name)
