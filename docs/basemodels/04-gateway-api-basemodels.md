# 04 — Gateway API BaseModels (`src/gateway/routers/`)

This is the largest BaseModel surface in the backend. **Every** FastAPI request body and every documented response body is a `BaseModel`. The catalogue here serves two purposes:

1. Confirm coverage (no router endpoint returns / accepts an untyped `dict`).
2. Identify duplicated or near-duplicate response shapes that should be consolidated.

> Convention reminder: gateway request bodies → `extra="forbid"`; gateway response bodies → `extra="forbid"`. **Drift between the embedded `CapyHomeClient` return shape and the response model is asserted by `TestGatewayConformance` in `tests/test_client.py`.**

---

## 4.1 Models, MCP, Skills, Memory, Uploads, Artifacts (the "core six")

### 4.1.1 Models

| Model | File | Line | Role |
|-------|------|-----:|------|
| `ModelResponse` | [src/gateway/routers/models.py](../../backend/src/gateway/routers/models.py) | 13 | Response — single model. |
| `ModelsListResponse` | [src/gateway/routers/models.py](../../backend/src/gateway/routers/models.py) | 40 | Response — `models: list[ModelResponse]`. |

### 4.1.2 MCP

| Model | File | Line | Role |
|-------|------|-----:|------|
| `McpOAuthConfigResponse` | [src/gateway/routers/mcp.py](../../backend/src/gateway/routers/mcp.py) | 15 | Mirror of `McpOAuthConfig` for outbound. |
| `McpServerConfigResponse` | [src/gateway/routers/mcp.py](../../backend/src/gateway/routers/mcp.py) | 34 | Mirror of `McpServerConfig`. |
| `McpConfigResponse` | [src/gateway/routers/mcp.py](../../backend/src/gateway/routers/mcp.py) | 49 | `mcp_servers: dict[str, McpServerConfigResponse]`. |
| `McpConfigUpdateRequest` | [src/gateway/routers/mcp.py](../../backend/src/gateway/routers/mcp.py) | 58 | Request — full replacement of MCP servers map. |
| `McpPreviewRequest` | [src/gateway/routers/mcp.py](../../backend/src/gateway/routers/mcp.py) | 175 | Request — preview tools from a candidate MCP config. |
| `McpPreviewToolResponse` | [src/gateway/routers/mcp.py](../../backend/src/gateway/routers/mcp.py) | 187 | One tool's preview entry. |
| `McpPreviewResponse` | [src/gateway/routers/mcp.py](../../backend/src/gateway/routers/mcp.py) | 195 | Wrapper. |

### 4.1.3 Skills

| Model | File | Line | Role |
|-------|------|-----:|------|
| `SkillResponse` | [src/gateway/routers/skills.py](../../backend/src/gateway/routers/skills.py) | 23 | Single-skill view. |
| `SkillsListResponse` | [src/gateway/routers/skills.py](../../backend/src/gateway/routers/skills.py) | 33 | List wrapper. |
| `SkillUpdateRequest` | [src/gateway/routers/skills.py](../../backend/src/gateway/routers/skills.py) | 39 | Toggle `enabled`. |
| `SkillInstallRequest` | [src/gateway/routers/skills.py](../../backend/src/gateway/routers/skills.py) | 45 | Multipart-companion fields. |
| `SkillInstallResponse` | [src/gateway/routers/skills.py](../../backend/src/gateway/routers/skills.py) | 52 | Install result. |
| `SkillCurationRequest` | [src/gateway/routers/skills.py](../../backend/src/gateway/routers/skills.py) | 60 | Self-improver review payload. |
| `SkillCurationResponse` | [src/gateway/routers/skills.py](../../backend/src/gateway/routers/skills.py) | 66 | Approval/rejection result. |

### 4.1.4 Memory

| Model | File | Line | Role |
|-------|------|-----:|------|
| `ContextSection` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 37 | Reusable nested block. |
| `UserContext` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 42 | `work`, `personal`, `topOfMind`. |
| `HistoryContext` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 48 | `recentMonths`, `earlierContext`, `longTermBackground`. |
| `Fact` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 54 | `id`, `content`, `category`, `confidence`, `createdAt`, `source`. |
| `BehaviorRule` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 63 | Active behavior-rule fact. |
| `MemoryResponse` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 74 | Full memory payload. |
| `MemoryConfigResponse` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 85 | Echo of memory config. |
| `MemoryStatusResponse` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 102 | `config + data`. |
| `MemoryVersionSummary` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 108 | One version row. |
| `MemoryVersionsResponse` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 120 | List of summaries. |
| `MemoryVersionDetailResponse` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 124 | Single version detail. |
| `MemoryRedactRequest` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 137 | `pattern`, `replacement`. |
| `MemoryRedactResponse` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 145 | Redaction outcome. |
| `FactUpdateRequest` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 151 | PATCH a fact. |
| `BehaviorRuleCreateRequest` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 158 | Create behavior rule. |
| `BehaviorRuleUpdateRequest` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 164 | Update rule. |
| `ForgetThreadRequest` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 169 | Targeted forget. |
| `CompactionEntriesResponse` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 173 | Compaction archive view. |
| `MemoryClearResponse` | [src/gateway/routers/memory.py](../../backend/src/gateway/routers/memory.py) | 177 | Clear outcome. |

