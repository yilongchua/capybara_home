# Lead Agent Prompt Analysis — PROMPT_ID_14

> **Date:** 2026-05-19
> **Scope:** `prompt-tunning/PROMPT_ID_14/` (cycle 1 + cycle 2 logs, metadata)
> **Primary files:** `backend/src/agents/lead_agent/prompt.py`, `backend/src/agents/memory/prompt.py`
> **Related surfaces:** planner/evaluator/todo/web-search middlewares, subagent prompts, search masking
> **Test query:** "Help me choose between Bali, Chiang Mai, Lisbon, and Mexico City for 2 months of remote work. Compare cost, internet, safety, community, weather, and visa basics."
> **Model:** `mlx-community/qwen3.6-35b-a3b` (local MLX)

---

## 1. File Catalog

| File | Type | Lines | Purpose |
|---|---|---|---|
| `cycle_1_metadata.json` | Metadata | — | Cycle 1 run config, response preview, log provenance |
| `cycle_1_promptlog_001.txt` | Prompt log | ~764 | Lead agent system prompt + user request (initial injection) |
| `cycle_1_promptlog_002.txt` | Prompt log | ~83 | Planning assistant JSON schema prompt |
| `cycle_1_promptlog_003.txt` | Prompt log | ~26 | Title generation prompt |
| `cycle_1_promptlog_004.txt` | Prompt log | ~775 | Lead agent retry — 3x web_search FAILED (asyncio semaphore) |
| `cycle_1_promptlog_005.txt` | Prompt log | ~745 | Lead agent retry w/ memory removed — same failures + planning fallback |
| `cycle_2_metadata.json` | Metadata | — | Cycle 2 run config, response preview, log provenance |
| `cycle_2_promptlog_001.txt` | Prompt log | ~767 | Lead agent system prompt + user request (cycle 2 initial) |
| `cycle_2_promptlog_002.txt` | Prompt log | ~83 | Planning assistant (same as cycle 1) |
| `cycle_2_promptlog_003.txt` | Prompt log | ~26 | Title generator (same as cycle 1) |
| `cycle_2_promptlog_004.txt` | Prompt log | — | Research summarizer — safety/community query (5 results, 3 empty) |
| `cycle_2_promptlog_005.txt` | Prompt log | — | Research summarizer — internet speed query (5 results, 3 empty) |
| `cycle_2_promptlog_006.txt` | Prompt log | — | Research summarizer — cost of living query (5 results, 4 empty) |
| `cycle_2_promptlog_007.txt` | Prompt log | — | Lead agent turn — 3x web_search TIMEOUT (45s) |
| `cycle_2_promptlog_008.txt` | Prompt log | ~747 | Lead agent turn w/ memory removed — same timeouts + planning fallback |

---

## 2. Execution Flow Architecture

### 2.1 Pipeline Structure (Both Cycles)

```
[1] Lead Agent System Prompt + User Request
    └── Model attempts parallel web_search (3 calls)
    └── Cycle 1: asyncio.Semaphore event-loop mismatch → ALL FAIL
    └── Cycle 2: 45s timeout per call → ALL TIMEOUT

[2] Planning Assistant (JSON plan generator)
    └── Triggered by "Work Mode detected this request is too complex"
    └── Produces structured JSON: trivial, title, objective, todos, risks, clarifications
    └── Domain detection: trip (correct for this query)

[3] Title Generator
    └── Minimal prompt: "Generate a concise title (max 6 words)"
    └── Used for UI/thread naming

[4] Lead Agent Retry (Cycle 1: logs 004-005)
    └── Same failures persist

[5] Research Summarizer (Cycle 2: logs 004-006)
    └── 3 separate web_search queries fired in parallel:
        - safety/community
        - internet speed
        - cost of living
    └── Each returns 5 results, but 60-80% have empty extracted_content
    └── Results queued for knowledge vault ingestion

[6] Lead Agent Final Turn (Cycle 2: logs 007-008)
    └── web_search calls timeout again (45s)
    └── Empty AI response
    └── Fallback to planning assistant
```

### 2.2 Key Observation: No Tool Call Succeeded in Either Cycle

- **Cycle 1:** `asyncio.locks.Semaphore ... bound to a different event loop` — infrastructure bug
- **Cycle 2:** 45s timeout on all parallel `web_search` calls — reliability regression
- Both cycles ultimately produced usable responses (see `response_preview` in metadata), but these came from the model's **internal knowledge**, not from tool-executed research
- The agent correctly fell back to "I'll draw from my knowledge base" when tools failed

---

