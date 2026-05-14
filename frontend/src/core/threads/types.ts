import type { Message, Thread } from "@langchain/langgraph-sdk";

import type { ActivityTimelineState } from "../activity";
import type { Todo } from "../todos";
import type { ExecutionTraceState } from "../traces";

export interface UploadedFileMeta {
  filename: string;
  size: number;
  path: string;
  extension?: string;
}

export interface PhaseResult {
  phase_index: number;
  todo_id: string;
  content: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  subagent_type?: string | null;
  completed_at?: string;
}

export interface WorkModeState {
  active?: boolean;
  plan_source?: string;
  current_phase_index?: number;
  total_phases?: number;
  phases_completed?: number;
}

export interface PhaseExecutionState {
  current_phase?: number;
  total_phases?: number;
  phase_results?: PhaseResult[];
  plan_adapted?: boolean;
  adaptation_notes?: string;
  adaptation_attempts?: number;
}

export interface PlanState {
  plan_id?: string;
  status?: "draft" | "approved" | "executing" | "completed" | string;
  title?: string;
  objective?: string;
  summary?: string;
  assumptions?: string[];
  constraints?: string[];
  risks?: Array<{ risk?: string; mitigation?: string }>;
  acceptance_criteria?: string[];
  domain?: string;
  todo_ids?: string[];
  clarifications?: Array<{
    question?: string;
    options?: Array<{
      label?: string;
      recommended?: boolean;
      description?: string | null;
    }>;
  }>;
  clarification_pending?: boolean;
  clarification_question?: string;
  clarification_answered_at?: string;
  sprint_contract_path?: string;
  plan_path?: string;
  latest_alias_path?: string;
  created_at?: string;
  approved_at?: string;
  execution_started_at?: string;
  completed_at?: string;
}

export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: Message[];
  artifacts: string[];
  uploaded_files?: UploadedFileMeta[] | null;
  plan?: PlanState | null;
  dreamy_mode?: boolean;
  dreamy_intent?: {
    shape: string;
    intent_class: string;
    confidence: number;
    extracted_fields: string[];
    inferred_goal: string;
    workflow_requested: boolean;
  };
  todos?: Todo[];
  execution_trace?: ExecutionTraceState;
  activity_timeline?: ActivityTimelineState;
  context_metrics?: {
    token_count?: number;
    message_count?: number;
    context_updated_at?: number;
    compaction_count?: number;
    last_compaction_at?: number;
    messages_compressed?: number;
    messages_kept?: number;
  };
  work_mode?: WorkModeState | null;
  phase_execution?: PhaseExecutionState | null;
}

export type AgentThread = Thread<AgentThreadState>;

export interface AgentThreadContext extends Record<string, unknown> {
  thread_id: string;
  model_name: string | undefined;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  dreamy_mode?: boolean;
  reasoning_effort?: "minimal" | "low" | "medium" | "high";
  mask_sensitive_search?: boolean;
  agent_name?: string;
  auto_mode?: boolean;
  execute_approved_plan?: boolean;
  mode?: "work" | "plan";
}
