import { getBackendBaseURL } from "@/core/config";

import type {
  ApprovalRequest,
  CreateFeedbackRequest,
  CreatePipelineRunRequest,
  FeedbackEvent,
  FolderSyncManifest,
  IntegrationStatusResponse,
  PipelineRun,
  PipelineTemplate,
  PipelineArtifactContent,
  ProposalApprovalItem,
  ResolveApprovalRequest,
  ResolveProposalApprovalRequest,
  SchedulerRuntimeJobCreateRequest,
  StartAutoresearchObjectiveRequest,
  StartAutoresearchObjectiveResponse,
  RunAutoresearchObjectiveResponse,
  DeleteAutoresearchObjectiveResponse,
  CleanupAutoresearchResponse,
  CleanupPipelineRunsRequest,
  CleanupPipelineRunsResponse,
  AutoresearchObjective,
  SelfImproverDraftReport,
  VaultSearchResponse,
  VaultSaveRequest,
  VaultActionItemsResponse,
  VaultSufficiencyRequest,
  VaultSufficiencyResponse,
  VaultStatusResponse,
  VaultWriteResponse,
  VaultExplorerResponse,
  VaultExplorerChildrenResponse,
  VaultFileResponse,
  VaultFileWriteRequest,
  VaultIngestStatusResponse,
  VaultLintResponse,
  VaultEntityBrowserResponse,
  VaultEntityDismissalsResponse,
  VaultEntityDismissRequest,
  VaultEntityDismissResponse,
  VaultEntityRestoreResponse,
  VaultEntityAutoresearchRequest,
  VaultEntityAutoresearchResponse,
} from "./types";

async function parseError(response: Response, fallback: string) {
  const err = (await response.json().catch(() => ({}))) as { detail?: string };
  throw new Error(err.detail ?? fallback);
}

export async function listPipelineTemplates(): Promise<PipelineTemplate[]> {
  const response = await fetch(`${getBackendBaseURL()}/api/pipelines`);
  if (!response.ok) {
    await parseError(response, `Failed to load pipelines: ${response.statusText}`);
  }
  const data = (await response.json()) as { items: PipelineTemplate[] };
  return data.items;
}

export interface ListPipelineRunsParams {
  threadId?: string;
  statuses?: string[];
  limit?: number;
}

export async function listPipelineRuns(params?: ListPipelineRunsParams): Promise<PipelineRun[]> {
  const qs = new URLSearchParams();
  if (params?.threadId) {
    qs.set("thread_id", params.threadId);
  }
  if (params?.statuses && params.statuses.length > 0) {
    qs.set("status", params.statuses.join(","));
  }
  if (typeof params?.limit === "number") {
    qs.set("limit", String(params.limit));
  }
  const url = `${getBackendBaseURL()}/api/pipelines/runs${qs.size > 0 ? `?${qs.toString()}` : ""}`;
  const response = await fetch(url);
  if (!response.ok) {
    await parseError(response, `Failed to load pipeline runs: ${response.statusText}`);
  }
  const data = (await response.json()) as { items: PipelineRun[] };
  return data.items;
}

export async function createPipelineRun(
  request: CreatePipelineRunRequest,
): Promise<PipelineRun> {
  const response = await fetch(`${getBackendBaseURL()}/api/pipelines/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    await parseError(response, `Failed to create pipeline run: ${response.statusText}`);
  }
  return response.json() as Promise<PipelineRun>;
}

export async function startPipelineRun(runId: string): Promise<PipelineRun> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/pipelines/runs/${runId}/start`,
    { method: "POST" },
  );
  if (!response.ok) {
    await parseError(response, `Failed to start pipeline run: ${response.statusText}`);
  }
  return response.json() as Promise<PipelineRun>;
}

