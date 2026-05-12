export type TraceStage = "lead" | "planner" | "evaluator" | "subagent" | "harness";
export type TraceThinkingSource = "raw" | "summary";

export interface TraceThinking {
  source: TraceThinkingSource;
  content: string;
}

export interface TraceTokenUsage {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
}

export interface ExecutionTraceEvent {
  id?: string;
  schema?: string;
  run_id: string;
  turn_id?: string | null;
  stage: TraceStage;
  event_type: string;
  timestamp: number;
  seq?: number;
  status: string;
  payload?: Record<string, unknown>;
  token_usage?: TraceTokenUsage;
  thinking?: TraceThinking;
  assistant_message_id?: string | null;
  task_id?: string | null;
  payload_truncated?: boolean;
  payload_original_chars?: number;
}

export interface ExecutionTraceRun {
  run_id: string;
  started_at?: number;
  updated_at?: number;
  events: ExecutionTraceEvent[];
}

export interface ExecutionTraceState {
  version?: string;
  runs: Record<string, ExecutionTraceRun>;
}

export interface ExecutionTraceIndex {
  allEvents: ExecutionTraceEvent[];
  byAssistantMessageId: Record<string, ExecutionTraceEvent[]>;
  byTaskId: Record<string, ExecutionTraceEvent[]>;
  runs: Record<string, ExecutionTraceRun>;
  latestRunId?: string;
  aggregateTokenUsage: TraceTokenUsage;
}

