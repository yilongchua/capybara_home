"use client";

import { Clock3Icon, ClockIcon, Loader2Icon } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo } from "react";

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useDreamyAsLongRunningTask } from "@/core/dreamy/hooks/use-dreamy-as-long-running-task";
import { useLongRunningTasks } from "@/core/long-running/hooks";

const TERMINAL_STATUSES = new Set(["completed", "failed", "timed_out", "cancelled", "rejected"]);

export function LongRunningTasksSidebarSection() {
  const { thread_id } = useParams<{ thread_id?: string }>();
  const activeThreadId =
    thread_id && thread_id !== "new" ? thread_id : "";
  const enableDreamyPolling = Boolean(activeThreadId);
  const { tasks, activeCount } = useLongRunningTasks(activeThreadId, {
    enabled: Boolean(activeThreadId),
  });
  const dreamyTask = useDreamyAsLongRunningTask(activeThreadId, enableDreamyPolling);

  const visible = useMemo(() => {
    const base = tasks.filter((t) => !TERMINAL_STATUSES.has(t.status));
    return [
      ...(dreamyTask ? [dreamyTask] : []),
      ...base,
    ].slice(0, 8);
  }, [tasks, dreamyTask]);

  const totalActive = activeCount + (dreamyTask ? 1 : 0);

  return (
    <SidebarGroup>
      <SidebarGroupLabel className="flex items-center justify-between">
        <span className="flex items-center gap-1.5">
          <Clock3Icon className="size-3.5" />
          Long-running
        </span>
        <span className="text-[10px]">{totalActive} active</span>
      </SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {visible.length === 0 ? (
            <SidebarMenuItem className="text-muted-foreground px-2 py-1 text-xs">
              No tasks
            </SidebarMenuItem>
          ) : (
            visible.map((task) => (
              <SidebarMenuItem key={task.id} className="rounded-md border px-2 py-1.5">
                <div className="flex items-center gap-2">
                  {(task.status === "running" ||
                    task.status === "queued" ||
                    task.status === "submitted") && (
                    <Loader2Icon className="size-3 shrink-0 animate-spin" />
                  )}
                  {task.status === "pending_approval" && (
                    <ClockIcon className="size-3 shrink-0 text-amber-500" />
                  )}
                  <div className="min-w-0">
                    <div className="truncate text-xs font-medium">{task.title}</div>
                    <div className="text-muted-foreground truncate text-[10px]">
                      {task.detail ?? task.status}
                    </div>
                  </div>
                </div>
              </SidebarMenuItem>
            ))
          )}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}
