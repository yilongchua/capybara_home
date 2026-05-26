# Dreamy Removal — Implementation Plan

This plan was executed when Dreamy was retired. Kept for traceability and for rollback (apply the inverse via [REIMPLEMENTATION.md](REIMPLEMENTATION.md)).

## Guiding Constraints

- **Do not disturb Plan mode or Work mode.** Their middlewares live alongside Dreamy's but have no dependency on Dreamy's classes or state fields.
- **Do not disturb the mount-folder feature.** `MountFolderMiddleware` and the badge UI are general-purpose; only the Dreamy-specific cache-key prefixes and gateway routes are owned by Dreamy.
- **Single commit / single PR.** Dreamy's middleware DAG, prompt section, runtime-context flag, and frontend pane are tightly coupled — partial removal leaves dangling imports.

## Order Of Operations

Removal proceeds backend-first to avoid frontend type checks failing on stale references, then frontend, finishing with verification:

1. **Backend wiring removals** (so subsequent file deletes don't break imports):
   1. `backend/src/agents/lead_agent/agent.py` — remove the dreamy hook + middleware imports, the `dreamy_mode` plumbing in `_create_summarization_middleware`, `_build_middlewares` (incl. the five `MiddlewareSpec`s and the sandbox `after={…}` edges), `_extract_runtime_params`, and `make_lead_agent`.
   2. `backend/src/agents/lead_agent/prompt.py` — drop `DREAMY_MODE_SECTION`, drop `dreamy_mode` param + branch in `apply_prompt_template`.
   3. `backend/src/agents/thread_state.py` — drop `DreamyIntentState`, drop `ThreadState.dreamy_mode` and `dreamy_intent`.
   4. `backend/src/gateway/app.py` — drop `dreamy` from the router import block, the lifespan recovery hook, and the `include_router(dreamy.router)` call.
   5. `backend/src/config/__init__.py` — drop the dreamy timeout re-exports.
   6. `backend/src/config/app_config.py` — drop the import, the `dreamy_timeout` field, and the load call.
   7. `backend/src/config/summarization_config.py` — drop the `dreamy` mention from the per-mode description string.
   8. `backend/src/config/question_generation_config.py` — drop the `enabled_in_dreamy` field.
   9. `config.yaml` and `config.example.yaml` — drop the `summarization.modes.dreamy:` block, the `question_generation.enabled_in_dreamy` line, and the top-level `dreamy_timeout:` block.

2. **Backend file deletions** (now safe, no live imports):
   - `backend/src/agents/middlewares/dreamy_bootstrap_middleware.py`
   - `backend/src/agents/middlewares/dreamy_execution_middleware.py`
   - `backend/src/agents/middlewares/dreamy_intent_middleware.py`
   - `backend/src/agents/middlewares/dreamy_poc_middleware.py`
   - `backend/src/agents/middlewares/dreamy_watchdog_middleware.py`
   - `backend/src/agents/memory/dreamy_state_preservation_hook.py`
   - `backend/src/gateway/routers/dreamy.py`
   - `backend/src/config/dreamy_timeout_config.py`
   - `backend/tests/test_dreamy_bootstrap_middleware.py`
   - `backend/tests/test_dreamy_intent_middleware.py`
   - `backend/tests/test_dreamy_mount_folder_router.py`
   - `backend/tests/test_dreamy_repo_overview_refresh.py`
   - *(Optional, only if Dreamy is permanently gone)* `skills/dreamy-workflow/` — leaving it in place is harmless since nothing references it anymore.

3. **Frontend wiring removals** (mirror the backend order):
   1. `frontend/src/components/workspace/input-box.tsx` — drop the four props, the type signature entries, every `api.threads.dreamy.*` call site, the `isDreamyThread` derivation and its propagation onto the run payload + effect deps, the `{!dreamy && …}` guards, and the `executeSlashCommand("dreamy" | "dreamy-exit", …)` branches.
   2. `frontend/src/app/workspace/chats/[thread_id]/layout.tsx` — drop the `DreamyProvider` import and wrapper.
   3. `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/layout.tsx` — same.
   4. `frontend/src/core/threads/slash-commands.ts` — remove the `"dreamy"` / `"dreamy-exit"` members if still present.
   5. `frontend/src/core/threads/types.ts` — drop `dreamy_mode` and `dreamy_intent` from `ThreadStateValues` and the run-create payload type.
   6. `frontend/src/core/threads/hooks.ts` — drop the `api` import from `core/dreamy`, drop the dreamy delta forwarding block.
   7. `frontend/src/core/threads/utils.ts` — drop `DREAMY_TITLE_PREFIX` and the `isDreamyThread` helper (any caller becomes "always returns false", so remove the call too).
   8. `frontend/src/core/workspace-refresh/index.ts` — drop the `` `dreamy:${string}` `` event variant.
   9. `frontend/src/components/workspace/chat-ui/mount-folder-badge.tsx` — cosmetically rename the react-query keys (or keep the `dreamy-` prefix for cache-key compatibility, no functional impact).
   10. `frontend/src/components/workspace/artifacts/context.tsx` — drop the stale dreamy comment.
   11. `frontend/src/core/i18n/locales/types.ts` and `en-US.ts` — drop the dreamy nav entry and pane copy bundle.

4. **Frontend file deletions**:
   - `frontend/src/components/workspace/dreamy/` (entire folder)
   - `frontend/src/core/dreamy/` (entire folder, incl. `hooks/`)
   - `frontend/src/app/workspace/dreamy/` (entire folder)

5. **Verification**:
   - `make lint` (backend) — ensures no stray imports.
   - Frontend type check + build — catches dangling references.
   - Manual smoke: open `/workspace/chats/[thread_id]`, confirm chat works, confirm Plan-mode + Work-mode toggle, confirm `/mount` and `/analyse` still function (they're general-purpose, not Dreamy-owned).

## Risk Surface

| Area | Risk | Mitigation |
|---|---|---|
| Middleware DAG | Removing the `sandbox` `after={"dreamy_intent", "dreamy_bootstrap"}` edges could in principle re-order other middleware that depend transitively on `sandbox`. | Inspect the topological sort with the dreamy edges removed — `sandbox` still gates on `thread_data`, which is the only ordering Plan/Work mode rely on. |
| ThreadState | Removing `dreamy_mode` / `dreamy_intent` from `ThreadState` is a schema-narrowing change. Existing LangGraph checkpoints may include those keys. | LangGraph tolerates extra keys on read; new writes simply won't emit them. No migration needed. |
| Config | `summarization.modes.dreamy:` was looked up by string in `_create_summarization_middleware`. Removing the block and the `normalized_mode = "dreamy" if dreamy_mode else mode` line are paired changes. | Both are removed in step 1.1 / 1.7 simultaneously. |
| Frontend cache | React-query keys prefixed `dreamy-` in `mount-folder-badge.tsx` are persisted in some clients. | Either keep the prefix (no functional issue) or rename and accept a one-time cache invalidation. |
| Tests | The four `test_dreamy_*` files import the deleted middlewares. | They are deleted in step 2. No other test file references Dreamy. |

## Rollback

`git revert <removal-sha>` restores everything atomically. The reimplementation guide ([REIMPLEMENTATION.md](REIMPLEMENTATION.md)) is the manual alternative when `git revert` is not viable (e.g. after substantial drift in the surrounding code).
