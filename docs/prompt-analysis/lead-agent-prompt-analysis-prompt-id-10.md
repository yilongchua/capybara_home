# Lead Agent Prompt Analysis — PROMPT_ID_10

**Date:** 2026-05-19
**Model:** mlx-community/qwen3.6-35b-a3b (local, via MLX)
**Mode:** work (auto_mode: true)
**Request:** "I'm starting a small home coffee setup. Compare espresso, pour-over, AeroPress, and moka pot for taste, cost, learning curve, and daily convenience."
**Cycles:** 2 (cycle_1: 3 invocations, cycle_2: 9 invocations)

---

## Overview

PROMPT_ID_10 tests the lead agent on a straightforward multi-attribute product comparison — no tool orchestration, no file operations, no code. It should be answerable from the model's training data alone. Both cycles ultimately produced a passable answer, but the path reveals severe inefficiencies: Cycle 1 made 3 LLM calls for a 1-call query (~1m52s). Cycle 2 made 9 LLM calls (~2m31s), spawned parallel subagents that collected results that were never used, and entered a degenerate clarification loop. The same quality answer was produced in both cycles — the extra cost bought nothing.

---

## Cycle 1 Flow Analysis

### Execution Summary

| Invocation | File | Timestamp | Purpose | Outcome |
|---|---|---|---|---|
| 001 | cycle_1_promptlog_001.txt | 17:52:29Z | Lead agent system prompt + user query | Model loaded 14 tools, full memory |
| 002 | cycle_1_promptlog_002.txt | 17:52:31Z | Planner middleware | Generated JSON plan for a simple comparison |
| 003 | cycle_1_promptlog_003.txt | 17:53:26Z | Title generation | Produced ~6 word title via separate LLM call |

### Issues

#### 1. Planner middleware misclassifies simple comparison as complex
- **Source:** `cycle_1_promptlog_002.txt:84`
- **Text:** "Generate a detailed structured plan for the previous user request. Work Mode detected this request is too complex for direct execution."
- **Problem:** Comparing 4 coffee methods on 4 dimensions is a canonical "answer directly" query. It requires no multi-step execution, no tool orchestration, no file operations.
- **Impact:** +1 LLM call, +84 lines of planner prompt overhead, JSON parsing complexity.
- **Root cause:** The work-mode classifier uses a broad heuristic. It lacks a "direct answer" domain for product comparisons.

#### 2. Trivial-signal escape hatch in planner prompt is pre-empted
- **Source:** `cycle_1_promptlog_002.txt:55-58`
- **Text:** "TRIVIAL SIGNAL — if the request is clearly trivial (single factual lookup, greeting, simple calculation, definition request), return: {\"trivial\": true}"
- **Problem:** The work-mode classifier already decided "too complex" before the planner prompt even ran. The escape hatch for triviality is never triggered because the classifier gates entry.
- **Impact:** The `trivial` signal is dead code for any query pre-classified as non-trivial by work mode.

#### 3. Title generation is a separate, unnecessary LLM call
- **Source:** `cycle_1_promptlog_003.txt:18-31`
- **Evidence:** A dedicated LLM call at 17:53:26Z, after the answer was fully generated. It re-passes the user query + partial assistant response just to produce "Home Coffee Setup Comparison" (6 words).
- **Cost per call:** ~200 input tokens + 1 LLM round trip + ~5-10s latency.
- **Better alternatives:** (1) Extract first 6 meaningful words of user query client-side. (2) Include title generation as a single token in lead agent's output format. (3) Use `response_preview` truncation.

#### 4. Memory context is severely bloated and irrelevant
- **Source:** `cycle_1_promptlog_001.txt:498-518`
- **Evidence:** ~270 lines of memory covering: Accenture CAG, URA RAG API, Singapore maritime law, Jira MDATA-799, Greece island-hopping, Netherlands coastal trip, Luke Legal Case Analysis, standing desks under $400, macOS downgrade, Dreamy Executor CSV pipeline, metaphysical crystals. **Nothing relevant to coffee.**
- **Impact:** ~2000+ tokens of useless context per call. Signal-to-noise degradation.
- **Root cause:** `get_memory_data()` dumps the entire global memory store. No semantic filtering or domain-based pruning.

#### 5. No evidence of web_search being used (or it timed out)
- **Timing:** Only ~2s between Turn 1 (17:52:29) and Turn 2 (17:52:31) — impossibly fast for a web search round trip.
- **Response source:** The final answer contains SGD pricing and brand names (Breville Barista Express, Hario V60, Bialetti), suggesting parametric knowledge from training data rather than web search.
- **Impact:** If web_search was invoked, it timed out silently. The prompt logs don't capture tool call results.

