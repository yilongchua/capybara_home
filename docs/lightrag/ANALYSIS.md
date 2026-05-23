# LightRAG vs. Capybara Home Knowledge Vault — In-Depth Analysis

> Captured at the point of removal. References file paths and line numbers
> as they existed before the removal commit.

## 1. What was actually integrated

The "LightRAG integration" was much thinner than the agent prompts and
skills suggested.

### Tool wrapper

`backend/src/community/lightrag/tool.py` — 109 lines total:

- Read `knowledge_vault.lightrag.{enabled, base_url, timeout, default_mode, max_top_k}` from config.
- POSTed `{query, mode, top_k, filters}` to `/query` (falling back to
  `/v1/query`, `/api/query`) on `http://localhost:9621`.
- Returned whatever JSON the LightRAG server returned, unparsed.
- That was the entire integration surface. No ingestion, no schema
  translation, no provenance handling, no result merging with the vault.

### Where it was referenced in the agent

| Location | Role |
|---|---|
| `lead_agent/prompt.py:131-133, 243` | Listed as option #3 in `fetch_policy` for "graph-oriented, multi-hop relationship evidence when available". |
| `skills/knowledge-vault/SKILL.md` "Graph Evidence Mode" | One example query. |
| `phase_tool_filter_middleware.py:45` and `plan_execution_gate_middleware.py:57` | Gated as a search-class tool. |
| `web_search_circuit_breaker_middleware.py:107` | Suggested as a fallback when `web_search` kept failing. |
| `execution_trace_middleware.py:76` | Emitted trajectory traces. |
| `vault_learning.py:1966-2050` (`synthesize_knowledge_graph`) | Accepted a LightRAG payload via `graph_evidence`, but only read `summary` and `entities` *as freeform text*. Did not use graph structure. |
| `frontend/src/app/workspace/integrations/page.tsx` | Health tile alongside `llm` / `comfyui` / `websearch`. |
| `community/registry.py` | Listed in the tool registry. |

### Where the LightRAG server itself came from

**Nowhere in this repo.** `scripts/local-stack.sh` expected an external
clone at `$HOME/Desktop/LightRAG/docker-compose.yml` +
`docker-compose.infinity-standalone.yaml`. There was no LightRAG compose
file under `docker/`. Without that user-side clone, the `lightrag_compose`
function failed fast.

### Effective state at removal

In `config.yaml`, LightRAG was set `enabled: true`. The integration was
"disabled" only **operationally** — the LightRAG server stack wasn't part
of this repo and wasn't standing up reliably. The tool returned
`lightrag_query_failed` whenever the server was down. Effectively dead.

### Critical observation — there was no ingestion into LightRAG

A full-codebase search confirmed: **nothing in this repo wrote to
LightRAG**. The vault ingestion pipeline (`vault_learning.ingest`,
`_analyze_source`, `_update_reference_page`, `_update_synthesis_page`,
`compile_incremental`) only wrote markdown. So even if the LightRAG
server were running, it was empty (or populated by a separate,
out-of-band process). The agent's "Graph Evidence Mode" was querying a
graph the system never built.

## 2. What the current vault actually does ("the LLM wiki")

This is the part that makes the LightRAG decision asymmetric — the
existing system already implements most of what LightRAG provides, just
expressed as Obsidian-compatible markdown instead of a graph DB.

### Storage layout

`backend/.capybara-home/knowledge_vault/`:

- `00_schema/` — VAULT_SCHEMA, RESEARCH_POLICY, QUERY_RETENTION_POLICY.
- `01_raw/sources/YYYY/MM/{source-id}/` — raw fetched content.
- `02_compiled/{sources,entities,concepts,syntheses,queries}/*.md` — **the canonical graph**. Each page is markdown with YAML frontmatter holding typed cross-refs (`source_refs`, `concept_refs`, `entity_refs`, `synthesis_refs`).
- `02_compiled/{index.md, log.md}` — regenerated indexes.
- `03_ops/queues/search_results_ingestion_queue.json` — ingest queue.
- `.vault_state/{vector_index.json, vector_index.npz}` — chunk embeddings.

### Ingestion pipeline

`backend/src/control_plane/vault_learning.py` — 2,528 lines, ~80 methods.
See `docs/knowledge_graph_ingestion.mmd` for the full diagram. Summary:

