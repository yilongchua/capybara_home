"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useDreamy } from "@/core/dreamy/context";
import type { WorkflowStep } from "@/core/dreamy/types";
import { cn } from "@/lib/utils";

interface StepTypeOption {
  action: WorkflowStep["action"];
  icon: string;
  label: string;
  description: string;
  colorClass: string;
}

const STEP_TYPE_OPTIONS: StepTypeOption[] = [
  {
    action: "tool_call",
    icon: "🔧",
    label: "Tool Call",
    description: "Call a Python tool or function (search, API, transform)",
    colorClass: "border-cyan-500/60 bg-cyan-50/50 dark:bg-cyan-950/20",
  },
  {
    action: "write_row",
    icon: "📝",
    label: "Write Row",
    description: "Write the current row's results to the output file",
    colorClass: "border-blue-500/60 bg-blue-50/50 dark:bg-blue-950/20",
  },
  {
    action: "conditional",
    icon: "🔀",
    label: "Branch",
    description: "Conditional branching based on a field or expression",
    colorClass: "border-yellow-500/60 bg-yellow-50/50 dark:bg-yellow-950/20",
  },
  {
    action: "ask_clarification",
    icon: "❓",
    label: "Ask User",
    description: "Pause and request clarification from the user",
    colorClass: "border-orange-500/60 bg-orange-50/50 dark:bg-orange-950/20",
  },
];

interface DreamyAddStepDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function DreamyAddStepDialog({ open, onOpenChange }: DreamyAddStepDialogProps) {
  const { addStep } = useDreamy();

  const [selectedAction, setSelectedAction] = useState<WorkflowStep["action"]>("tool_call");
  const [description, setDescription] = useState("");
  const [tool, setTool] = useState("");
  const [condition, setCondition] = useState("");

  const handleAdd = () => {
    addStep(selectedAction, {
      description: description.trim() || `New ${selectedAction.replace("_", " ")} step`,
      tool: selectedAction === "tool_call" ? (tool.trim() || undefined) : undefined,
      condition: selectedAction === "conditional" ? (condition.trim() || undefined) : undefined,
      input_fields: [],
      output_fields: [],
    });
    onOpenChange(false);
    setDescription("");
    setTool("");
    setCondition("");
    setSelectedAction("tool_call");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Add Step</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium">Step type</p>
          <div className="grid grid-cols-2 gap-2">
            {STEP_TYPE_OPTIONS.map((opt) => (
              <button
                key={opt.action}
                type="button"
                onClick={() => setSelectedAction(opt.action)}
                className={cn(
                  "flex flex-col gap-1 rounded-lg border-2 p-3 text-left transition-all",
                  opt.colorClass,
                  selectedAction === opt.action
                    ? "border-primary ring-2 ring-primary/30"
                    : "border-transparent hover:border-border",
                )}
              >
                <span className="text-lg">{opt.icon}</span>
                <span className="text-sm font-medium">{opt.label}</span>
                <span className="text-xs text-muted-foreground">{opt.description}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="add-step-desc" className="text-sm font-medium">Description</label>
            <Input
              id="add-step-desc"
              placeholder="What does this step do?"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          {selectedAction === "tool_call" && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor="add-step-tool" className="text-sm font-medium">
                Tool <span className="font-normal text-muted-foreground">(optional)</span>
              </label>
              <Input
                id="add-step-tool"
                placeholder="e.g. get_vessel_info"
                value={tool}
                onChange={(e) => setTool(e.target.value)}
              />
            </div>
          )}

          {selectedAction === "conditional" && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor="add-step-cond" className="text-sm font-medium">
                Condition <span className="font-normal text-muted-foreground">(optional)</span>
              </label>
              <Input
                id="add-step-cond"
                placeholder="e.g. result is not empty"
                value={condition}
                onChange={(e) => setCondition(e.target.value)}
              />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleAdd}>Add step</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
