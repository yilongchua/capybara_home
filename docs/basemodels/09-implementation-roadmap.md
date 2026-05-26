# 09 — Implementation Roadmap

This document sequences the migrations described in [05](05-thread-state-basemodels.md)–[08](08-tools-skills-subagents-basemodels.md) into deliverable **phases**. Each phase is independently shippable and leaves the system in a coherent state.

> **Reminder from the task brief**: this is a planning artefact. No code is written here.

---

## 1. Risk matrix

| Migration cluster | Blast radius (call sites) | Touches persisted state | Touches SSE wire | Touches FastAPI schema | Tests at risk |
|-------------------|---------------------------|:-----------------------:|:----------------:|:----------------------:|---------------|
| `src/models/base.py` introduction | 0 (new file) | — | — | — | None |
| Config audits (§02 findings) | 5–10 per finding | — | — | — | Config loader tests |
| Control-plane dataclass → BaseModel (§03.4) | ~12 sites | Yes (ledger.json) | No | No | autoresearch tests |
| Thread-state TypedDict → BaseModel (§05) | **~130+ sites** | **Yes** (checkpointer sqlite) | Indirect | Indirect (StreamEvent) | Most agent tests |
| Runtime events (§06) | ~40 sites | Persisted in `ThreadState` | **Yes** — primary | Yes (StreamEvent union) | `tests/test_runtime_events.py`, frontend e2e |
| Middleware records (§07.1) | ~25 sites | Some (registry) | Some | No | Middleware unit tests |
| Channels (§07.3) | ~15 sites | Yes (store.json) | No | Yes (`/api/channels/*`) | Channel integration tests |
| Tool I/O (§08.1) | ~30 sites | No | No | Yes (via tool schemas) | Tool unit tests |
| Subagents / Skills / MCP / Sandbox / Memory (§08.2–§08.6) | ~50 sites | Yes (memory.json, sandbox state) | Some | Some | Memory tests, sandbox tests |

---

## 2. Phased rollout

### Phase 0 — Foundation (no behavior change)

| # | Step | Files | Risk |
|---|------|-------|------|
| 0.1 | Create `src/models/base.py` with `CapyBaseModel`, `CapyEvent`, `CapyEntity`, `CapyRequest`, `CapyResponse`, `CapyConfigNode`, `TimestampMixin`, `IdentifiedMixin`. | new file | None |
| 0.2 | Create `src/models/validators.py` with `safe_path`, `sha256_str`, `non_empty_str`, `image_mime_type` shared validators. | new file | None |
| 0.3 | Document conventions in [01-conventions-and-standards.md](01-conventions-and-standards.md) (✅ already in this catalogue). | docs/basemodels | None |
| 0.4 | Address audit findings C-1..C-6 (config tightening) and CP-1..CP-6 (control-plane Literal promotions). | `src/config/*`, `src/control_plane/models.py` | Low — config-only |

**Exit criteria**: Foundation classes exist; existing tests pass; no consumer changes.

### Phase 1 — Quick wins (low-blast migrations)

| # | Step | Targets | Owner files |
|---|------|---------|-------------|
| 1.1 | Convert §03.4.1 control-plane dataclasses to `BaseModel`. | `AgentExecutionContext`, `AgentExecutionResult`, `UnifiedVaultSearchHit`, `DeduplicationDecision`, `ResearcherDispatch`, `TaxonomyCluster` | `src/control_plane/agents/schemas.py`, `src/control_plane/autoresearch_loop/*.py` |
| 1.2 | Convert `QuestionNode` TypedDict → BaseModel (§03.4 / §06.7). | autoresearch loop | `src/control_plane/autoresearch_loop/ledger.py` |
| 1.3 | Convert `Skill` dataclass → BaseModel + add `SkillFrontmatter` validation. | skills loader | `src/skills/types.py`, `src/skills/parser.py` |
| 1.4 | Convert `SubagentConfig` dataclass → BaseModel. | subagents config | `src/subagents/config.py` |
| 1.5 | Convert `SandboxInfo` dataclass → BaseModel. | aio_sandbox | `src/community/aio_sandbox/sandbox_info.py` |
| 1.6 | Convert `CIDGuardrailConfig` dataclass → BaseModel. | guardrails | `src/security/search_guardrails.py` |
| 1.7 | Convert `_OAuthToken` dataclass → BaseModel + `SecretStr`. | MCP oauth | `src/mcp/oauth.py` |
| 1.8 | Convert `CommunityToolEntry` TypedDict → BaseModel with regex validation. | community tools | `src/community/registry.py` |

**Exit criteria**: All §03 / §08.2–§08.5 dataclass migrations land; on-disk JSON unchanged; vault-search and autoresearch e2e green.

### Phase 2 — Channels (independent surface)

