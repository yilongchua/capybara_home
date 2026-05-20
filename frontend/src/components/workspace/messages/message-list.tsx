import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { useEffect, useMemo } from "react";

import {
  Conversation,
  ConversationContent,
} from "@/components/ai-elements/conversation";
import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
import { asActivityTimelineState, mergeActivityEvents, useActivityContext } from "@/core/activity";
import type { LiveGenerationNotice } from "@/core/generation/hooks";
import { useI18n } from "@/core/i18n/hooks";
import {
  extractContentFromMessage,
  extractPresentFilesFromMessage,
  extractTextFromMessage,
  groupMessages,
  hasContent,
  hasPresentFiles,
  hasReasoning,
  hasReasoningInCurrentTurn,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import type { Subtask } from "@/core/tasks";
import { useSubtaskContext } from "@/core/tasks/context";
import { mergeSubtask } from "@/core/tasks/utils";
import type { AgentThreadState } from "@/core/threads";
import {
  resolveAdjacentBranch,
  resolveBranchCursor,
  resolveForkDraft,
} from "@/core/threads/fork";
import { env } from "@/env";
import { useCurrentTaskDescription } from "@/hooks/use-current-task-description";
import { cn } from "@/lib/utils";

import { CapybaraRunner } from "../chat-ui/capybara-runner";

import { ArtifactLink } from "./artifact-link";
import { useThread } from "./context";
import { MarkdownContent } from "./markdown-content";
import { MessageGroup } from "./message-group";
import { MessageListItem } from "./message-list-item";
import { MessageListSkeleton } from "./skeleton";
import { SubtaskCard } from "./subtask-card";

function buildSubtaskUpdates(
  messages: BaseStream<AgentThreadState>["messages"],
): Array<Partial<Subtask> & { id: string }> {
  const updates: Array<Partial<Subtask> & { id: string }> = [];
  const taskCallIds = new Set<string>();

  for (const message of messages) {
    if (message.type === "ai") {
      for (const toolCall of message.tool_calls ?? []) {
        if (toolCall.name !== "task" || !toolCall.id) {
          continue;
        }
        taskCallIds.add(toolCall.id);

        updates.push({
          id: toolCall.id,
          subagent_type: toolCall.args.subagent_type,
          description: toolCall.args.description,
          group_title:
            typeof toolCall.args.subagent_type === "string" && typeof toolCall.args.description === "string"
              ? `${toolCall.args.subagent_type}: ${toolCall.args.description}`
              : undefined,
          prompt: toolCall.args.prompt,
          status: "in_progress",
        });
      }
      continue;
    }

    if (
      message.type !== "tool" ||
      !message.tool_call_id ||
      !taskCallIds.has(message.tool_call_id)
    ) {
      continue;
    }

    const result = extractTextFromMessage(message);
    if (result.startsWith("Task Succeeded. Result:")) {
      updates.push({
        id: message.tool_call_id,
        status: "completed",
        result: result.split("Task Succeeded. Result:")[1]?.trim(),
      });
    } else if (result.startsWith("Task failed.")) {
      updates.push({
        id: message.tool_call_id,
        status: "failed",
        error: result.split("Task failed.")[1]?.trim(),
      });
    } else if (result.startsWith("Task timed out")) {
      updates.push({
        id: message.tool_call_id,
        status: "failed",
        error: result,
      });
    } else {
      updates.push({
        id: message.tool_call_id,
        status: "in_progress",
      });
    }
  }

  return updates;
}

function normalizeSubtask(task: Partial<Subtask> & { id: string }): Subtask {
  return {
    id: task.id,
    status: task.status ?? "in_progress",
    subagent_type: task.subagent_type ?? "task",
    description: task.description ?? "Running subtask",
    group_title: task.group_title,
    prompt: task.prompt ?? "",
    latestMessage: task.latestMessage,
    result: task.result,
    error: task.error,
    started_at: task.started_at,
    updated_at: task.updated_at,
    completed_at: task.completed_at,
  };
}

function resolveStatus(
  prevStatus: Subtask["status"] | undefined,
  nextStatus: Subtask["status"],
): Subtask["status"] {
  if ((prevStatus === "completed" || prevStatus === "failed") && nextStatus === "in_progress") {
    return prevStatus;
  }
  return nextStatus;
}

function extractSubagentTaskIds(messages: BaseStream<AgentThreadState>["messages"]) {
  const taskIds: string[] = [];
  const seenTaskIds = new Set<string>();

  for (const message of messages) {
    if (message.type !== "ai") {
      continue;
    }

    for (const toolCall of message.tool_calls ?? []) {
      if (toolCall.name !== "task" || !toolCall.id || seenTaskIds.has(toolCall.id)) {
        continue;
      }
      seenTaskIds.add(toolCall.id);
      taskIds.push(toolCall.id);
    }
  }

  return taskIds;
}

export function MessageList({
  className,
  threadId,
  thread,
  liveNotices = [],
  liveThinkingContent,
  paddingBottom = 160,
}: {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  liveNotices?: LiveGenerationNotice[];
  liveThinkingContent?: string;
  paddingBottom?: number;
}) {
  const { t } = useI18n();
  const { isMock, setForkDraft } = useThread();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(!thread.isLoading);
  const { tasks: contextTasks, setTasks } = useSubtaskContext();
  const { liveEvents: liveActivityEvents } = useActivityContext();
  const messages = thread.messages;
  const persistedReasoningInCurrentTurn = useMemo(
    () => hasReasoningInCurrentTurn(messages),
    [messages],
  );
  const showLiveThinking =
    Boolean(thread.isLoading && liveThinkingContent?.trim()) &&
    !persistedReasoningInCurrentTurn;
  const messageIndexById = useMemo(() => {
    const map = new Map<string, number>();
    messages.forEach((message, index) => {
      if (message.id) {
        map.set(message.id, index);
      }
    });
    return map;
  }, [messages]);
  const latestHumanMessageId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const current = messages[i];
      if (current?.type === "human" && current.id) {
        return current.id;
      }
    }
    return null;
  }, [messages]);
  const disableForkActions =
    thread.isLoading ||
    Boolean(isMock) ||
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
  const subtaskUpdates = useMemo(() => buildSubtaskUpdates(messages), [messages]);
  const subtasksById = useMemo(() => {
    const next: Record<string, Subtask> = {};
    for (const update of subtaskUpdates) {
      next[update.id] = normalizeSubtask({
        ...next[update.id],
        ...update,
        id: update.id,
      });
    }
    return next;
  }, [subtaskUpdates]);
  const currentTaskDescription = useCurrentTaskDescription(messages, subtasksById);
  const allActivityEvents = useMemo(
    () =>
      mergeActivityEvents(
        asActivityTimelineState(thread.values.activity_timeline),
        liveActivityEvents,
      ),
    [liveActivityEvents, thread.values.activity_timeline],
  );
  const hasRecentLiveRunSignal = useMemo(() => {
    const now = Date.now() / 1000;
    return allActivityEvents.some((event) => {
      const kind = (event.kind ?? "").toLowerCase();
      const isStartLike =
        kind.includes("start") ||
        kind.includes("running") ||
        kind.includes("work_");
      const isEndLike =
        kind.includes("completed") ||
        kind.includes("failed") ||
        kind.includes("timed_out") ||
        kind.includes("cancel");
      const recent = now - event.timestamp < 120;
      return isStartLike && !isEndLike && recent;
    });
  }, [allActivityEvents]);
  const activeActivityLine = useMemo(() => {
    for (let i = allActivityEvents.length - 1; i >= 0; i--) {
      const line = allActivityEvents[i]?.line?.trim();
      if (line) {
        return line;
      }
    }
    return undefined;
  }, [allActivityEvents]);
  const activityLinesByAssistantMessageId = useMemo(() => {
    const byId: Record<string, string[]> = {};
    for (const event of allActivityEvents) {
      if (!event.assistant_message_id || !event.line) {
        continue;
      }
      const next = byId[event.assistant_message_id] ?? [];
      if (next[next.length - 1] === event.line) {
        byId[event.assistant_message_id] = next;
        continue;
      }
      byId[event.assistant_message_id] = [...next, event.line];
    }
    return byId;
  }, [allActivityEvents]);

  useEffect(() => {
    if (subtaskUpdates.length === 0) {
      return;
    }

    setTasks((prev) => {
      let next = prev;

      for (const update of subtaskUpdates) {
        const previousTask = next[update.id];
        const rawMergedTask = normalizeSubtask({
          ...previousTask,
          ...update,
          id: update.id,
        });
        const mergedTask = {
          ...rawMergedTask,
          status: resolveStatus(previousTask?.status, rawMergedTask.status),
          completed_at:
            rawMergedTask.status === "in_progress"
              ? previousTask?.completed_at
              : rawMergedTask.completed_at,
        };

        if (
          previousTask?.status === mergedTask.status &&
          previousTask.subagent_type === mergedTask.subagent_type &&
          previousTask.description === mergedTask.description &&
          previousTask.prompt === mergedTask.prompt &&
          previousTask.result === mergedTask.result &&
          previousTask.error === mergedTask.error &&
          previousTask.latestMessage === mergedTask.latestMessage &&
          previousTask.started_at === mergedTask.started_at &&
          previousTask.updated_at === mergedTask.updated_at &&
          previousTask.completed_at === mergedTask.completed_at
        ) {
          continue;
        }

        if (next === prev) {
          next = { ...prev };
        }
        next[update.id] = mergedTask;
      }

      return next;
    });
  }, [setTasks, subtaskUpdates]);

  if (thread.isThreadLoading && messages.length === 0) {
    return <MessageListSkeleton />;
  }
  return (
    <Conversation
      className={cn("flex size-full flex-col justify-center", className)}
    >
      <ConversationContent className="mx-auto w-full max-w-(--container-width-md) gap-8 pt-12">
        {groupMessages(messages, (group) => {
          if (group.type === "human" || group.type === "assistant") {
            return group.messages.map((msg) => {
              const inlineLines =
                msg.type === "ai" && msg.id
                  ? (activityLinesByAssistantMessageId[msg.id] ?? [])
                  : [];
              return (
                <div key={`${group.id}/${msg.id}`} className="space-y-2">
                  {inlineLines.length > 0 && (
                    <div className="text-muted-foreground rounded-md border bg-muted/30 px-3 py-2 text-xs">
                      {inlineLines.slice(-4).map((line, index) => (
                        <div key={`${msg.id}-line-${index}`}>{line}</div>
                      ))}
                    </div>
                  )}
                  <MessageListItem
                    message={msg}
                    isLoading={thread.isLoading}
                    branchControl={(() => {
                      const metadata = thread.getMessagesMetadata(
                        msg,
                        msg.id ? messageIndexById.get(msg.id) : undefined,
                      );
                      const cursor = resolveBranchCursor(
                        metadata?.branchOptions,
                        metadata?.branch,
                      );
                      if (!cursor) {
                        return undefined;
                      }
                      return {
                        currentIndex: cursor.index,
                        total: cursor.total,
                        onPrevious: () => {
                          const prev = resolveAdjacentBranch(
                            metadata?.branchOptions,
                            metadata?.branch,
                            "prev",
                          );
                          if (prev) {
                            thread.setBranch(prev);
                          }
                        },
                        onNext: () => {
                          const next = resolveAdjacentBranch(
                            metadata?.branchOptions,
                            metadata?.branch,
                            "next",
                          );
                          if (next) {
                            thread.setBranch(next);
                          }
                        },
                      };
                    })()}
                    canEditFork={(() => {
                      if (msg.type !== "human" || disableForkActions || !setForkDraft) {
                        return false;
                      }
                      if (!msg.id || msg.id === latestHumanMessageId) {
                        return false;
                      }
                      const metadata = thread.getMessagesMetadata(
                        msg,
                        msg.id ? messageIndexById.get(msg.id) : undefined,
                      );
                      return Boolean(resolveForkDraft(msg, metadata));
                    })()}
                    onEditFork={() => {
                      if (!setForkDraft || msg.type !== "human") {
                        return;
                      }
                      const metadata = thread.getMessagesMetadata(
                        msg,
                        msg.id ? messageIndexById.get(msg.id) : undefined,
                      );
                      const nextDraft = resolveForkDraft(msg, metadata);
                      if (nextDraft) {
                        setForkDraft(nextDraft);
                      }
                    }}
                  />
                </div>
              );
            });
          } else if (group.type === "assistant:clarification") {
            const message = group.messages[0];
            if (message && hasContent(message)) {
              return (
                <MarkdownContent
                  key={group.id}
                  content={extractContentFromMessage(message)}
                  isLoading={thread.isLoading}
                  rehypePlugins={rehypePlugins}
                />
              );
            }
            return null;
          } else if (group.type === "assistant:present-files") {
            const files: string[] = [];
            for (const message of group.messages) {
              if (hasPresentFiles(message)) {
                const presentFiles = extractPresentFilesFromMessage(message);
                files.push(...presentFiles);
              }
            }
            return (
              <div className="w-full" key={group.id}>
                {group.messages[0] && hasContent(group.messages[0]) && (
                  <MarkdownContent
                    content={extractContentFromMessage(group.messages[0])}
                    isLoading={thread.isLoading}
                    rehypePlugins={rehypePlugins}
                    className="mb-2"
                  />
                )}
                {files.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-1">
                    {files.map((file) => (
                      <ArtifactLink key={file} filepath={file} threadId={threadId} />
                    ))}
                  </div>
                )}
              </div>
            );
          } else if (group.type === "assistant:subagent") {
            const taskIds = extractSubagentTaskIds(group.messages);
            const results: React.ReactNode[] = [];
            for (const message of group.messages.filter(
              (message) => message.type === "ai",
            )) {
              if (hasReasoning(message)) {
                results.push(
                    <MessageGroup
                      key={"thinking-group-" + message.id}
                      messages={[message]}
                      isLoading={thread.isLoading}
                  />,
                );
              }
              results.push(
                <div
                  key={`subtask-count-${message.id}`}
                  className="text-muted-foreground font-norma pt-2 text-sm"
                >
                  {t.subtasks.executing(taskIds.length)}
                </div>,
              );
              const messageTaskIds = (message.tool_calls ?? [])
                .filter((toolCall) => toolCall.name === "task" && Boolean(toolCall.id))
                .map((toolCall) => toolCall.id!);
              for (const taskId of messageTaskIds) {
                const task = mergeSubtask(subtasksById[taskId], contextTasks[taskId]);
                if (!task) {
                  continue;
                }
                results.push(
                  <SubtaskCard
                    key={"task-group-" + taskId}
                    task={task}
                    isLoading={thread.isLoading}
                    isStaleRunning={task.status === "in_progress" && !hasRecentLiveRunSignal}
                  />,
                );
              }
            }
            return (
              <div
                key={"subtask-group-" + group.id}
                className="relative z-1 flex flex-col gap-2"
              >
                {results}
              </div>
            );
          }
          return (
            <MessageGroup
              key={"group-" + group.id}
              messages={group.messages}
              isLoading={thread.isLoading}
            />
          );
        })}
        {thread.isLoading && (
          <div className="text-muted-foreground rounded-md border bg-muted/20 px-3 py-2 text-xs">
            {activeActivityLine ?? (
              <CapybaraRunner className="my-0 text-xs" taskDescription={currentTaskDescription} />
            )}
          </div>
        )}
        {showLiveThinking && liveThinkingContent && (
          <Reasoning isStreaming className="rounded-lg border px-3 py-1">
            <ReasoningTrigger />
            <ReasoningContent>{liveThinkingContent}</ReasoningContent>
          </Reasoning>
        )}
        {liveNotices.map((notice) => (
          <MarkdownContent
            key={notice.id}
            content={notice.content}
            isLoading={false}
            rehypePlugins={rehypePlugins}
            className="my-3"
          />
        ))}
        <div style={{ height: `${paddingBottom}px` }} />
      </ConversationContent>
    </Conversation>
  );
}
