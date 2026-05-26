# 04 — Middleware Prompts

Audit of every LLM-facing prompt owned by a middleware module. Middleware that only intercepts tool calls or injects static reminders is listed at the bottom for completeness.

## Inventory

| # | Identifier | File | Lines | Purpose | Severity |
|---|------------|------|-------|---------|----------|
| 1 | `PLANNER_SYSTEM_PROMPT` | [backend/src/agents/middlewares/planner_middleware.py](../../backend/src/agents/middlewares/planner_middleware.py#L203-L332) | 203–332 | Produce structured execution plan (JSON) with todos / clarifications / dependencies | High |
| 2 | `_EVALUATOR_SYSTEM_PROMPT` | [backend/src/agents/middlewares/recursion_pivot_middleware.py](../../backend/src/agents/middlewares/recursion_pivot_middleware.py#L34-L47) | 34–47 | KEEP / PIVOT decision near recursion limit | Medium |
| 3 | `_PLAN_EVAL_PROMPT` | [backend/src/agents/middlewares/plan_evaluator_middleware.py](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L34-L63) | 34–63 | Structural review of a generated plan | Medium |
| 4 | `_EVALUATOR_PROMPT_TEMPLATE` | [backend/src/agents/middlewares/evaluator_middleware.py](../../backend/src/agents/middlewares/evaluator_middleware.py#L19-L32) | 19–32 | Verify Plan Mode terminal response (artifacts present) | Medium |
| 5 | `DEFAULT_SUMMARY_PROMPT` | [backend/src/agents/middlewares/summarization_middleware.py](../../backend/src/agents/middlewares/summarization_middleware.py#L68-L98) | 68–98 | Compact conversation summary for context continuation | Medium |
| 6 | `_SUMMARY_PROMPT_TEMPLATE` | [backend/src/agents/middlewares/web_search_summary_middleware.py](../../backend/src/agents/middlewares/web_search_summary_middleware.py#L37-L48) | 37–48 | Summarise large web search results | Medium |
| 7 | Step-inference prompt (inline) | [backend/src/agents/middlewares/dreamy_bootstrap_middleware.py](../../backend/src/agents/middlewares/dreamy_bootstrap_middleware.py#L378-L397) | 378–397 | Infer per-row processing steps from a table schema | Medium |
| 8 | (loaded from config) | [backend/src/agents/middlewares/question_generation_middleware.py](../../backend/src/agents/middlewares/question_generation_middleware.py#L99-L113) | 99–113 | Follow-up question generation; template lives in `config/question_generation_config.py` | Low |
| 9 | (loaded from config) | [backend/src/agents/middlewares/title_middleware.py](../../backend/src/agents/middlewares/title_middleware.py#L106-L110) | 106–110 | Thread title generation; template lives in `config/title_config.py` | Low |

## Detailed findings

### 1. `PLANNER_SYSTEM_PROMPT` — planner_middleware.py 203–332

**Issues**
- `{max_steps}` / `{max_clarifications}` placeholders are substituted via `str.replace` (around line 785) — a user input that contains the literal placeholder leaks through.
- Dense JSON schema embedded as prose; sections "TRIVIAL SIGNAL", "DEPENDENCY RULES", "CLARIFICATION RULES", "TODO STYLE", "RICH EXECUTION FIELDS" share visual weight despite different criticality.
- Only one example (the trivial path) — no end-to-end non-trivial example.
- `completion_requirement` format is illustrated only loosely (e.g. "file exists with >= 10 entries").
- Optional fields (`steps`, `subagent_types`, `tools`) are presented inline with required ones with no explicit "OPTIONAL" markers.

**Improvements**
- Use a templating library or `format_map` with sanitisation so user content can't collide with placeholders.
- Re-order: required output first, then optional enrichments, then rules, then examples.
- Add 1 worked example for a non-trivial plan (e.g. multi-source research with synthesis).
- Tighten `completion_requirement` with regex-like patterns: `"path:<glob> exists"`, `"row_count(<table>) >= <N>"`, `"section:<name> present"`.
- Tag every optional field with `// optional` in the schema.
- Add a hard rule: *Do not generate `steps` for plans flagged trivial.*

### 2. `_EVALUATOR_SYSTEM_PROMPT` — recursion_pivot_middleware.py 34–47

**Issues**
- KEEP/PIVOT binary — no middle ground for "narrow scope".
- "Stuck" and "slow progress" undefined.
- Output is short (`DECISION/DIRECTIVE/REASON`) but DIRECTIVE has no length cap or example.

**Improvements**
- Define "stuck": *same tool with similar args called ≥3 times, results unchanged.*
- Default to KEEP when uncertain (avoid disrupting mid-run work).
- Cap DIRECTIVE: *one sentence, ≤100 words.*
- Add a third value `NARROW` for scope-reduction directives.
- Concrete examples:
  - KEEP — agent making steady progress, just slow.
  - PIVOT — agent retried same query 3× with same empty result.
  - NARROW — agent attempting whole-task too aggressively, instruct to focus on first deliverable.

### 3. `_PLAN_EVAL_PROMPT` — plan_evaluator_middleware.py 34–63

**Issues**
- Output schema mentions `revised_todos` but doesn't show its structure.
- "Lenient — only flag genuine blockers" is unanchored.
- Coverage of common plan defects is incomplete (no check for missing setup todos, no realism check on time/scope).

**Improvements**
- Include a concrete example of `revised_todos` matching the planner's todo schema.
- Define genuine blocker: *circular dependency, synthesis with no inputs, completion gate that no preceding todo can satisfy.*
- Add 2 domain-specific checks:
  - Research domain: synthesis must depend on at least one research todo.
  - Code domain: tests/verification todo must follow implementation todo.
- Spell out: *return `revised_todos: null` when the issues cannot be resolved by patching todos.*

### 4. `_EVALUATOR_PROMPT_TEMPLATE` — evaluator_middleware.py 19–32

**Issues**
- Hard-codes `/mnt/user-data/workspace/plan.md` and `/mnt/user-data/workspace/plans/plan-*.md`.
- "Stale" undefined.
- "Substantive" response criterion undefined.

**Improvements**
- Inject paths via template variable `{plan_paths}` so the middleware controls them.
- Define stale: *file timestamp older than the last plan-status transition.*
- Define substantive: *response references the plan deliverable(s) and acknowledges any open items.*
- Add explicit pass/fail examples.

### 5. `DEFAULT_SUMMARY_PROMPT` — summarization_middleware.py 68–98

**Issues**
- "Drop low-value intermediate reasoning" is subjective.
- 300-word hard cap with no pruning guidance when content exceeds it.
- Doesn't say what to do when conversation is empty or tiny.

**Improvements**
- Define low-value as: *acknowledgements, false starts, tool-choice meta-reasoning, retries that didn't change state.*
- Pruning order when over budget: drop Files & Code first, then Open Items, then Goal as last resort.
- Empty/short conversation rule: *return `No prior context.` literally.*
- State the message format explicitly: *messages are `[user]` / `[assistant]` labelled.*

### 6. `_SUMMARY_PROMPT_TEMPLATE` — web_search_summary_middleware.py 37–48

**Issues**
- "Key information" undefined.
- No rule for contradictory sources.
- No citation format inside the summary.

**Improvements**
- Define key information: *data points, dates, names, prices, claims with verifiable evidence.*
- Contradiction rule: *if sources conflict, present both with attribution; do not silently pick one.*
- Citation rule inside summary: *append `(source URL)` after the relevant sentence.*
- Length: aim for 150–250 words, 250 hard cap.
- Add a fallback: *if results contain no substantive information, output a 1–2 sentence summary saying so.*

### 7. Dreamy step-inference prompt — dreamy_bootstrap_middleware.py 378–397

**Issues**
- Lists allowed `action` values including `conditional`, but downstream pipeline doesn't currently handle it.
- No worked example of a valid steps array.
- `tool` field allowed values not stated.

**Improvements**
- Restrict `action` to the values actually supported (`tool_call`, `write_row`); remove `conditional` until implemented.
- Constrain `tool` to `"bash"` and state this explicitly.
- Add an example:
  ```json
  [
    {"id": "s1", "action": "tool_call", "tool": "bash", "description": "Fetch row data", "input_fields": ["url"], "output_fields": ["raw"], "on_no_result": "skip"},
    {"id": "s2", "action": "write_row", "description": "Persist results", "input_fields": ["raw"], "output_fields": []}
  ]
  ```
- Define `on_no_result` enum: `skip`, `fail`, `mark_empty`.

### 8. Question-generation prompt — loaded from `config/question_generation_config.py`

**Action**
- Open `backend/src/config/question_generation_config.py` and audit the template directly.
- Confirm it includes:
  - "Generate exactly `{count}` questions"
  - "Each question advances or extends the assistant response"
  - "Return one question per line, no numbering/bullets"
- The middleware truncates messages to `max_response_chars` (line 106–107); document this in the template so the model knows context may be cut.

### 9. Title-generation prompt — loaded from `config/title_config.py`

**Action**
- Audit `backend/src/config/title_config.py` template.
- Ensure it covers:
  - "≤ `{max_words}` words"
  - "Return only the title text — no quotes, no emoji, no surrounding punctuation"
  - "Dreamy threads receive a `✨` prefix automatically; do not add one yourself"
- The middleware truncates messages to 500 chars (lines 108–109); note this in the template.

## Middleware that calls no model

These were checked and contain no LLM-facing prompts. Included here so future audits don't re-investigate them:

| Middleware | File | Why no prompt |
|------------|------|---------------|
| `clarification_middleware` | [backend/src/agents/middlewares/clarification_middleware.py](../../backend/src/agents/middlewares/clarification_middleware.py) | Pure tool-call interception |
| `dreamy_intent_middleware` | [backend/src/agents/middlewares/dreamy_intent_middleware.py](../../backend/src/agents/middlewares/dreamy_intent_middleware.py) | Heuristic intent detection |
| `dreamy_poc_middleware` | [backend/src/agents/middlewares/dreamy_poc_middleware.py](../../backend/src/agents/middlewares/dreamy_poc_middleware.py) | Injects static system reminders |
| `dreamy_execution_middleware` | [backend/src/agents/middlewares/dreamy_execution_middleware.py](../../backend/src/agents/middlewares/dreamy_execution_middleware.py) | Spawns Python executor, status reminders |
| `autoresearch_middleware` | [backend/src/agents/middlewares/autoresearch_middleware.py](../../backend/src/agents/middlewares/autoresearch_middleware.py) | Delegates to `control_plane/autoresearch_loop/` (audit prompts there) |
| `skill_disclosure_middleware` | [backend/src/agents/middlewares/skill_disclosure_middleware.py](../../backend/src/agents/middlewares/skill_disclosure_middleware.py) | Injects skill bodies as messages |
| `tool_disclosure_middleware` | [backend/src/agents/middlewares/tool_disclosure_middleware.py](../../backend/src/agents/middlewares/tool_disclosure_middleware.py) | Phase-based tool gating |
| `progress_guard_middleware` | [backend/src/agents/middlewares/progress_guard_middleware.py](../../backend/src/agents/middlewares/progress_guard_middleware.py) | Heuristic stall detection |
| `loop_detection_middleware` | [backend/src/agents/middlewares/loop_detection_middleware.py](../../backend/src/agents/middlewares/loop_detection_middleware.py) | Static warning injection |
| `work_mode_middleware` | [backend/src/agents/middlewares/work_mode_middleware.py](../../backend/src/agents/middlewares/work_mode_middleware.py) | Templated instructions (not LLM-generated) |

## Cross-cutting notes

- **Injection risk** in `planner_middleware`: switch from `str.replace` to `string.Template` with safe substitution or `format_map`.
- **Config-resident templates** (`question_generation`, `title`) are out of reach of this audit pass — add them to a follow-up sweep covering `backend/src/config/*_config.py`.
- **Undefined adjectives** recur: "stuck", "stale", "substantive", "low-value", "key information", "genuine blocker". Each should grow a one-line signal.
- **Missing examples**: every middleware prompt that returns structured output (JSON, enum verdicts) would benefit from one positive and one negative example.
- **Hard-coded paths** in `evaluator_middleware` should become injected template variables.
- **Pruning rules** missing whenever the model is asked to fit content into a token/word cap (summarization, web summary).
