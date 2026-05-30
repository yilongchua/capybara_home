"""Plan-mode agent factory.

The plan_agent owns the planning turn: scope discovery, plan drafting, and
producing the canonical ``plan.md`` that the work_agent later parses on
handoff. It shares all infrastructure (sandbox, memory, model factory, tool
loader) with work_agent, but is invoked as a distinct LangGraph entry point
(graph id ``plan_agent``) so the frontend's manual toggle (Shift+Tab) can
route there directly. Work Mode never auto-escalates to Plan Mode anymore;
entry is fully user-initiated.

Today this is a thin wrapper around :func:`src.agents.work_agent.make_work_agent`
that forces ``current_mode='plan'`` in the configurable. The middleware
registry inside the work-agent factory already conditionally activates
plan-mode middlewares (``PlannerMiddleware``, ``PlanEvaluatorMiddleware``,
``PlanExecutionGateMiddleware``, ``PlanFileSyncMiddleware``,
``TodoDagMiddleware``) when ``is_plan_mode=True``, so a separate factory body
isn't required for parity.

Future divergence (step 7+ of the migration plan): plan_agent will get its own
standalone prompt and tool/skill catalog, at which point this wrapper grows
its own ``create_agent`` call rather than delegating.
"""

from langchain_core.runnables import RunnableConfig

from src.agents.plan_agent.prompt import apply_prompt_template as plan_apply_prompt_template
from src.agents.work_agent.agent import _build_work_agent


def make_plan_agent(config: RunnableConfig):
    cfg = dict(config.get("configurable") or {})
    cfg["current_mode"] = "plan"
    # Legacy dual-write; the writers in step 2 set these too, but force them
    # here so a caller that addresses the graph by name without setting mode
    # still gets plan-mode behavior.
    cfg["is_plan_mode"] = True
    cfg["mode"] = "plan"
    cfg["plan_behavior"] = cfg.get("plan_behavior") or "plan_foreground"
    forced_config: RunnableConfig = {**config, "configurable": cfg}
    # Inject the plan-mode prompt template via the internal builder so we
    # bypass the strict single-arg signature of the graph entry point.
    return _build_work_agent(forced_config, prompt_template_fn=plan_apply_prompt_template)
