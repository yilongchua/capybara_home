# Lead Agent Prompt Analysis — PROMPT_ID_8

**Date:** 2026-05-19
**Model:** qwen3.6-35b-a3b (local, via MLX)
**Mode:** work (auto_mode: true)
**Request:** "Plan a weekend in Tokyo for someone who likes food, bookstores, quiet neighborhoods, and one nice cocktail bar."
**Cycles:** 2 (cycle_1: 8 invocations, cycle_2: 4 invocations)

---

## Overview

PROMPT_ID_8 tests the lead agent's ability to handle a moderately complex content-generation task. Both cycles ultimately succeeded but reveal significant prompt inefficiencies. Cycle 1 required 8 invocations and external planner intervention to recover from total web_search timeout failure. Cycle 2 was more efficient (4 invocations) but introduced its own planner context-loss bug. Across both cycles, ~70-80% of tokens sent to the model are wasted on redundant system prompt sections, irrelevant memory, and bloated tool definitions.

---

## Cycle 1 Flow Analysis

### Execution Summary

| Invocation | Purpose | Outcome |
|---|---|---|
| 001 | System prompt + user request | Model launched 3 parallel web_searches |
| 002 | Planner middleware (unrelated) | Planned against wrong input |
| 003 | Title generation | Success (simple prompt) |
| 004 | Web search summary middleware | Summarized cocktail bar results |
| 005 | Web search summary middleware | Summarized bookstore results |
| 006 | Web search summary middleware | Summarized neighborhood results |
| 007 | Agent response attempt | **ALL 3 web_search timed out (45s)** → model produced blank response |
| 008 | Planner reroute (dropped memory) | Recovery — produced final itinerary |

### Issues

#### 1. Memory bloat — 500+ tokens of irrelevant context every turn
- **Where:** `prompt.py:379-429` (`_get_memory_context`) → `<memory>` injection
- **Evidence:** `cycle_1_promptlog_001.txt:498-519` — User Context lists Accenture POC, maritime law, Jira tickets, protective crystals, standing desks under $400, macOS downgrade — none relevant to a Tokyo itinerary.
- **Root cause:** `get_memory_data()` dumps the entire global memory store. No semantic filtering or domain-based pruning. The `max_injection_tokens=2000` cap is generous for a 3.6B model.
- **Impact:** ~2000 chars / 500 tokens wasted per turn × 8 turns = **~4000 tokens burned** on irrelevant context.

#### 2. Subagent system section is a massive tutorial (~2000 tokens)
- **Where:** `prompt.py:18-155` (`_build_subagent_section`)
- **Evidence:** `cycle_1_promptlog_001.txt:560-697` — Full orchestration tutorial with 3 worked examples (Tencent stock, 5 cloud providers, auth refactoring), complete Python code blocks, 6 repetitions of the "max N task calls" rule, and a "How It Works" section.
- **Root cause:** The section reads like onboarding documentation, not a system instruction. The same lesson ("batch task() calls in groups of N") is taught 6 different ways: 3 examples, 2 usage examples, 1 counter-example, plus the CRITICAL WORKFLOW checklist.
- **Impact:** ~800-900 lines / ~2000 tokens per invocation. The `subagent_reminder` and `subagent_thinking` variables in `_build_prompt` then **repeat the same concurrency limit a third time**. Could be compressed to ~300 tokens. **~1700 extra tokens × 8 = ~13600 tokens wasted.**

#### 3. Tool schema descriptions are verbose and repeated every invocation
- **Where:** Tool definitions in `invocation_params.tools` (repeated across all 8 logs)
- **Evidence:** `cycle_1_promptlog_001.txt` — `present_files` description runs 3 paragraphs. `ask_clarification` runs 7+ paragraphs. `task` embeds full subagent type descriptions inline. The same 13 tool definitions (~500 lines) appear verbatim in every invocation.
- **Root cause:** Tool descriptions mix "when to use", "when NOT to use", "best practices", and "notes". No pruning based on task relevance.
- **Impact:** ~12KB of tool schemas per invocation. Removing redundant prose would save ~500 tokens per invocation × 8 = **~4000 tokens wasted.**

