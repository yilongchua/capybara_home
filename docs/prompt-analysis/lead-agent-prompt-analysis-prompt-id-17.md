# Lead Agent Prompt Analysis — PROMPT_ID_17

## Overview

- **Test prompt**: "I need to understand the current Israel-Palestine conflict without propaganda. Summarize the recent timeline, humanitarian situation, political constraints, and where sources disagree."
- **Model**: `qwen3.6-35b-a3b` (via ChatOpenAI wrapper)
- **Mode**: work / auto_mode=true
- **Total prompt logs**: 42 (Cycle 1: 31, Cycle 2: 11)
- **Cycle 1 duration**: ~10.5 min (20:05:33 → 20:16:08)
- **Cycle 2 duration**: ~5.8 min (22:58:51 → 23:04:44)

## 1. Critical Execution Failures (Both Cycles)

### 1a. Web Search Timeout Epidemic

Every prompt log after the initial system injection shows the same pattern:

```
[model_timeout]
Tool `web_search` exceeded the 45s timeout and was cancelled.
```

- **Cycle 1**: timeout mentions grow monotonically from 1 (log 001) → 21 (logs 021-025). The agent never learns — it retries `web_search` up to 15+ times per turn even after observing repeated failures.
- **Cycle 2**: Same pattern — timeout mentions grow 1 → 11 across 11 logs, with identical retry behavior. The agent burns through the retry budget every cycle.

**Root cause**: The `fetch_policy` section in `prompt.py` lists `web_search` as priority #1, and there is **no instruction to stop retrying after N consecutive failures**. The prompt tells the agent to "use sources in this priority order" but never says "after 2 timeouts, skip web_search entirely and go straight to fallback."

**Cycle 1 escape hatch**: Around turn 15, the agent found BBC RSS feeds and switched to reading those instead. The best response came from RSS data, not web_search. Cycle 2 never found this alternative and ended up relying solely on training data.

### 1b. task() Call Limit Violation

The prompt hard-declares `max 3` task calls per response. Every prompt log shows **9 task() calls** being generated per turn. The excess 6 are silently discarded by the backend.

**Impact**: The agent's sub-task decomposition produces 9 sub-tasks per turn (likely from the subagent examples in the prompt), but only 3 execute. The remaining 6 represent wasted LLM output tokens and lost work. The agent never receives feedback that calls were discarded (silent discard), so it has no way to correct behavior.

**Root cause**: The subagent examples in `prompt.py` (`_build_subagent_section`) are long and vivid (compare 5 cloud providers, refactor auth system, etc.), but the agent generalizes from these into massive decompositions of 9+ sub-tasks — far exceeding the limit.

### 1c. Knowledge Vault Returns Irrelevant Context

The agent falls back to `query_knowledge_vault` after web_search fails, but the returned facts are about entirely unrelated topics:

- Accenture Refinery POC (URA RAG API)
- Legal case folder (EHP 2025 / Luke s340)
- S&P 500 macroeconomic indicators
- Iran war analysis requests

**Root cause**: `MEMORY_UPDATE_PROMPT` in `memory/prompt.py` records facts broadly without domain classification. There is no per-domain relevance filtering in `format_memory_for_injection`. The vector store recall (`get_memory_vector_store().query()`) returns top-k by embedding similarity without cross-referencing whether those facts are topically related to the current conversation.

### 1d. Agent Stuck in Retry-React Loop

After 3+ web_search timeouts, the agent responds:

> "Web search is timing out — let me pull from the knowledge vault and internal sources first."

Then it queries the knowledge vault, gets irrelevant results, and **immediately tries web_search again** — repeating the same cycle that just failed.

```
web_search ×3 → timeout
query_knowledge_vault → irrelevant results
web_search ×3 → timeout  (repeat)
```

This loop burns 10+ turns per cycle. The prompt has no "if web_search fails N times, stop using it" instruction, no circuit-breaker pattern, and no explicit guidance on when to switch to training-data-only mode.

## 2. System Prompt Structural Issues

### 2a. Subagent Section Bloat

`_build_subagent_section()` in `prompt.py` generates ~300 lines of subagent instructions including:

- Task decomposition workflow (50+ lines)
- 3 full worked examples (100+ lines)
- 2 usage code examples (100+ lines)
- Multi-batch execution instructions
- Counter-example with direct execution

**Problem**: This section dominates the system prompt and crowds out other critical instructions. The mass of examples causes the model to over-decompose tasks (always creating 6-9 sub-tasks regardless of task complexity).

### 2b. Triplicate Subagent Reminders

Subagent instructions appear in **three separate locations** in the assembled prompt:

1. `<subagent_system>` section (`_build_subagent_section`)
2. `subagent_reminder` in `<critical_reminders>` (Orchestrator Mode line)
3. `subagent_thinking` in `<thinking_style>` (DECOMPOSITION CHECK instruction)

