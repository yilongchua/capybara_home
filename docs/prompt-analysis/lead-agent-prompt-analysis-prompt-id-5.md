# Lead Agent Prompt Analysis — PROMPT_ID_5

## Data Summary

| Cycle | Thread ID | Duration | Logs | Status |
|---|---|---|---|---|
| 1 | `466de10a-4739-4769-8644-a4ed01b8fee6` | ~5 min (17:32-17:36) | 3 prompt logs | Completed — direct answer, no planner intervention |
| 2 | `23387076-b28b-4070-afe0-1069d88b8d76` | ~11 min (21:32-21:43) | 10 prompt logs | Completed — planner intervened, web_search timeouts, plan-gate loop |

**User request (same for both cycles):** "Help me plan a 30 day routine to get better sleep and reduce phone scrolling at night. Include practical steps, what to track, and how to adjust if I miss days."

**Difficulty:** medium  
**Model:** qwen3.6-local (ChatOpenAI wrapper over `mlx-community/qwen3.6-35b-a3b`)  
**Mode:** work, auto_mode: true

**Files read:**
- `prompt-tunning/PROMPT_ID_5/cycle_1_metadata.json`
- `prompt-tunning/PROMPT_ID_5/cycle_2_metadata.json`
- `prompt-tunning/PROMPT_ID_5/cycle_1_promptlog_001.txt` through `_003.txt`
- `prompt-tunning/PROMPT_ID_5/cycle_2_promptlog_001.txt` through `_010.txt`
- `backend/src/agents/lead_agent/prompt.py`
- `backend/src/agents/memory/prompt.py`
- `backend/src/agents/middlewares/planner_middleware.py`
- `backend/src/agents/middlewares/evaluator_middleware.py`

---

## Issue 1: Planner Over-Intervention on Personal/Health Queries

**Severity:** High  
**Location:** `backend/src/agents/middlewares/planner_middleware.py:284-338` (complexity classification + `_ensure_research_clarifications`)

### Evidence

Cycle 1 executed cleanly without planner intervention. The agent answered directly in ~5 minutes with a well-structured 30-day plan including tables, tracking metrics, and week-by-week phases.

Cycle 2 was routed through the planner. The planner classified it as needing clarification: *"What is the primary domain or subject of the request that needs planning?"* with options `['Software development / Code', 'Research and Analysis', 'Business and Strategy', 'Content and Creative']` — none of which fit a personal health routine. This forced an unnecessary round-trip that wasted time and context.

### Root Cause

The `_classify_complexity` function (line 326) uses keyword matching. The word "plan" in the user's request ("plan a 30 day routine") matches the `_COMPLEX_KEYWORDS` tuple (line 285), triggering `"complex"` classification. The planner LLM then outputs a plan with `domain: "generic"` and `requires_clarification: true`. The `_ensure_research_clarifications` function (line 143) doesn't filter for non-research/non-code queries — it only adds more clarifications for research domains.

The planner's domain enum is: `code|research|legal|trip|generic`. There is no `health`, `personal`, or `lifestyle` domain. The fallback `generic` domain has no special handling.

### Recommendations

1. **Add a `personal` domain to the planner domain enum.** This should be used for health, lifestyle, routine, habit, wellness, and similar requests.

2. **Add personal/lifestyle keywords to the trivial/moderate classifier.** Keywords like "sleep", "routine", "diet", "exercise", "habit", "fitness", "wellness", "health" should classify as `"moderate"` or lower. The planner should skip or auto-approve these.

3. **Improve the planner's clarification prompt.** The planner LLM prompt (`PLANNER_SYSTEM_PROMPT`) says "Only ask for clarification when a missing detail would fundamentally change the plan." For a sleep routine request, asking "what domain is this?" is a clear violation of its own rule. Add explicit guidance: "For personal/lifestyle/health requests, do not ask domain clarification — set domain to 'generic' and proceed."

