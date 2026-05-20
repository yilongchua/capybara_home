import type { AIMessage } from "@langchain/langgraph-sdk";

export interface Subtask {
  id: string;
  status: "in_progress" | "completed" | "failed";
  subagent_type: string;
  description: string;
  group_title?: string;
  latestMessage?: AIMessage;
  prompt: string;
  result?: string;
  error?: string;
  started_at?: number;
  updated_at?: number;
  completed_at?: number;
}
