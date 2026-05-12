"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { getBackendBaseURL } from "@/core/config";
import type { LongRunningTask, LongRunningTaskStatus } from "@/core/long-running/types";

import { api } from "@/core/dreamy/api";
import { REFRESH_INTERVAL_LRT } from "@/core/dreamy/constants";

import type { WorkflowJson } from "../types";

import { useCheckpoint } from "./use-checkpoint";

async function fetchWorkflowJsonRaw(threadId: string): Promise<WorkflowJson | null> {
  const res = await fetch(`${getBackendBaseURL()}${api.threads.dreamy.workflow(threadId)}`);
  if (res.status === 404) return null;
  if (!res.ok) return null;
  return res.json() as Promise<WorkflowJson>;
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
  const enabled = enabledOverride && Boolean(threadId && threadId !== "new");

  const { data: workflow } = useQuery<WorkflowJson | null>({
    queryKey: ["dreamy-workflow-lrt", threadId],
    queryFn: () => fetchWorkflowJsonRaw(threadId),
    enabled,
    refetchInterval: REFRESH_INTERVAL_LRT,
    staleTime: 0,
    retry: false,
  });

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