4. **Add a direct-answer bypass for non-work tasks.** When the planner classifies complexity as "moderate" and the domain is not "code" or "research", skip the full planning step and let the agent answer directly. The planner was designed for work-mode complexity.

---

## Issue 2: Web Search Timeout Cascade

**Severity:** High  
**Location:** `web_search_summary_middleware.py`, tool invocation in cycle 2

### Evidence

- `cycle_2_promptlog_008.txt` (lines 775-779): Two `web_search` calls both hit the 45s timeout and were cancelled.
- `cycle_2_promptlog_009.txt` (lines 755-761): Same two `web_search` calls timeout again on retry.
- The agent never produced a final answer in these turns — it was stuck in a retry loop.

### Root Cause

The agent's `fetch_policy` (`prompt.py:337-345`) prioritizes `web_search` first: "external web research should be attempted first for fresh information." The system prompt gives no guidance on what to do when `web_search` fails. The `<critical_reminders>` section has no mention of timeout handling, retry limits, or fallback strategies.

When both web search calls time out, the agent's only instruction is to "Try a different approach or skip this step" (from the `[model_timeout]` tool feedback), but the prompt's fetch policy tells it to prefer web_search, creating contradictory signals.

### Recommendations

1. **Add explicit fallback guidance to the system prompt:** "If `web_search` times out or fails, proceed with your existing knowledge and state any assumptions you're making. Do not retry more than once."

2. **Make the fetch policy domain-adaptive.** For personal/lifestyle queries (`domain: personal`), web_search is less critical than for research/code tasks. Consider injecting a lighter fetch policy via middleware based on the planner's domain classification.

3. **Add a hard retry limit to the prompt.** The `<critical_reminders>` section should include: "If a tool call times out, try at most once more. If it fails again, proceed without it."

---

## Issue 3: Plan-Gate Clarification Loop

**Severity:** Critical  
**Location:** `backend/src/agents/middlewares/planner_middleware.py:78-93` (`_pending_clarification_answered`) and `684-696` (clarification injection)

### Evidence

`cycle_2_promptlog_010.txt` (lines 784-797) shows the agent caught in a clarification loop:

```
[7] role=ai: Here's a comprehensive 30-day plan...
[8] role=tool: [plan_gate] Clarification is required before plan execution. Call `ask_clarification` first.
[9] role=ai: The domain is clear from your request — this is a personal health & habit-building plan.
[10] role=tool: [plan_gate] Clarification is required before plan execution. Call `ask_clarification` first.
```

The agent tried to answer directly twice, but the plan-gate blocked it because clarification was never formally resolved.

### Root Cause

The `_pending_clarification_answered` function (line 78) checks for:
1. A tool message from `ask_clarification` in the conversation history
2. A subsequent human message with text content

The agent's response "The domain is clear..." was a plain text AI message, not an `ask_clarification` tool call followed by a human response. The plan-gate only accepts clarification as resolved when the tool call was made and the user responded. The agent cannot self-resolve clarification in plain text.

The planner's `<planner_clarification>` message (line 687) says: "Before any execution, ask the user this clarification via `ask_clarification`." But the agent ignored this instruction because its own `clarification_system` says "Default: attempt with a stated assumption. Ask only when genuinely blocked." — and the agent correctly identified the domain as already clear.

### Recommendations

1. **Strengthen the planner clarification instruction.** Change the `<planner_clarification>` message to: "You MUST call the `ask_clarification` tool with this exact question and options. Do NOT try to answer in plain text — the plan-gate will reject it."

2. **Add a plan-gate timeout or auto-resolve.** If clarification remains pending for N consecutive turns without progress, the plan-gate should either:
   - Auto-resolve by selecting the recommended option as default
   - Abandon the plan and let the agent answer directly
   - Surface a runtime event so the frontend can intervene

