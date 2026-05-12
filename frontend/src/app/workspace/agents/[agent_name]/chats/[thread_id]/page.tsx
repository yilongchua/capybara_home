"use client";

import { BotIcon, PlusSquare } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { AgentWelcome } from "@/components/workspace/agent-welcome";
import { ChatBox, useThreadChat } from "@/components/workspace/chats";
import {
  InputBox,
  type InputBoxSubmitOptions,
} from "@/components/workspace/input-box";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { QueuedMessageList } from "@/components/workspace/queued-message-list";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { Tooltip } from "@/components/workspace/tooltip";
import { useAgent } from "@/core/agents";
import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/dreamy/api";
import { useGenerationCompletions } from "@/core/generation/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings } from "@/core/settings";
import type { ForkDraft } from "@/core/threads/fork";
import { useThreadStream } from "@/core/threads/hooks";
import { textOfMessage } from "@/core/threads/utils";
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

export default function AgentChatPage() {
  const { agent_name } = useParams<{
    agent_name: string;
  }>();
  const { threadId, isNewThread, setIsNewThread } = useThreadChat();

  return (
    <AgentChatPageContent
      key={threadId}
      agentName={agent_name}
      isNewThread={isNewThread}
      setIsNewThread={setIsNewThread}
      threadId={threadId}
    />
  );
}

function AgentChatPageContent({
  agentName,
  threadId,
  isNewThread,
  setIsNewThread,
}: {
  agentName: string;
  threadId: string;
  isNewThread: boolean;
  setIsNewThread: (value: boolean) => void;
}) {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();
  const router = useRouter();
  const { agent } = useAgent(agentName);
  const [forkDraft, setForkDraft] = useState<ForkDraft | null>(null);
  const { notices: generationNotices, artifactPaths: generationArtifacts } =
    useGenerationCompletions(threadId);
  const { showNotification } = useNotification();
  const [thread, sendMessage, , queueControls] = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    context: { ...settings.context, agent_name: agentName },
    onStart: () => {
      setIsNewThread(false);
      history.replaceState(
        null,
        "",
        `/workspace/agents/${agentName}/chats/${threadId}`,
      );
    },
    onFinish: (state) => {
      if (document.hidden || !document.hasFocus()) {
        let body = "Conversation finished";
        const lastMessage = state.messages[state.messages.length - 1];
        if (lastMessage) {
          const textContent = textOfMessage(lastMessage);
          if (textContent) {
            body =
              textContent.length > 200
                ? textContent.substring(0, 200) + "..."
                : textContent;
          }
        }
        showNotification(state.title, { body });
      }
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
        { agent_name: agentName, execute_approved_plan: true },
        { mode: "work" },
      );
    };
    void run();
  }, [agentName, sendMessage, threadId]);

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
      void sendMessage(threadId, message, { agent_name: agentName }, options);
    },
    [agentName, handleExecutePlan, sendMessage, thread.isLoading, thread.values.plan?.status, threadId],
  );

  const handleStop = useCallback(async () => {
    await queueControls.stop();
  }, [queueControls]);

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
      { agent_name: agentName },
      { mode: "plan" },
    );
  }, [agentName, sendMessage, setSettings, settings.context, thread.values.plan?.title, threadId]);

  return (
    <ThreadContext.Provider value={{ thread, forkDraft, setForkDraft }}>
      <ChatBox
        threadId={threadId}
        extraArtifacts={generationArtifacts}
        onSubmitPlanRevision={handleSubmitPlanRevision}
      >
        <div className="relative flex size-full min-h-0 justify-between">
          <header
            className={cn(
              "absolute top-0 right-0 left-0 z-30 flex h-12 shrink-0 items-center gap-2 px-4",
              isNewThread
                ? "bg-background/0 backdrop-blur-none"
                : "bg-background/80 shadow-xs backdrop-blur",
            )}
          >
            <div className="flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1">
              <BotIcon className="text-primary h-3.5 w-3.5" />
              <span className="text-xs font-medium">
                {agent?.name ?? agentName}
              </span>
            </div>

            <div className="flex w-full items-center text-sm font-medium">
              <ThreadTitle threadId={threadId} thread={thread} />
            </div>
            {queueControls.queueLength > 0 && (
              <span className="text-muted-foreground rounded bg-blue-500/10 px-2 py-0.5 text-xs font-normal">
                {queueControls.queueLength} queued
              </span>
            )}
            <div className="mr-4 flex items-center">
              <Tooltip content={t.agents.newChat}>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    router.push(`/workspace/agents/${agentName}/chats/new`);
                  }}
                >
                  <PlusSquare /> {t.agents.newChat}
                </Button>
              </Tooltip>
            </div>
          </header>

          <main className="flex min-h-0 max-w-full grow flex-col">
            <div className="flex size-full justify-center">
              <MessageList
                className={cn("size-full", !isNewThread && "pt-10")}
                threadId={threadId}
                thread={thread}
                liveNotices={generationNotices}
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
                <div className="absolute -top-4 right-0 left-0 z-0">
                  <div className="absolute right-0 bottom-0 left-0">
                    <TodoList
                      className="bg-background/5"
                      todos={thread.values.todos ?? []}
                      hidden={
                        !thread.values.todos || thread.values.todos.length === 0
                      }
                    />
                  </div>
                </div>
                <div className="mb-2">
                  <QueuedMessageList
                    items={queueControls.queueItems}
                    onSteer={queueControls.steerQueued}
                    onDismiss={queueControls.dismissQueued}
                  />
                </div>

                <InputBox
                  className={cn("bg-background/5 w-full -translate-y-4")}
                  isNewThread={isNewThread}
                  threadId={threadId}
                  newChatHref={`/workspace/agents/${agentName}/chats/new`}
                  autoFocus={isNewThread}
                  status={thread.isLoading ? "streaming" : "ready"}
                  context={settings.context}
                  extraHeader={
                    isNewThread && (
                      <AgentWelcome agent={agent} agentName={agentName} />
                    )
                  }
                  disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
                  onContextChange={(context) => setSettings("context", context)}
                  onSubmit={handleSubmit}
                  onStop={handleStop}
                />
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
