import { ChevronUpIcon, ListTodoIcon } from "lucide-react";
import { useState } from "react";

import type { Todo } from "@/core/todos";
import { cn } from "@/lib/utils";

import {
  QueueItem,
  QueueItemContent,
  QueueItemIndicator,
  QueueList,
} from "../ai-elements/queue";

export function TodoList({
  className,
  todos,
  collapsed: controlledCollapsed,
  hidden = false,
  onToggle,
  embedded = false,
}: {
  className?: string;
  todos: Todo[];
  collapsed?: boolean;
  hidden?: boolean;
  onToggle?: () => void;
  embedded?: boolean;
}) {
  const [internalCollapsed, setInternalCollapsed] = useState(true);
  const isControlled = controlledCollapsed !== undefined;
  const collapsed = isControlled ? controlledCollapsed : internalCollapsed;

  const handleToggle = () => {
    if (isControlled) {
      onToggle?.();
    } else {
      setInternalCollapsed((prev) => !prev);
    }
  };

  return (
    <div
      className={cn(
        "flex h-fit w-full flex-col overflow-hidden border transition-all duration-200 ease-out",
        embedded
          ? "rounded-lg border-border/50 bg-card/50"
          : "origin-bottom translate-y-4 rounded-t-xl border-b-0 bg-white backdrop-blur-sm",
        hidden ? (embedded ? "pointer-events-none opacity-0" : "pointer-events-none translate-y-8 opacity-0") : "",
        className,
      )}
    >
      <header
        className={cn(
          "flex min-h-8 shrink-0 cursor-pointer items-center justify-between px-4 text-sm transition-all duration-300 ease-out",
          embedded ? "bg-transparent" : "bg-accent",
        )}
        onClick={handleToggle}
      >
        <div className="text-muted-foreground">
          <div className="flex items-center justify-center gap-2">
            <ListTodoIcon className="size-4" />
            <div>To-do</div>
          </div>
        </div>
        <div>
          <ChevronUpIcon
            className={cn(
              "text-muted-foreground size-4 transition-transform duration-300 ease-out",
              collapsed ? "" : "rotate-180",
            )}
          />
        </div>
      </header>
      <main
        className={cn(
          "flex grow px-2 transition-all duration-300 ease-out",
          embedded ? "bg-transparent" : "bg-accent",
          collapsed ? (embedded ? "h-0 pb-0" : "h-0 pb-3") : "h-28 pb-4",
        )}
      >
        <QueueList className={cn("bg-background mt-0 w-full", embedded ? "rounded-md" : "rounded-t-xl")}>
          {todos.map((todo, i) => (
            <QueueItem key={i + (todo.content ?? "")}>
              <div className="flex items-center gap-2">
                <QueueItemIndicator
                  className={
                    todo.status === "in_progress" ? "bg-primary/70" : ""
                  }
                  completed={todo.status === "completed"}
                />
                <QueueItemContent
                  className={
                    todo.status === "in_progress" ? "text-primary/70" : ""
                  }
                  completed={todo.status === "completed"}
                >
                  {todo.content}
                </QueueItemContent>
              </div>
            </QueueItem>
          ))}
        </QueueList>
      </main>
    </div>
  );
}
