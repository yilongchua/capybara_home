# Core Middleware — Code Review

## Summary

Reviewed 26 "general" core middleware modules in `backend/src/agents/middlewares/`
end-to-end. The original audit's High-severity findings (#18 write-artifact
gate, #29 summarization tool-pair coherence) are resolved, along with the
full sweep of Medium and Low items below.

Verified against current code on 2026-05-30. Original finding numbers
preserved for traceability; everything is now in the resolved index unless
noted otherwise.

What remained out of scope after this pass:
- **#21 (ActivityTimeline event-type registry):** the hardcoded fallback set
  was extended to cover all known emitters, but the broader refactor to a
  decorator-based registry is deferred — it requires touching every
  emitting middleware and isn't justified by current pain.
- **#30 (hooks `shell=True`):** documented in code as
  operator-trusted (config-source policy). Switching individual hooks to
  `shlex.split` + `shell=False` is deferred until config ingestion ever
  broadens beyond operator-owned files.
- **#39 (steering id stability):** legacy intents now get a deterministic
  content-hash id rather than a fresh UUID on each load. A proper fix
  (mint ids exactly once at write time) needs cooperation from upstream
  writers and is out of scope here.

---

## Resolved Items

The original finding numbers are kept so cross-references in the
conversational record remain greppable. Each entry names the resolution.

### High Severity

- **#18** — `WriteFileArtifactMiddleware`: split honest pre-write gate
  (`_quality_gate_precheck`, full-replace `write_file` only) from
  post-write gate (`_run_postwrite_gate`, `str_replace` and
  `write_file append=True`). Distinct `QUALITY_GATE_POSTWRITE_FAILED`
  message tells the agent the edit landed and asks for a corrective edit
  rather than a "retry". `block_on_failure` now honest for the full-replace
  case and clearly advisory for edit-style. Module docstring states the
  contract.
- **#29** — `SummarizationMiddleware`: pair rescue
  (`_rescue_tool_call_pairs`) drags orphan tool_result counterparts'
  parent `AIMessage` from the to-summarize set back into preserved, in
  chronological order. Mirror direction (AI preserved, ToolMessage in
  remaining) intentionally not auto-rescued because it cannot arise from
  natural partition flow and prepending would violate Anthropic's
  tool_use-before-tool_result invariant; instead a WARNING is logged via
  `_assert_tool_pair_coherence`.

### Medium Severity

- **#14** — `TitleMiddleware`: per-instance `_generated_title` /
  `_title_bg_task` migrated to run-scoped storage
  (`run_scoped.get_run_store(runtime)` keyed by runtime identity). No
  more cross-run leakage on shared middleware instances.
- **#16** — `EvaluatorMiddleware._pre_verify` /` _evaluate_llm`: extract
  latest AI answer via `_latest_real_ai_answer` (walks backwards to the
  last real AIMessage) instead of blindly taking `messages[-1]`. Skips
  injected evaluator-feedback echoes on retry turns.
- **#17** — `HooksMiddleware.after_model`: new `FileRemoved` hook event
  emitted for `observed - current`. `hooks_state` checkpoint write is
  skipped when `current_files == observed_files` (eliminates spurious
  per-turn checkpoint churn). `HooksConfig.FileRemoved` added to the
  config schema.
- **#19** — `WebSearchSummaryMiddleware`: prompt template now uses
  unambiguous sentinels (`<<__CAPYHOME_WS_QUERY_SLOT__>>` /
  `<<__CAPYHOME_WS_CONTENT_SLOT__>>`) instead of `{query}` /
  `{raw_content}` markers, closing the prompt-injection surface where a
  user query containing literal `{raw_content}` could be replaced with
  the raw search-result body.
- **#20** — `UploadsMiddleware`: `<uploaded_files>` block now injected
  **ephemerally** via `wrap_model_call` (and `awrap_model_call`) rather
  than mutating the canonical message history in `before_agent`.
  `before_agent` only records the new-files list in state. Closes #20
  and indirectly fixes #28 (title fallback no longer leaks the
  bookkeeping block, since it's never in stored history) and improves
  #23.
- **#23** — `SummarizationMiddleware._deterministic_fallback_summary`:
  `/mnt/user-data/` regex matches are intersected with the canonical
  `state["artifacts"]` registry so stale paths from old tool errors are
  no longer elevated into "Files Referenced".
- **#24** — `SkillDisclosureMiddleware._SKILL_BODY_CACHE`: now a bounded
  LRU `OrderedDict` (max 128 entries) instead of an unbounded dict. mtime
  invalidation kept; eviction now happens on insertion when the cap is
  reached.
