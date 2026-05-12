export type LongRunningTaskStatus =
  | "queued"
  | "submitted"
  | "pending_approval"
  | "approved"
  | "running"
  | "completed"
  | "failed"
  | "timed_out"
  | "cancelled"
  | "rejected";

export interface LongRunningTask {
  id: string;
  source: string;
  kind: string;
  title: string;
  status: LongRunningTaskStatus;
  detail?: string;
  outputPath?: string;
  error?: string;
  updatedAt?: string;
}
