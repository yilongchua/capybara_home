# Guardrails — Code Review

## Summary

CapyHome's guardrail layer is a thoughtfully constructed defense-in-depth stack: declarative permissions, dual-layer loop detection, endpoint-aware subagent scheduling, a recursion-budget evaluator pivot, a per-stage model timeout, retry policy, a web-search circuit breaker, dangling-tool-call repair, and a first-turn execution gate. The middlewares clearly reflect lessons learned in production (the comments name specific runs like `run-c0425b71bd` and `thread-cd90decb`).

That said, several guardrails have **bypass vectors that an adversarial or merely-creative LLM can hit by accident**, and a few have **shared mutable state that is not safe under parallel requests**. The most important gaps are:

1. The TODO-bypass regex in `PermissionMiddleware` is a brittle string filter that the LLM can sidestep by reformulation, while the actual `write_todos` enforcement happens only at the policy boundary.
2. `_default_mode == "auto"` causes the permission middleware to silently **default-allow** any unmatched tool. Combined with `_serialize_tool_args` projecting dicts to one of six keys, an attacker-controlled JSON shape can evade `tool(arg-pattern)` deny rules entirely.
3. `LoopDetectionMiddleware` keeps process-global state and resets counters when "the latest real user message" changes — an LLM that injects a `HumanMessage` (or that a middleware injects one without a `name`) can reset the loop counters mid-run.
4. `WebSearchCircuitBreakerMiddleware` decides "failure" purely by the ToolMessage content; the circuit can be reset by interleaving any single successful-looking ToolMessage. It also reads `_FAILURE_THRESHOLD = 2` as a module constant — not configurable, not testable in isolation.
5. `RecursionBudgetPivotMiddleware` measures `step` as `len(messages) // 2`, which is a coarse proxy and can underestimate, never firing the pivot in tool-heavy runs.
6. `ModelTimeoutMiddleware` has **no sync timeout** — the embedded `CapyHomeClient` path is unguarded.
7. `RetryPolicyMiddleware` retries by re-invoking `handler(request)` synchronously without checking idempotency of the failed call; `rule.idempotent` is logged but **never checked**.
8. `SubagentLimitMiddleware` blindly prepends previously-deferred tool calls onto the next AI message, but the IDs originate from a different (rewritten) AI message — if the LLM resubmits with the same description, both copies can execute.

There is no central registry of "what each guardrail asserts and what it doesn't" — each one defends a single failure mode in isolation, with subtle interactions that can either neutralise one another or compound into double-counting. See "Defense-in-depth gaps" and "Recommendations for consolidation" at the bottom.

---

## Bypass Vulnerabilities

These are the most important findings. Every item below is something the LLM can do (intentionally or by accident) that defeats a guardrail without exploiting a memory-corruption-style bug.

### B1. Permission middleware: `_serialize_tool_args` only inspects 6 keys, then JSON-dumps

- File: `backend/src/agents/middlewares/permission_middleware.py:48-57`
- Mechanism: `_serialize_tool_args` walks the keys `("command", "path", "file_path", "query", "prompt", "description")` and returns the first non-empty string value. If a tool's dangerous argument lives under a different key, the rule never matches.
- Bypass: A `deny: bash(*rm -rf*)` rule works only because `bash` has a `command` field. A community tool such as `image_search(prompt=...)` will match `prompt`; but `aio_sandbox(shell=...)`, `browser_automation(url=...)`, or `task(subagent_type=..., prompt=...)` will pick `prompt` (and miss `subagent_type`/`url`). MCP tools are entirely uncoordinated and will fall back to the JSON-dump branch.
- Impact: Argument-targeted deny/ask rules are silently inert for any tool whose payload is not one of these six keys. `default_mode="auto"` then allows the call.
- Recommendation: Either (a) always JSON-dump the whole args dict and match against that, or (b) document the supported keys per tool and emit a startup warning when a rule's `arg_pattern` cannot possibly match the tool's signature.

### B2. Permission middleware: TODO bypass detection is regex-only and easy to reword

- File: `backend/src/agents/middlewares/permission_middleware.py:22-25,138-143`
- Mechanism: `_TODO_BYPASS_RE` matches `(mark|set|update) ... todo-N ... (completed|done)` within 40 characters in a `bash` command. The LLM can write `sed -i 's/in_progress/done/' todos.json` or `python -c "open('todos.json','a').write('todo-3: finished')"` or use `awk`, `python -m json.tool`, etc.
- Bypass: Trivial — anything that doesn't say "mark/set/update todo-N completed" in those exact tokens within 40 chars goes through. Also `bash` is the only matched tool name; an LLM can use `write_file` to overwrite the todos JSON directly and the regex never fires.
- Impact: The "todos can only be modified through write_todos" invariant is defended only against the most obvious shell incantation. Plan execution gate, todo_dag, and evaluator middlewares can be desynchronized from disk.
- Recommendation: Treat `write_todos` as the only writer at the *tool registration* layer — i.e., make the todos JSON file path unwritable to `write_file`/`str_replace`/`bash` (sandbox-level mount restriction). Regex-based content filters on LLM output are not a security boundary.

### B3. Permission middleware: `ask_user_for_clarification` is hard-coded allow

