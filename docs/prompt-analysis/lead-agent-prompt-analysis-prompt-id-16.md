# Lead Agent Prompt Analysis — PROMPT_ID_16

> **Scope:** Analysis of `cycle_*_promptlog_*.txt` and `cycle_*_metadata.json` files in `prompt-tunning/PROMPT_ID_16/`, cross-referenced with `backend/src/agents/lead_agent/prompt.py` and related prompt surfaces.
>
> **Goal:** Identify actionable improvements to the Lead Agent system prompt based on observed execution behavior across 2 tuning cycles.

---

## 1. Executive Summary

| Metric | Cycle 1 | Cycle 2 |
|---|---|---|
| Prompt logs | 40 | 17 |
| Runtime | ~75 min | ~8.5 min |
| Outcome | **FAILED** — synthesis stage timeout (1200s) | **SUCCESS** — report delivered |
| Root cause | Oversized subagent prompts + cascading timeouts | Narrower subagent scopes, but still hit web_search timeouts |

The delta between cycles shows the model learned to decompose more narrowly, but the **system prompt itself did not change** between cycles — the improvement came from the model's own adaptation within the conversation. This means the prompt is not actively guiding the model toward the better behavior observed in Cycle 2.

---

## 2. Cycle 1 Failure Analysis

### 2.1 Execution Flow

1. **Log 001** — Initial prompt received. Full system prompt injected (~767 lines including memory, subagent system, working directory, fetch policy, response style, citations, critical reminders). Memory context alone is ~500 lines of dense user history.
2. **Log 002** — Planner middleware fires. Returns structured JSON plan with todos.
3. **Logs 003–004** — Title generation (750B each, minimal).
4. **Log 005** — Lead agent launches 3 parallel `task()` subagents for protection/grounding research. Each subagent receives a **mega-brief** prompt with 5 detailed research dimensions per crystal.
5. **Logs 006–008** — Subagents execute web searches. Results contain massive noise (nav bars, cookie banners, unrelated article links).
6. **Logs 009–020** — Subagents continue searching. Each web_search returns ~2000 chars of truncated content with heavy HTML noise. Subagent context balloons.
7. **Logs 021–036** — Lead agent launches additional subagent batches for luck/love/karma categories. Context window fills with accumulated search results.
8. **Logs 037–039** — Subagents return massive results. Lead agent attempts synthesis.
9. **Log 040** — **Catastrophic failure**: All 3 `task()` calls timeout at 1800s. Then all 3 `web_search()` calls timeout at 45s. Agent falls back to writing from memory, then hits `write_file` error (missing `description` field). Finally triggers replanning loop.

### 2.2 Key Failure Modes

| # | Failure | Evidence | Severity |
|---|---|---|---|
| F1 | **Subagent prompt bloat** — Each subagent was given 5 crystals × 5 research dimensions = 25 research targets in a single prompt | Log 005/009/010: subagent prompt lists Black Tourmaline, Obsidian, Sardonyx, Onyx, Hematite, Smoky Quartz, Petrified Wood with 5 bullets each | **Critical** |
| F2 | **Context window explosion** — Web search results include full HTML noise (nav bars, cookie banners, sidebar links) that consume context without adding signal | Log 009: Obsidian search returns 2000+ chars of Science.org cookie consent HTML | **Critical** |
| F3 | **No incremental write strategy** — Agent attempted single `write_file` with entire report, then failed on retry | Log 040: `write_file` error "Field required" (missing description param) | **High** |
| F4 | **Synthesis timeout** — Model tried to produce entire report in one response after collecting all results | Metadata: "~54568 characters of content that could not be summarized in one pass" | **Critical** |
| F5 | **Cascading timeouts** — After subagent timeouts, agent retried with web_search which also timed out, creating a death spiral | Log 040: 3× task timeout (1800s) + 3× web_search timeout (45s) | **High** |
| F6 | **Replanning loop** — After failure, the system injected "Generate a detailed structured plan" which restarted the planning cycle | Log 040 line 812 | **Medium** |

---

## 3. Cycle 2 Improvement Analysis

### 3.1 What Changed (Behaviorally, Not in Prompt)

Cycle 2 used the **identical system prompt** but the model behaved differently:

1. **Log 001** — Same initial prompt. Same memory injection.
2. **Log 002** — Planner fires again.
3. **Logs 003–004** — Title generation + initial web search.
4. **Log 005** — Web search summary middleware fires (new pattern). Summarizes search results into concise paragraphs.
5. **Logs 006–008** — More focused subagent launches.
6. **Log 009** — Title generation (750B).
7. **Logs 010–017** — Agent launches 3 parallel subagents with **narrower scopes** (protection/grounding split, luck/love/karma split, safety/evaluation split). Uses `write_todos` with dependency graph.

