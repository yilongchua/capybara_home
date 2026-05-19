# Lead Agent Prompt Analysis — PROMPT_ID_20

> **Date:** 2026-05-19
> **Model:** `mlx-community/qwen3.6-35b-a3b` (qwen3.6-local)
> **Runtime:** server
> **Mode:** work (auto_mode: true)
> **Test Prompt:** "Act like a research assistant for someone deciding whether to move from Singapore to London, Dubai, or Sydney. Compare taxes, career opportunity, rent, healthcare, lifestyle, climate, and long-term tradeoffs."

---

## 1. File Inventory

| File | Cycle | Role |
|---|---|---|
| `cycle_1_metadata.json` | 1 | Run metadata, 10 prompt logs |
| `cycle_1_promptlog_001.txt` | 1 | Initial system prompt + user request (tools attached) |
| `cycle_1_promptlog_002.txt` | 1 | Planner prompt (JSON plan generation) |
| `cycle_1_promptlog_003.txt` | 1 | Title generation prompt |
| `cycle_1_promptlog_004.txt` | 1 | Web search summary — SG→Sydney tax |
| `cycle_1_promptlog_005.txt` | 1 | Web search summary — SG→London tax |
| `cycle_1_promptlog_006.txt` | 1 | Web search summary — SG→Dubai tax |
| `cycle_1_promptlog_007.txt` | 1 | System prompt + 3× `web_search` timeout errors |
| `cycle_1_promptlog_008.txt` | 1 | System prompt (no memory) + plan request |
| `cycle_1_promptlog_009.txt` | 1 | System prompt + planner_handoff + planner_clarification + system_reminder |
| `cycle_1_promptlog_010.txt` | 1 | Same as 009 + AI attempt + 3× plan_gate blocks |
| `cycle_2_metadata.json` | 2 | Run metadata, 8 prompt logs |
| `cycle_2_promptlog_001.txt` | 2 | Initial system prompt + user request (tools attached) |
| `cycle_2_promptlog_002.txt` | 2 | Planner prompt (identical to cycle 1) |
| `cycle_2_promptlog_003.txt` | 2 | Title generation prompt (identical) |
| `cycle_2_promptlog_004.txt` | 2 | Web search summary — Dubai tax |
| `cycle_2_promptlog_005.txt` | 2 | Web search summary — London tax |
| `cycle_2_promptlog_006.txt` | 2 | System prompt + 2× timeout + 1× zero-result search |
| `cycle_2_promptlog_007.txt` | 2 | System prompt (no memory) + plan request |
| `cycle_2_promptlog_008.txt` | 2 | System prompt + planner_handoff + planner_clarification + system_reminder |

**No cycle_3 files exist.**

---

## 2. Cycle 1 Execution Flow Analysis

### 2.1 Timeline (all timestamps UTC, 2026-05-17)

| Log | Timestamp | Elapsed | Event |
|---|---|---|---|
| 001 | 20:28:28 | 0s | Initial turn: system prompt (~767 lines) + user request. Tools attached. |
| 002 | 20:28:30 | +2s | Planner prompt invoked (JSON plan generation). No tools. |
| 003 | 20:28:44 | +14s | Title generation prompt. |
| 004 | 20:28:48 | +4s | Web search summary: SG→Sydney tax (5 results, all populated). |
| 005 | 20:28:51 | +3s | Web search summary: SG→London tax (5 results, some empty `extracted_content`). |
| 006 | 20:28:52 | +1s | Web search summary: SG→Dubai tax (5 results, some empty). |
| 007 | 20:29:29 | +37s | **CRITICAL**: System prompt re-injected. 3× `web_search` timeout errors (45s each). Memory block **present**. |
| 008 | 20:29:31 | +2s | System prompt re-injected. Memory block **absent**. Plan request appended. |
| 009 | 20:31:42 | +2m11s | System prompt + planner_handoff + planner_clarification + system_reminder. **Memory absent**. |
| 010 | 20:31:58 | +16s | Same as 009 + AI response attempt + 3× plan_gate blocks. **Total runtime: ~3m30s**. |

### 2.2 Key Failures in Cycle 1

#### Failure 1: Triple `web_search` Timeout (log 007)
- Three parallel `web_search` calls all exceeded the 45s timeout.
- The system prompt was **re-injected** at this point (message_count: 6), meaning the full ~767-line system prompt was resent.
- The memory block (`<memory>`) was still present at this turn.

