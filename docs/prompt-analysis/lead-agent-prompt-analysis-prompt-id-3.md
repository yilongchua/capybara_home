# Lead Agent Prompt Analysis — PROMPT_ID_3

**Date:** 2026-05-19  
**Model:** qwen3.6-local  
**Initial Prompt:** "Can you research crystals that people use for karma protection, spiritual protection, and bad energy? I want beginner-friendly explanations, not just a list of names."  
**Test Type:** Research task (easy difficulty) — beginner-friendly crystal guide with explanations, not just a list.

---

## 1. Metadata Summary

### Cycle 1
- **Thread ID:** `13581251-e3f2-47e7-af4b-0e7d5b9abdc9`
- **Started:** 2026-05-17T17:14:59Z
- **Completed:** 2026-05-17T17:26:48Z (~12 minutes)
- **Prompt logs:** 20 files (13 with agent tool calls, 7 infrastructure/empty)
- **Response preview:** Consolidated beginner-friendly guide covering karma-protection crystals, spiritual/bad-energy crystals as shields, with usage instructions.

### Cycle 2
- **Thread ID:** `03241d21-beac-418b-ad67-a632bf2b10af`
- **Started:** 2026-05-17T20:57:39Z
- **Completed:** 2026-05-17T21:22:40Z (~25 minutes)
- **Prompt logs:** 44 files (32 with agent tool calls, 12 infrastructure/empty)
- **Response preview:** Comprehensive guide saved as `crystals-protection-guide.md` covering 10 crystals with beginner explanations, cost estimates, cleansing instructions, buying tips, safety notes.

---

## 2. Quantitative Comparison

| Metric | Cycle 1 | Cycle 2 |
|---|---|---|
| Total log files | 20 | 44 |
| Agent runs with tool calls | 13 (65%) | 32 (73%) |
| Infrastructure/empty files | 7 (35%) | 12 (27%) |
| Avg turns per agent run | ~8 | ~11 |
| Total tool calls (all files) | 56 | 195 |
| Unique search queries | 18 unique / 42 total (57%) | 22 unique / 85 total (74% repetition) |
| Good content extraction rate | 60% | 62% |
| Empty/blocked content rate | 38% | 33% |

**Key observation:** Cycle 2 ran 2.5x more agent attempts with deeper conversations per run (11 vs 8 avg turns), but exhibited higher query repetition. The planning layer consumed significant overhead in both cycles.

---

## 3. Critical Issues Identified

### Issue #1: Massive Query Repetition (CRITICAL)

**Severity:** High  
**Impact:** Token waste, redundant work, slower completion

The agent repeats nearly identical search queries across independent runs:
- Cycle 1: 42 total queries, only **18 unique** (57% repetition)
- Cycle 2: 85 total queries, only **22 unique** (74% repetition)

Examples of repeated queries in Cycle 2:
- `"best crystals for spiritual protection black tourmaline obsidian amethyst..."` — 8 repetitions
- `"crystals for spiritual protection properties benefits where to find buy..."` — 8 repetitions  
- `"kyanite crystal karma protection breaking negative cycles..."` — 6 repetitions

**Root cause:** The lead agent prompt does not instruct the agent to deduplicate or track previously searched topics. Each subagent call is treated as a fresh run with no cross-call memory of search intent.

**Prompt fix location:** `backend/src/agents/lead_agent/prompt.py` — subagent orchestration section or critical_reminders.

**Suggested addition to `<critical_reminders>`:**
```
- Search Deduplication: Before launching web_search, consider if you've already searched for this topic. Avoid repeating similar queries across subagent calls.
```

---

### Issue #2: Plan Gate Clarification Loops (HIGH)

**Severity:** High  
**Impact:** Agent gets stuck in meta-clarification loops instead of proceeding

