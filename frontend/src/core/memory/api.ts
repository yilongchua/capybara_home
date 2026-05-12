import { getBackendBaseURL } from "../config";

import type {
  BehaviorRuleCreate,
  BehaviorRuleUpdate,
  MemoryFactUpdate,
  UserMemory,
} from "./types";

type MemoryScope = "global" | "workspace";

function scopeQuery(scope: MemoryScope, workspaceId?: string | null) {
  const params = new URLSearchParams({ scope });
  if (workspaceId) {
    params.set("workspace_id", workspaceId);
  }
  return params.toString();
}

async function assertOk(response: Response) {
  if (response.ok) return;
  const text = await response.text();
  throw new Error(text || "Memory request failed");
}

export async function loadMemory(scope: MemoryScope = "global", workspaceId?: string | null) {
  const memory = await fetch(`${getBackendBaseURL()}/api/memory?${scopeQuery(scope, workspaceId)}`);
  await assertOk(memory);
  const json = await memory.json();
  return json as UserMemory;
}

export async function updateMemoryFact(
  factId: string,
  payload: MemoryFactUpdate,
  scope: MemoryScope = "global",
  workspaceId?: string | null,
) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/memory/facts/${encodeURIComponent(factId)}?${scopeQuery(scope, workspaceId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  await assertOk(response);
  return response.json();
}

export async function deleteMemoryFact(
  factId: string,
  scope: MemoryScope = "global",
  workspaceId?: string | null,
) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/memory/facts/${encodeURIComponent(factId)}?${scopeQuery(scope, workspaceId)}`,
    { method: "DELETE" },
  );
  await assertOk(response);
  return response.json();
}

export async function createBehaviorRule(
  payload: BehaviorRuleCreate,
  scope: MemoryScope = "global",
  workspaceId?: string | null,
) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/memory/rules?${scopeQuery(scope, workspaceId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  await assertOk(response);
  return response.json();
}

export async function patchBehaviorRule(
  ruleId: string,
  payload: BehaviorRuleUpdate,
  scope: MemoryScope = "global",
  workspaceId?: string | null,
) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/memory/rules/${encodeURIComponent(ruleId)}?${scopeQuery(scope, workspaceId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  await assertOk(response);
  return response.json();
}

export async function deleteBehaviorRule(
  ruleId: string,
  scope: MemoryScope = "global",
  workspaceId?: string | null,
) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/memory/rules/${encodeURIComponent(ruleId)}?${scopeQuery(scope, workspaceId)}`,
    { method: "DELETE" },
  );
  await assertOk(response);
  return response.json();
}

export async function forgetThreadMemory(workspaceId: string, threadId: string) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/memory/forget-thread?${scopeQuery("workspace", workspaceId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: threadId }),
    },
  );
  await assertOk(response);
  return response.json();
}

export async function loadCompactions(workspaceId: string, limit = 100) {
  const response = await fetch(
    `${getBackendBaseURL()}/api/memory/compactions?workspace_id=${encodeURIComponent(workspaceId)}&limit=${limit}`,
  );
  await assertOk(response);
  const json = await response.json();
  return (json?.items ?? []) as Array<Record<string, unknown>>;
}
