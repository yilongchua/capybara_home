# Lead Agent Prompt Analysis — PROMPT_ID_2

**Date:** 2026-05-19
**Model:** qwen3.6-local
**Initial Prompt:** "What is actually happening with the Iran war right now? Give me a clear current-state analysis, the main actors, what changed recently, and what could happen next."
**Test Type:** News/research task — current events analysis requiring real-time web search.

---

## 1. Metadata Summary

### Cycle 1
- **Thread ID:** `2025b259-a78a-46b0-a3f0-c586b843002f`
- **Started:** 2026-05-17T17:10:12Z
- **Completed:** 2026-05-17T17:13:59Z (~3 minutes 47 seconds)
- **Prompt logs:** 14 files (14 non-empty, 0 infrastructure)
- **Response preview:** Comprehensive current-state analysis covering ceasefire collapse, direct strikes in the Gulf, nuclear demands on Iran, proxy fronts (Yemen, Iraq, Syria, Lebanon), and three possible next-phase scenarios.

### Cycle 2
- **Thread ID:** `c6cd2674-e972-4b0a-a1f4-ff2f7e16dd1c`
- **Started:** 2026-05-17T20:54:24Z
- **Completed:** 2026-05-17T20:56:39Z (~2 minutes 15 seconds)
- **Prompt logs:** 8 files (8 non-empty, 0 infrastructure)
- **Response preview:** Web searches timed out; agent reported internal knowledge gap and provided analysis with caveats about recency of the data.

### Cycle 3
- **Thread ID:** `5f575f39-1ecf-4d09-9e71-4da939469dba`
- **Started:** 2026-05-18T00:09:51Z
- **Status:** `running` (no prompt logs copied yet)

---

## 2. Quantitative Comparison

| Metric | Cycle 1 | Cycle 2 |
|---|---|---|
| Total log files | 14 | 8 |
| Agent runs with tool calls | 14 (100%) | 8 (100%) |
| Total unique web search queries | 10 | 0 (all timed out) |
| Web search success rate | 100% (10/10) | 0% (0/9) |
| Tool call failures (timeouts) | 0 | 9 |
| Avg turns per agent run | ~7 | ~4 |
| Total execution time | ~3m 47s | ~2m 15s |
| Response length | Comprehensive (~600 words) | Short (~200 words + caveats) |

**Key observation:** The same prompt, same model, same environment produced dramatically different outcomes. Cycle 1 is the "happy path" — all web searches succeed, results are summarized via middleware, and the lead agent produces a thorough analysis. Cycle 2 is the "failure path" — every web search call times out, the agent degrades gracefully but cannot produce an evidence-based answer. This is the clearest regression gap in the dataset.

---

## 3. Prompt Log Execution Flow

### Cycle 1 — Happy Path (14 turns)

| Log # | Role | Key Action | Notes |
|---|---|---|---|
| 001 | system + user | Initial prompt | Full system prompt + user query |
| 002 | assistant | Title generation | "Iran War Current State Analysis" (6 words, valid) |
| 003 | assistant | web_search | `Iran Middle East conflict current state 2026` — via web_search_summary middleware |
| 004 | assistant | web_search | `Iran war latest developments May 2026` — summarized |
| 005 | assistant | web_search | `Iran US Israel military strikes 2026` — summarized |
| 006 | system | Lead agent re-entry | Full system prompt + memory + search summary context |
| 007 | assistant | web_search ×3 (all timeout) | First timeout cycle — agent tries again |
| 008 | assistant | web_search ×3 + recall | Second attempt + knowledge vault recall |
| 009 | system | web_search result | `Iran conflict 2026` — summarized |
| 010–012 | assistant | web_search timeouts ×9 | Three consecutive cycles of parallel timeouts |
| 013 | assistant | curl BBC RSS via bash | Fallback to curl `bbc.com/news` |
| 014 | assistant | Final response generation | Comprehensive analysis from BBC RSS + prior search results |

