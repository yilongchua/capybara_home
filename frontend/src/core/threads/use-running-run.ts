"use client";

// Detect whether the current thread has a run already in flight on the server.
//
// `useStream({ reconnectOnMount: true, streamResumable: true })` already does
// the heavy lifting — when the user reopens a chat with a live run, the SDK
// joins its SSE. This hook is a thin diagnostic + safety-net: it polls the
// server's `runs.list({ status: "running" })` when the page mounts and exposes
// the running run id (if any) so the chat UI can label the experience as
// "resuming" and so we have a fallback path if SDK reconnect ever silently
// no-ops (e.g., localStorage cleared, cross-device session).
//
// We deliberately avoid kicking off a second joinStream here — that risks
// double-consumption of the SSE. Treat this as observation only.

import { useEffect, useState } from "react";

import { getAPIClient } from "../api/api-client";

export interface RunningRunInfo {
  runId: string;
  createdAt: string | null;
}

export function useRunningRun(threadId: string | null | undefined): {
  runningRun: RunningRunInfo | null;
  loading: boolean;
} {
  const [runningRun, setRunningRun] = useState<RunningRunInfo | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(threadId));

  useEffect(() => {
    if (!threadId) {
      setRunningRun(null);
      setLoading(false);
      return;
    }
    const client = getAPIClient();
    let cancelled = false;
    const pollRunningRun = async (isInitial: boolean) => {
      if (isInitial) {
        setLoading(true);
      }
      try {
        const runs = await client.runs.list(threadId, { status: "running", limit: 1 });
        if (cancelled) return;
        const first = runs?.[0];
        if (first) {
          setRunningRun({
            runId: String(first.run_id),
            createdAt:
              typeof first.created_at === "string" ? first.created_at : null,
          });
        } else {
          setRunningRun(null);
        }
      } catch {
        if (cancelled) return;
        setRunningRun(null);
      } finally {
        if (isInitial && !cancelled) {
          setLoading(false);
        }
      }
    };

    void pollRunningRun(true);
    const interval = window.setInterval(() => {
      void pollRunningRun(false);
    }, 3000);
    const onFocus = () => {
      void pollRunningRun(false);
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void pollRunningRun(false);
      }
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [threadId]);

  return { runningRun, loading };
}
