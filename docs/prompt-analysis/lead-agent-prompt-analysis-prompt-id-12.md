# Lead Agent Prompt Analysis — PROMPT_ID_12

**Date:** 2026-05-19
**Model:** mlx-community/qwen3.6-35b-a3b (local, via MLX)
**Mode:** work (auto_mode: true)
**Request:** "I want to build an emergency kit for a family of four in an apartment. Make a prioritized checklist, explain quantities, and separate must-haves from nice-to-haves."
**Cycles:** 2 (cycle_1: 3 invocations, cycle_2: 3 invocations)

---

## Overview

PROMPT_ID_12 tests the lead agent on a structured informational request — a prioritized checklist with quantities and categorization. It requires zero tool orchestration, no file operations, no code. Both cycles produced a solid answer with FEMA/CDC-aligned guidance, but the execution reveals systemic inefficiencies: the planner middleware adds overhead for a 1-call query, the system prompt is bloated with irrelevant subagent orchestration instructions, and memory context grows unbounded (~18% between cycles) with mostly irrelevant content.

---

## File Inventory — PROMPT_ID_12

| File | Purpose |
|---|---|
| `cycle_1_metadata.json` | Metadata: thread 8d1a1acc, runtime ~4m, status=completed |
| `cycle_1_promptlog_001.txt` | Full system prompt + user query (767 lines, 13 tools) |
| `cycle_1_promptlog_002.txt` | Planner middleware prompt (84 lines) |
| `cycle_1_promptlog_003.txt` | Title generation prompt (37 lines) |
| `cycle_2_metadata.json` | Metadata: thread f991da45, runtime ~5m28s, status=completed |
| `cycle_2_promptlog_001.txt` | Full system prompt + user query (767 lines, same structure) |
| `cycle_2_promptlog_002.txt` | Planner middleware prompt (84 lines, identical) |
| `cycle_2_promptlog_003.txt` | Title generation prompt (33 lines) |

**No cycle_3 exists.**

---

## Cycle 1 Flow Analysis

### Execution Summary

| Invocation | File | Timestamp | Purpose | Outcome |
|---|---|---|---|---|
| 001 | cycle_1_promptlog_001.txt | 18:09:39Z | Lead agent system prompt + user query | Model loaded full system prompt (~8,000+ tokens) |
| 002 | cycle_1_promptlog_002.txt | 18:09:42Z | Planner middleware | Generated JSON plan for a checklist |
| 003 | cycle_1_promptlog_003.txt | 18:11:27Z | Title generation | "Family of Four Emergency Kit — Apartment Checklist" |

### Issues

#### 1. Planner middleware adds overhead for a direct-answer query

- **Source:** `cycle_1_promptlog_002.txt:84`
- **Evidence:** Request was classified as complex enough for planning ("Work Mode detected this request is too complex for direct execution") even though a categorized checklist is a canonical "answer directly" query.
- **Impact:** +1 LLM call, +84 lines of planner prompt overhead, JSON parsing, 3-second latency.
- **Root cause:** The complexity classifier in `planner_middleware.py:326-338` relies on keyword heuristics. This request contains "plan" implicitly (in "emergency kit") and is >300 chars, triggering the "complex" classification even though the task is structurally simple (single-turn formatted answer).

#### 2. Subagent system section consumes ~950 tokens for an irrelevant use case

- **Source:** `cycle_1_promptlog_001.txt:560-697`
- **Evidence:** 137 lines of subagent orchestration instructions — concurrency limits, multi-batch strategy, 3 worked examples (Tencent stock, cloud providers, auth refactoring), counter-examples. None of this is relevant to writing an emergency kit checklist.
- **Impact:** ~25% of the content-bearing prompt. The model must process 950 tokens of "how to delegate to subagents" before seeing the actual question.
- **Mitigation:** The model correctly ignored subagent instructions and answered directly, showing robustness against irrelevant prompt sections — but at a token cost.

#### 3. Title generation is a separate, unnecessary LLM call

- **Source:** `cycle_1_promptlog_003.txt:18-37`
- **Evidence:** A dedicated LLM call at 18:11:27Z re-passing the user query + partial assistant answer just to produce "Family of Four Emergency Kit — Apartment Checklist" (6 words).
- **Alternatives:** (1) Use `response_preview` truncation for the title. (2) Have the lead agent include a title in its output format. (3) Extract first 6 words client-side.

