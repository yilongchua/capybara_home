"use client";

import { FileIcon } from "lucide-react";
import { useState } from "react";

import { ErrorState, resolveUrl } from "./file-preview-shared";

export function ImagePreview({
  filename,
  artifactUrl,
}: {
  filename: string;
  artifactUrl: string;
}) {
  const [errored, setErrored] = useState(false);
  const url = resolveUrl(artifactUrl);

  if (errored) return <ErrorState filename={filename} artifactUrl={artifactUrl} />;

  return (
    <div className="flex size-full items-center justify-center bg-muted/20 p-4">
      <img
        src={url}
        alt={filename}
        loading="lazy"
        className="max-h-full max-w-full rounded object-contain"
        onError={() => setErrored(true)}
      />
    </div>
  );
}

export function AudioPreview({
  filename,
  artifactUrl,
}: {
  filename: string;
  artifactUrl: string;
}) {
  const url = resolveUrl(artifactUrl);
  return (
    <div className="flex size-full flex-col items-center justify-center gap-4 p-6">
      <FileIcon className="size-12 text-muted-foreground opacity-30" />
      <p className="text-sm font-medium">{filename}</p>
      <audio controls src={url} className="w-full max-w-xs" />
    </div>
  );
}

export function VideoPreview({
  filename,
  artifactUrl,
}: {
  filename: string;
  artifactUrl: string;
}) {
  const url = resolveUrl(artifactUrl);
  return (
    <video
      controls
      src={url}
      className="size-full bg-black object-contain"
      title={filename}
    />
  );
}
