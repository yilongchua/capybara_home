# Lead Agent Prompt Analysis — PROMPT_ID_9

> **Analysis Date:** 2026-05-19
> **Prompt ID:** 9
> **Cycles Reviewed:** 2 (cycle_3 not present in folder)
> **Initial Prompt:** "Do a balanced deep dive on whether AI will replace junior software engineers. Include the strongest arguments on both sides, recent evidence, and what juniors should do now."
> **Model:** qwen3.6-local (mlx-community/qwen3.6-35b-a3b)
> **Mode:** work, auto_mode: true

---

## Executive Summary

Two cycles were completed for PROMPT_ID_9. Both cycles exhibited the same core behavioral pattern:
the agent **did not use subagents**, **did not produce a visible plan**, and **web_search calls consistently timed out**. Cycle 2 improved marginally over Cycle 1 by implementing a knowledge-based fallback and writing output to a file, but the fundamental issues — no task decomposition, no planning, and wasted time on repeated failing web searches — persisted.

The system prompt's `<subagent_system>` section (138 lines, ~35-40% of the prompt) is **ineffective**: it consumes massive context window but the agent never delegates. The prompt has instruction conflicts (conciseness vs verbose subagent examples), dead code (LEGACY template path), and no explicit coupling between the planner middleware and the lead agent's own todo/task management.

---

## Cycle 1 Analysis

### Runtime & Turns

| Metric | Value |
|---|---|
| Started | 2026-05-17 17:48:55 UTC |
| Completed | 2026-05-17 17:51:28 UTC |
| Duration | ~2m 33s |
| Log files | 6 (logs 001-006) |

### Turn Sequence

1. **Log 001** — System prompt loaded + user message (2 messages)
2. **Log 002** — Auto-generated title request (system internal, not agent)
3. **Log 003** — `web_search` query: "will AI replace junior software engineers 2025 2026 evidence data" → returns 5 results
4. **Log 004** — `web_search` query: "junior software engineer hiring trends 2025 layoffs AI impact tech industry" → returns results
5. **Log 005** — `web_search` query: "AI replacing junior developers arguments against replacement studies" → returns results
6. **Log 006** — Agent sends **3 parallel `web_search` calls** (via single response). **ALL 3 TIMED OUT at 45s.** The timeout error messages read: `Tool 'web_search' exceeded the 45s timeout and was cancelled. Try a different approach or skip this step.`

### Tools Used

| Tool | Count | Details |
|---|---|---|
| `web_search` | 6 | 3 sequential (returned) + 3 parallel (all timed out) |
| `task` (subagent) | 0 | **Not used once** |
| `write_todos` | 0 | Not used |
| `save_to_knowledge_vault` | 0 | Not used |
| `ask_clarification` | 0 | Not used (correct — none needed) |

### Behavioral Assessment

The agent performed no visible planning or task decomposition. It immediately began firing sequential web searches:

1. **No plan step.** Despite `<thinking_style>` instructing it to "think concisely and strategically BEFORE taking action," no plan was produced. The agent jumped directly into execution.
2. **Subagent instructions completely ignored.** 138 lines of `<subagent_system>` were loaded, but the agent never called `task()`. This is a textbook decomposable task (3 parallel research vectors: arguments for replacement, arguments against, career advice) — exactly the use case the prompt teaches.
3. **Pattern: sequential then parallel.** The agent first ran 3 sequential web searches successfully, then attempted 3 parallel ones — all of which timed out simultaneously. This wasted ~45s.
4. **No source deduplication.** The same sources (Stack Overflow Blog, Reddit/MIT post) appeared across multiple queries. The agent didn't recognize overlap.
5. **No citation formatting.** The `[citation:TITLE](URL)` format from the prompt was not used in the final output.

---

## Cycle 2 Analysis

### Runtime & Turns

| Metric | Value |
|---|---|
| Started | 2026-05-17 21:55:56 UTC |
| Completed | 2026-05-17 22:01:17 UTC |
| Duration | ~5m 21s |
| Log files | 8 (logs 001-008) |

### Turn Sequence

1. **Log 001** — System prompt loaded (nearly identical to cycle 1) + user message
2. **Log 002** — Auto-generated title request (system internal)
3. **Log 006** — 3 parallel `web_search` calls → **all 3 timed out at 45s**
4. **Log 007** — Agent retries the **same 3 parallel `web_search` calls** → **all 3 timed out again**
5. **Log 008** — Agent decides: "Web searches timed out, so I'll compose from up-to-date knowledge" → calls `write_file` (first attempt fails with missing `description` param, retry succeeds)

