"use client";

import { CheckCircle2Icon, CircleDotIcon, CircleIcon, LoaderCircleIcon } from "lucide-react";

import type { PhaseExecutionState, PhaseResult } from "@/core/threads/types";
import { cn } from "@/lib/utils";

function PhaseIcon({ status }: { status: PhaseResult["status"] }) {
  switch (status) {
    case "completed":
      return <CheckCircle2Icon className="size-4 shrink-0 text-green-500" />;
    case "in_progress":
      return <LoaderCircleIcon className="size-4 shrink-0 animate-spin text-blue-400" />;
    case "failed":
      return <CircleDotIcon className="size-4 shrink-0 text-red-400" />;
    default:
      return <CircleIcon className="size-4 shrink-0 text-muted-foreground/40" />;
  }
}

function PhaseRow({ result, isLast }: { result: PhaseResult; isLast: boolean }) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex flex-col items-center">
        <PhaseIcon status={result.status} />
        {!isLast && <div className="mt-1 w-px flex-1 bg-border/50" style={{ minHeight: "1rem" }} />}
      </div>
      <div className={cn("pb-3 text-sm", isLast && "pb-0")}>
        <p
          className={cn(
            "font-medium leading-snug",
            result.status === "completed" && "text-foreground",
            result.status === "in_progress" && "text-blue-400",
            result.status === "failed" && "text-red-400",
            result.status === "pending" && "text-muted-foreground/60",
          )}
        >
          {result.content}
        </p>
        {result.status === "in_progress" && (
          <p className="mt-0.5 text-xs text-muted-foreground">Running…</p>
        )}
        {result.status === "completed" && result.completed_at && (
          <p className="mt-0.5 text-xs text-muted-foreground">Done</p>
        )}
        {result.status === "failed" && (
          <p className="mt-0.5 text-xs text-red-400/70">Failed</p>
        )}
      </div>
    </div>
  );
}

export function PhaseProgress({
  phaseExecution,
  runState,
}: {
  phaseExecution: PhaseExecutionState | null | undefined;
  runState?: "run" | "idle";
}) {
  if (!phaseExecution) return null;

  const results = phaseExecution.phase_results;
  if (!results || results.length === 0) return null;

  const completed = results.filter((r) => r.status === "completed").length;
  const total = phaseExecution.total_phases ?? results.length;

  return (
    <div className="my-2 rounded-lg border border-border/50 bg-card/50 p-3">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">Phase Progress</span>
        <div className="flex items-center gap-2">
          {runState && (
            <span className="rounded-md border px-2 py-0.5 text-[11px] font-medium capitalize text-muted-foreground">
              {runState}
            </span>
          )}
          <span className="text-xs text-muted-foreground">
            {completed}/{total}
          </span>
        </div>
      </div>
      <div className="space-y-0">
        {results.map((result, i) => (
          <PhaseRow key={result.todo_id} result={result} isLast={i === results.length - 1} />
        ))}
      </div>
    </div>
  );
}