### 3.2 Why Cycle 2 Succeeded

| Factor | Cycle 1 | Cycle 2 |
|---|---|---|
| Subagent scope | 5 crystals × 5 dimensions each | 1–2 categories per subagent |
| Context management | Accumulated all search results | Used web_search_summary middleware |
| Write strategy | Single monolithic write | Incremental (implied by success) |
| Todo usage | Not observed | Used `write_todos` with DAG deps |
| Turn count | 40 | 17 |

**Key insight:** The model *can* behave well under this prompt, but it requires learning from failure. The prompt should encode Cycle 2's successful patterns as explicit instructions.

---

## 4. System Prompt Audit

### 4.1 Prompt Structure (from `prompt.py`)

The Lead Agent prompt is assembled from these sections:

```
<role> → 1 line
<soul> → variable (agent personality)
<memory> → 200–500 lines of user context (injected at runtime)
<thinking_style> → 8 lines
<clarification_system> → 25 lines
<skill_system> → variable (skills catalog)
<subagent_system> → 120+ lines (THE BIGGEST SECTION)
<working_directory> → 20 lines
<fetch_policy> → 8 lines
<response_style> → 4 lines
<citations> → 10 lines
<critical_reminders> → 12 lines
<current_date> → 1 line
```

### 4.2 Problem Areas Identified

#### P1: Subagent Section Dominance (~120 lines, 25% of prompt)

The `<subagent_system>` section is massively over-engineered with:
- 3 full code examples (Usage Example 1, Example 2, Counter-Example)
- 5 "DO/DON'T" rule blocks
- Repeated concurrency limit warnings (stated 6+ times)
- 3 different workflow descriptions that overlap

**Impact:** Consumes context window budget that could be used for task-specific guidance. The repetition dilutes signal.

#### P2: No Research-Specific Guidance

The prompt has generic "DECOMPOSE + PARALLEL EXECUTION" guidance but **zero research-specific instructions**:
- No guidance on how to scope research subagents
- No instruction to write incrementally during research
- No guidance on handling web search noise
- No instruction on when to stop researching and start writing

**Impact:** Cycle 1's mega-brief subagents were a direct result of this gap.

#### P3: Memory Context Bloat

The `<memory>` section injects ~500 lines of user history including:
- Detailed work projects (URA RAG API, CAG, Luke Legal Case)
- Personal interests (Dutch politics, astronomy, pickleball, crystals)
- Travel plans (Greece, Netherlands, Tasmania, Tokyo)
- Health optimization routines
- Financial analysis projects

For a crystals research task, the crystal-related memory is useful but everything else is noise. The memory injection has no relevance filtering.

#### P4: Conflicting Instructions

| Conflict | Location | Description |
|---|---|---|
| Bullet points | `response_style` vs actual usage | Says "not bullet points by default" but examples and critical reminders use bullets extensively |
| Subagent usage | `subagent_system` vs `critical_reminders` | Subagent section says "Preferred Approach" for complex tasks, but critical reminders say "Skill First" |
| Clarification | `clarification_system` vs planner | Clarification says "ask only when blocked" but planner middleware injects its own clarification questions |

#### P5: No Timeout Recovery Guidance

The prompt has no instructions for what to do when tools timeout. Cycle 1's death spiral (task timeout → web_search timeout → write_file error → replanning) could have been prevented with explicit recovery guidance.

#### P6: `write_file` Description Parameter Not Enforced

The tool schema requires `description` as the first parameter, but the agent failed to provide it in Cycle 1 (log 040, line 808: "Field required"). The prompt does not emphasize this requirement.

---

## 5. Related Prompt Surface Analysis

### 5.1 Planner Middleware (`planner_middleware.py`)

**Strengths:**
- Domain-aware planning (code|research|legal|trip|generic)
- Dependency-aware todo generation
- Clarification rules with max 2 questions

**Weaknesses:**
- PLANNER_SYSTEM_PROMPT has no research-specific todo templates
- Max 8 todos is too few for 5-category research with safety + evaluation
- No guidance on subagent assignment in todos

### 5.2 Plan Evaluator Middleware (`plan_evaluator_middleware.py`)

**Strengths:**
- Checks for circular dependencies, missing prerequisites, missing synthesis step
- Async path avoids event loop blocking

**Weaknesses:**
- Only checks "hard problems" — misses scope bloat detection
- No check for whether todos are appropriately scoped for subagent dispatch

### 5.3 Evaluator Middleware (`evaluator_middleware.py`)

