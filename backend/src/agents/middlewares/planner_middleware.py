"""Planner middleware for Phase B Plan-mode runs."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, override
from uuid import uuid4

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime

from src.agents.common.handoff import serialize_plan_md
from src.agents.common.runtime_context import get_runtime_context
from src.agents.middlewares._fs_utils import atomic_write_text
from src.agents.middlewares.handoff_sync import render_plan_md, versioned_plan_filename
from src.agents.middlewares.message_selection import extract_text, original_user_prompt
from src.agents.middlewares.plan_execution import (
    apply_clarification_progress,
    approve_plan_if_auto_mode,
    build_clarification_prompt_message,
    mark_handoff_requested,
    should_spawn_work_handoff,
)
from src.agents.middlewares.runtime_events import append_runtime_event
from src.agents.middlewares.todo_dag_middleware import _legacy_todos, normalize_todo_nodes
from src.agents.middlewares.work_run_handoff import spawn_work_mode_handoff
from src.config.handoffs_config import HandoffsConfig
from src.config.sprint_contracts_config import SprintContractsConfig
from src.models import create_chat_model, resolve_model_name
from src.sandbox.path_mapping import to_virtual_path

logger = logging.getLogger(__name__)


class PlannerState(AgentState):
    plan: NotRequired[dict | None]
    todo_graph: NotRequired[dict | None]
    todos: NotRequired[list | None]
    handoff_artifacts: NotRequired[list[str] | None]
    artifacts: NotRequired[list[str] | None]
    plan_evaluated: NotRequired[bool]
    plan_history: NotRequired[list[dict[str, Any]] | None]
    planner_ephemeral_handoff: NotRequired[str | None]
    planner_ephemeral_clarification: NotRequired[str | None]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _emit_planning_failed(runtime: Runtime, *, reason: str) -> None:
    """Mirror of the inline planning_started emit, for the failure path."""
    append_runtime_event(runtime, {"source": "planner_middleware", "event": "planning_failed", "reason": reason})
    try:
        writer = get_stream_writer()
        writer({"type": "planning_failed", "source": "planner_middleware", "reason": reason})
    except Exception:
        logger.exception("Failed to emit planning_failed SSE")


def _runtime_context(runtime: Runtime) -> dict[str, Any]:
    return get_runtime_context(runtime)


def _plan_behavior(runtime: Runtime) -> str:
    return str(_runtime_context(runtime).get("plan_behavior") or "").strip().lower()


def _auto_mode_enabled(runtime: Runtime, state: PlannerState) -> bool:
    ctx = _runtime_context(runtime)
    if bool(ctx.get("auto_mode")):
        return True
    return bool(state.get("auto_mode"))


# ---------------------------------------------------------------------------
# Structured planner output
# ---------------------------------------------------------------------------


@dataclass
class ClarificationOption:
    label: str
    recommended: bool = False
    description: str | None = None


@dataclass
class PlannerClarification:
    question: str
    options: list[ClarificationOption] = field(default_factory=list)


@dataclass
class PlannerOutput:
    title: str = "Execution Plan"
    summary: str = ""
    objective: str = ""
    assumptions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    risks: list[dict[str, str]] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    domain: str = "generic"
    todos: list[dict[str, Any]] = field(default_factory=list)
    clarifications: list[PlannerClarification] = field(default_factory=list)
    parse_ok: bool = True


def _ordered_clarification_options(options: list[ClarificationOption]) -> list[ClarificationOption]:
    recommended = [option for option in options if option.recommended]
    non_recommended = [option for option in options if not option.recommended]
    return [*recommended[:1], *non_recommended, *recommended[1:]]


def _normalize_clarification_options(options: list[ClarificationOption]) -> list[ClarificationOption]:
    normalized = [option for option in _ordered_clarification_options(options) if option.label.strip()]
    if not normalized:
        return []
    if not any(option.recommended for option in normalized):
        normalized[0] = ClarificationOption(
            label=normalized[0].label,
            recommended=True,
            description=normalized[0].description,
        )
    return normalized[:4]


def _normalize_planner_clarifications(output: PlannerOutput, max_clarifications: int = 5) -> list[PlannerClarification]:
    """Dedupe by question text and normalize options on each clarification.

    Hard-coded domain heuristics (timeframe / AI-trends injection) were removed —
    the planner LLM is responsible for surfacing missing-detail questions itself,
    and the prior heuristics didn't generalise beyond the research domain.
    """
    deduped: list[PlannerClarification] = []
    seen_questions: set[str] = set()
    for clarification in output.clarifications:
        question = clarification.question.strip()
        if not question:
            continue
        key = question.lower()
        if key in seen_questions:
            continue
        seen_questions.add(key)
        options = _normalize_clarification_options(clarification.options)
        if len(options) < 2:
            continue
        deduped.append(PlannerClarification(question=question, options=options))
    return deduped[:max_clarifications]


# ---------------------------------------------------------------------------
# Planner system prompt — domain-aware with real dependency generation
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """\
<identity>
You are CapyHome's Plan-Mode Strategist.

CapyHome is a personal AI agent that helps a single user with anything they bring
to it: software work, research, legal review, life admin (forms, claims,
applications), spreadsheets and data, shopping decisions, food and recipes, local
events (Singapore and beyond), travel, learning plans, comparisons, summaries,
routines. You are the planning brain that runs BEFORE execution. A separate Work
agent reads your output and carries the plan out — you do not execute. Your only
output is one JSON object that matches the schema below.
</identity>

