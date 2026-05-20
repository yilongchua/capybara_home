"use client";

import { useEffect, useRef } from "react";

import { useRunningRun } from "./use-running-run";

type ThreadStream = {
  isLoading: boolean;
  joinStream: (runId: string) => Promise<void>;
};

/**
 * Rejoin an out-of-band server run (execute plan, planner auto-handoff) via SSE.
 */
export function useRejoinRunningRun(
  threadId: string | null | undefined,
  thread: ThreadStream,
  options?: { pollBump?: number },
): ReturnType<typeof useRunningRun> {
  const pollBump = options?.pollBump ?? 0;
  const { runningRun, loading } = useRunningRun(threadId, pollBump);
  const lastJoinedRunningRunRef = useRef<string | null>(null);

  useEffect(() => {
    lastJoinedRunningRunRef.current = null;
  }, [threadId]);

  useEffect(() => {
    const runId = runningRun?.runId;
    if (!runId) {
      return;
    }
    if (lastJoinedRunningRunRef.current === runId) {
      return;
    }
    lastJoinedRunningRunRef.current = runId;
    void thread.joinStream(runId).catch((error) => {
      lastJoinedRunningRunRef.current = null;
      console.warn("Failed to rejoin running stream:", error);
    });
  }, [runningRun?.runId, thread]);

  return { runningRun, loading };
}