This redundancy wastes tokens and creates conflicting emphasis — the `<subagent_system>` section says max 3, but the sheer volume of subagent content signals "this is very important" and the model over-prioritizes decomposition.

### 2c. Legacy Template vs Componentized Build

`_build_prompt()` supports two paths:

- **Legacy**: Single `LEGACY_SYSTEM_PROMPT_TEMPLATE` string with `.format()` substitution
- **Componentized**: Individual sections concatenated in `_build_componentized_prompt()`

The componentized path is cleaner but both still produce essentially the same content. The `prompt_config.componentized` flag controls which path is used.

**Issue**: The legacy template is still the default in some code paths. The componentized version doesn't enforce any structural improvements — it just concatenates the same sections.

### 2d. Memory Injection at Runtime

`_inject_memory_context()` inserts memory context just before `<thinking_style>` in the cached prompt. This works but:
- The memory context can push the prompt over the model's effective context window
- `format_memory_for_injection` has a `max_tokens=2000` limit but doesn't account for the base prompt size
- No truncation/priority logic for when memory + base prompt exceed model limits

### 2e. Fetch Policy Ordering

Current order in `<fetch_policy>`:
1. `web_search`
2. `query_knowledge_vault`
3. `query_lightrag`
4. `search_internal_documents`

When `web_search` is persistently unavailable (local model without internet), the agent wastes all its turns on step 1 before ever reaching 2-4. The policy should account for the possibility that web_search is unavailable **for the entire session**.

## 3. Response Quality: Cycle 1 vs Cycle 2

### Cycle 1 Response

Cycle 1 produced a rich, structured response organized by **three concurrent fronts** (Gaza, West Bank, Israel-Iran). It cited real BBC RSS data, named specific articles, and provided concrete dates and events. **Quality: HIGH** — the agent successfully adapted by finding BBC RSS feeds.

### Cycle 2 Response

Cycle 2 produced a generic response organized by **generic sections** (Timeline, Humanitarian, etc.). It openly stated "Web search is persistently timing out" and relied on training data (up to early 2025). **Quality: MEDIUM-LOW** — the response was structured but contained no real-time data, contradicted the user's request for "current" information, and never found the RSS alternative.

### Attribution

The quality difference is **not attributable to the prompt itself** — both cycles used identical prompts (same agent_id, same model, same test case). The difference is stochastic: Cycle 1 happened to discover RSS feeds; Cycle 2 did not. This means **the current prompt does not reliably produce high-quality research outcomes** — success depends on lucky exploration, not prompt guidance.

## 4. Related Prompt Surface Issues

### 4a. Planner Middleware (`planner_middleware.py`)

- **PLANNER_SYSTEM_PROMPT** (line ~129): Clean JSON schema with specific max todos limit. Good structure.
- **Complexity classification** (`_classify_complexity`): Keywords-based heuristic is fragile. "defence" and "legal" and "law" are listed but domain-specific terms like "Israel-Palestine" or "geopolitical conflict" are not. This test case would be classified as "complex" only because length >300 chars.
- **Research fanout**: Has `research_fanout` feature but it defaults to off. When enabled, this could help parallelize research but only after plan approval.

### 4b. Plan Evaluator (`plan_evaluator_middleware.py`)

- `_PLAN_EVAL_PROMPT`: Reasonably scoped to 3 checks (circular deps, missing prerequisites, missing synthesis). Good leniency instruction.
- **Timeout risk**: Uses same model as planner. If planner consumed the budget, evaluator deterministically times out (`decision=timeout_skipped`).

### 4c. Evaluator Middleware (`evaluator_middleware.py`)

- `_EVALUATOR_PROMPT_TEMPLATE`: Minimal — just VERDICT + CRITIQUE. Fine for terminal verification but too simplistic for nuanced quality assessment.
- **Pre-verification check**: Checks for incomplete todos — useful but wouldn't have caught the research quality gap in Cycle 2.

### 4d. Web Search Summary Middleware (`web_search_summary_middleware.py`)

- Handles oversized web_search results by summarizing them. **Not triggered** in this test case because web_search never returned results — it always timed out.
- Could be enhanced to also handle the "timeout" case by notifying the main agent to stop trying.

### 4e. Search Masking (`search_masking.py`)

- Adds an LLM call (re-routing through a model) before every web_search. For a local model that's already timing out on web_search, this **adds latency and can deepen timeouts**.
- When the masking model call fails, it raises `ValueError` — no graceful fallback to the original query.

### 4f. Memory Update Prompt (`memory/prompt.py`)

- **MEMORY_UPDATE_PROMPT** (351 lines total): Extremely verbose with detailed length guidelines, section-by-section rules, and multilingual content handling. This prompt itself consumes significant tokens.
- The "Do NOT record file upload events" instruction at the bottom is a hack — should be a filter rule, not a prompt instruction.
- **Fact extraction** produces facts with extremely broad categories (preference, knowledge, context, behavior, goal). These are insufficiently granular for topical relevance filtering.

