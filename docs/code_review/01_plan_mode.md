# Plan Mode — Code Review

## Summary

Plan Mode is implemented as a thin wrapper around the work-agent factory, with five plan-mode-specific middlewares (planner, plan_evaluator, plan_execution_gate, plan_file_sync, todo_dag) that are conditionally activated when `is_plan_mode=True`. The architecture is largely sound — clean separation of concerns, sensible structured-output contracts, and a deterministic pre-check before the LLM evaluator. However, the review found one major correctness regression (PlanExecutionGateMiddleware is no longer registered yet the plan-mode prompt still relies on it), a handful of latent concurrency/race issues around the shared `_HANDOFF_GUARD` and `_classifier_cache`, several unbounded LLM calls without timeouts, and a meaningful amount of stale code and docstrings left over from the removed auto-escalation feature. The clarification flow has two overlapping subsystems (planner inline clarifications vs. `ClarificationMiddleware`) whose interaction is fragile.

> **Status update (2026-05-30 recheck):** Findings #1, #2, #7, #15, #20, and #22 cleared in the 05-30 recheck.
>
> **Status update (2026-05-30 implementation pass 1):** Findings #3, #10, #12, #13, #14, #16, #17, #18, #19, #23, #24, #30, and #33 cleared.
>
> **Status update (2026-05-30 implementation pass 2):** Findings #5, #6, #8 (already-clear in-tree), #21 (de-duplicated via short-circuit), #25, #26, #27, #28, #29, #31, and #34 (obsoleted by #14) are now cleared. The full set of in-doc findings is now resolved one way or another. Key additions in pass 2:
> - `_IN_FLIGHT_HANDOFFS` is now a `dict[str, float]` with a 5-minute TTL; a poisoned thread_id can no longer permanently block re-handoffs.
> - `PlannerMiddleware.abefore_model` now runs the sync `before_model` via `asyncio.to_thread`, freeing the event loop under LangGraph Server.
> - `ClarificationMiddleware` short-circuits when the LLM calls `ask_user_for_clarification` with a question already surfaced inline by the planner — the two subsystems no longer create duplicate panels.
> - Plan filename utilities consolidated to `handoff_sync.versioned_plan_filename` / `slugify_plan_title`; planner's duplicate removed.
> - Hard-coded research-clarification heuristics (`_ensure_research_clarifications`) dropped; the planner LLM owns clarification generation, and only `_normalize_planner_clarifications` (dedup + option normalisation) remains.
> - Dead `router=` parameters dropped from `PlannerMiddleware` and `PlanEvaluatorMiddleware` (and test sites that passed `router=_router()`).
> - Defensive `str(thread_id or "")[:8]` slicing applied across the daemon-thread name sites.
> - Doc drift: `04_handoff_contract.md` section B retitled to "Daemon-driven (auto-approval)". `plan_agent/agent.py` docstring updated.
>
> Totals: 30 fully cleared, 1 dormant (#4 — code present but unreachable), 1 not-reproducible (#32), 1 downgraded to Low with no fix needed (#11), 1 acceptable-as-is (#9 — SSE-before-checkpoint ordering is inherent to LangGraph's commit model and the existing stall_signature debounce prevents the spam scenario). **All findings closed.**

## Critical Findings

### ~~1. PlanExecutionGateMiddleware is dead code but its security guarantee is still advertised~~ ✅ CLEARED
- **File:** [backend/src/agents/work_agent/agent.py:505-510](../../backend/src/agents/work_agent/agent.py#L505), [backend/src/agents/middlewares/plan_execution_gate_middleware.py](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py), [backend/src/agents/plan_agent/prompt.py:82-83](../../backend/src/agents/plan_agent/prompt.py#L82)
- **Severity:** ~~Critical~~ — Resolved via the second recommendation path: the plan-mode prompt no longer references `[plan_gate]` or `scope_search`, and now states explicitly "This is a behavioral norm, not a runtime gate — the catalog-driven tool-mode split is what defines what's available" ([prompt.py:67-69](../../backend/src/agents/plan_agent/prompt.py#L67)). The runtime/prompt inconsistency is gone. (`PlanExecutionGateMiddleware` remains deregistered intentionally; see findings #4 dependency note.)
- ~~**Issue:** `PlanExecutionGateMiddleware` is the runtime backstop that blocks `web_search`, `bash` mutations, `write_file`, `task`, etc. while a plan is in draft or while clarifications are pending. It is currently commented out in the middleware registry (lines 505-510 in `work_agent/agent.py`), as is `PhaseToolFilterMiddleware`. The deprecation note says "web_search is now exposed in Plan Mode directly", but the plan-mode system prompt (`PLAN_MODE_SECTION`) still tells the model: "If tools return `[plan_gate]`, stop and refine the plan" and explicitly lists `web_search` and `task` as not allowed before approval. The runtime no longer enforces any of this.~~
- ~~**Impact:** A Plan Mode run with a still-draft plan can call `web_search`, `bash` with mutations (`rm`, `>`, `tee`, etc.), `write_file`, `task`, etc., contradicting the documented contract. In auto-mode the planner pre-approves the plan so the issue is masked, but in foreground mode the draft state is supposed to be a hard gate. This also weakens the clarification flow: a plan with `clarification_pending=True` no longer blocks tool calls, so the model can ignore the pending question and start executing.~~
- ~~**Recommendation:** Either re-register `PlanExecutionGateMiddleware` (the simplest fix; the file is intact and well-tested), or delete the prompt sections that reference `[plan_gate]` and `scope_search` and update the documented contract to "no runtime gating; relies on the catalog-driven tool-mode split". Today's state is the worst of both worlds — prompt says one thing, runtime does another.~~

### ~~2. `scope_search` is referenced everywhere but is deprecated and unregistered~~ ✅ CLEARED
- **Verified:** `grep -rn "scope_search" backend/src/agents/` returns no matches. The plan prompt now uses `web_search` only and explicitly states the catalog-driven mode split is the source of truth.
- ~~**File:** [backend/src/agents/plan_agent/prompt.py:32,65,75](../../backend/src/agents/plan_agent/prompt.py#L32), [backend/src/agents/middlewares/plan_execution_gate_middleware.py:33-41,254,290](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L33), [backend/src/tools/tools.py:8-71](../../backend/src/tools/tools.py#L8)~~
- ~~**Severity:** High~~
- ~~**Issue:** `scope_search` is mentioned in three places in `PLAN_MODE_SECTION` ("Use scope_search, memory, and read-only tools…", "`scope_search` is for when you genuinely don't know WHAT to search for", "Not allowed: Using `web_search`, `recall`, `scope_search` for content gathering"). But `src/tools/tools.py` shows the wrapper is deprecated and the registration is commented out, and the module-level comment says "web_search is now available in plan mode as well (scope_search deprecated)".~~
- ~~**Impact:** The model is told to call a tool that doesn't exist. In best case the LLM gets a "tool not found" error and falls back to `web_search`. In worst case it never resolves what to do and either stalls or fabricates. The "Not allowed" list also contradicts itself with "Allowed: Use read-only tools for scope understanding".~~
- ~~**Recommendation:** Strip all `scope_search` references from `PLAN_MODE_SECTION` and `plan_execution_gate_middleware.py`. Delete or move `src/community/scope_search/` if confirmed dead.~~

### ~~3. Auto-mode handoff bypass: resolved-clarification path leaks `jump_to=end` without spawning a handoff~~ ✅ CLEARED
- **Verified:** Both inline branches in `PlannerMiddleware.before_model` now route through a single helper `_finalize_plan_handoff` ([planner_middleware.py:644-707](../../backend/src/agents/middlewares/planner_middleware.py#L644)). At the resolved-clarification site, `jump_to=end` only fires when the handoff actually spawned (which requires `thread_id`). The fresh-plan site keeps the original unconditional pause in `plan_foreground` mode — intentional asymmetry, because a draft plan should still halt the planning turn so the user can review even when no handoff fires. Embedded `CapyHomeClient` clarification resolution no longer drops the handoff silently.

### 4. `_classifier_cache` is a per-middleware-instance dict that persists across requests (DORMANT)
- **File:** [backend/src/agents/middlewares/plan_execution_gate_middleware.py:131-220](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L131)
- **Severity:** N/A while deregistered (would be High if re-enabled). `PlanExecutionGateMiddleware` is still commented out at [work_agent/agent.py:511](../../backend/src/agents/work_agent/agent.py#L511); the cache code remains unchanged.
- **Issue:** `self._classifier_cache: dict[str, str] = {}` is keyed on `tool_call_id`. Tool-call IDs are typically unique per call, but the middleware instance is built once per `make_work_agent(config)` call. If the agent is cached/reused across threads (the embedded client does `reset_agent()` only on memory/skill changes — see `src/client.py`), this dict grows unboundedly across requests. There's no eviction. Also no thread-safety: concurrent `wrap_tool_call` on two threads racing the same call_id are possible (very unlikely but not impossible).
- **Impact:** Memory leak proportional to total tool calls observed. No correctness issue absent ID collisions.
- **Recommendation:** Move the cache onto `request.runtime.context` (per-run) or onto a `weakref.WeakValueDictionary`, or use an `lru_cache`-style bounded dict. Or simply drop the cache and accept the rare double-classify cost.

### ~~5. `_HANDOFF_GUARD` deadlock risk: lock is released before in-flight set is fully cleaned~~ ✅ CLEARED
- **Verified:** [work_run_handoff.py:21-42](../../backend/src/agents/middlewares/work_run_handoff.py#L21) — `_IN_FLIGHT_HANDOFFS` is now `dict[str, float]` keyed on `time.monotonic()` with `_IN_FLIGHT_HANDOFF_TTL_SECONDS = 300.0`. A new helper `_in_flight_handoff_present` checks the timestamp and drops stale entries on read. A poisoned thread_id (daemon killed before cleanup) is no longer permanent — after 5 minutes a fresh spawn attempt succeeds.

### ~~6. PlannerMiddleware: synchronous LLM call inside an async path~~ ✅ CLEARED
- **Verified:** `abefore_model` now runs the sync `before_model` via `await asyncio.to_thread(self.before_model, state, runtime)` ([planner_middleware.py](../../backend/src/agents/middlewares/planner_middleware.py)). The LangGraph Server event loop is free during the planner LLM call. The existing inter-token idle timeout (finding #7) keeps wedged providers from leaking worker threads indefinitely. This is the lowest-risk fix; a future `_ainvoke_planner` using `astream`/`asyncio.wait_for` directly would shave off the worker-thread roundtrip but isn't required for correctness.

## High Severity Findings

### ~~7. PlannerMiddleware has no timeout on the LLM call at all~~ ✅ CLEARED
- **Verified:** `_invoke_planner` ([planner_middleware.py:798-848](../../backend/src/agents/middlewares/planner_middleware.py#L798)) now streams tokens and watches the inter-token idle gap; if no token arrives within `_timeout_seconds`, it raises `TimeoutError`. Long local generations still succeed; only a wedged provider trips the guard.
- ~~**File:** [backend/src/agents/middlewares/planner_middleware.py:784-797](../../backend/src/agents/middlewares/planner_middleware.py#L784)~~
- ~~**Severity:** High~~
- ~~**Issue:** `_invoke_planner` calls `model.invoke([SystemMessage, HumanMessage])` with no timeout, no retry. A hung model call blocks the planner indefinitely. Plan Evaluator wraps its call in `_run_with_timeout` (sync) or `asyncio.wait_for` (async); planner has neither.~~
- ~~**Impact:** A wedged LLM endpoint (network stall, OOM at provider) hangs the planning turn forever. The user sees a frozen "planning started" SSE with no recovery.~~
- ~~**Recommendation:** Add `_run_with_timeout` (or extract the helper from `plan_evaluator_middleware`) and reuse a `planner.timeout_seconds` config.~~

### ~~8. `_handle_plan_adapted` SSE fires every single cycle while stuck~~ ✅ CLEARED
- **Verified:** On recheck, [work_mode_middleware.py:613-617](../../backend/src/agents/middlewares/work_mode_middleware.py#L613) already implements the recommended debounce: a `plan_adapted_stall_signature = [blocked_ids, pending_ids]` is computed, compared against `phase_execution.plan_adapted_stall_signature`, and `should_emit` is False when unchanged. `adaptation_attempts` only advances on actual emit. The UI spam scenario is prevented.

### 9. Race: plan_adapted SSE fires during execution but checkpoint write is non-atomic — ACCEPTED AS-IS
- **File:** [backend/src/agents/middlewares/work_mode_middleware.py:619-633](../../backend/src/agents/middlewares/work_mode_middleware.py#L619)
- **Severity:** Low (downgraded from Medium-High)
- **Status:** The SSE-before-checkpoint ordering is inherent to LangGraph's commit model — middleware can't reliably defer SSE emission until after the checkpointer flushes a returned payload. The `adaptation_attempts` counter is purely diagnostic. With finding #8's stall-signature debounce now confirmed, the original spam scenario is prevented, so the race window is brief and only affects a diagnostic field. Accepted as a known limitation.

### ~~10. ClarificationMiddleware mutates the runtime context dict directly~~ ✅ CLEARED
- **Verified:** `before_model` is now a no-op ([clarification_middleware.py:127-134](../../backend/src/agents/middlewares/clarification_middleware.py#L127)). Auto-mode is resolved on demand inside `_handle_clarification` via the new `_resolve_auto_mode(runtime, state)` helper, which reads from `runtime.config["configurable"]` first, then `runtime.context`, then state — preserving the original precedence without mutating any shared dict. `_AUTO_MODE_CTX_KEY` is gone.

### ~~11. PlannerMiddleware applies clarification progress with auto-mode approval bypassed when only one clarification remains~~ ✅ NO ACTION (no bug)
- **File:** [backend/src/agents/middlewares/planner_middleware.py:805-822](../../backend/src/agents/middlewares/planner_middleware.py#L805)
- **Severity:** Low (downgraded — re-read confirms no actual bug, just fragile guard chain)
- **Issue:** When the user answers the LAST clarification, `progress.get("messages")` is None (no next question to prompt). The code skips that branch and proceeds to the handoff branch. Good. But when the user answers an INTERMEDIATE clarification (not the last), `progress.get("messages")` is the next clarification prompt, and we return early at line 822 with `payload = {"plan": resolved_plan, "messages": [next_prompt]}`. Here `resolved_plan` is still `clarification_pending=True`, so `approve_plan_if_auto_mode` at line 809 is a no-op (it checks `clarification_pending` — wait, no it doesn't, it only checks `status == "draft"`).
  
  Actually wait — `approve_plan_if_auto_mode` does NOT check `clarification_pending`. It only checks `status == "draft"`. So if `auto_mode=True` and there are still pending clarifications, the plan can flip to `status="approved"` on the FIRST resolved clarification. Then on the next clarification answer, `should_spawn_work_handoff` becomes True (because status is approved AND clarification_pending may have become False on this answer), and a handoff fires while there are STILL unanswered clarifications waiting.
  
  Re-reading: at L808 the guard is `if not bool(resolved_plan.get("clarification_pending"))`. So approval only happens when ALL clarifications are resolved. OK so it's gated correctly. But the gate is also `should_spawn_work_handoff` which checks `all_clarifications_resolved`. Defensive but correct.
- **Impact:** No bug confirmed, but the chain of guards is fragile — three different functions each check clarification state independently. If one is forgotten in a refactor, auto-mode could spawn premature handoffs.
- **Recommendation:** Centralise the "plan is ready for handoff" predicate. Have one function `is_plan_executable(plan) -> bool` that checks all conditions; have everyone call it.

### ~~12. The "Re-plan with no new user message" baseline detection is off-by-one for legacy plans~~ ✅ CLEARED (defensively)
- **Verified:** [planner_middleware.py:706-724](../../backend/src/agents/middlewares/planner_middleware.py#L706) now returns `False` when the baseline is missing AND `clarification_pending` is set. Note: the outer `_should_plan` already gates on `clarification_pending` before calling this function, so the guard is defensive-only against future refactors that bypass `_should_plan`. No functional regression possible from the legacy-plan + clarification path.

### ~~13. `_plan_behavior` and `_auto_mode_enabled` read from `runtime.context` but `runtime.config["configurable"]` can also carry the same fields~~ ✅ CLEARED
- **Verified:** New shared helper [`backend/src/agents/common/runtime_context.py`](../../backend/src/agents/common/runtime_context.py): `get_runtime_context(runtime)` reads `runtime.context` first, falls back to `runtime.config["configurable"]`. `PlannerMiddleware._runtime_context` ([planner_middleware.py:71-72](../../backend/src/agents/middlewares/planner_middleware.py#L71)) and `PlanFileSyncMiddleware` now delegate. `plan_behavior` written via `make_plan_agent`'s `forced_config["configurable"]` is now honored even when not surfaced on `runtime.context`.

## Medium Severity Findings

### ~~14. `direct_answer_fast_path` is keyword-list-based and English-only~~ ✅ CLEARED (dropped)
- **Verified:** `_looks_like_direct_answer_request`, `_DIRECT_ANSWER_MARKERS`, `_DIRECT_ANSWER_DOMAINS`, and `_DIRECT_ANSWER_BLOCKERS` have all been deleted from `planner_middleware.py`. The single call site in `before_model` is gone; all queries now route through the planner LLM uniformly (the planner's domain classifier already handles "generic chat" cheaply). The dead `skipped_direct_answer` branch in `activity_timeline_middleware.py` was also removed. Also resolves finding #30.

### ~~15. PlanEvaluator's `_run_with_timeout` leaks daemon threads~~ ✅ CLEARED
- **Verified:** The helper was extracted to [`backend/src/agents/middlewares/_timeout_utils.py`](../../backend/src/agents/middlewares/_timeout_utils.py) as `run_with_timeout`, with the daemon-thread caveat documented in its own module docstring (lines 1-7). The async evaluator path at [plan_evaluator_middleware.py:417](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L417) now uses `asyncio.wait_for` directly so the event loop can cancel cleanly; the plan_evaluator module docstring (lines 16-18) explicitly states "Async path uses `asyncio.wait_for` directly so the event loop is free during local LLM token generation; the sync path keeps a daemon-thread fallback for embedded callers." Recommendation satisfied on both fronts.

### ~~16. PlanFileSync background thread holds a deep copy of state but doesn't bound size~~ ✅ CLEARED
- **Verified:** [plan_file_sync_middleware.py:29-50,99-107](../../backend/src/agents/middlewares/plan_file_sync_middleware.py#L29) narrows the snapshot to `_DEEP_COPY_FIELDS = (plan, todo_graph, artifacts, handoff_artifacts, thread_data, todos)` plus a shallow copy of `messages` (kept because `handoff_sync` uses it for the plan-title fallback and execution-notes rendering — BaseMessage instances are effectively immutable so shallow copy is safe). `viewed_images`, `uploaded_files`, `scratchpad`, etc. are no longer copied. Memory cost on 50-turn conversations drops by an order of magnitude.

### ~~17. PlanFileSync uses an implicit `time.sleep(1.0)` to "let state settle"~~ ✅ CLEARED
- **Verified:** [plan_file_sync_middleware.py:20-37,67-79](../../backend/src/agents/middlewares/plan_file_sync_middleware.py#L20) adds a per-thread lock registry (`_THREAD_SYNC_LOCKS` keyed on `thread_id`, guarded by `_LOCKS_REGISTRY_LOCK`). The 1s settle delay is kept but writes are now serialized within the lock; concurrent background workers for the same thread can no longer race the same file. Combined with finding #18's atomic write, plan.md corruption is no longer possible.

### ~~18. `_write_file` in PlannerMiddleware is non-atomic~~ ✅ CLEARED
- **Verified:** New helper [`atomic_write_text(path, content)`](../../backend/src/agents/middlewares/_fs_utils.py) writes to a uuid-suffixed `.tmp` file then `os.replace`s into place. `planner_middleware._write_file` and `handoff_sync._write_if_changed` both delegate. The uuid suffix makes concurrent callers safe even without an external lock. A mid-write crash now leaves the prior file intact; no more silent loss of user edits between approval and crash.

### ~~19. PlannerMiddleware emits SSE `plan_created` even when plan was auto-approved AND a handoff fires~~ ✅ CLEARED
- **Verified:** `_finalize_plan_handoff` ([planner_middleware.py:644-707](../../backend/src/agents/middlewares/planner_middleware.py#L644)) now emits a `plan_handoff_started` SSE event (carrying `plan_id`, `status`, `thread_id`) immediately after `spawn_work_mode_handoff` succeeds, before any `jump_to=end`. A matching `plan_handoff_started` runtime event is also appended for trajectory consumers. The frontend has a clean transition signal between plan-mode and work-mode SSE streams.

### ~~20. PlanEvaluator: max_attempts loop may emit `max_attempts_reached` for already-okay plans~~ ✅ CLEARED
- **Verified:** [plan_evaluator_middleware.py:698](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L698) now gates on `attempts >= self._max_attempts AND last_decision not in {ok, timeout_skipped, non_json_skipped, llm_error_skipped}`, so an early break on `revision_invalid` / `issues_no_revision` with `attempts < max_attempts` no longer triggers the misleading decision.
- ~~**File:** [backend/src/agents/middlewares/plan_evaluator_middleware.py:698-704](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L698)~~
- ~~**Severity:** Medium~~
- ~~**Issue:** `_build_terminal_payload` emits `max_attempts_reached` only when `last_decision not in {"ok", "timeout_skipped", "non_json_skipped", "llm_error_skipped"}`. But the loop can break on `revision_invalid` or `issues_no_revision`, both of which also won't fix the plan. The current check would emit `max_attempts_reached` in those cases even when only 1 attempt ran (because the loop broke early without incrementing past max).~~
- ~~**Impact:** Misleading observability — `max_attempts_reached` decision is logged when attempts < max.~~
- ~~**Recommendation:** Tighten the predicate: only emit `max_attempts_reached` when `attempts >= max_attempts` AND a "revised" attempt was made.~~

### ~~21. Inline clarification panel and `ClarificationMiddleware` step on each other~~ ✅ CLEARED (dedup short-circuit)
- **Verified:** `ClarificationMiddleware._handle_clarification` ([clarification_middleware.py](../../backend/src/agents/middlewares/clarification_middleware.py)) now checks the incoming question against `state.plan.clarifications` via the new `_planner_clarification_duplicate` helper. When the LLM follows the `planner_clarification_required` prompt and calls `ask_user_for_clarification` with a question already surfaced inline by the planner, the middleware returns a short-circuit `ToolMessage` ("Clarification already pending in the inline panel — the user will answer there") without appending to `state.clarifications` or interrupting. Both subsystems still exist (full unification would require a coordinated frontend change), but the duplicate-UI symptom is gone.

### ~~22. ClarificationMiddleware: state.clarifications append semantics depends on reducer~~ ✅ CLEARED
- **Verified:** [thread_state.py:239-267](../../backend/src/agents/thread_state.py#L239) defines a `merge_clarifications` reducer that dedupes-by-id, preserves order, and merges entries; [thread_state.py:315](../../backend/src/agents/thread_state.py#L315) annotates the field as `clarifications: Annotated[list[Clarification], merge_clarifications]`. The append-semantics assumption is now backed by an explicit reducer rather than default-replacement.

### ~~23. Plan Evaluator does not validate that the LLM left `todo_ids` consistent~~ ✅ CLEARED
- **Verified:** [plan_evaluator_middleware.py:681-712](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L681) — `_build_terminal_payload` now threads `plan` through and, when `nodes_changed`, also writes back `plan["todo_ids"] = [node["id"] for node in nodes if node.get("id")]` and refreshes `plan["updated_at"]`. Progress-UI consumers reading `plan["todo_ids"]` after a revision now see the patched node set.

### ~~24. `_normalize_plan_status` silently coerces invalid status to "draft"~~ ✅ CLEARED
- **Verified:** Both sites now emit `logger.warning("Unknown plan status %r coerced to 'draft'", value)` when a non-empty unknown value is coerced ([work_mode_middleware.py:113-122](../../backend/src/agents/middlewares/work_mode_middleware.py#L113), [plan_execution_gate_middleware.py:95-101](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L95)). The empty-string case (legitimate "no plan yet") is correctly suppressed. The coercion behavior is preserved for defensive safety; only the silence is fixed.

## Low Severity / Nits

### ~~25. Stale module docstring in `plan_agent/agent.py`~~ ✅ CLEARED
- **Verified:** [plan_agent/agent.py:1-12](../../backend/src/agents/plan_agent/agent.py#L1) — docstring rewritten. "auto-escalation paths" replaced with "the frontend's manual toggle (Shift+Tab)" plus an explicit note that "Work Mode never auto-escalates to Plan Mode anymore; entry is fully user-initiated."

### ~~26. Stale docstring in `work_mode_middleware.py` / doc drift~~ ✅ CLEARED
- **Verified:** [04_handoff_contract.md:112](../../docs/plan-mode/04_handoff_contract.md#L112) section header is now "Daemon-driven (auto-approval)" — the misleading "/ auto-escalation" suffix is gone. Remaining mentions in `README.md`, `01_overview.md`, `02_components.md`, and `03_flow_narrative.md` correctly document that auto-escalation **was removed** (historical context); they're informative, not stale.

### ~~27. `del router` pattern is repeated but unhelpful~~ ✅ CLEARED
- **Verified:** `router` parameter removed from `PlannerMiddleware.__init__` and `PlanEvaluatorMiddleware.__init__`. Production callers (`work_agent/agent.py` `_create_planner` / `_create_plan_evaluator`) didn't pass it. Test sites in `test_planner_evaluator_middleware.py` that passed `router=_router()` to `PlannerMiddleware` were programmatically updated; the unrelated `EvaluatorMiddleware` sites in the same file (a different class) are untouched.

### ~~28. `_ensure_research_clarifications` mutates list shape using hard-coded heuristics~~ ✅ CLEARED
- **Verified:** Function deleted along with `_YEAR_RANGE_RE`. Replaced by `_normalize_planner_clarifications(output, max_clarifications)` which only keeps the generic dedup-by-question + option-normalisation logic — no domain-specific injection. The planner LLM is now the single source for clarification *content*. Test `test_research_clarifications_normalize_recommended_first_and_option_count` renamed and updated.

### ~~29. `_versioned_plan_filename` duplicated~~ ✅ CLEARED
- **Verified:** `handoff_sync.py` now exposes `slugify_plan_title` and `versioned_plan_filename` as the canonical public functions (with private `_slugify_title` / `_versioned_plan_filename` aliases retained for in-module callers). `planner_middleware` imports `versioned_plan_filename` from `handoff_sync` and the local regex-based duplicate is gone.

### ~~30. `_DIRECT_ANSWER_BLOCKERS` includes "legal" — conflicts with the legal domain support~~ ✅ CLEARED (by removal)
- **Verified:** Resolved via finding #14: the entire keyword-driven fast path including `_DIRECT_ANSWER_BLOCKERS` was deleted. The legal/contract blocker conflict is moot.

### ~~31. Hard-coded thread name string slicing~~ ✅ CLEARED
- **Verified:** Defensive `str(thread_id or "")[:8]` applied in `work_run_handoff.py` (both spawn sites) and `plan_file_sync_middleware.py` (with an `'anon'` fallback when thread_id is empty).

### ~~32. Question-generation middleware `.format(...)` unguarded~~ ❌ NOT REPRODUCIBLE
- **File:** [backend/src/agents/middlewares/question_generation_middleware.py:61-72](../../backend/src/agents/middlewares/question_generation_middleware.py#L61)
- **Status:** On re-check, no unguarded `.format(...)` was found at the cited site. The original concern appears to have referenced a path that was either removed or refactored. Dropping unless a regression reappears.

### ~~33. `Runtime.context` typed as dict but read as Any~~ ✅ CLEARED
- **Verified:** Added [`backend/src/agents/common/runtime_context.py`](../../backend/src/agents/common/runtime_context.py) exporting `get_runtime_context(runtime) -> dict[str, Any]`. `PlannerMiddleware` and `PlanFileSyncMiddleware` now delegate to it. Other middlewares can be migrated incrementally — the helper exists and the pattern is established. Also clears finding #13.

### ~~34. Planner: `_should_plan` returns True when ai_count == 0, regardless of whether the planner already ran~~ ✅ OBSOLETED BY #14
- **Status:** The original concern was driven by the direct-answer fast path returning early without setting a plan. With #14/PR6 deleting that fast path entirely, the only way for `_should_plan → _invoke_planner` to fail to produce a plan is LLM timeout/error, and retrying on the next turn is the desirable behaviour. No cache flag needed.

## Architectural Observations

- **Centralise plan-lifecycle predicates.** ⚠️ PARTIALLY ADDRESSED — added `is_plan_executable(plan)` in [plan_execution.py:151-171](../../backend/src/agents/middlewares/plan_execution.py#L151) as the canonical "ready for handoff" check. `should_spawn_work_handoff` now delegates to it. `all_clarifications_resolved`, `handoff_already_started`, `work_execution_underway`, `execute_plan_should_duplicate` remain as separate concerns and could be folded in later.
- **Plan Mode prompt should live next to a registered guardrail middleware.** With `PlanExecutionGateMiddleware` deregistered, the plan-mode prompt is the only thing stopping the model from calling `web_search` / `task` / `write_file` in draft state. Prompt-only enforcement is unreliable. Either re-register the gate or drop the prompt's discipline language. (Per finding #1's resolution, the prompt no longer claims runtime gating exists — the catalog-driven mode split is now the documented contract.)
- **Two clarification subsystems is one too many.** See Finding #21. The interaction matrix between planner-inline clarifications, ClarificationMiddleware deferred clarifications, and `ask_user_for_clarification` tool calls is fragile. A single source of truth (one queue, one set of predicates) would dramatically simplify reasoning. **Not addressed in the implementation pass** — flagged as requiring a design decision (planner-owns vs tool-call-owns).
- **Background daemon threads everywhere.** `spawn_work_mode_handoff`, `spawn_title_handoff_if_missing`, `_run_background_plan_sync`, `run_with_timeout`, `MemoryMiddleware` queue — these all spawn daemon threads with manual coordination via module-level locks and sets. The plan-sync writer now has a per-thread lock (finding #17) and atomic writes (finding #18), narrowing the surface — but the systemic concern remains: consider moving to a single bounded worker pool with structured supervision; finding #5's leak remains.
- **Planner prompt is enormous** (~200 lines including domain rules, todo style, example, rich-execution fields). The token cost per planning turn is non-trivial. Several sections are documentation that the LLM doesn't need on every call (e.g. the full example). Consider extracting per-domain prompts conditionally.

## Dead code / stale references (2026-05-30 final recheck)

- **`PlanExecutionGateMiddleware`** ([plan_execution_gate_middleware.py](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py)) — still deregistered in [work_agent/agent.py:505-511](../../backend/src/agents/work_agent/agent.py#L505). Decision pending: re-register or delete. Kept warning on `_normalize_plan_status` (finding #24) so the file at least stays consistent with the live one. Recommend: ship a follow-up that deletes both this middleware and `PhaseToolFilterMiddleware` since prompt-only enforcement is now the documented contract.
- **`PhaseToolFilterMiddleware`** import still commented; source file likely still exists. Same recommendation as above.
- ~~**`scope_search`** community module references.~~ ✅ CLEARED.
- ~~**`auto-escalation paths`** wording in `plan_agent/agent.py:7`.~~ ✅ CLEARED — docstring rewritten.
- ~~**`docs/plan-mode/04_handoff_contract.md:112`** "auto-approval / auto-escalation" header.~~ ✅ CLEARED — retitled to "Daemon-driven (auto-approval)". Other doc mentions correctly document removal as historical context.
- ~~**`router=ctx.router` parameter**~~ ✅ CLEARED — parameter removed from both middlewares.
- **Legacy `revised_todos` contract** in `PlanEvaluatorMiddleware._apply_response` ([plan_evaluator_middleware.py:481-489](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L481)) — kept for back-compat. **Open**: audit callers and drop if unused.
- **`mark_handoff_started`** in [plan_execution.py:146-148](../../backend/src/agents/middlewares/plan_execution.py#L146) is a backward-compatible alias. **Open**: audit callers and drop.
- ~~**`_DIRECT_ANSWER_DOMAINS` / `_DIRECT_ANSWER_MARKERS` / `_DIRECT_ANSWER_BLOCKERS`** lists.~~ ✅ CLEARED.