export async function getPipelineRunArtifact(
  runId: string,
  artifactName: string,
): Promise<SelfImproverDraftReport> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/pipelines/runs/${runId}/artifacts/${encodeURIComponent(artifactName)}`,
  );
  if (!response.ok) {
    await parseError(response, `Failed to load pipeline artifact: ${response.statusText}`);
  }
  return response.json() as Promise<SelfImproverDraftReport>;
}

export async function getPipelineRunArtifactContent(
  runId: string,
  artifactName: string,
): Promise<PipelineArtifactContent> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/pipelines/runs/${runId}/artifacts/${encodeURIComponent(artifactName)}/content`,
  );
  if (!response.ok) {
    await parseError(response, `Failed to load artifact content: ${response.statusText}`);
  }
  return response.json() as Promise<PipelineArtifactContent>;
}

export async function listAutoresearchObjectives(): Promise<AutoresearchObjective[]> {
  const response = await fetch(`${getBackendBaseURL()}/api/pipelines/autoresearch`);
  if (!response.ok) {
    await parseError(response, `Failed to load autoresearch objectives: ${response.statusText}`);
  }
  const data = (await response.json()) as { items: AutoresearchObjective[] };
  return data.items;
}

export async function startAutoresearchObjective(
  request: StartAutoresearchObjectiveRequest,
): Promise<StartAutoresearchObjectiveResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/pipelines/autoresearch/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    await parseError(response, `Failed to start autoresearch objective: ${response.statusText}`);
  }
  return response.json() as Promise<StartAutoresearchObjectiveResponse>;
}

export async function pauseAutoresearchObjective(
  objectiveId: string,
  reason = "denied",
): Promise<AutoresearchObjective> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/pipelines/autoresearch/${encodeURIComponent(objectiveId)}/pause`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    },
  );
  if (!response.ok) {
    await parseError(response, `Failed to pause autoresearch objective: ${response.statusText}`);
  }
  return response.json() as Promise<AutoresearchObjective>;
}

export async function resumeAutoresearchObjective(
  objectiveId: string,
): Promise<AutoresearchObjective> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/pipelines/autoresearch/${encodeURIComponent(objectiveId)}/resume`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    await parseError(response, `Failed to resume autoresearch objective: ${response.statusText}`);
  }
  return response.json() as Promise<AutoresearchObjective>;
}

export async function stopAutoresearchObjective(
  objectiveId: string,
): Promise<AutoresearchObjective> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/pipelines/autoresearch/${encodeURIComponent(objectiveId)}/stop`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    await parseError(response, `Failed to stop autoresearch objective: ${response.statusText}`);
  }
  return response.json() as Promise<AutoresearchObjective>;
}

export async function runAutoresearchObjective(
  objectiveId: string,
): Promise<RunAutoresearchObjectiveResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/pipelines/autoresearch/${encodeURIComponent(objectiveId)}/run`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    await parseError(response, `Failed to run autoresearch objective: ${response.statusText}`);
  }
  return response.json() as Promise<RunAutoresearchObjectiveResponse>;
}

export async function deleteAutoresearchObjective(
  objectiveId: string,
): Promise<DeleteAutoresearchObjectiveResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/pipelines/autoresearch/${encodeURIComponent(objectiveId)}`,
    {
      method: "DELETE",
    },
  );
  if (!response.ok) {
    await parseError(response, `Failed to delete autoresearch objective: ${response.statusText}`);
  }
  return response.json() as Promise<DeleteAutoresearchObjectiveResponse>;
}

export async function cleanupPipelineRuns(
  request: CleanupPipelineRunsRequest,
): Promise<CleanupPipelineRunsResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/pipelines/runs/cleanup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    await parseError(response, `Failed to clean pipeline runs: ${response.statusText}`);
  }
  return response.json() as Promise<CleanupPipelineRunsResponse>;
}

export async function cleanupAutoresearch(includeRuns = true): Promise<CleanupAutoresearchResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/pipelines/autoresearch/cleanup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ include_runs: includeRuns }),
  });
  if (!response.ok) {
    await parseError(response, `Failed to clean autoresearch data: ${response.statusText}`);
  }
  return response.json() as Promise<CleanupAutoresearchResponse>;
}

export async function getVaultStatus(): Promise<VaultStatusResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/vault/status`);
  if (!response.ok) {
    await parseError(response, `Failed to load vault status: ${response.statusText}`);
  }
  return response.json() as Promise<VaultStatusResponse>;
}

