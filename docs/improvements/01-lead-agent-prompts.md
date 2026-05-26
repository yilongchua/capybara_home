# 01 — Lead Agent Prompts

Audit of every LLM-facing prompt in the lead agent and its directly attached prompt files (memory, todos, plan mode, dreamy mode).

## Inventory

| # | Identifier | File | Lines | Purpose | Approx. Length |
|---|------------|------|-------|---------|----------------|
| 1 | `LEGACY_SYSTEM_PROMPT_TEMPLATE` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L52-L167) | 52–167 | Monolithic system prompt used when componentized mode disabled | ~3,200 chars / ~550 tok |
| 2 | `ROLE_SECTION_TEMPLATE` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L170-L172) | 170–172 | Injects agent name into role declaration | ~80 chars |
| 3 | `THINKING_STYLE_SECTION_TEMPLATE` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L174-L181) | 174–181 | How the model should think before acting | ~300 chars |
| 4 | `CLARIFICATION_SECTION` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L183-L210) | 183–210 | Policy on when to ask vs. proceed | ~900 chars |
| 5 | `WORKING_DIRECTORY_SECTION` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L212-L236) | 212–236 | Virtual paths, mirrors, multi-file output | ~1,400 chars |
| 6 | `FETCH_POLICY_SECTION` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L238-L247) | 238–247 | When to use web search vs. vault vs. internal docs | ~500 chars |
| 7 | `RESPONSE_STYLE_SECTION` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L249-L253) | 249–253 | Response format / tone | ~200 chars |
| 8 | `CITATIONS_SECTION` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L255-L265) | 255–265 | Citation format after web search | ~400 chars |
| 9 | `CRITICAL_REMINDERS_SECTION_TEMPLATE` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L267-L278) | 267–278 | Last-mile reminders (skills, traceability, parallelism) | ~700 chars |
| 10 | `_build_subagent_section()` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L8-L49) | 8–49 | Builds `<subagent_system>` block | ~1,200 chars rendered |
| 11 | `DREAMY_MODE_SECTION` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L501-L530) | 501–530 | Dreamy mode batch execution rules | ~900 chars |
| 12 | `PLAN_MODE_SECTION` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L533-L596) | 533–596 | Plan-only behaviour | ~2,000 chars |
| 13 | `PLAN_BACKGROUND_FOLLOWUP_SECTION` | [backend/src/agents/lead_agent/prompt.py](../../backend/src/agents/lead_agent/prompt.py#L599-L608) | 599–608 | Background follow-up after plan delivered | ~400 chars |
| 14 | `MEMORY_UPDATE_PROMPT` | [backend/src/agents/memory/prompt.py](../../backend/src/agents/memory/prompt.py#L18-L123) | 18–123 | Extract user context / history / facts to persistent memory | ~2,400 chars |
| 15 | `FACT_EXTRACTION_PROMPT` | [backend/src/agents/memory/prompt.py](../../backend/src/agents/memory/prompt.py#L127-L151) | 127–151 | Per-message fact extraction | ~600 chars |
| 16 | `TODO_LIST_SYSTEM_PROMPT` | [backend/src/agents/lead_agent/todo_prompts.py](../../backend/src/agents/lead_agent/todo_prompts.py#L12-L45) | 12–45 | When/how to call `write_todos` | ~1,000 chars |
| 17 | `TODO_LIST_TOOL_DESCRIPTION` | [backend/src/agents/lead_agent/todo_prompts.py](../../backend/src/agents/lead_agent/todo_prompts.py#L49-L110) | 49–110 | Detailed tool description for `write_todos` | ~2,100 chars |

## Detailed findings & improvements

### 1. `LEGACY_SYSTEM_PROMPT_TEMPLATE` — lines 52–167

**Issues**
- Duplicates the componentized sections that follow (lines 170–278) — drift risk and two places to maintain.
- Mixes 11+ concerns (role, thinking, clarification, skills, subagents, file discipline, fetch policy, response, citations, reminders) in one block.
- `{subagent_thinking}` placeholder is never defined.
- "sensible attempt" left undefined; same with "directly required" file listing.
- "avoid over-formatting" contradicts the heavy XML scaffolding the prompt itself uses.

**Improvements**
- Decide on one source of truth (componentized) and delete the legacy template, or keep legacy as a thin wrapper that imports the sections.
- Define `{subagent_thinking}` or remove the placeholder.
- Replace "sensible attempt" with explicit criteria: *Has a reasonable default? → proceed. Missing info that blocks any sensible attempt? → ask.*
- Add 2–3 worked examples of when `ask_clarification` fires (destructive ops, ambiguous spec, hard-to-reverse defaults).
- Soften the formatting rule: "Use formatting only when it clarifies — prose by default."

### 2. `ROLE_SECTION_TEMPLATE` — lines 170–172

**Issues**
- "Open-source super agent" is vague and conveys no concrete capability.
- No anchor for personality/values.

**Improvements**
- Expand to: `You are {agent_name}, a {capability area} agent. You prioritise {core behaviour}.`
- If SOUL.md is loaded later, defer most personality content there and keep this minimal.

### 3. `THINKING_STYLE_SECTION_TEMPLATE` — lines 174–181

**Issues**
- Vague break-down methodology.
- The "do NOT write your full final answer in thinking" instruction conflicts with the way Sonnet/Opus extended thinking actually works — the thinking channel *is* the reasoning channel.
- `{subagent_thinking}` placeholder still undefined.

**Improvements**
- Give an explicit breakdown: (a) identify unknowns/dependencies, (b) propose a default, (c) check reversibility.
- Reconcile with extended thinking: "Use thinking for analysis. Make the final response concise — don't restate every thought."
- Define what `{subagent_thinking}` should inject (e.g., parallel-batch planning hint) or remove.

### 4. `CLARIFICATION_SECTION` — lines 183–210

**Issues**
- The JWT example is too trivial to illustrate the ambiguity threshold.
- The `ask_clarification(...)` example may drift from the real tool schema.
- "Never ask about stylistic or preference choices" is too broad — choice of *language* is technically a preference but materially changes the deliverable.
- Destructive-op list is short ("deleting files, dropping tables") and missing force-push, config overwrite, key revocation, service restart.

**Improvements**
- Replace JWT example with a richer one that shows defaulting + flagging: *"I'll default to session cookies (simpler, stateful). Tell me if you want JWT/OAuth instead."*
- Keep the example in sync with the actual `ask_clarification` schema; consider generating it from the tool definition.
- Distinguish *shape-affecting* choices (language/framework/structure) from *internal* choices (variable names, file layout).
- Expand the destructive-op checklist explicitly.

### 5. `WORKING_DIRECTORY_SECTION` — lines 212–236

**Issues**
- Dense; mirror discipline rules (`.docs` vs `.analyse` vs `.mounted`) are repeated and ordering-dependent.
- "Only list/read files directly required" conflicts with "except when executing explicit repository-wide indexing."
- No reference table for the virtual paths.
- Multi-file output heuristic ("prefer multiple well-named files") gives no split criteria.

**Improvements**
- Add a small reference table at the top:

  | Path | Purpose | Lifecycle |
  |------|---------|-----------|
  | `/mnt/user-data/uploads` | User uploads | Per-session |
  | `/mnt/user-data/workspace` | Scratch + output | Per-session |
  | `…/workspace/.docs` | Mirrored corpus | Mounted source |
  | `…/workspace/.analyse` | Derived analysis | Created by agent |

- Replace "directly required" with: *list/read files that contribute to completing the user's request; skip lockfiles, caches, and env artifacts (`node_modules`, `.venv`, `__pycache__`, `.git`).*
- State precedence: `.docs` canonical for analysis; fall back to `.mounted` only if `.docs` absent.
- Add a split heuristic: split when audiences differ, output >5 pages, or topics are distinct.

### 6. `FETCH_POLICY_SECTION` — lines 238–247

**Issues**
- "Minimum source needed" is undefined.
- Tool semantics (`web_search`, `query_knowledge_vault`, `search_internal_documents`) assumed known.
- "Plan Mode" referenced without definition here.
- No fallback when all fetches fail.

**Improvements**
- Define freshness tiers (must-be-fresh / should-be-fresh / nice-to-have).
- One-line semantics per tool inline.
- Add: *if 2 retries fail, state the limitation explicitly and proceed with best reasoning or decline.*

### 7. `RESPONSE_STYLE_SECTION` — lines 249–253

**Issues**
- "Avoid over-formatting" conflicts with the heavy XML structure in the rest of the prompt.
- "Action-oriented" is undefined.
- No length heuristic.

**Improvements**
- "Default to prose. Use lists/code blocks only when structure clarifies."
- Define action-oriented: *lead with what the user can do or what you've done; explain reasoning only when it affects next steps.*
- Add a length hint: short tasks → 1–3 short paragraphs; complex tasks → up to 5–10.

### 8. `CITATIONS_SECTION` — lines 255–265

**Issues**
- Only covers `web_search`; silent on memory, vault, and local docs.
- Example formatting is unclear about title-vs-link ordering.
- No de-duplication rule.
- Doesn't say when citations are *required* vs. nice-to-have.

**Improvements**
- Extend scope: cite web, vault, and any time-sensitive external source; skip training knowledge and general definitions.
- Show a canonical example and a fallback when title is missing.
- "List each unique source once per response."
- "Cite when claim is time-sensitive, proprietary, or contestable."

### 9. `CRITICAL_REMINDERS_SECTION_TEMPLATE` — lines 267–278

**Issues**
- Overuse of **CRITICAL** dilutes signal.
- "Complex tasks" is undefined for the skill-loading rule.
- Double-negative on traceability ("never claim … unless observed").
- Mermaid encouragement contradicts the earlier "avoid over-formatting".
- `{subagent_reminder}` placeholder undefined.

**Improvements**
- Reserve **CRITICAL** for one or two truly non-negotiable rules.
- Define complex tasks by trigger (code generation, multi-step research, data analysis).
- Rewrite traceability rule positively: *only mention tool execution details you have observed in this turn.*
- Move Mermaid into the response-style section as an optional technique.
- Define `{subagent_reminder}` content or remove.

### 10. `_build_subagent_section()` — lines 8–49

**Issues**
- "Naturally splits into 2+ tasks" is fuzzy.
- No failure handling (timeout, partial result).
- "3–5 concrete checks per prompt" appears arbitrary.
- `{n}` in the batching example is ambiguous (hard limit or suggestion?).
- Missing latency/overhead trade-off.

**Improvements**
- Add a small decision tree: independent streams? complex enough? expected >30s? → subagent.
- Show good vs. bad task split examples.
- Add failure handling: narrow scope and retry once; on second failure, synthesise partial.
- Note subagent overhead (~2–5s) so the model doesn't dispatch trivial work.

### 11. `DREAMY_MODE_SECTION` — lines 501–530

**Issues**
- Refers to `workflow.json`, `execution_state`, `current_row_index`, `current_step_id`, `phase` with no glossary.
- "NEVER call the `task()` tool" stated but not justified.
- "Inline" row processing left undefined.
- No path for user rejecting at `awaiting_approval`.

**Improvements**
- Add a 5-line glossary at the top of the section.
- Justify the `task()` prohibition (rows must remain observable / checkpointable).
- Define inline: tool calls + explanation within the same response, with checkpoint after each row.
- Specify `awaiting_approval` flow: emit `ask_clarification` of type `risk_confirmation` and freeze until user replies.

### 12. `PLAN_MODE_SECTION` — lines 533–596

**Issues**
- "Suppress" your knowledge instruction is unclear — better to say "do not output the answer body."
- Same rule stated twice (lines 552 and 559).
- `scope_search` usage line contradicts the surrounding "no content gathering" rule.
- `<planner_handoff>` is a tag, not a runtime signal — explain how the model detects mode change.
- Two artifact paths (`plan.md` + timestamped `plans/plan-*.md`) with no rationale.

**Improvements**
- Single rule: *Plan Mode produces HOW (steps, scope, sources to check), not WHAT (the answer).*  Give a good vs. bad example.
- Define `scope_search` strictly as scope discovery (unknown vocabulary, unfamiliar domains).
- Replace `<planner_handoff>` reference with the actual runtime trigger ("Execute Plan" / mode-switch event).
- Document the artifact split: `plan.md` = live; `plans/plan-*.md` = audit trail; never edit timestamped copies.

### 13. `PLAN_BACKGROUND_FOLLOWUP_SECTION` — lines 599–608

**Issues**
- "Meaningful improvement" undefined.
- No iteration ceiling.
- Unclear whether the background pass may refine the plan or only enrich the answer.

**Improvements**
- Define value-add hierarchy: fill source gaps → cross-validate → deepen detail.
- Hard cap at a single pass; note major plan gaps separately rather than restructuring.

### 14. `MEMORY_UPDATE_PROMPT` — memory/prompt.py lines 18–123

**Issues**
- The User Context vs. History distinction is implicit.
- Length guidelines mix units (sentences vs. paragraphs).
- Confidence tier rationale is missing.
- Contradiction detection rules are absent.
- File-upload caveat (lines 119–121) is critical but buried.
- "Durable context" undefined.
- No format spec for fact IDs.

**Improvements**
- Lead with a one-line distinction between *User Context* (now) and *History* (past).
- Use character counts instead of mixed sentence/paragraph caps.
- Justify confidence tiers with concrete signals (explicit statement / inferred from action / fuzzy pattern).
- Add contradiction-detection rules (explicit negation, supersession, quantifiable conflict).
- Move file-upload caveat to the top under "Important Rules."
- Define durable vs. stale.
- Specify ID format (hash or UUID; stable across updates).

### 15. `FACT_EXTRACTION_PROMPT` — memory/prompt.py lines 127–151

**Issues**
- Categories lack examples.
- "Clear" and "specific" undefined.
- No dedup rule, no scope rule.

**Improvements**
- Add one example per category (preference, knowledge, context, behaviour, goal).
- Define clear = unambiguous in isolation; specific = named entity / quantified / domain-specific.
- Restrict scope to this single message.

### 16. `TODO_LIST_SYSTEM_PROMPT` — todo_prompts.py lines 12–45

**Issues**
- Inconsistent "<3 steps" boundary (3 steps in or out?).
- "REAL-TIME" undefined.
- Only `in_progress` / `completed` states mentioned; blocked/skipped omitted.
- Token cost left vague.

**Improvements**
- Use ≥3 explicitly.
- Define real-time as: update after each task completion or new blocker discovery; not after every tool call.
- Add `blocked` and `skipped` states.
- Quantify cost (`~50–100 tokens per update`) and give a cost/benefit rule.

### 17. `TODO_LIST_TOOL_DESCRIPTION` — todo_prompts.py lines 49–110

**Issues**
- Heavy overlap with `TODO_LIST_SYSTEM_PROMPT` — same rules in two places.
- Field schema (required vs. optional) not stated.
- "Multiple in_progress when running in parallel" then "always at least one in_progress" is borderline contradictory.

**Improvements**
- Extract shared content to a single constant referenced by both.
- Add explicit JSON-Schema-style field summary at the top.
- Reconcile parallel-in-progress rule: allow multiple in_progress only when tasks are truly independent; require ≥1 in_progress whenever pending tasks remain.

## Cross-cutting notes

- **Placeholders without definitions**: `{subagent_thinking}`, `{subagent_reminder}`, `{n}` (in subagent batching example). Audit-trail these across the codebase.
- **Redundancy with componentized sections**: Most legacy/component duplication can be removed.
- **Contradictions**: "avoid over-formatting" vs. Mermaid encouragement; "suppress your knowledge" in Plan Mode vs. extended thinking semantics.
- **Missing failure modes**: web search failure, subagent timeout, ask_clarification rejection — none have specified fallbacks.
- **Vague thresholds**: "complex," "natural split," "durable," "stale," "low-value," "meaningful improvement" — each should get an explicit signal.
