"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/dreamy/api";
import { REFRESH_INTERVAL_LRT } from "@/core/dreamy/constants";
import type { LongRunningTask, LongRunningTaskStatus } from "@/core/long-running/types";

import type { WorkflowJson } from "../types";

import { useCheckpoint } from "./use-checkpoint";

type WorkflowFetchResult = {
  workflow: WorkflowJson | null;
  notFound: boolean;
};

async function fetchWorkflowJsonRaw(threadId: string): Promise<WorkflowFetchResult> {
  const res = await fetch(`${getBackendBaseURL()}${api.threads.dreamy.workflow(threadId)}`);
  if (res.status === 404) return { workflow: null, notFound: true };
  if (!res.ok) return { workflow: null, notFound: false };
  return { workflow: (await res.json()) as WorkflowJson, notFound: false };
}

function phaseToStatus(phase: string): LongRunningTaskStatus | null {
  switch (phase) {
    case "poc":               return "running";
    case "awaiting_approval": return "pending_approval";
    case "bulk":              return "running";
    default:                  return null; // design / done → don't show
  }
}

function buildDetail(phase: string, completedRows: number, totalRows: number): string {
  const pct = totalRows > 0 ? ((completedRows / totalRows) * 100).toFixed(1) : "0";
  switch (phase) {
    case "poc":               return `POC: ${completedRows} / ${Math.min(3, totalRows)} rows`;
    case "awaiting_approval": return "POC done · awaiting approval";
    case "bulk":              return `${completedRows} / ${totalRows} rows · ${pct}%`;
    default:                  return "";
  }
}

export function useDreamyAsLongRunningTask(
  threadId: string,
  enabledOverride = true,
): LongRunningTask | null {
  const [notFoundStreak, setNotFoundStreak] = useState(0);
  const enabled =
    enabledOverride && Boolean(threadId && threadId !== "new") && notFoundStreak < 3;

  const { data } = useQuery<WorkflowFetchResult>({
    queryKey: ["dreamy-workflow-lrt", threadId],
    queryFn: () => fetchWorkflowJsonRaw(threadId),
    enabled,
    refetchInterval: REFRESH_INTERVAL_LRT,
    staleTime: 0,
    retry: false,
  });
  const workflow = data?.workflow ?? null;

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

  const { data: checkpoint } = useCheckpoint(threadId, enabled);

  return useMemo(() => {
    if (!workflow) return null;

    const es = workflow.execution_state;
    const status = phaseToStatus(es.phase);
    if (!status) return null;

    const completedRows = checkpoint ? checkpoint.completed.length : es.current_row_index;
    const totalRows = es.total_rows;
    const filename = workflow.data_source?.filename ?? "workflow";

    return {
      id: `dreamy-${threadId}`,
      source: "dreamy",
      kind: "dreamy-workflow",
      title: `Workflow: ${filename}`,
      status,
      detail: buildDetail(es.phase, completedRows, totalRows),
      updatedAt: checkpoint?.updated_at ?? undefined,
    } satisfies LongRunningTask;
  }, [workflow, checkpoint, threadId]);
}