### Tools Used

| Tool | Count | Details |
|---|---|---|
| `web_search` | 6 | Same 3 parallel calls, attempted twice, all 6 timed out |
| `write_file` | 2 | 1 failed (missing param), 1 succeeded |
| `task` (subagent) | 0 | **Not used** |
| `write_todos` | 0 | Not used |

### Behavioral Assessment vs Cycle 1

| Aspect | Cycle 1 | Cycle 2 | Delta |
|---|---|---|---|
| **Completion** | Timed out on parallel searches | Completed via knowledge fallback | ✅ Improvement |
| **Runtime** | 2m 33s | 5m 21s | ❌ Wasted time |
| **web_search timeout** | 3 calls timed out | 6 calls timed out (retried same pattern) | ❌ Worse |
| **Subagent usage** | None | None | — |
| **Planning phase** | None | None | — |
| **Fallback strategy** | None visible | Knowledge-based + file output | ✅ Improvement |
| **Error recovery** | None | Retried write_file with correct params | ✅ Improvement |

### Key Finding: Failed Twice, Same Approach

The agent's decision-making in Cycle 2 is concerning:

- After all 3 parallel searches timed out (Turn 3/006), the agent waited ~2 minutes then **retried the exact same 3 parallel calls** (Turn 4/007) instead of switching strategy.
- The searches actually **did return results** (visible in logs 003, 004, 005 which contain full search result JSON with 5 results each from the first sequential batch), but the agent had already given up and moved to knowledge-based fallback.

---

## Source Code Structural Analysis

### 1. Prompt Size / Bloat

Estimated runtime system prompt size:

| Section | Lines (approx) | Tokens (est.) |
|---|---|---|
| `<role>` + `<soul>` | 5 | ~50 |
| `<memory>` (dynamic) | 10-40 | 200-800 |
| `<thinking_style>` | 9 | ~150 |
| `<clarification_system>` | 25 | ~350 |
| `skills_section` (dynamic) | 20-60 | 500-1,500 |
| `<subagent_system>` | 138 | 2,500-3,000 |
| `<working_directory>` | 22 | ~350 |
| `<fetch_policy>` | 9 | ~180 |
| `<response_style>` | 4 | ~60 |
| `<citations>` | 10 | ~150 |
| `<critical_reminders>` | 12 | ~250 |
| **Total** | **~300-450** | **~6,000-8,000** |

**The subagent section consumes ~35-40% of the entire system prompt** — yet the agent never uses subagents in either cycle.

### 2. Dead Code: LEGACY Template Path

The codebase maintains two identical prompt assembly paths:

- `LEGACY_SYSTEM_PROMPT_TEMPLATE` (line 158-270): monolithic `.format()` template
- `_build_componentized_prompt()` (line 580-604): modular `"\n\n".join()` of section constants

`prompt_cfg.componentized` controls which path is used. The legacy template has a slightly different section order and produces blank lines for empty sections. It's dead code if `componentized=true` is the default.

### 3. Instruction Conflicts

**Conflict A: Conciseness vs Verbosity**
- `<thinking_style>`: "Think concisely and strategically"
- `<response_style>`: "Clear and Concise: Avoid over-formatting"
- But the `<subagent_system>` block immediately follows with 138 lines of exhaustive examples, Python code blocks, and repeated warnings.

**Conflict B: Skill First vs Subagent Delegation**
- `<critical_reminders>`: "Skill First: Always load the relevant skill before starting **complex** tasks."
- `<subagent_system>`: "For ANY non-trivial task... decompose into parallel sub-tasks"
- No priority ordering is stated between these two competing strategies.

**Conflict C: Proceed vs Ask**
- `<clarification_system>`: "Default: attempt with a stated assumption. Ask only when genuinely blocked."
- Planner middleware injects `planner_clarification_required` HumanMessage that directly contradicts this by forcing the agent to ask.
- The agent receives conflicting signals about when to proceed vs when to ask.

### 4. Subagent Section Ineffectiveness — Root Causes

The subagent section fails to drive behavior because:

1. **Over-specification creates paralysis.** 138 lines with 3 detailed examples, 2 counter-examples, Python code blocks, and a 6-step workflow. The agent can't distinguish "hard rules" from "soft guidance."
2. **Teaches planning, not execution.** The section describes decomposition strategy abstractly rather than providing few-shot examples in the task tool description itself.
3. **Positionally disadvantaged.** The subagent section appears at ~line 206 (in the middle of the prompt), after `<role>`, `<soul>`, `<memory>`, `<thinking_style>`, and `<clarification_system>`. Middle instructions get less attention.
4. **No explicit coupling to state.** The planner middleware creates structured plans with `owner: "lead"` and `subagent_type` fields, but the lead agent's prompt never references this structure. The agent doesn't know that `todo.subagent_type` is its signal for when to delegate.
5. **Model-level constraints.** The model may lack the capability to reliably follow multi-step orchestration instructions, especially when the instruction length itself pushes the effective context window.

### 5. Todo System Fragmentation

Three separate systems handle task management with no coordination:

| System | Location | Purpose |
|---|---|---|
| `TODO_LIST_SYSTEM_PROMPT` | `todo_prompts.py:12-46` | Guides `write_todos` tool usage |
| TODO_DAG system prompt | `todo_dag_middleware.py:214-260` | DAG-aware todos with dependencies |
| Lead agent `critical_reminders` | `prompt.py:258-269` | Implicit todo awareness |

The lead agent's system prompt never explicitly mentions `write_todos`. The `{subagent_reminder}` placeholder covers orchestration only, not todo management. The agent has no unified mental model of task tracking.

### 6. Middleware Overlap

| Middleware | When it runs | What it does | Conflict |
|---|---|---|---|
| `planner_middleware` | Before agent | Creates plan + todos, injects handoff message | May conflict with agent's own `write_todos` |
| `plan_evaluator_middleware` | Before agent | Reviews plan, may revise todos silently | Revisions invisible to agent |
| `evaluator_middleware` | After agent | Injects feedback HumanMessage if FAIL | No reconciliation guidance in prompt |

The evaluator can tell the agent "FAIL: Plan has unfinished todos" but the agent has no instructions on how to reconcile this with its own judgment.

---

## Specific Line-Level Issues in prompt.py

| Location | Issue | Fix Recommendation |
|---|---|---|
| `prompt.py:19` | Emoji wastes tokens | Remove `🚀`, use plain text |
| `prompt.py:28,99,151` | Same warning repeated 3x | State once, remove redundancy |
| `prompt.py:57-74` | 3 examples, same pattern | Keep 1, remove redundant 2 |
| `prompt.py:103-148` | 2 Python code block examples | Remove (tool definitions already teach syntax) |
| `prompt.py:158-270` | LEGACY template maintained alongside componentized | Delete if componentized is default |
| `prompt.py:167` | "Think concisely" contradicts 138-line subagent section | Cut subagent section 60%+ |
| `prompt.py:260` | Skill First vs subagent delegation, no priority | Add explicit priority ordering |
| `prompt.py:367` | `{subagent_reminder}` glued to clarification line | Give its own bullet with proper newline |
| `prompt.py:574` | `_inject_memory_context` uses `"\n<thinking_style>"` as fragile marker | Add fallback warning, verify marker exists |
| `prompt.py:607-636` | `DREAMY_MODE_SECTION` hardcoded in prompt.py | Move to separate file |
| `prompt.py:639-656` | `PLAN_MODE_SECTION` hardcoded in prompt.py | Move to separate file |

---

## Cross-Cycle Comparison

| Metric | Cycle 1 | Cycle 2 |
|---|---|---|
| Agent turns | ~6 | ~7 |
| Runtime | 2m 33s | 5m 21s |
| web_search calls | 6 (3 returned, 3 timed out) | 6 (all timed out) |
| Subagent calls | 0 | 0 |
| write_todos calls | 0 | 0 |
| Save to vault | 0 | 0 |
| write_file calls | 0 | 2 (1 fail, 1 success) |
| Parallel search timeout | 3 calls at 45s | 6 calls at 45s (retried same) |
| Fallback strategy | None | Knowledge-based + file output |
| Response structure | Paragraph format | BLUF + sections + specific data |

---

## Todo Items for Prompt Improvement

### P1 — Critical (High Impact, Solvable via Prompt Changes)

- [ ] **Cut subagent_section by 60-70%.** Remove the 3 redundant examples, remove Python code blocks, consolidate concurrency warnings to one statement. Target: 40-50 lines from current 138. This recovers ~1,500-2,000 tokens of context window.
- [ ] **Add explicit planning requirement before tool execution.** Change `<thinking_style>` to require a brief plan output BEFORE any tool calls. This ensures the agent decomposes before executing.
- [ ] **Add web_search timeout guidance.** Instruct the agent to search sequentially instead of parallel, with a clear fallback: "If web_search times out, try subagent delegation or knowledge-based response. Do NOT retry the same pattern."
- [ ] **Add skill-vs-subagent priority ordering.** Clarify: "For complex tasks, decompose into subagents first. Load skills only for subtasks needing specialized workflows."

