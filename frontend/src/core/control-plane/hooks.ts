import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  publishWorkspaceRefresh,
  useWorkspaceRefreshQuery,
} from "../workspace-refresh";

import {
  cleanupAutoresearch,
  cleanupPipelineRuns,
  createRuntimeSchedulerJob,
  evaluateVaultSufficiency,
  createFeedback,
  createPipelineRun,
  deleteAutoresearchObjective,
  deleteRuntimeSchedulerJob,
  updateRuntimeSchedulerJob,
  updateRuntimeSchedulerJobTime,
  getPipelineRunArtifactContent,
  getPipelineRunArtifact,
  getVaultActionItems,
  getVaultGraph,
  getVaultExplorer,
  getVaultFile,
  getIntegrationStatus,
  getIntegrationServicesStatus,
  getVaultStatus,
  listApprovals,
  listFeedback,
  listProposalApprovals,
  listAutoresearchObjectives,
  listPipelineRuns,
  listPipelineTemplates,
  pauseAutoresearchObjective,
  reingestFolderSyncTarget,
  resolveApproval,
  resolveProposalApproval,
  runSchedulerJob,
  saveToVault,
  saveVaultFile,
  deleteVaultFile,
  searchVault,
  setIntegrationServiceEnabled,
  startIntegrationService,
  startAutoresearchObjective,
  startPipelineRun,
  startVaultIngest,
  getVaultIngestStatus,
  refreshVaultExplorer,
  resumeAutoresearchObjective,
} from "./api";
import type {
  AutoresearchObjective,
  CleanupPipelineRunsRequest,
  CreateFeedbackRequest,
  CreatePipelineRunRequest,
  ResolveProposalApprovalRequest,
  ResolveApprovalRequest,
  SchedulerRuntimeJobCreateRequest,
  SelfImproverDraftReport,
  PipelineArtifactContent,
  VaultSearchResponse,
  VaultSaveRequest,
  VaultActionItemsResponse,
  VaultGraphResponse,
  VaultSufficiencyRequest,
  VaultStatusResponse,
  VaultExplorerResponse,
  VaultFileWriteRequest,
  VaultIngestStatusResponse,
  StartAutoresearchObjectiveRequest,
} from "./types";

function publishControlPlaneRefresh(domains: Array<
  "runs" | "approvals" | "vault" | "integrations" | "feedback"
>) {
  publishWorkspaceRefresh(domains, { source: "control-plane" });
}

export function usePipelineTemplates() {
  const { data, isLoading, error } = useWorkspaceRefreshQuery({
    queryKey: ["control-plane", "templates"],
    queryFn: () => listPipelineTemplates(),
  });
  return { templates: data ?? [], isLoading, error };
}

export function usePipelineRuns(options?: {
  refetchInterval?: number;
  threadId?: string;
  statuses?: string[];
  limit?: number;
}) {
  const threadId = options?.threadId?.trim();
  const statuses = options?.statuses ?? [];
  const limit = options?.limit;
  const { data, isLoading, error } = useWorkspaceRefreshQuery({
    queryKey: ["control-plane", "runs", threadId ?? "", statuses.join(","), limit ?? ""],
    queryFn: () =>
      listPipelineRuns({
        threadId: threadId ?? undefined,
        statuses: statuses.length > 0 ? statuses : undefined,
        limit,
      }),
    refetchInterval: (query) => {
      if (typeof options?.refetchInterval === "number") {
        return options.refetchInterval;
      }
      const runs = query.state.data ?? [];
      const hasActive = runs.some((run) =>
        run.status === "pending_approval" || run.status === "approved" || run.status === "running",
      );
      return hasActive ? 5_000 : 20_000;
    },
    refreshDomains: ["runs"],
  });
  return { runs: data ?? [], isLoading, error };
}

export function useAutoresearchObjectives(options?: { refetchInterval?: number }) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery<AutoresearchObjective[]>({
    queryKey: ["control-plane", "autoresearch-objectives"],
    queryFn: () => listAutoresearchObjectives(),
    refetchInterval: options?.refetchInterval ?? 20_000,
    refreshDomains: ["vault", "runs"],
  });
  return { objectives: data ?? [], isLoading, error };
}