- File: `backend/src/agents/middlewares/permission_middleware.py:118-119`
- Mechanism: `_resolve_decision` returns `"allow"` unconditionally for `ask_user_for_clarification`, bypassing deny/ask rules. Combined with `ClarificationMiddleware` (which interrupts and exposes the message to the user), the LLM can use this tool to deliver any text it wants directly to the user UI even when other tools are denied/asked.
- Bypass: An LLM that wants to surface unsanitized output, leak a prompt, or render arbitrary markdown can call `ask_user_for_clarification` with the payload as the question text. There is no length cap on the question, no content filter, no "this is a real question" classifier.
- Impact: Tier-skipping of the permission layer. Whether this matters depends on whether ask_user_for_clarification content is rendered raw in the UI (the README implies it is).
- Recommendation: Either subject this tool to deny rules (rare case the operator wants to disable clarification), or apply minimal sanitization (length cap, no embedded tool-result fingerprints) before it reaches the UI.

### B4. Loop detection: counter reset triggered by any human message without a `name`

- File: `backend/src/agents/middlewares/loop_detection_middleware.py:188-200, 285-290`
- Mechanism: `_latest_real_user_signature` walks messages in reverse and treats *any* `HumanMessage` whose `.name` is falsy as a "real user message". When the signature changes, `_track_and_check` resets `_history`, `_warned`, `_tool_freq`, `_tool_freq_warned` for that thread.
- Bypass: Several middlewares already inject `HumanMessage` instances mid-run; only some of them set `name=`. Verified injectors that **do** set name: `recursion_pivot_steering`, `recursion_pivot_warning`, `task_deferred`. The `LoopDetectionMiddleware` itself injects an *unnamed* `HumanMessage(content=warning)` at line 407 — but it does so *after* the loop counter check, so it can't reset itself in the same turn. However any other guardrail or future middleware that injects an unnamed HumanMessage will silently wipe the loop counters. An LLM that learns to emit `HumanMessage`-shaped content via a tool result could exploit this if state ever round-trips through serialization.
- Impact: Loop counters can be reset by adjacent middleware injections, allowing a genuinely looping agent to run past the hard limit.
- Recommendation: Use a positive marker (e.g. `state["user_turn_id"]` set by the entrypoint) rather than the negative "looks like a real user message" check; document that *every* injected HumanMessage must carry `name=`.

### B5. Loop detection: `_stable_key` salient-field projection collapses different reads to the same hash

- File: `backend/src/agents/middlewares/loop_detection_middleware.py:128-158`
- Mechanism: For non-read_file/write_file tools, the hash is computed over `("path", "url", "query", "command", "pattern", "glob", "cmd")` only. Any tool whose distinguishing argument lives under a different key (subagent `prompt`, `description`, MCP `args`) will hash to the same key when called repeatedly.
- Bypass: A legitimately different `task(prompt="A", description="...")` vs `task(prompt="B", description="...")` calls will have *no* salient field projection match — they fall back to `fallback`, which `_normalize_args` only sets for non-dict args. For a dict args call with none of the salient fields, the projection is `{}`, then `stable` is empty, then `fallback` is `None`, then we land in the `else` branch and dump the *whole* args dict. OK for that path.
- However: `read_file` buckets by 200-line windows. If the LLM repeatedly reads `file.py` lines `1-100`, `101-200`, `201-300`, ..., each is in a different bucket and the hash differs every time. So Layer 1 never fires, even on a 50-file sequential read. Layer 2's `tool_freq` catches it eventually at 30/50 calls, but that's late and only fires when no skill has `workflow=True`.
- Impact: Hash-based detection is effectively disabled for sequential reads, which is the most common loop pattern in code exploration.
- Recommendation: Either drop the 200-line bucketing (was added to suppress false positives, but creates false negatives) or add a separate "same file, sequential lines" detector.

### B6. Web search circuit breaker: any non-`web_search` ToolMessage erases the failure trail

- File: `backend/src/agents/middlewares/web_search_circuit_breaker_middleware.py:56-79`
- Mechanism: `_failure_count_since_latest_user` counts only ToolMessages whose name contains `web_search` or `searx`. The breaker resets only on a new real user message.
- Bypass: After 2 web_search failures, the LLM only needs the next attempt to *not* look like web_search to slip through — for example, calling a community tool that wraps web_search under a different name, or calling `query_knowledge_vault` (which the circuit breaker assumes the LLM falls back to) and then re-trying `web_search` afterwards. Each `web_search` retry still adds to the failure count, but the breaker fires only when `>= 2` — so once at 2, every subsequent retry is blocked. That part is fine.
- However, the breaker *cannot reset within a user turn*. A genuinely transient failure (one upstream outage, then service recovers) cannot recover until the next user message. The circuit has open and closed states but no half-open state. That's the larger issue.
- Impact: Permanent open within a user turn, even when the underlying issue resolves. Defeats the whole purpose of a circuit-breaker pattern.
- Recommendation: Implement half-open: after N failures, allow one probe; if it succeeds, reset the counter; if it fails, keep blocking. Also make `_FAILURE_THRESHOLD = 2` configurable.

### B7. Loop detection hard-stop content collision

- File: `backend/src/agents/middlewares/loop_detection_middleware.py:373-385`
- Mechanism: `_build_hard_stop_update` strips `tool_calls`, clears `additional_kwargs.tool_calls`/`function_call`, and rewrites `response_metadata.finish_reason="stop"`. But it leaves the AIMessage's `id` intact and modifies in place via `model_copy`.
- Bypass: If the AIMessage was already persisted with tool_calls, downstream consumers (UI, checkpointer) that key by message id may see the original AND the stripped version. Tool-call IDs without corresponding ToolMessages will then trigger `DanglingToolCallMiddleware` on the next turn, injecting `[Tool call was interrupted and did not return a result.]` placeholders. The LLM might interpret these as "tools were attempted, here are stub results" and try again.
- Impact: Loop hard-stop and dangling-tool-call repair fight each other. The forced-stop AIMessage may itself become a source of new tool_call IDs that need synthetic ToolMessages on the next turn.
- Recommendation: When stripping tool_calls in the hard-stop path, also record the stripped IDs in state so DanglingToolCallMiddleware can ignore them. Or use a sentinel ToolMessage rather than full strip.

