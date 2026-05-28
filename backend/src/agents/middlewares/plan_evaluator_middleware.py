"""Plan evaluator middleware — quality check on planner output before execution.

Pipeline:
  1. Deterministic pre-check ([_precheck_nodes]) — drops dangling deps and
     normalises IDs, short-circuits on cycles. The LLM only sees structurally
     valid plans, so its budget goes toward judgement calls.
  2. LLM evaluation prompted with domain, acceptance criteria, and rich todo
     fields. Output contract: `{ok, issues, advice, patch}` where `patch` is a
     list of `{op: modify|add|remove, ...}` operations applied via
     `merge_todo_nodes`. Legacy `revised_todos` (full replacement) is still
     accepted for back-compat.
  3. Re-evaluation loop bounded by `EvaluatorConfig.max_attempts`. A patch that
     yields a still-failing plan is re-evaluated up to the cap, then we
     proceed with whatever we have and emit `decision=max_attempts_reached`.

Async path uses `asyncio.wait_for` directly so the event loop is free during
local LLM token generation; the sync path keeps a daemon-thread fallback for
embedded callers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.agents.middlewares._timeout_utils import run_with_timeout
from src.agents.middlewares.runtime_events import append_runtime_event
from src.agents.middlewares.todo_dag_middleware import (
    _is_acyclic,
    _legacy_todos,
    _materialize_ready_ids,
    merge_todo_nodes,
    normalize_todo_nodes,
)
from src.config.evaluator_config import get_evaluator_config
from src.models import create_chat_model, resolve_model_name

logger = logging.getLogger(__name__)

_TODO_ID_RE = re.compile(r"^todo-\d+$")

_DOMAIN_RULES: dict[str, str] = {
    "code": "Test todos must depend on the implementation todos they cover.",
    "research": "Synthesis / write-up todos must depend on all research-gathering todos.",
    "legal": "Analysis todos must depend on document-reading todos.",
    "trip": "Booking todos must depend on visa / permit todos when applicable.",
    "generic": "No domain-specific dependency rules apply.",
}

_PLAN_EVAL_PROMPT = """\
You are a plan quality reviewer. Evaluate the execution plan below and either
approve it or return a targeted patch that fixes specific problems.

Return ONLY valid JSON — no prose, no markdown fences:
{
  "ok": true,
  "issues": [],
  "advice": "",
  "patch": []
}

If the plan is acceptable, return {"ok": true} and nothing else.

If you find genuine problems:
- List each issue briefly in "issues" (max 3 issues).
- Write a 1-3 sentence "advice" explaining what should change and why.
- Provide a "patch" array of operations rather than a full plan rewrite:
    {"op": "modify", "id": "todo-3", "fields": {"depends_on": ["todo-1"], "failure_fallback": "..."}}
    {"op": "add", "after_id": "todo-2", "todo": { /* full todo schema */ }}
    {"op": "remove", "id": "todo-5"}
- Touch only the todos that need changing. Untouched todos are preserved verbatim.
- When using "modify", do NOT strip rich fields (objective, failure_fallback,
  steps[].completion_requirement) that the original todo had — only set them
  to a new value when you mean to update them.

Plan to evaluate:
Title: {title}
Domain: {domain}
Summary: {summary}
Acceptance criteria:
{acceptance_criteria_formatted}
Todos:
{todos_formatted}

Check for:
1. Acceptance-criteria coverage — every acceptance criterion must map to at
   least one todo's `completion_requirement` (todo-level or steps[].). Flag
   uncovered criteria.
2. Missing prerequisite todos (e.g., auth/setup step before API calls).
3. Missing final delivery / synthesis step for multi-step plans.
4. Domain rules for `{domain}`: {domain_rule}
5. Rich-field gaps for non-trivial work — todos missing `objective`,
   `failure_fallback`, or any `steps[].completion_requirement`.

Structural checks (cycles, dangling deps, duplicate IDs, ID format) have
already been validated in code — do not flag these.

