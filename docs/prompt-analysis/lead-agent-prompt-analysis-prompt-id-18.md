# Lead Agent Prompt Analysis — PROMPT_ID_18

> **Scope:** Analysis of cycle 1 (9 turns) and cycle 2 (12 turns) prompt logs for PROMPT_ID_18, cross-referenced with `backend/src/agents/lead_agent/prompt.py`, `memory/prompt.py`, and all related middleware prompt surfaces.
>
> **Test prompt:** "Create a 6 month learning plan for becoming employable in machine learning engineering. Assume I know Python but not much math. Include projects, milestones, and how to prove skill."
>
> **Model:** `mlx-community/qwen3.6-35b-a3b` (local qwen3.6)
>
> **Mode:** `work`, `auto_mode: true`

---

## Executive Summary

PROMPT_ID_18 exposes **five systemic prompt failures** in the lead agent orchestration pipeline:

1. **Clarification deadlock** — planner generates useless clarifications that block execution; model refuses to ask them; system won't proceed without them
2. **Empty response epidemic** — 9 out of 21 total turns across both cycles produce blank AI responses
3. **Memory bloat and stripping** — 200+ lines of irrelevant user context in initial turn, then silently stripped in execution turns
4. **Quality gate prompt misalignment** — gate expects `executive_summary` section that the system prompt never instructs the model to produce
5. **Dead subagent/todo instructions** — extensive prompt sections for `task()` and `write_todos` that the model never uses

The model *can* produce a quality answer (cycle 2, file 011) when it finally breaks through the gates, but the path to get there wastes ~8 minutes and 12 turns of retries.

---

## 1. Cycle 1 Analysis (9 turns, ~3.5 min)

### 1.1 Execution Flow

| Turn | What Happened | Key Observation |
|------|--------------|-----------------|
| 001 | Initial lead agent invocation | Full system prompt (~767 lines) + 200-line irrelevant `<memory>` block injected |
| 002 | Planner JSON schema prompt | Separate model call, no tools, no memory — pure JSON generation |
| 003 | Title generation | Utility prompt, 2.5 min gap from 002 |
| 004 | First execution turn | **Quality gate failure**: `duplicate_table_rows`, `missing_required_sections:executive_summary`. Empty AI response. |
| 005 | Retry with `write_todos` hint | `<memory>` block removed. **Same quality gate failure persists**. |
| 006 | Files presented | **Same quality gate failure** (3rd occurrence). Empty AI response. |
| 007 | Planner re-injected | **Same quality gate failure** (4th occurrence). |
| 008 | Planner re-injected again | Model finally produces visible text: "The plan is already written..." **Same failure** (5th). |
| 009 | Final turn with file listing | Model acknowledges existing files, lists workspace. **Same failure** (6th). |

### 1.2 Critical Findings

**Quality gate failures (6/6 execution turns):** The same two failures appeared every time:
- `duplicate_table_rows` — qwen3.6-35B struggles with markdown table consistency (known LLM artifact)
- `missing_required_sections:executive_summary` — the system prompt never instructs the model to produce this section; this is a prompt-to-gate alignment bug

**Fail-forward masked the problem:** The system kept retrying instead of stopping and fixing the root cause. The quality gate was non-blocking, so the loop continued indefinitely.

**No subagent utilization:** Despite extensive `<subagent_system>` instructions (max 3 parallel tasks, decomposition strategies, batch planning), the model never used the `task` tool once.

**No `write_todos` usage:** Despite the hint added in turn 005, the model never called `write_todos`.

### 1.3 What Changed Between Turns

| Change | Impact |
|--------|--------|
| Memory block removed (004→005) | Reduced context noise, **no improvement** in quality gate results |
| `write_todos` hint added (005) | **No effect** — model never used it |
| Planner re-injected (006→009) | Model eventually recognized plan existed and presented it |

---

## 2. Cycle 2 Analysis (12 turns, ~8 min)

