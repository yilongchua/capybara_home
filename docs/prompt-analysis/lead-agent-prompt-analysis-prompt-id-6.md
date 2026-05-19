# Lead Agent Prompt Analysis — PROMPT_ID_6

**Generated:** 2026-05-19
**Prompt ID:** 6
**Model:** `mlx-community/qwen3.6-35b-a3b` (qwen3.6-local)
**Difficulty:** medium

---

## 1. Test Overview

| Cycle | Thread ID | Initial Prompt | Duration | Logs |
|---|---|---|---|---|
| 1 | `9f1b7c77-c7ed-45ec-9eb3-fd578e87c4b1` | "I'm confused about whether renting or buying is smarter in my city. Walk me through the numbers I need, the non-financial tradeoffs, and a simple decision framework." | ~3 min | 3 files |
| 2 | `75317721-d0a3-4848-949b-c1699adf2ffb` | Same prompt | ~2 min 17s | 2 files |

**Total interactions analyzed:** 5 prompt logs across both cycles.

---

## 2. Critical Findings

### 2.1 Memory Retrieval Returns Irrelevant Facts (Severity: Critical)

**Evidence:** `cycle_1_promptlog_003.txt:769-775`

The `recall` tool was invoked with query `"user location city home renting buying housing"` but returned five facts all scoring ~0.425 that are completely irrelevant:

```json
{"content": "User is researching crystals for karma protection, spiritual shielding..."}
{"content": "User successfully retrieves real-time geopolitical analysis via BBC RSS feeds..."}
{"content": "User is actively seeking a detailed, real-time current-state analysis of the Iran war..."}
{"content": "User expects the assistant to utilize web search capabilities..."}
{"content": "User's finalized 12-day Greece island-hopping itinerary covers a Cyclades route..."}
```

**The Tasmania trip fact** (`[context] User is planning a trip to Tasmania (Hobart) from May 23 to June 6, 2026`) **exists in the static memory injection** (line 509 of all log files) but was NOT returned by recall. This means:

- The vector store returns low-confidence, semantically broad facts
- High-signal location context is buried in static memory and never surfaced at query time
- The agent has no mechanism to connect "my city" in the user's question with known location data

**Impact:** The agent cannot reliably retrieve personal context for location-dependent questions, which is a core use case for the memory system.

---

### 2.2 Subagent Section Dominates System Prompt (~31% of Total) (Severity: High)

**Evidence:** `backend/src/agents/lead_agent/prompt.py:8-155` (240 lines)

The `<subagent_system>` section occupies ~240 lines of a 760+ line system prompt. For simple knowledge queries like "renting vs buying", this:

- Consumes ~30% of the context window
- Provides zero value (the agent never used subagents for this query)
- Creates cognitive noise — the model must constantly suppress the urge to decompose a non-decomposable task

**Cross-cycle observation:** In all 4 agent turns, the subagent system was completely unused. The section is only relevant for complex multi-step tasks.

**Impact:** Wasted tokens on every turn, increased latency, and potential for the model to over-decompose simple queries.

---

### 2.3 No Guidance for Location-Dependent Questions (Severity: High)

**Evidence:** `prompt.py:175-202` (clarification_system), `prompt.py:230-238` (fetch_policy)

There is no explicit guidance for handling questions that depend on user location when:
1. The location IS known from memory (Tasmania trip, relocation evaluation)
2. The location is unknown and needs to be asked

The clarification_system says "proceed with stated assumption" but for location-dependent financial advice, an assumption is worse than asking. The fetch_policy says "web_search first" but searching without a city is futile.

**Cross-cycle behavior:**
- Cycle 1: Agent ran recall with a generic query instead of checking memory for location, then responded with generic advice
- Cycle 2: Agent skipped recall entirely and gave general renting vs buying advice — never surfaced the user's active relocation evaluation (Singapore → London/Dubai/Sydney) which is in memory

**Impact:** The agent gives generic advice when it could provide personalized guidance based on known location context.

---

### 2.4 Response Style Contradiction (Severity: Medium)

**Evidence:** `prompt.py:240-244` vs actual response previews in metadata

```
<response_style>
- Clear and Concise: Avoid over-formatting unless requested
- Natural Tone: Use paragraphs and prose, not bullet points by default
```

Both cycle response previews produced heavily formatted output with markdown tables, `##` headers, bold items, and bullet lists — directly contradicting the "natural tone / paragraphs" instruction.

**Root cause:** The response_style section conflicts with:
- `working_directory` guidance encouraging "multiple well-named output files" and structured reports
- The overall prompt structure which encourages comparison tables (fetch_policy examples, citations section)

**Impact:** The model ignores this section because it's in tension with other prompt instructions. Contradictory guidance degrades overall instruction adherence.

