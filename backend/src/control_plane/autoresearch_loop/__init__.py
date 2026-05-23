"""Agentic autoresearch learning loop.

Replaces the legacy template-based pipeline with a generator / researcher /
reflector loop. Each scheduled run executes one iteration:

    1. Load (or seed) the question taxonomy from the vault.
    2. Generator LLM proposes new sub-questions across uncovered clusters.
    3. Dedup against existing ledger + vault entries.
    4. Dispatch surviving questions to the ``vault-source-researcher`` subagent.
    5. Reflector LLM extracts follow-up questions from new answers.
    6. Update ledger; compute novelty rate; signal stop if saturated.
"""

from .ledger import QuestionLedger, QuestionNode
from .loop import run_one_iteration
from .stop_criteria import compute_novelty_rate, should_stop
from .taxonomy import (
    DEFAULT_TAXONOMY,
    TAXONOMY_FILENAME,
    Cluster,
    load_taxonomy,
    seed_taxonomy_if_missing,
)

__all__ = [
    "QuestionNode",
    "QuestionLedger",
    "run_one_iteration",
    "compute_novelty_rate",
    "should_stop",
    "DEFAULT_TAXONOMY",
    "TAXONOMY_FILENAME",
    "Cluster",
    "load_taxonomy",
    "seed_taxonomy_if_missing",
]
