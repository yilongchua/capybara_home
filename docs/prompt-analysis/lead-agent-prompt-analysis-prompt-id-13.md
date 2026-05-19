# Lead Agent Prompt Analysis — PROMPT_ID_13

**Date:** 2026-05-19
**Scope:** `prompt-tunning/PROMPT_ID_13/` (Cycle 1 + Cycle 2 logs + metadata)
**Related Code:** `backend/src/agents/lead_agent/prompt.py`, `backend/src/agents/memory/prompt.py`, middleware layers, subagent prompts
**Test Prompt:** "Give me a serious research summary on creatine: benefits, dosing, safety, myths, who should avoid it, and what the evidence actually says."
**Model:** qwen3.6-local (35B parameter class)

---

## 1. File Catalog

| File | Type | Size |
|---|---|---|
| `cycle_1_metadata.json` | JSON | 8.3 KB |
| `cycle_1_promptlog_001.txt` – `cycle_1_promptlog_020.txt` | TXT (20 files) | 14–53 KB each |
| `cycle_2_metadata.json` | JSON | 5.8 KB |
| `cycle_2_promptlog_001.txt` – `cycle_2_promptlog_011.txt` | TXT (11 files) | 0.7–44 KB each |

**Total:** 33 files, ~948 KB

---

## 2. Execution Flow Summary

### Cycle 1 (~12 min, 20 logs)

```
001  Lead agent receives user request + full system prompt (memory, subagent, clarification, fetch_policy)
002  Planner middleware invoked → generates plan JSON
003  Title generation (meta-call, 1 message)
004-006  Subagent web_search summarization prompts (3 parallel searches: dosing, benefits, myths)
007  Lead agent retry after 3× web_search timeouts (45s each) → 6 messages
008  Same retry path, now with write_todos reminder appended → 7 messages
009-012  More subagent search summarizations (4 more searches)
013  Planner handoff returns clarification_pending: yes
     Question: "What specific topic or project should the structured plan address?"
014  Agent attempts write_file → fails with "Field required" (missing description param)
015-018  Repeated timeout loops + plan_gate blocking → agent stuck
019-020  Subagent prompts dispatched (safety/myths + dosing) — actual productive work
```

### Cycle 2 (~9 min, 11 logs)

```
001  Same initial prompt
002  Planner invoked
003  Title generation
004-006  Subagent search summarizations
007  3× web_search timeouts
008  Retry with plan trigger
009  Planner returns spurious clarification: "What is the original user request...?"
010  Title generation (again)
011  Agent tries to dispatch subagents → hits [plan_gate] 4 times → deadlocked
```

### Key Difference

Cycle 1 partially escaped plan_gate by dispatching subagents (logs 019-020). Cycle 2 remained fully blocked. Both eventually produced good answers, suggesting a fallback path bypasses plan_gate after enough retries. Cycle 2 was faster (9 min vs 12 min) but produced fewer logs (11 vs 20), indicating it either deadlocked earlier or took a shorter path to completion.

---

## 3. Tool Call Success/Failure Rates

| Tool | Cycle 1 | Cycle 2 | Success Rate | Failure Mode |
|---|---|---|---|---|
| `web_search` (lead agent) | 6 calls | 3 calls | **0%** | 100% timeout (45s ceiling) |
| `web_search` (subagent) | 3 calls | 3 calls | **100%** | All succeeded (5 results each) |
| `write_file` | 1 call | 0 | **0%** | `"Field required"` — missing `description` |
| `task` (subagent dispatch) | 2 calls | 0 | **100% (C1)** | Succeeded in C1; C2 blocked by plan_gate |
| Planner LLM | 2 calls | 2 calls | **0%** | Both returned `clarification_pending: yes` |

**Critical finding:** Lead-agent `web_search` always times out (45s), while subagent `web_search` succeeds. Subagents run in a different execution context with different timeout behavior.

---

## 4. Failure Mode Analysis

### 4A. `web_search` Timeout Cascade (100% occurrence)

**Symptom:** Every cycle, the lead agent launches 3 parallel `web_search` calls → all hit 45s timeout → agent retries → more timeouts. Wasted ~10 min wall-clock in Cycle 1.

**Root cause:** The lead agent's `web_search` tool has a 45s timeout that is consistently exceeded. Subagent `web_search` works because it runs in an isolated context with different timeout handling.

**Prompt contribution:** The `<fetch_policy>` section says:
> "1. `web_search` — external web research should be attempted first for fresh information"

This instructs the lead agent to call `web_search` directly rather than delegating to subagents. The prompt contradicts itself — `<subagent_system>` says to decompose complex tasks, but `<fetch_policy>` says to use `web_search` first.