In Cycle 1, files `cycle_1_promptlog_017.txt` and `cycle_1_promptlog_018.txt` show the agent stuck in `[plan_gate] Clarification is required` loops. The agent itself recognized this meta-issue:
> "The planner is stuck on a meta-clarification, but the user's request is actually quite clear"

However, the agent couldn't break out of the loop because:
1. The planner middleware (`planner_middleware.py`) adds forced clarifications for research-domain tasks (e.g., "What timeframe should the research cover?")
2. The lead agent's clarification system (`prompt.py` lines 175-202) says "Default: attempt with stated assumption" but the plan gate overrides this behavior
3. The agent lacks explicit permission to bypass unnecessary clarifications

**Root cause:** Conflict between two clarification philosophies:
- Lead agent prompt says: "Proceed and state your assumption when requirements are ambiguous but a reasonable default exists"
- Planner middleware says: "Only ask for clarification when a missing detail would fundamentally change the plan" — but then adds domain-specific forced clarifications (lines 143-206 in `planner_middleware.py`)

**Prompt fix location:** `backend/src/agents/lead_agent/prompt.py` — critical_reminders or clarification_system section.

**Suggested addition to `<clarification_system>`:**
```
**Override for Planning Layer:** If the planner asks for clarification on a request that is already clear and actionable, proceed with reasonable assumptions rather than looping. The planner's forced clarifications (timeframe, scope) are optional suggestions — treat them as defaults and continue.
```

---

### Issue #3: No Search Result Quality Awareness (HIGH)

**Severity:** High  
**Impact:** Agent enters retry loops on blocked/empty content instead of adapting strategy

~30-38% of web_search results have empty `extracted_content` (blocked by cookies, CAPTCHAs, or HTML-only pages). When this happens:
- The agent simply tries more searches with similar queries rather than adapting its approach
- No fallback to alternative strategies (e.g., different search engines, direct URL fetching, or using cached/vault knowledge)
- The agent doesn't report content quality to the lead agent in a structured way

**Root cause:** The lead agent prompt doesn't include guidance for handling poor search quality. The subagent prompts (general_purpose.py, bash_agent.py) also lack this instruction.

**Prompt fix location:** `backend/src/agents/lead_agent/prompt.py` — critical_reminders; and/or `backend/src/subagents/builtins/general_purpose.py`.

**Suggested addition to subagent prompt:**
```
- Content Quality Check: If extracted content is empty or mostly boilerplate, try a different search query variant or source before retrying the same approach.
```

---

### Issue #4: Subagent Concurrency Limit Enforcement Gap (MEDIUM)

**Severity:** Medium  
**Impact:** Excess task calls silently discarded, leading to lost work

The lead agent prompt (`prompt.py` lines 28-37) clearly states "MAXIMUM {n} `task` CALLS PER RESPONSE" where n=3 by default. However:

1. The agent frequently exceeds this limit (Cycle 2 had runs with 10-11 tool calls)
2. The prompt says excess calls are "silently discarded" — but the agent has no visibility into this
3. There's no feedback mechanism to tell the agent when calls were discarded

**Root cause:** The hard limit is enforced by the system, not by prompt guidance. The agent doesn't know it's violating the limit until work is silently lost.

**Prompt fix location:** `backend/src/agents/lead_agent/prompt.py` — subagent orchestration section.

**Suggested addition:** Add a post-execution feedback loop indicator:
```
**Post-execution awareness:** If you notice that expected subagent results are missing from subsequent turns, it may mean your previous batch exceeded the concurrency limit. In that case, reduce to exactly {n} sub-tasks next turn and rebatch remaining work.
```

---

### Issue #5: No Cross-Run Learning or State Persistence (MEDIUM)

**Severity:** Medium  
**Impact:** Each agent run starts from scratch, repeating the same mistakes

Both cycles show that each log file represents an independent agent run with no memory of prior runs. The same queries, same errors, and same inefficiencies repeat across all 20 (Cycle 1) or 44 (Cycle 2) runs.

