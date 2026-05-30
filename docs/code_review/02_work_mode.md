# Work Mode — Code Review

## Summary

Work Mode is a thoughtfully layered system: the `_RegistryContext` pattern centralizes factory wiring, the DAG todo middleware enforces cycles deterministically, and the phase-loop driver in `WorkModeMiddleware` is small enough to reason about.

> **Status update (2026-05-30 recheck):** All 5 Critical and all 8 High findings (1–13) are resolved. Medium findings #14 and #23 are also resolved. Handoff & State Sync concern #3 (OSError swallow) is resolved. Several other items are partially addressed via incremental fixes (#16, #25, #30, TODO DAG #3, Handoff #4). The remaining open findings are tracked below with current severity reassessments.
>
> 16 findings cleared, 4 partially addressed, ~17 remain open.

## Resolved Findings

The following items have been fixed and verified by tests in the repo. They are listed here for traceability; full diffs are in the git history.

| # | Finding | Resolution |
|---|---------|------------|
| 1 | `_HANDOFF_GUARD` stale duplicate-detection entry on thread-start failure | `spawn_work_mode_handoff` now discards `thread_id` on `worker.start()` failure. |
| 2 | `WorkModeMiddleware._completed_before` per-instance state | Completion snapshot lives in `phase_execution["completed_snapshot_ids"]`. |
| 3 | `_is_acyclic` conflated cycle + dangling-dep detection | Split into `_is_acyclic` (pure) and `find_dangling_deps`. |
| 4 | `asyncio.run` per call in daemon thread | Persistent event loop per worker via `_run_awaitable_in_worker`. |
| 5 | `_get_memory_context` swallowed exceptions via `print` | Replaced with `logger.exception(...)`. |
| 6 | `TodoFailureRetryMiddleware._MAX_TODO_RECOVERY_ATTEMPTS` never reset across turns | Counter resets on new user `HumanMessage` via `todo_recovery_turn_key`. |
| 7 | Work-mode instruction interpolated todo content unescaped | Escape + length cap on todo content, rationale, id, subagent hint, clarification. |
| 8 | `_is_report_todo` over-triggered on common keywords | Driven by explicit `kind="report"` / `artifact_type="report"` metadata. |
| 9 | Memory injection used `\n<thinking_style>` anchor | Cached prompts use `<!--__MEMORY_INJECTION_POINT__-->` sentinel with idempotency. |
| 10 | `prompt_cache._cache` unbounded | LRU `OrderedDict` with `MAX_CACHE_ENTRIES = 64`. |
| 11 | `_load_canonical_plan_overrides` skipped DAG validation | Validates nodes, runs cycle check, recomputes ready_ids, falls back on failure. |
| 12 | `before_model` self-heal raced with `deferred_task_calls` | Age-aware via `phase_execution["in_progress_started_at"]` + grace threshold. |
| 13 | Stale `ephemeral_instruction_text` leaked across turns | Cleared on completion/stall/wait; todo-id match verified on inject. |
| 14 | `handoff_artifacts` write conflict between middlewares | `ThreadState.handoff_artifacts` uses additive `merge_artifacts` reducer ([thread_state.py:320](../../backend/src/agents/thread_state.py#L320)). |
| 23 | `_create_todo_failure_retry` lacked "no todos" early-out | `_has_incomplete_todos` now inspects `state.get("todo_graph")` and short-circuits. |
| H3 | `_load_canonical_plan_overrides` swallowed `OSError` | Now logs a warning before falling back. |

## Medium Severity (open)

### 15. `_run_work_mode_handoff` spawns `spawn_title_handoff_if_missing` without joining
- **File:** [backend/src/agents/middlewares/work_run_handoff.py:231](../../backend/src/agents/middlewares/work_run_handoff.py#L231)
- **Severity:** Medium (unchanged)
- **Issue:** Title-handoff daemon is fire-and-forget; work handoff proceeds immediately. If title generation and work handoff both call `update_state` at roughly the same time, one is rejected and silently retried. There's still no explicit ordering — title appearance in plan.md is timing-dependent.
- **Impact:** Inconsistent title rendering.
- **Recommendation:** Either inline the title fetch synchronously before `invoke_client_agent_async`, or have the title handoff write to a separate state field outside the plan dict.

### 16. `sync_handoff_files_from_state` re-renders plan.md on every cycle
- **File:** [backend/src/agents/middlewares/todo_middleware.py:130](../../backend/src/agents/middlewares/todo_middleware.py#L130), [handoff_sync.py:480-487](../../backend/src/agents/middlewares/handoff_sync.py#L480)
- **Severity:** ~~Medium~~ → **Low** (partially addressed)
- **Status:** A `_write_if_changed` byte-comparison guard now exists in `handoff_sync.py:480-487`, so no-op writes are suppressed. However the full plan render still runs every `after_model`, and the render path contains a `last_synced_at` timestamp that causes the byte-check to miss when only the timestamp differs.
- **Impact:** CPU/latency on the hot path; disk writes are no longer the worst-case.
- **Recommendation:** Hash the meaningful payload (todos + state, *sans* timestamp) and skip the render entirely when the hash is unchanged.

### 17. `TodoMiddleware` and `TodoDagMiddleware` both inject `name="todo_reminder"` HumanMessages
- **File:** [backend/src/agents/middlewares/todo_middleware.py:104](../../backend/src/agents/middlewares/todo_middleware.py#L104), [backend/src/agents/middlewares/todo_dag_middleware.py:376](../../backend/src/agents/middlewares/todo_dag_middleware.py#L376)
- **Severity:** ~~Medium~~ → **Low** (still present; impact is narrow)
- **Issue:** `_create_todo` picks one or the other based on `dag_enabled`, so they should not coexist. Risk surfaces only on config-flip mid-thread (e.g. `reload_app_config()` swapping `dag_enabled`), where both reminders could be emitted and each would pass the other's "already present" guard since both check `name=="todo_reminder"` only.
- **Impact:** Duplicate reminders on the rare config-flip boundary.
- **Recommendation:** Differentiate names (`todo_dag_reminder` vs `todo_list_reminder`) and have each guard check for both.

### 18. `_handle_plan_adapted` increments counter and emits SSE forever on stall
- **File:** [backend/src/agents/middlewares/work_mode_middleware.py:556-580](../../backend/src/agents/middlewares/work_mode_middleware.py#L556)
- **Severity:** Medium (unchanged)
- **Issue:** Every `before_model` cycle that ends in a stalled-plan state increments `adaptation_attempts` and emits a `plan_adapted` SSE. Since Work Mode no longer auto-respawns Plan Mode (per `CLAUDE.md`), `pending_nodes` will remain stuck and every subsequent cycle emits a fresh `plan_adapted` event.
- **Impact:** SSE spam; UI may enter a "switch to plan mode" loop.
- **Recommendation:** Emit the SSE only on the first occurrence per cycle; subsequent stalls should be silent until the user takes action.

### 19. `MiddlewareSpec("plan_followup")` is wired unconditionally in work_agent
- **File:** [backend/src/agents/work_agent/agent.py:541](../../backend/src/agents/work_agent/agent.py#L541)
- **Severity:** Medium (unchanged)
- **Issue:** `PlanFollowupMiddleware` is registered with no mode gate (no `_create_plan_followup` factory). It runs in pure work-mode turns, where its `plan_followup` SSE events have no UI meaning.
- **Impact:** Wasted cycles; possible UI confusion.
- **Recommendation:** Gate via `if not ctx.is_plan_mode: return None` factory pattern, matching `_create_todo_failure_retry`.

### 20. `merge_todo_nodes` shallow-copies nodes; `steps` field aliases between views
- **File:** [backend/src/agents/middlewares/todo_dag_middleware.py:202](../../backend/src/agents/middlewares/todo_dag_middleware.py#L202)
- **Severity:** Medium (unchanged)
- **Issue:** `merged = [dict(node) for node in existing_nodes ...]` is shallow. `_patch_existing` rebuilds `depends_on` so that field is safe, but `steps` is referenced by identity in both the patch branch (lines 236-241) and the new-node branch (line 279+). A planner-evaluator that mutates the step list elsewhere will mutate both views simultaneously.
- **Impact:** Aliasing bug under planner-evaluator patch flows.
- **Recommendation:** `copy.deepcopy` on merge, or explicitly rebuild `steps` on patch.

### 21. `WorkModeMiddleware` SSE failures swallowed with no replay
- **File:** [backend/src/agents/middlewares/work_mode_middleware.py:283-293, 369-381, 560-573](../../backend/src/agents/middlewares/work_mode_middleware.py#L283)
- **Severity:** Medium (unchanged)
- **Issue:** SSE emit failures are logged via `logger.exception` and swallowed. The surrounding state mutation (snapshot update, `phase_results` rewrite) proceeds even though the UI never saw the event. There is no compensating re-emit.
- **Impact:** A flaky stream writer permanently desyncs the UI from server state.
- **Recommendation:** Track an "unemitted events" buffer in state and flush on the next cycle.

### 22. `_write_scratchpad_artifact` writes on every cycle
- **File:** [backend/src/agents/middlewares/scratchpad_task_memory_middleware.py:82-101](../../backend/src/agents/middlewares/scratchpad_task_memory_middleware.py#L82)
- **Severity:** Medium (unchanged — the finding-16 byte-check does not extend here)
- **Issue:** `path.write_text(...)` runs unconditionally; no "if changed" guard. Combined with `sync_handoff_files_from_state` (now mostly no-op), the scratchpad is the dominant per-cycle disk write.
- **Impact:** Disk churn, FS watchers triggered each cycle, etag invalidation in UI.
- **Recommendation:** Read existing content first and skip the write when bytes match (the same shape as `_write_if_changed` in `handoff_sync.py`).

## Low Severity / Nits (open)

### 24. `_resolve_compaction_context_tokens` warning logs on every cold-start
- **File:** [backend/src/agents/work_agent/agent.py:147-151](../../backend/src/agents/work_agent/agent.py#L147)
- **Severity:** Low (unchanged)
- **Issue:** Every cold-start of summarization for a model with no profile and no config emits a `WARNING`. Noisy in production logs.
- **Recommendation:** Suppress via `lru_cache`-style memoization keyed on model id.

### 25. `_normalize_token_only_keep` silently degrades on unknown `kind`
- **File:** [backend/src/agents/work_agent/agent.py:191-206](../../backend/src/agents/work_agent/agent.py#L191)
- **Severity:** Low (partially addressed)
- **Status:** `kind == "messages"` now emits a warning. Any other unknown `kind` (e.g. `"seconds"`) still falls through to the default silently.
- **Recommendation:** Treat any unknown `kind` as warning + fallback.

### 26. `_build_subagent_section` repeats the `{n}` count three times
- **File:** [backend/src/agents/work_agent/prompt.py:18-49](../../backend/src/agents/work_agent/prompt.py#L18)
- **Severity:** Low (unchanged)
- **Issue:** `{n}` appears in three substrings of the same template; easy to drift if anyone updates the message.
- **Recommendation:** Compute the count string once at the top.

### 27. `LEGACY_SYSTEM_PROMPT_TEMPLATE` and `_build_componentized_prompt` diverge in section ordering
- **File:** [backend/src/agents/work_agent/prompt.py:56-171, 484-508](../../backend/src/agents/work_agent/prompt.py#L56)
- **Severity:** Low (unchanged)
- **Issue:** Both code paths still exist, selected by `prompt_cfg.componentized`. Section ordering differs (memory insertion in particular). Cache key includes `prompt_componentized`, so caching is sound — but A/B comparisons of behavior are confounded by structural drift.
- **Recommendation:** Generate both from the same section list with a flag, or delete the legacy template if no production callers depend on it.

### 28. `MiddlewareSpec("trajectory")` after-key only references `thread_data`
- **File:** [backend/src/agents/work_agent/agent.py:550-559](../../backend/src/agents/work_agent/agent.py#L550)
- **Severity:** Low (unchanged; explanatory comment added)
- **Issue:** A comment now documents the trade-off, but no unit test asserts that trajectory wraps `model_timeout`, `retry`, `subagent_limit`, etc. Topo sort is free to reorder.
- **Recommendation:** Add a unit test that pins the wrap ordering for trajectory.

### 29. `_topological_sort_middleware_specs` private alias still exported
- **File:** [backend/src/agents/work_agent/agent.py:280](../../backend/src/agents/work_agent/agent.py#L280)
- **Severity:** Low (unchanged — nit)
- **Status:** Alias still present, comment still promises cleanup once tests are updated.

### 30. `_RegistryContext` typing still partly loose
- **File:** [backend/src/agents/work_agent/agent.py:299-300](../../backend/src/agents/work_agent/agent.py#L299)
- **Severity:** Low (partially addressed)
- **Status:** `router: ModelRouter` is now typed properly. `model_config: object | None` remains loose.
- **Recommendation:** Type `model_config` to the actual config protocol/dataclass.

## Architectural Observations

1. **`agent.py` is still ~832 lines** — registry factories, summarization helpers, runtime-params extraction, the model resolver, and the LangGraph entry point are still tangled in one file. Moving factories to `agents/common/registry_factories.py` would shave significant complexity.

2. **Three independent "todo reminder" sources** — `TodoMiddleware`, `TodoDagMiddleware`, `TodoFailureRetryMiddleware` each inject their own reminders with separate counters and triggers. No single source of truth for "the model is stuck; remind it." Consolidating into one `TodoReminderMiddleware` with a strategy enum would simplify finding-17 plus the budget-drift class of bugs.

3. **Phase-loop driver coexists with TodoListMiddleware** — `WorkModeMiddleware` assigns next todos in work mode while `TodoMiddleware` is wired only for plan mode. The "what is the next todo" concern is split across both, and any third middleware that wants to re-order must mutate `todo_graph.nodes` directly without an API contract.

4. **Handoff state divergence** — `state["plan"]`, on-disk `plan.md`, and the `ThreadState` checkpoint can all disagree. Three writers (scratchpad, handoff_sync, work_run_handoff) and three readers touch handoff state without a single ownership boundary.

5. **No dead-letter for failed todos** — `TodoFailureRetryMiddleware` caps retries then silently logs and quits. There is no terminal `dead_letter`/`failed_terminal` status the UI can render; the user sees a todo stuck in `in_progress` with no signal that the system has stopped trying.

## TODO DAG specific concerns

1. **Cycle detection runs only at `normalize_todo_nodes` / `merge_todo_nodes`** — finding 11's fix added re-validation inside `_load_canonical_plan_overrides`, but neither `TodoDagMiddleware.before_model` nor `WorkModeMiddleware` re-checks the graph after state-channel merges from other sources. Still a risk if any future code path bypasses the canonical-load helper.

2. **`compute_effective_ready_ids` ignores `target_endpoint`** — readiness considers only status and clarification blocks. When the helper endpoint is saturated, the lead agent still believes a helper-targeted todo is ready and tries to dispatch, getting a deferred-task entry. UI flickers between "ready" and "deferred."

3. **`_slugify` collisions in `merge_todo_nodes`** — Severity downgrade. `normalize_todo_nodes` now appends `-2`, `-3` suffixes on collision. `merge_todo_nodes` (lines 254, 290) still calls `_slugify` without the dedupe loop and relies only on the `index` argument — two genuine duplicates can still pass through indistinguishable to the model.

4. **`ready_ids` is computed twice per cycle** — `TodoDagMiddleware._recompute_state` (~line 396) and `WorkModeMiddleware._materialize_ready_ids` (~line 296) both call the same function. If clarifications change between the two calls, they disagree.

5. **`_materialize_ready_ids` imported across module boundaries** — `work_mode_middleware.py:45` imports the private helper from `todo_dag_middleware`. A documented "Import rule" comment exists but the contract is still fragile. Promote to `agents/common/todo_graph.py`.

## Handoff & State Sync concerns

1. **`spawn_work_mode_handoff` has no observability** — Daemon logs exceptions and increments retry counters but emits no SSE/runtime events on retry or permanent failure. From the frontend perspective the handoff is invisible until a `plan` state update lands; if it fails permanently after `max_attempts`, the user sees the plan stuck in "approved" forever.

2. **`mark_handoff_succeeded` / `mark_handoff_failed` race on stale read** — [work_run_handoff.py:301-310, 334-346](../../backend/src/agents/middlewares/work_run_handoff.py#L301) re-reads state then calls `update_state` without a version/etag check. A concurrent user message updating the plan status will be clobbered.

3. **`replace_virtual_path` with potentially missing `thread_data`** — Partially addressed. `handoff_sync.py:490-493` now has a `_can_resolve_write_path` guard that returns False when `path.startswith("/mnt/")` and `thread_data` is falsy, blocking the bad call. The `_load_canonical_plan_overrides` path itself still depends on `thread_data` being populated in `values` at handoff time and could surface symptoms in edge cases (e.g. fresh runs before `ThreadDataMiddleware` first executes).

4. **`sync_handoff_files_from_state` writes `plan_path` and `latest_alias_path` with identical content** — [handoff_sync.py:577-587](../../backend/src/agents/middlewares/handoff_sync.py#L577). Intentional on Local sandbox (versioned + alias), but on read-only sandboxes that fail silently this doubles the failure surface. Worth a sandbox-capability check before the second write.

5. **`spawn_title_handoff_if_missing` uses `time.sleep(0.4)` in a retry loop** — [work_run_handoff.py:163](../../backend/src/agents/middlewares/work_run_handoff.py#L163). Fixed 0.4s sleep, no exponential backoff. If the LangGraph SDK is throttling, this hammers it.
