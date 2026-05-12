"use client";

import { CircleDotIcon, FolderOpenIcon, HardDriveIcon, SparklesIcon, TextIcon } from "lucide-react";

import { useDreamy } from "@/core/dreamy/context";
import { useStepHighlight } from "@/core/dreamy/hooks/use-step-highlight";
import { cn } from "@/lib/utils";

const SOURCE_BADGE: Record<string, { label: string; icon: React.ElementType; className: string }> = {
  mounted_file: { label: "mounted", icon: FolderOpenIcon, className: "text-violet-600 dark:text-violet-400" },
  file:         { label: "upload",  icon: HardDriveIcon,  className: "text-blue-600 dark:text-blue-400" },
  inline:       { label: "inline",  icon: TextIcon,       className: "text-muted-foreground" },
};

export function DreamyStepsList() {
  const { workflowJson, setEditingStepId } = useDreamy();
  const activeStepId = useStepHighlight();

  if (!workflowJson || workflowJson.steps.length === 0) {
    return (
      <div className="flex size-full items-center justify-center">
        <div className="text-center text-sm text-muted-foreground">
          <SparklesIcon className="mx-auto size-8 opacity-40" />
          <p className="mt-2">Workflow steps will appear here</p>
          <p className="mt-1 text-xs">Click &quot;Start Workflow&quot; and describe what to do per row.</p>
        </div>
      </div>
    );
  }

  const { steps, data_source, task_source } = workflowJson;
  const sourceType    = data_source?.type ?? "inline";
  const sourceFilename = data_source?.filename ?? task_source?.filename ?? "unknown";
  const sourceTotal   = data_source?.total_rows ?? task_source?.total_tasks ?? 0;
  const sourceFields  = data_source?.fields ?? task_source?.fields ?? [];
  const sourceVPath   = data_source?.virtual_path;
  const badge         = SOURCE_BADGE[sourceType] ?? SOURCE_BADGE.inline!;
  const BadgeIcon     = badge.icon;

  return (
    <div className="flex size-full flex-col overflow-auto p-4">
      <div className="mb-4 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <BadgeIcon className={cn("size-3 shrink-0", badge.className)} />
          <span className={cn("font-medium", badge.className)}>{sourceFilename}</span>
          <span className="mx-0.5 opacity-40">·</span>
          <span>{sourceTotal} rows</span>
          {sourceFields.length > 0 && (
            <>
              <span className="mx-0.5 opacity-40">·</span>
              <span className="truncate">{sourceFields.join(", ")}</span>
            </>
          )}
        </div>
        {sourceVPath && sourceType === "mounted_file" && (
          <div className="mt-1 truncate font-mono opacity-60">{sourceVPath}</div>
        )}
      </div>

      <ol className="flex flex-col gap-2">
        {steps.map((step, idx) => {
          const isActive = step.id === activeStepId;
          return (
            <li
              key={step.id}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm transition-colors hover:bg-accent/30",
                isActive && "border-primary bg-primary/5 ring-1 ring-primary",
              )}
              onClick={() => setEditingStepId(step.id)}
            >
              <span className="mt-0.5 shrink-0 font-mono text-xs text-muted-foreground">
                {idx + 1}
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="font-medium">{step.description}</div>
                <div className="text-xs text-muted-foreground">
                  {step.action === "tool_call" && (
                    <>
                      Tool: <span className="font-mono">{step.tool ?? "(not set)"}</span>
                    </>
                  )}
                  {step.action === "write_row" && "Write row to output file"}
                  {step.action === "conditional" && `Condition: ${step.condition ?? ""}`}
                  {step.input_fields.length > 0 && (
                    <> · in: {step.input_fields.join(", ")}</>
                  )}
                  {step.output_fields.length > 0 && (
                    <> · out: {step.output_fields.join(", ")}</>
                  )}
                </div>
              </div>
              {isActive && (
                <CircleDotIcon className="size-4 shrink-0 animate-pulse text-primary" />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