#### 4. No timeout recovery logic — model blanks after 3 failures
- **Where:** `cycle_1_promptlog_007.txt:769-786`
- **Evidence:** Messages 4-6 show `[model_timeout] Tool 'web_search' exceeded the 45s timeout`. The model responded with blank whitespace (message 3) and never tried fallback approaches — no `task` delegation, no direct knowledge, no "let me work with what I know".
- **Root cause:** The timeout message says "Try a different approach" but there's no structured recovery protocol in the system prompt. The 3.6B local model lacks the reasoning to self-correct from 3 concurrent timeouts.
- **Impact:** ~2 minutes wall-clock lost + 3 wasted 45s timeout windows + 3 wasted LLM invocations.

#### 5. Planner reroute accidentally fixed things by dropping memory
- **Where:** `cycle_1_promptlog_008.txt:493-744` vs `cycle_1_promptlog_007.txt:498-519`
- **Evidence:** In invocation 8, the `<memory>` block is completely absent. The plan-mode directive was injected instead, reducing the prompt from ~700 lines to ~350 lines.
- **Root cause (positive):** The planner middleware's `_should_plan()` triggered and replaced the context. Dropping memory was an accidental optimization — the planner doesn't inject memory.
- **Impact:** This is why the flow succeeded. The model could actually "think" without 500 tokens of standing desk research distracting it.

**Cycle 1 Token Wastage Estimate: ~12,000–15,000 tokens across 8 invocations.**

---

## Cycle 2 Flow Analysis

### Execution Summary

| Invocation | Purpose | Outcome |
|---|---|---|
| 001 | System prompt + user request | Model received full system + memory + tools |
| 002 | Planner middleware | Planned against **wrong** input ("Generate a detailed structured plan...") |
| 003 | Title generation | Success (model had partial response context) |
| 004 | Agent response attempt | Planner handoff with clarification: **"What was the content of the previous user request?"** |

### Issues

#### 1. Planner loses context via cascading message injection
- **Where:** `planner_middleware.py:508-515` (`_invoke_planner`), `planner_middleware.py:541-545` (`before_model`)
- **Evidence:** `cycle_2_promptlog_002.txt:83-84` — planner LLM sees `"User request:\nGenerate a detailed structured plan for the previous user request. Work Mode detected this request is too complex for direct execution."` instead of the original Tokyo prompt. Then `cycle_2_promptlog_004.txt:753-761` — planner handoff says *"Since the context of the previous request is missing"* and asks *"What was the content of the previous user request?"*
- **Root cause:** `before_model` picks `latest_user` by iterating `reversed(messages)` for the most recent human message. A "Work Mode" system message was injected as a human message between the user's original request and the planner running. No mechanism preserves the original user prompt through middleware injection.
- **Impact:** 2 invocations (002+003) and ~90 seconds wasted producing a plan that tells the user to re-state their request. The model had to re-process the accumulated history at invocation 4.

#### 2. Complete system prompt re-sent across invocations (~1300 lines)
- **Where:** `cycle_2_promptlog_001.txt:493-764` and `cycle_2_promptlog_004.txt:493-741`
- **Evidence:** The same ~270-line system prompt block is repeated verbatim in invocations 1 and 4.
- **Root cause:** Each LangGraph invocation rebuilds the full system message from scratch.
- **Impact:** ~1300 lines of repeated system text per cycle. The `subagent_system` section (~140 lines) is irrelevant for a travel itinerary task.

#### 3. Long-term memory irrelevant to the request domain
- **Where:** `cycle_2_promptlog_001.txt:498-519`
- **Evidence:** Pickleball, protective crystals, M3 Max Thunderbolt ports, Docker sandbox mode detection, Norway maple syrup certification, standing desks under $400 — none related to Tokyo weekend planning.
- **Root cause:** No domain-based memory filtering. The memory system surfaces all "relevant" facts regardless of whether they match the current task domain.
- **Impact:** ~45 lines of noise per invocation.

