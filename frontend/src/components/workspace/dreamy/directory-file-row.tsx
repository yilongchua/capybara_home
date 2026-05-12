"use client";

import {
  FileIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
} from "lucide-react";

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileIcon(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (["csv", "tsv", "xlsx", "xls"].includes(ext)) return FileSpreadsheetIcon;
  if (["txt", "md", "json", "yaml", "yml"].includes(ext)) return FileTextIcon;
  return FileIcon;
}

export interface FileRowProps {
  name: string;
  size?: string;
  badge: "input" | "uploaded" | "created" | "mounted";
  isSelected?: boolean;
  onClick: () => void;
}

const BADGE_STYLES: Record<FileRowProps["badge"], string> = {
  input:    "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400",
  uploaded: "bg-muted text-muted-foreground",
  created:  "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400",
  mounted:  "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-400",
};

const BADGE_LABELS: Record<FileRowProps["badge"], string> = {
  input: "input",
  uploaded: "file",
  created: "created",
  mounted: "mount",
};

export function FileRow({ name, size, badge, isSelected, onClick }: FileRowProps) {
  const Icon = getFileIcon(name);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onClick(); }}
      className={`group flex items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors cursor-pointer ${
        isSelected ? "bg-muted ring-1 ring-primary/40" : "hover:bg-muted/50"
      }`}
    >
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{name}</p>
        {size && <p className="text-xs text-muted-foreground">{size}</p>}
      </div>
      <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${BADGE_STYLES[badge]}`}>
        {BADGE_LABELS[badge]}
      </span>
    </div>
  );
}
