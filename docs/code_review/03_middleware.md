# Core Middleware — Code Review

## Summary

Reviewed 26 "general" core middleware modules in `backend/src/agents/middlewares/`
end-to-end (with deep-reads on the largest: `summarization_middleware.py`,
`activity_timeline_middleware.py`, `trajectory_middleware.py`,
`execution_trace_middleware.py`).

The most severe correctness, concurrency, and resource-leak issues from the
original review have been resolved (see the original audit for context):
sync/async write-artifact parity, the evaluator's event-loop blocker, the
unbounded follow-up client leak, runtime-event compaction with a single
consumer, per-instance autoresearch race, the unbounded tool-input scratch,
the `runtime.context` mutability assumption, global trajectory-write lock,
brittle hook-arg dispatch, summarization rescue overshoot, and the
web-search timeout thread storm have all been fixed or formally evaluated.

What's left is mostly **resource-bound hygiene**, **logic edges around
compaction / evaluator / hooks**, and **low-severity ergonomics**. Original
finding numbers are preserved for traceability; completed items have been
dropped. Verified against current code on 2026-05-30.

Themes that remain:
- `UploadsMiddleware` still mutates the last `HumanMessage` in-place, baking
  upload metadata into thread state forever (#20).
- A handful of unbounded module-level caches/counters (`MetricsMiddleware`,
  `SkillDisclosureMiddleware`) still grow without eviction (#24, #25).
- Several `print()` calls remain in production code paths (#13, #36).
- Two real **High** issues survive: `WriteFileArtifactMiddleware`'s
  post-write quality gate cannot actually block (#18), and
  `SummarizationMiddleware` does not guarantee AI+Tool pair co-preservation
  across compaction (#29).

---

## High Severity Findings

### 18. `WriteFileArtifactMiddleware._quality_gate_precheck` is actually a post-check; `block_on_failure` cannot roll back the write
- File: `backend/src/agents/middlewares/write_file_artifact_middleware.py:49-66,215-239`
- Severity: High
- Status: Still present (verified). The shared sync/async path consolidation from finding #1 did not address this — the check is invoked both as a pre-check and as a post-check, but for `str_replace`/append/edit the meaningful validation only runs *after* the tool has already written to disk.
- Issue: Postcheck calls `host_path.read_text(...)` to validate file content, but the tool has already mutated the file. If quality gate fails, only a warning message is appended — the bad write persists.
- Impact: The `block_on_failure` contract is misleading for edit-style tools; users expect blocking, get advisory.
- Recommendation: Document this caveat explicitly in the middleware docstring, or apply edit semantics in a sandbox (temp file, simulated str_replace) before invoking the handler. The fully-replacing `write_file` case *can* be true pre-checked since content is known up front; split the two paths.

### 29. `SummarizationMiddleware` does not guarantee AI+Tool message pair co-preservation across the cutoff
- File: `backend/src/agents/middlewares/summarization_middleware.py:309-323`
- Severity: High
- Status: Partially mitigated by the skill-rescue rework (#11), but the core AI+Tool pairing invariant is still not asserted.
- Issue: `[RemoveMessage(id=REMOVE_ALL_MESSAGES), *new_messages, *preserved]`.
  If a preserved AIMessage carries `tool_calls=[X]` but the corresponding
  ToolMessage(id=X) was in the `to_summarize` set, the rebuilt thread has a
  dangling `tool_use` with no matching `tool_result` — an Anthropic API
  hard error (`tool_use_ids must have matching tool_result blocks`).
- Impact: Model API failures *after* compaction; failure mode is a hard
  500 from the provider, not a graceful degradation.
- Recommendation: Either (a) extend `_partition_messages` to drag any
  ToolMessage matching a preserved AIMessage's `tool_calls` into the
  preserved set, or (b) add a post-build assertion that walks preserved
  messages and verifies every `tool_use` id has a matching `tool_result`,
  rescuing or dropping the orphan AI's `tool_calls` field if not.

---

## Medium Severity Findings

### 14. `TitleMiddleware` background task is per-instance; cross-run leakage if same agent reused
- File: `backend/src/agents/middlewares/title_middleware.py:73-75,213,232-244`
- Severity: Medium
- Status: Partially mitigated — `aafter_model` now resets `self._generated_title = None; self._title_bg_task = None` at line 171-172. However, the reset happens at the start of a *new* `aafter_model`, which means if two runs overlap, the second resets the first's title before `aafter_agent` can consume it.
- Issue: Same root cause as the (now fixed) finding #5 — run-scoped state on `self` of a shared middleware instance.
- Impact: Title-update race for concurrent runs on the same agent instance.
- Recommendation: Migrate `_generated_title` / `_title_bg_task` onto the existing run-scoped storage helper (introduced for finding #5/#7).

### 16. `EvaluatorMiddleware._pre_verify` extracts `latest_ai` from `messages[-1]` without skipping evaluator feedback
- File: `backend/src/agents/middlewares/evaluator_middleware.py:162-164`
- Severity: Medium
- Status: Still present.
- Issue: `latest_ai = _extract_text(getattr(messages[-1], "content", ""))`. On a retry turn, `messages[-1]` may be the injected `HumanMessage(name="evaluator_feedback", ...)` from the prior eval cycle, not the real AI answer. The 400-char draft-mode guard then compares against synthetic content.
- Impact: Wrong verdict on retry loops; draft-mode guard can trigger on evaluator echo.
- Recommendation: Use `message_selection.latest_real_ai_answer` to walk back past evaluator-feedback messages.

### 17. `HooksMiddleware.after_model` does not emit `FileRemoved`; checkpoint write fires when `observed != current` even with no `added`
- File: `backend/src/agents/middlewares/hooks_middleware.py:163-174`
- Severity: Medium
- Status: Still present.
- Issue: The handler only emits `FileChanged` for `added` files. If a file disappears from `artifacts + handoff_artifacts` (current < observed), no hook event fires, and `observed_files` is silently overwritten. Additionally, the state update at line 174 runs whenever the sets differ — including the empty-added case — triggering an extra checkpoint write per turn.
- Impact: Missed `FileRemoved` semantics; minor checkpoint churn.
- Recommendation: Emit `FileRemoved` for `observed - current`. Skip the `hooks_state` write when `current_files == observed_files`.

### 19. `WebSearchSummaryMiddleware` summarization prompt uses naive `.replace("{query}", ...)`
- File: `backend/src/agents/middlewares/web_search_summary_middleware.py:146-149`
- Severity: Medium
- Status: Still present.
- Issue: `prompt = _SUMMARY_PROMPT_TEMPLATE.replace("{query}", query).replace("{raw_content}", content)`. If a search result includes the literal `{raw_content}` (a JSON dump, a template snippet, a deliberately crafted page), the second `.replace` substitutes within it.
- Impact: Prompt-injection surface via web-search results.
- Recommendation: Use unambiguous sentinel markers (e.g. `<<RAW_CONTENT_PLACEHOLDER_UUID>>`) substituted in a fixed order, or `str.Template` with safe substitution.

### 20. `UploadsMiddleware` rewrites the last `HumanMessage` every turn the user uploads
- File: `backend/src/agents/middlewares/uploads_middleware.py:193-204`
- Severity: Medium
- Status: Still present.
- Issue: `before_agent` creates `HumanMessage(content=..., id=last_message.id, ...)` with prepended `<uploaded_files>` content. The id-preserving reducer replaces in place, but the new content is now persisted into thread state and shows up in every future summarization snapshot — even after the user removes the file.
- Impact: Token bloat in long sessions; stale file paths linger; summarization snapshots reference files that no longer exist.
- Recommendation: Inject the `<uploaded_files>` block ephemerally via `wrap_model_call` (override `request.messages` for that call only), mirroring `MountFolderMiddleware._with_ephemeral_mount_context`. This is the right architectural pattern and also closes finding #28 (title fallback) and improves #23 (stale path regex).

### 23. `SummarizationMiddleware` deterministic fallback regex may pull stale paths
- File: `backend/src/agents/middlewares/summarization_middleware.py:453-457`
- Severity: Medium
- Status: Still present. Lower urgency since the deterministic fallback rarely runs in practice, but the issue compounds with #20 — the `<uploaded_files>` block in persisted history feeds stale paths into the regex.
- Issue: `re.finditer(r"/mnt/user-data/[^\s)`'\"]+", content)` scrapes file paths from raw message content with no source filtering. Paths from old tool errors or transient logs are elevated into the "Files Referenced" section.
- Impact: Misleading "Files Referenced" in fallback summaries.
- Recommendation: Intersect regex matches with `state["artifacts"]` (or whatever the canonical artifact registry is at that point).

### 24. `SkillDisclosureMiddleware` cache never evicts
- File: `backend/src/agents/middlewares/skill_disclosure_middleware.py:26-45`
- Severity: Medium
- Status: Still present.
- Issue: `_SKILL_BODY_CACHE: dict[str, tuple[float, str]]` is a module-level dict that grows with every distinct skill file ever read. Mtime checks only invalidate stale entries, never evict.
- Impact: Slow memory growth in installations with churning skill files.
- Recommendation: `functools.lru_cache(maxsize=64)` or a bounded `OrderedDict`.

### 25. `MetricsMiddleware._COUNTERS` has unbounded cardinality
- File: `backend/src/agents/middlewares/metrics_middleware.py:22-31,96`
- Severity: Medium
- Status: Still present.
- Issue: `_base_labels` (line 95) includes `"thread_id": context.get("thread_id") or "unknown"`. Every distinct thread creates a new counter key for every metric name; counters are never reset and never expired.
- Impact: Memory growth in `_COUNTERS` proportional to thread count × metric × tool. Long-running deployments accumulate forever.
- Recommendation: Drop `thread_id` from the default label set (classic high-cardinality anti-pattern). If per-thread metrics are needed downstream, expose them via a separate per-run scratchpad cleared in `after_agent`.

### 26. `ThreadDataMiddleware` falls back to a random UUID `thread_id`, masking config bugs
- File: `backend/src/agents/middlewares/thread_data_middleware.py:79-83`
- Severity: Medium
- Status: Still present.
- Issue: When `thread_id is None`, generates `"test-" + uuid4()` silently. A production misconfiguration that drops `thread_id` looks like "thread state isn't persisting" — every turn creates a new disposable thread directory.
- Impact: Silent data-loss appearance; hard to diagnose.
- Recommendation: `logger.warning(...)` on the fallback path. Gate the fallback itself behind `CAPYHOME_TEST_MODE=1` (or similar) so production fails fast instead of silently creating disposable threads.

### 30. `HooksMiddleware._run_command` runs `shell=True`
- File: `backend/src/agents/middlewares/hooks_middleware.py:64-74`
- Severity: Medium (security)
- Status: Still present.
- Issue: `subprocess.run(hook.command, shell=True, cwd=...)`. Hook commands come from config. As long as configs are not editable through unprivileged endpoints, this is trust-by-policy and OK. The risk surfaces only if config ingestion ever broadens.
- Impact: Config-injection if config source widens.
- Recommendation: Document hook commands as trusted. Where individual hooks could plausibly be expressed as argv lists, prefer `shlex.split` + `shell=False`.

### 35. `EvaluatorMiddleware._evaluate_llm` mishandles empty `VERDICT:` value
- File: `backend/src/agents/middlewares/evaluator_middleware.py:233-245`
- Severity: Medium
- Status: Still present.
- Issue: `if verdict is None:` — if the model emits `VERDICT:` with no value, `verdict` is parsed as `""`, not `None`, so the first-line fallback never runs. `passed = "" == "PASS"` is False, meaning every empty-verdict response is treated as a fail.
- Impact: Spurious eval failures on a fairly easy LLM mistake.
- Recommendation: `if not verdict:` instead of `if verdict is None:`. Or normalize parsed verdict to `None` when empty.

### 27. `ExecutionTraceMiddleware` event-id dedup keyed on a field producers may not set
- File: `backend/src/agents/middlewares/execution_trace_middleware.py:291-300,136-142`
- Severity: Medium
- Status: Still present.
- Issue: `streamed_event_ids = {event.get("id") ... if isinstance(event.get("id"), str)}`. `_inline_trace_from_runtime_event` passes `inline_trace` through verbatim from the producer; producers that omit `id` won't be deduped.
- Impact: Duplicate SSE events on the trace stream.
- Recommendation: Always assign an id in `_inline_trace_from_runtime_event` (e.g. UUID4 if missing), or drop the dedup attempt entirely.

### 38. `ThreadDataMiddleware._probe_writability` defeats `_lazy_init=True`
- File: `backend/src/agents/middlewares/thread_data_middleware.py:108`
- Severity: Medium
- Status: Still present.
- Issue: `_probe_writability` is called unconditionally and does `os.makedirs(..., exist_ok=True)`. The directories are created every turn regardless of `_lazy_init`. The flag is mostly cosmetic.
- Impact: Lazy-init design intent broken; minor disk traffic.
- Recommendation: Gate the probe behind `_lazy_init=False`, or document that the flag does not affect probe behavior.

### 39. `SteeringMiddleware` mints UUIDs/timestamps at normalize time, not write time
- File: `backend/src/agents/middlewares/steering_middleware.py:28-68`
- Severity: Medium
- Status: Still present.
- Issue: `_legacy_intent` and `_normalize_intents` generate `intent_id`/`created_at` at normalize time. A legacy intent reloaded from a checkpoint gets a new id on every read; downstream persistence/dedup cannot rely on stable ids.
- Impact: Dedup downstream cannot work; intent history is non-deterministic.
- Recommendation: Mint ids/timestamps once at write time and persist them.

### 41. `PlanFollowupMiddleware._has_plan_context` inconsistent truthiness for plan vs todo_graph
- File: `backend/src/agents/middlewares/pro_followup_middleware.py:90-91,122-128`
- Severity: Medium
- Status: Still present.
- Issue: Empty `plan={}` is falsy, but empty `todo_graph={"nodes":[]}` is truthy as a non-empty dict. The check "we have plan context" returns True spuriously when only an empty-nodes graph exists.
- Impact: Background-deepen gating can fire when there's no real plan content.
- Recommendation: Check for either a non-empty `plan` dict OR `len(todo_graph.get("nodes", [])) > 0`, not just key presence.

---

## Low Severity / Nits

### 13. `MemoryMiddleware.after_agent` uses `print()` instead of `logger`
- File: `backend/src/agents/middlewares/memory_middleware.py:166,172`
- Severity: Low
- Status: Still present.
- Issue: `print("MemoryMiddleware: No thread_id in context, skipping ...")` and `print("MemoryMiddleware: No messages in state, skipping ...")`. Pollutes stdout in deployments where stdout is reserved for protocol output.
- Recommendation: Replace with `logger.debug(...)`.

### 15. `MountFolderMiddleware.before_agent` returns the same value on both branches
- File: `backend/src/agents/middlewares/mount_folder_middleware.py:91-94`
- Severity: Low (dead code)
- Status: Still present.
- Issue:
  ```python
  if mode == "plan":
      return {"thread_data": updated_thread_data}
  return {"thread_data": updated_thread_data}
  ```
- Recommendation: Remove the conditional.

### 21. `ActivityTimelineMiddleware` event-type detection is string-coupled to source modules
- File: `backend/src/agents/middlewares/activity_timeline_middleware.py:319-335`
- Severity: Low
- Status: Partially mitigated — fallback table at lines 338-350 covers more sources than before, but still hardcoded and missing entries for summarization, web_search_summary, quality_gate, loop_detection, model_timeout, thread_data, activity_timeline.
- Impact: Renaming a middleware silently drops its events from the timeline; new emitters need to be remembered to add.
- Recommendation: Define event-type registration alongside the emitter (decorator / class attribute) so registration follows the module, not a central table.

### 22. `ViewImageMiddleware._should_inject_image_message` does O(N) substring scan every turn
- File: `backend/src/agents/middlewares/view_image_middleware.py:155-163`
- Severity: Low
- Status: Still present.
- Issue: Scans all messages after the assistant message for the literal `"Here are the images you've viewed"`.
- Impact: Linear in history × image-content size; runs every model call.
- Recommendation: Mark injection in state (`viewed_images_injected_at`) rather than substring-scanning.

### 28. `TitleMiddleware._fallback_title` leaks the `<uploaded_files>` block
- File: `backend/src/agents/middlewares/title_middleware.py:127-131`
- Severity: Low
- Status: Still present; would self-resolve if #20 is fixed.
- Issue: `_fallback_title` doesn't strip the `<uploaded_files>` block prepended by `UploadsMiddleware`. When the LLM call times out and fallback is used, the title can literally be `<uploaded_files>The follo...`.
- Recommendation: Strip the block in `_prepare_generation`. Becomes moot if `UploadsMiddleware` switches to ephemeral injection (#20).

### 31. `TrajectoryMiddleware._truncate` recurses without depth limit
- File: `backend/src/agents/middlewares/trajectory_middleware.py:73-80`
- Severity: Low
- Status: Still present.
- Issue: Recursion through dict/list with no depth cap. A deeply nested or self-referential payload could blow the recursion limit. The trajectory write would fail and be swallowed.
- Recommendation: Add a depth cap (e.g. depth ≥ 10 → `str(value)[:max_chars]`).

### 32. `runtime_events.append_runtime_event` does `deepcopy(event)` on every append
- File: `backend/src/agents/middlewares/runtime_events.py:35`
- Severity: Low
- Status: Still present.
- Issue: deepcopy is expensive for moderately-sized events (tool outputs) and runs inside the lock.
- Recommendation: Document the deep-copy contract for callers; if callers agree not to mutate post-append, drop the deepcopy.

### 33. `AutoresearchMiddleware._handle_autoresearch` surfaces exception messages to the model
- File: `backend/src/agents/middlewares/autoresearch_middleware.py:140-150`
- Severity: Low
- Status: Still present.
- Issue: `except Exception as exc:` returns the exception message inline in the AI response. A `KeyError`/`TypeError` leaks internal types into user-visible text.
- Recommendation: Log the exception, return a generic message. Include `exc.__class__.__name__` only when debug mode is on.

### 34. `MessageSelection._SYNTHETIC_REQUEST_PATTERNS` couples to free-text
- File: `backend/src/agents/middlewares/message_selection.py:24-30`
- Severity: Low
- Status: Still present.
- Issue: Substring match on `"continue the previous plan-mode answer in the background"` ties this module to wording in `pro_followup_middleware.py:191-198`. No test enforces the linkage.
- Recommendation: Use a sentinel marker in the synthetic message content (`<!-- synthetic:plan_followup -->`) and match the marker.

### 36. `ViewImageMiddleware` uses `print(...)` instead of logger
- File: `backend/src/agents/middlewares/view_image_middleware.py:186`
- Severity: Low
- Status: Still present.
- Issue: `print("[ViewImageMiddleware] Injecting image details message ...")`.
- Recommendation: Use module logger.

### 40. `MemoryMiddleware.filter_messages_for_memory` recompiles regex on every call
- File: `backend/src/agents/middlewares/memory_middleware.py:44`
- Severity: Low
- Status: Still present.
- Issue: `_UPLOAD_BLOCK_RE = re.compile(...)` defined inside the function body. Python caches re-compiles internally, but the placement is also misleading vs the docstring's "session-scoped" framing.
- Recommendation: Hoist to module level.

### 42. `MountFolderMiddleware._mount_block` is missing a space between concatenated f-strings
- File: `backend/src/agents/middlewares/mount_folder_middleware.py:48-49`
- Severity: Low
- Status: Still present.
- Issue:
  ```python
  f"A local folder is mounted and accessible at"
  f"virtual path: {VIRTUAL_MOUNT_PATH}",
  ```
  Implicit concatenation produces `"...accessible atvirtual path: ..."`.
- Recommendation: Add the missing space.

### 43. `ExecutionTraceMiddleware._SOURCE_STAGE` missing entries for several real sources
- File: `backend/src/agents/middlewares/execution_trace_middleware.py:40-52`
- Severity: Low
- Status: Still present.
- Issue: Sources `summarization_middleware`, `web_search_summary`, `quality_gate_middleware`, `loop_detection_middleware`, `model_timeout_middleware`, `thread_data_middleware`, `activity_timeline_middleware` aren't mapped; they fall back to `stage="harness"`.
- Impact: Trace UI can't filter by their true stage.
- Recommendation: Add a comprehensive mapping, or compute stage from a declarative class attribute on each middleware.

---

## Resolved Items (dropped from this review)

The following findings from the original audit have been verified as completed
and are no longer part of the active review. Kept here as a short index so
cross-references in the conversational record remain greppable:

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

1. **Per-instance state vs. per-run state**: The major offenders (#5, #6, #7)
   were migrated to a `WeakKeyDictionary`-backed run-scoped store. One
   straggler remains: `TitleMiddleware._generated_title` / `_title_bg_task`
   (#14) should adopt the same helper.

2. **Async fall-throughs to sync**: The critical instance (`EvaluatorMiddleware`,
   #2) is fixed. The CPU-only `aafter_*` → `after_*` shortcuts in
   `ResumeStateMiddleware`, `HooksMiddleware`, `SteeringMiddleware`,
   `SkillDisclosureMiddleware`, `ViewImageMiddleware`, `PlanFollowupMiddleware`
   are accepted as safe (no I/O on those paths). Consider a comment or marker
   to make the invariant explicit so future I/O additions don't silently
   re-introduce the bug.

3. **Stringly-typed event types**: `event`, `decision`, `signal`, `phase` are
   still used interchangeably across middlewares (see
   `execution_trace._runtime_event_to_trace` lines 154-162 which falls back
   through all four). A `TypedDict` or enum would catch typos.

4. **Unbounded module-level state**: `_SKILL_BODY_CACHE` (#24), `_COUNTERS`
   (#25), regex-only-cached patterns (#40), and the `_failed_jobs` cap from
   #3 form a recurring shape — module-level dicts/lists with no eviction.
   A reusable bounded-cache primitive in `agents/middlewares/_caches.py`
   (LRU with TTL) would close several findings at once.

5. **Persistent state pollution from middleware**: `UploadsMiddleware` (#20)
   is the last remaining middleware that *writes back* into the canonical
   message history rather than injecting ephemerally via `wrap_model_call`.
   This is the right architectural fix for #20, #23, and #28
   simultaneously.

---

## Middleware ordering concerns

Based on the registry order documented in `backend/CLAUDE.md` and registry
construction in `work_agent/agent.py`:

1. **UploadsMiddleware before SummarizationMiddleware (correct, but
   problematic):** Uploads injects the `<uploaded_files>` block by mutating
   the last HumanMessage's content (#20). Summarization later may compact
   that modified message, baking the upload metadata permanently into a
   summary snapshot. If a user removes a file, the summary still references
   it forever.

2. **SkillDisclosureMiddleware before SummarizationMiddleware:**
   SkillDisclosureMiddleware injects `HumanMessage(name="active_skills")`.
   SummarizationMiddleware's `_rescue_skill_messages` saves the *most recent*
   skill block. If skills are activated mid-thread and then deactivated, the
   *old* injection from before deactivation is rescued — meaning the agent
   keeps seeing a skill it's no longer using. Combined with the cache in #24,
   deletes are doubly-sticky.

3. **EvaluatorMiddleware vs. WriteFileArtifactMiddleware ordering:**
   EvaluatorMiddleware writes evaluator reports to disk (in `_write_report`)
   and adds them to `handoff_artifacts`. HooksMiddleware's `FileChanged`
   watches `artifacts + handoff_artifacts`. Order isn't obviously broken
   but it's not enforced — if EvaluatorMiddleware moved *after*
   HooksMiddleware, FileChanged would miss evaluator reports.

4. **ToolDisclosureMiddleware before HooksMiddleware:** ToolDisclosure can
   short-circuit with a `[tool_disclosure_blocked]` ToolMessage.
   HooksMiddleware's PreToolUse hook *also* short-circuits. Ordering
   determines whether a blocked tool runs hooks first. Today ToolDisclosure
   runs first (it can prevent hook side effects), which seems correct, but
   isn't called out anywhere.

5. **TrajectoryMiddleware position relative to ResumeStateMiddleware:**
   ResumeStateMiddleware's `after_model` snapshots state to `resume_meta`.
   If TrajectoryMiddleware runs after ResumeStateMiddleware, it sees the
   updated resume_meta in state; before, it sees the previous. The
   trajectory is then inconsistent with the resume marker.

---

## Suggested consolidation (remaining)

1. **Stop mutating `last_message.content` in UploadsMiddleware** — apply
   the ephemeral-injection pattern that MountFolderMiddleware uses (override
   `request.messages` in `wrap_model_call`). Closes #20 and indirectly
   improves #23, #28.

2. **Bounded-cache primitive** — introduce a small
   `agents/middlewares/_caches.py` with LRU+TTL helpers, then migrate
   `_SKILL_BODY_CACHE` (#24) and the `_COUNTERS` dict (#25 — after dropping
   `thread_id` from labels) onto it. Hoist the `_UPLOAD_BLOCK_RE` regex
   (#40) to module level while passing through.

3. **Guarantee tool_call/tool_result coherence across compaction** — fix
   #29 with either a pair-rescue rule in `_partition_messages` or a
   post-build coherence pass. This is the highest-severity remaining item
   after #18.

4. **Move title state onto run-scoped storage** — finish the migration
   started for #5/#7; close #14.

5. **Real pre-validation for write_file_artifact** — split fully-replacing
   write_file from edit-style (`str_replace`/append) at the gate, since
   only the former is genuinely pre-checkable. Document the post-check
   caveat for the latter (#18).

6. **Replace `print()` with logger** in `memory_middleware.py` (#13) and
   `view_image_middleware.py` (#36). Trivial.

7. **Extract common helpers**: `_extract_text` and `_message_type` /
   `_message_name` are reimplemented in `evaluator_middleware`,
   `message_selection`, `title_middleware`, `activity_timeline_middleware`,
   etc. Promote `message_selection.extract_text` as the canonical version.

8. **Trace-event dedup**: always assign an id in
   `_inline_trace_from_runtime_event` (#27), or drop the dedup attempt.

9. **Document the runtime-events contract**: add a header comment to
   `runtime_events.py` listing which middlewares are producers vs consumers.
   The compaction-with-single-consumer issue (#4) is fixed in code; the
   contract should now be documented so the next consumer reads/writes
   correctly without re-deriving it.