#### 4. Memory context is bloated with irrelevant content

- **Source:** `cycle_1_promptlog_001.txt:498-518`
- **Evidence:** ~2,000 tokens of memory covering: Accenture CAG/URA RAG API, Singapore maritime law, Jira MDATA-799, Luke Legal Case Analysis, Tasmania trip planning, macOS downgrade plan, sleep hygiene protocol, metaphysical crystals guide, standing desks under $400, Greece island-hopping itinerary (SGD 10,400–14,630 budget), EV market research, Netherlands coastal trip. **Nothing relevant to emergency kits.**
- **Impact:** Signal-to-noise ratio is ~0%. The model must process 2,000 tokens of irrelevant personal data before seeing the user's actual question.
- **Root cause:** `format_memory_for_injection()` dumps the entire global memory store with only a token budget cap, no semantic filtering.

#### 5. Response quality was solid despite prompt inefficiencies

- **Source:** `cycle_1_metadata.json:17`
- **Evidence:** The response included proper FEMA/CDC-aligned 72-hour guidance, correct quantity calculations (1 gallon × 4 people × 3 days = 12 gallons), clear must-have vs nice-to-have separation, and well-structured tables with explanations.
- **Observation:** The model is resilient enough to produce good output even with ~75% of the prompt being irrelevant or unnecessary. But the token cost of processing those 8,000+ tokens on every turn is real (latency, cost, context window pressure).

---

## Cycle 2 Flow Analysis

### Execution Summary

| Invocation | File | Timestamp | Purpose | Outcome |
|---|---|---|---|---|
| 001 | cycle_2_promptlog_001.txt | 22:16:07Z | Lead agent system prompt + user query (same 13 tools) | Model loaded full system prompt |
| 002 | cycle_2_promptlog_002.txt | 22:16:09Z | Planner middleware (same prompt) | Generated JSON plan |
| 003 | cycle_2_promptlog_003.txt | 22:18:34Z | Title generation | "Emergency Kit Checklist — Family of Four, Apartment" |

### Cycle 1 vs Cycle 2 Comparison

| Metric | Cycle 1 | Cycle 2 | Delta |
|---|---|---|---|
| Runtime | ~4m02s | ~5m28s | **+35%** |
| Memory size | ~2,980 chars | ~3,510 chars | **+18%** |
| System prompt structure | 767 lines, 13 tools | 767 lines, same 13 tools | Identical |
| Response quality | Solid (FEMA/CDC, 72h guidance) | Solid (calorie counts, storage advice) | Marginally different |
| Memory file bytes | 39,252 | 39,618 | +0.9% |

### Issues

#### 1. Memory growth without intelligent pruning

- **Source:** `cycle_2_promptlog_001.txt:498-518`
- **Growth:** Current Focus section grew from ~850 chars to ~1,100 chars (+29%). History Recent grew from ~1,050 chars to ~1,300 chars (+24%). Personal section lost specificity ("metaphysical practices" → "health optimization").
- **New items in C2:** Permanent relocation evaluation (Singapore → London/Dubai/Sydney), beginner investment strategies ($10K), renting vs buying analysis, EV market research, emergency preparedness.
- **Problem:** The memory update prompt (`memory/prompt.py:18-120`) only appends new data — it never prunes stale or completed items. The user's macOS downgrade goal from months ago is still present as a "relevant fact."
- **Impact:** Unbounded growth pattern. At ~18% growth per cycle, after 10 cycles the memory section would exceed 15,000 chars, consuming ~50% of a 32K context window.

#### 2. Same system prompt overhead as Cycle 1 — no optimization

- **Source:** `cycle_2_promptlog_001.txt`
- **Evidence:** The system prompt is structurally identical to Cycle 1. All 13 tool definitions are baked in. The subagent section is unchanged. The planner prompt is identical.
- **Impact:** No learning across cycles. Each cycle wastes the same ~1,300 tokens on subagent instructions the model doesn't need and ~2,000 tokens on tool definitions.

#### 3. Cycle 2 runtime increased 35% over Cycle 1

