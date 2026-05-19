# Lead Agent Prompt Analysis — PROMPT_ID_4

**Generated:** 2026-05-18
**Prompt ID:** 4
**Model:** `mlx-community/qwen3.6-35b-a3b` (qwen3.6-local)
**Difficulty:** easy-medium

---

## 1. Test Overview

| Cycle | Thread ID | Initial Prompt | Duration | Logs |
|---|---|---|---|---|
| 1 | `b271799b-ff49-...` | "I want to buy a standing desk for a small apartment. Compare a few good options, explain what specs matter, and tell me what you would choose under $400." | ~3 min 31s | 12 files |
| 2 | `3ba1371a-534e-...` | Same prompt | ~7 min 55s | 15 files |

**Total interactions analyzed:** 27 prompt logs across both cycles.

---

## 2. Critical Findings

### 2.1 Tool Availability Mismatch — `fetch_policy` References Non-Existent Tools

**Severity:** Critical
**Evidence:** `cycle_1_promptlog_001.txt:493-764`, `cycle_2_promptlog_001.txt`

The `<fetch_policy>` section in `backend/src/agents/lead_agent/prompt.py:230-238` instructs the agent to use tools in this priority order:

```
1. `web_search` — exists ✓
2. `query_knowledge_vault` — NOT in tool schema ✗
3. `query_lightrag` — NOT in tool schema ✗
4. `search_internal_documents` — NOT in tool schema ✗
```

**Observed failure:** In `cycle_2_promptlog_009.txt:8-10`, after web_search fails, the agent attempts:
```
[9] role=tool: Error: query_knowledge_vault is not a valid tool, try one of [ls, read_file, write_file, str_replace, bash, present_files, ask_clarification, recall, write_todos, web_search, save_to_knowledge_vault, task, view_image].
[10] role=tool: Error: query_lightrag is not a valid tool, try one of [ls, read_file, write_file, str_replace, bash, present_files, ask_clarification, recall, write_todos, web_search, save_to_knowledge_vault, task, view_image].
```

**Impact:** The agent wastes 2+ turns per failure chain trying non-existent tools instead of falling back to built-in knowledge. This compounds after web_search already failed, creating cascading stalls.

**Fix:** Align `<fetch_policy>` with actual available tools (see `prompt.py:13-487` for the real tool list), or make these references conditional on backend configuration.

---

### 2.2 No Fallback Strategy When Web Search Fails

**Severity:** Critical
**Evidence:** `cycle_1_promptlog_006.txt:4-5`, `cycle_2_promptlog_004.txt:4-5`, `cycle_2_promptlog_007.txt:6-7`

Across both cycles, web_search failed in **14 out of 27 attempts**:
- `asyncio.locks.Semaphore` event loop errors: 10 instances
- 45-second timeouts: 4 instances

After failure, the agent's behavior was consistently poor:
- Produced **empty AI responses** (`role=ai` with no content) in 8+ instances
- Repeatedly retried the same failing web_search tool instead of switching strategy
- Only in `cycle_2_promptlog_015.txt:10` did it eventually fall back to `write_todos`

In `cycle_2_promptlog_007.txt`, the agent correctly identified "Web search is temporarily glitching — let me retry with simpler queries" but the retry also timed out. No further fallback was attempted.

**Fix:** Add an explicit error handling section:
```xml
<error_handling>
When web_search fails (timeout or error):
1. Immediately fall back to your built-in knowledge — state "Based on my knowledge..."
2. Do NOT retry web_search more than once
3. If the task requires current data you don't have, say so and proceed with best available info
</error_handling>
```

---

### 2.3 Agent Produces Empty Responses After Tool Errors

**Severity:** High
**Evidence:** 10+ instances across both cycles where `role=ai` was empty following tool errors

**Example from `cycle_1_promptlog_006.txt:3-5`:**
```
[2] role=human: Standing desk request
[3] role=ai: (empty — model produced no response)
[4] role=tool: [model_timeout] Tool web_search exceeded the 45s timeout
[5] role=tool: [model_timeout] Tool web_search exceeded the 45s timeout
```

**Root cause:** The prompt lacks explicit instruction about what to do when tool calls fail. The model interprets the error as a signal to stop rather than recover.

**Fix:** Add recovery guidance:
```xml
<recovery>
When any tool call returns an error or timeout:
- Acknowledge the failure briefly in your response
- Switch to an alternative approach (built-in knowledge, different tool, or direct answer)
- NEVER produce an empty response — always say something to the user
</recovery>
```

---

### 2.4 Subagent Delegation Works Well When Reached