### 2.1 Execution Flow

| Turn | What Happened | Key Observation |
|------|--------------|-----------------|
| 001 | Initial prompt injection | Full system prompt + `<memory>` block present |
| 002 | Planner JSON generation | Separate prompt, no system context |
| 003 | First execution after planning | **Planner generated useless clarification**: "What is the subject of the previous user request?" — nonsensical for an ML plan request. `<memory>` block stripped. |
| 004 | Title generation | Utility prompt |
| 005 | First execution attempt | **Empty AI response**. Quality gate: `missing_required_sections:executive_summary` |
| 006 | Retry after quality gate | **Empty AI response again**. Planner prompt re-injected. |
| 007 | Files presented | **Empty AI response**. Files somehow presented (background process?). |
| 008 | Planner re-injected (2nd time) | **Empty AI response**. Looping behavior confirmed. |
| 009 | Model tries to bypass clarification gate | Model: "I have everything I need..." → **Blocked by plan_gate** twice. |
| 010 | Stuck in clarification loop | **Empty AI response**. Blocked by plan_gate twice more. **Deadlock**. |
| 011 | **Breakthrough** | Model produces well-structured 6-month plan. But evaluator catches: `todo-1` never marked completed. |
| 012 | Final attempt | **Empty AI response**. Still blocked by plan_gate. Plan never formally completed. |

### 2.2 Critical Findings

**Clarification deadlock (turns 009-012):** The planner generated a generic clarification ("What is the subject?") that was meaningless for this self-evident request. The model correctly identified it had enough information but the `plan_gate` blocked execution. This is a **fundamental instruction conflict**:
- `<clarification_system>` says: "Default: attempt with a stated assumption. Ask only when genuinely blocked."
- `plan_gate` says: "Clarification is required before plan execution. Call `ask_clarification` first."

**Empty response epidemic (6/12 turns):** Turns 005, 006, 007, 008, 010, 012 all show blank AI responses. This suggests the model is confused by conflicting instructions or the prompt is too long/complex.

**Memory stripping regression:** `<memory>` block present in turn 001, absent from turns 003+. This is a regression from cycle 1 where memory was at least present in the first turn.

**Todo lifecycle broken:** Evaluator caught that `todo-1` was never marked as completed. The model bypassed the entire todo lifecycle.

**Planner comprehension failure:** The planner's generic clarification question shows it has no understanding of the actual request. The planner prompt (`PLANNER_SYSTEM_PROMPT` in `planner_middleware.py`) asks for clarifications but provides no guidance on when clarifications are actually needed vs. when the request is self-evident.

---

## 3. Cross-Cycle Comparison

### 3.1 Issues Resolved

| Issue | Cycle 1 | Cycle 2 |
|-------|---------|---------|
| Quality gate active | ✅ Working | ✅ Working |
| File presentation | ✅ Working | ✅ Working |
| Model produces answer | ✅ Eventually | ✅ Eventually (turn 011, better quality) |

### 3.2 Issues Persistent or Regressed

| Issue | Cycle 1 | Cycle 2 | Severity |
|-------|---------|---------|----------|
| Empty AI responses | 3/9 turns | 6/12 turns | **Critical** |
| Quality gate `executive_summary` mismatch | Persistent | Persistent | **Critical** |
| `duplicate_table_rows` | Persistent | Resolved (not seen in cycle 2) | Medium |
| Planner useless clarification | Not observed | **New** — "What is the subject?" | **Critical** |
| Clarification deadlock | Not observed | **New** — plan_gate vs clarification_system conflict | **Critical** |
| Memory stripping | Removed mid-cycle | Stripped from turn 003+ | **High** |
| Todo lifecycle broken | Not used | Used but not completed | **Medium** |
| Planner re-injection looping | 4x re-injections | 3x re-injections | **High** |
| Subagent dead code | Never used | Never used | **Low** |

### 3.3 Runtime Comparison