Be lenient on style and word choice; be strict on coverage and verifiability.
"""


class PlanEvaluatorState(AgentState):
    plan: NotRequired[dict | None]
    todo_graph: NotRequired[dict | None]
    plan_evaluated: NotRequired[bool]
    plan_eval_attempts: NotRequired[int]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _format_acceptance_criteria(criteria: list[str]) -> str:
    if not criteria:
        return "  (none specified)"
    return "\n".join(f"  - {c}" for c in criteria)


def _format_todos_for_eval(nodes: list[dict[str, Any]], rich_by_id: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    for node in nodes:
        node_id = str(node.get("id", ""))
        dep_str = f"  (depends_on={node.get('depends_on')})" if node.get("depends_on") else ""
        lines.append(f"[{node_id}] {node.get('content')}{dep_str}")

        rich = rich_by_id.get(node_id, {})

        def _field(key: str) -> str:
            value = node.get(key) or rich.get(key)
            return str(value or "").strip()

        objective = _field("objective")
        if objective:
            lines.append(f"  objective: {objective}")
        rationale = _field("rationale")
        if rationale:
            lines.append(f"  rationale: {rationale}")
        failure_fallback = _field("failure_fallback")
        if failure_fallback:
            lines.append(f"  failure_fallback: {failure_fallback}")
        todo_completion = _field("completion_requirement")
        if todo_completion:
            lines.append(f"  completion_requirement: {todo_completion}")

        steps = node.get("steps") or rich.get("steps") or []
        if isinstance(steps, list) and steps:
            lines.append("  steps:")
            for i, step in enumerate(steps, start=1):
                if not isinstance(step, dict):
                    continue
                desc = str(step.get("description") or "").strip() or f"step {i}"
                done = str(step.get("completion_requirement") or "").strip()
                suffix = f" → done when: {done}" if done else ""
                lines.append(f"    {i}. {desc}{suffix}")
    return "\n".join(lines)


def _build_rich_by_id(plan: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The planner stores rich todo fields transiently; only some survive into
    `todo_graph["nodes"]`. Build a side-map from `plan["todos"]` if present so
    we can surface them in the eval prompt even when the node lacks them."""
    if not isinstance(plan, dict):
        return {}
    raw = plan.get("todos")
    if not isinstance(raw, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("id") or "").strip()
        if node_id:
            out[node_id] = item
    return out


