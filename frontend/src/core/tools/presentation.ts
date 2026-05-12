import type { ToolCall } from "@langchain/core/messages";
import type { AIMessage } from "@langchain/langgraph-sdk";

export const TOOL_ICON_OPTIONS = [
  "tool",
  "web",
  "vault",
  "assistant",
  "terminal",
] as const;

export type ToolIconKey = (typeof TOOL_ICON_OPTIONS)[number];

export const DEFAULT_TOOL_ICON_BY_TOOL: Record<string, ToolIconKey> = {
  web_search: "web",
  image_search: "web",
  web_fetch: "web",
  query_knowledge_vault: "vault",
  knowledge_vault_query: "vault",
  read_knowledge_vault: "vault",
  run_command: "terminal",
  exec_command: "terminal",
  shell: "terminal",
  task: "assistant",
};

export function normalizeToolName(name: string | undefined | null): string {
  if (!name) return "";
  return name.trim().toLowerCase();
}

export function resolveToolIconKey(
  toolName: string | undefined,
  iconByToolSetting?: Record<string, string>,
): ToolIconKey {
  const normalized = normalizeToolName(toolName);
  const configured = normalized ? iconByToolSetting?.[normalized] : undefined;
  if (configured && TOOL_ICON_OPTIONS.includes(configured as ToolIconKey)) {
    return configured as ToolIconKey;
  }
  if (normalized && DEFAULT_TOOL_ICON_BY_TOOL[normalized]) {
    return DEFAULT_TOOL_ICON_BY_TOOL[normalized];
  }
  if (normalized.includes("web") || normalized.includes("search")) {
    return "web";
  }
  if (normalized.includes("vault") || normalized.includes("knowledge")) {
    return "vault";
  }
  if (normalized.includes("shell") || normalized.includes("command")) {
    return "terminal";
  }
  return "tool";
}

export function readToolQuery(args: unknown): string | undefined {
  if (typeof args !== "object" || args === null || Array.isArray(args)) {
    return undefined;
  }
  const record = args as Record<string, unknown>;
  if (typeof record.query === "string" && record.query.trim()) {
    return record.query.trim();
  }
  if (typeof record.q === "string" && record.q.trim()) {
    return record.q.trim();
  }
  if (Array.isArray(record.queries)) {
    const parts = record.queries.filter(
      (item): item is string => typeof item === "string",
    );
    if (parts.length > 0) {
      return parts.join(" | ");
    }
  }
  return undefined;
}

export function toolActionLabel(toolName: string | undefined) {
  const normalized = normalizeToolName(toolName);
  if (!normalized) {
    return "Tool";
  }
  return normalized.replaceAll("_", " ").trim();
}

export function lastToolCall(message: AIMessage | undefined): ToolCall | undefined {
  if (!Array.isArray(message?.tool_calls) || message.tool_calls.length === 0) {
    return undefined;
  }
  return message.tool_calls[message.tool_calls.length - 1];
}