---

### 2.5 Fetch Policy Misaligned with Question Type (Severity: Medium)

**Evidence:** `prompt.py:230-238`

```
<fetch_policy>
1. `web_search` — external web research should be attempted first for fresh information
```

For "is renting or buying smarter in **my city**", web_search is the wrong first step. The user's city isn't in context, and searching "user location city" wastes tokens. There is no "personal context first, then web search" hierarchy for location-dependent questions.

**Impact:** The agent defaults to external search before checking what personal context is already available.

---

### 2.6 Memory Update Prompt Over-Specification (Severity: Low-Medium)

**Evidence:** `backend/src/agents/memory/prompt.py:18-120`

The MEMORY_UPDATE_PROMPT specifies very detailed length guidelines (e.g., "workContext: 2-3 sentences", "recentMonths: 4-6 sentences or 1-2 paragraphs"). This creates:

- Memory sections dense with low-value detail (e.g., "Recently completed a beginner-friendly guide on metaphysical crystals for spiritual protection and grounding")
- Facts that crowd out high-signal context (Tasmania trip, relocation evaluation)
- The user's active work context is buried under completed trip planning details

**Impact:** Over time, memory becomes cluttered with stale or low-signal entries, reducing the signal-to-noise ratio for recall.

---

## 3. Prompt Structure Analysis

### 3.1 Section Size Breakdown (Estimated)

| Section | Lines | % of Total | Value for Simple Queries |
|---|---|---|---|
| subagent_system | ~240 | 31% | Very low (never used for knowledge Qs) |
| memory injection (runtime) | ~20-35 | 4-5% | Medium-high (when relevant facts surface) |
| thinking_style | ~8 | 1% | Low-medium |
| clarification_system | ~25 | 3% | Medium |
| working_directory | ~20 | 3% | Low (static) |
| fetch_policy | ~10 | 1% | Medium (misaligned) |
| response_style | ~5 | 0.7% | Low (ignored by model) |
| citations | ~12 | 1.5% | Low-medium |
| critical_reminders | ~15 | 2% | Medium |
| **Static overhead** | **~350+** | **~46%** | **Mixed** |

### 3.2 Token Efficiency Issue

The system prompt alone (before any user message) consumes ~1500-2000 tokens. For the qwen3.6-35b model, this is less critical than for smaller context windows but still wastes budget on static instructions that don't apply to every turn.

---

## 4. Specific Improvement Recommendations

### 4.1 Fix Memory Retrieval for Personal Context (Priority: P0)

**Problem:** Recall returns irrelevant low-confidence facts; known location context is buried in static memory.

**Recommended changes to `backend/src/agents/memory/prompt.py`:**
- Add a "location" or "geography" field to the memory schema, separate from general context
- Increase recall weight for high-confidence facts (currently all returning ~0.425)
- Add explicit guidance in the memory update prompt to extract and preserve location data with high confidence when mentioned
- Consider a "top_of_mind_location" field that gets updated whenever the user mentions a city/region

**Alternative:** Add location facts to a higher-priority slot in the "Relevant Facts" section that's always visible (not just via recall).

---

### 4.2 Make Subagent Section Compact (Priority: P1)

**Problem:** The subagent_system section is ~31% of the prompt but unused for most queries.

**Recommended changes to `backend/src/agents/lead_agent/prompt.py`:**
- Reduce the section from ~240 lines to ~80 lines by:
  - Removing the two full code-block usage examples (Usage Example 1 & 2 in `prompt.py:109-148`)
  - Condensing the 3 task decomposition examples into a single compact example
  - Removing redundant "CRITICAL WORKFLOW" steps (already covered by the concise rules above)
- Consider making it a "progressive loading" skill that's only injected when task complexity suggests decomposition is needed

**Target reduction:** ~60% smaller subagent section without losing critical guidance.

---

### 4.3 Add Location-Aware Query Handling (Priority: P1)

**Recommended addition to `backend/src/agents/lead_agent/prompt.py` — new section after `fetch_policy`:**

```
<location_awareness>
For questions that depend on user location (housing, weather, local services, regulations):
1. First check memory for any known location context (trips, residence, relocation plans)
2. If no location is found in memory, ask the user for their city/region BEFORE using web_search
3. Do NOT make assumptions about location — personal advice requires accurate geography
4. If the user mentions a location in passing (e.g., "I'm visiting X"), treat it as temporary context, not permanent residence
</location_awareness>
```

This directly addresses the failure mode seen in PROMPT_ID_6 where the Tasmania trip was known but never surfaced.

---

### 4.4 Align Fetch Policy with Question Type (Priority: P2)

**Recommended changes to `fetch_policy` section in `prompt.py`:**

