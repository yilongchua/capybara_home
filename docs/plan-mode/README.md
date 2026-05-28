# Plan Mode — Architectural Analysis

This folder documents the **Plan Mode** flow in CapyHome end-to-end: from the user
typing a request, through trigger resolution, mode resolution, middleware
activation, planner LLM call, plan-gate enforcement, plan approval, and
finally the handoff into Work Mode for execution.

It reflects the state of the codebase on **2026-05-28** after the
`plan_agent` / `work_agent` graph split, the canonical `plan.md` handoff
(`plan_version: 5`), the removal of Work→Plan auto-escalation
(`_spawn_plan_rerun` / `_classify_complexity` /
`_MAX_AUTO_ADAPTATION_ATTEMPTS`), and the move to per-mode JSON tool
catalogs (`internal_tools_plan.json` / `internal_tools_work.json`) which
replaced runtime mode/phase filtering in `PhaseToolFilterMiddleware`.

## Files in this folder

- [`README.md`](README.md) — this index
- [`01_overview.md`](01_overview.md) — what Plan Mode is, why it exists,
  the manual-only entry path, the `plan_adapted` stall signal, and the
  high-level lifecycle.
- [`02_components.md`](02_components.md) — exhaustive inventory of every
  prompt, middleware, tool, skill, route and helper involved in Plan Mode.
- [`03_flow_narrative.md`](03_flow_narrative.md) — step-by-step narrative of
  a single Plan Mode turn end-to-end with file:line references.
- [`04_handoff_contract.md`](04_handoff_contract.md) — the canonical
  `plan.md` schema and how `plan_agent → work_agent` exchange state.
- [`plan_mode_flow.png`](plan_mode_flow.png) — visual flow diagram (rendered
  from [`plan_mode_flow.mmd`](plan_mode_flow.mmd) source).
- [`plan_mode_flow.mmd`](plan_mode_flow.mmd) — Mermaid source for the diagram.

## TL;DR

Plan Mode is a **dedicated LangGraph entry point** (`plan_agent`, registered
in [backend/langgraph.json](../../backend/langgraph.json#L7)) that shares
all infrastructure with `work_agent` but:

1. **Forces** `current_mode="plan"` in `config.configurable` so mode-aware
   middlewares activate ([plan_agent/agent.py:29-41](../../backend/src/agents/plan_agent/agent.py#L29-L41)).
2. **Overrides** the system prompt to append `PLAN_MODE_SECTION`
   ([plan_agent/prompt.py:18-89](../../backend/src/agents/plan_agent/prompt.py#L18-L89)).
3. **Serves a restricted tool catalog** at agent build time:
   `get_available_tools(mode="plan", ...)` reads
   [`internal_tools_plan.json`](../../backend/src/tools/internal_tools_plan.json)
   which excludes execution tools (`bash`, `write_file`, `str_replace`,
   `task`). Community tools are mode-scoped by `_COMMUNITY_TOOL_MODES`
   ([tools/tools.py](../../backend/src/tools/tools.py)) — `web_search` is
   available in all modes, knowledge-vault tools are work-only. The
   legacy `scope_search` wrapper is deprecated. `PhaseToolFilterMiddleware`
   no longer mediates mode filtering.
4. **Runs the planner LLM** in [`PlannerMiddleware.before_model`](../../backend/src/agents/middlewares/planner_middleware.py#L848)
   on the first eligible turn, producing a structured `PlannerOutput` that
   is serialized to canonical `plan.md` via
   [`serialize_plan_md`](../../backend/src/agents/common/handoff.py#L32).
5. **Backstops** any execution tool that slips past the catalog at
   `wrap_tool_call` time via
   [`PlanExecutionGateMiddleware`](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L119).
6. **Optionally** evaluates plan quality with
   [`PlanEvaluatorMiddleware`](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L330).
7. **Persists** `plan.md` (latest alias + timestamped version) to
   `/mnt/user-data/workspace/` via
   [`PlanFileSyncMiddleware`](../../backend/src/agents/middlewares/plan_file_sync_middleware.py).
8. **Hands off** to Work Mode when the user clicks **Execute Plan**
   ([gateway/routers/steering.py:480](../../backend/src/gateway/routers/steering.py#L480))
   or when the planner auto-approves (auto_mode + no pending clarifications).

## One way to enter Plan Mode

Plan Mode is reachable through a **single trigger**:

| Trigger | Source | Path |
|---|---|---|
| Manual toggle | User clicks the Plan-Mode chip in the input toolbar | [frontend/src/components/workspace/input-box.tsx:505-554](../../frontend/src/components/workspace/input-box.tsx#L505-L554) → sets `context.mode = "plan"` → LangGraph SDK posts to `plan_agent` graph |

Work Mode **no longer auto-escalates** into Plan Mode. The previous
complexity-based escalation (`_classify_complexity` /
`_handle_complexity_escalation` / `_spawn_plan_rerun`) and the auto-mode
plan-adaptation respawn (`_MAX_AUTO_ADAPTATION_ATTEMPTS`) have been
removed. When a plan stalls (pending todos exist but none are ready),
[`WorkModeMiddleware._handle_plan_adapted`](../../backend/src/agents/middlewares/work_mode_middleware.py#L463)
emits a `plan_adapted` SSE so the UI can prompt the user to switch back
to Plan Mode; the user decides whether to revise.
