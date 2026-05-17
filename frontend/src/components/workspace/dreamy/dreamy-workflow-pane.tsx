"use client";

import { CheckCircle2Icon, ChevronRightIcon, PinIcon, PinOffIcon, PlusIcon } from "lucide-react";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDreamy } from "@/core/dreamy/context";
import { useDreamyProgress } from "@/core/dreamy/hooks/use-dreamy-progress";
import { useWorkflowJson } from "@/core/dreamy/hooks/use-workflow-json";
import type { SelectedFile } from "@/core/dreamy/types";
import { cn } from "@/lib/utils";

import { DreamyAddStepDialog } from "./dreamy-add-step-dialog";
import { DreamyDirectoryTab } from "./dreamy-directory-tab";
import { DreamyFilePreview } from "./dreamy-file-preview";
import { DreamyStepEditor } from "./dreamy-step-editor";
import { DreamyStepsList } from "./dreamy-steps-list";

const PHASE_BADGE: Record<string, { label: string; className: string }> = {
  poc:                { label: "POC",      className: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400" },
  awaiting_approval:  { label: "approval", className: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400" },
  bulk:               { label: "row-by-row", className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400" },
  done:               { label: "done",     className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400" },
};

export function DreamyWorkflowPane({ threadId }: { threadId: string }) {
  useWorkflowJson(threadId);

  const { workflowJson, isPinned, setIsPinned, setIsPaneCollapsed } = useDreamy();
  const progress = useDreamyProgress(threadId);
  const [addStepOpen, setAddStepOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"workflow" | "directory" | "preview">("workflow");
  const [selectedFile, setSelectedFile] = useState<SelectedFile | null>(null);

  const isExecuting = progress.phase === "poc" || progress.phase === "bulk";
  const showProgress = workflowJson !== null && progress.totalRows > 0 && progress.phase !== "design";
  const phaseBadge = PHASE_BADGE[progress.phase];

  const handleSelectFile = useCallback((file: SelectedFile) => {
    setSelectedFile(file);
    setActiveTab("preview");
  }, []);

  const handleClosePreview = useCallback(() => {
    setSelectedFile(null);
    setActiveTab("directory");
  }, []);

  return (
    <Tabs
      value={activeTab}
      onValueChange={(v) => setActiveTab(v as typeof activeTab)}
      className="relative size-full gap-0"
    >
      {/* Header row */}
      <div className="flex shrink-0 items-center gap-1 border-b px-2 py-1.5">
        {/* Pin button */}
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="size-7 shrink-0"
              onClick={() => setIsPinned(!isPinned)}
            >
              {isPinned ? (
                <PinIcon className="size-3.5 text-primary" />
              ) : (
                <PinOffIcon className="size-3.5 text-muted-foreground" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            {isPinned ? "Unpin panel" : "Pin panel"}
          </TooltipContent>
        </Tooltip>

        {/* Tab triggers */}
        <TabsList className="h-7 gap-0 p-0.5">
          <TabsTrigger value="workflow" className="h-6 px-2.5 text-xs">
            Workflow
          </TabsTrigger>
          <TabsTrigger value="directory" className="h-6 px-2.5 text-xs">
            Directory
          </TabsTrigger>
          <TabsTrigger
            value="preview"
            className="h-6 px-2.5 text-xs"
            disabled={!selectedFile}
          >
            Preview
            {isExecuting && selectedFile && (
              <span className="ml-1 size-1.5 rounded-full bg-emerald-500" />
            )}
          </TabsTrigger>
        </TabsList>

        {/* Right-side actions */}
        <div className="ml-auto flex items-center gap-0.5">
          {workflowJson && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7"
                  onClick={() => setAddStepOpen(true)}
                >
                  <PlusIcon className="size-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">Add step</TooltipContent>
            </Tooltip>
          )}

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="size-7"
                disabled={isPinned}
                onClick={() => { if (!isPinned) setIsPaneCollapsed(true); }}
              >
                <ChevronRightIcon className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              {isPinned ? "Unpin to collapse" : "Collapse panel"}
            </TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* Progress strip */}
      {showProgress && (
        <div className="shrink-0 border-b px-3 py-1.5">
          <div className="mb-1 flex items-center justify-between text-[10px] text-muted-foreground">
            <span>
              {progress.phase === "done" && (
                <CheckCircle2Icon className="mr-1 inline size-3 text-emerald-600" />
              )}
              {progress.completedRows} / {progress.totalRows} rows
              {progress.pctDone > 0 && ` · ${progress.pctDone.toFixed(1)}%`}
            </span>
            {phaseBadge && (
              <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", phaseBadge.className)}>
                {phaseBadge.label}
              </span>
            )}
          </div>
          <Progress value={progress.pctDone} className="h-0.5" />
        </div>
      )}

      {/* Workflow tab */}
      <TabsContent value="workflow" className="min-h-0 flex-1">
        <DreamyStepsList />
      </TabsContent>

      {/* Directory tab */}
      <TabsContent value="directory" className="min-h-0 flex-1">
        <DreamyDirectoryTab
          threadId={threadId}
          selectedFilename={selectedFile?.filename}
          onSelectFile={handleSelectFile}
        />
      </TabsContent>

      {/* Preview tab */}
      <TabsContent value="preview" className="min-h-0 flex-1">
        {selectedFile ? (
          <DreamyFilePreview
            file={selectedFile}
            threadId={threadId}
            onClose={handleClosePreview}
          />
        ) : (
          <div className="flex size-full items-center justify-center text-xs text-muted-foreground">
            Select a file in the Directory tab to preview it
          </div>
        )}
      </TabsContent>

      <DreamyStepEditor threadId={threadId} />

      {workflowJson && (
        <DreamyAddStepDialog open={addStepOpen} onOpenChange={setAddStepOpen} />
      )}
    </Tabs>
  );
}
