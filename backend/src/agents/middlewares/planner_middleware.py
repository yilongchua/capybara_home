"""Planner middleware for Phase B Plan-mode runs."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, override
from uuid import uuid4

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime

from src.agents.middlewares.handoff_sync import render_plan_md
from src.agents.middlewares.runtime_events import append_runtime_event
from src.agents.middlewares.todo_dag_middleware import _legacy_todos, normalize_todo_nodes
from src.config.handoffs_config import HandoffsConfig
from src.config.sprint_contracts_config import SprintContractsConfig
from src.models import ModelRouter, create_chat_model
from src.sandbox.path_mapping import to_virtual_path

logger = logging.getLogger(__name__)


class PlannerState(AgentState):
    plan: NotRequired[dict | None]
    todo_graph: NotRequired[dict | None]
    todos: NotRequired[list | None]
    handoff_artifacts: NotRequired[list[str] | None]
    artifacts: NotRequired[list[str] | None]
    complexity_tier: NotRequired[str | None]
    plan_evaluated: NotRequired[bool]
    plan_history: NotRequired[list[dict[str, Any]] | None]


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content)


def _message_type(message: Any) -> str:
    raw = getattr(message, "type", None)
    if isinstance(raw, str):
        return raw
    if isinstance(message, dict):
        val = message.get("type")
        if isinstance(val, str):
            return val
    return ""


def _message_name(message: Any) -> str:
    raw = getattr(message, "name", None)
    if isinstance(raw, str):
        return raw
    if isinstance(message, dict):
        val = message.get("name")
        if isinstance(val, str):
            return val
    return ""


def _pending_clarification_answered(messages: list[Any]) -> bool:
    if not messages:
        return False
    last_ask_idx = -1
    for idx, message in enumerate(messages):
        if _message_type(message) == "tool" and _message_name(message) == "ask_clarification":
            last_ask_idx = idx
    if last_ask_idx < 0:
        return False
    for message in messages[last_ask_idx + 1 :]:
        if _message_type(message) != "human":
            continue
        text = _extract_text(getattr(message, "content", ""))
        if text.strip():
            return True
    return False


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
    trivial: bool = False
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


_YEAR_RANGE_RE = re.compile(r"\b(19|20)\d{2}\b")


def _ordered_clarification_options(options: list[ClarificationOption]) -> list[ClarificationOption]:
    recommended = [option for option in options if option.recommended]
    non_recommended = [option for option in options if not option.recommended]
    return [*recommended[:1], *non_recommended, *recommended[1:]]


def _ensure_research_clarifications(user_prompt: str, output: PlannerOutput) -> list[PlannerClarification]:
    clarifications: list[PlannerClarification] = list(output.clarifications)
    text = user_prompt.lower()
    if output.domain != "research":
        return clarifications

    has_timeframe = bool(_YEAR_RANGE_RE.search(user_prompt)) or any(token in text for token in ("today", "latest", "recent", "last ", "this year", "past ", "since "))
    has_scope = any(
        token in text
        for token in (
            "in healthcare",
            "in finance",
            "in education",
            "for enterprise",
            "for startups",
            "consumer",
            "global",
            "us",
            "asia",
            "europe",
            "industry",
            "sector",
        )
    )

    if not has_timeframe:
        clarifications.append(
            PlannerClarification(
                question="What timeframe should the research cover?",
                options=[
                    ClarificationOption(label="Last 12 months", recommended=True, description="Balances recency with enough signal."),
                    ClarificationOption(label="Last 3 years", recommended=False, description="Captures medium-term shifts and trend continuity."),
                    ClarificationOption(label="Since 2020", recommended=False, description="Gives broad post-pandemic context."),
                ],
            )
        )

    if ("ai trend" in text or "ai trends" in text) and not has_scope:
        clarifications.append(
            PlannerClarification(
                question="Which AI trend scope should be prioritized?",
                options=[
                    ClarificationOption(label="Cross-industry global trends", recommended=True, description="Best default for a broad strategy brief."),
                    ClarificationOption(label="Industry-specific trends", recommended=False, description="Focuses depth on one sector."),
                    ClarificationOption(label="Regional policy and market trends", recommended=False, description="Emphasizes geography and regulation."),
                ],
            )
        )

    deduped: list[PlannerClarification] = []
    seen_questions: set[str] = set()
    for clarification in clarifications:
        question = clarification.question.strip()
        if not question:
            continue
        key = question.lower()
        if key in seen_questions:
            continue
        seen_questions.add(key)
        options = _ordered_clarification_options(clarification.options)
        if not options:
            continue
        deduped.append(PlannerClarification(question=question, options=options[:4]))
    return deduped[:2]


# ---------------------------------------------------------------------------
# Planner system prompt — domain-aware with real dependency generation
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """\
You are a planning assistant. Produce a structured execution plan for the user's request.

