# Slash Commands (Deferred)

This folder documents slash commands that were previously available in the chat input box (the `/` menu) and have been **removed from the UI** because their behavior had issues that need to be reworked before they can ship again.

The backend implementations behind most of these features are **still present** — only the chat-box `/` entry points were removed. The features may continue to be reachable via direct REST endpoints, pipelines UI, or other surfaces. Re-enabling them in the chat input box is deferred to a future improvement cycle.

## Removed commands

| Command | Doc |
|---|---|
| `/autoresearch` | [autoresearch.md](autoresearch.md) |
| `/vault-save` | [vault-save.md](vault-save.md) |
| `/vault-search` | [vault-search.md](vault-search.md) |
| `/dreamy` + `/dreamy-exit` (entire mode) | [dreamy/](dreamy/) — full removal archive with reimplementation guide |

## Where they used to live

- **Registration** — `frontend/src/core/threads/slash-commands.ts` defined the `SlashCommandName` union and `SUPPORTED_COMMANDS` allowlist.
- **Menu rendering & dispatch** — `frontend/src/components/workspace/input-box.tsx` declared the `SLASH_COMMANDS` array (titles/descriptions shown in the `/` dropdown) and a single `executeSlashCommand` switch that called the relevant API client method.
- **Dialogs** — `frontend/src/components/workspace/input-box-dialogs.tsx` hosted any modal forms (e.g. `AutoresearchDialog`).
- **API clients** — `frontend/src/core/control-plane/api.ts` (`startAutoresearchObjective`, `saveToVault`, `searchVault`). The Dreamy backend stack (middlewares, router, prompt section, ThreadState fields) has been fully removed — see [dreamy/REMOVAL_PLAN.md](dreamy/REMOVAL_PLAN.md) and [dreamy/REIMPLEMENTATION.md](dreamy/REIMPLEMENTATION.md).

## Why they were removed

Each command had user-facing issues — see the per-command notes for the specifics. Removing them from the `/` menu prevents users from triggering broken flows while the underlying features are reworked. The remaining commands (`/compact`, `/recover`, `/handoff`, `/new`, `/mount`, `/analyse`, `/publishdocs`, `/rename`) are unaffected.
