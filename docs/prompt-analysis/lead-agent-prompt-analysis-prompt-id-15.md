# Lead Agent Prompt Analysis — PROMPT_ID_15

> **Date:** 2026-05-19
> **Scope:** `prompt-tunning/PROMPT_ID_15/` (Cycle 1: 20 turns, Cycle 2: 14 turns)
> **Task:** "Analyse the electric vehicle market right now. Cover major brands, battery trends, charging issues, government incentives, and whether buying used makes sense."
> **Model:** `mlx-community/qwen3.6-35b-a3b` (qwen3.6-local)
> **Subagent limit:** 3 concurrent `task` calls per response

---

## 1. Executive Summary

Both cycles exhibit the same failure cascade: **3 parallel `web_search` calls all timeout at 45s**, forcing the agent into a degraded fallback path. The prompt itself contributes to this through (a) no guidance on handling search failures gracefully, (b) an enormous irrelevant memory injection that wastes context, and (c) a planner middleware that generates a generic clarification question completely disconnected from the user's request. Cycle 2 additionally hit an `asyncio.Semaphore` event-loop binding bug (backend issue, not prompt).

The subagent system section (~140 lines) is heavily over-instructed with 3 near-identical examples and repeated warnings, yet the agent **never uses subagents** for this research task — it defaults to direct `web_search` calls every time.

---

## 2. File Catalog

| File | Purpose |
|---|---|
| `cycle_1_metadata.json` | Cycle 1 run metadata (20 turns, ~16 min) |
| `cycle_1_promptlog_001–020.txt` | Per-turn prompt logs for Cycle 1 |
| `cycle_2_metadata.json` | Cycle 2 run metadata (14 turns, ~8.5 min) |
| `cycle_2_promptlog_001–014.txt` | Per-turn prompt logs for Cycle 2 |

**Source files reviewed:**
- `backend/src/agents/lead_agent/prompt.py` (701 lines)
- `backend/src/agents/memory/prompt.py` (351 lines)
- `backend/src/agents/lead_agent/todo_prompts.py` (110 lines)
- `backend/src/agents/middlewares/planner_middleware.py` (775 lines)
- `backend/src/agents/middlewares/evaluator_middleware.py` (220 lines)
- `backend/src/agents/middlewares/plan_evaluator_middleware.py` (274 lines)
- `backend/src/agents/middlewares/web_search_summary_middleware.py` (251 lines)

---

## 3. Cycle-by-Cycle Execution Flow

### 3.1 Cycle 1 (20 turns, ~16 min)

| Turn | Actor | What Happened |
|---|---|---|
| 1 | System | Full system prompt injected (~767 lines including massive `<memory>` block) |
| 2 | Human | User request |
| 3 | AI | *(empty thinking)* → launches 3 parallel `web_search` calls |
| 4–6 | Tool | **ALL 3 `web_search` calls timeout at 45s** |
| 7 | AI | Retries with `recall` tool |
| 8 | Tool | `recall` returns **irrelevant facts**: sleep hygiene protocol, S&P 500 tracking, Tokyo trip planning — zero EV-related content |
| 9 | AI | "Let me retry the searches — I'll keep them shorter" → 2 more `web_search` |
| 10–11 | Tool | **Both timeout again** |
| 12–14 | AI/Tool | Agent proceeds with knowledge-base-only research, web_search_summary middleware condenses results |
| 15–19 | AI/Tool | Continues research with mixed success; some searches succeed via summary middleware |
| 20 | System | Planner middleware activates with a **generic clarification**: "What is the specific original request or project that needs a structured plan?" — completely irrelevant to the EV question |

### 3.2 Cycle 2 (14 turns, ~8.5 min)

| Turn | Actor | What Happened |
|---|---|---|
| 1 | System | Same system prompt (memory updated with newer personal info) |
| 2 | Human | Same user request |
| 3 | AI | *(empty thinking)* → 3 parallel `web_search` |
| 4–6 | Tool | **ALL 3 timeout at 45s** |
| 7–8 | Tool | **NEW ERROR**: `<asyncio.locks.Semaphore object... is bound to a different event loop>` — backend concurrency bug on searches 4 and 5 |
| 9 | Human | Planner activates: "Generate a detailed structured plan..." |
| 10 | AI | *(empty thinking)* |
| 11 | Tool | Todo DAG updated with 6 items: `1-market-brands`, `2-battery-trends`, `3-charging-issues`, `4-incentives`, `5-used-evs`, `6-synthesis` |
| 12–14 | AI/Tool | Title generation, final response synthesis |

### 3.3 Pattern Comparison

