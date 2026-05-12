"use client";

import { useParams } from "next/navigation";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { ActivityProvider } from "@/core/activity";
import { DreamyProvider } from "@/core/dreamy/context";
import { DreamyErrorBoundary } from "@/core/dreamy/error-boundary";
import { useThreadRemount } from "@/core/threads/use-thread-remount";
import { SubtasksProvider } from "@/core/tasks/context";
import { ExecutionTraceProvider } from "@/core/traces";

export default function DreamyLayout({ children }: { children: React.ReactNode }) {
  const { thread_id } = useParams<{ thread_id: string }>();
  const generation = useThreadRemount(thread_id);

  return (
    <SubtasksProvider key={generation}>
      <ActivityProvider>
        <ExecutionTraceProvider>
          <ArtifactsProvider>
            <PromptInputProvider>
              <DreamyErrorBoundary><DreamyProvider>{children}</DreamyProvider></DreamyErrorBoundary>
            </PromptInputProvider>
          </ArtifactsProvider>
        </ExecutionTraceProvider>
      </ActivityProvider>
    </SubtasksProvider>
  );
}