export async function searchVault(
  query: string,
  limit = 10,
): Promise<VaultSearchResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/vault/search?q=${encodeURIComponent(query)}&limit=${limit}`,
  );
  if (!response.ok) {
    await parseError(response, `Failed to search vault: ${response.statusText}`);
  }
  return response.json() as Promise<VaultSearchResponse>;
}

export async function getVaultActionItems(limit = 100): Promise<VaultActionItemsResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/vault/action-items?limit=${Math.max(1, Math.min(500, limit))}`,
  );
  if (!response.ok) {
    await parseError(response, `Failed to load vault action items: ${response.statusText}`);
  }
  return response.json() as Promise<VaultActionItemsResponse>;
}

export async function saveToVault(request: VaultSaveRequest): Promise<VaultWriteResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/vault/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    await parseError(response, `Failed to save to vault: ${response.statusText}`);
  }
  return response.json() as Promise<VaultWriteResponse>;
}

export async function getVaultExplorer(): Promise<VaultExplorerResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/vault/explorer`);
  if (!response.ok) {
    await parseError(response, `Failed to load vault explorer: ${response.statusText}`);
  }
  return response.json() as Promise<VaultExplorerResponse>;
}

export async function refreshVaultExplorer(): Promise<VaultExplorerResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/vault/explorer/refresh`, {
    method: "POST",
  });
  if (!response.ok) {
    await parseError(response, `Failed to refresh vault explorer: ${response.statusText}`);
  }
  return response.json() as Promise<VaultExplorerResponse>;
}

export async function getVaultExplorerChildren(path: string): Promise<VaultExplorerChildrenResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/vault/explorer/children?path=${encodeURIComponent(path)}`,
  );
  if (!response.ok) {
    await parseError(response, `Failed to load vault folder: ${response.statusText}`);
  }
  return response.json() as Promise<VaultExplorerChildrenResponse>;
}

export async function startVaultIngest(
  options?: { forceReanalyze?: boolean; workers?: number },
): Promise<VaultIngestStatusResponse> {
  const workers = Math.max(1, Math.min(3, Math.trunc(options?.workers ?? 1)));
  const response = await fetch(`${getBackendBaseURL()}/api/vault/ingest/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      force_reanalyze: Boolean(options?.forceReanalyze),
      workers,
    }),
  });
  if (!response.ok) {
    await parseError(response, `Failed to start vault ingest: ${response.statusText}`);
  }
  return response.json() as Promise<VaultIngestStatusResponse>;
}

export async function getVaultIngestStatus(): Promise<VaultIngestStatusResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/vault/ingest/status`);
  if (!response.ok) {
    await parseError(response, `Failed to load vault ingest status: ${response.statusText}`);
  }
  return response.json() as Promise<VaultIngestStatusResponse>;
}

export async function cancelVaultIngest(): Promise<VaultIngestStatusResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/vault/ingest/cancel`, {
    method: "POST",
  });
  if (!response.ok) {
    await parseError(response, `Failed to cancel vault ingest: ${response.statusText}`);
  }
  return response.json() as Promise<VaultIngestStatusResponse>;
}

export async function lintVault(options?: {
  dryRun?: boolean;
  useLlm?: boolean;
  entitySlugs?: string[];
  conceptSlugs?: string[];
}): Promise<VaultLintResponse> {
  const body: Record<string, unknown> = {
    dry_run: options?.dryRun ?? true,
    use_llm: options?.useLlm ?? false,
  };
  if (options?.entitySlugs !== undefined) body.entity_slugs = options.entitySlugs;
  if (options?.conceptSlugs !== undefined) body.concept_slugs = options.conceptSlugs;
  const response = await fetch(`${getBackendBaseURL()}/api/vault/lint`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    await parseError(response, `Failed to lint vault: ${response.statusText}`);
  }
  return response.json() as Promise<VaultLintResponse>;
}

