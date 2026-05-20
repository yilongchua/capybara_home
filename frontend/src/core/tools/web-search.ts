const SNIPPET_MAX_CHARS = 200;
const EXTRACTED_PREVIEW_MAX_CHARS = 280;

export type WebSearchResultItem = {
  title: string;
  url: string;
  snippet: string;
  extractedPreview: string;
  source?: string;
};

export type NormalizedWebSearchPayload = {
  results: WebSearchResultItem[];
  executedQuery?: string;
  summary?: string;
};

function truncate(text: string, maxChars: number): string {
  const trimmed = text.trim();
  if (trimmed.length <= maxChars) {
    return trimmed;
  }
  return `${trimmed.slice(0, maxChars).trimEnd()}…`;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, unknown>;
}

function parseToolResultObject(result: unknown): Record<string, unknown> | null {
  if (Array.isArray(result)) {
    return { results: result };
  }
  const direct = asRecord(result);
  if (direct) {
    return direct;
  }
  if (typeof result === "string") {
    try {
      const parsed = JSON.parse(result) as unknown;
      return asRecord(parsed) ?? (Array.isArray(parsed) ? { results: parsed } : null);
    } catch {
      return null;
    }
  }
  return null;
}

function normalizeResultItem(raw: unknown): WebSearchResultItem | null {
  const item = asRecord(raw);
  if (!item) {
    return null;
  }
  const url = String(item.url ?? "").trim();
  if (!url) {
    return null;
  }
  const title = String(item.title ?? url).trim() || url;
  const snippet = String(item.snippet ?? "").trim();
  const extracted = String(item.extracted_content ?? "").trim();
  return {
    title,
    url,
    snippet: truncate(snippet, SNIPPET_MAX_CHARS),
    extractedPreview: truncate(extracted, EXTRACTED_PREVIEW_MAX_CHARS),
    source: String(item.source ?? "").trim() || undefined,
  };
}

/** Normalize web_search tool JSON (array legacy or `{ results: [...] }`) for UI. */
export function normalizeWebSearchPayload(
  result: unknown,
): NormalizedWebSearchPayload | null {
  const payload = parseToolResultObject(result);
  if (!payload) {
    return null;
  }

  const rawResults = Array.isArray(payload.results) ? payload.results : [];
  const results = rawResults
    .map((item) => normalizeResultItem(item))
    .filter((item): item is WebSearchResultItem => item !== null);

  if (results.length === 0 && typeof payload.summary !== "string") {
    return null;
  }

  const executedQuery =
    typeof payload.executed_query === "string"
      ? payload.executed_query
      : typeof payload.query === "string"
        ? payload.query
        : undefined;

  const summary =
    typeof payload.summary === "string" && payload.summary.trim()
      ? payload.summary.trim()
      : undefined;

  return { results, executedQuery, summary };
}
