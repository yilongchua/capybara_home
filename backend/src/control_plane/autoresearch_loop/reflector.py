"""Reflector: read recent answers and propose follow-up sub-questions.

Runs after the researchers report back. The reflector reads each ``answered``
question's ``researcher_summary`` and produces (a) follow-up questions that
naturally fall out of the new information and (b) a short assessment of
whether the iteration produced novel learning.
"""

from __future__ import annotations

import logging
from typing import Any

from .llm import invoke_json

logger = logging.getLogger(__name__)


REFLECTOR_PROMPT = """You are the reflection step of an autoresearch loop.
Given a set of sub-questions that were just answered and a short summary of each finding,
propose follow-up sub-questions that a curious person with a strong understanding would naturally ask next.

# Topic
{topic}

# Objective
{endpoint_goal}

# Answered sub-questions and findings
{findings_block}

# Instructions
- Produce UP TO {max_followups} NEW follow-up questions.
- Each follow-up MUST be directly motivated by one of the findings above. Reference the parent question's id in the `parent_id` field.
- Phrase each question as a human would search for it. Be specific. Avoid generic restatements.
- Skip filler questions ("tell me more about X"). Only propose follow-ups that ask something genuinely new.
- Also produce a short overall reflection: did the new findings change the picture, or mostly confirm what was already known?

# Output format
Return ONLY a JSON object:
{{
  "followups": [
    {{
      "content": "natural-language question",
      "parent_id": "<question id from above>",
      "cluster": <int 1-12 or 0 if unsure>,
      "level": <int 1|2|3>,
      "rationale": "one sentence on why"
    }}
  ],
  "reflection": "1-3 sentence overall note on novelty / surprises / open threads"
}}
"""


def _format_findings(answered: list[dict[str, Any]]) -> str:
    if not answered:
        return "(no findings this iteration)"
    rows: list[str] = []
    for node in answered:
        qid = str(node.get("id") or "")
        question = str(node.get("content") or "").strip()
        summary = str(node.get("researcher_summary") or "").strip()
        rows.append(f"- [{qid}] Q: {question}\n  Findings: {summary[:800]}")
    return "\n".join(rows)


def reflect(
    *,
    topic: str,
    endpoint_goal: str,
    answered_nodes: list[dict[str, Any]],
    max_followups: int,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Ask the LLM for follow-up questions plus a short reflection note.

    Returns ``{"followups": [...], "reflection": "..."}``. On failure returns
    empty lists and an empty string.
    """
    if not answered_nodes:
        return {"followups": [], "reflection": ""}

    prompt = REFLECTOR_PROMPT.format(
        topic=topic.strip(),
        endpoint_goal=endpoint_goal.strip(),
        findings_block=_format_findings(answered_nodes),
        max_followups=int(max_followups),
    )

    payload = invoke_json(prompt, model_name=model_name)
    if not isinstance(payload, dict):
        return {"followups": [], "reflection": ""}

    raw_followups = payload.get("followups") or []
    followups: list[dict[str, Any]] = []
    if isinstance(raw_followups, list):
        for raw in raw_followups:
            if not isinstance(raw, dict):
                continue
            content = str(raw.get("content") or "").strip()
            if not content:
                continue
            try:
                cluster = int(raw.get("cluster") or 0)
                level = int(raw.get("level") or 1)
            except (TypeError, ValueError):
                cluster, level = 0, 1
            if level not in (1, 2, 3):
                level = 1
            followups.append(
                {
                    "content": content,
                    "cluster": cluster,
                    "level": level,
                    "parent_id": str(raw.get("parent_id") or "").strip(),
                    "rationale": str(raw.get("rationale") or "").strip(),
                }
            )
            if len(followups) >= max_followups:
                break

    return {
        "followups": followups,
        "reflection": str(payload.get("reflection") or "").strip(),
    }
