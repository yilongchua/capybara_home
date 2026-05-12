import type {
  ExecutionTraceEvent,
  ExecutionTraceIndex,
  ExecutionTraceRun,
  ExecutionTraceState,
  TraceTokenUsage,
} from "./types";

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

function normalizeEvent(input: unknown): ExecutionTraceEvent | null {
  const record = asRecord(input);
  const runId = record.run_id;
  const stage = record.stage;
  const eventType = record.event_type;
  const status = record.status;
  const timestamp = asNumber(record.timestamp);
  if (
    typeof runId !== "string" ||
    typeof stage !== "string" ||
    typeof eventType !== "string" ||
    typeof status !== "string" ||
    timestamp === undefined
  ) {
    return null;
  }

  const event: ExecutionTraceEvent = {
    id: typeof record.id === "string" ? record.id : undefined,
    schema: typeof record.schema === "string" ? record.schema : undefined,
    run_id: runId,
    stage: stage as ExecutionTraceEvent["stage"],
    event_type: eventType,
    timestamp,
    seq: asNumber(record.seq),
    status,
    turn_id:
      typeof record.turn_id === "string" || record.turn_id === null
        ? (record.turn_id)
        : undefined,
    assistant_message_id:
      typeof record.assistant_message_id === "string" ||
      record.assistant_message_id === null
        ? (record.assistant_message_id)
        : undefined,
    task_id:
      typeof record.task_id === "string" || record.task_id === null
        ? (record.task_id)
        : undefined,
    payload: asRecord(record.payload),
    payload_truncated:
      typeof record.payload_truncated === "boolean"
        ? record.payload_truncated
        : undefined,
    payload_original_chars: asNumber(record.payload_original_chars),
  };

  const thinking = asRecord(record.thinking);
  if (
    typeof thinking.source === "string" &&
    typeof thinking.content === "string"
  ) {
    event.thinking = {
      source: thinking.source as "raw" | "summary",
      content: thinking.content,
    };
  }

  const tokenUsage = asRecord(record.token_usage);
  if (Object.keys(tokenUsage).length > 0) {
    event.token_usage = {
      input_tokens: asNumber(tokenUsage.input_tokens),
      output_tokens: asNumber(tokenUsage.output_tokens),
      total_tokens: asNumber(tokenUsage.total_tokens),
    };
  }

  return event;
}

export function isTraceEventV1(input: unknown): input is ExecutionTraceEvent {
  const record = asRecord(input);
  return (
    record.type === "trace_event.v1" &&
    typeof record.run_id === "string" &&
    typeof record.stage === "string" &&
    typeof record.event_type === "string" &&
    typeof record.status === "string" &&
    typeof record.timestamp === "number"
  );
}

function addToIndexMap(
  target: Record<string, ExecutionTraceEvent[]>,
  key: string | null | undefined,
  event: ExecutionTraceEvent,
) {
  if (!key) {
    return;
  }
  const arr = target[key] ?? [];
  arr.push(event);
  target[key] = arr;
}

function dedupeAndSort(events: ExecutionTraceEvent[]): ExecutionTraceEvent[] {
  const byId = new Map<string, ExecutionTraceEvent>();
  const withoutId: ExecutionTraceEvent[] = [];
  for (const event of events) {
    if (event.id) {
      byId.set(event.id, event);
    } else {
      withoutId.push(event);
    }
  }
  const deduped = [...byId.values(), ...withoutId];
  deduped.sort((a, b) => {
    const aSeq = a.seq ?? Number.MAX_SAFE_INTEGER;
    const bSeq = b.seq ?? Number.MAX_SAFE_INTEGER;
    if (aSeq !== bSeq) return aSeq - bSeq;
    if (a.timestamp !== b.timestamp) return a.timestamp - b.timestamp;
    return (a.id ?? "").localeCompare(b.id ?? "");
  });
  return deduped;
}

