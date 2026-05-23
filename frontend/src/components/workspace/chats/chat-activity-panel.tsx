"use client";

import { ChevronUpIcon, Clock3Icon } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { useThread } from "@/components/workspace/messages/context";
import { PhaseProgress } from "@/components/workspace/phase-progress";
import { asActivityTimelineState, mergeActivityEvents, useActivityContext } from "@/core/activity";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import {
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
  const [timelineCollapsed, setTimelineCollapsed] = useState(false);

  const timeline = useMemo<TimelineItem[]>(() => {
    const persisted = asActivityTimelineState(thread.values.activity_timeline);
    const merged = mergeActivityEvents(persisted, liveEvents);

    const items: TimelineItem[] = merged.map((event, index) => {
      const title = event.line || "CapyHome is working on the next step...";
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

  const todos = useMemo(() => thread.values.todos ?? [], [thread.values.todos]);
  const phaseExecution = thread.values.phase_execution;
  const effectivePhaseExecution = useMemo(() => {
    if (todos.length === 0) {
      return phaseExecution;
    }

    // Keep Phase Progress aligned with the latest todo list, which is the most
    // up-to-date execution signal in some runs.
    const derivedResults = todos.map((todo, index) => {
      const existing = phaseExecution?.phase_results?.[index];
      const status = todo.status ?? existing?.status ?? "pending";
      return {
        phase_index: existing?.phase_index ?? index + 1,
        todo_id: existing?.todo_id ?? `todo-${index + 1}`,
        content: todo.content ?? existing?.content ?? `Todo ${index + 1}`,
        status,
        subagent_type: existing?.subagent_type,
        completed_at: existing?.completed_at,
      };
    });

    const hasDrift =
      !phaseExecution ||
      (phaseExecution.phase_results?.length ?? 0) !== todos.length ||
      derivedResults.some((result, index) => {
        const existing = phaseExecution.phase_results?.[index];
        if (!existing) return true;
        return existing.status !== result.status || existing.content !== result.content;
      });

    if (!hasDrift) {
      return phaseExecution;
    }

    return {
      ...(phaseExecution ?? {}),
      total_phases: todos.length,
      phase_results: derivedResults,
    };
  }, [phaseExecution, todos]);

  const hasInProgressPhase = (effectivePhaseExecution?.phase_results ?? []).some(
    (phase) => phase.status === "in_progress",
  );
  const mergedActivityForRunSignal = useMemo(
    () => mergeActivityEvents(asActivityTimelineState(thread.values.activity_timeline), liveEvents),
    [liveEvents, thread.values.activity_timeline],
  );
  const hasRecentLiveRunSignal = useMemo(() => {
    const now = Date.now() / 1000;
    return mergedActivityForRunSignal.some((event) => {
      const kind = (event.kind ?? "").toLowerCase();
      const isStartLike =
        kind.includes("start") ||
        kind.includes("running") ||
        kind.includes("work_");
      const isEndLike =
        kind.includes("completed") ||
        kind.includes("failed") ||
        kind.includes("timed_out") ||
        kind.includes("cancel");
      const recent = now - event.timestamp < 120;
      return isStartLike && !isEndLike && recent;
    });
  }, [mergedActivityForRunSignal]);

  const runState: "run" | "idle" =
    thread.isLoading && hasInProgressPhase && hasRecentLiveRunSignal ? "run" : "idle";

  const displayPhaseExecution = useMemo(() => {
    if (!effectivePhaseExecution) {
      return effectivePhaseExecution;
    }
    if (runState === "run") {
      return effectivePhaseExecution;
    }
    // If no live run signal exists, avoid showing stale in-progress rows from
    // persisted thread snapshots as currently running.
    return {
      ...effectivePhaseExecution,
      phase_results: (effectivePhaseExecution.phase_results ?? []).map((phase) => (
        phase.status === "in_progress"
          ? { ...phase, status: "pending" as const }
          : phase
      )),
    };
  }, [effectivePhaseExecution, runState]);

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
          <PhaseProgress phaseExecution={displayPhaseExecution} runState={runState} />
          <section className="mt-2 space-y-2 rounded-lg border p-3">
            <header
              className="flex cursor-pointer items-center justify-between gap-2 text-sm font-medium"
              onClick={() => setTimelineCollapsed((prev) => !prev)}
            >
              <div className="flex items-center gap-2 text-sm font-medium">
                <Clock3Icon className="size-4" />
                {t.chatActivity.title}
                <Badge variant="secondary">{orderedTimeline.length}</Badge>
              </div>
              <ChevronUpIcon
                className={cn(
                  "text-muted-foreground size-4 transition-transform duration-300 ease-out",
                  timelineCollapsed ? "" : "rotate-180",
                )}
              />
            </header>
            {!timelineCollapsed && (
              <>
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
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