export function usePipelineRunArtifact(
  runId: string | null,
  artifactName: string | null,
) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery<SelfImproverDraftReport>({
    queryKey: ["control-plane", "run-artifact", runId, artifactName],
    queryFn: () => getPipelineRunArtifact(runId!, artifactName!),
    enabled: Boolean(runId && artifactName),
    refreshDomains: ["runs"],
  });
  return { artifact: data ?? null, isLoading, error };
}

export function usePipelineRunArtifactContent(
  runId: string | null,
  artifactName: string | null,
) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery<PipelineArtifactContent>({
    queryKey: ["control-plane", "run-artifact-content", runId, artifactName],
    queryFn: () => getPipelineRunArtifactContent(runId!, artifactName!),
    enabled: Boolean(runId && artifactName),
    refreshDomains: ["runs"],
  });
  return { artifactContent: data ?? null, isLoading, error };
}

export function useVaultStatus(options?: { refetchInterval?: number }) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery<VaultStatusResponse>({
    queryKey: ["control-plane", "vault-status"],
    queryFn: () => getVaultStatus(),
    refetchInterval: options?.refetchInterval ?? 20_000,
    refreshDomains: ["vault", "runs"],
  });
  return { vaultStatus: data ?? null, isLoading, error };
}

export function useVaultSearch(query: string, options?: { enabled?: boolean; limit?: number }) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery<VaultSearchResponse>({
    queryKey: ["control-plane", "vault-search", query, options?.limit ?? 10],
    queryFn: () => searchVault(query, options?.limit ?? 10),
    enabled: Boolean(options?.enabled && query.trim()),
    refreshDomains: ["vault"],
  });
  return { results: data ?? null, isLoading, error };
}

export function useVaultActionItems(options?: { refetchInterval?: number; limit?: number }) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery<VaultActionItemsResponse>({
    queryKey: ["control-plane", "vault-action-items", options?.limit ?? 100],
    queryFn: () => getVaultActionItems(options?.limit ?? 100),
    refetchInterval: options?.refetchInterval ?? 20_000,
    refreshDomains: ["vault", "runs"],
  });
  return { actionItems: data ?? null, isLoading, error };
}

export function useVaultGraph(options?: { refetchInterval?: number; limit?: number }) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery<VaultGraphResponse>({
    queryKey: ["control-plane", "vault-graph", options?.limit ?? 200],
    queryFn: () => getVaultGraph(options?.limit ?? 200),
    refetchInterval: options?.refetchInterval ?? 20_000,
    refreshDomains: ["vault"],
  });
  return { vaultGraph: data ?? null, isLoading, error };
}

export function useVaultExplorer(options?: { refetchInterval?: number; listenForRefreshEvents?: boolean }) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery<VaultExplorerResponse>({
    queryKey: ["control-plane", "vault-explorer"],
    queryFn: () => getVaultExplorer(),
    refetchInterval: options?.refetchInterval,
    refreshDomains: options?.listenForRefreshEvents === false ? [] : ["vault"],
  });
  return { explorer: data ?? null, isLoading, error };
}

export function useVaultFile(path: string | null) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery({
    queryKey: ["control-plane", "vault-file", path ?? ""],
    queryFn: () => getVaultFile(path!),
    enabled: Boolean(path && path.trim().length > 0),
    refreshDomains: ["vault"],
  });
  return { vaultFile: data ?? null, isLoading, error };
}

export function useRefreshVaultExplorer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => refreshVaultExplorer(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-explorer"] });
      publishControlPlaneRefresh(["vault"]);
    },
  });
}

export function useVaultIngestStatus(options?: { refetchInterval?: number; enabled?: boolean }) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery<VaultIngestStatusResponse>({
    queryKey: ["control-plane", "vault-ingest-status"],
    queryFn: () => getVaultIngestStatus(),
    enabled: options?.enabled ?? true,
    refetchInterval: (query) => {
      if (typeof options?.refetchInterval === "number") {
        return options.refetchInterval;
      }
      const status = query.state.data?.status;
      return status === "running" ? 2_000 : 15_000;
    },
    refreshDomains: ["vault"],
  });
  return { ingestStatus: data ?? null, isLoading, error };
}

