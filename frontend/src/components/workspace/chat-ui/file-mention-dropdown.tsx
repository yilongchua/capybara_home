"use client";

import { FileIcon, FolderIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { usePromptInputController } from "@/components/ai-elements/prompt-input";
import {
  Command,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { getBackendBaseURL } from "@/core/config";
import {
  type MountedFolderFile,
  useMountedFolderFiles,
} from "@/core/dreamy/hooks/use-mounted-folder-files";
import { useFileMention } from "@/hooks/use-file-mention";
import { cn } from "@/lib/utils";

const MAX_VISIBLE = 120;
export const FILE_MENTION_ACTIVITY_EVENT = "capyhome:file-mention-activity";

function fuzzyMatch(file: MountedFolderFile, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  const normalizedName = file.name.replace(/\/$/, "").toLowerCase();
  const normalizedPath = file.virtual_path.replace(/\/$/, "").toLowerCase();
  return (
    normalizedName.includes(q) ||
    normalizedPath.includes(q)
  );
}

function valueOf(file: MountedFolderFile): string {
  return file.virtual_path;
}

function displayNameOf(file: MountedFolderFile): string {
  const raw = file.name.replace(/\/$/, "");
  const segments = raw.split("/").filter(Boolean);
  return segments[segments.length - 1] ?? raw;
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
  const [outputFiles, setOutputFiles] = useState<MountedFolderFile[]>([]);

  useEffect(() => {
    if (!isActive || !threadId || threadId === "new") {
      setOutputFiles([]);
      return;
    }
    let cancelled = false;
    const loadWorkspaceFiles = async () => {
      try {
        const res = await fetch(`${getBackendBaseURL()}/api/threads/${threadId}/artifacts-list`);
        if (!res.ok) {
          throw new Error("Failed to list thread artifacts");
        }
        const payload = (await res.json()) as { files?: string[] };
        if (cancelled) {
          return;
        }
        const rawWorkspaceFiles = (payload.files ?? [])
          .filter((file) => file.startsWith("/mnt/user-data/workspace/"))
          .map((virtualPath) => {
            const name = virtualPath.split("/").pop() ?? virtualPath;
            return {
              name,
              size: 0,
              virtual_path: virtualPath,
              full_path: virtualPath,
              is_dir: false,
            } satisfies MountedFolderFile;
          });
        const directoryMap = new Map<string, MountedFolderFile>();
        for (const file of rawWorkspaceFiles) {
          const rel = file.virtual_path.replace("/mnt/user-data/workspace/", "");
          const parts = rel.split("/").filter(Boolean);
          if (parts.length <= 1) continue;
          let acc = "/mnt/user-data/workspace";
          for (let i = 0; i < parts.length - 1; i += 1) {
            acc += `/${parts[i]}`;
            if (!directoryMap.has(acc)) {
              directoryMap.set(acc, {
                name: `${parts[i]}/`,
                size: 0,
                virtual_path: acc,
                full_path: acc,
                is_dir: true,
              });
            }
          }
        }
        setOutputFiles([...directoryMap.values(), ...rawWorkspaceFiles]);
      } catch {
        if (!cancelled) {
          setOutputFiles([]);
        }
      }
    };
    void loadWorkspaceFiles();
    return () => {
      cancelled = true;
    };
  }, [isActive, threadId]);

  const allFiles = useMemo<MountedFolderFile[]>(
    () => {
      const mounted = data?.files ?? [];
      const byPath = new Map<string, MountedFolderFile>();
      for (const file of mounted) {
        byPath.set(file.virtual_path, file);
      }
      for (const file of outputFiles) {
        if (!byPath.has(file.virtual_path)) {
          byPath.set(file.virtual_path, file);
        }
      }
      return Array.from(byPath.values());
    },
    [data, outputFiles],
  );
  const folderMounted = Boolean(data?.folder_path) || outputFiles.length > 0;

  const filtered = useMemo(
    () =>
      allFiles
        .filter((f) => fuzzyMatch(f, query))
        .sort((a, b) => {
          const aDir = Boolean(a.is_dir);
          const bDir = Boolean(b.is_dir);
          if (aDir !== bDir) return aDir ? -1 : 1;
          return a.virtual_path.localeCompare(b.virtual_path);
        })
        .slice(0, MAX_VISIBLE),
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
          "bg-background/95 text-popover-foreground absolute right-0 bottom-full left-0 z-50 mb-2 mx-2 overflow-hidden rounded-lg border shadow-md backdrop-blur-sm",
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
                  className="items-center gap-2 py-2"
                >
                  {file.is_dir ? (
                    <FolderIcon className="size-4 shrink-0 text-blue-500" />
                  ) : (
                    <FileIcon className="size-4 shrink-0 text-violet-500" />
                  )}
                  <div className="min-w-0 flex-1 truncate text-sm">
                    <span
                      className={cn(
                        file.is_dir ? "text-blue-500" : "text-violet-500",
                      )}
                    >
                      {displayNameOf(file)}
                    </span>
                    <span className="text-muted-foreground ml-2">
                      {file.virtual_path}
                    </span>
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </div>
    </>
  );
}
