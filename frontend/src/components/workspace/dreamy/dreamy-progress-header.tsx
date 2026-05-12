"use client";

import { AlertTriangleIcon, ClockIcon, PauseIcon, PlayIcon, SquareIcon } from "lucide-react";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/dreamy/api";
import { MS_PER_MINUTE } from "@/core/dreamy/constants";
import { useDreamyProgress } from "@/core/dreamy/hooks/use-dreamy-progress";
import { cn } from "@/lib/utils";

function formatTimeLeft(until: Date | null): string {
  if (!until) return "—";
  const ms = until.getTime() - Date.now();
  if (ms <= 0) return "finishing...";
  const mins = Math.ceil(ms / MS_PER_MINUTE);
  return mins < 60 ? `~${mins} min left` : `~${Math.ceil(mins / 60)} hr left`;
}

export function DreamyProgressHeader({
  threadId,
  isStreaming,
  onPause,
  onResume,
  onStop,
}: {
  threadId: string;
  isStreaming: boolean;
  onPause: () => void;
  onResume: () => void;
  onStop?: () => void;
}) {
  const {
    completedRows, totalRows, pctDone,
    estimatedCompletion, activeStepDescription,
    phase, failedRows, executorActive,
  } = useDreamyProgress(threadId);

  const handleExecutorPause = useCallback(async () => {
    await fetch(`${getBackendBaseURL()}${api.threads.dreamy.executor.pause(threadId)}`, {
      method: "POST",
    });
  }, [threadId]);

  const handleExecutorStop = useCallback(async () => {
    await fetch(`${getBackendBaseURL()}${api.threads.dreamy.executor.stop(threadId)}`, {
      method: "POST",
    });
    onStop?.();
  }, [threadId, onStop]);

  const showProgress =
    executorActive
      ? phase === "running"
      : isStreaming && (phase === "bulk" || phase === "poc");

  return (
    <>
      {phase === "awaiting_approval" && (
        <div className="flex shrink-0 items-center gap-2 border-b bg-amber-50 px-4 py-2 text-sm text-amber-700 dark:bg-amber-950/20 dark:text-amber-400">
          <ClockIcon className="size-4 shrink-0" />
          POC complete — waiting for your approval to continue
        </div>
      )}

      {phase === "paused" && (
        <div className="flex shrink-0 items-center gap-2 border-b bg-blue-50 px-4 py-2 text-sm text-blue-700 dark:bg-blue-950/20 dark:text-blue-400">
          <PauseIcon className="size-4 shrink-0" />
          Paused at row {completedRows} — send a message to resume
        </div>
      )}

      {phase === "stopped" && (
        <div className="flex shrink-0 items-center gap-2 border-b bg-muted px-4 py-2 text-sm text-muted-foreground">
          <SquareIcon className="size-4 shrink-0" />
          Stopped at row {completedRows} of {totalRows}
        </div>
      )}

      {showProgress && (
        <div className={cn("flex shrink-0 flex-col gap-1 border-b bg-background/95 px-4 py-2 backdrop-blur")}>
          <div className="flex items-center gap-3">
            {/* Executor-driven buttons (large runs) */}
            {executorActive ? (
              <>
                <Button
                  size="icon-sm"
                  variant="outline"
                  onClick={() => void handleExecutorPause()}
                  title="Pause at next row boundary"
                >
                  <PauseIcon className="size-3.5" />
                </Button>
                <Button
                  size="icon-sm"
                  variant="outline"
                  onClick={() => void handleExecutorStop()}
                  title="Hard stop now"
                >
                  <SquareIcon className="size-3.5" />
                </Button>
              </>
            ) : (
              /* Stream-kill button for small LLM-driven runs */
              <Button
                size="icon-sm"
                variant="outline"
                onClick={isStreaming ? onPause : onResume}
                title={isStreaming ? "Pause" : "Resume"}
              >
                {isStreaming ? (
                  <PauseIcon className="size-3.5" />
                ) : (
                  <PlayIcon className="size-3.5" />
                )}
              </Button>
            )}

            <div className="flex min-w-0 flex-1 items-center gap-2 text-sm">
              <span className="shrink-0 font-medium">
                {completedRows} / {totalRows} rows
              </span>
              <span className="min-w-0 truncate text-muted-foreground">
                {activeStepDescription}
              </span>
              {failedRows > 0 && (
                <span className="flex shrink-0 items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
                  <AlertTriangleIcon className="size-3" /> {failedRows} failed
                </span>
              )}
              <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                {formatTimeLeft(estimatedCompletion)}
              </span>
            </div>
          </div>
          <Progress value={pctDone} className="h-1" />
        </div>
      )}
    </>
  );
}