## 3. Prompt Construction Analysis (`prompt.py`)

### 3.1 System Prompt Structure

The lead agent's system prompt is assembled via `_build_prompt()` with two modes:

| Mode | Template | Characteristics |
|---|---|---|
| **Legacy** | `LEGACY_SYSTEM_PROMPT_TEMPLATE` | Single monolithic string with `{}` interpolation |
| **Componentized** | `_build_componentized_prompt()` | 12 named section templates, joined with `\n\n` |

Both modes produce functionally identical output. The componentized mode is preferred (controlled by `prompt_cfg.componentized`).

### 3.2 Section Breakdown (Componentized)

| Section | Template Variable | Approx. Lines | Notes |
|---|---|---|---|
| `<role>` | `ROLE_SECTION_TEMPLATE` | 3 | Static identity |
| `<soul>` | `get_agent_soul()` | variable | Loaded from `SOUL.md` if present |
| `<memory>` | `_get_memory_context()` | 0-20 | Runtime injection, not cached |
| `<thinking_style>` | `THINKING_STYLE_SECTION_TEMPLATE` | 8 | Includes subagent decomposition check |
| `<clarification_system>` | `CLARIFICATION_SECTION` | 22 | When to ask vs. assume |
| `<skill_system>` | `get_skills_prompt_section()` | variable | Dynamic based on enabled skills |
| `<subagent_system>` | `_build_subagent_section()` | 80-100 | **Largest section** — 3 full examples |
| `<working_directory>` | `WORKING_DIRECTORY_SECTION` | 22 | File management rules |
| `<fetch_policy>` | `FETCH_POLICY_SECTION` | 10 | Search priority order |
| `<response_style>` | `RESPONSE_STYLE_SECTION` | 4 | Output formatting |
| `<citations>` | `CITATIONS_SECTION` | 10 | Citation format |
| `<critical_reminders>` | `CRITICAL_REMINDERS_SECTION_TEMPLATE` | 14 | Catch-all reminders |

**Total:** ~740-760 lines depending on memory/skills presence.

### 3.3 Subagent Section — The Heaviest Component

`_build_subagent_section()` (lines 8-130 of `prompt.py`) is the single largest block at ~100 lines. It contains:

- Core principle statement
- Hard concurrency limit explanation (with `{n}` placeholder)
- Multi-batch execution pattern
- 3 detailed examples (stock analysis, cloud comparison, auth refactor)
- Task decomposition quality bar (4 rules)
- When to use vs. not use subagents (5 + 5 bullet points)
- Critical workflow (6 steps)
- 3 usage examples with code blocks
- Violation warning

**Assessment:** This section is well-structured but extremely verbose. The 3 examples alone consume ~40 lines. For a 35B local model, this represents significant context budget that could be trimmed without losing enforcement power.

### 3.4 Memory Context Injection

`_get_memory_context()` (lines 280-318) loads memory at prompt-render time:

- Global + workspace memory scopes
- Formatted via `format_memory_for_injection()` from `memory/prompt.py`
- Token-limited by `max_injection_tokens` (default 2000)
- Wrapped in `<memory>` tags
- **Not cached** — injected into the cached prompt via `_inject_memory_context()`

**Assessment:** Memory injection is correctly separated from the cached base prompt. The memory content itself (analyzed below) is the bloat concern, not the injection mechanism.

### 3.5 Mode Sections

Three optional mode sections are appended post-cache:

| Mode | Section | Trigger |
|---|---|---|
| Dreamy Mode | `DREAMY_MODE_SECTION` | `dreamy_mode=True` |
| Plan Mode | `PLAN_MODE_SECTION` | `plan_mode=True` |
| Background Followup | `PLAN_BACKGROUND_FOLLOWUP_SECTION` | `plan_mode=True` + `background_followup=True` |

These are appended as raw text after the base prompt. Dreamy mode disables `task()` tool entirely.

---

## 4. Memory Prompt Analysis (`memory/prompt.py`)

### 4.1 Prompt Templates

| Template | Purpose | Lines |
|---|---|---|
| `MEMORY_UPDATE_PROMPT` | Update user memory from conversation | ~100 |
| `FACT_EXTRACTION_PROMPT` | Extract facts from single message | ~25 |

### 4.2 Memory Update Prompt — Over-Specified

`MEMORY_UPDATE_PROMPT` (351 lines total file, ~100 lines of prompt) contains:

- Detailed section guidelines for `workContext`, `personalContext`, `topOfMind`
- History timeline specifications (`recentMonths`, `earlierContext`, `longTermBackground`)
- Fact extraction categories with confidence levels
- "What Goes Where" disambiguation rules
- Multilingual content rules
- Important rules section (9 bullet points)