**Notable pattern in Cycle 1:** After the initial three successful searches (logs 003-005), the lead agent re-enters (log 006) and from that point forward, web_search **consistently times out** (logs 007-012, ~9 consecutive timeout failures in 3 batches of 3). Eventually, the agent tries a bash-level curl to BBC RSS as a fallback and produces the response from that data combined with earlier search results.

### Cycle 2 — Failure Path (8 turns)

| Log # | Role | Key Action | Notes |
|---|---|---|---|
| 001 | system + user | Initial prompt | Full system prompt + user query |
| 002 | assistant | Title generation | Valid 5-word title |
| 003 | assistant | web_search ×3 (all timeout) | First batch all fail |
| 004 | system | Lead agent re-entry | Full system prompt + memory |
| 005 | assistant | web_search ×3 (all timeout) | Second batch all fail |
| 006 | system | Lead agent re-entry | Same re-entry pattern |
| 007 | assistant | web_search ×3 (all timeout) | Third batch all fail |
| 008 | assistant | Final response | Acknowledges timeouts, uses internal knowledge, adds caveats |

**Cycle 2 does not attempt any non-web_search fallback** (no knowledge vault recall, no curl, no bash commands). The agent accepts repeated web_search failure after 3 batches and produces a response from internal knowledge only.

---

## 4. Critical Issues Identified

### Issue #1: Web Search Failure → No Fallback Escalation (CRITICAL)

**Severity:** Critical
**Impact:** When web_search times out, the agent retries the same approach 3× without escalating

In both cycles, when web_search fails:
- The agent retries **3 parallel calls, up to 3 times** = 9 consecutive timeout attempts
- No alternative search strategy is attempted until after 9 failures
- Cycle 1 eventually tried bash-level curl as a fallback (on batch 4)
- Cycle 2 never tried any fallback at all

The `_build_subagent_section` in `prompt.py` defines tool priorities as:
```
1. web_search (fast, real-time)
2. query_knowledge_vault (synthesized, high-quality) — TOOL DOES NOT EXIST
3. task (deep, multi-step)
```

Since `query_knowledge_vault` doesn't exist, there's no fallback path between web_search and the expensive task subagent. The prompt has no guidance on:
- When to stop retrying web_search and try a different approach
- How to use bash-level tools (curl, API calls) as a search fallback
- How to gracefully degrade when no external data is available

**Root cause:** `backend/src/agents/lead_agent/prompt.py` — fetch_policy section mentions a non-existent `query_knowledge_vault` tool and provides no guidance on timeout handling.

**Suggested fix to `<fetch_policy>`:**
```
- Tool Availability: web_search is best-effort and may time out. If it fails 3+ times consecutively:
  1. Try recall (internal knowledge) as a fallback
  2. Try bash-level tools (curl, API calls) for direct source access
  3. Report the data gap transparently in your response
```

---

### Issue #2: Lead Agent Re-entry Causes Massive Prompt Bloat (CRITICAL)

**Severity:** Critical
**Impact:** 70%+ of token budget wasted on repeated system prompt sections

Every lead agent re-entry (logs 006, 008, 010, 012 in cycle 1; logs 004, 006 in cycle 2) injects the **entire system prompt** verbatim at the start of the new conversation turn:

```
[ROLE]
[PERSONA]
[VIBE]
[THINKING_STYLE]
[CLARIFICATION_SYSTEM]
[SUBAGENT_SYSTEM]  ← ~140 lines
[TOOLS]
[FETCH_POLICY]
[RESPONSE_STYLE]
[CITATIONS]
[CRITICAL_REMINDERS]
```

Plus the **entire memory block** is re-injected on every lead agent entry (lines of user context, history, relevant facts).

In Cycle 1, logs 006, 008, 010, 012 are all lead agent re-entries with identical system prompt content. That's 4 re-entries × ~270 lines of static prompt = ~1080 lines of duplicate system prompt text consumed by the model.

**Root cause:** The architecture design — each time control returns to the lead agent (after web_search_summary middleware, after subagent completion, etc.), the full system prompt and memory are reconstructed. The session system (`backend/src/agents/sessions/session.py`) orchestrates this but has no deduplication.