#### 6. Tool call traceability is absent
- **Source:** All cycle_1 logs.
- **Problem:** Prompt logs only capture prompts sent *to* the model. Tool invocations, results, and timeouts are invisible. We cannot determine what tools were called, which succeeded/failed, or why.
- **Recommendation:** Add tool-call capture to `prompt_tuning` logging: tool name, invocation args, result status, latency.

---

## Cycle 2 Flow Analysis

### Execution Summary

| Invocation | File | Timestamp | Purpose | Outcome |
|---|---|---|---|---|
| 001 | cycle_2_promptlog_001.txt | 22:02:18Z | Lead agent system + memory + user query | Model launched 4 parallel web_searches |
| 002 | cycle_2_promptlog_002.txt | 22:02:20Z | Planner middleware | Generated JSON plan |
| 003 | cycle_2_promptlog_003.txt | 22:02:37Z | Title generation | Success |
| 004 | cycle_2_promptlog_004.txt | 22:02:40Z | Subagent web search: pour-over | SUCCESS (5 results) |
| 005 | cycle_2_promptlog_005.txt | 22:02:45Z | Subagent web search: AeroPress | SUCCESS (5 results) |
| 006 | cycle_2_promptlog_006.txt | 22:02:45Z | Subagent web search: espresso | SUCCESS (5 results) |
| 007 | cycle_2_promptlog_007.txt | 22:03:22Z | Lead agent retry (saw timeouts) | All 4 lead-agent web_search failed. Model blanked. |
| 008 | cycle_2_promptlog_008.txt | 22:03:24Z | Lead agent + planner_handoff | Planner handoff appended |
| 009 | cycle_2_promptlog_009.txt | 22:04:36Z | Planner clarification | Asked user: "What is the content/topic?" |

### Two Parallel Tracks

- **Track A (Lead Agent direct):** 001 → 4 web_search calls (3 timeouts + 1 event loop error) → 007 (failures visible) → 008 (planner handoff) → 009 (degenerate clarification)
- **Track B (Planner/Subagent):** 002 → 003 → 004/005/006 (all three web searches succeed) → results logged but **never consumed** by lead agent

**Critical finding:** The subagent searches succeeded while the lead agent's direct `web_search` calls all failed. Both use the same backend. The successful subagent results were collected (004-006) but never reached the lead agent's execution context for synthesis.

### Issues

#### 1. web_search timeout cascade — 3 timeouts + 1 event loop error
- **Source:** `cycle_2_promptlog_007.txt:778-790`
- **Errors:**
  - 3× `[model_timeout] Tool web_search exceeded the 45s timeout and was cancelled. Try a different approach or skip this step.`
  - 1× `{"ok": false, "error": "<asyncio.locks.Semaphore object at 0x111e683e0 [locked]> is bound to a different event loop", "query": "moka pot cost beginner setup 2026"}`
- **Root cause:** The `web_search` tool uses an `asyncio.locks.Semaphore` for concurrency control (max 3). Track A (lead agent) and Track B (subagents) run on different event loops. The Semaphore was instantiated on one loop but used on another. The first 3 calls blocked/timeout, the 4th hit the event-loop mismatch.
- **Prompt impact:** The error message surfaces a raw Python object repr (`<asyncio.locks.Semaphore object at 0x111e683e0 [locked]>`) that the 3.6B model cannot interpret or recover from.

#### 2. Planner clarification context loss — degenerate behavior
- **Source:** `cycle_2_promptlog_009.txt:764-768`
- **Text:** "Before any execution, ask the user this clarification via `ask_clarification`. Question: What is the content or topic of the previous user request?"
- **Problem:** After 3 successful subagent web searches for "home espresso machine cost", "AeroPress accessories", and "pour over coffee setup" — all directly about the coffee topic — the planner asks the user what the topic is. This is a degenerate state.
- **Root cause:** The planner middleware doesn't read conversation history. It only sees the last planner_handoff payload. The handoff lost the original user request text. The planner prompt says "previous user request" without restating it (`cycle_2_promptlog_002.txt:83-84`).
- **Irony:** The user's original message and all 3 search results are right there in the conversation history, but the planner middleware doesn't have access to them.

