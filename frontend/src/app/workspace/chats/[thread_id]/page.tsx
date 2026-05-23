"use client";

import { ArrowUpRightIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { Badge } from "@/components/ui/badge";
import { AdaptationNotice } from "@/components/workspace/adaptation-notice";
import { MountFolderBadge } from "@/components/workspace/chat-ui/mount-folder-badge";
import {
  ChatBox,
  useThreadChat,
} from "@/components/workspace/chats";
import { ComplexityEscalationPopup } from "@/components/workspace/complexity-escalation-popup";
import { ExecutePlanPopup } from "@/components/workspace/execute-plan-popup";
import {
  InputBox,
  type InputBoxSubmitOptions,
} from "@/components/workspace/input-box";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { QueuedMessageList } from "@/components/workspace/queued-message-list";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { Welcome } from "@/components/workspace/welcome";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/dreamy/api";
import { useMountedFolder } from "@/core/dreamy/hooks/use-mounted-folder";
import { useMountedFolderFiles } from "@/core/dreamy/hooks/use-mounted-folder-files";
import {
  type LiveGenerationNotice,
  useGenerationCompletions,
} from "@/core/generation/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useLocalSettings } from "@/core/settings";
import {
  clearPendingChatLaunchPayload,
  getPendingChatLaunchPayload,
} from "@/core/threads/chat-launch-payload";
import type { ForkDraft } from "@/core/threads/fork";
import type { ComplexityEscalationEvent, PlanAdaptedEvent, PlanCreatedEvent } from "@/core/threads/hooks";
import { useRenameThread, useThreadStream } from "@/core/threads/hooks";
import { useContextTokens } from "@/core/threads/use-context-tokens";
import { useRejoinRunningRun } from "@/core/threads/use-rejoin-running-run";
import { useThreadNotification } from "@/core/threads/use-thread-notification";
import { publishWorkspaceRefresh } from "@/core/workspace-refresh";
import { env } from "@/env";
import { cn } from "@/lib/utils";

const EXECUTE_PLAN_INTENTS = new Set([
  "execute plan",
  "implement plan",
  "proceed",
  "proceed with plan",
  "run plan",
  "start plan",
]);

function normalizeIntent(text: string): string {
  return text.toLowerCase().trim().replace(/[.!?]+$/g, "");
}

function getMountedFolderName(
  fallbackPath: string | null | undefined,
): string | null {
  const normalized = fallbackPath?.trim().replace(/[\\/]+$/, "");
  if (!normalized) {
    return null;
  }
  const segments = normalized.split(/[\\/]/).filter(Boolean);
  return segments[segments.length - 1] ?? null;
}

function formatMountedThreadTitle(title: string): string {
  const trimmed = title.trim();
  const normalized = trimmed.startsWith("📁 ")
    ? trimmed.slice("📁 ".length).trim()
    : trimmed;
  return `📁 ${normalized}`;
}

function isMountPlaceholderTitle(title: string): boolean {
  return title === "" || title === "mount-drive";
}

function getComplexityEscalationKey(
  event: ComplexityEscalationEvent | null | undefined,
): string | null {
  if (!event) {
    return null;
  }
  return [
    event.complexity_tier ?? "",
    event.recommended_action ?? "",
    event.message ?? "",
  ].join("|");
}

function upsertNotice(
  notices: LiveGenerationNotice[],
  notice: LiveGenerationNotice,
): LiveGenerationNotice[] {
  const next = notices.filter((item) => item.id !== notice.id);
  return [...next, notice];
}

function parseErrorDetail(rawBody: string): string {
  const trimmed = rawBody.trim();
  if (!trimmed) {
    return "Unknown error";
  }
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (typeof parsed === "object" && parsed !== null && "detail" in parsed) {
      const detail = (parsed as { detail?: unknown }).detail;
      if (typeof detail === "string" && detail.trim()) {
        return detail.trim();
      }
    }
  } catch {
    // fall through to raw body
  }
  return trimmed;
}