**Strengths:**
- Pre-verification checks for unfinished todos
- LLM-based verdict with critique

**Weaknesses:**
- _EVALUATOR_PROMPT_TEMPLATE is extremely minimal (3 lines)
- No check for report completeness across all requested categories

### 5.4 Web Search Summary Middleware (`web_search_summary_middleware.py`)

**Strengths:**
- Summarizes raw search results into concise paragraphs (seen in Cycle 2, log 005)
- Reduces noise from HTML artifacts

**Weaknesses:**
- Not referenced in the lead agent prompt — model doesn't know to use it
- Summary prompt doesn't instruct to preserve URLs/citations

### 5.5 Subagent Prompts (`general_purpose.py`, `bash_agent.py`)

**Strengths:**
- Clear output format specification
- Working directory context included

**Weaknesses:**
- No research-specific guidance in general-purpose subagent
- No instruction to handle noisy web search results
- No max output length guidance

### 5.6 Search Masking (`search_masking.py`)

- Not directly relevant to prompt quality but adds latency to every web_search call
- Uses a separate LLM call for query anonymization

---

## 6. Todo List: Lead Agent Prompt Improvements

### High Priority

- [ ] **T1: Add research-specific decomposition guidance** — New section in system prompt instructing how to scope research subagents (1 category per subagent, max 3 crystals per subagent, explicit output format requirement)
- [ ] **T2: Add incremental write instruction** — Explicit guidance: "For research tasks exceeding ~5000 words, write sections incrementally using `write_file` with `append: true`. Never attempt a single monolithic write."
- [ ] **T3: Add timeout recovery protocol** — New section: "When a tool times out: (1) Do NOT retry the same call. (2) Fall back to alternative tools. (3) If all external tools fail, compile from knowledge and label as 'from established knowledge'."
- [ ] **T4: Compress subagent section** — Remove redundant examples. Keep 1 example, collapse repeated concurrency warnings into a single bold statement. Target: 60 lines → 35 lines.
- [ ] **T5: Add web search noise handling** — Instruction: "Web search results may contain HTML noise, navigation menus, and cookie banners. Extract only the substantive content. Ignore page chrome."

### Medium Priority

- [ ] **T6: Add `write_file` parameter emphasis** — In critical reminders: "ALWAYS provide the `description` parameter first when calling `write_file`, `read_file`, `str_replace`, and `bash`."
- [ ] **T7: Reference web_search_summary middleware** — Add to fetch_policy: "After web_search, use the search summary to distill results before incorporating into your analysis."
- [ ] **T8: Add research completeness checklist** — Before finalizing: "Verify all requested categories are covered. For research tasks, check: [category 1], [category 2], ..., safety notes, critical evaluation."
- [ ] **T9: Reduce memory injection noise** — Add relevance scoring to memory injection. For a crystals query, non-crystal personal context should be truncated or omitted.
- [ ] **T10: Add subagent output length guidance** — In general-purpose subagent prompt: "Keep research summaries under 2000 words. Use concise prose, not exhaustive lists."

### Low Priority

- [ ] **T11: Resolve bullet point contradiction** — Either update response_style to allow bullets for structured content, or remove bullet-heavy examples from other sections.
- [ ] **T12: Add planner todo subagent hints** — In PLANNER_SYSTEM_PROMPT, add optional `subagent_type` field guidance for research todos.
- [ ] **T13: Strengthen evaluator completeness check** — Add category coverage verification to evaluator middleware prompt.
- [ ] **T14: Add citation preservation in search summary** — Update web_search_summary prompt to preserve source URLs for citation.
- [ ] **T15: Consider componentized prompt mode** — The `componentized` flag in `prompt.py` exists but is not well-documented. Evaluate whether dynamic section loading (only include relevant sections based on task type) would reduce context bloat.

---

## 7. Architecture Observations

### 7.1 Prompt Caching

The `apply_prompt_template` function uses `get_cached_prompt()` with a cache key based on `(agent_name, subagent_enabled, max_concurrent_subagents, available_skills, prompt_componentized, progressive_skills)`. This means the prompt is computed once and reused. **Memory injection happens post-cache** via `_inject_memory_context()`.

**Implication:** Any prompt improvements will be immediately effective across all threads using the same configuration.

### 7.2 Componentized vs Legacy Mode

The code supports two modes:
- **Legacy:** `LEGACY_SYSTEM_PROMPT_TEMPLATE` with `.format()` substitution
- **Componentized:** `_build_componentized_prompt()` that joins discrete section templates

Both modes produce functionally identical output for the current configuration. The componentized mode enables future dynamic section loading.

