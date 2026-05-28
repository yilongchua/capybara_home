import type { ActivityEvent } from "./types";

export type ProgressOperationStatus = "active" | "completed" | "failed" | "stale";

export interface ProgressOperation {
  operationId: string;
  runId: string;
  label: string;
  status: ProgressOperationStatus;
  startedAt: number;
  completedAt?: number;
  detail?: string;
  taskId?: string;
  assistantMessageId?: string;
}

function isTerminalKind(kind: string) {
  const normalized = kind.toLowerCase();
  return (
    normalized.includes("completed") ||
    normalized.includes("failed") ||
    normalized.includes("timed_out") ||
    normalized.includes("title_generation_completed") ||
    normalized.includes("tool_call_end") ||
    normalized.includes("plan_created") ||
    normalized.includes("plan_auto_approved") ||
    normalized.includes("skipped_direct_answer") ||
    normalized.includes("parse_failed_fallback")
  );
}

function statusFromKind(kind: string): ProgressOperationStatus {
  const normalized = kind.toLowerCase();
  if (
    normalized.includes("failed") ||
    normalized.includes("timed_out") ||
    normalized.includes("validation_failed") ||
    normalized.includes("rejected")
  ) {
    return "failed";
  }
  return isTerminalKind(kind) ? "completed" : "active";
}

function operationIdForEvent(event: ActivityEvent): string | null {
  const kind = event.kind.toLowerCase();
  const source = typeof event.payload?.source === "string" ? event.payload.source : "";
  const tool = typeof event.payload?.tool === "string" ? event.payload.tool : "";

  if (kind.startsWith("title_generation")) {
    return `title:${event.run_id}`;
  }
  if (kind === "planning_started" || kind === "planning_failed" || kind === "plan_created" || kind === "plan_auto_approved") {
    return `planner:todos:${event.run_id}`;
  }
  if (kind === "skipped_direct_answer" || kind === "parse_failed_fallback") {
    return `planner:complexity:${event.run_id}`;
  }
  if (source === "plan_evaluator") {
    return `planner:evaluator:${event.run_id}`;
  }
  if (source === "write_todos_tool") {
    return `tool:write_todos:${event.task_id ?? event.run_id}`;
  }
  if (kind === "tool_call_start" || kind === "tool_call_end" || kind === "plan_gate_blocked") {
    return `tool:${event.task_id ?? `${tool}:${event.run_id}`}`;
  }
  if (event.task_id && (kind.startsWith("task_") || event.actor === "baby_capy")) {
    return `subagent:${event.task_id}`;
  }
  return null;
}

function labelForEvent(event: ActivityEvent, status: ProgressOperationStatus): string {
  const kind = event.kind.toLowerCase();
  const line = event.line.trim();
  const source = typeof event.payload?.source === "string" ? event.payload.source : "";
  const tool = typeof event.payload?.tool === "string" ? event.payload.tool : "";

  if (kind === "planning_started") {
    return "Planner is creating todos...";
  }
  if (kind === "planning_failed") {
    const reason = typeof event.payload?.reason === "string" ? event.payload.reason : "error";
    return reason === "timeout" ? "Planner timed out — try again" : "Planner failed — try again";
  }
  if (kind === "plan_created" || kind === "plan_auto_approved") {
    const count = event.payload?.todo_count;
    return typeof count === "number" ? `Planner created ${count} todo(s)` : "Planner created todos";
  }
  if (kind === "skipped_direct_answer") {
    return "Planner answered directly without a separate plan";
  }
  if (kind === "parse_failed_fallback") {
    return "Planner evaluated request complexity and used a fallback";
  }
  if (source === "plan_evaluator" && status === "active") {
    return "Plan evaluator is reviewing the plan...";
  }
  if (tool === "present_files") {
    return kind === "tool_call_end" ? "Presented files" : "Preparing files...";
  }
  return line;
}

function detailForEvent(event: ActivityEvent): string | undefined {
  const tool = typeof event.payload?.tool === "string" ? event.payload.tool : "";
  if (tool === "write_todos" || tool === "present_files") {
    return undefined;
  }
  const summary = event.tool_summary ?? undefined;
  if (summary && event.line.includes(summary)) {
    return undefined;
  }
  return summary;
}

export function buildProgressOperations(events: ActivityEvent[]): ProgressOperation[] {
  const operations = new Map<string, ProgressOperation>();

  const upsertOperation = (
    operationId: string,
    event: ActivityEvent,
    status: ProgressOperationStatus,
    label: string,
  ) => {
    const existing = operations.get(operationId);
    const startedAt = existing?.startedAt ?? event.timestamp;
    const completedAt = status === "active" ? existing?.completedAt : event.timestamp;

    operations.set(operationId, {
      operationId,
      runId: event.run_id,
      label,
      status,
      startedAt,
      completedAt,
      detail: detailForEvent(event),
      taskId: event.task_id ?? undefined,
      assistantMessageId: event.assistant_message_id ?? undefined,
    });
  };

  for (const event of events) {
    if (event.kind.toLowerCase() === "planning_started") {
      upsertOperation(
        `planner:complexity:${event.run_id}`,
        event,
        "completed",
        "Planner evaluated request complexity",
      );
    }

    const operationId = operationIdForEvent(event);
    if (!operationId) {
      continue;
    }

    const status = statusFromKind(event.kind);
    upsertOperation(operationId, event, status, labelForEvent(event, status));
  }

  return [...operations.values()].sort((a, b) => {
    const aTime = a.completedAt ?? a.startedAt;
    const bTime = b.completedAt ?? b.startedAt;
    if (aTime !== bTime) return aTime - bTime;
    return a.operationId.localeCompare(b.operationId);
  });
}