- **#25** — `MetricsMiddleware._base_labels`: dropped `thread_id` from
  the label set. `_COUNTERS` no longer grows per-thread. The
  recommendation to expose per-thread metrics via a separate per-run
  scratchpad (if ever needed) is documented in code.
- **#26** — `ThreadDataMiddleware.before_agent`: UUID fallback now gated
  behind `CAPYHOME_TEST_MODE=1` and logs a WARNING. Production
  misconfigurations that drop `thread_id` now raise a clear
  `RuntimeError` immediately instead of silently creating disposable
  per-turn threads.
- **#27** — `ExecutionTraceMiddleware._inline_trace_from_runtime_event`:
  always assigns an `id` (UUID4 when missing) so the downstream
  `streamed_event_ids` dedup at line 291-300 reliably catches duplicates.
- **#35** — `EvaluatorMiddleware._evaluate_llm`: empty-string `VERDICT:`
  is now treated as missing (`if not verdict:`) so the first-line
  fallback fires and avoids spuriously downgrading every empty-verdict
  response to FAIL.
- **#38** — `ThreadDataMiddleware._probe_writability`: now gated behind
  `not self._lazy_init`. The `_lazy_init=True` flag actually defers
  directory I/O instead of being cosmetic.
- **#39** — `SteeringMiddleware._normalize_intents` / `_legacy_intent`:
  legacy intents get a deterministic content-hash id (`legacy-{sha256[:16]}`)
  and an epoch timestamp instead of a fresh `uuid4()` + `datetime.now()`
  on every read, so downstream dedup keyed on `intent_id` works across
  reloads.
- **#41** — `PlanFollowupMiddleware._has_plan_context`: now checks for
  non-empty `plan` dict OR non-empty `todo_graph.nodes` list, not just
  key presence. Closes the asymmetric truthiness gap where
  `todo_graph={"nodes":[]}` was truthy but `plan={}` was falsy.
- **#43** — `ExecutionTraceMiddleware._SOURCE_STAGE`: extended with
  explicit mappings for `summarization_middleware`,
  `web_search_summary`, `quality_gate_middleware`,
  `loop_detection_middleware`, `model_timeout_middleware`,
  `thread_data_middleware`, `activity_timeline_middleware`,
  `autoresearch_middleware`.

### Low Severity / Nits

- **#13** — `MemoryMiddleware.after_agent`: two `print()` calls replaced
  with `logger.debug(...)`.
- **#15** — `MountFolderMiddleware.before_agent`: dead `if mode == "plan":`
  conditional removed.
- **#21** — `ActivityTimelineMiddleware`: hardcoded fallback set extracted
  into module-level `_ACTIVITY_FALLBACK_SOURCES` and extended to cover
  every known emitter. Decorator-based registry deferred (see Summary).
- **#22** — `ViewImageMiddleware._should_inject_image_message`: dedup
  now keyed on `SystemMessage.name == "viewed_images_disclosure"` (set
  at injection time) instead of substring-scanning the injected
  message's multi-MB base64 content. O(1) per message instead of
  O(content size).