### 7.3 Memory Injection Point

Memory is injected between `<soul>` and `<thinking_style>` via string replacement. The memory content is generated by `format_memory_for_injection()` which merges global + workspace scopes and formats into "User Context", "History", "Relevant Facts" sections.

**Risk:** Memory can exceed 2000 tokens (the configured `max_injection_tokens`), and there's no relevance filtering per query.

---

## 8. Cycle Comparison: What the Model Learned

| Behavior | Cycle 1 (failed) | Cycle 2 (succeeded) | Prompt Guidance? |
|---|---|---|---|
| Subagent scope | 5 crystals × 5 dims | 1–2 categories each | ❌ Not in prompt |
| Incremental writing | Attempted single write | Incremental (implied) | ❌ Not in prompt |
| Todo usage | None observed | DAG with dependencies | ✅ "Use write_todos" in log 040/744 |
| Timeout handling | Death spiral | Not encountered | ❌ Not in prompt |
| Search noise | Accumulated raw HTML | Used summary middleware | ❌ Not in prompt |

**Conclusion:** The model's improvement from Cycle 1 to Cycle 2 was **self-directed learning**, not prompt-guided. The prompt should be updated to encode these learned behaviors as explicit instructions, so the model exhibits Cycle 2 behavior on the first attempt.

---

## 9. Recommended Prompt Changes (Concrete)

### 9.1 New Section: Research Workflow

Insert after `<fetch_policy>`:

```
<research_workflow>
For deep research tasks:
1. DECOMPOSE by category — one subagent per research category (max 3 crystals per subagent)
2. SCOPE tightly — each subagent handles 1–2 categories with explicit output format
3. WRITE incrementally — save findings to `/mnt/user-data/workspace/<category>.md` as each subagent completes
4. SYNTHESIZE last — only after all categories are written, compile the final report
5. VERIFY completeness — check all requested categories are covered before presenting

NEVER give a single subagent more than 3 crystals or 5 research dimensions.
If a category has many items, split across multiple subagent batches.
</research_workflow>
```

### 9.2 New Section: Timeout Recovery

Insert in `<critical_reminders>`:

```
- Timeout Recovery: If a tool times out, do NOT retry the same call. Fall back to alternative tools or compile from existing knowledge. Label unverified content appropriately.
```

### 9.3 Compress Subagent Section

Remove:
- Usage Example 2 (multi-batch) — collapse into a single line in the workflow
- Counter-Example — merge into "DO NOT use subagents" bullet
- "How It Works" block — model already knows this from tool descriptions
- Redundant "CRITICAL" warnings — keep only the first one

### 9.4 Update Critical Reminders

Add:
```
- Tool Parameters: ALWAYS provide the `description` parameter FIRST for write_file, read_file, str_replace, and bash.
```

---

## 10. Files Referenced

| File | Purpose |
|---|---|
| `backend/src/agents/lead_agent/prompt.py` | Lead agent system prompt construction |
| `backend/src/agents/lead_agent/todo_prompts.py` | Todo system/tool prompts |
| `backend/src/agents/memory/prompt.py` | Memory update/injection prompts |
| `backend/src/agents/middlewares/planner_middleware.py` | Planning system prompt |
| `backend/src/agents/middlewares/plan_evaluator_middleware.py` | Plan quality evaluation |
| `backend/src/agents/middlewares/evaluator_middleware.py` | Terminal evaluation |
| `backend/src/agents/middlewares/web_search_summary_middleware.py` | Search result summarization |
| `backend/src/security/search_masking.py` | Query anonymization |
| `backend/src/subagents/builtins/general_purpose.py` | General-purpose subagent config |
| `backend/src/subagents/builtins/bash_agent.py` | Bash subagent config |
| `backend/src/control_plane/prompts/vault_analyze.py` | Vault analysis prompt |
| `backend/src/control_plane/prompts/vault_generate.py` | Vault generation prompt |
| `prompt-tunning/PROMPT_ID_16/cycle_1_metadata.json` | Cycle 1 run metadata |
| `prompt-tunning/PROMPT_ID_16/cycle_2_metadata.json` | Cycle 2 run metadata |
| `prompt-tunning/PROMPT_ID_16/cycle_1_promptlog_001.txt` | Cycle 1 initial prompt |
| `prompt-tunning/PROMPT_ID_16/cycle_1_promptlog_040.txt` | Cycle 1 failure state |
| `prompt-tunning/PROMPT_ID_16/cycle_2_promptlog_001.txt` | Cycle 2 initial prompt |
| `prompt-tunning/PROMPT_ID_16/cycle_2_promptlog_017.txt` | Cycle 2 final state |