#### Failure 2: Memory Disappearance (log 008 onward)
- At log 007, the `<memory>` block is present (lines 498-519: User Context, History, Relevant Facts).
- At log 008, the `<memory>` block is **completely absent**. The system prompt jumps from `<role>` directly to `<thinking_style>`.
- This pattern persists through logs 009 and 010.
- **Root cause hypothesis:** The memory injection via `_inject_memory_context()` in `prompt.py:569-577` either failed silently or the middleware stopped injecting memory after the timeout recovery.

#### Failure 3: Planner Handoff Deadlock (logs 009-010)
- The planner middleware generated a plan with `Clarification required: yes` asking "What was the content of the previous user request?"
- This is a **context loss bug**: the planner cannot see the original user request that triggered the plan.
- The AI attempted to proceed with research (log 010, role=ai: "I'll research this comprehensively...") but was blocked by 3× `[plan_gate]` responses.
- The plan_gate messages repeat the same clarification question, creating a deadlock loop.

### 2.3 Search Quality in Cycle 1
- **SG→Sydney tax** (log 004): 5 results with good `extracted_content`. Query: `Singapore to Sydney tax comparison 2026 income tax expat`
- **SG→London tax** (log 005): 5 results, but 3 of 5 have empty `extracted_content`. Query: `Singapore to London tax comparison 2026 income tax expat`
- **SG→Dubai tax** (log 006): 5 results, 3 of 5 have empty `extracted_content`. Query: `Singapore to Dubai tax comparison 2026 income tax expat`
- **Pattern:** Only the first search (Sydney) returned fully populated results. Subsequent searches degraded, suggesting the search backend was under load or rate-limited.

---

## 3. Cycle 2 Execution Flow Analysis

### 3.1 Timeline (all timestamps UTC, 2026-05-17)

| Log | Timestamp | Elapsed | Event |
|---|---|---|---|
| 001 | 23:22:21 | 0s | Initial turn: system prompt (~767 lines) + user request. |
| 002 | 23:22:23 | +2s | Planner prompt (JSON plan generation). |
| 003 | 23:25:19 | +2m56s | Title generation prompt. **Long gap** — planner took ~3 min. |
| 004 | 23:25:27 | +8s | Web search summary — Dubai tax (5 results, some empty). |
| 005 | 23:25:29 | +2s | Web search summary — London tax (5 results, some empty). |
| 006 | 23:26:04 | +35s | System prompt + 2× timeout + 1× zero-result (Sydney). **No memory**. |
| 007 | 23:26:07 | +3s | Same as 006 + plan request. **No memory**. |
| 008 | 23:29:19 | +3m12s | Planner handoff deadlock (same pattern as cycle 1). **Total runtime: ~7m20s**. |

### 3.2 Key Differences from Cycle 1

| Aspect | Cycle 1 | Cycle 2 |
|---|---|---|
| Memory in initial prompt | Present | Present |
| Memory after timeout | Lost at log 008 | **Never present** after initial (log 006 onward) |
| Search order | Sydney → London → Dubai | Dubai → London → Sydney |
| Sydney search result | 5 populated results | **0 results** (empty) |
| Timeout pattern | 3× timeout at log 007 | 2× timeout + 1× zero-result at log 006 |
| Total runtime | ~3m30s | ~7m20s (2× slower) |
| Planner clarification | "What was the content of the previous user request?" | Same question, different options |

### 3.3 Cycle 2 Regressions

1. **Memory injection completely absent** after the initial turn. In cycle 1, memory persisted through log 007 before disappearing. In cycle 2, it was gone by log 006.
2. **Sydney search returned zero results** — the query `Australia Sydney tax rates 2025 expat income tax comparison Singapore resident` returned `total_results: 0`. This is a search query quality issue.
3. **Longer planner latency** — the title generation took ~3 minutes (log 001→003), compared to ~14 seconds in cycle 1.
4. **No improvement in planner deadlock** — the same context-loss bug persists.

---

## 4. Lead Agent `prompt.py` Construction Analysis

### 4.1 Architecture

The prompt is built via two modes controlled by `prompt_cfg.componentized`:

1. **Legacy mode** (`LEGACY_SYSTEM_PROMPT_TEMPLATE`): Single monolithic template with `{variable}` substitution.
2. **Componentized mode** (`_build_componentized_prompt`): Joins 10 section templates with `\n\n`.

Both produce the same output structure:

```
<role> → <soul> → <memory> → <thinking_style> → <clarification_system>
→ <skill_system> → <subagent_system> → <working_directory> → <fetch_policy>
→ <response_style> → <citations> → <critical_reminders> → <current_date>
```

### 4.2 Prompt Size

- **System prompt alone:** ~767 lines (approximately 4,500-5,500 tokens)
- **Subagent section alone:** ~100 lines (~600 tokens) — the single largest static block
- **Memory block (when present):** ~22 lines (~300-500 tokens) — highly variable
- **Total initial turn:** ~800 lines (~5,000-6,000 tokens)