| Metric | Cycle 1 | Cycle 2 |
|---|---|---|
| Total turns | 20 | 14 |
| Runtime | ~16 min | ~8.5 min |
| web_search timeouts | 5+ | 3 + 2 event-loop errors |
| Subagent `task` calls used | 0 | 0 |
| Planner activated | Yes (irrelevant clarification) | Yes (todo DAG only) |
| recall tool used | Yes (irrelevant results) | No |
| Final outcome | Knowledge-base response | Knowledge-base response |

---

## 4. Prompt-Level Findings

### 4.1 P1 — Memory Bloat (Critical)

**Location:** `backend/src/agents/memory/prompt.py` → `format_memory_for_injection()` → injected into `prompt.py`

The `<memory>` block injected into every system prompt is **enormous** (~500+ tokens) and **completely irrelevant** to the EV market task:

```
- Work: Core contributor to agentic harness engineering...
- Personal: Follows Dutch socio-political analysis...
- Current Focus: Execution is currently pivoting back to core workstreams...
- History: Recent: In the past month, the user heavily utilized...
- Relevant Facts: Tasmania trip, macOS downgrade, CAG project...
```

For a research query about electric vehicles, **zero** of this memory is useful. It consumes valuable context window tokens and may distract the model with unrelated personal context.

**Impact:** High. Wastes context budget, potentially degrades response quality by injecting noise.

**Recommendation:**
- Implement semantic relevance filtering before memory injection — only inject facts related to the current query domain
- Add a `max_memory_tokens` cap specific to the query type (research queries should get minimal memory)
- Consider a `memory_relevance_score` threshold — if no facts score above 0.3 relevance to the query, inject an empty memory block

### 4.2 P2 — Subagent Section Bloat (High)

**Location:** `backend/src/agents/lead_agent/prompt.py` → `_build_subagent_section()` (~140 lines)

The subagent section contains:
- 3 near-identical usage examples (Tencent stock, 5 cloud providers, auth refactor)
- 5+ repetitions of the "max 3 task calls" rule
- Redundant "CRITICAL WORKFLOW" steps that repeat information from earlier bullets
- A `subagent_reminder` in `<critical_reminders>` that repeats the same limit again

**Impact:** Medium-High. Consumes ~2000+ tokens of context. The repetition suggests the model isn't following the instruction, but more repetition isn't the solution — the agent never uses subagents for research tasks despite this massive section.

**Recommendation:**
- Collapse 3 examples into 1 canonical example + 1 counter-example
- Remove the redundant `subagent_reminder` from `<critical_reminders>` (it duplicates the section)
- Add explicit guidance: "For multi-topic research queries like market analysis, use subagents to research each topic in parallel"
- Reduce from ~140 lines to ~50 lines

### 4.3 P3 — No Web Search Failure Guidance (High)

**Location:** `<fetch_policy>` section in `prompt.py`

The fetch policy says:
```
1. web_search — external web research should be attempted first for fresh information
```

But there is **zero guidance** on what to do when web_search fails or times out. The agent's observed behavior:
1. Retry the same failing calls (Turn 9 in Cycle 1: "Let me retry the searches")
2. Fall back to `recall` (which returns irrelevant data)
3. Eventually rely on knowledge base

**Impact:** High. Causes wasted turns and timeouts.

**Recommendation:**
- Add explicit fallback guidance to `<fetch_policy>`:
  ```
  If web_search times out or fails after 1 attempt, proceed to step 2 (vault) or step 3 (LightRAG).
  Do not retry the same web_search query more than once.
  If all external sources fail, deliver the best answer from your knowledge base and label it as such.
  ```
- Add to `<critical_reminders>`: "When web_search fails, move on immediately — do not retry the same query."

### 4.4 P4 — Planner Clarification Mismatch (Medium)

**Location:** `backend/src/agents/middlewares/planner_middleware.py` → `_ensure_research_clarifications()`

The planner generates a **generic template question** that ignores the actual user request:

```
Question: What is the specific original request or project that needs a structured plan?
Options: ['Software development project', 'Business strategy or marketing campaign',
          'Research study or data analysis', 'Creative or content production']
```

This is clearly a fallback/default when the planner's LLM fails to extract a meaningful clarification. The agent then tries to bypass this gate and gets blocked by `[plan_gate] Clarification is required before plan execution`.

**Impact:** Medium. Wastes turns, creates friction.

**Recommendation:**
- The planner should detect when the user request is already specific enough and skip clarification
- `_ensure_research_clarifications()` already does some keyword detection but the base planner LLM output takes precedence
- Add a "no clarification needed" path when the user request contains 5+ specific sub-topics (as the EV query does)

