"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useDreamy } from "@/core/dreamy/context";
import { saveWorkflowJson } from "@/core/dreamy/hooks/use-workflow-json";

export function DreamyStepEditor({ threadId }: { threadId: string }) {
  const { workflowJson, editingStepId, setEditingStepId, patchStep } = useDreamy();

  const step = workflowJson?.steps.find((s) => s.id === editingStepId) ?? null;

  const [description, setDescription] = useState("");
  const [tool, setTool] = useState("");
  const [inputFields, setInputFields] = useState("");
  const [outputFields, setOutputFields] = useState("");
  const [condition, setCondition] = useState("");
  const isUserEditingRef = useRef(false);

  useEffect(() => {
    // Don't overwrite local state while the user is actively editing
    if (isUserEditingRef.current) return;
    if (step) {
      setDescription(step.description ?? "");
      setTool(step.tool ?? "");
      setInputFields((step.input_fields ?? []).join(", "));
      setOutputFields((step.output_fields ?? []).join(", "));
      setCondition(step.condition ?? "");
    }
  }, [step]);

  const handleFieldChange = useCallback(<T extends string>(setter: (v: T) => void) => (e: React.ChangeEvent<HTMLInputElement>) => {
    isUserEditingRef.current = true;
    setter(e.target.value as T);
  }, []);

  const handleSave = useCallback(async () => {
    if (!step || !workflowJson) return;
    const patch = {
      description,
      tool: tool || undefined,
      input_fields: inputFields.split(",").map((s) => s.trim()).filter(Boolean),
      output_fields: outputFields.split(",").map((s) => s.trim()).filter(Boolean),
      condition: condition || undefined,
    };
    const previousStep = { ...step };
    patchStep(step.id, patch);
    setEditingStepId(null);
    isUserEditingRef.current = false;
    const updated = {
      ...workflowJson,
      steps: workflowJson.steps.map((s) =>
        s.id === step.id ? { ...s, ...patch } : s,
      ),
    };
    try {
      await saveWorkflowJson(threadId, updated);
    } catch {
      patchStep(step.id, previousStep);
      toast.error("Failed to save step — changes reverted.");
    }
  }, [step, workflowJson, description, tool, inputFields, outputFields, condition, patchStep, setEditingStepId, threadId]);

  const handleCancel = useCallback(() => {
    isUserEditingRef.current = false;
    setEditingStepId(null);
  }, [setEditingStepId]);

  return (
    <Sheet open={!!editingStepId} onOpenChange={(open) => !open && handleCancel()}>
      <SheetContent side="right" className="flex w-96 flex-col p-0">
        <SheetHeader className="border-b px-6 py-4">
          <SheetTitle>Edit Step</SheetTitle>
        </SheetHeader>
        {step && (
          <ScrollArea className="min-h-0 flex-1 px-6 py-4">
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="step-desc" className="text-sm font-medium">Description</label>
                <Input
                  id="step-desc"
                  value={description}
                  onChange={handleFieldChange(setDescription)}
                />
              </div>
              {step.action === "tool_call" && (
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="step-tool" className="text-sm font-medium">Tool</label>
                  <Input
                    id="step-tool"
                    placeholder="e.g. get_vessel_particulars"
                    value={tool}
                    onChange={handleFieldChange(setTool)}
                  />
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <label htmlFor="step-in" className="text-sm font-medium">Input Fields</label>
                <Input
                  id="step-in"
                  placeholder="Comma-separated field names"
                  value={inputFields}
                  onChange={handleFieldChange(setInputFields)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="step-out" className="text-sm font-medium">Output Fields</label>
                <Input
                  id="step-out"
                  placeholder="Comma-separated column names to populate"
                  value={outputFields}
                  onChange={handleFieldChange(setOutputFields)}
                />
              </div>
              {step.action === "conditional" && (
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="step-cond" className="text-sm font-medium">Condition</label>
                  <Input
                    id="step-cond"
                    placeholder="e.g. result is not empty"
                    value={condition}
                    onChange={handleFieldChange(setCondition)}
                  />
                </div>
              )}
              <div className="text-xs text-muted-foreground">
                Action: <span className="font-mono">{step.action}</span>
                {" · "}ID: <span className="font-mono">{step.id}</span>
              </div>
            </div>
          </ScrollArea>
        )}
        <SheetFooter className="border-t px-6 py-4">
          <Button variant="outline" onClick={handleCancel}>Cancel</Button>
          <Button onClick={handleSave}>Save</Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
