"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { MountFolderBadge } from "@/components/workspace/chat-ui/mount-folder-badge";
import { DreamyBox } from "@/components/workspace/dreamy/dreamy-box";
import { InputBox, type InputBoxSubmitOptions } from "@/components/workspace/input-box";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { QueuedMessageList } from "@/components/workspace/queued-message-list";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/dreamy/api";
import { useLocalSettings } from "@/core/settings";
import type { ForkDraft } from "@/core/threads/fork";
import { useThreadStream } from "@/core/threads/hooks";
import { uuid } from "@/core/utils/uuid";

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

export default function DreamyPage() {
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();
  const router = useRouter();
  const [settings, setSettings] = useLocalSettings();

  const [threadId] = useState(() =>
    threadIdFromPath === "new" ? uuid() : threadIdFromPath,
  );
  const [isNewThread, setIsNewThread] = useState(() => threadIdFromPath === "new");
  const [forkDraft, setForkDraft] = useState<ForkDraft | null>(null);

  const [thread, sendMessage, liveThinkingContent, queueControls] = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    context: settings.context,
    onStart: () => {
      setIsNewThread(false);
      router.replace(`/workspace/dreamy/${threadId}`);
    },
  });
  const handleExecutePlan = useCallback(() => {
    const run = async () => {
      const response = await fetch(`${getBackendBaseURL()}${api.threads.executePlan(threadId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!response.ok) {
        const detail = await response.text();
        toast.error(`Failed to execute plan. ${detail}`);
        return;
      }
      await sendMessage(
        threadId,
        { text: "", files: [] },
        { dreamy_mode: true, execute_approved_plan: true },
        { mode: "work" },
      );
    };
    void run();
  }, [sendMessage, threadId]);
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
      void sendMessage(threadId, message, { dreamy_mode: true }, options);
    },
    [handleExecutePlan, sendMessage, thread.isLoading, thread.values.plan?.status, threadId],
  );

  const handleStop = useCallback(async () => {
    await queueControls.stop();
  }, [queueControls]);

  useEffect(() => {
    document.title = "Dreamy — Capybara";
  }, []);

  return (
    <ThreadContext.Provider value={{ thread, isMock: false, forkDraft, setForkDraft }}>
      <DreamyBox threadId={threadId} isNewThread={isNewThread}>
        <div className="relative flex size-full min-h-0 flex-col">
          <header className="absolute top-0 right-0 left-0 z-30 flex h-12 shrink-0 items-center bg-background/80 px-4 shadow-xs backdrop-blur">
            <div className="flex w-full items-center text-sm font-medium">
              <ThreadTitle threadId={threadId} thread={thread} />
            </div>
            {queueControls.queueLength > 0 && (
              <span className="text-muted-foreground rounded bg-blue-500/10 px-2 py-0.5 text-xs font-normal">
                {queueControls.queueLength} queued
              </span>
            )}
          </header>
          <main className="flex min-h-0 max-w-full grow flex-col">
            <MessageList
              className="size-full pt-10"
              threadId={threadId}
              thread={thread}
              liveNotices={[]}
              liveThinkingContent={liveThinkingContent}
            />
          </main>
          <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center px-4">
            <div className="relative w-full max-w-(--container-width-md)">
              {!isNewThread && (
                <div className="absolute -top-9 left-2 z-10">
                  <MountFolderBadge threadId={threadId} />
                </div>
              )}
              <div className="mb-2">
                <QueuedMessageList
                  items={queueControls.queueItems}
                  onSteer={queueControls.steerQueued}
                  onDismiss={queueControls.dismissQueued}
                />
              </div>
              <InputBox
                className="bg-background/5 w-full -translate-y-4"
                dreamy
                isNewThread={isNewThread}
                threadId={threadId}
                newChatHref="/workspace/dreamy/new"
                autoFocus={isNewThread}
                status={thread.isLoading ? "streaming" : "ready"}
                context={{ ...settings.context, mode: "work" }}
                onContextChange={(context) => setSettings("context", { ...context, mode: "work" })}
                onSubmit={handleSubmit}
                onStop={handleStop}
              />
            </div>
          </div>
        </div>
      </DreamyBox>
    </ThreadContext.Provider>
  );
}
