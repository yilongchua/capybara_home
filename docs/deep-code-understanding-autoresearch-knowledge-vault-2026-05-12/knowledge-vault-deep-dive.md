# Knowledge Vault Deep Dive

## Main Runtime Owner

File: `backend/src/control_plane/vault_learning.py`

`VaultLearningManager` is the primary implementation for discover/ingest/compile/lint/sufficiency/search.

## Directory and State Layout

Created/maintained in constructor:
- `00_schema/` policy docs
- `01_raw/` source packages
- `02_compiled/` compiled markdown knowledge pages
- `03_ops/` reports/queues/tasks/quarantine
- `.vault_state/manifest.json` (versioned manifest with loop guard + objective state)

Manifest tracks:
- sources, queries, candidates, trust decisions
- dirty pages + dependencies + search index
- topic syntheses + objectives + action history
- loop guard fingerprints and coverage/sufficiency signals

## Pipeline Step Behavior via KnowledgeVaultAgent

File: `backend/src/control_plane/agents/knowledge_vault_agent.py`

- `_execution_profile()` infers `continuous` vs `autoresearch` mode.
- Discover/ingest can skip if workspace inactive (`stop_if_inactive`).
- Discover applies loop guard check before network work.
- Ingest can pull from explicit URLs and/or queued search results.
- Compile regenerates indexes/log.
- Lint evaluates freshness/orphans/backlinks/contradictions/queue backlog.
- Synthesis writes topic graph syntheses.
- Sufficiency scores objective and can recommend/trigger scheduler pause.

## Key Manager Capabilities

### Discovery and queueing
- `discover()` filters URL inputs (scheme/domain rules), writes inbox report, records candidates.
- `enqueue_search_results()` accepts extracted content payloads into ingestion queue with dedupe windows.
- `claim_search_queue_items()` claims queue records for ingest runs.

### Ingestion and curation
- `ingest()` fetches/uses extracted content, computes trust, writes raw package + compiled pages.
- `_trust_score()` + `_record_trust_decision()` gate low-trust content.
- `reingest_if_changed()` detects source deltas and updates dependent compiled pages.

### Compile and maintenance
- `compile_incremental()` and `compile_indexes()` update global indexes.
- `lint_vault()` + `_collect_lint_snapshot()` produce maintenance diagnostics.

### Sufficiency and progress
- `synthesize_knowledge_graph()` updates objective/topic synthesis pages.
- `evaluate_sufficiency()` computes score/decision/blockers/actions and auto-pause recommendation.
- `get_coverage_progress()` and `_coverage_progress()` provide objective progress percentages.
- `get_action_items()` derives prioritized actionable backlog.

### Retrieval
- `search()` returns ranked compiled-page results.
- Community tool path also exists (`query_knowledge_vault`) with BM25 implementation in:
- `backend/src/community/knowledge_vault_search/search.py`
- wrapper tool in `backend/src/community/knowledge_vault_search/tool.py`

## Search System Notes

Community search uses on-demand disk reads of compiled markdown pages and BM25 scoring:
- categories: `sources`, `entities`, `concepts`, `syntheses`, `queries`
- title/tags are included in searchable text for relevance boost
- excerpt generation centers around first token hit
- tool validates categories and clamps limit to 1..20
