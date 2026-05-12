"use client";

import { useQuery } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/dreamy/api";
import { REFRESH_INTERVAL_ACTIVE, REFRESH_INTERVAL_IDLE } from "@/core/dreamy/constants";

export interface CheckpointData {
  total: number;
  completed: number[];
  last_done: number | null;
  started_at: string | null;
  updated_at: string | null;
}

async function fetchCheckpoint(threadId: string): Promise<CheckpointData | null> {
  const res = await fetch(`${getBackendBaseURL()}${api.threads.checkpoint(threadId)}`);
  if (!res.ok) return null;
  return res.json() as Promise<CheckpointData>;
}

export function useCheckpoint(threadId: string, enabled = true) {
  return useQuery<CheckpointData | null>({
    queryKey: ["dreamy-checkpoint", threadId],
    queryFn: () => fetchCheckpoint(threadId),
    enabled: enabled && Boolean(threadId && threadId !== "new"),
    refetchInterval: (query) => (query.state.data ? REFRESH_INTERVAL_ACTIVE : REFRESH_INTERVAL_IDLE),
    staleTime: 0,
    retry: false,
  });
}
