import {
  BotIcon,
  CheckCircleIcon,
  ChevronUp,
  DatabaseIcon,
  ClipboardListIcon,
  GlobeIcon,
  HammerIcon,
  TerminalIcon,
  XCircleIcon,
} from "lucide-react";
import { useMemo, useState, type ReactElement } from "react";
import { Streamdown } from "streamdown";

import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import { Shimmer } from "@/components/ai-elements/shimmer";
import { Button } from "@/components/ui/button";
import { ShineBorder } from "@/components/ui/shine-border";
import { useI18n } from "@/core/i18n/hooks";
import { hasToolCalls } from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import { useLocalSettings } from "@/core/settings";
import { streamdownPluginsWithWordAnimation } from "@/core/streamdown";
import type { Subtask } from "@/core/tasks";
import {
  lastToolCall,
  resolveToolIconKey,
  type ToolIconKey,
} from "@/core/tools/presentation";
import { explainLastToolCall } from "@/core/tools/utils";
import { cn } from "@/lib/utils";

import { CapybaraRunner } from "../chat-ui/capybara-runner";
import { CitationLink } from "../citations/citation-link";
import { FlipDisplay } from "../flip-display";


import { MarkdownContent } from "./markdown-content";

export function SubtaskCard({
  className,
  task,
  isLoading,
  isStaleRunning = false,
}: {
  className?: string;
  task: Subtask;
  isLoading: boolean;
  isStaleRunning?: boolean;
}) {
  const { t } = useI18n();
  const [settings] = useLocalSettings();
  const [collapsed, setCollapsed] = useState(true);
  const rehypePlugins = useRehypeSplitWordsIntoSpans(!isLoading);
  const taskIcon = useMemo(() => {
    const toolCall = lastToolCall(task.latestMessage);
    return resolveToolIconKey(
      toolCall?.name ?? task.subagent_type ?? "task",
      settings.toolPresentation.iconByTool,
    );
  }, [settings.toolPresentation.iconByTool, task.latestMessage, task.subagent_type]);
  const taskLabel = useMemo(
    () => task.group_title?.trim() || `${task.subagent_type}: ${task.description}`,
    [task.description, task.group_title, task.subagent_type],
  );
  const taskIconNode = useMemo(() => {
    const iconByType: Record<ToolIconKey, ReactElement> = {
      web: <GlobeIcon className="size-4" />,
      vault: <DatabaseIcon className="size-4" />,
      assistant: <BotIcon className="size-4" />,
      terminal: <TerminalIcon className="size-4" />,
      tool: <HammerIcon className="size-4" />,
    };
    return iconByType[taskIcon] ?? <ClipboardListIcon className="size-4" />;
  }, [taskIcon]);
  const icon = useMemo(() => {
    if (task.status === "completed") {
      return <CheckCircleIcon className="size-3" />;
    } else if (task.status === "failed") {
      return <XCircleIcon className="size-3 text-red-500" />;
    } else if (task.status === "in_progress") {
      return isStaleRunning
        ? <ClipboardListIcon className="size-3" />
        : <CapybaraRunner actor="baby_capy" size="sm" taskDescription={taskLabel} />;
    }
  }, [isStaleRunning, task.status, taskLabel]);
  return (
    <ChainOfThought
      className={cn("relative w-full gap-2 rounded-lg border py-0", className)}
      open={!collapsed}
    >
      <div
        className={cn(
          "ambilight z-[-1]",
          task.status === "in_progress" ? "enabled" : "",
        )}
      ></div>
      {task.status === "in_progress" && !isStaleRunning && (
        <>
          <ShineBorder
            borderWidth={1.5}
            shineColor={["#A07CFE", "#FE8FB5", "#FFBE7B"]}
          />
        </>
      )}
      <div className="bg-background/95 flex w-full flex-col rounded-lg">
        <div className="flex w-full items-center justify-between p-0.5">
          <Button
            className="w-full items-start justify-start text-left"
            variant="ghost"
            onClick={() => setCollapsed(!collapsed)}
          >
            <div className="flex w-full items-center justify-between">
              <ChainOfThoughtStep
                className="font-normal"
                label={
                  task.status === "in_progress" ? (
                    isStaleRunning
                      ? taskLabel
                      : (
                        <Shimmer duration={3} spread={3}>
                          {taskLabel}
                        </Shimmer>
                      )
                  ) : (
                    taskLabel
                  )
                }
                icon={taskIconNode}
              ></ChainOfThoughtStep>
              <div className="flex items-center gap-1">
                {collapsed && (
                  <div
                    className={cn(
                      "text-muted-foreground flex items-center gap-1 text-xs font-normal",
                      task.status === "failed" ? "text-red-500 opacity-67" : "",
                    )}
                  >
                    {icon}
                    <FlipDisplay
                      className="max-w-[420px] truncate pb-1"
                      uniqueKey={task.latestMessage?.id ?? ""}
                    >
                      {task.status === "in_progress" &&
                      task.latestMessage &&
                      hasToolCalls(task.latestMessage) &&
                      !isStaleRunning
                        ? explainLastToolCall(task.latestMessage, t)
                        : task.status === "in_progress" && isStaleRunning
                          ? "Waiting for run execution..."
                        : t.subtasks[task.status]}
                    </FlipDisplay>
                  </div>
                )}
                <ChevronUp
                  className={cn(
                    "text-muted-foreground size-4",
                    !collapsed ? "" : "rotate-180",
                  )}
                />
              </div>
            </div>
          </Button>
        </div>
        <ChainOfThoughtContent className="px-4 pb-4">
          {task.prompt && (
            <ChainOfThoughtStep
              label={
                <Streamdown
                  {...streamdownPluginsWithWordAnimation}
                  components={{ a: CitationLink }}
                >
                  {task.prompt}
                </Streamdown>
              }
            ></ChainOfThoughtStep>
          )}
          {task.status === "in_progress" &&
            task.latestMessage &&
            hasToolCalls(task.latestMessage) &&
            !isStaleRunning && (
              <ChainOfThoughtStep
                label={t.subtasks.in_progress}
                icon={<CapybaraRunner actor="baby_capy" size="sm" taskDescription={explainLastToolCall(task.latestMessage, t)} />}
              >
                {explainLastToolCall(task.latestMessage, t)}
              </ChainOfThoughtStep>
            )}
          {task.status === "completed" && (
            <>
              <ChainOfThoughtStep
                label={t.subtasks.completed}
                icon={<CheckCircleIcon className="size-4" />}
              ></ChainOfThoughtStep>
              <ChainOfThoughtStep
                label={
                  task.result ? (
                    <MarkdownContent
                      content={task.result}
                      isLoading={false}
                      rehypePlugins={rehypePlugins}
                    />
                  ) : null
                }
              ></ChainOfThoughtStep>
            </>
          )}
          {task.status === "failed" && (
            <ChainOfThoughtStep
              label={<div className="text-red-500">{task.error}</div>}
              icon={<XCircleIcon className="size-4 text-red-500" />}
            ></ChainOfThoughtStep>
          )}
        </ChainOfThoughtContent>
      </div>
    </ChainOfThought>
  );
}