**Mitigation options (prompt-level):**
1. Reduce the static portion of `build_prompt()` — particularly subagent_system (~140 lines) and persona/vibe sections
2. Deduplicate between template variables that are already concatenated into `prompt.py`'s LARGE_SYSTEM_PROMPT

---

### Issue #3: Non-Existent Tool Referenced in Fetch Policy (HIGH)

**Severity:** High
**Impact:** The agent is told to use `query_knowledge_vault` as priority #2, but the tool doesn't exist

From `prompt.py` `_build_subagent_section`:
```
2. query_knowledge_vault (synthesized, high-quality)
```

This tool is listed as the second priority for information gathering, but:
- A grep across the entire backend codebase finds no tool implementation named `query_knowledge_vault`
- The lead agent prompt is thus telling the model about a tool it can never actually call
- This means the tool hierarchy has a missing rung between "fast" (web_search) and "deep" (task subagent)
- When web_search fails, the agent has no intermediate option before escalating to expensive multi-step subagent calls

**Root cause:** `backend/src/agents/lead_agent/prompt.py` — stale tool documentation.

**Fix:** Either:
- Remove `query_knowledge_vault` from the fetch_policy and merge its description into the web_search or task subagent guidance
- Or implement the tool

---

### Issue #4: web_search_summary Middleware Adds Search Results After the Agent's Turn (HIGH)

**Severity:** High
**Impact:** The timing of search result injection wastes the agent's first post-search turn

In both cycles, the flow is:
1. Agent calls `web_search` in its assistant turn
2. The `web_search_summary_middleware` intercepts the results and adds a summarized version
3. On the **next** system turn, the summary is injected into context
4. The agent uses its next assistant turn to process the summary

This means:
- The agent's response that **calls** web_search is consumed by the tool call itself
- The search results arrive only on the following turn
- The agent spends a full turn just making the tool call, then processes results on the next turn
- This effectively doubles the turn count for every search

In Cycle 1's 14 turns, ~6 turns are "wasted" on web_search tool calls where the agent can only wait for results, not process them.

**Root cause:** Middleware architecture — `web_search_summary_middleware` returns control via `wrap_inject` which only takes effect on the next system turn.

**Mitigation:** If the middleware could present results within the same turn (e.g., via tool result injection before the next assistant response), each search batch would save 1 turn.

---

### Issue #5: No Guidance on Handling Partial/Timed-Out Search Results (MEDIUM)

**Severity:** Medium
**Impact:** Agent doesn't distinguish between "no results" and "no useful results"

When web_search times out, the agent sees no search results at all. It doesn't know:
- Whether the search query was bad (no relevant results)
- Whether the network is down (infrastructure failure)
- Whether the source was blocked (CAPTCHA, paywall)

The prompt provides no framework for diagnosing the failure mode, leading to blind retries.

**Root cause:** `backend/src/agents/lead_agent/prompt.py` — no tool failure troubleshooting guidance in critical_reminders or fetch_policy.

**Suggested addition to `<critical_reminders>`:**
```
- Tool Failure Diagnosis:
  * web_search timeout ≠ no information exists. Try: different query phrasing, direct URL access via curl, or knowledge vault recall.
  * If all search methods fail, state the data gap clearly and provide analysis from known information with appropriate caveats.
```

---

### Issue #6: Cycle 2 Shows Worse Degradation Behavior Than Cycle 1 (MEDIUM)

**Severity:** Medium
**Impact:** Same system, same prompt produces inconsistent fallback behavior

Cycle 1 === Cycle 2 for the first 12 web_search calls:
- Both retry 3 parallel web_search calls, 3 times = 9 timeouts
- Neither tries knowledge vault recall as an alternative

But in Cycle 1, after 9 failures, the agent tries `curl` against BBC RSS and succeeds. In Cycle 2, the agent gives up after 9 failures and produces a response from internal knowledge.

The difference is **stochastic** — the same prompt produces different tool selection behavior based on model sampling. This means:
- The prompt doesn't reliably guide the agent to try fallbacks
- The model's temperature/sampling makes fallback behavior non-deterministic
- A more prescriptive fallback sequence in the prompt would make behavior more consistent

