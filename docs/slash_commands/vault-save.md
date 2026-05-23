# `/vault-save`

**Status:** Removed from the chat input box. Deferred for future improvement.

## What it did

`/vault-save` saved a free-form note directly into the **Knowledge Vault** from the chat input box, tagged with the originating thread id.

**Usage in chat:**

```
/vault-save <title> | <content>
```

Both `title` and `content` were required. The title doubled as the `topic` field on the vault entry.

## Implementation (frontend, now removed)

- **Registration** — `"vault-save"` was a member of `SlashCommandName` and `SUPPORTED_COMMANDS` in `frontend/src/core/threads/slash-commands.ts`.
- **Menu entry** — declared in the `SLASH_COMMANDS` array in `frontend/src/components/workspace/input-box.tsx` with usage hint `<title> | <content>`.
- **Dispatch path** — inside `executeSlashCommand()`:
  - Split the args on the first `|` into `title` and `content`.
  - If either side was empty, toasted `Usage: /vault-save <title> | <content>`.
  - Otherwise called `saveToVaultApi({ title, content, topic: title, source_thread_id: threadId })`.
  - On success, cleared the input and toasted `Saved to Knowledge Vault.`.
- **API client** — `saveToVault()` in `frontend/src/core/control-plane/api.ts` POSTs to `/api/vault/save` with a `VaultSaveRequest` body.

## Implementation (backend, still present)

- **REST entry point** — `POST /api/vault/save` in `backend/src/gateway/routers/vault.py`.
- **Service** — `ControlPlaneService.save_to_vault()` writes a new vault page (frontmatter-tagged markdown) under the configured vault root, optionally feeding the ingest pipeline.
- **Vault learning utilities** — `backend/src/control_plane/vault_learning.py` and `backend/src/control_plane/vault_text_utils.py` handle slugging, frontmatter assembly, and dedup against existing pages.

Manual notes can still be added to the vault via:
- The clipper / vault UI in `frontend/src/components/workspace/vault/`.
- A direct `POST /api/vault/save` call.
- The `vault-source-researcher` subagent during an autoresearch run.

## Why it was deferred

The inline `<title> | <content>` form was fragile: long bodies with literal `|` characters got truncated, titles collided with auto-generated topic slugs, and there was no clear feedback path when ingest post-processing failed asynchronously. The UI flow needs to be reworked (probably as a proper dialog with title/content/tag fields and a confirm step) before re-exposing it as a slash command.
