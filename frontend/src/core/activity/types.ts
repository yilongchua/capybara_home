export type ActivityActor = "capybara" | "baby_capy" | "system";

export interface ActivityEvent {
  id?: string;
  schema?: string;
  run_id: string;
  seq?: number;
  timestamp: number;
  actor: ActivityActor;
  kind: string;
  line: string;
  task_id?: string | null;
  group_id?: string | null;
  group_kind?: string | null;
  group_title?: string | null;
  group_role?: string | null;
  subagent_type?: string | null;
  description?: string | null;
  tool_summary?: string | null;
  assistant_message_id?: string | null;
  payload?: Record<string, unknown>;
}

export interface ActivityTimelineState {
  version?: string;
  events: ActivityEvent[];
}
