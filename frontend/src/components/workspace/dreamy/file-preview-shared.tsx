"use client";

import { AlertTriangleIcon, DownloadIcon, LoaderIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";

export function LoadingState({ filename }: { filename: string }) {
  return (
    <div className="flex size-full flex-col items-center justify-center gap-2 text-muted-foreground">
      <LoaderIcon className="size-5 animate-spin opacity-60" />
      <p className="text-xs">{filename}</p>
    </div>
  );
}

export function ErrorState({
  filename,
  artifactUrl,
}: {
  filename: string;
  artifactUrl: string;
}) {
  const { t } = useI18n();
  const downloadUrl = artifactUrl.startsWith("http")
    ? `${artifactUrl}?download=true`
    : `${getBackendBaseURL()}${artifactUrl}?download=true`;
  return (
    <div className="flex size-full flex-col items-center justify-center gap-3 p-6 text-center text-muted-foreground">
      <AlertTriangleIcon className="size-8 opacity-40" />
      <p className="text-sm font-medium">{t.dreamy.filePreview.previewUnavailable}</p>
      <a href={downloadUrl} target="_blank" rel="noreferrer">
        <Button variant="outline" size="sm">
          <DownloadIcon className="size-3.5" />
          {t.common.download} {filename}
        </Button>
      </a>
    </div>
  );
}

export function resolveUrl(artifactUrl: string) {
  return artifactUrl.startsWith("http")
    ? artifactUrl
    : `${getBackendBaseURL()}${artifactUrl}`;
}
