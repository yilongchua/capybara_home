# Reinstating Dreamy — Step-By-Step

This is the canonical recipe for bringing Dreamy back. Follow in order. Cross-references point to [ARCHITECTURE.md](ARCHITECTURE.md), [BACKEND.md](BACKEND.md), and [FRONTEND.md](FRONTEND.md) for byte-level detail.

## 0. Decide The Scope

Pick one before writing any code:

- **Full restoration** — chat-thread `/dreamy` toggle + dedicated Dreamy pane. This is what the old implementation tried to be.
- **Pane-only Dreamy** — drop the `/dreamy` slash command entirely; Dreamy only lives in `/workspace/dreamy/[thread_id]`, which auto-sets `dreamy_mode: true` on every run payload. This is what [dreamy.md](dreamy.md) §"Why it was deferred" recommends.

The instructions below cover full restoration. For pane-only, skip §6 (slash-command wiring) and skip the `dreamy` / `dreamy-exit` entries in `slash-commands.ts`.

## 1. Restore The Backend Files

Restore every file listed under [BACKEND.md §Whole-File](BACKEND.md#whole-file-re-create-these-in-full):

```text
backend/src/agents/middlewares/dreamy_intent_middleware.py
backend/src/agents/middlewares/dreamy_watchdog_middleware.py
backend/src/agents/middlewares/dreamy_bootstrap_middleware.py
backend/src/agents/middlewares/dreamy_poc_middleware.py
backend/src/agents/middlewares/dreamy_execution_middleware.py
backend/src/agents/memory/dreamy_state_preservation_hook.py
backend/src/gateway/routers/dreamy.py
backend/src/config/dreamy_timeout_config.py
backend/tests/test_dreamy_bootstrap_middleware.py
backend/tests/test_dreamy_intent_middleware.py
backend/tests/test_dreamy_mount_folder_router.py
backend/tests/test_dreamy_repo_overview_refresh.py
```

Easiest path: `git show <pre-removal-sha>:<path>` for each file, or `git checkout <pre-removal-sha> -- <path>`.

## 2. Re-add The Backend Wiring

Re-apply the surgical edits documented in [BACKEND.md §Surgical Edits](BACKEND.md#surgical-edits-re-add-these-lines-to-surviving-files):

1. `backend/src/agents/lead_agent/agent.py` — imports, summarization signature, `_RegistryContext` flag plumbing, five `MiddlewareSpec`s, sandbox `after={…}` edges, `_extract_runtime_params`, `make_lead_agent`.
2. `backend/src/agents/lead_agent/prompt.py` — `DREAMY_MODE_SECTION` constant + `apply_prompt_template(dreamy_mode=…)`.
3. `backend/src/agents/thread_state.py` — `DreamyIntentState` + the two `ThreadState` fields.
4. `backend/src/gateway/app.py` — router import, lifespan startup hook, `app.include_router(dreamy.router)`.
5. `backend/src/config/__init__.py` — re-export `DreamyTimeoutConfig` and `get_dreamy_timeout_config`.
6. `backend/src/config/app_config.py` — embed `DreamyTimeoutConfig` + load at startup.
7. `backend/src/config/summarization_config.py` — restore the "dreamy" mode in the doc string.
8. `backend/src/config/question_generation_config.py` — `enabled_in_dreamy` flag.
9. `config.yaml` and `config.example.yaml` — restore `summarization.modes.dreamy:` block, `question_generation.enabled_in_dreamy:`, top-level `dreamy_timeout:`.
10. `skills/dreamy-workflow/SKILL.md` — restore the skill so the model can `read_file /mnt/skills/dreamy-workflow/SKILL.md` per `DREAMY_MODE_SECTION`.

### Sanity check the middleware DAG

After restoration, the relevant edges in `_build_middlewares` must be:

```
thread_data → dreamy_watchdog → dreamy_intent → dreamy_bootstrap → dreamy_poc → dreamy_execution
                                       ↓
                                    sandbox  (after={"dreamy_intent", "dreamy_bootstrap"})
                                       ↓
                                dreamy_execution  (after={"…", "sandbox"})
```

If `sandbox` does not list `dreamy_intent` and `dreamy_bootstrap` in its `after`, the sandbox can be acquired before the intent classifier sees `/dreamy-exit`, and Dreamy will incorrectly stay active.

## 3. Restore The Frontend Files

Restore every file listed under [FRONTEND.md §Whole-File](FRONTEND.md#whole-file-re-create-these-in-full):

```text
frontend/src/components/workspace/dreamy/        (entire folder)
frontend/src/core/dreamy/                        (entire folder, incl. hooks/)
frontend/src/app/workspace/dreamy/               (entire folder)
```

## 4. Re-add The Frontend Wiring

Re-apply the surgical edits documented in [FRONTEND.md §Surgical Edits](FRONTEND.md#surgical-edits-re-add-these-lines-to-surviving-files):

1. `frontend/src/components/workspace/input-box.tsx` — props, type signature, `isDreamyThread` derivation, `dreamy: isDreamyThread` on run payload, plan-mode hiding when dreamy is active, `executeSlashCommand("dreamy" | "dreamy-exit", …)` branches.
2. `frontend/src/app/workspace/chats/[thread_id]/layout.tsx` — `<DreamyProvider>` wrapper.
3. `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/layout.tsx` — `<DreamyProvider>` wrapper.
4. `frontend/src/core/threads/slash-commands.ts` — `"dreamy"` / `"dreamy-exit"` in `SlashCommandName` + `SUPPORTED_COMMANDS`.
5. `frontend/src/core/threads/types.ts` — `dreamy_mode` and `dreamy_intent` on `ThreadStateValues`; `dreamy_mode` on the run-create payload type.
6. `frontend/src/core/threads/hooks.ts` — `api` import, dreamy delta forwarding in the state-stream reducer.
7. `frontend/src/core/threads/utils.ts` — `DREAMY_TITLE_PREFIX`, `isDreamyThread`.
8. `frontend/src/core/workspace-refresh/index.ts` — `` `dreamy:${string}` `` event variant.
9. `frontend/src/components/workspace/chat-ui/mount-folder-badge.tsx` — react-query keys (optional cosmetic change).
10. `frontend/src/core/i18n/locales/types.ts` + `en-US.ts` — nav entry + pane copy bundle.

## 5. Wire Activation Surfaces

Decide which chat surfaces can host `/dreamy`. Then:

- For each supported surface, pass concrete `onActivateDreamy` / `onDeactivateDreamy` to `<InputBox>`. These should call into `DreamyProvider`'s setters and update the `dreamy_mode` on the next run payload.
- For each *un*supported surface, filter `"dreamy"` and `"dreamy-exit"` out of the slash menu so they cannot appear there. Do **not** rely on a "not available" toast.

## 6. Backfill The `/dreamy` & `/dreamy-exit` Slash Commands

Old behaviour from [dreamy.md](dreamy.md) and [dreamy-exit.md](dreamy-exit.md):

```ts
// inside executeSlashCommand(...) in input-box.tsx
case "dreamy": {
  const isDreamyThread = [dreamy, dreamyActive].some(Boolean);
  if (isDreamyThread) {
    toast("Dreamy mode is already active for this thread.");
    return;
  }
  if (!onActivateDreamy) {
    toast("Dreamy mode is not available on this chat surface yet.");
    return;
  }
  await onActivateDreamy();
  clearInput();
  return;
}

case "dreamy-exit": {
  const isDreamyThread = [dreamy, dreamyActive].some(Boolean);
  if (!isDreamyThread) {
    toast("Dreamy mode is not active for this thread.");
    return;
  }
  if (!onDeactivateDreamy) {
    toast("Dreamy exit is not available on this chat surface yet.");
    return;
  }
  await onDeactivateDreamy();
  clearInput();
  return;
}
```

`/handoff` precondition (preserved):

```ts
case "handoff": {
  if ([dreamy, dreamyActive].some(Boolean)) {
    toast("Exit Dreamy with /dreamy-exit before creating a handoff.");
    return;
  }
  // ... rest of handoff dispatch ...
}
```

## 7. Smoke Tests

After reinstatement, walk through:

1. Open `/workspace/dreamy/[thread_id]` — pane renders, no console errors.
2. Mount a folder via the pane → confirm `<user-data>/dreamy_mount.json` is written.
3. Send a workflow-design message → confirm `dreamy_intent` appears in the LangGraph state stream and `workflow.json` is created.
4. Run `/analyse` → confirm `.docs/` mirror and `.analyse/index.md` exist.
5. Run a row through POC phase → confirm `execution_state.phase` advances to `awaiting_approval`.
6. Approve via `ask_clarification` → confirm bulk execution starts.
7. Restart the gateway mid-job → confirm `initialize_repo_overview_refresh_jobs()` recovers the queued/running job.
8. `/dreamy-exit` → confirm `dreamy_mode` flips false in the state stream and a follow-up `/handoff` succeeds.
9. Open a `/workspace/chats/[thread_id]` thread (non-Dreamy surface) → confirm `/dreamy` either works or is hidden from the slash menu — **not** silently toast-only.

## 8. Don't Forget

- `subagents.enabled = false` is enforced *inside* Dreamy at the registry level. If you remove that override, the planner will gleefully delegate row work to subagents and your row-by-row contract breaks.
- The `dreamy_state_preservation_hook` must run **before** `CapyHomeSummarizationMiddleware` compacts. The factory already appends it to `before_summarization` when `dreamy_mode=True` — keep that wiring intact.
- `workflow.json` is at `/mnt/user-data/workspace/workflow.json` (virtual path). In the host filesystem this is under `<thread_dir>/user-data/outputs/workflow.json`. The gateway's `_workflow_path` helper resolves this — do not hardcode the host path elsewhere.
- The `dreamy-workflow` skill must remain enabled in `extensions_config.json` for the model's `read_file /mnt/skills/dreamy-workflow/SKILL.md` instruction in `DREAMY_MODE_SECTION` to resolve.
