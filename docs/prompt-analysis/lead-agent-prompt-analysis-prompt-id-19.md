# Lead Agent Prompt Analysis — PROMPT_ID_19

> **Test query:** "Compare the best approaches to investing $10,000 as a beginner in 2026. Explain index funds, bonds, cash, crypto, risk tolerance, taxes, and what not to do."
> **Model:** `mlx-community/qwen3.6-35b-a3b` (local, qwen3.6-local)
> **Cycles analyzed:** Cycle 1 (20:21–20:27 UTC) + Cycle 2 (23:14–23:21 UTC)
> **Date:** 2026-05-17

---

## 1. File Catalog

| File | Purpose |
|---|---|
| `cycle_1_metadata.json` | Cycle 1 run metadata — thread ID, timing, model, initial prompt |
| `cycle_1_promptlog_001.txt` | Initial system prompt + user request (full lead agent prompt with memory) |
| `cycle_1_promptlog_002.txt` | Planner middleware prompt (JSON plan generation) |
| `cycle_1_promptlog_003.txt` | Title generation prompt (max 6 words) |
| `cycle_1_promptlog_004.txt` | Web search summary middleware — tax rules query |
| `cycle_1_promptlog_005.txt` | Web search summary middleware — investing $10k query |
| `cycle_1_promptlog_006.txt` | Web search summary middleware — interest rates query |
| `cycle_1_promptlog_007.txt` | Re-invocation with 3× web_search timeouts |
| `cycle_1_promptlog_008.txt` | Re-invocation (memory stripped) with 3× web_search timeouts + planner handoff |
| `cycle_1_promptlog_009.txt` | Title generation (retry) |
| `cycle_2_metadata.json` | Cycle 2 run metadata — different thread, same query |
| `cycle_2_promptlog_001.txt` | Initial system prompt + user request (Cycle 2) |
| `cycle_2_promptlog_002.txt` | Planner middleware prompt (identical to C1) |
| `cycle_2_promptlog_003.txt` | Title generation (identical to C1) |
| `cycle_2_promptlog_004.txt` | Web search summary — bond market query |
| `cycle_2_promptlog_005.txt` | Web search summary — index funds query |
| `cycle_2_promptlog_006.txt` | Re-invocation with 2× timeouts + 1× empty crypto search |
| `cycle_2_promptlog_007.txt` | Re-invocation (memory stripped) with same failures + planner handoff |
| `cycle_2_promptlog_008.txt` | Title generation (retry) |
| `cycle_2_promptlog_009.txt` | Final re-invocation with planner handoff + clarification required |

---

## 2. Execution Flow Analysis

### 2.1 Cycle 1 Flow (9 prompts, ~5m 45s total)

```
[001] Lead agent system prompt (767 lines) + user request
      → Model receives full prompt with memory, subagent, fetch_policy, etc.
      → Model launches 3× parallel web_search calls

[004, 005, 006] Web search summary middleware intercepts 3 results
      → Each result > threshold chars → LLM summarizes inline
      → Queries: tax rules, investing $10k, interest rates
      → All 3 summaries succeed

[007] Re-invocation: 3× web_search TIMEOUT (45s each)
      → Model tried 3 more searches, all exceeded 45s timeout
      → System injected: "Tool `web_search` exceeded the 45s timeout and was cancelled."

[008] Re-invocation (memory stripped — <memory> block removed)
      → Same 3× timeouts persist
      → Planner middleware injects handoff: "Generate a detailed structured plan..."

[002] Planner prompt (invoked as middleware, not in main loop)
      → JSON plan generation with todos, domain, clarifications

[003, 009] Title generation (2× — likely initial + retry)
      → Simple 6-word title prompt

[009] Final state: Plan created but clarification required
      → Planner produced a plan asking "What was the primary subject?"
      → This is a BUG — the domain should have been detected as "research"
```

### 2.2 Cycle 2 Flow (9 prompts, ~6m 56s total)