<objective>
Turn the user's request into a concrete execution plan the Work agent can run
end-to-end. A good plan:
  - names the end state the user actually wants (objective + summary),
  - covers every explicit requirement (and the obvious implicit ones) with the
    smallest set of todos that gets there — no padding,
  - gives every todo an OBSERVABLE done-criterion the Work agent (or the user)
    can verify,
  - sequences with depends_on only where there is a real data dependency, so
    independent work can run in parallel,
  - asks clarifying questions ONLY when a missing detail would fundamentally
    change the plan.
</objective>

<scope>
In scope — any task type the user might bring to a personal agent:
  software, research, legal, life admin, data/Excel, shopping, food, events,
  travel, learning, comparisons, summaries, checklists, routines, and more.

Out of scope — do NOT:
  - execute the plan (no tool calls, no web search, no file writes — JSON only),
  - rewrite or second-guess the user's request,
  - ask more than {max_clarifications} clarifying questions,
  - pad the plan with filler todos to hit a count,
  - default to a software-engineering framing when the request is not technical
    (e.g. "find me a hawker brunch in Tiong Bahru" is a food/events plan, not
    a code plan).
</scope>

<thinking_flow>
Reason through these stages internally. Do NOT emit them in your output —
emit only the JSON contract below.

  1. UNDERSTAND — read the request in full. Name the end state the user wants.
  2. COVER — list every explicit requirement plus reasonable implicit ones.
     Every requirement must be covered by at least one todo.
  3. CLASSIFY — pick the dominant domain (see DOMAIN). It shapes dependency
     defaults and verification style.
  4. DECOMPOSE — break the work into the smallest set of todos that cover all
     requirements. Combine trivially-small steps; split anything that hides two
     separate deliverables.
  5. SEQUENCE — add depends_on only where there is a real data dependency.
     Maximise the number of todos that can run in parallel.
  6. DEFINE DONE — for each todo, write a completion_requirement that is
     OBSERVABLE (a file with >= N entries, a comparison table with K columns,
     a confirmed booking reference, a filled form, a passing test, a draft of
     at least N words, ...). Never "task completes" or "step ran".
  7. SURFACE UNKNOWNS — only if a missing fact would change the plan's shape,
     raise a clarification question with 3-4 options.
</thinking_flow>

<output_contract>
Return ONLY valid JSON matching this exact schema (no prose, no markdown fences):
{
  "title": "Short plan title (≤ 8 words)",
  "objective": "One paragraph objective describing the intended end state.",
  "summary": "1-2 sentence overview of what will be accomplished.",
  "assumptions": ["Concise assumption strings"],
  "constraints": ["Concise constraint strings"],
  "risks": [
    {"risk": "Main delivery risk", "mitigation": "Concrete mitigation"}
  ],
  "acceptance_criteria": ["Observable success criterion 1", "Observable success criterion 2"],
  "domain": "code|research|legal|life_admin|data|shopping|food|events|travel|learning|generic",
  "requires_clarification": false,
  "clarifications": [
    {
      "question": "What should the output format be?",
      "options": [
        {"label": "Markdown document", "recommended": true, "description": null},
        {"label": "Bullet-point summary", "recommended": false, "description": null}
      ]
    }
  ],
  "todos": [
    {
      "id": "todo-1",
      "content": "Action verb + concise task (≤ 14 words)",
      "rationale": "Why this step exists and why now (1 sentence).",
      "depends_on": [],
      "owner": "lead",
      "subagent_type": null,
      "objective": "Phase-level outcome this todo achieves (1-2 sentences).",
      "failure_fallback": "What to do if a step fails (e.g., return best-effort with label, ask_user_for_clarification).",
      "steps": [
        {
          "description": "What this step does (action sentence)",
          "completion_requirement": "Observable check that proves the step is done"
        }
      ]
    }
  ]
}
</output_contract>

DOMAIN — pick the closest match. Free-form strings are accepted; if nothing
fits cleanly, use "generic". Domain shapes dependency defaults below.
- code        — software engineering, refactors, debugging, building features
- research    — investigating a topic, gathering sources, producing a brief
- legal       — reading/analysing contracts, forms, policies, regulations
- life_admin  — government forms, claims, applications, appointments, accounts
- data        — Excel/CSV/spreadsheet work, analysis, dashboards
- shopping    — product research, comparisons, purchase recommendations
- food        — recipes, meal plans, restaurant picks, dietary research
- events      — finding/booking events (Singapore or elsewhere)
- travel      — trip planning, itineraries, bookings, visas
- learning    — study plans, reading lists, curriculum design
- generic     — fallback when nothing else fits

DEPENDENCY RULES:
- depends_on lists IDs of todos that MUST complete before this one starts.
- Do NOT create circular dependencies.
- Minimise unnecessary sequencing — only add depends_on when there is a real
  data dependency between two todos.
- code: test todos depend on the implementation todos they test.
- research: synthesis / write-up todos depend on all research-gathering todos.
- legal: analysis todos depend on document-reading todos.
- travel: booking todos depend on visa / permit todos when applicable.
- life_admin / data / shopping / food / events / learning: gathering todos run
  in parallel; the decision, comparison, or write-up todo depends on them.

CLARIFICATION RULES:
- Only ask when a missing detail would fundamentally change the plan.
- At most {max_clarifications} clarification questions. Each must have 3-4 options.
- Mark exactly one option per question as recommended: true and put it FIRST.

TODO STYLE:
- Start each todo with a clear action verb (Research, Compare, Draft, Book,
  Fill, Build, Review, Summarise, Shortlist...).
- Keep each todo to one sentence, ≤ 14 words.
- Include a rationale sentence per todo.
- Avoid jargon, nested clauses, or stacked subtasks in a single todo.
- Maximum {max_steps} todos. Do NOT pad to hit the cap.