3. **Make `_pending_clarification_answered` more flexible.** In addition to the tool result + human response pattern, also accept an AI message that directly answers the clarification question. This allows the agent to self-resolve when it has sufficient context.

---

## Issue 4: Memory Injection Too Heavy for Simple Requests

**Severity:** Medium  
**Location:** `backend/src/agents/lead_agent/prompt.py:379-429` (`_get_memory_context`), `backend/src/agents/memory/prompt.py:200-312` (`format_memory_for_injection`)

### Evidence

Both cycles show a massive `<memory>` section (~500+ lines) injected into the system prompt. The memory includes:
- Work projects (Accenture URA RAG API, CAG, Singapore maritime law, Jira MDATA-799)
- Personal interests (Dutch politics, Middle East geopolitics, pickleball, astronomy)
- Trip planning (Greece island-hopping, Netherlands coastal trip)
- Technology stack details (FastAPI, Ollama, FAISS, PDM)
- Recent history spanning months of activity
- 10+ "Relevant Facts" about the user

For a simple "30-day sleep routine" query, virtually all of this memory is irrelevant. It wastes context window and may distract the model from the task.

### Root Cause

The memory system injects all available context indiscriminately. The `_get_memory_context` function loads global memory data without any relevance filtering relative to the current user query. `format_memory_for_injection` has a `max_tokens` parameter (line 201) defaulting to 2000, but no mechanism to query-specific relevance scoring.

### Recommendations

1. **Add query-memory relevance scoring.** Before injection, compute relevance between the user's query and each memory section. Only inject sections with relevance above a threshold.

2. **Make the memory token budget dynamic.** Personal/lifestyle requests should get a smaller allocation (e.g., 500 tokens) vs. complex work tasks (2000+). This can be driven by the planner's domain classification.

3. **Inject structured summaries instead of raw memory blobs.** The memory prompt already has section structure (`workContext`, `personalContext`, `topOfMind`, etc.). Consider only injecting `personalContext` for personal/lifestyle requests and skipping work-related sections entirely.

---

## Issue 5: Subagent Prompt Section Overwhelmingly Long

**Severity:** Medium  
**Location:** `backend/src/agents/lead_agent/prompt.py:8-155` (`_build_subagent_section`)

### Evidence

The `<subagent_system>` section is ~150 lines of text including:
- 3 fully worked examples (Tencent stock, cloud providers, auth refactoring)
- Multiple repetitions of the same core rules and concurrency limits
- A full workflow checklist with 6 steps
- Redundant explanation of batching with varying N values

For the sleep routine query, this entire section is irrelevant — no subagents were needed or used in either cycle. Yet it consumes significant context window on every turn.

### Root Cause

The subagent section is always injected when `subagent_enabled=True`, regardless of task complexity or domain. There's no conditional logic to skip, shorten, or defer it for simple tasks.

### Recommendations

1. **Make the subagent section conditional on domain/complexity.** If the task is classified as `personal`, `moderate`, or simpler, inject a 3-line summary instead: "You have subagent capabilities. Use `task()` for parallel subtasks (max 3 per turn). For simple tasks, answer directly."

2. **Consolidate the examples into a reference pattern.** The current section repeats the same examples in different formats (workflow checklist, python code blocks, inline rules). Remove the redundant `How It Works` section and keep only one concise reference.

3. **Use progressive disclosure.** Only inject the full subagent guidance when the agent actually attempts to call `task()`. This requires middleware-level interception rather than prompt injection.

---

## Issue 6: Contradictory Clarification Signals

**Severity:** Medium  
**Location:** `backend/src/agents/lead_agent/prompt.py:286-313` (`CLARIFICATION_SECTION`) vs. `planner_middleware.py:684-696`

### Evidence

The lead agent's `CLARIFICATION_SECTION` states:

> "Default: attempt with a stated assumption. Ask only when genuinely blocked."
> "Never ask about: Stylistic or preference choices you can decide yourself"
> "Things you can try and revise if wrong"