#### 4. Work Mode misclassification triggers unnecessary planner overhead
- **Where:** `planner_middleware.py:284-338` (`_classify_complexity`)
- **Evidence:** `promptlog_002.txt:83` — *"Work Mode detected this request is too complex for direct execution."* The keyword "plan" in "Plan a weekend in Tokyo" triggered `_COMPLEX_KEYWORDS` matching.
- **Root cause:** The keyword-based classifier cannot distinguish "plan a vacation" (content gen) from "plan a software migration" (multi-step engineering).
- **Impact:** Triggered 3 extra invocations + planner + evaluator middleware for a task that should be direct execution.

#### 5. Planner clarification reads as a bug to the user
- **Where:** `cycle_2_promptlog_004.txt:764-769`
- **Evidence:** *"What was the content of the previous user request? Options: ['Paste original text', 'Code generation task', 'Research inquiry', 'Creative writing task']"* — this is confusing and unhelpful.
- **Root cause:** The planner prompt's `requires_clarification` field was set to true, but the clarification question was auto-generated with no awareness of the actual conversation.
- **Impact:** Loss of user trust — the assistant appears to have forgotten the conversation.

**Cycle 2 Token Wastage Estimate: ~10,000 tokens across 4 invocations (~70% of total).**

---

## Cross-Cycle Systemic Issues

### 1. System Prompt Too Large for a 3.6B Model
At ~270 lines (~1200 tokens) static + ~500 tokens memory + ~1500 tokens tools + ~2000 tokens subagent tutorial = **~5200 tokens per invocation**. For a 3.6B local model, this leaves very little budget for actual task processing. The model has a ~8K context window, so ~65% is consumed by system boilerplate before the user even speaks.

### 2. Memory Has No Relevance Filtering
Both cycles show the same pattern: user memory includes facts about Accenture, maritime law, metaphysics, pickleball, standing desks — none of which help plan a Tokyo trip. The `memory_config.py` has `max_injection_tokens=2000` but no semantic relevance threshold.

### 3. Planner  & Work Mode Interaction Is Fragile
The planner middleware:
- Picks the latest human message (not the original user intent)
- Has no mechanism to preserve original context through middleware injections
- The complexity classifier is too coarse
- The planner handoff message doesn't include the original user request text

### 4. Subagent System Section Is Overengineered
The `_build_subagent_section()` function (138 lines) is a full tutorial with:
- 3 worked examples + 2 additional usage examples + 1 counter-example
- 40+ interpolations of the concurrency limit `{n}`
- 3 separate sections teaching the same "batch and parallelize" lesson
- The `subagent_reminder` and `subagent_thinking` variables re-state the limit a 3rd time

This is appropriate for developer onboarding, not for a model system prompt.

### 5. Tool Redundancy Across Prompts
Multiple prompt surfaces share identical patterns:
- "Return ONLY valid JSON — no prose, no markdown fences" appears in planner, plan-evaluator, vault_analyze, vault_generate prompts
- Sandbox paths (`/mnt/user-data/uploads`, `/mnt/user-data/workspace`) are defined in lead agent prompt AND subagent configs
- `disallowed_tools=["task", "ask_clarification", "present_files"]` is duplicated verbatim across subagent configs

---

## Middleware & Subagent Prompt Surface Analysis

### Planner Middleware (`planner_middleware.py:213-277`)
- **~64 lines / ~550 tokens.** JSON schema takes 36 lines for 15 fields. The "TRIVIAL SIGNAL" convention and "CLARIFICATION RULES" are well-structured but duplicative with the lead agent's own clarification system.

### Plan Evaluator (`plan_evaluator_middleware.py:34-63`)
- **~30 lines / ~400 tokens.** Clean and focused. Minor: "Return ONLY valid JSON" matches planner prompt verbatim. The `revised_todos` explanation could be 1 line instead of 3.

### Evaluator (`evaluator_middleware.py:19`)
- **1 line / ~60 tokens.** The leanest prompt in the codebase. No issues.

