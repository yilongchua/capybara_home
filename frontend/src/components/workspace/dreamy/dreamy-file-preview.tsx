"use client";

import {
  ClipboardIcon,
  DownloadIcon,
  FolderOpenIcon,
  SquareArrowOutUpRightIcon,
  XIcon,
} from "lucide-react";
import { useCallback } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { getBackendBaseURL } from "@/core/config";
import { useCheckpoint } from "@/core/dreamy/hooks/use-checkpoint";
import {
  isMacOS,
  useMacOSFileActions,
} from "@/core/dreamy/hooks/use-macos-file-actions";
import type { SelectedFile } from "@/core/dreamy/types";
import { useI18n } from "@/core/i18n/hooks";
import { checkCodeFile, getFileIcon } from "@/core/utils/files";

import {
  AudioPreview,
  CodePreview,
  CsvPreview,
  GenericPreview,
  HtmlPreview,
  ImagePreview,
  MarkdownPreview,
  OfficePreview,
  PdfPreview,
  VideoPreview,
} from "./dreamy-file-renderers";

export type { SelectedFile };

// ─── Renderer router ────────────────────────────────────────────────────────

function PreviewContent({
  file,
  thumbnailUrl,
  liveVersion,
}: {
  file: SelectedFile;
  thumbnailUrl: string;
  liveVersion?: number;
}) {
  const ext = file.filename.split(".").pop()?.toLowerCase() ?? "";

  // Images
  if (["jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "tiff", "tif", "heic", "ico"].includes(ext)) {
    return <ImagePreview filename={file.filename} artifactUrl={file.artifactUrl} />;
  }

  // PDF
  if (ext === "pdf") {
    if (file.markdownArtifactUrl) {
      return <OfficePreview filename={file.filename} artifactUrl={file.artifactUrl} markdownArtifactUrl={file.markdownArtifactUrl} />;
    }
    return <PdfPreview filename={file.filename} artifactUrl={file.artifactUrl} />;
  }

  // CSV / TSV
  if (["csv", "tsv"].includes(ext)) {
    return <CsvPreview filename={file.filename} artifactUrl={file.artifactUrl} version={liveVersion} />;
  }

  // Audio
  if (["mp3", "wav", "ogg", "aac", "m4a", "flac", "aiff", "ape", "wma"].includes(ext)) {
    return <AudioPreview filename={file.filename} artifactUrl={file.artifactUrl} />;
  }

  // Video
  if (["mp4", "mov", "m4v", "webm", "mkv", "avi"].includes(ext)) {
    return <VideoPreview filename={file.filename} artifactUrl={file.artifactUrl} />;
  }

  // Office (Word / Excel / PowerPoint) — show converted markdown if available
  if (["xlsx", "xls", "doc", "docx", "ppt", "pptx"].includes(ext)) {
    return (
      <OfficePreview
        filename={file.filename}
        artifactUrl={file.artifactUrl}
        markdownArtifactUrl={file.markdownArtifactUrl}
      />
    );
  }

  // HTML
  if (["html", "htm"].includes(ext)) {
    return <HtmlPreview filename={file.filename} artifactUrl={file.artifactUrl} />;
  }

  // Markdown
  if (["md", "mdx"].includes(ext)) {
    return <MarkdownPreview filename={file.filename} artifactUrl={file.artifactUrl} />;
  }

  // All other code files
  if (checkCodeFile(file.filename).isCodeFile) {
    return <CodePreview filename={file.filename} artifactUrl={file.artifactUrl} />;
  }

  // Generic fallback — shows qlmanage thumbnail on macOS
  return (
    <GenericPreview
      filename={file.filename}
      artifactUrl={file.artifactUrl}
      thumbnailUrl={isMacOS() ? thumbnailUrl : undefined}
    />
  );
}

// ─── Header ─────────────────────────────────────────────────────────────────

function HeaderAction({
  icon: Icon,
  label,
  onClick,
}: {
  icon: React.ElementType;
  label: string;
  onClick: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="icon" className="size-7" onClick={onClick}>
          <Icon className="size-3.5" />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
}

// ─── Main component ─────────────────────────────────────────────────────────

export function DreamyFilePreview({
  file,
  threadId,
  onClose,
}: {
  file: SelectedFile;
  threadId: string;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const { revealInFinder, getThumbnailUrl } = useMacOSFileActions(threadId);
  const thumbnailUrl = file.fullPath ? getThumbnailUrl(file.fullPath) : "";

  const isLiveOutput = file.isLiveOutput ?? false;
  const { data: checkpoint } = useCheckpoint(threadId, isLiveOutput);
  const liveVersion = isLiveOutput ? (checkpoint?.completed.length ?? 0) : undefined;

  const downloadUrl = (() => {
    const base = file.artifactUrl.startsWith("http")
      ? file.artifactUrl
      : `${getBackendBaseURL()}${file.artifactUrl}`;
    return `${base}?download=true`;
  })();

  const openUrl = file.artifactUrl.startsWith("http")
    ? file.artifactUrl
    : `${getBackendBaseURL()}${file.artifactUrl}`;

  const handleCopyPath = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(file.fullPath ?? file.filename);
      toast.success("Path copied");
    } catch {
      toast.error("Failed to copy path");
    }
  }, [file.fullPath, file.filename]);

  const handleReveal = useCallback(async () => {
    if (!file.fullPath) return;
    try {
      await revealInFinder(file.fullPath);
    } catch {
      toast.error("Failed to reveal in Finder");
    }
  }, [file.fullPath, revealInFinder]);

  return (
    <div className="flex size-full flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center gap-2 border-b bg-muted/30 px-2 py-1.5">
        {getFileIcon(file.filename, "size-4 shrink-0 text-muted-foreground")}
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {file.filename}
        </span>
        {isLiveOutput && liveVersion !== undefined && liveVersion > 0 && (
          <span className="flex shrink-0 items-center gap-1 text-[10px] text-emerald-600 dark:text-emerald-400">
            <span className="size-1.5 rounded-full bg-emerald-500 animate-pulse" />
            {t.dreamy.filePreview.liveRows(liveVersion)}
          </span>
        )}
        <div className="flex shrink-0 items-center gap-0.5">
          {isMacOS() && file.fullPath && (
            <HeaderAction
              icon={FolderOpenIcon}
              label="Reveal in Finder"
              onClick={handleReveal}
            />
          )}
          <HeaderAction
            icon={ClipboardIcon}
            label="Copy path"
            onClick={handleCopyPath}
          />
          <HeaderAction
            icon={SquareArrowOutUpRightIcon}
            label="Open in new tab"
            onClick={() => window.open(openUrl, "_blank")}
          />
          <HeaderAction
            icon={DownloadIcon}
            label="Download"
            onClick={() => window.open(downloadUrl, "_blank")}
          />
          <HeaderAction
            icon={XIcon}
            label="Close preview"
            onClick={onClose}
          />
        </div>
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1">
        <PreviewContent file={file} thumbnailUrl={thumbnailUrl} liveVersion={liveVersion} />
      </div>
    </div>
  );
}
