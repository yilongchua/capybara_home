import type { Message } from "@langchain/langgraph-sdk";
import type { QueryClient } from "@tanstack/react-query";

export const threadMessagesQueryKey = (threadId: string) =>
  ["threads", threadId, "messages"] as const;

export type CachedThreadMessages = {
  messages: Message[];
  cachedAt: number;
};

export function setCachedThreadMessages(
  queryClient: QueryClient,
  threadId: string,
  messages: Message[],
) {
  if (!threadId || messages.length === 0) {
    return;
  }
  queryClient.setQueryData<CachedThreadMessages>(threadMessagesQueryKey(threadId), {
    messages,
    cachedAt: Date.now(),
  });
}

export function getCachedThreadMessages(
  queryClient: QueryClient,
  threadId: string,
): CachedThreadMessages | undefined {
  return queryClient.getQueryData<CachedThreadMessages>(
    threadMessagesQueryKey(threadId),
  );
}

export function invalidateCachedThreadMessages(
  queryClient: QueryClient,
  threadId: string,
) {
  queryClient.removeQueries({ queryKey: threadMessagesQueryKey(threadId) });
}
