import type { AIMessage, Checkpoint, Message } from "@langchain/langgraph-sdk";
import type { ThreadsClient } from "@langchain/langgraph-sdk/client";
import { useStream } from "@langchain/langgraph-sdk/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { toast } from "sonner";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import {
  isActivityEventV1,
  normalizeActivityEvent,
  useActivityContext,
} from "@/core/activity";
import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/dreamy/api";
import { uuid } from "@/core/utils/uuid";

import { getAPIClient } from "../api";
import { useI18n } from "../i18n/hooks";
import type { FileInMessage } from "../messages/utils";
import type { LocalSettings } from "../settings";
import { useUpdateSubtask } from "../tasks/context";
import type { ExecutionTraceEvent } from "../traces";
import { isTraceEventV1, useExecutionTraceContext } from "../traces";
import type { UploadedFileInfo } from "../uploads";
import { uploadFiles } from "../uploads";
import {
  publishWorkspaceRefresh,
  type WorkspaceRefreshDomain,
  useWorkspaceRefreshQuery,
} from "../workspace-refresh";

import {
  deleteAllThreads as deleteAllThreadsWithCleanup,
  deleteThread as deleteThreadWithCleanup,
} from "./api";
import {
  clearQueue as clearQueueState,
  dequeueMatching,
  enqueueMessage,
  removeById,
  requeueFront,
  shouldEnqueueMessage,
  updateById,
} from "./queue";
import type { AgentThread, AgentThreadState, PlanState } from "./types";

export type ToolEndEvent = {
  name: string;
  data: unknown;
};

export type PlanCreatedEvent = {
  type: "plan_created";
  plan_id?: string;
  status?: string;
  title: string;
  summary: string;
  domain: string;
  todo_count: number;
  first_todos: string[];
  plan_path: string | null;
};

export type PhaseStartedEvent = {
  type: "phase_started";
  todo_id: string;
  content: string;
  subagent_type?: string | null;
  phase_index: number;
  total_phases: number;
};

export type PhaseCompletedEvent = {
  type: "phase_completed";
  todo_id: string;
  content: string;
  phase_index: number;
  completed_at: string;
};

export type PlanAdaptedEvent = {
  type: "plan_adapted";
  blocked_ids: string[];
  message: string;
  adaptation_attempt?: number;
  max_attempts?: number;
};

export type ComplexityEscalationEvent = {
  type: "complexity_escalation";
  complexity_tier: string;
  recommended_action: string;
  message: string;
};

export type ThreadStreamOptions = {
  threadId?: string | null | undefined;
  context: LocalSettings["context"];
  isMock?: boolean;
  onStart?: (threadId: string) => void;
  onFinish?: (state: AgentThreadState) => void;
  onToolEnd?: (event: ToolEndEvent) => void;
  onContextTokens?: (event: { tokenCount: number; messageCount?: number }) => void;
  onCompaction?: (event: { messagesCompressed?: number; messagesKept?: number }) => void;
  onPlanningStarted?: () => void;
  onPlanCreated?: (event: PlanCreatedEvent) => void;
  onPhaseStarted?: (event: PhaseStartedEvent) => void;
  onPhaseCompleted?: (event: PhaseCompletedEvent) => void;
  onPlanAdapted?: (event: PlanAdaptedEvent) => void;
  onComplexityEscalation?: (event: ComplexityEscalationEvent) => void;
};

export type SendMessageOptions = {
  planMode?: boolean;
  queued?: boolean;
  mode?: "work" | "plan";
  checkpoint?: Omit<Checkpoint, "thread_id">;
  forkSourceMessageId?: string;
  forkSourceBranch?: string;
};

type QueuedMessage = {
  id: string;
  createdAt: number;
  threadId: string;
  message: PromptInputMessage;
  extraContext?: Record<string, unknown>;
  options?: SendMessageOptions;
  allowSteer: boolean;
  steerIntent?: {
    intentId: string;
    status: "pending" | "retrying" | "failed";
    failureCount: number;
  };
};

export type ThreadQueueItem = {
  id: string;
  text: string;
  createdAt: number;
  steerEnabled: boolean;
  steerStatus: "none" | "pending" | "retrying" | "failed";
};

export type ThreadQueueControls = {
  queueLength: number;
  queueItems: ThreadQueueItem[];
  steerQueued: (itemId: string) => Promise<void>;
  dismissQueued: (itemId: string) => void;
  clearQueue: () => void;
  stop: () => Promise<void>;
};

/** Converts FileUIPart blob URLs into native File objects, ready for upload. */
async function resolveFilesForUpload(
  files: NonNullable<PromptInputMessage["files"]>,
): Promise<File[]> {
  const filePromises = files.map(async (fileUIPart) => {
    if (!fileUIPart.url || !fileUIPart.filename) return null;
    try {
      const response = await fetch(fileUIPart.url);
      const blob = await response.blob();
      return new File([blob], fileUIPart.filename, {
        type: fileUIPart.mediaType || blob.type,
      });
    } catch (error) {
      console.error(`Failed to fetch file ${fileUIPart.filename}:`, error);
      return null;
    }
  });

  const results = await Promise.all(filePromises);
  const resolved = results.filter((f): f is File => f !== null);
  const failedCount = results.length - resolved.length;
  if (failedCount > 0) {
    throw new Error(
      `Failed to prepare ${failedCount} attachment(s) for upload. Please retry.`,
    );
  }
  return resolved;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, unknown>;
}

function publishThreadRefresh(
  threadId: string,
  extraDomains: WorkspaceRefreshDomain[] = [],
) {
  publishWorkspaceRefresh(
    [
      "threads",
      `thread:${threadId}`,
      ...extraDomains,
    ] as const,
    { source: "thread-stream" },
  );
}

function extractSteeringError(raw: string): { detail: string; status?: string } {
  const trimmed = raw.trim();
  if (!trimmed) {
    return { detail: "Unknown steering error." };
  }
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (typeof parsed === "object" && parsed !== null) {
      if ("detail" in parsed) {
        const detailRaw = (parsed as { detail?: unknown }).detail;
        if (typeof detailRaw === "string" && detailRaw.trim()) {
          return { detail: detailRaw.trim() };
        }
        if (typeof detailRaw === "object" && detailRaw !== null) {
          const detail = (detailRaw as { detail?: unknown }).detail;
          const status = (detailRaw as { status?: unknown }).status;
          if (typeof detail === "string" && detail.trim()) {
            return {
              detail: detail.trim(),
              status: typeof status === "string" ? status : undefined,
            };
          }
        }
      }
    }
  } catch {
    // Non-JSON response body; fall through to raw text.
  }
  return { detail: trimmed };
}