#### 3. Subagent web search results never synthesized
- **Source:** 004, 005, 006 all succeeded with rich search data. None of it appears in the final answer.
- **Problem:** The `task()` function returned results to the subagent caller, but the lead agent never received them in its conversation context. The subagent results were logged but never injected into the lead agent's execution loop.
- **Impact:** 3 successful web searches (with ~500 results each) went entirely unused. The model fell back to parametric knowledge for its answer.

#### 4. Research assistant prompts are duplicated per query
- **Source:** `cycle_2_promptlog_004.txt:18-22`, `_005.txt:18-22`, `_006.txt:18-22`
- **Text (identical in all 3):** "You are a research assistant. The following text is the raw result of a web search query. Summarize it into a concise, factual paragraph (max 250 words)..."
- **Problem:** The same 7-line instruction is repeated as a separate LLM call for each search query. For 3 related searches (pour-over, AeroPress, espresso), the subagent could batch-synthesize into a unified comparison.
- **Impact:** 2 extra LLM calls that could be eliminated.

#### 5. Memory injected twice, identically
- **Source:** `cycle_2_promptlog_001.txt:498-519` and `_007.txt:498-519` — identical memory block.
- **Impact:** ~540 total lines of irrelevant context across two invocations for the same user query. The planner middleware calls (002, 008, 009) don't inject memory — which is actually better behavior.

#### 6. Tool definition bloat — 14 tools every turn
- **Source:** All cycle_2 logs, tool definitions in invocation_params.
- **Evidence:** Every lead agent invocation carries schemas for `ls`, `read_file`, `write_file`, `str_replace`, `bash`, `present_files`, `ask_clarification`, `recall`, `write_todos`, `web_search`, `save_to_knowledge_vault`, `task`, `view_image`.
- **Impact:** ~475 lines of tool schema injected every turn. For a coffee comparison query, file-editing and code-execution tools are dead weight.
- **Opportunity:** Prune tools by domain — for `research` domain, strip `write_file`, `str_replace`, `bash`, `view_image`, `save_to_knowledge_vault`.

#### 7. No timeout recovery in system prompt
- **Source:** `cycle_2_promptlog_007.txt`
- **Problem:** After 4 consecutive web_search failures, the model produced blank whitespace (message 3). No fallback strategy was attempted — no `task` delegation, no "let me work with what I know", no partial answer.
- **Root cause:** The system prompt has no `<tool_failure>` recovery block. The timeout error message says "Try a different approach or skip this step" but provides no structured guidance.
- **Compare with Track B:** Subagent web_search worked every time. The recovery instruction should be: "When web_search fails, delegate to a general-purpose subagent via `task()`."

---

## Cycle 1 vs Cycle 2 Comparison

| Dimension | Cycle 1 | Cycle 2 | Delta |
|---|---|---|---|
| Prompt logs | 3 | 9 | +200% |
| Duration | ~1m52s | ~2m31s | +35% |
| LLM calls | 3 | 9 | +200% |
| Memory injections | 1 | 2 | +100% |
| Web search failures | 0 (no evidence of use) | 4 (3 timeout + 1 event loop) | Regression |
| Subagent searches | 0 | 3 (all succeeded, none consumed) | Mixed |
| Planner clarifications | 0 | 1 (degenerate) | Regression |
| Answer quality | Comprehensive | Comprehensive | Same |

Cycle 2 spent 3× the invocations and 35% more time to produce the same quality answer as Cycle 1. The subagent infrastructure worked correctly (all 3 searches succeeded) but the results were never used. The lead agent's direct tool calls all failed due to an event-loop concurrency bug. The cascade of failures pushed the system into a degenerate clarification.

---

## Backend Prompt Architecture Findings

### prompt.py — System Prompt Assembly

The lead agent prompt is assembled in `_build_componentized_prompt` (line 580-604) from 12 sections:

| Section | Lines | Static? |
|---|---|---|
| `<role>` | 2 | Yes (agent_name) |
| `<soul>` | varies | Per-agent |
| `<memory>` | varies | Runtime-injected |
| `<thinking_style>` | 7 | +subagent_thinking |
| `<clarification_system>` | 28 | Static |
| `<skill_system>` | 30-50 | Per-skill config |
| `<subagent_system>` | 147 | n=max_concurrent |
| `<working_directory>` | 21 | Static |
| `<fetch_policy>` | 9 | Static |
| `<response_style>` | 5 | Static |
| `<citations>` | 11 | Static |
| `<critical_reminders>` | 12 | +subagent_reminder |

**Key redundancy:** The subagent concurrency limit (`n`) is embedded in ~20 places across 3 separate prompt locations:
1. `_build_subagent_section` (147 lines) — full tutorial
2. `subagent_reminder` (3 lines) — in `<critical_reminders>`
3. `subagent_thinking` (3 lines) — in `<thinking_style>`

