"use client";

import { PlayIcon, XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PlanCreatedEvent } from "@/core/threads/hooks";

export function ExecutePlanPopup({
  event,
  onExecute,
  onDismiss,
}: {
  event: PlanCreatedEvent;
  onExecute: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="pointer-events-none absolute right-0 bottom-full left-0 z-20 mb-3 flex items-end justify-center">
      <div className="pointer-events-auto w-full max-w-(--container-width-md) rounded-2xl border bg-background/90 p-4 shadow-lg backdrop-blur-md">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold leading-tight">
              Plan ready: {event.title}
            </p>
            {event.summary && (
              <p className="text-muted-foreground mt-0.5 line-clamp-2 text-xs">
                {event.summary}
              </p>
            )}
            {event.todo_count > 0 && (
              <p className="text-muted-foreground mt-1 text-xs">
                {event.todo_count} task{event.todo_count !== 1 ? "s" : ""}
                {event.first_todos.length > 0 && (
                  <span className="ml-1 opacity-70">
                    · {event.first_todos[0]}
                    {event.todo_count > 1 && `, +${event.todo_count - 1} more`}
                  </span>
                )}
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
          <Button size="sm" className="gap-1.5" onClick={onExecute}>
            <PlayIcon className="size-3.5" />
            Execute Plan
          </Button>
          <Button size="sm" variant="outline" onClick={onDismiss}>
            Keep editing
          </Button>
        </div>
      </div>
    </div>
  );
}
