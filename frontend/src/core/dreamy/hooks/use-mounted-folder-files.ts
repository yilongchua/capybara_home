"use client";

import { useQuery } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/dreamy/api";
import {
  MOUNTED_FOLDER_REFRESH_EMPTY,
  MOUNTED_FOLDER_REFRESH_HAS_DATA,
  MOUNTED_FOLDER_STALE_TIME,
} from "@/core/dreamy/constants";

export interface MountedFolderFile {
  name: string;
  size: number;
  virtual_path: string;
  full_path: string;
  is_dir?: boolean;
}

export interface MountedFolderFilesResult {
  files: MountedFolderFile[];
  folder_path: string | null;
}

async function fetchMountedFolderFiles(threadId: string): Promise<MountedFolderFilesResult> {
  const res = await fetch(`${getBackendBaseURL()}${api.threads.dreamy.mountFolderFiles(threadId)}`);
  if (!res.ok) throw new Error("Failed to list mounted folder files");
  return res.json() as Promise<MountedFolderFilesResult>;
}

export function useMountedFolderFiles(threadId: string, enabled: boolean) {
  return useQuery<MountedFolderFilesResult>({
    queryKey: ["dreamy-mounted-folder-files", threadId],
    queryFn: () => fetchMountedFolderFiles(threadId),
    enabled: enabled && Boolean(threadId && threadId !== "new"),
    staleTime: MOUNTED_FOLDER_STALE_TIME,
    refetchInterval: (query) => (query.state.data?.files?.length ? MOUNTED_FOLDER_REFRESH_HAS_DATA : MOUNTED_FOLDER_REFRESH_EMPTY),
    refetchIntervalInBackground: false,
  });
}