### 4.5 P5 — Response Style Contradiction (Low)

**Location:** `<response_style>` vs `<citations>` in `prompt.py`

```
<response_style>
- Natural Tone: Use paragraphs and prose, not bullet points by default
</response_style>

<citations>
- Format: Use Markdown link format [citation:TITLE](URL)
</citations>
```

The citation format encourages heavy markdown formatting while the response style says to avoid it. For a 35B parameter model, this contradiction may cause inconsistent formatting.

**Impact:** Low. Minor style inconsistency.

### 4.6 P6 — Duplicate Prompt Templates (Low)

**Location:** `prompt.py` — `LEGACY_SYSTEM_PROMPT_TEMPLATE` vs `_build_componentized_prompt()`

Both produce nearly identical output. The componentized version splits into separate template constants (`ROLE_SECTION_TEMPLATE`, `THINKING_STYLE_SECTION_TEMPLATE`, etc.) but the content is duplicated. This creates a maintenance burden — changes to one must be mirrored in the other.

**Impact:** Low (maintenance only, not runtime).

### 4.7 P7 — Empty AI Thinking Turns (Medium)

**Observation:** Multiple turns show the AI response as completely empty (just whitespace):

```
[3] role=ai




```

This appears in both cycles. Possible causes:
- The model's thinking/reasoning content is being stripped before logging
- The model is producing tool calls without visible reasoning text
- A streaming/logging issue in the prompt capture pipeline

**Impact:** Medium. Makes it impossible to audit the model's reasoning process from logs alone.

**Recommendation:**
- Verify that the prompt logging pipeline captures the full AI response including tool calls and thinking blocks
- If thinking is being stripped, include a `<thinking>` block in the logged output

### 4.8 P8 — `recall` Tool Returns Irrelevant Facts (Medium)

**Location:** Cycle 1, Turn 8

When web_search fails, the agent calls `recall` with query `"electric vehicle market EV brands battery charging incentives"`. The vector store returns:
- Sleep hygiene protocol facts
- S&P 500 macroeconomic tracking
- Tokyo trip planning

**Root cause:** This is likely a vector similarity issue in the memory store, not a prompt issue. However, the prompt could guide the agent on how to handle irrelevant recall results.

**Recommendation:**
- Add guidance: "If recall returns facts unrelated to your query, ignore them and proceed to the next information source."

### 4.9 P9 — Web Search Summary Middleware Works But Agent Doesn't Adapt

**Location:** `backend/src/agents/middlewares/web_search_summary_middleware.py`

The middleware successfully condenses large web_search results (observed in Cycle 1 logs where summarized results appear). However, the agent doesn't adapt its search strategy — it continues launching 3 broad parallel searches that all timeout.

**Impact:** Medium. The middleware is a good safety net but doesn't prevent the initial timeout cascade.

### 4.10 P10 — Backend Concurrency Bug (Not Prompt)

**Location:** Cycle 2, Turns 7–8

```
{"ok": false, "error": "<asyncio.locks.Semaphore object at 0x111e683e0 [locked]> is bound to a different event loop"}
```

This is a backend concurrency bug where asyncio locks are created in one event loop and used in another. **Not a prompt issue** but it compounds the web_search failure problem.

---

## 5. Related Prompt Surface Analysis

### 5.1 Planner Middleware (`planner_middleware.py`)

- `PLANNER_SYSTEM_PROMPT` is well-structured with clear JSON schema
- Domain detection works (`research`, `code`, `legal`, `trip`, `generic`)
- `_ensure_research_clarifications()` adds domain-specific clarifications but only when the base planner doesn't already produce them
- **Issue:** The planner classifies the EV query as `generic` domain instead of `research`, missing the research-specific clarification logic

### 5.2 Evaluator Middleware (`evaluator_middleware.py`)

- Simple PASS/FAIL verdict pattern
- Pre-verification checks for incomplete todos
- Not triggered in either cycle (no plan was executed to completion)

### 5.3 Plan Evaluator Middleware (`plan_evaluator_middleware.py`)

- Checks for circular dependencies, missing prerequisites, missing synthesis steps
- Lenient by design ("only flag genuine blockers")
- Not triggered in either cycle

### 5.4 Web Search Summary Middleware (`web_search_summary_middleware.py`)

- Well-implemented async path with `asyncio.wait_for`
- `_SUMMARY_PROMPT_TEMPLATE` is clean and focused
- Threshold-based (only summarizes when content exceeds `summary_threshold_chars`)
- Works correctly when web_search succeeds