**Consolidation opportunity:** The same batch-size rule is taught 6 different ways (3 examples, 2 usage examples, 1 counter-example). The subagent section reads like onboarding documentation, not a system instruction.

### todo_prompts.py — Tool Description Redundancy

- System prompt (34 lines) and tool description (60 lines) substantially overlap — both cover "when to use", "when NOT to use", best practices, and critical rules.
- The tool description is nearly 2× the size of the system prompt and restates the same information for the tool-calling schema.

### planner_middleware.py — Complexity Classification

- `_classify_complexity` (line 326-338) uses O(1) keyword heuristics — no LLM call.
- Planner prompt (65 lines) is well-structured with JSON schema, domain-specific dependency rules, and clarification guardrails.
- **Bug:** `_ensure_research_clarifications` (line 143-206) is deterministic post-processing (regex + keywords) that could be folded into the planner prompt itself. Why run an additional processing step when the LLM could emit correct clarifications directly?

### plan_evaluator_middleware.py — Domain Bug

- **Bug at line 144:** `{domain}` is populated from `state.get("complexity_tier")` which returns "trivial"/"moderate"/"complex" — not the plan's actual domain ("code"/"research"/"legal"/"trip"/"generic").
- The evaluator prompt says "Domain: {domain}" but receives a complexity tier instead. If it uses this value, it's making decisions on wrong data.

### evaluator_middleware.py — Too Thin

- The evaluation prompt is a single line: `"You are a strict evaluator. Respond with:\nVERDICT: PASS or FAIL\nCRITIQUE: <one concise paragraph>\n\nPlan title: {plan_title}\nPlan summary: {plan_summary}\n\nCandidate response:\n{candidate_response}\n"`
- **Problem:** It doesn't receive the plan's todos, acceptance criteria, or domain. For a "strict evaluator," this is surprisingly shallow context. It's judging a response against a plan title and summary alone.

### web_search_summary_middleware.py — Clean but Unused

- The summary prompt (11 lines) is clean and well-designed. "Start directly with the key information" is a good guardrail.
- The suffix tracking (`[Summarized by web_search_summary_middleware — original: X chars]`) is good for observability.
- **Problem:** This middleware's output (004-006) was successfully produced but never reached the lead agent's response generation context in Cycle 2.

### search_masking.py — Separate LLM Call

- The masking prompt (10 lines) is compact and well-structured. Rules are clear and actionable.
- **Cost:** Each privacy-masked search query consumes an additional LLM call for model invocation (line 76-84). If `simplify_queries` is also enabled, that's 2 LLM calls per search before the actual search happens.
- **Opportunity:** Combine masking and query simplification into a single prompt step.

### Subagent Configurations (general_purpose.py, bash_agent.py)

- **general_purpose.py (46 lines):** Clean, focused system prompt (20 lines). Proper tool restrictions (disallows `task` — prevents nesting, `ask_clarification` — no clarification). The `output_format` with citations requirement is good.
- **bash_agent.py (45 lines):** Similarly clean. Tool list is explicitly limited to `bash`, `ls`, `read_file`, `write_file`, `str_replace` — sandbox-only tools. Prevents dangerous escalation.
- **Both:** Use `model="inherit"` which means they use the same model as the parent. For a 3.6B model running locally, this is appropriate but could benefit from smaller/faster models for subagent work.

### Vault Prompts (vault_analyze.py, vault_generate.py)

- Both are short (26 lines each), domain-agnostic, and return strict JSON. Clean design.

---

## Priority Improvement Recommendations

### P0 — Critical (prevents correct execution or wastes >50% cost)

| # | Issue | File | Recommendation |
|---|---|---|---|
| P0.1 | Event-loop Semaphore mismatch causes all lead-agent web_searches to fail | Runtime bug in web_search tool | Replace `asyncio.locks.Semaphore` with `threading.Semaphore` or per-loop instantiation |
| P0.2 | Subagent web search results never reach lead agent's synthesis context | Execution engine / task tool | Ensure `task()` return values are injected into lead agent's conversation context as tool results |
| P0.3 | Planner clarification loses original request context | `planner_middleware.py` | Pass original user request text explicitly in planner_handoff: `<original_request>{{text}}</original_request>` |
| P0.4 | Memory bloat: ~270 lines of irrelevant context on every call | `prompt.py:379-429` | Implement **semantic memory gating**: compute cosine similarity between query and memory chunks; only inject chunks with similarity > threshold. Coffee query → zero memory needed. |

