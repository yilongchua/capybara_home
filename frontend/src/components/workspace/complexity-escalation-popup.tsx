"use client";

import { SparklesIcon, XIcon, ZapIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ComplexityEscalationEvent } from "@/core/threads/hooks";

export function ComplexityEscalationPopup({
  event,
  onSwitchToPlan,
  onContinueWork,
  onDismiss,
}: {
  event: ComplexityEscalationEvent;
  onSwitchToPlan: () => void;
  onContinueWork: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="pointer-events-none absolute right-0 bottom-full left-0 z-20 mb-3 flex items-end justify-center">
      <div className="pointer-events-auto w-full max-w-(--container-width-md) rounded-2xl border border-blue-500/30 bg-background/90 p-4 shadow-lg backdrop-blur-md">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold leading-tight text-blue-600 dark:text-blue-400">
              Complex task detected
            </p>
            <p className="text-muted-foreground mt-0.5 text-xs">
              {event.message}
            </p>
            {event.complexity_tier && (
              <p className="text-muted-foreground mt-1 text-xs">
                Complexity:{" "}
                <span className="font-medium capitalize">
                  {event.complexity_tier}
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
          <Button
            size="sm"
            variant="outline"
            className="gap-1.5"
            onClick={onSwitchToPlan}
          >
            <SparklesIcon className="size-3.5 text-blue-500" />
            Switch to Plan Mode
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="gap-1.5"
            onClick={onContinueWork}
          >
            <ZapIcon className="size-3.5 text-amber-500" />
            Continue in Work Mode
          </Button>
        </div>
      </div>
    </div>
  );
}