Return ONLY valid JSON matching this exact schema (no prose, no markdown fences):
{
  "trivial": false,
  "title": "Short plan title (≤ 8 words)",
  "objective": "One paragraph objective describing the intended end state.",
  "summary": "1-2 sentence overview of what will be accomplished.",
  "assumptions": ["List core assumptions as concise bullet strings"],
  "constraints": ["List important constraints as concise bullet strings"],
  "risks": [
    {"risk": "Main delivery risk", "mitigation": "Concrete mitigation"}
  ],
  "acceptance_criteria": ["Observable success criterion 1", "Observable success criterion 2"],
  "domain": "code|research|legal|trip|generic",
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
      "subagent_type": null
    }
  ]
}

TRIVIAL SIGNAL — if the request is clearly trivial (single factual lookup, greeting,
simple calculation, definition request), return:
  {"trivial": true}
and nothing else.

DEPENDENCY RULES:
- depends_on lists IDs of todos that MUST complete before this one starts.
- Do NOT create circular dependencies.
- Minimise unnecessary sequencing — only add depends_on when there is a real data dependency.
- For code domain: test todos always depend on the implementation todos they test.
- For research domain: synthesis / write-up todos depend on all research-gathering todos.
- For legal domain: analysis todos depend on document-reading todos.
- For trip domain: booking todos depend on visa / permit todos when applicable.

CLARIFICATION RULES:
- Only ask for clarification when a missing detail would fundamentally change the plan.
- At most 2 clarification questions. Each question must have 3-4 options.
- Mark exactly one option per question as recommended: true.
- Put the recommended option FIRST in the list.

