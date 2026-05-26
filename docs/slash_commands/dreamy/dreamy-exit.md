# `/dreamy-exit`

**Status:** Removed from the chat input box. Deferred for future improvement.

## What it did

`/dreamy-exit` was the inverse of `/dreamy`: it turned off Dreamy mode for the current chat thread and hid the Dreamy banner. It was also a hard prerequisite for `/handoff` — attempting to create a handoff while Dreamy mode was active toasted `Exit Dreamy with /dreamy-exit before creating a handoff.`.

**Usage in chat:**

```
/dreamy-exit
```

(No arguments.)

If Dreamy mode was not active, the command toasted `Dreamy mode is not active for this thread.` and stopped.

## Implementation (frontend, now removed)

- **Registration** — `"dreamy-exit"` was a member of `SlashCommandName` and `SUPPORTED_COMMANDS` in `frontend/src/core/threads/slash-commands.ts`.
- **Menu entry** — declared in the `SLASH_COMMANDS` array in `frontend/src/components/workspace/input-box.tsx` with usage hint `Disable Dreamy mode banner`.
- **Dispatch path** — inside `executeSlashCommand()`:
  - Checked `isDreamyThread = dreamy || dreamyActive`.
  - If not active → toast `Dreamy mode is not active for this thread.` and stop.
  - If the chat surface did not pass an `onDeactivateDreamy` callback → toast `Dreamy exit is not available on this chat surface yet.`.
  - Otherwise `await onDeactivateDreamy?.()` and clear the input.
- **Handoff interaction** — `executeSlashCommand("handoff", ...)` short-circuited with the "Exit Dreamy with /dreamy-exit" toast whenever `isDreamyThread` was true. With `/dreamy-exit` removed, this branch is no longer reachable from the slash menu (and the `/handoff` guard remains intact for the remaining programmatic paths that can set `dreamy`/`dreamyActive`).

## Implementation (backend, still present)

There is no dedicated "exit Dreamy" backend endpoint. Dreamy mode lives in the runtime context (`context.dreamy_mode`) and in client-side state on the Dreamy pane. `DreamyIntentMiddleware` keys off the per-request flag rather than a persisted "active" record, so leaving Dreamy mode is effectively a frontend state transition. The Dreamy workflow APIs, hooks, and components under `frontend/src/core/dreamy/` and `frontend/src/components/workspace/dreamy/` continue to manage their own lifecycle.

## Why it was deferred

`/dreamy-exit` inherited the same issues as [`/dreamy`](dreamy.md):

- Most chat surfaces never wired `onDeactivateDreamy`, so the command often dead-ended on a "not available" toast.
- Because activation was banner-only on the chat surfaces, exiting was also banner-only — confusing in cases where the runtime context had already drifted out of sync with the banner.

A future revision should pair Dreamy enter/exit as a single, surface-aware affordance, ideally inside the Dreamy pane only, and let the chat-box `/` menu surface stay focused on commands that work uniformly across all chat surfaces.