**Root cause:** This is an architectural limitation rather than a prompt issue, but the lead agent prompt could work around it by:
1. Instructing the agent to save its search queries and findings to a file in `/mnt/user-data/workspace/`
2. Instructing the agent to read any existing research state file before starting a new search batch

**Prompt fix location:** `backend/src/agents/lead_agent/prompt.py` — working_directory or critical_reminders.

**Suggested addition to `<working_directory>`:**
```
- Research State: For multi-turn research tasks, save your search queries and key findings to `/mnt/user-data/workspace/.research_state.json` so subsequent turns can avoid redundant work.
```

---

### Issue #6: Plan Mode Interference on Simple Research Tasks (MEDIUM)

**Severity:** Medium  
**Impact:** Added overhead from planning layer on tasks that don't need it

The planner middleware (`planner_middleware.py`) classifies complexity based on keyword matching and prompt length. A research task like "research crystals for karma protection" triggers the planner because it contains "research" in `_COMPLEX_KEYWORDS` (line 298). This adds:
- A planning phase that produces a structured plan with todos
- Plan evaluation by the plan evaluator middleware
- Evaluator feedback loops

For a "beginner-friendly" research task that doesn't need structured planning, this adds ~5-10 turns of overhead.

**Root cause:** The planner's keyword-based complexity classification is too broad — "research" triggers planning even for simple informational queries.

**Prompt fix location:** `backend/src/agents/middlewares/planner_middleware.py` — `_TRIVIAL_KEYWORDS` / `_COMPLEX_KEYWORDS`, or the lead agent prompt could include guidance about when to bypass planning.

**Alternative approach (prompt-only):** Add to lead agent prompt:
```
- Planning Bypass: For straightforward informational requests (e.g., "explain X", "list Y with descriptions"), you may proceed directly to research without waiting for a plan. The planning layer is designed for complex multi-step projects, not simple informational queries.
```

---

## 4. Subagent Prompt Surface Analysis

### general_purpose.py

**Strengths:**
- Clear delegation criteria with "use when" / "do not use for" guidance
- Structured 5-part output format (summary, findings, paths/artifacts, issues, citations)
- Sensible tool restrictions (no task, no ask_clarification, no present_files)

**Issues:**
1. `max_turns=50` is very generous — a stuck subagent could consume significant context without the lead agent knowing
2. No error-escalation protocol — no guidance on what constitutes failure worth reporting vs. something to work around
3. `tools=None` (inherit all tools) with blacklisted disallowed_tools is less safe than whitelisting
4. Citation format present but no guidance on *when* to cite

### bash_agent.py

**Strengths:**
- Tight tool whitelist (bash, ls, read_file, write_file, str_replace) — much safer
- Appropriate `max_turns=30` for command execution

**Issues:**
1. "Report both stdout and stderr when relevant" is vague — no structured output format
2. No explicit error-handling protocol for commands (retry? skip? abort?)
3. Missing output format discipline compared to general-purpose subagent
4. "Use absolute paths" conflicts with potential relative path instructions from lead agent

### vault_analyze.py / vault_generate.py

**Issues:**
1. No `<output_format>` section — "Return JSON only" is buried in Rules but not emphasized
2. `synthesis_refs` field is undefined — unclear what content belongs here
3. `open_questions` and `gap_queries` overlap without clear distinction
4. No confidence/uncertainty signal per claim or entity
5. No interaction guidance — lead agent has no awareness of when to trigger these prompts

---

## 5. Middleware Prompt Analysis

### planner_middleware.py — PLANNER_SYSTEM_PROMPT

**Strengths:**
- Domain-aware planning with dependency rules
- Clear JSON schema for structured output
- Good clarification guidance (max 2 questions, 3-4 options each)

**Issues:**
1. Forced domain-specific clarifications (lines 143-206) override the lead agent's "proceed with assumption" philosophy — this is a systemic conflict
2. Complexity classification relies on keyword matching which catches simple research queries

