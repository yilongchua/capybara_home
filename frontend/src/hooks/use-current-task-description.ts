import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { useMemo } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { Subtask } from "@/core/tasks";
import type { AgentThreadState } from "@/core/threads";
import { explainLastToolCall } from "@/core/tools/utils";

const GENERIC_SUBTASK_DESCRIPTIONS = new Set([
  "running subtask",
  "subtask",
  "running task",
  "task",
]);

function normalizeInline(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function truncate(text: string, max = 140): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
}

function formatInProgressSubtask(task: Subtask): string | undefined {
  const rawDescription = normalizeInline(task.description ?? "");
  const prompt = normalizeInline(task.prompt ?? "");
  const isGeneric =
    rawDescription.length === 0 ||
    GENERIC_SUBTASK_DESCRIPTIONS.has(rawDescription.toLowerCase());

  const detail = isGeneric ? prompt : rawDescription;
  if (!detail) {
    return undefined;
  }

  return `subtask - ${truncate(detail)}`;
}

export function useCurrentTaskDescription(
  messages: BaseStream<AgentThreadState>["messages"],
  subtasksById: Record<string, Subtask>,
) {
  const { t } = useI18n();

  return useMemo(() => {
    if (!messages || messages.length === 0) {
      return undefined;
    }

    const inProgressTasks = Object.values(subtasksById)
      .filter((task) => task.status === "in_progress")
      .sort((a, b) => {
        const aTs = a.updated_at ?? a.started_at ?? 0;
        const bTs = b.updated_at ?? b.started_at ?? 0;
        return bTs - aTs;
      });

    if (inProgressTasks.length > 0) {
      for (const task of inProgressTasks) {
        const formatted = formatInProgressSubtask(task);
        if (formatted) {
          return formatted;
        }
      }
    }

    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg && msg.type === "ai" && Array.isArray(msg.tool_calls) && msg.tool_calls.length > 0) {
        return explainLastToolCall(msg, t);
      }
    }

    return undefined;
  }, [messages, subtasksById, t]);
}
