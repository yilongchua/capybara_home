import { ChevronLeftIcon, ChevronRightIcon, FilesIcon, MapIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { usePanelRef } from "react-resizable-panels";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getBackendBaseURL } from "@/core/config";
import { sanitizeThreadId } from "@/core/utils/strings";
import { cn } from "@/lib/utils";

import {
  ArtifactFileDetail,
  ArtifactFileList,
  useDirectory,
} from "../artifacts";
import { useThread } from "../messages/context";

import { ChatActivityPanel } from "./chat-activity-panel";

function sameStringArray(a: string[], b: string[]) {
  if (a.length !== b.length) {
    return false;
  }
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) {
      return false;
    }
  }
  return true;
}

const ChatBox: React.FC<{
  children: React.ReactNode;
  threadId: string;
  extraDirectoryFiles?: string[];
  onSubmitPlanRevision?: (markdown: string) => Promise<void> | void;
}> = ({
  children,
  threadId,
  extraDirectoryFiles = [],
  onSubmitPlanRevision,
}) => {
  const { thread } = useThread();
  const threadIdRef = useRef(threadId);
  const panelRef = usePanelRef();

  const {
    directoryFiles,
    open: directoryOpen,
    setOpen: setDirectoryOpen,
    setDirectoryFiles,
    deselect,
    selectedFile,
  } = useDirectory();

  const planPath = thread.values.plan?.plan_path ?? thread.values.plan?.latest_alias_path ?? null;
  const [sandboxOutputFiles, setSandboxOutputFiles] = useState<string[]>([]);

  const [activeTab, setActiveTab] = useState<"activity" | "directory" | "preview">("activity");
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(false);
  const stableThreadId = sanitizeThreadId(threadId);
  const tabsActivityTriggerId = `chatbox-tabs-trigger-activity-${stableThreadId}`;
  const tabsDirectoryTriggerId = `chatbox-tabs-trigger-directory-${stableThreadId}`;
  const tabsPreviewTriggerId = `chatbox-tabs-trigger-preview-${stableThreadId}`;
  const tabsActivityContentId = `chatbox-tabs-content-activity-${stableThreadId}`;
  const tabsDirectoryContentId = `chatbox-tabs-content-directory-${stableThreadId}`;
  const tabsPreviewContentId = `chatbox-tabs-content-preview-${stableThreadId}`;

  useEffect(() => {
    if (threadIdRef.current !== threadId) {
      threadIdRef.current = threadId;
      deselect();
      setActiveTab("activity");
      setIsPanelCollapsed(false);
      panelRef.current?.expand();
    }

    const nextDirectoryFiles = Array.from(
      new Set([...(thread.values.artifacts ?? []), ...extraDirectoryFiles, ...sandboxOutputFiles]),
    );
    if (!sameStringArray(directoryFiles, nextDirectoryFiles)) {
      setDirectoryFiles(nextDirectoryFiles);
    }
  }, [
    directoryFiles,
    deselect,
    extraDirectoryFiles,
    panelRef,
    sandboxOutputFiles,
    setDirectoryFiles,
    thread.values.artifacts,
    threadId,
  ]);

  useEffect(() => {
    if (!directoryOpen) {
      if (activeTab === "directory") {
        setActiveTab("activity");
      }
      return;
    }
    setActiveTab("directory");
    setIsPanelCollapsed(false);
    panelRef.current?.expand();
  }, [activeTab, directoryOpen, panelRef]);

  useEffect(() => {
    let active = true;
    let timer: number | null = null;

    const load = async () => {
      try {
        const response = await fetch(
          `${getBackendBaseURL()}/api/threads/${threadId}/artifacts-list`,
        );
        if (!response.ok) {
          throw new Error("Failed to list thread directory files");
        }
        const payload = (await response.json()) as { files?: string[] };
        if (!active) {
          return;
        }
        setSandboxOutputFiles(
          (payload.files ?? []).filter((file) =>
            file.startsWith("/mnt/user-data/outputs/"),
          ),
        );
      } catch {
        if (active) {
          setSandboxOutputFiles([]);
        }
      } finally {
        if (active) {
          timer = window.setTimeout(() => {
            void load();
          }, 5000);
        }
      }
    };

    void load();
    return () => {
      active = false;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [threadId]);


  const handleCollapse = () => {
    setIsPanelCollapsed(true);
    panelRef.current?.collapse();
  };

  const handleExpand = () => {
    setIsPanelCollapsed(false);
    panelRef.current?.expand();
  };

  const handleTabChange = (value: string) => {
    const next =
      value === "directory"
        ? "directory"
        : value === "preview"
          ? "preview"
          : "activity";
    setActiveTab(next);
    setDirectoryOpen(next === "directory");
  };

  const handlePlanPreviewClose = () => {
    setActiveTab("activity");
    setDirectoryOpen(false);
  };

  return (
    <div className="relative size-full">
      <ResizablePanelGroup
        orientation="horizontal"
        id="workspace-chat-panel-group"
      >
        <ResizablePanel className="relative" defaultSize={66} minSize={40} id="chat">
          {children}
        </ResizablePanel>
        <ResizableHandle
          id="workspace-chat-panel-separator"
          className={cn(
            "opacity-33 hover:opacity-100",
            isPanelCollapsed && "pointer-events-none opacity-0",
          )}
        />
        <ResizablePanel
          panelRef={panelRef}
          defaultSize={34}
          minSize={24}
          collapsible
          collapsedSize={0}
          id="activity-directory"
          onResize={(size) => {
            const collapsed = size.asPercentage < 1;
            setIsPanelCollapsed(collapsed);
          }}
        >
          <Tabs
            value={activeTab}
            onValueChange={handleTabChange}
            className="flex size-full flex-col"
          >
            <div className="flex items-center gap-2 border-b p-2">
              <TabsList className={cn("grid w-full", planPath ? "grid-cols-3" : "grid-cols-2")}>
                <TabsTrigger
                  id={tabsActivityTriggerId}
                  aria-controls={tabsActivityContentId}
                  value="activity"
                >
                  Activity
                </TabsTrigger>
                <TabsTrigger
                  id={tabsDirectoryTriggerId}
                  aria-controls={tabsDirectoryContentId}
                  value="directory"
                >
                  Directories
                </TabsTrigger>
                {planPath && (
                  <TabsTrigger
                    id={tabsPreviewTriggerId}
                    aria-controls={tabsPreviewContentId}
                    value="preview"
                    className="flex items-center gap-1"
                  >
                    <MapIcon className="size-3" />
                    Plan
                  </TabsTrigger>
                )}
              </TabsList>
              <Button size="icon-sm" variant="ghost" onClick={handleCollapse}>
                <ChevronRightIcon className="size-4" />
              </Button>
            </div>

            <TabsContent
              id={tabsActivityContentId}
              aria-labelledby={tabsActivityTriggerId}
              value="activity"
              className="min-h-0 flex-1 p-0"
            >
              <ChatActivityPanel className="size-full" threadId={threadId} />
            </TabsContent>

            <TabsContent
              id={tabsDirectoryContentId}
              aria-labelledby={tabsDirectoryTriggerId}
              value="directory"
              className="min-h-0 flex-1 overflow-hidden p-0"
            >
              <div className="size-full overflow-y-auto p-3">
                {selectedFile ? (
                  <ArtifactFileDetail
                    className="size-full"
                    filepath={selectedFile}
                    threadId={threadId}
                    onSubmitPlanRevision={onSubmitPlanRevision}
                  />
                ) : directoryFiles?.length === 0 ? (
                  <ConversationEmptyState
                    icon={<FilesIcon />}
                    title="No directories yet"
                    description="Directories will appear here once files are generated."
                  />
                ) : (
                  <ArtifactFileList
                    className="size-full"
                    files={directoryFiles ?? []}
                    threadId={threadId}
                  />
                )}
              </div>
            </TabsContent>

            {planPath && (
              <TabsContent
                id={tabsPreviewContentId}
                aria-labelledby={tabsPreviewTriggerId}
                value="preview"
                className="min-h-0 flex-1 p-0"
              >
                <ArtifactFileDetail
                  className="size-full"
                  filepath={planPath}
                  threadId={threadId}
                  onClose={handlePlanPreviewClose}
                  onSubmitPlanRevision={onSubmitPlanRevision}
                />
              </TabsContent>
            )}
          </Tabs>
        </ResizablePanel>
      </ResizablePanelGroup>

      {isPanelCollapsed && (
        <div className="absolute top-2 right-2 z-30">
          <Button
            variant="secondary"
            size="icon-sm"
            className="border shadow-sm"
            onClick={handleExpand}
            aria-label="Open activity panel"
          >
            <ChevronLeftIcon className="size-4" />
          </Button>
        </div>
      )}
    </div>
  );
};

export { ChatBox };