export function useStartVaultIngest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (options?: { forceReanalyze?: boolean }) => startVaultIngest(options),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-ingest-status"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-status"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-explorer"] });
      publishControlPlaneRefresh(["vault"]);
    },
  });
}

export function useSaveVaultFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: VaultFileWriteRequest) => saveVaultFile(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-file"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-explorer"] });
      publishControlPlaneRefresh(["vault"]);
    },
  });
}

export function useDeleteVaultFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (path: string) => deleteVaultFile(path),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-file"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-explorer"] });
      publishControlPlaneRefresh(["vault"]);
    },
  });
}

export function useEvaluateVaultSufficiency() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: VaultSufficiencyRequest) => evaluateVaultSufficiency(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-status"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-action-items"] });
      publishControlPlaneRefresh(["vault"]);
    },
  });
}

export function useSaveToVault() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: VaultSaveRequest) => saveToVault(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-status"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-search"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-graph"] });
      publishControlPlaneRefresh(["vault"]);
    },
  });
}

export function useCreatePipelineRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreatePipelineRunRequest) => createPipelineRun(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "runs"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "approvals"] });
      publishControlPlaneRefresh(["runs", "approvals"]);
    },
  });
}

export function useStartPipelineRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => startPipelineRun(runId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "runs"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "approvals"] });
      publishControlPlaneRefresh(["runs", "approvals"]);
    },
  });
}

export function useCleanupPipelineRuns() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CleanupPipelineRunsRequest) => cleanupPipelineRuns(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "runs"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "autoresearch-objectives"] });
      publishControlPlaneRefresh(["runs", "vault"]);
    },
  });
}

export function useCleanupAutoresearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (includeRuns: boolean) => cleanupAutoresearch(includeRuns),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "runs"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "autoresearch-objectives"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-status"] });
      publishControlPlaneRefresh(["runs", "vault"]);
    },
  });
}

export function useApprovals(options?: { refetchInterval?: number }) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery({
    queryKey: ["control-plane", "approvals"],
    queryFn: () => listApprovals(),
    refetchInterval: options?.refetchInterval,
    refreshDomains: ["approvals", "runs"],
  });
  return { approvals: data ?? [], isLoading, error };
}

export function useResolveApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      approvalId,
      request,
    }: {
      approvalId: string;
      request: ResolveApprovalRequest;
    }) => resolveApproval(approvalId, request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "approvals"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "runs"] });
      publishControlPlaneRefresh(["approvals", "runs"]);
    },
  });
}

export function useProposalApprovals(options?: { refetchInterval?: number }) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery({
    queryKey: ["control-plane", "proposal-approvals"],
    queryFn: () => listProposalApprovals(),
    refetchInterval: options?.refetchInterval,
    refreshDomains: ["approvals", "runs"],
  });
  return { proposals: data ?? [], isLoading, error };
}

export function useResolveProposalApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      runId,
      proposalId,
      request,
    }: {
      runId: string;
      proposalId: string;
      request: ResolveProposalApprovalRequest;
    }) => resolveProposalApproval(runId, proposalId, request),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["control-plane", "proposal-approvals"],
      });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "runs"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "approvals"] });
      publishControlPlaneRefresh(["approvals", "runs"]);
    },
  });
}

export function useFeedback() {
  const { data, isLoading, error } = useWorkspaceRefreshQuery({
    queryKey: ["control-plane", "feedback"],
    queryFn: () => listFeedback(),
    refreshDomains: ["feedback"],
  });
  return { feedback: data ?? [], isLoading, error };
}

export function useCreateFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateFeedbackRequest) => createFeedback(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "feedback"] });
      publishControlPlaneRefresh(["feedback"]);
    },
  });
}

