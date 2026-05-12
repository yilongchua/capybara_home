import type { ActivityEvent, ActivityTimelineState } from "./types";

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  return undefined;
}

export function normalizeActivityEvent(input: unknown): ActivityEvent | null {
  const record = asRecord(input);
  const runId = record.run_id;
  const actor = record.actor;
  const kind = record.kind;
  const line = record.line;
  const timestamp = asNumber(record.timestamp);

  if (
    typeof runId !== "string" ||
    typeof actor !== "string" ||
    typeof kind !== "string" ||
    typeof line !== "string" ||
    timestamp === undefined
  ) {
    return null;
  }

  return {
    id: typeof record.id === "string" ? record.id : undefined,
    schema: typeof record.schema === "string" ? record.schema : undefined,
    run_id: runId,
    seq: asNumber(record.seq),
    timestamp,
    actor: actor as ActivityEvent["actor"],
    kind,
    line,
    task_id:
      typeof record.task_id === "string" || record.task_id === null
        ? record.task_id
        : undefined,
    group_id:
      typeof record.group_id === "string" || record.group_id === null
        ? record.group_id
        : undefined,
    tool_summary:
      typeof record.tool_summary === "string" || record.tool_summary === null
        ? record.tool_summary
        : undefined,
    assistant_message_id:
      typeof record.assistant_message_id === "string" || record.assistant_message_id === null
        ? record.assistant_message_id
        : undefined,
    payload: asRecord(record.payload),
  };
}

export function isActivityEventV1(input: unknown): input is ActivityEvent {
  const record = asRecord(input);
  return (
    record.type === "activity_event.v1" &&
    typeof record.run_id === "string" &&
    typeof record.actor === "string" &&
    typeof record.kind === "string" &&
    typeof record.line === "string" &&
    typeof record.timestamp === "number"
  );
}

function dedupeAndSort(events: ActivityEvent[]): ActivityEvent[] {
  const byId = new Map<string, ActivityEvent>();
  const withoutId: ActivityEvent[] = [];
  for (const event of events) {
    if (event.id) {
      byId.set(event.id, event);
    } else {
      withoutId.push(event);
    }
  }
  const deduped = [...byId.values(), ...withoutId];
  deduped.sort((a, b) => {
    if (a.timestamp !== b.timestamp) return a.timestamp - b.timestamp;
    if ((a.seq ?? 0) !== (b.seq ?? 0)) return (a.seq ?? 0) - (b.seq ?? 0);
    return (a.id ?? "").localeCompare(b.id ?? "");
  });
  return deduped;
}

export function asActivityTimelineState(input: unknown): ActivityTimelineState | undefined {
  const record = asRecord(input);
  const rawEvents = Array.isArray(record.events) ? record.events : [];
  const events = rawEvents
    .map((item) => normalizeActivityEvent(item))
    .filter((item): item is ActivityEvent => item !== null);
  return {
    version: typeof record.version === "string" ? record.version : undefined,
    events: dedupeAndSort(events),
  };
}

export function mergeActivityEvents(
  persisted?: ActivityTimelineState,
  liveEvents?: ActivityEvent[],
): ActivityEvent[] {
  const events = dedupeAndSort([
    ...(persisted?.events ?? []),
    ...(liveEvents ?? []),
  ]);
  return events.slice(-1200);
}