| # | Step | Targets | Owner files |
|---|------|---------|-------------|
| 2.1 | Create `ChannelsConfig` / `SlackChannelConfig` / `TelegramChannelConfig`; mount on `AppConfig.channels`. | new config node | `src/config/channels_config.py`, `src/config/app_config.py` |
| 2.2 | Convert `InboundMessage`, `OutboundMessage`, `ResolvedAttachment` to BaseModel (`frozen=True`, datetime). | channels message bus | `src/channels/message_bus.py` |
| 2.3 | Add `InboundFileAttachment` typed sub-model; replace `files: list[dict]`. | same | same |
| 2.4 | Introduce `ChannelThreadMapRecord` and migrate `store.json` (one-time migrator). | channels store | `src/channels/store.py` |
| 2.5 | Add `ChannelRuntimeStatus`, `ChannelCommandRequest`, `ChannelCommandResponse`. | manager | `src/channels/manager.py` |
| 2.6 | Update `/api/channels/*` to return typed responses (§04.5). | gateway | `src/gateway/routers/channels.py` |

**Exit criteria**: Channels still talk to Slack/Telegram; replay test passes; admin status page reads typed payload.

### Phase 3 — Runtime events & SSE wire (frontend coordination required)

This phase intersects the frontend; coordinate the order with `frontend/src/typings/`.

| # | Step | Targets |
|---|------|---------|
| 3.1 | Convert `ActivityEvent` / `ActivityTimelineState` / `ContextMetricsState` to BaseModel (`frozen=True`, `extra="forbid"`). | `src/agents/activity_timeline.py` |
| 3.2 | Convert `TraceThinking` / `TraceTokenUsage` / `ExecutionTraceEvent` / `ExecutionTraceRun` / `ExecutionTraceState`. | `src/agents/execution_trace.py` |
| 3.3 | Convert `SteeringQueuedIntent` / `SteeringEnqueueResult`. | `src/agents/steering_queue_store.py` |
| 3.4 | Promote middleware-local TypedDicts (`DreamyIntent`, `SteeringIntent`, `_DetectedData`). | `src/agents/middlewares/*.py` |
| 3.5 | Create `src/agents/events.py` discriminated `StreamEvent` union (§06.5–§06.6). | new file |
| 3.6 | Enumerate the `runtime_events.kind` set into a `Literal` (audit RE-1). | `src/agents/middlewares/runtime_events.py` |
| 3.7 | Regenerate frontend types from `/openapi.json`. | `frontend/scripts/*` |

**Exit criteria**: Frontend renders activity timeline + execution trace + steering queue identically; e2e SSE replay test green.

### Phase 4 — Thread state migration (the big one)

Recommended split into **sub-phases** to keep PRs reviewable. Each sub-phase migrates a related group; consumers can be updated as a single unit.

| Sub-phase | Targets (from §05) | Approx. sites touched |
|-----------|--------------------|----------------------:|
| 4a | Leaf states with no cross-validators: `SandboxState`, `ThreadDataState`, `ViewedImageData`, `ProgressGuardRuntimeState`, `TrajectoryRuntimeState`, `SkillDisclosureState`, `RetryRuntimeState`, `HandoffArtifactState`, `HooksRuntimeState`, `MemoryVersionRefState`, `ScratchpadEntry`, `TaskMemoryFact`, `BackgroundFollowupJob`, `SteeringIntentState`, `ExecutionIntentState`, `QualityGateState`, `HandoffMetaState` | ~40 |
| 4b | DAG-validated: `TodoGraphItem`, `TodoGraphState`, `PlanHistoryItem` | ~24 |
| 4c | Plan tree: `PlanState` + new sub-models (`PlanRisk`, `PlanEvaluationState`, `PlanClarificationState`, `PlanClarificationItem`, `PlanClarificationOption`, `PlanClarificationAnswer`, `PlanApprovalState`) | ~38 |
| 4d | Work-mode + phase execution: `WorkModeState`, `PhaseExecutionState`, `PhaseResultRecord` | ~24 |
| 4e | Resume + Dreamy: `ResumeMetaState`, `DreamyIntentState` | ~18 |
| 4f | New reducers `merge_plan`, `merge_phase_execution`; refactor middleware reads/writes through `.model_validate` / `.model_dump`. | 130+ |

**Acceptance gates per sub-phase**:
* Existing checkpoint sqlite round-trips byte-identical.
* `make test` (or focused subset) green.
* No `state.get("plan", {})` / `state["plan"] = dict(...)` patterns left in the touched files.

### Phase 5 — Middleware records & tool I/O

| # | Step | Targets |
|---|------|---------|
| 5.1 | Convert middleware dataclasses (§07.1): `PlannerOutput`, `PlannerClarification`, `PlannerClarificationOption`, `SummarizationEvent`, `ParsedRule`, `MiddlewareSpec`, `RegistryContext`, `PromptCacheEntry`, `ConversationContext`, `QualityCheckReport`. | `src/agents/middlewares/*.py`, `src/agents/lead_agent/*.py`, `src/agents/memory/queue.py`, `src/agents/report_quality.py` |
| 5.2 | Switch planner to `with_structured_output(PlannerOutput)`. Remove manual JSON normalisation. | `src/agents/middlewares/planner_middleware.py` |
| 5.3 | Add §07.2 NEW middleware event/record models. | various |
| 5.4 | Tool I/O migrations (§08.1) — every built-in tool gets typed input/output. | `src/tools/builtins/*.py`, `src/sandbox/tools.py` |