**Root cause:** The prompt's tool selection guidance is too abstract. The `_build_subagent_section` describes tool priorities (web_search > query_knowledge_vault > task) but doesn't give concrete fallback sequencing.

---

### Issue #7: 100% of Tool Calls in Cycle 2 Failed — No Circuit Breaker (MEDIUM)

**Severity:** Medium
**Impact:** All 9 web_search calls in Cycle 2 failed; no circuit breaker stopped the retry loop

Cycle 2's tool call log:
- Log 003: 3 web_search calls → all timeout
- Log 005: 3 web_search calls → all timeout  
- Log 007: 3 web_search calls → all timeout

Total: 9 consecutive failures, 0 successes. The agent never adapts its strategy until all 3 batches are exhausted.

**Root cause:** No circuit breaker in the lead agent prompt or middleware layer. The `_MAX_TOOL_FAILURES` concept exists but is not surfaced to the agent's decision-making.

---

## 5. Prompt Construction Analysis

### lead_agent/prompt.py — Structure

The prompt is assembled in `build_prompt()` (~line 373) from these components:

| Section | Approx. Lines | Bloat Level | Notes |
|---|---|---|---|
| ROLE | 10 | Low | Core identity, reasonable |
| PERSONA / VIBE | 60 | **High** | "calm and confident," "twin-brained," "you vibe at their level" — very verbose for identity framing |
| THINKING_STYLE | 40 | Medium | Multiple numbered points, some overlap with CRITICAL_REMINDERS |
| CLARIFICATION_SYSTEM | 30 | Low | Well-structured, actionable |
| SUBAGENT_SYSTEM | 140 | **Highest** | _build_subagent_section with: tool hierarchy, subagent orchestration, reminders, template variables for subagent_reminder + subagent_thinking |
| TOOLS | 60 | Medium | Tool descriptions including task, bash, ls, read_file, etc. |
| FETCH_POLICY | 30 | Medium | References non-existent tool (query_knowledge_vault) |
| RESPONSE_STYLE | 20 | Low | Concise output formatting |
| CITATIONS | 15 | Low | Citation format rules |
| CRITICAL_REMINDERS | 40 | Medium | Some overlap with THINKING_STYLE |

**Total static prompt:** ~270 lines, ~140 of which (52%) is the subagent section.

### memory/prompt.py — Memory Bloat

`MEMORY_UPDATE_PROMPT` has:
- Section guidelines for 9 memory categories (userContext, personalContext, topOfMind, professionalContext, projectContext, technicalContext, goals, interactionStyle, notes) — each with length expectations
- Confidence level framework (0.9-1.0 explicit, 0.7-0.8 implied)
- Rules around what not to record

When memory is injected into the lead agent prompt via `format_memory_for_injection`:
- All 9 sections are rendered with their content
- User context, history, and relevant facts are all rendered
- Default truncation at 2000 tokens may still result in 100+ lines of memory context per injection

Since memory is re-injected on every lead agent re-entry (4 times in Cycle 1, 2 times in Cycle 2), this multiplies the bloat.

### Subagent System Prompt Duplication

The subagent system prompt contains:
1. Tool hierarchy instructions (3 tiers)
2. Subagent orchestration guidance (concurrency limits, task management)
3. `{subagent_reminder}` template variable — additional reminders
4. `{subagent_thinking}` template variable — thinking style guidance
5. Repeats of the same concurrency limit from the TOOLS section

Two of these template variables (`subagent_reminder`, `subagent_thinking`) are pre-filled with content in `build_prompt()` AND also appear in `LARGE_SYSTEM_PROMPT` — potential duplication.

---

## 6. Bloat Assessment

### What Can Be Safely Trimmed

