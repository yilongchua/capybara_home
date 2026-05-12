from __future__ import annotations

import re
from typing import NotRequired, TypedDict, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.agents.middlewares.runtime_events import append_runtime_event


class DreamyIntent(TypedDict):
    shape: str
    intent_class: str
    confidence: float
    extracted_fields: list[str]
    inferred_goal: str
    workflow_requested: bool


class DreamyIntentState(AgentState):
    dreamy_mode: NotRequired[bool]
    dreamy_intent: NotRequired[DreamyIntent]


class DreamyIntentMiddleware(AgentMiddleware[DreamyIntentState]):
    """Detect explicit /workflow invocation and structural shape of user input."""

    state_schema = DreamyIntentState

    _CSV_SPLIT_RE = re.compile(r"\s*,\s*")

    @staticmethod
    def _strip_workflow_command(text: str) -> str:
        stripped = text.lstrip()
        if not stripped.startswith("/workflow"):
            return text
        remainder = stripped[len("/workflow"):]
        if remainder.startswith("\n"):
            remainder = remainder[1:]
        return remainder.lstrip()

    @staticmethod
    def _is_dreamy_mode(runtime: Runtime) -> bool:
        context = getattr(runtime, "context", None)
        if not isinstance(context, dict):
            return False
        return bool(context.get("dreamy_mode", False))

    @staticmethod
    def _extract_human_text(state: DreamyIntentState) -> str:
        messages = state.get("messages", []) or []
        for msg in reversed(messages):
            if getattr(msg, "type", None) != "human":
                continue
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(str(part.get("text", "")))
                return "\n".join(parts)
            return str(content)
        return ""

    def _extract_fields(self, text: str) -> list[str]:
        text = self._strip_workflow_command(text)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return []
        if "|" in lines[0]:
            first = [c.strip() for c in lines[0].strip("|").split("|")]
            if len(first) >= 2:
                return [c for c in first if c]
        if "," in lines[0]:
            first = [c.strip() for c in self._CSV_SPLIT_RE.split(lines[0])]
            if len(first) >= 2:
                return [c for c in first if c]
        return []

    def _detect_shape(self, text: str) -> str:
        if not text.strip():
            return "free_text"
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        has_table = len([ln for ln in lines if "|" in ln]) >= 2
        has_csv = len([ln for ln in lines if ln.count(",") >= 1]) >= 2
        has_list = len([ln for ln in lines if ln.startswith("- ") or re.match(r"^\d+[.)]\s+", ln)]) >= 2
        count = sum([has_table, has_csv, has_list])
        if count >= 2:
            return "mixed"
        if has_table:
            return "table"
        if has_csv:
            return "csv"
        if has_list:
            return "list"
        return "free_text"

    @override
    def before_agent(self, state: DreamyIntentState, runtime: Runtime) -> dict | None:
        if not self._is_dreamy_mode(runtime):
            return None

        text = self._extract_human_text(state)
        workflow_requested = text.lstrip().startswith("/workflow")
        shape = self._detect_shape(text)
        fields = self._extract_fields(text)

        intent: DreamyIntent = {
            "shape": shape,
            "intent_class": "explicit_workflow" if workflow_requested else "none",
            "confidence": 1.0 if workflow_requested else 0.0,
            "extracted_fields": fields,
            "inferred_goal": "",
            "workflow_requested": workflow_requested,
        }

        append_runtime_event(
            runtime,
            {
                "source": "dreamy_intent",
                "event": "dreamy_intent_detected",
                "phase": "dreamy_intent_detected",
                "workflow_requested": workflow_requested,
                "shape": shape,
                "extracted_fields": fields,
            },
        )
        return {"dreamy_mode": True, "dreamy_intent": intent}