### 4B. Plan Gate Blocking (100% occurrence)

**Symptom:**
- Cycle 1, Log 013: Planner returns `clarification_pending: yes` → "What specific topic or project should the structured plan address?"
- Cycle 2, Log 009: Same pattern → "What is the original user request or topic you need a structured plan for?"

The `[plan_gate]` middleware blocks all subsequent tool calls. The agent **never** calls `ask_clarification` to resolve this.

**Root cause:** The planner middleware (`planner_middleware.py`) has an `_ensure_research_clarifications` function that triggers when the prompt lacks year keywords like "2025" or "latest." The user's prompt is already specific (6 dimensions listed) but gets flagged anyway.

**Prompt contribution:** The `<clarification_system>` section says:
> "Default: attempt with a stated assumption. Ask only when genuinely blocked."

But the planner middleware ignores this policy and generates clarifications for any research prompt without explicit timeframe keywords. **This is a prompt-policy mismatch** — the prompt tells the model one thing, the middleware does another.

### 4C. `write_file` Parameter Error (Cycle 1, Log 014)

**Symptom:**
```
Error invoking tool 'write_file' with kwargs {'content': '...'}
description: Field required
```

**Root cause:** The model omitted the required `description` parameter under cognitive load from complex prompt context and accumulated timeout failures.

**Prompt contribution:** The prompt is ~130 lines of dense subagent instructions + memory context + skills + clarification rules + fetch policy + response style + citations + critical reminders. Under this cognitive load, the model drops required parameters.

### 4D. Planner Clarification Loop

**Symptom:** Planner consistently generates spurious clarifications for a perfectly clear request.

**Root cause:** In `planner_middleware.py`, the `_ensure_research_clarifications` function checks for keywords like "2025", "latest", "recent" and triggers clarification if absent. The creatine prompt is already well-scoped with 6 explicit dimensions.

---

## 5. Prompt Construction Analysis (`lead_agent/prompt.py`)

### 5.1 Structure

The prompt is built in two modes:
- **Legacy mode:** `LEGACY_SYSTEM_PROMPT_TEMPLATE` — single monolithic template with `{}` placeholders
- **Componentized mode:** `_build_componentized_prompt()` — joins 12 separate section templates

Both modes produce essentially the same content. The componentized mode adds maintainability but not functional difference.

### 5.2 Section Order (Componentized)

1. `<role>` — Agent identity
2. `<soul>` — Personality (from SOUL.md)
3. `<memory>` — User context (injected at runtime)
4. `<thinking_style>` — Planning instructions + subagent decomposition check
5. `<clarification_system>` — When to ask vs. assume
6. `<skill_system>` — Available skills
7. `<subagent_system>` — Subagent orchestration (~130 lines)
8. `<working_directory>` — File management rules
9. `<fetch_policy>` — Search priority order
10. `<response_style>` — Output format guidance
11. `<citations>` — Citation format
12. `<critical_reminders>` — Summary of key rules

### 5.3 Issues Identified

**Issue 1: Subagent section is overwhelmingly long (~130 lines)**

The `<subagent_system>` section contains:
- Core principle statement
- Hard concurrency limit (repeated 4+ times)
- Multi-batch execution rules
- Task decomposition quality bar
- 3 detailed examples
- When to use / when not to use
- Critical workflow (6 steps)
- Violation warning
- Usage examples (single batch, multi-batch, counter-example)
- Critical reminder (repeated again)

For a 35B local model, this is excessive. The model struggles to retain all constraints simultaneously, leading to:
- Repeatedly launching `web_search` directly instead of using `task()` subagents
- Forgetting the concurrency limit
- Dropping required parameters on tool calls

**Issue 2: Contradictory instructions**

| Section | Instruction | Conflict |
|---|---|---|
| `<fetch_policy>` | "use `web_search` first" | vs `<subagent_system>` "decompose into subagents" |
| `<clarification_system>` | "ask only when genuinely blocked" | vs planner middleware generates clarifications for any research prompt |
| `<subagent_system>` | "max N task calls per response" | vs model repeatedly exceeds limit |
| `<critical_reminders>` | "Skill First: Always load the relevant skill before starting complex tasks" | vs no skill loaded in either cycle |

**Issue 3: Memory context bloat**

The `<memory>` section injects ~20 lines of user context (Tasmania trip, Dutch politics, CAG project) that is completely irrelevant to a creatine research request. This:
- Consumes context window
- May distract the model with unrelated information
- Adds cognitive load

**Issue 4: Repetition across sections**