### 4.1.5 Uploads & Artifacts

| Model | File | Line | Role |
|-------|------|-----:|------|
| `UploadResponse` | [src/gateway/routers/uploads.py](../../backend/src/gateway/routers/uploads.py) | 28 | `success`, `files[]`. |
| `UpdateArtifactRequest` | [src/gateway/routers/artifacts.py](../../backend/src/gateway/routers/artifacts.py) | 21 | Mutate artifact metadata. |
| `ListArtifactsResponse` | [src/gateway/routers/artifacts.py](../../backend/src/gateway/routers/artifacts.py) | 25 | Artifact list. |

---

## 4.2 Threads, Runs, Steering, Suggestions

| Model | File | Line | Role |
|-------|------|-----:|------|
| `DeleteThreadResponse` | [src/gateway/routers/threads.py](../../backend/src/gateway/routers/threads.py) | 113 | Outcome. |
| `DeleteAllThreadsResponse` | [src/gateway/routers/threads.py](../../backend/src/gateway/routers/threads.py) | 119 | Outcome. |
| `HardStopThreadResponse` | [src/gateway/routers/threads.py](../../backend/src/gateway/routers/threads.py) | 125 | Outcome. |
| `ResumeRunRequest` | [src/gateway/routers/runs.py](../../backend/src/gateway/routers/runs.py) | 20 | LangGraph resume payload. |
| `ResumeRunAcceptedResponse` | [src/gateway/routers/runs.py](../../backend/src/gateway/routers/runs.py) | 30 | 202 envelope. |
| `ResumeRunStatusResponse` | [src/gateway/routers/runs.py](../../backend/src/gateway/routers/runs.py) | 39 | Run status. |
| `SteerRequest` | [src/gateway/routers/steering.py](../../backend/src/gateway/routers/steering.py) | 49 | Send a steering intent. |
| `SteerResponse` | [src/gateway/routers/steering.py](../../backend/src/gateway/routers/steering.py) | 59 | Steering outcome. |
| `ExecutePlanRequest` | [src/gateway/routers/steering.py](../../backend/src/gateway/routers/steering.py) | 66 | Trigger work-mode handoff. |
| `ExecutePlanResponse` | [src/gateway/routers/steering.py](../../backend/src/gateway/routers/steering.py) | 79 | Handoff result. |
| `ClarifyPlanRequest` | [src/gateway/routers/steering.py](../../backend/src/gateway/routers/steering.py) | 96 | Answer planner clarification. |
| `ClarifyPlanResponse` | [src/gateway/routers/steering.py](../../backend/src/gateway/routers/steering.py) | 117 | Acknowledgement. |
| `CompactThreadResponse` | [src/gateway/routers/steering.py](../../backend/src/gateway/routers/steering.py) | 126 | Manual compaction outcome. |
| `SuggestionMessage` | [src/gateway/routers/suggestions.py](../../backend/src/gateway/routers/suggestions.py) | 15 | One suggestion. |
| `SuggestionsRequest` | [src/gateway/routers/suggestions.py](../../backend/src/gateway/routers/suggestions.py) | 20 | Inbound. |
| `SuggestionsResponse` | [src/gateway/routers/suggestions.py](../../backend/src/gateway/routers/suggestions.py) | 27 | Outbound. |

---

## 4.3 Control plane facing routers

