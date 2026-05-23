# Reimplementing LightRAG in Capybara Home

> If you decide to reintroduce LightRAG later, do **not** simply copy the
> old code back. The old integration was a query-only wrapper against an
> empty graph. A real integration also needs an ingestion bridge, a
> sync/eviction path, and operational scaffolding that ships inside this
> repo. This guide walks through both.

## TL;DR

Three layers, in order. Stop after Layer 1 only if you genuinely want a
read-only escape hatch into a graph someone else maintains. Otherwise
all three are needed.

1. **Restore the query tool + config + UI** (1–2 hours, low risk).
2. **Build the ingestion bridge** from `vault_learning.py` into
   LightRAG's insert/upsert API (the missing piece — multi-day).
3. **Ship the compose stack inside the repo** so it isn't an external
   `$HOME/Desktop/LightRAG/` dependency.

---

## Layer 1 — Restore the query surface

Use [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md) as the
restore script. Concretely:

1. Recreate `backend/src/community/lightrag/{__init__.py,tool.py}` from
   the verbatim source. Defaults: `base_url=http://localhost:9621`,
   `default_mode=hybrid`, `max_top_k=20`, `timeout_seconds=12.0`.
2. Re-add the registry entry in
   `backend/src/community/registry.py` (`"query_lightrag"` → builtin).
3. Re-add `LightRAGConfig` nested class and the `lightrag` field in
   `backend/src/config/control_plane_config.py` → `KnowledgeVaultConfig`.
4. Re-add `tool_backends.lightrag` and `knowledge_vault.lightrag`
   sections to `config.yaml` (the user must opt in by setting
   `enabled: true`; default-ship as `enabled: false`).
5. Re-add `lightrag` to the integration service catalog,
   `_resolve_integration_services`, and `_docker_keywords_for_service`
   in `backend/src/control_plane/service.py`.
6. Re-add the `lightrag` member to `IntegrationServiceId` in
   `frontend/src/core/control-plane/types.ts`, and to the
   `orderedServiceIds` / `serviceOrder` arrays in
   `frontend/src/app/workspace/integrations/page.tsx` and
   `frontend/src/app/page.tsx`.
7. Re-add the `query_lightrag` branch in
   `frontend/src/components/workspace/messages/execution-trace-panel.tsx`.
8. Re-add `lightrag` to:
    - `_DRAFT_HIDDEN_TOOLS` (phase_tool_filter_middleware)
    - `_SCOPE_GATED_TOOLS` (plan_execution_gate_middleware)
    - `_TRACEABLE_TOOL_NAMES` (execution_trace_middleware)
    - The web_search circuit-breaker message
    - The planner schema docstring
9. Re-add the "Graph Evidence Mode" section to
   `skills/knowledge-vault/SKILL.md`, and the `query_lightrag` line in
   `backend/src/agents/lead_agent/prompt.py` fetch_policy.
10. Update the tests at
    `backend/tests/test_community_tools_api.py`,
    `backend/tests/test_phase_tool_filter_middleware.py`,
    `backend/tests/test_plan_execution_gate_middleware.py` to expect
    `query_lightrag` again.
11. Restore `synthesize_knowledge_graph(graph_evidence=...)` if you want
    the synthesizer to surface LightRAG findings — but see Layer 2.

That gets you back to the prior state: a tool the agent can call against
an external LightRAG server. **You still do not have a knowledge graph
the system builds itself.**

---

## Layer 2 — Build the ingestion bridge (the missing piece)

Without this, LightRAG is querying an empty (or out-of-band) store.

### 2.1 Decide ownership of source-of-truth

Pick one of:

- **Markdown vault stays canonical**, LightRAG is a derived index. (Recommended — keeps Obsidian compat, doesn't fork the data model.)
- **LightRAG becomes canonical**, markdown is demoted to "raw notes". (Heavy rework — kills autoresearch pipeline outputs, kills `02_compiled/` consumers, requires Neo4j as a hard dependency.)

The rest of this guide assumes the first option.

### 2.2 New module: `backend/src/control_plane/services/lightrag_bridge.py`

Responsibilities:

- On every successful `_write_page` / `_update_reference_page` /
  `_update_synthesis_page` in `vault_learning.py`, **also** upsert the
  same content into LightRAG via its insert API
  (`POST /documents/text` or `POST /documents/upload`).
- Track which vault `(category, slug)` corresponds to which LightRAG
  `doc_id` in a sidecar map (e.g.
  `.vault_state/lightrag_doc_map.json`).
- On reingestion (content hash changed), delete the old LightRAG doc and
  insert the new one.
- On vault-page deletion, evict from LightRAG.
- On startup, reconcile: any LightRAG docs not in the vault map get
  marked stale.

Sketch (~200 lines):

```python
class LightRAGBridge:
    def __init__(self, vault_root: Path, base_url: str, timeout: float):
        self.vault_root = vault_root
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.map_path = vault_root / ".vault_state" / "lightrag_doc_map.json"

    def upsert_page(self, *, category: str, slug: str, body: str, metadata: dict) -> None:
        # POST /documents/text with text=body, description=metadata,
        # then record the returned doc_id in the map.
        ...

    def evict_page(self, *, category: str, slug: str) -> None:
        # DELETE /documents/{doc_id}, drop from map.
        ...

    def reconcile(self) -> dict:
        # List LightRAG docs, diff against map, return orphans/missing.
        ...
```

Then in `vault_learning.py` wherever `_write_page` is called for
`02_compiled/{sources,entities,concepts,syntheses}/*.md`, also call
`bridge.upsert_page(...)`. Wherever a page is deleted, call
`bridge.evict_page(...)`.

### 2.3 Entity/relation reconciliation (optional but recommended)

LightRAG runs its own LLM extractor on every doc you upsert. Its entity
set will diverge from `_analyze_source`'s entity set.

Options:

- **Accept divergence.** LightRAG's `local`/`hybrid` mode will reference
  its own canonical entities; the markdown vault has its own. Provide
  both in the agent's context and let it cross-reference.
- **Pre-extract and pass to LightRAG.** Use LightRAG's entity-injection
  API (`POST /entities/upsert`) to seed it with `_analyze_source`'s
  outputs before document ingest. This makes both stores agree on
  entity identity at the cost of more LightRAG-specific code.

### 2.4 LLM-cost mitigation

LightRAG re-LLMs every document. If you're already paying for
`_analyze_source`, you're now paying twice. Mitigations:

- Configure LightRAG to use a cheaper model than `_analyze_source` uses
  (LightRAG accepts an OpenAI-compatible base_url and model name).
- Disable LightRAG's relation-extraction stage for entity-page upserts
  (they're already pre-extracted) and only run it on `sources/`.
- Batch upserts during quiet periods rather than synchronously per
  ingest.

### 2.5 Replace the existing `query_lightrag` tool call sites

Update `synthesize_knowledge_graph` to call `query_lightrag` itself
(rather than receiving `graph_evidence` from the caller). Wire it into
the synthesis stage of the `knowledge-vault-continuous` pipeline
template.

---

## Layer 3 — Ship the compose stack in-tree

The prior `scripts/local-stack.sh` required the user to clone
`hkuds/lightrag` to `$HOME/Desktop/LightRAG/`. That's brittle and
undocumented. Move the stack inside this repo:

```
docker/
  lightrag/
    docker-compose.yml                       # LightRAG server + storage
    docker-compose.infinity-standalone.yaml  # Infinity rerank
    .env.example                             # LIGHTRAG_LLM_MODEL, LIGHTRAG_EMBED_MODEL, etc.
```

Update `scripts/local-stack.sh` so `LIGHTRAG_DIR` defaults to
`$CAPYBARA_ROOT/docker/lightrag`. Either pin a specific LightRAG image
tag or build from a Dockerfile that vendors the upstream commit. Add a
`make lightrag-up` / `make lightrag-down` shortcut in the root
`Makefile`.

Document in `docs/agent-system/SETUP.md` that LightRAG is optional and
how to enable it.

---

## Operational checklist before merging the reintroduction

- [ ] Layer 1 query tool restored and tests green.
- [ ] Layer 2 ingestion bridge merged and at least one end-to-end test
      (`tests/test_lightrag_bridge.py`) covers
      `upsert_page → query_lightrag → evict_page → query_lightrag` and
      asserts content shows up then disappears.
- [ ] Layer 3 compose stack ships in-tree, `make lightrag-up` works on
      a fresh clone, and CI optionally exercises it behind a flag.
- [ ] `tests/test_integration_removal.py` is updated to drop the
      LightRAG-removal assertions added during this removal.
- [ ] `docs/lightrag/README.md` is rewritten from "archived" to "active
      integration".
- [ ] `synthesize_knowledge_graph` actually uses LightRAG's structured
      response (graph edges + entity provenance), not just `summary` +
      `entities` as freeform strings.
- [ ] Agent fetch_policy and skill text are updated to honestly describe
      what LightRAG returns — no more "when available" hedge.

---

## Decision triggers — when to actually do this

Don't reintroduce LightRAG just because the gap section is interesting.
Reintroduce only if **at least two** of the following are true:

1. Vault size has grown past ~10,000 compiled pages — at that scale
   in-memory frontmatter traversal in `get_graph()` starts to feel
   sluggish and community detection becomes useful.
2. Users are routinely asking questions that require ≥3-hop relation
   chains (e.g. "trace the funding path from foundation X to project Y
   via the intermediate orgs"). The current 1-hop explorer can't serve
   these.
3. You've already added typed relations to `_analyze_source` and an
   N-hop `traverse_vault` tool, and they're empirically insufficient.

If only the first one is true, scale the in-memory graph by indexing it
(SQLite + simple BFS). You still don't need LightRAG.