The concurrency limit is stated in:
- `<subagent_system>` header (2x)
- `<subagent_system>` body (3x)
- `<critical_reminders>` (1x)
- `_build_subagent_section()` f-string (multiple interpolations)

Total: 6+ repetitions of the same constraint. This wastes tokens and may cause the model to overweight this constraint at the expense of others.

---

## 6. Memory Prompt Analysis (`memory/prompt.py`)

### 6.1 `MEMORY_UPDATE_PROMPT`

The memory update prompt is well-structured with clear section guidelines. Issues:

**Issue 1: Length guidelines are verbose but not enforced**

The prompt specifies sentence counts for each section (e.g., "workContext: 2-3 sentences", "topOfMind: 3-5 sentences") but there's no enforcement mechanism. The LLM may produce longer or shorter content.

**Issue 2: No relevance filtering at update time**

All conversation content is processed for memory updates, including session-specific file uploads. The prompt has a rule:
> "Do NOT record file upload events in memory"

But this is a soft instruction that may not be followed consistently.

### 6.2 `format_memory_for_injection`

**Issue 1: No relevance scoring for injection**

Memory is injected wholesale without filtering for relevance to the current request. The vector store query (`query_knowledge_vault`) is only used when `current_turn_text` is available, and even then it returns top-k facts without relevance scoring against the current task.

**Issue 2: Token truncation is crude**

When memory exceeds `max_tokens` (2000), it's truncated by character count with a rough token estimation. This can cut off mid-sentence and lose important context.

---

## 7. Related Prompt Surface Analysis

### 7.1 Planner Middleware (`planner_middleware.py`)

- `_ensure_research_clarifications` triggers on absence of year keywords — too aggressive
- Returns `clarification_pending: yes` even for well-scoped requests
- No mechanism to detect that the user request is already specific

### 7.2 Plan Evaluator Middleware (`plan_evaluator_middleware.py`)

- Evaluates plan quality but doesn't check for spurious clarifications
- Could be extended to flag unnecessary clarification requests

### 7.3 Evaluator Middleware (`evaluator_middleware.py`)

- Post-execution quality check
- No feedback loop to adjust prompt behavior

### 7.4 Web Search Summary Middleware (`web_search_summary_middleware.py`)

- Summarizes web search results for subagent consumption
- Works correctly when subagent `web_search` succeeds

### 7.5 Subagent Prompts (`general_purpose.py`, `bash_agent.py`)

- General purpose subagent has its own system prompt
- Bash agent is narrowly scoped for command execution
- Neither has the bloat issues of the lead agent prompt

### 7.6 Vault Prompts (`vault_analyze.py`, `vault_generate.py`)

- Knowledge vault operations
- Not directly involved in the creatine research flow

### 7.7 Search Masking (`search_masking.py`)

- Security layer for search queries
- Not a prompt issue

---

## 8. Cycle 1 vs Cycle 2 Comparison

| Aspect | Cycle 1 | Cycle 2 |
|---|---|---|
| Total logs | 20 | 11 |
| Runtime | ~12 min | ~9 min |
| Subagent dispatches | 2 (succeeded) | 0 (blocked by plan_gate) |
| `write_file` attempt | Yes (failed) | No |
| Clarification question | "What specific topic..." | "What is the original user request..." |
| Recovery | Partially recovered — subagents ran | Never recovered via normal path |
| Final output quality | Good | Good |

Cycle 2 was shorter but more brittle — it deadlocked on plan_gate and never dispatched subagents. Both cycles produced good final answers, suggesting a fallback mechanism eventually bypasses the plan_gate.

---

## 9. Synthesized Findings

### 9.1 Root Causes

1. **Lead agent `web_search` timeout** is a backend infrastructure issue, not a prompt issue. But the prompt's `<fetch_policy>` directs the agent to use it first, amplifying the problem.

2. **Planner middleware over-clarification** is the single biggest blocker. It generates spurious clarifications for well-scoped requests, and the plan_gate then blocks all tool calls until clarification is resolved.

3. **Subagent prompt bloat** causes the 35B model to lose track of constraints. The model needs a much more concise subagent section.

4. **Memory context irrelevance** adds noise without value for most requests.

5. **Instruction contradictions** between sections create confusion about the correct behavior.

### 9.2 What Works Well

- Subagent task descriptions (when dispatched) are high-quality and well-scoped
- The componentized prompt structure is maintainable
- The clarification system policy ("assume and proceed") is sound — it's just not enforced by middleware
- The fetch policy priority order is reasonable (if the timeout issue is fixed)
- Response style guidance produces good output format

---

