import type { Subtask } from "./types";

/** Prefer live context updates over message-derived snapshots when newer. */
export function mergeSubtask(
  fromMessages: Subtask | undefined,
  fromContext: Subtask | undefined,
): Subtask | undefined {
  if (!fromMessages && !fromContext) {
    return undefined;
  }
  if (!fromMessages) {
    return fromContext;
  }
  if (!fromContext) {
    return fromMessages;
  }
  const contextUpdatedAt = fromContext.updated_at ?? 0;
  const messageUpdatedAt = fromMessages.updated_at ?? 0;
  const preferContext =
    contextUpdatedAt > messageUpdatedAt ||
    (fromContext.latestMessage != null && fromMessages.latestMessage == null) ||
    (fromContext.status === "in_progress" && fromMessages.status !== "in_progress");

  if (!preferContext) {
    return fromMessages;
  }
  return {
    ...fromMessages,
    ...fromContext,
    id: fromMessages.id,
    latestMessage: fromContext.latestMessage ?? fromMessages.latestMessage,
    status: fromContext.status ?? fromMessages.status,
    result: fromContext.result ?? fromMessages.result,
    error: fromContext.error ?? fromMessages.error,
  };
}
