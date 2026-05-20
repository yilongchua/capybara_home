import assert from "node:assert/strict";
import test from "node:test";

const {
  clearQueue,
  dequeueMatching,
  dequeueMessage,
  enqueueMessage,
  removeById,
  requeueFront,
  shouldEnqueueMessage,
  updateById,
} = await import(new URL("./queue.ts", import.meta.url).href);

void test("shouldEnqueueMessage submits immediately when idle", () => {
  assert.equal(
    shouldEnqueueMessage({
      queued: false,
      isLoading: false,
      isSubmitting: false,
      queueLength: 0,
    }),
    false,
  );
  assert.equal(
    shouldEnqueueMessage({
      queued: true,
      isLoading: false,
      isSubmitting: false,
      queueLength: 0,
    }),
    false,
  );
});

void test("shouldEnqueueMessage queues while busy or backlog exists", () => {
  assert.equal(
    shouldEnqueueMessage({
      queued: true,
      isLoading: true,
      isSubmitting: false,
      queueLength: 0,
    }),
    true,
  );
  assert.equal(
    shouldEnqueueMessage({
      isLoading: false,
      isSubmitting: true,
      queueLength: 0,
    }),
    true,
  );
  assert.equal(
    shouldEnqueueMessage({
      isLoading: false,
      isSubmitting: false,
      queueLength: 2,
    }),
    true,
  );
});

void test("enqueueMessage appends FIFO", () => {
  const q1 = enqueueMessage([], 1);
  const q2 = enqueueMessage(q1, 2);
  const q3 = enqueueMessage(q2, 3);
  assert.deepEqual(q3, [1, 2, 3]);
});

void test("dequeueMessage pops from front", () => {
  const { next, remaining } = dequeueMessage([1, 2, 3]);
  assert.equal(next, 1);
  assert.deepEqual(remaining, [2, 3]);
});

void test("requeueFront places failed item back first", () => {
  const recovered = requeueFront([2, 3], 1);
  assert.deepEqual(recovered, [1, 2, 3]);
});

void test("clearQueue drops all pending items", () => {
  const cleared = clearQueue();
  assert.deepEqual(cleared, []);
});

void test("dequeueMatching pops first item that passes predicate", () => {
  const { next, remaining, index } = dequeueMatching(
    [
      { id: "1", kind: "hold" },
      { id: "2", kind: "send" },
      { id: "3", kind: "send" },
    ],
    (item) => item.kind === "send",
  );
  assert.equal(index, 1);
  assert.deepEqual(next, { id: "2", kind: "send" });
  assert.deepEqual(remaining, [
    { id: "1", kind: "hold" },
    { id: "3", kind: "send" },
  ]);
});

void test("removeById removes targeted queue item", () => {
  const { removed, remaining } = removeById(
    [
      { id: "1", value: "a" },
      { id: "2", value: "b" },
    ],
    "2",
  );
  assert.deepEqual(removed, { id: "2", value: "b" });
  assert.deepEqual(remaining, [{ id: "1", value: "a" }]);
});

void test("updateById updates targeted queue item", () => {
  const updated = updateById(
    [
      { id: "1", count: 0 },
      { id: "2", count: 0 },
    ],
    "2",
    (item) => ({ ...item, count: item.count + 1 }),
  );
  assert.deepEqual(updated, [
    { id: "1", count: 0 },
    { id: "2", count: 1 },
  ]);
});