### B8. Phase tool filter only gates turn-1, then is permanently disabled

- File: `backend/src/agents/middlewares/phase_tool_filter_middleware.py:66-86`
- Mechanism: `_should_filter` returns True only when there are no AI messages yet AND no plan AND not plan-mode. After the very first AIMessage, the filter is off forever.
- Bypass: An LLM that produces a benign first turn (e.g. clarifying text) immediately gets full tool access from turn 2 onward. The execution-tool gate is purely a "think before you act" nudge; it is not a security boundary.
- Impact: This is by design (per the comment), but the file path implies a generic phase filter. Future maintainers may believe this enforces phase invariants and not add deeper checks.
- Recommendation: Rename to `FirstTurnExecutionGateMiddleware` (matches the docstring) so nobody assumes it does more than it does. Document that plan-status transitions are inter-graph and need no runtime gate.

### B9. Retry middleware ignores `rule.idempotent`

- File: `backend/src/agents/middlewares/retry_policy_middleware.py:53-83`
- Mechanism: `_mark_retry` logs `rule.idempotent` in the runtime event, but the retry loop at line 75-83 never inspects it. Every retryable error is retried up to `max_attempts`.
- Bypass / failure mode: A non-idempotent tool (e.g. `write_file` to a path that's a counter, `task` that spawns a subagent, `bash` that mutates the filesystem) can be invoked N times on a transient error message even if the first call succeeded server-side and the failure is in the response path.
- Impact: Duplicate subagent runs, duplicate file writes, double-charged API calls.
- Recommendation: Actually gate on `rule.idempotent`: `if not rule.idempotent: raise`. Or only retry on errors that occur before the tool's first observable side-effect (which is impossible to know from inside the middleware — making the idempotent flag the only safe knob).

### B10. Retry middleware writes into `runtime.context` directly

- File: `backend/src/agents/middlewares/retry_policy_middleware.py:46-50`
- Mechanism: `request.runtime.context or {}` then mutates it in-place. If `context` is shared across concurrent tool calls within a single request (which it is, by design — it's the LangGraph runtime context), two parallel tool calls retrying simultaneously will race on `attempt_map`.
- Impact: Lost retry counts; attempts may exceed `max_attempts` because two parallel calls each see attempt=1.
- Recommendation: Use a `threading.Lock` or per-tool-call attempt counter, not a shared dict in runtime context. Also: writing `{}` back when `context` is falsy (`or {}`) silently discards the mutation if `runtime.context` is None — a no-op rather than a failure.

### B11. Subagent limit: deferred calls preserve original tool_call IDs

- File: `backend/src/agents/middlewares/subagent_limit_middleware.py:96-103, 196`
- Mechanism: On overflow, excess tool_calls are stored in `state["deferred_task_calls"]` *with their original IDs*. On the next AI turn, they're prepended to the new tool_calls list (line 102) and applied to the *new* AIMessage's tool_calls.
- Bypass / failure mode: The original AIMessage was rewritten via `model_copy` to drop these IDs (line 179). The new AIMessage carries them. But the *checkpointed* original AIMessage may still contain them if the checkpoint snapshot was taken before the rewrite — depending on LangGraph's reducer semantics. Also, if the LLM re-emits a `task` call with the same `description` (because it doesn't know one was deferred), the deferred + fresh prepend creates duplicate semantically-identical calls with different IDs.
- Impact: Duplicate subagent spawns; tool_call_id can become non-unique across the trajectory after deferred recycling.
- Recommendation: Mint fresh tool_call IDs when recycling deferred calls. Add a hash-based dedup against the new turn's tool calls.

### B12. Permission `default_mode="auto"` is silent default-allow

- File: `backend/src/agents/middlewares/permission_middleware.py:131-136, src/config/permissions_config.py:26`
- Mechanism: `default_mode` defaults to `"auto"`, meaning any tool not matched by `allow`/`deny`/`ask` is permitted. The config schema has no warning when a config file uses `default_mode: auto` without any deny rules.
- Bypass / failure mode: A fresh install or misconfigured deployment runs with `default_mode="auto"` and no rules, which is functionally "no permission system". New MCP tools added at runtime (via Gateway API) are *implicitly allowed* unless an operator remembers to add a rule.
- Impact: New tools are unguarded by default. The permission layer has the shape of a safety system but the semantics of an opt-in audit log when no deny rules are present.
- Recommendation: Default-deny for unrecognised tools; require an explicit `allow: ["*"]` or `default_mode: auto` to get current behavior. Print a startup banner when `default_mode == "auto"` and `len(deny) == 0`.

---

## Critical Findings

### 1. Permission middleware can be circumvented by tools whose dangerous arg is not one of the 6 known keys

- File: `backend/src/agents/middlewares/permission_middleware.py:48-57`
- Severity: Critical
- Issue: `_serialize_tool_args` only inspects `command, path, file_path, query, prompt, description`. For any other tool key, the rule's `arg_pattern` is compared against a JSON dump with key ordering, which has different metacharacters than the args themselves.
- Impact: `deny: web_browse(*evil.com*)` does nothing if `web_browse` takes a `url=` parameter rather than one of the six.
- Attack/failure mode: An LLM calls a tool with the same semantic intent as a denied rule but via a different argument key (e.g. an MCP server's `target_url` instead of `url`). The deny rule never matches.
- Recommendation: Walk all string values of the args dict and run the pattern against each; or require deny rules to specify the key explicitly (e.g. `web_browse(url=*evil.com*)`).

### 2. Default permission mode is silent default-allow

- File: `backend/src/agents/middlewares/permission_middleware.py:131-132`, `backend/src/config/permissions_config.py:25-28`
- Severity: Critical
- Issue: `default_mode: PermissionDefaultMode = Field(default="auto", ...)` makes "allow everything unmatched" the out-of-the-box behavior.
- Impact: Permission layer is effectively disabled unless operator writes explicit deny rules. Newly-registered MCP tools are auto-allowed.
- Attack/failure mode: Threat model where a malicious MCP server registers a tool named `harmless_lookup` with destructive behavior — passes the permission check without scrutiny.
- Recommendation: Change default to `"ask"`. Operators who want zero friction must opt into `"auto"` explicitly.

### 3. Retry middleware retries non-idempotent tools

- File: `backend/src/agents/middlewares/retry_policy_middleware.py:75-83`
- Severity: Critical
- Issue: `rule.idempotent` is logged but never consulted. All retryable errors trigger a retry regardless of whether the tool is safe to re-execute.
- Impact: Duplicate writes, duplicate subagent spawns, duplicate API charges.
- Attack/failure mode: `task` (subagent dispatch) errors with a network blip after spawning the worker. Retry middleware re-spawns the subagent on the same input. Now there are two parallel runs writing to the same workspace path.
- Recommendation: `if not _is_retryable(exc, rule) or not rule.idempotent: raise`.

### 4. Model timeout sync path is a pass-through

- File: `backend/src/agents/middlewares/model_timeout_middleware.py:143-148, 177-181`
- Severity: Critical
- Issue: The `wrap_model_call` and `wrap_tool_call` sync paths return `handler(request)` unchanged. The class docstring says it caps each model call — but only on the async path.
- Impact: `CapyHomeClient` (embedded sync usage per CLAUDE.md) gets no timeout enforcement. A hung local model pins the entire process.
- Attack/failure mode: An OOM or stalled Ollama instance hangs indefinitely; no `[model_timeout]` event is ever emitted; the run is unkillable from the SDK side.
- Recommendation: Use `concurrent.futures.ThreadPoolExecutor` + `.result(timeout=)` for the sync path (the same pattern `RecursionBudgetPivotMiddleware` uses at line 175). Document that the LLM call itself isn't actually cancelled, but the harness regains control.

### 5. Loop detection state is process-global; counters bleed across concurrent threads (LangGraph server is multi-thread)

- File: `backend/src/agents/middlewares/loop_detection_middleware.py:236-246`
- Severity: Critical
- Issue: `self._history`, `self._warned`, `self._tool_freq`, `self._tool_freq_warned`, `self._last_user_sig` are instance attributes on the singleton middleware. They're keyed by `thread_id`, so cross-thread bleed is avoided — *as long as `thread_id` is unique per LangGraph thread*. The `_get_thread_id` method falls back to `"default"` when context is missing (line 254).
- Impact: Any request whose runtime.context lacks `thread_id` — e.g. an internal middleware call, a subagent call, an embedded client call — shares a single `"default"` bucket. Multiple concurrent default-bucket requests race on `self._lock`-protected counters, so they don't corrupt state, but their `_tool_freq` bleeds together and a single thread's behavior can trip the global default's hard limit.
- Attack/failure mode: Subagents running in parallel under the same parent thread can mutually inflate the default bucket; on a serverless or test setup where `thread_id` is None, repeated requests permanently inherit prior runs' state.
- Recommendation: Fail loudly when `thread_id` is missing rather than collapsing to `"default"`. Or namespace by parent_thread+sub_id.

### 6. Recursion-pivot step count is `len(messages) // 2`, which misfires for tool-heavy turns

- File: `backend/src/agents/middlewares/recursion_pivot_middleware.py:138-142`
- Severity: Critical
- Issue: `_step_count` uses `messages // 2` as a proxy for model invocations. This assumes every AI message is followed by exactly one tool/human message — but a single AIMessage with N tool_calls produces N ToolMessages, plus a human reminder, plus a system_reminder, etc. The proxy underestimates step count.
- Impact: The pivot evaluator fires later than configured. At `recursion_limit=100` with `threshold=0.75`, the pivot is supposed to fire at step 75; with N=3 tool calls per turn, `messages // 2` reaches 75 only when actual recursion depth is well past 100, after `GraphRecursionError` has already terminated the run.
- Attack/failure mode: The pivot guardrail is silently a no-op on any agent that batches tool calls. The very runs that most need a pivot never get one.
- Recommendation: Count actual AIMessages, or read LangGraph's internal step counter via `runtime.config["__step__"]` (whatever the real key is). Cite the source of truth, not a heuristic.

### 7. Recursion-pivot timeout uses an executor pool but daemon-leaks threads on timeout

- File: `backend/src/agents/middlewares/recursion_pivot_middleware.py:174-177`
- Severity: High
- Issue: `with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool: future = pool.submit(...); return future.result(timeout=...)`. On `TimeoutError`, `__exit__` is called, which calls `pool.shutdown(wait=True)` by default — blocking until the runaway thread *finishes naturally*. The comment claims "the daemon thread is abandoned" but with `wait=True` (the default), the shutdown blocks.
- Impact: A hung local model under the recursion-pivot evaluator blocks the `before_model` hook forever, defeating the whole purpose of the timeout.
- Attack/failure mode: Set `evaluator_timeout_seconds=30`, set the evaluator model to a hung endpoint. The supposed 30s timeout becomes "until the OS kills the worker."
- Recommendation: Use `pool.shutdown(wait=False, cancel_futures=True)` explicitly. Or keep a long-lived pool and don't use `with`.

### 8. Loop detection: `_normalize_args` accepts a JSON string args — risk of cache poisoning across providers

- File: `backend/src/agents/middlewares/loop_detection_middleware.py:107-125`
- Severity: High
- Issue: When `raw_args` is a string, it's JSON-parsed; if that fails, the raw string is used as a fallback key. Different providers serialize args differently (OpenAI: dict; some Bedrock/Ollama backends: JSON string). The same semantic call hashes differently depending on the provider, so a multi-provider run sees no loop even if all calls are identical.
- Impact: Inter-provider loop detection breaks. Less likely an LLM-bypass, more likely a silent false-negative for users on multi-endpoint setups.
- Recommendation: Always canonicalize to dict before hashing (the function already does this; ensure the fallback path doesn't escape the normalization).

---

## High Severity

### 9. Permission middleware truncates the request snippet at 200 chars in deny message — leaks first 200 chars

- File: `backend/src/agents/middlewares/permission_middleware.py:167, 147-148`
- Severity: High
- Issue: The denied-tool ToolMessage echoes back the first 200 chars of the args. If the args contain credentials, secrets, or PII (e.g. an `Authorization: Bearer ...` header an LLM tried to send to a denied URL), the snippet ends up in the conversation history.
- Impact: Secrets leakage into trajectory logs, checkpoint state, and UI rendering.
- Recommendation: Redact obvious secret patterns (use `src/security/search_guardrails.py:_IDENTIFIER_PATTERNS`) before snippet-rendering, or just emit "Tool execution blocked. See logs for details" with no args echo.

### 10. Dangling tool call middleware silently injects placeholder responses

- File: `backend/src/agents/middlewares/dangling_tool_call_middleware.py:78-85`
- Severity: High
- Issue: For each dangling tool_call id, a `ToolMessage(content="[Tool call was interrupted and did not return a result.]", status="error")` is inserted. This is a *recovery* mechanism but, if the original tool call was a destructive one (e.g. a `bash rm` that actually executed but was cancelled before the result was recorded), the LLM now thinks the tool didn't run and will retry.
- Impact: Double-execution after a real partial run.
- Attack/failure mode: User cancels run after a `bash rm -rf foo/` actually starts executing but before the ToolMessage is persisted. On resume, dangling middleware injects "Tool call was interrupted and did not return a result." The LLM re-issues the rm. The directory is gone but the second rm is a no-op; however, for ops like `git push`, `task` spawn, or HTTP `POST`, the duplicate is real.
- Recommendation: Mark dangling placeholders as "uncertain" rather than "did not return"; or surface the cancellation reason and let the LLM decide.

### 11. Loop detection warning is a `HumanMessage` — model treats it as user input

- File: `backend/src/agents/middlewares/loop_detection_middleware.py:404-407`
- Severity: High
- Issue: The warning is emitted as `HumanMessage(content=_WARNING_MSG)`. Comment says "Anthropic models reject non-consecutive system messages" — true, but this means the LLM sees `[LOOP DETECTED]` as user-spoken text and may reply "Okay, what do you want me to do?" rather than producing the requested final answer.
- Impact: The warning is ambiguous from the model's POV; it doesn't carry the authoritative weight intended.
- Recommendation: Wrap in a `<system_reminder>...</system_reminder>` tag (consistent with `RecursionBudgetPivotMiddleware`'s convention) and set `name="loop_detection_warning"`.

### 12. Web search circuit breaker never half-opens

- File: `backend/src/agents/middlewares/web_search_circuit_breaker_middleware.py:74-79, 91-109`
- Severity: High
- Issue: Once 2 failures occur, every subsequent `web_search` in the same user turn is blocked. There is no probe-and-recover path.
- Impact: Transient outages permanently disable search for the rest of the turn. Frustrating UX and missed information.
- Recommendation: Add a half-open state: after N failures, allow 1 probe every M tool calls; if it succeeds, reset the count.

### 13. Subagent limit middleware: `model_copy` rewrites the AI message but doesn't notify the checkpointer

- File: `backend/src/agents/middlewares/subagent_limit_middleware.py:179-196`
- Severity: High
- Issue: `last_msg.model_copy(update={...})` then `return {"messages": [updated_msg]}` relies on LangGraph's reducer to replace the previous AIMessage by id. If the reducer is `add_messages`, replacement-by-id works; if it's another reducer (or in resume paths), the original may persist alongside the rewrite.
- Impact: Two AIMessages with overlapping tool_calls — UI shows duplicate task spawns.
- Recommendation: Explicit dual-check: assert the reducer behavior in tests, or delete-and-re-add rather than rely on model_copy semantics.

### 14. Recursion pivot leaks `pivot_state` even when evaluator times out and configuration says `terminate`

- File: `backend/src/agents/middlewares/recursion_pivot_middleware.py:295-307`
- Severity: High
- Issue: `_handle_evaluator_failure` returns `jump_to: "end"` only when `on_evaluator_failure == "terminate"`. But the `pivot_state["fired_thresholds"]` was already updated (line 228-229) *before* the evaluator was invoked. So a threshold is consumed even if the run never gets the directive.
- Impact: After an evaluator timeout, the next threshold is the only remaining one. If subsequent thresholds also time out, all are silently consumed without any directive ever being applied.
- Recommendation: Defer consuming the threshold (`fired_indices.add`) until *after* the evaluator returns a usable response. On timeout/error, leave the threshold un-fired so the next iteration tries again.

### 15. Subagent limit double-counts when deferred queue isn't draining

- File: `backend/src/agents/middlewares/subagent_limit_middleware.py:158-164`
- Severity: High
- Issue: When `len(deferred_existing) >= dropped_count`, the warning "Subagent deferral queue is not draining" is logged but the deferred queue keeps growing unboundedly. There's no cap on `deferred_task_calls`.
- Impact: Memory growth via the deferred queue; LLM re-emits task calls each turn that pile up.
- Recommendation: Cap `len(deferred_task_calls)` at, say, 20; drop the oldest with a warning ToolMessage to the LLM.

### 16. Phase tool filter relies on `_EXECUTION_TOOLS` hard-coded set

- File: `backend/src/agents/middlewares/phase_tool_filter_middleware.py:35-46`
- Severity: High
- Issue: When new execution-class tools are added (MCP tools, community tools, future builtins), they are *not* in `_EXECUTION_TOOLS` and therefore not gated on turn 1.
- Impact: New tools bypass the "think before you act" warm-up.
- Recommendation: Inverse the filter — keep an allow-list of *safe-to-call-first* tools (`read_file`, `ls`, `present_files`, `ask_user_for_clarification`) and hide everything else on turn 1.

---

## Medium Severity

### 17. Permission middleware: rules with empty `arg_pattern` (e.g. `bash()`) get arg_pattern=None

- File: `backend/src/agents/middlewares/permission_middleware.py:43-45`
- Severity: Medium
- Issue: `arg_pattern or None` — a rule like `bash()` has empty args content, parsed to empty string, then coerced to `None`, meaning it matches *every* bash call. This may be intentional (operators write `bash()` meaning "any bash"), but it's surprising — `bash` and `bash()` and `bash(*)` are all equivalent.
- Recommendation: Document that explicitly.

### 18. Loop detection: cumulative `_tool_freq` never resets within a turn

- File: `backend/src/agents/middlewares/loop_detection_middleware.py:332-355`
- Severity: Medium
- Issue: Layer-2 frequency is "per user turn" (reset in line 288). But within a turn, a legitimate workflow that needs 35 read_file calls hits the warning at 30 and the hard limit at 50. The user can't override this from inside a single turn except via the skill workflow flag.
- Impact: False positives kill legitimate exploration work.
- Recommendation: Either expose a `runtime.context["force_workflow"]` escape, or scale `tool_freq_hard_limit` with the configured `recursion_limit`.

### 19. Retry middleware fnmatch matches first rule and stops

- File: `backend/src/agents/middlewares/retry_policy_middleware.py:37-43`
- Severity: Medium
- Issue: `_rule_for` returns on first match. If config has both `bash` and `*` rules, the order determines which applies.
- Impact: Order-dependent behavior, easy to misconfigure (most-specific-first vs first-listed).
- Recommendation: Sort rules by specificity (literal name > wildcarded), document the order.

### 20. Permission middleware: `_TODO_BYPASS_RE` re-evaluated synchronously on every call

- File: `backend/src/agents/middlewares/permission_middleware.py:179-189, 216-227`
- Severity: Medium
- Issue: The async path duplicates the sync-path TODO bypass block. Easy to drift; bug-fix in one needs to be applied to the other.
- Recommendation: Extract the bypass block into a shared method `_check_todo_bypass(request) -> ToolMessage | None`.

### 21. Web search circuit breaker fingerprint can be spoofed by tool output

- File: `backend/src/agents/middlewares/web_search_circuit_breaker_middleware.py:15, 63`
- Severity: Medium
- Issue: `_CIRCUIT_OPEN_FINGERPRINT = "[web_search_circuit_open]"`. The breaker counts ToolMessages whose content contains this string. If a web search result *contains the string "[web_search_circuit_open]"* (e.g. someone publishing a blog post with that fingerprint), it counts as a failure.
- Impact: Adversarial-content-induced false positive — a webpage triggers the breaker against its own crawler.
- Recommendation: Compare against `tool_call_id` or a metadata field, not a content substring.

### 22. Model timeout: `TIMEOUT_MESSAGE_FINGERPRINT = "[model_timeout]"` is grep-keyed across middlewares

- File: `backend/src/agents/middlewares/model_timeout_middleware.py:38`
- Severity: Medium
- Issue: This fingerprint is read by `web_search_circuit_breaker_middleware.py:13`. A coupling that's not obvious and brittle. Renaming the constant in one file breaks the other silently.
- Recommendation: Move shared fingerprints to a single module (e.g. `src/agents/middlewares/_fingerprints.py`).

### 23. Recursion pivot evaluator timeout uses a fresh pool every call

- File: `backend/src/agents/middlewares/recursion_pivot_middleware.py:175-177`
- Severity: Medium
- Issue: A new `ThreadPoolExecutor` per evaluator invocation is wasteful and amplifies the shutdown problem in finding #7.
- Recommendation: Long-lived module-level pool, or `asyncio.wait_for` from an async-only invocation path.

### 24. Subagent limit ignores explicit `max_concurrent_limit < 2`

- File: `backend/src/agents/middlewares/subagent_limit_middleware.py:33-36`
- Severity: Medium
- Issue: `lo = max(1, int(cfg.min_concurrent_limit))` — but the docstring at line 48 says "Clamped to [2, 4]". Drift between code and docs.
- Recommendation: Update docstring; or restore the [2, 4] floor with a startup warning when config exceeds it.

### 25. Loop detection's workflow cache: stale skill flags persist after a skill is disabled

- File: `backend/src/agents/middlewares/loop_detection_middleware.py:49-62`
- Severity: Medium
- Issue: `_WORKFLOW_CACHE_TTL = 30.0` — 30 seconds where a disabled workflow skill still suppresses Layer-2 detection.
- Impact: After disabling a runaway workflow skill, the loop detector remains silent for up to 30s.
- Recommendation: Plumb cache invalidation on skill update events (the Gateway API already invalidates the agent cache; same hook can poke this cache).

### 26. Permission middleware's `_apply_policy` and `_aapply_policy` are duplicated

- File: `backend/src/agents/middlewares/permission_middleware.py:178-241`
- Severity: Medium
- Issue: Sync and async paths are byte-for-byte duplicates except for one await. Easy to drift; the sync path could call the async one via `asyncio.run` only at top level — but here, both are needed since wrap_tool_call is sync-or-async. Worth extracting common helpers.
- Recommendation: Extract `_decide(request) -> Decision` and `_render(decision, request) -> ToolMessage | Command | "delegate"`; sync/async paths differ only in `await handler(request)`.

---

## Low Severity / Nits

### 27. `LoopDetectionMiddleware` initializer reads `_DEFAULT_*` constants but constructor arguments override them — no validation that `warn_threshold < hard_limit`

- File: `backend/src/agents/middlewares/loop_detection_middleware.py:220-235`
- Issue: A misconfigured `warn_threshold=10, hard_limit=5` would mean the hard limit triggers before the warning. No assertion.
- Recommendation: Add post-init validation.

### 28. `RecursionBudgetPivotMiddleware._summarize_recent_messages` doesn't redact PII

- File: `backend/src/agents/middlewares/recursion_pivot_middleware.py:64-78`
- Issue: The recent-messages summary is shipped to an evaluator LLM. If messages contain secrets/PII, those go to the evaluator endpoint.
- Recommendation: Add redaction using `src/security/search_guardrails.py:_IDENTIFIER_PATTERNS`.

### 29. `DanglingToolCallMiddleware` walks messages twice (existing IDs + needs_patch detection) — O(N + M*K)

- File: `backend/src/agents/middlewares/dangling_tool_call_middleware.py:38-100`
- Issue: Minor perf — for very long conversations, three passes vs one.
- Recommendation: Single-pass; build the patched list directly.

### 30. `model_timeout_middleware._stage_for` ignores `request.runtime.context["stage"]` if `runtime.config` is not a dict — silent fallback

- File: `backend/src/agents/middlewares/model_timeout_middleware.py:53-72`
- Issue: When the stage is missing or context is None, the heuristic kicks in. No log line indicating "using heuristic" — debugging the wrong timeout requires reading the code.
- Recommendation: Add a debug log.

### 31. `_BLOCKED_HOSTS` in `search_guardrails.py` doesn't include IPv6 link-local, IPv4-mapped IPv6, or rfc6890 addresses beyond the obvious

- File: `backend/src/security/search_guardrails.py:37-46, 155-163`
- Issue: The block list combines string-based and `ipaddress` module checks, but the string list is incomplete (e.g. `::ffff:127.0.0.1` is a string that won't match the IP check after `urlparse` because the brackets are stripped — needs testing).
- Recommendation: Always run through `ipaddress.ip_address`; add IPv6 mapped/compat range to the block list.

### 32. `enforce_query_guardrails` length check is byte-length-not-char-length-aware

- File: `backend/src/security/search_guardrails.py:108-111`
- Issue: `len(normalized_query)` counts Python str chars (code points), but underlying tool may apply byte limits. CJK or emoji-heavy queries pass the char check but blow byte limits.
- Recommendation: Document the unit; consider checking both.

### 33. Permission middleware `args_text` snippet uses 200-char cutoff; long base64-encoded image payloads (vision) are truncated silently

- File: `backend/src/agents/middlewares/permission_middleware.py:147-148`
- Issue: Echoing base64 first-200-chars is mostly useless for diagnosis. No special-case for known-large keys.
- Recommendation: Detect base64 prefix and render `<base64 payload, N bytes>` instead.

### 34. `LoopDetectionMiddleware._track_and_check` returns from inside the `with self._lock:` block in multiple places — risk of forgetting to release

- File: `backend/src/agents/middlewares/loop_detection_middleware.py:283-357`
- Issue: Multiple early returns within a `with` block — Python releases the lock correctly on context exit, but the code is hard to audit for added branches.
- Recommendation: Compute decisions inside the lock, return outside.

### 35. `runtime_events.append_runtime_event` is called with side-effecting mutation of `runtime.context` — if context is None, the event is silently dropped (see retry middleware line 47)

- Issue: A `runtime.context is None` case in several middlewares silently no-ops. Should at least warn-log.

---

## Defense-in-depth gaps

These are places where a single layer protects something that warrants two.

1. **Todo file integrity**: Only the regex in `PermissionMiddleware` protects todos from non-`write_todos` writers. A second layer at the sandbox/tool boundary (mount the todos JSON file as read-only to `bash`/`write_file`/`str_replace`) would close the regex-bypass loophole permanently.

2. **Subagent fan-out**: `SubagentLimitMiddleware` caps per-turn fan-out, but there's no *cumulative* cap across a run. A persistent LLM can spawn 3 subagents per turn for 100 turns = 300 subagents, each consuming concurrency budget. Add a cumulative counter + hard ceiling.

3. **Tool retry × Tool timeout**: `RetryPolicyMiddleware` retries on retryable error. `ModelTimeoutMiddleware` converts timeout into a fingerprinted `ToolMessage`, *which doesn't raise an exception*, so retry won't fire. But if the tool itself raises `TimeoutError` (not converted to a ToolMessage), retry treats it as retryable per `RetryRuleConfig.retryable_errors`. The interaction is ambiguous — document which path is canonical.

4. **Loop detection × Recursion pivot**: Both are "agent is stuck" detectors but operate on different signals (call-set hash vs step count vs evaluator opinion). They don't coordinate — a recursion pivot might inject a directive *immediately after* loop detection fired a warning, and the model now sees both, but neither knows about the other.

5. **Permission × Phase filter**: The phase filter hides tools from the LLM on turn 1; the permission filter denies them per-call. A tool can be visible-but-denied (works for newly-added tools, fails open if permission has no rule). Wire `_EXECUTION_TOOLS` to also be checked against `default_mode` so unmatched tools are at least `ask`-ed.

6. **Web search circuit breaker × Retry**: After 2 web_search failures the breaker opens. But `RetryPolicyMiddleware` may have already retried each of those 2 failures up to `max_attempts` — so the effective failure count from the LLM's POV is N attempts, but the breaker counted 2 ToolMessages. They should agree.

7. **Model timeout × Recursion pivot**: When a model call times out, an AIMessage is returned (line 140) instead of advancing the step counter. The recursion pivot's `_step_count = len(messages) // 2` *does* count this — but the model never produced a real "step." Pivot fires earlier than expected on timeout-heavy runs.

8. **Dangling tool call × Loop detection hard-stop**: As noted in B7, the hard-stop strips tool_calls from a checkpointed AIMessage. Cross-turn replay can re-introduce them. Coordination required.

9. **No guardrail on `ask_user_for_clarification`**: Hard-coded allow + ClarificationMiddleware interrupt = an LLM-controlled side channel to the user. No length/content gate.

10. **No guardrail on the evaluator LLM call**: The recursion pivot evaluator is invoked with no timeout-on-the-LLM-side checks (the executor timeout doesn't actually cancel the LLM call) and no retry limit on the evaluator itself. A misbehaving evaluator can stall every threshold.

---

## Recommendations for consolidation

1. **Centralize fingerprints and decision markers** in `src/agents/middlewares/_fingerprints.py` (TIMEOUT, CIRCUIT_OPEN, PERMISSION_DENIED, LOOP_FORCED_STOP, RECURSION_PIVOT, DANGLING_TOOL). Today they're scattered and cross-imported (`web_search_circuit_breaker` imports from `model_timeout`).

2. **Single "agent stuck" detector** that consumes signals from `LoopDetectionMiddleware`, `RecursionBudgetPivotMiddleware`, and per-tool retry counts, and emits a single coordinated directive. This eliminates the double-warning case and lets operators reason about one "stuck threshold."

3. **Permission decision pipeline**: extract `Decision = allow|deny|ask` calculation into a pure function `decide(rules, default_mode, tool_name, args) -> Decision` that's unit-testable. Make `_serialize_tool_args` per-tool (registered alongside the tool, like a permission-args adapter). Remove sync/async duplication.

4. **State-key namespace**: define a fixed list of state keys that guardrails write to (`retry_meta`, `deferred_task_calls`, `recursion_pivot`, etc.) so resume/checkpoint replay can clear/migrate them consistently. Today these are scattered across `ThreadState`.

5. **Configurable thresholds in one place**: today `_FAILURE_THRESHOLD = 2`, `_DEFAULT_WARN_THRESHOLD = 3`, `_DEFAULT_HARD_LIMIT = 5`, `_DEFAULT_TOOL_FREQ_WARN = 30`, etc. are constants in their respective files. Move to `config.yaml -> guardrails:` so deployments can tune without forking.

6. **Default-deny mode**: change `PermissionsConfig.default_mode` default from `"auto"` to `"ask"`. The current default is permissive; an "official safety system" should be restrictive-by-default.

7. **Idempotent flag enforcement**: actually use `RetryRuleConfig.idempotent`. Today it's logged and ignored.

8. **Standardize injected messages**: all guardrail-injected messages should be `HumanMessage(name="<guardrail_name>_<purpose>", content="<system_reminder>...</system_reminder>")` so loop detection can ignore them and the LLM understands they are authoritative system inputs, not user speech. Today the convention is mixed.

9. **Sync-path timeout enforcement**: implement sync timeouts in `ModelTimeoutMiddleware` (thread-pool-based as in `RecursionBudgetPivotMiddleware`). The embedded `CapyHomeClient` deserves the same protection.

10. **End-to-end guardrail tests**: a single tabletop test that, for each middleware, simulates a bypass and asserts it fails. Currently each middleware has unit tests but the interactions (e.g. retry × timeout × circuit-breaker) are not tested as a chain.