| Model | File | Line | Role |
|-------|------|-----:|------|
| `PipelineTemplateListResponse` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 20 | Templates list. |
| `PipelineTemplateUpsertRequest` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 24 | Upsert template. |
| `PipelineRunCreateRequest` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 28 | Create run. |
| `PipelineRunListResponse` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 39 | Runs list. |
| `AutoresearchObjectiveListResponse` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 43 | Objectives list. |
| `AutoresearchStartRequest` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 47 | Start objective. |
| `AutoresearchPauseRequest` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 57 | Pause objective. |
| `AutoresearchStartResponse` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 61 | Outcome. |
| `AutoresearchDeleteResponse` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 67 | Delete outcome. |
| `PipelineRunsCleanupRequest` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 74 | Cleanup filter. |
| `PipelineRunsCleanupResponse` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 79 | Cleanup outcome. |
| `AutoresearchCleanupRequest` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 85 | Cleanup objectives. |
| `AutoresearchCleanupResponse` | [src/gateway/routers/pipelines.py](../../backend/src/gateway/routers/pipelines.py) | 89 | Outcome. |
| `ApprovalListResponse` | [src/gateway/routers/approvals.py](../../backend/src/gateway/routers/approvals.py) | 14 | Approvals list. |
| `ApprovalResolveRequest` | [src/gateway/routers/approvals.py](../../backend/src/gateway/routers/approvals.py) | 18 | Resolve approval. |
| `ProposalApprovalListResponse` | [src/gateway/routers/approvals.py](../../backend/src/gateway/routers/approvals.py) | 24 | Proposals list. |
| `ProposalResolveRequest` | [src/gateway/routers/approvals.py](../../backend/src/gateway/routers/approvals.py) | 28 | Resolve proposal. |
| `TriggerCreateRequest` | [src/gateway/routers/triggers.py](../../backend/src/gateway/routers/triggers.py) | 12 | Create trigger event. |
| `TriggerListResponse` | [src/gateway/routers/triggers.py](../../backend/src/gateway/routers/triggers.py) | 22 | Trigger list. |
| `FeedbackCreateRequest` | [src/gateway/routers/feedback.py](../../backend/src/gateway/routers/feedback.py) | 12 | Create feedback. |
| `FeedbackListResponse` | [src/gateway/routers/feedback.py](../../backend/src/gateway/routers/feedback.py) | 21 | Feedback list. |
| `IntegrationToggleRequest` | [src/gateway/routers/integrations.py](../../backend/src/gateway/routers/integrations.py) | 13 | Toggle integration. |
| `SchedulerRuntimeJobCreateRequest` | [src/gateway/routers/integrations.py](../../backend/src/gateway/routers/integrations.py) | 17 | Create scheduler job. |
| `SchedulerRuntimeJobUpdateRequest` | [src/gateway/routers/integrations.py](../../backend/src/gateway/routers/integrations.py) | 26 | Update scheduler job. |

---

## 4.4 Vault (`/api/vault/*`) — high cardinality

The vault router has the densest cluster of response models (26 of them). Many are near-duplicate item/wrapper pairs.

| Model | File | Line | Role |
|-------|------|-----:|------|
| `VaultSearchItem` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 14 | Hit item. |
| `VaultSearchResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 25 | Search wrapper. |
| `VaultClipRequest` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 31 | Browser-extension clip. |
| `VaultSaveRequest` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 39 | Save into vault. |
| `VaultWriteResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 48 | Write outcome. |
| `VaultStatusResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 57 | Vault status. |
| `VaultActionItem` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 67 | Pending action item. |
| `VaultActionItemsResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 77 | Wrapper. |
| `VaultSufficiencyRequest` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 83 | Sufficiency evaluation input. |
| `VaultSufficiencyResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 89 | Output. |
| `VaultIngestStartRequest` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 104 | Kick-off ingest. |
| `VaultIngestStatusResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 108 | Poll. |
| `VaultFileNode` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 129 | File tree node. |
| `VaultExplorerSourceItem` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 137 | Source item. |
| `VaultExplorerKnowledgeResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 146 | Knowledge view. |
| `VaultExplorerResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 153 | Full explorer envelope. |
| `VaultFileResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 161 | Single file fetch. |
| `VaultFileWriteRequest` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 167 | Write a file. |
| `VaultFileWriteResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 172 | Outcome. |
| `VaultFileDeleteResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 177 | Outcome. |
| `VaultKnowledgeGraphDeleteResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 182 | Outcome. |
| `VaultEntitySourceItem` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 187 | Entity source. |
| `VaultEntityConceptItem` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 193 | Entity concept. |
| `VaultEntityBrowserItem` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 198 | Browser row. |
| `VaultEntityBrowserResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 206 | Browser wrapper. |
| `VaultEntityDismissalItem` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 214 | Dismissal row. |
| `VaultEntityDismissalsResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 222 | Dismissals wrapper. |
| `VaultEntityDismissRequest` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 226 | Dismiss action. |
| `VaultEntityDismissResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 231 | Outcome. |
| `VaultEntityRestoreResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 238 | Outcome. |
| `VaultEntityAutoresearchRequest` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 243 | Kick off objective. |
| `VaultEntityAutoresearchResponse` | [src/gateway/routers/vault.py](../../backend/src/gateway/routers/vault.py) | 248 | Outcome. |

