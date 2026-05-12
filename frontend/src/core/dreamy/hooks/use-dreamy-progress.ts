"use client";

import { useMemo } from "react";

import type { DreamyPhase } from "@/core/dreamy/types";

import { useDreamy } from "../context";

import { useCheckpoint } from "./use-checkpoint";
import { EXECUTOR_ACTIVE_STATES, useProgress } from "./use-progress";

export interface DreamyProgress {
  completedRows: number;
  totalRows: number;
  pctDone: number;
  estimatedCompletion: Date | null;
  activeStepDescription: string;
  phase: DreamyPhase;
  secondsPerRow: number | null;
  failedRows: number;
  executorActive: boolean;
}

export function useDreamyProgress(threadId?: string): DreamyProgress {
  const { workflowJson } = useDreamy();
  const { data: checkpoint } = useCheckpoint(threadId ?? "", Boolean(threadId));
  const { data: progress } = useProgress(threadId ?? "", Boolean(threadId));

  return useMemo(() => {
    const empty: DreamyProgress = {
      completedRows: 0, totalRows: 0, pctDone: 0,
      estimatedCompletion: null, activeStepDescription: "—",
      phase: "design", secondsPerRow: null, failedRows: 0, executorActive: false,
    };
    if (!workflowJson) return empty;

    const { execution_state, steps } = workflowJson;
    const executorActive = Boolean(progress && EXECUTOR_ACTIVE_STATES.has(progress.state));

    // Prefer executor progress.json (compact, always current) for large runs;
    // fall back to checkpoint.json then workflow.json for small LLM-driven runs.
    const completed = executorActive
      ? progress!.done
      : (checkpoint ? checkpoint.completed.length : execution_state.current_row_index);

    const total = execution_state.total_rows;
    const pct = total > 0 ? (completed / total) * 100 : 0;
    const activeStep = steps.find((s) => s.id === execution_state.current_step_id);

    // Phase: executor state takes precedence for large runs
    const phase: DreamyPhase = executorActive ? progress!.state : execution_state.phase;

    // ETA: from executor if active, else from workflow.json
    const etaStr = executorActive ? progress!.eta_iso : execution_state.estimated_completion_iso;

    return {
      completedRows: completed,
      totalRows: total,
      pctDone: pct,
      estimatedCompletion: etaStr ? new Date(etaStr) : null,
      activeStepDescription: activeStep?.description ?? "—",
      phase,
      secondsPerRow: execution_state.seconds_per_row_estimate,
      failedRows: executorActive ? progress!.failed : 0,
      executorActive,
    };
  }, [workflowJson, checkpoint, progress]);
}
