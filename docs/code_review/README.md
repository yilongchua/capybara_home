# Code Review — Plan Mode, Work Mode, Middleware, Guardrails

Generated 2026-05-28. Senior-review pass across the four agent-runtime subsystems that drive CapyHome's plan→work loop.

Each report is self-contained, cites `file:line`, and groups findings by severity (Critical / High / Medium / Low). Total: **142 concrete findings**.

## Reports

| # | Report | Findings | Critical |
|---|--------|---------:|---------:|
| 01 | [Plan Mode](01_plan_mode.md) | 34 | 1 |
| 02 | [Work Mode](02_work_mode.md) | 30 | 5 |
| 03 | [Core Middleware](03_middleware.md) | 43 | 5 |
| 04 | [Guardrails](04_guardrails.md) | 35 | 12 |

## Cross-cutting themes

These patterns recur across all four reports — fix them once and many individual findings collapse.

### 1. `async` paths quietly delegate to blocking `sync` paths
- `EvaluatorMiddleware.aafter_model` calls sync `after_model` → blocking `model.invoke()` ([03](03_middleware.md))
- `PlannerMiddleware.abefore_model` is sync-wrapped ([01](01_plan_mode.md))
- `ModelTimeoutMiddleware.wrap_model_call` is a pass-through no-op for sync path ([04](04_guardrails.md))
- `WriteFileArtifactMiddleware.wrap_tool_call` is a no-op — only `awrap_tool_call` runs quality gate ([03](03_middleware.md))

**Net effect:** sync code paths (embedded clients, tests) silently bypass timeouts, evaluators, artifact promotion. The event loop blocks during LLM calls.

### 2. Per-instance mutable state shared across runs
- `WorkModeMiddleware._completed_before` ([02](02_work_mode.md))
- `AutoresearchMiddleware._autoresearch_triggered` ([03](03_middleware.md))
- `TodoFailureRetryMiddleware` retry counter never resets ([02](02_work_mode.md))
- `PlanFollowupMiddleware._failed_jobs` unbounded ([03](03_middleware.md))

**Net effect:** concurrent threads/runs see each other's state. Duplicate/missed SSEs, retries running off stale counters.

### 3. Daemon-thread handoff pattern leaks
- `_HANDOFF_GUARD` / `_IN_FLIGHT_HANDOFFS` has no TTL — dead threads poison the set permanently ([01](01_plan_mode.md), [02](02_work_mode.md))
- `asyncio.run()` inside daemon retry loops breaks SDK connection pool ([02](02_work_mode.md))
- `PlanFollowupMiddleware` leaks a `CapyHomeClient` per follow-up ([03](03_middleware.md))
- `recursion_pivot_middleware` `ThreadPoolExecutor` `with`-block blocks on the hung thread it was supposed to escape ([04](04_guardrails.md))

### 4. Dead code & stale references from the auto-escalation removal
- `PlanExecutionGateMiddleware` is **commented out** in the registry but the Plan Mode prompt still references `[plan_gate]` blocks — prompt-only enforcement today ([01](01_plan_mode.md))
- `scope_search` tool is deprecated but referenced 7× across prompts and gate middleware ([01](01_plan_mode.md))
- `PhaseToolFilterMiddleware`, `revised_todos` branch, `mark_handoff_started` alias, `router=` parameters — all leftovers ([01](01_plan_mode.md))
- `plan_agent/agent.py:7` docstring still says "auto-escalation paths"

### 5. Guardrails default-allow / easily-bypassed
- `PermissionsConfig.default_mode = "auto"` — unmatched tools allowed by default ([04](04_guardrails.md))
- `_serialize_tool_args` only inspects 6 hardcoded keys — deny rules silently inert for other payloads ([04](04_guardrails.md))
- TODO-bypass regex only covers `bash` over a 40-char window — `write_file`/`str_replace` to todos JSON not blocked ([04](04_guardrails.md))
- `ask_user_for_clarification` is hard-coded allow — unguarded UI side-channel ([04](04_guardrails.md))
- Loop-detection bucket key for `read_file` is 200-line windows → sequential reads never match ([04](04_guardrails.md))

### 6. Plan.md / scratchpad / checkpoint — three writers, three readers, no owner
- `_run_work_mode_handoff` skips `normalize_todo_nodes` on user-edited plan.md ([02](02_work_mode.md))
- Full plan.md rewrite each cycle defeats byte-equality check ([02](02_work_mode.md))
- `merge_todo_nodes` shallow-copies `steps` (aliasing) ([02](02_work_mode.md))
- Non-atomic plan.md writes ([01](01_plan_mode.md))

### 7. Silent exception swallowing
- `_get_memory_context` bare `print()` on all exceptions ([02](02_work_mode.md))
- SSE failures with no compensation ([02](02_work_mode.md))
- `runtime_events._compact_runtime_events` needs ≥2 consumers to compact → leaks the queue when execution_trace or trajectory is disabled ([03](03_middleware.md))

## Recommended fix order

If you have a finite week of cleanup, this is the order with the highest return on risk reduction.

1. **Decide `PlanExecutionGateMiddleware`** — re-register it or scrub the prompt. The current state is the worst of both worlds. ([01 #1](01_plan_mode.md))
2. **Flip `permissions.default_mode` to deny + audit `_serialize_tool_args`** — broad cap on bypass attempts. ([04 #1, #2](04_guardrails.md))
3. **Fix async→sync fall-throughs** — `ModelTimeoutMiddleware`, `EvaluatorMiddleware`, `WriteFileArtifactMiddleware`, `PlannerMiddleware`. One pattern, multiple files. ([03](03_middleware.md), [04](04_guardrails.md))
4. **Add TTL/cleanup to `_HANDOFF_GUARD` and `_IN_FLIGHT_HANDOFFS`** — caps the daemon-thread leak blast radius. ([01](01_plan_mode.md), [02](02_work_mode.md))
5. **Move per-run mutable state out of middleware `__init__`** into runtime state / context. ([02 #2](02_work_mode.md), [03](03_middleware.md))
6. **Sweep stale auto-escalation references** — `scope_search`, `PhaseToolFilterMiddleware`, dead branches, docstrings, prompts. ([01](01_plan_mode.md))
7. **Split `work_agent/agent.py` (831 lines)** — middleware registry vs. agent factory vs. handoff orchestration. ([02](02_work_mode.md))
8. **Fix `recursion_pivot` and `loop_detection` bypass paths** — guardrail false-negatives. ([04 #6, #7, #9](04_guardrails.md))

## How to use this folder

- Each report stands alone — you do not need to read in order.
- Cross-references between reports are linked inline where they appear.
- Findings are pinned to `file:line` — drop them into PR descriptions or issues directly.
- Counts: don't optimize to drive findings to zero — some Lows are nits, some Mediums are real architectural debt. Treat the Critical/High lists as the working backlog.