### P1 — High Impact (saves >30% tokens or LLM calls)

| # | Issue | File | Recommendation |
|---|---|---|---|
| P1.1 | Work-mode classifier misclassifies simple comparisons as complex | Planner middleware | Add "product comparison", "recommendation", "compare X and Y" to the trivial/moderate classifier keywords |
| P1.2 | No timeout recovery in system prompt | `prompt.py` | Add `<tool_failure>` block: "When web_search fails with timeout or event-loop error, delegate all remaining searches to subagents via task(). Never retry web_search directly after failure." |
| P1.3 | Title generation is separate LLM call | Post-processing | Fold title into lead agent output format (`title`, `response`). Eliminate dedicated call. |
| P1.4 | Subagent concurrency logic repeated in 3 locations | `prompt.py:18-155, 526-540` | Keep only the full `<subagent_system>` section. Remove `subagent_reminder` and `subagent_thinking` — the same rules are already in the main section. |
| P1.5 | Plan evaluator uses wrong domain value | `plan_evaluator_middleware.py:144` | Fix: pass plan's actual `domain` field instead of `complexity_tier` |

### P2 — Medium Impact (incremental improvements)

| # | Issue | File | Recommendation |
|---|---|---|---|
| P2.1 | Tool definitions are monolithic for all domains | `prompt.py` tools list | Implement tool pruning by domain: strip `write_file`, `str_replace`, `bash`, `view_image` for research/comparison queries. Saves ~200 lines per call. |
| P2.2 | Research assistant prompt duplicated per search query | `web_search_summary_middleware.py` | Batch: "Below are raw results of 3 web searches. Produce unified comparison." Saves 2 LLM calls per multi-search batch. |
| P2.3 | Evaluator lacks plan todos and acceptance criteria | `evaluator_middleware.py:19` | Pass `todos` and `acceptance_criteria` fields to evaluator so it can make informed PASS/FAIL decisions. |
| P2.4 | Subagent section is a 147-line tutorial | `prompt.py:8-155` | Compress to ~40 lines. Keep 1 example, not 3 examples + 2 usage examples + 1 counter-example. |
| P2.5 | DREAMY_MODE_SECTION hardcodes a workflow skill | `prompt.py:607-636` | Move to a real loadable skill instead of baked-in prompt text |

### P3 — Low Impact (nice-to-have)

| # | Issue | File | Recommendation |
|---|---|---|---|
| P3.1 | Flashy emoji in system prompt (`🚀`) | `prompt.py:19` | Remove emoji — wastes tokens, provides no signal for a text-only model |
| P3.2 | `PLAN_MODE_SECTION` duplicates planner behavior | `prompt.py:639-656` | Remove — planner middleware already enforces structured planning |
| P3.3 | `PLAN_BACKGROUND_FOLLOWUP_SECTION` extremely narrow | `prompt.py:659-668` | Remove — only activates for `plan_mode=True AND background_followup=True` |
| P3.4 | Search masking adds separate LLM call per query | `search_masking.py` | Combine with query simplification into a single prompt step (if both are enabled) |
| P3.5 | Subagent configs use `model="inherit"` — no model tiering | `general_purpose.py:43`, `bash_agent.py:43` | Allow configuring smaller/faster models for subagent work (e.g., a 1B model for web search summarization) |

---

## Summary

PROMPT_ID_10 reveals that the lead agent prompt architecture has a **fundamental one-size-fits-all problem**: it's designed for complex multi-step code/research workflows but applied uniformly to every query. For a simple coffee comparison:

- **~70% of the system prompt** is wasted on irrelevant memory, bloated tool definitions, duplicated subagent instructions, and unnecessary mode sections
- **The planner middleware** adds 1-3 extra LLM calls but zero value for simple queries
- **Title generation** is a pure waste — a separate LLM call for 6 words
- **A runtime concurrency bug** (event-loop Semaphore) caused all Cycle 2 lead-agent web_searches to fail, while subagent searches worked perfectly — revealing a systemic lack of error recovery in the prompt
- **Successful subagent results were collected but never consumed** — a data-flow architecture gap

The core recommendation: **implement query-type routing** that strips irrelevant prompt sections and bypasses unnecessary middleware for simple queries. Reserve the full prompt architecture (planner, subagents, evaluators, memory, all tools) for genuinely complex work.

**Estimated token wastage across 12 invocations in 2 cycles:** ~25,000–35,000 tokens.