function isThreadLockError(error: unknown): boolean {
  const message =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : JSON.stringify(error);
  const normalized = message.toLowerCase();
  return (
    normalized.includes("http 409") ||
    normalized.includes("http 423") ||
    normalized.includes("in-flight runs") ||
    normalized.includes("temporarily locked")
  );
}

type ExecutePlanResponse = {
  acknowledged: boolean;
  status: "accepted" | "duplicate" | "conflict" | "failed";
  plan_status?: string | null;
};

function getExecutePlanFailureMessage(result: ExecutePlanResponse): string | null {
  if (result.acknowledged && result.status !== "conflict" && result.status !== "failed") {
    return null;
  }
  if (result.status === "conflict") {
    if (result.plan_status) {
      return `Plan execution is blocked while the plan is ${result.plan_status}.`;
    }
    return "Plan execution is blocked. Please resolve the pending plan state and try again.";
  }
  if (result.status === "failed") {
    return "Plan execution failed. Please try again.";
  }
  return "Plan execution was not accepted. Please try again.";
}

export default function ChatPage() {
  const { threadId, isNewThread, setIsNewThread, isMock } = useThreadChat();

  return (
    <ChatPageContent
      key={threadId}
      isMock={isMock}
      isNewThread={isNewThread}
      setIsNewThread={setIsNewThread}
      threadId={threadId}
    />
  );
}