- **Source:** `cycle_2_metadata.json:16-17`
- **Evidence:** Cycle 2 took 5m28s vs 4m02s for Cycle 1 (+86 seconds, +35%).
- **Causes:** Larger memory context (+530 chars), potentially more intermediate tool calls (not captured in prompt logs), model cold-start cache effects.
- **Assessment:** The marginal quality improvement (calorie counts, storage advice) does not justify the 86-second increase. This is a scalability red flag.

### Response Quality Differences

| Aspect | Cycle 1 | Cycle 2 | Verdict |
|---|---|---|---|
| "How to Read This" section | Present — explains format, 72h assumption, must-have vs nice-to-have | Missing — jumps straight into content | **C1 better** |
| Calorie counts | "~36–48 meals/snacks" | "1,200–1,500 kcal × 4 people × 3 days" | **C2 better** |
| Apartment storage advice | "store in 6–8× gallon jugs" | "buy in smaller bottles (1L–2L) that stack neatly" | **C2 better** |
| Documents & Cash section | Not explicitly listed | Explicit category | **C2 better** |
| FEMA/CDC citations | Explicit in water row | Less explicit | **C1 better** |

---

## Prompt Architecture Analysis — Cross-Cutting Issues

### 1. Token Budget Breakdown

| Section | Est. Tokens | % of Content Prompt | Notes |
|---|---|---|---|
| Tool definitions (13 tools) | 2,000–4,000 | ~30-40% | Injected by framework, always present |
| Memory context | 1,000–2,000 | ~15-20% | Growing unbounded |
| Subagent system section | ~950 | ~12% | Always active, rarely needed |
| Core system prompt (role, thinking, clarification, working_dir, fetch, response_style, citations) | ~1,300 | ~17% | Static, cached |
| Critical reminders | ~175 | ~2% | Partially redundant |
| **Total system prompt** | **~5,400–8,400** | **~76% of 11K turn** | Leaves ~24% for user message + tool outputs |

### 2. Cross-Prompt Redundancies

#### Redundancy A: Clarification Rules Defined 4 Times

| Location | Section | Lines |
|---|---|---|
| `lead_agent/prompt.py` | LEGACY `<clarification_system>` | 175-202 |
| `lead_agent/prompt.py` | componentized `CLARIFICATION_SECTION` | 286-313 |
| `lead_agent/prompt.py` | `CRITICAL_REMINDERS_SECTION_TEMPLATE` | 366 |
| `planner_middleware.py` | `CLARIFICATION_RULES` | 265-269 |

Each copy is worded slightly differently. The model receives overlapping signals that could diverge over time.

#### Redundancy B: Subagent Instructions Repeated Within the Same Prompt

| Location | Section | Text |
|---|---|---|
| `lead_agent/prompt.py:8-155` | `_build_subagent_section()` | Full 147-line orchestration guide |
| `lead_agent/prompt.py:526-531` | `subagent_reminder` → critical reminders | "You are a task orchestrator... HARD LIMIT: max {n} task calls" |
| `lead_agent/prompt.py:534-539` | `subagent_thinking` → thinking style | "DECOMPOSITION CHECK: Can this task be broken into 2+ parallel sub-tasks?" |

The concurrency limit rule appears 3 times in different wording. ~200+ tokens of pure duplication.

#### Redundancy C: Working Directory Instructions — Duplicated Across Modes

| Location | Lines |
|---|---|
| `LEGACY_SYSTEM_PROMPT_TEMPLATE` | 208-228 |
| `WORKING_DIRECTORY_SECTION` constant | 315-335 |

Byte-for-byte identical. Dual maintenance burden.

#### Redundancy D: TODO Prompts Overlap ~60%

| Location | Lines | Purpose |
|---|---|---|
| `todo_prompts.py:12-45` | `TODO_LIST_SYSTEM_PROMPT` (~325 tokens) | System prompt for todo tool |
| `todo_prompts.py:49-109` | `TODO_LIST_TOOL_DESCRIPTION` (~650 tokens) | Tool definition description |

Both sections contain "When to Use" / "When NOT to Use" / "Best Practices" with near-identical wording. Both are injected into the same model context.

### 3. Prompt Composition Pipeline Issues

#### Fragile memory injection via string replacement

