"""Dispatch sub-questions to the vault-source-researcher subagent.

We run subagents directly through ``SubagentExecutor`` (not through the
``task`` tool) because the autoresearch loop fires from the control plane,
outside any agent conversation.

Researchers are fanned out via a bounded ``ThreadPoolExecutor`` so wall-time
per iteration stays O(ceil(N / fanout)) rather than O(N) — important because
the iteration runs inside a pipeline-run step that blocks downstream work.
"""

from __future__ import annotations

import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ResearchOutcome:
    question_id: str
    status: str            # "answered" | "blocked"
    summary: str           # one-paragraph paraphrase of vault entry
    sources_used: int
    vault_entries: list[str]
    error: str | None


def _build_task_prompt(*, topic: str, endpoint_goal: str, question: str) -> str:
    return (
        "You are researching ONE sub-question for an ongoing autoresearch objective.\n\n"
        f"Topic (use as the `topic` argument to save_to_knowledge_vault): {topic}\n"
        f"Overall objective: {endpoint_goal}\n\n"
        f"Sub-question to answer: {question}\n\n"
        "Investigate, save your answer using save_to_knowledge_vault exactly once, "
        "then return the JSON object described in your instructions."
    )


def _parse_subagent_result(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    text = raw.strip()
    if text.startswith("```"):
        # Strip fences if present
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return {}


def _run_one(
    *,
    question: dict[str, Any],
    topic: str,
    endpoint_goal: str,
    thread_id: str,
    tools: list[Any],
) -> tuple[str, ResearchOutcome]:
    from src.subagents.builtins import VAULT_SOURCE_RESEARCHER_CONFIG
    from src.subagents.executor import SubagentExecutor, SubagentStatus

    question_id = str(question.get("id") or "")
    question_text = str(question.get("content") or "").strip()
    if not question_id or not question_text:
        return question_id, ResearchOutcome(
            question_id=question_id,
            status="blocked",
            summary="",
            sources_used=0,
            vault_entries=[],
            error="empty question",
        )

    trace_id = uuid.uuid4().hex[:8]
    executor = SubagentExecutor(
        config=VAULT_SOURCE_RESEARCHER_CONFIG,
        tools=tools,
        parent_model=None,
        sandbox_state=None,
        thread_data=None,
        thread_id=thread_id,
        trace_id=trace_id,
        # Autoresearch runs without a user, so "ask" permission rules can't be resolved.
        # Bypass the parent's permission filter; the SubagentConfig allow-list
        # (web_search, save_to_knowledge_vault) is the only gate.
        enforce_permissions=False,
    )

    task_prompt = _build_task_prompt(topic=topic, endpoint_goal=endpoint_goal, question=question_text)

    try:
        result = executor.execute(task_prompt)
    except Exception as exc:
        logger.exception("autoresearch researcher: executor crashed for %s", question_id)
        return question_id, ResearchOutcome(
            question_id=question_id,
            status="blocked",
            summary="",
            sources_used=0,
            vault_entries=[],
            error=str(exc),
        )

    if result.status != SubagentStatus.COMPLETED:
        return question_id, ResearchOutcome(
            question_id=question_id,
            status="blocked",
            summary="",
            sources_used=0,
            vault_entries=[],
            error=result.error or f"subagent status={result.status.value}",
        )

    parsed = _parse_subagent_result(result.result)
    status_raw = str(parsed.get("status") or "").lower()
    is_answered = status_raw in {"succeeded", "partial"}

    return question_id, ResearchOutcome(
        question_id=question_id,
        status="answered" if is_answered else "blocked",
        summary=" ".join(
            str(item) for item in (parsed.get("key_findings") or []) if str(item).strip()
        )[:1000],
        sources_used=int(parsed.get("source_count") or 0),
        vault_entries=[str(parsed.get("vault_title") or "").strip()]
        if parsed.get("vault_title")
        else [],
        error=str(parsed.get("uncertainty") or "") if not is_answered else None,
    )


def dispatch_questions(
    *,
    topic: str,
    endpoint_goal: str,
    questions: list[dict[str, Any]],
    thread_id: str,
    max_fanout: int = 3,
) -> dict[str, ResearchOutcome]:
    """Run the vault-source-researcher subagent for each question in parallel.

    ``max_fanout`` bounds concurrent subagents. Each subagent runs in its own
    thread; ``SubagentExecutor.execute`` opens its own asyncio loop, so the
    threads do not contend on a shared event loop.

    Returns a mapping ``question_id -> ResearchOutcome``. Questions that fail
    are returned with status ``"blocked"`` and a populated ``error``.
    """
    if not questions:
        return {}

    # Late imports keep the loop module light at startup and avoid circulars.
    from src.tools import get_available_tools

    try:
        tools = get_available_tools(model_name=None, subagent_enabled=False)
    except Exception:
        logger.exception("autoresearch researcher: failed to load tools")
        return {
            str(q.get("id")): ResearchOutcome(
                question_id=str(q.get("id")),
                status="blocked",
                summary="",
                sources_used=0,
                vault_entries=[],
                error="tool loading failed",
            )
            for q in questions
        }

    fanout = max(1, int(max_fanout))
    results: dict[str, ResearchOutcome] = {}
    with ThreadPoolExecutor(max_workers=fanout, thread_name_prefix="autoresearch-researcher-") as pool:
        futures = {
            pool.submit(
                _run_one,
                question=question,
                topic=topic,
                endpoint_goal=endpoint_goal,
                thread_id=thread_id,
                tools=tools,
            ): str(question.get("id") or "")
            for question in questions
        }
        for future in as_completed(futures):
            question_id = futures[future]
            try:
                qid, outcome = future.result()
            except Exception as exc:
                logger.exception("autoresearch researcher: future raised for %s", question_id)
                results[question_id] = ResearchOutcome(
                    question_id=question_id,
                    status="blocked",
                    summary="",
                    sources_used=0,
                    vault_entries=[],
                    error=str(exc),
                )
            else:
                results[qid] = outcome

    return results