### 5.5 Memory Prompt (`memory/prompt.py`)

- `MEMORY_UPDATE_PROMPT` is comprehensive with detailed section guidelines
- `format_memory_for_injection()` merges global + workspace memory, applies token limits
- **Issue:** No semantic relevance filtering — all memory sections are injected regardless of query relevance
- Token counting uses tiktoken (accurate) with fallback to character estimation

### 5.6 Todo Prompts (`todo_prompts.py`)

- Clear guidance on when to use vs not use todos
- Well-scoped to 3+ step tasks
- Not directly implicated in the EV analysis failures

---

## 6. Todo List for Prompt Improvements

### Critical (P0)

| # | Action | File | Rationale |
|---|---|---|---|
| T1 | Add semantic relevance filtering to memory injection | `memory/prompt.py` | Memory block wastes 500+ tokens with irrelevant personal info for research queries |
| T2 | Add web_search failure fallback guidance to `<fetch_policy>` | `lead_agent/prompt.py` | Agent retries failing searches instead of moving to vault/knowledge base |
| T3 | Collapse subagent section from ~140 to ~50 lines | `lead_agent/prompt.py` | 3 redundant examples + 5x repeated rules; agent never uses subagents for research |

### High (P1)

| # | Action | File | Rationale |
|---|---|---|---|
| T4 | Add explicit subagent guidance for research tasks | `lead_agent/prompt.py` | Agent should decompose multi-topic research into parallel subagents instead of direct web_search |
| T5 | Fix planner domain classification for research queries | `planner_middleware.py` | EV query classified as `generic` instead of `research`, missing domain-specific logic |
| T6 | Add "no clarification needed" path when request is already specific | `planner_middleware.py` | Generic clarification question wastes turns on well-specified requests |
| T7 | Add guidance for handling irrelevant `recall` results | `lead_agent/prompt.py` | Agent receives unrelated memory facts when recall fails to find relevant content |

### Medium (P2)

| # | Action | File | Rationale |
|---|---|---|---|
| T8 | Resolve response_style vs citations contradiction | `lead_agent/prompt.py` | "Natural prose" conflicts with markdown citation format |
| T9 | Fix empty AI thinking in prompt logs | Prompt logging pipeline | Cannot audit model reasoning from logs |
| T10 | Consolidate LEGACY and componentized prompt templates | `lead_agent/prompt.py` | Duplicate content creates maintenance burden |

### Low (P3)

| # | Action | File | Rationale |
|---|---|---|---|
| T11 | Add max_memory_tokens cap per query type | `memory/prompt.py` | Research queries should get less memory than conversational tasks |
| T12 | Add "do not retry same web_search query more than once" rule | `lead_agent/prompt.py` | Prevents wasted timeout cycles |

---

## 7. Non-Prompt Issues (Backend Bugs)

| # | Issue | File | Description |
|---|---|---|---|
| B1 | asyncio.Semaphore event loop binding | web_search backend | Locks created in one event loop, used in another — causes search failures |
| B2 | web_search 45s timeout too aggressive | Infrastructure | 3 parallel searches all consistently timeout; may need retry logic or timeout tuning |
| B3 | Planner generic clarification fallback | `planner_middleware.py` | When planner LLM produces no clarifications, a hardcoded generic question is used |

---

## 8. Metrics Summary

| Metric | Value |
|---|---|
| System prompt size (with memory) | ~767 lines / ~4500 tokens |
| Subagent section size | ~140 lines / ~2000 tokens |
| Memory block size | ~20 lines / ~500 tokens |
| Web search timeout rate | 100% (all 3 parallel calls timeout in both cycles) |
| Subagent utilization | 0% (never used in either cycle) |
| Planner relevance | Low (generic clarification on specific request) |
| Cycle 1 turns to useful output | ~12 |
| Cycle 2 turns to useful output | ~8 |

---

## 9. Conclusion

The Lead Agent prompt for PROMPT_ID_15 suffers from three core problems:

1. **Context budget waste** — The memory injection and subagent section consume ~2500 tokens of largely irrelevant content, leaving less room for the actual task.

2. **No failure recovery guidance** — When web_search times out (which it does consistently), the agent has no instructions on how to adapt, leading to wasted retry cycles.

3. **Planner-lead agent misalignment** — The planner generates generic clarifications that don't match the user's specific request, creating friction and wasted turns.

The most impactful changes would be: (T1) semantic memory filtering, (T2) web_search fallback guidance, and (T3) subagent section consolidation. These three changes alone would reduce context waste by ~30% and give the agent clear recovery paths when tools fail.