```
[001] Lead agent system prompt (767 lines) + user request
      → Same structure as Cycle 1

[004, 005] Web search summary — bond market + index funds
      → Both succeed with valid results

[006] Re-invocation: 2× web_search TIMEOUT + 1× EMPTY crypto search
      → 2 searches timed out at 45s
      → 1 search returned 0 results (crypto query)

[007] Re-invocation (memory stripped)
      → Same timeout pattern
      → Planner handoff injected

[002] Planner prompt → JSON plan generation
[003, 008] Title generation (2×)

[009] Final state: Plan with clarification required
      → Same bug: planner asks "What was the primary subject?"
      → Plan title: "Clarify Missing Request Context"
      → Domain: "generic" (should be "research")
```

---

## 3. Critical Findings

### 3.1 P0 — Planner Domain Misclassification (Both Cycles)

**Problem:** The planner middleware classified the investment research query as `domain: "generic"` instead of `"research"`. This caused:

1. The planner produced a clarification question asking "What was the primary subject?" with options like "Coding or technical development", "Research or content creation", etc.
2. This is nonsensical — the user request explicitly says "Compare the best approaches to investing $10,000" which is clearly research.
3. The `_classify_complexity()` function in `planner_middleware.py:326` uses keyword matching but does NOT feed domain classification. Domain is determined by the planner LLM itself, which failed.

**Root cause:** The planner LLM (qwen3.6-35b-a3b) is not reliably classifying domain. The `PLANNER_SYSTEM_PROMPT` provides the schema with `domain: "code|research|legal|trip|generic"` but gives no guidance on how to choose.

**Impact:** Execution stalls waiting for user clarification on an obvious research task.

### 3.2 P0 — Web Search Timeout Cascade (Both Cycles)

**Problem:** In both cycles, the model launched 3 parallel `web_search` calls and ALL timed out at 45s. This is a systemic issue:

- Cycle 1: 3 searches succeeded initially (prompts 004-006), then 3 more timed out (prompt 007)
- Cycle 2: 2 searches succeeded, 1 returned empty, then 2 more timed out (prompt 006)

**Root cause:** The model is launching too many concurrent searches, overwhelming the search backend. The `fetch_policy` section tells the model to use `web_search` first but doesn't limit concurrency.

**Impact:** 45s × 3 = 135s wasted per timeout cascade. The model then retries, causing another cascade.

### 3.3 P1 — Memory Bloat in System Prompt

**Problem:** The `<memory>` section in the lead agent prompt is ~400 lines of dense text covering:
- Work context (3 long paragraphs)
- Personal context (2 long paragraphs)
- Current Focus (2 massive paragraphs with 15+ concurrent initiatives)
- History: Recent (400+ words)
- History: Earlier (100+ words)
- Relevant Facts (10 bullet points)

This memory block is injected into EVERY turn, consuming significant context window tokens. For a 35B parameter model, this is a substantial fraction of the available context.

**Observation:** In Cycle 1 prompt 008 and Cycle 2 prompt 007, the `<memory>` block was stripped (likely due to token budget management). The system continued functioning, suggesting much of the memory is not critical for task execution.

### 3.4 P1 — Subagent Section Dominates Prompt (~35% of total)

**Problem:** The `<subagent_system>` section is ~130 lines (lines 560-697 in promptlog_001), making up roughly 35% of the total system prompt. For a research task like "investing $10,000", subagent decomposition is NOT the right approach — the task should be answered directly with web research.

**Evidence:** In neither cycle did the model actually use subagents. The entire section is dead weight for this query type.

### 3.5 P2 — Web Search Summary Prompt Redundancy

**Problem:** The web search summary middleware prompt (`web_search_summary_middleware.py:36-47`) is identical in structure across all invocations. It works well when searches succeed, but:

1. The prompt is 250-word max summary — but the raw results often contain 2000+ chars of navigation chrome, not actual content
2. Several search results returned empty or near-empty extracted_content (Cloudflare bot protection, paywalls)
3. The middleware doesn't filter out empty results before summarization

### 3.6 P2 — Title Generation Prompt Wasted Turns

**Problem:** Title generation fires twice per cycle (prompts 003 + 009 in C1, 003 + 008 in C2). This suggests the first attempt failed or was retried. Each is a 26-line prompt for a trivial task.

---

## 4. Prompt Construction Analysis (lead_agent/prompt.py)

### 4.1 Architecture

The prompt is built via `_build_prompt()` which supports two modes:
- **Legacy mode:** `LEGACY_SYSTEM_PROMPT_TEMPLATE` — single monolithic template with `{variable}` substitution
- **Componentized mode:** `_build_componentized_prompt()` — joins 12 separate section templates

