import { useEffect, useMemo, useRef, useState } from "react";

import {
  publishWorkspaceRefresh,
  useWorkspaceRefreshSubscription,
} from "@/core/workspace-refresh";

import { fetchGenerationCompletions, fetchGenerationJobs } from "./api";
import type { GenerationJob } from "./types";

export interface LiveGenerationNotice {
  id: string;
  content: string;
  artifactPath?: string;
}

function noticeText(job: GenerationJob): string {
  if (job.status === "completed") {
    const path = job.output_virtual_path ?? job.expected_virtual_path;
    return `Generation completed (${job.kind}). File stored at: \`${path}\`.`;
  }
  if (job.status === "failed") {
    return `Generation failed (${job.kind}) for job \`${job.id}\`: ${job.error ?? "Unknown error"}`;
  }
  return `Generation timed out (${job.kind}) for job \`${job.id}\`.`;
}

export function useGenerationCompletions(threadId: string) {
  const [notices, setNotices] = useState<LiveGenerationNotice[]>([]);
  const [artifactPaths, setArtifactPaths] = useState<string[]>([]);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [isDocumentVisible, setIsDocumentVisible] = useState(
    () => typeof document === "undefined" || document.visibilityState === "visible",
  );
  const sinceSeqRef = useRef(0);
  const seenSeqRef = useRef<Set<number>>(new Set());
  const recentActivityUntilRef = useRef(0);
  const lastJobsCheckAtRef = useRef(0);
  const hasActiveJobsRef = useRef(false);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    const onVisibilityChange = () => {
      setIsDocumentVisible(document.visibilityState === "visible");
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

  useWorkspaceRefreshSubscription(
    threadId ? [`thread:${threadId}`] : [],
    () => {
      setRefreshSignal((value) => value + 1);
    },
    { includeOwnEvents: false },
  );

  useEffect(() => {
    sinceSeqRef.current = 0;
    seenSeqRef.current = new Set();
    recentActivityUntilRef.current = 0;
    lastJobsCheckAtRef.current = 0;
    hasActiveJobsRef.current = false;
    setNotices([]);
    setArtifactPaths([]);
  }, [threadId]);

  useEffect(() => {
    if (!threadId) {
      return;
    }
    let active = true;
    let timer: number | null = null;

    const schedule = async () => {
      if (!active) return;

      let receivedItems = false;
      const now = Date.now();
      const hasRecentActivity = recentActivityUntilRef.current > now;
      let isRelevant = hasRecentActivity || hasActiveJobsRef.current;
      // Only re-check jobs every 60 s. The old condition (`!isRelevant || ...`)
      // fired on every schedule iteration when there were no active jobs, producing
      // O(schedule-calls) API requests instead of O(1/min) on idle threads.
      const shouldCheckJobs = now - lastJobsCheckAtRef.current >= 60_000;

      try {
        if (shouldCheckJobs) {
          const jobs = await fetchGenerationJobs(threadId);
          if (!active) return;
          hasActiveJobsRef.current = jobs.some((job) =>
            job.status === "queued" || job.status === "submitted" || job.status === "running",
          );
          lastJobsCheckAtRef.current = Date.now();
          isRelevant = hasRecentActivity || hasActiveJobsRef.current;
        }

        if (isRelevant || shouldCheckJobs) {
          const payload = await fetchGenerationCompletions(threadId, sinceSeqRef.current);
          if (!active) return;

          sinceSeqRef.current = Math.max(sinceSeqRef.current, payload.next_since_seq);

          const newNotices: LiveGenerationNotice[] = [];
          const newArtifacts: string[] = [];
          for (const item of payload.items) {
            const seq = item.completion_seq ?? 0;
            if (seq <= 0 || seenSeqRef.current.has(seq)) {
              continue;
            }
            seenSeqRef.current.add(seq);
            receivedItems = true;
            const artifact = item.output_virtual_path ?? undefined;
            if (artifact) {
              newArtifacts.push(artifact);
            }
            newNotices.push({
              id: `gen-notice-${seq}`,
              content: noticeText(item),
              artifactPath: artifact,
            });
          }

          if (newNotices.length > 0) {
            setNotices((prev) => [...prev, ...newNotices]);
            publishWorkspaceRefresh(["threads", `thread:${threadId}`], {
              source: "generation-completions",
            });
          }
          if (newArtifacts.length > 0) {
            setArtifactPaths((prev) => Array.from(new Set([...prev, ...newArtifacts])));
          }
        }

        if (receivedItems) {
          recentActivityUntilRef.current = Date.now() + 2 * 60_000;
        }
      } catch {
        // Swallow polling errors for transient backend downtime.
      }

      if (active) {
        const visible = isDocumentVisible;
        const hasRecentActivityNow = recentActivityUntilRef.current > Date.now();
        const msSinceJobsCheck = Date.now() - lastJobsCheckAtRef.current;
        const msUntilJobsRecheck = Math.max(1_000, 60_000 - msSinceJobsCheck);
        let delay = 45_000;
        if (!visible) {
          delay = 60_000;
        } else if (hasActiveJobsRef.current || receivedItems) {
          delay = 3_000;
        } else if (hasRecentActivityNow) {
          delay = 10_000;
        } else {
          delay = Math.min(45_000, msUntilJobsRecheck);
        }
        timer = window.setTimeout(() => {
          void schedule();
        }, delay);
      }
    };

    void schedule();

    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [isDocumentVisible, refreshSignal, threadId]);

  return useMemo(
    () => ({
      notices,
      artifactPaths,
    }),
    [artifactPaths, notices],
  );
}
