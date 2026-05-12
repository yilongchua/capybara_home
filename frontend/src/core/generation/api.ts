import { getBackendBaseURL } from "@/core/config";

import type { GenerationCompletionsResponse } from "./types";
import type { GenerationJob } from "./types";

export async function fetchGenerationCompletions(
  threadId: string,
  sinceSeq: number,
  signal?: AbortSignal,
): Promise<GenerationCompletionsResponse> {
  const url = `${getBackendBaseURL()}/api/threads/${threadId}/generation/completions?since_seq=${sinceSeq}&limit=20`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Failed to fetch generation completions (${response.status})`);
  }
  return (await response.json()) as GenerationCompletionsResponse;
}

export async function fetchGenerationJobs(
  threadId: string,
  signal?: AbortSignal,
): Promise<GenerationJob[]> {
  const url = `${getBackendBaseURL()}/api/threads/${threadId}/generation/jobs?limit=100`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Failed to fetch generation jobs (${response.status})`);
  }
  const payload = (await response.json()) as { items: GenerationJob[] };
  return payload.items ?? [];
}
