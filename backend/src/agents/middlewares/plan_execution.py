"""Shared plan lifecycle helpers: clarifications, approval, and work handoff."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage

from src.agents.middlewares.message_selection import (
    extract_text,
    is_synthetic_human_message,
    message_name,
    message_type,
    original_user_prompt,
)

_AUTO_MODE_PREFIX = "[Auto Mode] Selected:"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _message_content(message: Any) -> Any:
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", "")


def _normalize_answer_text(text: str) -> str:
    cleaned = text.lower().strip()
    cleaned = re.sub(r"[.!?]+$", "", cleaned)
    return " ".join(cleaned.split())


def _is_clarification_marker(message: Any) -> bool:
    msg_type = message_type(message)
    name = message_name(message)
    return (msg_type == "tool" and name == "ask_clarification") or (
        msg_type == "human" and name == "planner_clarification_required"
    )


def _clarifications_list(plan: dict[str, Any]) -> list[dict[str, Any]]:
    raw = plan.get("clarifications")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and str(item.get("question") or "").strip()]


def clarification_index(plan: dict[str, Any]) -> int:
    raw = plan.get("clarification_index")
    if isinstance(raw, int) and raw >= 0:
        return raw
    return 0


def current_clarification(plan: dict[str, Any]) -> dict[str, Any] | None:
    clarifications = _clarifications_list(plan)
    if clarifications:
        idx = min(clarification_index(plan), len(clarifications) - 1)
        return clarifications[idx]
    question = str(plan.get("clarification_question") or "").strip()
    if question and bool(plan.get("clarification_pending")):
        return {"question": question, "options": []}
    return None


def all_clarifications_resolved(plan: dict[str, Any]) -> bool:
    clarifications = _clarifications_list(plan)
    if not clarifications:
        return True
    if bool(plan.get("clarification_resolved")):
        return True
    answers = plan.get("clarification_answers")
    if isinstance(answers, list) and len(answers) >= len(clarifications):
        return True
    return clarification_index(plan) >= len(clarifications)


def handoff_already_started(plan: dict[str, Any]) -> bool:
    if bool(plan.get("execution_handoff_failed")):
        return False
    return bool(plan.get("execution_handoff_started"))


def work_execution_underway(values: dict[str, Any]) -> bool:
    """True when work mode is actively driving plan execution on this thread."""
    work_mode = values.get("work_mode")
    if isinstance(work_mode, dict) and bool(work_mode.get("active")):
        return True
    plan = values.get("plan")
    if isinstance(plan, dict):
        status = str(plan.get("status") or "").strip().lower()
        if status in {"executing", "completed"}:
            return True
    return False


def execute_plan_should_duplicate(plan: dict[str, Any], values: dict[str, Any]) -> bool:
    """Duplicate only when a handoff succeeded and work is actually running."""
    return handoff_already_started(plan) and work_execution_underway(values)


def mark_handoff_requested(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        **plan,
        "execution_requested_at": _utc_now_iso(),
        "execution_handoff_failed": False,
        "execution_handoff_error": None,
        "execution_handoff_failed_at": None,
    }


def mark_handoff_succeeded(plan: dict[str, Any]) -> dict[str, Any]:
    started_at = _utc_now_iso()
    status = str(plan.get("status") or "").strip().lower()
    next_status = "executing" if status == "approved" else status
    return {
        **plan,
        "status": next_status,
        "execution_handoff_started": True,
        "execution_handoff_started_at": started_at,
        "execution_requested_at": plan.get("execution_requested_at") or started_at,
        "execution_handoff_failed": False,
        "execution_handoff_error": None,
        "execution_handoff_failed_at": None,
    }


def mark_handoff_failed(plan: dict[str, Any], error: str | None = None) -> dict[str, Any]:
    message = str(error or "").strip()[:500]
    return {
        **plan,
        "execution_handoff_started": False,
        "execution_handoff_started_at": None,
        "execution_handoff_failed": True,
        "execution_handoff_failed_at": _utc_now_iso(),
        "execution_handoff_error": message or None,
    }


def mark_handoff_started(plan: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias for successful handoff completion."""
    return mark_handoff_succeeded(plan)


def should_spawn_work_handoff(
    plan: dict[str, Any],
    *,
    plan_behavior: str,
    plan_status: str,
) -> bool:
    if plan_behavior != "plan_foreground":
        return False
    if plan_status not in {"approved"}:
        return False
    if handoff_already_started(plan):
        return False
    if bool(plan.get("clarification_pending")) and not all_clarifications_resolved(plan):
        return False
    return True


def _option_labels(clarification: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for option in clarification.get("options") or []:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "").strip()
        if label:
            labels.append(label)
    return labels


def _match_answer_to_option(answer_text: str, clarification: dict[str, Any]) -> tuple[str, str | None] | None:
    normalized_answer = _normalize_answer_text(answer_text)
    if not normalized_answer:
        return None

    if normalized_answer.startswith(_normalize_answer_text(_AUTO_MODE_PREFIX)):
        selected = answer_text.split(":", 1)[-1].strip()
        if selected:
            return selected, None

    for option in clarification.get("options") or []:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "").strip()
        if not label:
            continue
        normalized_label = _normalize_answer_text(label)
        if normalized_answer == normalized_label or normalized_label in normalized_answer or normalized_answer in normalized_label:
            description = option.get("description")
            return label, str(description).strip() if description else None

    # Unstructured or legacy clarifications without options: accept substantive free text.
    if len(normalized_answer) >= 3 and not _option_labels(clarification):
        return answer_text.strip(), None

    # Accept substantive free-text replies when options exist but text doesn't match exactly.
    if len(normalized_answer) >= 3 and _option_labels(clarification):
        return answer_text.strip(), None
    return None