### 4.3 Memory Injection Mechanism

```python
# prompt.py:569-577
def _inject_memory_context(prompt: str, memory_context: str) -> str:
    memory = memory_context.strip()
    if not memory:
        return prompt
    marker = "\n<thinking_style>"
    if marker not in prompt:
        return f"{memory}\n\n{prompt}"
    return prompt.replace(marker, f"\n{memory}\n\n<thinking_style>", 1)
```

**Critical finding:** Memory is injected by string replacement on the cached prompt. If the cached prompt doesn't contain `\n<thinking_style>` (e.g., due to componentization differences), memory falls back to prepending — which may cause ordering issues.

### 4.4 Subagent Section Bloat

The `_build_subagent_section()` function (lines 8-155) generates ~150 lines of instruction text. It includes:
- 3 full examples (Tencent stock, 5 cloud providers, auth refactor)
- 3 code blocks with Python examples
- Repeated warnings about the 3-call limit (mentioned 8+ times)
- Usage examples that consume ~60 lines alone

**This section is 20% of the total prompt size** and repeats the same constraint multiple times.

---

## 5. Memory `prompt.py` Bloat Analysis

### 5.1 Memory Injection Size

The `<memory>` block injected in cycle 1 contains:
- **User Context:** 3 sub-sections (Work, Personal, Current Focus) — ~250 words
- **History:** 2 sub-sections (Recent, Earlier) — ~350 words
- **Relevant Facts:** 10 facts — ~200 words
- **Total:** ~800 words (~1,000-1,200 tokens)

### 5.2 Bloat Issues

1. **Stale context:** Memory contains references to projects that may no longer be active (Luke Legal Case Analysis, Greece itinerary, Netherlands trip). The `topOfMind` section is a dense paragraph of 5+ concurrent priorities.
2. **Fact redundancy:** Some facts overlap with the User Context section (e.g., CAG project mentioned in both Work context and Relevant Facts).
3. **No pruning logic:** The `format_memory_for_injection()` function truncates by token count but doesn't prioritize recency or relevance. It sorts facts by confidence, but the User Context and History sections are injected wholesale.
4. **Memory update prompt** (`MEMORY_UPDATE_PROMPT`, lines 18-120): 120 lines of instructions for the memory agent itself — this is a separate concern but contributes to overall system complexity.

---

## 6. Related Prompt Surface Issues

### 6.1 Planner Middleware Context Loss

The planner middleware (`planner_middleware.py`) generates a plan based on "the previous user request" but **does not have access to the conversation history**. The planner prompt receives:

```
User request:
Generate a detailed structured plan for the previous user request. Work Mode detected this request is too complex for direct execution.
```

There is no injection of the actual user request text. This is the root cause of the planner clarification deadlock.

### 6.2 Web Search Summary Prompt

The web search summary prompt (seen in logs 004-006) is a fixed template:

```
You are a research assistant. The following text is the raw result of a web search query.
Summarize it into a concise, factual paragraph (max 250 words)...
```

This prompt is **not logged in the prompt logs as a separate system prompt** — it appears as a single `role=human` message. This means the summarization is done by the same model in the same context, consuming context window.

### 6.3 Search Query Quality

Cycle 2's Sydney search query was:
```
Australia Sydney tax rates 2025 expat income tax comparison Singapore resident
```

This returned **zero results**. Compare with Cycle 1's query:
```
Singapore to Sydney tax comparison 2026 income tax expat
```

This returned 5 populated results. The Cycle 2 query is longer, more specific, and uses "2025" instead of "2026" — all factors that likely contributed to the empty result.

---

## 7. Consolidated Findings

### 7.1 Critical Issues (P0)

| # | Issue | Evidence | Impact |
|---|---|---|---|
| 1 | **Planner context loss** | Logs 009-010 (C1), 008 (C2): planner asks "What was the content of the previous user request?" | Deadlock on every complex request; agent cannot proceed |
| 2 | **Memory injection disappears after timeout** | Log 007 (C1) has memory; log 008 (C1) does not. Log 006 (C2) never has memory. | Agent loses all user context mid-execution |
| 3 | **Triple web_search timeout** | Logs 007 (C1), 006 (C2): 3 parallel searches all timeout or return empty | Wastes 45s+ per timeout; no data gathered for synthesis |

### 7.2 High-Priority Issues (P1)

