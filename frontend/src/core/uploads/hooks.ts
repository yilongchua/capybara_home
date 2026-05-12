/**
 * React hooks for file uploads
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import {
  publishWorkspaceRefresh,
  useWorkspaceRefreshQuery,
} from "../workspace-refresh";

import {
  deleteUploadedFile,
  listUploadedFiles,
  uploadFiles,
  type UploadedFileInfo,
  type UploadResponse,
} from "./api";

/**
 * Hook to upload files
 */
export function useUploadFiles(threadId: string) {
  const queryClient = useQueryClient();

  return useMutation<UploadResponse, Error, File[]>({
    mutationFn: (files: File[]) => uploadFiles(threadId, files),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["uploads", "list", threadId],
      });
      publishWorkspaceRefresh([`uploads:${threadId}`, `thread:${threadId}`], {
        source: "uploads",
      });
    },
  });
}

/**
 * Hook to list uploaded files
 */
export function useUploadedFiles(threadId: string) {
  return useWorkspaceRefreshQuery({
    queryKey: ["uploads", "list", threadId],
    queryFn: () => listUploadedFiles(threadId),
    enabled: !!threadId,
    refreshDomains: threadId ? [`uploads:${threadId}`] : [],
  });
}

/**
 * Hook to delete an uploaded file
 */
export function useDeleteUploadedFile(threadId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (filename: string) => deleteUploadedFile(threadId, filename),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["uploads", "list", threadId],
      });
      publishWorkspaceRefresh([`uploads:${threadId}`, `thread:${threadId}`], {
        source: "uploads",
      });
    },
  });
}

/**
 * Hook to handle file uploads in submit flow
 * Returns a function that uploads files and returns their info
 */
export function useUploadFilesOnSubmit(threadId: string) {
  const uploadMutation = useUploadFiles(threadId);

  return useCallback(
    async (files: File[]): Promise<UploadedFileInfo[]> => {
      if (files.length === 0) {
        return [];
      }

      const result = await uploadMutation.mutateAsync(files);
      return result.files;
    },
    [uploadMutation],
  );
}
