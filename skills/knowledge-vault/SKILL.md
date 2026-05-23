---
name: knowledge-vault
description: Use this skill to ingest web articles into CapyHome's Obsidian-compatible knowledge_vault, keep source notes up to date, and compile index/log pages for continuous learning workflows.
---

# Knowledge Vault Skill

Use this skill when the user asks to:
- continuously learn from new articles
- ingest links into an Obsidian vault
- build/update a durable knowledge base beyond chat memory

## Core Behavior

1. Prefer the built-in pipeline template `knowledge-vault-continuous`.
2. Pass URLs through pipeline run inputs (`urls` list).
3. Confirm outcomes using pipeline run artifacts:
   - `*-vault-discover.json`
   - `*-vault-ingest.json`
   - `*-vault-compile.json`
   - `*-vault-lint.json`
4. Keep outputs in `knowledge_vault/`:
   - `01_raw/sources/YYYY/MM/<source-id>/*`
   - `02_compiled/sources/*.md`
   - `02_compiled/syntheses/*.md`
   - `02_compiled/index.md`
   - `02_compiled/log.md`
   - `03_ops/queues/search_results_ingestion_queue.json`

## Trigger Modes

- Manual chat trigger:
  - Create a pipeline run with `template_id=knowledge-vault-continuous`
  - Set `auto_start=true`
  - Provide `inputs.urls`
- Autoresearch chat trigger:
  - User types `autoresearch - <topic>`
  - Middleware creates a runtime daily scheduler job for `knowledge-vault-autoresearch`
  - Middleware starts a bootstrap run immediately with `inputs.autoresearch_topic`
- Scheduled trigger:
  - Create a runtime scheduler job targeting `knowledge-vault-continuous`
  - Use `schedule_type=daily_time` and `daily_time=HH:MM`

## Query Mode

When the user asks about a topic and you want to check if the knowledge vault has relevant material:

1. Call `query_knowledge_vault` with a descriptive query string.
2. If results are returned, cite them and use the excerpts to answer.
3. If no results match, tell the user the vault has no pages on this topic.
4. Treat this as a **mental model pass**: infer current vault structure, snippets, and concept connectivity before deciding to fetch externally.

Example usage:
- "What do I know about LangGraph?" → `query_knowledge_vault(query="LangGraph memory state")`
- "Show me my notes on climate policy" → `query_knowledge_vault(query="climate policy", categories=["syntheses","concepts"])`

## Synthesis Mode

- `synthesize_knowledge_graph` is not a default ad-hoc chat tool.
- It runs as an **autoresearch pipeline stage** to produce:
  - `findings`
  - `gaps`
  - `contradictions`
  - `next_actions`

## Guardrails

- Only ingest `http`/`https` URLs.
- Respect optional domain allowlist from `knowledge_vault.allowed_domains`.
- Skip unchanged pages by content hash.
- Require trust score >= `knowledge_vault.min_trust_score` before appending to vault.
- For autoresearch runs, pause the runtime scheduler job if no workspace chat activity exists in the last 24 hours.
- Never store transient upload path metadata in vault notes.
