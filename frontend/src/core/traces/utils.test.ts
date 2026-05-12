import assert from "node:assert/strict";
import test from "node:test";

const { buildExecutionTraceIndex, isTraceEventV1 } = await import(
  new URL("./utils.ts", import.meta.url).href
);

void test("detects trace_event.v1 payloads", () => {
  const payload = {
    type: "trace_event.v1",
    run_id: "run-1",
    stage: "lead",
    event_type: "model_response",
    status: "completed",
    timestamp: 100,
  };
  assert.equal(isTraceEventV1(payload), true);
});

void test("detects trace_event.v1 payloads for context token events", () => {
  const payload = {
    type: "trace_event.v1",
    run_id: "run-ctx",
    stage: "harness",
    event_type: "context_tokens",
    status: "info",
    timestamp: 200,
    payload: {
      token_count: 12345,
      message_count: 40,
    },
  };
  assert.equal(isTraceEventV1(payload), true);
});

void test("merges persisted and live trace events with dedupe + indexing", () => {
  const persisted = {
    version: "v1",
    runs: {
      "run-1": {
        run_id: "run-1",
        started_at: 1,
        updated_at: 2,
        events: [
          {
            id: "run-1:1",
            run_id: "run-1",
            stage: "lead",
            event_type: "model_response",
            status: "running",
            timestamp: 2,
            seq: 1,
            assistant_message_id: "ai-1",
          },
        ],
      },
    },
  };

  const live = [
    {
      id: "run-1:1",
      run_id: "run-1",
      stage: "lead",
      event_type: "model_response",
      status: "completed",
      timestamp: 2,
      seq: 1,
      assistant_message_id: "ai-1",
    },
    {
      id: "run-1:2",
      run_id: "run-1",
      stage: "subagent",
      event_type: "task_running",
      status: "running",
      timestamp: 3,
      seq: 2,
      task_id: "task-1",
      token_usage: { total_tokens: 15 },
    },
  ];

  const index = buildExecutionTraceIndex({
    persisted,
    liveEvents: live,
    currentRunId: "run-1",
  });

  assert.equal(index.latestRunId, "run-1");
  assert.equal(index.allEvents.length, 2);
  assert.equal(index.byAssistantMessageId["ai-1"]?.length, 1);
  assert.equal(index.byTaskId["task-1"]?.length, 1);
  assert.equal(index.byAssistantMessageId["ai-1"]?.[0]?.status, "completed");
  assert.equal(index.aggregateTokenUsage.total_tokens, 15);
});