### plan_evaluator_middleware.py — _PLAN_EVAL_PROMPT

**Strengths:**
- Focused on hard problems only (circular deps, missing prerequisites, missing delivery step)
- "Be lenient — only flag genuine blockers" is good guidance

**Issues:**
1. Uses the planner model with a hard timeout — timeouts cause `decision=timeout_skipped` deterministically when budget is consumed
2. No guidance on plan quality beyond structural issues (no content/coverage evaluation)

### evaluator_middleware.py — _EVALUATOR_PROMPT_TEMPLATE

**Strengths:**
- Simple PASS/FAIL verdict with one-paragraph critique
- Pre-verify checks for unfinished todos and missing plan artifacts

**Issues:**
1. The template is extremely short (~3 lines of prompt text) — could benefit from more evaluation criteria
2. No guidance on what constitutes "good" vs "acceptable" output quality

### web_search_summary_middleware.py — _SUMMARY_PROMPT_TEMPLATE

**Strengths:**
- Focused on factual summarization with specific constraints (max 250 words)
- Preserves numbers, dates, names, URLs

**Issues:**
1. No guidance on handling contradictory information across sources
2. The summary suffix `[Summarized by web_search_summary_middleware — original: {orig_chars} chars]` adds noise to the context

---

## 6. Memory Prompt Analysis (memory/prompt.py)

### MEMORY_UPDATE_PROMPT

**Strengths:**
- Well-structured with clear section guidelines and length expectations
- Good confidence level framework (0.9-1.0 explicit, 0.7-0.8 implied)
- Important rule: "Do NOT record file upload events in memory"

**Issues:**
1. Memory injection into lead agent prompt happens at runtime but the lead agent has no guidance on *how* to use memory context
2. The `format_memory_for_injection` function truncates at 2000 tokens by default — this may cut off important context for complex research tasks

### format_memory_for_injection (lines 200-312)

**Issues:**
1. When `current_turn_text` is available, it queries the vector store for relevant facts — but this happens at every turn, potentially adding noise
2. Facts are sorted by confidence and limited to top 10/15 — but for research tasks, lower-confidence facts might still be relevant

---

## 7. Prompt Improvement Recommendations (Prioritized)

### P0 — Immediate (High Impact, Low Effort)

1. **Add search deduplication instruction to lead agent** (`prompt.py` → critical_reminders)
   - "Before searching, consider if you've already searched for this topic. Avoid redundant queries."
   - Expected impact: Reduce query repetition from 57-74% to <20%

2. **Add plan gate bypass instruction** (`prompt.py` → clarification_system)
   - "If the planner asks for optional clarifications (timeframe, scope), proceed with reasonable defaults rather than looping."
   - Expected impact: Eliminate plan gate clarification loops

3. **Add search quality awareness** (`prompt.py` → critical_reminders + subagent prompts)
   - "If web_search results are mostly empty or boilerplate, try different query variants before repeating."
   - Expected impact: Reduce retry loops on blocked content

### P1 — Short-term (High Impact, Medium Effort)

4. **Standardize subagent output format** (`general_purpose.py`, `bash_agent.py`)
   - Add explicit numbered field structure matching across all subagent prompts
   - Expected impact: More reliable lead agent parsing of subagent results

5. **Add research state file instruction** (`prompt.py` → working_directory)
   - "Save search queries and findings to `.research_state.json` for cross-turn continuity"
   - Expected impact: Enable partial state persistence across agent runs

6. **Add subagent result quality feedback** (`prompt.py` → subagent section)
   - "If subagent results are missing or empty, reduce batch size and retry with more specific prompts"
   - Expected impact: Better recovery from silent task call discards

### P2 — Medium-term (Medium Impact, Higher Effort)

