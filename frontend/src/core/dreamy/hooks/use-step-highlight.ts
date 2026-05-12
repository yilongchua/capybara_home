"use client";

import { useDreamy } from "../context";

export function useStepHighlight(): string | null {
  const { workflowJson } = useDreamy();
  return workflowJson?.execution_state.current_step_id ?? null;
}