### 4g. Todo Prompts (`todo_prompts.py`)

- `TODO_LIST_SYSTEM_PROMPT` and `TODO_LIST_TOOL_DESCRIPTION`: Both promote task management for "3+ steps" but don't mention the subagent concurrency limit. The agent creates 9 sub-tasks in todos even though only 3 can execute per turn. This creates friction: the todo list says "plan for all tasks" but the subagent system says "only 3 per turn."

## 5. Recommendations (TODOs)

### Priority 1: Fix Web Search Loops

- [ ] **Add circuit-breaker guidance to `<fetch_policy>`**: After 2 consecutive web_search timeouts, skip web_search for the rest of the turn. Only retry once per turn maximum, not per message.
- [ ] **Add fallback routing instruction**: "If web_search consistently fails, immediately move to alternative sources (knowledge vault, lightrag, training data). Do not retry web_search more than once per turn."
- [ ] **Surface timeout feedback in tool result**: The current `[model_timeout]` message could be enhanced to say "web_search unavailable this turn; do not retry until next turn."
- [ ] **Evaluate search_masking.py latency impact**: For local models, consider skipping the masking LLM call or caching rewrites to reduce timeout probability.

### Priority 2: Fix task() Over-Decomposition

- [ ] **Reduce `_build_subagent_section()` example count**: Remove 2 of 3 worked examples and 1 of 2 code examples. Keep only the batch splitting example. The section should be ~100 lines, not ~300.
- [ ] **Add a hard-count instruction**: "If you identify more than N sub-tasks, stop and re-think. You can only launch 3 per turn."
- [ ] **Add feedback mechanism**: Replace silent discard with an explicit error message when task call limit is exceeded, so the agent learns.
- [ ] **Remove redundant reminders**: The subagent instructions appear 3 times. Keep only the `<subagent_system>` section; remove the duplicate reminders from `<critical_reminders>` and `<thinking_style>`.

### Priority 3: Improve Knowledge Vault Relevance

- [ ] **Add domain/topic tags to memory facts** so the retrieval can filter by topical relevance.
- [ ] **In `format_memory_for_injection()`**, add a relevance filter: only inject facts whose domain overlaps with the current conversation topic.
- [ ] **Reduce max_injection_tokens** from 2000 to 500 or implement token budget per-section (e.g., max 500 for user context, max 500 for facts).

### Priority 4: Prompt Structure Optimization

- [ ] **Switch componentized prompt to default** and remove legacy template code path.
- [ ] **Prune MEMORY_UPDATE_PROMPT** from 351 lines to ~150 lines. The per-section length guidelines are too detailed and cause the model to over-generate.
- [ ] **Add token budget tracking**: The `_build_prompt()` function should estimate total prompt tokens and warn when approaching the model's limit.
- [ ] **Merge `todo_prompts.py` todo limits with subagent limits** so the todo list tool doesn't suggest more tasks than can be parallelized.

### Priority 5: Reliability & Monitoring

- [ ] **Add session-level web_search failure counter** to state so the prompt can conditionally skip web_search after N consecutive failures.
- [ ] **Add runtime event for "final answer used training data only"** so operators can detect when the agent couldn't fetch live data.
- [ ] **Test with a model that can actually perform web_search** (e.g., GPT-4o) to isolate whether these are model-level issues or prompt-level issues.
- [ ] **Consider adding a timeout handler middleware** that catches `[model_timeout]` patterns and injects a system message telling the agent to stop retrying that tool.

### Priority 6: Test Completeness

- [ ] **Add test cases that specifically test error recovery**: How does the agent behave when web_search always fails? When knowledge vault is empty? When subagent limit is hit?
- [ ] **Add a regression test for task() call count**: Verify the agent never generates more than max_concurrent task calls per response.
- [ ] **Run with non-controversial factual queries** to separate "web_search failure" issues from "geopolitical content handling" issues.

---

## Appendix: Key File Paths

| File | Lines | Role |
|---|---|---|
| `backend/src/agents/lead_agent/prompt.py` | 701 | System prompt construction |
| `backend/src/agents/lead_agent/todo_prompts.py` | 110 | Todo list tool prompt |
| `backend/src/agents/memory/prompt.py` | 351 | Memory update/injection prompts |
| `backend/src/agents/middlewares/planner_middleware.py` | 775 | Plan generation |
| `backend/src/agents/middlewares/plan_evaluator_middleware.py` | 274 | Plan quality check |
| `backend/src/agents/middlewares/evaluator_middleware.py` | 220 | Response evaluation |
| `backend/src/agents/middlewares/web_search_summary_middleware.py` | 251 | Web search result summarization |
| `backend/src/security/search_masking.py` | 89 | Search query anonymization |
| `prompt-tunning/PROMPT_ID_17/cycle_1_metadata.json` | — | Cycle 1 config/results |
| `prompt-tunning/PROMPT_ID_17/cycle_2_metadata.json` | — | Cycle 2 config/results |
