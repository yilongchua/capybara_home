# Lead Agent Prompt Analysis Report

**Date:** 2026-05-18
**Model:** mlx-community/qwen3.6-35b-a3b (qwen3.6-local)
**Test Prompt:** "I'm thinking of taking a 12 day trip to Greece with my partner in September. Can you make a realistic itinerary with places to stay, travel time between islands, and a rough budget?"
**Source:** `prompt-tunning/prompt_id_1/`

---

## 1. Data Overview

| Cycle | Thread Duration | Prompt Logs | System Prompt Size | Key Change |
|-------|----------------|-------------|-------------------|------------|
| 1 | ~2 min (17:07-17:09) | 6 logs | ~767 lines | Memory context **included** (~247 lines of `<memory>`) |
| 2 | ~20 min (20:33-20:53) | 22 logs | ~744 lines | Memory context **removed** |
| 3 | ~38 min (23:30-00:08) | 20 logs | ~744 lines | Same as cycle 2, but more tool failures |

All cycles used the same user prompt. The system prompt evolved across cycles, primarily in whether memory context was injected and how the agent chose to execute (direct tool calls vs. subagent delegation).

---

## 2. Prompt Evolution Across Cycles

### Cycle 1: Memory-Enabled, Direct Execution
- System prompt included a full `<memory>` block with Work/Personal/Current Focus/History/Relevant Facts
- Agent attempted **3 parallel `web_search` calls** directly (no subagents)
- All 3 timed out at 45s → agent fell back to knowledge-based response
- Response was generated quickly (~2 min total) but acknowledged web search failure

### Cycle 2: Memory-Removed, Subagent Delegation
- `<memory>` section removed entirely (prompt shrank from 767 to ~744 lines)
- Agent delegated research to **subagents** (2 `task` calls for itinerary + budget)
- Subagents hit `asyncio.locks.Semaphore` errors on web_search (backend bug, not prompt issue)
- Agent produced a detailed response using subagent results + internal knowledge
- Took ~20 min (longer due to subagent orchestration overhead)

### Cycle 3: Memory-Removed, Mixed Strategy
- Same prompt as cycle 2
- Agent tried subagent first → `task` timed out at 1800s (30 min!)
- Fell back to direct `web_search` → mixed results: some timeouts, some empty results (0 total_results)
- Eventually used `save_to_knowledge_vault` and fell back to internal knowledge
- Took ~38 min (longest of all cycles)

---

## 3. Key Problems Identified

### Problem A: No Tool Failure Recovery Strategy
**Severity: Critical**

The prompt has no guidance on what to do when tools fail. Across all cycles, the agent:
- Retried failed tools without a fallback strategy
- In cycle 3, spent 38 minutes because the subagent timed out at 1800s
- No instruction to "fall back to internal knowledge after N failures"

**Evidence:**
- Cycle 1: `web_search` timed out 3x, agent just produced answer from knowledge
- Cycle 2: Subagents got asyncio errors, but agent recovered well
- Cycle 3: `task` tool timed out at 1800s — agent should have given up much sooner

### Problem B: Subagent Section is Overwhelmingly Verbose
**Severity: High**

The `<subagent_system>` section is **~137 lines**, containing:
- 3 detailed examples with multi-turn breakdowns
- Repeated warnings about the "max 3" limit (mentioned 8+ times)
- Full code block examples with `task()` calls
- "Counter-example" section

This is ~18% of the entire system prompt. The agent clearly reads and follows these instructions (it respects the 3-call limit), but the verbosity:
- Wastes context window that could be used for other guidance
- Creates redundancy with the `{subagent_reminder}` in `<critical_reminders>` and `{subagent_thinking}` in `<thinking_style>`

### Problem C: Fetch Policy Has No Failure Handling
**Severity: Medium**

Current `<fetch_policy>` says:
```
1. web_search — external web research should be attempted first for fresh information
2. query_knowledge_vault — enrich with local vault structure/snippets/concept links
3. query_lightrag — retrieve graph-oriented, multi-hop relationship evidence when available
4. search_internal_documents — alias for indexed internal doc search
```

But there's no instruction for: "if web_search fails N times, fall back to vault/knowledge." The agent should be told to use its internal knowledge as a valid primary source, not just a last resort.

### Problem D: Memory Context Was Removed Entirely
**Severity: Medium (context-dependent)**

Cycle 1 had rich memory context. Cycles 2-3 have none. For the Greece trip query:
- Cycle 1's memory mentioned a previous Greece itinerary was already generated — this could have been leveraged
- Without memory, the agent treats every query as fresh, potentially re-doing work

However, this may have been intentional to test the prompt without memory bias. The question is whether memory injection should be **selective** (only for relevant queries) rather than always-on or always-off.

### Problem E: No Guidance on Response Completeness vs. Tool Reliance
**Severity: Medium**

The prompt says "Clear and Concise" and "Natural Tone" but doesn't address:
- When to produce a complete answer from internal knowledge vs. when to keep searching
- The agent in cycle 3 kept searching even after multiple failures instead of producing a useful answer

### Problem F: Redundant Subagent Instructions Across Sections
**Severity: Low-Medium**

The subagent concurrency limit and batching instructions appear in **three places**:
1. `<subagent_system>` section (~137 lines of detail)
2. `{subagent_thinking}` injected into `<thinking_style>` 
3. `{subagent_reminder}` injected into `<critical_reminders>`

This triple-repetition wastes tokens and could be consolidated.

---

## 4. Actionable Recommendations (No Code Changes)

### R1: Add Tool Failure Recovery Protocol
**Priority: P0 | Severity: Critical**