```
<fetch_policy>
When looking for information, use sources in this priority order:
1. **Personal context first** — Check memory/relevant facts for user-specific information before external search
2. `web_search` — For fresh, location-specific, or publicly available information
3. `query_knowledge_vault` — For internal/knowledge-base content
4. `query_lightrag` — For graph-oriented, multi-hop relationship evidence
5. `search_internal_documents` — For indexed internal doc search

**When NOT to use web_search:**
- For personal advice where the answer depends on user-specific context (check memory first)
- For conceptual/explanatory questions that don't require current data
- When the user hasn't provided necessary identifying details (ask first)

For `web_search`, prefer short human-like search phrases.
</fetch_policy>
```

---

### 4.5 Fix Response Style Enforcement (Priority: P2)

**Option A — Strengthen the instruction in `prompt.py`:**

```
<response_style>
- Default to natural prose paragraphs, not bullet points or tables
- Use formatting (lists, tables, headers) ONLY when the user requests structured output or when it materially improves clarity
- Avoid markdown over-formatting: no headers for simple answers, no tables for 2-3 items
- Match the user's tone: casual questions get conversational answers; technical requests get structured output
</response_style>
```

**Option B — Remove the section entirely.** The "Clear and Concise" + "Action-Oriented" reminders in `critical_reminders` may be sufficient, and the contradiction between "natural tone" and "multi-file research output" creates confusion.

---

### 4.6 Streamline Memory Update Guidelines (Priority: P3)

**Recommended changes to `backend/src/agents/memory/prompt.py`:**
- Reduce the excessive length specifications (e.g., "4-6 sentences" is too prescriptive)
- Add explicit rule: "When user mentions a location, city, or region for travel/residence purposes, extract it as a high-confidence [context] fact with the date and purpose"
- Add: "Deprioritize or summarize completed trip planning details; focus on active/current plans"
- This would prevent memory from being cluttered with outdated Greece/Netherlands trip details when Tasmania is active

---

### 4.7 Add Task-Complexity-Based Query Routing (Priority: P3 — long-term)

**Concept:** The system prompt could include a small routing section that activates different instruction sets based on query type:

```
<query_routing>
Before responding, classify the user's request:
- **Personal advice** (housing, finance, career): Check memory for context first. Ask for missing specifics.
- **Knowledge/explanation** (how does X work): Provide direct answer. Use web_search only for current data.
- **Code/implementation**: Use subagents if >3 parallel steps. Otherwise execute directly.
- **Research/deep analysis**: Use subagents with decomposition. Produce structured output files.
- **Simple request** (1-2 steps): Execute directly, no tools needed.
</query_routing>
```

This would help the model make better decisions about tool usage rather than defaulting to recall or web_search for everything.

---

## 5. Summary of Impact

| Recommendation | Effort | Expected Impact | Addresses PROMPT_ID_6 Issue? |
|---|---|---|---|
| Fix memory retrieval (P0) | Medium | High — solves the core recall failure | Yes, directly |
| Compact subagent section (P1) | Low | Medium — saves ~500 tokens/turn, less noise | Partially |
| Location-aware guidance (P1) | Low | High — prevents this exact failure mode | Yes, directly |
| Align fetch policy (P2) | Low | Medium — better tool selection | Partially |
| Fix response style (P2) | Low | Low — cosmetic, but reduces formatting noise | No |
| Streamline memory update (P3) | Medium | Medium — cleaner memory over time | Indirectly |
| Query routing (P3) | High | High — systemic improvement | Yes, fundamentally |

**Top 3 actions to fix PROMPT_ID_6 specifically:**
1. **Fix recall relevance** — the Tasmania trip fact exists but isn't surfaced; vector store needs better scoring or a dedicated "active context" slot
2. **Add location-aware query handling** — explicit guidance to check memory for location before web_search
3. **Compact the subagent section** — remove ~60% of redundant examples and boilerplate

---

## 6. Files Referenced

| File | Relevance |
|---|---|
| `backend/src/agents/lead_agent/prompt.py` | Main system prompt template — subagent section, fetch_policy, response_style, clarification_system |
| `backend/src/agents/memory/prompt.py` | Memory update prompt, memory injection formatting, fact extraction |
| `prompt-tunning/PROMPT_ID_6/cycle_1_promptlog_003.txt` | Evidence of recall returning irrelevant facts (line 769-775) |
| `prompt-tunning/PROMPT_ID_6/cycle_2_promptlog_001.txt` | Evidence of agent giving generic advice without surfacing relocation context |
| `prompt-tunning/PROMPT_ID_6/cycle_*_metadata.json` | Response previews, test metadata |
| `backend/src/agents/lead_agent/todo_prompts.py` | Related prompt surface (todo list instructions) |