1. `requeue_all_claimed_items` → `claim_search_queue_items` (rescue orphans).
2. `reingest_if_changed` (content-hash dedup) → `trust_score` gate.
3. `_analyze_source` calls the LLM with `ANALYZE_SOURCE_PROMPT` — strict-JSON output of `summary`, `key_claims`, `entities`, `concepts`, `topic_tags`, `open_questions`, `gap_queries`, `synthesis_refs`. The prompt has explicit anti-pollution rules; `_is_quality_entity` filters again post-hoc.
4. `_generate_source_sections` writes `02_compiled/sources/{id}.md`.
5. For each `entity_ref` / `concept_ref` / `synthesis_ref`, `_update_reference_page` and `_update_synthesis_page` create or merge cross-linked pages — **this is the graph being built**.
6. `compile_incremental` regenerates indexes; `reprocess_existing_sources` backfills edges; `_vault_explorer_cache` is cleared.

### Multi-hop retrieval — already exists, in two forms

- **Graph traversal** — `VaultLearningManager.get_graph()`
  (vault_learning.py:1668-1753): walks `02_compiled/*/*.md`, parses
  frontmatter, builds an in-memory node/edge graph (kinds: `sources`,
  `entities`, `concepts`, `syntheses`), computes degree, returns ranked
  subgraph. The vault explorer at
  `frontend/src/app/workspace/vault/page.tsx` polls
  `/api/vault/explorer` every 10s and expands 1-hop neighborhoods.
- **Semantic search** — `community/knowledge_vault_search/vector_index.py`
  (410 lines): section-aware ~1200-char chunking with 200 overlap, real
  `/embeddings` endpoint (user-onboarded model from
  `extensions_config.json`), cosine over an in-memory `.npz` matrix,
  category filter. Strict mode — no hash-vector fallback.
- **BM25** — `control_plane/services/unified_vault_search.py`
  (`VaultSearcher`, 286 lines). This is what `query_knowledge_vault`
  actually calls today.

### Synthesis

`synthesize_knowledge_graph` (vault_learning.py:1966) aggregates lint
findings (stale syntheses, queue backlog, open questions, contradictions)
plus an *optional* `graph_evidence` blob — meant to be the LightRAG
response, but only `summary` and `entities` were extracted as strings.

### Agent loop today

`web_search` → `_analyze_source` → write to `02_compiled/` with typed
frontmatter refs → BM25/vector search retrieves chunks → agent reads
referenced pages → graph explorer renders 1-hop neighborhoods. The
"LLM wiki" is genuinely a knowledge graph, just stored as markdown.

## 3. What LightRAG would actually add

