"use client";

import {
  QueryClient,
  type QueryKey,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

type StaticWorkspaceRefreshDomain =
  | "threads"
  | "runs"
  | "approvals"
  | "vault"
  | "integrations"
  | "agents"
  | "feedback";

export type WorkspaceRefreshDomain =
  | StaticWorkspaceRefreshDomain
  | `thread:${string}`
  | `uploads:${string}`
  | `dreamy:${string}`;

export type WorkspaceRefreshEvent = {
  id: string;
  domains: WorkspaceRefreshDomain[];
  at: number;
  meta?: Record<string, unknown>;
  originTabId: string;
};

type WorkspaceRefreshListener = (event: WorkspaceRefreshEvent) => void;

type WorkspaceRefreshSubscriptionOptions = {
  includeOwnEvents?: boolean;
};

type WorkspaceRefreshQueryOptions<
  TQueryFnData,
  TError = Error,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey,
> = UseQueryOptions<TQueryFnData, TError, TData, TQueryKey> & {
  refreshDomains?: WorkspaceRefreshDomain[];
  invalidateQueryKey?: QueryKey;
  invalidateExact?: boolean;
};

const STORAGE_KEY = "capybara:workspace-refresh";
const CHANNEL_NAME = "capybara-workspace-refresh";
const listeners = new Set<WorkspaceRefreshListener>();
let broadcastChannel: BroadcastChannel | null = null;
let listenersInitialized = false;
let tabId: string | null = null;

function getTabId(): string {
  if (tabId) {
    return tabId;
  }

  if (typeof window === "undefined") {
    tabId = "server";
    return tabId;
  }

  try {
    const existing = window.sessionStorage.getItem("capybara:workspace-tab-id");
    if (existing) {
      tabId = existing;
      return tabId;
    }
  } catch {
    // Ignore storage access failures and fall back to an in-memory ID.
  }

  tabId = `tab-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  try {
    window.sessionStorage.setItem("capybara:workspace-tab-id", tabId);
  } catch {
    // Ignore storage access failures.
  }
  return tabId;
}

function isWorkspaceRefreshEvent(value: unknown): value is WorkspaceRefreshEvent {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Partial<WorkspaceRefreshEvent>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.at === "number" &&
    typeof candidate.originTabId === "string" &&
    Array.isArray(candidate.domains)
  );
}

function notifyListeners(event: WorkspaceRefreshEvent) {
  for (const listener of listeners) {
    listener(event);
  }
}

function initWorkspaceRefreshListeners() {
  if (listenersInitialized || typeof window === "undefined") {
    return;
  }
  listenersInitialized = true;

  if ("BroadcastChannel" in window) {
    broadcastChannel = new BroadcastChannel(CHANNEL_NAME);
    broadcastChannel.addEventListener("message", (message) => {
      if (isWorkspaceRefreshEvent(message.data)) {
        notifyListeners(message.data);
      }
    });
  }

  window.addEventListener("storage", (event) => {
    if (event.key !== STORAGE_KEY || !event.newValue) {
      return;
    }
    try {
      const parsed = JSON.parse(event.newValue) as unknown;
      if (isWorkspaceRefreshEvent(parsed)) {
        notifyListeners(parsed);
      }
    } catch {
      // Ignore malformed storage events.
    }
  });
}

function uniqDomains(domains: WorkspaceRefreshDomain[]) {
  return Array.from(new Set(domains.filter(Boolean)));
}

function matchesRefreshDomains(
  eventDomains: WorkspaceRefreshDomain[],
  targetDomains: WorkspaceRefreshDomain[],
) {
  if (targetDomains.length === 0) {
    return true;
  }
  return targetDomains.some((domain) => eventDomains.includes(domain));
}

export function createWorkspaceQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        refetchOnReconnect: true,
        retry: 2,
        staleTime: 5_000,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export function publishWorkspaceRefresh(
  domains: WorkspaceRefreshDomain[],
  meta?: Record<string, unknown>,
) {
  if (typeof window === "undefined") {
    return;
  }

  const uniqueDomains = uniqDomains(domains);
  if (uniqueDomains.length === 0) {
    return;
  }

  initWorkspaceRefreshListeners();

  const event: WorkspaceRefreshEvent = {
    id: `refresh-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    at: Date.now(),
    domains: uniqueDomains,
    meta,
    originTabId: getTabId(),
  };

  notifyListeners(event);

  try {
    broadcastChannel?.postMessage(event);
  } catch {
    // Ignore broadcast failures and still fall back to storage.
  }

  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(event));
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore storage failures.
  }
}

export function subscribeWorkspaceRefresh(listener: WorkspaceRefreshListener) {
  initWorkspaceRefreshListeners();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useWorkspaceRefreshSubscription(
  domains: WorkspaceRefreshDomain[],
  handler: (event: WorkspaceRefreshEvent) => void,
  options?: WorkspaceRefreshSubscriptionOptions,
) {
  const domainKey = useMemo(
    () => uniqDomains(domains).sort().join("|"),
    [domains],
  );
  const includeOwnEvents = options?.includeOwnEvents ?? true;

  useEffect(() => {
    const targetDomains = domainKey
      ? (domainKey.split("|") as WorkspaceRefreshDomain[])
      : [];
    const currentTabId = getTabId();
    return subscribeWorkspaceRefresh((event) => {
      if (!includeOwnEvents && event.originTabId === currentTabId) {
        return;
      }
      if (!matchesRefreshDomains(event.domains, targetDomains)) {
        return;
      }
      handler(event);
    });
  }, [domainKey, handler, includeOwnEvents]);
}

export function useWorkspaceRefreshSignal(
  domains: WorkspaceRefreshDomain[],
  options?: WorkspaceRefreshSubscriptionOptions,
) {
  const [signal, setSignal] = useState(0);

  useWorkspaceRefreshSubscription(
    domains,
    () => {
      setSignal((value) => value + 1);
    },
    options,
  );

  return signal;
}

export function useWorkspaceReconcileSignal(
  domains: WorkspaceRefreshDomain[],
  options?: WorkspaceRefreshSubscriptionOptions,
) {
  const [signal, setSignal] = useState(0);

  useWorkspaceRefreshSubscription(
    domains,
    () => {
      setSignal((value) => value + 1);
    },
    options,
  );

  useEffect(() => {
    if (typeof window === "undefined" || typeof document === "undefined") {
      return;
    }

    const bump = () => {
      setSignal((value) => value + 1);
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        bump();
      }
    };

    window.addEventListener("focus", bump);
    window.addEventListener("online", bump);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("focus", bump);
      window.removeEventListener("online", bump);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  return signal;
}

export function useWorkspaceRefreshQuery<
  TQueryFnData,
  TError = Error,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey,
>(
  options: WorkspaceRefreshQueryOptions<TQueryFnData, TError, TData, TQueryKey>,
) {
  const queryClient = useQueryClient();
  const query = useQuery(options);
  const shouldSubscribe = (options.refreshDomains?.length ?? 0) > 0;

  useWorkspaceRefreshSubscription(
    shouldSubscribe ? options.refreshDomains ?? [] : [],
    () => {
      if (!shouldSubscribe || options.enabled === false) {
        return;
      }
      void queryClient.invalidateQueries({
        queryKey: options.invalidateQueryKey ?? options.queryKey,
        exact: options.invalidateExact ?? true,
      });
    });

  return query;
}
