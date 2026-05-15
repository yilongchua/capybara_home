"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

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

type CheckpointFetchResult = {
  checkpoint: CheckpointData | null;
  notFound: boolean;
};

async function fetchCheckpoint(threadId: string): Promise<CheckpointFetchResult> {
  const res = await fetch(`${getBackendBaseURL()}${api.threads.checkpoint(threadId)}`);
  if (res.status === 404) return { checkpoint: null, notFound: true };
  if (!res.ok) return { checkpoint: null, notFound: false };
  return { checkpoint: (await res.json()) as CheckpointData, notFound: false };
}

export function useCheckpoint(threadId: string, enabled = true) {
  const [notFoundStreak, setNotFoundStreak] = useState(0);
  const query = useQuery<CheckpointFetchResult>({
    queryKey: ["dreamy-checkpoint", threadId],
    queryFn: () => fetchCheckpoint(threadId),
    enabled:
      enabled && Boolean(threadId && threadId !== "new") && notFoundStreak < 3,
    refetchInterval: (query) =>
      query.state.data?.checkpoint ? REFRESH_INTERVAL_ACTIVE : REFRESH_INTERVAL_IDLE,
    staleTime: 0,
    retry: false,
  });

  useEffect(() => {
    setNotFoundStreak(0);
  }, [threadId]);

  useEffect(() => {
    if (!query.data) return;
    if (query.data.notFound) {
      setNotFoundStreak((prev) => prev + 1);
      return;
    }
    setNotFoundStreak(0);
  }, [query.data]);

  return {
    ...query,
    data: query.data?.checkpoint ?? null,
  };
}
