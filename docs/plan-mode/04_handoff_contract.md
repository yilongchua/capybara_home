# 04 — Plan ↔ Work Handoff Contract

The handoff between Plan Mode and Work Mode is mediated by **two parallel
sources of truth**: the in-memory `ThreadState` (LangGraph checkpoint) and
the on-disk `plan.md`. Either can be authoritative; the handoff code
prefers the file when it carries a canonical frontmatter so user edits
between approval and execution are honored.

## The canonical `plan.md` format (`plan_version: 5`)

Serializer: [`serialize_plan_md`](../../backend/src/agents/common/handoff.py#L32).
Parser: [`parse_plan_md`](../../backend/src/agents/common/handoff.py#L84).

```yaml
---
plan_version: 5
plan_id: plan-a1b2c3d4e5
title: Compare soba shops between Singapore and Tokyo
status: draft               # draft | approved | executing | completed
domain: research            # code | research | legal | trip | generic
target_mode: work
created_at: 2026-05-27T03:14:15Z
last_synced_at: 2026-05-27T03:14:30Z
objective: |
  Identify the top soba shops in each city and compare them on dimensions
  selected by the user.
summary: |
  Two-pass research plan that fans out per-city investigation, then synthesizes
  a comparison report.
assumptions:
  - English-language sources are sufficient
constraints:
  - No site visits / phone calls
risks:
  - risk: source sparsity for niche shops
    mitigation: fall back to aggregator sites; label confidence
acceptance_criteria:
  - At least 5 shops per city
  - Side-by-side comparison on 3+ dimensions
todos:
  - id: todo-1
    content: Identify top-rated soba shops in Singapore
    status: pending
    depends_on: []
    rationale: …
    objective: …
    failure_fallback: …
    owner: lead
    subagent_type: source-researcher
    steps:
      - description: Web search for candidates
        completion_requirement: candidates_sg.md contains at least 8 entries
todo_ready_ids: [todo-1, todo-2]
clarifications: []
clarification_answers: []
clarification_pending: false
clarification_resolved: true
total_todos: 4
completed_todos: 0
---

# Compare soba shops between Singapore and Tokyo
…human-readable body produced by render_plan_md…
```

The body is **regenerated** on every write from the frontmatter via
`body_renderer`. The parser ignores the body entirely.

## State carried across the handoff

| ThreadState field | Authoritative source after handoff |
|---|---|
| `plan` | `parse_plan_md` if present and canonical; else checkpoint |
| `todo_graph` | Same as above |
| `todos` | Derived from `todo_graph.nodes` via `_legacy_todos` |
| `plan_history` | Checkpoint (carries the trace of revisions) |
| `messages` | Checkpoint (full conversation transcript) |
| `thread_data`, `sandbox`, `artifacts` | Checkpoint |

`_load_canonical_plan_overrides`
([work_run_handoff.py:22](../../backend/src/agents/middlewares/work_run_handoff.py#L22))
is what makes file-on-disk authoritative at handoff time. It:

1. Reads `plan.latest_alias_path` (virtual path) and resolves to physical
   via `replace_virtual_path(thread_data)`.
2. Loads file bytes; if missing, returns `{}` and the checkpoint stays
   authoritative.
3. Calls `parse_plan_md`. If the file's `plan_version < 5`, returns `{}`.
4. Carries forward runtime-only fields (`plan_path`, `latest_alias_path`,
   `execution_requested_at`, `approved_at`, …) so the disk overrides don't
   clobber them.

## Two handoff entry points

### A. Gateway-driven (user-clicked Execute Plan)

Path: `POST /api/threads/{id}/plan/execute` →
[`steering.execute_plan`](../../backend/src/gateway/routers/steering.py#L480) →
[`_create_work_mode_run`](../../backend/src/gateway/routers/steering.py#L188).

The endpoint:

1. Marks `plan.status="approved"` in checkpoint state via
   `client.threads.update_state`.
2. Registers a fresh `work_agent` run via `client.runs.create` with
   `_WORK_MODE_TRIGGER_CONTENT = "<execute_plan/>"`.
3. Returns `{run_id, assistant_id}` so the frontend can `useRejoinRunningRun`.

This path is **synchronous** from the user's perspective and used by the
manual approval flow.

### B. Daemon-driven (auto-approval / auto-escalation)

Path: `PlannerMiddleware.before_model` →
[`spawn_work_mode_handoff`](../../backend/src/agents/middlewares/work_run_handoff.py#L317).

Triggered when `auto_mode=True` AND no pending clarifications. The daemon:

1. Sleeps briefly so the planning run reaches its checkpoint.
2. Constructs an embedded `CapyHomeClient` with `plan_mode=False`.
3. Calls `_get_runnable_config` with `current_mode="work"`,
   `plan_behavior="work_interactive"`.
4. Reads thread state, formats `<clarification_resolved>` block, calls
   `_load_canonical_plan_overrides` to honor disk edits.
5. Calls `invoke_client_agent_async` which streams the new Work Mode run
   on the same thread.
6. Retries up to `handoffs.work_handoff_retry_attempts` (default 1) and
   bounds total recursion via `handoffs.work_handoff_recursion_limit`.

Concurrency guard: `_IN_FLIGHT_HANDOFFS` set + `_HANDOFF_GUARD` lock
prevent duplicate handoffs for the same thread
([work_run_handoff.py:18-19](../../backend/src/agents/middlewares/work_run_handoff.py#L18-L19)).

## Work → Plan re-runs (removed)

Work Mode **no longer spawns Plan Mode re-runs automatically**. The
historical `_spawn_plan_rerun` daemon, the `complexity_escalation`
classification, and the `_MAX_AUTO_ADAPTATION_ATTEMPTS` cap have all been
removed from `work_mode_middleware.py`. The graph never auto-flips
direction.

What remains is a one-way SSE signal:

- When Work Mode encounters a stalled plan (pending todos but none
  ready),
  [`WorkModeMiddleware._handle_plan_adapted`](../../backend/src/agents/middlewares/work_mode_middleware.py#L463-L503)
  emits a `plan_adapted` event carrying the blocked todo IDs and an
  `adaptation_attempts` counter, and writes
  `phase_execution.plan_adapted = True` to state.
- The frontend surfaces this as a "plan is stuck — switch back to Plan
  Mode?" prompt.
- The **user** decides whether to flip the input box to Plan Mode and
  re-submit. There is no daemon, no embedded-client re-entry, no auto
  synthesis of a Plan-Mode prompt from the backend.

## Clarification round-trips

Clarifications can be answered in three ways, all converging on the same
`apply_clarification_progress` state machine
([middlewares/plan_execution.py](../../backend/src/agents/middlewares/plan_execution.py)):

1. **Inline popup** — `/plan/clarify` synthesizes the `HumanMessage` and
   advances `clarification_index`.
2. **Free-form chat** — user types a reply; the next planner cycle detects
   the answer via `apply_clarification_progress(plan, messages)`.
3. **`ask_user_for_clarification` tool** — model in plan mode calls the
   builtin tool; `ClarificationMiddleware` interrupts the run via
   `Command(goto=END)`. The frontend renders the popup; user reply
   resumes via LangGraph `Command(resume=…)`.

In all cases, the resolved plan re-enters `PlannerMiddleware.before_model`
on the next turn for either auto-approval (auto_mode) or continued draft
state.
