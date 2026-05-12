import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createBehaviorRule,
  deleteBehaviorRule,
  deleteMemoryFact,
  forgetThreadMemory,
  loadCompactions,
  loadMemory,
  patchBehaviorRule,
  updateMemoryFact,
} from "./api";
import type { BehaviorRuleCreate, BehaviorRuleUpdate, MemoryFactUpdate } from "./types";

export function useMemory(scope: "global" | "workspace" = "global", workspaceId?: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["memory", scope, workspaceId ?? null],
    queryFn: () => loadMemory(scope, workspaceId),
    enabled: scope === "global" || Boolean(workspaceId),
  });
  return { memory: data ?? null, isLoading, error };
}

export function useCompactions(workspaceId?: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["memory-compactions", workspaceId ?? null],
    queryFn: () => loadCompactions(String(workspaceId)),
    enabled: Boolean(workspaceId),
  });
  return { compactions: data ?? [], isLoading, error };
}

export function useMemoryMutations(scope: "global" | "workspace", workspaceId?: string | null) {
  const queryClient = useQueryClient();
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["memory", scope, workspaceId ?? null] });
  };

  const updateFact = useMutation({
    mutationFn: ({ factId, payload }: { factId: string; payload: MemoryFactUpdate }) =>
      updateMemoryFact(factId, payload, scope, workspaceId),
    onSuccess: invalidate,
  });
  const removeFact = useMutation({
    mutationFn: (factId: string) => deleteMemoryFact(factId, scope, workspaceId),
    onSuccess: invalidate,
  });
  const addRule = useMutation({
    mutationFn: (payload: BehaviorRuleCreate) => createBehaviorRule(payload, scope, workspaceId),
    onSuccess: invalidate,
  });
  const editRule = useMutation({
    mutationFn: ({ ruleId, payload }: { ruleId: string; payload: BehaviorRuleUpdate }) =>
      patchBehaviorRule(ruleId, payload, scope, workspaceId),
    onSuccess: invalidate,
  });
  const removeRule = useMutation({
    mutationFn: (ruleId: string) => deleteBehaviorRule(ruleId, scope, workspaceId),
    onSuccess: invalidate,
  });
  const forgetThread = useMutation({
    mutationFn: (threadId: string) => forgetThreadMemory(String(workspaceId), threadId),
    onSuccess: invalidate,
  });

  return { updateFact, removeFact, addRule, editRule, removeRule, forgetThread };
}
