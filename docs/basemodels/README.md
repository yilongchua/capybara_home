# CapyHome Backend — Pydantic BaseModel Catalogue

> **Scope**: This folder documents every Pydantic `BaseModel` that the CapyHome backend either **already has** or **should have** to reach a fully-structured, validation-first architecture.
>
> **Status**: Investigation & specification only — **no implementation work** is performed here. Each table lists the canonical source location (file + line) so the migration owner can locate the existing definition or target file in one click.

---

## 1. Why this document exists

The CapyHome backend currently mixes **three** schema styles:

| Style | Count (approx.) | Strengths | Weaknesses |
|-------|-----------------|-----------|------------|
| `pydantic.BaseModel` | **235** classes | Validation, JSON schema, FastAPI integration, `model_dump`, `model_validate`, runtime invariants | — |
| `typing.TypedDict` | **56** classes | Zero-cost at runtime, LangGraph-state compatibility (must remain `TypedDict` for `AgentState`) | No validation, no defaults, no methods, silent type drift |
| `@dataclass` (frozen / mutable) | **30** classes | Lightweight, `__init__` / `__eq__` for free | No validation, no JSON ser/de, no extra-field rejection, no field constraints |

The objective is to **migrate every `@dataclass` and most `TypedDict` declarations to `BaseModel`** wherever the value crosses a process boundary (disk, SSE wire, FastAPI body, subagent → lead handoff, channel inbound/outbound, scheduler tick) **except** the few `TypedDict`s that LangGraph's `AgentState` reducer machinery requires to remain `TypedDict`.

---

## 2. Folder map

| # | File | Domain | Phase |
|---|------|--------|-------|
| 0 | [README.md](README.md) | Index + conventions | — |
| 1 | [01-conventions-and-standards.md](01-conventions-and-standards.md) | `ConfigDict`, naming, base class hierarchy, mixins | Foundation |
| 2 | [02-config-basemodels.md](02-config-basemodels.md) | `src/config/` — application config tree (64 models) | Existing — audit only |
| 3 | [03-control-plane-basemodels.md](03-control-plane-basemodels.md) | `src/control_plane/`, `src/generation/` — pipeline/run/approval/scheduler/autoresearch (20 models) | Existing — audit only |
| 4 | [04-gateway-api-basemodels.md](04-gateway-api-basemodels.md) | `src/gateway/routers/` — REST request/response envelopes (~150 models) | Existing — audit + dedup |
| 5 | [05-thread-state-basemodels.md](05-thread-state-basemodels.md) | `src/agents/thread_state.py` — LangGraph `ThreadState` shape | **Migration target (high priority)** |
| 6 | [06-runtime-event-basemodels.md](06-runtime-event-basemodels.md) | `activity_timeline`, `execution_trace`, `steering_queue_store` — SSE wire-format | **Migration target (high priority)** |
| 7 | [07-middleware-and-channel-basemodels.md](07-middleware-and-channel-basemodels.md) | Middleware `@dataclass` + channels message bus | **Migration target** |
| 8 | [08-tools-skills-subagents-basemodels.md](08-tools-skills-subagents-basemodels.md) | Tool I/O, skills, subagents, MCP, sandbox, memory | **Migration target** |
| 9 | [09-implementation-roadmap.md](09-implementation-roadmap.md) | Phased rollout plan, dependency order, risk matrix | Plan |

---

## 3. Inventory summary (totals by domain)

| Domain | Existing `BaseModel` | `TypedDict` to migrate | `@dataclass` to migrate | New `BaseModel` proposed |
|--------|---------------------:|-----------------------:|------------------------:|-------------------------:|
| `src/config/` | 64 | 0 | 0 | 0 |
| `src/control_plane/` | 18 | 1 (`QuestionNode`) | 5 | 2 |
| `src/generation/` | 2 | 0 | 0 | 0 |
| `src/gateway/routers/` | ~110 | 0 | 2 | ~6 (consolidation) |
| `src/gateway/` (config) | 1 | 0 | 0 | 0 |
| `src/agents/` (state + memory + lead) | 0 | 32 (`thread_state.py` + `activity_timeline.py` + `execution_trace.py` + `steering_queue_store.py`) | 6 | 8 (event payloads, plan history, etc.) |
| `src/agents/middlewares/` | 0 | 7 | 6 | 12 (planner output, summarization event, registry spec) |
| `src/channels/` | 0 | 0 | 3 | 5 (manager + store records) |
| `src/tools/builtins/` | 0 | 3 | 0 | 6 (tool input/output envelopes) |
| `src/skills/` | 0 | 0 | 1 (`Skill`) | 1 (`SkillFrontmatter`) |
| `src/subagents/` | 0 | 0 | 2 (`SubagentConfig`, executor record) | 3 (task envelope, result, event) |
| `src/sandbox/` | 0 | 0 | 1 (`SandboxInfo`) | 2 (volume mount info, virtual path map) |
| `src/community/` | 0 | 1 (`CommunityToolEntry`) | 0 | 0 |
| `src/mcp/` | 0 | 0 | 1 (`_OAuthToken`) | 2 (preview cache record, tool-load result) |
| `src/security/` | 0 | 0 | 1 (`CIDGuardrailConfig`) | 0 |
| **Total** | **~195** | **~44** | **~28** | **~47** |

> The 235 `BaseModel` count in §1 includes a handful of legacy / duplicate response wrappers in gateway routers that §4 flags for consolidation.

---

## 4. How to use this catalogue

* **Owner of a subsystem**: Open the file for your domain, find your class in the table, follow the file-path link to the existing source.
* **Migration owner**: Tables prefixed **PROPOSED** in §5–§8 list the target class name, the source `TypedDict` / `@dataclass` to replace, fields to enforce, and the consumers that read the value (so you can size the blast radius).
* **Reviewer**: Cross-reference [01-conventions-and-standards.md](01-conventions-and-standards.md) — every new or migrated `BaseModel` must follow those conventions (e.g. `ConfigDict(extra="forbid", frozen=True)` for wire-format events; `extra="allow"` only for persisted snapshots).

---

## 5. Out of scope

* Migrating `langchain.agents.AgentState` itself — it is required to be a `TypedDict` by LangGraph's reducer protocol.
* Changing the JSON shape persisted on disk in `backend/.capyhome/` (the migration must preserve byte-level compatibility; `BaseModel` is a wrapper around the same dict shape).
* Frontend TypeScript types — those are tracked separately under `docs/agent-system/` and will track the new server schemas via the `/openapi.json` produced by FastAPI once response models are unified.