- **#28** — `TitleMiddleware._prepare_generation`: strips the
  `<uploaded_files>` block from `user_msg` before truncation, so the
  fallback title can never literally be `<uploaded_files>The follo...`.
  (Also self-resolves through #20.)
- **#30** — `HooksMiddleware._run_command`: `shell=True` documented in
  code as operator-trusted, with explicit guidance for future
  hardening if config ingestion broadens.
- **#31** — `TrajectoryMiddleware._truncate`: depth cap (10) added so
  deeply-nested or self-referential payloads can't blow the recursion
  limit.
- **#32** — `runtime_events.append_runtime_event`: deep-copy contract
  now documented in the docstring (conservative copy retained; callers
  agreeing not to mutate post-append could drop it in a future pass).
- **#33** — `AutoresearchMiddleware._handle_autoresearch`: exception
  handler logs the full traceback via `logger.exception(...)` but
  surfaces only `exc.__class__.__name__` to the model output, so
  internal types/paths/tokens don't leak into user-visible text.
- **#34** — `MessageSelection._SYNTHETIC_REQUEST_PATTERNS`: dropped the
  brittle "continue the previous plan-mode answer in the background"
  free-text pattern since `plan_followup_prompt` (the structural name)
  already catches the same messages. Comment explains why.
- **#36** — `ViewImageMiddleware`: `print(...)` replaced with
  `logger.debug(...)`.
- **#40** — `MemoryMiddleware`: `_UPLOAD_BLOCK_RE` hoisted to
  module-level.
- **#42** — `MountFolderMiddleware._mount_block`: missing space in
  implicit-concatenated f-strings fixed (`"accessible at"
  "virtual path:"` → `"accessible at virtual path:"`).

### From the original audit, previously resolved

- #1 — `WriteFileArtifactMiddleware` sync/async quality-gate parity
- #2 — `EvaluatorMiddleware.aafter_model` no longer blocks the event loop
- #3 — `PlanFollowupMiddleware` background-client leak
- #4 — `runtime_events._compact_runtime_events` single-consumer leak
- #5 — `AutoresearchMiddleware._autoresearch_triggered` race
- #6 — Activity-timeline tool-input scratch eviction
- #7 — `runtime.context` mutation contract (run-scoped storage helper)
- #8 — Per-file trajectory write locks
- #9 — `SummarizationMiddleware._fire_hooks` explicit signature
- #10 — `ResumeStateMiddleware.aafter_model` evaluated and accepted
- #11 — Summarization skill-rescue token-budget recheck
- #12 — `WebSearchSummaryMiddleware` timeout-thread containment via shared executor
- #37 — Verified not a bug: `Command`-result short-circuit in `WriteFileArtifactMiddleware` is by design

---

## Cross-cutting observations

1. **Per-instance state vs. per-run state**: The remaining offender
   (`TitleMiddleware`) was migrated to `run_scoped.get_run_store`.
   No known per-run state remains on `self` of a shared middleware.

2. **Async fall-throughs to sync**: The critical instance
   (`EvaluatorMiddleware`) was fixed in the original pass. The
   remaining CPU-only `aafter_*` → `after_*` shortcuts are accepted as
   safe with the invariant documented in the code.

3. **Unbounded module-level state**: `_SKILL_BODY_CACHE` (#24),
   `_COUNTERS` (#25), `_FAILED_JOBS` (#3) all now bounded. A reusable
   LRU+TTL primitive in `agents/middlewares/_caches.py` is a possible
   future cleanup but no longer load-bearing.

4. **Persistent state pollution from middleware**: With
   `UploadsMiddleware` switched to ephemeral injection (#20), no
   remaining middleware writes back into the canonical message
   history. The pattern of injecting via `wrap_model_call` is the
   established convention going forward.

5. **Stringly-typed event types**: `event` / `decision` / `signal` /
   `phase` are still used interchangeably across middlewares (see
   `execution_trace._runtime_event_to_trace` lines 154-162). A
   `TypedDict` or enum would catch typos at edit time. Out of scope
   for this pass.

---

## Middleware ordering concerns

Based on the registry order documented in `backend/CLAUDE.md` and
registry construction in `work_agent/agent.py`:

1. **UploadsMiddleware before SummarizationMiddleware**: with the
   ephemeral-injection fix (#20), this is no longer a problem.
   Summarization snapshots no longer freeze upload metadata.

2. **SkillDisclosureMiddleware before SummarizationMiddleware**:
   SkillDisclosureMiddleware injects `HumanMessage(name="active_skills")`.
   SummarizationMiddleware's `_rescue_skill_messages` saves the *most
   recent* skill block. If skills are activated mid-thread and then
   deactivated, the old injection from before deactivation is rescued.
   Worth tracking but low-impact in practice.

3. **EvaluatorMiddleware vs. WriteFileArtifactMiddleware ordering**:
   EvaluatorMiddleware writes evaluator reports to disk and adds them
   to `handoff_artifacts`. HooksMiddleware's `FileChanged` watches
   `artifacts + handoff_artifacts`. Order isn't obviously broken but
   it's not enforced — if EvaluatorMiddleware moved *after*
   HooksMiddleware, FileChanged would miss evaluator reports.

4. **ToolDisclosureMiddleware before HooksMiddleware**: ToolDisclosure
   can short-circuit with a `[tool_disclosure_blocked]` ToolMessage.
   HooksMiddleware's PreToolUse hook *also* short-circuits. Today
   ToolDisclosure runs first (it can prevent hook side effects),
   which seems correct, but the ordering invariant isn't asserted
   anywhere.

5. **TrajectoryMiddleware position relative to
   ResumeStateMiddleware**: ResumeStateMiddleware's `after_model`
   snapshots state to `resume_meta`. If TrajectoryMiddleware runs
   after ResumeStateMiddleware, it sees the updated resume_meta in
   state; before, it sees the previous. The trajectory is then
   inconsistent with the resume marker.