| Metric | Cycle 1 | Cycle 2 |
|--------|---------|---------|
| Duration | ~3.5 min | ~8 min |
| Total turns | 9 | 12 |
| Quality gate failures | 6 | 4 (but different pattern) |
| Empty responses | 3 | 6 |
| Final answer quality | Good | Better (more structured) |

---

## 4. Root Cause Analysis by Prompt Surface

### 4.1 `lead_agent/prompt.py` — System Prompt Construction

**File:** `backend/src/agents/lead_agent/prompt.py`

**Issues found:**

1. **Massive system prompt (~767 lines):** The `LEGACY_SYSTEM_PROMPT_TEMPLATE` concatenates: `<role>`, `<soul>`, `<memory>`, `<thinking_style>`, `<clarification_system>`, `<skill_system>`, `<subagent_system>`, `<working_directory>`, `<fetch_policy>`, `<response_style>`, `<citations>`, `<critical_reminders>`. For a 35B local model, this is excessive context that dilutes instruction following.

2. **`<clarification_system>` conflicts with `plan_gate`:** The clarification section says "Default: attempt with a stated assumption" but the planner middleware's clarification gate blocks execution. These two surfaces have contradictory semantics.

3. **Subagent section is dead weight:** The `_build_subagent_section()` function generates ~150 lines of detailed subagent orchestration instructions that the model never follows. The model never uses `task()` in either cycle.

4. **No `executive_summary` instruction:** The system prompt never tells the model to produce an `executive_summary` section, yet the quality gate expects it. This is a direct prompt-to-gate misalignment.

5. **Componentized mode duplicates content:** `_build_componentized_prompt()` assembles the same sections from individual templates (`ROLE_SECTION_TEMPLATE`, `THINKING_STYLE_SECTION_TEMPLATE`, etc.) — these are near-identical to the legacy template strings, creating maintenance debt.

6. **`_inject_memory_context()` is fragile:** Uses string replacement on `<thinking_style>` marker. If the marker changes or the prompt structure changes, memory injection silently fails.

### 4.2 `memory/prompt.py` — Memory Bloat

**File:** `backend/src/agents/memory/prompt.py`

**Issues found:**

1. **Memory content is 200+ lines of irrelevant context:** Tasmania trips, Dutch politics, crystals, legal cases, coffee brewing — none relevant to an ML learning plan. The `format_memory_for_injection()` function doesn't filter by relevance to the current request.

2. **Memory stripping between turns:** The `<memory>` block is present in the initial turn but absent in subsequent execution turns. This suggests `_inject_memory_context()` is only called once during initial prompt construction, not on re-invocations.

3. **`MEMORY_UPDATE_PROMPT` is overly complex:** The memory update prompt has detailed section guidelines (workContext, personalContext, topOfMind, recentMonths, etc.) that produce verbose output. This contributes to the bloat.

4. **No relevance scoring:** Memory facts are injected wholesale without scoring against the current user request. A simple keyword or embedding-based relevance filter would reduce noise significantly.

### 4.3 `planner_middleware.py` — Planner Prompt

**File:** `backend/src/agents/middlewares/planner_middleware.py`

**Issues found:**

1. **`PLANNER_SYSTEM_PROMPT` generates useless clarifications:** The prompt says "Only ask for clarification when a missing detail would fundamentally change the plan" but provides no concrete guidance on what constitutes a "fundamental" gap. The model produced "What is the subject?" — a generic fallback indicating it couldn't parse the request.

2. **No self-evident request detection:** The planner should recognize when a request is self-contained (like "Create a 6 month ML learning plan") and skip clarifications entirely.

3. **Clarification injected as blocking gate:** The planner's clarifications become hard gates (`plan_gate`) that block all execution. This is too aggressive for non-critical clarifications.

4. **Research fan-out is opt-in and unused:** The `research_fanout` feature detects independent ready todos for parallel dispatch but is disabled by default.

