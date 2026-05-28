# Core Middleware — Code Review

## Summary

Reviewed 26 "general" core middleware modules in `backend/src/agents/middlewares/`
end-to-end (with deep-reads on the largest: `summarization_middleware.py`,
`activity_timeline_middleware.py`, `trajectory_middleware.py`,
`execution_trace_middleware.py`). The middleware chain is generally well-
factored — runtime events are properly multiplexed across consumers, summary
guards exist, trajectory IO is fail-safe — but several substantive issues stand
out:

- A per-instance `_autoresearch_triggered` flag and other instance attributes
  are mutated without locks even though middleware instances are reused across
  concurrent threads.
- `runtime_events._compact_runtime_events` requires "at least two active
  consumers" before compacting, which silently leaks unbounded events when only
  one consumer is registered (e.g. activity_timeline without execution_trace).
- `summarization_middleware._fire_hooks` uses a positional-argument detection
  pattern that is fragile and easy to break.
- `pro_followup_middleware` spawns a daemon thread that constructs a brand-new
  `CapyHomeClient` per follow-up — the client is leaked (never closed), and the
  daemon's `asyncio.run` inside it conflicts with `daemon_agent_invoke`'s retry
  logic.
- `trajectory_middleware` writes JSONL through a shared global lock used by
  every flush in the process; that lock plus `fsync` can serialize parallel
  tool calls.
- `evaluator_middleware.aafter_model` calls the *sync* `after_model` which
  performs blocking `model.invoke()` — a clear async-correctness bug.
- `memory_middleware.after_agent` uses `print()` instead of logger.
- `write_file_artifact_middleware` only implements `awrap_tool_call`; sync
  `wrap_tool_call` short-circuits and skips both the quality gate and artifact
  promotion entirely.
- Multiple middlewares mutate `runtime.context` as a dict (the runtime-events
  bus, the activity-timeline `_TOOL_INPUT_BY_TASK_ID_KEY` store) — this assumes
  a per-run mutable context that is not documented and not guaranteed.

Detailed findings below.

---

## Critical Findings

