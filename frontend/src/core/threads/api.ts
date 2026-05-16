import { clearThreadClientCache } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";

export type DeleteThreadResponse = {
  thread_id: string;
  deleted: boolean;
  files_deleted: boolean;
};

export type DeleteAllThreadsResponse = {
  deleted_count: number;
  files_deleted_count: number;
  failed_thread_ids: string[];
};

export async function deleteThread(threadId: string): Promise<DeleteThreadResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    const err = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to delete thread: ${response.statusText}`);
  }
  clearThreadClientCache(threadId);
  return response.json() as Promise<DeleteThreadResponse>;
}

export async function deleteAllThreads(): Promise<DeleteAllThreadsResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/threads`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const err = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to delete all chats: ${response.statusText}`);
  }
  return response.json() as Promise<DeleteAllThreadsResponse>;
}
