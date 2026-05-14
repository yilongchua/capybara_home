"use client";

import { DownloadIcon, FileIcon, FileTextIcon } from "lucide-react";
import { useCallback } from "react";

import { useDirectory } from "@/components/workspace/artifacts/context";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { cn } from "@/lib/utils";

const EXT_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  md: FileTextIcon,
  txt: FileTextIcon,
};

function getIcon(filepath: string) {
  const ext = filepath.split(".").pop()?.toLowerCase() ?? "";
  const Icon = EXT_ICONS[ext] ?? FileIcon;
  return Icon;
}

function getBasename(filepath: string) {
  return filepath.split("/").pop() ?? filepath;
}

export function ArtifactLink({
  filepath,
  threadId,
  className,
}: {
  filepath: string;
  threadId: string;
  className?: string;
}) {
  const { select, setOpen } = useDirectory();

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      select(filepath);
      setOpen(true);
    },
    [filepath, select, setOpen],
  );

  const Icon = getIcon(filepath);
  const basename = getBasename(filepath);
  const downloadUrl = urlOfArtifact({ filepath, threadId, download: true });

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-sm transition-colors",
        "bg-muted/40 hover:bg-muted cursor-pointer select-none",
        className,
      )}
    >
      <button
        type="button"
        onClick={handleClick}
        className="flex items-center gap-1.5 min-w-0"
        title={`Open ${basename}`}
      >
        <Icon className="size-3.5 shrink-0 text-blue-600" />
        <span className="truncate max-w-48 font-medium">{basename}</span>
      </button>
      <a
        href={downloadUrl}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        title="Download"
        className="text-muted-foreground hover:text-foreground shrink-0"
      >
        <DownloadIcon className="size-3" />
      </a>
    </span>
  );
}