Add a new `<tool_failure_handling>` section that instructs the agent to:
- After **2 consecutive tool failures** (timeouts/errors), fall back to internal knowledge
- Never wait more than **60 seconds total** for tool results before producing a partial answer
- If subagent times out, immediately switch to direct tool execution
- Explicitly state: "Internal knowledge is a valid primary source — do not treat tool failures as blocking"

### R2: Condense Subagent Section by 60-70%
**Priority: P1 | Severity: High**

The subagent section could be reduced from ~137 lines to ~40-50 lines by:
- Removing the detailed multi-turn code block examples (keep only one concise example)
- Consolidating the "max 3" warnings into a single prominent callout
- Removing the "counter-example" section (the DO/DON'T lists already cover this)
- Keeping only the essential: decomposition principle, concurrency limit, batching strategy

### R3: Revise Fetch Policy to Include Fallback
**Priority: P1 | Severity: Medium**

Change the fetch policy from a strict priority list to a **priority with fallback** model:
```
1. web_search — for time-sensitive/current information
2. knowledge_vault / lightrag — for enriched context  
3. Internal knowledge — valid primary source for well-established topics
```
Add: "For evergreen topics (travel, how-to, general knowledge), internal knowledge is sufficient. Use web_search primarily for current prices, schedules, and real-time data."

### R4: Add "Completeness Over Perfection" Directive
**Priority: P0 | Severity: Medium**

Add to `<thinking_style>` or a new section:
- "Produce a complete, useful answer even with partial information"
- "If tools fail, state your assumption and proceed — don't leave the user waiting"
- "Mark uncertain information clearly rather than continuing to search indefinitely"

### R5: Consolidate Subagent Instructions
**Priority: P2 | Severity: Low-Medium**

Merge the three redundant subagent instruction locations into one canonical source. The `<subagent_system>` section should be the single source of truth, and `{subagent_reminder}` / `{subagent_thinking}` should reference it rather than repeating.

### R6: Consider Selective Memory Injection
**Priority: P2 | Severity: Medium**

Rather than always injecting full memory (cycle 1) or never injecting it (cycles 2-3), consider:
- Only injecting memory when the query is likely to benefit from user context
- Using a lightweight "memory relevance check" before injection
- This would reduce prompt size for generic queries while preserving personalization when useful

### R7: Add Response Quality Checklist
**Priority: P3 | Severity: Low**

Add a brief pre-response checklist to `<thinking_style>`:
- "Have I addressed all parts of the user's request?"
- "Is my answer complete enough to be useful, even if not exhaustive?"
- "Have I stated assumptions where information is uncertain?"

---

## 5. Cycle-by-Cycle Performance Summary

| Metric | Cycle 1 | Cycle 2 | Cycle 3 |
|--------|---------|---------|---------|
| Total Duration | ~2 min | ~20 min | ~38 min |
| Prompt Logs | 6 | 22 | 20 |
| Tool Strategy | Direct web_search (3x) | Subagent delegation | Mixed (subagent → direct search) |
| Tool Failures | 3x web_search timeout | 3x asyncio errors (backend) | 1x task timeout, 4x web_search timeout, 2x empty results |
| Final Output Quality | Good (from knowledge) | Excellent (subagent + knowledge) | Good (knowledge_vault + fallback) |
| Efficiency | Best | Good | Worst |

**Key insight:** Cycle 2 produced the best balance of quality and efficiency. The subagent delegation worked well (despite backend errors), and the agent recovered gracefully. Cycle 3's mixed strategy was inefficient — trying subagent, then falling back to direct search after a 30-minute timeout.

---

## 6. Priority Ranking of Recommendations

| Priority | Recommendation | Expected Impact |
|----------|---------------|-----------------|
| **P0** | R1: Tool failure recovery protocol | Prevents 38-minute hangs like cycle 3 |
| **P0** | R4: Completeness over perfection directive | Reduces tool-chasing behavior |
| **P1** | R2: Condense subagent section by 60-70% | Frees ~90 lines of context window |
| **P1** | R3: Revise fetch policy with fallback | Better tool selection for evergreen topics |
| **P2** | R5: Consolidate redundant subagent instructions | Reduces token waste |
| **P2** | R6: Selective memory injection | Balances personalization vs. prompt size |
| **P3** | R7: Response quality checklist | Improves answer completeness |

---

## 7. Files Analyzed

### Primary (cycle prompt logs + metadata)
- `prompt-tunning/prompt_id_1/cycle_1_metadata.json` (6 logs)
- `prompt-tunning/prompt_id_1/cycle_2_metadata.json` (22 logs)
- `prompt-tunning/prompt_id_1/cycle_3_metadata.json` (20 logs)
- `prompt-tunning/prompt_id_1/cycle_*_promptlog_*.txt` (48 files total)

### Current prompt surfaces
- `backend/src/agents/lead_agent/prompt.py` — system prompt template, subagent section, memory injection
- `backend/src/agents/memory/prompt.py` — memory update/injection templates

### Related (not directly analyzed but relevant)
- `backend/src/agents/lead_agent/todo_prompts.py`
- `backend/src/agents/middlewares/planner_middleware.py`
- `backend/src/agents/middlewares/plan_evaluator_middleware.py`
- `backend/src/agents/middlewares/evaluator_middleware.py`
- `backend/src/agents/middlewares/web_search_summary_middleware.py`
- `backend/src/security/search_masking.py`
- `backend/src/subagents/builtins/general_purpose.py`
- `backend/src/subagents/builtins/bash_agent.py`
- `backend/src/control_plane/prompts/vault_analyze.py`
- `backend/src/control_plane/prompts/vault_generate.py`
