# Lead Agent Prompt Analysis — PROMPT_ID_7

> **Test prompt:** "Can you compare intermittent fasting, calorie counting, and just eating more whole foods for weight loss? I want the pros, cons, risks, and who each approach fits."
> **Difficulty:** medium | **Mode:** work | **Auto:** true | **Model:** qwen3.6-local | **Cycles:** 2

## Executive Summary

PROMPT_ID_7 tested the lead agent against a medium-complexity research comparison request in `auto_mode: true` / `mode: work`. Across 2 cycles (10 prompt logs), the agent exhibited 5 systemic issues:

1. **Planner receives the wrong input message** → generates irrelevant clarifications
2. **Plan gate blocks correct agent execution** → deadlock in auto-mode
3. **Memory context bloat** → ~2000 tokens of irrelevant data injected every turn
4. **System prompt redundancy** → 300+ lines with duplicated instructions
5. **Verbose tool descriptions** → 110 lines for a simple CRUD todo tool

The agent's final response (visible in metadata `response_preview`) was well-structured and high quality — the issues are entirely in **process overhead**, not output quality.

---

## 1. Planner Receives Wrong Input Message

**Severity: Critical** | **Files:** `planner_middleware.py:542`, `cycle_1_promptlog_004.txt:753-769`

### Observation

The planner middleware picks the **latest** human message:

```python
# planner_middleware.py:542
latest_user = next((msg for msg in reversed(messages) if getattr(msg, "type", None) == "human"), None)
```

By the time the planner fires, the message sequence is:
1. `[human]` — Real user request: *"Can you compare intermittent fasting..."*
2. `[human]` — Work-mode injection: *"Generate a detailed structured plan for the previous user request. Work Mode detected this request is too complex for direct execution."*

The planner sees **only message #2**, which says *"previous user request"* — opaque text with no topic context.

### Evidence from Logs

In `cycle_1_promptlog_004.txt:754-769`:
```
<planner_handoff>
Title: Plan for missing request
Domain: generic
Summary: Request clarification regarding the missing context of the 'previous user request' to proceed with planning.
```

The planner then injected a useless clarification:
```
<planner_clarification>
Question: What is the topic or content you want planned?
Options: ['Software development task', 'Travel or trip planning', 'Research or analysis project', 'Other custom request']
```

### Impact

- **Domain detection fails** — defaults to `"generic"` instead of `"research"`, so `_ensure_research_clarifications()` never fires (`planner_middleware.py:146`)
- **Clarification is wrong** — the request is clearly defined; asking for a topic wastes a turn
- **Cascading failure** — wrong domain → wrong clarifications → plan stays draft → no execution

### Recommended Fix

Pass the **original user message** (index 0) alongside the latest human message to `_invoke_planner()`, or concatenate: `"Original request: {original}\n\nWork-mode instruction: {latest}"`.

---

## 2. Plan Gate Blocks Correct Agent Execution

**Severity: Critical** | **Files:** Plan gate middleware, `cycle_2_promptlog_005.txt:770-776`

### Observation

In cycle 2, the agent correctly decomposed into 3 parallel sub-tasks (one per diet strategy) and launched 3 `task()` calls. All were blocked:

```
[plan_gate] Plan is still draft. Execution tools are blocked until explicit plan approval via the execute-plan action.
```

The plan is initialized as `"draft"` at `planner_middleware.py:601`:
```python
plan_status = "draft"
```

And `_ALLOWED_WHEN_DRAFT` excludes `"task"`, so even valid decomposition is blocked.

### Root Cause

Both metadata files show `"auto_mode": true` — there is no user in the loop to approve plans. The combination of:
- `auto_mode: true` (no user to approve)
- Plan status `"draft"` (requires explicit approval)
- `task()` excluded from `_ALLOWED_WHEN_DRAFT`

creates a **deadlock**: the agent does the right work, but nothing can execute.

### Impact

- Cycle 1: Agent never attempts execution (stuck on clarification flow)
- Cycle 2: Agent correctly dispatches 3 subagents → all blocked → run ends
- ~2 minutes of overhead with zero useful output
- Both cycles eventually produced a good response through a different flow path (likely work-mode direct execution on re-run)

### Recommended Fix

When `auto_mode: true`:
- Auto-approve plans with no pending clarifications (transition `draft` → `approved` at creation time), OR
- Add `"task"` to `_ALLOWED_WHEN_DRAFT`, OR
- Skip plan gate entirely in auto-mode

---

## 3. Memory Context Bloat

**Severity: High** | **Files:** `lead_agent/prompt.py:379-429`, `memory/prompt.py:200-312`

### Observation

The `<memory>` section injects ~270 lines (~2000 tokens) of context on every turn. Content breakdown for the diet comparison request:

