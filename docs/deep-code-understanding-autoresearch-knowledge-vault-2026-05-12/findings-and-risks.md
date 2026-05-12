# Findings and Risks

## High-Confidence Findings

- Autoresearch is integrated as a first-class objective lifecycle, not just a one-off pipeline trigger.
- Objective progress is dual-tracked in state snapshot and durable markdown/json ledgers.
- Sufficiency outcomes are wired back into objective status and scheduler control.
- Inactivity gating is designed to skip work without permanently disabling the daily schedule.
- Queue-based ingestion allows approval-driven or deferred ingestion from search results.
- Vault storage separates immutable raw evidence from curated compiled knowledge.

## Notable Design Strengths

- Strong separation of concerns:
- middleware (trigger UX)
- orchestrator (objective lifecycle)
- step agent (pipeline semantics)
- manager (content/state mechanics)
- observable operational artifacts in `03_ops/reports` + objective progress markdown
- tests cover core lifecycle flows, search behavior, and loop-guard/queue mechanics

## Risks and Constraints

- `vault_learning.py` is very large and functionally dense; maintainability risk is concentrated in one module.
- Markdown percent parsing in UI depends on string format in progress ledger (`- Percent: ...`), creating a brittle contract.
- Some objective/scheduler coupling relies on metadata conventions (`objective_id`, `autoresearch_topic`, `first_run_for_objective`).
- Daily schedule naming currently hardcodes `"Autoresearch Daily 02:00 - ..."` in upsert path even when time changes (cosmetic inconsistency risk).
- Search relevance uses lightweight BM25 without semantic ranking; quality depends on token overlap and curation quality.

## Test Coverage Signals

Primary coverage anchors:
- `backend/tests/test_autoresearch_control_plane.py`
- `backend/tests/test_vault_learning.py`
- `backend/tests/test_vault_search.py`
- `backend/tests/test_control_plane_api.py`

Important verified behaviors include:
- objective start/pause/resume/delete
- endpoint completion auto-pausing scheduler
- inactivity skip keeping scheduler enabled
- queue dedupe + claim flow
- vault status/search/action item scaffolding

## Suggested Refactor Opportunities

- Split `VaultLearningManager` into focused modules:
- queue and dedupe
- ingestion/trust scoring
- compile/lint
- sufficiency/progress
- Replace UI markdown parsing with explicit progress API field if possible.
- Centralize objective metadata keys as constants to reduce hidden coupling.
