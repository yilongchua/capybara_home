"""Render two end-to-end flow diagrams as PNG using Pillow.

Outputs:
  - work_mode_flow_no_plan.png      (Flow A: Work Mode, complex query, no plan)
  - plan_mode_flow_end_to_end.png   (Flow B: Plan Mode end-to-end)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Font loading
# ---------------------------------------------------------------------------

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Box primitives
# ---------------------------------------------------------------------------

@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int
    title: str
    subtitle: str = ""
    fill: str = "#E8F0FE"
    border: str = "#1A73E8"
    title_color: str = "#0B3D91"
    subtitle_color: str = "#333333"
    shape: str = "rect"  # rect | round | diamond | ellipse | hex
    radius: int = 14

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    @property
    def top(self) -> tuple[int, int]:
        return (self.cx, self.y)

    @property
    def bottom(self) -> tuple[int, int]:
        return (self.cx, self.y + self.h)

    @property
    def left(self) -> tuple[int, int]:
        return (self.x, self.cy)

    @property
    def right(self) -> tuple[int, int]:
        return (self.x + self.w, self.cy)


def draw_box(draw: ImageDraw.ImageDraw, b: Box, fnt_title, fnt_sub):
    if b.shape == "rect":
        draw.rounded_rectangle([b.x, b.y, b.x + b.w, b.y + b.h], radius=b.radius,
                               fill=b.fill, outline=b.border, width=2)
    elif b.shape == "ellipse":
        draw.ellipse([b.x, b.y, b.x + b.w, b.y + b.h],
                     fill=b.fill, outline=b.border, width=2)
    elif b.shape == "diamond":
        pts = [(b.cx, b.y), (b.x + b.w, b.cy), (b.cx, b.y + b.h), (b.x, b.cy)]
        draw.polygon(pts, fill=b.fill, outline=b.border)
        # extra outline thickness
        draw.line(pts + [pts[0]], fill=b.border, width=2)
    elif b.shape == "hex":
        off = b.h // 2
        pts = [
            (b.x + off, b.y),
            (b.x + b.w - off, b.y),
            (b.x + b.w, b.cy),
            (b.x + b.w - off, b.y + b.h),
            (b.x + off, b.y + b.h),
            (b.x, b.cy),
        ]
        draw.polygon(pts, fill=b.fill, outline=b.border)
        draw.line(pts + [pts[0]], fill=b.border, width=2)

    # Title text (centered)
    title_lines = b.title.split("\n")
    sub_lines = [l for l in b.subtitle.split("\n") if l] if b.subtitle else []
    line_h_title = fnt_title.size + 4
    line_h_sub = fnt_sub.size + 2
    total_h = line_h_title * len(title_lines) + line_h_sub * len(sub_lines)
    y = b.cy - total_h // 2
    for tl in title_lines:
        tw = draw.textlength(tl, font=fnt_title)
        draw.text((b.cx - tw // 2, y), tl, fill=b.title_color, font=fnt_title)
        y += line_h_title
    for sl in sub_lines:
        tw = draw.textlength(sl, font=fnt_sub)
        draw.text((b.cx - tw // 2, y), sl, fill=b.subtitle_color, font=fnt_sub)
        y += line_h_sub


def draw_arrow(draw: ImageDraw.ImageDraw, p1: tuple[int, int], p2: tuple[int, int],
               color: str = "#444444", width: int = 2, label: str = "",
               fnt=None, label_color: str = "#222222",
               label_offset: tuple[int, int] = (0, -14), dashed: bool = False):
    if dashed:
        _dashed_line(draw, p1, p2, color, width)
    else:
        draw.line([p1, p2], fill=color, width=width)
    # arrowhead
    import math
    angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    size = 10
    a1 = (p2[0] - size * math.cos(angle - math.pi / 7),
          p2[1] - size * math.sin(angle - math.pi / 7))
    a2 = (p2[0] - size * math.cos(angle + math.pi / 7),
          p2[1] - size * math.sin(angle + math.pi / 7))
    draw.polygon([p2, a1, a2], fill=color)
    if label and fnt is not None:
        mx = (p1[0] + p2[0]) // 2 + label_offset[0]
        my = (p1[1] + p2[1]) // 2 + label_offset[1]
        # white halo behind label
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                draw.text((mx + dx, my + dy), label, fill="white", font=fnt)
        draw.text((mx, my), label, fill=label_color, font=fnt)


def _dashed_line(draw, p1, p2, color, width):
    import math
    x1, y1 = p1; x2, y2 = p2
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist == 0:
        return
    dx = (x2 - x1) / dist; dy = (y2 - y1) / dist
    seg = 8; gap = 5
    d = 0.0
    while d < dist:
        a = (x1 + dx * d, y1 + dy * d)
        b = (x1 + dx * min(d + seg, dist), y1 + dy * min(d + seg, dist))
        draw.line([a, b], fill=color, width=width)
        d += seg + gap


def draw_elbow(draw: ImageDraw.ImageDraw, p1, p2, color="#444444", width=2,
               label: str = "", fnt=None, label_color: str = "#222222",
               via: str = "v", dashed: bool = False):
    """L-shaped connector. via='v' means go vertical then horizontal."""
    if via == "v":
        mid = (p1[0], p2[1])
    else:
        mid = (p2[0], p1[1])
    if dashed:
        _dashed_line(draw, p1, mid, color, width)
    else:
        draw.line([p1, mid], fill=color, width=width)
    draw_arrow(draw, mid, p2, color=color, width=width, label=label, fnt=fnt,
               label_color=label_color, dashed=dashed)


# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

C_USER     = ("#FFF4E5", "#E07B00", "#7A3D00")   # user/external
C_GRAPH    = ("#E3F2FD", "#1565C0", "#0D3D7A")   # langgraph entry
C_MID      = ("#E8F5E9", "#2E7D32", "#1B4D1F")   # middleware
C_MODEL    = ("#F3E5F5", "#7B1FA2", "#4A0072")   # LLM model
C_TOOL     = ("#FFF3E0", "#EF6C00", "#8A3D00")   # tool execution
C_DECISION = ("#FFFDE7", "#F9A825", "#7A5300")   # decision/diamond
C_PLAN     = ("#FCE4EC", "#C2185B", "#7A0E3B")   # plan/storage
C_END      = ("#ECEFF1", "#455A64", "#263238")   # end terminal
C_GATE     = ("#FFEBEE", "#C62828", "#7A0F10")   # gate/filter


# ===========================================================================
# Flow A: Work Mode (no plan, complex query)
# ===========================================================================

def render_work_mode_no_plan():
    W, H = 1800, 2100
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_title = _load_font(28, bold=True)
    f_h = _load_font(18, bold=True)
    f_sub = _load_font(13)
    f_lbl = _load_font(13, bold=True)
    f_legend = _load_font(13)

    # Title
    d.text((40, 30), "Work Mode — Complex User Message (No Plan)",
           fill="#0B3D91", font=f_title)
    d.text((40, 70),
           "End-to-end flow from user message to final output. Plan-mode middlewares are inactive (is_plan_mode=False).",
           fill="#333333", font=f_sub)

    # Lanes (rough vertical bands by responsibility)
    lane_x = [60, 660, 1200]  # left | center | right

    BW, BH = 480, 86   # standard box
    SW, SH = 360, 60   # small box

    boxes: dict[str, Box] = {}

    def add(name: str, x: int, y: int, w: int, h: int, title: str,
            subtitle: str = "", color=C_MID, shape="rect"):
        fill, border, title_color = color
        boxes[name] = Box(x, y, w, h, title, subtitle, fill, border, title_color, shape=shape)

    # 1. User
    add("user", lane_x[1], 130, BW, BH,
        "User submits complex message",
        "Frontend (Next.js) → POST /api/langgraph/runs\nmode='work'  (no Shift+Tab)",
        C_USER, "rect")

    # 2. LangGraph server invokes make_work_agent
    add("langgraph", lane_x[1], 260, BW, BH,
        "LangGraph Server invokes work_agent",
        "make_work_agent(config)  langgraph.json: graph 'work_agent'",
        C_GRAPH, "rect")

    # 3. _build_work_agent: model + tools + middlewares
    add("build", lane_x[1], 390, BW, BH,
        "_build_work_agent  (work_agent/agent.py:721)",
        "create_chat_model() · get_available_tools(mode='work')\nloads internal_tools_work.json  (full execution surface)",
        C_GRAPH, "rect")

    # 4. Middleware registry (before_model chain)
    add("pre_mw", lane_x[0], 540, 540, 240,
        "Pre-model middlewares (before_model)",
        "ThreadData → Sandbox → Uploads → MountFolder\nAutoresearch / WriteFileArtifact / DanglingToolCall\nPermission → ToolDisclosure → Hooks\nSummarization → SkillDisclosure → Memory\nViewImage → RetryPolicy → ModelTimeout\nPlanner / PlanEvaluator / TodoDag / Evaluator  ← skipped\n(is_plan_mode=False)",
        C_MID, "rect")

    # 5. PhaseToolFilter (first-turn gate)
    add("phase_filter", 1240, 540, 500, 110,
        "PhaseToolFilterMiddleware  (first-turn gate)",
        "phase_tool_filter_middleware.py\nturn 1 + no plan + no AI msg → HIDE execution tools\n(bash, write_file, web_search, task)",
        C_GATE, "rect")

    # 6. Model call (LLM)
    add("model", lane_x[1], 830, BW, BH,
        "LLM model call",
        "Reasons over user query + system prompt + memory.\nProduces either tool_calls or final text.",
        C_MODEL, "rect")

    # 7. Decision: tool calls?
    add("decide", lane_x[1], 970, BW, BH,
        "Tool calls in response?",
        "If yes → execute tool; if no → finalize",
        C_DECISION, "diamond")

    # 8. Tool execution (ToolNode)
    add("tool_node", 70, 1140, 520, 110,
        "ToolNode runs requested tool",
        "bash · web_search · write_file · task (subagent)\nquery_knowledge_vault · view_image · ...",
        C_TOOL, "rect")

    # 9. After-model middlewares
    add("post_mw", 1200, 1140, 540, 200,
        "Post-model / wrap_tool_call middlewares",
        "ToolResultTruncation · WebSearchCircuitBreaker\nSubagentLimit · TodoFailureRetry  (work-mode only)\nScratchpadTaskMemory · ResumeState\nPlanFollowup\nLoopDetection · RecursionBudgetPivot",
        C_MID, "rect")

    # 10. Loop back to before_model
    add("loop_back", lane_x[1], 1330, BW, BH,
        "Loop: re-enter before_model",
        "From turn 2 → PhaseToolFilter exposes full catalog.\nReAct continues until model emits no tool calls.",
        C_GRAPH, "rect")

    # 11. Clarification intercept (special END branch)
    add("clarify", 60, 1490, 540, 110,
        "ClarificationMiddleware  (last in chain)",
        "If model calls ask_user_for_clarification\n→ Command(goto=END)  · interrupt for user input",
        C_GATE, "rect")

    # 12. Final-text path: trajectory/metrics/title/memory
    add("final_mw", 1180, 1490, 580, 140,
        "Outermost finalization wrappers",
        "TrajectoryMiddleware · ExecutionTraceMiddleware\nActivityTimelineMiddleware · MetricsMiddleware\nTitleMiddleware · QuestionGenerationMiddleware\nMemoryMiddleware  (async fact extraction)",
        C_MID, "rect")

    # 13. Optional plan_adapted SSE (won't fire without plan, shown as note)
    add("stall", 60, 1700, 540, 90,
        "WorkModeMiddleware._handle_plan_adapted",
        "Inactive without plan. With todo_graph and stall →\nemits plan_adapted SSE; user must opt into Plan Mode.",
        C_PLAN, "rect")

    # 14. Final output
    add("output", lane_x[1], 1830, BW, BH,
        "Final assistant response",
        "Streamed via SSE (values + messages-tuple events).\nArtifacts saved in /mnt/user-data/workspace.",
        C_END, "rect")

    # 15. END
    add("end", lane_x[1], 1970, BW, 70,
        "END  (LangGraph terminal node)",
        "",
        C_END, "ellipse")

    # Draw all boxes
    for b in boxes.values():
        draw_box(d, b, f_h, f_sub)

    # Edges
    a = lambda k1, k2, **kw: draw_arrow(d, boxes[k1].bottom, boxes[k2].top, fnt=f_lbl, **kw)

    a("user", "langgraph")
    a("langgraph", "build")
    # build → both pre_mw and phase_filter
    draw_elbow(d, boxes["build"].bottom, boxes["pre_mw"].top, fnt=f_lbl, via="h")
    draw_elbow(d, boxes["build"].bottom, boxes["phase_filter"].top, fnt=f_lbl, via="h")
    # pre_mw → model
    draw_elbow(d, boxes["pre_mw"].right, boxes["model"].left, fnt=f_lbl, via="h",
               label="chain ends → LLM")
    # phase_filter → model (tools filtered)
    draw_elbow(d, boxes["phase_filter"].bottom, boxes["model"].right, fnt=f_lbl, via="v",
               label="filtered tool list")
    # model → decide
    a("model", "decide")
    # decide → tool_node (yes)
    draw_elbow(d, boxes["decide"].left, boxes["tool_node"].top, fnt=f_lbl, via="v",
               label="yes")
    # decide → final_mw (no)
    draw_elbow(d, boxes["decide"].right, boxes["final_mw"].top, fnt=f_lbl, via="v",
               label="no (final text)")
    # tool_node → post_mw
    draw_elbow(d, boxes["tool_node"].right, boxes["post_mw"].left, fnt=f_lbl, via="h",
               label="tool result")
    # post_mw → loop_back
    draw_elbow(d, boxes["post_mw"].bottom, boxes["loop_back"].top, fnt=f_lbl, via="v")
    # loop_back → model (up arrow loop)
    draw_elbow(d, boxes["loop_back"].left, boxes["model"].bottom, fnt=f_lbl, via="h",
               label="ReAct loop", dashed=True)
    # model → clarify (special branch)
    draw_elbow(d, boxes["model"].left, boxes["clarify"].top, fnt=f_lbl, via="v",
               label="ask_user_for_clarification", dashed=True)
    # clarify → end
    draw_elbow(d, boxes["clarify"].bottom, boxes["end"].left, fnt=f_lbl, via="v",
               label="Command(goto=END)")
    # final_mw → output
    draw_elbow(d, boxes["final_mw"].bottom, boxes["output"].top, fnt=f_lbl, via="v")
    # output → end
    a("output", "end")
    # stall note: dashed edge from post_mw to stall
    draw_elbow(d, boxes["post_mw"].left, boxes["stall"].right, fnt=f_lbl, via="v",
               label="inactive (no plan)", dashed=True)

    # Legend
    lx, ly = 60, 100
    d.rectangle([lx, ly, lx + 16, ly + 16], fill=C_USER[0], outline=C_USER[1])
    d.text((lx + 22, ly), "User / External", fill="#333", font=f_legend)
    d.rectangle([lx + 160, ly, lx + 176, ly + 16], fill=C_GRAPH[0], outline=C_GRAPH[1])
    d.text((lx + 182, ly), "Graph / Build", fill="#333", font=f_legend)
    d.rectangle([lx + 320, ly, lx + 336, ly + 16], fill=C_MID[0], outline=C_MID[1])
    d.text((lx + 342, ly), "Middleware", fill="#333", font=f_legend)
    d.rectangle([lx + 460, ly, lx + 476, ly + 16], fill=C_MODEL[0], outline=C_MODEL[1])
    d.text((lx + 482, ly), "LLM", fill="#333", font=f_legend)
    d.rectangle([lx + 560, ly, lx + 576, ly + 16], fill=C_TOOL[0], outline=C_TOOL[1])
    d.text((lx + 582, ly), "Tool exec", fill="#333", font=f_legend)
    d.rectangle([lx + 680, ly, lx + 696, ly + 16], fill=C_GATE[0], outline=C_GATE[1])
    d.text((lx + 702, ly), "Gate / Interrupt", fill="#333", font=f_legend)
    d.rectangle([lx + 870, ly, lx + 886, ly + 16], fill=C_END[0], outline=C_END[1])
    d.text((lx + 892, ly), "Terminal", fill="#333", font=f_legend)

    out_path = OUT_DIR / "work_mode_flow_no_plan.png"
    img.save(out_path)
    print(f"wrote {out_path}")
    return out_path


# ===========================================================================
# Flow B: Plan Mode (end-to-end)
# ===========================================================================

def render_plan_mode_end_to_end():
    W, H = 1900, 2700
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    f_title = _load_font(28, bold=True)
    f_h = _load_font(18, bold=True)
    f_sub = _load_font(13)
    f_lbl = _load_font(13, bold=True)
    f_legend = _load_font(13)
    f_phase = _load_font(20, bold=True)

    d.text((40, 30), "Plan Mode — End-to-End Flow",
           fill="#0B3D91", font=f_title)
    d.text((40, 70),
           "Shift+Tab toggles plan_agent → plan drafted/evaluated → user approves → "
           "inter-graph handoff to work_agent → todos executed → completion.",
           fill="#333333", font=f_sub)

    boxes: dict[str, Box] = {}

    def add(name, x, y, w, h, title, subtitle="", color=C_MID, shape="rect"):
        fill, border, tc = color
        boxes[name] = Box(x, y, w, h, title, subtitle, fill, border, tc, shape=shape)

    cx_mid = 700
    BW = 500
    BH = 90

    # Phase headers (left band)
    def phase_band(y0, y1, text, fill="#F5F5F5"):
        d.rectangle([20, y0, 38, y1], fill=fill, outline="#999")
        # rotated-ish phase label printed horizontally near top
        d.text((46, y0 + 6), text, fill="#555", font=f_phase)

    # ── PHASE 1: Entry ──────────────────────────────────────────────────────
    phase_band(110, 380, "PHASE 1  ·  Entry & graph selection")

    add("user", cx_mid, 130, BW, BH,
        "User: Shift+Tab → submits complex request",
        "Frontend sets graph_id='plan_agent', mode='plan'\nPOST /api/langgraph/runs",
        C_USER)
    add("plan_graph", cx_mid, 250, BW, BH,
        "LangGraph invokes make_plan_agent",
        "plan_agent/agent.py:29  forces current_mode='plan',\nis_plan_mode=True; calls _build_work_agent w/ plan prompt",
        C_GRAPH)

    # ── PHASE 2: Plan agent middlewares + planner ────────────────────────────
    phase_band(400, 980, "PHASE 2  ·  Plan-mode middlewares & planner LLM")

    add("plan_build", cx_mid, 410, BW, BH,
        "Tools = internal_tools_plan.json (read-only)",
        "No bash / write_file / task. web_search allowed.\nPlanner / PlanEvaluator / TodoDag activated.",
        C_GRAPH)

    add("planner", cx_mid, 540, BW, 110,
        "PlannerMiddleware  (planner_middleware.py)",
        "before_model: inject <planning_instructions> system msg\nafter_model: parse PlannerOutput → todo list\nnormalize_todo_nodes() assigns todo-N ids, detects cycles\n→ state.plan + state.todo_graph",
        C_PLAN)

    add("evaluator", cx_mid, 690, BW, 130,
        "PlanEvaluatorMiddleware  (plan_evaluator_middleware.py)",
        "Deterministic pre-check: _precheck_nodes() repairs\ndangling deps / duplicate ids; _is_acyclic short-circuits.\nLLM eval: {ok, issues, advice, patch}; loops up to\nevaluator.max_attempts. Emits plan_evaluation_complete SSE.",
        C_PLAN)

    add("plan_md", cx_mid, 860, BW, BH,
        "serialize_plan_md  (common/handoff.py)",
        "Writes /mnt/user-data/workspace/plan.md\nplan_version: 5 frontmatter + Markdown body\nstatus='draft'  → emits plan_created SSE",
        C_PLAN)

    # ── PHASE 3: User review ────────────────────────────────────────────────
    phase_band(1000, 1230, "PHASE 3  ·  User review of plan.md")

    add("review", cx_mid, 1010, BW, 100,
        "User reviews plan.md in UI",
        "User may EDIT plan.md directly on disk.\nClicks 'Approve' OR replies in chat.\nplan_agent stays in draft until approval.",
        C_USER)

    add("approve_decision", cx_mid, 1130, BW, 90,
        "Approve plan?",
        "yes → handoff to work_agent\nno → revise (loop to planner)",
        C_DECISION, shape="diamond")

    # ── PHASE 4: Inter-graph handoff ─────────────────────────────────────────
    phase_band(1250, 1530, "PHASE 4  ·  Inter-graph handoff (plan_agent → work_agent)")

    add("terminate_plan", cx_mid, 1260, BW, BH,
        "plan_agent terminates",
        "plan['status'] = 'approved'\nplan.md persisted on disk.",
        C_GRAPH)

    add("spawn_work", cx_mid, 1380, BW, BH,
        "Frontend spawns work_agent run",
        "make_work_agent(config) — same thread_id\ninherits sandbox, uploads, memory, plan.md",
        C_GRAPH)

    add("handoff_load", cx_mid, 1500, BW, BH,
        "_load_canonical_plan_overrides  (work_run_handoff.py)",
        "Reads plan.md from disk · parse_plan_md(text)\nReturns (plan, todo_graph) — honors user edits.",
        C_PLAN)

    # ── PHASE 5: Work execution loop ─────────────────────────────────────────
    phase_band(1550, 2300, "PHASE 5  ·  Work execution — per-todo ReAct loop")

    add("work_mode", cx_mid, 1560, BW, 110,
        "WorkModeMiddleware.before_model",
        "Computes ready_ids = _materialize_ready_ids(nodes)\nEmits phase_started SSE\nInjects HumanMessage: 'Work on todo-N: …'",
        C_MID)

    add("phase_filter", 60, 1560, 510, 110,
        "PhaseToolFilterMiddleware",
        "Plan approved → full execution catalog exposed.\n(scope_search hidden; bash/web_search/task/write_file OK)",
        C_GATE)

    add("model2", cx_mid, 1710, BW, BH,
        "LLM model call",
        "Sees full work-mode tool catalog + injected todo.\nCalls tools to satisfy the active todo.",
        C_MODEL)

    add("tool2", cx_mid, 1830, BW, BH,
        "ToolNode executes",
        "bash · write_file · web_search · task (subagent)\n· query_knowledge_vault · view_image",
        C_TOOL)

    add("after_post", 1240, 1830, 500, 140,
        "Post-tool middlewares",
        "ToolResultTruncation · SubagentLimit\nTodoFailureRetry  (work-mode only)\nLoopDetection\nRecursionBudgetPivot",
        C_MID)

    add("sync", 60, 1830, 510, 140,
        "PlanFileSyncMiddleware  (background)",
        "Background thread on after_model:\nensure_plan_state() + sync_handoff_files_from_state()\n→ plan.md kept in sync on disk\nTodoDagMiddleware updates ready/blocked/completed.",
        C_PLAN)

    add("todo_done", cx_mid, 1990, BW, BH,
        "WorkModeMiddleware detects completion",
        "completed_set diff vs snapshot →\nemits phase_completed SSE for each.\nplan['status']: approved → executing",
        C_MID)

    add("more_todos", cx_mid, 2110, BW, 90,
        "More ready todos?",
        "yes → next todo · no → check pending",
        C_DECISION, shape="diamond")

    add("stall", 60, 2110, 510, 100,
        "Stall: pending exist, none ready/in_progress",
        "WorkModeMiddleware._handle_plan_adapted\n→ plan_adapted SSE  · user re-enters Plan Mode\n(no auto-escalation)",
        C_GATE)

    # ── PHASE 6: Completion ─────────────────────────────────────────────────
    phase_band(2320, 2660, "PHASE 6  ·  Completion")

    add("complete", cx_mid, 2330, BW, BH,
        "All todos completed",
        "plan['status'] = 'completed'\nEvaluatorMiddleware: final verification pass",
        C_MID)

    add("finalize", cx_mid, 2450, BW, BH,
        "Finalize: title · memory · trajectory",
        "Title / QuestionGeneration / Memory (async)\nTrajectory / ExecutionTrace / ActivityTimeline / Metrics",
        C_MID)

    add("output", cx_mid, 2560, BW, BH,
        "Final assistant response + artifacts",
        "Streamed via SSE (values + messages-tuple).\nArtifacts in /mnt/user-data/workspace.",
        C_END)

    add("end", cx_mid, 2660, BW, 60,
        "END",
        "",
        C_END, shape="ellipse")

    # Draw all boxes
    for b in boxes.values():
        draw_box(d, b, f_h, f_sub)

    # Edges along the spine
    def link(a, b, **kw):
        draw_arrow(d, boxes[a].bottom, boxes[b].top, fnt=f_lbl, **kw)

    link("user", "plan_graph")
    link("plan_graph", "plan_build")
    link("plan_build", "planner")
    link("planner", "evaluator")
    link("evaluator", "plan_md")
    # evaluator → planner (revise loop on patch)
    draw_elbow(d, boxes["evaluator"].right, boxes["planner"].right, fnt=f_lbl, via="h",
               label="patch / revise", dashed=True)
    link("plan_md", "review")
    link("review", "approve_decision")
    # decision branches
    draw_elbow(d, boxes["approve_decision"].left, boxes["planner"].left, fnt=f_lbl, via="h",
               label="no → revise", dashed=True)
    link("approve_decision", "terminate_plan", label="yes")
    link("terminate_plan", "spawn_work")
    link("spawn_work", "handoff_load")
    link("handoff_load", "work_mode")
    # phase filter side-info into work_mode
    draw_elbow(d, boxes["phase_filter"].right, boxes["work_mode"].left, fnt=f_lbl, via="h",
               label="full catalog")
    link("work_mode", "model2")
    link("model2", "tool2")
    # tool2 → after_post + sync
    draw_elbow(d, boxes["tool2"].right, boxes["after_post"].left, fnt=f_lbl, via="h",
               label="tool result")
    draw_elbow(d, boxes["tool2"].left, boxes["sync"].right, fnt=f_lbl, via="h",
               label="state update")
    # after_post + sync → todo_done
    draw_elbow(d, boxes["after_post"].bottom, boxes["todo_done"].right, fnt=f_lbl, via="v")
    draw_elbow(d, boxes["sync"].bottom, boxes["todo_done"].left, fnt=f_lbl, via="v")
    link("todo_done", "more_todos")
    # more_todos branches
    draw_elbow(d, boxes["more_todos"].right, boxes["work_mode"].right, fnt=f_lbl, via="h",
               label="yes → next ready todo", dashed=True)
    draw_elbow(d, boxes["more_todos"].left, boxes["stall"].right, fnt=f_lbl, via="h",
               label="none ready · pending exist", dashed=True)
    # stall → user re-enters plan_mode (dashed back to top)
    draw_elbow(d, boxes["stall"].top, boxes["user"].left, fnt=f_lbl, via="v",
               label="user opens Plan Mode again", dashed=True)
    link("more_todos", "complete", label="no pending → done")
    link("complete", "finalize")
    link("finalize", "output")
    link("output", "end")

    # Legend
    lx, ly = 60, 100
    d.rectangle([lx, ly, lx + 16, ly + 16], fill=C_USER[0], outline=C_USER[1])
    d.text((lx + 22, ly), "User / External", fill="#333", font=f_legend)
    d.rectangle([lx + 160, ly, lx + 176, ly + 16], fill=C_GRAPH[0], outline=C_GRAPH[1])
    d.text((lx + 182, ly), "Graph / Build", fill="#333", font=f_legend)
    d.rectangle([lx + 320, ly, lx + 336, ly + 16], fill=C_MID[0], outline=C_MID[1])
    d.text((lx + 342, ly), "Middleware", fill="#333", font=f_legend)
    d.rectangle([lx + 460, ly, lx + 476, ly + 16], fill=C_MODEL[0], outline=C_MODEL[1])
    d.text((lx + 482, ly), "LLM", fill="#333", font=f_legend)
    d.rectangle([lx + 560, ly, lx + 576, ly + 16], fill=C_TOOL[0], outline=C_TOOL[1])
    d.text((lx + 582, ly), "Tool exec", fill="#333", font=f_legend)
    d.rectangle([lx + 680, ly, lx + 696, ly + 16], fill=C_PLAN[0], outline=C_PLAN[1])
    d.text((lx + 702, ly), "Plan / plan.md", fill="#333", font=f_legend)
    d.rectangle([lx + 850, ly, lx + 866, ly + 16], fill=C_GATE[0], outline=C_GATE[1])
    d.text((lx + 872, ly), "Gate / Stall", fill="#333", font=f_legend)
    d.rectangle([lx + 1020, ly, lx + 1036, ly + 16], fill=C_END[0], outline=C_END[1])
    d.text((lx + 1042, ly), "Terminal", fill="#333", font=f_legend)

    out_path = OUT_DIR / "plan_mode_flow_end_to_end.png"
    img.save(out_path)
    print(f"wrote {out_path}")
    return out_path


if __name__ == "__main__":
    render_work_mode_no_plan()
    render_plan_mode_end_to_end()
