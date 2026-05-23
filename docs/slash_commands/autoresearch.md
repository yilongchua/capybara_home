# `/autoresearch`

**Status:** Removed from the chat input box. Deferred for future improvement.

## What it did

`/autoresearch` let the user start an **autoresearch objective** tied to the current chat thread directly from the input box. An autoresearch objective is a long-running, multi-iteration research loop that asks a generator LLM to propose sub-questions, dispatches the `vault-source-researcher` subagent to answer each one, deduplicates against a per-objective ledger and the Knowledge Vault, and reflects on the answers to emit follow-up questions until novelty decays.

**Usage in chat:**

```
/autoresearch <topic> | <endpoint goal>
/autoresearch                 # opens a dialog asking for topic + endpoint goal
```

If the user omitted `| <endpoint goal>`, the frontend fell back to:

> "Deliver a complete, evidence-backed research brief for `<topic>` with actionable next steps."

## Implementation (frontend, now removed)

- **Registration** — `"autoresearch"` was a member of `SlashCommandName` and `SUPPORTED_COMMANDS` in `frontend/src/core/threads/slash-commands.ts`.
- **Menu entry** — declared in the `SLASH_COMMANDS` array in `frontend/src/components/workspace/input-box.tsx` with usage hint `<topic> [| endpoint goal]`.
- **Argument parsing** — `parseAutoresearchArgs()` split the args on `|` into `topic` and `endpointGoal`, applying the default endpoint goal template when the second half was missing.
- **Dispatch path** — inside `executeSlashCommand()`:
  - If both `topic` and `endpointGoal` were provided inline, it called `runAutoresearch()` directly.
  - Otherwise it opened the `<AutoresearchDialog>` (from `input-box-dialogs.tsx`) with two-field form (`Topic` input, `Endpoint goal` textarea) and confirmed via the dialog's Start button.
- **API call** — `runAutoresearch()` invoked `startAutoresearchObjective({ topic, endpoint_goal, thread_id, bootstrap: true })` from `frontend/src/core/control-plane/api.ts`, which POSTs to `/api/pipelines/autoresearch/start`.
- **State held in `InputBox`** — `autoresearchDialogOpen`, `autoresearchTopic`, `autoresearchEndpointGoal`, `autoresearchSubmitting`.

## Implementation (backend, still present)

The autoresearch loop itself remains intact and is unaffected by removing the slash command:

- **REST entry point** — `POST /api/pipelines/autoresearch/start` on the gateway (see `backend/src/gateway/routers/pipelines.py`-style routing wired through `ControlPlaneService`).
- **Pipeline template** — `knowledge-vault-autoresearch-loop` registered in `backend/src/control_plane/services/templates.py`.
- **Loop driver** — `backend/src/control_plane/autoresearch_loop/`:
  - `loop.py` — single-iteration driver
  - `generator.py` — proposes sub-questions across the 12-cluster taxonomy
  - `dedup.py` — token-Jaccard dedup against the ledger + vault keyword search
  - `researcher.py` — spawns the `vault-source-researcher` subagent per question
  - `reflector.py` — emits follow-up questions from new answers
  - `stop_criteria.py` — novelty-decay stop signal
  - `ledger.py` — per-objective question ledger at `{vault_root}/03_ops/autoresearch/objectives/{slug}/`
  - `taxonomy.py` — 12-cluster question taxonomy loader
- **Orchestrator agent** — `backend/src/control_plane/agents/autoresearch_agent.py` (`AutoresearchOrchestratorAgent`) handles `update_after_run` and lifecycle transitions.
- **Middleware** — `backend/src/agents/middlewares/autoresearch_middleware.py` performs early routing inside the lead agent.

Autoresearch objectives can still be created and managed via the pipelines page (`frontend/src/app/workspace/pipelines/page.tsx`) and the REST endpoints — only the chat-box `/autoresearch` shortcut is gone.

## Why it was deferred

The feature has behavior issues — for example, objective lifecycle / interruption handling, runaway iterations, and surface confusion between chat-thread context and pipeline-run context — that need to be addressed before exposing it again as a one-line chat command. Until then, use the pipelines page or call the REST endpoint directly with explicit topic/endpoint-goal payloads.
