"use client";

import { ChevronLeftIcon } from "lucide-react";
import { useCallback, useEffect, useRef } from "react";
import { usePanelRef } from "react-resizable-panels";

import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useThread } from "@/components/workspace/messages/context";
import { useDreamy } from "@/core/dreamy/context";

import { DreamyProgressHeader } from "./dreamy-progress-header";
import { DreamyWorkflowPane } from "./dreamy-workflow-pane";

export function DreamyBox({
  children,
  threadId,
  isNewThread: _isNewThread,
}: {
  children: React.ReactNode;
  threadId: string;
  isNewThread: boolean;
}) {
  const { thread } = useThread();
  const { workflowJson, isPinned, setIsPinned, isPaneCollapsed, setIsPaneCollapsed } = useDreamy();
  const panelRef = usePanelRef();
  const didAutoPinRef = useRef(false);

  // Auto-pin and expand the panel when workflow.json first arrives.
  // Guard with ref set before any state updates so concurrent effect
  // re-fires (e.g. rapid workflowJson updates) skip the auto-pin.
  useEffect(() => {
    if (!workflowJson || didAutoPinRef.current) return;
    didAutoPinRef.current = true;
    setIsPinned(true);
    setIsPaneCollapsed(false);
    panelRef.current?.expand();
    return () => {
      // Reset on unmount so a remount can re-trigger if needed
      didAutoPinRef.current = false;
    };
  }, [workflowJson, setIsPinned, setIsPaneCollapsed, panelRef]);

  // Sync panel expand/collapse with context state
  useEffect(() => {
    if (isPaneCollapsed) {
      panelRef.current?.collapse();
    } else {
      panelRef.current?.expand();
    }
  }, [isPaneCollapsed, panelRef]);

  const handlePause = useCallback(async () => {
    await thread.stop();
  }, [thread]);

  const handleResume = useCallback(() => {
    // Resume is triggered by sending a new message in the chat pane
  }, []);

  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

  const handleExpand = useCallback(() => {
    setIsPaneCollapsed(false);
    panelRef.current?.expand();
  }, [setIsPaneCollapsed, panelRef]);

  return (
    <div className="flex size-full flex-col">
      <DreamyProgressHeader
        threadId={threadId}
        isStreaming={thread.isLoading}
        onPause={handlePause}
        onResume={handleResume}
        onStop={handleStop}
      />
      <div className="relative min-h-0 flex-1">
        <ResizablePanelGroup
          orientation="horizontal"
          id="dreamy-panel-group"
          className="size-full"
        >
          <ResizablePanel defaultSize={45} minSize={30} id="dreamy-chat">
            {children}
          </ResizablePanel>
          <ResizableHandle id="dreamy-separator" className="opacity-33 hover:opacity-100" />
          <ResizablePanel
            panelRef={panelRef}
            defaultSize={55}
            minSize={25}
            collapsedSize={0}
            collapsible
            id="dreamy-workflow"
            onResize={(size) => {
              const collapsed = size.asPercentage < 1;
              if (collapsed && !isPinned) {
                setIsPaneCollapsed(true);
              } else if (!collapsed) {
                setIsPaneCollapsed(false);
              }
            }}
          >
            <DreamyWorkflowPane threadId={threadId} />
          </ResizablePanel>
        </ResizablePanelGroup>

        {/* Expand button — floats at the right edge when the panel is collapsed */}
        {isPaneCollapsed && (
          <div className="absolute right-0 top-1/2 -translate-y-1/2 z-10">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="secondary"
                  size="icon"
                  className="h-14 w-5 rounded-l-md rounded-r-none border border-r-0 shadow-md"
                  onClick={handleExpand}
                >
                  <ChevronLeftIcon className="size-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="left">Open panel</TooltipContent>
            </Tooltip>
          </div>
        )}
      </div>
    </div>
  );
}