def _answer_after_last_marker(messages: list[Any]) -> str | None:
    last_marker_idx = -1
    for idx, message in enumerate(messages):
        if _is_clarification_marker(message):
            last_marker_idx = idx

    if last_marker_idx < 0:
        return None

    last_marker = messages[last_marker_idx]
    marker_text = extract_text(_message_content(last_marker)).strip()
    if marker_text.startswith(_AUTO_MODE_PREFIX):
        return marker_text

    for message in messages[last_marker_idx + 1 :]:
        if message_type(message) != "human":
            continue
        if is_synthetic_human_message(message):
            continue
        text = extract_text(_message_content(message)).strip()
        if text:
            return text
    return None


def has_answer_for_current_question(plan: dict[str, Any], messages: list[Any]) -> bool:
    clarification = current_clarification(plan)
    if clarification is None:
        return False
    answer_text = _answer_after_last_marker(messages)
    if not answer_text:
        return False
    return _match_answer_to_option(answer_text, clarification) is not None


def pending_clarification_answered(messages: list[Any]) -> bool:
    """Backward-compatible: true when the latest clarification marker has a follow-up answer."""
    if not messages:
        return False
    last_marker_idx = -1
    for idx, message in enumerate(messages):
        if _is_clarification_marker(message):
            last_marker_idx = idx
    if last_marker_idx < 0:
        return False
    last_marker = messages[last_marker_idx]
    last_marker_text = extract_text(_message_content(last_marker))
    if last_marker_text.strip().startswith(_AUTO_MODE_PREFIX):
        return True
    for message in messages[last_marker_idx + 1 :]:
        if message_type(message) != "human":
            continue
        if is_synthetic_human_message(message):
            continue
        text = extract_text(_message_content(message))
        if text.strip():
            return True
    return False


def build_clarification_prompt_message(clarification: dict[str, Any]) -> HumanMessage:
    structured_options = [
        {
            "label": str(option.get("label") or "").strip(),
            "recommended": bool(option.get("recommended", False)),
            "description": option.get("description"),
        }
        for option in (clarification.get("options") or [])
        if isinstance(option, dict) and str(option.get("label") or "").strip()
    ]
    return HumanMessage(
        name="planner_clarification_required",
        content=(
            "<planner_clarification>\n"
            "Before any execution, ask the user this clarification via `ask_clarification`.\n"
            f"Question: {clarification.get('question')}\n"
            "IMPORTANT: pass options as structured dicts; do NOT flatten to plain strings.\n"
            f"Options JSON: {json.dumps(structured_options, ensure_ascii=False)}\n"
            "</planner_clarification>"
        ),
    )


def format_clarification_context_for_work(plan: dict[str, Any]) -> str:
    answers = plan.get("clarification_answers")
    if not isinstance(answers, list) or not answers:
        return ""
    lines: list[str] = []
    for entry in answers:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "").strip()
        label = str(entry.get("selected_label") or "").strip()
        if question and label:
            lines.append(f"- {question} → {label}")
    if not lines:
        return ""
    return "User clarifications:\n" + "\n".join(lines)


def resolve_original_user_request(values: dict[str, Any]) -> str | None:
    messages = values.get("messages")
    if isinstance(messages, list):
        prompt = original_user_prompt(messages)
        if prompt.strip():
            return prompt
    return None


def resolve_auto_mode(values: dict[str, Any], *, request_auto_mode: bool | None = None) -> bool:
    if request_auto_mode is not None:
        return bool(request_auto_mode)
    if bool(values.get("auto_mode")):
        return True
    return False


def apply_clarification_progress(
    plan: dict[str, Any],
    messages: list[Any],
) -> dict[str, Any] | None:
    """Record an answer for the active question and advance or finish clarification."""
    if not bool(plan.get("clarification_pending")):
        return None
    if not has_answer_for_current_question(plan, messages):
        return None

    clarification = current_clarification(plan)
    if clarification is None:
        return None

    answer_text = _answer_after_last_marker(messages)
    if not answer_text:
        return None
    matched = _match_answer_to_option(answer_text, clarification)
    if matched is None:
        return None
    selected_label, selected_description = matched

    existing_answers = [
        entry for entry in (plan.get("clarification_answers") or []) if isinstance(entry, dict)
    ]
    question_text = str(clarification.get("question") or "").strip()
    existing_answers.append(
        {
            "question": question_text,
            "selected_label": selected_label,
            "selected_description": selected_description,
            "answered_at": _utc_now_iso(),
        }
    )

    clarifications = _clarifications_list(plan)
    next_index = clarification_index(plan) + 1
    resolved_plan: dict[str, Any] = {
        **plan,
        "clarification_answers": existing_answers,
        "clarification_answered_at": _utc_now_iso(),
    }

    payload: dict[str, Any] = {"plan": resolved_plan}
    if next_index < len(clarifications):
        next_clarification = clarifications[next_index]
        resolved_plan.update(
            {
                "clarification_index": next_index,
                "clarification_pending": True,
                "clarification_resolved": False,
                "clarification_question": str(next_clarification.get("question") or "").strip(),
            }
        )
        payload["messages"] = [build_clarification_prompt_message(next_clarification)]
        return payload

    resolved_plan.update(
        {
            "clarification_index": next_index,
            "clarification_pending": False,
            "clarification_resolved": True,
            "clarification_question": None,
        }
    )
    return payload


def approve_plan_if_auto_mode(plan: dict[str, Any], *, auto_mode: bool) -> dict[str, Any]:
    if not auto_mode:
        return plan
    if str(plan.get("status") or "").strip().lower() != "draft":
        return plan
    return {
        **plan,
        "status": "approved",
        "approved_at": _utc_now_iso(),
        "awaiting_execution_approval": False,
    }
