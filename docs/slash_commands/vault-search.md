# `/vault-search`

**Status:** Removed from the chat input box. Deferred for future improvement.

## What it did

`/vault-search` ran a quick BM25/keyword search over the cached Knowledge Vault contents from the chat input box and surfaced a one-line toast with the top hit.

**Usage in chat:**

```
/vault-search <query>
```

## Implementation (frontend, now removed)

- **Registration** — `"vault-search"` was a member of `SlashCommandName` and `SUPPORTED_COMMANDS` in `frontend/src/core/threads/slash-commands.ts`.
- **Menu entry** — declared in the `SLASH_COMMANDS` array in `frontend/src/components/workspace/input-box.tsx` with usage hint `<query>`.
- **Dispatch path** — inside `executeSlashCommand()`:
  - Trimmed the args into a `query` string. Empty query → toast `Usage: /vault-search <query>`.
  - Called `searchVaultApi(query, 5)` to fetch up to 5 hits.
  - If `items.length === 0`, toasted `No cached vault matches yet.`.
  - Otherwise toasted `Found <n> cached result(s). Top: <title-or-path>`.
- **API client** — `searchVault()` in `frontend/src/core/control-plane/api.ts` GETs `/api/vault/search?q=<query>&limit=<n>`.

## Implementation (backend, still present)

- **REST entry point** — `GET /api/vault/search` in `backend/src/gateway/routers/vault.py`.
- **Service** — `ControlPlaneService.search_vault(query, limit)` runs the keyword index lookup against the compiled vault.
- **Community tool** — `backend/src/community/knowledge_vault_search/` provides the BM25 search the agent itself uses as a tool.
- **Frontend vault UI** — the entity-browser and vault explorer panes (`frontend/src/components/workspace/vault/`) still offer richer search, filtering, and graph navigation.

## Why it was deferred

A one-line toast was too thin a surface to be useful: there was no way to open a result, see snippets, or refine the query. The intended UX was always to escalate into the vault panel, not to replace it with a toast. Re-introducing this command should land alongside an inline result preview (popover or panel) instead of a toast, and ideally share UI with the existing vault search inputs.
