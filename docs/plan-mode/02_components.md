# 02 — Component Inventory

Every concrete piece of code that participates in a Plan Mode turn, grouped
by category.

## 1. LangGraph entry points

| Graph id | Factory | File |
|---|---|---|
| `plan_agent` | `make_plan_agent` | [backend/src/agents/plan_agent/agent.py:29](../../backend/src/agents/plan_agent/agent.py#L29) |
| `work_agent` | `make_work_agent` | [backend/src/agents/work_agent/agent.py:705](../../backend/src/agents/work_agent/agent.py#L705) |

Registered in [backend/langgraph.json](../../backend/langgraph.json). Both
delegate to the shared `_build_work_agent(config, prompt_template_fn=…)`
builder; `make_plan_agent` injects the plan-mode prompt template and forces
`current_mode="plan"`.

## 2. Mode resolution

| Symbol | File | Role |
|---|---|---|
| `resolve_current_mode(cfg)` | [common/mode.py:38](../../backend/src/agents/common/mode.py#L38) | Reads `current_mode` (canonical) → `mode` (legacy alias) → `is_plan_mode` (legacy bool); returns `"work"` or `"plan"`. |
| `normalize_runtime_mode(raw)` | [common/mode.py:17](../../backend/src/agents/common/mode.py#L17) | Validates a raw mode string; rejects legacy aliases `pro`/`fast`. |

Every middleware reads mode through these helpers, never raw config.

## 3. Prompts

| Prompt asset | File | Role |
|---|---|---|
| `PLAN_MODE_SECTION` | [plan_agent/prompt.py:18](../../backend/src/agents/plan_agent/prompt.py#L18) | Plan-mode discipline appended to the base work prompt. |
| `PLAN_BACKGROUND_FOLLOWUP_SECTION` | [plan_agent/prompt.py:92](../../backend/src/agents/plan_agent/prompt.py#L92) | Extra overlay when the run is a background follow-up. |
| `apply_prompt_template(...)` (plan) | [plan_agent/prompt.py:104](../../backend/src/agents/plan_agent/prompt.py#L104) | Composes work base + PLAN_MODE_SECTION. |
| `apply_prompt_template(...)` (work) | [work_agent/prompt.py](../../backend/src/agents/work_agent/prompt.py) | Base prompt (working directory, fetch policy, skill catalog, etc.). |
| `PLANNER_SYSTEM_PROMPT` | [planner_middleware.py:204](../../backend/src/agents/middlewares/planner_middleware.py#L204) | The JSON-only contract that the **planner LLM** (a sub-LLM call) follows when producing structured plan output. |
| `_PLAN_EVAL_PROMPT` | [plan_evaluator_middleware.py:34](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L34) | Reviewer prompt for the optional plan-quality LLM check. |
| `_CLASSIFIER_PROMPT_TEMPLATE` | [plan_execution_gate_middleware.py:107](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L107) | One-shot scope-vs-content classifier (used when the LLM tries a search tool in plan mode). |

## 4. Plan-mode-only middlewares

These middlewares are conditionally constructed via `_create_*(ctx)` factory
functions in [work_agent/agent.py:301-456](../../backend/src/agents/work_agent/agent.py#L301-L456),
each checking `ctx.is_plan_mode`.

| Middleware | File | Activation | Responsibility |
|---|---|---|---|
| `PlannerMiddleware` | [planner_middleware.py:660](../../backend/src/agents/middlewares/planner_middleware.py#L660) | `is_plan_mode AND planner.enabled` | Calls the planner LLM once per eligible turn; produces structured plan + `plan.md`; emits `plan_created` SSE; supports in-place re-planning capped at `_MAX_DRAFT_REVISIONS = 5` ([planner_middleware.py:731](../../backend/src/agents/middlewares/planner_middleware.py#L731)). |
| `PlanEvaluatorMiddleware` | [plan_evaluator_middleware.py:330](../../backend/src/agents/middlewares/plan_evaluator_middleware.py#L330) | `is_plan_mode AND planner.enabled` | Fast LLM quality check on planner output (timeout-bounded); may revise the todo graph. |
| `TodoDagMiddleware` | [todo_dag_middleware.py](../../backend/src/agents/middlewares/todo_dag_middleware.py) | `is_plan_mode AND todos.dag_enabled` | Normalises todo nodes into a DAG; surfaces `ready_ids` for the work loop. |
| `TodoMiddleware` (fallback) | [todo_middleware.py](../../backend/src/agents/middlewares/todo_middleware.py) | `is_plan_mode AND not dag_enabled` | Legacy flat-list todo tracking. |
| `EvaluatorMiddleware` | [evaluator_middleware.py](../../backend/src/agents/middlewares/evaluator_middleware.py) | `is_plan_mode AND evaluator.enabled` | Final-attempt verifier (mainly relevant to plan-mode loops). |

## 5. Always-on middlewares that *adapt* to plan mode

| Middleware | File | Plan-mode behaviour |
|---|---|---|
| `PhaseToolFilterMiddleware` | [phase_tool_filter_middleware.py:102](../../backend/src/agents/middlewares/phase_tool_filter_middleware.py#L102) | **Not built in Plan Mode** (deprecated as a plan-mode filter — see Section 6). In Work Mode its only remaining job is a first-turn execution-tool gate: when no plan exists and no prior AI message, execution tools are hidden so the LLM has to reason before acting. From turn 2 onward the full Work catalog is exposed. |
| `PlanExecutionGateMiddleware` | [plan_execution_gate_middleware.py:119](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L119) | Runtime backstop: blocks execution tools at `wrap_tool_call` time if a custom agent re-exposes them; runs an LLM scope-vs-content classifier on `web_search` etc. and blocks "content" verdicts before plan approval. |
| `WorkModeMiddleware` | [work_mode_middleware.py:93](../../backend/src/agents/middlewares/work_mode_middleware.py#L93) | Only constructed when `is_work_mode`. Does **not** spawn Plan Mode re-runs anymore — auto-escalation (`_spawn_plan_rerun` / `_MAX_AUTO_ADAPTATION_ATTEMPTS`) was removed. When a plan stalls (no ready todos but pending ones remain), [`_handle_plan_adapted`](../../backend/src/agents/middlewares/work_mode_middleware.py#L463) emits a `plan_adapted` SSE event so the UI can prompt the user to switch back to Plan Mode; the user decides. |
| `PlanFileSyncMiddleware` | [plan_file_sync_middleware.py:52](../../backend/src/agents/middlewares/plan_file_sync_middleware.py#L52) | After model in any mode, refreshes `plan.md` and its versioned alias in a background daemon thread. |
| `SummarizationMiddleware` | [summarization_middleware.py](../../backend/src/agents/middlewares/summarization_middleware.py) | Uses the `"plan"` mode override for trigger/keep thresholds via `_create_summarization_middleware(mode=mode)` ([work_agent/agent.py:207](../../backend/src/agents/work_agent/agent.py#L207)). |
| `SkillDisclosureMiddleware` | [skill_disclosure_middleware.py](../../backend/src/agents/middlewares/skill_disclosure_middleware.py) | Injects active skill bodies regardless of mode; ordering ensures the planner sees the skill catalog. |
| `ClarificationMiddleware` | [clarification_middleware.py](../../backend/src/agents/middlewares/clarification_middleware.py) | Intercepts `ask_user_for_clarification` calls; routes via `Command(goto=END)` to interrupt the run. |

## 6. Plan-mode tool catalog (what the LLM sees)

The tool catalog is now **resolved up-front at agent build time**, not at
runtime via middleware. `make_plan_agent` and `make_work_agent` are
different LangGraph graphs; `get_available_tools(mode=...)` in
[tools/tools.py](../../backend/src/tools/tools.py) picks the appropriate
per-mode catalog JSON. Plan-status transitions (`draft` → `approved`) are
inter-graph (`plan_agent` terminates, `work_agent` spawns), so no runtime
mode/phase filter is needed.

| Catalog file | Served when | Excludes |
|---|---|---|
| [`internal_tools_plan.json`](../../backend/src/tools/internal_tools_plan.json) | `mode=plan` | Execution tools: `bash`, `write_file`, `str_replace`, `task`. Descriptions framed for drafting / information gathering. |
| [`internal_tools_work.json`](../../backend/src/tools/internal_tools_work.json) | `mode=work` (and default when unset) | Nothing — full execution surface. |
| [`external_tools.json`](../../backend/src/tools/external_tools.json) | both | Policy-only entries for MCP / CLI bridges. |

Community tools (no JSON catalog entry) are mode-scoped at load time by
`_COMMUNITY_TOOL_MODES` in [tools/tools.py](../../backend/src/tools/tools.py):

- `web_search` — available in **all** modes (exposed directly in Plan
  Mode; the legacy `scope_search` wrapper is deprecated).
- `query_knowledge_vault`, `save_to_knowledge_vault` — **work-only**.

Typical Plan-Mode tool surface (resolved from `internal_tools_plan.json` +
community scoping):

| Tool | Source | Why it's allowed in plan mode |
|---|---|---|
| `write_todos` | [tools/builtins/write_todos_tool.py](../../backend/src/tools/builtins/write_todos_tool.py) | Plan authoring — agent manipulates the todo list directly. |
| `ask_user_for_clarification` | `src/tools/builtins/ask_user_for_clarification.py` | Plan-time scope-narrowing. Intercepted to suspend the run. |
| `web_search` | `src/community/web_search/` | Scope-discovery research. The plan-mode prompt still names `scope_search` conceptually, but the registered handler is `web_search` (the wrapper is deprecated). |
| `recall` | [tools/builtins/recall_tool.py](../../backend/src/tools/builtins/recall_tool.py) | Read-only memory lookup. |
| `ls`, `read_file`, `view_image` | sandbox + builtins | Read-only investigation. |
| `present_files` | [tools/builtins/present_files_tool.py](../../backend/src/tools/builtins/present_files_tool.py) | Surface `plan.md` to the user. |

`PlanExecutionGateMiddleware` ([plan_execution_gate_middleware.py:119](../../backend/src/agents/middlewares/plan_execution_gate_middleware.py#L119))
remains as a **runtime backstop**: if a custom agent re-exposes an
execution tool (or `web_search` is used for content gathering rather than
scope discovery), the gate blocks the call at `wrap_tool_call` time and
runs a scope-vs-content LLM classifier on `web_search` invocations.

**Drift validator** — [`tests/test_tool_schema_sync.py`](../../backend/tests/test_tool_schema_sync.py)
walks every entry across both catalog files, instantiates the handler,
and asserts JSON parameters match the handler signature. It also asserts
that the plan catalog excludes execution tools and that the work catalog
includes them.

**Audit tool** — `make tools-audit` (or `python -m src.tools.audit --mode
plan`) prints the resolved catalog for a given mode/phase triple.

## 7. Skills

There are no plan-mode-exclusive skills. Skills are filtered/injected by
`SkillDisclosureMiddleware` based on the same enabled-skill catalogue used in
Work Mode. The plan-mode prompt does not change the active skill set —
`apply_prompt_template` is called identically with `available_skills` from
the agent config.

## 8. Plan persistence / handoff

| Symbol | File | Role |
|---|---|---|
| `serialize_plan_md(plan, todo_graph, body_renderer)` | [common/handoff.py:32](../../backend/src/agents/common/handoff.py#L32) | Writes canonical `plan_version: 5` frontmatter + markdown body. |
| `parse_plan_md(text)` | [common/handoff.py:84](../../backend/src/agents/common/handoff.py#L84) | Reads canonical frontmatter back into `(plan, todo_graph)`; returns `None` for v<5 (legacy fallback). |
| `_load_canonical_plan_overrides(values)` | [work_run_handoff.py:22](../../backend/src/agents/middlewares/work_run_handoff.py#L22) | At Work Mode handoff, re-reads `plan.md` from disk to honor user edits between approval and execution. |
| `spawn_work_mode_handoff(...)` | [work_run_handoff.py:317](../../backend/src/agents/middlewares/work_run_handoff.py#L317) | Daemon-thread path (used in `auto_mode` planner-resolved clarifications). |
| `_create_work_mode_run(...)` | [gateway/routers/steering.py:188](../../backend/src/gateway/routers/steering.py#L188) | API path: registers a new `work_agent` run on the LangGraph Server. |
| `render_plan_md(...)` | [middlewares/handoff_sync.py](../../backend/src/agents/middlewares/handoff_sync.py) | Renders the human-readable markdown body of `plan.md`. |
| `ensure_plan_state`, `sync_handoff_files_from_state` | [middlewares/handoff_sync.py](../../backend/src/agents/middlewares/handoff_sync.py) | Idempotent reconciliation: ensures plan dict has all required fields and `plan.md` exists on disk. |

## 9. Plan-execution helpers (state machine primitives)

In [middlewares/plan_execution.py](../../backend/src/agents/middlewares/plan_execution.py):

| Function | Role |
|---|---|
| `apply_clarification_progress(plan, messages)` | Advances `clarification_index` after a `HumanMessage` answer is detected. |
| `approve_plan_if_auto_mode(plan, auto_mode)` | Flips `status` → `approved` when auto mode is on and no clarifications pending. |
| `build_clarification_prompt_message(...)` | Synthesizes the bubble shown to the user. |
| `format_clarification_context_for_work(plan)` | Renders the `<clarification_resolved>` block injected into the Work Mode handoff message. |
| `mark_handoff_requested/succeeded/failed(plan)` | State bits used by retry/recovery. |
| `should_spawn_work_handoff(plan, plan_behavior, plan_status)` | Decides whether the planner should auto-spawn a Work Mode run (auto-mode short-circuit). |
| `execute_plan_should_duplicate(plan, values)` | Idempotency check for the Execute Plan endpoint. |
| `resolve_auto_mode(values, request_auto_mode)` | Resolution order for `auto_mode` between request and persisted state. |
| `resolve_original_user_request(values)` | Pulls the original user message for the handoff. |

## 10. Gateway API surface (frontend ↔ backend)

In [backend/src/gateway/routers/steering.py](../../backend/src/gateway/routers/steering.py):

| Route | Purpose |
|---|---|
| `POST /api/threads/{id}/steer` | Generic one-shot steering (not plan-mode-specific). |
| `POST /api/threads/{id}/plan/execute` | **Execute Plan** button. Flips `plan.status` → `approved`, marks handoff requested, calls `_create_work_mode_run` to register a Work Mode run on the LangGraph Server. |
| `POST /api/threads/{id}/plan/clarify` | Inline clarification answer from the Execute Plan popup. Synthesizes a `HumanMessage`, advances `clarification_index`. |
| `POST /api/threads/{id}/compact` | Force-compact thread history (not plan-mode-specific, but reachable during long planning runs). |

## 11. Frontend touchpoints

| File | Role |
|---|---|
| [components/workspace/input-box-left-toolbar.tsx](../../frontend/src/components/workspace/input-box-left-toolbar.tsx) | Plan-Mode chip; toggles `settings.context.mode`. |
| [components/workspace/input-box.tsx:505-554](../../frontend/src/components/workspace/input-box.tsx#L505-L554) | Toggle handler; dual-writes `mode` and `is_plan_mode`. |
| [core/threads/hooks.ts:1362](../../frontend/src/core/threads/hooks.ts#L1362) | Maps `selectedMode === "plan"` to the LangGraph configurable payload. |
| [app/workspace/chats/[thread_id]/page.tsx](../../frontend/src/app/workspace/chats/[thread_id]/page.tsx) | Renders the Execute Plan popup, calls `/plan/execute` and `/plan/clarify`. |
| [components/workspace/workspace-header.tsx:49](../../frontend/src/components/workspace/workspace-header.tsx#L49) | Header pill that reflects the active mode. |

## 12. Runtime config knobs

In [config.yaml](../../config.example.yaml):

| Key | Default | Effect on Plan Mode |
|---|---|---|
| `planner.enabled` | `true` | Master switch for `PlannerMiddleware` + `PlanEvaluatorMiddleware`. |
| `planner.max_plan_steps` | `8` | Cap on todos the planner LLM may emit. |
| `planner.max_clarifications` | `5` | Cap on clarification questions. |
| `planner.research_fanout` | `false` | If `true`, planner surfaces independent ready todos as fan-out candidates for parallel subagents. |
| `planner.research_fanout_min_todos` | `2` | Threshold for fan-out activation. |
| `evaluator.enabled` | varies | Toggles `PlanEvaluatorMiddleware`. |
| `evaluator.plan_evaluator_timeout_seconds` | `10` | Hard timeout on the plan-quality LLM call. |
| `todos.dag_enabled` | `true` | Chooses `TodoDagMiddleware` vs legacy `TodoMiddleware`. |
| `handoffs.*` | — | Work-handoff retry attempts + recursion limit. |
| `harness.enabled` | `true` | Kill switch — when `false`, drops all non-minimal middlewares (kills Plan Mode). |

## 13. Runtime context keys (set in `config.configurable`)

| Key | Type | Set by | Read by |
|---|---|---|---|
| `current_mode` | `"work" \| "plan"` | frontend, `make_plan_agent`, handoff helpers | `resolve_current_mode`, every mode-aware middleware |
| `mode` | legacy alias | dual-write | back-compat readers |
| `is_plan_mode` | legacy bool | dual-write | back-compat readers |
| `plan_behavior` | `"plan_foreground" \| "work_interactive"` | frontend / handoff | `_plan_behavior(runtime)` in planner + plan-execution helpers |
| `auto_mode` | bool | frontend toggle | planner auto-approval (work-mode auto-escalation has been removed) |
| `background_followup` | bool | follow-up daemons | `apply_prompt_template`, `PlanFileSyncMiddleware` |
| `current_turn_text`, `original_user_request` | str | frontend / handoff | planner, summarization, memory injection |
| `thread_id`, `model_name` | str | frontend / handoff | every middleware that spawns subruns |
