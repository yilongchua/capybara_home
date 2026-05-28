# ProgressGuard Middleware — Reimplementation Guide

This folder is the **authoritative reference** for the ProgressGuard middleware after it was removed from the active codebase. Everything needed to bring it back — original source, tests, wiring sites, config schema — is preserved here.

The middleware was deleted from the tree to simplify the harness; if a regression appears (runs blowing past `recursion_limit`, identical tool-result loops, context-pressure ceiling crashes) reintroduce it by following the steps below.

---

## 1. What ProgressGuard does

A **warn-first, optionally-terminating** safety middleware that runs in `after_model`. It watches four signals on every model turn and:

1. Emits a `HumanMessage(name="progress_guard_warning")` once per signal (so the agent sees the warning inline).
2. Optionally **terminates** the run via `jump_to: "end"` when stall or cyclic-tool-result hard limits are reached.

| Signal | Detection | Default warn threshold | Hard-stop? |
|---|---|---|---|
| `no_progress_turns` | Snapshot of `artifacts + todos + todo_graph + outputs_path` directory is unchanged turn-over-turn | `no_progress_turn_threshold` (50, prod 80) | Yes — when `terminate_on_stall=true` |
| `conversation_inactivity` | AI message has no user-visible content AND snapshot unchanged | `conversation_inactivity_turn_threshold` (8, prod 10) | No |
| `cyclic_tool_results` | Last tool result has the same `name + content` hash N turns in a row | `cyclic_tool_result_threshold` (3, prod 6) | Yes — at `cyclic_tool_result_hard_limit` (8, prod 12) when `terminate_on_cyclic_tool_results=true` |
| `context_pressure` | `prompt_tokens / model.context_window` ≥ threshold | `context_pressure_threshold` (0.85) | No |

State is **scoped per real-user-message**: every new human input resets counters and the `emitted_signals` set so each user turn gets a fresh budget.

### Design properties

- **Output-focused** — looks at *what the agent produced* (artifacts, todos, files on disk), not just messages. Complements `LoopDetectionMiddleware` which looks at *what the agent called* (identical tool-call hashes, frequency saturation).
- **Retry-aware** — coordinates with `RetryPolicyMiddleware` via a per-turn context flag (`RETRY_PROGRESS_GUARD_KEY = "_phase_b_retry_turn"`). When a turn is the result of an idempotent retry, the no-progress and cyclic-tool-result counters are held constant so a transient retry can't trip the stall guard.
- **Warn-once** — each signal name is added to `pg["emitted_signals"]` after firing; reset only on a new real-user message.
- **Operational-message-preserving** — `progress_guard_warning` is in `SummarizationMiddleware._OPERATIONAL_MESSAGE_NAMES`, so warnings survive context compaction.

---

## 2. Files to recreate

The original sources are preserved verbatim in [`source/`](source/) — copy them into the locations below:

| Source preserved here | Destination in repo |
|---|---|
| [source/progress_guard_middleware.py](source/progress_guard_middleware.py) | `backend/src/agents/middlewares/progress_guard_middleware.py` |
| [source/progress_guard_config.py](source/progress_guard_config.py) | `backend/src/config/progress_guard_config.py` |
| [source/test_progress_guard_middleware.py](source/test_progress_guard_middleware.py) | `backend/tests/test_progress_guard_middleware.py` |
| [source/progress_guard_calibration.json](source/progress_guard_calibration.json) | `backend/tests/evals/fixtures/progress_guard_calibration.json` |

---

## 3. Wiring checklist

The following edits are required outside the two new files. **Make all of them or the middleware won't activate / `jump_to:"end"` won't terminate the graph.**

### 3.1 `backend/src/agents/thread_state.py`

Add the runtime-state TypedDict and the field on `ThreadState`:

```python
class ProgressGuardRuntimeState(TypedDict, total=False):
    no_progress_turns: int
    inactivity_turns: int
    repeated_tool_result_turns: int
    last_snapshot_hash: str
    last_tool_result_sig: str
    emitted_signals: list[str]
```

