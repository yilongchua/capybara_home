import { CheckCircle2Icon, ChevronUpIcon, Clock3Icon, Loader2Icon, XCircleIcon } from "lucide-react";
import { useMemo, useState } from "react";

import type { LongRunningTask } from "@/core/long-running/types";
import { cn } from "@/lib/utils";

function statusIcon(status: LongRunningTask["status"]) {
  if (status === "completed") {
    return <CheckCircle2Icon className="size-3.5 text-green-600" />;
  }
  if (status === "failed" || status === "timed_out" || status === "cancelled" || status === "rejected") {
    return <XCircleIcon className="size-3.5 text-red-600" />;
  }
  if (status === "queued" || status === "submitted" || status === "pending_approval" || status === "approved") {
    return <Clock3Icon className="size-3.5 text-amber-600" />;
  }
  return <Loader2Icon className="size-3.5 animate-spin text-blue-600" />;
}

function statusLabel(status: LongRunningTask["status"]) {
  if (status === "completed") return "Completed";
  if (status === "failed") return "Failed";
  if (status === "timed_out") return "Timed out";
  if (status === "cancelled") return "Cancelled";
  if (status === "rejected") return "Rejected";
  if (status === "queued") return "Queued";
  if (status === "submitted") return "Submitted";
  if (status === "pending_approval") return "Pending approval";
  if (status === "approved") return "Approved";
  return "Running";
}

export function LongRunningTasksPanel({
  className,
  tasks,
}: {
  className?: string;
  tasks: LongRunningTask[];
}) {
  const [collapsed, setCollapsed] = useState(true);

  const visibleTasks = useMemo(() => tasks.slice(0, 20), [tasks]);
  const activeCount = useMemo(
    () =>
      tasks.filter(
        (item) =>
          item.status === "queued" ||
          item.status === "submitted" ||
          item.status === "pending_approval" ||
          item.status === "running",
      ).length,
    [tasks],
  );

  return (
    <div
      className={cn(
        "flex h-fit w-full origin-bottom translate-y-4 flex-col overflow-hidden rounded-t-xl border border-b-0 bg-white backdrop-blur-sm transition-all duration-200 ease-out",
        className,
      )}
    >
      <header
        className="bg-accent flex min-h-8 shrink-0 cursor-pointer items-center justify-between px-4 text-sm"
        onClick={() => setCollapsed((prev) => !prev)}
      >
        <div className="text-muted-foreground flex items-center gap-2">
          <Clock3Icon className="size-4" />
          <span>Long-running tasks</span>
          <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px]">{activeCount} active</span>
        </div>
        <ChevronUpIcon
          className={cn(
            "text-muted-foreground size-4 transition-transform duration-300 ease-out",
            collapsed ? "" : "rotate-180",
          )}
        />
      </header>
      <main
        className={cn(
          "bg-accent transition-all duration-300 ease-out",
          collapsed ? "h-0" : "max-h-64 overflow-y-auto",
        )}
      >
        <div className="space-y-2 p-2">
          {visibleTasks.length === 0 ? (
            <div className="text-muted-foreground bg-background rounded-md border px-3 py-2 text-xs">
              No long-running tasks yet.
            </div>
          ) : (
            visibleTasks.map((task) => (
              <div key={task.id} className="bg-background rounded-md border px-3 py-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <div className="truncate font-medium">{task.title}</div>
                  <div className="flex shrink-0 items-center gap-1 text-[11px]">
                    {statusIcon(task.status)}
                    <span>{statusLabel(task.status)}</span>
                  </div>
                </div>
                {task.detail && <div className="text-muted-foreground mt-1 truncate">{task.detail}</div>}
                {task.outputPath && (
                  <div className="mt-1 truncate text-[11px] text-green-700">output: {task.outputPath}</div>
                )}
                {task.error && <div className="mt-1 truncate text-[11px] text-red-600">{task.error}</div>}
              </div>
            ))
          )}
        </div>
      </main>
    </div>
  );
}
