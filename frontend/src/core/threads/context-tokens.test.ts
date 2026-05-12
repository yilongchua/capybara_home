import assert from "node:assert/strict";
import test from "node:test";

const {
  buildInitialContextTokenState,
  reduceContextTokenState,
  resolveContextWindowFromModels,
  formatTokenCompact,
  extractLatestContextTokensFromTrace,
} = await import(new URL("./context-tokens.ts", import.meta.url).href);

void test("resolveContextWindowFromModels uses model metadata when present", () => {
  const result = resolveContextWindowFromModels(
    [{ name: "qwen3.6-local", context_window: 256000 }],
    "qwen3.6-local",
  );
  assert.deepEqual(result, { contextWindow: 256000, isApproximate: false });
});

void test("resolveContextWindowFromModels falls back when model context is missing", () => {
  const result = resolveContextWindowFromModels(
    [{ name: "qwen3.6-local", context_window: null }],
    "qwen3.6-local",
  );
  assert.equal(result.contextWindow, 128000);
  assert.equal(result.isApproximate, true);
});

void test("reduceContextTokenState handles context token growth and compaction reset", () => {
  let state = buildInitialContextTokenState({
    modelName: "qwen3.6-local",
    models: [{ name: "qwen3.6-local", context_window: 200000 }],
  });

  state = reduceContextTokenState(state, {
    type: "context_tokens",
    tokenCount: 90000,
  });
  assert.equal(state.currentTokens, 90000);
  assert.equal(state.maxTokens, 90000);
  assert.equal(state.percentage, 0.45);

  state = reduceContextTokenState(state, {
    type: "compaction",
  });
  assert.equal(state.maxTokens, 0);
  assert.equal(state.isCompacting, true);

  state = reduceContextTokenState(state, {
    type: "clear_compacting",
  });
  assert.equal(state.isCompacting, false);
});

void test("reduceContextTokenState recalculates percentage when context window changes", () => {
  let state = buildInitialContextTokenState({
    modelName: "qwen3.6-local",
    models: [{ name: "qwen3.6-local", context_window: 256000 }],
  });
  state = reduceContextTokenState(state, {
    type: "context_tokens",
    tokenCount: 64000,
  });
  state = reduceContextTokenState(state, {
    type: "set_context_window",
    contextWindow: 128000,
    isApproximate: true,
  });
  assert.equal(state.percentage, 0.5);
  assert.equal(state.isContextWindowApproximate, true);
});

void test("formatTokenCompact renders expected labels", () => {
  assert.equal(formatTokenCompact(1234), "~1K");
  assert.equal(formatTokenCompact(90240), "~90K");
  assert.equal(formatTokenCompact(2200000), "~2M");
});

void test("extractLatestContextTokensFromTrace returns most recent context token count", () => {
  const result = extractLatestContextTokensFromTrace({
    version: "v1",
    runs: {
      "run-1": {
        run_id: "run-1",
        events: [
          {
            run_id: "run-1",
            stage: "harness",
            event_type: "context_tokens",
            status: "info",
            timestamp: 100,
            seq: 1,
            payload: { token_count: 200, message_count: 2 },
          },
          {
            run_id: "run-1",
            stage: "harness",
            event_type: "context_tokens",
            status: "info",
            timestamp: 101,
            seq: 2,
            payload: { token_count: 450, message_count: 4 },
          },
        ],
      },
      "run-2": {
        run_id: "run-2",
        events: [
          {
            run_id: "run-2",
            stage: "harness",
            event_type: "context_tokens",
            status: "info",
            timestamp: 100.5,
            seq: 8,
            payload: { token_count: 300, message_count: 3 },
          },
        ],
      },
    },
  });

  assert.deepEqual(result, { tokenCount: 450, messageCount: 4 });
});
