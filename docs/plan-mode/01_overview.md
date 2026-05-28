# 01 — Overview

## What is Plan Mode?

Plan Mode is one of two **runtime modes** in CapyHome (the other being Work
Mode). Both run on a shared agent factory and middleware registry; what
differs is:

- Which prompt overlay is applied
- Which middlewares activate
- Which tool catalog is served to the LLM
- What the agent is *supposed to produce*

In Plan Mode, the agent's **single deliverable is a `plan.md` file** — a
canonical, structured handoff artifact that a subsequent Work Mode run will
parse and execute. The agent is explicitly told **not** to produce the user's
answer; it scopes the work, drafts todos with dependencies, asks
clarifications when scope is ambiguous, and stops.

## Why a separate mode?

The original architecture had a single `lead_agent` with conditional plan
behavior. The refactor split it into two LangGraph entry points so that:

1. The frontend can address `plan_agent` **by name**
   (`graph_id="plan_agent"`) in `langgraph.json`.
2. Plan-mode discipline (prompt + middleware + tool catalog) is reified —
   you cannot accidentally run plan logic against the `work_agent` graph or
   vice-versa.
3. Mode-based tool filtering is **resolved up-front at agent build time**
   (different graphs read different JSON catalogs) rather than at runtime
   via middleware. Plan-status transitions (`draft` → `approved`) are
   inter-graph: `plan_agent` terminates and `work_agent` spawns.
4. A future divergence (fully separate prompt body, narrower tool surface)
   can happen without touching `work_agent`.

Today `plan_agent` is a **thin wrapper** around `_build_work_agent` that
forces `current_mode="plan"` and injects the plan-mode prompt template
([plan_agent/agent.py:29-41](../../backend/src/agents/plan_agent/agent.py#L29-L41)).
The middleware registry inside `_build_work_agent` conditionally activates
plan-mode middlewares (`PlannerMiddleware`, `PlanEvaluatorMiddleware`,
`PlanExecutionGateMiddleware`, `PlanFileSyncMiddleware`, `TodoDagMiddleware`)
when `is_plan_mode=True`.

## High-level lifecycle

```
┌────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ User input │ →  │ User toggles │ →  │ plan_agent   │ →  │ plan.md      │
│ (chat)     │    │ Plan Mode    │    │ run          │    │ (canonical)  │
└────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                                                                 │
                                                                 ▼
                                                          ┌─────────────────┐
                                                          │ User reviews    │
                                                          │ (Execute Plan / │
                                                          │  Clarify popup) │
                                                          └─────────────────┘
                                                                 │
                                                       approve   │
                                                                 ▼
                                                          ┌─────────────────┐
                                                          │ work_agent run  │
                                                          │ (parses plan.md │
                                                          │  + executes)    │
                                                          └─────────────────┘
```

## Three states a plan can be in

`plan.status` ∈ `{"draft", "approved", "executing", "completed"}`
([work_mode_middleware.py:74](../../backend/src/agents/middlewares/work_mode_middleware.py#L74)).

- **`draft`** — Planner has written `plan.md`. LLM is gated from execution
  tools. Clarifications may be pending. Re-planning is allowed (capped at
  `_MAX_DRAFT_REVISIONS = 5`,
  [planner_middleware.py:731](../../backend/src/agents/middlewares/planner_middleware.py#L731)).
- **`approved`** — Either (a) the user clicked **Execute Plan** in the UI
  and `/api/threads/{id}/plan/execute` flipped the status, or (b)
  `auto_mode=True` + no pending clarifications caused the planner to
  auto-approve on creation. A Work Mode run is spawned.
- **`executing`** — Work Mode has started; `WorkModeMiddleware` drives the
  todo loop.
- **`completed`** — All todos closed; final summary emitted.

## Entry to Plan Mode is user-initiated only

Plan Mode is entered **manually via the UI** (Shift+Tab or the toolbar
chip). Work Mode **never auto-escalates** into Plan Mode — both the legacy
complexity-based escalation and the auto-mode plan-adaptation respawn
(`_spawn_plan_rerun` / `_MAX_AUTO_ADAPTATION_ATTEMPTS`) have been removed.

### Manual toggle (the only path)

The input-box toolbar exposes a Plan-Mode chip inside a dropdown
([input-box-left-toolbar.tsx:146-170](../../frontend/src/components/workspace/input-box-left-toolbar.tsx#L146-L170)).
Clicking it flips `settings.context.mode` to `"plan"`
([input-box.tsx:505-554](../../frontend/src/components/workspace/input-box.tsx#L505-L554)).

On send, the thread hook posts to LangGraph with:

```json
{
  "configurable": {
    "current_mode": "plan",
    "mode": "plan",             // legacy dual-write
    "is_plan_mode": true,       // legacy dual-write
    "plan_behavior": "plan_foreground"
  }
}
```

Modern clients address the `plan_agent` graph directly by name.
`make_plan_agent` re-writes these keys defensively so a caller that
addresses the graph by name without setting `mode` still gets plan-mode
behavior ([plan_agent/agent.py:30-37](../../backend/src/agents/plan_agent/agent.py#L30-L37)).

### Plan stalls emit `plan_adapted` (UI surfaces, user decides)

When Work Mode encounters a plan with no ready todos but pending ones
remain (typically because every remaining todo is `blocked`),
[`WorkModeMiddleware._handle_plan_adapted`](../../backend/src/agents/middlewares/work_mode_middleware.py#L463-L503)
emits a `plan_adapted` SSE event with the blocked todo IDs and an
`adaptation_attempts` counter. The UI surfaces this stall and **the user
decides** whether to switch back to Plan Mode and revise. No daemon
re-spawns Plan Mode automatically.

## What Plan Mode is NOT

- **Not** an alternative chat mode for "structured answers". It produces a
  plan, not the answer. The plan-mode prompt explicitly tells the LLM to
  suppress training-data answers
  ([plan_agent/prompt.py:37-48](../../backend/src/agents/plan_agent/prompt.py#L37-L48)).
- **Not** an unrestricted research surface. The tool catalog served to
  Plan Mode is [`internal_tools_plan.json`](../../backend/src/tools/internal_tools_plan.json),
  which excludes execution tools (`bash`, `write_file`, `str_replace`,
  `task`). Community tools are mode-scoped at load time by
  `_COMMUNITY_TOOL_MODES` in [`tools/tools.py`](../../backend/src/tools/tools.py)
  — `web_search` is available in all modes, knowledge-vault tools are
  work-only. The legacy `scope_search` wrapper is deprecated;
  `web_search` is exposed directly in Plan Mode. The plan-mode prompt
  still names `scope_search` as the conceptual "scope discovery" tool
  ([prompt.py:65](../../backend/src/agents/plan_agent/prompt.py#L65)), but
  the underlying handler is `web_search`.
- **Not** filtered at runtime by `PhaseToolFilterMiddleware`. That
  middleware was previously responsible for hiding execution tools in
  Plan Mode; today its only remaining job is a Work-Mode first-turn
  execution-tool gate (no plan, no prior AI message → execution tools
  hidden so the LLM has to reason before acting). Mode/plan-status
  filtering is resolved up-front by per-mode catalog selection in
  [`get_available_tools`](../../backend/src/tools/tools.py).
- **Not** the trivial fast path. Trivial requests skip the planner LLM via
  [`_looks_like_direct_answer_request`](../../backend/src/agents/middlewares/planner_middleware.py#L473)
  in `planner_middleware.py`.