On `class ThreadState(AgentState):` add (near the other `NotRequired` blocks):

```python
progress_guard: NotRequired[ProgressGuardRuntimeState | None]
```

### 3.2 `backend/src/config/progress_guard_config.py`

This file is the pydantic config + a module-level singleton + a loader. See [source/progress_guard_config.py](source/progress_guard_config.py).

### 3.3 `backend/src/config/__init__.py`

```python
from .progress_guard_config import ProgressGuardConfig, get_progress_guard_config
```

And add `"ProgressGuardConfig"`, `"get_progress_guard_config"` to `__all__`.

### 3.4 `backend/src/config/app_config.py`

Import:
```python
from src.config.progress_guard_config import ProgressGuardConfig, load_progress_guard_config_from_dict
```

Field on `AppConfig`:
```python
progress_guard: ProgressGuardConfig = Field(default_factory=ProgressGuardConfig, description="Progress guard configuration")
```

In the config loader (search for `# Load progress guard config`):
```python
load_progress_guard_config_from_dict(config_data.get("progress_guard", {}))
```

### 3.5 `backend/src/agents/middlewares/retry_policy_middleware.py`

Add the context-key constant near `RETRY_ATTEMPTS_CONTEXT_KEY`:

```python
RETRY_PROGRESS_GUARD_KEY = "_phase_b_retry_turn"
```

In `_mark_retry(...)`:

```python
context[RETRY_PROGRESS_GUARD_KEY] = bool(rule.idempotent)
```

Without this, retried tool calls will increment the stall counter and can trip termination on transient retries.

### 3.6 `backend/src/agents/work_agent/agent.py` — middleware registration

Import:

```python
from src.agents.middlewares.progress_guard_middleware import ProgressGuardMiddleware
```

In `build_middleware_specs()` (or equivalent) insert the spec **after `resume_state`** and update the consumers:

```python
MiddlewareSpec("progress_guard", lambda: ProgressGuardMiddleware(), after={"resume_state"}),
MiddlewareSpec("plan_followup", lambda: PlanFollowupMiddleware(), after={"progress_guard", "evaluator"}),
# LoopDetectionMiddleware complements ProgressGuard: ProgressGuard detects stalls by
# inspecting outputs (unchanged artifacts/todos/files), while LoopDetection detects
# repetitive inputs (identical call-pattern hashes and per-tool-type frequency saturation).
MiddlewareSpec("loop_detection", bind(_create_loop_detection), after={"plan_followup"}),
```

And add `"progress_guard"` to the `after={...}` set of the `clarification` spec (it must run after progress_guard so warnings are visible to clarification interception).

### 3.7 `backend/src/agents/middlewares/execution_trace_middleware.py`

In the `_SOURCE_STAGE` mapping:

```python
"progress_guard": "harness",
```

So runtime events tagged `source: "progress_guard"` route into the execution trace under the `harness` stage.

### 3.8 `backend/src/agents/middlewares/summarization_middleware.py`

Add `"progress_guard_warning"` to `_OPERATIONAL_MESSAGE_NAMES`. This prevents the summarizer from collapsing the warning messages out of context.

### 3.9 `config.example.yaml`

```yaml
progress_guard:
  enabled: false # Master switch for no-progress and stall detection.
  terminate_on_stall: true # End run when no progress persists to threshold (prevents recursion-limit crashes).
  context_pressure_threshold: 0.85 # Warn when prompt/context usage reaches this fraction of model context window.
  conversation_inactivity_turn_threshold: 10 # Warn after this many turns with no user-visible assistant text.
  cyclic_tool_result_threshold: 6 # Warn when identical tool results repeat this many consecutive turns.
  no_progress_turn_threshold: 80 # Stall threshold for ending run when outputs/todos/artifacts stop changing.
  terminate_on_cyclic_tool_results: true # End run on severe repeated identical tool-result cycles.
  cyclic_tool_result_hard_limit: 12 # Hard-stop threshold for cyclic tool-result loops.
```

