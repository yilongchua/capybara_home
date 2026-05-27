"use client";

import { PencilIcon, PlayIcon, SendIcon, XIcon } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Mode = "choose" | "edit";

export function PlanApprovalOverlay({
  planTitle,
  onExecute,
  onCancel,
  onSubmitEdit,
  isExecuting = false,
  isSubmittingEdit = false,
  className,
}: {
  planTitle?: string;
  onExecute: () => void;
  onCancel: () => void;
  onSubmitEdit: (suggestion: string) => Promise<void> | void;
  isExecuting?: boolean;
  isSubmittingEdit?: boolean;
  className?: string;
}) {
  const [mode, setMode] = useState<Mode>("choose");
  const [editText, setEditText] = useState("");
  const editRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (mode === "edit") {
      editRef.current?.focus();
    }
  }, [mode]);

  const handleSend = useCallback(async () => {
    const text = editText.trim();
    if (!text || isSubmittingEdit) {
      return;
    }
    await onSubmitEdit(text);
    setEditText("");
    setMode("choose");
  }, [editText, isSubmittingEdit, onSubmitEdit]);

  const handleEditKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMode("choose");
        setEditText("");
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        void handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div
      className={cn(
        "bg-background/95 absolute inset-0 z-20 flex flex-col rounded-2xl border border-dashed backdrop-blur-sm",
        className,
      )}
      role="dialog"
      aria-label="Plan approval"
    >
      <div className="flex items-start justify-between gap-2 px-4 pt-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Plan ready
          </p>
          {planTitle ? (
            <p className="truncate text-sm font-semibold">{planTitle}</p>
          ) : null}
        </div>
        <Button
          size="icon-sm"
          variant="ghost"
          className="text-muted-foreground shrink-0"
          onClick={onCancel}
          aria-label="Cancel plan"
          disabled={isExecuting || isSubmittingEdit}
        >
          <XIcon className="size-3.5" />
        </Button>
      </div>

      {mode === "choose" ? (
        <div className="flex flex-1 items-center justify-center gap-3 px-4 pb-3">
          <Button
            size="lg"
            className="gap-2"
            onClick={onExecute}
            disabled={isExecuting}
          >
            <PlayIcon className="size-4" />
            {isExecuting ? "Starting..." : "Execute Plan"}
          </Button>
          <Button
            size="lg"
            variant="outline"
            className="gap-2"
            onClick={() => setMode("edit")}
            disabled={isExecuting}
          >
            <PencilIcon className="size-4" />
            Edit Plan
          </Button>
        </div>
      ) : (
        <div className="flex flex-1 items-stretch gap-2 px-4 pb-3">
          <textarea
            ref={editRef}
            value={editText}
            onChange={(event) => setEditText(event.target.value)}
            onKeyDown={handleEditKeyDown}
            placeholder="Edit plan — describe what should change"
            className="bg-background placeholder:text-muted-foreground flex-1 resize-none rounded-md border px-3 py-2 text-sm outline-none focus:ring-1"
            disabled={isSubmittingEdit}
          />
          <div className="flex flex-col justify-between gap-1">
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={() => {
                setMode("choose");
                setEditText("");
              }}
              aria-label="Cancel edit"
              disabled={isSubmittingEdit}
            >
              <XIcon className="size-3.5" />
            </Button>
            <Button
              size="icon-sm"
              onClick={() => void handleSend()}
              aria-label="Send edit"
              disabled={isSubmittingEdit || editText.trim().length === 0}
            >
              <SendIcon className="size-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
