# LightRAG Integration — Archived Removal Notes

> **Status: REMOVED** from the Capybara Home codebase. This folder is the
> complete archival record of the integration as it existed, plus a
> step-by-step reimplementation guide if it is ever reintroduced.

## Why it was removed

See [ANALYSIS.md](ANALYSIS.md) for the full rationale. Short version:

1. The integration was a 109-line HTTP wrapper that pointed at an external
   LightRAG server stack which Capybara Home does not ship.
2. There was **no ingestion path** from the markdown knowledge vault into
   LightRAG — the wrapper queried a store nothing in this repo populated.
3. The current `02_compiled/**/*.md` vault is already a typed knowledge
   graph (entities / concepts / syntheses with YAML frontmatter
   cross-refs). LightRAG would have duplicated 90% of it at ~2× LLM cost
   on ingest and created a source-of-truth fork.
4. The genuine multi-hop / community-detection gains are real but
   cheaper to address inside the vault (typed relations in
   `_analyze_source` + an N-hop `traverse_vault` tool) than by adopting
   LightRAG.
5. The codebase has been actively trimming heavyweight external research
   services (`searxng`, `crawl4ai`, `onyx_mcp` were already removed and
   are guarded by `tests/test_integration_removal.py`). LightRAG fits
   the same pattern.

## What's in this folder

| File | Purpose |
|---|---|
| [README.md](README.md) | This file. |
| [ANALYSIS.md](ANALYSIS.md) | Full in-depth code analysis: what existed, what the vault already does, what LightRAG would add, why removal is the right call. |
| [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md) | Verbatim source of every LightRAG-related artifact that was removed, organized by file. Restore-from-here. |
| [REIMPLEMENTATION_GUIDE.md](REIMPLEMENTATION_GUIDE.md) | Step-by-step instructions to bring LightRAG back, including the ingestion bridge that was *never* built but would be required for a real integration. |
| [REMOVAL_CHANGELOG.md](REMOVAL_CHANGELOG.md) | Exact list of files touched during removal, with the change made in each. |

## Upstream reference

- LightRAG repo: <https://github.com/hkuds/lightrag>
- Default ports used by the prior integration: `9621` (LightRAG API), `7997` (Infinity rerank).
- External stack location expected by `scripts/local-stack.sh`:
  `$HOME/Desktop/LightRAG/{docker-compose.yml,docker-compose.infinity-standalone.yaml}`.