ID RULE:
- All todo IDs MUST use the format "todo-1", "todo-2", etc.
- Do NOT use "plan-*", "research-*", or any other prefix.

RICH EXECUTION FIELDS (per todo):
Required:
- objective: 1-2 sentence phase-level goal — what the todo achieves overall.
- failure_fallback: what to do if a step fails — e.g., "return best-effort
  from prior knowledge, clearly labelled" or "call ask_user_for_clarification".
- steps: ordered execution steps. Each step MUST include:
    - description: short action sentence.
    - completion_requirement: concrete check that proves the step is done
      (e.g., "file exists with >= 10 entries", "comparison table has
      price+rating+source columns filled", "form has all required fields").

Optional — include ONLY when they carry real signal, otherwise omit:
- completion_requirement (todo-level): include only when it adds something
  beyond the final step's done-criterion (e.g., a cross-step invariant).
- steps[].subagent_types: from {source-researcher, docs-explorer,
  comparison-dimension-researcher, synthesis-reviewer, general-purpose, bash}.
  Omit when the lead agent handles the step directly. Prefer
  ["source-researcher"] for broad web research (it has its own search budget).
- steps[].tools: from {web_search, query_knowledge_vault,
  read_file, write_file, str_replace, bash, ls, view_image, task,
  present_files}. Omit when the step needs no specific tool gating.
- steps[].output_artifact_path: virtual path under /mnt/user-data/workspace,
  but ONLY when the step's completion_requirement actually references a file.
  Do not invent paths to fill the field.

Do not pad fields with vague text ("step completes", "retry"). If a field
would be filler, omit it.

EXAMPLE rich todo for "Find 10 well-reviewed restaurants matching my criteria":
{
  "id": "todo-1",
  "content": "Identify 10 well-reviewed restaurants matching the user's criteria",
  "rationale": "Foundational lookup that downstream filtering depends on.",
  "depends_on": [],
  "owner": "lead",
  "subagent_type": "source-researcher",
  "objective": "Produce a candidate list of restaurants with enough headroom to filter to top 10.",
  "failure_fallback": "If web_search returns < 10 results, fall back to model's prior knowledge and label results as 'best-effort from training data'. If criteria are ambiguous, call ask_user_for_clarification.",
  "steps": [
    {
      "description": "Web search for candidate restaurants",
      "subagent_types": ["source-researcher"],
      "output_artifact_path": "/mnt/user-data/workspace/candidates.md",
      "completion_requirement": "candidates.md contains at least 15 entries with name + URL"
    },
    {
      "description": "Filter to top 10 by review score",
      "completion_requirement": "top10.md contains exactly 10 entries with name, URL, and score"
    }
  ]
}
"""


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------


def _normalize_todo_steps(raw: Any) -> list[dict[str, Any]]:
    """Normalize rich todo ``steps`` field into a list of dicts.

    Robust to:
    - missing field (returns [])
    - non-list field
    - non-dict entries
    - missing sub-fields (filled with safe defaults)

    Older plans without ``steps`` simply get an empty list; rendering and
    Work Mode dispatchers must tolerate that.
    """
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        subagent_types_raw = item.get("subagent_types")
        subagent_types: list[str] = []
        if isinstance(subagent_types_raw, list):
            subagent_types = [str(s).strip() for s in subagent_types_raw if str(s).strip()]
        tools_raw = item.get("tools")
        tools: list[str] = []
        if isinstance(tools_raw, list):
            tools = [str(t).strip() for t in tools_raw if str(t).strip()]
        output_artifact_path = item.get("output_artifact_path")
        if output_artifact_path is not None:
            output_artifact_path = str(output_artifact_path).strip() or None
        normalized.append(
            {
                "description": description,
                "subagent_types": subagent_types,
                "tools": tools,
                "output_artifact_path": output_artifact_path,
                "completion_requirement": str(item.get("completion_requirement") or "").strip(),
            }
        )
    return normalized


def _parse_plan_response(raw: str, max_steps: int) -> PlannerOutput:
    """Parse the planner LLM JSON output into a PlannerOutput."""
    text = raw.strip()
    # Strip any accidental markdown fences
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        payload = json.loads(text)
    except Exception:
        # Fallback: treat each non-empty line as a todo
        lines = [line.strip("- ").strip() for line in text.splitlines() if line.strip()]
        todos = [{"id": f"todo-{i + 1}", "content": line, "depends_on": []} for i, line in enumerate(lines[:max_steps]) if len(line) > 2]
        if not todos:
            todos = [{"id": "todo-1", "content": "Complete the user request end-to-end.", "depends_on": []}]
        return PlannerOutput(
            title="Execution Plan",
            objective="Deliver the user request with a structured implementation approach.",
            summary="Fallback plan generated from unstructured planner output.",
            todos=todos,
            parse_ok=False,
        )

    title = str(payload.get("title") or "Execution Plan")
    objective = str(payload.get("objective") or payload.get("summary") or "").strip()
    summary = str(payload.get("summary") or "")
    domain = str(payload.get("domain") or "generic")
    assumptions = [str(item).strip() for item in (payload.get("assumptions") or []) if str(item).strip()]
    constraints = [str(item).strip() for item in (payload.get("constraints") or []) if str(item).strip()]
    acceptance_criteria = [str(item).strip() for item in (payload.get("acceptance_criteria") or []) if str(item).strip()]
    risks: list[dict[str, str]] = []
    for item in payload.get("risks") or []:
        if not isinstance(item, dict):
            continue
        risk_text = str(item.get("risk") or "").strip()
        mitigation_text = str(item.get("mitigation") or "").strip()
        if not risk_text and not mitigation_text:
            continue
        risks.append({"risk": risk_text, "mitigation": mitigation_text})

    # Parse todos WITH depends_on preserved (critical fix from design study P8)
    raw_todos = list(payload.get("todos") or [])
    todos: list[dict[str, Any]] = []
    for i, item in enumerate(raw_todos[:max_steps]):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        todos.append(
            {
                "id": item.get("id") or f"todo-{i + 1}",
                "content": content,
                "status": "pending",
                "depends_on": [str(d) for d in (item.get("depends_on") or [])],  # PRESERVED
                "owner": item.get("owner") or "lead",
                "subagent_type": item.get("subagent_type"),
                "rationale": str(item.get("rationale") or "").strip(),
                # Rich todo annotations — optional. Missing fields default to
                # empty so legacy plans without these fields stay valid.
                "objective": str(item.get("objective") or "").strip(),
                "completion_requirement": str(item.get("completion_requirement") or "").strip(),
                "failure_fallback": str(item.get("failure_fallback") or "").strip(),
                "steps": _normalize_todo_steps(item.get("steps")),
            }
        )
    if not todos:
        todos = [{"id": "todo-1", "content": "Complete the user request end-to-end.", "status": "pending", "depends_on": [], "owner": "lead", "subagent_type": None}]

    # Parse clarifications (accept LLM clarifications even when requires_clarification is false)
    clarifications: list[PlannerClarification] = []
    for raw_clar in payload.get("clarifications") or []:
        if not isinstance(raw_clar, dict):
            continue
        options = [
            ClarificationOption(
                label=str(o.get("label") or ""),
                recommended=bool(o.get("recommended", False)),
                description=o.get("description"),
            )
            for o in (raw_clar.get("options") or [])
            if isinstance(o, dict)
        ]
        if raw_clar.get("question") and options:
            clarifications.append(PlannerClarification(question=str(raw_clar["question"]), options=options))

    return PlannerOutput(
        title=title,
        objective=objective or summary or "Deliver the user request with a structured implementation approach.",
        summary=summary or objective or "Structured implementation plan.",
        assumptions=assumptions,
        constraints=constraints,
        risks=risks,
        acceptance_criteria=acceptance_criteria,
        domain=domain,
        todos=todos,
        clarifications=clarifications,
    )


# ---------------------------------------------------------------------------
# Plan file naming — `versioned_plan_filename` lives in `handoff_sync` (single
# source of truth, finding #29).
# ---------------------------------------------------------------------------


def _write_file(path: Path, content: str) -> None:
    atomic_write_text(path, content)


class PlannerMiddleware(AgentMiddleware[PlannerState]):
    """Builds a structured plan before execution."""

    state_schema = PlannerState

    def __init__(
        self,
        *,
        requested_model: str | None,
        max_plan_steps: int,
        max_clarifications: int = 5,
        dag_enabled: bool,
        handoffs_config: HandoffsConfig,
        sprint_contracts_config: SprintContractsConfig,
        research_fanout: bool = False,
        research_fanout_min_todos: int = 2,
        timeout_seconds: float = 120.0,
    ):
        super().__init__()
        self._requested_model = requested_model
        self._max_plan_steps = max_plan_steps
        self._max_clarifications = max_clarifications
        self._dag_enabled = dag_enabled
        self._handoffs_config = handoffs_config
        self._sprint_contracts_config = sprint_contracts_config
        self._research_fanout = bool(research_fanout)
        self._research_fanout_min_todos = max(2, int(research_fanout_min_todos))
        self._timeout_seconds = float(timeout_seconds)

    def _finalize_plan_handoff(
        self,
        *,
        payload: dict[str, Any],
        plan_dict: dict[str, Any],
        runtime: Runtime,
        auto_mode: bool,
        user_prompt: str | None,
        thread_name_suffix: str,
        clarification_pending: bool,
    ) -> dict[str, Any]:
        """Spawn a work-mode handoff and (conditionally) end the planning turn.

        Centralises the gating that used to live duplicated in `before_model`
        at two sites. Rules:

        * `jump_to=end` only fires when ALL of:
          - we have a real `thread_id` (otherwise nothing will spawn),
          - the plan has no pending clarifications,
          - `plan_behavior == "plan_foreground"`.

          This prevents the embedded-client path (no thread_id) from ending
          the planning turn with an un-handed-off plan.
        * On a successful spawn we emit a `plan_handoff_started` SSE so the
          frontend has a clean transition signal between plan-mode and
          work-mode event streams.
        """
        plan_behavior = _plan_behavior(runtime)
        runtime_context = _runtime_context(runtime)
        thread_id = runtime_context.get("thread_id")

        handoff_spawned = False
        if isinstance(thread_id, str) and thread_id:
            requested_model_name = runtime_context.get("model_name")
            plan_dict = mark_handoff_requested(plan_dict)
            payload["plan"] = plan_dict
            spawn_work_mode_handoff(
                thread_id=thread_id,
                requested_model_name=requested_model_name if isinstance(requested_model_name, str) else None,
                auto_mode=auto_mode,
                original_user_request=user_prompt or None,
                thread_name_suffix=thread_name_suffix,
            )
            handoff_spawned = True
            try:
                writer = get_stream_writer()
                writer({
                    "type": "plan_handoff_started",
                    "source": "planner_middleware",
                    "plan_id": plan_dict.get("plan_id"),
                    "status": plan_dict.get("status"),
                    "thread_id": thread_id,
                })
            except Exception:
                logger.exception("Failed to emit plan_handoff_started SSE")
            append_runtime_event(
                runtime,
                {
                    "source": "planner_middleware",
                    "event": "plan_handoff_started",
                    "plan_id": plan_dict.get("plan_id"),
                },
            )

        if handoff_spawned and not clarification_pending and plan_behavior == "plan_foreground":
            payload["jump_to"] = "end"
        return payload

    def _with_ephemeral_planner_context(self, request: ModelRequest) -> ModelRequest:
        runtime_state = request.state if isinstance(getattr(request, "state", None), dict) else {}
        if not runtime_state:
            runtime_obj = getattr(request, "runtime", None)
            runtime_state = getattr(runtime_obj, "state", {}) if isinstance(getattr(runtime_obj, "state", None), dict) else {}
        if not isinstance(runtime_state, dict):
            return request
        if bool(runtime_state.get("plan_evaluated")):
            return request
        handoff_text = str(runtime_state.get("planner_ephemeral_handoff") or "").strip()
        clarification_text = str(runtime_state.get("planner_ephemeral_clarification") or "").strip()
        prefix: list = []
        if handoff_text:
            prefix.append(SystemMessage(name="planner_handoff", content=handoff_text))
        if clarification_text:
            prefix.append(SystemMessage(name="planner_clarification_required", content=clarification_text))
        if not prefix:
            return request
        return request.override(messages=[*prefix, *request.messages])

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._with_ephemeral_planner_context(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._with_ephemeral_planner_context(request))

    # Cap the number of in-place revisions we allow on a single draft plan so
    # a confused agent (or replay loop) can't trigger unbounded planner calls.
    _MAX_DRAFT_REVISIONS = 5

    def _should_plan(self, state: PlannerState, runtime: Runtime) -> bool:
        plan = state.get("plan")
        # Re-plan opportunity: if a plan already exists in any non-clarifying
        # state and a fresh HumanMessage has arrived since the last revision,
        # run the planner again to incorporate the user's edit. The new plan
        # reuses the same plan_id and bumps a `revision` counter — see
        # before_model below. Plan Mode and Work Mode are separate graphs;
        # re-planning here updates the plan artifact only, Work Mode runs
        # independently against whichever plan was current when it started.
        if isinstance(plan, dict):
            if bool(plan.get("clarification_pending")):
                return False
            if int(plan.get("revision") or 0) >= self._MAX_DRAFT_REVISIONS:
                append_runtime_event(
                    runtime,
                    {
                        "source": "planner_middleware",
                        "decision": "replan_capped",
                        "plan_id": plan.get("plan_id"),
                        "revision": plan.get("revision"),
                    },
                )
                return False
            return self._has_new_user_message_since_plan(state, plan)
        messages = state.get("messages", []) or []
        human_count = sum(1 for msg in messages if getattr(msg, "type", None) == "human")
        ai_count = sum(1 for msg in messages if getattr(msg, "type", None) == "ai")
        mode = str(_runtime_context(runtime).get("mode") or "").strip().lower()
        # In Plan mode, allow re-planning in ongoing chats even when there are
        # prior AI turns.
        if mode == "plan":
            return human_count >= 1
        return human_count >= 1 and ai_count == 0

    @staticmethod
    def _has_new_user_message_since_plan(state: PlannerState, plan: dict[str, Any]) -> bool:
        """Detect a fresh user message that warrants a draft re-plan.

        We compare HumanMessage count against the recorded baseline at plan
        creation time. If we don't have a baseline yet (legacy plans), allow
        a single revision when at least two human messages exist AND there is
        no clarification pending — otherwise we'd treat a clarification answer
        as a re-plan trigger. The baseline is set in ``before_model`` after a
        successful plan.
        """
        baseline_raw = plan.get("human_messages_at_plan")
        baseline = int(baseline_raw) if isinstance(baseline_raw, int) else None
        messages = state.get("messages") or []
        human_count = sum(1 for msg in messages if getattr(msg, "type", None) == "human")
        if baseline is None:
            # Avoid mistaking a clarification answer for a re-plan trigger.
            if bool(plan.get("clarification_pending")):
                return False
            return human_count >= 2
        return human_count > baseline

    def _invoke_planner(self, user_prompt: str) -> tuple[PlannerOutput, str]:
        # Single-model invariant: honor the user's chat-selected model directly
        # rather than consulting stage-based routing. See src/models/resolver.py.
        model_name = resolve_model_name(self._requested_model)
        model = create_chat_model(name=model_name, thinking_enabled=False)
        system_prompt = PLANNER_SYSTEM_PROMPT.replace("{max_steps}", str(self._max_plan_steps)).replace("{max_clarifications}", str(self._max_clarifications))
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

        # Stream tokens and watch the inter-token gap rather than total wall-clock.
        # Long local generations are fine; only a truly wedged provider (no token
        # for `_timeout_seconds`) raises TimeoutError. Falls back to .invoke for
        # model classes that don't expose .stream (e.g. test mocks).
        stream_fn = getattr(model, "stream", None)
        if not callable(stream_fn):
            response = model.invoke(messages)
            output = _parse_plan_response(extract_text(response.content), max_steps=self._max_plan_steps)
            return output, model_name

        parts: list[str] = []
        last_token_at = [time.monotonic()]
        done = threading.Event()
        error_holder: list[BaseException | None] = [None]

        def _consume() -> None:
            try:
                for chunk in stream_fn(messages):
                    text = extract_text(getattr(chunk, "content", ""))
                    if text:
                        parts.append(text)
                        last_token_at[0] = time.monotonic()
            except Exception as e:  # noqa: BLE001
                error_holder[0] = e
            finally:
                done.set()

        consumer = threading.Thread(target=_consume, daemon=True)
        consumer.start()

        poll_interval = 1.0
        idle_limit = self._timeout_seconds
        while not done.wait(poll_interval):
            if time.monotonic() - last_token_at[0] > idle_limit:
                # Daemon thread keeps running in the background; the underlying
                # HTTP call is not cancelled, but the process owns its lifetime.
                raise TimeoutError(f"Planner stream idle for >{idle_limit}s (no token received)")

        if error_holder[0] is not None:
            raise error_holder[0]

        output = _parse_plan_response("".join(parts), max_steps=self._max_plan_steps)
        return output, model_name

    @override
    def before_model(self, state: PlannerState, runtime: Runtime) -> dict | None:
        current_plan = state.get("plan")
        if isinstance(current_plan, dict) and bool(current_plan.get("clarification_pending")):
            messages = state.get("messages", []) or []
            progress = apply_clarification_progress(current_plan, messages)
            if progress is not None:
                resolved_plan = dict(progress["plan"])
                auto_mode = _auto_mode_enabled(runtime, state)
                if not bool(resolved_plan.get("clarification_pending")):
                    resolved_plan = approve_plan_if_auto_mode(resolved_plan, auto_mode=auto_mode)
                append_runtime_event(
                    runtime,
                    {
                        "source": "planner_middleware",
                        "decision": "clarification_resolved",
                        "plan_id": resolved_plan.get("plan_id"),
                        "clarification_pending": bool(resolved_plan.get("clarification_pending")),
                    },
                )
                payload: dict[str, Any] = {"plan": resolved_plan}
                if progress.get("messages"):
                    payload["messages"] = progress["messages"]
                    return payload

                plan_status = str(resolved_plan.get("status") or "").strip().lower()
                clarification_pending = bool(resolved_plan.get("clarification_pending"))
                if should_spawn_work_handoff(
                    resolved_plan,
                    plan_behavior=_plan_behavior(runtime),
                    plan_status=plan_status,
                ):
                    user_prompt = original_user_prompt(messages) or ""
                    payload = self._finalize_plan_handoff(
                        payload=payload,
                        plan_dict=resolved_plan,
                        runtime=runtime,
                        auto_mode=auto_mode,
                        user_prompt=user_prompt,
                        thread_name_suffix="-planner-clarification-auto",
                        clarification_pending=clarification_pending,
                    )
                return payload

        if not self._should_plan(state, runtime):
            return None

        messages = state.get("messages", []) or []
        user_prompt = original_user_prompt(messages)
        if not user_prompt.strip():
            latest_user = next((msg for msg in reversed(messages) if getattr(msg, "type", None) == "human"), None)
            if latest_user is None:
                return None
            user_prompt = extract_text(getattr(latest_user, "content", ""))
        if not user_prompt.strip():
            return None

        # Emit planning_started immediately — fires within ~100ms of request arrival
        append_runtime_event(runtime, {"source": "planner_middleware", "event": "planning_started"})
        try:
            writer = get_stream_writer()
            writer({"type": "planning_started", "source": "planner_middleware"})
        except Exception:
            logger.exception("Failed to emit planning_started SSE")

        # Invoke planner LLM via streaming. There is no total wall-clock cap —
        # long local generations are expected to succeed. The streaming loop
        # inside `_invoke_planner` raises TimeoutError only when no token has
        # arrived for `_timeout_seconds` (a wedged provider). The except blocks
        # below emit planning_failed so the frontend can clear the spinner.
        try:
            plan_output, planner_model = self._invoke_planner(user_prompt)
        except TimeoutError:
            logger.warning("Planner LLM stream idle for >%ss; skipping planning", self._timeout_seconds)
            _emit_planning_failed(runtime, reason="timeout")
            return None
        except Exception:
            logger.exception("Planner LLM call failed; skipping planning")
            _emit_planning_failed(runtime, reason="error")
            return None

        if not plan_output.parse_ok:
            append_runtime_event(runtime, {"source": "planner_middleware", "decision": "parse_failed_fallback", "todo_count": len(plan_output.todos)})

        # Validate and normalize nodes (preserves depends_on from planner output)
        try:
            nodes = normalize_todo_nodes(plan_output.todos)
        except ValueError as e:
            logger.warning("Plan dependency cycle detected (%s); stripping deps", e)
            for node in plan_output.todos:
                node["depends_on"] = []
            nodes = normalize_todo_nodes(plan_output.todos)

        from src.agents.middlewares.todo_dag_middleware import _materialize_ready_ids

        ready_ids = _materialize_ready_ids(nodes)
        clarifications = _normalize_planner_clarifications(plan_output, max_clarifications=self._max_clarifications)
        clarification_pending = len(clarifications) > 0
        primary_clarification = clarifications[0] if clarifications else None

        # Resolve file paths
        thread_data = state.get("thread_data") or {}
        workspace_path = thread_data.get("workspace_path")
        plan_root = workspace_path

        artifact_paths: list[str] = []
        plan_path: str | None = None
        latest_alias_path: str | None = None
        # Plan-edit reuse: if a plan already exists in any non-clarifying state
        # and the user is refining it, preserve plan_id and bump revision. This
        # keeps plan.md history coherent and lets the frontend update the same
        # popup in place. Mirrors the gating in ``_should_plan``.
        existing_plan = state.get("plan") if isinstance(state.get("plan"), dict) else None
        is_replan = (
            isinstance(existing_plan, dict)
            and not bool(existing_plan.get("clarification_pending"))
        )
        if is_replan:
            plan_id = str(existing_plan.get("plan_id") or "").strip() or f"plan-{uuid4().hex[:10]}"
            revision = int(existing_plan.get("revision") or 0) + 1
        else:
            plan_id = f"plan-{uuid4().hex[:10]}"
            revision = 0
        auto_mode = _auto_mode_enabled(runtime, state)
        plan_status = "approved" if auto_mode and not clarification_pending else "draft"
        approved_at = _utc_now_iso() if plan_status == "approved" else None
        created_at_dt = datetime.now(UTC)
        created_at = created_at_dt.isoformat()

        # Build inline clarifications payload for plan.md
        inline_clarifications = [
            {
                "question": c.question,
                "options": [
                    {"label": o.label, "recommended": o.recommended, "description": o.description}
                    for o in c.options
                ],
            }
            for c in clarifications
        ]
        canonical_plan_for_md = {
            "plan_id": plan_id,
            "title": plan_output.title,
            "status": plan_status,
            "domain": plan_output.domain,
            "target_mode": "work",
            "created_at": created_at,
            "objective": plan_output.objective,
            "summary": plan_output.summary,
            "assumptions": plan_output.assumptions,
            "constraints": plan_output.constraints,
            "risks": plan_output.risks,
            "acceptance_criteria": plan_output.acceptance_criteria,
            "clarifications": inline_clarifications or [],
        }
        canonical_todo_graph_for_md = {
            "nodes": nodes,
            "ready_ids": ready_ids,
        }

        def _render_body(_plan: dict, _nodes: list[dict]) -> str:
            return render_plan_md(
                plan_output.title,
                plan_output.summary,
                _nodes,
                domain=plan_output.domain,
                plan_id=plan_id,
                status=plan_status,
                created_at=created_at,
                objective=plan_output.objective,
                assumptions=plan_output.assumptions,
                constraints=plan_output.constraints,
                risks=plan_output.risks,
                acceptance_criteria=plan_output.acceptance_criteria,
                clarifications=inline_clarifications or None,
                include_frontmatter=False,
            )

        plan_md_content = serialize_plan_md(
            canonical_plan_for_md,
            canonical_todo_graph_for_md,
            body_renderer=_render_body,
        )

        # Write versioned plan file + latest alias.
        if plan_root:
            plans_dir = Path(plan_root) / "plans"
            versioned_plan_file = plans_dir / versioned_plan_filename(plan_output.title, created_at_dt)
            latest_plan_alias_file = Path(plan_root) / "plan.md"
            try:
                _write_file(versioned_plan_file, plan_md_content)
                _write_file(latest_plan_alias_file, plan_md_content)
                plan_path = to_virtual_path(str(versioned_plan_file), thread_data) or str(versioned_plan_file)
                latest_alias_path = to_virtual_path(str(latest_plan_alias_file), thread_data) or str(latest_plan_alias_file)
                artifact_paths.extend([plan_path, latest_alias_path])
            except Exception:
                logger.exception("Failed to write versioned plan artifacts to outputs/")

        # Research fan-out detection (opt-in). When enabled and the plan is a
        # research workload with N independent ready todos, surface them to the
        # agent as candidates for parallel `task` subagent dispatch — this lets
        # the lead agent fire off N concurrent research subagents instead of
        # serializing through the main loop. Default off; enable via
        # planner.research_fanout in config.yaml. See thread-cd90decb plan WS3.
        fanout_ids: list[str] = []
        if self._research_fanout and plan_output.domain == "research" and len(ready_ids) >= self._research_fanout_min_todos:
            fanout_ids = [tid for tid in ready_ids if not any(tid == n.get("id") and n.get("depends_on") for n in nodes)]

        plan_created_event: dict[str, Any] = {
            "source": "planner_middleware",
            "decision": "plan_created",
            "todo_count": len(nodes),
            "domain": plan_output.domain,
            "has_deps": any(n.get("depends_on") for n in nodes),
            "has_clarifications": clarification_pending,
            "model": planner_model,
            "fanout_candidates": fanout_ids,
            "fanout_candidates_count": len(fanout_ids),
            "plan_status": plan_status,
        }
        if plan_status == "approved":
            plan_created_event["decision"] = "plan_auto_approved"
        append_runtime_event(runtime, plan_created_event)

        fanout_block = ""
        if fanout_ids:
            node_by_id = {
                str(node.get("id") or "").strip(): str(node.get("content") or "").strip()
                for node in nodes
                if isinstance(node, dict)
            }
            candidate_lines = [
                f"- {todo_id}: {node_by_id.get(todo_id) or 'todo objective'}"
                for todo_id in fanout_ids
            ]
            fanout_candidates_text = "\n".join(candidate_lines)
            fanout_block = (
                "\nFanout candidates (independent — eligible for parallel execution once approved):\n"
                f"{fanout_candidates_text}\n"
                "Execution remains gated until explicit plan approval.\n"
                "Do not dispatch one giant subagent prompt that covers multiple candidates.\n"
                "Delegate one narrow objective per subagent task, then run multiple tasks in parallel.\n"
                "When synthesizing fanout results, merge by unique topic/claim, deduplicate overlapping sections, and preserve a single clean heading hierarchy.\n"
            )

        planner_handoff = HumanMessage(
            name="planner_handoff",
            content=(
                f"<planner_handoff>\n"
                f"Title: {plan_output.title}\n"
                f"Plan ID: {plan_id}\n"
                f"Original request: {user_prompt}\n"
                f"Domain: {plan_output.domain}\n"
                f"Summary: {plan_output.summary}\n"
                f"Planned todos: {len(nodes)}\n"
                f"Ready to start: {ready_ids}\n"
                f"Clarification required: {'yes' if clarification_pending else 'no'}\n"
                f"Plan status: {plan_status}"
                + (
                    " (auto-approved; you may use execution tools now).\n"
                    if plan_status == "approved"
                    else " (draft — do NOT call web_search, task, or write_file until the user approves via Execute Plan).\n"
                )
                + f"{fanout_block}</planner_handoff>"
            ),
        )

        clarification_prompt_message = None
        if primary_clarification is not None:
            clarification_prompt_message = build_clarification_prompt_message(
                {
                    "question": primary_clarification.question,
                    "options": [
                        {
                            "label": option.label,
                            "recommended": option.recommended,
                            "description": option.description,
                        }
                        for option in primary_clarification.options
                    ],
                }
            )

        # Serialize clarifications once so both the SSE event and the persisted
        # plan dict carry the same payload — the frontend popup needs the full
        # list to render the inline clarification panel.
        clarifications_payload = [
            {
                "question": clarification.question,
                "options": [
                    {
                        "label": option.label,
                        "recommended": option.recommended,
                        "description": option.description,
                    }
                    for option in clarification.options
                ],
            }
            for clarification in clarifications
        ]

        # Emit plan_created with inline first_todos — no async fetch needed on frontend
        try:
            writer = get_stream_writer()
            writer({
                "type": "plan_created",
                "source": "planner_middleware",
                "title": plan_output.title,
                "summary": plan_output.summary,
                "domain": plan_output.domain,
                "plan_id": plan_id,
                "status": plan_status,
                "auto_approved": plan_status == "approved",
                "todo_count": len(nodes),
                "first_todos": [n.get("content", "") for n in nodes[:5]],
                "plan_path": plan_path,
                "clarification_pending": clarification_pending,
                # Inline clarification panel: the frontend Execute Plan popup
                # renders options directly so the user can answer without an
                # `ask_user_for_clarification` round-trip. POST to /plan/clarify advances.
                "clarifications": clarifications_payload,
                "clarification_index": 0,
                # Revision counter for in-place plan edits; 0 = brand new.
                "revision": revision,
            })
        except Exception:
            logger.exception("Failed to emit plan_created SSE")

        existing_history_raw = state.get("plan_history") or []
        existing_history = [item for item in existing_history_raw if isinstance(item, dict)]
        plan_history = [
            *existing_history,
            {
                "plan_id": plan_id,
                "title": plan_output.title,
                "path": plan_path,
                "created_at": created_at,
                "status": plan_status,
            },
        ][-40:]

        plan_dict: dict[str, Any] = {
                "plan_id": plan_id,
                "status": plan_status,
                "title": plan_output.title,
                "objective": plan_output.objective,
                "summary": plan_output.summary,
                "assumptions": plan_output.assumptions,
                "constraints": plan_output.constraints,
                "risks": plan_output.risks,
                "acceptance_criteria": plan_output.acceptance_criteria,
                "domain": plan_output.domain,
                "todo_ids": [node["id"] for node in nodes],
                "plan_path": plan_path,
                "latest_alias_path": latest_alias_path,
                "clarifications": clarifications_payload,
                "clarification_pending": clarification_pending,
                "clarification_index": 0,
                "clarification_answers": [],
                "clarification_resolved": not clarification_pending,
                "clarification_question": primary_clarification.question if primary_clarification else None,
                "created_at": created_at,
                # Plan editing bookkeeping: revision starts at 0 for new plans
                # and is bumped on each in-place re-plan. human_messages_at_plan
                # records the HumanMessage count at this revision so future
                # re-plan checks can detect a fresh user turn (see _should_plan).
                "revision": revision,
                "human_messages_at_plan": sum(
                    1 for msg in (state.get("messages") or []) if getattr(msg, "type", None) == "human"
                ),
                "updated_at": _utc_now_iso(),
            }
        if approved_at:
            plan_dict["approved_at"] = approved_at
            plan_dict["awaiting_execution_approval"] = False
        elif plan_status == "draft":
            plan_dict["awaiting_execution_approval"] = True

        payload: dict[str, Any] = {
            "plan": plan_dict,
            "plan_history": plan_history,
            "todo_graph": {"nodes": nodes, "ready_ids": ready_ids, "updated_at": _utc_now_iso()},
            "todos": _legacy_todos(nodes),
            "handoff_artifacts": [p for p in [plan_path, latest_alias_path] if p],
            "artifacts": artifact_paths,
            "plan_evaluated": False,
            "planner_ephemeral_handoff": planner_handoff.content,
            "planner_ephemeral_clarification": clarification_prompt_message.content if clarification_prompt_message is not None else None,
        }

        if should_spawn_work_handoff(plan_dict, plan_behavior=_plan_behavior(runtime), plan_status=plan_status):
            payload = self._finalize_plan_handoff(
                payload=payload,
                plan_dict=plan_dict,
                runtime=runtime,
                auto_mode=auto_mode,
                user_prompt=user_prompt,
                thread_name_suffix="-planner-auto",
                clarification_pending=clarification_pending,
            )
        # Fresh-plan semantics: in plan_foreground mode, always halt the
        # planning turn after producing a plan so the user can review (even
        # for draft plans where no handoff fires). Skip the halt when a
        # clarification is pending because the planner explicitly wants the
        # next turn to surface the clarification prompt.
        if not clarification_pending and _plan_behavior(runtime) == "plan_foreground":
            payload["jump_to"] = "end"
        return payload

    @override
    async def abefore_model(self, state: PlannerState, runtime: Runtime) -> dict | None:
        # Run the sync `before_model` in a worker thread so the LangGraph Server
        # event loop stays free while the planner LLM runs. Without this, a slow
        # planner blocks SSE writers, healthchecks, and other coroutines on the
        # same loop worker for the duration of the planning turn.
        return await asyncio.to_thread(self.before_model, state, runtime)

# End the planning turn before the lead model runs while the plan is still draft.
PlannerMiddleware.before_model.__can_jump_to__ = ["end"]  # type: ignore[attr-defined]
PlannerMiddleware.abefore_model.__can_jump_to__ = ["end"]  # type: ignore[attr-defined]