export async function getVaultFile(path: string): Promise<VaultFileResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/vault/file?path=${encodeURIComponent(path)}`,
  );
  if (!response.ok) {
    await parseError(response, `Failed to load vault file: ${response.statusText}`);
  }
  return response.json() as Promise<VaultFileResponse>;
}

export async function saveVaultFile(request: VaultFileWriteRequest): Promise<{
  status: string;
  path: string;
  bytes: number;
}> {
  const response = await fetch(`${getBackendBaseURL()}/api/vault/file`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    await parseError(response, `Failed to save vault file: ${response.statusText}`);
  }
  return response.json() as Promise<{ status: string; path: string; bytes: number }>;
}

export async function getVaultEntityBrowser(
  options?: { top?: number; bottom?: number; criticalMaxDegree?: number },
): Promise<VaultEntityBrowserResponse> {
  const params = new URLSearchParams();
  if (options?.top !== undefined) params.set("top", String(options.top));
  if (options?.bottom !== undefined) params.set("bottom", String(options.bottom));
  if (options?.criticalMaxDegree !== undefined) {
    params.set("critical_max_degree", String(options.criticalMaxDegree));
  }
  const qs = params.toString();
  const response = await fetch(
    `${getBackendBaseURL()}/api/vault/entity-browser${qs ? `?${qs}` : ""}`,
  );
  if (!response.ok) {
    await parseError(response, `Failed to load entity browser: ${response.statusText}`);
  }
  return response.json() as Promise<VaultEntityBrowserResponse>;
}

export async function listVaultEntityDismissals(): Promise<VaultEntityDismissalsResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/vault/entity-dismissals`);
  if (!response.ok) {
    await parseError(response, `Failed to load entity dismissals: ${response.statusText}`);
  }
  return response.json() as Promise<VaultEntityDismissalsResponse>;
}

export async function dismissVaultEntity(
  slug: string,
  request: VaultEntityDismissRequest = {},
): Promise<VaultEntityDismissResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/vault/entities/${encodeURIComponent(slug)}/dismiss`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    await parseError(response, `Failed to dismiss entity: ${response.statusText}`);
  }
  return response.json() as Promise<VaultEntityDismissResponse>;
}

export async function restoreVaultEntityDismissal(
  slug: string,
): Promise<VaultEntityRestoreResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/vault/entity-dismissals/${encodeURIComponent(slug)}/restore`,
    { method: "POST" },
  );
  if (!response.ok) {
    await parseError(response, `Failed to restore entity dismissal: ${response.statusText}`);
  }
  return response.json() as Promise<VaultEntityRestoreResponse>;
}

