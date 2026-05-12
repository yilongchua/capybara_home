export interface WorkflowStep {
  id: string;
  action: "tool_call" | "write_row" | "conditional" | "ask_clarification";
  tool?: string;
  description: string;
  input_fields: string[];
  output_fields: string[];
  on_no_result?: "skip" | "error";
  condition?: string;
  on_true_step_id?: string;
  on_false_step_id?: string;
}

export interface DataSource {
  type: "inline" | "file" | "mounted_file";
  filename: string;
  total_rows: number;
  fields: string[];
  sample_rows: Record<string, unknown>[];
  virtual_path?: string;  // agent-accessible virtual path to the source file
}

export interface PocResult {
  row_index: number;
  status: "found" | "no_result" | "error";
  seconds: number;
}

export interface ExecutionState {
  phase: "design" | "poc" | "awaiting_approval" | "bulk" | "done";
  current_row_index: number;
  current_step_id: string | null;
  total_rows: number;
  poc_results: PocResult[];
  seconds_per_row_estimate: number | null;
  estimated_completion_iso: string | null;
  started_at: string | null;
}

export interface ProgressData {
  total: number;
  done: number;
  failed: number;
  skipped: number;
  rows_per_minute: number | null;
  eta_iso: string | null;
  state:
    | "running"
    | "paused"
    | "stopped"
    | "completed"
    | "failed"
    | "awaiting_approval"
    | "not_started";
  started_at: string | null;
  updated_at: string | null;
}

export type DreamyPhase =
  | "design"
  | "poc"
  | "awaiting_approval"
  | "bulk"
  | "done"
  | "running"
  | "paused"
  | "stopped"
  | "completed"
  | "failed"
  | "not_started";

export interface SelectedFile {
  filename: string;
  artifactUrl: string;
  /** Absolute local path — set for mounted-folder files so Finder reveal works */
  fullPath?: string;
  /** Markdown version URL for converted Office/PDF uploads */
  markdownArtifactUrl?: string;
  /** True when this file updates incrementally while the workflow runs (e.g. _results CSV). Replace with a typed backend flag once the API surfaces it. */
  isLiveOutput?: boolean;
}

export interface WorkflowJson {
  version: string;
  thread_id: string;
  created_at: string;
  data_source?: DataSource;
  task_source?: {
    type: "inline" | "file" | "inferred";
    filename: string;
    total_tasks: number;
    fields: string[];
    sample_tasks: Record<string, unknown>[];
  };
  steps: WorkflowStep[];
  execution_state: ExecutionState;
}