| Section | Injected Lines | Relevance to Diet Comparison |
|---|---|---|
| Work: Accenture CAG, URA RAG API, Jira MDATA-799 | ~60 | 0% |
| Personal: Dutch politics, crystals, MacBook | ~25 | 0% |
| Current Focus: Greece itinerary, Iran war, legal case | ~80 | 0% |
| History: Netherlands trip, CSV processing, sleep detox | ~60 | 0% |
| Facts: Tasmania, macOS downgrade, EV research | ~45 | 0% |

### Root Cause

**`_get_memory_context()`** (`lead_agent/prompt.py:411-418`) does NOT pass the user's current turn text:

```python
# We only have prompt-time access to thread-level metadata here; the
# current user turn text can be threaded in later by middleware if needed.
memory_content = format_memory_for_injection(
    memory_data,
    max_tokens=config.max_injection_tokens,
    # current_turn_text NOT passed — default ""
)
```

This means:
- **Vector store is never queried** — it's guarded by `if current_turn_text.strip():` at `memory/prompt.py:270`
- **User Context and History** are always injected verbatim regardless of query relevance (`memory/prompt.py:224-257`)
- **Fallback facts** dump all top-10 by confidence, not by relevance

### Impact

- ~2000 tokens wasted per turn for the diet comparison
- Noise dilutes signal — the model has to process irrelevant personal/work context
- Over cycles, memory accumulation amplifies the bloat (cycle 2 is more verbose than cycle 1)

### Recommended Fix

1. Pass `current_turn_text` to `format_memory_for_injection()`
2. Gate ALL memory sections behind a relevance signal (vector store query or embedding comparison)
3. If vector store returns nothing relevant, inject no memory rather than dumping top-N facts
4. Add memory decay/staleness pruning to prevent accumulation

---

## 4. System Prompt Redundancy

**Severity: Medium** | **Files:** `lead_agent/prompt.py`

### Section Inventory

| Section | Lines | Issues |
|---|---|---|
| role | 2 | Fine |
| soul | ~10-50 | Depends on SOUL.md |
| memory | variable | Conditionally injected |
| thinking_style | 10 | Includes `subagent_thinking` which repeats batching logic from `subagent_section` |
| clarification_system | 30 | Comprehensive, but line 1 duplicates `critical_reminders` line 1 |
| skills_section | ~20-50 | Depends on skill count |
| subagent_section | **~150** | 6 complete worked examples (Tencent, 5 cloud providers, auth refactor + 3 inline) |
| working_directory | 24 | Reasonable |
| fetch_policy | 8 | Reasonable |
| response_style | 3 | Duplicates `thinking_style` and `critical_reminders` |
| citations | 10 | Fine |
| critical_reminders | 14 | Line 1 is a duplicate of `clarification_system` |
| **Total** | **~300+** | |

### Specific Redundancies

1. **Triple duplication of concurrency limit**: The "max N task calls per response" rule appears in:
   - `subagent_section` (~10 lines of examples)
   - `subagent_reminder` in `critical_reminders` (1 line)
   - `subagent_thinking` in `thinking_style` (1 line)

2. **6 worked examples in subagent_section** (~80 lines) for a concept that boils down to "decompose → batch N → synthesize". The Tencent example (3 sub-tasks), 5-cloud-provider example (batched), and auth-refactor example (3 sub-tasks) all demonstrate the same pattern with different labels.

3. **`response_style`** (3 lines: "clear/concise, natural tone, action-oriented") adds no unique content — already implied by `thinking_style` and `critical_reminders`.

4. **`critical_reminders` line 1** replicates `clarification_system`: "Use `ask_clarification` only for genuinely missing critical info or irreversible operations."

### Recommended Fix

- **Cut subagent examples to 2**: single-batch (≤N) + multi-batch (>N)
- **Remove `response_style`** or inline into `thinking_style`
- **Deduplicate clarification rules**: keep in `clarification_system`, remove from `critical_reminders`
- **One canonical concurrency-limit statement** in `subagent_section`, reference it from elsewhere

---

## 5. Verbose Tool Descriptions (todo_prompts.py)

**Severity: Low-Medium** | **File:** `todo_prompts.py` (110 lines)

### Observation

Two prompts (system prompt + tool description) consume ~800 tokens for a CRUD tool with 3 states:

| File | Lines | Content |
|---|---|---|
| `TODO_LIST_SYSTEM_PROMPT` | 45 | "When to use" / "When NOT to use" / "Best Practices" — 3-step threshold repeated 4x |
| `TODO_LIST_TOOL_DESCRIPTION` | 65 | Same structure, same rules, wordier — "CRITICAL" section has 6 sub-bullets |

### Specific Issues

