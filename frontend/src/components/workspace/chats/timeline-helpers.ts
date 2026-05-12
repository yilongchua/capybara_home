import type { ToolCall } from "@langchain/core/messages";
import type { Message } from "@langchain/langgraph-sdk";

import type { Subtask } from "@/core/tasks";
import {
  lastToolCall,
  readToolQuery,
  resolveToolIconKey,
  toolActionLabel,
  type ToolIconKey,
} from "@/core/tools/presentation";

export const TIMELINE_MAX_ITEMS = 500;
export const MESSAGE_PREVIEW_LIMIT = 140;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TimelineItemKind =
  | "user"
  | "assistant"
  | "task_started"
  | "task_completed"
  | "task_failed";

export type TimelineIcon = "user" | "assistant" | "done" | "failed" | ToolIconKey;

export type TimelineItem = {
  id: string;
  timestamp: number;
  order: number;
  kind: TimelineItemKind;
  icon: TimelineIcon;
  title: string;
  detail?: string;
  groupId?: string;
  startTimestamp?: number;
  durationMs?: number;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function runStatusTone(state: "run" | "idle") {
  if (state === "run") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-600";
}

export function formatTime(ts?: number) {
  if (!ts || !Number.isFinite(ts)) return "--:--:--";
  return new Date(ts * 1000).toLocaleTimeString();
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function extractMessageText(message: Message): string {
  const content = message.content;
  if (typeof content === "string") return content.trim();
  if (Array.isArray(content)) {
    const parts: string[] = [];
    for (const block of content) {
      if (typeof block === "string") parts.push(block);
      else if (typeof block === "object" && block !== null && "text" in block && typeof block.text === "string") {
        parts.push(block.text);
      }
    }
    return parts.join(" ").trim();
  }
  return "";
}

export function getMessageTimestamp(message: Message, fallback: number): number {
  const created = (message as Record<string, unknown>).created_at;
  if (typeof created === "string") {
    const parsed = Date.parse(created);
    if (Number.isFinite(parsed)) return parsed / 1000;
  }
  return fallback;
}

export function preview(text: string, limit = MESSAGE_PREVIEW_LIMIT) {
  if (text.length <= limit) return text;
  return text.slice(0, limit).trimEnd() + "…";
}

export function toolDetail(toolCall: ToolCall): string | undefined {
  const query = readToolQuery(toolCall.args);
  if (query) return `query: ${query}`;
  if (typeof toolCall.args === "object" && toolCall.args !== null && !Array.isArray(toolCall.args)) {
    const args = toolCall.args as Record<string, unknown>;
    if (typeof args.description === "string" && args.description.trim()) return args.description.trim();
  }
  return undefined;
}

export function looksLikeFailure(text: string, toolName?: string): boolean {
  const normalized = text.toLowerCase();
  if (normalized.includes('"ok":false') || normalized.includes('"ok": false')) return true;
  if (normalized.startsWith("error:")) return true;
  if (normalized.startsWith("failed:")) return true;
  if (normalized.includes("traceback (most recent")) return true;
  if (toolName === "bash" && normalized.includes("exit code 1")) return true;
  return false;
}

export function deriveSubtaskDescriptor(
  task: Subtask,
  iconByTool: Record<string, string>,
): { action: string; detail?: string; icon: ToolIconKey } {
  const toolCall = lastToolCall(task.latestMessage);
  if (toolCall) {
    return {
      action: toolActionLabel(toolCall.name),
      detail: toolDetail(toolCall) ?? task.prompt?.trim(),
      icon: resolveToolIconKey(toolCall.name, iconByTool),
    };
  }
  const description = task.description?.trim();
  const action =
    description && description.toLowerCase() !== "running subtask"
      ? description
      : task.subagent_type
        ? toolActionLabel(task.subagent_type)
        : "subtask";
  return { action, detail: task.prompt?.trim(), icon: resolveToolIconKey(task.subagent_type, iconByTool) };
}

export function kindToSpineColor(kind: TimelineItemKind): string {
  if (kind === "task_completed") return "bg-emerald-400";
  if (kind === "task_failed") return "bg-red-400";
  if (kind === "task_started") return "bg-amber-400";
  return "bg-slate-200";
}
