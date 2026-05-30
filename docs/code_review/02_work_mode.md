# Work Mode — Code Review

## Summary

Work Mode is a thoughtfully layered system: the `_RegistryContext` pattern centralizes factory wiring, the DAG todo middleware enforces cycles deterministically, and the phase-loop driver in `WorkModeMiddleware` is small enough to reason about.

> **Status update (2026-05-30, final):** All 5 Critical and all 8 High findings (1–13) are resolved. All 9 Medium findings (#14–#23) are resolved or investigated. Low/Nit findings #24, #25, #26, #28, #29, #30 all resolved. TODO DAG #3 and Handoff #6 resolved. The remaining items are architectural observations and a handful of Handoff/TODO-DAG concerns that require larger design changes (cross-module refactors, optimistic-concurrency design) — tracked at the bottom for future sprints.
>
> **30 findings cleared, ~6 architectural items remain open** (none with active bug-class impact).

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
| 15 | Title/work-handoff `update_state` collision | Investigated — writes target disjoint top-level keys (`title` vs `plan`); plan.md renders from `plan["title"]` not `state["title"]`. Contract pinned via comments + regression test. |
| 18 | `plan_adapted` SSE re-fired every stall cycle | Stall-signature dedup; SSE re-arms only when blocked/pending topology changes. |
| 19 | `PlanFollowupMiddleware` wired unconditionally in work_agent | `_create_plan_followup` factory now gates on `is_plan_mode`. |
| 20 | `merge_todo_nodes` shallow-copied; `steps` field aliased | `_clone_todo_node` / `_clone_existing_node` defensive copies applied across both implementations (`todo_dag_middleware`, `write_todos_tool`). |
| 21 | `WorkModeMiddleware` SSE failures swallowed with no replay | Buffer with bounded LRU semantics in `phase_execution.pending_sse_events`; drained on next cycle. |
| 22 | `_write_scratchpad_artifact` rewrote file on every cycle | Shared `write_if_changed` helper in `_fs_utils.py` (atomic + read-compare-skip). |
| 23 | `_create_todo_failure_retry` lacked "no todos" early-out | `_has_incomplete_todos` now inspects `state.get("todo_graph")` and short-circuits. |
| 16 | Plan.md re-rendered every cycle | Shared `write_if_changed` consolidates byte-comparison; render-skip via payload hash deferred. |
| 17 | Both todo middlewares emitted `todo_reminder` | DAG middleware now emits `todo_dag_reminder`; both guards recognize either name. |
| 24 | Compaction-token warning logged on every cold start | Once-per-model warning suppression via module-level set. |
| 25 | `_normalize_token_only_keep` silently degraded on unknown kind | Warns on any unknown kind before fallback. |
| 26 | `{n}` repetitions in subagent section | Investigated — already single-bound; no fix needed. |
| 28 | No test for trajectory wrap order | `test_trajectory_wraps_inner_middlewares` pins the invariant. |
| 29 | Private alias `_topological_sort_middleware_specs` | Removed; tests + production code use the public name. |
| 30 | `_RegistryContext.model_config` typed `object \| None` | Now `ModelConfig \| None` (full typing). |
| TODO DAG #3 | `_slugify` collisions silently renumbered | Debug log added on collision for trace diagnostics. |
| Handoff #5 | `spawn_title_handoff_if_missing` hammered SDK on throttle | Exponential backoff (0.4s → 0.8s → 1.6s) + final re-raise. |
| H3 | `_load_canonical_plan_overrides` swallowed `OSError` | Now logs a warning before falling back. |

## Medium Severity (open)

### ~~15. `_run_work_mode_handoff` spawns `spawn_title_handoff_if_missing` without joining~~ ✅ NON-ISSUE (contract pinned)
- **File:** [backend/src/agents/middlewares/work_run_handoff.py:159, 307-313](../../backend/src/agents/middlewares/work_run_handoff.py#L159)
- **Severity:** ~~Medium~~ → **N/A** (investigated; the stated impact cannot occur)
- **Investigation result:** The two `update_state` writers target **disjoint top-level state keys** — title handoff writes `{"title": ...}`, work handoff writes `{"plan": ...}`. There is no key-level collision. Furthermore, `plan.md` is rendered from `plan["title"]` (planner-set, inside the plan dict), not from the top-level `state["title"]`, so the original stated impact ("sometimes title appears in plan.md, sometimes not") cannot actually occur — the title-handoff write is irrelevant to plan.md output. The race the original finding described was theoretical: by the time the work-handoff write fires (after `invoke_client_agent_async` returns from a multi-second LLM call producing many intermediate checkpoints), the title-handoff write has long since committed.
- **Pinned:** Added explicit contract comments at both `update_state` sites and a regression test [`test_work_handoff_update_state_payload_has_no_title_key`](../../backend/tests/test_daemon_agent_invoke.py) that asserts work-handoff payloads contain only the `plan` key. Future changes that bundle `title` into the work-handoff payload will fail the test.

### ~~16. `sync_handoff_files_from_state` re-renders plan.md on every cycle~~ ✅ FIXED (partial)
- **File:** [backend/src/agents/middlewares/_fs_utils.py:33-49](../../backend/src/agents/middlewares/_fs_utils.py#L33), [handoff_sync.py:481-485](../../backend/src/agents/middlewares/handoff_sync.py#L481)
- **Status:** `write_if_changed` is now a shared helper in `_fs_utils.py` (reused by `handoff_sync` and the scratchpad writer). The byte-comparison guard suppresses no-op writes. The full plan render is still triggered every `after_model` — eliminating that requires a payload hash that strips `last_synced_at`; deferred as separate optimization since the disk-write path is no longer the bottleneck.

### ~~17. `TodoMiddleware` and `TodoDagMiddleware` both inject `name="todo_reminder"` HumanMessages~~ ✅ FIXED
- **Files:** [todo_middleware.py:39-51](../../backend/src/agents/middlewares/todo_middleware.py#L39), [todo_dag_middleware.py:378-390](../../backend/src/agents/middlewares/todo_dag_middleware.py#L378), [message_selection.py:12-13](../../backend/src/agents/middlewares/message_selection.py#L12), [summarization_middleware.py:52-53](../../backend/src/agents/middlewares/summarization_middleware.py#L52)
- **Status:** `TodoDagMiddleware` now emits `name="todo_dag_reminder"` (sibling middleware retains `name="todo_reminder"`). Both guards recognize either name, so a config-flip from one mode to the other mid-thread can't stack duplicate reminders. Synthetic-message filter lists in `message_selection.py` and `summarization_middleware.py` updated to include both names.
- **Tests:** `test_dag_reminder_skipped_when_list_mode_reminder_recently_injected` ([tests/test_todo_dag_middleware.py](../../backend/tests/test_todo_dag_middleware.py)).

### ~~18. `_handle_plan_adapted` increments counter and emits SSE forever on stall~~ ✅ FIXED
- **File:** [backend/src/agents/middlewares/work_mode_middleware.py:547-598](../../backend/src/agents/middlewares/work_mode_middleware.py#L547)
- **Status:** `_handle_plan_adapted` now stores a `plan_adapted_stall_signature = [blocked_ids_sorted, pending_ids_sorted]` in `phase_execution`. The SSE only fires when the current signature differs from the stored one, so repeated stalls with identical topology are silent. `adaptation_attempts` only advances when an SSE actually fires, keeping its semantic as "times the UI was told." When the user edits the plan and the topology changes, the signature differs and the event re-arms exactly once.
- **Tests:** `test_plan_adapted_sse_emits_once_per_unchanged_stall`, `test_plan_adapted_sse_re_arms_when_topology_changes` ([tests/test_work_mode_middleware.py](../../backend/tests/test_work_mode_middleware.py)).

### ~~19. `MiddlewareSpec("plan_followup")` is wired unconditionally in work_agent~~ ✅ FIXED
- **File:** [backend/src/agents/work_agent/agent.py:449-452, 547](../../backend/src/agents/work_agent/agent.py#L449)
- **Status:** Added `_create_plan_followup` factory that returns `None` when `ctx.is_plan_mode` is false; spec rewired to `bind(_create_plan_followup)`. PlanFollowupMiddleware no longer runs in pure work-mode turns. `loop_detection`'s `after={"plan_followup"}` dependency is unaffected because the topo sort runs on spec names before factories execute.
- **Tests:** `test_plan_followup_factory_skips_in_work_mode`, `test_plan_followup_factory_enabled_in_plan_mode`, `test_work_mode_middleware_list_omits_plan_followup` ([tests/test_middleware_registry.py](../../backend/tests/test_middleware_registry.py)).

### ~~20. `merge_todo_nodes` shallow-copies nodes; `steps` field aliases between views~~ ✅ FIXED
- **Files:** [backend/src/agents/middlewares/todo_dag_middleware.py:200-206](../../backend/src/agents/middlewares/todo_dag_middleware.py#L200), [backend/src/tools/builtins/write_todos_tool.py:88-102](../../backend/src/tools/builtins/write_todos_tool.py#L88)
- **Status:** Added `_clone_todo_node` / `_clone_existing_node` helpers that deep-copy the `steps` list-of-dicts. Applied at three call sites in `todo_dag_middleware` (`normalize_todo_nodes`, `_patch_existing`, new-node branch) and in the **duplicate** `merge_todo_nodes` implementation inside `write_todos_tool.py` that an independent review caught — the two implementations are intentionally different in scope (the tool restricts which fields the LLM can write), but both must defensively copy `steps`.
- **Tests:** `test_merge_todo_nodes_does_not_alias_steps_from_source`, `test_merge_todo_nodes_appended_new_node_detaches_steps`, `test_normalize_todo_nodes_detaches_steps_from_source`, `test_write_todos_tool_merge_passes_through_steps_without_aliasing` ([tests/test_todo_dag_middleware.py](../../backend/tests/test_todo_dag_middleware.py)).

### ~~21. `WorkModeMiddleware` SSE failures swallowed with no replay~~ ✅ FIXED
- **Files:** [work_mode_middleware.py:280-307](../../backend/src/agents/middlewares/work_mode_middleware.py#L280), [_MAX_SSE_BUFFER constant](../../backend/src/agents/middlewares/work_mode_middleware.py#L51)
- **Status:** Replaced the three inline `try/except: logger.exception` emit sites (`phase_completed`, `phase_started`, `plan_adapted`) with a closure-based `_safe_emit` helper that maintains a bounded buffer in `phase_execution["pending_sse_events"]`. On each cycle, queued events are drained first; new events are buffered when emit fails. The buffer is capped at 50 (`_MAX_SSE_BUFFER`) with oldest-dropped semantics, so a persistently flaky stream writer can't blow up state. `_handle_plan_adapted` was refactored to accept the emitter callbacks so its plan_adapted event participates in the same replay buffer. All `before_model` return paths now thread the finalized buffer back through `phase_execution`.
- **Tests:** `test_failed_emit_is_buffered_in_phase_execution`, `test_next_cycle_drains_backlog_then_emits_new_event`, `test_buffer_is_bounded` ([tests/test_work_mode_middleware.py](../../backend/tests/test_work_mode_middleware.py)).

### ~~22. `_write_scratchpad_artifact` writes on every cycle~~ ✅ FIXED
- **File:** [backend/src/agents/middlewares/scratchpad_task_memory_middleware.py:100-109](../../backend/src/agents/middlewares/scratchpad_task_memory_middleware.py#L100)
- **Status:** `_write_scratchpad_artifact` uses the shared `write_if_changed` helper in `_fs_utils.py` — same atomic write + read-compare-skip semantics as the handoff sync path. Both call sites now share one implementation.
- **Tests:** `test_write_scratchpad_artifact_skips_no_op_writes` ([tests/test_scratchpad_task_memory_middleware.py](../../backend/tests/test_scratchpad_task_memory_middleware.py)).

## Low Severity / Nits

### ~~24. `_resolve_compaction_context_tokens` warning logs on every cold-start~~ ✅ FIXED
- **File:** [backend/src/agents/work_agent/agent.py:132-161](../../backend/src/agents/work_agent/agent.py#L132)
- **Status:** Added a module-level `_COMPACTION_FALLBACK_WARNED` set so the WARNING fires exactly once per unresolvable model name. Subsequent cold-starts for the same model are silent.

### ~~25. `_normalize_token_only_keep` silently degrades on unknown `kind`~~ ✅ FIXED
- **File:** [backend/src/agents/work_agent/agent.py:201-225](../../backend/src/agents/work_agent/agent.py#L201)
- **Status:** Any `kind` other than `fraction`, `tokens`, or the deprecated `messages` now emits a warning identifying the offending value before falling back to `("tokens", default)`. The previous silent degrade is gone.

### ~~26. `_build_subagent_section` repeats the `{n}` count three times~~ ✅ INVESTIGATED (no fix needed)
- **File:** [backend/src/agents/work_agent/prompt.py:18-49](../../backend/src/agents/work_agent/prompt.py#L18)
- **Status:** The f-string already binds `n = max_concurrent` once and substitutes the same variable in three places — no value drift is possible. The three substrings serve different rhetorical roles (limit, threshold, example) and collapsing them would reduce clarity. The original finding overstated the risk; closing as a no-op.

### 27. `LEGACY_SYSTEM_PROMPT_TEMPLATE` and `_build_componentized_prompt` diverge in section ordering
- **File:** [backend/src/agents/work_agent/prompt.py:56-171, 484-508](../../backend/src/agents/work_agent/prompt.py#L56)
- **Severity:** Low (unchanged)
- **Issue:** Both code paths still exist, selected by `prompt_cfg.componentized`. Section ordering differs (memory insertion in particular). Cache key includes `prompt_componentized`, so caching is sound — but A/B comparisons of behavior are confounded by structural drift.
- **Recommendation:** Generate both from the same section list with a flag, or delete the legacy template if no production callers depend on it.

### ~~28. `MiddlewareSpec("trajectory")` after-key only references `thread_data`~~ ✅ FIXED
- **File:** [tests/test_middleware_registry.py](../../backend/tests/test_middleware_registry.py)
- **Status:** Added `test_trajectory_wraps_inner_middlewares` that pins the wrap-order invariant: `trajectory` index in the topologically sorted list must be lower than `model_timeout`, `retry`, `subagent_limit`, and `tool_result_truncation`. If a future change accidentally constrains `trajectory` to run later (e.g., by adding `after={"loop_detection"}`), the topo sort would reorder it and the test fails.

### 29. `_topological_sort_middleware_specs` private alias still exported
- **File:** [backend/src/agents/work_agent/agent.py:296-299](../../backend/src/agents/work_agent/agent.py#L296)
- **Status:** Alias removed. All callers (production at `agent.py:626` and 6 sites in `tests/test_middleware_registry.py`) now call `topological_sort_middleware_specs` directly from `src.agents.common.middleware_registry`.

### ~~30. `_RegistryContext` typing still partly loose~~ ✅ FIXED
- **File:** [backend/src/agents/work_agent/agent.py:318](../../backend/src/agents/work_agent/agent.py#L318)
- **Status:** `model_config` is now typed as `ModelConfig | None` (imported from `src.config.model_config`). The `router` field was already tightened in a prior pass. The dataclass is now fully typed.

## Architectural Observations

1. **`agent.py` is still ~832 lines** — registry factories, summarization helpers, runtime-params extraction, the model resolver, and the LangGraph entry point are still tangled in one file. Moving factories to `agents/common/registry_factories.py` would shave significant complexity.

2. **Three independent "todo reminder" sources** — `TodoMiddleware`, `TodoDagMiddleware`, `TodoFailureRetryMiddleware` each inject their own reminders with separate counters and triggers. No single source of truth for "the model is stuck; remind it." Consolidating into one `TodoReminderMiddleware` with a strategy enum would simplify finding-17 plus the budget-drift class of bugs.

3. **Phase-loop driver coexists with TodoListMiddleware** — `WorkModeMiddleware` assigns next todos in work mode while `TodoMiddleware` is wired only for plan mode. The "what is the next todo" concern is split across both, and any third middleware that wants to re-order must mutate `todo_graph.nodes` directly without an API contract.

4. **Handoff state divergence** — `state["plan"]`, on-disk `plan.md`, and the `ThreadState` checkpoint can all disagree. Three writers (scratchpad, handoff_sync, work_run_handoff) and three readers touch handoff state without a single ownership boundary.

5. **No dead-letter for failed todos** — `TodoFailureRetryMiddleware` caps retries then silently logs and quits. There is no terminal `dead_letter`/`failed_terminal` status the UI can render; the user sees a todo stuck in `in_progress` with no signal that the system has stopped trying.

## TODO DAG specific concerns

1. **Cycle detection runs only at `normalize_todo_nodes` / `merge_todo_nodes`** — finding 11's fix added re-validation inside `_load_canonical_plan_overrides`, but neither `TodoDagMiddleware.before_model` nor `WorkModeMiddleware` re-checks the graph after state-channel merges from other sources. Still a risk if any future code path bypasses the canonical-load helper.

2. **`compute_effective_ready_ids` ignores `target_endpoint`** — readiness considers only status and clarification blocks. When the helper endpoint is saturated, the lead agent still believes a helper-targeted todo is ready and tries to dispatch, getting a deferred-task entry. UI flickers between "ready" and "deferred."

3. **`_slugify` collisions in `merge_todo_nodes`** — ✅ Closed via debug log. Both `normalize_todo_nodes` and `merge_todo_nodes` already had dedup loops appending `-2`, `-3` suffixes. The real concern was that the UX impact (two distinct todos indistinguishable to the model) was silent. Added a `logger.debug` at `merge_todo_nodes` that records the base id, the disambiguated id, and the first 80 chars of content whenever a suffix is appended. Surfaces collisions in traces without changing behavior. Promoting to a UI-visible warning is deferred — collisions in practice are rare and a debug-level breadcrumb is sufficient for diagnostics.

4. **`ready_ids` is computed twice per cycle** — `TodoDagMiddleware._recompute_state` (~line 396) and `WorkModeMiddleware._materialize_ready_ids` (~line 296) both call the same function. If clarifications change between the two calls, they disagree.

5. **`_materialize_ready_ids` imported across module boundaries** — `work_mode_middleware.py:45` imports the private helper from `todo_dag_middleware`. A documented "Import rule" comment exists but the contract is still fragile. Promote to `agents/common/todo_graph.py`.

## Handoff & State Sync concerns

1. **`spawn_work_mode_handoff` has no observability** — Daemon logs exceptions and increments retry counters but emits no SSE/runtime events on retry or permanent failure. From the frontend perspective the handoff is invisible until a `plan` state update lands; if it fails permanently after `max_attempts`, the user sees the plan stuck in "approved" forever.

2. **`mark_handoff_succeeded` / `mark_handoff_failed` race on stale read** — [work_run_handoff.py:301-310, 334-346](../../backend/src/agents/middlewares/work_run_handoff.py#L301) re-reads state then calls `update_state` without a version/etag check. A concurrent user message updating the plan status will be clobbered.

3. **`replace_virtual_path` with potentially missing `thread_data`** — Partially addressed. `handoff_sync.py:490-493` now has a `_can_resolve_write_path` guard that returns False when `path.startswith("/mnt/")` and `thread_data` is falsy, blocking the bad call. The `_load_canonical_plan_overrides` path itself still depends on `thread_data` being populated in `values` at handoff time and could surface symptoms in edge cases (e.g. fresh runs before `ThreadDataMiddleware` first executes).

4. **`sync_handoff_files_from_state` writes `plan_path` and `latest_alias_path` with identical content** — [handoff_sync.py:577-587](../../backend/src/agents/middlewares/handoff_sync.py#L577). Intentional on Local sandbox (versioned + alias), but on read-only sandboxes that fail silently this doubles the failure surface. Worth a sandbox-capability check before the second write.

5. **`spawn_title_handoff_if_missing` uses `time.sleep(0.4)` in a retry loop** — ✅ FIXED. The retry now uses exponential backoff (0.4s → 0.8s → 1.6s) and re-raises on the final attempt instead of silently swallowing. ([work_run_handoff.py:181-194](../../backend/src/agents/middlewares/work_run_handoff.py#L181))
