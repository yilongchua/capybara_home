# Lead Agent Prompt Analysis — PROMPT_ID_11

- **Date:** 2026-05-19
- **Source data:** `prompt-tunning/PROMPT_ID_11/` (76 files: 42 cycle 1 logs + 32 cycle 2 logs + 2 metadata files)
- **Prompt tested:** *"Research the current state of the Ukraine war and explain it like a geopolitical brief: front lines, military capacity, diplomacy, sanctions, and realistic scenarios for the next 6 months."*
- **Model:** `qwen3.6-local` — `work` mode, `auto_mode: true`
- **Key constraint:** Ignore `difficulty` field in metadata

---

## 1. Executive Summary

The prompt logs for PROMPT_ID_11 reveal a system that completes successfully but suffers from **four systemic problems**, only some of which are prompt-related:

| # | Problem | Root Cause | Impact |
|---|---|---|---|
| A | Web search 45s timeouts | Infrastructure (not prompt) | Agent forced to rely on training data |
| B | `asyncio` semaphore event loop error | Backend bug (new in cycle 2) | All parallel subagent searches fail simultaneously |
| C | Massive system prompt bloat (~8K–15K tokens) | Prompt architecture | Crowds out search results, slows reasoning |
| D | Subagent task re-dispatching | Lead agent prompt lacks guardrails | Same subagent task dispatched 5×, wasting turns |

**Cycle 1 → Cycle 2 trajectory:** Runtime improved 31% (13m → 9m), logs dropped 24% (42 → 32), but web search timeouts *worsened* (3 consecutive in C1 → 5 consecutive in C2 + new event loop error). The `write_file` tool error (missing `description` param) first appears in C2.

---

## 2. Run Summary

| Metric | Cycle 1 | Cycle 2 |
|---|---|---|
| Started | 2026-05-17 17:55 UTC | 2026-05-17 22:05 UTC |
| Duration | ~13m 18s | ~9m 18s |
| Prompt logs | 42 | 32 |
| Status | completed | completed |
| Web search outcome | All timeouts (fell back to training data) | All timeouts + new event loop bug |
| Response quality | Executive summary + 5 sections | Numbered sections, more geographic detail |

Both cycles use the **identical initial prompt** and **identical assistant config**. The only variable is the thread/session. Cycle 2 was faster but encountered *more* tool-level errors — suggesting the speed came from giving up faster, not from better reasoning.

---

## 3. Prompt Log Analysis — Execution Flow

Both cycles follow the same 4-phase pipeline:

### Phase 1: Lead Agent Initialization (log 001)
- Full system prompt (~8K-15K tokens) injected with memory context
- 13 tools available: `web_search`, `recall`, `write_file`, `present_files`, `task`, `ask_clarification`, etc.
- **Key problem:** Memory section contains ~350 lines of irrelevant user context (work, personal, travel, legal cases) for a Ukraine war research task

### Phase 2: Planning (logs 002-003)
- Planner middleware generates structured JSON plan
- Title generation (≤6 words)

### Phase 3: Research Execution (logs 004-027)
- Phase 3a: Lead-agent web search + summarization (logs 004-005)
- Phase 3b: Subagent delegation — 3 parallel research streams:
  - Front lines / battlefield dynamics
  - Military capacity
  - Diplomacy / sanctions / scenarios
- **Key problem:** Subagent tasks for the same topic dispatched 4-5× identically

### Phase 4: Synthesis & Output (logs 028-032)
- Final assembly
- `write_file` attempts
- Error recovery

---

## 4. Lead Agent `prompt.py` — Structural Findings

Source: `backend/src/agents/lead_agent/prompt.py`

### Finding 4.1: Subagent Section Is the #1 Bloat Source (lines 8–155, ~1,829 tokens)

The `_build_subagent_section` function contains:
- 5-line banner
- 80+ lines of batching instructions with multi-turn code examples
- 3 code examples with inline comments
- Repetitious warnings about hard concurrency limits

**Problem:** Almost all of this is also conveyed by `subagent_reminder` (injected into `CRITICAL_REMINDERS`) and `subagent_thinking` (injected into `THINKING_STYLE`), creating triple redundancy. The hard limit is enforced by `SubagentLimitMiddleware` regardless of prompt content.

**Recommendation:** Cut from ~1,829 to ~300 tokens. Drop code examples, reduce batching instructions. The middleware enforces limits — the prompt only needs to explain the *why*.

### Finding 4.2: Triple Redundancy on Subagent Rules

