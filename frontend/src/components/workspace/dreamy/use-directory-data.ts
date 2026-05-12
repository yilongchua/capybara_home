"use client";

import { useCallback, useMemo } from "react";

import { useThread } from "@/components/workspace/messages/context";
import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/dreamy/api";
import { useDreamy } from "@/core/dreamy/context";
import { useMountedFolder } from "@/core/dreamy/hooks/use-mounted-folder";
import { useMountedFolderFiles } from "@/core/dreamy/hooks/use-mounted-folder-files";
import type { SelectedFile } from "@/core/dreamy/types";
import { useUploadedFiles } from "@/core/uploads/hooks";

export interface MergedFile {
  filename: string;
  size: number;
  artifact_url?: string;
  markdown_artifact_url?: string;
}

export function useDirectoryData(
  threadId: string,
  onSelectFile: (file: SelectedFile) => void,
) {
  const { workflowJson } = useDreamy();
  const { thread } = useThread();
  const { data: uploadsData } = useUploadedFiles(threadId);
  const { data: mountedFolder } = useMountedFolder(threadId);
  const hasMountedFolder = Boolean(mountedFolder);
  const { data: mountedFolderFiles } = useMountedFolderFiles(threadId, hasMountedFolder);

  const uploadedFilesFromFS = useMemo(() => uploadsData?.files ?? [], [uploadsData?.files]);
  const rawStateFiles = thread.values.uploaded_files;
  const uploadedFilesFromState = useMemo(
    () =>
      (rawStateFiles ?? []) as Array<{
        filename: string;
        size: number;
        path: string;
        extension?: string;
      }>,
    [rawStateFiles],
  );

  const allUploadedFiles: MergedFile[] = useMemo(
    () => {
      const stateOnlyFiles = uploadedFilesFromState.filter(
        (sf) => !uploadedFilesFromFS.some((f) => f.filename.toLowerCase() === sf.filename.toLowerCase()),
      );
      return [
        ...uploadedFilesFromFS.map((f) => ({
          filename: f.filename,
          size: Number(f.size) || 0,
          artifact_url: f.artifact_url,
          markdown_artifact_url: f.markdown_artifact_url,
        })),
        ...stateOnlyFiles.map((sf) => ({
          filename: sf.filename,
          size: sf.size,
        })),
      ];
    },
    [uploadedFilesFromFS, uploadedFilesFromState],
  );

  const dataSourceType = workflowJson?.data_source?.type ?? workflowJson?.task_source?.type ?? null;
  const dataSourceFilename =
    dataSourceType === "file" || dataSourceType === "mounted_file" ||
    dataSourceType === "inline" || dataSourceType === "inferred"
      ? (workflowJson?.data_source?.filename ?? workflowJson?.task_source?.filename ?? null)
      : null;

  const dataSourceFile = dataSourceFilename
    ? allUploadedFiles.find((f) => f.filename === dataSourceFilename)
    : null;

  const otherUploads = allUploadedFiles.filter((f) => f.filename !== dataSourceFilename);

  const artifactPaths = thread.values.artifacts ?? [];
  const createdFileEntries: { filename: string; fullPath: string }[] = Array.from(
    new Map(
      artifactPaths
        .map((p) => ({ filename: p.split("/").pop() ?? "", fullPath: p }))
        .filter(({ filename }) => filename && !allUploadedFiles.some((u) => u.filename === filename))
        .map((e) => [e.filename, e]),
    ).values(),
  );

  const hasFiles = Boolean(dataSourceFilename) || otherUploads.length > 0 || createdFileEntries.length > 0;
  const hasMountedFiles = (mountedFolderFiles?.files?.length ?? 0) > 0;
  const hasAnything = hasFiles || hasMountedFolder;

  const selectUploadedFile = useCallback(
    (filename: string) => {
      const file = allUploadedFiles.find((f) => f.filename === filename);
      if (!file) {
        onSelectFile({ filename, artifactUrl: api.threads.uploads(threadId, filename) });
        return;
      }
      onSelectFile({
        filename: file.filename,
        artifactUrl: file.artifact_url ?? api.threads.uploads(threadId, filename),
        markdownArtifactUrl: file.markdown_artifact_url,
      });
    },
    [allUploadedFiles, threadId, onSelectFile],
  );

  const selectCreatedFile = useCallback(
    (filename: string, fullPath: string) => {
      onSelectFile({
        filename,
        artifactUrl: `${getBackendBaseURL()}${api.threads.artifacts(threadId, fullPath)}`,
        fullPath,
        isLiveOutput: filename.includes("_results"),
      });
    },
    [threadId, onSelectFile],
  );

  const selectMountedFile = useCallback(
    (name: string, virtualPath: string, fullPath: string) => {
      onSelectFile({
        filename: name,
        artifactUrl: `${getBackendBaseURL()}${api.threads.artifacts(threadId, virtualPath)}`,
        fullPath,
      });
    },
    [threadId, onSelectFile],
  );

  return {
    allUploadedFiles,
    dataSourceFilename,
    dataSourceFile,
    otherUploads,
    createdFileEntries,
    hasFiles,
    hasMountedFolder,
    hasMountedFiles,
    hasAnything,
    mountedFolder,
    mountedFolderFiles,
    selectUploadedFile,
    selectCreatedFile,
    selectMountedFile,
  };
}