**Positive finding:** In `cycle_1_promptlog_011.txt` and `cycle_1_promptlog_012.txt`, subagents successfully executed web_search calls that the lead agent itself could not. Three parallel searches completed with full results covering dimensions, frame types, and motor comparisons.

**Key observation:** The subagent prompt (`cycle_1_promptlog_008.txt:368-394`) is leaner (~27 lines) and more focused than the lead agent prompt (~700+ lines). Subagents don't carry the full system overhead, which likely explains their higher success rate.

**Recommendation:** Consider making subagent delegation the default path for research tasks rather than a fallback. The lead agent should delegate web_search to subagents proactively, not just after failures.

---

### 2.5 Prompt Length and Cognitive Overload

**Severity:** Medium
**Evidence:** `cycle_1_promptlog_001.txt:493-764` — system prompt is ~270 lines

**Breakdown of lead agent system prompt:**
| Section | Approx. Lines |
|---|---|
| Tool schemas (ls, read_file, write_file, str_replace, bash, present_files, ask_clarification, recall, write_todos, web_search, save_to_knowledge_vault, task, view_image) | ~475 |
| Role + memory context | ~15 |
| Thinking style | 6 |
| Clarification system | 20 |
| Subagent system (with examples) | ~135 |
| Working directory | 20 |
| Fetch policy | 8 |
| Response style | 4 |
| Citations | 10 |
| Critical reminders | 15 |

**Impact:** The model appears confused about available tools, likely because the fetch_policy section references tools not in the tool schema. The massive subagent section (135 lines with 3 full examples) may be consuming context budget that could be used for task-relevant instructions.

**Fix:**
1. Remove or make conditional the `<fetch_policy>` section — only include when those tools actually exist
2. Trim subagent examples from 3 verbose to 1 concise example + bullet list
3. Move rarely-used sections (citations format, mermaid/image instructions) to lower-priority position or skill-based loading

---

### 2.6 Memory Section Has No Measurable Impact on Error Recovery

**Severity:** Low
**Evidence:** `cycle_1_promptlog_006.txt` (with memory) vs `cycle_1_promptlog_007.txt` (without memory) show identical failure patterns

Both cycles produced the same web_search timeouts and empty responses. Removing the memory section did not improve or worsen outcomes on this task.

**Insight:** Memory context is not the bottleneck — tool availability and fallback behavior are. However, memory does add ~15 lines of context that could be better used for error recovery instructions.

**Recommendation:** Consider making memory injection conditional on task complexity rather than always-on for every request.

---

### 2.7 Planner Handoff Gets Stuck on Clarification for Simple Tasks

**Severity:** Medium
**Evidence:** `cycle_1_promptlog_010.txt:4-5`

The planner system was invoked for a straightforward standing desk comparison but got stuck asking "What is the actual target task or project you need planned?" — a question that should have been answered by the original user request.

**Root cause:** The planner prompt (`cycle_1_promptlog_002.txt`) has overly aggressive clarification rules. For a "generic" domain task with clear intent, it should proceed rather than ask for clarification.

**Fix:** Tighten the planner's `requires_clarification` logic:
```
Only require clarification when:
- The domain cannot be determined (code vs research vs legal)
- A critical constraint is missing (budget, timeline, format)
- The request is genuinely ambiguous about what to produce

For research/comparison tasks with clear intent, proceed directly.
```

---

## 3. Error Frequency Summary

| Error Type | Cycle 1 | Cycle 2 | Total |
|---|---|---|---|
| `web_search` timeout (45s) | 2 | 3 | 5 |
| `asyncio.Semaphore` event loop error | 0 | 10 | 10 |
| `query_knowledge_vault` not a valid tool | 0 | 2 | 2 |
| `query_lightrag` not a valid tool | 0 | 2 | 2 |
| Empty `role=ai` response after error | 2 | 6+ | 8+ |
| Successful tool execution | 5 | 1 | 6 |

**Success rate:** 6 out of 27 attempts (~22%) completed a tool call successfully on the first try.

---

## 4. Recommended Prompt Changes (Prioritized)

| # | Section | Change | Priority |
|---|---|---|---|
| 1 | `<fetch_policy>` | Remove `query_knowledge_vault`, `query_lightrag`, `search_internal_documents` references OR make conditional on backend config | **Critical** |
| 2 | New section `<error_handling>` | Add explicit fallback: fall back to built-in knowledge after 1 failed web_search, never retry more than once | **Critical** |
| 3 | New section `<recovery>` | Never produce empty responses after tool errors; always acknowledge and switch strategy | **High** |
| 4 | `<critical_reminders>` | Add "After tool failure, immediately use built-in knowledge as fallback" | **High** |
| 5 | `<subagent_system>` | Trim examples from 3 verbose to 1 concise; move detail to skill-based loading | **Medium** |
| 6 | Planner prompt (separate) | Tighten `requires_clarification` for generic research tasks with clear intent | **Medium** |
| 7 | Memory injection | Consider conditional injection based on task complexity to reduce prompt bloat | **Low** |

