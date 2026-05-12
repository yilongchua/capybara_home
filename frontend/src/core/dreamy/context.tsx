"use client";

import { createContext, useCallback, useContext, useState } from "react";

import type { WorkflowJson, WorkflowStep } from "./types";

interface DreamyContextType {
  workflowJson: WorkflowJson | null;
  setWorkflowJson: (wf: WorkflowJson | null) => void;
  editingStepId: string | null;
  setEditingStepId: (id: string | null) => void;
  patchStep: (stepId: string, patch: Partial<WorkflowStep>) => void;
  addStep: (action: WorkflowStep["action"], data: Partial<WorkflowStep>) => void;
  isPinned: boolean;
  setIsPinned: (v: boolean) => void;
  isPaneCollapsed: boolean;
  setIsPaneCollapsed: (v: boolean) => void;
}

const DreamyContext = createContext<DreamyContextType | null>(null);

export function DreamyProvider({ children }: { children: React.ReactNode }) {
  const [workflowJson, setWorkflowJson] = useState<WorkflowJson | null>(null);
  const [editingStepId, setEditingStepId] = useState<string | null>(null);
  const [isPinned, setIsPinned] = useState(false);
  const [isPaneCollapsed, setIsPaneCollapsed] = useState(false);

  const patchStep = useCallback((stepId: string, patch: Partial<WorkflowStep>) => {
    setWorkflowJson((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        steps: prev.steps.map((s) =>
          s.id === stepId ? { ...s, ...patch } : s,
        ),
      };
    });
  }, []);

  const addStep = useCallback(
    (action: WorkflowStep["action"], data: Partial<WorkflowStep>) => {
      setWorkflowJson((prev) => {
        if (!prev) return prev;
        const newStep: WorkflowStep = {
          id: `user-step-${Date.now()}`,
          action,
          description: data.description ?? "",
          tool: data.tool,
          input_fields: data.input_fields ?? [],
          output_fields: data.output_fields ?? [],
          condition: data.condition,
          on_no_result: data.on_no_result,
        };
        return { ...prev, steps: [...prev.steps, newStep] };
      });
    },
    [],
  );

  return (
    <DreamyContext.Provider
      value={{
        workflowJson,
        setWorkflowJson,
        editingStepId,
        setEditingStepId,
        patchStep,
        addStep,
        isPinned,
        setIsPinned,
        isPaneCollapsed,
        setIsPaneCollapsed,
      }}
    >
      {children}
    </DreamyContext.Provider>
  );
}

export function useDreamy() {
  const ctx = useContext(DreamyContext);
  if (!ctx) throw new Error("useDreamy must be used inside DreamyProvider");
  return ctx;
}
