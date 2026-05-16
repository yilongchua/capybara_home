"use client";

import { useEffect, useState } from "react";

import { getBackendBaseURL } from "@/core/config";
import {
  publishWorkspaceRefresh,
  useWorkspaceRefreshQuery,
} from "@/core/workspace-refresh";

import { api } from "@/core/dreamy/api";
import { REFRESH_INTERVAL_ACTIVE, REFRESH_INTERVAL_IDLE } from "@/core/dreamy/constants";

import { useDreamy } from "../context";
import type { WorkflowJson } from "../types";

type WorkflowFetchResult = {
  workflow: WorkflowJson | null;
  notFound: boolean;
};

async function fetchWorkflowJson(threadId: string): Promise<WorkflowFetchResult> {
  const res = await fetch(`${getBackendBaseURL()}${api.threads.dreamy.workflow(threadId)}`);
  if (res.status === 404) {
    return { workflow: null, notFound: true };
  }
  if (!res.ok) throw new Error("failed to load workflow.json");
  const workflow = (await res.json()) as WorkflowJson;
  return { workflow, notFound: false };
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
  const [notFoundStreak, setNotFoundStreak] = useState(0);
  const { data } = useWorkspaceRefreshQuery<WorkflowFetchResult>({
    queryKey: ["dreamy-workflow", threadId],
    queryFn: () => fetchWorkflowJson(threadId),
    enabled: Boolean(threadId && threadId !== "new") && notFoundStreak < 3,
    refetchInterval: (query) => (query.state.data?.workflow ? REFRESH_INTERVAL_ACTIVE : REFRESH_INTERVAL_IDLE),
    staleTime: 0,
    retry: false,
    refreshDomains: threadId ? [`dreamy:${threadId}`, `thread:${threadId}`] : [],
  });

  useEffect(() => {
    setNotFoundStreak(0);
  }, [threadId]);

  useEffect(() => {
    if (!data) return;
    if (data.notFound) {
      setNotFoundStreak((prev) => prev + 1);
      return;
    }
    setNotFoundStreak(0);
  }, [data]);

  const workflow = data?.workflow ?? null;

  useEffect(() => {
    setWorkflowJson(workflow);
  }, [setWorkflowJson, workflow]);

  return workflow;
}
