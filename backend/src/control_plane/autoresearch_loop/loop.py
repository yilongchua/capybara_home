"""Single-iteration driver for the autoresearch agentic loop.

Called from the scheduler / pipeline-run path. One call = one iteration:

    1. Load ledger + taxonomy + coverage.
    2. Generator proposes new sub-questions.
    3. Dedup against ledger + vault.
    4. Researcher subagent fans out per surviving question and writes vault.
    5. Reflector reads new answers and proposes follow-ups.
    6. Ledger is updated; iteration summary is recorded.
    7. Novelty decay is computed; ``stop`` is set if saturated.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .dedup import classify_questions
from .generator import generate_questions
from .ledger import QuestionLedger
from .reflector import reflect
from .researcher import dispatch_questions
from .stop_criteria import should_stop
from .taxonomy import load_taxonomy

logger = logging.getLogger(__name__)


def run_one_iteration(
    *,
    vault_root: Path,
    objective_slug: str,
    topic: str,
    endpoint_goal: str,
    thread_id: str,
    max_questions: int,
    max_followups: int,
    max_researcher_fanout: int,
    novelty_decay_threshold: float,
    novelty_window: int,
    dedup_similarity_threshold: float,
    model_name: str | None = None,
    vault_search: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Execute exactly one autoresearch loop iteration.

    Returns a structured iteration summary; also persists to the ledger.
    The returned dict has a ``stop`` boolean and ``reason`` so the caller can
    flip the objective to ``completed_endpoint``.
    """
    ledger = QuestionLedger(vault_root=vault_root, objective_slug=objective_slug)
    state = ledger.load()
    previous_iteration = int(state.get("loop_iteration") or 0)
    current_iteration = previous_iteration + 1
    taxonomy = load_taxonomy(vault_root)
    existing = list(state.get("questions") or [])
    coverage = ledger.cluster_coverage()
    recent = ledger.recent_questions(limit=15)

    # 1. Generator
    candidates = generate_questions(
        topic=topic,
        endpoint_goal=endpoint_goal,
        taxonomy=taxonomy,
        coverage=coverage,
        recent_questions=recent,
        max_questions=max_questions,
        model_name=model_name,
    )

    # If the generator returned nothing (LLM unreachable, no models configured,
    # malformed JSON, etc.), do not advance the iteration counter or write a
    # phantom "0/0/0" iteration entry. The next scheduled run will retry.
    if not candidates:
        logger.warning(
            "autoresearch loop: generator returned no candidates for %s — skipping iteration",
            objective_slug,
        )
        coverage_after = {str(cid): depth for cid, depth in coverage.items()}
        return {
            "iteration": previous_iteration,
            "ledger_path": str(ledger.md_path),
            "generated": 0,
            "answered": 0,
            "duplicates": 0,
            "blocked": 0,
            "followups": 0,
            "novelty_rate": 1.0,
            "stop": False,
            "stop_reason": "generator_empty",
            "reflection": "",
            "cluster_coverage": coverage_after,
        }

    # 2. Dedup
    verdicts = classify_questions(
        candidates=candidates,
        existing_questions=existing,
        similarity_threshold=dedup_similarity_threshold,
        vault_lookup=vault_search,
    )

    items_to_append: list[dict[str, Any]] = []
    for cand, verdict in verdicts:
        node: dict[str, Any] = {
            "content": cand["content"],
            "cluster": cand.get("cluster", 0),
            "level": cand.get("level", 1),
            "asked_by": "generator",
            "novelty": float(verdict.novelty),
            "status": "duplicate" if verdict.is_duplicate else "pending",
            "duplicate_of": verdict.duplicate_of,
        }
        items_to_append.append(node)
    added = ledger.append_questions(
        items=items_to_append,
        loop_iteration=current_iteration,
        topic=topic,
        endpoint_goal=endpoint_goal,
    )

    # 3. Dispatch researchers for the survivors
    survivors = [node for node in added if node["status"] == "pending"]
    for node in survivors:
        ledger.update_question(
            node["id"],
            status="in_progress",
            topic=topic,
            endpoint_goal=endpoint_goal,
        )

    outcomes = dispatch_questions(
        topic=topic,
        endpoint_goal=endpoint_goal,
        questions=[{"id": n["id"], "content": n["content"]} for n in survivors],
        thread_id=thread_id,
        max_fanout=max_researcher_fanout,
    )

    answered_nodes: list[dict[str, Any]] = []
    for node in survivors:
        outcome = outcomes.get(node["id"])
        if outcome is None:
            ledger.update_question(
                node["id"],
                status="blocked",
                error="no outcome returned",
                topic=topic,
                endpoint_goal=endpoint_goal,
            )
            continue
        updated = ledger.update_question(
            node["id"],
            status=outcome.status,
            researcher_summary=outcome.summary,
            sources_used=outcome.sources_used,
            vault_entries=outcome.vault_entries,
            error=outcome.error,
            topic=topic,
            endpoint_goal=endpoint_goal,
        )
        if updated and updated.get("status") == "answered":
            answered_nodes.append(updated)

    # 4. Reflector
    reflection = reflect(
        topic=topic,
        endpoint_goal=endpoint_goal,
        answered_nodes=answered_nodes,
        max_followups=max_followups,
        model_name=model_name,
    )

    followups = reflection.get("followups") or []
    if followups:
        # Reuse dedup against the now-larger ledger.
        followup_existing = ledger.questions()
        followup_verdicts = classify_questions(
            candidates=followups,
            existing_questions=followup_existing,
            similarity_threshold=dedup_similarity_threshold,
            vault_lookup=vault_search,
        )
        ledger.append_questions(
            items=[
                {
                    "content": cand["content"],
                    "cluster": cand.get("cluster", 0),
                    "level": cand.get("level", 1),
                    "asked_by": "reflector",
                    "novelty": float(fv.novelty),
                    "status": "duplicate" if fv.is_duplicate else "pending",
                    "duplicate_of": fv.duplicate_of,
                    "depends_on": [cand["parent_id"]] if cand.get("parent_id") else [],
                }
                for cand, fv in followup_verdicts
            ],
            loop_iteration=current_iteration,
            topic=topic,
            endpoint_goal=endpoint_goal,
        )

    # 5. Stop check
    fresh_questions = ledger.questions()
    stop, novelty_rate, reason = should_stop(
        questions=fresh_questions,
        novelty_decay_threshold=novelty_decay_threshold,
        window=novelty_window,
    )

    # Cluster coverage AFTER this iteration's writes — Pydantic on the orchestrator
    # side stores dict[str, int], so stringify the keys here.
    coverage_after = {str(cluster_id): depth for cluster_id, depth in ledger.cluster_coverage().items()}

    summary = {
        "generated": len(added),
        "answered": len(answered_nodes),
        "duplicates": sum(1 for node in added if node["status"] == "duplicate"),
        "blocked": sum(1 for node in added if node["status"] == "blocked"),
        "followups": len(followups),
        "novelty_rate": novelty_rate,
        "stop": stop,
        "stop_reason": reason,
        "reflection": reflection.get("reflection", ""),
        "cluster_coverage": coverage_after,
    }
    ledger.record_iteration(
        loop_iteration=current_iteration,
        summary=summary,
        topic=topic,
        endpoint_goal=endpoint_goal,
    )

    return {
        "iteration": current_iteration,
        "ledger_path": str(ledger.md_path),
        **summary,
    }
