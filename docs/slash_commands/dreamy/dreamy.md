# `/dreamy`

**Status:** Removed from the chat input box. Deferred for future improvement.

## What it did

`/dreamy` switched the current chat thread into **Dreamy mode** — a workflow-design mode where the agent is steered toward producing a structured workflow (steps, inputs, outputs) rather than free-form chat. The command showed the Dreamy mode banner for the thread and let downstream middleware (`DreamyIntentMiddleware`) start extracting structured intent from subsequent user turns.

**Usage in chat:**

```
/dreamy
```

(No arguments.)

If Dreamy mode was already active for the thread, the command toasted `Dreamy mode is already active for this thread.` instead of activating again.

## Implementation (frontend, now removed)

- **Registration** — `"dreamy"` was a member of `SlashCommandName` and `SUPPORTED_COMMANDS` in `frontend/src/core/threads/slash-commands.ts`.
- **Menu entry** — declared in the `SLASH_COMMANDS` array in `frontend/src/components/workspace/input-box.tsx` with usage hint `Switch this thread into workflow mode`.
- **Dispatch path** — inside `executeSlashCommand()`:
  - Read `isDreamyThread = dreamy || dreamyActive` from the `InputBox` props.
  - If already active → toast `Dreamy mode is already active for this thread.` and stop.
  - If the chat surface did not pass an `onActivateDreamy` callback → toast `Dreamy mode is not available on this chat surface yet.`.
  - Otherwise `await onActivateDreamy?.()` and clear the input.
- **Surface-level wiring** — `InputBox` accepts the optional `dreamy`, `dreamyActive`, `onActivateDreamy`, and `onDeactivateDreamy` props. The Dreamy workflow pane (`frontend/src/components/workspace/dreamy/`) is the canonical Dreamy surface; standalone chat pages did not wire `onActivateDreamy`, which is why the command commonly produced the "not available on this chat surface yet" toast.

## Implementation (backend, still present)

- **Intent middleware** — `backend/src/agents/middlewares/dreamy_intent_middleware.py` (`DreamyIntentMiddleware`) strips `/dreamy` / `/workflow` prefixes from the latest human turn and classifies the user's workflow-design intent. The `dreamy_mode` flag travels in the runtime context.
- **Dreamy workflow APIs** — `backend/src/gateway/routers/...` exposes mount-folder, analyse, repo-overview, and workflow-JSON endpoints consumed by `frontend/src/core/dreamy/api.ts` and the Dreamy hooks under `frontend/src/core/dreamy/hooks/`.
- **Dreamy UI** — `frontend/src/components/workspace/dreamy/` (workflow pane, step editor, directory tab, file preview, etc.) provides the dedicated Dreamy surface where workflow mode is the default — no `/dreamy` toggle needed there.

## Why it was deferred

In practice the `/dreamy` slash command had two recurring problems:

1. **Inconsistent activation surface.** Most chat surfaces did not pass `onActivateDreamy`, so the command frequently dead-ended on a toast telling the user it wasn't available. The Dreamy pane already runs in workflow mode by default, making the toggle redundant where it does work.
2. **Banner-only effect.** Activation flipped the banner but didn't always propagate `dreamy_mode` into the runtime context reliably, so the agent's behavior didn't always change to match the banner — leading to user confusion.

A future revision should either (a) make Dreamy activation a surface-level affordance only inside the Dreamy pane, or (b) wire the runtime-context flag end-to-end and gate the slash command on surfaces that actually support it.
