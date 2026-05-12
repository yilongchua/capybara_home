"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Returns a generation counter that increments only when the thread ID
 * transitions TO "new" from a non-"new" route. Use this as a `key` prop
 * to force a full remount on new-chat navigation without interrupting
 * the "new" → actual-id URL transition during streaming.
 */
export function useThreadRemount(threadId: string): number {
  const prevThreadId = useRef(threadId);
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    if (threadId === "new" && prevThreadId.current !== "new") {
      setGeneration((g) => g + 1);
    }
    prevThreadId.current = threadId;
  }, [threadId]);

  return generation;
}
