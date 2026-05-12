import assert from "node:assert/strict";
import test from "node:test";

const {
  resolveAdjacentBranch,
  resolveBranchCursor,
  resolveForkDraft,
} = await import(new URL("./fork.ts", import.meta.url).href);

void test("resolveForkDraft returns null when checkpoint metadata is missing", () => {
  const draft = resolveForkDraft(
    {
      id: "m-1",
      type: "human",
      content: "Hello world",
    },
    undefined,
  );
  assert.equal(draft, null);
});

void test("resolveForkDraft strips thread_id from checkpoint and keeps source text", () => {
  const draft = resolveForkDraft(
    {
      id: "m-2",
      type: "human",
      content: [{ type: "text", text: "Update this paragraph" }],
      created_at: "2026-05-12T00:00:00.000Z",
    },
    {
      firstSeenState: {
        checkpoint: {
          thread_id: "thread-123",
          checkpoint_ns: "root",
          checkpoint_id: "cp-1",
          checkpoint_map: null,
        },
      },
      branch: "cp-0>cp-1",
      branchOptions: ["cp-0>cp-1", "cp-0>cp-2"],
    },
  );

  assert.ok(draft);
  assert.equal(draft.sourceMessageId, "m-2");
  assert.equal(draft.sourceMessageText, "Update this paragraph");
  assert.equal(draft.sourceBranch, "cp-0>cp-1");
  assert.deepEqual(draft.checkpoint, {
    checkpoint_ns: "root",
    checkpoint_id: "cp-1",
    checkpoint_map: null,
  });
});

void test("resolveBranchCursor defaults to first branch when current branch is missing", () => {
  const cursor = resolveBranchCursor(["a", "b", "c"], undefined);
  assert.deepEqual(cursor, { index: 0, total: 3 });
});

void test("resolveAdjacentBranch wraps in both directions", () => {
  const branches = ["branch-a", "branch-b", "branch-c"];
  assert.equal(
    resolveAdjacentBranch(branches, "branch-a", "prev"),
    "branch-c",
  );
  assert.equal(
    resolveAdjacentBranch(branches, "branch-c", "next"),
    "branch-a",
  );
});