**Assessment:** This prompt is over-specified for a memory update task. The "What Goes Where" section repeats guidance already implied by the section descriptions. The confidence level guidelines are useful but could be compressed.

### 4.3 `format_memory_for_injection()` — Token Management

The function correctly:
- Merges global + workspace memory scopes
- Formats user context, history, behavior rules, and relevant facts
- Uses tiktoken for accurate token counting
- Truncates to `max_tokens` (default 2000) with 95% margin

**Issue:** The fallback to character-based estimation (`len(text) // 4`) when tiktoken is unavailable is crude but acceptable as a last resort.

### 4.4 Memory Bloat Assessment

From the prompt logs, the `<memory>` block in cycle 1/2 logs contains:

```
User Context:
- Work: [~2 sentences]
- Personal: [~1 sentence]
- Current Focus: [~3-5 sentences]

History:
- Recent: [~4-6 sentences]
- Earlier: [~3-5 sentences]

Relevant Facts:
- [10-15 facts with categories]
```

This is ~15-20 lines of dense text. While not enormous, it adds ~200-300 tokens to every turn. The cycle 1/005 and cycle 2/008 experiments removing memory showed **no improvement in tool execution**, confirming memory is not the bottleneck.

---

## 5. Related Prompt Surface Analysis

### 5.1 `todo_prompts.py` — Severe Duplication

| Issue | Severity |
|---|---|
| `TODO_LIST_SYSTEM_PROMPT` and `TODO_LIST_TOOL_DESCRIPTION` share ~50% content overlap | **High** |
| Both contain identical "When to Use", "When NOT to Use", "Best Practices" sections | **High** |
| "complex tasks (3+ steps)" phrase repeated 4+ times across both prompts | Medium |
| Only used in legacy plan mode (DAG mode has its own inline prompt) | Medium |

**Recommendation:** Consolidate into a single source of truth. The tool description should reference the system prompt, not duplicate it.

### 5.2 `planner_middleware.py` — Well-Structured but Heavy

- `PLANNER_SYSTEM_PROMPT` (line 213) is a large JSON-schema-enforcing prompt
- Makes independent LLM call via "planner" model profile
- Contains domain-specific hardcoded questions in `_ensure_research_clarifications()` (line 143)
- Complexity classification (`_classify_complexity`, line 326) uses keyword heuristics that could conflict with LLM's own `trivial` judgment

**Assessment:** The planner prompt is well-designed but the hardcoded research clarifications are a maintenance concern. The keyword-based complexity classifier is fragile.

### 5.3 `plan_evaluator_middleware.py` — Lean and Focused

