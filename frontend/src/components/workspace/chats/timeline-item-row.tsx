"use client";

import {
  BotIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  ChevronRightIcon,
  DatabaseIcon,
  GlobeIcon,
  HammerIcon,
  TerminalIcon,
  TriangleAlertIcon,
  UserIcon,
} from "lucide-react";
import { memo } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import {
  formatDuration,
  formatTime,
  kindToSpineColor,
  type TimelineIcon,
  type TimelineItem,
  type TimelineItemKind,
} from "./timeline-helpers";

function renderEventIcon(icon: TimelineIcon) {
  if (icon === "user") return <UserIcon className="text-muted-foreground mt-0.5 size-3.5 shrink-0" />;
  if (icon === "assistant") return <BotIcon className="text-muted-foreground mt-0.5 size-3.5 shrink-0" />;
  if (icon === "done") return <CheckCircle2Icon className="mt-0.5 size-3.5 shrink-0 text-emerald-700" />;
  if (icon === "failed") return <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0 text-red-700" />;
  if (icon === "web") return <GlobeIcon className="mt-0.5 size-3.5 shrink-0 text-blue-700" />;
  if (icon === "vault") return <DatabaseIcon className="mt-0.5 size-3.5 shrink-0 text-indigo-700" />;
  if (icon === "terminal") return <TerminalIcon className="mt-0.5 size-3.5 shrink-0 text-amber-700" />;
  return <HammerIcon className="mt-0.5 size-3.5 shrink-0 text-slate-700" />;
}

export const TimelineItemRow = memo(function TimelineItemRow_({
  item,
  isGroupHeader,
  groupSize,
  groupCollapsed,
  onToggleGroup,
}: {
  item: TimelineItem;
  isGroupHeader: boolean;
  groupSize: number;
  groupCollapsed: boolean;
  onToggleGroup: (groupId: string) => void;
}) {
  const spineColor = kindToSpineColor(item.kind);
  const hasGroup = Boolean(item.groupId) && groupSize > 1;

  return (
    <div className="relative flex gap-2">
      {/* Vertical spine */}
      <div className="flex flex-col items-center">
        <div className={cn("mt-2.5 w-0.5 shrink-0 self-stretch rounded-full", spineColor)} />
      </div>

      <div
        className={cn(
          "mb-1.5 min-w-0 flex-1 rounded-md border-[1px]! border-border/40 px-2.5 py-2",
          hasGroup && isGroupHeader && "cursor-pointer hover:bg-muted/40",
        )}
        onClick={hasGroup && isGroupHeader ? () => onToggleGroup(item.groupId!) : undefined}
      >
        <div className="text-muted-foreground mb-0.5 flex items-center justify-between text-[11px]">
          <span>{formatTime(item.timestamp)}</span>
          <div className="flex items-center gap-1">
            {item.durationMs !== undefined && item.durationMs > 0 && (
              <span className="rounded bg-slate-100 px-1 font-mono text-[10px]">
                {formatDuration(item.durationMs)}
              </span>
            )}
            {hasGroup && isGroupHeader && (
              <Badge variant="secondary" className="px-1 py-0 text-[10px]">
                {groupCollapsed ? (
                  <><ChevronRightIcon className="size-2.5 mr-0.5" />{groupSize}</>
                ) : (
                  <><ChevronDownIcon className="size-2.5 mr-0.5" />{groupSize}</>
                )}
              </Badge>
            )}
          </div>
        </div>
        <div className="flex items-start gap-2">
          {renderEventIcon(item.icon)}
          <div className="min-w-0 flex-1 text-sm leading-5 whitespace-normal break-all">{item.title}</div>
        </div>
        {item.detail && (
          <div className="text-muted-foreground mt-1 text-xs leading-5 whitespace-normal break-all" title={item.detail}>
            {item.detail}
          </div>
        )}
      </div>
    </div>
  );
});
