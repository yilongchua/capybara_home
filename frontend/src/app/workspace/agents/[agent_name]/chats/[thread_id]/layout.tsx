"use client";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { DirectoryProvider } from "@/components/workspace/artifacts";
import { ActivityProvider } from "@/core/activity";
import { DreamyProvider } from "@/core/dreamy/context";
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
            <PromptInputProvider>
              <DreamyProvider>{children}</DreamyProvider>
            </PromptInputProvider>
          </DirectoryProvider>
        </ExecutionTraceProvider>
      </ActivityProvider>
    </SubtasksProvider>
  );
}
