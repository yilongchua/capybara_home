"use client";

import { useEffect } from "react";

import { getBackendBaseURL } from "@/core/config";
import {
  publishWorkspaceRefresh,
  useWorkspaceRefreshQuery,
} from "@/core/workspace-refresh";

import { api } from "@/core/dreamy/api";
import { REFRESH_INTERVAL_ACTIVE, REFRESH_INTERVAL_IDLE } from "@/core/dreamy/constants";

import { useDreamy } from "../context";
import type { WorkflowJson } from "../types";

async function fetchWorkflowJson(threadId: string): Promise<WorkflowJson | null> {
  const res = await fetch(`${getBackendBaseURL()}${api.threads.dreamy.workflow(threadId)}`);
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) throw new Error("failed to load workflow.json");
  return res.json() as Promise<WorkflowJson>;
}

export async function saveWorkflowJson(threadId: string, workflow: WorkflowJson): Promise<void> {
  await fetch(`${getBackendBaseURL()}${api.threads.dreamy.workflow(threadId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflow }),
  });
  publishWorkspaceRefresh([`dreamy:${threadId}`, `thread:${threadId}`], {
    source: "dreamy-workflow",
  });
}

export function useWorkflowJson(threadId: string) {
  const { setWorkflowJson } = useDreamy();
  const { data } = useWorkspaceRefreshQuery<WorkflowJson | null>({
    queryKey: ["dreamy-workflow", threadId],
    queryFn: () => fetchWorkflowJson(threadId),
    enabled: Boolean(threadId && threadId !== "new"),
    refetchInterval: (query) => (query.state.data ? REFRESH_INTERVAL_ACTIVE : REFRESH_INTERVAL_IDLE),
    staleTime: 0,
    retry: false,
    refreshDomains: threadId ? [`dreamy:${threadId}`, `thread:${threadId}`] : [],
  });

  useEffect(() => {
    setWorkflowJson(data ?? null);
  }, [data, setWorkflowJson]);

  return data ?? null;
}
