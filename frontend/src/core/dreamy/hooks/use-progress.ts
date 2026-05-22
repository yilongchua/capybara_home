"use client";

import { useQuery } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/dreamy/api";
import { REFRESH_INTERVAL_ACTIVE, REFRESH_INTERVAL_IDLE } from "@/core/dreamy/constants";
import type { ProgressData } from "@/core/dreamy/types";
import { useDocumentVisible } from "@/core/workspace-refresh";

async function fetchProgress(threadId: string): Promise<ProgressData | null> {
  const res = await fetch(`${getBackendBaseURL()}${api.threads.dreamy.executor.status(threadId)}`);
  if (!res.ok) return null;
  return res.json() as Promise<ProgressData>;
}

export const EXECUTOR_PROGRESS_STATES = new Set<ProgressData["state"]>([
  "running",
  "awaiting_approval",
  "paused",
  "stopped",
  "completed",
  "failed",
]);

const EXECUTOR_FAST_POLL_STATES = new Set<ProgressData["state"]>([
  "running",
  "awaiting_approval",
  "paused",
]);

export function useProgress(threadId: string, enabled = true) {
  const isVisible = useDocumentVisible();
  return useQuery<ProgressData | null>({
    queryKey: ["dreamy-executor-progress", threadId],
    queryFn: () => fetchProgress(threadId),
    enabled: enabled && Boolean(threadId && threadId !== "new"),
    refetchInterval: (query) => {
      if (!isVisible) return false;
      const data = query.state.data;
      if (data && EXECUTOR_FAST_POLL_STATES.has(data.state)) return REFRESH_INTERVAL_ACTIVE;
      return REFRESH_INTERVAL_IDLE;
    },
    staleTime: 0,
    retry: false,
  });
}