### 4.4 `plan_evaluator_middleware.py` — Plan Evaluator

**File:** `backend/src/agents/middlewares/plan_evaluator_middleware.py`

**Issues found:**

1. **`_PLAN_EVAL_PROMPT` is too lenient:** "Be lenient — only flag genuine blockers, not stylistic preferences." This is appropriate but the prompt only checks for 3 things (circular deps, missing prerequisites, missing synthesis). It doesn't check for planner comprehension failures like useless clarifications.

2. **Timeout handling:** Uses `asyncio.wait_for` with configurable timeout. If the planner already consumed the cycle's budget, the evaluator times out (`decision=timeout_skipped`).

### 4.5 `evaluator_middleware.py` — Terminal Evaluator

**File:** `backend/src/agents/middlewares/evaluator_middleware.py`

**Issues found:**

1. **`_EVALUATOR_PROMPT_TEMPLATE` is minimal:** Only 3 lines: "You are a strict evaluator. Respond with: VERDICT: PASS or FAIL\nCRITIQUE: <one concise paragraph>". No structured evaluation criteria.

2. **Todo completion check is post-hoc:** The evaluator catches incomplete todos after the model has already produced its answer. This should be a pre-condition, not a post-hoc critique.

3. **Max attempts loop:** If `eval_attempts >= max_attempts`, the evaluator silently gives up. No escalation or fallback.

### 4.6 `web_search_summary_middleware.py`

**File:** `backend/src/agents/middlewares/web_search_summary_middleware.py`

**Not directly implicated** in PROMPT_ID_18 failures (no web search was triggered in either cycle), but the middleware adds another layer of prompt complexity to the middleware chain.

### 4.7 `todo_prompts.py` — Todo System

**File:** `backend/src/agents/lead_agent/todo_prompts.py`

**Issues found:**

1. **`TODO_LIST_SYSTEM_PROMPT` is 50+ lines of instructions** for a tool the model never uses in either cycle.

2. **`TODO_LIST_TOOL_DESCRIPTION` is 80+ lines** of detailed usage instructions. The model never reads or follows these.

3. **Legacy flat-list todos vs DAG:** The `todo_prompts.py` file is for the legacy flat-list `TodoMiddleware`. The DAG-capable `TodoDagMiddleware` carries its own system prompt. This creates two parallel todo instruction surfaces that may confuse the model.

### 4.8 Other Prompt Surfaces

| File | Relevance | Issues |
|------|-----------|--------|
| `search_masking.py` | Low | Not implicated in PROMPT_ID_18 |
| `general_purpose.py` | Low | Subagent never invoked |
| `bash_agent.py` | Low | Subagent never invoked |
| `vault_analyze.py` | Low | Vault not queried in either cycle |
| `vault_generate.py` | Low | Vault not queried in either cycle |

---

## 5. Architecture-Level Issues

### 5.1 Middleware Chain Complexity

The middleware chain for `work` mode is:
```
PlannerMiddleware → PlanEvaluatorMiddleware → [execution] → EvaluatorMiddleware
```

Each middleware injects its own prompt content into the conversation via `HumanMessage` handoffs:
- `planner_handoff` — plan title, domain, summary, todo count, ready IDs
- `planner_clarification_required` — clarification question and options
- `system_reminder` — todo DAG active
- `evaluator_feedback` — critique or pre-verify failures

This creates a **stacked instruction environment** where the model receives conflicting directives from multiple sources.

### 5.2 Prompt Fragmentation

Prompt instructions are scattered across:
- `lead_agent/prompt.py` — main system prompt (12 sections)
- `lead_agent/todo_prompts.py` — todo system prompt (2 templates)
- `memory/prompt.py` — memory update and injection prompts (2 templates)
- `planner_middleware.py` — planner system prompt
- `plan_evaluator_middleware.py` — plan evaluator prompt
- `evaluator_middleware.py` — terminal evaluator prompt
- `todo_dag_middleware.py` — DAG todo prompt (separate from todo_prompts.py)