Both modes produce identical output. The componentized mode exists for future flexibility but adds no current value.

### 4.2 Section Ordering (as rendered)

```
1. <role>                          — 3 lines
2. <soul>                          — variable (empty if no SOUL.md)
3. <memory>                        — ~400 lines (INJECTED AT RUNTIME)
4. <thinking_style>                — 8 lines (+ subagent decomposition check)
5. <clarification_system>          — 25 lines
6. <skill_system>                  — variable (empty if no skills)
7. <subagent_system>               — ~130 lines
8. <working_directory>             — 20 lines
9. <fetch_policy>                  — 8 lines
10. <response_style>               — 5 lines
11. <citations>                    — 10 lines
12. <critical_reminders>           — 15 lines (+ subagent reminder)
13. <current_date>                 — 1 line
```

**Total static prompt:** ~230 lines (without memory)
**With memory:** ~630 lines

### 4.3 Memory Injection Mechanism

Memory is injected via `_inject_memory_context()` which inserts the `<memory>` block before `<thinking_style>`. The memory content comes from `format_memory_for_injection()` in `memory/prompt.py`, which:

1. Merges global + workspace memory scopes
2. Formats User Context, History, Facts
3. Truncates to `max_tokens` (default 2000) using tiktoken

**Issue:** The 2000-token limit is generous. The actual memory in both cycles was ~1500-1800 tokens, filling most of the budget with information irrelevant to the current query.

---

## 5. Related Prompt Surface Analysis

### 5.1 Planner Middleware (`planner_middleware.py`)

**Strengths:**
- Well-structured JSON schema with clear field descriptions
- Dependency rules for different domains
- Clarification rules with option ordering
- Complexity classification via keyword matching

**Weaknesses:**
- Domain classification is delegated entirely to the LLM with no guidance
- `_ensure_research_clarifications()` only auto-adds clarifications for "ai trends" queries, not general research
- No fallback when the LLM returns `domain: "generic"` for an obviously research-classified query

### 5.2 Plan Evaluator Middleware (`plan_evaluator_middleware.py`)

**Strengths:**
- Fast async evaluation with proper `asyncio.wait_for`
- Lenient — only flags hard problems (circular deps, missing prerequisites)
- Graceful timeout handling

**Weaknesses:**
- Only runs once (sets `plan_evaluated: true`) — doesn't re-evaluate after clarification
- The prompt doesn't check domain classification quality

### 5.3 Evaluator Middleware (`evaluator_middleware.py`)

**Strengths:**
- Deterministic pre-verification (checks todos completion)
- LLM-based verdict with structured parsing

**Weaknesses:**
- Very short prompt template (~4 lines) — lacks evaluation criteria
- No domain-specific evaluation rubrics

### 5.4 Web Search Summary Middleware (`web_search_summary_middleware.py`)

**Strengths:**
- Proper async/sync paths
- Character threshold prevents unnecessary summarization
- Graceful fallback on timeout/failure

**Weaknesses:**
- No content quality filtering before summarization
- Empty results (like the crypto search in C2) still trigger the middleware
- No deduplication of overlapping search results

---

## 6. Todo List for Lead Agent Prompt Improvement

### P0 — Critical (Blockers)

- [ ] **Fix planner domain classification for research queries.** Add domain detection heuristics to `_classify_complexity()` or add a pre-classification step that detects research keywords (compare, explain, analyze, research, invest, guide, etc.) and forces `domain: "research"` before the LLM planner runs. Alternatively, add domain selection guidance to `PLANNER_SYSTEM_PROMPT`.

- [ ] **Add web search concurrency guard.** The model launches 3 parallel searches that all timeout. Add explicit guidance in `<fetch_policy>` to limit concurrent searches to 1-2, or add a middleware-level throttle. Consider adding: "When doing web research, launch at most 2 searches at a time. If a search times out, do not retry the same query."

- [ ] **Prevent planner clarification on self-evident queries.** The planner asked "What was the primary subject?" for a query that explicitly states its topic. Add a pre-check: if the user prompt contains 3+ topic keywords from the request itself, skip clarification.

### P1 — High Impact