function ChatPageContent({
  threadId,
  isNewThread,
  setIsNewThread,
  isMock,
}: {
  threadId: string;
  isNewThread: boolean;
  setIsNewThread: (value: boolean) => void;
  isMock: boolean;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const [settings, setSettings] = useLocalSettings();
  const selectedModelName =
    typeof settings.context.model_name === "string"
      ? settings.context.model_name
      : undefined;
  const { models } = useModels();
  const { state: contextTokenState, onCompaction, onContextTokens } = useContextTokens({
    modelName: selectedModelName,
    models,
  });
  const { notices: generationNotices, artifactPaths: generationArtifacts } =
    useGenerationCompletions(threadId);
  const { data: mountedFolder } = useMountedFolder(threadId);
  const { data: mountedFolderFiles } = useMountedFolderFiles(
    threadId,
    Boolean(mountedFolder),
  );
  const mountedArtifacts = (mountedFolderFiles?.files ?? []).map(
    (file) => file.virtual_path,
  );
  const combinedArtifacts = Array.from(
    new Set([...generationArtifacts, ...mountedArtifacts]),
  );

  // Probe for an in-flight run so we can label resume situations. The
  // langgraph-sdk `useStream` already auto-joins via reconnectOnMount, so this
  // is observation-only — it lets the UI distinguish "fresh open" from
  // "resuming a still-running answer that started in another tab/session."
  const { onFinish } = useThreadNotification();

  const [planCreatedEvent, setPlanCreatedEvent] = useState<PlanCreatedEvent | null>(null);
  const [adaptationEvent, setAdaptationEvent] = useState<PlanAdaptedEvent | null>(null);
  const [escalationEvent, setEscalationEvent] = useState<ComplexityEscalationEvent | null>(null);
  const [forkDraft, setForkDraft] = useState<ForkDraft | null>(null);
  const [uiNotices, setUiNotices] = useState<LiveGenerationNotice[]>([]);
  const [pendingExecutePlan, setPendingExecutePlan] = useState(false);
  const [isExecutingPlan, setIsExecutingPlan] = useState(false);
  const [runPollBump, setRunPollBump] = useState(0);
  const [isMountBootstrapRunning, setIsMountBootstrapRunning] = useState(false);
  const [hiddenPlanEventKey, setHiddenPlanEventKey] = useState<string | null>(null);
  const [pendingMountPath, setPendingMountPath] = useState<string | null>(null);
  const suppressedAutoExecutePlanKeyRef = useRef<string | null>(null);
  const suppressedComplexityEscalationKeyRef = useRef<string | null>(null);
  const executePlanRetryCountRef = useRef(0);
  const finalizedMountedTitleRef = useRef<string | null>(null);
  const finalizingMountedTitleRef = useRef<string | null>(null);
  const mountBootstrapSentRef = useRef<string | null>(null);
  const renameThread = useRenameThread();
  const mountStatusNoticeId = `mount-status-${threadId}`;
  const mountedNoticeId = `mount-ready-${threadId}`;
  const mountBootstrapStorageKey = useMemo(
    () => `mount.bootstrap.sent.${threadId}`,
    [threadId],
  );

  const isInFlightRunConflict = useCallback((statusCode: number, rawBody: string): boolean => {
    if (statusCode === 409 || statusCode === 423) {
      return true;
    }
    const normalized = rawBody.toLowerCase();
    return normalized.includes("in-flight runs") || normalized.includes("temporarily locked");
  }, []);

  const planEventKey = useCallback((event: PlanCreatedEvent | null) => {
    if (!event) {
      return null;
    }
    return event.plan_id ?? `${event.title}:${event.todo_count}:${event.plan_path ?? "none"}`;
  }, []);

  const [thread, sendMessage, liveThinkingContent, queueControls] = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    context: settings.context,
    isMock,
    onContextTokens: ({ tokenCount }) => onContextTokens(tokenCount),
    onCompaction: onCompaction,
    onStart: () => {
      setIsNewThread(false);
      // Use router.replace so Next.js Router's internal state is updated.
      // This ensures subsequent "New Chat" clicks are treated as a real
      // cross-route navigation (actual-id → "new") rather than a no-op
      // same-path navigation, which was causing stale content to persist.
      router.replace(`/workspace/chats/${threadId}`);
    },
    onFinish,
    onPlanCreated: (event) => setPlanCreatedEvent(event),
    onPlanAdapted: (event) => setAdaptationEvent(event),
    onComplexityEscalation: (event) => {
      const eventKey = getComplexityEscalationKey(event);
      if (!eventKey) {
        return;
      }
      if (settings.context.mode === "plan") {
        return;
      }
      if (suppressedComplexityEscalationKeyRef.current === eventKey) {
        return;
      }
      setEscalationEvent(event);
    },
  });

  const { runningRun } = useRejoinRunningRun(isNewThread ? null : threadId, thread, {
    pollBump: runPollBump,
  });

  const handleStop = useCallback(async () => {
    await queueControls.stop();
  }, [queueControls]);
  const handleContextChange = useCallback(
    (nextContext: Parameters<typeof setSettings>[1]) => {
      setSettings("context", nextContext);
    },
    [setSettings],
  );
  const clarificationPending =
    planCreatedEvent?.clarification_pending === true ||
    thread.values.plan?.clarification_pending === true;
  const effectivePlanCreatedEvent = useMemo(() => {
    if (planCreatedEvent) {
      return planCreatedEvent;
    }
    const plan = thread.values.plan;
    if (!plan || clarificationPending) {
      return null;
    }
    const planStatus = String(plan.status ?? "").toLowerCase();
    const awaitingApproval = plan.awaiting_execution_approval === true || planStatus === "draft";
    const approvedButIdle =
      planStatus === "approved" &&
      !plan.execution_started_at &&
      !thread.values.work_mode?.active;
    if (!awaitingApproval && !approvedButIdle) {
      return null;
    }
    const todos = Array.isArray(thread.values.todos) ? thread.values.todos : [];
    const firstTodos = todos
      .map((todo) => String(todo.content ?? "").trim())
      .filter(Boolean)
      .slice(0, 5);
    const todoCount = todos.length > 0 ? todos.length : (plan.todo_ids?.length ?? 0);
    return {
      type: "plan_created" as const,
      plan_id: plan.plan_id,
      status: plan.status,
      auto_approved: false,
      clarification_pending: false,
      title: String(plan.title ?? "Approved Plan"),
      summary: String(plan.summary ?? ""),
      domain: String(plan.domain ?? "generic"),
      todo_count: todoCount,
      first_todos: firstTodos,
      plan_path: plan.plan_path ?? null,
    };
  }, [clarificationPending, planCreatedEvent, thread.values.plan, thread.values.todos, thread.values.work_mode?.active]);
  const effectivePlanEventKey = useMemo(
    () => planEventKey(effectivePlanCreatedEvent),
    [effectivePlanCreatedEvent, planEventKey],
  );
  const planReviewHref = useMemo(() => {
    const planPath = effectivePlanCreatedEvent?.plan_path ?? "/mnt/user-data/workspace/plan.md";
    return urlOfArtifact({ filepath: planPath, threadId, isMock });
  }, [effectivePlanCreatedEvent?.plan_path, isMock, threadId]);

  useEffect(() => {
    if (!effectivePlanEventKey) {
      return;
    }
    if (hiddenPlanEventKey && hiddenPlanEventKey !== effectivePlanEventKey) {
      setHiddenPlanEventKey(null);
      setIsExecutingPlan(false);
    }
  }, [effectivePlanEventKey, hiddenPlanEventKey]);

  const handleExecutePlan = useCallback(() => {
    const run = async () => {
      try {
        if (isExecutingPlan) {
          return;
        }
        const eventKey = effectivePlanEventKey;
        if (eventKey && suppressedAutoExecutePlanKeyRef.current === eventKey) {
          return;
        }
        setSettings("context", { ...settings.context, mode: "work" });
        setIsExecutingPlan(true);
        setHiddenPlanEventKey(eventKey);
        setPlanCreatedEvent(null);
        if (thread.isLoading) {
          if (!pendingExecutePlan) {
            toast.message("Plan execution is queued and will start after the current run finishes.");
          }
          setPendingExecutePlan(true);
          return;
        }
        const response = await fetch(`${getBackendBaseURL()}${api.threads.executePlan(threadId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            plan_id: effectivePlanCreatedEvent?.plan_id,
            auto_mode: settings.context.auto_mode === true,
          }),
        });
        if (!response.ok) {
          const raw = await response.text();
          if (isInFlightRunConflict(response.status, raw)) {
            executePlanRetryCountRef.current += 1;
            if (executePlanRetryCountRef.current <= 6) {
              setPendingExecutePlan(true);
              return;
            }
            throw new Error("Thread still has an active run. Please wait and retry Execute Plan.");
          }
          throw new Error(parseErrorDetail(raw));
        }
        const result = await response.json() as ExecutePlanResponse;
        const failureMessage = getExecutePlanFailureMessage(result);
        if (failureMessage) {
          throw new Error(failureMessage);
        }
        executePlanRetryCountRef.current = 0;
        setPendingExecutePlan(false);
        setIsExecutingPlan(false);
        setRunPollBump((value) => value + 1);
        publishWorkspaceRefresh(["runs", "threads", `thread:${threadId}`], {
          source: "execute-plan",
        });
      } catch (error) {
        // Keep popup open so user can retry execute.
        console.error("Failed to execute plan:", error);
        const detail = error instanceof Error ? error.message : "Unknown error";
        toast.error(`Failed to execute plan. ${detail}`);
        setPendingExecutePlan(false);
        setIsExecutingPlan(false);
        setHiddenPlanEventKey(null);
      }
    };
    void run();
  }, [
    effectivePlanCreatedEvent?.plan_id,
    effectivePlanEventKey,
    isExecutingPlan,
    isInFlightRunConflict,
    pendingExecutePlan,
    setSettings,
    settings.context,
    settings.context.auto_mode,
    threadId,
    thread.isLoading,
  ]);

  // Auto-trigger Execute Plan when a plan is created and auto_mode is on.
  useEffect(() => {
    const handler = (event: Event) => {
      const custom = event as CustomEvent<{ threadId?: string; content?: string }>;
      const content = custom.detail?.content;
      if (!content || custom.detail?.threadId !== threadId) {
        return;
      }
      setUiNotices((prev) =>
        upsertNotice(prev, {
          id: mountedNoticeId,
          content,
        }));
    };
    window.addEventListener("chat-mounted-notice", handler as EventListener);
    return () => {
      window.removeEventListener("chat-mounted-notice", handler as EventListener);
    };
  }, [mountedNoticeId, threadId]);

  useEffect(() => {
    const payload = getPendingChatLaunchPayload();
    if (payload?.source !== "mount" || payload.targetThreadId !== threadId) {
      return;
    }
    const normalizedMountedPath = payload.mountedPath?.trim();
    setPendingMountPath(normalizedMountedPath && normalizedMountedPath.length > 0 ? normalizedMountedPath : null);
    setUiNotices((prev) =>
      upsertNotice(prev, {
        id: mountStatusNoticeId,
        content: payload.mountedPath
          ? `Mounting files from ${payload.mountedPath}...`
          : "Mounting files...",
      }));
    clearPendingChatLaunchPayload();
  }, [mountStatusNoticeId, threadId]);

  useEffect(() => {
    if (!pendingMountPath) {
      return;
    }
    const normalizedPath = pendingMountPath.trim();
    if (!normalizedPath) {
      return;
    }

    // React Strict Mode can remount components in development, which resets
    // refs and may dispatch this verification twice. Persist a per-thread/path
    // marker so we only send once for the same mounted target.
    const marker = `${threadId}:${normalizedPath}`;
    if (typeof window !== "undefined") {
      const sentMarker = window.sessionStorage.getItem(mountBootstrapStorageKey);
      if (sentMarker === marker) {
        mountBootstrapSentRef.current = threadId;
        return;
      }
      window.sessionStorage.setItem(mountBootstrapStorageKey, marker);
    }

    if (mountBootstrapSentRef.current === threadId) {
      return;
    }
    mountBootstrapSentRef.current = threadId;
    setIsMountBootstrapRunning(true);
    void sendMessage(
      threadId,
      {
        text: "Check if drive is mounted. Reply yes or no.",
        files: [],
      },
      undefined,
      { queued: true },
    ).catch((error) => {
      // Mount bootstrap verification is best-effort. During short overlap
      // windows, thread-level lock conflicts are expected and already retried.
      if (isThreadLockError(error)) {
        return;
      }
      console.error("Mount bootstrap verification failed:", error);
    }).finally(() => {
      setIsMountBootstrapRunning(false);
    });
  }, [mountBootstrapStorageKey, pendingMountPath, sendMessage, threadId]);

  useEffect(() => {
    const currentTitle = String(thread.values.title ?? "").trim();
    const mountSourcePath = pendingMountPath ?? mountedFolder ?? null;

    if (!mountSourcePath) {
      return;
    }
    if (finalizedMountedTitleRef.current === threadId) {
      return;
    }
    if (finalizingMountedTitleRef.current === threadId) {
      return;
    }
    if (!mountedFolderFiles) {
      return;
    }
    if (pendingMountPath && thread.messages.length === 0) {
      return;
    }
    if (isMountBootstrapRunning || thread.isLoading || runningRun) {
      return;
    }

    const derivedTitle = getMountedFolderName(
      mountedFolderFiles.folder_path ?? mountSourcePath,
    );
    if (!derivedTitle) {
      return;
    }

    const formattedTitle = formatMountedThreadTitle(derivedTitle);
    if (currentTitle === formattedTitle) {
      finalizedMountedTitleRef.current = threadId;
      setPendingMountPath(null);
      setUiNotices((prev) =>
        prev.filter((notice) => notice.id !== mountStatusNoticeId),
      );
      return;
    }
    if (!pendingMountPath && !isMountPlaceholderTitle(currentTitle) && currentTitle !== derivedTitle) {
      return;
    }

    void (async () => {
      finalizingMountedTitleRef.current = threadId;
      try {
        await renameThread.mutateAsync({
          threadId,
          title: formattedTitle,
        });
        finalizedMountedTitleRef.current = threadId;
        setPendingMountPath(null);
        setUiNotices((prev) =>
          prev.filter((notice) => notice.id !== mountStatusNoticeId),
        );
        toast.success(`Mounted folder ready: ${formattedTitle}`, {
          id: mountedNoticeId,
        });
      } catch (error) {
        if (isThreadLockError(error)) {
          return;
        }
        console.error("Failed to finalize mounted thread title:", error);
      } finally {
        if (finalizingMountedTitleRef.current === threadId) {
          finalizingMountedTitleRef.current = null;
        }
      }
    })();
  }, [isMountBootstrapRunning, mountStatusNoticeId, mountedFolder, mountedFolderFiles, mountedNoticeId, pendingMountPath, renameThread, runningRun, thread.isLoading, thread.messages.length, thread.values.title, threadId]);

  useEffect(() => {
    if (settings.context.mode !== "plan") {
      return;
    }
    if (!escalationEvent) {
      return;
    }
    suppressedComplexityEscalationKeyRef.current = getComplexityEscalationKey(escalationEvent);
    setEscalationEvent(null);
  }, [escalationEvent, settings.context.mode]);

  useEffect(() => {
    if (!pendingExecutePlan || thread.isLoading) {
      return;
    }
    const delayMs = Math.min(1200 * Math.max(1, executePlanRetryCountRef.current), 8000);
    const timer = window.setTimeout(() => {
      void handleExecutePlan();
    }, delayMs);
    return () => window.clearTimeout(timer);
  }, [handleExecutePlan, pendingExecutePlan, planCreatedEvent, thread.isLoading]);

  const handleKeepEditingPlan = useCallback(() => {
    const eventKey = planEventKey(effectivePlanCreatedEvent);
    if (eventKey) {
      suppressedAutoExecutePlanKeyRef.current = eventKey;
      setHiddenPlanEventKey(eventKey);
    }
    setSettings("context", { ...settings.context, mode: "plan" });
    setIsExecutingPlan(false);
    executePlanRetryCountRef.current = 0;
    setPendingExecutePlan(false);
    setPlanCreatedEvent(null);
  }, [effectivePlanCreatedEvent, planEventKey, setSettings, settings.context]);

  const handleRevisePlan = useCallback(() => {
    const blockedIds = adaptationEvent?.blocked_ids ?? [];
    const blockedContext = blockedIds.length > 0
      ? ` The following todos are blocked: ${blockedIds.join(", ")}.`
      : "";
    setAdaptationEvent(null);
    setSettings("context", { ...settings.context, mode: "plan" });
    void sendMessage(
      threadId,
      { text: `Revise the plan.${blockedContext} Please resolve the dependency issues.`, files: [] },
      undefined,
      { mode: "plan" },
    );
  }, [adaptationEvent, sendMessage, setSettings, settings.context, threadId]);

  const handleSwitchToPlan = useCallback(() => {
    suppressedComplexityEscalationKeyRef.current = getComplexityEscalationKey(escalationEvent);
    setEscalationEvent(null);
    setSettings("context", { ...settings.context, mode: "plan" });
  }, [escalationEvent, setEscalationEvent, setSettings, settings.context]);

  const handleContinueWork = useCallback(() => {
    suppressedComplexityEscalationKeyRef.current = getComplexityEscalationKey(escalationEvent);
    setEscalationEvent(null);
  }, [escalationEvent]);

  const handleSubmitPlanRevision = useCallback(async (markdown: string) => {
    const currentPlanTitle = String(thread.values.plan?.title ?? "Draft Plan");
    setSettings("context", { ...settings.context, mode: "plan" });
    await sendMessage(
      threadId,
      {
        text: [
          `Revise the current draft plan titled "${currentPlanTitle}" to match the edited markdown below.`,
          "Treat this as the user's explicit plan edits.",
          "Requirements:",
          "1. Update the draft plan state and todo graph to align with this markdown.",
          "2. Keep the plan in draft status (do not execute yet).",
          "3. Rewrite plan artifacts (including plan.md) so preview and state stay in sync.",
          "<edited_plan_markdown>",
          markdown,
          "</edited_plan_markdown>",
        ].join("\n"),
        files: [],
      },
      undefined,
      { mode: "plan" },
    );
  }, [sendMessage, setSettings, settings.context, thread.values.plan?.title, threadId]);

  const handleSubmit = useCallback(
    (message: PromptInputMessage, options?: InputBoxSubmitOptions) => {
      suppressedComplexityEscalationKeyRef.current = null;
      const maybeIntent = normalizeIntent(message.text ?? "");
      const planStatus = String(thread.values.plan?.status ?? "").toLowerCase();
      const hasPlanReadyForExecution = planStatus === "draft" || planStatus === "approved";
      if (
        !thread.isLoading &&
        hasPlanReadyForExecution &&
        (!message.files || message.files.length === 0) &&
        EXECUTE_PLAN_INTENTS.has(maybeIntent)
      ) {
        handleExecutePlan();
        return;
      }
      const { extraContext: submitExtraContext, ...submitOptions } = options ?? {};
      const normalizedSubmitOptions = options ? submitOptions : undefined;
      void sendMessage(threadId, message, submitExtraContext, normalizedSubmitOptions);
    },
    [handleExecutePlan, sendMessage, thread.isLoading, thread.values.plan?.status, threadId],
  );

  const latestPersistedContextTokens = useMemo(
    () => {
      const metrics = thread.values.context_metrics;
      if (!metrics || typeof metrics !== "object") {
        return null;
      }
      const tokenCount = (metrics as { token_count?: unknown }).token_count;
      if (typeof tokenCount !== "number" || !Number.isFinite(tokenCount)) {
        return null;
      }
      const messageCount = (metrics as { message_count?: unknown }).message_count;
      return {
        tokenCount,
        messageCount:
          typeof messageCount === "number" && Number.isFinite(messageCount)
            ? messageCount
            : undefined,
      };
    },
    [thread.values.context_metrics],
  );

  const handoffBanner = useMemo(() => {
    const meta = thread.values.handoff_meta;
    if (!meta || typeof meta !== "object") {
      return null;
    }
    const handoffRoot = typeof meta.handoff_root_virtual_path === "string"
      ? meta.handoff_root_virtual_path
      : "";
    if (!handoffRoot) {
      return null;
    }
    const normalizedRoot = handoffRoot.replace(/\/$/, "");
    const handoffIndexPath = `${normalizedRoot}/index.md`;
    const sourceThreadId = typeof meta.source_thread_id === "string" ? meta.source_thread_id : "";
    return {
      handoffRoot,
      handoffIndexPath,
      sourceThreadId,
      href: urlOfArtifact({ filepath: handoffIndexPath, threadId, isMock }),
    };
  }, [isMock, thread.values.handoff_meta, threadId]);

  useEffect(() => {
    if (!latestPersistedContextTokens) {
      return;
    }
    onContextTokens(latestPersistedContextTokens.tokenCount);
  }, [latestPersistedContextTokens, onContextTokens]);

  return (
    <ThreadContext.Provider value={{ thread, isMock, forkDraft, setForkDraft }}>
      <ChatBox
        threadId={threadId}
        isNewThread={isNewThread}
        extraDirectoryFiles={combinedArtifacts}
        onSubmitPlanRevision={handleSubmitPlanRevision}
      >
        <div className="relative flex size-full min-h-0 justify-between">
          <header
            className={cn(
              "absolute top-0 right-0 left-0 z-30 flex h-12 shrink-0 items-center px-4",
              isNewThread
                ? "bg-background/0 backdrop-blur-none"
                : "bg-background/80 shadow-xs backdrop-blur",
            )}
          >
            <div className="flex w-full items-center gap-2 text-sm font-medium">
              <ThreadTitle threadId={threadId} thread={thread} />
              {runningRun && (thread.isLoading || isExecutingPlan) && (
                <span
                  className="text-muted-foreground rounded bg-amber-500/10 px-2 py-0.5 text-xs font-normal"
                  title={`Resuming run ${runningRun.runId}`}
                >
                  resuming…
                </span>
              )}
              {queueControls.queueLength > 0 && (
                <span className="text-muted-foreground rounded bg-blue-500/10 px-2 py-0.5 text-xs font-normal">
                  {queueControls.queueLength} queued
                </span>
              )}
            </div>
          </header>
          <main className="flex min-h-0 max-w-full grow flex-col">
            <div className="flex size-full justify-center">
              <div className="flex size-full flex-col">
                {handoffBanner && !isNewThread && (
                  <div className="px-4 pt-14 pb-2">
                    <div className="bg-background/80 flex items-center justify-between gap-3 rounded-lg border px-3 py-2 backdrop-blur">
                      <div className="flex min-w-0 items-center gap-2">
                        <Badge variant="secondary" className="shrink-0">Handoff</Badge>
                        <div className="min-w-0 text-sm">
                          <div className="truncate font-medium">
                            This thread was created from a handoff package.
                          </div>
                          <div className="text-muted-foreground truncate text-xs">
                            {handoffBanner.sourceThreadId
                              ? `Source thread: ${handoffBanner.sourceThreadId} · ${handoffBanner.handoffRoot}`
                              : handoffBanner.handoffRoot}
                          </div>
                        </div>
                      </div>
                      <a
                        href={handoffBanner.href}
                        target="_blank"
                        rel="noreferrer"
                        className="text-sm font-medium whitespace-nowrap underline underline-offset-4"
                      >
                        <span className="inline-flex items-center gap-1">
                          Open handoff
                          <ArrowUpRightIcon className="size-3.5" />
                        </span>
                      </a>
                    </div>
                  </div>
                )}
                <MessageList
                  className={cn("size-full", !isNewThread && "pt-10", handoffBanner && !isNewThread && "pt-0")}
                  threadId={threadId}
                  thread={thread}
                  liveNotices={[...generationNotices, ...uiNotices]}
                  liveThinkingContent={liveThinkingContent}
                />
              </div>
            </div>
            <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center px-4">
              <div
                className={cn(
                  "relative w-full",
                  isNewThread && "-translate-y-[calc(50vh-96px)]",
                  isNewThread
                    ? "max-w-[50vw]"
                    : "max-w-(--container-width-md)",
                )}
              >
                <div className="mb-2 flex flex-col gap-2">
                  <QueuedMessageList
                    items={queueControls.queueItems}
                    onSteer={queueControls.steerQueued}
                    onDismiss={queueControls.dismissQueued}
                  />
                </div>
                {!isNewThread && mountedFolder && (
                  <div className="mb-1 flex justify-end px-1">
                    <MountFolderBadge
                      threadId={threadId}
                      className="bg-transparent border-none p-0 shadow-none backdrop-blur-none rounded-none"
                    />
                  </div>
                )}
                  <div className="relative">
                  {effectivePlanCreatedEvent && !clarificationPending && !isNewThread && effectivePlanEventKey !== hiddenPlanEventKey && !(effectivePlanCreatedEvent.auto_approved && settings.context.auto_mode === true) && (
                    <ExecutePlanPopup
                      event={effectivePlanCreatedEvent}
                      planHref={planReviewHref}
                      onExecute={handleExecutePlan}
                      onDismiss={handleKeepEditingPlan}
                      isExecuting={isExecutingPlan}
                    />
                  )}
                  {adaptationEvent && !isNewThread && (
                    <AdaptationNotice
                      event={adaptationEvent}
                      onRevisePlan={handleRevisePlan}
                      onDismiss={() => setAdaptationEvent(null)}
                    />
                  )}
                  {escalationEvent && !isNewThread && (
                    <ComplexityEscalationPopup
                      event={escalationEvent}
                      onSwitchToPlan={handleSwitchToPlan}
                      onContinueWork={handleContinueWork}
                      onDismiss={() => {
                        suppressedComplexityEscalationKeyRef.current = getComplexityEscalationKey(escalationEvent);
                        setEscalationEvent(null);
                      }}
                    />
                  )}
                  <InputBox
                    className={cn("bg-background/5 w-full")}
                    isNewThread={isNewThread}
                    threadId={threadId}
                    newChatHref="/workspace/chats/new"
                    autoFocus={isNewThread}
                    status={thread.isLoading ? "streaming" : "ready"}
                    context={settings.context}
                    extraHeader={
                      isNewThread && (
                        <Welcome
                          mode={settings.context.mode}
                        />
                      )
                    }
                    disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
                    contextTokenState={contextTokenState}
                    onContextChange={handleContextChange}
                    onCompaction={onCompaction}
                    onSubmit={handleSubmit}
                    onStop={handleStop}
                  />
                </div>
                {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" && (
                  <div className="text-muted-foreground/67 w-full translate-y-12 text-center text-xs">
                    {t.common.notAvailableInDemoMode}
                  </div>
                )}
              </div>
            </div>
          </main>
        </div>
      </ChatBox>
    </ThreadContext.Provider>
  );
}