This fragmentation makes it impossible to reason about the total instruction set the model receives.

### 5.3 Context Window Pressure

For a 35B local model (likely 32K-128K context), the cumulative context pressure is:
- System prompt: ~767 lines (~15K+ tokens)
- Memory block: ~200 lines (~4K+ tokens) — when present
- Conversation history: grows from 2 → 17 messages across cycles
- Middleware handoffs: 3-5 additional `HumanMessage` injections per cycle
- Tool outputs: quality gate warnings, file listings, etc.

This pushes the model into context saturation, which explains the empty responses and degraded instruction following.

---

## 6. Todo List for Prompt Improvements

### P0 — Critical (Blockers)

| # | Todo | File(s) | Rationale |
|---|------|---------|-----------|
| 1 | **Resolve clarification_system vs plan_gate conflict** | `prompt.py`, `planner_middleware.py` | The two surfaces have contradictory semantics. One says "proceed with assumption," the other blocks execution. Align them: either make clarifications non-blocking, or remove the "proceed with assumption" directive when plan mode is active. |
| 2 | **Fix planner useless clarification generation** | `planner_middleware.py` | Add self-evident request detection. If the user request contains a clear objective, subject, and scope, skip clarifications entirely. Add concrete examples of when clarifications are vs. aren't needed to `PLANNER_SYSTEM_PROMPT`. |
| 3 | **Add `executive_summary` instruction to system prompt** | `prompt.py` | The quality gate expects this section but the system prompt never instructs the model to produce it. Add a required output structure section or remove the quality gate check. |
| 4 | **Fix empty response epidemic** | `prompt.py`, middleware chain | 9/21 turns produce blank AI responses. Likely caused by context saturation + conflicting instructions. Reduce system prompt size, resolve instruction conflicts, add a "you must always produce visible text" directive. |

### P1 — High Impact

| # | Todo | File(s) | Rationale |
|---|------|---------|-----------|
| 5 | **Implement memory relevance filtering** | `memory/prompt.py` | Filter memory facts by relevance to current user request. Use keyword matching or embedding similarity. Remove 200+ lines of irrelevant context (Tasmania trips, Dutch politics, etc.) from ML plan requests. |
| 6 | **Fix memory stripping between turns** | `prompt.py` (`_inject_memory_context`) | Memory is present in initial turn but absent in re-invocations. Ensure `_inject_memory_context` is called on every turn, not just initial construction. |
| 7 | **Reduce system prompt size for 35B model** | `prompt.py` | The ~767-line system prompt is too large for a 35B local model. Condense or remove sections that are never followed (subagent instructions, detailed todo guidance). Target: reduce by 40-50%. |
| 8 | **Make planner clarifications non-blocking by default** | `planner_middleware.py` | Clarifications should be suggestions, not hard gates. Only block execution for truly critical missing information (e.g., target environment for deployment). |
| 9 | **Add todo completion pre-check** | `evaluator_middleware.py` | Move todo completion check from post-hoc evaluator to a pre-condition. The model should not be allowed to produce a final answer until all todos are marked complete or explicitly skipped. |

### P2 — Medium Impact

| # | Todo | File(s) | Rationale |
|---|------|---------|-----------|
| 10 | **Consolidate duplicate todo instruction surfaces** | `todo_prompts.py`, `todo_dag_middleware.py` | Two parallel todo instruction systems exist. Consolidate into one surface to reduce model confusion. |
| 11 | **Add table generation guidance for 35B model** | `prompt.py` | `duplicate_table_rows` is a known 35B model artifact. Add explicit table generation instructions: "When writing markdown tables, ensure each row has unique content. Do not repeat rows." |
| 12 | **Strengthen plan evaluator prompt** | `plan_evaluator_middleware.py` | Add checks for planner comprehension failures (useless clarifications, nonsensical todos) to `_PLAN_EVAL_PROMPT`. |
| 13 | **Add retry logic for empty responses** | Middleware chain | Detect blank AI responses and inject a recovery prompt: "Your previous response was empty. Please provide your response in visible text." |
| 14 | **Audit componentized vs legacy prompt duplication** | `prompt.py` | `_build_componentized_prompt()` and `LEGACY_SYSTEM_PROMPT_TEMPLATE` contain near-identical content. Consolidate to a single source of truth. |

