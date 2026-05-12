"use client";

import { AlertTriangleIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PlanAdaptedEvent } from "@/core/threads/hooks";

export function AdaptationNotice({
  event,
  onRevisePlan,
  onDismiss,
}: {
  event: PlanAdaptedEvent;
  onRevisePlan: () => void;
  onDismiss: () => void;
}) {
  const limitReached =
    event.max_attempts !== undefined &&
    event.adaptation_attempt !== undefined &&
    event.adaptation_attempt >= event.max_attempts;

  return (
    <div className="pointer-events-none absolute right-0 bottom-full left-0 z-20 mb-3 flex items-end justify-center">
      <div className="pointer-events-auto w-full max-w-(--container-width-md) rounded-2xl border border-amber-500/30 bg-background/90 p-4 shadow-lg backdrop-blur-md">
        <div className="flex items-start gap-3">
          <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-amber-500" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold leading-tight text-amber-600 dark:text-amber-400">
              {limitReached ? "Plan revision needed" : "Plan adapted"}
            </p>
            <p className="text-muted-foreground mt-0.5 text-xs">
              {limitReached
                ? "Auto-adaptation limit reached. Please revise the plan manually to resolve the dependency issues."
                : event.message}
            </p>
            {event.blocked_ids.length > 0 && (
              <p className="text-muted-foreground mt-1 text-xs">
                Blocked:{" "}
                <span className="font-mono">
                  {event.blocked_ids.join(", ")}
                </span>
              </p>
            )}
          </div>
          <Button
            size="icon-sm"
            variant="ghost"
            className="text-muted-foreground shrink-0"
            onClick={onDismiss}
          >
            <XIcon className="size-3.5" />
          </Button>
        </div>
        <div className="mt-3 flex gap-2">
          <Button size="sm" variant="outline" onClick={onRevisePlan}>
            Revise Plan
          </Button>
          <Button size="sm" variant="ghost" onClick={onDismiss}>
            {limitReached ? "Dismiss" : "Continue"}
          </Button>
        </div>
      </div>
    </div>
  );
}
