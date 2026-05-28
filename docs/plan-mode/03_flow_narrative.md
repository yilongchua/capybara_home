# 03 — End-to-End Flow Narrative

This document walks through a single Plan Mode turn from user keystroke to
`plan.md` on disk, then through the Execute-Plan handoff into Work Mode.
References use `file:line` so each step can be traced in the codebase.

## Phase 0 — Frontend prepares the request

User types a request into the input box. If the Plan-Mode chip is on,
`settings.context.mode === "plan"`
([input-box.tsx:505](../../frontend/src/components/workspace/input-box.tsx#L505)).
On submit, `core/threads/hooks.ts` builds a LangGraph `stream` request with:

```ts
configurable: {
  current_mode: "plan",
  mode: "plan",            // legacy alias (kept until step 8 of migration)
  is_plan_mode: true,       // legacy boolean (same)
  plan_behavior: "plan_foreground",
  auto_mode,
  thinking_enabled, subagent_enabled, model_name, …
}
```

The LangGraph SDK posts to the `plan_agent` graph (or `work_agent` with
`mode="plan"` — same behaviour after mode resolution).

## Phase 1 — Graph factory

LangGraph invokes `make_plan_agent(config)`
([plan_agent/agent.py:29](../../backend/src/agents/plan_agent/agent.py#L29)).
It forces the canonical mode flags and delegates to
`_build_work_agent(config, prompt_template_fn=plan_apply_prompt_template)`
([work_agent/agent.py:705](../../backend/src/agents/work_agent/agent.py#L705)).

`_build_work_agent` then:

1. Calls `_extract_runtime_params` to unpack `is_plan_mode=True`,
   `plan_behavior`, `auto_mode`, etc.
2. Resolves the chat model via `ModelRouter.resolve("generator", ...)`.
3. Reconciles `thinking_enabled` vs the model's `supports_thinking`.
4. Calls the **plan-mode prompt builder**
   ([plan_agent/prompt.py:104](../../backend/src/agents/plan_agent/prompt.py#L104))
   which produces `work_base_prompt + "\n\n" + PLAN_MODE_SECTION`.
5. Calls `_build_middlewares(config, ...)` →
   `_build_middleware_registry` → `topological_sort_middleware_specs`
   ([work_agent/agent.py:466](../../backend/src/agents/work_agent/agent.py#L466)).
   The `ctx.is_plan_mode` flag drives conditional construction of
   `PlannerMiddleware`, `PlanEvaluatorMiddleware`,
   `TodoDagMiddleware`/`TodoMiddleware`. `WorkModeMiddleware` is NOT built
   (its factory returns `None` when `is_work_mode=False`).
6. Calls `create_agent(model, tools, middleware, system_prompt, state_schema)`.
   `get_available_tools(mode="plan", ...)` is called once and returns the
   **plan-mode catalog** directly (sourced from `internal_tools_plan.json`
   + community-tool mode scoping). No runtime mode/phase filter is needed
   because the LangGraph entry-point split (`plan_agent` vs `work_agent`)
   makes mode resolution up-front.

## Phase 2 — First model cycle: planning

LangGraph kicks the run; middlewares run in topologically-sorted order
(see [work_agent/agent.py:491-560](../../backend/src/agents/work_agent/agent.py#L491-L560)
for the full spec list).

### 2a. `before_model` hooks (in order)

- `ThreadDataMiddleware` — creates per-thread workspace directory.
- `SteeringMiddleware` — drains any pending steering intents.
- `UploadsMiddleware` — injects newly uploaded files.
- `SandboxMiddleware` — acquires sandbox.
- `WorkModeMiddleware` — **not present** (plan mode).
- `PlanExecutionGateMiddleware` — passive at this stage (no plan yet).
- `PermissionMiddleware`, `ToolDisclosureMiddleware`, `HooksMiddleware` —
  declarative gating.
- `SummarizationMiddleware` — uses the `"plan"` mode override for
  trigger/keep thresholds.
- `SkillDisclosureMiddleware` — injects active skill bodies.
- **`PlannerMiddleware.before_model`** ← *the main event*.

### 2b. PlannerMiddleware fires

[planner_middleware.py:848](../../backend/src/agents/middlewares/planner_middleware.py#L848).

1. Check `_should_plan(state, runtime)`
   ([planner_middleware.py:733](../../backend/src/agents/middlewares/planner_middleware.py#L733)):
   - If a draft plan exists with a fresh user message → re-plan (capped at
     `_MAX_DRAFT_REVISIONS = 5`).
   - If no plan yet and there is at least 1 HumanMessage → plan.
   - In plan mode, allow planning even when prior AI turns exist.
2. Extract `user_prompt = original_user_prompt(messages)`.
3. **Direct-answer fast path** ([planner_middleware.py:863](../../backend/src/agents/middlewares/planner_middleware.py#L863)):
   - `_looks_like_direct_answer_request(user_prompt)` short-circuits
     checklists, comparisons, etc. — skips the planner LLM entirely for
     queries well-served by a single-shot response. (The legacy
     `_classify_complexity` tier system has been removed.)
4. Emit `planning_started` SSE.
5. **Call the planner LLM** with `PLANNER_SYSTEM_PROMPT`
   ([planner_middleware.py:202](../../backend/src/agents/middlewares/planner_middleware.py#L202)).
   The planner uses the same chat-selected model
   (`resolve_model_name(requested_model)` — single-model invariant).
6. Parse JSON output via `_parse_plan_response` into `PlannerOutput`.
   Tolerates markdown fences and falls back to per-line todos if JSON parse
   fails.
7. Normalize todos into DAG nodes via
   `normalize_todo_nodes` + `_materialize_ready_ids`.
8. Augment domain-specific clarifications via `_ensure_research_clarifications`
   (timeframe / scope for research-domain plans).
9. Decide plan_status:
   - `auto_mode AND not clarification_pending` → `"approved"` (auto-approve)
   - otherwise → `"draft"`
10. **Write `plan.md`** twice:
    - Versioned: `<workspace>/plans/plan-YYYYMMDD-HHMMSS-<slug>.md`
    - Latest alias: `<workspace>/plan.md`
    - Both use `serialize_plan_md(plan, todo_graph, body_renderer=render_plan_md)`
      so the frontmatter is canonical (`plan_version: 5`).
11. Emit `plan_created` SSE with inline clarifications so the frontend can
    render the popup directly.
12. Build the **`planner_handoff` ephemeral HumanMessage** describing the
    plan to the model on the next cycle.
13. If `should_spawn_work_handoff` (auto-mode + approved + no clarifications),
    call `spawn_work_mode_handoff` to fire the daemon-thread Work Mode
    handoff. If `plan_behavior == "plan_foreground"`, set `jump_to="end"`
    so the planner turn ends here.
14. Return the state update with `plan`, `todo_graph`, `todos`,
    `planner_ephemeral_handoff`, etc.

### 2c. PlanEvaluatorMiddleware

[plan_evaluator_middleware.py:223](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L223)
runs after the planner. It:

1. Skips trivial plans and already-evaluated ones.
2. Calls the planner model with `_PLAN_EVAL_PROMPT` under a hard timeout
   (`evaluator.plan_evaluator_timeout_seconds`, default 10s).
3. If issues are found AND `revised_todos` is structurally valid, rewrites
   the `todo_graph`. Otherwise keeps the original.
4. Sets `plan_evaluated=True` to short-circuit on subsequent cycles.

### 2d. Tool catalog (resolved up-front, not at runtime)

In the current architecture there is **no `PhaseToolFilterMiddleware` step
in Plan Mode**. The plan-mode tool catalog was already locked in at agent
build time by `get_available_tools(mode="plan", ...)` reading
`internal_tools_plan.json` (which excludes execution tools) and applying
community-tool mode scoping (`web_search` allowed, knowledge-vault tools
hidden). The LLM call goes out with the plan-mode catalog as bound; the
model cannot emit a tool call for `bash`/`write_file`/`task` etc. because
those tools were never registered on this graph.

`PlanExecutionGateMiddleware` ([plan_execution_gate_middleware.py:119](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L119))
acts as a runtime backstop: if a custom agent re-exposes an execution
tool, the gate blocks the call at `wrap_tool_call` time, and a
scope-vs-content classifier ([plan_execution_gate_middleware.py:107](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L107))
runs on `web_search` invocations to block content-gathering use.

### 2e. The LLM responds

In `plan_foreground` mode the planner middleware has already set
`jump_to="end"`, so the LLM **never runs this turn**. The frontend receives
`plan_created` SSE and renders the Execute-Plan popup.

If `plan_foreground` is not in effect (legacy/single-graph flow), the LLM
sees the `<planner_handoff>` system message and either drafts refinements
via `write_todos` / `ask_user_for_clarification` / `scope_search` or stops.

## Phase 3 — User interaction with the popup

Three branches:

### 3a. User answers a clarification inline

Frontend POSTs to `/api/threads/{id}/plan/clarify`
([steering.py:649](../../backend/src/gateway/routers/steering.py#L649)).
That endpoint:

1. Fetches current state via `client.threads.get_state`.
2. Validates the answer matches an existing option label.
3. Synthesizes a `HumanMessage(content=selected_option_label)`.
4. Calls `apply_clarification_progress(plan, messages + [prompt, answer])`
   to advance `clarification_index`.
5. Persists the new plan state + the synthetic answer in thread messages.

When the next planning turn fires, `PlannerMiddleware.before_model` sees
`clarification_pending=False` and either auto-approves (auto_mode) or stays
in draft awaiting the Execute Plan click.

### 3b. User edits `plan.md` directly

The on-disk `plan.md` is the canonical source. `PlanFileSyncMiddleware`
keeps it in sync after model turns
([plan_file_sync_middleware.py:52](../../backend/src/agents/middlewares/plan_file_sync_middleware.py#L52)),
but at handoff time `_load_canonical_plan_overrides`
([work_run_handoff.py:22](../../backend/src/agents/middlewares/work_run_handoff.py#L22))
re-reads the file from disk and parses it via `parse_plan_md`. If
`plan_version >= 5`, the parsed `(plan, todo_graph)` **override** the
checkpointed state on the Work Mode run.

### 3c. User clicks Execute Plan

Frontend POSTs to `/api/threads/{id}/plan/execute`
([steering.py:480](../../backend/src/gateway/routers/steering.py#L480)).
The endpoint:

1. Fetches current state.
2. Refuses if no plan exists or `plan_id` mismatches.
3. Handles `current_status` cases:
   - Already `approved`/`executing`/`completed`: dedupe via
     `execute_plan_should_duplicate`, or recover by creating a fresh Work
     Mode run.
   - `draft` + clarification still pending: returns `409 conflict`.
   - `draft` + ready: flips `status="approved"`, sets `approved_at`,
     marks handoff requested, updates `plan_history`.
4. Calls `_create_work_mode_run(client, thread_id, …)`
   ([steering.py:188](../../backend/src/gateway/routers/steering.py#L188))
   which registers a new run on the LangGraph Server with:
   - `assistant_id="work_agent"`
   - `input={"messages": [HumanMessage(name="execute_plan", content="<execute_plan/>")]}`
   - `context={"current_mode": "work", "plan_behavior": "work_interactive", auto_mode, …}`
5. Marks the plan with `mark_handoff_succeeded`.
6. Returns `{run_id, assistant_id}` so the frontend can subscribe to the
   Work Mode SSE stream.

## Phase 4 — Work Mode picks up the plan

The new run lands in `make_work_agent`. Mode resolution gives `"work"`, so
`WorkModeMiddleware` is constructed and `PlannerMiddleware` is not.

Notable handoff steps:

- The checkpointer-restored `plan` already has `status="approved"`.
- Tool catalog is now the Work catalog (`internal_tools_work.json` +
  full community tools), resolved up-front by
  `get_available_tools(mode="work", ...)`. `PhaseToolFilterMiddleware`
  applies a first-turn execution-tool gate only: if no plan exists and
  there is no prior AI message, execution tools are hidden so the LLM has
  to reason before acting. From turn 2 onward the full Work catalog is
  exposed. (After a Plan-Mode handoff, the plan exists, so the gate is a
  no-op.)
- `WorkModeMiddleware.before_model` finds the first ready todo via
  `_materialize_ready_ids`, emits `phase_started` SSE, and injects a
  `<work_mode_instruction>` HumanMessage instructing the model to execute
  that todo and emit no other text.
- The model executes the todo (often via subagent dispatch through `task`).
- Each cycle, `WorkModeMiddleware` detects newly-completed todos via
  set diff and emits `phase_completed` SSE.
- When all todos complete, the middleware returns `None`, letting the
  model produce the final user-facing summary.

## Phase 5 — Background plan file sync

After every Work Mode turn, `PlanFileSyncMiddleware.after_model`:

1. Detects a terminal AI response (no tool calls, has content).
2. Snapshots state and starts a daemon thread that sleeps 1s then calls
   `ensure_plan_state` + `sync_handoff_files_from_state`.
3. The on-disk `plan.md` stays current with `status="executing"`,
   completed todos, etc.

This ensures the user-visible `plan.md` always matches reality even if a
run is interrupted.

## Plan stalls — Work Mode signals, user decides

Work Mode **does not** auto-escalate into Plan Mode anymore. Both the
legacy complexity-based escalation (`_classify_complexity` /
`_handle_complexity_escalation` / `_spawn_plan_rerun`) and the auto-mode
plan-adaptation respawn (`_MAX_AUTO_ADAPTATION_ATTEMPTS`) have been
removed from `work_mode_middleware.py`. The only entry to Plan Mode is
the manual toggle in the input box (Phase 0 above).

When Work Mode encounters a stalled plan — pending todos remain but none
are ready (typically because every remaining todo is `blocked`) —
[`WorkModeMiddleware._handle_plan_adapted`](../../backend/src/agents/middlewares/work_mode_middleware.py#L463-L503)
runs:

1. Inspect `todo_graph.nodes`; collect IDs of `blocked` todos.
2. Increment `phase_execution.adaptation_attempts` (kept as a diagnostic
   so repeated stalls are visible in state).
3. Emit a `plan_adapted` SSE event with shape:

   ```json
   {
     "type": "plan_adapted",
     "source": "work_mode_middleware",
     "blocked_ids": ["todo-3", "todo-5"],
     "message": "2 pending todo(s) have unmet dependencies. Switch to Plan Mode to revise the plan.",
     "adaptation_attempt": 1
   }
   ```

4. Return `phase_execution.plan_adapted = True` and stop the work loop.

The frontend renders this SSE as a "plan is stuck — revise?" prompt. The
**user** then decides whether to flip the input box back to Plan Mode and
re-submit; no daemon re-spawns Plan Mode automatically.