| Source | Location | Content |
|---|---|---|
| `_build_subagent_section` | lines 8-155 | Full treatise |
| `subagent_reminder` | lines 526-532 | Injected into reminders |
| `subagent_thinking` | lines 534-540 | Injected into thinking style |

All three say the same thing: "max N per turn, batch if >N, synthesize after batches." When subagent is enabled, all three are active simultaneously, wasting ~200+ tokens.

### Finding 4.3: Legacy System Prompt Is Dead Code (lines 158–270, ~1,625 tokens)

`prompt_config.py` defaults `componentized: bool = True`. The legacy path (`_build_prompt` line 556) never executes unless someone explicitly constructs `PromptConfig(componentized=False)`. This is 1,625 tokens of dead code.

### Finding 4.4: Memory Injection Fragile String Replacement (line 569–577)

`_inject_memory_context` searches for `\n<thinking_style>` marker in the cached prompt. If absent (e.g., format changes), memory is prepended to the entire prompt with no warning logged.

### Finding 4.5: `print()` Instead of `logger` in Error Path (line 428)

```python
except Exception as e:
    print(f"Failed to load memory context: {e}")
```

Silently swallows ALL exceptions during memory loading. No structured logging, no observability.

### Finding 4.6: Hardcoded Dreamy Mode Path (line 612)

```python
read_file /mnt/skills/dreamy-workflow/SKILL.md
```

Should come from config like `container_base_path` on line 444.

### Finding 4.7: No `write_file` Guidance in Prompt

The working directory section (lines 315–335) mentions `present_file` and `read_file` but not `write_file`. The model learns about `write_file` only from tool descriptions. This likely caused the C2 `write_file` error (missing `description` parameter).

### Finding 4.8: No Web Search Retry Guidance

The `FETCH_POLICY_SECTION` (lines 337–345) tells the model to prefer short human-like search phrases but provides no guidance on:
- How many retries
- When to fall back to `recall` vs. training data
- How to report partial vs. failed results

### Finding 4.9: Cache Invalidation Config-Dependent

Cache key: `(agent_name, subagent_enabled, max_concurrent, skills_set, is_componentized, progressive_skills)`. Invalidated on mtime changes to `extensions_config.json`, `SOUL.md`, `config.yaml`, or date change. This is generally correct but misses the skills content hash — if a skill file changes without its container config changing, cache stays stale.

---

## 5. Memory `prompt.py` — Bloat & Efficiency

Source: `backend/src/agents/memory/prompt.py`

### Finding 5.1: `MEMORY_UPDATE_PROMPT` Is 119 Lines (~1,500 tokens)

Contains:
- Detailed section guidelines (workContext, personalContext, topOfMind — each with character/length specs)
- History section guidelines (recentMonths, earlierContext, longTermBackground)
- Fact extraction rules with 5 categories and confidence levels
- Output JSON schema with nested `shouldUpdate` flags
- Multilingual content handling

**Observation:** This is consumed by a *separate* LLM call (memory update), not the lead agent's context. It's reasonable for its purpose but worth monitoring if memory updates contribute to overall system latency.

### Finding 5.2: `format_memory_for_injection` (lines 200–312) Merges + Truncates

- Merges global + workspace memory scopes
- Token-counts with tiktoken and truncates to `max_tokens` (default 2000)
- Merged memory includes behavior rules, facts (vector-queried then sorted by confidence)
- Falls back to full fact list if vector store query fails

### Finding 5.3: Vector Store Query Uses Current Turn Text

Line 276-278: `get_memory_vector_store().query(query=current_turn_text, ...)`. The recall relevance depends entirely on how well `current_turn_text` captures the user's intent. For broad research prompts like "Ukraine war geopolitical brief", the vector query likely returns scattered results — explaining why C2 recall returned irrelevant items (Luke legal case, Iran war, Tasmania trip).

---

## 6. Related Prompt Surfaces — Key Findings

### 6.1 `todo_prompts.py` (~1,875 tokens)

- Injected into lead agent system prompt when plan mode is active
- Contains significant redundancy between system prompt and tool description
- Two parallel todo paths exist: DAG middleware (short prompt) and legacy flat-list (this file), based on `dag_enabled` config

### 6.2 `planner_middleware.py` (~450 tokens + variable plan content)

- **Strength:** Complexity classification fast-paths trivial requests
- **Problem:** Injects `HumanMessage(name="planner_handoff")` — synthetic message misclassified as user input. Agent may respond to the wrong "speaker."
- **Problem:** `clarification_prompt_message` also injected as `HumanMessage` — agent sees two synthetic human messages before first real user input.

