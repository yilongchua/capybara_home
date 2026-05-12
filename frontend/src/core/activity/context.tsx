import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

import type { ActivityEvent } from "./types";

type ActivityContextValue = {
  liveEvents: ActivityEvent[];
  appendLiveEvent: (event: ActivityEvent) => void;
  appendLiveEvents: (events: ActivityEvent[]) => void;
  clear: () => void;
};

const ActivityContext = createContext<ActivityContextValue>({
  liveEvents: [],
  appendLiveEvent: () => {
    /* noop */
  },
  appendLiveEvents: () => {
    /* noop */
  },
  clear: () => {
    /* noop */
  },
});

export function ActivityProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [liveEvents, setLiveEvents] = useState<ActivityEvent[]>([]);

  const appendLiveEvents = useCallback((events: ActivityEvent[]) => {
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
      return next.slice(-300);
    });
  }, []);

  const appendLiveEvent = useCallback((event: ActivityEvent) => {
    appendLiveEvents([event]);
  }, [appendLiveEvents]);

  const clear = useCallback(() => {
    setLiveEvents((prev) => (prev.length === 0 ? prev : []));
  }, []);

  const value = useMemo(
    () => ({
      liveEvents,
      appendLiveEvent,
      appendLiveEvents,
      clear,
    }),
    [appendLiveEvent, appendLiveEvents, clear, liveEvents],
  );

  return (
    <ActivityContext.Provider value={value}>
      {children}
    </ActivityContext.Provider>
  );
}

export function useActivityContext() {
  return useContext(ActivityContext);
}
