# Dreamy Mode — Archived Documentation

**Status:** Removed from the codebase. This folder preserves everything needed to reimplement Dreamy without re-discovering the architecture.

## What Dreamy Was

Dreamy was a **batch-workflow execution mode** for CapyHome. Instead of free-form chat, the agent operated against a structured `workflow.json` document that described:

1. A **data source** (mounted folder, table, CSV, or inline rows).
2. An ordered set of **steps** to perform per row.
3. An **execution state** (`current_row_index`, `current_step_id`, `phase`) that the agent advanced one step at a time.

It had its own dedicated UI surface (the Dreamy workspace pane), a dedicated agent prompt section, and five dedicated LangGraph middlewares plus a state-preservation hook.

## Files in This Archive

| File | Purpose |
|---|---|
| [README.md](README.md) | This index. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | End-to-end architecture, request lifecycle, runtime-context flag flow, middleware DAG. |
| [BACKEND.md](BACKEND.md) | Every backend file Dreamy owned, with line-anchored notes for surgical edits and full re-creation. |
| [FRONTEND.md](FRONTEND.md) | Every frontend file Dreamy owned (components, hooks, providers, routes). |
| [REIMPLEMENTATION.md](REIMPLEMENTATION.md) | Step-by-step guide for putting Dreamy back, including the canonical wiring points. |
| [REMOVAL_PLAN.md](REMOVAL_PLAN.md) | The removal plan that was executed when Dreamy was retired (kept for traceability and rollback). |
| [dreamy.md](dreamy.md) | Original `/dreamy` slash-command write-up (verbatim copy). |
| [dreamy-exit.md](dreamy-exit.md) | Original `/dreamy-exit` slash-command write-up (verbatim copy). |

## Why It Was Removed

Two recurring failure modes (also covered in [dreamy.md](dreamy.md) §"Why it was deferred"):

1. **Inconsistent activation surface.** Most chat surfaces never wired the `onActivateDreamy`/`onDeactivateDreamy` callbacks, so `/dreamy` and `/dreamy-exit` regularly dead-ended on "not available on this chat surface yet." toasts.
2. **Banner-only effect.** Flipping the banner did not always propagate `dreamy_mode` into the runtime context, so the agent's behaviour did not always match the UI.

The capabilities Dreamy depended on (mount folder, `/analyse`, `/publishdocs`) are general-purpose and have been kept under non-Dreamy ownership in [MountFolderMiddleware](../../backend/src/agents/middlewares/mount_folder_middleware.py) and the gateway. Only the Dreamy-specific layers were removed.

## Hard Invariants For Any Reimplementation

These are *non-negotiable* lessons from the old implementation:

1. **Wire the runtime-context flag end-to-end** before exposing any UI affordance. The banner must be a read-only reflection of `context.dreamy_mode`, not the source of truth.
2. **Gate the surface affordance on real wiring.** If a chat surface cannot honour `onActivateDreamy`, the slash command should not appear in its menu at all — toast-with-no-effect is worse than missing.
3. **Subagents must stay disabled inside Dreamy** (see `_RegistryContext.subagent_enabled` override in `agent.py` — `False if dreamy_mode else cfg.get(...)`). Row-by-row work assumes serial execution.
4. **`/dreamy-exit` precedes `/handoff`.** Handoff packaging assumes a normal chat session; Dreamy state must be cleared first.
5. **`DreamyExecutionMiddleware` depends on `sandbox`, `dreamy_poc`, `thread_data`, `dreamy_watchdog`.** Reproduce this ordering exactly or the executor will see partial state.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full dependency graph and [REIMPLEMENTATION.md](REIMPLEMENTATION.md) for the wiring checklist.
