"use client";

import { useQueryClient } from "@tanstack/react-query";
import { RefreshCwIcon, FolderOpenIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useMountedFolder } from "@/core/workspace-io/hooks/use-mounted-folder";
import { cn } from "@/lib/utils";

import { Tooltip } from "../tooltip";

function truncatePath(path: string, maxLen = 36): string {
  if (path.length <= maxLen) return path;
  const head = path.slice(0, 8);
  const tail = path.slice(-(maxLen - head.length - 1));
  return `${head}…${tail}`;
}

export function MountFolderBadge({
  threadId,
  className,
}: {
  threadId: string;
  className?: string;
}) {
  const queryClient = useQueryClient();
  const { data: mountedPath } = useMountedFolder(threadId);

  if (!mountedPath) {
    return null;
  }

  return (
    <div
      className={cn(
        "text-muted-foreground inline-flex items-center gap-1.5 px-0 py-0 text-xs",
        className,
      )}
    >
      <FolderOpenIcon className="text-violet-500 size-3.5 shrink-0" />
      <Tooltip content={mountedPath}>
        <span className="max-w-[280px] truncate font-mono">
          {truncatePath(mountedPath)}
        </span>
      </Tooltip>
      <Button
        variant="ghost"
        size="icon-sm"
        className="size-5"
        title="Refresh mounted folder"
        aria-label="Refresh mounted folder"
        onClick={() => {
          void queryClient.invalidateQueries({
            queryKey: ["dreamy-mounted-folder", threadId],
            exact: true,
          });
          void queryClient.invalidateQueries({
            queryKey: ["dreamy-mounted-folder-files", threadId],
            exact: true,
          });
        }}
      >
        <RefreshCwIcon className="size-3" />
      </Button>
    </div>
  );
}
