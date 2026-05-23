"""Generator: propose new sub-questions for the autoresearch loop."""

from __future__ import annotations

import logging
from typing import Any

from .llm import invoke_json
from .taxonomy import Cluster

logger = logging.getLogger(__name__)


def _format_taxonomy(taxonomy: list[Cluster]) -> str:
    lines = []
    for cluster in taxonomy:
        lines.append(
            f"- C{cluster.id} {cluster.name}: {cluster.description}\n"
            f"    L1: {cluster.level_1}\n"
            f"    L2: {cluster.level_2}\n"
            f"    L3: {cluster.level_3}"
        )
    return "\n".join(lines)


def _format_coverage(coverage: dict[int, int], taxonomy: list[Cluster]) -> str:
    rows: list[str] = []
    for cluster in taxonomy:
        depth = coverage.get(cluster.id, 0)
        marker = "empty" if depth == 0 else f"deepest=L{depth}"
        rows.append(f"  C{cluster.id} {cluster.name}: {marker}")
    return "\n".join(rows)


def _format_recent(recent: list[dict[str, Any]]) -> str:
    if not recent:
        return "(no prior questions)"
    rows: list[str] = []
    for node in recent[-15:]:
        status = node.get("status", "?")
        cluster = node.get("cluster") or "?"
        level = node.get("level") or "?"
        rows.append(f"- [{status}] C{cluster}L{level} {node.get('content','').strip()[:160]}")
    return "\n".join(rows)


GENERATOR_PROMPT = """You generate sub-questions for an autoresearch loop. The loop's job is to anticipate the questions a curious human would ask about a topic and pre-fill a knowledge vault before they search.

# Topic
{topic}

# Overall objective
{endpoint_goal}

# Question taxonomy (12 clusters x 3 depth levels)
{taxonomy_block}

# Current coverage of this topic
{coverage_block}

# Recently generated / answered questions (for context, do not duplicate)
{recent_block}

# Instructions
- Produce UP TO {max_questions} NEW sub-questions that a human might genuinely search for.
- PRIORITISE clusters where coverage is empty (`empty`). Within those, start at L1.
- For clusters already at L1, push to L2; for L2, push to L3.
- Skip clusters that are nonsensical for this topic (e.g. cluster 5 "Geography" for a purely abstract concept).
- Each question must be:
  - PHRASED THE WAY A HUMAN WOULD TYPE IT in a search box. Use natural language, not bureaucratic phrasing.
  - SPECIFIC to the topic. Reject vague filler like "What about X?".
  - INDEPENDENT — answerable in isolation by one short research pass.
- Do NOT restate the topic verbatim as a question.
- Do NOT duplicate the recent questions above.

# Output format
Return ONLY a JSON object with this shape (no prose, no markdown):
{{
  "questions": [
    {{
      "content": "the question, as a human would search",
      "cluster": <int cluster id>,
      "level": <int 1|2|3>,
      "rationale": "one short sentence explaining why this matters now"
    }},
    ...
  ]
}}
"""


def generate_questions(
    *,
    topic: str,
    endpoint_goal: str,
    taxonomy: list[Cluster],
    coverage: dict[int, int],
    recent_questions: list[dict[str, Any]],
    max_questions: int,
    model_name: str | None = None,
) -> list[dict[str, Any]]:
    """Ask the LLM for up to ``max_questions`` new sub-questions.

    Returns a list of dicts with keys ``content``, ``cluster``, ``level``,
    ``rationale``. Returns an empty list on any failure — the caller should
    treat that as "no new questions this iteration".
    """
    prompt = GENERATOR_PROMPT.format(
        topic=topic.strip(),
        endpoint_goal=endpoint_goal.strip(),
        taxonomy_block=_format_taxonomy(taxonomy),
        coverage_block=_format_coverage(coverage, taxonomy),
        recent_block=_format_recent(recent_questions),
        max_questions=int(max_questions),
    )

    payload = invoke_json(prompt, model_name=model_name)
    if not isinstance(payload, dict):
        return []

    raw_questions = payload.get("questions") or []
    if not isinstance(raw_questions, list):
        return []

    cluster_ids = {cluster.id for cluster in taxonomy}
    out: list[dict[str, Any]] = []
    seen_content: set[str] = set()
    for raw in raw_questions:
        if not isinstance(raw, dict):
            continue
        content = str(raw.get("content") or "").strip()
        if not content:
            continue
        key = content.lower()
        if key in seen_content:
            continue
        seen_content.add(key)
        try:
            cluster = int(raw.get("cluster") or 0)
            level = int(raw.get("level") or 1)
        except (TypeError, ValueError):
            cluster, level = 0, 1
        if cluster not in cluster_ids:
            cluster = 0
        if level not in (1, 2, 3):
            level = 1
        out.append(
            {
                "content": content,
                "cluster": cluster,
                "level": level,
                "rationale": str(raw.get("rationale") or "").strip(),
            }
        )
        if len(out) >= max_questions:
            break
    return out