[hkuds/lightrag](https://github.com/hkuds/lightrag) is an end-to-end
graph-RAG system: LLM-extracted entities + typed relations → Neo4j (or
JSON) + vector store + KV stores; retrieval modes `naive` / `local` /
`global` / `hybrid` / `mix`. Mapped against the vault:

| Capability | Vault today | LightRAG | Delta |
|---|---|---|---|
| Entity extraction | `_analyze_source` + `_is_quality_entity` filter | LLM entity extractor | parity |
| **Typed relations between entities** | only frontmatter refs by kind (`source_refs`/`concept_refs`/...) — not labeled triples | `(src, relation_label, dst)` triples | **LightRAG gain** |
| Cross-doc edges | frontmatter refs + `_update_reference_page` | graph DB | parity |
| Graph traversal | in-memory degree-ranked subgraph, **1-hop** in the UI | N-hop traversal + `local`/`global` modes | **LightRAG gain** |
| **Community detection** | none | via Leiden/louvain in `global` mode | **LightRAG gain (situational)** |
| Vector index | chunk-level cosine | chunk + entity embeddings | parity |
| BM25 | available | none | vault gain |
| Incremental refresh | content-hash dedup, backfill pass | available | parity |
| Synthesis output | `synthesize_knowledge_graph` | `global` mode summaries | parity |
| Obsidian compatibility | markdown vault | opaque DB | vault gain |
| Provenance | frontmatter `source_refs` + file paths | via stored metadata | vault gain |
| Operational cost | low — files + 1 embedding endpoint | high — Neo4j + Infinity rerank + LightRAG server + own LLM extraction cost | vault gain |

**The genuine new capabilities are exactly three**: typed relations,
≥2-hop traversal, and community detection. Everything else is parity or
a vault win.

## 4. The cost — why removal won

Five concrete frictions, each independently expensive:

1. **Source-of-truth fork.** `02_compiled/**/*.md` is canonical today —
   autoresearch writes to it, the vector index derives from it, the
   explorer renders it, queries return paths into it. LightRAG's truth
   is its own graph DB. There is no two-way sync. Either (a) demote
   markdown to "raw notes" and rebuild every consumer on LightRAG
   (kills Obsidian compat, kills the pipeline templates, hard dep on
   Neo4j), or (b) keep markdown canonical and bolt on a
   markdown→LightRAG sync layer that didn't exist anywhere in this repo
   and would mirror the bulk of `vault_learning.py`.
2. **Dual LLM cost on ingest.** `_analyze_source` already runs an LLM
   per source for entity/concept extraction. LightRAG re-runs its own
   entity+relation extractor on the same chunks. Roughly 2× the
   per-source LLM bill unless one was turned off — and turning off
   `_analyze_source` breaks the markdown vault.
3. **External stack.** No LightRAG compose file shipped with capybara.
   `local-stack.sh` expected `$HOME/Desktop/LightRAG/` to exist with
   both `docker-compose.yml` and
   `docker-compose.infinity-standalone.yaml`. Adding LightRAG + Neo4j +
   Infinity rerank to a local-first deployment is real operational tax.
4. **The integration was dead-on-arrival.** The 109-line wrapper assumed
   a *populated* LightRAG instance. Nothing populated it. To make it
   useful would require writing the ingestion bridge (call LightRAG's
   insert/upsert APIs from `vault_learning.ingest` and
   `reingest_if_changed`), an entity/relation reconciliation layer
   (LightRAG entities won't match `_analyze_source` entities
   one-to-one), and a probe/eviction path for deleted vault pages.
   Several hundred lines minimum, plus ongoing maintenance.
5. **The "multi-hop" prompt was overpromising.** The agent was told the
   tool provided "graph-oriented, multi-hop relationship evidence when
   available". In practice the agent called a stub against an
   empty/missing service. Worse than not advertising it at all, because
   it misled the agent's planning.

## 5. Recommendation that was acted on

- Removed `query_lightrag` from the default tool surface.
- Deleted `backend/src/community/lightrag/`.
- Removed `LightRAGConfig` and `knowledge_vault.lightrag.*` config.
- Removed `lightrag` from the control-plane integration service catalog
  and the integrations UI tile.
- Stripped `query_lightrag` mentions from middlewares, lead-agent
  prompt, knowledge-vault skill, and execution trace.
- Removed `lightrag` health checks and start/stop commands from
  `scripts/local-stack.sh`.
- Updated regression tests accordingly. Added LightRAG-removal
  regression assertions to `tests/test_integration_removal.py`.

## 6. Closing the genuine multi-hop gap inside the vault

The capabilities you actually want from LightRAG are cheap to add
in-vault:

1. **Extend `_analyze_source` to extract typed relations**, not just
   entities. Add a `relations: [{src, type, dst}]` field to the prompt
   schema, persist them as additional frontmatter on entity pages
   (e.g. `relations: [{type: governed_by, target: "policy:gdpr"}]`).
   One-prompt, one-schema-field change in
   `prompts/vault_analyze.py`.
2. **Add a `traverse_vault(start, max_hops=3, relation_filter=...)`
   tool** that walks the frontmatter graph N hops and returns a labeled
   chain. ~150-200 lines on top of `get_graph()`. This gives the agent
   the only LightRAG capability it actually exercised today.
3. **Lift the explorer from 1-hop to N-hop** in the UI — same graph,
   deeper BFS, optional relation-label filter.

That gets ~80% of LightRAG's value, keeps markdown canonical, adds zero
new services.

**Community detection** (the one capability given up) is not worth a
graph DB at this vault size — `02_compiled/` is on the order of dozens
of source pages. If/when the vault grows to the tens of thousands of
nodes where Leiden communities pay off, revisit then; at that scale the
engineering tax also amortizes differently.
