# Plan Mode — Code Review

## Summary

Plan Mode is implemented as a thin wrapper around the work-agent factory, with five plan-mode-specific middlewares (planner, plan_evaluator, plan_execution_gate, plan_file_sync, todo_dag) that are conditionally activated when `is_plan_mode=True`. The architecture is largely sound — clean separation of concerns, sensible structured-output contracts, and a deterministic pre-check before the LLM evaluator. However, the review found one major correctness regression (PlanExecutionGateMiddleware is no longer registered yet the plan-mode prompt still relies on it), a handful of latent concurrency/race issues around the shared `_HANDOFF_GUARD` and `_classifier_cache`, several unbounded LLM calls without timeouts, and a meaningful amount of stale code and docstrings left over from the removed auto-escalation feature. The clarification flow has two overlapping subsystems (planner inline clarifications vs. `ClarificationMiddleware`) whose interaction is fragile.

## Critical Findings

### 1. PlanExecutionGateMiddleware is dead code but its security guarantee is still advertised
- **File:** [backend/src/agents/work_agent/agent.py:505-510](../../backend/src/agents/work_agent/agent.py#L505), [backend/src/agents/middlewares/plan_execution_gate_middleware.py](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py), [backend/src/agents/plan_agent/prompt.py:82-83](../../backend/src/agents/plan_agent/prompt.py#L82)
- **Severity:** Critical
- **Issue:** `PlanExecutionGateMiddleware` is the runtime backstop that blocks `web_search`, `bash` mutations, `write_file`, `task`, etc. while a plan is in draft or while clarifications are pending. It is currently commented out in the middleware registry (lines 505-510 in `work_agent/agent.py`), as is `PhaseToolFilterMiddleware`. The deprecation note says "web_search is now exposed in Plan Mode directly", but the plan-mode system prompt (`PLAN_MODE_SECTION`) still tells the model: "If tools return `[plan_gate]`, stop and refine the plan" and explicitly lists `web_search` and `task` as not allowed before approval. The runtime no longer enforces any of this.
- **Impact:** A Plan Mode run with a still-draft plan can call `web_search`, `bash` with mutations (`rm`, `>`, `tee`, etc.), `write_file`, `task`, etc., contradicting the documented contract. In auto-mode the planner pre-approves the plan so the issue is masked, but in foreground mode the draft state is supposed to be a hard gate. This also weakens the clarification flow: a plan with `clarification_pending=True` no longer blocks tool calls, so the model can ignore the pending question and start executing.
- **Recommendation:** Either re-register `PlanExecutionGateMiddleware` (the simplest fix; the file is intact and well-tested), or delete the prompt sections that reference `[plan_gate]` and `scope_search` and update the documented contract to "no runtime gating; relies on the catalog-driven tool-mode split". Today's state is the worst of both worlds — prompt says one thing, runtime does another.
- **Snippet:**
```python
# work_agent/agent.py L505-510
# DEPRECATED: plan_execution_gate is no longer registered. web_search and
# other execution tools are allowed in Plan Mode directly.
# MiddlewareSpec("plan_execution_gate", lambda: PlanExecutionGateMiddleware(...), after={"planner"}, before={"permissions"}),
```

### 2. `scope_search` is referenced everywhere but is deprecated and unregistered
- **File:** [backend/src/agents/plan_agent/prompt.py:32,65,75](../../backend/src/agents/plan_agent/prompt.py#L32), [backend/src/agents/middlewares/plan_execution_gate_middleware.py:33-41,254,290](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L33), [backend/src/tools/tools.py:8-71](../../backend/src/tools/tools.py#L8)
- **Severity:** High
- **Issue:** `scope_search` is mentioned in three places in `PLAN_MODE_SECTION` ("Use scope_search, memory, and read-only tools…", "`scope_search` is for when you genuinely don't know WHAT to search for", "Not allowed: Using `web_search`, `recall`, `scope_search` for content gathering"). But `src/tools/tools.py` shows the wrapper is deprecated and the registration is commented out, and the module-level comment says "web_search is now available in plan mode as well (scope_search deprecated)".
- **Impact:** The model is told to call a tool that doesn't exist. In best case the LLM gets a "tool not found" error and falls back to `web_search`. In worst case it never resolves what to do and either stalls or fabricates. The "Not allowed" list also contradicts itself with "Allowed: Use read-only tools for scope understanding".
- **Recommendation:** Strip all `scope_search` references from `PLAN_MODE_SECTION` and `plan_execution_gate_middleware.py`. Delete or move `src/community/scope_search/` if confirmed dead.

### 3. Auto-mode handoff bypass: the second `if isinstance(thread_id, str)` block leaves `payload["plan"]` stale
- **File:** [backend/src/agents/middlewares/planner_middleware.py:824-846](../../backend/src/agents/middlewares/planner_middleware.py#L824)
- **Severity:** High
- **Issue:** After all clarifications are resolved and the plan is auto-approved, the code attempts to spawn a work-mode handoff. If the runtime context lacks a `thread_id` (e.g. the embedded `CapyHomeClient` path), the `spawn_work_mode_handoff` call is skipped. But the `resolved_plan = mark_handoff_requested(...)` and `payload["plan"] = resolved_plan` lines are inside the `if isinstance(thread_id, str) and thread_id:` block, so when no thread_id is present, the plan is **not** marked as handoff-requested even though execution should be considered approved. Worse, the `payload["jump_to"] = "end"` outside that block fires unconditionally for `plan_foreground`, terminating the turn while the plan is still marked as merely "approved" with `execution_requested_at=None`. On the next turn nothing will spawn the handoff and the user will see a stuck "approved but not running" plan.
- **Impact:** Embedded clients (no thread_id) or any race where the runtime context strips thread_id will silently drop the work-handoff transition.
- **Recommendation:** Either move `payload["plan"] = mark_handoff_requested(...)` outside the `if thread_id` block (so the plan state always reflects "handoff requested"), or only jump-to-end when the handoff was actually spawned. The two states should be tied together.

### 4. `_classifier_cache` is a per-middleware-instance dict that persists across requests
- **File:** [backend/src/agents/middlewares/plan_execution_gate_middleware.py:131-220](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L131)
- **Severity:** High (assuming the middleware is re-registered per finding #1; otherwise N/A)
- **Issue:** `self._classifier_cache: dict[str, str] = {}` is keyed on `tool_call_id`. Tool-call IDs are typically unique per call, but the middleware instance is built once per `make_work_agent(config)` call. If the agent is cached/reused across threads (the embedded client does `reset_agent()` only on memory/skill changes — see `src/client.py`), this dict grows unboundedly across requests. There's no eviction. Also no thread-safety: concurrent `wrap_tool_call` on two threads racing the same call_id are possible (very unlikely but not impossible).
- **Impact:** Memory leak proportional to total tool calls observed. No correctness issue absent ID collisions.
- **Recommendation:** Move the cache onto `request.runtime.context` (per-run) or onto a `weakref.WeakValueDictionary`, or use an `lru_cache`-style bounded dict. Or simply drop the cache and accept the rare double-classify cost.

### 5. `_HANDOFF_GUARD` deadlock risk: lock is released before in-flight set is fully cleaned
- **File:** [backend/src/agents/middlewares/work_run_handoff.py:317-352](../../backend/src/agents/middlewares/work_run_handoff.py#L317)
- **Severity:** High
- **Issue:** `_HANDOFF_GUARD` is a module-level `threading.Lock`. `spawn_work_mode_handoff` acquires it, checks `_IN_FLIGHT_HANDOFFS`, mutates the set, and releases. The daemon thread's `_run_with_cleanup` re-acquires the lock to discard. So far so good. But the daemon thread is started *after* the lock is released, and the cleanup runs in a `finally` block. If `_run_work_mode_handoff` raises before it gets to its own internal try/finally machinery (e.g. import error of `CapyHomeClient`), the cleanup still runs because of `try/finally`. OK.
  
  Real issue: there is NO timeout on the in-flight set entry. If the daemon thread is killed (process restart, segfault, blocking import), `_IN_FLIGHT_HANDOFFS` permanently contains the thread_id and subsequent handoff calls for that thread are silently skipped forever. The fix in finally would only help live processes.
- **Impact:** A poisoned thread_id can never be re-handed-off in the lifetime of the process. Users see plans stuck in "approved" with no work-mode run.
- **Recommendation:** Add a TTL or wall-clock entry to the set (e.g. `_IN_FLIGHT_HANDOFFS: dict[str, float]` keyed on `time.monotonic()`); drop entries older than, say, 5 minutes when checking. Or instrument with a thread name probe / heartbeat.

### 6. PlannerMiddleware: synchronous LLM call inside an async path
- **File:** [backend/src/agents/middlewares/planner_middleware.py:784-797,1211-1212](../../backend/src/agents/middlewares/planner_middleware.py#L784)
- **Severity:** High
- **Issue:** `_invoke_planner` calls `model.invoke(...)` — synchronous. `abefore_model` just delegates to `before_model` directly (`return self.before_model(...)`). That means in an async runtime, the planner's LLM call blocks the event loop for however long the LLM takes (10–60s typical, no timeout). No `await model.ainvoke` path exists. PlanEvaluatorMiddleware does this correctly (separate `_call_sync` and `_call_async`); planner does not.
- **Impact:** Under LangGraph Server (which runs middlewares in an async context), a slow planner LLM blocks ALL coroutines on the same event-loop worker, including SSE writers, healthchecks, and other threads' planner calls. A 30s planner call effectively freezes the server for that worker.
- **Recommendation:** Add an `async` path that uses `await model.ainvoke(...)` with a bounded `asyncio.wait_for` and a config-driven timeout. Mirror the structure of `PlanEvaluatorMiddleware._call_async`.

## High Severity Findings

### 7. PlannerMiddleware has no timeout on the LLM call at all
- **File:** [backend/src/agents/middlewares/planner_middleware.py:784-797](../../backend/src/agents/middlewares/planner_middleware.py#L784)
- **Severity:** High
- **Issue:** `_invoke_planner` calls `model.invoke([SystemMessage, HumanMessage])` with no timeout, no retry. A hung model call blocks the planner indefinitely. Plan Evaluator wraps its call in `_run_with_timeout` (sync) or `asyncio.wait_for` (async); planner has neither.
- **Impact:** A wedged LLM endpoint (network stall, OOM at provider) hangs the planning turn forever. The user sees a frozen "planning started" SSE with no recovery.
- **Recommendation:** Add `_run_with_timeout` (or extract the helper from `plan_evaluator_middleware`) and reuse a `planner.timeout_seconds` config.

### 8. `_handle_plan_adapted` SSE fires every single cycle while stuck
- **File:** [backend/src/agents/middlewares/work_mode_middleware.py:265-275,463-503](../../backend/src/agents/middlewares/work_mode_middleware.py#L265)
- **Severity:** High
- **Issue:** When the plan stalls (all pending todos blocked), `_handle_plan_adapted` increments `adaptation_attempts` and emits a `plan_adapted` SSE every time `before_model` runs. There's no debounce, no "already emitted" guard. The `phase_execution.plan_adapted` flag is set but never checked before re-emitting.
- **Impact:** The UI is spammed with `plan_adapted` events on every model cycle. Each turn re-emits. If the model keeps producing AI messages that don't fix anything, the user sees a cascade of identical toasts.
- **Recommendation:** Check `existing_pe.get("plan_adapted")` before emitting; only emit on the *first* stall detection (or on signature change of blocked_ids set).

### 9. Race: plan_adapted SSE fires during execution but checkpoint write is non-atomic
- **File:** [backend/src/agents/middlewares/work_mode_middleware.py:463-503](../../backend/src/agents/middlewares/work_mode_middleware.py#L463)
- **Severity:** Medium-High
- **Issue:** `_handle_plan_adapted` returns an update payload that LangGraph commits to the checkpointer after the cycle. The SSE write happens immediately. If the user clicks "switch to Plan Mode" between the SSE emission and the checkpoint commit, the subsequent Plan Mode run reads stale state and may not see the updated `adaptation_attempts`.
- **Impact:** Minor — the counter is purely diagnostic per the docstring. But the pattern (emit SSE first, persist state later) is fragile if the counter ever becomes load-bearing.
- **Recommendation:** Emit the SSE only after returning the state update, or wrap both in a queued post-commit hook.

### 10. ClarificationMiddleware mutates the runtime context dict directly
- **File:** [backend/src/agents/middlewares/clarification_middleware.py:120-133](../../backend/src/agents/middlewares/clarification_middleware.py#L120)
- **Severity:** High
- **Issue:** `before_model` writes to `ctx[_AUTO_MODE_CTX_KEY] = auto_mode` on the runtime's context dict — this is shared mutable state per the Runtime contract. LangGraph's `runtime.context` is intended as a read-mostly view of `RunnableConfig.configurable`. Writing to it from `before_model` to communicate with `wrap_tool_call` is a coupling-by-side-effect pattern.
- **Impact:** If LangGraph ever copies the context (or freezes it as `MappingProxyType`), this silently breaks auto-mode bypass. The auto-mode bypass would silently regress to interrupting.
- **Recommendation:** Pass the auto-mode flag through state (`state["auto_mode"]`) which is already read at line 128, or use an instance variable + threading-local. Read state directly inside `wrap_tool_call` via `request.state`.

### 11. PlannerMiddleware applies clarification progress with auto-mode approval bypassed when only one clarification remains
- **File:** [backend/src/agents/middlewares/planner_middleware.py:805-822](../../backend/src/agents/middlewares/planner_middleware.py#L805)
- **Severity:** High
- **Issue:** When the user answers the LAST clarification, `progress.get("messages")` is None (no next question to prompt). The code skips that branch and proceeds to the handoff branch. Good. But when the user answers an INTERMEDIATE clarification (not the last), `progress.get("messages")` is the next clarification prompt, and we return early at line 822 with `payload = {"plan": resolved_plan, "messages": [next_prompt]}`. Here `resolved_plan` is still `clarification_pending=True`, so `approve_plan_if_auto_mode` at line 809 is a no-op (it checks `clarification_pending` — wait, no it doesn't, it only checks `status == "draft"`).
  
  Actually wait — `approve_plan_if_auto_mode` does NOT check `clarification_pending`. It only checks `status == "draft"`. So if `auto_mode=True` and there are still pending clarifications, the plan can flip to `status="approved"` on the FIRST resolved clarification. Then on the next clarification answer, `should_spawn_work_handoff` becomes True (because status is approved AND clarification_pending may have become False on this answer), and a handoff fires while there are STILL unanswered clarifications waiting.
  
  Re-reading: at L808 the guard is `if not bool(resolved_plan.get("clarification_pending"))`. So approval only happens when ALL clarifications are resolved. OK so it's gated correctly. But the gate is also `should_spawn_work_handoff` which checks `all_clarifications_resolved`. Defensive but correct.
- **Impact:** No bug confirmed, but the chain of guards is fragile — three different functions each check clarification state independently. If one is forgotten in a refactor, auto-mode could spawn premature handoffs.
- **Recommendation:** Centralise the "plan is ready for handoff" predicate. Have one function `is_plan_executable(plan) -> bool` that checks all conditions; have everyone call it.

### 12. The "Re-plan with no new user message" baseline detection is off-by-one for legacy plans
- **File:** [backend/src/agents/middlewares/planner_middleware.py:767-782](../../backend/src/agents/middlewares/planner_middleware.py#L767)
- **Severity:** Medium-High
- **Issue:** `_has_new_user_message_since_plan` falls back to "human_count >= 2" when no baseline exists. The first time a legacy plan loads with exactly one human message, this returns False (correct). The second time, with 2 human messages, it returns True even if the second human message was just the user's clarification answer (which is processed by `apply_clarification_progress`, not re-planning). The clarification answer would (incorrectly) trigger another full re-plan in addition to the clarification advance.
- **Impact:** A user answering a clarification on a legacy plan (no baseline) may trigger an unintended re-plan + clarification-advance, both with duplicate `plan_created` SSE.
- **Recommendation:** Tighten the fallback to "human_count >= 2 AND no clarification_pending". Or — better — backfill the baseline once when loading legacy plans rather than relying on a fallback.

### 13. `_plan_behavior` and `_auto_mode_enabled` read from `runtime.context` but `runtime.config["configurable"]` can also carry the same fields
- **File:** [backend/src/agents/middlewares/planner_middleware.py:66-75](../../backend/src/agents/middlewares/planner_middleware.py#L66)
- **Severity:** Medium-High
- **Issue:** `_runtime_context(runtime)` returns `runtime.context` if it's a dict. But `make_plan_agent` writes to `forced_config["configurable"]["plan_behavior"]`, not to `runtime.context`. LangGraph's middleware runtime may expose both as `runtime.config["configurable"]` (legacy) and `runtime.context` (newer). The planner only reads context.
- **Impact:** If LangGraph plumbs `plan_behavior` only into `configurable`, the planner reads empty string, falls back to defaults. `plan_foreground` may not be honored.
- **Recommendation:** Add a small helper that reads `runtime.context` first, then falls back to `runtime.config.get("configurable", {})`. `ClarificationMiddleware` does this correctly at line 122-130.

## Medium Severity Findings

### 14. `direct_answer_fast_path` is keyword-list-based and English-only
- **File:** [backend/src/agents/middlewares/planner_middleware.py:411-487](../../backend/src/agents/middlewares/planner_middleware.py#L411)
- **Severity:** Medium
- **Issue:** `_looks_like_direct_answer_request` uses hard-coded keyword lists like "coffee", "aeropress", "creatine" to skip the planner. This is brittle — a Singapore user asking about "kopi gao siu dai routine" will not match "coffee" or "routine" cleanly. The list is also outside the domain scope (legal/admin/Excel/food/Singapore events/shopping all need varied keywords).
- **Impact:** Inconsistent UX: some lifestyle queries skip planning, most don't. Singapore-domain queries unlikely to match.
- **Recommendation:** Either drop the fast-path (planner LLM is cheap when domain-classified as "generic") or replace with a tiny LLM classifier. At minimum localize the keyword set per the project's actual domain scope.

### 15. PlanEvaluator's `_run_with_timeout` leaks daemon threads
- **File:** [backend/src/agents/middlewares/plan_evaluator_middleware.py:712-730](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L712)
- **Severity:** Medium
- **Issue:** When the LLM call exceeds the timeout, the wrapper raises `TimeoutError` and returns — but the daemon thread continues to run inside the LLM client. It cannot be cancelled (Python lacks thread cancellation). The thread may finish minutes later, producing a side-effect log line ("model generated …") long after the user has moved on.
- **Impact:** Resource leak (daemon thread persists), and any per-request usage counters keep incrementing post-timeout.
- **Recommendation:** Document the leak in the docstring (acceptable for sync path) or push every caller toward the async path which CAN be properly cancelled via `asyncio.wait_for`.

### 16. PlanFileSync background thread holds a deep copy of state but doesn't bound size
- **File:** [backend/src/agents/middlewares/plan_file_sync_middleware.py:82-90,43-49](../../backend/src/agents/middlewares/plan_file_sync_middleware.py#L82)
- **Severity:** Medium
- **Issue:** `copy.deepcopy(dict(state))` captures the whole ThreadState into a daemon thread. ThreadState may include large `artifacts`, `messages`, `viewed_images`, `uploaded_files`, etc. The thread sleeps 1 second, then writes plan.md and runtime files. For a 50-turn conversation with images, the deep copy is significant.
- **Impact:** Memory spike per finalisation; GC pause; race if state mutates concurrently in the foreground (deep copy avoids the race but at cost).
- **Recommendation:** Only copy the fields needed (`plan`, `todo_graph`, `artifacts`, `handoff_artifacts`, `thread_data`). Avoid `messages` which is by far the biggest field.

### 17. PlanFileSync uses an implicit `time.sleep(1.0)` to "let state settle"
- **File:** [backend/src/agents/middlewares/plan_file_sync_middleware.py:43-44](../../backend/src/agents/middlewares/plan_file_sync_middleware.py#L43)
- **Severity:** Medium
- **Issue:** The background worker sleeps 1.0s before writing plan.md to "let state settle" (implicit). This is a synchronization hack — there's no signal that the state IS settled. If the next turn fires within 1s (rare but possible on cached models), two background sync threads compete to write the same file. No file-lock.
- **Impact:** Potential plan.md corruption / lost edits under concurrent writes (rare).
- **Recommendation:** Use atomic write (temp + rename) — `_write_file` in planner_middleware does NOT do this either. Or use a per-thread lock so only one sync runs at a time.

### 18. `_write_file` in PlannerMiddleware is non-atomic
- **File:** [backend/src/agents/middlewares/planner_middleware.py:655-657](../../backend/src/agents/middlewares/planner_middleware.py#L655)
- **Severity:** Medium
- **Issue:** `path.write_text(...)` is not atomic. If the process crashes mid-write, plan.md is truncated. On re-load, `parse_plan_md` raises ValueError and the canonical handoff falls back to checkpointed state silently (per `_load_canonical_plan_overrides`), so user edits between approval and crash are lost.
- **Impact:** Low frequency, but data loss when it happens.
- **Recommendation:** Write to `.tmp` and `os.replace()` to final path.

### 19. PlannerMiddleware emits SSE `plan_created` even when plan was auto-approved AND a handoff fires
- **File:** [backend/src/agents/middlewares/planner_middleware.py:1103-1125,1192-1208](../../backend/src/agents/middlewares/planner_middleware.py#L1103)
- **Severity:** Medium
- **Issue:** The SSE writer fires `plan_created` at line 1106, then later `spawn_work_mode_handoff` schedules a daemon, then `payload["jump_to"] = "end"` terminates the current turn. The frontend now sees: `plan_created` immediately, then the Plan Mode turn ends, then Work Mode SSE events start streaming on the same thread from the daemon-spawned run. There's no `plan_handoff_started` or analogous SSE in the foreground stream — the frontend has to infer it from work_mode events.
- **Impact:** Frontend state confusion: a plan_created with `status=approved` is followed by no further plan-mode events; SSE consumer must guess the plan is now executing.
- **Recommendation:** Emit a `plan_handoff_started` SSE before jumping to end, so the frontend has a clean transition signal.

### 20. PlanEvaluator: max_attempts loop may emit `max_attempts_reached` for already-okay plans
- **File:** [backend/src/agents/middlewares/plan_evaluator_middleware.py:698-704](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L698)
- **Severity:** Medium
- **Issue:** `_build_terminal_payload` emits `max_attempts_reached` only when `last_decision not in {"ok", "timeout_skipped", "non_json_skipped", "llm_error_skipped"}`. But the loop can break on `revision_invalid` or `issues_no_revision`, both of which also won't fix the plan. The current check would emit `max_attempts_reached` in those cases even when only 1 attempt ran (because the loop broke early without incrementing past max).
- **Impact:** Misleading observability — `max_attempts_reached` decision is logged when attempts < max.
- **Recommendation:** Tighten the predicate: only emit `max_attempts_reached` when `attempts >= max_attempts` AND a "revised" attempt was made.

### 21. Inline clarification panel and `ClarificationMiddleware` step on each other
- **File:** [backend/src/agents/middlewares/planner_middleware.py:1102-1125](../../backend/src/agents/middlewares/planner_middleware.py#L1102), [backend/src/agents/middlewares/clarification_middleware.py:198-277](../../backend/src/agents/middlewares/clarification_middleware.py#L198)
- **Severity:** Medium
- **Issue:** Two separate clarification subsystems coexist:
  1. PlannerMiddleware emits `plan_created` with `clarifications: [...]` inline, plus a `planner_clarification_required` HumanMessage prompting the model to call `ask_user_for_clarification`.
  2. ClarificationMiddleware intercepts the `ask_user_for_clarification` tool call and appends to `state.clarifications`, possibly interrupting.
  
  If the model follows the prompt and calls `ask_user_for_clarification` with options matching the planner's inline clarifications, the result is two entries: one in `plan.clarifications` and one in `state.clarifications`. Auto-mode bypass and answer resolution paths differ between the two systems.
- **Impact:** Duplicate UI panels (frontend popup from `plan_created` + tab from `ClarificationMiddleware`), inconsistent answer routing, and possible double-counted questions.
- **Recommendation:** Pick one. Either let the planner own clarifications end-to-end (and tell the model NOT to call `ask_user_for_clarification` for planner-generated questions), or have the planner skip inline clarifications and rely on the tool-call path.

### 22. ClarificationMiddleware: state.clarifications append semantics depends on reducer
- **File:** [backend/src/agents/middlewares/clarification_middleware.py:249-260](../../backend/src/agents/middlewares/clarification_middleware.py#L249)
- **Severity:** Medium
- **Issue:** The update returns `"clarifications": [entry]` — a list of one entry. LangGraph applies state updates by default-replacement unless a reducer is registered. The middleware assumes "append" semantics. If the ThreadState schema for `clarifications` uses default-replacement, this OVERWRITES the prior questions and the user sees only the latest.
- **Impact:** Latent dataloss bug if clarifications field reducer is wrong.
- **Recommendation:** Verify a list-append reducer is configured on `clarifications` in `ThreadState`. Add an explicit unit test.

### 23. Plan Evaluator does not validate that the LLM left `todo_ids` consistent
- **File:** [backend/src/agents/middlewares/plan_evaluator_middleware.py:493-501](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L493)
- **Severity:** Medium
- **Issue:** When `_commit_revision` writes back new nodes, it does NOT update `plan["todo_ids"]` to match. The planner sets `plan["todo_ids"]` once on creation. After a patch removes/adds todos, `plan["todo_ids"]` may be stale.
- **Impact:** Anything that uses `plan["todo_ids"]` (e.g. progress UI) shows stale IDs.
- **Recommendation:** Also update `plan["todo_ids"]` in `_commit_revision`.

### 24. `_normalize_plan_status` silently coerces invalid status to "draft"
- **File:** [backend/src/agents/middlewares/work_mode_middleware.py:72-76](../../backend/src/agents/middlewares/work_mode_middleware.py#L72), [backend/src/agents/middlewares/plan_execution_gate_middleware.py:100-104](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L100)
- **Severity:** Medium
- **Issue:** Unknown plan statuses (e.g. typos, future "cancelled" status, or genuinely unset) are coerced to `"draft"`. In `PlanExecutionGateMiddleware._maybe_block`, an unknown status would BLOCK execution tools (since draft is the most-restrictive). Defensible, but it means a plan with a corrupted status field becomes a soft brick.
- **Impact:** Bug masking — corrupted plan state silently re-enters draft, user can't see why.
- **Recommendation:** Log a warning when an unknown status is coerced; emit a runtime event.

## Low Severity / Nits

### 25. Stale module docstring in `plan_agent/agent.py`
- **File:** [backend/src/agents/plan_agent/agent.py:7](../../backend/src/agents/plan_agent/agent.py#L7)
- **Severity:** Low
- **Issue:** "so the frontend and **auto-escalation paths** can address it by name" — auto-escalation has been removed (per project memory). Comment is stale.
- **Recommendation:** Strike "auto-escalation paths"; replace with "manual user toggle".

### 26. Stale docstring in `work_mode_middleware.py`
- **File:** [backend/src/agents/middlewares/work_mode_middleware.py:23-27](../../backend/src/agents/middlewares/work_mode_middleware.py#L23)
- **Severity:** Low
- **Issue:** "Work Mode never **auto-escalates**" — phrased correctly. But docs/plan-mode/04_handoff_contract.md still says "auto-approval / auto-escalation" in section B. Drift.
- **Recommendation:** Update docs/plan-mode/04_handoff_contract.md section B title to "auto-approval (daemon-driven)" since auto-escalation no longer exists.

### 27. `del router` pattern is repeated but unhelpful
- **File:** [backend/src/agents/middlewares/planner_middleware.py:677-683](../../backend/src/agents/middlewares/planner_middleware.py#L677), [backend/src/agents/middlewares/plan_evaluator_middleware.py:342-345](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L342)
- **Severity:** Low
- **Issue:** `router` is accepted, immediately `del`'d, with comments saying "kept for backwards compatibility". Dead parameter signature noise.
- **Recommendation:** Once all call sites are updated, remove the parameter entirely.

### 28. `_ensure_research_clarifications` mutates list shape using hard-coded heuristics
- **File:** [backend/src/agents/middlewares/planner_middleware.py:132-195](../../backend/src/agents/middlewares/planner_middleware.py#L132)
- **Severity:** Low
- **Issue:** The function injects "What timeframe should the research cover?" and an "AI trends" clarification using string-match heuristics. This is brittle and doesn't extend to non-research domains; the planner itself is supposed to produce these.
- **Recommendation:** Drop the function; trust the planner LLM. If the planner doesn't include a timeframe, that's the planner's job to fix via better prompting.

### 29. `_versioned_plan_filename` duplicated
- **File:** [backend/src/agents/middlewares/planner_middleware.py:650-652](../../backend/src/agents/middlewares/planner_middleware.py#L650), [backend/src/agents/middlewares/handoff_sync.py:26-28](../../backend/src/agents/middlewares/handoff_sync.py#L26)
- **Severity:** Low
- **Issue:** Two identical implementations of `_versioned_plan_filename` and `_slugify_title`.
- **Recommendation:** Move to a shared util.

### 30. `_DIRECT_ANSWER_BLOCKERS` includes "legal" — conflicts with the legal domain support
- **File:** [backend/src/agents/middlewares/planner_middleware.py:449-471](../../backend/src/agents/middlewares/planner_middleware.py#L449)
- **Severity:** Low-Medium
- **Issue:** `_DIRECT_ANSWER_BLOCKERS` contains "legal", "contract". This blocks the direct-answer fast path. But the planner's domain enum explicitly supports "legal" as a first-class domain. So legal queries always go through the planner (intended), but the keyword-based blocker is fragile (e.g. "explain legal contracts" matches both markers and blockers, blockers win → planner runs, fine).
- **Recommendation:** Probably intentional. Add a comment clarifying why "legal" is a blocker rather than a marker.

### 31. Hard-coded thread name string slicing
- **File:** [backend/src/agents/middlewares/plan_file_sync_middleware.py:87](../../backend/src/agents/middlewares/plan_file_sync_middleware.py#L87), [backend/src/agents/middlewares/work_run_handoff.py:141](../../backend/src/agents/middlewares/work_run_handoff.py#L141), [backend/src/agents/middlewares/work_run_handoff.py:349](../../backend/src/agents/middlewares/work_run_handoff.py#L349)
- **Severity:** Low
- **Issue:** `thread_id[:8]` is used as a thread name slug. If `thread_id` is shorter than 8 chars (unlikely but possible in tests), no error; just shorter. If it's None somewhere upstream, str() conversion in `f-string` is "None".
- **Recommendation:** Defensive: `str(thread_id or "")[:8]`.

### 32. Question-generation middleware reads from `last_user_message` ignoring `name`
- **File:** [backend/src/agents/middlewares/question_generation_middleware.py:61-72](../../backend/src/agents/middlewares/question_generation_middleware.py#L61)
- **Severity:** Low
- **Issue:** `_last_user_message` skips synthetic human messages (those with a `name`). Good. But the prompt template `cfg.prompt_template.format(...)` will silently fail with `KeyError` if config has a stray `{x}` in the template. No guard.
- **Recommendation:** Wrap `.format(...)` in try/except KeyError with a log warning.

### 33. `Runtime.context` typed as dict but read as Any
- **File:** Throughout
- **Severity:** Low
- **Issue:** Every middleware does `getattr(runtime, "context", None) or {}` defensively. This is a sign the type is unclear. A typed accessor in `src/agents/common/` would clean this up.
- **Recommendation:** Add a `get_runtime_context(runtime) -> dict` helper.

### 34. Planner: `_should_plan` returns True when ai_count == 0, regardless of whether the planner already ran (e.g. via direct-answer fast path)
- **File:** [backend/src/agents/middlewares/planner_middleware.py:733-765](../../backend/src/agents/middlewares/planner_middleware.py#L733)
- **Severity:** Low-Medium
- **Issue:** In Work Mode with `ai_count == 0`, the planner runs even if `_looks_like_direct_answer_request` skipped it on the prior turn (since prior turn produced no plan). Two consecutive direct-answer requests on the same thread would each re-trigger `_should_plan` → `_invoke_planner` → fast-path skip. Wasteful only in that the planner LLM doesn't actually fire, but `_should_plan` returns True and the function enters the heavyweight code path.
- **Recommendation:** Cache a flag on state like `planner_skipped_at_human_count` to avoid re-entering the planner path on already-classified turns.

## Architectural Observations

- **Centralise plan-lifecycle predicates.** Right now the predicates `should_spawn_work_handoff`, `all_clarifications_resolved`, `handoff_already_started`, `work_execution_underway`, `execute_plan_should_duplicate` are scattered across `plan_execution.py` and called in multiple places. Add one canonical `is_plan_ready_for_handoff(plan) -> bool` and refactor callers.
- **Plan Mode prompt should live next to a registered guardrail middleware.** With `PlanExecutionGateMiddleware` deregistered, the plan-mode prompt is the only thing stopping the model from calling `web_search` / `task` / `write_file` in draft state. Prompt-only enforcement is unreliable. Either re-register the gate or drop the prompt's discipline language.
- **Two clarification subsystems is one too many.** See Finding #21. The interaction matrix between planner-inline clarifications, ClarificationMiddleware deferred clarifications, and `ask_user_for_clarification` tool calls is fragile. A single source of truth (one queue, one set of predicates) would dramatically simplify reasoning.
- **Background daemon threads everywhere.** `spawn_work_mode_handoff`, `spawn_title_handoff_if_missing`, `_run_background_plan_sync`, `_run_with_timeout`, `MemoryMiddleware` queue — these all spawn daemon threads with manual coordination via module-level locks and sets. Consider moving to a single bounded worker pool with structured supervision; right now leaks (Finding #5) and racing writes (Finding #17) are easy to introduce.
- **Planner prompt is enormous** (~200 lines including domain rules, todo style, example, rich-execution fields). The token cost per planning turn is non-trivial. Several sections are documentation that the LLM doesn't need on every call (e.g. the full example). Consider extracting per-domain prompts conditionally.

## Dead code / stale references

- **`PlanExecutionGateMiddleware`** ([plan_execution_gate_middleware.py](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py)) — entire file is unused per the deprecation in `work_agent/agent.py` L505-510. Either re-register or delete.
- **`PhaseToolFilterMiddleware`** import is commented in `work_agent/agent.py` L26-31, L517-519; the source file likely still exists. Confirm and prune.
- **`scope_search`** community module is referenced in 3 places in plan prompts and 4 places in `plan_execution_gate_middleware.py` but the tool is deprecated/unregistered in `src/tools/tools.py` L8-71.
- **`auto-escalation paths`** wording in `plan_agent/agent.py:7` — stale per project memory (only one trigger now).
- **`docs/plan-mode/04_handoff_contract.md:112`** still uses "auto-approval / auto-escalation" header; should be "auto-approval (daemon-driven)".
- **`router=ctx.router` parameter** in `PlannerMiddleware.__init__` and `PlanEvaluatorMiddleware.__init__` is kept "for backwards compatibility" then immediately `del`'d. Once all call sites are scrubbed, remove the parameter entirely.
- **Legacy `revised_todos` contract** in `PlanEvaluatorMiddleware._apply_response` (L481-489) — kept for back-compat. If no callers send it any more, drop the branch.
- **`mark_handoff_started`** in `plan_execution.py` L146-148 is a "backward-compatible alias" for `mark_handoff_succeeded`. Audit for callers and drop.
- **`_DIRECT_ANSWER_DOMAINS` / `_DIRECT_ANSWER_MARKERS` / `_DIRECT_ANSWER_BLOCKERS`** lists — keyword heuristics that don't generalise to the project's documented domain scope (law/admin/Excel/Singapore events). Either rebuild or drop.
