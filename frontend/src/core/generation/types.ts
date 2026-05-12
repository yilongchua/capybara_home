export type GenerationStatus =
  | "queued"
  | "submitted"
  | "running"
  | "completed"
  | "failed"
  | "timed_out";

export type GenerationKind = "image" | "video";

export interface GenerationJob {
  id: string;
  thread_id: string;
  kind: GenerationKind;
  status: GenerationStatus;
  prompt_id: string | null;
  filename_prefix: string;
  expected_virtual_path: string;
  output_virtual_path: string | null;
  source_output_path: string | null;
  prompt_excerpt: string;
  output_name: string;
  aspect_ratio: string;
  error: string | null;
  completion_seq: number | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface GenerationCompletionsResponse {
  items: GenerationJob[];
  next_since_seq: number;
}