| # | Issue | Evidence | Impact |
|---|---|---|---|
| 4 | **Subagent section bloat** | ~150 lines, 8+ repetitions of same constraint | Consumes 20% of prompt tokens; dilutes attention |
| 5 | **Search query degradation** | C2 Sydney query returns 0 results vs C1's 5 results | Missing data dimension in final answer |
| 6 | **Web search summary in context** | Summary prompts consume model turns and context window | Reduces available context for actual reasoning |
| 7 | **Memory staleness** | Memory contains completed/abandoned projects | Irrelevant context competes for attention |

### 7.3 Medium-Priority Issues (P2)

| # | Issue | Evidence | Impact |
|---|---|---|---|
| 8 | **Prompt re-injection after timeout** | Full 767-line system prompt resent on every turn after timeout | Wastes tokens; compounds context window pressure |
| 9 | **Planner latency variance** | C1: 14s for title; C2: 3min for title | Unpredictable user experience |
| 10 | **Empty extracted_content in search results** | 3/5 results empty in C1 logs 005-006 | Reduces signal-to-noise for summarization |

---

## 8. Improvement Recommendations (Todos)

### P0 — Must Fix

1. **Fix planner context loss**: Inject the original user request text into the planner prompt. The planner middleware should receive the conversation history or at minimum the triggering user message.

2. **Fix memory injection persistence**: Investigate why `_inject_memory_context()` stops working after a timeout. Add logging to track when memory injection succeeds/fails. Ensure the marker `\n<thinking_style>` is always present in the cached prompt.

3. **Implement web_search retry/backoff**: Instead of 3 parallel searches that all timeout, implement sequential fallback: try parallel, if 2+ timeout, retry with staggered timing or reduced concurrency.

### P1 — Should Fix

4. **Compress subagent section**: Reduce from ~150 lines to ~60 lines. Keep the hard limit warning (1×), one concise example, and the workflow steps. Remove redundant warnings and the second code example.

5. **Improve search query generation**: Add query validation or fallback. If a search returns 0 results, automatically retry with a simplified query (remove year, remove comparison terms).

6. **Move web search summary out of main context**: The search summary should be done by a separate middleware step or subagent, not as a turn in the main conversation. This preserves context window for reasoning.

7. **Implement memory recency pruning**: Add a `max_age_days` parameter to `format_memory_for_injection()`. Deprioritize or exclude facts/context older than N days unless marked as `longTermBackground`.

### P2 — Nice to Have

8. **Implement prompt delta injection**: Instead of re-injecting the full system prompt after a timeout, only inject the parts that changed (e.g., tool results, reminders). The static sections (role, thinking_style, etc.) are already in the conversation history.

9. **Add planner timeout guard**: If the planner takes >30s, fall back to a simpler plan template or skip planning entirely for this turn.

10. **Add search result quality scoring**: Filter out results with empty `extracted_content` before sending to the summarization prompt. Log a warning when >50% of results are empty.

---

## 9. Prompt Size Breakdown

| Section | Lines (approx) | Tokens (approx) | % of Total |
|---|---|---|---|
| `<role>` | 3 | 15 | 0.3% |
| `<memory>` (when present) | 22 | 1,100 | 18% |
| `<thinking_style>` | 8 | 80 | 1.3% |
| `<clarification_system>` | 22 | 180 | 3% |
| `<subagent_system>` | 100 | 600 | 10% |
| `<working_directory>` | 20 | 180 | 3% |
| `<fetch_policy>` | 8 | 80 | 1.3% |
| `<response_style>` | 4 | 30 | 0.5% |
| `<citations>` | 10 | 60 | 1% |
| `<critical_reminders>` | 14 | 120 | 2% |
| `<current_date>` | 1 | 10 | 0.2% |
| **Static total** | ~212 | ~2,455 | 41% |
| **Tool definitions** | ~400 | ~2,500 | 42% |
| **Conversation history** (variable) | ~155 | ~1,045 | 17% |
| **Total (initial turn)** | ~767 | ~6,000 | 100% |

---

## 10. Cycle Comparison Summary

| Metric | Cycle 1 | Cycle 2 | Change |
|---|---|---|---|
| Prompt logs | 10 | 8 | -2 |
| Total runtime | 3m30s | 7m20s | +110% |
| Memory present in initial | Yes | Yes | Same |
| Memory present after timeout | Yes (until log 008) | No (from log 006) | Worse |
| Successful searches | 3/3 (partial) | 2/3 (1 zero-result) | Worse |
| Timeouts | 3 | 2 | Better |
| Planner deadlock | Yes | Yes | Same |
| Final answer delivered | Yes (from response_preview) | No (empty response_preview) | Worse |

**Conclusion:** Cycle 2 regressed on almost every metric despite being a second iteration. The core issues (planner context loss, memory injection fragility, search timeout handling) remain unaddressed between cycles.
