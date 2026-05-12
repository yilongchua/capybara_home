export type QueueDecisionInput = {
  queued?: boolean;
  isLoading: boolean;
  isSubmitting: boolean;
  queueLength: number;
};

export function shouldEnqueueMessage(input: QueueDecisionInput): boolean {
  void input;
  return true;
}

export function enqueueMessage<T>(queue: T[], item: T): T[] {
  return [...queue, item];
}

export function dequeueMessage<T>(queue: T[]): { next: T | null; remaining: T[] } {
  if (queue.length === 0) {
    return { next: null, remaining: [] };
  }
  return { next: queue[0] ?? null, remaining: queue.slice(1) };
}

export function dequeueMatching<T>(
  queue: T[],
  predicate: (item: T) => boolean,
): { next: T | null; remaining: T[]; index: number } {
  const index = queue.findIndex(predicate);
  if (index < 0) {
    return { next: null, remaining: queue, index: -1 };
  }
  const next = queue[index] ?? null;
  if (!next) {
    return { next: null, remaining: queue, index: -1 };
  }
  return {
    next,
    remaining: [...queue.slice(0, index), ...queue.slice(index + 1)],
    index,
  };
}

export function removeById<T extends { id: string }>(
  queue: T[],
  id: string,
): { removed: T | null; remaining: T[] } {
  const index = queue.findIndex((item) => item.id === id);
  if (index < 0) {
    return { removed: null, remaining: queue };
  }
  const removed = queue[index] ?? null;
  if (!removed) {
    return { removed: null, remaining: queue };
  }
  return {
    removed,
    remaining: [...queue.slice(0, index), ...queue.slice(index + 1)],
  };
}

export function updateById<T extends { id: string }>(
  queue: T[],
  id: string,
  updater: (item: T) => T,
): T[] {
  let changed = false;
  const next = queue.map((item) => {
    if (item.id !== id) return item;
    changed = true;
    return updater(item);
  });
  return changed ? next : queue;
}

export function requeueFront<T>(queue: T[], item: T): T[] {
  return [item, ...queue];
}

export function clearQueue<T>(): T[] {
  return [];
}
