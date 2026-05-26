# Dreamy Architecture

## 1. Runtime Mental Model

Dreamy is a **mode flag** carried in the LangGraph runtime context (`context.dreamy_mode: bool`) plus a chain of middlewares and a frontend pane that read/write that flag. There is no persisted "Dreamy session" record — once the flag goes false, the thread reverts to a normal chat thread (with the chat history intact, and any `workflow.json` left behind in `/mnt/user-data/workspace/`).

### State surfaces

| Surface | Field | Owner |
|---|---|---|
| LangGraph runtime context | `context.dreamy_mode: bool` | `RunnableConfig.configurable` (set by the API caller — the frontend's run-create payload). |
| LangGraph state schema | `ThreadState.dreamy_mode: bool`, `ThreadState.dreamy_intent: DreamyIntentState` | `DreamyIntentMiddleware.before_agent` returns a state update; `DreamyIntentState` defined in `thread_state.py`. |
| Frontend thread cache | `thread.values.dreamy_mode`, `thread.values.dreamy_intent` | LangGraph SDK sync — wired in `frontend/src/core/threads/hooks.ts`. |
| Frontend pane state | `dreamyActive`, `onActivateDreamy`, `onDeactivateDreamy` | `DreamyProvider` context (`frontend/src/core/dreamy/context.tsx`). |
| On-disk thread state | `<thread_dir>/dreamy_resumption.json`, `<thread_dir>/user-data/dreamy_mount.json`, `<thread_dir>/user-data/outputs/workflow.json`, `<thread_dir>/user-data/repo_overview_refresh_jobs.json` | `dreamy_state_preservation_hook` + gateway router. |

The single source of truth at run time is `RunnableConfig.configurable.dreamy_mode`. Every middleware reads it from `Runtime.context`.

## 2. Lifecycle Of A Dreamy Turn

```
                                          ┌────────────────────────────────┐
                                          │ Frontend: Dreamy pane open     │
                                          │ - sets `dreamy: true` on run   │
                                          │   payload via DreamyProvider   │
                                          └──────────────┬─────────────────┘
                                                         │
                                            POST /api/langgraph/.../runs
                                            { configurable: { dreamy_mode: true, ... } }
                                                         │
                          ┌──────────────────────────────▼──────────────────────────────┐
                          │ LangGraph Server → make_lead_agent(config)                  │
                          │                                                             │
                          │ Middleware DAG (ordered by topological sort of `after`):    │
                          │   thread_data → dreamy_watchdog → dreamy_intent             │
                          │              → dreamy_bootstrap → sandbox → dreamy_poc      │
                          │              → dreamy_execution → … → trajectory            │
                          │                                                             │
                          │   summarization is fed `dreamy_mode=True` so the dreamy     │
                          │   state-preservation hook runs before compaction.           │
                          │                                                             │
                          │ Subagents are FORCE-DISABLED when dreamy_mode is true       │
                          │ (`_RegistryContext.subagent_enabled = False if dreamy_mode`)│
                          └──────────────┬──────────────────────────────────────────────┘
                                         │
                                         ▼
                          model is invoked with `DREAMY_MODE_SECTION` appended to
                          the system prompt (prompt.py). The model reads
                          `workflow.json` from `/mnt/user-data/workspace/` and
                          executes exactly one step for the row pointed to by
                          execution_state.current_row_index / current_step_id,
                          then writes execution_state back.
```

## 3. Middleware Pipeline (exact insertion points)

This is the subset of `_build_middlewares` in `backend/src/agents/lead_agent/agent.py` that Dreamy owned:

```python
specs = [
    MiddlewareSpec("thread_data",       lambda: ThreadDataMiddleware()),
    MiddlewareSpec("steering",          lambda: SteeringMiddleware(),     after={"thread_data"}, before={"uploads"}),

    # === Dreamy block ==========================================================
    MiddlewareSpec("dreamy_watchdog",   lambda: DreamyWatchdogMiddleware(),    after={"thread_data"}),
    MiddlewareSpec("dreamy_intent",     lambda: DreamyIntentMiddleware(),      after={"thread_data", "dreamy_watchdog"}),
    MiddlewareSpec("dreamy_bootstrap",  lambda: DreamyBootstrapMiddleware(),   after={"thread_data", "dreamy_intent", "dreamy_watchdog"}),
    MiddlewareSpec("dreamy_poc",        lambda: DreamyPocMiddleware(),         after={"dreamy_bootstrap", "thread_data", "dreamy_watchdog"}),
    MiddlewareSpec("dreamy_execution",  lambda: DreamyExecutionMiddleware(),   after={"dreamy_poc", "thread_data", "sandbox", "dreamy_watchdog"}),
    # === end Dreamy block ======================================================

    MiddlewareSpec("uploads",           lambda: UploadsMiddleware(),           after={"thread_data"}),
    MiddlewareSpec("mount_folder",      lambda: MountFolderMiddleware(),       after={"uploads", "thread_data"}),
    MiddlewareSpec("sandbox",           lambda: SandboxMiddleware(),           after={"thread_data", "dreamy_intent", "dreamy_bootstrap"}),
    # ... rest of the pipeline (unchanged) ...
    MiddlewareSpec("summarization",
        lambda: _create_summarization_middleware(mode=mode, dreamy_mode=dreamy_mode),
        after={"dangling_tool_call"}),
]
```

**Reverse-edge note:** `sandbox` declares `after={"thread_data", "dreamy_intent", "dreamy_bootstrap"}` so the sandbox is acquired *after* dreamy_intent has had a chance to flip `dreamy_mode` to false on `/dreamy-exit`. The execution middleware in turn waits for the sandbox to be live.

### Responsibility split

| Middleware | Role |
|---|---|
| `DreamyWatchdogMiddleware` | Bounded-time watchdog for long-running Dreamy runs. Reads `DreamyTimeoutConfig`. Cancels or marks runs stuck past thresholds. |
| `DreamyIntentMiddleware` | Strips `/dreamy` / `/workflow` prefix from the latest human turn, classifies workflow-design intent (shape detection — table/csv/list/free_text — and field extraction). Handles `/dreamy-exit` by writing `{"dreamy_mode": False}`. Emits `dreamy_intent_detected` / `dreamy_mode_exited` runtime events. |
| `DreamyBootstrapMiddleware` | One-shot bootstrap. Detects the data source (mounted folder vs inline). Spawns `load_tasks.py` helper subprocess (bounded by `DreamyTimeoutConfig.bootstrap_subprocess_timeout`). Produces the initial `workflow.json` skeleton when one does not exist. |
| `DreamyPocMiddleware` | Proof-of-concept phase. Runs the workflow against the first row (or sample rows) so the user can approve before bulk execution. Sets `execution_state.phase = "awaiting_approval"`. |
| `DreamyExecutionMiddleware` | Bulk execution. Reads `execution_state.current_row_index` / `current_step_id`, asks the model to execute one step at a time, writes state back, advances on success, calls `checkpoint.py --mark-done` per completed row. |
| `dreamy_state_preservation_hook` (memory hook, not a middleware) | Wired into `CapyHomeSummarizationMiddleware.before_summarization` when `dreamy_mode=True`. Snapshots `dreamy_intent`, the last 5 messages tagged `name="dreamy_anchor"`, and persists to `<thread_dir>/dreamy_resumption.json` so context compaction does not destroy workflow continuity. |

## 4. Backend Wiring Points

The non-middleware backend integrations:

| Location | What it does |
|---|---|
| `backend/src/agents/lead_agent/agent.py` (imports L12, L18-L22) | Imports the five middleware classes + the state-preservation hook. |
| `backend/src/agents/lead_agent/agent.py` L223-L283 (`_create_summarization_middleware`) | Accepts `dreamy_mode: bool`, normalises mode to `"dreamy"` for picking the per-mode summarization profile, and appends `dreamy_state_preservation_hook` to `before_summarization`. |
| `backend/src/agents/lead_agent/agent.py` L548-L554 (`_build_middlewares` top) | Reads `dreamy_mode = bool(cfg.get("dreamy_mode", False))` from `RunnableConfig.configurable`, forces `subagent_enabled=False` when dreamy. |
| `backend/src/agents/lead_agent/agent.py` L569-L573 | The five Dreamy `MiddlewareSpec` entries (see DAG above). |
| `backend/src/agents/lead_agent/agent.py` L576 | `sandbox` declares `after={"…", "dreamy_intent", "dreamy_bootstrap"}`. |
| `backend/src/agents/lead_agent/agent.py` L588 | `summarization` passes `dreamy_mode` through to `_create_summarization_middleware`. |
| `backend/src/agents/lead_agent/agent.py` L710-L721 (`_extract_runtime_params`) | Re-reads `dreamy_mode`, propagates `subagent_enabled=False` when true. |
| `backend/src/agents/lead_agent/agent.py` L788, L866 (`make_lead_agent`) | Passes `dreamy_mode` to `apply_prompt_template`. |
| `backend/src/agents/lead_agent/prompt.py` L501-L530 | `DREAMY_MODE_SECTION` system-prompt fragment (the rulebook the model sees inside Dreamy mode). |
| `backend/src/agents/lead_agent/prompt.py` L617, L636-L637 (`apply_prompt_template`) | Appends `DREAMY_MODE_SECTION` to the rendered prompt when `dreamy_mode=True`. |
| `backend/src/agents/thread_state.py` L157-L163 (`DreamyIntentState`) | TypedDict for the per-turn intent classifier output. |
| `backend/src/agents/thread_state.py` L256-L257 | `ThreadState.dreamy_mode` / `ThreadState.dreamy_intent` fields (NotRequired). |
| `backend/src/agents/memory/dreamy_state_preservation_hook.py` | The compaction-aware state preserver. |
| `backend/src/gateway/app.py` L19, L113-L119, L379 | Imports the `dreamy` router, runs `initialize_repo_overview_refresh_jobs()` on lifespan startup, mounts `dreamy.router`. |
| `backend/src/gateway/routers/dreamy.py` | The whole router (mount-folder, analyse, repo-overview-refresh, workflow.json CRUD, publishdocs). |
| `backend/src/config/dreamy_timeout_config.py` | `DreamyTimeoutConfig` model + module-level singleton + load helper. |
| `backend/src/config/__init__.py` L3, L35-L36 | Re-exports `DreamyTimeoutConfig`, `get_dreamy_timeout_config`. |
| `backend/src/config/app_config.py` L21, L74-L76, L199-L200 | Embeds dreamy timeout config into `AppConfig`; calls `load_dreamy_timeout_config_from_dict` at load time. |
| `backend/src/config/summarization_config.py` L58 | Doc-string mentions `dreamy` as a valid per-mode key (no functional dependency — see `_create_summarization_middleware` for the consumer). |
| `backend/src/config/question_generation_config.py` L13-L15 | `enabled_in_dreamy: bool` switch (controls whether question generation runs inside Dreamy threads). |
| `config.yaml` / `config.example.yaml` | `summarization.modes.dreamy:` block, `question_generation.enabled_in_dreamy`, top-level `dreamy_timeout:` section. |
| `skills/dreamy-workflow/SKILL.md` | The progressive-disclosure skill the model loads on entering Dreamy mode (referenced explicitly in `DREAMY_MODE_SECTION`). |

## 5. Frontend Wiring Points

| Location | What it does |
|---|---|
| `frontend/src/core/dreamy/api.ts` | Typed fetch client for the gateway `/api/threads/{id}/dreamy/...` endpoints. |
| `frontend/src/core/dreamy/types.ts` | TypeScript shape mirrors for `WorkflowJson`, `DreamyIntent`, `MountFolderConfig`, etc. |
| `frontend/src/core/dreamy/constants.ts` | Constants (default poll intervals, phase strings, etc.). |
| `frontend/src/core/dreamy/context.tsx` | `DreamyProvider` React context. Holds `dreamyActive`, `onActivateDreamy`, `onDeactivateDreamy`. Wrapped around chat layouts via `<DreamyProvider>{children}</DreamyProvider>` in `app/workspace/chats/[thread_id]/layout.tsx` and `app/workspace/agents/[agent_name]/chats/[thread_id]/layout.tsx`. |
| `frontend/src/core/dreamy/error-boundary.tsx` | Dreamy-pane-specific React error boundary. |
| `frontend/src/core/dreamy/hooks/` | The hook surface used by the Dreamy pane (workflow JSON polling, mounted folder, checkpoint, progress, file preview, folder picker, macOS file actions, step highlighting). |
| `frontend/src/components/workspace/dreamy/` | The pane itself: `dreamy-workflow-pane.tsx` (root), `dreamy-box.tsx`, `dreamy-step-editor.tsx`, `dreamy-steps-list.tsx`, `dreamy-add-step-dialog.tsx`, `dreamy-progress-header.tsx`, directory & file-preview helpers. |
| `frontend/src/app/workspace/dreamy/[thread_id]/page.tsx` + `layout.tsx` | The dedicated Dreamy route. The layout wraps in `<DreamyProvider>` and renders the workflow pane. |
| `frontend/src/components/workspace/input-box.tsx` | Accepts `dreamy`, `dreamyActive`, `onActivateDreamy`, `onDeactivateDreamy` props. Implements `executeSlashCommand("dreamy" \| "dreamy-exit", ...)`. Calls `api.threads.dreamy.*` endpoints for `/mount`, `/analyse`, `/publishdocs`. Sets `dreamy: isDreamyThread` on outgoing run payloads. |
| `frontend/src/core/threads/slash-commands.ts` | `"dreamy"`, `"dreamy-exit"` in `SlashCommandName` union and `SUPPORTED_COMMANDS` set. *(In the final state at removal time these had already been pulled out of the slash-command registry — verify before reinstating.)* |
| `frontend/src/core/threads/types.ts` L100-L101, L134 | `ThreadStateValues.dreamy_mode`, `.dreamy_intent`; `RunCreatePayload.dreamy_mode`. |
| `frontend/src/core/threads/hooks.ts` L15, L1116-L1138 | Imports `api` from `core/dreamy/api`. Forwards `dreamy_mode` / `dreamy_intent` deltas from LangGraph state-stream into the thread cache. |
| `frontend/src/core/threads/utils.ts` L5, L11-L16 | `DREAMY_TITLE_PREFIX = "✨ "`, `isDreamyThread(thread)` checks `values.dreamy_mode` OR title prefix. |
| `frontend/src/core/workspace-refresh/index.ts` L25 | Workspace-refresh event union includes `` `dreamy:${string}` `` so the pane can listen for backend-triggered refresh events. |
| `frontend/src/components/workspace/chat-ui/mount-folder-badge.tsx` L54, L58 | Queries keyed `["dreamy-mounted-folder", threadId]` and `["dreamy-mounted-folder-files", threadId]`. *(The mount-folder feature itself is general-purpose now — only the cache keys carry the historical "dreamy-" prefix.)* |
| `frontend/src/components/workspace/artifacts/context.tsx` L49 | Comment mentioning Dreamy sidebar UX (no functional dependency). |
| `frontend/src/core/i18n/locales/types.ts` L146, L502-L503; `en-US.ts` L187, L570 | i18n strings for the Dreamy nav entry and pane copy. |

## 6. The `workflow.json` Schema

Persisted at `/mnt/user-data/workspace/workflow.json` (per-thread). Two versions:

**v1 (legacy, auto-migrated in-memory by the gateway):**

```jsonc
{
  "version": "1",
  "thread_id": "...",
  "created_at": "ISO-8601",
  "task_source": { "type": "...", "filename": "...", "total_tasks": 0, "fields": [], "sample_tasks": [] },
  "execution_state": {
    "phase": "design | approval | bulk | done",
    "current_task_index": 0,
    "active_node_id": "step_id_or_null",
    "total_tasks": 0,
    "estimated_completion_iso": "...",
    "started_at": "..."
  },
  "dag": {} // legacy DAG node graph
}
```

**v2 (current at removal time):**

```jsonc
{
  "version": "2",
  "thread_id": "...",
  "created_at": "ISO-8601",
  "data_source": {
    "type": "inline | csv | xlsx | mounted_folder",
    "filename": "...",
    "total_rows": 0,
    "fields": ["col1", "col2"],
    "sample_rows": [{...}]
  },
  "steps": [
    { "id": "step_1", "name": "...", "instructions": "...", "outputs": [...] }
  ],
  "execution_state": {
    "phase": "design | awaiting_approval | bulk | done",
    "current_row_index": 0,
    "current_step_id": "step_1",
    "total_rows": 0,
    "poc_results": [],
    "seconds_per_row_estimate": null,
    "estimated_completion_iso": null,
    "started_at": null
  }
}
```

`_maybe_migrate_v1` in `backend/src/gateway/routers/dreamy.py` performs the in-memory migration when a v1 file is read. v1 → v2 conversion is *not* written back to disk automatically.

## 7. Gateway Endpoints (under `dreamy` router)

All mounted under `prefix="/api"`, tags `["dreamy"]`:

| Method | Path | Purpose |
|---|---|---|
| GET    | `/threads/{thread_id}/dreamy/workflow` | Read `workflow.json` (with in-memory v1→v2 migration). |
| PATCH  | `/threads/{thread_id}/dreamy/workflow` | Persist node-editor edits to `workflow.json`. |
| GET    | `/threads/{thread_id}/dreamy/mount-folder` | Read configured mounted folder for the thread. |
| POST   | `/threads/{thread_id}/dreamy/mount-folder` | Set/replace mounted folder (writes `<user-data>/dreamy_mount.json`). |
| POST   | `/threads/{thread_id}/analyse` | Mirror mounted folder into `/mnt/user-data/workspace/.docs` as markdown (and analyse manifests into `.analyse/`). Auto-enqueues a repo-overview-refresh job. |
| GET    | `/threads/{thread_id}/analyse/status` | Whether staged docs/analysis exist. |
| POST   | `/threads/{thread_id}/analyse/repo-overview-refresh` | Enqueue a model-driven refresh of `repo_overview.md`. |
| GET    | `/threads/{thread_id}/analyse/repo-overview-refresh/{job_id}` | Poll job status. |
| POST   | `/threads/{thread_id}/publishdocs` | Copy `.docs` mirror back to `<mounted_folder>/.docs/`. Gated by latest refresh status unless `?force=true`. |

Plus a startup hook: `initialize_repo_overview_refresh_jobs()` resumes any queued/running jobs across all threads after a gateway restart.

## 8. On-Disk Layout (per thread)

```
backend/.capyhome/threads/<thread_id>/
├── dreamy_resumption.json                       # state-preservation snapshot (anchors + intent)
├── user-data/
│   ├── dreamy_mount.json                        # { "path": "/abs/host/path" }
│   ├── repo_overview_refresh_jobs.json          # job ledger (persisted across restarts)
│   ├── outputs/
│   │   └── workflow.json                        # the workflow doc
│   └── workspace/
│       ├── .docs/...                            # markdown mirror produced by /analyse
│       └── .analyse/
│           ├── index.md
│           ├── directory_tree.md
│           ├── file_catalog.md
│           ├── created_files.md
│           ├── failed_files.md
│           ├── repo_overview.md
│           └── repo_overview.previous.md
```

## 9. Cross-References (do-not-touch list)

Things that *look* Dreamy-adjacent but are general-purpose and stayed:

- `MountFolderMiddleware` (`backend/src/agents/middlewares/mount_folder_middleware.py`) — used by both Dreamy and Work/Plan flows; do not delete.
- `mount-folder-badge.tsx` — uses `dreamy-mounted-folder` query keys but the feature itself is generic. The query-key strings should be renamed *if* Dreamy is permanently retired; if Dreamy is coming back, leave them.
- `summarization.modes.dreamy` in `config.yaml` — only meaningful when a `dreamy_mode` flag exists. Removed alongside Dreamy and must be reintroduced if the mode is brought back.
- `question_generation.enabled_in_dreamy` — same as above.