---

## 4. The crucial `__can_jump_to__` attribute

LangChain's agent factory builds the conditional edge from `after_model` to `END` by **reading the `__can_jump_to__` attribute off the overridden hook**. Without these two lines at the bottom of the middleware module, returning `{"jump_to": "end"}` is silently ignored:

```python
ProgressGuardMiddleware.after_model.__can_jump_to__ = ["end"]
ProgressGuardMiddleware.aafter_model.__can_jump_to__ = ["end"]
```

If you split the middleware into multiple files, keep these attribute assignments in the same module that defines the class (post-class-body) — adding them from another module won't be picked up by the factory.

---

## 5. State invariants and edge cases

These are the non-obvious invariants the implementation enforces — preserve them on reimplementation:

1. **User message identity is hashed**, not message-count based. New real-user content (ignoring middleware-injected `HumanMessage`s with a `name=` attribute) → counters reset. Same user message replayed → counters continue.
2. **Tool-only turns count as activity** when `todo_graph` changes between turns. The outputs fingerprint includes `todo_graph` so a `write_todos` tool-only turn that changes the graph resets `no_progress_turns` to 0. ([test_tool_only_turn_with_todo_graph_change_counts_as_activity](source/test_progress_guard_middleware.py))
3. **Outputs-on-disk are walked**, not just state fields. `_outputs_fingerprint` recursively `rglob`s `state["thread_data"]["outputs_path"]` and includes `(relative_path, size, mtime)` for each file. This is how the guard sees that the agent really did write something to disk even when state didn't change.
4. **Idempotent retry turns hold counters**. When `runtime.context[RETRY_PROGRESS_GUARD_KEY]` is truthy, the no-progress and cyclic-tool-result counters keep their previous values rather than incrementing. The flag is popped (`pop`, not `get`) so it applies to exactly one turn.
5. **Warn-once per signal per user turn**. `pg["emitted_signals"]` is a sorted list of signal names already fired; new warnings only fire for unseen signals. Resets when the user message hash changes.
6. **Termination always emits a final HumanMessage** explaining why, before returning `jump_to: "end"`. The agent never gets a silent termination.

---

## 6. Calibration gate

The test fixture [`progress_guard_calibration.json`](source/progress_guard_calibration.json) holds the regression gate:

```json
{"legitimate_runs": 500, "false_positives": 4, "runaway_runs": 20, "true_positives": 15}
```

`test_progress_guard_calibration_fixture_meets_gate` asserts:

- false-positive rate (`false_positives / legitimate_runs`) < 1%
- true-positive rate (`true_positives / runaway_runs`) ≥ 70%

When re-tuning thresholds, regenerate this fixture from a fresh sweep before merging — otherwise the gate is meaningless.

---

## 7. Dependencies summary

ProgressGuard depends on:

- `langchain.agents.middleware.AgentMiddleware` and `AgentState`
- `langgraph.runtime.Runtime` (for `runtime.context`)
- `src.agents.middlewares.runtime_events.append_runtime_event` (event emission)
- `src.config.app_config.get_app_config` (to look up `model_config.model_extra["context_window"]` for context-pressure)
- `src.config.progress_guard_config.{ProgressGuardConfig, get_progress_guard_config}`

It is depended on by:

- `RetryPolicyMiddleware` — sets the per-turn skip flag
- `SummarizationMiddleware` — preserves `progress_guard_warning` across compaction
- `ExecutionTraceMiddleware` — maps the `progress_guard` event source to `harness` stage
- `PlanFollowupMiddleware`, `LoopDetectionMiddleware`, `ClarificationMiddleware` — registered `after` it so ordering is deterministic

---

## 8. Why it was removed

Recorded here for future reviewers — the middleware was working; the removal was a deliberate simplification of the harness chain in favour of fewer moving parts. If runs start hitting `recursion_limit` without warning, or you see runaway cyclic-tool-result patterns in trajectories, reintroduce this middleware first before reaching for harder limits.
