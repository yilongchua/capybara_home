"use client";

import { FolderOpenIcon, UploadIcon } from "lucide-react";

import { ScrollArea } from "@/components/ui/scroll-area";
import type { SelectedFile } from "@/core/dreamy/types";
import { useI18n } from "@/core/i18n/hooks";

import { FileRow, formatBytes } from "./directory-file-row";
import { useDirectoryData } from "./use-directory-data";

interface DreamyDirectoryTabProps {
  threadId: string;
  selectedFilename?: string | null;
  onSelectFile: (file: SelectedFile) => void;
}

export function DreamyDirectoryTab({ threadId, selectedFilename, onSelectFile }: DreamyDirectoryTabProps) {
  const { t } = useI18n();
  const {
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
  } = useDirectoryData(threadId, onSelectFile);

  if (!hasAnything) {
    return (
      <div className="flex size-full flex-col items-center justify-center gap-2 px-6 py-10 text-center text-muted-foreground">
        <FolderOpenIcon className="size-8 opacity-40" />
        <p className="text-sm">{t.dreamy.directory.noFilesYet}</p>
        <p className="text-xs opacity-70">{t.dreamy.directory.noFilesDescription}</p>
      </div>
    );
  }

  return (
    <ScrollArea className="size-full">
      <div className="flex flex-col gap-3 px-3 py-3">

        {/* Mounted Folder */}
        {hasMountedFolder && (
          <section>
            <div className="mb-1 flex items-center gap-1.5 px-2">
              <FolderOpenIcon className="size-3 text-muted-foreground" />
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                {t.dreamy.directory.mountedFolder}
              </span>
            </div>
            <div className="mb-1 rounded-md border bg-muted/30 px-2 py-1.5 text-xs font-mono text-muted-foreground">
              {mountedFolder}
            </div>
            {hasMountedFiles ? (
              <div className="flex flex-col gap-0.5">
                {mountedFolderFiles!.files.map((f) => (
                  <FileRow
                    key={f.name}
                    name={f.name}
                    size={formatBytes(f.size)}
                    badge="mounted"
                    isSelected={selectedFilename === f.name}
                    onClick={() => selectMountedFile(f.name, f.virtual_path, f.full_path)}
                  />
                ))}
              </div>
            ) : (
              <p className="px-2 text-xs text-muted-foreground opacity-60">{t.dreamy.directory.noFilesInFolder}</p>
            )}
          </section>
        )}

        {/* Files (uploaded + created merged) */}
        {hasFiles && (
          <section>
            <div className="mb-1 flex items-center gap-1.5 px-2">
              <UploadIcon className="size-3 text-muted-foreground" />
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                {t.dreamy.directory.filesSection}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              {/* Data source (input) */}
              {dataSourceFilename && (
                dataSourceFile ? (
                  <FileRow
                    name={dataSourceFile.filename}
                    size={formatBytes(dataSourceFile.size)}
                    badge="input"
                    isSelected={selectedFilename === dataSourceFile.filename}
                    onClick={() => selectUploadedFile(dataSourceFile.filename)}
                  />
                ) : (
                  <FileRow
                    name={dataSourceFilename}
                    badge="input"
                    isSelected={selectedFilename === dataSourceFilename}
                    onClick={() => selectUploadedFile(dataSourceFilename)}
                  />
                )
              )}
              {/* Other uploads */}
              {otherUploads.map((f) => (
                <FileRow
                  key={f.filename}
                  name={f.filename}
                  size={formatBytes(f.size)}
                  badge="uploaded"
                  isSelected={selectedFilename === f.filename}
                  onClick={() => selectUploadedFile(f.filename)}
                />
              ))}
              {/* Created files */}
              {createdFileEntries.map(({ filename, fullPath }) => (
                <FileRow
                  key={filename}
                  name={filename}
                  badge="created"
                  isSelected={selectedFilename === filename}
                  onClick={() => selectCreatedFile(filename, fullPath)}
                />
              ))}
            </div>
          </section>
        )}

      </div>
    </ScrollArea>
  );
}
