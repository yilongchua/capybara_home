"use client";

import { DownloadIcon, FileIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { getBackendBaseURL } from "@/core/config";

import { ErrorState, resolveUrl } from "./file-preview-shared";
import { MarkdownPreview } from "./file-preview-text";

export function PdfPreview({
  filename,
  artifactUrl,
}: {
  filename: string;
  artifactUrl: string;
}) {
  const url = resolveUrl(artifactUrl);
  return (
    <iframe
      src={url}
      className="size-full border-none"
      title={filename}
    />
  );
}

export function OfficePreview({
  filename,
  artifactUrl,
  markdownArtifactUrl,
}: {
  filename: string;
  artifactUrl: string;
  markdownArtifactUrl?: string;
}) {
  if (markdownArtifactUrl) {
    return <MarkdownPreview filename={filename} artifactUrl={markdownArtifactUrl} />;
  }
  return <ErrorState filename={filename} artifactUrl={artifactUrl} />;
}

export function GenericPreview({
  filename,
  artifactUrl,
  thumbnailUrl,
}: {
  filename: string;
  artifactUrl: string;
  thumbnailUrl?: string;
}) {
  const [thumbErrored, setThumbErrored] = useState(false);
  const downloadUrl = artifactUrl.startsWith("http")
    ? `${artifactUrl}?download=true`
    : `${getBackendBaseURL()}${artifactUrl}?download=true`;

  return (
    <div className="flex size-full flex-col items-center justify-center gap-4 p-6 text-center">
      {thumbnailUrl && !thumbErrored ? (
        <img
          src={thumbnailUrl}
          alt={filename}
          className="max-h-32 max-w-full rounded object-contain shadow"
          onError={() => setThumbErrored(true)}
        />
      ) : (
        <FileIcon className="size-12 text-muted-foreground opacity-30" />
      )}
      <p className="text-sm font-medium">{filename}</p>
      <a href={downloadUrl} target="_blank" rel="noreferrer">
        <Button variant="outline" size="sm">
          <DownloadIcon className="size-3.5" />
          Download
        </Button>
      </a>
    </div>
  );
}