## 10. TODO List for Prompt Improvement

### Priority 1: Fix Blocking Issues

- [ ] **1.1** Reduce planner `_ensure_research_clarifications` aggressiveness — should not trigger when user request lists 3+ specific dimensions
- [ ] **1.2** Add plan_gate auto-resolution for clarification questions where the answer is obvious from context (e.g., user already stated the topic)
- [ ] **1.3** Fix lead-agent `web_search` timeout (backend issue, but prompt should work around it)

### Priority 2: Reduce Prompt Bloat

- [ ] **2.1** Condense `<subagent_system>` section from ~130 lines to ~40 lines — keep only: core principle, hard limit, batching rule, 1 example, when to use/not use
- [ ] **2.2** Remove redundant repetitions of the concurrency limit (currently stated 6+ times)
- [ ] **2.3** Consolidate `<critical_reminders>` to reference other sections instead of repeating their content

### Priority 3: Resolve Contradictions

- [ ] **3.1** Update `<fetch_policy>` to say "For research tasks, delegate `web_search` to subagents via `task()` tool" instead of "use `web_search` first"
- [ ] **3.2** Align planner middleware behavior with `<clarification_system>` policy — don't generate clarifications that contradict the "assume and proceed" rule
- [ ] **3.3** Add explicit instruction: "If planner returns a clarification question and the answer is already in the user's request, proceed without calling `ask_clarification`"

### Priority 4: Memory Context Improvement

- [ ] **4.1** Add relevance filtering to `format_memory_for_injection` — only inject memory sections relevant to the current request type
- [ ] **4.2** Implement semantic similarity scoring between current turn and memory facts before injection
- [ ] **4.3** Reduce `max_injection_tokens` from 2000 to 800 for non-personalized requests

### Priority 5: Prompt Quality Guards

- [ ] **5.1** Add tool call schema reminder in `<critical_reminders>` — "Always check required parameters before calling tools"
- [ ] **5.2** Add explicit subagent delegation rule: "For web research, always use `task()` with subagent_type='general-purpose' rather than calling `web_search` directly"
- [ ] **5.3** Test with componentized mode enabled to verify no regression vs legacy mode

### Priority 6: Testing & Validation

- [ ] **6.1** Run PROMPT_ID_14 with fixes from 1.1–1.3 and compare cycle logs
- [ ] **6.2** Measure: web_search timeout rate, plan_gate blocking frequency, subagent dispatch success rate
- [ ] **6.3** A/B test condensed vs full subagent section on 35B model

---

## Appendix A: Prompt Section Token Estimates

| Section | Estimated Tokens | % of Total |
|---|---|---|
| `<role>` | 10 | 0.5% |
| `<soul>` | 50 | 2% |
| `<memory>` (injected) | 200–500 | 8–20% |
| `<thinking_style>` | 80 | 3% |
| `<clarification_system>` | 120 | 5% |
| `<skill_system>` | 50–200 | 2–8% |
| `<subagent_system>` | 400–500 | 16–20% |
| `<working_directory>` | 150 | 6% |
| `<fetch_policy>` | 80 | 3% |
| `<response_style>` | 30 | 1% |
| `<citations>` | 50 | 2% |
| `<critical_reminders>` | 150 | 6% |
| **Total (base)** | **~1,400** | **100%** |
| + memory injection | **+200–500** | |
| + dreamy/plan mode | **+100–300** | |

The `<subagent_system>` section alone consumes 16-20% of the total prompt. Condensing it to 40 lines would save ~250 tokens.

## Appendix B: Key Code References

| File | Line(s) | Relevance |
|---|---|---|
| `backend/src/agents/lead_agent/prompt.py` | 1-600 | Main prompt construction |
| `backend/src/agents/lead_agent/prompt.py` | 23-100 | `_build_subagent_section()` — bloat source |
| `backend/src/agents/lead_agent/prompt.py` | 102-180 | `LEGACY_SYSTEM_PROMPT_TEMPLATE` |
| `backend/src/agents/lead_agent/prompt.py` | 280-340 | `_build_componentized_prompt()` |
| `backend/src/agents/memory/prompt.py` | 1-100 | `MEMORY_UPDATE_PROMPT` |
| `backend/src/agents/memory/prompt.py` | 100-200 | `format_memory_for_injection()` |
| `backend/src/agents/middlewares/planner_middleware.py` | — | `_ensure_research_clarifications` — over-clarification source |
| `backend/src/agents/middlewares/plan_evaluator_middleware.py` | — | Plan quality evaluation |
| `backend/src/agents/middlewares/evaluator_middleware.py` | — | Post-execution quality check |