### P2 — Medium (Structural Improvements)

- [ ] **Delete LEGACY_SYSTEM_PROMPT_TEMPLATE.** Single-source-of-truth via componentized path only.
- [ ] **Move DREAMY_MODE_SECTION and PLAN_MODE_SECTION** to separate files loaded conditionally.
- [ ] **Fix `{subagent_reminder}` formatting** — give it its own bullet point.
- [ ] **Add middleware coordination signal.** The lead agent should know when a plan has been evaluated and approved, so it doesn't second-guess the pre-verified todo structure.
- [ ] **Add explicit `write_todos` mention** to the lead agent's critical_reminders section. Currently the task management instructions are invisible to the agent.

### P3 — Lower Priority (Cleanup & Polish)

- [ ] **Remove emoji from system prompt** (wasted tokens).
- [ ] **Consolidate concurrency warnings** from 3 mentions to 1.
- [ ] **Fix `_inject_memory_context` marker fragility** — add validation that marker exists before string replacement.
- [ ] **Align response_style with subagent instructions.** Remove the "not bullet points by default" clause if subagent task descriptions are expected to use structured format.

### Infrastructure-Level Issues (Not Fixable by Prompt Alone)

- [ ] **Increase web_search timeout** from 45s to at least 90-120s for parallel requests.
- [ ] **Reduce memory token budget** when subagent_section is enabled (or vice versa) — ensure total system prompt stays under 6,000 tokens.
- [ ] **Add telemetry** to track when subagent delegation is suggested by the prompt but not followed by the model — this would validate whether the prompt or the model is the bottleneck.

---

## Appendices

### Appendix A: Prompt Files Reviewed

- `prompt-tunning/PROMPT_ID_9/cycle_1_metadata.json`
- `prompt-tunning/PROMPT_ID_9/cycle_1_promptlog_001.txt` — `cycle_1_promptlog_006.txt`
- `prompt-tunning/PROMPT_ID_9/cycle_2_metadata.json`
- `prompt-tunning/PROMPT_ID_9/cycle_2_promptlog_001.txt` — `cycle_2_promptlog_008.txt`
- `backend/src/agents/lead_agent/prompt.py`
- `backend/src/agents/lead_agent/todo_prompts.py`
- `backend/src/agents/memory/prompt.py`
- `backend/src/agents/middlewares/planner_middleware.py`
- `backend/src/agents/middlewares/plan_evaluator_middleware.py`
- `backend/src/agents/middlewares/evaluator_middleware.py`
- `backend/src/agents/middlewares/web_search_summary_middleware.py`
- `backend/src/security/search_masking.py`
- `backend/src/subagents/builtins/general_purpose.py`
- `backend/src/subagents/builtins/bash_agent.py`
- `backend/src/control_plane/prompts/vault_analyze.py`
- `backend/src/control_plane/prompts/vault_generate.py`

### Appendix B: Response Quality Comparison

Cycle 1 and Cycle 2 both produced similar-quality responses from the metadata previews. Cycle 2 had slightly better structure (BLUF, sections, specific data points) but both relied on pre-training knowledge (web_search timed out). Neither cycle produced a response that would be considered superior to the other in terms of research depth or actionable advice.

### Appendix C: Estimated Token Waste by Section

| Section | Tokens | % of Prompt | Value Delivered |
|---|---|---|---|
| `<role>` | ~50 | <1% | High |
| `<soul>` | ~100 | 1-2% | Medium |
| `<memory>` | 200-800 | 3-13% | High |
| `<thinking_style>` | ~150 | 2-3% | Medium |
| `<clarification_system>` | ~350 | 5-8% | Medium |
| `skills_section` | 500-1,500 | 8-25% | Medium-high |
| `<subagent_system>` | 2,500-3,000 | 35-40% | **Low (agent ignores it)** |
| `<working_directory>` | ~350 | 5-8% | Medium |
| `<fetch_policy>` | ~180 | 3% | Medium |
| `<response_style>` | ~60 | 1% | Low |
| `<citations>` | ~150 | 2-3% | Low |
| `<critical_reminders>` | ~250 | 3-5% | Medium |

The subagent section is the single largest token consumer and delivers the least observable value based on behavioral evidence across both cycles.
