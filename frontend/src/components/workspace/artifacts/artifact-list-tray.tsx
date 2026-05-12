import { ChevronUpIcon, FilesIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

import { ArtifactFileList } from "./artifact-file-list";

export function ArtifactListTray({
  className,
  files,
  threadId,
  hidden = false,
  autoExpand = false,
}: {
  className?: string;
  files: string[];
  threadId: string;
  hidden?: boolean;
  autoExpand?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(true);

  useEffect(() => {
    if (autoExpand) {
      setCollapsed(false);
    }
  }, [autoExpand]);

  return (
    <div
      className={cn(
        "flex h-fit w-full origin-bottom translate-y-4 flex-col overflow-hidden rounded-t-xl border border-b-0 bg-white backdrop-blur-sm transition-all duration-200 ease-out",
        hidden ? "pointer-events-none translate-y-8 opacity-0" : "",
        className,
      )}
    >
      <header
        className="bg-accent flex min-h-8 shrink-0 cursor-pointer items-center justify-between px-4 text-sm transition-all duration-300 ease-out"
        onClick={() => setCollapsed((prev) => !prev)}
      >
        <div className="text-muted-foreground flex items-center justify-center gap-2">
          <FilesIcon className="size-4" />
          <div>Files</div>
        </div>
        <ChevronUpIcon
          className={cn(
            "text-muted-foreground size-4 transition-transform duration-300 ease-out",
            collapsed ? "" : "rotate-180",
          )}
        />
      </header>
      <main
        className={cn(
          "bg-accent flex grow px-2 transition-all duration-300 ease-out",
          collapsed ? "h-0 pb-3" : "h-60 pb-4",
        )}
      >
        <div className="bg-background mt-0 w-full rounded-t-xl p-2">
          <ArtifactFileList
            className="h-full overflow-y-auto"
            files={files}
            threadId={threadId}
          />
        </div>
      </main>
    </div>
  );
}