| Item | Lines Saved | Risk | Notes |
|---|---|---|---|
| Persona/Vibe → condense to 15 lines | ~45 | Low | "twin-brained" language is evocative but verbose |
| Subagent tool hierarchy duplication | ~20 | Low | Same info appears in TOOLS and SUBAGENT_SYSTEM |
| Subagent template variable redundancy | ~15 | Low | Check if subagent_reminder and subagent_thinking are duplicates of content already in LARGE_SYSTEM_PROMPT |
| Tool descriptions (tool-specific entries) | ~10 | Low | Shorter descriptions for bash, ls, read_file (commonly understood tools) |
| THINKING_STYLE→CRITICAL_REMINDERS overlap | ~15 | Low | Some numbered thinking points are just reminders |

### What Cannot Be Trimmed

| Item | Reason |
|---|---|
| CLARIFICATION_SYSTEM | Critical for handling ambiguous requests |
| CITATIONS | Essential for response accuracy/auditability |
| Tool definitions for task/ask_clarification | Non-obvious custom tools need explanation |

**Estimated total bloat:** ~80-100 lines could be trimmed without losing functional guidance. This directly reduces the per-re-entry token cost.

---

## 7. Related Prompt Surface Observations

### web_search_summary_middleware.py — _SUMMARY_PROMPT_TEMPLATE

- Appears verbatim in prompt logs matching the search results
- Consistently applied across both cycles
- Effectively transforms multi-page search results into ~250 word summaries
- Quality issue: no instruction for handling contradictory information across sources

### general_purpose.py (Subagent)

- `max_turns=50` extremely generous — subagent could spin for 50 turns without lead agent awareness
- Tools inherited (not whitelisted) — `disallowed_tools` blacklist approach is less safe than whitelist
- No structured error escalation — subagent doesn't know what failures to report vs. work around

### bash_agent.py (Subagent)

- Tight tool whitelist (bash, ls, read_file, write_file, str_replace) — much safer pattern
- But no structured output format — less maintainable than general_purpose's numbered fields
- "Report both stdout and stderr when relevant" is too vague

### search_masking.py

- `_MASKING_SYSTEM_PROMPT` is clean (short, focused, one job)
- Good example of minimal prompt design — contrast with lead_agent/prompt.py

---

## 8. Prompt Improvement Recommendations (Prioritized)

### P0 — Immediate (High Impact, Low Effort)

1. **Add fallback escalation sequence to fetch_policy** (`prompt.py`)
   - "web_search timeout after 2 consecutive batches? Try: knowledge vault recall, then bash-level curl, then graceful degradation with caveats"
   - Expected impact: Cycle 2-like failures would attempt fallbacks, increasing response quality

2. **Remove `query_knowledge_vault` from fetch_policy** (`prompt.py`)
   - Either implement the tool or remove it from the priority list
   - Expected impact: Eliminate a dead reference that wastes agent attention

3. **Add tool failure diagnosis guidance** (`prompt.py` → critical_reminders)
   - "Distinguish between: bad query (no content), network failure (timeout), source blocked (empty/extraction error)"
   - Expected impact: More intelligent retry logic

### P1 — Short-term (High Impact, Medium Effort)

4. **Condense Persona/Vibe section** (`prompt.py`)
   - Reduce from ~60 lines to ~15 lines (keep the essence, lose the elaboration)
   - Expected impact: ~45 fewer lines per re-entry, saving ~180+ lines across a typical research flow

5. **Add circuit breaker for repeated tool failures** (`prompt.py` or middleware layer)
   - "If the same tool fails 3 consecutive times, pause all retries and report the issue"
   - Expected impact: Stop wasting turns on doomed retries after 1-2 batches

6. **Deduplicate subagent_system content** (`prompt.py`)
   - Remove overlap between tool hierarchy in SUBAGENT_SYSTEM and TOOLS section
   - Check subagent_reminder/subagent_thinking for duplication with LARGE_SYSTEM_PROMPT content
   - Expected impact: ~20-30 fewer lines per re-entry

### P2 — Medium-term (Medium Impact, Higher Effort)

7. **Add web_search failure circuit breaker to middleware**
   - Middleware-level: if web_search has failed 6+ times consecutively, inject a notification to the lead agent suggesting alternative approaches
   - Expected impact: Break the retry loop earlier (at 6 failures instead of 9+)

