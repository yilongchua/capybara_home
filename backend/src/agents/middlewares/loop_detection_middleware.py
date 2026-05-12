"""Two-layer loop detection middleware.

P0 safety: prevents the agent from calling the same tool with the same
arguments indefinitely until the recursion limit kills the run.

Detection strategy
------------------
Layer 1 — hash-based (identical call sets):
  After each model response, compute a stable multiset hash of all tool calls
  (name + salient args).  Track the last N hashes in a per-thread sliding
  window.  If the same hash appears >= warn_threshold times, inject a
  "you are repeating yourself" message (once per hash).  At hard_limit,
  strip all tool_calls from the AIMessage so the agent is forced to produce
  a final text answer.

Layer 2 — frequency-based (tool-type saturation):
  Count cumulative calls to each tool name across the whole thread, regardless
  of arguments.  Catches cross-file read loops and similar patterns where each
  call uses different args (so Layer 1's hash never repeats) but the agent
  is clearly stuck saturating a single tool type.

This middleware complements ProgressGuardMiddleware: ProgressGuard detects
stalls by inspecting *outputs* (unchanged artifacts/todos/files), while
LoopDetectionMiddleware detects repetitive *inputs* (call patterns).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict, defaultdict
from copy import deepcopy
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

_WORKFLOW_CACHE_TTL = 30.0  # seconds between skill reloads for workflow check
_workflow_skill_names: set[str] = set()
_workflow_cache_ts: float = 0.0
_workflow_cache_lock = threading.Lock()


def _get_workflow_skill_names() -> set[str]:
    """Return the set of skill names that have workflow=True, cached for TTL seconds."""
    global _workflow_skill_names, _workflow_cache_ts
    now = time.monotonic()
    with _workflow_cache_lock:
        if now - _workflow_cache_ts > _WORKFLOW_CACHE_TTL:
            try:
                from src.skills.loader import load_skills

                _workflow_skill_names = {s.name for s in load_skills(enabled_only=True) if s.workflow}
                _workflow_cache_ts = now
            except Exception:
                pass  # keep stale cache on error
        return set(_workflow_skill_names)


def _is_workflow_active(state: AgentState) -> bool:
    """Return True if any active skill in the current thread has workflow=True."""
    sd = state.get("skill_disclosure") or {}
    active_map = sd.get("active") or {}
    if not active_map:
        return False
    active_names = set(active_map.keys())
    workflow_names = _get_workflow_skill_names()
    return bool(active_names & workflow_names)

_DEFAULT_WARN_THRESHOLD = 3
_DEFAULT_HARD_LIMIT = 5
_DEFAULT_WINDOW_SIZE = 20
_DEFAULT_MAX_TRACKED_THREADS = 100
_DEFAULT_TOOL_FREQ_WARN = 30
_DEFAULT_TOOL_FREQ_HARD_LIMIT = 50

_WARNING_MSG = (
    "[LOOP DETECTED] You are repeating the same tool calls. "
    "Stop calling tools and produce your final answer now. "
    "If you cannot complete the task, summarize what you accomplished so far."
)
_TOOL_FREQ_WARNING_MSG = (
    "[LOOP DETECTED] You have called {tool_name} {count} times without producing a final answer. "
    "Stop calling tools and produce your final answer now. "
    "If you cannot complete the task, summarize what you accomplished so far."
)
_HARD_STOP_MSG = (
    "[FORCED STOP] Repeated tool calls exceeded the safety limit. "
    "Producing final answer with results collected so far."
)
_TOOL_FREQ_HARD_STOP_MSG = (
    "[FORCED STOP] Tool {tool_name} called {count} times — exceeded the per-tool safety limit. "
    "Producing final answer with results collected so far."
)


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------


def _normalize_args(raw_args: object) -> tuple[dict, str | None]:
    """Normalise tool call args to (dict, fallback_key).

    Some providers serialise ``args`` as a JSON string.  We defensively parse
    those cases and keep a stable fallback for non-dict payloads.
    """
    if isinstance(raw_args, dict):
        return raw_args, None
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}, raw_args
        if isinstance(parsed, dict):
            return parsed, None
        return {}, json.dumps(parsed, sort_keys=True, default=str)
    if raw_args is None:
        return {}, None
    return {}, json.dumps(raw_args, sort_keys=True, default=str)


def _stable_key(name: str, args: dict, fallback: str | None) -> str:
    """Derive a stable key from salient args without overfitting to noise.

    Special cases:
    * ``read_file`` — bucket by 200-line windows so adjacent reads of the same
      file region hash the same (avoids false positives on sequential reads).
    * ``write_file`` / ``str_replace`` — hash full args because the same path
      with different content is a genuinely distinct operation.
    * Everything else — project to a small set of salient field names.
    """
    if name == "read_file" and fallback is None:
        path = args.get("path") or ""
        try:
            start = int(args.get("start_line") or 1)
        except (TypeError, ValueError):
            start = 1
        try:
            end = int(args.get("end_line") or start)
        except (TypeError, ValueError):
            end = start
        bucket = 200
        return f"{path}:{(start - 1) // bucket}-{(end - 1) // bucket}"

    if name in {"write_file", "str_replace"}:
        return fallback if fallback is not None else json.dumps(args, sort_keys=True, default=str)

    salient = ("path", "url", "query", "command", "pattern", "glob", "cmd")
    stable = {k: args[k] for k in salient if args.get(k) is not None}
    if stable:
        return json.dumps(stable, sort_keys=True, default=str)
    return fallback if fallback is not None else json.dumps(args, sort_keys=True, default=str)


def _hash_tool_calls(tool_calls: list[dict]) -> str:
    """Deterministic, order-independent multiset hash of a tool-call list."""
    parts: list[str] = []
    for tc in tool_calls:
        name = tc.get("name", "")
        args, fallback = _normalize_args(tc.get("args", {}))
        parts.append(f"{name}:{_stable_key(name, args, fallback)}")
    parts.sort()
    return hashlib.md5(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content).strip() if content is not None else ""


def _latest_real_user_signature(state: AgentState) -> str | None:
    messages = state.get("messages", []) or []
    for msg in reversed(messages):
        if getattr(msg, "type", None) != "human":
            continue
        # Ignore middleware-injected reminders/anchors.
        if getattr(msg, "name", None):
            continue
        text = _message_text(getattr(msg, "content", ""))
        if not text:
            continue
        return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]
    return None


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class LoopDetectionMiddleware(AgentMiddleware[AgentState]):
    """Detect and break repetitive tool-call loops.

    Args:
        warn_threshold: Identical call-set hash count before injecting a warning.
        hard_limit: Identical call-set hash count before stripping tool_calls entirely.
        window_size: Sliding window size (number of turns tracked per thread).
        max_tracked_threads: LRU eviction limit for per-thread state.
        tool_freq_warn: Per-tool-type call count before a frequency warning.
        tool_freq_hard_limit: Per-tool-type call count before a hard stop.
    """

    def __init__(
        self,
        warn_threshold: int = _DEFAULT_WARN_THRESHOLD,
        hard_limit: int = _DEFAULT_HARD_LIMIT,
        window_size: int = _DEFAULT_WINDOW_SIZE,
        max_tracked_threads: int = _DEFAULT_MAX_TRACKED_THREADS,
        tool_freq_warn: int = _DEFAULT_TOOL_FREQ_WARN,
        tool_freq_hard_limit: int = _DEFAULT_TOOL_FREQ_HARD_LIMIT,
    ) -> None:
        super().__init__()
        self.warn_threshold = warn_threshold
        self.hard_limit = hard_limit
        self.window_size = window_size
        self.max_tracked_threads = max_tracked_threads
        self.tool_freq_warn = tool_freq_warn
        self.tool_freq_hard_limit = tool_freq_hard_limit
        self._lock = threading.Lock()
        # Per-thread hash history (LRU ordered dict)
        self._history: OrderedDict[str, list[str]] = OrderedDict()
        # Per-thread set of hashes we already warned about
        self._warned: dict[str, set[str]] = defaultdict(set)
        # Per-thread per-tool-name cumulative call counter
        self._tool_freq: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # Per-thread set of tool names we already warned about (frequency layer)
        self._tool_freq_warned: dict[str, set[str]] = defaultdict(set)
        # Per-thread fingerprint of latest real user message; resets counters when user sends a new message.
        self._last_user_sig: dict[str, str] = {}

    # ------------------------------------------------------------------
    # LRU helpers
    # ------------------------------------------------------------------

    def _get_thread_id(self, runtime: Runtime) -> str:
        ctx = getattr(runtime, "context", None) or {}
        return ctx.get("thread_id") or "default"

    def _evict_if_needed(self) -> None:
        while len(self._history) > self.max_tracked_threads:
            evicted, _ = self._history.popitem(last=False)
            self._warned.pop(evicted, None)
            self._tool_freq.pop(evicted, None)
            self._tool_freq_warned.pop(evicted, None)

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _track_and_check(self, state: AgentState, runtime: Runtime) -> tuple[str | None, bool]:
        """Return (warning_msg | None, should_hard_stop)."""
        messages = state.get("messages", [])
        if not messages:
            return None, False
        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None, False
        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None, False

        thread_id = self._get_thread_id(runtime)
        call_hash = _hash_tool_calls(tool_calls)
        user_sig = _latest_real_user_signature(state)

        with self._lock:
            # Scope detection to a single user message turn, not whole thread history.
            if user_sig and self._last_user_sig.get(thread_id) != user_sig:
                self._history[thread_id] = []
                self._warned[thread_id].clear()
                self._tool_freq[thread_id].clear()
                self._tool_freq_warned[thread_id].clear()
                self._last_user_sig[thread_id] = user_sig

            if thread_id in self._history:
                self._history.move_to_end(thread_id)
            else:
                self._history[thread_id] = []
                if user_sig:
                    self._last_user_sig[thread_id] = user_sig
                self._evict_if_needed()

            history = self._history[thread_id]
            history.append(call_hash)
            if len(history) > self.window_size:
                history[:] = history[-self.window_size :]

            count = history.count(call_hash)
            tool_names = [tc.get("name", "?") for tc in tool_calls]

            # --- Layer 1: hash-based ---
            if count >= self.hard_limit:
                logger.error(
                    "Loop hard limit reached — forcing stop (thread=%s hash=%s count=%d tools=%s)",
                    thread_id, call_hash, count, tool_names,
                )
                return _HARD_STOP_MSG, True

            if count >= self.warn_threshold:
                warned = self._warned[thread_id]
                if call_hash not in warned:
                    warned.add(call_hash)
                    logger.warning(
                        "Repetitive tool calls detected (thread=%s hash=%s count=%d tools=%s)",
                        thread_id, call_hash, count, tool_names,
                    )
                    return _WARNING_MSG, False

            # --- Layer 2: per-tool-type frequency ---
            # Skip for intentional workflow tasks (skill declares workflow: true).
            # Layer 1 (hash-based) above still catches genuine stuck loops.
            if _is_workflow_active(state):
                return None, False

            freq = self._tool_freq[thread_id]
            for tc in tool_calls:
                name = tc.get("name", "")
                if not name:
                    continue
                freq[name] += 1
                tc_count = freq[name]

                if tc_count >= self.tool_freq_hard_limit:
                    logger.error(
                        "Tool frequency hard limit reached (thread=%s tool=%s count=%d)",
                        thread_id, name, tc_count,
                    )
                    return _TOOL_FREQ_HARD_STOP_MSG.format(tool_name=name, count=tc_count), True

                if tc_count >= self.tool_freq_warn:
                    freq_warned = self._tool_freq_warned[thread_id]
                    if name not in freq_warned:
                        freq_warned.add(name)
                        logger.warning(
                            "Tool frequency warning (thread=%s tool=%s count=%d)",
                            thread_id, name, tc_count,
                        )
                        return _TOOL_FREQ_WARNING_MSG.format(tool_name=name, count=tc_count), False

        return None, False

    # ------------------------------------------------------------------
    # Message mutation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _append_text(content: str | list | None, text: str) -> str | list:
        if content is None:
            return text
        if isinstance(content, list):
            return [*content, {"type": "text", "text": f"\n\n{text}"}]
        if isinstance(content, str):
            return content + f"\n\n{text}"
        return str(content) + f"\n\n{text}"

    @staticmethod
    def _build_hard_stop_update(last_msg, content: str | list) -> dict:
        """Build model_copy kwargs that strip tool-call metadata for a forced stop."""
        update: dict = {"tool_calls": [], "content": content}
        extra = dict(getattr(last_msg, "additional_kwargs", {}) or {})
        for key in ("tool_calls", "function_call"):
            extra.pop(key, None)
        update["additional_kwargs"] = extra
        meta = deepcopy(getattr(last_msg, "response_metadata", {}) or {})
        if meta.get("finish_reason") == "tool_calls":
            meta["finish_reason"] = "stop"
        update["response_metadata"] = meta
        return update

    # ------------------------------------------------------------------
    # Middleware hooks
    # ------------------------------------------------------------------

    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        warning, hard_stop = self._track_and_check(state, runtime)

        if hard_stop:
            messages = state.get("messages", [])
            last_msg = messages[-1]
            content = self._append_text(last_msg.content, warning or _HARD_STOP_MSG)
            stripped = last_msg.model_copy(update=self._build_hard_stop_update(last_msg, content))
            return {"messages": [stripped]}

        if warning:
            # Use HumanMessage instead of SystemMessage — Anthropic models reject
            # non-consecutive system messages injected mid-conversation.
            return {"messages": [HumanMessage(content=warning)]}

        return None

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    def reset(self, thread_id: str | None = None) -> None:
        """Clear per-thread tracking state (useful for tests)."""
        with self._lock:
            if thread_id:
                self._history.pop(thread_id, None)
                self._warned.pop(thread_id, None)
                self._tool_freq.pop(thread_id, None)
                self._tool_freq_warned.pop(thread_id, None)
                self._last_user_sig.pop(thread_id, None)
            else:
                self._history.clear()
                self._warned.clear()
                self._tool_freq.clear()
                self._tool_freq_warned.clear()
                self._last_user_sig.clear()