function isRetryableSteeringConflict(status: number, detail: string, failureStatus?: string): boolean {
  if (failureStatus === "conflict" && status === 423) {
    return true;
  }
  if (status === 409 || status === 423) {
    const normalized = detail.toLowerCase();
    return normalized.includes("in-flight runs") || normalized.includes("no tasks in progress") || normalized.includes("temporarily locked");
  }
  return false;
}

function isRetryableSubmitConflictError(error: unknown): boolean {
  const message =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : JSON.stringify(error);
  const normalized = message.toLowerCase();

  const asAny = error as {
    status?: unknown;
    statusCode?: unknown;
    response?: { status?: unknown };
  };
  const status = typeof asAny?.status === "number"
    ? asAny.status
    : typeof asAny?.statusCode === "number"
      ? asAny.statusCode
      : typeof asAny?.response?.status === "number"
        ? asAny.response.status
        : null;

  const hasConflictStatus =
    status === 409 ||
    status === 423 ||
    normalized.includes("http 409") ||
    normalized.includes("http 423");
  if (!hasConflictStatus) {
    return false;
  }

  return (
    normalized.includes("in-flight runs") ||
    normalized.includes("temporarily locked") ||
    normalized.includes("no tasks in progress")
  );
}

export function useThreadStream({
  threadId,
  context,
  isMock,
  onStart,
  onFinish,
  onToolEnd,
  onContextTokens,
  onCompaction,
  onPlanningStarted,
  onPlanCreated,
  onPhaseStarted,
  onPhaseCompleted,
  onPlanAdapted,
  onComplexityEscalation,
}: ThreadStreamOptions) {
  const { t } = useI18n();
  // Track the thread ID that is currently streaming to handle thread changes during streaming
  const [onStreamThreadId, setOnStreamThreadId] = useState(() => threadId);
  // Ref to track current thread ID across async callbacks without causing re-renders,
  // and to allow access to the current thread id in onUpdateEvent
  const threadIdRef = useRef<string | null>(threadId ?? null);
  const startedRef = useRef(false);
  const [messageQueue, setMessageQueue] = useState<QueuedMessage[]>([]);
  const queueRef = useRef<QueuedMessage[]>([]);
  const isSubmittingRef = useRef(false);
  const isDequeuingRef = useRef(false);
  const activeSteerRequestRef = useRef<Set<string>>(new Set());
  const steeringLockUntilRef = useRef<Map<string, number>>(new Map());
  const steerRetryTimeoutRef = useRef<number | null>(null);
  const queueRetryTimeoutRef = useRef<number | null>(null);
  const retrySteerRef = useRef<() => Promise<void>>(() => Promise.resolve());
  const processQueueRef = useRef<() => void>(() => undefined);

  const listeners = useRef({
    onStart,
    onFinish,
    onToolEnd,
    onContextTokens,
    onCompaction,
    onPlanningStarted,
    onPlanCreated,
    onPhaseStarted,
    onPhaseCompleted,
    onPlanAdapted,
    onComplexityEscalation,
  });

  // Keep listeners ref updated with latest callbacks
  useEffect(() => {
    listeners.current = {
      onStart,
      onFinish,
      onToolEnd,
      onContextTokens,
      onCompaction,
      onPlanningStarted,
      onPlanCreated,
      onPhaseStarted,
      onPhaseCompleted,
      onPlanAdapted,
      onComplexityEscalation,
    };
  }, [onStart, onFinish, onToolEnd, onContextTokens, onCompaction, onPlanningStarted, onPlanCreated, onPhaseStarted, onPhaseCompleted, onPlanAdapted, onComplexityEscalation]);

  useEffect(() => {
    queueRef.current = messageQueue;
  }, [messageQueue]);

  useEffect(() => {
    const normalizedThreadId = threadId ?? null;
    if (!normalizedThreadId) {
      // Just reset for new thread creation when threadId becomes null/undefined
      startedRef.current = false;
      setOnStreamThreadId(normalizedThreadId);
    }
    threadIdRef.current = normalizedThreadId;
  }, [threadId]);

  const _handleOnStart = useCallback((id: string) => {
    if (!startedRef.current) {
      listeners.current.onStart?.(id);
      startedRef.current = true;
    }
  }, []);

  const handleStreamStart = useCallback(
    (_threadId: string) => {
      threadIdRef.current = _threadId;
      _handleOnStart(_threadId);
    },
    [_handleOnStart],
  );

  const clearQueue = useCallback(() => {
    const empty = clearQueueState<QueuedMessage>();
    queueRef.current = empty;
    setMessageQueue(empty);
  }, []);

  const applyQueue = useCallback((nextQueue: QueuedMessage[]) => {
    queueRef.current = nextQueue;
    setMessageQueue(nextQueue);
  }, []);

  const clearScheduledSteerRetry = useCallback(() => {
    if (steerRetryTimeoutRef.current !== null) {
      window.clearTimeout(steerRetryTimeoutRef.current);
      steerRetryTimeoutRef.current = null;
    }
  }, []);

  const clearScheduledQueueRetry = useCallback(() => {
    if (queueRetryTimeoutRef.current !== null) {
      window.clearTimeout(queueRetryTimeoutRef.current);
      queueRetryTimeoutRef.current = null;
    }
  }, []);

  const scheduleSteerRetry = useCallback(
    (delayMs: number) => {
      clearScheduledSteerRetry();
      steerRetryTimeoutRef.current = window.setTimeout(() => {
        steerRetryTimeoutRef.current = null;
        void retrySteerRef.current();
      }, delayMs);
    },
    [clearScheduledSteerRetry],
  );

  useEffect(
    () => () => {
      clearScheduledSteerRetry();
      clearScheduledQueueRetry();
    },
    [clearScheduledQueueRetry, clearScheduledSteerRetry],
  );

  const queryClient = useQueryClient();
  const updateSubtask = useUpdateSubtask();
  const { appendLiveEvents: appendTraceLiveEvents, setCurrentRunId, clear: clearTraceLiveEvents } = useExecutionTraceContext();
  const {
    appendLiveEvent: appendActivityLiveEvent,
    clear: clearActivityLiveEvents,
  } = useActivityContext();
  const syntheticSeqRef = useRef(0);
  const syntheticActivitySeqRef = useRef(0);
  const currentRunIdRef = useRef<string | null>(null);
  const pendingTraceEventsRef = useRef<ExecutionTraceEvent[]>([]);
  const flushTimerRef = useRef<number | null>(null);
  const fetchStateHistory = true;
  const thinkingSignalEmittedRef = useRef(false);

  useEffect(() => {
    // Live activity/trace buffers are global provider state; clear them when
    // switching threads so one chat never shows another chat's running signals.
    clearActivityLiveEvents();
    clearTraceLiveEvents();
    currentRunIdRef.current = null;
    dispatchThinking({ type: "reset" });
    thinkingSignalEmittedRef.current = false;
  }, [clearActivityLiveEvents, clearTraceLiveEvents, threadId]);

  // Accumulates streamed thinking/reasoning tokens for the current run.
  // Reset to "" when a new message is submitted. Exposed as liveThinkingContent.
  const [liveThinkingContent, dispatchThinking] = useReducer(
    (prev: string, action: { type: "append"; chunk: string } | { type: "reset" }) =>
      action.type === "reset" ? "" : prev + action.chunk,
    "",
  );

  const flushPendingTraceEvents = useCallback(() => {
    if (flushTimerRef.current !== null) {
      window.clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    const pending = pendingTraceEventsRef.current;
    if (pending.length === 0) {
      return;
    }
    pendingTraceEventsRef.current = [];
    appendTraceLiveEvents(pending);
  }, [appendTraceLiveEvents]);

  const enqueueTraceEvent = useCallback(
    (event: ExecutionTraceEvent) => {
      pendingTraceEventsRef.current.push(event);
      if (flushTimerRef.current !== null) {
        return;
      }
      flushTimerRef.current = window.setTimeout(() => {
        flushPendingTraceEvents();
      }, 120);
    },
    [flushPendingTraceEvents],
  );

  const appendSyntheticTrace = useCallback(
    (partial: Partial<ExecutionTraceEvent> & { event_type: string }) => {
      syntheticSeqRef.current += 1;
      const runId = partial.run_id ?? currentRunIdRef.current ?? "run-unknown";
      enqueueTraceEvent({
        run_id: runId,
        stage: partial.stage ?? "harness",
        status: partial.status ?? "info",
        event_type: partial.event_type,
        timestamp: partial.timestamp ?? Date.now() / 1000,
        seq: partial.seq ?? syntheticSeqRef.current,
        payload: partial.payload,
        thinking: partial.thinking,
        token_usage: partial.token_usage,
        task_id: partial.task_id,
        turn_id: partial.turn_id,
        assistant_message_id: partial.assistant_message_id,
        id:
          partial.id ??
          `synthetic:${runId}:${partial.event_type}:${syntheticSeqRef.current}`,
      });
    },
    [enqueueTraceEvent],
  );

  // ── Custom event handlers (one per event type) ───────────────────────────

  const handleTraceEventV1 = useCallback(
    (event: ExecutionTraceEvent) => {
      enqueueTraceEvent(event);
      currentRunIdRef.current = event.run_id;
      setCurrentRunId(event.run_id);
      const payload = asRecord(event.payload);
      if (event.event_type === "context_tokens") {
        const tokenCount = payload?.token_count;
        const messageCount = payload?.message_count;
        if (typeof tokenCount === "number" && Number.isFinite(tokenCount)) {
          listeners.current.onContextTokens?.({
            tokenCount,
            messageCount:
              typeof messageCount === "number" && Number.isFinite(messageCount)
                ? messageCount
                : undefined,
          });
        }
      } else if (event.event_type === "compaction") {
        const messagesCompressed = payload?.messages_compressed;
        const messagesKept = payload?.messages_kept;
        listeners.current.onCompaction?.({
          messagesCompressed:
            typeof messagesCompressed === "number" && Number.isFinite(messagesCompressed)
              ? messagesCompressed
              : undefined,
          messagesKept:
            typeof messagesKept === "number" && Number.isFinite(messagesKept)
              ? messagesKept
              : undefined,
        });
      }
    },
    [enqueueTraceEvent, setCurrentRunId],
  );

  const handleActivityEventV1 = useCallback(
    (event: unknown) => {
      const normalized = normalizeActivityEvent(event);
      if (!normalized) {
        return;
      }
      appendActivityLiveEvent(normalized);
    },
    [appendActivityLiveEvent],
  );

  const handleTitleUpdate = useCallback(
    (event: { type: "title_update"; title: string; thread_id: string }) => {
      void queryClient.setQueriesData(
        { queryKey: ["threads", "search"], exact: false },
        (oldData: AgentThread[] | undefined) =>
          oldData?.map((t) =>
            t.thread_id === event.thread_id
              ? { ...t, values: { ...t.values, title: event.title } }
              : t,
          ),
      );
      publishThreadRefresh(event.thread_id);
    },
    [queryClient],
  );

  const handleThinkingChunk = useCallback(
    (event: { type: "thinking_chunk"; content: string }) => {
      if (typeof event.content === "string" && event.content) {
        if (!thinkingSignalEmittedRef.current) {
          thinkingSignalEmittedRef.current = true;
          syntheticActivitySeqRef.current += 1;
          appendActivityLiveEvent({
            id: `synthetic-activity:capybara-thinking:${syntheticActivitySeqRef.current}`,
            run_id: currentRunIdRef.current ?? "run-unknown",
            seq: syntheticActivitySeqRef.current,
            timestamp: Date.now() / 1000,
            actor: "capybara",
            kind: "thinking",
            line: "Capybara is thinking...",
          });
        }
        dispatchThinking({ type: "append", chunk: event.content });
      }
    },
    [appendActivityLiveEvent, dispatchThinking],
  );

  const handleCompaction = useCallback(
    (event: { type: "compaction"; messages_compressed?: number }) => {
      toast.info(
        `Context compressed${typeof event.messages_compressed === "number" ? ` (${event.messages_compressed} messages)` : ""}`,
      );
    },
    [],
  );

  const handleTaskRunning = useCallback(
    (event: {
      type: "task_running";
      task_id: string;
      message: AIMessage;
      trace?: Partial<ExecutionTraceEvent> & { event_id?: string };
      message_index?: number;
      total_messages?: number;
      tool_summary?: string;
      group_id?: string;
    }) => {
      const taskUpdatedAt =
        typeof event.trace?.timestamp === "number"
          ? event.trace.timestamp
          : Date.now() / 1000;
      updateSubtask({
        id: event.task_id,
        status: "in_progress",
        latestMessage: event.message,
        updated_at: taskUpdatedAt,
      });
      syntheticActivitySeqRef.current += 1;
      appendActivityLiveEvent({
        id: `synthetic-activity:${event.task_id}:running:${syntheticActivitySeqRef.current}`,
        run_id:
          typeof event.trace?.run_id === "string"
            ? event.trace.run_id
            : currentRunIdRef.current ?? "run-unknown",
        seq: syntheticActivitySeqRef.current,
        timestamp: taskUpdatedAt,
        actor: "baby_capy",
        kind: "task_running",
        line: event.tool_summary
          ? `Baby Capy is working on ${event.tool_summary}...`
          : "Baby Capy is working on delegated steps...",
        task_id: event.task_id,
        group_id: event.group_id ?? event.task_id,
        tool_summary: event.tool_summary,
        assistant_message_id:
          typeof event.trace?.assistant_message_id === "string"
            ? event.trace.assistant_message_id
            : undefined,
        payload: {
          message_index: event.message_index,
          total_messages: event.total_messages,
        },
      });
      if (!event.trace?.event_type) return;
      const tracePayload = event.trace.payload;
      const payload = asRecord(tracePayload) ?? {};
      const traceRunId =
        typeof event.trace.run_id === "string" ? event.trace.run_id : undefined;
      const traceId =
        typeof event.trace.id === "string"
          ? event.trace.id
          : typeof event.trace.event_id === "string"
            ? event.trace.event_id
            : undefined;
      if (traceRunId) {
        currentRunIdRef.current = traceRunId;
        setCurrentRunId(traceRunId);
      }
      appendSyntheticTrace({
        id: traceId,
        run_id: traceRunId,
        seq: event.trace.seq,
        timestamp: event.trace.timestamp,
        turn_id: event.trace.turn_id,
        assistant_message_id: event.trace.assistant_message_id,
        stage:
          typeof event.trace.stage === "string" ? event.trace.stage : "subagent",
        status: String(event.trace.status ?? "running"),
        event_type: String(event.trace.event_type),
        task_id: event.task_id,
        thinking: event.trace.thinking,
        token_usage: event.trace.token_usage,
        payload: {
          ...payload,
          message_index: event.message_index,
          total_messages: event.total_messages,
        },
      });
    },
    [appendActivityLiveEvent, appendSyntheticTrace, setCurrentRunId, updateSubtask],
  );

  const handleTaskLifecycle = useCallback(
    (event: {
      type: "task_started" | "task_completed" | "task_failed" | "task_timed_out";
      task_id: string;
      description?: string;
      result?: string;
      error?: string;
      trace?: Partial<ExecutionTraceEvent>;
    }) => {
      const taskTimestamp =
        typeof event.trace?.timestamp === "number"
          ? event.trace.timestamp
          : Date.now() / 1000;

      if (event.type === "task_started") {
        const payload = asRecord(event.trace?.payload) ?? {};
        const description =
          event.description ??
          (typeof payload.description === "string" ? payload.description : undefined) ??
          "Running subtask";
        const subagentType =
          typeof payload.subagent_type === "string" ? payload.subagent_type : "task";
        updateSubtask({
          id: event.task_id,
          status: "in_progress",
          description,
          subagent_type: subagentType,
          started_at: taskTimestamp,
          updated_at: taskTimestamp,
        });
        syntheticActivitySeqRef.current += 1;
        appendActivityLiveEvent({
          id: `synthetic-activity:${event.task_id}:started:${syntheticActivitySeqRef.current}`,
          run_id:
            typeof event.trace?.run_id === "string"
              ? event.trace.run_id
              : currentRunIdRef.current ?? "run-unknown",
          seq: syntheticActivitySeqRef.current,
          timestamp: taskTimestamp,
          actor: "baby_capy",
          kind: "task_started",
          line: `Baby Capy is working on ${description}...`,
          task_id: event.task_id,
          group_id: event.task_id,
          assistant_message_id:
            typeof event.trace?.assistant_message_id === "string"
              ? event.trace.assistant_message_id
              : undefined,
        });
      } else if (event.type === "task_completed") {
        updateSubtask({
          id: event.task_id,
          status: "completed",
          result: event.result,
          completed_at: taskTimestamp,
          updated_at: taskTimestamp,
        });
        syntheticActivitySeqRef.current += 1;
        appendActivityLiveEvent({
          id: `synthetic-activity:${event.task_id}:completed:${syntheticActivitySeqRef.current}`,
          run_id:
            typeof event.trace?.run_id === "string"
              ? event.trace.run_id
              : currentRunIdRef.current ?? "run-unknown",
          seq: syntheticActivitySeqRef.current,
          timestamp: taskTimestamp,
          actor: "baby_capy",
          kind: "task_completed",
          line: "Baby Capy is working on wrapping up results...",
          task_id: event.task_id,
          group_id: event.task_id,
          assistant_message_id:
            typeof event.trace?.assistant_message_id === "string"
              ? event.trace.assistant_message_id
              : undefined,
        });
      } else {
        updateSubtask({
          id: event.task_id,
          status: "failed",
          error:
            event.error ??
            (event.type === "task_timed_out" ? "Task timed out." : "Task failed."),
          completed_at: taskTimestamp,
          updated_at: taskTimestamp,
        });
        syntheticActivitySeqRef.current += 1;
        appendActivityLiveEvent({
          id: `synthetic-activity:${event.task_id}:failed:${syntheticActivitySeqRef.current}`,
          run_id:
            typeof event.trace?.run_id === "string"
              ? event.trace.run_id
              : currentRunIdRef.current ?? "run-unknown",
          seq: syntheticActivitySeqRef.current,
          timestamp: taskTimestamp,
          actor: "baby_capy",
          kind: event.type,
          line: "Baby Capy is working on recovery after an issue...",
          task_id: event.task_id,
          group_id: event.task_id,
          assistant_message_id:
            typeof event.trace?.assistant_message_id === "string"
              ? event.trace.assistant_message_id
              : undefined,
        });
      }

      if (!event.trace?.event_type) return;
      const traceRunId =
        typeof event.trace.run_id === "string" ? event.trace.run_id : undefined;
      if (traceRunId) {
        currentRunIdRef.current = traceRunId;
        setCurrentRunId(traceRunId);
      }
      appendSyntheticTrace({
        id: event.trace.id,
        run_id: traceRunId,
        seq: event.trace.seq,
        timestamp: event.trace.timestamp,
        turn_id: event.trace.turn_id,
        assistant_message_id: event.trace.assistant_message_id,
        stage:
          typeof event.trace.stage === "string" ? event.trace.stage : "subagent",
        status: String(event.trace.status ?? "info"),
        event_type: String(event.trace.event_type),
        task_id: event.task_id,
        thinking: event.trace.thinking,
        token_usage: event.trace.token_usage,
        payload: asRecord(event.trace.payload),
      });
    },
    [appendActivityLiveEvent, appendSyntheticTrace, setCurrentRunId, updateSubtask],
  );

  const handleCustomEvent = useCallback(
    (event: unknown) => {
      if (isActivityEventV1(event)) {
        handleActivityEventV1(event);
        return;
      }
      if (isTraceEventV1(event)) { handleTraceEventV1(event); return; }
      if (typeof event !== "object" || event === null || !("type" in event)) return;
      const typed = event as { type: string };
      switch (typed.type) {
        case "title_update":
          handleTitleUpdate(event as { type: "title_update"; title: string; thread_id: string });
          break;
        case "thinking_chunk":
          handleThinkingChunk(event as { type: "thinking_chunk"; content: string });
          break;
        case "compaction":
          handleCompaction(event as { type: "compaction"; messages_compressed?: number });
          break;
        case "task_running":
          handleTaskRunning(event as Parameters<typeof handleTaskRunning>[0]);
          break;
        case "task_started":
        case "task_completed":
        case "task_failed":
        case "task_timed_out":
          handleTaskLifecycle(event as Parameters<typeof handleTaskLifecycle>[0]);
          break;
        case "planning_started":
          listeners.current.onPlanningStarted?.();
          break;
        case "plan_created":
          listeners.current.onPlanCreated?.(event as Parameters<typeof listeners.current.onPlanCreated>[0]);
          break;
        case "phase_started":
          listeners.current.onPhaseStarted?.(event as Parameters<typeof listeners.current.onPhaseStarted>[0]);
          break;
        case "phase_completed":
          listeners.current.onPhaseCompleted?.(event as Parameters<typeof listeners.current.onPhaseCompleted>[0]);
          break;
        case "plan_adapted":
          listeners.current.onPlanAdapted?.(event as Parameters<typeof listeners.current.onPlanAdapted>[0]);
          break;
        case "complexity_escalation":
          listeners.current.onComplexityEscalation?.(event as Parameters<typeof listeners.current.onComplexityEscalation>[0]);
          break;
      }
    },
    [
      handleActivityEventV1,
      handleTraceEventV1,
      handleTitleUpdate,
      handleThinkingChunk,
      handleCompaction,
      handleTaskRunning,
      handleTaskLifecycle,
    ],
  );

  const thread = useStream<AgentThreadState>({
    client: getAPIClient(isMock),
    assistantId: "lead_agent",
    threadId: onStreamThreadId,
    reconnectOnMount: true,
    // Guard: history-backed SDK APIs throw if this is false.
    // Keep this explicit and immutable for chat pages.
    fetchStateHistory,
    onCreated(meta) {
      handleStreamStart(meta.thread_id);
      setOnStreamThreadId(meta.thread_id);
      publishThreadRefresh(meta.thread_id);
    },
    onLangChainEvent(event) {
      if (event.event === "on_tool_end") {
        listeners.current.onToolEnd?.({
          name: event.name,
          data: event.data,
        });
        if (threadIdRef.current) {
          publishThreadRefresh(threadIdRef.current);
        }
      }
    },
    onUpdateEvent(data) {
      const updates: Array<Partial<AgentThreadState> | null> = Object.values(
        data || {},
      );
      for (const update of updates) {
        if (
          update &&
          (("title" in update && update.title) ||
            "dreamy_mode" in update ||
            "dreamy_intent" in update ||
            "handoff_meta" in update ||
            "phase_execution" in update ||
            "work_mode" in update ||
            "plan" in update)
        ) {
          void queryClient.setQueriesData(
            {
              queryKey: ["threads", "search"],
              exact: false,
            },
            (oldData: Array<AgentThread> | undefined) => {
              return oldData?.map((t) => {
                if (t.thread_id === threadIdRef.current) {
                  return {
                    ...t,
                    values: {
                      ...t.values,
                      ...(update.title ? { title: update.title } : {}),
                      ...("dreamy_mode" in update ? { dreamy_mode: Boolean(update.dreamy_mode) } : {}),
                      ...("dreamy_intent" in update
                        ? { dreamy_intent: update.dreamy_intent }
                        : {}),
                      ...("handoff_meta" in update
                        ? { handoff_meta: update.handoff_meta }
                        : {}),
                      ...("phase_execution" in update
                        ? { phase_execution: update.phase_execution }
                        : {}),
                      ...("work_mode" in update ? { work_mode: update.work_mode } : {}),
                      ...("plan" in update ? { plan: update.plan as PlanState | null } : {}),
                    },
                  };
                }
                return t;
              });
            },
          );
          if (threadIdRef.current) {
            publishThreadRefresh(threadIdRef.current);
          }
        }
      }
    },
    onCustomEvent: handleCustomEvent,
    onMetadataEvent(data) {
      if (typeof data.run_id === "string") {
        currentRunIdRef.current = data.run_id;
        setCurrentRunId(data.run_id);
      }
    },
    onFinish(state) {
      listeners.current.onFinish?.(state.values);
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      if (threadIdRef.current) {
        publishThreadRefresh(threadIdRef.current);
      }
      processQueueRef.current();
    },
  });

  // Optimistic messages shown before the server stream responds
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  // Track message count before sending so we know when server has responded
  const prevMsgCountRef = useRef(thread.messages.length);

  useEffect(() => {
    return () => {
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
      }
      pendingTraceEventsRef.current = [];
    };
  }, []);

  // Clear optimistic when server messages arrive (count increases)
  useEffect(() => {
    if (
      optimisticMessages.length > 0 &&
      thread.messages.length > prevMsgCountRef.current
    ) {
      setOptimisticMessages([]);
    }
  }, [thread.messages.length, optimisticMessages.length]);

  // Uploads files, updates optimistic messages with uploaded status, returns UploadedFileInfo[].
  const handleFileUpload = useCallback(
    async (
      threadId: string,
      files: NonNullable<PromptInputMessage["files"]>,
    ): Promise<UploadedFileInfo[]> => {
      if (files.length === 0) return [];
      if (!threadId) throw new Error("Thread is not ready for file upload.");

      const resolvedFiles = await resolveFilesForUpload(files);
      if (resolvedFiles.length === 0) return [];

      const uploadResponse = await uploadFiles(threadId, resolvedFiles);
      publishWorkspaceRefresh([`uploads:${threadId}`], { source: "thread-upload" });

      const uploadedFiles: FileInMessage[] = uploadResponse.files.map((info) => ({
        filename: info.filename,
        size: info.size,
        path: info.virtual_path,
        status: "uploaded" as const,
      }));
      setOptimisticMessages((messages) => {
        if (messages.length > 1 && messages[0]) {
          return [
            { ...messages[0], additional_kwargs: { files: uploadedFiles } },
            ...messages.slice(1),
          ];
        }
        return messages;
      });

      return uploadResponse.files;
    },
    [],
  );

  const autoSwitchToForkBranch = useCallback(
    (sourceMessageId?: string, sourceBranch?: string) => {
      if (!sourceMessageId) {
        return;
      }
      const sourceMessage = thread.messages.find(
        (msg) => msg.id === sourceMessageId,
      );
      if (!sourceMessage) {
        return;
      }
      const metadata = thread.getMessagesMetadata(sourceMessage);
      const branchOptions = metadata?.branchOptions;
      if (!branchOptions || branchOptions.length < 2) {
        return;
      }
      const targetBranch =
        branchOptions.find((branch) => branch !== sourceBranch) ??
        branchOptions[branchOptions.length - 1];
      if (targetBranch) {
        thread.setBranch(targetBranch);
      }
    },
    [thread],
  );

  const submitMessageNow = useCallback(
    async (
      threadId: string,
      message: PromptInputMessage,
      extraContext?: Record<string, unknown>,
      options?: SendMessageOptions,
    ) => {
      isSubmittingRef.current = true;
      const text = message.text.trim();
      prevMsgCountRef.current = thread.messages.length;

      // Show optimistic messages immediately
      const optimisticFiles: FileInMessage[] = (message.files ?? []).map((f) => ({
        filename: f.filename ?? "",
        size: 0,
        status: "uploading" as const,
      }));
      const newOptimistic: Message[] = [];
      if (text || optimisticFiles.length > 0) {
        const optimisticHumanMsg: Message = {
          type: "human",
          id: `opt-human-${Date.now()}`,
          content: text ? [{ type: "text", text }] : "",
          additional_kwargs: optimisticFiles.length > 0 ? { files: optimisticFiles } : {},
        };
        newOptimistic.push(optimisticHumanMsg);
      }
      if (optimisticFiles.length > 0) {
        newOptimistic.push({
          type: "ai",
          id: `opt-ai-${Date.now()}`,
          content: t.uploads.uploadingFiles,
          additional_kwargs: { element: "task" },
        });
      }
      setOptimisticMessages(newOptimistic);
      _handleOnStart(threadId);

      let uploadedFileInfo: UploadedFileInfo[] = [];

      try {
        if (message.files && message.files.length > 0) {
          try {
            uploadedFileInfo = await handleFileUpload(threadId, message.files);
          } catch (error) {
            console.error("Failed to upload files:", error);
            toast.error(
              error instanceof Error ? error.message : "Failed to upload files.",
            );
            setOptimisticMessages([]);
            throw error;
          }
        }

        const filesForSubmit: FileInMessage[] = uploadedFileInfo.map((info) => ({
          filename: info.filename,
          size: info.size,
          path: info.virtual_path,
          status: "uploaded" as const,
        }));

        clearActivityLiveEvents();
        dispatchThinking({ type: "reset" });
        thinkingSignalEmittedRef.current = false;
        syntheticActivitySeqRef.current += 1;
        appendActivityLiveEvent({
          id: `synthetic-activity:capybara-working:${syntheticActivitySeqRef.current}`,
          run_id: currentRunIdRef.current ?? "run-unknown",
          seq: syntheticActivitySeqRef.current,
          timestamp: Date.now() / 1000,
          actor: "capybara",
          kind: "work_started",
          line: text
            ? `Capybara is working on ${text.slice(0, 140)}...`
            : "Capybara is working on the next step...",
        });
        const outboundMessages = text || filesForSubmit.length > 0
          ? [
              {
                type: "human" as const,
                content: [{ type: "text" as const, text }],
                additional_kwargs: filesForSubmit.length > 0 ? { files: filesForSubmit } : {},
              },
            ]
          : [];
        await thread.submit(
          {
            messages: outboundMessages,
          },
          {
            threadId,
            streamSubgraphs: false,
            streamResumable: true,
            checkpoint: options?.checkpoint,
            config: { recursion_limit: 1000 },
            context: {
              ...extraContext,
              ...context,
              thinking_enabled: true,
              is_plan_mode: (options?.mode ?? context.mode) === "plan",
              mode: options?.mode ?? context.mode ?? "work",
              subagent_enabled: true,
              plan_behavior: (options?.mode ?? context.mode) === "plan" ? "plan_foreground" : "work_interactive",
              auto_mode: context.auto_mode ?? false,
              thread_id: threadId,
            },
          },
        );
        if (options?.checkpoint) {
          autoSwitchToForkBranch(
            options.forkSourceMessageId,
            options.forkSourceBranch,
          );
        }
        void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
        publishThreadRefresh(
          threadId,
          uploadedFileInfo.length > 0 ? [`uploads:${threadId}`] : [],
        );
      } catch (error) {
        setOptimisticMessages([]);
        throw error;
      } finally {
        isSubmittingRef.current = false;
      }
    },
    [
      appendActivityLiveEvent,
      clearActivityLiveEvents,
      thread,
      _handleOnStart,
      t.uploads.uploadingFiles,
      context,
      queryClient,
      handleFileUpload,
      autoSwitchToForkBranch,
    ],
  );

  const submitSteeringIntent = useCallback(
    async (
      itemId: string,
      steerThreadId: string,
      intentId: string,
      message: string,
      retrying: boolean,
    ): Promise<boolean> => {
      const lockUntil = steeringLockUntilRef.current.get(steerThreadId) ?? 0;
      if (Date.now() < lockUntil) {
        if (!retrying) {
          toast.message("Thread is still processing. Steering is temporarily paused.");
        }
        return false;
      }
      if (activeSteerRequestRef.current.has(itemId)) {
        return false;
      }
      activeSteerRequestRef.current.add(itemId);

      try {
        const response = await fetch(`${getBackendBaseURL()}${api.threads.steer(steerThreadId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message, intent_id: intentId }),
        });
        if (!response.ok) {
          const rawError = await response.text();
          const parsedError = extractSteeringError(rawError);
          const detail = parsedError.detail;
          if (isRetryableSteeringConflict(response.status, detail, parsedError.status)) {
            const existing = queueRef.current.find((entry) => entry.id === itemId);
            const failureCount = (existing?.steerIntent?.failureCount ?? 0) + 1;
            const next = updateById(queueRef.current, itemId, (entry) => ({
              ...entry,
              steerIntent: {
                intentId,
                status: "failed" as const,
                failureCount,
              },
            }));
            applyQueue(next);
            const delayMs = Math.min(1500 * Math.max(1, failureCount), 10_000);
            steeringLockUntilRef.current.set(steerThreadId, Date.now() + delayMs);
            scheduleSteerRetry(delayMs);
            if (!retrying) {
              toast.message("Thread is still busy. Steering will retry automatically.");
            }
            return false;
          }
          throw new Error(detail);
        }
        const { remaining } = removeById(queueRef.current, itemId);
        applyQueue(remaining);
        clearScheduledSteerRetry();
        toast.success("Steering queued and will be injected on the next available model turn.");
        return true;
      } catch (error) {
        console.error("Failed to submit steering intent:", error);
        const next = updateById(queueRef.current, itemId, (entry) => ({
          ...entry,
          steerIntent: {
            intentId,
            status: "failed" as const,
            failureCount: (entry.steerIntent?.failureCount ?? 0) + 1,
          },
        }));
        applyQueue(next);
        steeringLockUntilRef.current.set(steerThreadId, Date.now() + 3_000);
        toast.error(
          retrying
            ? "Retrying steering failed. It will be retried again after queue progress."
            : "Failed to queue steering. It will retry after the next queued progress.",
        );
        return false;
      } finally {
        activeSteerRequestRef.current.delete(itemId);
      }
    },
    [applyQueue, clearScheduledSteerRetry, scheduleSteerRetry],
  );

  const retryFailedSteering = useCallback(async () => {
    const candidate = queueRef.current.find(
      (item) => item.steerIntent?.status === "failed",
    );
    if (!candidate) {
      return;
    }
    const intentId = candidate.steerIntent?.intentId ?? candidate.id;
    const message = candidate.message.text.trim();
    if (!message) {
      return;
    }
    const updated = updateById(queueRef.current, candidate.id, (entry) => ({
      ...entry,
      steerIntent: {
        intentId,
        status: "retrying" as const,
        failureCount: entry.steerIntent?.failureCount ?? 0,
      },
    }));
    applyQueue(updated);
    await submitSteeringIntent(candidate.id, candidate.threadId, intentId, message, true);
  }, [applyQueue, submitSteeringIntent]);

  useEffect(() => {
    retrySteerRef.current = retryFailedSteering;
  }, [retryFailedSteering]);

  const processQueue = useCallback(() => {
    if (isDequeuingRef.current || isSubmittingRef.current || thread.isLoading) {
      return;
    }
    const { next, remaining } = dequeueMatching(
      queueRef.current,
      (item) => !item.steerIntent,
    );
    if (!next) {
      return;
    }

    isDequeuingRef.current = true;
    applyQueue(remaining);

    let submitted = false;
    let shouldRetryLater = false;
    void submitMessageNow(next.threadId, next.message, next.extraContext, next.options)
      .then(() => {
        submitted = true;
      })
      .catch((error) => {
        const recovered = requeueFront(queueRef.current, next);
        applyQueue(recovered);
        if (isRetryableSubmitConflictError(error)) {
          shouldRetryLater = true;
          clearScheduledQueueRetry();
          queueRetryTimeoutRef.current = window.setTimeout(() => {
            queueRetryTimeoutRef.current = null;
            processQueueRef.current();
          }, 2000);
          return;
        }
        console.error("Failed to send queued message:", error);
        toast.error("Failed to send queued message. It was returned to the queue.");
      })
      .finally(() => {
        isDequeuingRef.current = false;
        if (submitted) {
          void retrySteerRef.current();
        }
        if (!shouldRetryLater && queueRef.current.length > 0) {
          processQueueRef.current();
        }
      });
  }, [applyQueue, clearScheduledQueueRetry, submitMessageNow, thread.isLoading]);

  useEffect(() => {
    processQueueRef.current = processQueue;
  }, [processQueue]);

  useEffect(() => {
    if (messageQueue.length === 0 || thread.isLoading || isSubmittingRef.current) {
      return;
    }
    processQueueRef.current();
  }, [messageQueue.length, thread.isLoading]);

  const sendMessage = useCallback(
    async (
      threadId: string,
      message: PromptInputMessage,
      extraContext?: Record<string, unknown>,
      options?: SendMessageOptions,
    ) => {
      const shouldQueue = shouldEnqueueMessage({
        queued: options?.queued,
        isLoading: thread.isLoading,
        isSubmitting: isSubmittingRef.current,
        queueLength: queueRef.current.length,
      });

      if (!shouldQueue) {
        return;
      }

      const queueItem: QueuedMessage = {
        id: uuid(),
        createdAt: Date.now(),
        threadId,
        message,
        extraContext,
        allowSteer: !Boolean(options?.checkpoint),
        options: options ? { ...options, queued: false } : undefined,
      };
      const nextQueue = enqueueMessage(queueRef.current, queueItem);
      applyQueue(nextQueue);
      processQueueRef.current();
    },
    [applyQueue, thread.isLoading],
  );

  const dismissQueued = useCallback(
    (itemId: string) => {
      const { remaining } = removeById(queueRef.current, itemId);
      applyQueue(remaining);
      void retrySteerRef.current();
    },
    [applyQueue],
  );

  const steerQueued = useCallback(
    async (itemId: string) => {
      const item = queueRef.current.find((entry) => entry.id === itemId);
      if (!item) {
        return;
      }
      if (!item.allowSteer) {
        toast.message("Steering is unavailable for forked checkpoint submissions.");
        return;
      }
      if (item.steerIntent?.status === "pending" || item.steerIntent?.status === "retrying") {
        return;
      }

      const message = item.message.text.trim();
      if (!message) {
        toast.error("Cannot steer with an empty queued message.");
        return;
      }

      const intentId = item.steerIntent?.intentId ?? item.id;
      const updated = updateById(queueRef.current, itemId, (entry) => ({
        ...entry,
        steerIntent: {
          intentId,
          status: "pending" as const,
          failureCount: entry.steerIntent?.failureCount ?? 0,
        },
      }));
      applyQueue(updated);
      await submitSteeringIntent(itemId, item.threadId, intentId, message, false);
      processQueueRef.current();
    },
    [applyQueue, submitSteeringIntent],
  );

  const stop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

  // Merge thread with optimistic messages for display
  const mergedThread =
    optimisticMessages.length > 0
      ? ({
          ...thread,
          messages: [...thread.messages, ...optimisticMessages],
        } as typeof thread)
      : thread;

  return [
    mergedThread,
    sendMessage,
    liveThinkingContent,
    {
      queueLength: messageQueue.length,
      queueItems: messageQueue.map((item) => ({
        id: item.id,
        text: item.message.text,
        createdAt: item.createdAt,
        steerEnabled: item.allowSteer,
        steerStatus: item.steerIntent?.status ?? "none",
      })),
      steerQueued,
      dismissQueued,
      clearQueue,
      stop,
    } as ThreadQueueControls,
  ] as const;
}

export function useThreads(
  params?: Parameters<ThreadsClient["search"]>[0],
) {
  const apiClient = getAPIClient();
  const effectiveParams: Parameters<ThreadsClient["search"]>[0] = params ?? {
    limit: 50,
    sortBy: "updated_at",
    sortOrder: "desc",
    select: ["thread_id", "updated_at", "values"],
  };
  return useWorkspaceRefreshQuery<AgentThread[]>({
    // Keep key deterministic to prevent accidental query churn/cancellation loops.
    queryKey: [
      "threads",
      "search",
      effectiveParams.limit ?? null,
      effectiveParams.offset ?? null,
      effectiveParams.sortBy ?? null,
      effectiveParams.sortOrder ?? null,
      Array.isArray(effectiveParams.select) ? effectiveParams.select.join(",") : null,
      Array.isArray(effectiveParams.ids) ? effectiveParams.ids.join(",") : null,
      effectiveParams.status ?? null,
    ],
    queryFn: async () => {
      const searchWithTimeout = async (
        query: Parameters<ThreadsClient["search"]>[0],
        timeoutMs: number,
      ) => {
        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), timeoutMs);
        try {
          return await apiClient.threads.search<AgentThreadState>({
            ...query,
            signal: controller.signal,
          });
        } finally {
          window.clearTimeout(timer);
        }
      };

      // Prefer full records (including values.title) for proper recent-chat labels.
      // If this fails (e.g. oversized/invalid state payload in one thread), fall
      // back to a lightweight list so the sidebar still renders past chats.
      try {
        const response = await searchWithTimeout(effectiveParams, 8_000);
        if (!Array.isArray(response)) {
          return [];
        }
        return response as AgentThread[];
      } catch (error) {
        console.warn("Primary threads.search failed; falling back to lightweight thread list.", error);
        const fallbackResponse = await searchWithTimeout({
          limit: effectiveParams.limit,
          offset: effectiveParams.offset,
          sortBy: effectiveParams.sortBy,
          sortOrder: effectiveParams.sortOrder,
          metadata: effectiveParams.metadata,
          status: effectiveParams.status,
          ids: effectiveParams.ids,
          // Avoid selecting values in fallback to bypass state serialization issues.
          select: ["thread_id", "updated_at"],
        }, 5_000);
        if (!Array.isArray(fallbackResponse)) {
          return [];
        }
        return fallbackResponse.map((thread) => ({
          ...thread,
          values: {
            title: "Untitled",
          },
        })) as AgentThread[];
      }
    },
    refreshDomains: ["threads"],
    invalidateQueryKey: ["threads", "search"],
    invalidateExact: false,
  });
}

export function useDeleteThread() {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: async ({ threadId }: { threadId: string }) => {
      await deleteThreadWithCleanup(threadId);
    },
    onSuccess(_, { threadId }) {
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread>) => {
          return oldData.filter((t) => t.thread_id !== threadId);
        },
      );
      publishThreadRefresh(threadId);
      toast.success(t.chats.deleteChatSuccess);
    },
    onError(error) {
      toast.error(error instanceof Error ? error.message : t.chats.deleteChatFailed);
    },
  });
}

export function useRenameThread() {
  const queryClient = useQueryClient();
  const apiClient = getAPIClient();
  return useMutation({
    mutationFn: async ({
      threadId,
      title,
    }: {
      threadId: string;
      title: string;
    }) => {
      await apiClient.threads.updateState(threadId, {
        values: { title },
      });
    },
    onSuccess(_, { threadId, title }) {
      queryClient.setQueriesData(
        {
          queryKey: ["threads", "search"],
          exact: false,
        },
        (oldData: Array<AgentThread>) => {
          return oldData.map((t) => {
            if (t.thread_id === threadId) {
              return {
                ...t,
                values: {
                  ...t.values,
                  title,
                },
              };
            }
            return t;
          });
        },
      );
      publishThreadRefresh(threadId);
    },
  });
}

export function useDeleteAllThreads() {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: async () => {
      return deleteAllThreadsWithCleanup();
    },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({
        queryKey: ["threads", "search"],
      });
      publishWorkspaceRefresh(["threads"], { source: "delete-all-threads" });
      if (result.failed_thread_ids.length > 0) {
        toast.error(t.chats.deleteAllChatsPartialFailure(result.failed_thread_ids.length));
        return;
      }
      toast.success(t.chats.deleteAllChatsSuccess);
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : t.chats.deleteAllChatsFailed);
    },
  });
}
