"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
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
import { PhaseProgress } from "@/components/workspace/phase-progress";
import { QueuedMessageList } from "@/components/workspace/queued-message-list";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { Welcome } from "@/components/workspace/welcome";
import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/dreamy/api";
import { useMountedFolder } from "@/core/dreamy/hooks/use-mounted-folder";
import { useMountedFolderFiles } from "@/core/dreamy/hooks/use-mounted-folder-files";
import { useGenerationCompletions } from "@/core/generation/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { useLocalSettings } from "@/core/settings";
import type { ForkDraft } from "@/core/threads/fork";
import type { ComplexityEscalationEvent, PlanAdaptedEvent, PlanCreatedEvent } from "@/core/threads/hooks";
import { useThreadStream } from "@/core/threads/hooks";
import { useContextTokens } from "@/core/threads/use-context-tokens";
import { useRunningRun } from "@/core/threads/use-running-run";
import { useThreadNotification } from "@/core/threads/use-thread-notification";
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
  const { runningRun } = useRunningRun(isNewThread ? null : threadId);
  const { onFinish } = useThreadNotification();

  const [planCreatedEvent, setPlanCreatedEvent] = useState<PlanCreatedEvent | null>(null);
  const [adaptationEvent, setAdaptationEvent] = useState<PlanAdaptedEvent | null>(null);
  const [escalationEvent, setEscalationEvent] = useState<ComplexityEscalationEvent | null>(null);
  const [forkDraft, setForkDraft] = useState<ForkDraft | null>(null);
  const [pendingExecutePlan, setPendingExecutePlan] = useState(false);
  const suppressedAutoExecutePlanKeyRef = useRef<string | null>(null);
  const executePlanRetryCountRef = useRef(0);

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
    onComplexityEscalation: (event) => setEscalationEvent(event),
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

  const handleExecutePlan = useCallback(() => {
    const run = async () => {
      try {
        const eventKey = planEventKey(planCreatedEvent);
        if (eventKey && suppressedAutoExecutePlanKeyRef.current === eventKey) {
          return;
        }
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
            plan_id: planCreatedEvent?.plan_id,
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
          }
          throw new Error(raw);
        }
        executePlanRetryCountRef.current = 0;
        setPendingExecutePlan(false);
        setPlanCreatedEvent(null);
        await sendMessage(
          threadId,
          { text: "", files: [] },
          { execute_approved_plan: true },
          { mode: "work" },
        );
      } catch (error) {
        // Keep popup open so user can retry execute.
        console.error("Failed to execute plan:", error);
        const detail = error instanceof Error ? error.message : "Unknown error";
        toast.error(`Failed to execute plan. ${detail}`);
        setPendingExecutePlan(false);
      }
    };
    void run();
  }, [isInFlightRunConflict, pendingExecutePlan, planCreatedEvent, planEventKey, sendMessage, threadId, thread.isLoading]);

  // Auto-trigger Execute Plan when a plan is created and auto_mode is on.
  useEffect(() => {
    if (planCreatedEvent && settings.context.auto_mode === true) {
      const eventKey = planEventKey(planCreatedEvent);
      if (eventKey && suppressedAutoExecutePlanKeyRef.current === eventKey) {
        return;
      }
      handleExecutePlan();
    }
  }, [planCreatedEvent, settings.context.auto_mode, handleExecutePlan, planEventKey]);

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
    const eventKey = planEventKey(planCreatedEvent);
    if (eventKey) {
      suppressedAutoExecutePlanKeyRef.current = eventKey;
    }
    setSettings("context", { ...settings.context, mode: "plan" });
    executePlanRetryCountRef.current = 0;
    setPendingExecutePlan(false);
    setPlanCreatedEvent(null);
  }, [planCreatedEvent, planEventKey, setSettings, settings.context]);

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
    setEscalationEvent(null);
    setSettings("context", { ...settings.context, mode: "plan" });
  }, [setEscalationEvent, setSettings, settings.context]);

  const handleContinueWork = useCallback(() => {
    setEscalationEvent(null);
  }, []);

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
      const maybeIntent = normalizeIntent(message.text ?? "");
      const planStatus = String(thread.values.plan?.status ?? "").toLowerCase();
      const hasPlanReadyForExecution = planStatus === "draft";
      if (
        !thread.isLoading &&
        hasPlanReadyForExecution &&
        (!message.files || message.files.length === 0) &&
        EXECUTE_PLAN_INTENTS.has(maybeIntent)
      ) {
        handleExecutePlan();
        return;
      }
      void sendMessage(threadId, message, undefined, options);
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
        extraArtifacts={combinedArtifacts}
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
              {runningRun && thread.isLoading && (
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
              <MessageList
                className={cn("size-full", !isNewThread && "pt-10")}
                threadId={threadId}
                thread={thread}
                liveNotices={generationNotices}
                liveThinkingContent={liveThinkingContent}
              />
            </div>
            <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center px-4">
              <div
                className={cn(
                  "relative w-full",
                  isNewThread && "-translate-y-[calc(50vh-96px)]",
                  isNewThread
                    ? "max-w-(--container-width-sm)"
                    : "max-w-(--container-width-md)",
                )}
              >
                <div className="mb-2 flex flex-col gap-2">
                  <PhaseProgress phaseExecution={thread.values.phase_execution} />
                  <TodoList
                    className="bg-background/5"
                    todos={thread.values.todos ?? []}
                    hidden={!thread.values.todos || thread.values.todos.length === 0}
                  />
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
                  {planCreatedEvent && !isNewThread && (
                    <ExecutePlanPopup
                      event={planCreatedEvent}
                      onExecute={handleExecutePlan}
                      onDismiss={handleKeepEditingPlan}
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
                      onDismiss={() => setEscalationEvent(null)}
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