### P3 — Low Impact / Nice-to-Have

| # | Todo | File(s) | Rationale |
|---|------|---------|-----------|
| 15 | **Enable research fan-out by default** | `planner_middleware.py` | The `research_fanout` feature detects independent ready todos for parallel subagent dispatch. Enable it for research domain plans to improve execution speed. |
| 16 | **Add subagent usage telemetry** | `prompt.py`, middleware | Track whether the model actually uses `task()` calls. If usage is consistently 0%, consider removing subagent instructions from the system prompt for this model size. |
| 17 | **Improve evaluator prompt structure** | `evaluator_middleware.py` | Replace the 3-line `_EVALUATOR_PROMPT_TEMPLATE` with structured evaluation criteria (completeness, accuracy, actionability, format compliance). |
| 18 | **Add fail-forward escape hatch** | Middleware chain | After N consecutive quality gate failures with the same reasons, stop retrying and surface the error to the user instead of looping. |

---

## 7. Appendix

### 7.1 Files Analyzed

| File | Purpose |
|------|---------|
| `prompt-tunning/PROMPT_ID_18/cycle_1_metadata.json` | Cycle 1 run metadata |
| `prompt-tunning/PROMPT_ID_18/cycle_1_promptlog_001-009.txt` | Cycle 1 prompt logs (9 turns) |
| `prompt-tunning/PROMPT_ID_18/cycle_2_metadata.json` | Cycle 2 run metadata |
| `prompt-tunning/PROMPT_ID_18/cycle_2_promptlog_001-012.txt` | Cycle 2 prompt logs (12 turns) |
| `backend/src/agents/lead_agent/prompt.py` | Lead agent system prompt construction |
| `backend/src/agents/lead_agent/todo_prompts.py` | Legacy todo system prompts |
| `backend/src/agents/memory/prompt.py` | Memory update and injection prompts |
| `backend/src/agents/middlewares/planner_middleware.py` | Planner middleware + PLANNER_SYSTEM_PROMPT |
| `backend/src/agents/middlewares/plan_evaluator_middleware.py` | Plan evaluator middleware + _PLAN_EVAL_PROMPT |
| `backend/src/agents/middlewares/evaluator_middleware.py` | Terminal evaluator middleware + _EVALUATOR_PROMPT_TEMPLATE |
| `backend/src/agents/middlewares/web_search_summary_middleware.py` | Web search summary middleware |
| `backend/src/security/search_masking.py` | Search result masking |
| `backend/src/subagents/builtins/general_purpose.py` | General-purpose subagent |
| `backend/src/subagents/builtins/bash_agent.py` | Bash subagent |
| `backend/src/control_plane/prompts/vault_analyze.py` | Vault analysis prompt |
| `backend/src/control_plane/prompts/vault_generate.py` | Vault generation prompt |

### 7.2 Key Metrics

| Metric | Cycle 1 | Cycle 2 |
|--------|---------|---------|
| Total turns | 9 | 12 |
| Runtime | ~3.5 min | ~8 min |
| Empty AI responses | 3 (33%) | 6 (50%) |
| Quality gate failures | 6 (all same reasons) | 4 (different pattern) |
| Subagent `task()` calls | 0 | 0 |
| `write_todos` calls | 0 | 0 |
| Planner re-injections | 4 | 3 |
| Clarification deadlocks | 0 | 4 turns |
| Final answer delivered | Yes | Yes (better quality) |
