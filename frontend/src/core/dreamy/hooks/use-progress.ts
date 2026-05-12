"use client";

import { useQuery } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/dreamy/api";
import { REFRESH_INTERVAL_ACTIVE } from "@/core/dreamy/constants";
import type { ProgressData } from "@/core/dreamy/types";

async function fetchProgress(threadId: string): Promise<ProgressData | null> {
  const res = await fetch(`${getBackendBaseURL()}${api.threads.dreamy.executor.status(threadId)}`);
  if (!res.ok) return null;
  return res.json() as Promise<ProgressData>;
}

export function useProgress(threadId: string, enabled = true) {
  return useQuery<ProgressData | null>({
    queryKey: ["dreamy-executor-progress", threadId],
    queryFn: () => fetchProgress(threadId),
    enabled: enabled && Boolean(threadId && threadId !== "new"),
    refetchInterval: REFRESH_INTERVAL_ACTIVE,
    staleTime: 0,
    retry: false,
  });
}

export const EXECUTOR_ACTIVE_STATES = new Set<ProgressData["state"]>([
  "running",
  "paused",
  "stopped",
  "completed",
  "failed",
]);