### 6.3 `plan_evaluator_middleware.py` (~225 tokens)

- **Problem:** Semantic mismatch — passes `complexity_tier` as `domain` to the evaluator prompt. The prompt tells evaluator to check domain-specific rules but gets wrong data.
- **Problem:** If planner model is saturated (it's used by planner, plan evaluator, and web search summary middleware), the evaluator predictably times out.

### 6.4 `evaluator_middleware.py` (~50 tokens per call)

- **Problem:** Single-line prompt template with zero domain-specific criteria. PASS/FAIL is a coin flip per model/run.
- **Problem:** Synchronous blocking — `_evaluate_llm` runs synchronously inside `after_model`, blocking the middleware chain.
- **Problem:** Injecting feedback as `HumanMessage(name="evaluator_feedback")` means the user sees a failed response, then agent retries — no seamless correction.

### 6.5 `web_search_summary_middleware.py` (~112 tokens per call + response)

- **Strength:** Reduces search results from 10K+ chars to ~250 words — huge context savings
- **Problem:** Uses planner model, competing with planner + evaluator calls. In plan mode, same model called 3+ times sequentially (planner → evaluator → summarizer).

### 6.6 `search_masking.py` (~137 tokens per call)

- **Problem:** On failure, raises hard `ValueError` — entire web search blocked, no un-masked fallback
- **Problem:** LLM call overhead for trivial queries (e.g., "weather today") is disproportionate

### 6.7 Subagent Prompts (`general_purpose.py`, `bash_agent.py`)

- Both are concise (~175-200 tokens each) — well-sized
- `general_purpose.py`: No retry/fallback guidance for web search failures
- `bash_agent.py`: `max_turns=30` is generous — N concurrent subagents could each consume 30 turns

---

## 7. Failure Mode Analysis

### Failure A: Web Search 45s Timeouts (All Cycles)

**Manifestation:** `Tool web_search exceeded the 45s timeout and was cancelled.` — repeated 3-5× per cycle.

**Root cause:** Infrastructure. The web search tool consistently times out regardless of prompt content. Not a prompt problem, but the prompt should prepare the agent for this scenario.

**Prompt-addressable mitigation:**
- Add retry/fallback guidance: "If web_search times out, retry once with a shorter query. If it fails again, use `recall` to search the knowledge vault. If no results, state what you found from training data with uncertainty markers."
- This already happens somewhat (agent falls back gracefully), but the behavior is emergent, not instructed.

### Failure B: `asyncio` Semaphore Event Loop Error (Cycle 2 only)

**Manifestation:** `<asyncio.locks.Semaphore ...> is bound to a different event loop` — all 5 parallel subagent searches fail simultaneously.

**Root cause:** Backend bug — subagent event loop differs from HTTP client event loop. Not a prompt problem.

**Mitigation (prompt-level):** Limit concurrent `web_search` calls in subagent prompts to ≤3, reducing the chance of event loop collisions. But proper fix is in the backend.

### Failure C: `write_file` Missing `description` Parameter (Cycle 2)

**Manifestation:** `Error invoking tool 'write_file' with kwargs {'content': '...', description: Field required}`

**Root cause:** No prompt guidance on `write_file` requirements. The model guesses the parameters and omits `description`.

**Prompt fix:** Add a reminder to the synthesis/working-directory section: "When calling `write_file`, always include the `description` parameter first."

### Failure D: Subagent Task Re-dispatching

**Manifestation:** Identical subagent prompts for "front lines and battlefield dynamics" appear in logs 015, 020, 025, 028, 032 — 5 dispatches of the same task.

**Root cause:** Lead agent prompt and `SubagentLimitMiddleware` lack a "don't re-dispatch completed tasks" guard. When a subagent times out or returns partial results, the lead agent re-dispatches the same task.

**Prompt fix:** Add: "Do not re-dispatch a subagent task if a previous attempt for the same topic already ran. Use its results even if partial."

### Failure E: Irrelevant Recall Results

**Manifestation:** Vector recall returns Luke legal case, Iran war, and Tasmania trip for Ukraine war query.

**Root cause:** Vector similarity search on `current_turn_text` ("Research the current state of the Ukraine war...") against a memory store that contains mixed-domain content. The query tokens match random unrelated documents.

**Mitigation:** No easy prompt fix. Consider domain-scoped query rewriting or hybrid search (keyword + vector).

---

## 8. Prompt Size Budget Analysis

Estimated token consumption for a typical turn:

| Component | Tokens | Notes |
|---|---|---|
| Role + soul | ~50-200 | |
| Memory context | ~500-2000 | Variable, 2000 default max |
| Thinking style | ~176 | |
| Clarification section | ~322 | |
| **Subagent section** | **~1,829** | **#1 bloat target** |
| Skills catalog | ~500-2000 | Depends on skill count |
| Working directory | ~421 | |
| Fetch policy | ~182 | |
| Response style + citations | ~159 | |
| Critical reminders | ~313 | |
| Todo system prompt | ~1,875 | Plan mode only |
| Plan/Dreamy mode | ~400-700 | Mode-specific append |
| **Cached static total** | **~5,900-7,400** | Before mode/todo injection |
| **With plan mode** | **~8,175-9,575** | |
| **With todos** | **~10,050-11,450** | |

For a 32K-128K context model, this leaves adequate room for search results. But at 8K-15K tokens, memory + search summaries + conversation history can easily push past 32K for complex multi-turn research tasks.

### Savings if Subagent Section Is Slimmed:

Current: ~1,829 tokens → Target: ~300 tokens → **Savings: ~1,529 tokens (84%)**

This alone gives the model ~6,000 more characters of usable context for search results and reasoning.

---

## 9. Recommendations (Prioritized)

### P0 — Immediate Impact

1. **Slim subagent section** (`prompt.py:8-155`): Cut from ~1,829 to ~300 tokens. Drop code examples, reduce batching instructions. The middleware enforces hard limits.

2. **Eliminate `subagent_reminder` + `subagent_thinking` redundancy** (`prompt.py:526-540`): Save ~110 tokens of repeated text.

3. **Remove `LEGACY_SYSTEM_PROMPT_TEMPLATE`** (`prompt.py:158-270`): Dead code (~1,625 tokens) since `componentized` defaults to `True`.

4. **Add `write_file` guidance** to working directory section: "Always include `description` parameter."

5. **Add web search retry/fallback guidance** to fetch policy section.

### P1 — Quality of Life

6. **Replace `print()` with `logger.error()`** in `_get_memory_context` (`prompt.py:428`).

7. **Add warning log** in `_inject_memory_context` fallback (`prompt.py:576`).

8. **Replace hardcoded dreamy path** (`prompt.py:612`) with config-sourced path.

9. **Add deferred-queue awareness** to subagent prompt: check for `deferred_task_calls` state.

10. **Add re-dispatch guard** to lead agent prompt: "Do not re-dispatch a subagent task if a previous attempt for the same topic already ran."

### P2 — Architectural

11. **Fix `asyncio` event loop binding** in HTTP client — backend bug causing semaphore errors in parallel subagent searches.

12. **Limit concurrent `web_search` calls** to ≤3 per subagent to reduce event loop collision probability.

13. **Replace `evaluator_middleware.py` single-line prompt** with domain-aware evaluation criteria.

14. **Fix `plan_evaluator_middleware.py` semantic mismatch** — `complexity_tier` should not be passed as `domain`.

15. **Fix synthetic `HumanMessage` injection** — `planner_handoff`, `planner_clarification_required`, and `evaluator_feedback` should use a distinct message type or role.

---

## 10. Todo List

- [ ] Slim `_build_subagent_section` from ~1,829 to ~300 tokens (drop code examples, consolidate batching instructions)
- [ ] Remove `subagent_reminder` and `subagent_thinking` redundancy (or make conditional)
- [ ] Delete `LEGACY_SYSTEM_PROMPT_TEMPLATE` dead code (or add deprecation warning)
- [ ] Add `write_file` guidance to working directory section (always include `description`)
- [ ] Add web search retry/fallback guidance to fetch policy section
- [ ] Replace `print()` with `logger.error()` in `_get_memory_context` error path
- [ ] Add warning log in `_inject_memory_context` fallback (marker `\n<thinking_style>` not found)
- [ ] Replace hardcoded dreamy path with config-sourced path
- [ ] Add re-dispatch guard: "do not re-dispatch completed subagent tasks"
- [ ] Add deferred-queue awareness to subagent prompt
- [ ] Fix `asyncio` event loop binding in HTTP client (backend, not prompt)
- [ ] Limit concurrent `web_search` to ≤3 per subagent
- [ ] Replace `evaluator_middleware.py` single-line prompt with domain-aware criteria
- [ ] Fix `plan_evaluator_middleware.py` — stop passing `complexity_tier` as `domain`
- [ ] Stop injecting synthetic messages as `HumanMessage` type
