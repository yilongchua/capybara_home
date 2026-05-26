# Plan Mode Audit: Implemented Fixes (Final)

Audit thread reference: `a73a4607-ab65-49d4-af18-66bb16b56c56` (Singapore vs Tokyo soba comparison).

This document records the **final implemented fixes** after independent review and follow-up remediation.

---

## Fix 1 — Clarification deadlock in draft plans (UI + state flow)

**Problem:** Draft plans with `clarification_pending=true` could block Execute Plan without a usable inline clarification path.

**Final fix:**
- Kept clarification state authoritative (no silent backend auto-clear).
- Added frontend inline clarification handling inside the plan popup:
  - show clarification question/options when pending
  - submit answer to `/api/threads/{thread_id}/plan/clarify`
  - update local clarification state and continue gating until resolved
- Execute Plan remains gated while clarification is pending.

**Files changed:**
- `frontend/src/app/workspace/chats/[thread_id]/page.tsx`
- `frontend/src/components/workspace/execute-plan-popup.tsx`
- `frontend/src/core/dreamy/api.ts`
- `frontend/src/core/threads/hooks.ts`

---

## Fix 2 — Removed unsafe clarification auto-clear

**Problem:** A backend patch cleared `clarification_pending` when `ask_clarification` tool was not called, which could bypass intended user input.

**Final fix:**
- Removed this auto-clear behavior from planner middleware.
- Clarification state now advances only through explicit clarification resolution flow.

**Files changed:**
- `backend/src/agents/middlewares/planner_middleware.py`

---

## Fix 3 — Strict draft todo ID validation

**Problem:** Draft todo validation accepted any ID starting with `todo-` (e.g., `todo-foo`).

**Final fix:**
- Enforced regex `^todo-\d+$` for draft plan todo IDs in plan mode.
- Invalid IDs are rejected with `validation_failed` and explicit error text.

**Files changed:**
- `backend/src/tools/builtins/write_todos_tool.py`

---

## Fix 4 — Planner prompt no longer forces filler todos

**Problem:** Prompt required exactly `{max_steps}` todos, encouraging low-value filler steps.

**Final fix:**
- Updated prompt rule to: generate **up to** `{max_steps}` todos.
- Explicitly disallowed filler todos to hit count targets.

**Files changed:**
- `backend/src/agents/middlewares/planner_middleware.py`

---

## Fix 5 — Evaluator skip telemetry renamed semantically

**Problem:** Event label implied draft-specific skipping when the condition was actually incomplete todos.

**Final fix:**
- Renamed decision event to `evaluation_skipped_incomplete_todos`.

**Files changed:**
- `backend/src/agents/middlewares/evaluator_middleware.py`

---

## Previously Implemented/Retained Fixes

The following fixes remain in place from the earlier patch set:

1. `save_to_knowledge_vault` hidden during draft plan mode.
   - `backend/src/agents/middlewares/phase_tool_filter_middleware.py`
2. Memory injection relevance tightened (`injection_relevance_threshold=0.5`) with stricter context-fact gating.
   - `backend/src/config/memory_config.py`
   - `backend/src/agents/memory/prompt.py`
3. `max_clarifications` made configurable and threaded through planner flow.
   - `backend/src/config/planner_config.py`
   - `backend/src/agents/lead_agent/agent.py`
   - `backend/src/agents/middlewares/planner_middleware.py`
4. Plan rendering now includes clarifications/Q&A and removes “Execution Notes & Insights”.
   - `backend/src/agents/middlewares/handoff_sync.py`

---

## Net Behavior After Final Fixes

1. Draft plan with clarifications now surfaces actionable clarification UI.
2. Clarification state is not silently bypassed.
3. Execute Plan appears only after clarification resolution.
4. Draft todo IDs are strictly normalized (`todo-<number>`).
5. Planner produces concise, non-padded todo sets.
6. Evaluator telemetry now reflects actual skip reason.