### 1. `WriteFileArtifactMiddleware.wrap_tool_call` skips quality gate and artifact promotion entirely
- File: `backend/src/agents/middlewares/write_file_artifact_middleware.py:249-251`
- Severity: Critical
- Issue: The sync override is `return handler(request)` only; all the quality-
  gate pre-check + artifact promotion logic lives exclusively in
  `awrap_tool_call`. Any sync code path (embedded `CapyHomeClient.chat`,
  test fixtures, daemon flows using `invoke_agent_async`'s fallback) will write
  files without registering them as artifacts and without running the report
  quality gate.
- Impact: Files written via sync path never appear in `state["artifacts"]`,
  so they disappear after page refresh (the exact regression this middleware
  was created to fix per its module docstring). Quality-gate `block_on_failure`
  is silently disabled for those flows.
- Recommendation: Factor the async body into a shared helper and have both
  `wrap_tool_call` and `awrap_tool_call` call it. The pre-check is purely
  CPU-bound so it's safe to share.

### 2. `EvaluatorMiddleware.aafter_model` invokes the sync `after_model` (blocking LLM call from event loop)
- File: `backend/src/agents/middlewares/evaluator_middleware.py:333-335`
- Severity: Critical
- Issue: `aafter_model` is `return self.after_model(state, runtime)`, and
  `after_model` calls `self._evaluate_llm(state)` which calls `model.invoke(prompt)`
  — a synchronous, blocking network call. Inside the event loop, this blocks all
  other concurrent coroutines (including streaming SSE writers, parallel tool
  calls) for the entire duration of the LLM call.
- Impact: Event-loop starvation; cancels look-ahead concurrency gains from
  WebSearchSummaryMiddleware/SubagentLimitMiddleware.
- Recommendation: Add a true async path: `await asyncio.to_thread(self.after_model, ...)`,
  or factor `_evaluate_llm` into sync + async (`model.ainvoke`) and call the
  async variant from `aafter_model`.

### 3. `PlanFollowupMiddleware` daemon thread leaks an entire `CapyHomeClient` per follow-up
- File: `backend/src/agents/middlewares/pro_followup_middleware.py:36-85,199-210`
- Severity: Critical
- Issue: `_run_background_followup` constructs `CapyHomeClient(...)` per
  invocation but never closes it. The client owns checkpointers, model
  factories, and (per `daemon_agent_invoke.py:45-61`) can swap in a transient
  async SQLite checkpointer. On exception, `_failed_jobs` accumulates without
  bound (no eviction policy). The thread is daemon=True so the process can exit
  mid-write.
- Impact: Memory leak proportional to follow-ups per process; resource leak of
  open SQLite handles; daemon thread abrupt termination can corrupt the
  checkpoint database.
- Recommendation: Use a context manager (`with CapyHomeClient(...) as c:`) or
  add explicit close in `finally`. Bound `_failed_jobs` with an LRU cap and TTL.
  Use a managed thread pool with shutdown hooks rather than ad-hoc daemon
  threads.

### 4. `runtime_events._compact_runtime_events` leaks the event queue when only one consumer runs
- File: `backend/src/agents/middlewares/runtime_events.py:38-69`
- Severity: High (verges on critical for long-running threads)
- Issue: The comment says "Keep the queue intact until we have at least two
  active consumers" and the code does
  `if len(valid_cursor_values) < 2: return` (line 51). If only one consumer
  exists (e.g. `activity_timeline` is enabled but `execution_trace` is
  disabled), the queue is *never* compacted and grows for the entire run.
  Worse, `deepcopy(event)` (line 35) increases peak memory.
- Impact: Memory growth O(events per run) when execution_trace or trajectory is
  disabled; quietly silent unless someone profiles.
- Recommendation: When only one consumer exists, the safe compact point is
  that consumer's cursor — there is no "second observer" to wait for. Track
  which consumers have *ever* registered and compact at min(active cursors).

### 5. `AutoresearchMiddleware._autoresearch_triggered` instance flag is not thread-safe
- File: `backend/src/agents/middlewares/autoresearch_middleware.py:98-102,186-196`
- Severity: High
- Issue: `self._autoresearch_triggered: bool` is a per-instance scalar mutated
  from `wrap_model_call` / `awrap_model_call` and read from `after_agent`.
  Middleware instances are typically reused across runs in the same process.
  Two concurrent runs in the same agent (e.g. async tool calls within a run,
  or two threads sharing the agent) would race: run A sets the flag, run B
  reads it in `after_agent`, A's flag is incorrectly observed.
- Impact: Duplicate `record_workspace_activity` writes (cosmetic) OR skipping
  workspace-activity for an unrelated thread (functional: autoresearch
  inactivity guard pauses a job it shouldn't).
- Recommendation: Use a runtime-scoped attribute (write a key into
  `runtime.context`), or a `WeakKeyDictionary[Runtime, bool]`. Never store
  per-run state on `self` for shared middlewares.

---

## High Severity Findings

### 6. `_TOOL_INPUT_BY_TASK_ID_KEY` store in `runtime.context` is never bounded
- File: `backend/src/agents/middlewares/activity_timeline_middleware.py:115-136`
- Severity: High
- Issue: `_remember_tool_input` stores `{task_id: tool_input}` keyed in
  `runtime.context` and `_recall_tool_input` pops by id. But if `tool_call_end`
  is never observed (e.g. a tool returns a `Command` that doesn't propagate
  through `_wrap_tool_call_inner`, a tool errors out, or the cleanup runs in
  the wrong order), entries accumulate. There is no per-run sweep.
- Impact: Slow memory growth per orphaned tool call; unbounded over a long-
  lived thread.
- Recommendation: Track insertion time and evict entries older than N seconds,
  or cap dict size with LRU eviction. At least clear on `after_agent`.

### 7. `runtime.context` is mutated as a dict but is not guaranteed to be one
- File: `backend/src/agents/middlewares/runtime_events.py:25-35`, `activity_timeline_middleware.py:115-126`
- Severity: High
- Issue: Multiple call-sites do `context[KEY] = ...` against
  `runtime.context`. The `Runtime` API in LangGraph documents `context` as a
  read-only typed object in newer versions. Several middlewares already
  defensively check `isinstance(context, dict)`. A future SDK upgrade where
  `context` is a Pydantic model or frozen dict would silently break the entire
  runtime-events bus — and the failure mode is "all middlewares stop seeing
  events" with no traceback because `append_runtime_event` swallows the no-
  context case with a bare `return`.
- Impact: SDK-upgrade time bomb. Today only "works by accident".
- Recommendation: Move the runtime-events bus to a `WeakKeyDictionary[Runtime, dict]`
  module-level store, OR a sentinel attribute set on the runtime object via
  `setattr`. At minimum, raise/log when `context` is not mutable.

### 8. `TrajectoryMiddleware._TRAJECTORY_LOCK` serializes ALL trajectory writes globally
- File: `backend/src/agents/middlewares/trajectory_middleware.py:33-58,127-132`
- Severity: High
- Issue: Single module-level lock guards both the handle cache and every
  `handle.write/flush/fsync`. Multiple concurrent runs (different threads,
  even different agents in the same process) contend on this lock. With
  `cfg.fsync=True`, each event call does a synchronous fsync inside the lock;
  parallel tool calls thus serialize on disk syncs even when writing to
  different files.
- Impact: Latency spikes under concurrency; defeats the parallelism added in
  `awrap_tool_call`/web_search_summary.
- Recommendation: Use one lock per file handle (key by path), not one global
  lock. Or use a background log-writer thread fed from a queue.

### 9. `SummarizationMiddleware._fire_hooks` positional-argument shape detection is brittle
- File: `backend/src/agents/middlewares/summarization_middleware.py:876-895`
- Severity: High
- Issue: `_fire_hooks(*args)` checks `len(args)==3` vs `4` to decide whether
  the first argument is a `state`. Any future signature change or accidental
  keyword call breaks the dispatch silently (the `TypeError` only fires if
  the *positional* arity matches neither). The current single call site at
  line 297/358 always passes 4 args, making the 3-arg branch dead code that
  cannot be reached but cannot be removed (it's a backwards-compat shim).
- Impact: Fragile; future maintainers will not know it's there. If a hook
  expects `state` and it's not passed, hooks silently lose access.
- Recommendation: Make `_fire_hooks` a normal method
  `(self, state, to_summarize, preserved, runtime)` and delete the 3-arg
  branch. If backwards-compat is needed for a public API, gate behind an
  explicit `legacy=True` parameter.

### 10. `ResumeStateMiddleware.aafter_model` re-enters the sync path
- File: `backend/src/agents/middlewares/resume_state_middleware.py:89-90`
- Severity: Medium-High
- Issue: `async def aafter_model: return self.after_model(state, runtime)`. The
  sync method is CPU-only here (no I/O) so this is functionally OK, but the
  pattern repeats across many middlewares (`HooksMiddleware.aafter_model`,
  `PlanFollowupMiddleware.aafter_model`, `SteeringMiddleware.abefore_model`,
  `SkillDisclosureMiddleware.abefore_model`, `ViewImageMiddleware.abefore_model`,
  `EvaluatorMiddleware.aafter_model`). For evaluator this is critical (#2),
  but for others it still means an async caller cannot await `aafter_model`
  while inside a sync section without a context switch.
- Impact: Minor for CPU-only middlewares; combined with #2 for evaluator.
- Recommendation: For CPU-only paths it's fine; explicitly document the
  invariant. For any that touch disk/LLM, route through `asyncio.to_thread`.

### 11. `SummarizationMiddleware` skill-rescue runs after partition without re-checking token budget
- File: `backend/src/agents/middlewares/summarization_middleware.py:585-618`
- Severity: Medium-High
- Issue: `_partition_with_skill_rescue` moves rescued messages into the
  *preserved* set after the base class has already chosen `cutoff_index`.
  Rescue can push the kept-budget arbitrarily over the target. With
  `preserve_recent_skill_tokens=25_000`, a single oversized skill body could
  defeat compaction entirely (preserve a 30k-token skill block while
  compressing the rest).
- Impact: Compaction may produce a "compressed" history that is larger than
  the original threshold; defeats the trigger.
- Recommendation: After rescue, recompute the preserved-set token count and
  log a warning when it exceeds the target. Or apply rescue *before* cutoff
  determination so the budget calculus is correct.

### 12. `WebSearchSummaryMiddleware._run_with_timeout` orphans the worker thread on timeout
- File: `backend/src/agents/middlewares/web_search_summary_middleware.py:92-110`
- Severity: Medium-High
- Issue: `t.join(timeout=timeout); if t.is_alive(): raise TimeoutError(...)`.
  The thread is *not* cancelled — it continues running in the background,
  potentially completing its LLM call long after the timeout. Multiple
  consecutive timeouts spawn zombie threads each holding an LLM client.
- Impact: Resource leak proportional to timeout rate; can exhaust the LLM
  client connection pool.
- Recommendation: At minimum, name the threads and emit a metric.
  Realistically the sync path should be removed for async callers (it's only
  reachable from the legacy sync flow now).

### 13. `MemoryMiddleware.after_agent` uses `print()` instead of `logger`
- File: `backend/src/agents/middlewares/memory_middleware.py:166,172`
- Severity: Medium
- Issue: `print("MemoryMiddleware: No thread_id in context, skipping memory update")`
  and `print("MemoryMiddleware: No messages in state, skipping memory update")`.
  These should be `logger.debug` or `logger.info`. They pollute stdout in
  production deployments where stdout is reserved for protocol output.
- Impact: Log noise; can corrupt stdout-based pipes.
- Recommendation: Replace with `logger.debug(...)` (likely they're not
  actionable, just informational).

### 14. `TitleMiddleware` background task is per-instance; cross-run leakage if same agent reused
- File: `backend/src/agents/middlewares/title_middleware.py:73-75,213,232-244`
- Severity: Medium
- Issue: `self._generated_title` and `self._title_bg_task` are instance attrs.
  If two runs of the same middleware overlap (rare but possible in concurrent
  thread setups), the second `aafter_model` resets the title from the first
  before it's consumed by `aafter_agent`. Also if `aafter_agent` is never
  reached (e.g. process kill), the background task continues running with a
  dangling closure over `state`.
- Impact: Title-update race; rare but real.
- Recommendation: Key by run_id in a dict keyed off runtime context. Same
  recommendation as #5.

### 15. `MountFolderMiddleware.before_agent` returns the same value on both branches
- File: `backend/src/agents/middlewares/mount_folder_middleware.py:91-94`
- Severity: Low (logic bug / dead branch)
- Issue:
  ```python
  if mode == "plan":
      return {"thread_data": updated_thread_data}
  return {"thread_data": updated_thread_data}
  ```
  Both branches are identical; the `if mode == "plan"` is dead. The intent
  reads like plan-mode used to return something different but the code never
  diverged.
- Impact: Confusing dead code; misleads future readers about plan/work split.
- Recommendation: Remove the conditional; just `return {"thread_data": ...}`.

### 16. `EvaluatorMiddleware` `_pre_verify` reports `state.get("messages")[-1]` as the latest AI when it may be a HumanMessage
- File: `backend/src/agents/middlewares/evaluator_middleware.py:162-164`
- Severity: Medium
- Issue: `latest_ai = _extract_text(getattr(messages[-1], "content", ""))`
  — if the last message is an injected `HumanMessage(name="evaluator_feedback",...)`
  from a prior eval cycle, the "latest_ai" snippet length check (line 164,
  `len(latest_ai.strip()) > 400`) evaluates against synthetic user content.
- Impact: Wrong verdict on retry loops; the draft-mode guard may trigger from
  evaluator's own feedback echo.
- Recommendation: Walk backwards to find the last actual AI message
  (use `latest_real_ai_answer` from `message_selection.py`).

### 17. `HooksMiddleware.after_model` triggers FileChanged hook even when no change occurred
- File: `backend/src/agents/middlewares/hooks_middleware.py:163-174`
- Severity: Medium
- Issue: When `added` is empty but `current_files != observed_files`, the
  function falls through to writing `hooks_state` without invoking hooks but
  *unnecessarily updates state* — this triggers a checkpoint write. More
  importantly, if a file is *removed* from artifacts (current < observed), no
  hook fires; symmetric "file removed" events are missing.
- Impact: Missed FileRemoved events; one extra checkpoint write per turn when
  observed != current but added is empty.
- Recommendation: Emit FileRemoved for `observed - current`, and only update
  state when `current_files != observed_files`.

### 18. `WriteFileArtifactMiddleware._quality_gate_precheck` reads file from disk while LLM has only proposed it
- File: `backend/src/agents/middlewares/write_file_artifact_middleware.py:49-66, 215-239`
- Severity: Medium
- Issue: Postcheck reads `host_path.read_text(...)` to validate the resulting
  file content for `str_replace`/append. This happens *after* the tool has
  already executed and written to disk. If quality gate fails, the tool's
  effect is not rolled back — only a warning message is added. The contract
  "block_on_failure" is a lie for append/str_replace.
- Impact: Misleading config; users expect block-on-failure to prevent the
  bad write but it only blocks future calls.
- Recommendation: Document this caveat explicitly. Or read existing file
  content + apply edit logic before invoking the handler. (Hard for str_replace
  since the edit semantics live in the tool.)

---

## Medium Severity Findings

### 19. `WebSearchSummaryMiddleware` summarization prompt uses naive `.replace("{query}", ...)`
- File: `backend/src/agents/middlewares/web_search_summary_middleware.py:146-149`
- Severity: Medium
- Issue: `prompt = _SUMMARY_PROMPT_TEMPLATE.replace("{query}", query).replace("{raw_content}", content)`.
  If a search result contains the literal string `{raw_content}` (a JSON dump,
  a template, etc.), the second `.replace` replaces it. Prompt injection
  surface: a malicious site can include `{raw_content}` in its content and
  influence the second replacement to inject content into the assistant
  prompt section.
- Impact: Prompt injection vector via web_search results.
- Recommendation: Use `str.format` with KeyError-safe substitution, or use
  unambiguous markers like `<<RAW_CONTENT_PLACEHOLDER_UUID>>`.

### 20. `UploadsMiddleware` rewrites the last HumanMessage every turn the user uploads
- File: `backend/src/agents/middlewares/uploads_middleware.py:193-204`
- Severity: Medium
- Issue: `UploadsMiddleware.before_agent` creates a brand-new `HumanMessage(...)`
  with prepended `<uploaded_files>` content but keeps `id=last_message.id`.
  LangGraph's message reducer keys by id and replaces. However the new message
  string is now embedded into the conversation history *and persists*
  forever — every future summarization sees the file list, even if the user
  has deleted the files. Memory middleware (`memory_middleware.py:44-71`)
  has special handling to strip the block but only when filtering for memory
  storage, not for in-context use.
- Impact: Token bloat in long sessions; stale file paths linger.
- Recommendation: Inject `<uploaded_files>` ephemerally via `wrap_model_call`
  (override request messages) rather than mutating thread state. The same
  pattern that `MountFolderMiddleware._with_ephemeral_mount_context` uses.

### 21. `ActivityTimelineMiddleware` event-type detection is string-coupled to source modules
- File: `backend/src/agents/middlewares/activity_timeline_middleware.py:319-335`
- Severity: Medium
- Issue: Fallback line generation depends on a hardcoded set of `source`
  module names. Renaming a middleware (e.g. `evaluator_middleware` →
  something else) silently drops its events from the activity timeline.
- Impact: UX regression risk on refactor; no test enforces the contract.
- Recommendation: Add a registry decorator or central constant; add a test
  that asserts every middleware that emits runtime events is registered here
  too.

### 22. `ViewImageMiddleware._should_inject_image_message` does O(N) substring scan every turn
- File: `backend/src/agents/middlewares/view_image_middleware.py:155-163`
- Severity: Medium
- Issue: Detects already-injected by scanning all messages after the
  assistant message for the literal string `"Here are the images you've viewed"`.
  Cost is linear in history × image_content_size; for a 200-turn session with
  images, this runs every model call.
- Impact: Performance degradation on long image-heavy threads.
- Recommendation: Mark injection in state (`viewed_images_injected_at`)
  rather than substring scanning.

### 23. `SummarizationMiddleware` deterministic fallback regex `/mnt/user-data/...` may pull stale paths
- File: `backend/src/agents/middlewares/summarization_middleware.py:453-457`
- Severity: Medium
- Issue: The fallback summarizer scrapes file paths from raw message content
  using `re.finditer(r"/mnt/user-data/[^\s)`'\"]+", content)`. Paths that
  appear only in old tool errors or transient logs would be elevated into
  the "Files Referenced" section, misleading future reasoning.
- Impact: Low — fallback path is rare.
- Recommendation: Filter to artifacts actually in `state["artifacts"]` or
  intersect with the regex.

### 24. `SkillDisclosureMiddleware` cache never evicts
- File: `backend/src/agents/middlewares/skill_disclosure_middleware.py:26-45`
- Severity: Medium
- Issue: `_SKILL_BODY_CACHE: dict[str, tuple[float, str]]` is a module-level
  dict that grows with every distinct skill file ever read. Deleted/renamed
  skills are never removed; mtime checks only invalidate stale entries, not
  evict.
- Impact: Slow memory growth for installations with many short-lived custom
  skills.
- Recommendation: Use `functools.lru_cache(maxsize=64)` or a bounded
  `OrderedDict`.

### 25. `MetricsMiddleware._COUNTERS` has unbounded cardinality
- File: `backend/src/agents/middlewares/metrics_middleware.py:22-31`
- Severity: Medium
- Issue: Label key includes `thread_id` (line 96). Every thread creates a new
  counter key for every metric name; counters are never reset and never
  expired. Long-running deployments accumulate one bucket per thread × tool ×
  endpoint forever.
- Impact: Memory growth in `_COUNTERS` proportional to thread count; render
  cost grows linearly.
- Recommendation: Drop `thread_id` from labels (high-cardinality anti-pattern
  in Prometheus). Aggregate at the endpoint level. If per-thread metrics are
  needed, expose them via a separate per-run scratchpad.

### 26. `ThreadDataMiddleware` falls back to a random UUID thread_id, masking config bugs
- File: `backend/src/agents/middlewares/thread_data_middleware.py:79-83`
- Severity: Medium
- Issue: When `thread_id is None`, generates `"test-" + uuid4()`. This means
  a production misconfiguration that drops thread_id is silently absorbed —
  every turn creates a brand-new disposable thread directory. There's no
  warning log.
- Impact: Data loss looks like "thread state didn't persist"; debugging is
  hard.
- Recommendation: Log a warning when thread_id is missing. Make this only
  happen when an env var (`CAPYHOME_TEST_MODE=1`) is set.

### 27. `ExecutionTraceMiddleware` event id deduplication uses string `id` lookup but the inline trace path doesn't always set one
- File: `backend/src/agents/middlewares/execution_trace_middleware.py:291-300`
- Severity: Medium
- Issue: `streamed_event_ids = {event.get("id") ... if isinstance(event.get("id"), str)}`.
  Per `_inline_trace_from_runtime_event` (line 136-142), `inline_trace` is
  passed through verbatim from the producer. Producers that omit `id` won't
  be deduped, leading to double streaming.
- Impact: Duplicate SSE events on the trace stream.
- Recommendation: Always assign an id in `_inline_trace_from_runtime_event`
  if missing.

### 28. `TitleMiddleware._fallback_title` mixes plain string and `_extract_text` outputs inconsistently
- File: `backend/src/agents/middlewares/title_middleware.py:127-131`
- Severity: Low-Medium
- Issue: `if len(user_msg) > fallback_chars:` — `user_msg` was already
  truncated to 500 chars via `_prepare_generation`. The 500-char truncation
  and the 50-char fallback cap interact: the title is taken from the first
  50 chars of an already-truncated string, fine. But `_fallback_title`
  doesn't strip the `<uploaded_files>` block that may be at the start of
  the user message thanks to `UploadsMiddleware`. The fallback title will
  literally be `<uploaded_files>The follo...`.
- Impact: Title generation regression when uploads are present and the LLM
  call times out (fallback is used).
- Recommendation: Strip `<uploaded_files>` block in `_prepare_generation`
  before passing to the prompt or fallback.

### 29. `SummarizationMiddleware` does not preserve `tool_call_id` linkage when removing messages
- File: `backend/src/agents/middlewares/summarization_middleware.py:309-323`
- Severity: Medium
- Issue: `[RemoveMessage(id=REMOVE_ALL_MESSAGES), *new_messages, *preserved]`.
  Preserved messages may include AIMessages with `tool_calls` whose matching
  ToolMessage responses are in the `to_summarize` set. After compaction, an
  AIMessage with `tool_calls[X]` survives but no ToolMessage with id X
  follows — this is an Anthropic API hard error (`tool_use_ids must have
  matching tool_result blocks`).
- Impact: Model API errors after compaction if tool_call/result pairs split
  across the cutoff.
- Recommendation: `_partition_messages` and rescue logic must keep AI+Tool
  pairs together. (The base class may already do this — verify; if not, add
  the invariant as a post-condition assertion.)

### 30. `HooksMiddleware._run_command` runs `shell=True` with hook-config strings as cwd
- File: `backend/src/agents/middlewares/hooks_middleware.py:64-74`
- Severity: Medium (security review)
- Issue: `cwd=str(cwd) if cwd else None` where `cwd` comes from
  `thread_data.workspace_path` — which is computed from `thread_id`. A
  thread_id like `..; rm -rf $HOME` cannot reach `cwd` since it's joined via
  `Path()`, but `shell=True` means `hook.command` is run via shell. Hook
  commands are loaded from config so trust is at config-author level — OK as
  long as configs are not user-editable through unprivileged endpoints.
- Impact: Config-injection if config is ever sourced from untrusted input.
- Recommendation: Document hook commands as trusted; consider `shlex.split`
  + `shell=False` where possible.

### 31. `TrajectoryMiddleware._truncate` recurses without depth limit
- File: `backend/src/agents/middlewares/trajectory_middleware.py:73-80`
- Severity: Low-Medium
- Issue: Recursive truncation through dict/list. A deeply nested payload or
  a self-referential dict will blow the recursion limit / hang.
- Impact: Pathological payload → trajectory write fails → swallowed; not
  catastrophic but obscures debugging.
- Recommendation: Add depth cap (e.g. depth >= 10 → str(value)[:max_chars]).

---

## Low Severity / Nits

### 32. `runtime_events.append_runtime_event` does `deepcopy(event)` on every append
- File: `backend/src/agents/middlewares/runtime_events.py:35`
- Issue: deepcopy is expensive for moderately-sized events (tool outputs).
  The lock is held across deepcopy. Combined with #4, peak memory and lock
  contention both suffer.
- Recommendation: Document the deep-copy contract for callers. If callers
  agree not to mutate events post-append, drop the deepcopy.

### 33. `AutoresearchMiddleware._handle_autoresearch` swallows all exceptions and surfaces them to the model
- File: `backend/src/agents/middlewares/autoresearch_middleware.py:140-150`
- Issue: `except Exception as exc:` returns the exception message inline in
  the AI response. A `KeyError` or `TypeError` would leak internal types to
  the user.
- Recommendation: Log the exception and return a generic message; include
  `exc.__class__.__name__` only when in debug mode.

### 34. `MessageSelection._SYNTHETIC_REQUEST_PATTERNS` couples to free-text
- File: `backend/src/agents/middlewares/message_selection.py:24-30`
- Issue: Pattern strings like `"continue the previous plan-mode answer in the background"`
  are matched as substrings. Any future change to that prompt text in
  `pro_followup_middleware.py:191-198` requires a parallel edit here. There's
  no test linking the two.
- Recommendation: Use a sentinel marker in the synthetic message content
  (e.g. `<!-- synthetic:plan_followup -->`) and match the marker.

### 35. `EvaluatorMiddleware._evaluate_llm` parses `VERDICT:` line but the first-line fallback overwrites it incorrectly
- File: `backend/src/agents/middlewares/evaluator_middleware.py:233-245`
- Issue: `if verdict is None:` block — if `verdict` is parsed as empty
  string (`VERDICT:` with no value), the fallback isn't triggered because
  `verdict` is `""`, not `None`. `passed = "" == "PASS"` is False.
- Recommendation: `if not verdict:` instead of `if verdict is None:`.

### 36. `ViewImageMiddleware` `print(...)` call instead of logger
- File: `backend/src/agents/middlewares/view_image_middleware.py:186`
- Issue: `print("[ViewImageMiddleware] Injecting image details message ...")`.
- Recommendation: Use module logger.

### 37. `WriteFileArtifactMiddleware` doesn't handle `Command` returns from inner handler
- File: `backend/src/agents/middlewares/write_file_artifact_middleware.py:198-210`
- Issue: `if not isinstance(result, ToolMessage): return result` short-
  circuits on `Command` results, so write_file/str_replace tools that
  themselves return `Command` (none currently, but they could) skip artifact
  promotion silently.
- Recommendation: Extract content from `Command` updates too.

### 38. `ThreadDataMiddleware._probe_writability` calls `os.makedirs(... exist_ok=True)` even when `_lazy_init=True`
- File: `backend/src/agents/middlewares/thread_data_middleware.py:108`
- Issue: `_probe_writability` is called unconditionally and does
  `os.makedirs(...)`. This defeats the `lazy_init=True` optimization — the
  directories are created every turn anyway. The `_lazy_init` flag is mostly
  cosmetic.
- Recommendation: Either gate the probe behind `_lazy_init=False` or document
  that the probe always creates dirs.

### 39. `SteeringMiddleware._legacy_intent` and `_normalize_intents` mint UUIDs and timestamps on every read
- File: `backend/src/agents/middlewares/steering_middleware.py:28-68`
- Issue: Generating `intent_id`/`created_at` at normalize time means a
  legacy-only intent reloaded from a checkpoint gets a *new* id on every
  read. Persistence/dedup downstream cannot rely on ids.
- Recommendation: Mint ids/timestamps once at write time, not on every
  load.

### 40. `MemoryMiddleware` `filter_messages_for_memory` recompiles regex on every call
- File: `backend/src/agents/middlewares/memory_middleware.py:44`
- Issue: `_UPLOAD_BLOCK_RE = re.compile(...)` inside the function body. The
  function is called per memory-flush; while `re.compile` does cache, moving
  it to module level is cleaner and matches the docstring's claim about
  being session-scoped.
- Recommendation: Hoist to module-level constant.

### 41. `PlanFollowupMiddleware._has_plan_context` returns True if either plan OR todo_graph exists
- File: `backend/src/agents/middlewares/pro_followup_middleware.py:90-91`
- Issue: For background-deepen gating (line 122-128), an empty `plan={}` is
  falsy but a non-empty `todo_graph={"nodes":[]}` is truthy. The intent
  ("we have plan context") is ambiguous when only one is present.
- Recommendation: Require either a non-empty plan dict OR a non-empty
  todo_graph nodes list, not just presence of the key.

### 42. `MountFolderMiddleware._mount_block` has a missing space between strings (concatenation bug)
- File: `backend/src/agents/middlewares/mount_folder_middleware.py:48-49`
- Issue:
  ```python
  f"A local folder is mounted and accessible at"
  f"virtual path: {VIRTUAL_MOUNT_PATH}",
  ```
  These two implicit-concatenated f-strings become `"A local folder is mounted and accessible atvirtual path: ..."` — missing the space.
- Recommendation: Add a trailing space to the first string or join with `" "`.

### 43. `ExecutionTraceMiddleware._SOURCE_STAGE` missing entries for several real sources
- File: `backend/src/agents/middlewares/execution_trace_middleware.py:40-52`
- Issue: Sources like `summarization_middleware`, `web_search_summary`,
  `quality_gate_middleware`, `loop_detection_middleware`, `model_timeout_middleware`,
  `thread_data_middleware`, `activity_timeline_middleware` are *not* in the
  map. They fall back to `stage="harness"` — fine, but the trace UI cannot
  filter by their true stage.
- Recommendation: Add a comprehensive mapping or compute stage from a
  declarative attribute on each middleware.

---

## Cross-cutting observations

1. **Per-instance state vs. per-run state**: Many middlewares store run-
   scoped state on `self` (`AutoresearchMiddleware._autoresearch_triggered`,
   `TitleMiddleware._generated_title`, `_title_bg_task`,
   `SummarizationMiddleware._last_*`, `_summary_state_snapshot`). When
   middleware instances are reused across runs (the common case), these
   create race conditions and cross-run leakage. A standardized
   "RuntimeScoped[T]" helper (keyed off `runtime` identity) would fix the
   whole class.

2. **Async fall-throughs to sync**: At least six middlewares define
   `aafter_*` as `return self.after_*(...)`. For CPU-only paths this is
   correct; for `EvaluatorMiddleware` (which does `model.invoke`) this is a
   functional bug (#2). Adopt a lint rule: an `a*` override that calls a
   sync method that does I/O must wrap in `asyncio.to_thread`.

3. **Stringly-typed event types**: `event`, `decision`, `signal`, `phase`
   are all used interchangeably across middlewares (see
   `execution_trace._runtime_event_to_trace` lines 154-162 which falls back
   through all four). A `TypedDict` or enum would catch typos.

4. **`runtime.context` mutation**: As noted in #7, mutating `runtime.context`
   is widespread. This needs a documented contract or a refactor to a
   module-level `WeakKeyDictionary`. The `_phase_a_runtime_events` and
   `_activity_tool_input_by_task_id` prefixes already feel like
   namespace-collision avoidance hacks.

5. **Hooks/disclosure don't sanitize tool_name**: `wrap_tool_call` reads
   `request.tool_call.get("name")` directly into log lines and shell
   `fnmatch` patterns without validation. A malicious tool name like
   `*; rm -rf $HOME` couldn't reach `subprocess` (the hook *command* is
   trusted) but could log-inject. Low priority but worth tracking.

6. **No backpressure on background daemon threads**:
   `PlanFollowupMiddleware` and `WebSearchSummaryMiddleware._run_with_timeout`
   both spawn `threading.Thread(daemon=True)` directly with no pool limit.
   Under a burst of follow-ups, the process could spawn many concurrent
   `CapyHomeClient`s, each with its own model pool. A shared
   `ThreadPoolExecutor` with `max_workers` is the right primitive.

---

## Middleware ordering concerns

Based on the registry order documented in `backend/CLAUDE.md` and registry
construction in `work_agent/agent.py`:

1. **UploadsMiddleware before SummarizationMiddleware (correct, but problematic):**
   Uploads injects the `<uploaded_files>` block by mutating the last
   HumanMessage's content (#20). Summarization later may compact that
   modified message, baking the upload metadata permanently into a summary
   snapshot. If a user removes a file, the summary still references it
   forever.

2. **SkillDisclosureMiddleware before SummarizationMiddleware:**
   SkillDisclosureMiddleware injects `HumanMessage(name="active_skills")`.
   SummarizationMiddleware's `_rescue_skill_messages` saves the *most
   recent* skill block. If skills are activated mid-thread and then
   deactivated, the *old* injection from before deactivation is rescued —
   meaning the agent keeps seeing a skill it's no longer actively using.
   Combined with the cache in #24, deletes are doubly-sticky.

3. **EvaluatorMiddleware vs. WriteFileArtifactMiddleware ordering:**
   EvaluatorMiddleware writes evaluator reports to disk (in
   `_write_report`) and adds them to `handoff_artifacts`. HooksMiddleware's
   `FileChanged` watches `artifacts + handoff_artifacts`. Order isn't
   obviously broken but it's not enforced — if EvaluatorMiddleware moved
   *after* HooksMiddleware, FileChanged would miss evaluator reports.

4. **ActivityTimelineMiddleware and ExecutionTraceMiddleware both drain
   runtime events as independent consumers:**
   `_compact_runtime_events` requires "≥2 consumers" to compact (#4). If
   ExecutionTraceMiddleware is ever disabled (via config), the queue leaks.
   This is an *invariant of the chain shape* that isn't documented or
   tested.

5. **ToolDisclosureMiddleware before HooksMiddleware:**
   ToolDisclosure can short-circuit with a `[tool_disclosure_blocked]`
   ToolMessage. HooksMiddleware's PreToolUse hook *also* short-circuits.
   Ordering determines whether a blocked tool runs hooks first. Today
   ToolDisclosure runs first (it can prevent hook side effects), which
   seems correct, but isn't called out anywhere.

6. **TrajectoryMiddleware position relative to ResumeStateMiddleware:**
   ResumeStateMiddleware's `after_model` snapshots state to `resume_meta`.
   If TrajectoryMiddleware runs after ResumeStateMiddleware, it sees the
   updated resume_meta in state; before, it sees the previous. The
   trajectory is then inconsistent with the resume marker.

---

## Suggested consolidation

1. **Merge `WriteFileArtifactMiddleware` sync + async paths** (#1). Trivial
   correctness fix.

2. **Centralize per-run state**: Introduce a small
   `src/agents/middlewares/run_scoped.py` with
   `WeakKeyDictionary[Runtime, dict]` helpers. Migrate
   `_autoresearch_triggered`, `_generated_title`, `_title_bg_task`,
   `_last_trigger_*`, `_last_summary_*`, `_summary_state_snapshot`, and the
   `_activity_tool_input_by_task_id` store onto it. Eliminates findings
   #5, #6, #7, #14, and parts of #11.

3. **Replace the ad-hoc `_run_with_timeout` and daemon-thread followup with
   a shared `ThreadPoolExecutor`** owned by `src/agents/background.py`,
   bounded by config. Fixes #3, #12, observation #6.

4. **Stop mutating `last_message.content`** in UploadsMiddleware. Apply
   the same ephemeral-injection pattern that MountFolderMiddleware uses
   (override `request.messages` in `wrap_model_call`). Fixes #20.

5. **Standardize `aafter_*` overrides**: Either delete them (LangGraph
   falls back to sync) or wrap with `asyncio.to_thread`. Auditing each
   middleware once is cheaper than re-discovering #2 across many files.

6. **Per-file trajectory locks**: Refactor `_TRAJECTORY_LOCK` to a per-file
   lock map. Fixes #8.

7. **Bound the in-memory metrics counter**: Drop `thread_id` from labels.
   Fixes #25.

8. **Consider extracting common helpers**: `_extract_text` and
   `_message_type`/`_message_name` are reimplemented in
   `evaluator_middleware`, `message_selection`, `title_middleware`,
   `activity_timeline_middleware`, etc. Promote `message_selection.extract_text`
   as the canonical version.

9. **Trace-event dedup**: The id-set dedup in
   `ExecutionTraceMiddleware.after_model` (lines 291-300) is buggy
   without a guaranteed id (#27). Either always assign one in
   `_inline_trace_from_runtime_event` or drop the dedup attempt.

10. **Document the runtime-events contract**: Add a header comment to
    `runtime_events.py` listing which middlewares are producers vs
    consumers, and crucially that the queue is leaked when there is only
    one active consumer. Better still, fix the compaction rule.