TODO STYLE:
- Start each todo with a clear action verb (Research, Write, Build, Analyse, Review...).
- Keep each todo to one sentence, ≤ 14 words.
- Include a rationale sentence per step.
- Avoid jargon, nested clauses, or stacked subtasks in a single todo.
- Maximum {max_steps} todos.
"""


# ---------------------------------------------------------------------------
# Complexity classification
# ---------------------------------------------------------------------------

_TRIVIAL_KEYWORDS = ("hello", "hi", "what is", "who is", "define", "translate", "convert")
_COMPLEX_KEYWORDS = (
    "plan",
    "analyze",
    "analyse",
    "compare",
    "design",
    "build",
    "implement",
    "refactor",
    "migrate",
    "audit",
    "review",
    "investigate",
    "explore",
    "research",
    "end-to-end",
    "comprehensive",
    "all of",
    "multi-step",
    "trip plan",
    "defence",
    "legal",
    "multiple documents",
    "law",
    "contract",
    "strategy",
    "roadmap",
    "architecture",
    "proposal",
)

_WORD_RE = re.compile(r"\b\w+\b")


def _has_keyword(text: str, keyword: str) -> bool:
    """Match single-word keywords by token, multi-word keywords by substring."""
    if " " in keyword or "-" in keyword:
        return keyword in text
    return keyword in set(_WORD_RE.findall(text))


def _classify_complexity(user_prompt: str) -> str:
    """Returns 'trivial', 'moderate', or 'complex'."""
    text = user_prompt.strip()
    lowered = text.lower()
    if not text or len(text) < 25:
        return "trivial"
    if any(_has_keyword(lowered, kw) for kw in _TRIVIAL_KEYWORDS) and len(text) < 80:
        return "trivial"
    if any(_has_keyword(lowered, kw) for kw in _COMPLEX_KEYWORDS):
        return "complex"
    if len(text) > 300 or "\n" in text:
        return "complex"
    return "moderate"


# Legacy alias used by agent.py harness check
def _looks_trivial(user_prompt: str, *, plan_mode: bool = False) -> bool:  # noqa: ARG001
    return _classify_complexity(user_prompt) == "trivial"


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------


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

    # Trivial signal
    if payload.get("trivial"):
        return PlannerOutput(trivial=True)

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
            }
        )
    if not todos:
        todos = [{"id": "todo-1", "content": "Complete the user request end-to-end.", "status": "pending", "depends_on": [], "owner": "lead", "subagent_type": None}]

    # Parse clarifications
    clarifications: list[PlannerClarification] = []
    if payload.get("requires_clarification"):
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
# Plan file naming
# ---------------------------------------------------------------------------


def _slugify_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:48] or "execution-plan"


def _versioned_plan_filename(title: str, created_at: datetime) -> str:
    stamp = created_at.strftime("%Y%m%d-%H%M%S")
    return f"plan-{stamp}-{_slugify_title(title)}.md"


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_sprint_contract(path: Path, nodes: list[dict[str, Any]]) -> None:
    scope_lines = []
    status_lines = []
    for node in nodes:
        content = str(node.get("content") or "").strip()
        if not content:
            continue
        status = str(node.get("status") or "pending")
        scope_lines.append(f"- {content}")
        status_lines.append(f"- [{status}] {content}")
    scope_block = "\n".join(scope_lines) if scope_lines else "- Complete the user request end-to-end."
    status_block = "\n".join(status_lines) if status_lines else "- [pending] Complete the user request end-to-end."
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Sprint Contract\n\n## Scope\n{scope_block}\n\n## Done Criteria\n- All todos marked completed\n- Final answer includes outcomes and artifacts\n\n## Todo Status\n{status_block}\n",
        encoding="utf-8",
    )


class PlannerMiddleware(AgentMiddleware[PlannerState]):
    """Builds a structured plan and optional sprint contract before execution."""

    state_schema = PlannerState

    def __init__(
        self,
        *,
        router: ModelRouter,
        requested_model: str | None,
        max_plan_steps: int,
        dag_enabled: bool,
        handoffs_config: HandoffsConfig,
        sprint_contracts_config: SprintContractsConfig,
        research_fanout: bool = False,
        research_fanout_min_todos: int = 2,
    ):
        super().__init__()
        self._router = router
        self._requested_model = requested_model
        self._max_plan_steps = max_plan_steps
        self._dag_enabled = dag_enabled
        self._handoffs_config = handoffs_config
        self._sprint_contracts_config = sprint_contracts_config
        self._research_fanout = bool(research_fanout)
        self._research_fanout_min_todos = max(2, int(research_fanout_min_todos))

    def _should_plan(self, state: PlannerState) -> bool:
        if state.get("plan"):
            return False
        if state.get("todo_graph"):
            return False
        messages = state.get("messages", []) or []
        human_count = sum(1 for msg in messages if getattr(msg, "type", None) == "human")
        ai_count = sum(1 for msg in messages if getattr(msg, "type", None) == "ai")
        return human_count >= 1 and ai_count == 0

    def _invoke_planner(self, user_prompt: str) -> tuple[PlannerOutput, str]:
        model_name = self._router.resolve("planner", requested_model=self._requested_model)
        model = create_chat_model(name=model_name, thinking_enabled=False)
        prompt = PLANNER_SYSTEM_PROMPT.replace("{max_steps}", str(self._max_plan_steps))
        full_prompt = f"{prompt}\n\nUser request:\n{user_prompt}"
        response = model.invoke(full_prompt)
        output = _parse_plan_response(_extract_text(response.content), max_steps=self._max_plan_steps)
        return output, model_name

    @override
    def before_model(self, state: PlannerState, runtime: Runtime) -> dict | None:
        current_plan = state.get("plan")
        if isinstance(current_plan, dict) and bool(current_plan.get("clarification_pending")):
            messages = state.get("messages", []) or []
            if _pending_clarification_answered(messages):
                resolved_plan = {
                    **current_plan,
                    "clarification_pending": False,
                    "clarification_answered_at": _utc_now_iso(),
                }
                append_runtime_event(
                    runtime,
                    {
                        "source": "planner_middleware",
                        "decision": "clarification_resolved",
                        "plan_id": resolved_plan.get("plan_id"),
                    },
                )
                return {"plan": resolved_plan}

        if not self._should_plan(state):
            return None

        messages = state.get("messages", []) or []
        latest_user = next((msg for msg in reversed(messages) if getattr(msg, "type", None) == "human"), None)
        if latest_user is None:
            return None
        user_prompt = _extract_text(getattr(latest_user, "content", ""))
        if not user_prompt.strip():
            return None

        # Emit planning_started immediately — fires within ~100ms of request arrival
        try:
            writer = get_stream_writer()
            writer({"type": "planning_started", "source": "planner_middleware"})
        except Exception:
            logger.exception("Failed to emit planning_started SSE")

        # Classify complexity and store in state
        tier = _classify_complexity(user_prompt)
        if tier == "trivial":
            append_runtime_event(runtime, {"source": "planner_middleware", "decision": "skipped_trivial", "prompt_chars": len(user_prompt)})
            return {"complexity_tier": "trivial"}

        # Invoke planner LLM
        try:
            plan_output, planner_model = self._invoke_planner(user_prompt)
        except Exception:
            logger.exception("Planner LLM call failed; skipping planning")
            return None

        if plan_output.trivial:
            append_runtime_event(runtime, {"source": "planner_middleware", "decision": "llm_classified_trivial"})
            return {"complexity_tier": "trivial"}

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
        clarifications = _ensure_research_clarifications(user_prompt, plan_output)
        clarification_pending = len(clarifications) > 0
        primary_clarification = clarifications[0] if clarifications else None

        # Resolve file paths
        thread_data = state.get("thread_data") or {}
        workspace_path = thread_data.get("workspace_path")
        outputs_path = thread_data.get("outputs_path") or (str(Path(workspace_path).parent / "outputs") if workspace_path else None)

        artifact_paths: list[str] = []
        plan_path: str | None = None
        latest_alias_path: str | None = None
        sprint_contract_path: str | None = None
        plan_id = f"plan-{uuid4().hex[:10]}"
        plan_status = "draft"
        created_at_dt = datetime.now(UTC)
        created_at = created_at_dt.isoformat()

        plan_md_content = render_plan_md(
            plan_output.title,
            plan_output.summary,
            nodes,
            domain=plan_output.domain,
            plan_id=plan_id,
            status=plan_status,
            created_at=created_at,
            objective=plan_output.objective,
            assumptions=plan_output.assumptions,
            constraints=plan_output.constraints,
            risks=plan_output.risks,
            acceptance_criteria=plan_output.acceptance_criteria,
        )

        # Write versioned plan file + latest alias.
        if outputs_path:
            plans_dir = Path(outputs_path) / "plans"
            versioned_plan_file = plans_dir / _versioned_plan_filename(plan_output.title, created_at_dt)
            latest_plan_alias_file = Path(outputs_path) / "plan.md"
            try:
                _write_file(versioned_plan_file, plan_md_content)
                _write_file(latest_plan_alias_file, plan_md_content)
                plan_path = to_virtual_path(str(versioned_plan_file), thread_data) or str(versioned_plan_file)
                latest_alias_path = to_virtual_path(str(latest_plan_alias_file), thread_data) or str(latest_plan_alias_file)
                artifact_paths.extend([plan_path, latest_alias_path])
            except Exception:
                logger.exception("Failed to write versioned plan artifacts to outputs/")

        # Also write plan.md to handoffs/ for internal agent reference.
        if self._handoffs_config.enabled and workspace_path:
            handoff_root = Path(workspace_path) / self._handoffs_config.dir
            handoff_plan = handoff_root / "plan.md"
            try:
                _write_file(handoff_plan, plan_md_content)
                if plan_path is None:
                    plan_path = to_virtual_path(str(handoff_plan), thread_data) or str(handoff_plan)
            except Exception:
                logger.exception("Failed to write plan.md to handoffs/")

            if self._sprint_contracts_config.enabled and len(nodes) >= self._sprint_contracts_config.min_todos_trigger:
                handoff_sprint = handoff_root / "sprint_contract.md"
                try:
                    _write_sprint_contract(handoff_sprint, nodes)
                    sprint_contract_path = to_virtual_path(str(handoff_sprint), thread_data) or str(handoff_sprint)
                except Exception:
                    logger.exception("Failed to write sprint_contract.md")

        # Research fan-out detection (opt-in). When enabled and the plan is a
        # research workload with N independent ready todos, surface them to the
        # agent as candidates for parallel `task` subagent dispatch — this lets
        # the lead agent fire off N concurrent research subagents instead of
        # serializing through the main loop. Default off; enable via
        # planner.research_fanout in config.yaml. See thread-cd90decb plan WS3.
        fanout_ids: list[str] = []
        if self._research_fanout and plan_output.domain == "research" and len(ready_ids) >= self._research_fanout_min_todos:
            fanout_ids = [tid for tid in ready_ids if not any(tid == n.get("id") and n.get("depends_on") for n in nodes)]

        append_runtime_event(
            runtime,
            {
                "source": "planner_middleware",
                "decision": "plan_created",
                "todo_count": len(nodes),
                "domain": plan_output.domain,
                "has_deps": any(n.get("depends_on") for n in nodes),
                "has_clarifications": clarification_pending,
                "model": planner_model,
                "fanout_candidates": fanout_ids,
                "fanout_candidates_count": len(fanout_ids),
            },
        )

        fanout_block = ""
        if fanout_ids:
            fanout_block = (
                "\nFanout candidates (independent — eligible for parallel execution once approved): "
                f"{fanout_ids}\n"
                "Execution remains gated until explicit plan approval.\n"
                "When synthesizing fanout results, merge by unique topic/claim, deduplicate overlapping sections, and preserve a single clean heading hierarchy.\n"
            )

        planner_handoff = HumanMessage(
            name="planner_handoff",
            content=(
                f"<planner_handoff>\n"
                f"Title: {plan_output.title}\n"
                f"Plan ID: {plan_id}\n"
                f"Domain: {plan_output.domain}\n"
                f"Summary: {plan_output.summary}\n"
                f"Planned todos: {len(nodes)}\n"
                f"Ready to start: {ready_ids}\n"
                f"Clarification required: {'yes' if clarification_pending else 'no'}\n"
                "Plan status: draft (execution is gated until explicit execute action).\n"
                f"{fanout_block}</planner_handoff>"
            ),
        )

        clarification_prompt_message = None
        if primary_clarification is not None:
            option_labels = [option.label for option in primary_clarification.options if option.label.strip()]
            clarification_prompt_message = HumanMessage(
                name="planner_clarification_required",
                content=(
                    "<planner_clarification>\n"
                    "Before any execution, ask the user this clarification via `ask_clarification`.\n"
                    f"Question: {primary_clarification.question}\n"
                    f"Options: {option_labels}\n"
                    "</planner_clarification>"
                ),
            )

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
                "todo_count": len(nodes),
                "first_todos": [n.get("content", "") for n in nodes[:5]],
                "plan_path": plan_path,
                "clarification_pending": clarification_pending,
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

        return {
            "plan": {
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
                "sprint_contract_path": sprint_contract_path,
                "clarifications": [
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
                ],
                "clarification_pending": clarification_pending,
                "clarification_question": primary_clarification.question if primary_clarification else None,
                "created_at": created_at,
            },
            "plan_history": plan_history,
            "todo_graph": {"nodes": nodes, "ready_ids": ready_ids, "updated_at": _utc_now_iso()},
            "todos": _legacy_todos(nodes),
            "handoff_artifacts": [p for p in [plan_path, latest_alias_path, sprint_contract_path] if p],
            "artifacts": artifact_paths,
            "complexity_tier": tier,
            "plan_evaluated": False,
            "messages": [message for message in [planner_handoff, clarification_prompt_message] if message is not None],
        }

    @override
    async def abefore_model(self, state: PlannerState, runtime: Runtime) -> dict | None:
        return self.before_model(state, runtime)
