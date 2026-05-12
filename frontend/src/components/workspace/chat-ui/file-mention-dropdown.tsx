"use client";

import { FileIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { usePromptInputController } from "@/components/ai-elements/prompt-input";
import {
  Command,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  type MountedFolderFile,
  useMountedFolderFiles,
} from "@/core/dreamy/hooks/use-mounted-folder-files";
import { useFileMention } from "@/hooks/use-file-mention";
import { cn } from "@/lib/utils";

const MAX_VISIBLE = 50;
export const FILE_MENTION_ACTIVITY_EVENT = "capybara:file-mention-activity";

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function fuzzyMatch(name: string, query: string): boolean {
  if (!query) return true;
  return name.toLowerCase().includes(query.toLowerCase());
}

function valueOf(file: MountedFolderFile): string {
  return file.virtual_path;
}

export function FileMentionDropdown({
  threadId,
  className,
}: {
  threadId: string;
  className?: string;
}) {
  const controller = usePromptInputController();
  const anchorRef = useRef<HTMLDivElement | null>(null);
  const [textarea, setTextarea] = useState<HTMLTextAreaElement | null>(null);

  // Locate the textarea sibling once mounted.
  useEffect(() => {
    const parent = anchorRef.current?.parentElement;
    const ta =
      parent?.querySelector<HTMLTextAreaElement>('textarea[name="message"]') ??
      null;
    if (ta !== textarea) {
      setTextarea(ta);
    }
  }, [textarea]);

  const { isActive, query, accept, dismiss } = useFileMention({
    textarea,
    value: controller.textInput.value,
    setValue: controller.textInput.setInput,
  });

  const { data } = useMountedFolderFiles(threadId, isActive);
  const allFiles = useMemo<MountedFolderFile[]>(
    () => data?.files ?? [],
    [data],
  );
  const folderMounted = Boolean(data?.folder_path);

  const filtered = useMemo(
    () => allFiles.filter((f) => fuzzyMatch(f.name, query)).slice(0, MAX_VISIBLE),
    [allFiles, query],
  );

  const [selected, setSelected] = useState<string>("");

  // Keep `selected` pointing at a real file as the filtered list changes.
  useEffect(() => {
    window.dispatchEvent(
      new CustomEvent(FILE_MENTION_ACTIVITY_EVENT, {
        detail: {
          active: isActive,
          query,
        },
      }),
    );

    return () => {
      window.dispatchEvent(
        new CustomEvent(FILE_MENTION_ACTIVITY_EVENT, {
          detail: { active: false, query: "" },
        }),
      );
    };
  }, [isActive, query]);

  useEffect(() => {
    if (filtered.length === 0) {
      setSelected("");
      return;
    }
    if (!filtered.some((f) => valueOf(f) === selected)) {
      setSelected(valueOf(filtered[0]!));
    }
  }, [filtered, selected]);

  // Intercept ArrowDown/ArrowUp/Enter/Tab/Escape on the textarea while active.
  useEffect(() => {
    if (!isActive) return;
    if (!textarea) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        dismiss();
        return;
      }
      if (filtered.length === 0) return;
      const idx = filtered.findIndex((f) => valueOf(f) === selected);
      if (e.key === "ArrowDown") {
        e.preventDefault();
        e.stopPropagation();
        const next = filtered[(idx + 1) % filtered.length]!;
        setSelected(valueOf(next));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        e.stopPropagation();
        const prev =
          filtered[(idx - 1 + filtered.length) % filtered.length]!;
        setSelected(valueOf(prev));
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        e.stopPropagation();
        const target = filtered.find((f) => valueOf(f) === selected) ?? filtered[0]!;
        accept(target);
      }
    };
    textarea.addEventListener("keydown", handler, true);
    return () => textarea.removeEventListener("keydown", handler, true);
  }, [isActive, textarea, filtered, selected, accept, dismiss]);

  if (!isActive) {
    return <div ref={anchorRef} className="hidden" aria-hidden />;
  }

  // Avoid showing an empty white popup when there are no candidates.
  // The larger files tray can still be used to browse files.
  if (!folderMounted || filtered.length === 0) {
    return <div ref={anchorRef} className="hidden" aria-hidden />;
  }

  return (
    <>
      <div ref={anchorRef} className="hidden" aria-hidden />
      <div
        className={cn(
          "bg-background/95 text-popover-foreground absolute bottom-full left-0 z-50 mb-2 w-80 overflow-hidden rounded-lg border shadow-md backdrop-blur-sm",
          className,
        )}
        role="listbox"
      >
        <Command
          shouldFilter={false}
          value={selected}
          onValueChange={setSelected}
          className="max-h-72"
        >
          <div className="border-b px-3 py-2 text-xs">
            <span className="text-muted-foreground">@</span>
            <span className="ml-1 font-mono">{query || "…"}</span>
          </div>
          <CommandList>
            <CommandGroup>
              {filtered.map((file) => (
                <CommandItem
                  key={valueOf(file)}
                  value={valueOf(file)}
                  onSelect={() => accept(file)}
                >
                  <FileIcon className="size-4 shrink-0 text-violet-500" />
                  <span className="truncate">{file.name}</span>
                  <span className="text-muted-foreground ml-auto text-[10px]">
                    {formatSize(file.size)}
                  </span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </div>
    </>
  );
}