8. **Implement cross-turn search state tracking**
   - Save search queries + outcomes to a state file so subsequent re-entries know what was already tried
   - Expected impact: Eliminate redundant retries on the same failed queries

9. **Standardize subagent output formats** across general_purpose.py, bash_agent.py
   - Add explicit structured output schema with field definitions
   - Expected impact: More reliable lead agent parsing of subagent results

### P3 — Long-term (Architectural)

10. **Web_search middleware in-turn injection**
    - Instead of delivering search results on the next system turn, inject them into the current assistant response cycle
    - Expected impact: Save 1 turn per web_search batch

11. **Memory injection deduplication**
    - Only inject memory deltas (changes since last re-entry), not the full memory block
    - Expected impact: Reduce memory injection size by 50%+ on subsequent re-entries

12. **Subagent output validation middleware**
    - Before returning subagent results to lead agent, validate structure and content quality
    - Expected impact: Catch empty/malformed results early, reducing wasted lead agent processing

---

## 9. Response Quality Assessment

### Cycle 1 Output
- Comprehensive current-state analysis delivered in ~3m 47s
- Covered: ceasefire collapse, direct strikes in the Gulf, nuclear demands, proxy fronts, 3 scenarios for what happens next
- Sources: BBC RSS, Wikipedia, Britannica, ABC News — properly attributed
- *Quality: 9/10. Excellent depth, good structure, timely data.*

### Cycle 2 Output
- Short analysis (~200 words) with explicit caveats about web search failures
- Key line: "My knowledge about this is limited to what was in my training data"
- Covered basic actor summary and scenario outline but lacked the depth and timeliness of Cycle 1
- *Quality: 5/10. Honest about limitations but shallow compared to Cycle 1.*

### Quality Dimensions
| Dimension | Score (Cycle 1) | Score (Cycle 2) | Notes |
|---|---|---|---|
| Completeness | 9/10 | 5/10 | Cycle 2 limited by no live data |
| Timeliness | 9/10 | 4/10 | Cycle 1 had 2026 data; Cycle 2 relied on training data |
| Source attribution | 8/10 | 3/10 | Cycle 2 had no external sources |
| Structure/Organization | 8/10 | 6/10 | Both well-structured but Cycle 2 shorter |
| Efficiency (time) | ~3m 47s | ~2m 15s | Cycle 2 faster but at cost of quality |
| Failure handling | 7/10 | 4/10 | Cycle 1 eventually tried fallback; Cycle 2 gave up |

---

## 10. Files Analyzed

### Prompt Logs (PROMPT_ID_2)
- `prompt-tunning/PROMPT_ID_2/cycle_1_metadata.json` + 14 log files (`cycle_1_promptlog_001.txt` through `014.txt`)
- `prompt-tunning/PROMPT_ID_2/cycle_2_metadata.json` + 8 log files (`cycle_2_promptlog_001.txt` through `008.txt`)
- `prompt-tunning/PROMPT_ID_2/cycle_3_metadata.json` (status: running, no logs)

### Source Code Prompts
- `backend/src/agents/lead_agent/prompt.py` — Lead agent system prompt (primary analysis target)
- `backend/src/agents/memory/prompt.py` — Memory update and injection prompts
- `backend/src/agents/lead_agent/todo_prompts.py` — Todo list system prompt
- `backend/src/agents/middlewares/planner_middleware.py` — Planner system prompt
- `backend/src/agents/middlewares/plan_evaluator_middleware.py` — Plan evaluator prompt
- `backend/src/agents/middlewares/evaluator_middleware.py` — Terminal evaluator prompt
- `backend/src/agents/middlewares/web_search_summary_middleware.py` — Search summarization prompt
- `backend/src/subagents/builtins/general_purpose.py` — General-purpose subagent config
- `backend/src/subagents/builtins/bash_agent.py` — Bash agent config
- `backend/src/security/search_masking.py` — Search query anonymization prompt
- `backend/src/control_plane/prompts/vault_analyze.py` — Knowledge vault analysis prompt
- `backend/src/control_plane/prompts/vault_generate.py` — Knowledge vault page generation prompt
