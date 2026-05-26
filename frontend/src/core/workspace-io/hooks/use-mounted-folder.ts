"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/workspace-io/api";
import {
  MOUNTED_FOLDER_REFRESH_EMPTY,
  MOUNTED_FOLDER_REFRESH_HAS_DATA,
  MOUNTED_FOLDER_STALE_TIME,
} from "@/core/workspace-io/constants";

async function fetchMountedFolder(threadId: string): Promise<string | null> {
  const res = await fetch(`${getBackendBaseURL()}${api.threads.workspaceIO.mountFolder(threadId)}`);
  if (!res.ok) {
    throw new Error("failed to load mounted folder");
  }
  const data = (await res.json()) as { path?: string | null };
  return data.path ?? null;
}

async function saveMountedFolder(threadId: string, path: string): Promise<string> {
  const res = await fetch(`${getBackendBaseURL()}${api.threads.workspaceIO.mountFolder(threadId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    const message = await res.text();
    throw new Error(message || "failed to mount folder");
  }
  const data = (await res.json()) as { path: string };
  return data.path;
}

async function clearMountedFolder(threadId: string): Promise<null> {
  const res = await fetch(`${getBackendBaseURL()}${api.threads.workspaceIO.mountFolder(threadId)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const message = await res.text();
    throw new Error(message || "failed to unmount folder");
  }
  return null;
}

export function useMountedFolder(threadId: string) {
  return useQuery<string | null>({
    queryKey: ["dreamy-mounted-folder", threadId],
    queryFn: () => fetchMountedFolder(threadId),
    enabled: Boolean(threadId && threadId !== "new"),
    staleTime: MOUNTED_FOLDER_STALE_TIME,
    refetchInterval: (query) => (query.state.data ? MOUNTED_FOLDER_REFRESH_HAS_DATA : MOUNTED_FOLDER_REFRESH_EMPTY),
    refetchIntervalInBackground: false,
  });
}

export function useSaveMountedFolder(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (path: string) => saveMountedFolder(threadId, path),
    onSuccess: (path) => {
      queryClient.setQueryData(["dreamy-mounted-folder", threadId], path);
    },
  });
}

export function useClearMountedFolder(threadId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => clearMountedFolder(threadId),
    onSuccess: () => {
      queryClient.setQueryData(["dreamy-mounted-folder", threadId], null);
      queryClient.setQueryData(["dreamy-mounted-folder-files", threadId], {
        files: [],
        folder_path: null,
      });
    },
  });
}
