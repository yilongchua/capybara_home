"use client";

import { Client as LangGraphClient } from "@langchain/langgraph-sdk/client";

import { getLangGraphBaseURL } from "../config";

import { sanitizeRunStreamOptions } from "./stream-mode";

// Deduplication map for SSE stream connections.
//
// Keys:
//   "{threadId}::{runId}"  — joinStream (join an existing run by runId)
//   "{threadId}::thread"   — runs.stream (thread-level subscription, new run)
//
// Each entry holds a tee'd AsyncIterable that fans out from a single underlying
// connection to N concurrent consumers. This prevents duplicate SSE connections
// when React Strict Mode double-mounts, hot reload, or simultaneous thread-level
// and run-level subscribers are active for the same thread.
// See thread-d2774293 audit Finding #4 (4 connections, ~57 MB SSE data).
type StreamTee = {
  iterable: AsyncIterable<unknown>;
  refCount: number;
  cleanup: () => void;
};
const _activeJoinStreams = new Map<string, StreamTee>();

type HistoryCacheEntry = {
  expiresAt: number;
  data?: unknown;
  inflight?: Promise<unknown>;
};

const HISTORY_CACHE_TTL_MS = 8_000;
const _threadHistoryCache = new Map<string, HistoryCacheEntry>();

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  const pairs = keys.map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`);
  return `{${pairs.join(",")}}`;
}

function historyCacheKey(threadId: string, options?: unknown): string {
  return `${threadId}::${stableStringify(options ?? {})}`;
}

export function clearThreadClientCache(threadId: string): void {
  const prefix = `${threadId}::`;
  for (const key of _threadHistoryCache.keys()) {
    if (key.startsWith(prefix)) {
      _threadHistoryCache.delete(key);
    }
  }
}

function teeJoinStream<T>(
  source: AsyncIterable<T>,
  key: string,
): AsyncIterable<T> {
  // Multi-consumer tee: each consumer gets its own queue, the source is read
  // once and fans out. When all consumers stop iterating, the entry is GC'd.
  const consumers: Array<{
    queue: T[];
    notify: ((value: IteratorResult<T>) => void) | null;
    closed: boolean;
  }> = [];
  let sourceDone = false;

  void (async () => {
    try {
      for await (const chunk of source) {
        for (const c of consumers) {
          if (c.closed) continue;
          if (c.notify) {
            const fn = c.notify;
            c.notify = null;
            fn({ value: chunk, done: false });
          } else {
            c.queue.push(chunk);
          }
        }
      }
    } finally {
      sourceDone = true;
      for (const c of consumers) {
        if (c.notify) c.notify({ value: undefined as never, done: true });
      }
      _activeJoinStreams.delete(key);
    }
  })();

  return {
    [Symbol.asyncIterator](): AsyncIterator<T> {
      const consumer = { queue: [] as T[], notify: null as ((value: IteratorResult<T>) => void) | null, closed: false };
      consumers.push(consumer);
      return {
        async next(): Promise<IteratorResult<T>> {
          if (consumer.queue.length > 0) {
            return { value: consumer.queue.shift() as T, done: false };
          }
          if (sourceDone) return { value: undefined as never, done: true };
          return new Promise<IteratorResult<T>>((resolve) => {
            consumer.notify = resolve;
          });
        },
        async return(): Promise<IteratorResult<T>> {
          consumer.closed = true;
          return { value: undefined as never, done: true };
        },
      };
    },
  };
}

function createCompatibleClient(isMock?: boolean): LangGraphClient {
  const client = new LangGraphClient({
    apiUrl: getLangGraphBaseURL(isMock),
  });

  const originalGetHistory = client.threads.getHistory.bind(client.threads);
  client.threads.getHistory = (async (threadId, options) => {
    const cacheKey = historyCacheKey(String(threadId), options);
    const now = Date.now();
    const cached = _threadHistoryCache.get(cacheKey);
    if (cached?.data !== undefined && cached.expiresAt > now) {
      return cached.data as Awaited<ReturnType<typeof originalGetHistory>>;
    }
    if (cached?.inflight) {
      return await cached.inflight;
    }

    const inflight = originalGetHistory(threadId, options)
      .then((result) => {
        _threadHistoryCache.set(cacheKey, {
          data: result,
          expiresAt: Date.now() + HISTORY_CACHE_TTL_MS,
        });
        return result;
      })
      .catch((error) => {
        _threadHistoryCache.delete(cacheKey);
        throw error;
      });

    _threadHistoryCache.set(cacheKey, {
      expiresAt: now + HISTORY_CACHE_TTL_MS,
      inflight,
    });
    return await inflight;
  }) as typeof client.threads.getHistory;

  const originalUpdateState = client.threads.updateState.bind(client.threads);
  client.threads.updateState = (async (threadId, options) => {
    const result = await originalUpdateState(threadId, options);
    clearThreadClientCache(String(threadId));
    return result;
  }) as typeof client.threads.updateState;

  const originalDeleteThread = client.threads.delete.bind(client.threads);
  client.threads.delete = (async (threadId, options) => {
    const result = await originalDeleteThread(threadId, options);
    clearThreadClientCache(String(threadId));
    return result;
  }) as typeof client.threads.delete;

  const originalRunStream = client.runs.stream.bind(client.runs);
  client.runs.stream = ((threadId, assistantId, payload) => {
    // Dedup concurrent thread-level stream subscriptions for the same thread.
    // React Strict Mode double-mounts and hot-reload can trigger simultaneous
    // `runs.stream` calls for the same thread, each opening a separate SSE
    // connection and creating duplicate backend runs.
    const key = `${String(threadId)}::thread`;
    const existing = _activeJoinStreams.get(key);
    if (existing) {
      existing.refCount += 1;
      return existing.iterable as ReturnType<typeof originalRunStream>;
    }
    clearThreadClientCache(String(threadId));
    const source = originalRunStream(
      threadId,
      assistantId,
      sanitizeRunStreamOptions(payload),
    ) as AsyncIterable<unknown>;
    const teed = teeJoinStream(source, key);
    _activeJoinStreams.set(key, {
      iterable: teed,
      refCount: 1,
      cleanup: () => _activeJoinStreams.delete(key),
    });
    return teed as ReturnType<typeof originalRunStream>;
  }) as typeof client.runs.stream;

  const originalJoinStream = client.runs.joinStream.bind(client.runs);
  client.runs.joinStream = ((threadId, runId, options) => {
    const key = `${String(threadId)}::${String(runId)}`;
    const existing = _activeJoinStreams.get(key);
    if (existing) {
      existing.refCount += 1;
      return existing.iterable as ReturnType<typeof originalJoinStream>;
    }
    clearThreadClientCache(String(threadId));
    const source = originalJoinStream(
      threadId,
      runId,
      sanitizeRunStreamOptions(options),
    ) as AsyncIterable<unknown>;
    const teed = teeJoinStream(source, key);
    _activeJoinStreams.set(key, {
      iterable: teed,
      refCount: 1,
      cleanup: () => _activeJoinStreams.delete(key),
    });
    return teed as ReturnType<typeof originalJoinStream>;
  }) as typeof client.runs.joinStream;

  return client;
}

let _singleton: LangGraphClient | null = null;
export function getAPIClient(isMock?: boolean): LangGraphClient {
  _singleton ??= createCompatibleClient(isMock);
  return _singleton;
}