def _precheck_nodes(nodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Deterministic structural validation.

    Returns (cleaned_nodes, fixes_applied, fatal). `fatal=True` means the plan
    has a cycle (or some other structural defect we can't safely repair) and
    the caller should skip the LLM call and route back to the planner.
    """
    fixes: list[str] = []
    if not nodes:
        return nodes, fixes, False

    # 1. Duplicate IDs — rename collisions with a numeric suffix.
    seen: dict[str, int] = {}
    cleaned: list[dict[str, Any]] = []
    for node in nodes:
        new_node = dict(node)
        node_id = str(new_node.get("id") or "").strip()
        if not node_id:
            node_id = f"todo-{len(cleaned) + 1}"
            new_node["id"] = node_id
            fixes.append("assigned missing todo id")
        if node_id in seen:
            seen[node_id] += 1
            new_id = f"{node_id}-{seen[node_id]}"
            fixes.append(f"renamed duplicate id {node_id!r} → {new_id!r}")
            new_node["id"] = new_id
            seen[new_id] = 1
        else:
            seen[node_id] = 1
        cleaned.append(new_node)

    valid_ids = {str(n["id"]) for n in cleaned}

    # 2. ID format conformance — re-number anything that doesn't match.
    if not all(_TODO_ID_RE.match(str(n["id"])) for n in cleaned):
        remap: dict[str, str] = {}
        for index, node in enumerate(cleaned):
            current = str(node["id"])
            canonical = f"todo-{index + 1}"
            if current != canonical:
                # Avoid colliding with an existing canonical id of a later node.
                if canonical in valid_ids and canonical != current:
                    canonical = f"todo-{index + 1}-x"
                remap[current] = canonical
                node["id"] = canonical
                fixes.append(f"renumbered id {current!r} → {canonical!r}")
        if remap:
            # Rewire depends_on to follow the rename.
            for node in cleaned:
                deps = [remap.get(d, d) for d in (node.get("depends_on") or [])]
                node["depends_on"] = deps
            valid_ids = {str(n["id"]) for n in cleaned}

    # 3. Dangling depends_on — drop them.
    for node in cleaned:
        deps = [d for d in (node.get("depends_on") or []) if d in valid_ids and d != node["id"]]
        if deps != list(node.get("depends_on") or []):
            fixes.append(f"trimmed dangling depends_on on {node['id']!r}")
        node["depends_on"] = deps

    # 4. Cycle detection — fatal, we don't try to auto-resolve.
    if not _is_acyclic(cleaned):
        return cleaned, fixes, True

    return cleaned, fixes, False


def _strip_markdown_fences(raw: str) -> str:
    if not raw.startswith("```"):
        return raw
    lines = raw.splitlines()
    if not lines:
        return raw
    body = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
    return "\n".join(body)


def _apply_patch(nodes: list[dict[str, Any]], patch: list[Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]] | None:
    """Apply a patch op list against `nodes`. Returns the new node list plus
    a map of `id → original rich fields` for the post-patch preservation guard.
    Returns None on malformed patch input."""
    if not isinstance(patch, list):
        return None

    rich_snapshot: dict[str, dict[str, Any]] = {
        str(n["id"]): {k: n[k] for k in ("objective", "failure_fallback", "completion_requirement", "steps") if k in n}
        for n in nodes
    }

    # Process removes first so subsequent adds/modifies don't see stale ids.
    surviving = list(nodes)
    raw_updates: list[dict[str, Any]] = []
    appends: list[dict[str, Any]] = []

    for op in patch:
        if not isinstance(op, dict):
            return None
        action = str(op.get("op") or "").lower()
        if action == "remove":
            target_id = str(op.get("id") or "").strip()
            if not target_id:
                return None
            surviving = [n for n in surviving if str(n.get("id")) != target_id]
            rich_snapshot.pop(target_id, None)
        elif action == "modify":
            target_id = str(op.get("id") or "").strip()
            fields = op.get("fields")
            if not target_id or not isinstance(fields, dict):
                return None
            raw_updates.append({"id": target_id, **fields})
        elif action == "add":
            todo = op.get("todo")
            if not isinstance(todo, dict):
                return None
            appends.append(todo)
        else:
            return None

    # merge_todo_nodes treats unseen ids as appends, so combining updates +
    # appends in one call gives us patch-by-id semantics for free.
    merged_input = raw_updates + appends
    if not merged_input and surviving == nodes:
        # Empty patch.
        return surviving, rich_snapshot

    merged = merge_todo_nodes(surviving, merged_input)
    return merged, rich_snapshot


def _preserves_rich_fields(new_nodes: list[dict[str, Any]], original_rich: dict[str, dict[str, Any]]) -> tuple[bool, str | None]:
    """Reject patches that nuke rich fields on todos that had them."""
    by_id = {str(n["id"]): n for n in new_nodes}
    for node_id, original in original_rich.items():
        if node_id not in by_id:
            # The patch removed the todo entirely — fine, that's an explicit op.
            continue
        node = by_id[node_id]
        for key in ("objective", "failure_fallback", "completion_requirement"):
            if original.get(key) and not node.get(key):
                return False, f"patch stripped {key!r} from {node_id!r}"
        if original.get("steps") and not node.get("steps"):
            return False, f"patch stripped 'steps' from {node_id!r}"
    return True, None


class PlanEvaluatorMiddleware(AgentMiddleware[PlanEvaluatorState]):
    """Quality-check the plan, optionally apply a patch, re-evaluate up to a
    configured attempt cap. See module docstring for the full flow."""

    state_schema = PlanEvaluatorState

    def __init__(
        self,
        *,
        requested_model: str | None,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
        router: Any = None,
    ):  # noqa: ARG002
        del router
        super().__init__()
        cfg = get_evaluator_config()
        self._requested_model = requested_model
        self._timeout_seconds = float(timeout_seconds if timeout_seconds is not None else cfg.plan_evaluator_timeout_seconds)
        self._max_attempts = int(max_attempts if max_attempts is not None else cfg.max_attempts)

    # ------------------------------------------------------------------
    # gating
    # ------------------------------------------------------------------

    def _should_evaluate(self, state: PlanEvaluatorState) -> bool:
        if state.get("plan_evaluated"):
            return False
        todo_graph = state.get("todo_graph")
        if not todo_graph:
            return False
        plan = state.get("plan")
        return bool(plan)

    # ------------------------------------------------------------------
    # prompt + model setup
    # ------------------------------------------------------------------

    def _build_prompt(self, plan: dict[str, Any], nodes: list[dict[str, Any]]) -> str:
        title = str(plan.get("title") or "Execution Plan")
        summary = str(plan.get("summary") or "")
        domain = str(plan.get("domain") or "generic").lower().strip() or "generic"
        domain_rule = _DOMAIN_RULES.get(domain, _DOMAIN_RULES["generic"])
        acceptance = [str(c).strip() for c in (plan.get("acceptance_criteria") or []) if str(c).strip()]
        rich_by_id = _build_rich_by_id(plan)
        return (
            _PLAN_EVAL_PROMPT.replace("{title}", title)
            .replace("{domain}", domain)
            .replace("{summary}", summary)
            .replace("{domain_rule}", domain_rule)
            .replace("{acceptance_criteria_formatted}", _format_acceptance_criteria(acceptance))
            .replace("{todos_formatted}", _format_todos_for_eval(nodes, rich_by_id))
        )

    def _model_name(self) -> str:
        return resolve_model_name(self._requested_model)

    # ------------------------------------------------------------------
    # LLM call wrappers — sync (daemon thread timeout) and async (wait_for)
    # ------------------------------------------------------------------

    def _call_sync(self, prompt: str, model_name: str) -> tuple[str | None, str | None]:
        """Returns `(raw, error_kind)`. `error_kind` is None on success,
        otherwise "timeout" or "exception"."""
        def _do_call() -> str:
            model = create_chat_model(name=model_name, thinking_enabled=False)
            response = model.invoke(prompt)
            raw = response.content if isinstance(response.content, str) else str(response.content)
            return raw.strip()

        try:
            return run_with_timeout(_do_call, timeout=self._timeout_seconds, label="Plan evaluator"), None
        except TimeoutError:
            logger.warning("Plan evaluator timed out; skipping further attempts")
            return None, "timeout"
        except Exception:
            logger.exception("Plan evaluator LLM call failed")
            return None, "exception"

    async def _call_async(self, prompt: str, model_name: str) -> tuple[str | None, str | None]:
        async def _do_call() -> str:
            model = create_chat_model(name=model_name, thinking_enabled=False)
            response = await model.ainvoke(prompt)
            raw = response.content if isinstance(response.content, str) else str(response.content)
            return raw.strip()

        try:
            return await asyncio.wait_for(_do_call(), timeout=self._timeout_seconds), None
        except TimeoutError:
            logger.warning("Plan evaluator timed out; skipping further attempts")
            return None, "timeout"
        except Exception:
            logger.exception("Plan evaluator LLM call failed")
            return None, "exception"

    # ------------------------------------------------------------------
    # response handling — pure, shared between sync/async loops
    # ------------------------------------------------------------------

    def _parse_response(self, raw: str | None) -> dict[str, Any] | None:
        if not raw:
            return None
        cleaned = _strip_markdown_fences(raw)
        try:
            payload = json.loads(cleaned)
        except Exception:
            logger.warning("Plan evaluator returned non-JSON")
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _apply_response(
        self,
        payload: dict[str, Any],
        nodes: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]] | None, str]:
        """Return (new_nodes_or_None, decision_label).

        * `(None, "ok")` — plan accepted, no change.
        * `(nodes, "issues_no_revision")` — issues but no patch/revision provided.
        * `(new_nodes, "revised")` — patch (or legacy revised_todos) applied successfully.
        * `(None, "revision_invalid")` — patch malformed or stripped rich fields.
        """
        ok = bool(payload.get("ok", True))
        issues = list(payload.get("issues") or [])
        if ok or not issues:
            return None, "ok"

        # Prefer new patch contract; fall back to legacy revised_todos.
        patch = payload.get("patch")
        revised_todos = payload.get("revised_todos")

        if isinstance(patch, list) and patch:
            applied = _apply_patch(nodes, patch)
            if applied is None:
                logger.warning("Plan evaluator returned malformed patch; ignoring")
                return None, "revision_invalid"
            new_nodes, rich_snapshot = applied
            preserved, why = _preserves_rich_fields(new_nodes, rich_snapshot)
            if not preserved:
                logger.warning("Plan evaluator patch rejected: %s", why)
                return None, "revision_invalid"
            try:
                # Re-normalise — catches cycles introduced by the patch.
                normalised = normalize_todo_nodes(new_nodes)
            except Exception:
                logger.warning("Plan evaluator patch produced invalid graph")
                return None, "revision_invalid"
            return normalised, "revised"

        if isinstance(revised_todos, list) and revised_todos:
            try:
                normalised = normalize_todo_nodes(revised_todos)
            except Exception:
                logger.warning("Plan evaluator provided invalid revised_todos; ignoring revision")
                return None, "revision_invalid"
            # Legacy contract — rich-field preservation can't be checked
            # against original because the LLM returned a full replacement.
            return normalised, "revised"

        return None, "issues_no_revision"

    def _commit_revision(self, new_nodes: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "todo_graph": {
                "nodes": new_nodes,
                "ready_ids": _materialize_ready_ids(new_nodes),
                "updated_at": _utc_now_iso(),
            },
            "todos": _legacy_todos(new_nodes),
        }

    # ------------------------------------------------------------------
    # main entry points
    # ------------------------------------------------------------------

    def _prepare(
        self, state: PlanEvaluatorState, runtime: Runtime
    ) -> tuple[dict[str, Any], list[dict[str, Any]], bool, dict[str, Any] | None]:
        """Run pre-checks. Returns (plan, nodes, nodes_changed, terminal_payload).
        If `terminal_payload` is not None the caller should return it directly
        (e.g. cycle detected — skip the LLM)."""
        plan = state["plan"]  # type: ignore[index]
        todo_graph = state["todo_graph"]  # type: ignore[index]
        original_nodes: list[dict[str, Any]] = list(todo_graph.get("nodes") or [])  # type: ignore[union-attr]

        cleaned, fixes, fatal = _precheck_nodes(original_nodes)

        if fatal:
            append_runtime_event(
                runtime,
                {
                    "source": "plan_evaluator",
                    "decision": "cycle_detected",
                    "issues": ["dependency cycle in plan"],
                    "model": self._model_name(),
                },
            )
            return plan, cleaned, False, {"plan_evaluated": True}

        if fixes:
            append_runtime_event(
                runtime,
                {
                    "source": "plan_evaluator",
                    "decision": "prechecked_fixed",
                    "fixes": fixes,
                    "model": self._model_name(),
                },
            )

        return plan, cleaned, bool(fixes), None

    def _record_decision(self, runtime: Runtime, decision: str, payload: dict[str, Any], model_name: str) -> None:
        event = {"source": "plan_evaluator", "decision": decision, "model": model_name}
        event.update(payload)
        append_runtime_event(runtime, event)

    @override
    def before_model(self, state: PlanEvaluatorState, runtime: Runtime) -> dict | None:
        if not self._should_evaluate(state):
            return None

        plan, nodes, nodes_changed, terminal = self._prepare(state, runtime)
        if terminal is not None:
            return terminal
        if not nodes:
            return {"plan_evaluated": True}

        attempts = int(state.get("plan_eval_attempts") or 0)
        model_name = self._model_name()
        accumulated_issues: list[str] = []
        last_advice = ""
        last_decision = "ok"

        while attempts < self._max_attempts:
            attempts += 1
            prompt = self._build_prompt(plan, nodes)
            raw, err = self._call_sync(prompt, model_name)
            if err == "timeout":
                last_decision = "timeout_skipped"
                self._record_decision(runtime, last_decision, {"attempts": attempts}, model_name)
                break
            if err == "exception":
                last_decision = "llm_error_skipped"
                self._record_decision(runtime, last_decision, {"attempts": attempts}, model_name)
                break
            payload = self._parse_response(raw)
            if payload is None:
                last_decision = "non_json_skipped"
                self._record_decision(runtime, last_decision, {"attempts": attempts}, model_name)
                break

            new_nodes, decision = self._apply_response(payload, nodes)
            last_decision = decision
            issues = list(payload.get("issues") or [])
            advice = str(payload.get("advice") or "").strip()
            if issues:
                accumulated_issues.extend(issues)
            if advice:
                last_advice = advice

            self._record_decision(
                runtime,
                decision,
                {
                    "attempts": attempts,
                    "issues": issues,
                    "advice": advice,
                    "new_todo_count": len(new_nodes) if new_nodes else None,
                },
                model_name,
            )

            if decision == "ok":
                break
            if decision == "revised" and new_nodes is not None:
                nodes = new_nodes
                nodes_changed = True
                continue
            break

        return self._build_terminal_payload(nodes, nodes_changed, attempts, last_decision, accumulated_issues, last_advice, runtime, model_name)

    @override
    async def abefore_model(self, state: PlanEvaluatorState, runtime: Runtime) -> dict | None:
        if not self._should_evaluate(state):
            return None

        plan, nodes, nodes_changed, terminal = self._prepare(state, runtime)
        if terminal is not None:
            return terminal
        if not nodes:
            return {"plan_evaluated": True}

        attempts = int(state.get("plan_eval_attempts") or 0)
        model_name = self._model_name()
        accumulated_issues: list[str] = []
        last_advice = ""
        last_decision = "ok"

        while attempts < self._max_attempts:
            attempts += 1
            prompt = self._build_prompt(plan, nodes)
            raw, err = await self._call_async(prompt, model_name)
            if err == "timeout":
                last_decision = "timeout_skipped"
                self._record_decision(runtime, last_decision, {"attempts": attempts}, model_name)
                break
            if err == "exception":
                last_decision = "llm_error_skipped"
                self._record_decision(runtime, last_decision, {"attempts": attempts}, model_name)
                break
            payload = self._parse_response(raw)
            if payload is None:
                last_decision = "non_json_skipped"
                self._record_decision(runtime, last_decision, {"attempts": attempts}, model_name)
                break

            new_nodes, decision = self._apply_response(payload, nodes)
            last_decision = decision
            issues = list(payload.get("issues") or [])
            advice = str(payload.get("advice") or "").strip()
            if issues:
                accumulated_issues.extend(issues)
            if advice:
                last_advice = advice

            self._record_decision(
                runtime,
                decision,
                {
                    "attempts": attempts,
                    "issues": issues,
                    "advice": advice,
                    "new_todo_count": len(new_nodes) if new_nodes else None,
                },
                model_name,
            )

            if decision == "ok":
                break
            if decision == "revised" and new_nodes is not None:
                nodes = new_nodes
                nodes_changed = True
                continue
            break

        return self._build_terminal_payload(nodes, nodes_changed, attempts, last_decision, accumulated_issues, last_advice, runtime, model_name)

    def _build_terminal_payload(
        self,
        nodes: list[dict[str, Any]],
        nodes_changed: bool,
        attempts: int,
        last_decision: str,
        accumulated_issues: list[str],
        last_advice: str,
        runtime: Runtime,
        model_name: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"plan_evaluated": True}
        if attempts:
            payload["plan_eval_attempts"] = attempts
        if nodes_changed:
            payload.update(self._commit_revision(nodes))

        if attempts >= self._max_attempts and last_decision not in {"ok", "timeout_skipped", "non_json_skipped", "llm_error_skipped"}:
            self._record_decision(
                runtime,
                "max_attempts_reached",
                {"attempts": attempts, "issues": accumulated_issues, "advice": last_advice},
                model_name,
            )
        return payload