- `_PLAN_EVAL_PROMPT` (line 34) is ~30 lines, concise and purpose-specific
- Checks for circular dependencies, missing prerequisites, missing synthesis steps
- Fail-open safety check (timeouts don't block execution)
- Shares `_run_with_timeout` pattern with other middlewares (DRY opportunity)

**Assessment:** Minimal bloat. Well-scoped.

### 5.4 `evaluator_middleware.py` — Underspecified Prompt

- `_EVALUATOR_PROMPT_TEMPLATE` (line 19) is a **single line** — extremely minimal
- Asks for `VERDICT: PASS or FAIL` with `CRITIQUE` paragraph
- Gives almost no guidance on what constitutes PASS vs FAIL
- Verdict parsing is fragile (searches for `VERDICT:` in first matching line)
- `_pre_verify()` method (line 88) overlaps conceptually with plan evaluator

**Assessment:** The prompt is too underspecified for reliable evaluation. The LLM needs more concrete criteria.

### 5.5 `web_search_summary_middleware.py` — Clean but Redundant Pattern

- `_SUMMARY_PROMPT_TEMPLATE` (line 36) is clean and purpose-specific
- Condenses oversized results to 250 words
- `_WEB_SEARCH_TOOL_NAMES` frozenset and `_is_web_search()` method have overlapping matching logic
- Shares `_run_with_timeout` pattern with two other middlewares

**Assessment:** Good prompt design. The `_run_with_timeout` pattern should be extracted to a shared utility.

### 5.6 Cross-Cutting Issues

| Issue | Files | Severity |
|---|---|---|
| `_run_with_timeout` duplicated across 3 middlewares | planner_evaluator, web_search_summary, evaluator | Medium |
| `_extract_text` duplicated in planner + evaluator | planner_middleware, evaluator_middleware | Low |
| Three middlewares all resolve "planner" model profile | planner, plan_evaluator, web_search_summary | Low (intentional) |
| Pre-verify overlaps with plan evaluator | evaluator_middleware, plan_evaluator_middleware | Medium |

---

## 6. Cycle Comparison

### 6.1 Cycle 1 vs Cycle 2

| Aspect | Cycle 1 | Cycle 2 | Change |
|---|---|---|---|
| **Failure mode** | asyncio.Semaphore event-loop mismatch | 45s web_search timeout | Different symptom, same root (tool infrastructure) |
| **Research queries** | 1 monolithic search attempt | 3 targeted queries (safety, internet, cost) | **Improvement** — better decomposition |
| **Scraping yield** | N/A (all failed) | 60-80% empty extracted_content | **Concern** — poor content extraction |
| **Memory experiment** | Removed in log 005, no effect | Removed in log 008, no effect | **Confirmed** — memory not the bottleneck |
| **Fallback mechanism** | Planning assistant triggered | Planning assistant triggered | Same fallback path |
| **Response quality** | Good (from internal knowledge) | Good (from internal knowledge) | Comparable |
| **Total runtime** | ~3m 19s | ~6m 25s | **Regression** — 2x slower |
| **Prompt logs** | 5 files | 8 files | More granular pipeline split |

### 6.2 What Changed Between Cycles

1. **Query decomposition improved:** Cycle 2 fires 3 targeted searches instead of 1 broad attempt
2. **Timeout handling added:** Cycle 2 has explicit 45s timeout per search (cycle 1 had semaphore bug)
3. **Scraping quality degraded:** Cycle 2 shows 60-80% empty content extraction
4. **Runtime doubled:** 3m 19s → 6m 25s (likely due to 3 sequential search batches)
5. **Pipeline more granular:** 5 logs → 8 logs (research summarizer logs added)

---

## 7. Findings Summary

### 7.1 Critical Issues

| # | Issue | Impact | Root Cause |
|---|---|---|---|
| 1 | **web_search tool failures** | All research attempts fail in both cycles | Infrastructure: asyncio event-loop mismatch (cycle 1) / timeout (cycle 2) |
| 2 | **Empty AI responses before tool calls** | Model produces no visible text before launching tools | Model behavior: jumps straight to tool calling |
| 3 | **Poor scraping yield** (cycle 2) | 60-80% of search results return empty content | External: content extraction pipeline |
| 4 | **Query truncation** (cycle 2, log 006) | `executed_query` shorter than original `query` | Bug: query string truncated during execution |

### 7.2 Prompt Quality Issues

| # | Issue | Severity | Location |
|---|---|---|---|
| 5 | **System prompt is ~750 lines** | Medium | `prompt.py` — total assembled prompt |
| 6 | **Subagent section is ~100 lines with 3 full examples** | Medium | `_build_subagent_section()` |
| 7 | **todo_prompts.py has 50% duplication** | High | `todo_prompts.py` |
| 8 | **Evaluator prompt is underspecified (1 line)** | Medium | `evaluator_middleware.py:19` |
| 9 | **Memory update prompt is over-specified** | Low | `memory/prompt.py:MEMORY_UPDATE_PROMPT` |
| 10 | **_run_with_timeout duplicated 3x** | Medium | 3 middleware files |

### 7.3 What Works Well

- Planning assistant prompt is well-structured with clear JSON schema
- Research summarizer prompt is concise and effective
- Memory injection is correctly separated from cached prompt
- Componentized prompt mode is clean and maintainable
- Fallback mechanism to planning assistant works reliably
- Skill system prompt section is well-designed with progressive disclosure

---

## 8. TODO List — Prompt Improvements

### P0 — Critical (Infrastructure, Not Prompt)

- [ ] **Fix web_search asyncio event-loop mismatch** — semaphore objects created in one event loop are used in another. This is the root cause of cycle 1 failures and likely contributes to cycle 2 timeouts.
- [ ] **Investigate 45s web_search timeout** — cycle 2 shows systematic timeouts. May be related to MLX model running on macOS native event loop while LangGraph creates its own loop.
- [ ] **Fix query truncation bug** — `executed_query` in cycle 2/log 006 is shorter than the original query, losing search precision.

### P1 — High Priority (Prompt Quality)

- [ ] **Consolidate `todo_prompts.py` duplication** — `TODO_LIST_SYSTEM_PROMPT` and `TODO_LIST_TOOL_DESCRIPTION` share ~50% content. Extract shared guidance into a single source.
- [ ] **Trim subagent section verbosity** — `_build_subagent_section()` is ~100 lines with 3 full examples. Consider reducing to 2 examples and compressing the workflow steps. Target: ~60 lines.
- [ ] **Strengthen evaluator prompt** — `_EVALUATOR_PROMPT_TEMPLATE` is a single line with no concrete PASS/FAIL criteria. Add specific evaluation dimensions (completeness, accuracy, plan adherence).
- [ ] **Compress memory update prompt** — `MEMORY_UPDATE_PROMPT` has redundant "What Goes Where" section that repeats section descriptions. Remove duplication. Target: ~70 lines.

### P2 — Medium Priority (Architecture)

- [ ] **Extract `_run_with_timeout` to shared utility** — duplicated across 3 middleware files. Create `backend/src/agents/middlewares/utils.py`.
- [ ] **Extract `_extract_text` to shared utility** — duplicated in `planner_middleware.py` and `evaluator_middleware.py`.
- [ ] **Remove hardcoded research clarifications** — `_ensure_research_clarifications()` in planner middleware embeds domain-specific logic. Make configurable or move to domain-specific module.
- [ ] **Improve complexity classifier** — `_classify_complexity()` uses keyword heuristics that conflict with LLM's own `trivial` judgment. Consider using LLM judgment as primary signal.
- [ ] **Strengthen verdict parsing** — evaluator's `VERDICT:` parsing is fragile. Use structured JSON output instead of text parsing.

### P3 — Low Priority (Optimization)

- [ ] **Evaluate memory injection ROI** — cycle experiments show memory removal has no effect on tool execution. Consider making memory injection conditional on task type (skip for research/comparison tasks).
- [ ] **Reduce citation section verbosity** — `<citations>` section is 10 lines with a full example. Could be compressed to 3-4 lines.
- [ ] **Consider prompt section ordering** — `<working_directory>` (22 lines) appears before `<fetch_policy>` (10 lines). For research tasks, fetch policy is more relevant. Consider dynamic ordering based on task type.
- [ ] **Document "planner" model profile usage** — 3 middlewares use the same model profile. This is intentional but undocumented. Add a comment or config note.

### P4 — Observability

- [ ] **Add prompt token counting to logs** — log the token count of each assembled prompt turn for monitoring context window pressure.
- [ ] **Add section-level token breakdown** — track which prompt sections consume the most tokens across turns.
- [ ] **Log scraping yield metrics** — track empty `extracted_content` rate to monitor content extraction quality over time.

---

## 9. Appendix

### 9.1 Prompt Log Timeline

```
Cycle 1 (2026-05-17 18:27:43 UTC — 18:31:02 UTC, ~3m 19s)
  18:27:43.948  → 001: Lead agent system prompt + user request
  18:27:45.951  → 002: Planning assistant
  18:28:09.751  → 003: Title generator
  18:28:09.780  → 004: Lead agent retry (3x web_search FAILED — semaphore)
  18:28:11.835  → 005: Lead agent retry w/ memory removed (same failures)

Cycle 2 (2026-05-17 22:32:31 UTC — 22:38:57 UTC, ~6m 25s)
  22:32:32.754  → 001: Lead agent system prompt + user request
  22:32:34.793  → 002: Planning assistant
  22:34:01.477  → 003: Title generator
  22:34:07.178  → 004: Research summarizer — safety/community
  22:34:09.306  → 005: Research summarizer — internet speed
  22:34:09.844  → 006: Research summarizer — cost of living
  22:34:46.530  → 007: Lead agent turn (3x web_search TIMEOUT — 45s)
  22:34:48.582  → 008: Lead agent turn w/ memory removed (same timeouts)
```

### 9.2 Tool Registration

Both cycles register 13 tools:
`ls`, `read_file`, `write_file`, `str_replace`, `bash`, `present_files`, `ask_clarification`, `recall`, `write_todos`, `web_search`, `save_to_knowledge_vault`, `task`, `view_image`

### 9.3 Key File References

| File | Path |
|---|---|
| Lead agent prompt | `backend/src/agents/lead_agent/prompt.py` (701 lines) |
| Memory prompt | `backend/src/agents/memory/prompt.py` (351 lines) |
| Todo prompts | `backend/src/agents/lead_agent/todo_prompts.py` |
| Planner middleware | `backend/src/agents/middlewares/planner_middleware.py` |
| Plan evaluator middleware | `backend/src/agents/middlewares/plan_evaluator_middleware.py` |
| Evaluator middleware | `backend/src/agents/middlewares/evaluator_middleware.py` |
| Web search summary middleware | `backend/src/agents/middlewares/web_search_summary_middleware.py` |
