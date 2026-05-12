"""Progress guard middleware (warn-first)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.agents.middlewares.retry_policy_middleware import RETRY_PROGRESS_GUARD_KEY
from src.agents.middlewares.runtime_events import append_runtime_event
from src.config.app_config import get_app_config
from src.config.progress_guard_config import ProgressGuardConfig, get_progress_guard_config


class ProgressGuardState(AgentState):
    progress_guard: NotRequired[dict | None]


def _stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        # Ignore middleware-injected human messages (reminders/system warnings/etc.).
        if getattr(msg, "name", None):
            continue
        text = _message_text(getattr(msg, "content", ""))
        if not text:
            continue
        return _stable_hash(text)
    return None


def _estimate_context_fraction(state: AgentState, runtime: Runtime) -> float | None:
    messages = state.get("messages", []) or []
    if not messages:
        return None
    last_msg = messages[-1]
    response_metadata = getattr(last_msg, "response_metadata", None) or {}
    usage = response_metadata.get("token_usage") or response_metadata.get("usage_metadata") or {}
    if not isinstance(usage, dict):
        return None
    prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("total_tokens")
    if not isinstance(prompt_tokens, int):
        return None

    context_window = None
    context = getattr(runtime, "context", None) or {}
    model_name = context.get("model_name")
    if isinstance(model_name, str):
        model_cfg = get_app_config().get_model_config(model_name)
        if model_cfg is not None and model_cfg.model_extra:
            context_window = model_cfg.model_extra.get("context_window") or model_cfg.model_extra.get("max_input_tokens")
    if not isinstance(context_window, int) or context_window <= 0:
        return None
    return max(0.0, min(1.0, prompt_tokens / context_window))


def _outputs_fingerprint(state: AgentState) -> dict:
    thread_data = state.get("thread_data") or {}
    outputs_path = thread_data.get("outputs_path")
    fingerprint: list[tuple[str, int, int]] = []
    if isinstance(outputs_path, str) and outputs_path:
        output_dir = Path(outputs_path)
        if output_dir.exists():
            for file_path in sorted(output_dir.rglob("*")):
                if not file_path.is_file():
                    continue
                stat = file_path.stat()
                fingerprint.append((str(file_path.relative_to(output_dir)), int(stat.st_size), int(stat.st_mtime)))
    return {
        "artifacts": state.get("artifacts", []) or [],
        "todos": state.get("todos", []) or [],
        "outputs": fingerprint,
    }


def _last_ai_visible_content(state: AgentState) -> bool:
    messages = state.get("messages", []) or []
    for msg in reversed(messages):
        if getattr(msg, "type", None) != "ai":
            continue
        if getattr(msg, "tool_calls", None):
            return False
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            return bool(content.strip())
        return bool(str(content).strip())
    return False


def _last_tool_result_signature(state: AgentState) -> str | None:
    messages = state.get("messages", []) or []
    for msg in reversed(messages):
        if getattr(msg, "type", None) != "tool":
            continue
        name = getattr(msg, "name", "") or "tool"
        content = getattr(msg, "content", "")
        return _stable_hash({"name": name, "content": str(content)})
    return None


class ProgressGuardMiddleware(AgentMiddleware[ProgressGuardState]):
    """Detect potential no-progress loops and emit structured warnings."""

    state_schema = ProgressGuardState

    def __init__(self, config: ProgressGuardConfig | None = None):
        super().__init__()
        self._config = config or get_progress_guard_config()

    def _emit_warning(
        self,
        runtime: Runtime,
        signal: str,
        value: int | float,
        threshold: int | float,
    ) -> HumanMessage:
        append_runtime_event(
            runtime,
            {
                "source": "progress_guard",
                "signal": signal,
                "value": value,
                "threshold": threshold,
            },
        )
        return HumanMessage(
            name="progress_guard_warning",
            content=(
                "<system_warning>\n"
                f"ProgressGuard warning: `{signal}` reached {value} (threshold={threshold}).\n"
                "Run continues in warn-only mode.\n"
                "</system_warning>"
            ),
        )

    @override
    def after_model(self, state: ProgressGuardState, runtime: Runtime) -> dict | None:
        cfg = self._config
        if not cfg.enabled:
            return None

        runtime_context = getattr(runtime, "context", None) or {}
        retry_turn = bool(runtime_context.pop(RETRY_PROGRESS_GUARD_KEY, False))
        pg = dict(state.get("progress_guard") or {})
        emitted = set(pg.get("emitted_signals") or [])

        # Scope progress tracking to the current real user message.
        # New user input resets all counters/warnings for a fresh turn budget.
        user_sig = _latest_real_user_signature(state)
        if user_sig and pg.get("user_message_sig") != user_sig:
            pg = {"user_message_sig": user_sig}
            emitted = set()
        elif user_sig:
            pg["user_message_sig"] = user_sig

        snapshot_hash = _stable_hash(_outputs_fingerprint(state))
        if retry_turn:
            no_progress_turns = int(pg.get("no_progress_turns", 0))
        elif snapshot_hash == pg.get("last_snapshot_hash"):
            no_progress_turns = int(pg.get("no_progress_turns", 0)) + 1
        else:
            no_progress_turns = 0
        pg["last_snapshot_hash"] = snapshot_hash
        pg["no_progress_turns"] = no_progress_turns

        if _last_ai_visible_content(state):
            inactivity_turns = 0
        else:
            inactivity_turns = int(pg.get("inactivity_turns", 0)) + 1
        pg["inactivity_turns"] = inactivity_turns

        tool_sig = _last_tool_result_signature(state)
        if retry_turn:
            repeated_tool_result_turns = int(pg.get("repeated_tool_result_turns", 0))
        elif tool_sig and tool_sig == pg.get("last_tool_result_sig"):
            repeated_tool_result_turns = int(pg.get("repeated_tool_result_turns", 0)) + 1
        else:
            repeated_tool_result_turns = 0
        pg["last_tool_result_sig"] = tool_sig
        pg["repeated_tool_result_turns"] = repeated_tool_result_turns

        warning_messages: list[HumanMessage] = []
        if no_progress_turns >= cfg.no_progress_turn_threshold and "no_progress_turns" not in emitted:
            emitted.add("no_progress_turns")
            warning_messages.append(
                self._emit_warning(runtime, "no_progress_turns", no_progress_turns, cfg.no_progress_turn_threshold)
            )

        if inactivity_turns >= cfg.conversation_inactivity_turn_threshold and "conversation_inactivity" not in emitted:
            emitted.add("conversation_inactivity")
            warning_messages.append(
                self._emit_warning(
                    runtime,
                    "conversation_inactivity",
                    inactivity_turns,
                    cfg.conversation_inactivity_turn_threshold,
                )
            )

        if repeated_tool_result_turns >= cfg.cyclic_tool_result_threshold and "cyclic_tool_results" not in emitted:
            emitted.add("cyclic_tool_results")
            warning_messages.append(
                self._emit_warning(
                    runtime,
                    "cyclic_tool_results",
                    repeated_tool_result_turns,
                    cfg.cyclic_tool_result_threshold,
                )
            )

        context_fraction = _estimate_context_fraction(state, runtime)
        if (
            context_fraction is not None
            and context_fraction >= cfg.context_pressure_threshold
            and "context_pressure" not in emitted
        ):
            emitted.add("context_pressure")
            warning_messages.append(
                self._emit_warning(runtime, "context_pressure", round(context_fraction, 3), cfg.context_pressure_threshold)
            )

        if cfg.terminate_on_cyclic_tool_results and repeated_tool_result_turns >= cfg.cyclic_tool_result_hard_limit:
            append_runtime_event(
                runtime,
                {
                    "source": "progress_guard",
                    "signal": "cyclic_tool_result_termination",
                    "value": repeated_tool_result_turns,
                    "threshold": cfg.cyclic_tool_result_hard_limit,
                },
            )
            warning_messages.append(
                HumanMessage(
                    name="progress_guard_warning",
                    content=(
                        "<system_warning>\n"
                        f"ProgressGuard stopped run: cyclic tool results reached {repeated_tool_result_turns} "
                        f"(hard_limit={cfg.cyclic_tool_result_hard_limit}).\n"
                        "Execution ended to prevent an infinite loop.\n"
                        "</system_warning>"
                    ),
                )
            )
            pg["emitted_signals"] = sorted(emitted)
            return {"progress_guard": pg, "messages": warning_messages, "jump_to": "end"}

        if cfg.terminate_on_stall and no_progress_turns >= cfg.no_progress_turn_threshold:
            append_runtime_event(
                runtime,
                {
                    "source": "progress_guard",
                    "signal": "stall_termination",
                    "value": no_progress_turns,
                    "threshold": cfg.no_progress_turn_threshold,
                },
            )
            warning_messages.append(
                HumanMessage(
                    name="progress_guard_warning",
                    content=(
                        "<system_warning>\n"
                        f"ProgressGuard stopped run: no forward progress for {no_progress_turns} turns.\n"
                        "Trajectory has been persisted for replay.\n"
                        "</system_warning>"
                    ),
                )
            )
            pg["emitted_signals"] = sorted(emitted)
            return {"progress_guard": pg, "messages": warning_messages, "jump_to": "end"}

        pg["emitted_signals"] = sorted(emitted)
        if warning_messages:
            return {"progress_guard": pg, "messages": warning_messages}
        return {"progress_guard": pg}

    @override
    async def aafter_model(self, state: ProgressGuardState, runtime: Runtime) -> dict | None:
        return self.after_model(state, runtime)


# LangChain's agent factory reads __can_jump_to__ off the overridden hook method to
# wire conditional edges from after_model → END. Without this, `jump_to: "end"` in
# the returned state is treated as a plain field and termination never fires.
ProgressGuardMiddleware.after_model.__can_jump_to__ = ["end"]  # type: ignore[attr-defined]
ProgressGuardMiddleware.aafter_model.__can_jump_to__ = ["end"]  # type: ignore[attr-defined]