---

## 4.5 Onboarding, Harness, Channels, Community tools, Generation, Handoff, Agents, Dreamy

| Model | File | Line | Role |
|-------|------|-----:|------|
| `TestLlmRequest` / `TestLlmResponse` | [src/gateway/routers/onboarding.py](../../backend/src/gateway/routers/onboarding.py) | 66, 71 | Probe `/v1/models`. |
| `TestComfyuiRequest` / `TestComfyuiResponse` | [src/gateway/routers/onboarding.py](../../backend/src/gateway/routers/onboarding.py) | 77, 81 | Probe `/system_stats`. |
| `TestGenericRequest` / `TestGenericResponse` | [src/gateway/routers/onboarding.py](../../backend/src/gateway/routers/onboarding.py) | 86, 91 | Generic URL probe. |
| `LlmEndpointsMap` | [src/gateway/routers/onboarding.py](../../backend/src/gateway/routers/onboarding.py) | 97 | Inbound LLM endpoints map. |
| `LlmEndpointsResponse` | [src/gateway/routers/onboarding.py](../../backend/src/gateway/routers/onboarding.py) | 106 | Outbound LLM endpoints. |
| `EmbeddingEndpointsMap` | [src/gateway/routers/onboarding.py](../../backend/src/gateway/routers/onboarding.py) | 114 | Inbound embeddings. |
| `EmbeddingEndpointsResponse` | [src/gateway/routers/onboarding.py](../../backend/src/gateway/routers/onboarding.py) | 123 | Outbound embeddings. |
| `TestEmbeddingRequest` / `TestEmbeddingResponse` | [src/gateway/routers/onboarding.py](../../backend/src/gateway/routers/onboarding.py) | 131, 137 | Probe embeddings endpoint. |
| `HarnessConfigResponse` | [src/gateway/routers/harness.py](../../backend/src/gateway/routers/harness.py) | 27 | Read harness flags. |
| `HarnessConfigUpdateRequest` | [src/gateway/routers/harness.py](../../backend/src/gateway/routers/harness.py) | 33 | Mutate harness flags. |
| `ChannelStatusResponse` | [src/gateway/routers/channels.py](../../backend/src/gateway/routers/channels.py) | 15 | Channels lifecycle status. |
| `ChannelRestartResponse` | [src/gateway/routers/channels.py](../../backend/src/gateway/routers/channels.py) | 20 | Restart outcome. |
| `CommunityToolResponse` | [src/gateway/routers/community_tools.py](../../backend/src/gateway/routers/community_tools.py) | 17 | Tool list row. |
| `CommunityToolsListResponse` | [src/gateway/routers/community_tools.py](../../backend/src/gateway/routers/community_tools.py) | 25 | Wrapper. |
| `CommunityToolUpdateRequest` | [src/gateway/routers/community_tools.py](../../backend/src/gateway/routers/community_tools.py) | 29 | Toggle tool. |
| `GenerationSubmitRequest` | [src/gateway/routers/generation.py](../../backend/src/gateway/routers/generation.py) | 14 | Submit generation. |
| `GenerationSubmitResponse` | [src/gateway/routers/generation.py](../../backend/src/gateway/routers/generation.py) | 21 | Accepted envelope. |
| `GenerationJobListResponse` | [src/gateway/routers/generation.py](../../backend/src/gateway/routers/generation.py) | 25 | Jobs list. |
| `GenerationCompletionsResponse` | [src/gateway/routers/generation.py](../../backend/src/gateway/routers/generation.py) | 29 | Completion notifications. |
| `HandoffResponse` | [src/gateway/routers/handoff.py](../../backend/src/gateway/routers/handoff.py) | 85 | Handoff manifest. |
| `AgentResponse` | [src/gateway/routers/agents.py](../../backend/src/gateway/routers/agents.py) | 20 | Custom-agent row. |
| `AgentsListResponse` | [src/gateway/routers/agents.py](../../backend/src/gateway/routers/agents.py) | 30 | Wrapper. |
| `AgentCreateRequest` | [src/gateway/routers/agents.py](../../backend/src/gateway/routers/agents.py) | 36 | Create custom agent. |
| `AgentUpdateRequest` | [src/gateway/routers/agents.py](../../backend/src/gateway/routers/agents.py) | 46 | Update custom agent. |
| `UserProfileResponse` | [src/gateway/routers/agents.py](../../backend/src/gateway/routers/agents.py) | 294 | User profile. |
| `UserProfileUpdateRequest` | [src/gateway/routers/agents.py](../../backend/src/gateway/routers/agents.py) | 300 | Mutate profile. |
| `WorkflowPatchRequest` | [src/gateway/routers/dreamy.py](../../backend/src/gateway/routers/dreamy.py) | 770 | Dreamy workflow patch. |
| `MountFolderRequest` | [src/gateway/routers/dreamy.py](../../backend/src/gateway/routers/dreamy.py) | 787 | Mount folder. |
| `AnalyseResponse` | [src/gateway/routers/dreamy.py](../../backend/src/gateway/routers/dreamy.py) | 791 | Analysis kickoff outcome. |
| `AnalyseStatusResponse` | [src/gateway/routers/dreamy.py](../../backend/src/gateway/routers/dreamy.py) | 815 | Status poll. |
| `PublishDocsResponse` | [src/gateway/routers/dreamy.py](../../backend/src/gateway/routers/dreamy.py) | 823 | Outcome. |
| `RepoOverviewRefreshStartResponse` | [src/gateway/routers/dreamy.py](../../backend/src/gateway/routers/dreamy.py) | 831 | Kickoff. |
| `RepoOverviewRefreshStatusResponse` | [src/gateway/routers/dreamy.py](../../backend/src/gateway/routers/dreamy.py) | 838 | Poll. |
| `FileActionRequest` | [src/gateway/routers/dreamy.py](../../backend/src/gateway/routers/dreamy.py) | 1607 | Dreamy file-action. |

