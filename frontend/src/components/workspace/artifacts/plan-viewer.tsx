"use client";

import { CheckIcon, CircleIcon, ClockIcon, XIcon } from "lucide-react";
import { useMemo } from "react";
import { Streamdown } from "streamdown";

import { cn } from "@/lib/utils";

interface PlanFrontmatter {
  plan_version?: number;
  domain?: string;
  title?: string;
  total_todos?: number;
  completed_todos?: number;
}

interface PlanTodo {
  id: string;
  content: string;
  status: "pending" | "in_progress" | "completed" | "blocked";
  dependsOn: string[];
}

function parseFrontmatter(content: string): { meta: PlanFrontmatter; body: string } {
  const trimmed = content.trimStart();
  if (!trimmed.startsWith("---")) {
    return { meta: {}, body: content };
  }
  const end = trimmed.indexOf("\n---", 3);
  if (end === -1) {
    return { meta: {}, body: content };
  }
  const yamlBlock = trimmed.slice(3, end).trim();
  const body = trimmed.slice(end + 4).trimStart();

  const meta: PlanFrontmatter = {};
  for (const line of yamlBlock.split("\n")) {
    const colonIdx = line.indexOf(":");
    if (colonIdx === -1) continue;
    const key = line.slice(0, colonIdx).trim();
    const val = line.slice(colonIdx + 1).trim().replace(/^"(.*)"$/, "$1");
    if (key === "plan_version") meta.plan_version = Number(val);
    else if (key === "domain") meta.domain = val;
    else if (key === "title") meta.title = val;
    else if (key === "total_todos") meta.total_todos = Number(val);
    else if (key === "completed_todos") meta.completed_todos = Number(val);
  }
  return { meta, body };
}

function parseTodos(body: string): PlanTodo[] {
  const todos: PlanTodo[] = [];
  const taskSectionMatch = /## Phased Implementation Steps\n([\s\S]*?)(\n## |\n?$)/.exec(body);
  const taskSection = taskSectionMatch?.[1] ?? body;

  for (const line of taskSection.split("\n")) {
    const match = /^- \[([ x])\] \*\*([^:]+)\*\*: (.+?)(\s+← depends on (.+))?$/.exec(line);
    if (!match) continue;
    const checked = (match[1] ?? "") === "x";
    const id = (match[2] ?? "").trim();
    const rest = (match[3] ?? "").trim();
    const depsRaw = match[5];
    const dependsOn = depsRaw ? depsRaw.split(",").map((d) => d.trim()) : [];
    todos.push({
      id,
      content: rest,
      status: checked ? "completed" : "pending",
      dependsOn,
    });
  }
  return todos;
}

function StatusIcon({ status }: { status: PlanTodo["status"] }) {
  if (status === "completed") {
    return <CheckIcon className="size-4 text-emerald-500 shrink-0" />;
  }
  if (status === "in_progress") {
    return <ClockIcon className="size-4 text-amber-500 animate-pulse shrink-0" />;
  }
  if (status === "blocked") {
    return <XIcon className="size-4 text-red-500 shrink-0" />;
  }
  return <CircleIcon className="size-4 text-muted-foreground/40 shrink-0" />;
}

const DOMAIN_LABELS: Record<string, string> = {
  code: "Code",
  research: "Research",
  legal: "Legal",
  trip: "Trip",
  generic: "General",
};

export function PlanViewer({ content }: { content: string }) {
  const { meta, body } = useMemo(() => parseFrontmatter(content), [content]);
  const todos = useMemo(() => parseTodos(body), [body]);

  const total = meta.total_todos ?? todos.length;
  const completed = meta.completed_todos ?? todos.filter((t) => t.status === "completed").length;
  const progress = total > 0 ? Math.round((completed / total) * 100) : 0;
  const domain = meta.domain ?? "generic";
  const title = meta.title ?? "Execution Plan";

  return (
    <div className="flex flex-col gap-4 p-4 size-full overflow-y-auto">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold leading-tight">{title}</h2>
          <span className="text-muted-foreground text-xs mt-0.5 block">
            {DOMAIN_LABELS[domain] ?? domain} plan · {completed}/{total} tasks
          </span>
        </div>
        {total > 0 && (
          <span className="text-xs font-medium tabular-nums text-muted-foreground shrink-0">
            {progress}%
          </span>
        )}
      </div>

      {total > 0 && (
        <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500",
              progress === 100 ? "bg-emerald-500" : "bg-primary",
            )}
            style={{ width: `${progress}%` }}
          />
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        {todos.map((todo) => (
          <div
            key={todo.id}
            className={cn(
              "flex items-start gap-2.5 rounded-md border px-3 py-2 text-sm",
              todo.status === "completed" && "opacity-60",
            )}
          >
            <StatusIcon status={todo.status} />
            <div className="min-w-0 flex-1">
              <span
                className={cn(
                  "block leading-snug",
                  todo.status === "completed" && "line-through text-muted-foreground",
                )}
              >
                {todo.content}
              </span>
              {todo.dependsOn.length > 0 && (
                <span className="text-muted-foreground text-xs mt-0.5 block">
                  depends on {todo.dependsOn.join(", ")}
                </span>
              )}
            </div>
            <span className="text-muted-foreground/50 text-xs font-mono shrink-0 self-start pt-0.5">
              {todo.id}
            </span>
          </div>
        ))}
        {todos.length === 0 && (
          <p className="text-muted-foreground text-sm text-center py-4">
            No tasks found in this plan.
          </p>
        )}
      </div>

      <div className="prose prose-sm max-w-none rounded-md border p-3">
        <Streamdown>{body}</Streamdown>
      </div>
    </div>
  );
}
