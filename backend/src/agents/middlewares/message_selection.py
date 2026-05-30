from __future__ import annotations

from typing import Any

_SYNTHETIC_HUMAN_NAMES = {
    "planner_handoff",
    "planner_clarification_required",
    "system_reminder",
    "evaluator_feedback",
    "task_deferred",
    "work_mode_instruction",
    "todo_reminder",
    "todo_dag_reminder",
    "todo_failure_recovery",
    "plan_followup_prompt",
    "work_mode_plan_rerun",
    "active_skills",
    "execute_plan",
}
# Keep this set in sync with `SYNTHETIC_HUMAN_MESSAGE_NAMES` in
# `frontend/src/core/messages/utils.ts` — both halves of the rendering contract
# must agree on which `HumanMessage(name=...)` values are agent-internal and
# should be hidden from the chat timeline.

_SYNTHETIC_REQUEST_PATTERNS = (
    "generate a detailed structured plan for the previous user request",
    "work mode detected this request is too complex for direct execution",
    "what was the content of the previous user request",
    "what is the original user request",
)
# The "continue the previous plan-mode answer in the background" pattern was
# removed: that prompt is emitted by `pro_followup_middleware` as
# `HumanMessage(name="plan_followup_prompt", ...)` and is already caught by
# the `plan_followup_prompt` entry in `_SYNTHETIC_HUMAN_NAMES`. Matching on
# the name (structural) instead of the prompt body (free-text) means the
# wording can evolve without breaking detection here.


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content)


def message_type(message: Any) -> str:
    raw = getattr(message, "type", None)
    if isinstance(raw, str):
        return raw
    if isinstance(message, dict):
        val = message.get("type")
        if isinstance(val, str):
            return val
    return ""


def message_name(message: Any) -> str:
    raw = getattr(message, "name", None)
    if isinstance(raw, str):
        return raw
    if isinstance(message, dict):
        val = message.get("name")
        if isinstance(val, str):
            return val
    return ""


def is_synthetic_human_message(message: Any) -> bool:
    if message_type(message) != "human":
        return False
    name = message_name(message).strip()
    if name in _SYNTHETIC_HUMAN_NAMES:
        return True
    text = extract_text(getattr(message, "content", "")).strip().lower()
    return any(pattern in text for pattern in _SYNTHETIC_REQUEST_PATTERNS)


def original_user_prompt(messages: list[Any]) -> str:
    for message in reversed(messages):
        if message_type(message) != "human" or is_synthetic_human_message(message):
            continue
        text = extract_text(getattr(message, "content", "")).strip()
        if text:
            return text
    return ""


def latest_message_text(messages: list[Any], *, msg_type: str, skip_synthetic_human: bool = False) -> str:
    for message in reversed(messages):
        if message_type(message) != msg_type:
            continue
        if skip_synthetic_human and msg_type == "human" and is_synthetic_human_message(message):
            continue
        text = extract_text(getattr(message, "content", "")).strip()
        if text:
            return text
    return ""


def latest_real_ai_answer(messages: list[Any]) -> str:
    for message in reversed(messages):
        if message_type(message) != "ai":
            continue
        if getattr(message, "tool_calls", None):
            continue
        text = extract_text(getattr(message, "content", "")).strip()
        if text:
            return text
    return ""