- "Only use for 3+ steps" stated in 4 places across both prompts
- `TODO_LIST_SYSTEM_PROMPT:44` — "Writing todos takes time and tokens" is meta-advice with no behavioral effect
- `TODO_LIST_TOOL_DESCRIPTION:85-92` — "CRITICAL: Only mark a task as completed when you have FULLY accomplished it" with 6 sub-bullets describing what "not completed" means
- Line 104-105 repeats the "mark first task in_progress immediately" guidance from line 72-75

### Recommended Fix

Compress to ~25 lines:

```
- Use write_todos for 3+ step tasks. Skip for simple requests.
- States: pending → in_progress → completed (or blocked with reason)
- Mark completed immediately after finishing each step
- Keep exactly one in_progress at a time (unless parallel)
- Remove irrelevant tasks; add discovered ones
```

---

## 6. Process Overhead vs. Value

### Cycle Timeline (estimated)

```
1. Work-mode start — classify complexity (~100ms)
2. SSE: planning_started (~50ms)
3. Daemon sleep 2.0s (work_mode_middleware)
4. Plan-mode re-invoke (creates new client, serializes checkpoint)
5. Planner LLM call (~3-5s)
6. Plan written to filesystem + SSE
7. Agent turn: reads planner_handoff, produces task() calls (~5-10s)
8. Plan gate blocks task() — run ends
```

Total overhead: **~2 minutes** for a request that decomposes neatly into 3 parallel sub-searches.

### Simplified Flow

For domain=`research` with ≤5 todos and no dependency edges, the system should:
1. Classify complexity (fast)
2. Auto-approve plan (no gate)
3. Let agent execute subagents immediately

This would reduce overhead from ~2 min to ~5-10s.

---

## 7. What Works Well

Not all findings are negative. Several patterns are correct:

- **Title generation** (`cycle_1_promptlog_003.txt`, `cycle_2_promptlog_006.txt`): Lightweight, non-blocking, async background with immediate fallback — good pattern
- **Agent decomposition**: In cycle 2, the agent correctly identified 3 parallel sub-tasks (one per diet strategy) and batched them within the concurrency limit — the orchestration logic works
- **Final response quality**: The `response_preview` in both metadata files shows a well-structured, comprehensive comparison covering all requested dimensions
- **Web search summary middleware**: Condenses verbose search results inline — good context management
- **Search masking**: Protects privacy by anonymizing queries — good security practice

---

## Priority Action Items

| # | Issue | Impact | Suggested Fix | File(s) |
|---|---|---|---|---|
| P0 | Planner gets wrong message | Irrelevant clarifications, wrong domain | Pass original user prompt to planner LLM | `planner_middleware.py:542` |
| P0 | Plan gate blocks in auto-mode | Deadlock — no execution path | Auto-approve when `auto_mode=true`, no pending clarifications | Plan gate middleware |
| P1 | Memory bloat (~2000 tokens) | Wastes context window, dilutes signal | Pass `current_turn_text`, use vector store for relevance gating | `lead_agent/prompt.py:411-418`, `memory/prompt.py:200-312` |
| P2 | Subagent examples (6 → 2) | 80 lines of redundant instruction | Cut to 2 examples, one concurrency-limit statement | `lead_agent/prompt.py` |
| P2 | `todo_prompts.py` 110 lines | ~800 tokens for a CRUD tool | Compress to ~25 lines | `todo_prompts.py` |
| P3 | `response_style` duplicative | 3 lines of dead weight | Remove or inline | `lead_agent/prompt.py:347-351` |
| P3 | `critical_reminders` duplicates `clarification_system` | Confusing if rules drift | Remove duplicate from reminders | `lead_agent/prompt.py:365-376` |

---

## Files Referenced

- `prompt-tunning/PROMPT_ID_7/cycle_1_metadata.json`
- `prompt-tunning/PROMPT_ID_7/cycle_1_promptlog_001.txt` through `_004.txt`
- `prompt-tunning/PROMPT_ID_7/cycle_2_metadata.json`
- `prompt-tunning/PROMPT_ID_7/cycle_2_promptlog_001.txt` through `_006.txt`
- `backend/src/agents/lead_agent/prompt.py`
- `backend/src/agents/lead_agent/todo_prompts.py`
- `backend/src/agents/memory/prompt.py`
- `backend/src/agents/middlewares/planner_middleware.py`
- `backend/src/agents/middlewares/plan_evaluator_middleware.py`
- `backend/src/agents/middlewares/evaluator_middleware.py`
- `backend/src/agents/middlewares/web_search_summary_middleware.py`
- `backend/src/security/search_masking.py`
- `backend/src/subagents/builtins/general_purpose.py`
- `backend/src/subagents/builtins/bash_agent.py`
- `backend/src/control_plane/prompts/vault_analyze.py`
- `backend/src/control_plane/prompts/vault_generate.py`