But the planner middleware's `<planner_clarification>` message overrides this by forcing a domain clarification question for a query where the domain is self-evident. The agent receives two contradictory signals:
1. System prompt: "Default: assume, don't ask"
2. Planner middleware: "Ask this clarification before proceeding"

The agent attempted to follow rule 1 (by answering directly) but was blocked by the plan-gate enforcing rule 2.

### Root Cause

The clarification authority is not well-defined. The system prompt's clarification rules were written for the base agent behavior, but the planner middleware injects orthogonal constraints that conflict with those rules. The agent has no way to reconcile the two.

### Recommendations

1. **Add a clarification authority hierarchy to the system prompt.** Explicitly state: "When `<planner_clarification>` is present in the conversation, you MUST follow its instructions. When absent, use the default clarification rules below."

2. **The planner should be more conservative about injecting clarifications.** Before injecting a `<planner_clarification>` message, the middleware should check if the question is genuinely unanswerable from context. A sleep routine request where the domain question has no good option among "Software development / Code" options is a false positive.

3. **Add the clarification authority rule to the `<critical_reminders>` section.**

---

## Issue 7: No Explicit Tool Timeout Handling Guidance

**Severity:** Low  
**Location:** System prompt — no timeout handling section exists

### Evidence

The `<critical_reminders>` section has 10+ reminders (traceability, mermaid syntax, multi-task, language consistency) but nothing about tool failure handling. When web_search timed out, the agent had no prompt-level guidance and fell into a retry loop.

### Recommendations

1. **Add a tool-failure handling line to `<critical_reminders>`:** "If a tool call fails or times out, retry at most once. If it fails again, proceed without it and state your assumption."

2. **Consider a dedicated `<tool_failure>` section** for more complex guidance (e.g., what to do when different tools fail, fallback chains).

---

## Priority Summary

| Priority | Issue | Effort | Impact |
|---|---|---|---|
| P0 | Plan-gate clarification loop (Issue 3) | Low | Prevents indefinite agent stalls |
| P0 | Planner over-intervention (Issue 1) | Medium | Stops unnecessary planning for personal queries |
| P1 | Web search timeout cascade (Issue 2) | Low | Prevents infinite retry loops on tool failure |
| P1 | Contradictory clarification signals (Issue 6) | Low | Resolves conflicting instructions to agent |
| P2 | Memory injection too heavy (Issue 4) | Medium | Frees context window for actual task |
| P2 | Subagent prompt too long (Issue 5) | Medium | Reduces context waste on simple tasks |
| P2 | No timeout handling in prompt (Issue 7) | Low | Prevents silent tool failure loops |

## Root Architectural Insight

The fundamental problem is a **misalignment between the planner middleware and the lead agent prompt about when planning and clarification are needed.** The planner was designed for work-mode complexity (code, research, legal analysis) but applies uniformly to all requests that match keywords like "plan". The lead agent's own prompt encourages direct action with stated assumptions, creating a tension that manifests in the plan-gate loop.

The highest-leverage fix is at the **complexity classification layer** (`planner_middleware.py:_classify_complexity`). Adding a `personal` domain with a bypass for health/lifestyle/habit requests would eliminate Issues 1, 3, and 6 in one change. The downstream fixes (timeout handling, memory size, subagent section) address secondary friction but won't prevent the core planner-injection mismatch.

## Cross-Reference

- Prompt source: `backend/src/agents/lead_agent/prompt.py` (701 lines, componentized mode active)
- Planner logic: `backend/src/agents/middlewares/planner_middleware.py` (775 lines)
- Memory formatting: `backend/src/agents/memory/prompt.py` (351 lines)
- Evaluator middleware: `backend/src/agents/middlewares/evaluator_middleware.py` (220 lines)
- Related prompt logs: `prompt-tunning/PROMPT_ID_5/cycle_1_promptlog_*.txt`, `cycle_2_promptlog_*.txt`