---

## 5. Architecture-Level Observations (Beyond Prompt)

These are not prompt changes but affect how prompts perform:

- **Semaphore event loop error** (`asyncio.locks.Semaphore ... bound to a different event loop`) is a backend infrastructure bug, not a prompt issue. The agent cannot work around this — it needs a code fix in the `web_search` tool implementation.
- **45s timeout** may be too aggressive for web_search on a local model. Consider increasing to 60-90s or making it configurable per task type.
- **Subagents succeed where lead agent fails** on web_search — this suggests the subagent execution path has different infrastructure handling. Investigate why subagents don't hit the semaphore error.

---

## 6. Files Analyzed

### Cycle 1 (thread `b271799b`)
- `cycle_1_metadata.json` — session metadata, initial prompt, response preview
- `cycle_1_promptlog_001.txt` — full system prompt + tools schema (767 lines)
- `cycle_1_promptlog_002.txt` — planner handoff prompt (84 lines)
- `cycle_1_promptlog_003.txt` — title generation prompt (25 lines)
- `cycle_1_promptlog_004.txt` — web search for specs guide (177 lines)
- `cycle_1_promptlog_005.txt` — web search for desks under $400 (177 lines)
- `cycle_1_promptlog_006.txt` — first agent attempt with memory, web_search timeouts (781 lines)
- `cycle_1_promptlog_007.txt` — agent attempt without memory, same timeouts (764 lines)
- `cycle_1_promptlog_008.txt` — subagent prompt: specs guide task (410 lines)
- `cycle_1_promptlog_009.txt` — subagent prompt: desk research task (408 lines)
- `cycle_1_promptlog_010.txt` — planner clarification loop (775 lines)
- `cycle_1_promptlog_011.txt` — subagent successful web_searches (876 lines)
- `cycle_1_promptlog_012.txt` — subagent desk research with web_search (722 lines)

### Cycle 2 (thread `3ba1371a`)
- `cycle_2_metadata.json` — session metadata (81 lines)
- `cycle_2_promptlog_001.txt` — full system prompt (767 lines)
- `cycle_2_promptlog_002.txt` — planner handoff (84 lines)
- `cycle_2_promptlog_003.txt` — title generation (25 lines)
- `cycle_2_promptlog_004.txt` — semaphore errors (779 lines)
- `cycle_2_promptlog_005.txt` — condensed prompt, semaphore errors (762 lines)
- `cycle_2_promptlog_006.txt` — successful web search result (177 lines)
- `cycle_2_promptlog_007.txt` — timeout + retry failure (790 lines)
- `cycle_2_promptlog_008.txt` — condensed prompt, same failures (773 lines)
- `cycle_2_promptlog_009.txt` — knowledge_vault/lightrag errors (802 lines)
- `cycle_2_promptlog_010.txt` — condensed prompt with tool errors (785 lines)
- `cycle_2_promptlog_011.txt` — title generation (25 lines)
- `cycle_2_promptlog_012.txt` — successful web search result (177 lines)
- `cycle_2_promptlog_013.txt` — accumulated errors (811 lines)
- `cycle_2_promptlog_014.txt` — condensed prompt with planner handoff (794 lines)
- `cycle_2_promptlog_015.txt` — successful write_todos (781 lines)

---

## 7. Source Code References

| File | Lines | Relevance |
|---|---|---|
| `backend/src/agents/lead_agent/prompt.py` | 230-238 (`FETCH_POLICY_SECTION`) | References non-existent tools |
| `backend/src/agents/lead_agent/prompt.py` | 158-270 (`LEGACY_SYSTEM_PROMPT_TEMPLATE`) | Full system prompt template |
| `backend/src/agents/lead_agent/prompt.py` | 8-155 (`_build_subagent_section`) | Subagent system section (~135 lines) |
| `backend/src/agents/lead_agent/prompt.py` | 337-345 (`FETCH_POLICY_SECTION`) | Tool priority list with missing tools |
| `backend/src/agents/lead_agent/prompt.py` | 365-376 (`CRITICAL_REMINDERS_SECTION_TEMPLATE`) | Missing error recovery guidance |
| `prompt-tunning/prompt_id_4/cycle_*_metadata.json` | — | Test session metadata |
| `prompt-tunning/prompt_id_4/cycle_*_promptlog_*.txt` | — | 27 prompt log files analyzed |
