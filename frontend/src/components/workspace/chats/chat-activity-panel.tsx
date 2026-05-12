"use client";

import { Clock3Icon } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { useThread } from "@/components/workspace/messages/context";
import { asActivityTimelineState, mergeActivityEvents, useActivityContext } from "@/core/activity";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import {
  runStatusTone,
  TIMELINE_MAX_ITEMS,
  type TimelineIcon,
  type TimelineItem,
} from "./timeline-helpers";
import { TimelineItemRow } from "./timeline-item-row";

function iconFromEventKind(kind: string, actor: string): TimelineIcon {
  if (kind.includes("failed") || kind.includes("timed_out")) {
    return "failed";
  }
  if (kind.includes("completed")) {
    return "done";
  }
  if (kind.includes("tool") || kind.includes("task")) {
    return "tool";
  }
  if (actor === "baby_capy") {
    return "assistant";
  }
  if (actor === "system") {
    return "tool";
  }
  return "assistant";
}

export function ChatActivityPanel({
  className,
}: {
  className?: string;
  threadId: string;
}) {
  const { t } = useI18n();
  const { thread } = useThread();
  const { liveEvents } = useActivityContext();

  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const timeline = useMemo<TimelineItem[]>(() => {
    const persisted = asActivityTimelineState(thread.values.activity_timeline);
    const merged = mergeActivityEvents(persisted, liveEvents);

    const items: TimelineItem[] = merged.map((event, index) => {
      const title = event.line || "Capybara is working on the next step...";
      const detail = event.tool_summary ?? undefined;
      return {
        id: event.id ?? `activity:${event.timestamp}:${index}`,
        timestamp: event.timestamp,
        order: index,
        kind: event.kind.includes("failed")
          ? "task_failed"
          : event.kind.includes("completed")
            ? "task_completed"
            : "task_started",
        icon: iconFromEventKind(event.kind, event.actor),
        title,
        detail,
        groupId: event.group_id ?? undefined,
      };
    });

    if (items.length > TIMELINE_MAX_ITEMS) {
      return items.slice(items.length - TIMELINE_MAX_ITEMS);
    }
    return items;
  }, [liveEvents, thread.values.activity_timeline]);

  const runState: "run" | "idle" = thread.isLoading ? "run" : "idle";

  const orderedTimeline = useMemo(
    () => [...timeline].sort((a, b) => a.timestamp !== b.timestamp ? a.timestamp - b.timestamp : a.order - b.order),
    [timeline],
  );

  const groupSizeMap = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of orderedTimeline) {
      if (item.groupId) counts.set(item.groupId, (counts.get(item.groupId) ?? 0) + 1);
    }
    return counts;
  }, [orderedTimeline]);

  const groupFirstItemId = useMemo(() => {
    const first = new Map<string, string>();
    for (const item of orderedTimeline) {
      if (item.groupId && !first.has(item.groupId)) first.set(item.groupId, item.id);
    }
    return first;
  }, [orderedTimeline]);

  const handleToggleGroup = useCallback((groupId: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  }, []);

  const visibleTimeline = useMemo(() => {
    return orderedTimeline.filter((item) => {
      if (!item.groupId) return true;
      const isHeader = groupFirstItemId.get(item.groupId) === item.id;
      if (isHeader) return true;
      return !collapsedGroups.has(item.groupId);
    });
  }, [orderedTimeline, groupFirstItemId, collapsedGroups]);

  const trimmed = timeline.length >= TIMELINE_MAX_ITEMS;

  return (
    <div className={cn("flex h-full flex-col overflow-hidden", className)}>
      <div className="flex-1 overflow-y-auto">
        <div className="space-y-0 p-3">
          <section className="space-y-2 rounded-lg border p-3">
            <header className="flex items-center justify-between gap-2 text-sm font-medium">
              <div className="flex items-center gap-2">
                <Clock3Icon className="size-4" />
                {t.chatActivity.title}
                <Badge variant="secondary">{orderedTimeline.length}</Badge>
              </div>
              <span
                className={cn(
                  "rounded-md border px-2 py-0.5 text-[11px] font-medium capitalize",
                  runStatusTone(runState),
                )}
              >
                {runState === "run" ? t.chatActivity.runStatus.run : t.chatActivity.runStatus.idle}
              </span>
            </header>

            {trimmed && (
              <div className="text-muted-foreground rounded border px-2 py-1.5 text-xs">
                {t.chatActivity.trimmedNotice(TIMELINE_MAX_ITEMS)}
              </div>
            )}

            {visibleTimeline.length === 0 ? (
              <div className="text-muted-foreground text-xs">{t.chatActivity.noActivity}</div>
            ) : (
              <div>
                {visibleTimeline.map((item) => {
                  const groupId = item.groupId;
                  const groupSize = groupId ? (groupSizeMap.get(groupId) ?? 1) : 1;
                  const isGroupHeader = groupId ? groupFirstItemId.get(groupId) === item.id : false;
                  const groupCollapsed = groupId ? collapsedGroups.has(groupId) : false;

                  return (
                    <TimelineItemRow
                      key={item.id}
                      item={item}
                      isGroupHeader={isGroupHeader}
                      groupSize={groupSize}
                      groupCollapsed={groupCollapsed}
                      onToggleGroup={handleToggleGroup}
                    />
                  );
                })}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
