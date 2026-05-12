"use client";

import { useParams } from "next/navigation";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { ActivityProvider } from "@/core/activity";
import { SubtasksProvider } from "@/core/tasks/context";
import { useThreadRemount } from "@/core/threads/use-thread-remount";
import { ExecutionTraceProvider } from "@/core/traces";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { thread_id } = useParams<{ thread_id: string }>();
  const generation = useThreadRemount(thread_id);

  return (
    <SubtasksProvider key={generation}>
      <ActivityProvider>
        <ExecutionTraceProvider>
          <ArtifactsProvider>
            <PromptInputProvider>{children}</PromptInputProvider>
          </ArtifactsProvider>
        </ExecutionTraceProvider>
      </ActivityProvider>
    </SubtasksProvider>
  );
}