7. **Align planner complexity classification** (`planner_middleware.py` → `_COMPLEX_KEYWORDS`)
   - Add negative keywords or exceptions for simple research queries
   - Expected impact: Reduce unnecessary planning overhead on informational tasks

8. **Add vault orchestration guidance** (`prompt.py` → fetch_policy or new section)
   - When to write vs. read from knowledge vault, how to use vault analysis results
   - Expected impact: Better integration of local knowledge sources

9. **Add timeout recovery guidance** (`prompt.py` → critical_reminders)
   - "If a tool times out, try an alternative approach rather than repeating the same call"
   - Expected impact: Reduce timeout-related failures

### P3 — Long-term (Architectural)

10. **Implement cross-run state persistence**
    - Architecture-level change: persist agent search history and findings between runs
    - Expected impact: Eliminate most repetition across independent agent runs

11. **Add subagent output validation layer**
    - Middleware that validates subagent outputs before returning to lead agent
    - Expected impact: Catch empty/malformed results early

---

## 8. Response Quality Assessment

### Cycle 1 Output
- Produced a consolidated beginner-friendly guide covering karma-protection crystals, spiritual/bad-energy shields
- Good structure with crystal names, properties, and usage instructions
- Coverage was comprehensive but could have been deeper

### Cycle 2 Output  
- Produced a well-structured markdown guide (`crystals-protection-guide.md`)
- Covered 10 core crystals with beginner explanations, cost estimates ($20 threshold)
- Included practical sections: cleansing, intention setting, combining stones, safety notes
- Added a buying guide with tips for spotting fake crystals and ethical sourcing
- **Overall: Higher quality than Cycle 1, with better organization and practical value**

### Quality Dimensions
| Dimension | Score (Cycle 1) | Score (Cycle 2) | Notes |
|---|---|---|---|
| Completeness | 7/10 | 9/10 | Cycle 2 added practical sections |
| Accuracy | 8/10 | 8/10 | Consistent across cycles |
| Structure/Organization | 7/10 | 9/10 | Markdown guide in Cycle 2 |
| Beginner-friendliness | 8/10 | 9/10 | Clear explanations, cost estimates |
| Efficiency (turns to completion) | 8 avg turns | 11 avg turns | Cycle 2 less efficient |
| Token efficiency | Medium | Low | High repetition in both cycles |

---

## 9. Files Analyzed

### Prompt Logs (PROMPT_ID_3)
- `prompt-tunning/PROMPT_ID_3/cycle_1_metadata.json` (20 log files)
- `prompt-tunning/PROMPT_ID_3/cycle_2_metadata.json` (44 log files)
- Representative logs: `cycle_1_promptlog_{001,007,020}.txt`, `cycle_2_promptlog_{001,015,035,044}.txt`

### Source Code Prompts
- `backend/src/agents/lead_agent/prompt.py` (701 lines) — Lead agent system prompt
- `backend/src/agents/memory/prompt.py` (351 lines) — Memory update and injection prompts
- `backend/src/agents/lead_agent/todo_prompts.py` (110 lines) — Todo list system prompt
- `backend/src/agents/middlewares/planner_middleware.py` (775 lines) — Planner system prompt
- `backend/src/agents/middlewares/plan_evaluator_middleware.py` (274 lines) — Plan evaluator prompt
- `backend/src/agents/middlewares/evaluator_middleware.py` (220 lines) — Terminal evaluator prompt
- `backend/src/agents/middlewares/web_search_summary_middleware.py` (251 lines) — Search summarization prompt
- `backend/src/subagents/builtins/general_purpose.py` — General-purpose subagent config
- `backend/src/subagents/builtins/bash_agent.py` — Bash agent config
- `backend/src/security/search_masking.py` (89 lines) — Search query anonymization prompt
- `backend/src/control_plane/prompts/vault_analyze.py` — Knowledge vault analysis prompt
- `backend/src/control_plane/prompts/vault_generate.py` — Knowledge vault page generation prompt