function mergeTokenUsage(
  current: TraceTokenUsage,
  usage: TraceTokenUsage | undefined,
): TraceTokenUsage {
  if (!usage) {
    return current;
  }
  return {
    input_tokens: (current.input_tokens ?? 0) + (usage.input_tokens ?? 0),
    output_tokens: (current.output_tokens ?? 0) + (usage.output_tokens ?? 0),
    total_tokens: (current.total_tokens ?? 0) + (usage.total_tokens ?? 0),
  };
}

function normalizeRuns(state: ExecutionTraceState | undefined): Record<string, ExecutionTraceRun> {
  if (!state?.runs || typeof state.runs !== "object") {
    return {};
  }
  const normalized: Record<string, ExecutionTraceRun> = {};
  for (const [runId, runValue] of Object.entries(state.runs)) {
    const runRecord = asRecord(runValue);
    const runEventsRaw = Array.isArray(runRecord.events) ? runRecord.events : [];
    const runEvents = runEventsRaw
      .map((item) => normalizeEvent(item))
      .filter((item): item is ExecutionTraceEvent => item !== null);
    normalized[runId] = {
      run_id: runId,
      started_at: asNumber(runRecord.started_at),
      updated_at: asNumber(runRecord.updated_at),
      events: dedupeAndSort(runEvents),
    };
  }
  return normalized;
}

export function buildExecutionTraceIndex({
  persisted,
  liveEvents,
  currentRunId,
}: {
  persisted?: ExecutionTraceState;
  liveEvents?: ExecutionTraceEvent[];
  currentRunId?: string | null;
}): ExecutionTraceIndex {
  const runs = normalizeRuns(persisted);

  for (const event of liveEvents ?? []) {
    const normalized = normalizeEvent(event);
    if (!normalized) {
      continue;
    }
    const run = runs[normalized.run_id] ?? {
      run_id: normalized.run_id,
      events: [],
    };
    run.events = dedupeAndSort([...run.events, normalized]);
    run.updated_at = Math.max(run.updated_at ?? 0, normalized.timestamp);
    run.started_at = run.started_at ?? normalized.timestamp;
    runs[normalized.run_id] = run;
  }

  const runCandidates = Object.values(runs);
  const latestRun = currentRunId && runs[currentRunId]
    ? runs[currentRunId]
    : runCandidates.sort((a, b) => (b.updated_at ?? 0) - (a.updated_at ?? 0))[0];

  const allEvents = dedupeAndSort(
    runCandidates.flatMap((run) => run.events),
  );
  const byAssistantMessageId: Record<string, ExecutionTraceEvent[]> = {};
  const byTaskId: Record<string, ExecutionTraceEvent[]> = {};
  let aggregateTokenUsage: TraceTokenUsage = {};
  for (const event of allEvents) {
    addToIndexMap(byAssistantMessageId, event.assistant_message_id ?? event.turn_id, event);
    addToIndexMap(byTaskId, event.task_id, event);
    aggregateTokenUsage = mergeTokenUsage(aggregateTokenUsage, event.token_usage);
  }

  for (const value of Object.values(byAssistantMessageId)) {
    value.sort((a, b) => a.timestamp - b.timestamp);
  }
  for (const value of Object.values(byTaskId)) {
    value.sort((a, b) => a.timestamp - b.timestamp);
  }

  return {
    allEvents,
    byAssistantMessageId,
    byTaskId,
    runs,
    latestRunId: latestRun?.run_id,
    aggregateTokenUsage,
  };
}

export function asExecutionTraceState(input: unknown): ExecutionTraceState | undefined {
  const record = asRecord(input);
  const runs = record.runs;
  if (typeof runs !== "object" || runs === null || Array.isArray(runs)) {
    return undefined;
  }
  return {
    version: typeof record.version === "string" ? record.version : undefined,
    runs: runs as Record<string, ExecutionTraceRun>,
  };
}

