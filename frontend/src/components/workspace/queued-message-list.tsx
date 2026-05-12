"use client";

import { useMemo } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { ThreadQueueItem } from "@/core/threads/hooks";
import { cn } from "@/lib/utils";

export function QueuedMessageList({
  items,
  onSteer,
  onDismiss,
  className,
}: {
  items: ThreadQueueItem[];
  onSteer: (itemId: string) => Promise<void>;
  onDismiss: (itemId: string) => void;
  className?: string;
}) {
  const { t } = useI18n();
  const queuedCountText = useMemo(
    () => t.queue.queuedCount(items.length),
    [items.length, t],
  );

  if (items.length === 0) {
    return null;
  }

  return (
    <div className={cn("rounded-lg border bg-background/70 p-2 backdrop-blur", className)}>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-medium">{t.queue.title}</p>
        <p className="text-muted-foreground text-xs">{queuedCountText}</p>
      </div>
      <div className="space-y-2">
        {items.map((item) => {
          const disableSteer =
            !item.steerEnabled ||
            item.steerStatus === "pending" ||
            item.steerStatus === "retrying";
          const steerLabel =
            item.steerStatus === "retrying"
              ? t.queue.retrying
              : item.steerStatus === "pending"
                ? t.queue.pending
                : item.steerEnabled
                  ? t.queue.steer
                  : "N/A";

          return (
            <div
              key={item.id}
              className="flex items-start justify-between gap-2 rounded border bg-background/80 px-2 py-1.5"
            >
              <div className="min-w-0">
                <p className="line-clamp-2 text-xs">{item.text || t.queue.emptyMessageFallback}</p>
                {item.steerStatus === "failed" && (
                  <p className="text-xs text-amber-600">{t.queue.failedRetrying}</p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  className="rounded bg-emerald-500/15 px-2 py-0.5 text-xs hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={disableSteer}
                  onClick={() => void onSteer(item.id)}
                >
                  {steerLabel}
                </button>
                <button
                  type="button"
                  className="rounded bg-red-500/10 px-2 py-0.5 text-xs hover:bg-red-500/20"
                  onClick={() => onDismiss(item.id)}
                >
                  {t.queue.dismiss}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
