"use client";

import { useMemo } from "react";

import { CSV_ROW_LIMIT } from "@/core/dreamy/constants";
import { useFilePreviewContent } from "@/core/dreamy/hooks/use-file-preview-content";

import { ErrorState, LoadingState } from "./file-preview-shared";

/** RFC 4180-compliant parser: handles quoted fields, escaped quotes (""), and embedded newlines. */
function parseDelimited(text: string, delimiter: string): string[][] {
  const rows: string[][] = [];
  let cells: string[] = [];
  let cell = "";
  let inQuotes = false;
  let i = 0;

  while (i < text.length) {
    const ch = text[i];

    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 2;
        } else {
          inQuotes = false;
          i++;
        }
      } else {
        cell += ch;
        i++;
      }
    } else if (ch === '"') {
      inQuotes = true;
      i++;
    } else if (ch === delimiter) {
      cells.push(cell);
      cell = "";
      i++;
    } else if (ch === "\r" && text[i + 1] === "\n") {
      cells.push(cell);
      rows.push(cells);
      cells = [];
      cell = "";
      i += 2;
    } else if (ch === "\n") {
      cells.push(cell);
      rows.push(cells);
      cells = [];
      cell = "";
      i++;
    } else {
      cell += ch;
      i++;
    }
  }

  if (cell || cells.length > 0) {
    cells.push(cell);
    rows.push(cells);
  }

  return rows.filter((r) => r.some((c) => c.length > 0));
}

export function CsvPreview({
  filename,
  artifactUrl,
  version,
}: {
  filename: string;
  artifactUrl: string;
  version?: number;
}) {
  const delimiter = filename.toLowerCase().endsWith(".tsv") ? "\t" : ",";
  const { data: content, isLoading, error } = useFilePreviewContent({
    artifactUrl,
    enabled: true,
    version,
  });

  const { headers, rows, truncated } = useMemo(() => {
    if (!content) return { headers: [], rows: [], truncated: false };
    const all = parseDelimited(content, delimiter);
    const [head, ...rest] = all;
    const isTruncated = rest.length > CSV_ROW_LIMIT;
    return {
      headers: head ?? [],
      rows: rest.slice(0, CSV_ROW_LIMIT),
      truncated: isTruncated,
    };
  }, [content, delimiter]);

  if (isLoading) return <LoadingState filename={filename} />;
  if (error) return <ErrorState filename={filename} artifactUrl={artifactUrl} />;

  return (
    <div className="flex size-full flex-col">
      <div className="shrink-0 border-b px-3 py-1.5 text-xs text-muted-foreground">
        {rows.length} rows × {headers.length} columns
        {truncated && <span className="ml-2 text-amber-600">(showing first {CSV_ROW_LIMIT})</span>}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-background">
            <tr>
              {headers.map((h, i) => (
                <th
                  key={i}
                  className="border-b border-r px-2 py-1 text-left font-medium text-muted-foreground whitespace-nowrap last:border-r-0"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className="even:bg-muted/20 hover:bg-muted/40 transition-colors">
                {headers.map((_, ci) => (
                  <td
                    key={ci}
                    className="max-w-[200px] truncate border-b border-r px-2 py-1 last:border-r-0"
                    title={row[ci]}
                  >
                    {row[ci]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
