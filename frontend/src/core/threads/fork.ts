import type { Checkpoint, Message } from "@langchain/langgraph-sdk";

export type BranchMessageMetadata = {
  firstSeenState?: {
    checkpoint?: Checkpoint | null;
  };
  branch?: string;
  branchOptions?: string[];
};

export type ForkDraft = {
  sourceMessageId: string;
  sourceMessageText: string;
  sourcePreview: string;
  sourceCreatedAt?: string;
  sourceBranch?: string;
  checkpoint: Omit<Checkpoint, "thread_id">;
};

export function extractMessageText(message: Message): string {
  if (typeof message.content === "string") {
    return message.content.trim();
  }
  if (!Array.isArray(message.content)) {
    return "";
  }
  const parts: string[] = [];
  for (const chunk of message.content) {
    if (typeof chunk === "object" && chunk !== null && "text" in chunk) {
      const textRaw = (chunk as { text?: unknown }).text;
      const text = typeof textRaw === "string" ? textRaw.trim() : "";
      if (text) parts.push(text);
    }
  }
  return parts.join(" ").trim();
}

export function previewText(text: string, limit = 140): string {
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, limit).trimEnd()}...`;
}

export function resolveForkDraft(
  message: Message,
  metadata: BranchMessageMetadata | undefined,
): ForkDraft | null {
  if (!message.id) {
    return null;
  }
  const checkpoint = metadata?.firstSeenState?.checkpoint;
  if (!checkpoint?.checkpoint_ns) {
    return null;
  }
  const checkpointWithoutThread = { ...checkpoint };
  delete (checkpointWithoutThread as { thread_id?: string }).thread_id;
  const text = extractMessageText(message);
  const createdAtRaw = (message as { created_at?: unknown }).created_at;
  const createdAt =
    typeof createdAtRaw === "string" && createdAtRaw.trim()
      ? createdAtRaw
      : undefined;

  return {
    sourceMessageId: message.id,
    sourceMessageText: text,
    sourcePreview: previewText(text || "(empty message)"),
    sourceCreatedAt: createdAt,
    sourceBranch: metadata?.branch,
    checkpoint: checkpointWithoutThread,
  };
}

export function resolveBranchCursor(
  branchOptions: string[] | undefined,
  currentBranch: string | undefined,
): { index: number; total: number } | null {
  if (!branchOptions || branchOptions.length <= 1) {
    return null;
  }
  const index = currentBranch ? branchOptions.indexOf(currentBranch) : -1;
  return {
    index: index >= 0 ? index : 0,
    total: branchOptions.length,
  };
}

export function resolveAdjacentBranch(
  branchOptions: string[] | undefined,
  currentBranch: string | undefined,
  direction: "prev" | "next",
): string | null {
  const cursor = resolveBranchCursor(branchOptions, currentBranch);
  if (!cursor || !branchOptions) {
    return null;
  }
  const nextIndex =
    direction === "next"
      ? (cursor.index + 1) % cursor.total
      : (cursor.index - 1 + cursor.total) % cursor.total;
  return branchOptions[nextIndex] ?? null;
}
