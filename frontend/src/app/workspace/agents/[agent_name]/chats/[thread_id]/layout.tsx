"use client";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { DirectoryProvider } from "@/components/workspace/artifacts";
import { ActivityProvider } from "@/core/activity";
import { SubtasksProvider } from "@/core/tasks/context";
import { ExecutionTraceProvider } from "@/core/traces";

export default function AgentChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <SubtasksProvider>
      <ActivityProvider>
        <ExecutionTraceProvider>
          <DirectoryProvider>
            <PromptInputProvider>{children}</PromptInputProvider>
          </DirectoryProvider>
        </ExecutionTraceProvider>
      </ActivityProvider>
    </SubtasksProvider>
  );
}
