"use client";

import {
  Source,
  SourcesContent,
  SourcesTrigger,
} from "@/components/ai-elements/sources";
import { Collapsible } from "@/components/ui/collapsible";
import type { WebSearchResultItem } from "@/core/tools/web-search";
import { cn } from "@/lib/utils";

const DEFAULT_VISIBLE = 5;

export function WebSearchSources({
  results,
  executedQuery,
  className,
}: {
  results: WebSearchResultItem[];
  executedQuery?: string;
  className?: string;
}) {
  if (results.length === 0) {
    return null;
  }

  const visible = results.slice(0, DEFAULT_VISIBLE);
  const hiddenCount = results.length - visible.length;

  return (
    <Collapsible className={cn("not-prose mt-2 text-primary text-xs", className)} defaultOpen={false}>
      <SourcesTrigger count={results.length} />
      <SourcesContent>
        {executedQuery && (
          <p className="text-muted-foreground mb-1 text-xs">
            Query: {executedQuery}
          </p>
        )}
        {visible.map((item, index) => (
          <div
            key={`${item.url}-${index}`}
            className="border-border/60 space-y-1 border-b pb-2 last:border-0 last:pb-0"
          >
            <Source href={item.url} title={item.title} />
            {item.snippet && (
              <p className="text-muted-foreground pl-6 text-xs leading-relaxed">
                {item.snippet}
              </p>
            )}
            {item.extractedPreview && item.extractedPreview !== item.snippet && (
              <p className="text-muted-foreground/80 pl-6 text-xs leading-relaxed">
                {item.extractedPreview}
              </p>
            )}
          </div>
        ))}
        {hiddenCount > 0 && (
          <p className="text-muted-foreground text-xs">
            +{hiddenCount} more source{hiddenCount === 1 ? "" : "s"}
          </p>
        )}
      </SourcesContent>
    </Collapsible>
  );
}
