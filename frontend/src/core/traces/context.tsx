import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

import type { ExecutionTraceEvent } from "./types";

type ExecutionTraceContextValue = {
  liveEvents: ExecutionTraceEvent[];
  currentRunId: string | null;
  appendLiveEvent: (event: ExecutionTraceEvent) => void;
  appendLiveEvents: (events: ExecutionTraceEvent[]) => void;
  setCurrentRunId: (runId: string | null) => void;
  clear: () => void;
};

const ExecutionTraceContext = createContext<ExecutionTraceContextValue>({
  liveEvents: [],
  currentRunId: null,
  appendLiveEvent: () => {
    /* noop */
  },
  appendLiveEvents: () => {
    /* noop */
  },
  setCurrentRunId: () => {
    /* noop */
  },
  clear: () => {
    /* noop */
  },
});

export function ExecutionTraceProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [liveEvents, setLiveEvents] = useState<ExecutionTraceEvent[]>([]);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);

  const appendLiveEvents = useCallback((events: ExecutionTraceEvent[]) => {
    if (events.length === 0) {
      return;
    }
    setLiveEvents((prev) => {
      let next = prev;
      for (const event of events) {
        const eventId = event.id;
        if (eventId && next.some((candidate) => candidate.id === eventId)) {
          next = next.map((candidate) =>
            candidate.id === eventId ? event : candidate,
          );
          continue;
        }
        next = [...next, event];
      }
      return next.slice(-80);
    });
  }, []);

  const appendLiveEvent = useCallback((event: ExecutionTraceEvent) => {
    appendLiveEvents([event]);
  }, [appendLiveEvents]);

  const clear = useCallback(() => {
    setLiveEvents([]);
    setCurrentRunId(null);
  }, []);

  const value = useMemo(
    () => ({
      liveEvents,
      currentRunId,
      appendLiveEvent,
      appendLiveEvents,
      setCurrentRunId,
      clear,
    }),
    [appendLiveEvent, appendLiveEvents, clear, currentRunId, liveEvents],
  );

  return (
    <ExecutionTraceContext.Provider value={value}>
      {children}
    </ExecutionTraceContext.Provider>
  );
}

export function useExecutionTraceContext() {
  return useContext(ExecutionTraceContext);
}