### Web Search Summary (`web_search_summary_middleware.py:36-47`)
- **~12 lines / ~180 tokens.** Efficient. Minor: the prohibition on "The search results show..." is a reasonable guardrail for small models.

### Search Masking (`search_masking.py:15-25`)
- **~11 lines / ~150 tokens.** Concise standalone prompt. No issues.

### Subagent Prompts
- General-purpose (`general_purpose.py:16-41`): ~26 lines. `<working_directory>` duplicates sandbox paths from lead agent prompt.
- Bash agent (`bash_agent.py:16-40`): ~25 lines. Same `<working_directory>` duplication. `disallowed_tools` list duplicated from general_purpose.py.
- **Opportunity:** Extract shared constants for working_directory and disallowed_tools.

### Lead Agent Subagent Section (`prompt.py:18-155`)
- **138 lines / ~2000-2200 tokens.** This is the biggest single source of waste. A single example + short rules would suffice (~300 tokens).

### Control Plane Prompts
- Vault analyze (`vault_analyze.py`): 26 lines, clean and focused.
- Vault generate (`vault_generate.py`): 26 lines, clean and focused.
- No significant issues.

---

## Recommendations

### Priority 1: Trim the Subagent System Section (Saves ~1700 tokens/turn)
Replace the 138-line `_build_subagent_section()` with a 20-line version: 1 example, the concurrency rule, and the "decompose → delegate → synthesize" principle. Eliminate the `subagent_reminder`/`subagent_thinking` duplication.

**Target:** ~300 tokens instead of ~2000.

### Priority 2: Add Semantic Memory Filtering (Saves ~500 tokens/turn)
- Filter memory facts by cosine similarity to the current user query before injection
- Drop to `max_injection_tokens=800` for non-expert domains
- Consider domain-aware memory buckets (work vs personal vs travel)

### Priority 3: Preserve Original User Prompt Through Middleware
In `planner_middleware.py:541-545`, instead of using `latest_user` (which picks up injected messages), store the original user prompt from the first human message and pass it explicitly to `_invoke_planner`.

### Priority 4: Improve Complexity Classification
Add domain awareness to `_classify_complexity()`:
- "Plan a trip/vacation/weekend" → `moderate` (not `complex`)
- "Plan a migration/architecture/refactor" → `complex`
- Use a small classifier model or keyphrase heuristics

### Priority 5: Add Timeout Recovery Protocol
In the system prompt, add a fallback instruction:
```
If a tool call times out, immediately try an alternative approach (e.g., task delegation, direct reasoning, stated assumptions) — do not produce a blank response.
```

### Priority 6: Implement Task-Relevant Tool Pruning
Remove tool schemas for tools irrelevant to the current task (e.g., `str_replace`, `write_todos`, `save_to_knowledge_vault`, `recall` for a travel request). This saves ~500 tokens/turn.

### Priority 7: Deduplicate Cross-Prompt Patterns
- Create a shared `RETURN_ONLY_JSON` constant
- Create a shared `SANDBOX_PATHS` constant for subagent configs
- Create a shared `DISALLOWED_TOOLS` constant

### Priority 8: Fix Planner Clarification UX
When the planner generates a clarification question, include the original user request context so the question is grounded in what the user actually asked.

---

## Summary

| Metric | Cycle 1 | Cycle 2 |
|---|---|---|
| Invocations | 8 | 4 |
| Success | Yes (after external planner rescue) | Partial (context loss bug) |
| Token wastage | ~12-15K | ~10K |
| % total tokens wasted | ~75% | ~70% |
| Primary failure mode | Web search timeouts + no recovery | Planner context loss |
| Memory relevance | None | None |

The PROMPT_ID_8 data shows that the prompt system is fundamentally sound but dramatically over-engineered for the model size. A 3.6B local model cannot effectively process a 5200-token system prompt + any meaningful user task. The subagent tutorial alone consumes more tokens than many models' entire output budget. Trimming the system prompt from ~5200 → ~2000 tokens would likely improve both reliability and response quality.