**Exit criteria**: Tool schemas in `/openapi.json` reflect typed I/O; planner LLM call deterministically returns `PlannerOutput`.

### Phase 6 — Memory store consolidation

| # | Step | Targets |
|---|------|---------|
| 6.1 | Move `Fact`, `BehaviorRule`, `UserContext`, `HistoryContext` definitions to `src/agents/memory/store.py`. | memory store |
| 6.2 | Gateway router imports from memory store (delete duplicates). | `src/gateway/routers/memory.py` |
| 6.3 | Add `MemoryStore`, `MemoryUpdaterResult`, `MemoryVersion`, `CompactionArchiveEntry`, `MemoryVectorEntry`. | memory store / updater / compaction / vector store |

**Exit criteria**: `TestGatewayConformance` still green; `backend/.capyhome/memory.json` schema validated on load.

### Phase 7 — Final tightening

| # | Step |
|---|------|
| 7.1 | Switch all wire-format models to `extra="forbid"` (some still `extra="allow"` for migration safety). |
| 7.2 | Add `ser_json_timedelta` config where applicable; audit any remaining `time.time()` floats. |
| 7.3 | Enable Ruff rule `PYI013` / `PYI016` to forbid new TypedDict outside designated allow-list (`thread_state.ThreadState` root only). |
| 7.4 | Add lint check forbidding new `@dataclass` in `src/` outside the allow-list. |

---

## 3. Test strategy

| Layer | Test |
|-------|------|
| Unit | Each new `BaseModel` ships with a `tests/test_<module>_models.py` covering: required-field rejection, `Literal` rejection, default values, JSON round-trip. |
| Integration — checkpointer | Load a real sqlite checkpoint from before the migration, run `ThreadState.model_validate(loaded_dict)`, assert no `ValidationError`. |
| Integration — SSE replay | Capture an SSE stream pre-migration; replay post-migration; assert byte-identical events (after `extra` allowance). |
| Conformance | Extend `TestGatewayConformance` in `tests/test_client.py` to cover every new gateway response model. |
| Contract — frontend | Generate TypeScript from `/openapi.json` and `ThreadState` dump; run frontend type-check on a snapshot project. |

---

## 4. Dependencies & ordering

```
 Phase 0 (Foundation)
    │
    ├─► Phase 1 (Quick wins)
    │
    ├─► Phase 2 (Channels)        — independent of agent surface
    │
    ├─► Phase 3 (Runtime events)  ─┐
    │                              │
    └─► Phase 4 (ThreadState)  ◄───┘  (Phase 4 shares types with Phase 3 — coordinate)
            │
            ├─► Phase 5 (Middleware records & Tool I/O)
            │       └─► Planner with_structured_output requires Phase 4 PlanState
            │
            └─► Phase 6 (Memory)
                    │
                    └─► Phase 7 (Tightening)
```

---

## 5. Rollback strategy

Each migration is reversible:

1. **No on-disk schema change** — `BaseModel.model_dump()` produces the same dict the TypedDict / dataclass already wrote.
2. **Feature flag** — gate the new behaviour behind a `harness.basemodels_enabled` flag for sub-phases that touch >20 sites (specifically Phase 4c — Plan tree). Default to `True` after a 1-week soak.
3. **Snapshot tests** — keep a tagged commit of each phase's "before" checkpointer file in `backend/tests/fixtures/`; CI verifies forward and backward compatibility.

---

## 6. Definition of done

The migration is **complete** when:

* [ ] Zero `@dataclass` decorators remain in `src/` except in `src/control_plane/agents/schemas.py:AgentExecutionError` (Exception subclass) and any explicitly allow-listed exceptions.
* [ ] Every `TypedDict` outside `langchain.agents.AgentState` extension chain is gone (the root `ThreadState` and `AgentState` are the only allowed TypedDicts).
* [ ] `/openapi.json` exports a fully-typed `StreamEvent` discriminated union.
* [ ] `TestGatewayConformance` covers all `CapyHomeClient` methods returning dicts.
* [ ] Lint rules in §7.3/§7.4 are active in CI.
* [ ] Frontend `frontend/src/typings/` is generated 1:1 from `/openapi.json` — no hand-written agent state types remain.

---

## 7. Estimated effort (rough)

| Phase | PRs (rough) | Engineer-weeks |
|------:|------------:|---------------:|
| 0 | 1–2 | 0.5 |
| 1 | 4–6 | 1.0 |
| 2 | 3 | 1.0 |
| 3 | 3–4 | 1.5 |
| 4a–4f | 6 | 4.0 |
| 5 | 4 | 2.0 |
| 6 | 2 | 1.0 |
| 7 | 1 | 0.5 |
| **Total** | **~25 PRs** | **~11.5 engineer-weeks** |

Numbers assume one engineer; can compress with parallel work on Phases 2, 3, 5 since they don't share files.