- **Source:** `lead_agent/prompt.py:569-577`
- **Code:**
  ```python
  marker = "\n<thinking_style>"
  return prompt.replace(marker, f"\n{memory}\n\n<thinking_style>", 1)
  ```
- **Risk:** Breaks if section order changes. Breaks if memory content contains `\n<thinking_style>`. Not robust for prompt section reordering.

#### Cache key excludes memory content

- **Source:** `lead_agent/prompt.py:685-693`
- **Impact:** The base prompt is cached by `get_cached_prompt()`, but memory is injected post-cache. If memory injection logic changes (new sections, different ordering), cached base prompts must be invalidated manually (mtime-based).

#### Dual template maintenance (componentized + legacy)

- **Source:** `lead_agent/prompt.py:545-564`
- **Impact:** Two complete template definitions that produce identical output. Any prompt change must be applied to both. The legacy template should be removed.

#### Mode section concatenation is naive

- **Source:** `lead_agent/prompt.py:695-701`
- **Code:**
  ```python
  if dreamy_mode:
      return prompt + "\n\n" + DREAMY_MODE_SECTION
  ```
- **Problem:** No deduplication. If a mode section repeats instructions already in the base prompt, they accumulate. Dreamy mode section (lines 607-636) hardcodes paths like `/mnt/skills/dreamy-workflow/SKILL.md`.

### 4. Memory Injection Strategy Issues

#### Vector store retrieval is dead code

- **Source:** `memory/prompt.py:270-282`
- **Evidence:** The vector store query only fires when `current_turn_text.strip()` is truthy. In `_get_memory_context()` (prompt.py:412-413), the comment states: "can be threaded in later by middleware if needed" — but it never is. The `current_turn_text` parameter is always empty.
- **Impact:** The vector store path never activates. The fallback to "top 10 by confidence" always fires, returning a static set of facts regardless of the current query's semantic relevance.

#### Character-based truncation is lossy

- **Source:** `memory/prompt.py:305-310`
- **Code:**
  ```python
  char_per_token = len(result) / token_count
  target_chars = int(max_tokens * char_per_token * 0.95)
  result = result[:target_chars] + "\n..."
  ```
- **Problem:** Truncates mid-section. If the cutoff falls inside a "Relevant Facts" bullet or a behavior rule, the model receives broken content. No section-aware trim.

#### No dynamic token budget

- **Source:** `memory/prompt.py:201-202` — `max_tokens: int = 2000`
- **Problem:** A new user with no memory still pays the 2,000 token overhead. A power user with 100 facts hits aggressive truncation. A dynamic budget based on memory filled/filled ratio would be more efficient.

### 5. Planner Complexity Classification Issues

- **Source:** `planner_middleware.py:326-338`
- **Code:**
  ```python
  if not text or len(text) < 25:
      return "trivial"
  ```
- **Problem:** The "emergency kit" request is >300 chars and contains implied "planning" keywords, so it's classified as "complex" and routed through the planner. But a single-turn formatted checklist does not benefit from planning.
- **Fragile heuristics:** Keyword matching uses word-boundary checks for single words and substring for multi-word — inconsistent. A 24-character query with "refactor" is "trivial" (length < 25), but a 26-character greeting is not.

### 6. Evaluator Prompt Issues

- **Source:** `evaluator_middleware.py:19`
- **Code:**
  ```python
  _EVALUATOR_PROMPT_TEMPLATE = "You are a strict evaluator. Respond with:\nVERDICT: PASS or FAIL\nCRITIQUE: <one concise paragraph>\n\nPlan title: {plan_title}\nPlan summary: {plan_summary}\n\nCandidate response:\n{candidate_response}\n"
  ```
- **Problem:** The evaluator is a single paragraph with no output schema enforcement. The verdict parsing (`evaluator_middleware.py:123-133`) relies on fragile line scanning — if a model writes "Verdict: PASS" lowercase, it may not be captured by the `.upper()` check.
- **Issue with pre-verifier:** The `_pre_verify` method (`evaluator_middleware.py:87-106`) checks unfinished todos but overlaps with plan evaluator checks — no deduplication or coordination between the two evaluator stages.

### 7. Tool Definition Bloat