- [ ] **Reduce memory injection budget.** Lower `max_injection_tokens` from 2000 to 1000-1200. The memory block is too verbose and consumes context that could be used for task reasoning. Implement tiered memory: always inject facts (short), conditionally inject context (medium), lazily load history (long).

- [ ] **Make subagent section conditional on task type.** The 130-line `<subagent_system>` section is irrelevant for direct-answer research queries. Consider: (a) shortening it to ~40 lines, (b) making it dynamically injected only when complexity is "complex", or (c) moving subagent guidance to a skill that loads on demand.

- [ ] **Add timeout recovery guidance to the prompt.** The model receives "[model_timeout] Tool `web_search` exceeded the 45s timeout" but has no instruction on what to do next. Add to `<fetch_policy>`: "If a web_search times out, try a different query formulation or proceed with available results. Do not retry the same query."

- [ ] **Improve web search result quality filtering.** Before passing results to the summary middleware, filter out: (a) empty extracted_content, (b) Cloudflare/bot protection pages, (c) navigation chrome. This reduces wasted LLM calls and context pollution.

### P2 — Medium Impact

- [ ] **Consolidate duplicate prompt sections.** The `LEGACY_SYSTEM_PROMPT_TEMPLATE` and `_build_componentized_prompt()` produce identical output. Remove one or add a clear migration path. The 12 component templates duplicate the legacy template's content.

- [ ] **Shorten `<critical_reminders>`.** Currently 15 lines with some redundancy (e.g., "Always Respond" and "CRITICAL: After thinking, you MUST provide your actual response" say the same thing). Consolidate to 8-10 lines.

- [ ] **Fix title generation retry loop.** Title generation fires twice per cycle. Investigate why the first attempt fails and either fix it or accept the first result.

- [ ] **Add domain-specific fetch policies.** The `<fetch_policy>` section is generic. For research queries, add: "For research tasks, prioritize web_search for current data (2025-2026), then query_knowledge_vault for historical context. Limit to 3 searches total."

- [ ] **Improve web search summary prompt for empty results.** When `total_results: 0` (like the crypto search in C2), the summary prompt should not fire. Add a guard: only summarize if `total_results > 0` and `extracted_content` is non-empty.

### P3 — Low Impact / Nice-to-Have

- [ ] **Add response format guidance for research queries.** The `<response_style>` says "Use paragraphs and prose, not bullet points by default" but for comparison queries like "Compare the best approaches", structured output (tables, bullet comparisons) is more useful. Make this domain-aware.

- [ ] **Reduce tool schema verbosity in prompt logs.** Each promptlog file includes the full tool schema (~490 lines of JSON). This is useful for debugging but inflates log files. Consider separating tool schema into a header file.

- [ ] **Add prompt size monitoring.** Log the total token count of the assembled prompt (static + memory) per turn. This helps identify when context is approaching model limits.

---

## 7. Cycle Comparison Summary

| Metric | Cycle 1 | Cycle 2 |
|---|---|---|
| Total runtime | ~5m 45s | ~6m 56s |
| Successful web searches | 3 | 2 |
| Timed-out searches | 3 | 2 |
| Empty searches | 0 | 1 |
| Planner domain detected | generic (WRONG) | generic (WRONG) |
| Clarification required | Yes (unnecessary) | Yes (unnecessary) |
| Memory present in final turn | No (stripped) | No (stripped) |
| Subagents used | No | No |
| Final output quality | Good (from response_preview) | Good (from response_preview) |

**Key insight:** Both cycles produced good final answers despite the planner bug and search timeouts. The model fell back to its training knowledge when searches failed. However, the unnecessary clarification step and timeout cascades add ~2-3 minutes of wasted time per cycle.

---

## 8. Recommendations Priority Order

1. **Fix domain classification** (P0) — Eliminates the nonsensical clarification step
2. **Add search concurrency guard** (P0) — Prevents timeout cascades
3. **Reduce memory budget** (P1) — Frees context for task reasoning
4. **Shorten subagent section** (P1) — Reduces prompt bloat for non-subagent tasks
5. **Add timeout recovery guidance** (P1) — Helps model handle failures gracefully
6. **Filter empty search results** (P1) — Reduces wasted LLM calls
7. **Consolidate duplicate templates** (P2) — Code maintainability
8. **Domain-aware fetch policy** (P2) — Better search strategy per task type