export async function startVaultEntityAutoresearch(
  slug: string,
  request: VaultEntityAutoresearchRequest = {},
): Promise<VaultEntityAutoresearchResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/vault/entities/${encodeURIComponent(slug)}/autoresearch`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    await parseError(response, `Failed to start entity autoresearch: ${response.statusText}`);
  }
  return response.json() as Promise<VaultEntityAutoresearchResponse>;
}

export async function deleteVaultFile(path: string): Promise<{ status: string; path: string }> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/vault/file?path=${encodeURIComponent(path)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    await parseError(response, `Failed to delete vault file: ${response.statusText}`);
  }
  return response.json() as Promise<{ status: string; path: string }>;
}

export async function deleteVaultKnowledgeGraph(): Promise<{
  status: string;
  removed: Record<string, number>;
}> {
  const response = await fetch(`${getBackendBaseURL()}/api/vault/knowledge-graph`, {
    method: "DELETE",
  });
  if (!response.ok) {
    await parseError(response, `Failed to delete knowledge graph: ${response.statusText}`);
  }
  return response.json() as Promise<{ status: string; removed: Record<string, number> }>;
}

export async function evaluateVaultSufficiency(
  request: VaultSufficiencyRequest,
): Promise<VaultSufficiencyResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/vault/sufficiency/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    await parseError(response, `Failed to evaluate vault sufficiency: ${response.statusText}`);
  }
  return response.json() as Promise<VaultSufficiencyResponse>;
}

export async function listApprovals(): Promise<ApprovalRequest[]> {
  const response = await fetch(`${getBackendBaseURL()}/api/approvals`);
  if (!response.ok) {
    await parseError(response, `Failed to load approvals: ${response.statusText}`);
  }
  const data = (await response.json()) as { items: ApprovalRequest[] };
  return data.items;
}

export async function resolveApproval(
  approvalId: string,
  request: ResolveApprovalRequest,
): Promise<PipelineRun> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/approvals/${approvalId}/resolve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    await parseError(response, `Failed to resolve approval: ${response.statusText}`);
  }
  return response.json() as Promise<PipelineRun>;
}

export async function listProposalApprovals(): Promise<ProposalApprovalItem[]> {
  const response = await fetch(`${getBackendBaseURL()}/api/approvals/proposals`);
  if (!response.ok) {
    await parseError(
      response,
      `Failed to load proposal approvals: ${response.statusText}`,
    );
  }
  const data = (await response.json()) as { items: ProposalApprovalItem[] };
  return data.items;
}

export async function resolveProposalApproval(
  runId: string,
  proposalId: string,
  request: ResolveProposalApprovalRequest,
): Promise<ProposalApprovalItem> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/approvals/proposals/${encodeURIComponent(runId)}/${encodeURIComponent(proposalId)}/resolve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    await parseError(
      response,
      `Failed to resolve proposal approval: ${response.statusText}`,
    );
  }
  return response.json() as Promise<ProposalApprovalItem>;
}

export async function listFeedback(): Promise<FeedbackEvent[]> {
  const response = await fetch(`${getBackendBaseURL()}/api/feedback`);
  if (!response.ok) {
    await parseError(response, `Failed to load feedback: ${response.statusText}`);
  }
  const data = (await response.json()) as { items: FeedbackEvent[] };
  return data.items;
}

export async function createFeedback(
  request: CreateFeedbackRequest,
): Promise<FeedbackEvent> {
  const response = await fetch(`${getBackendBaseURL()}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    await parseError(response, `Failed to submit feedback: ${response.statusText}`);
  }
  return response.json() as Promise<FeedbackEvent>;
}

export async function getIntegrationStatus(): Promise<IntegrationStatusResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/integrations/status`);
  if (!response.ok) {
    await parseError(
      response,
      `Failed to load integrations status: ${response.statusText}`,
    );
  }
  return response.json() as Promise<IntegrationStatusResponse>;
}

export async function runSchedulerJob(jobId: string): Promise<PipelineRun> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/scheduler/${jobId}/run`,
    { method: "POST" },
  );
  if (!response.ok) {
    await parseError(
      response,
      `Failed to run scheduler job: ${response.statusText}`,
    );
  }
  return response.json() as Promise<PipelineRun>;
}

export async function createRuntimeSchedulerJob(
  request: SchedulerRuntimeJobCreateRequest,
) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/scheduler/jobs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    await parseError(
      response,
      `Failed to create runtime scheduler job: ${response.statusText}`,
    );
  }
  return response.json() as Promise<Record<string, unknown>>;
}

export async function deleteRuntimeSchedulerJob(jobId: string) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/scheduler/jobs/${encodeURIComponent(jobId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    await parseError(
      response,
      `Failed to delete runtime scheduler job: ${response.statusText}`,
    );
  }
  return response.json() as Promise<{ deleted: boolean; job_id: string }>;
}

export async function updateRuntimeSchedulerJob(
  jobId: string,
  patch: { daily_time?: string; endpoint_goal?: string },
) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/scheduler/jobs/${encodeURIComponent(jobId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    },
  );
  if (!response.ok) {
    await parseError(
      response,
      `Failed to update scheduler job: ${response.statusText}`,
    );
  }
  return response.json() as Promise<Record<string, unknown>>;
}

export async function updateRuntimeSchedulerJobTime(jobId: string, dailyTime: string) {
  return updateRuntimeSchedulerJob(jobId, { daily_time: dailyTime });
}

export async function reingestFolderSyncTarget(
  targetId: string,
): Promise<FolderSyncManifest> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/integrations/folder-sync/${targetId}/ingest`,
    { method: "POST" },
  );
  if (!response.ok) {
    await parseError(
      response,
      `Failed to re-ingest folder sync target: ${response.statusText}`,
    );
  }
  return response.json() as Promise<FolderSyncManifest>;
}