- **Source:** `cycle_1_promptlog_001.txt:14-488`
- **13 tool definitions injected every turn:** ls, read_file, write_file, str_replace, bash, present_files, ask_clarification, recall, write_todos, web_search, save_to_knowledge_vault, task, view_image
- **Impact:** ~2,000–4,000 tokens consumed by tool schemas on every turn, regardless of whether the task uses tools. A simple Q&A query gets all 13 tool definitions.
- **Optimization opportunity:** Domain-aware tool filtering. The planner already classifies requests into `code|research|legal|trip|generic`. Tools relevant only to code tasks (bash, str_replace) could be excluded for research/non-code domains.

---

## Recommendations

### Priority 0 — Critical

| # | Recommendation | Files Affected | Effort |
|---|---|---|---|
| R1 | **Activate vector store memory retrieval.** Thread `current_turn_text` through `_get_memory_context()` so semantically relevant facts are retrieved instead of stale top-10-by-confidence. | `lead_agent/prompt.py:412-413`, `memory/prompt.py:270` | Medium |
| R2 | **Replace character-based truncation with section-aware trimming.** Cut complete sections from the end (e.g., drop "Earlier History" before truncating mid-fact). | `memory/prompt.py:305-310` | Medium |
| R3 | **Remove legacy template.** Delete the `else` branch at `prompt.py:555-564` and `LEGACY_SYSTEM_PROMPT_TEMPLATE`. All caches should use componentized only. | `lead_agent/prompt.py` | Low |

### Priority 1 — High Impact

| # | Recommendation | Files Affected | Effort |
|---|---|---|---|
| R4 | **Trim subagent section examples.** Replace 3 full worked examples with a single condensed bullet-point checklist. Saves ~500 tokens. | `lead_agent/prompt.py:57-154` | Low |
| R5 | **Consolidate clarification rules** into a single shared constant imported by both lead agent and planner middlewares. | `lead_agent/prompt.py`, `planner_middleware.py` | Low |
| R6 | **Deduplicate TODO prompts.** Remove "when to use/not" from `TODO_LIST_TOOL_DESCRIPTION`. Tool descriptions are already visible to the model; the system prompt copy is redundant. Saves ~400 tokens. | `todo_prompts.py:49-109` | Low |
| R7 | **Add memory pruning logic.** The memory update prompt (`MEMORY_UPDATE_PROMPT`) should detect and flag stale/completed items for removal, not just append. | `memory/prompt.py:18-120` | Medium |

### Priority 2 — Quality of Life

| # | Recommendation | Files Affected | Effort |
|---|---|---|---|
| R8 | **Implement domain-aware tool filtering.** Use the domain classification from the planner to filter tool definitions for the lead agent (e.g., don't inject `bash` for research queries). | Framework-level, or `tools.py` | Medium |
| R9 | **Add prompt version identifiers.** Include `__prompt_version__` in cached entries so prompt changes are traceable and regressions can be diagnosed. | `lead_agent/prompt.py`, `prompt_cache.py` | Low |
| R10 | **Fix planner complexity classification.** Add a "direct answer" domain for queries that don't need planning (comparisons, checklists, tutorials). | `planner_middleware.py:326-338` | Low |
| R11 | **Replace title generation LLM call** with client-side extraction or embed title in lead agent's output format. Saves 1 LLM call per cycle. | Orchestrator level | Low |
| R12 | **Implement dynamic memory token budget.** Start small (e.g., 500 tokens) and scale up based on memory density. Don't waste 2,000 tokens on empty user profiles. | `memory/prompt.py:201-202` | Low |

---

## Summary

PROMPT_ID_12 reveals a system that produces good answers despite — not because of — its prompt infrastructure. The model is resilient enough to ignore ~75% of the input (irrelevant subagent instructions, bloated memory, redundant tool definitions) and still deliver a well-structured emergency kit checklist. But the token waste is real: ~6,000–8,500 tokens of overhead per turn, growing ~500 tokens per cycle through memory accumulation.

The four highest-ROI improvements are: (1) activate the vector store for relevant fact retrieval, (2) trim the subagent section from 950 tokens to ~400, (3) deduplicate TODO prompts to save 400 tokens, and (4) remove the legacy template to eliminate dual-maintenance burden. These four changes would reclaim ~1,000–1,500 tokens per turn (~15-20% of the current budget) and reduce the cognitive load on the model with each cycle.
