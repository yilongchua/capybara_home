import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  publishWorkspaceRefresh,
  useWorkspaceRefreshQuery,
} from "../workspace-refresh";

import {
  createAgent,
  deleteAgent,
  getAgent,
  listAgents,
  updateAgent,
} from "./api";
import type { CreateAgentRequest, UpdateAgentRequest } from "./types";

export function useAgents() {
  const { data, isLoading, error } = useWorkspaceRefreshQuery({
    queryKey: ["agents"],
    queryFn: () => listAgents(),
    refreshDomains: ["agents"],
  });
  return { agents: data ?? [], isLoading, error };
}

export function useAgent(name: string | null | undefined) {
  const { data, isLoading, error } = useWorkspaceRefreshQuery({
    queryKey: ["agents", name],
    queryFn: () => getAgent(name!),
    enabled: !!name,
    refreshDomains: ["agents"],
    invalidateQueryKey: ["agents"],
    invalidateExact: false,
  });
  return { agent: data ?? null, isLoading, error };
}

export function useCreateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: CreateAgentRequest) => createAgent(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      publishWorkspaceRefresh(["agents"], { source: "agents" });
    },
  });
}

export function useUpdateAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      request,
    }: {
      name: string;
      request: UpdateAgentRequest;
    }) => updateAgent(name, request),
    onSuccess: (_data, { name }) => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agents", name] });
      publishWorkspaceRefresh(["agents"], { source: "agents" });
    },
  });
}

export function useDeleteAgent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => deleteAgent(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      publishWorkspaceRefresh(["agents"], { source: "agents" });
    },
  });
}
