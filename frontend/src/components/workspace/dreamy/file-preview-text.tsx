"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import { CodeEditor } from "@/components/workspace/code-editor";
import { useFilePreviewContent } from "@/core/dreamy/hooks/use-file-preview-content";
import { streamdownPlugins } from "@/core/streamdown";
import { Streamdown } from "streamdown";

import { ErrorState, LoadingState } from "./file-preview-shared";

export function CodePreview({
  filename,
  artifactUrl,
}: {
  filename: string;
  artifactUrl: string;
}) {
  const { data: content, isLoading, error } = useFilePreviewContent({
    artifactUrl,
    enabled: true,
  });

  if (isLoading) return <LoadingState filename={filename} />;
  if (error) return <ErrorState filename={filename} artifactUrl={artifactUrl} />;

  return (
    <CodeEditor
      className="size-full resize-none rounded-none border-none"
      value={content ?? ""}
      readonly
    />
  );
}

export function MarkdownPreview({
  filename,
  artifactUrl,
}: {
  filename: string;
  artifactUrl: string;
}) {
  const { data: content, isLoading, error } = useFilePreviewContent({
    artifactUrl,
    enabled: true,
  });

  if (isLoading) return <LoadingState filename={filename} />;
  if (error) return <ErrorState filename={filename} artifactUrl={artifactUrl} />;

  return (
    <ScrollArea className="size-full">
      <div className="px-4 py-3">
        <Streamdown className="prose prose-sm dark:prose-invert max-w-none" {...streamdownPlugins}>
          {content ?? ""}
        </Streamdown>
      </div>
    </ScrollArea>
  );
}

export function HtmlPreview({
  filename,
  artifactUrl,
}: {
  filename: string;
  artifactUrl: string;
}) {
  const { data: content, isLoading, error } = useFilePreviewContent({
    artifactUrl,
    enabled: true,
  });

  if (isLoading) return <LoadingState filename={filename} />;
  if (error) return <ErrorState filename={filename} artifactUrl={artifactUrl} />;

  return (
    <iframe
      className="size-full border-none"
      title={filename}
      srcDoc={content ?? ""}
      sandbox="allow-scripts allow-forms"
    />
  );
}
