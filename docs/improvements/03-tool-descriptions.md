# 03 — Tool Descriptions

Audit of every built-in tool's LLM-facing description and parameter schema.

## Inventory

| # | Tool name | File | Lines | Primary use | Severity |
|---|-----------|------|-------|-------------|----------|
| 1 | `ask_clarification` | [backend/src/tools/builtins/clarification_tool.py](../../backend/src/tools/builtins/clarification_tool.py#L14-L64) | 14–64 | Ask the user a question before proceeding | Medium |
| 2 | `present_files` | [backend/src/tools/builtins/present_file_tool.py](../../backend/src/tools/builtins/present_file_tool.py#L62-L100) | 62–100 | Surface files to the user in the client | Medium |
| 3 | `recall` | [backend/src/tools/builtins/recall_tool.py](../../backend/src/tools/builtins/recall_tool.py#L15-L62) | 15–62 | Search long-term memory | High |
| 4 | `setup_agent` | [backend/src/tools/builtins/setup_agent_tool.py](../../backend/src/tools/builtins/setup_agent_tool.py#L14-L62) | 14–62 | Configure a custom CapyHome agent | High |
| 5 | `task` | [backend/src/tools/builtins/task_tool.py](../../backend/src/tools/builtins/task_tool.py#L228-L274) | 228–274 | Delegate a task to a subagent | Medium |
| 6 | `view_image` | [backend/src/tools/builtins/view_image_tool.py](../../backend/src/tools/builtins/view_image_tool.py#L15-L94) | 15–94 | Load an image into the model's view | Medium |
| 7 | `write_todos` | [backend/src/tools/builtins/write_todos_tool.py](../../backend/src/tools/builtins/write_todos_tool.py#L186-L197) | 186–197 | Create/update structured todo list | High |

## Detailed findings

### 1. `ask_clarification` — lines 14–64

**Issues**
- "Wait for the user's response before continuing" implies sync behaviour; the tool actually returns immediately and execution is interrupted via middleware.
- Duplicated "When to use" sections.
- `ClarificationOption` schema mentions `recommended` but doesn't explain its effect on the UI.
- No documented return value.

**Improvements**
- Replace "Wait for…" with: *Execution is interrupted by middleware; control returns once the user responds.*
- Collapse the duplicated bullet lists into one.
- Document `ClarificationOption` fields explicitly:
  ```
  label: short string shown to user
  description: optional supporting text
  recommended: bool — marks the suggested choice; UI highlights it
  ```
- Document the tool's return shape (interrupt token / Command pattern).

### 2. `present_files` — lines 62–100

**Issues**
- Workspace-only constraint buried in the `Args:` block.
- Supported file types unspecified.
- Implementation details ("safe to call in parallel", reducers) leak into the description.

**Improvements**
- Move the workspace constraint to the first line of the description.
- List supported types explicitly: PDF, MD, CSV/XLSX, images (PNG/JPG/SVG), code text.
- Drop reducer/parallelism implementation notes; keep the LLM-facing description focused on *when* and *what*.
- Add a one-line example: `present_files(["report.md", "results.csv", "chart.png"])`.

### 3. `recall` — lines 15–62

**Issues**
- Description is three sentences with no examples.
- No mention of which scopes are searched (workspace vs. global).
- No description of returned JSON shape (id, scope, content, category, confidence, score, source).
- Silent on what happens when memory is disabled / no results.

**Improvements**
- Expand to a paragraph with two example queries.
- State: *Searches both workspace and global memory scopes. Returns an empty list when no facts cross the relevance threshold.*
- Document the returned shape inline.
- Suggest query phrasing: short factual phrases work better than full questions.

### 4. `setup_agent` — lines 14–62

**Issues**
- Description is one line ("Setup the custom CapyHome agent").
- `soul` parameter has no schema or example.
- No description of what changes on disk and which agent name is used.
- No error-handling guidance.

**Improvements**
- Expand description: *Create or replace a custom CapyHome agent with a SOUL.md personality and a short summary description.*
- Document SOUL.md sections (Personality, Goals, Tool restrictions, Style).
- State: *Calling again with the same name updates the existing agent.*
- Add length constraints to `description`: keep under 100 chars.
- Show a minimal example.

### 5. `task` — lines 228–274

**Issues**
- ALL-CAPS "ALWAYS PROVIDE THIS PARAMETER FIRST/SECOND/THIRD" is unusual and unenforced.
- 3–5 word `description` constraint has no example.
- The list of subagent types doesn't communicate per-agent turn budgets or scope quirks.
- `source-researcher` rewrites broad prompts into narrow objectives — this isn't documented.
- Verbose-output handling and the 20k-token truncation are not surfaced to the model.

**Improvements**
- Remove caps lock; rely on parameter order in the schema.
- Add `description` example: `"Research async patterns"`.
- For each subagent type, add a one-line scope reminder + default `max_turns`.
- Add: *`source-researcher` automatically narrows broad prompts to a single objective — split work yourself if you want N parallel investigations.*
- Mention output truncation: *if a subagent's response exceeds ~20k tokens it is truncated; structure your delegation so the result fits.*

### 6. `view_image` — lines 15–94

**Issues**
- Extremely terse description.
- Circular phrasing ("Use to view when you need to view").
- "Common formats supported" instead of an explicit list.
- No path-format guidance (virtual paths vs. absolute).
- No size/encoding warning.

**Improvements**
- Open with: *Load an image into the model's vision channel so it can be analysed.*
- Explicit format list: `.jpg`, `.jpeg`, `.png`, `.webp`.
- State accepted path patterns and recommend `/mnt/user-data/workspace/...`.
- Add a soft size hint (best <10 MB).
- Sharpen the contrast with `present_files`: *`view_image` is for the model to see; `present_files` is for the user to see.*

### 7. `write_todos` — lines 186–197

**Issues**
- One-line description ("Create and update todo items, including dependency-aware DAG fields") is cryptic; "DAG" is jargon to the LLM.
- `TodoNodeInput` schema isn't surfaced in the description.
- Patch-by-id semantics not explained.
- Plan-mode validation rules (draft plans can't mark completed, completed plans are frozen) are invisible to the model.
- Error codes (`draft_completion_blocked`, `completed_plan_frozen`, `validation_failed`) not documented.

**Improvements**
- Replace the one-liner with a paragraph that names the lifecycle and dependency model:
  ```
  Create or update structured todo items. Items pass through pending → in_progress → completed/blocked.
  Items can declare dependencies via depends_on; downstream items remain blocked until their dependencies complete.
  ```
- Inline the schema:
  ```
  id              optional, auto-generated if omitted; reuse to patch
  content         required, short imperative description
  status          pending | in_progress | completed | blocked
  depends_on      optional list of todo IDs
  owner           lead | subagent
  subagent_type   set when owner=subagent
  target_endpoint primary | helper
  tool_budget     optional int
  ```
- Document plan-mode constraints up front (draft plans accept pending/in_progress/blocked only).
- List the error codes the tool returns.

## Cross-cutting observations

- **Length asymmetry**: `recall`, `setup_agent`, `write_todos` are critically under-described; `task` is over-emphatic with caps lock. Aim for one paragraph that names *what*, *when*, *when not*, *parameters*, *return shape*.
- **Return-value documentation** is missing on every tool. Add a `Returns:` line.
- **Example calls** missing on every tool. One realistic example per tool dramatically improves routing.
- **Implementation leakage**: `present_files` and `view_image` describe parallel-call safety and reducers — these are runtime concerns, not LLM-facing concerns. Move them to docstrings or developer comments.
- **Plan-mode-specific behaviour** of `write_todos` must be exposed to the model — the tool currently fails silently for the LLM if it doesn't know the rule.