---

## 4.6 PROPOSED — request/response models still missing

| Endpoint | Today | Proposed `BaseModel` |
|----------|-------|----------------------|
| `GET /health` (returns `{"status":"ok"}`) | dict literal | `HealthResponse(status: Literal["ok","degraded"], version: str)` in `src/gateway/app.py` |
| `GET /api/threads/{id}/artifacts/{path}` returns raw `bytes` + headers | n/a — binary | Add a `ArtifactDownloadHeadersModel` for the **HEAD** metadata route currently inferred from filesystem. |
| Streaming `/api/threads/{id}/runs` SSE | uses LangGraph wire-format | Document the union of `ValuesEvent | MessagesEvent | EndEvent` as **Pydantic discriminated union** for the `CapyHomeClient.stream()` consumers. See §06. |
| `POST /api/uploads/{thread_id}` multipart `UploadFile` | FastAPI built-in | Companion `UploadMetadataRequest` for the JSON description part. |
| `POST /api/threads/{id}/runs/cancel` | no payload class | `CancelRunRequest(reason: str | None)`. |
| `GET /api/channels/{name}/messages` | not yet typed | `ChannelMessageListResponse(messages: list[InboundMessageRecord])` — depends on `InboundMessageRecord` proposed in §07. |

---

## 4.7 Audit findings — actionable

| # | Finding | Suggested fix |
|---|---------|---------------|
| GW-1 | `MemoryRedactResponse`, `MemoryClearResponse`, `VaultFileDeleteResponse`, `VaultKnowledgeGraphDeleteResponse`, `PublishDocsResponse`, `AutoresearchDeleteResponse`, `AutoresearchPauseRequest`-acknowledgement-style models all carry the same `{success: bool, message: str}` shape. | Introduce a single `Acknowledgement(success: bool, message: str = "")` in `src/models/base.py`. Keep the named subclasses as thin aliases for OpenAPI clarity. |
| GW-2 | `VaultExplorerResponse` aggregates `VaultExplorerKnowledgeResponse` + tree nodes — there's no `kind` discriminator. | Add `kind: Literal["explorer"] = "explorer"` for forward compatibility. |
| GW-3 | The vault router has 32 models in one 250-line file. | Split into `src/gateway/routers/vault/__init__.py` + `models.py`. |
| GW-4 | `dreamy.py:39` and `dreamy.py:805` are `@dataclass` (lines 39 = `_AnalyseRun`, line 805 = unnamed). | Convert both to BaseModel (`AnalyseRunRecord`, `AnalyseProgressRecord`) — they are read by the polling endpoint. |
| GW-5 | `HarnessConfigUpdateRequest` allows full replacement; need `merge_only: bool` field for safer PATCH semantics. | Add the field with default `True`. |
| GW-6 | `AgentsListResponse` returns `agents: list[AgentResponse]` and there is also a `UserProfileResponse` returning unrelated profile — they share the router but have no kinship. | Split `agents.py` into `agents.py` (custom agents) + `profile.py` (user profile). |