export function useIntegrationStatus() {
  const { data, isLoading, error } = useWorkspaceRefreshQuery({
    queryKey: ["control-plane", "integrations"],
    queryFn: () => getIntegrationStatus(),
    refetchInterval: 30_000,
    refreshDomains: ["integrations", "runs", "vault"],
  });
  return { integrationStatus: data ?? null, isLoading, error };
}

export function useIntegrationServicesStatus() {
  const { data, isLoading, error } = useWorkspaceRefreshQuery({
    queryKey: ["control-plane", "integration-services"],
    queryFn: () => getIntegrationServicesStatus(),
    refetchInterval: 30_000,
    refreshDomains: ["integrations"],
  });
  return { servicesStatus: data ?? null, isLoading, error };
}

export function useStartIntegrationService() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (serviceId: string) => startIntegrationService(serviceId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["control-plane", "integration-services"],
      });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "integrations"] });
      publishControlPlaneRefresh(["integrations"]);
    },
  });
}

export function useRunSchedulerJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => runSchedulerJob(jobId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "integrations"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "runs"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "approvals"] });
      publishControlPlaneRefresh(["integrations", "runs", "approvals", "vault"]);
    },
  });
}

export function useCreateRuntimeSchedulerJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: SchedulerRuntimeJobCreateRequest) =>
      createRuntimeSchedulerJob(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "integrations"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "runs"] });
      publishControlPlaneRefresh(["integrations", "runs", "vault"]);
    },
  });
}

export function useDeleteRuntimeSchedulerJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => deleteRuntimeSchedulerJob(jobId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "integrations"] });
      publishControlPlaneRefresh(["integrations", "vault"]);
    },
  });
}

export function useUpdateRuntimeSchedulerJobTime() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, dailyTime }: { jobId: string; dailyTime: string }) =>
      updateRuntimeSchedulerJobTime(jobId, dailyTime),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "integrations"] });
      publishControlPlaneRefresh(["integrations", "vault"]);
    },
  });
}

export function useUpdateRuntimeSchedulerJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      jobId,
      patch,
    }: {
      jobId: string;
      patch: { daily_time?: string; endpoint_goal?: string };
    }) => updateRuntimeSchedulerJob(jobId, patch),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "integrations"] });
      publishControlPlaneRefresh(["integrations", "vault"]);
    },
  });
}

export function useStartAutoresearchObjective() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: StartAutoresearchObjectiveRequest) =>
      startAutoresearchObjective(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["control-plane", "autoresearch-objectives"],
      });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "integrations"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "runs"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-status"] });
      publishControlPlaneRefresh(["vault", "runs", "integrations"]);
    },
  });
}

export function usePauseAutoresearchObjective() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ objectiveId, reason }: { objectiveId: string; reason?: string }) =>
      pauseAutoresearchObjective(objectiveId, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["control-plane", "autoresearch-objectives"],
      });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "integrations"] });
      publishControlPlaneRefresh(["vault", "integrations"]);
    },
  });
}

export function useResumeAutoresearchObjective() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (objectiveId: string) => resumeAutoresearchObjective(objectiveId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["control-plane", "autoresearch-objectives"],
      });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "integrations"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "runs"] });
      publishControlPlaneRefresh(["vault", "runs", "integrations"]);
    },
  });
}

export function useDeleteAutoresearchObjective() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (objectiveId: string) => deleteAutoresearchObjective(objectiveId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["control-plane", "autoresearch-objectives"],
      });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "integrations"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-status"] });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "vault-action-items"] });
      publishControlPlaneRefresh(["vault", "runs", "integrations"]);
    },
  });
}

export function useSetIntegrationServiceEnabled() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      serviceId,
      enabled,
    }: {
      serviceId: string;
      enabled: boolean;
    }) => setIntegrationServiceEnabled(serviceId, enabled),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["control-plane", "integration-services"],
      });
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "integrations"] });
      publishControlPlaneRefresh(["integrations"]);
    },
  });
}

export function useReingestFolderSyncTarget() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (targetId: string) => reingestFolderSyncTarget(targetId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["control-plane", "integrations"] });
      publishControlPlaneRefresh(["integrations", "vault"]);
    },
  });
}
