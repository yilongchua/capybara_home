import { ChevronLeftIcon, ChevronRightIcon, FilesIcon, RefreshCwIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
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

const ARTIFACTS_POLL_INTERVAL_MS = 5 * 60_000;
const DIRECTORY_ARTIFACT_ROOTS = [
  "/mnt/user-data/workspace/",
  "/mnt/user-data/mounted/",
];

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

function isDirectoryArtifactPath(file: string) {
  return DIRECTORY_ARTIFACT_ROOTS.some((root) => file.startsWith(root));
}

const ChatBox: React.FC<{
  children: React.ReactNode;
  threadId: string;
  isNewThread?: boolean;
  extraDirectoryFiles?: string[];
  onSubmitPlanRevision?: (markdown: string) => Promise<void> | void;
}> = ({
  children,
  threadId,
  isNewThread = false,
  extraDirectoryFiles = [],
  onSubmitPlanRevision,
}) => {
  const { thread } = useThread();
  const threadIdRef = useRef(threadId);
  const panelRef = usePanelRef();
  const directoryExplorerPanelRef = usePanelRef();
  const activityDirectoryOpenedRef = useRef(false);
  const activityDirectorySizeRef = useRef(30);
  const directoryExplorerOpenedRef = useRef(false);
  const directoryExplorerSizeRef = useRef(50);
  const isOuterPanelCollapsingRef = useRef(false);

  const {
    directoryFiles,
    open: directoryOpen,
    setOpen: setDirectoryOpen,
    setDirectoryFiles,
    deselect,
    selectedFile,
  } = useDirectory();

  const [sandboxOutputFiles, setSandboxOutputFiles] = useState<string[]>([]);

  const [activeTab, setActiveTab] = useState<"activity" | "directory">("activity");
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(true);
  const [isDirectoryExplorerCollapsed, setIsDirectoryExplorerCollapsed] = useState(true);
  const stableThreadId = sanitizeThreadId(threadId);
  const tabsActivityTriggerId = `chatbox-tabs-trigger-activity-${stableThreadId}`;
  const tabsDirectoryTriggerId = `chatbox-tabs-trigger-directory-${stableThreadId}`;
  const tabsActivityContentId = `chatbox-tabs-content-activity-${stableThreadId}`;
  const tabsDirectoryContentId = `chatbox-tabs-content-directory-${stableThreadId}`;
  const restoreDirectoryExplorerIfOpen = useCallback(() => {
    if (isDirectoryExplorerCollapsed) return;
    window.requestAnimationFrame(() => {
      directoryExplorerPanelRef.current?.resize(`${directoryExplorerSizeRef.current}%`);
    });
  }, [directoryExplorerPanelRef, isDirectoryExplorerCollapsed]);

  useEffect(() => {
    if (threadIdRef.current !== threadId) {
      threadIdRef.current = threadId;
      deselect();
      setActiveTab("activity");
      setIsPanelCollapsed(true);
      setIsDirectoryExplorerCollapsed(true);
      activityDirectoryOpenedRef.current = false;
      activityDirectorySizeRef.current = 30;
      directoryExplorerOpenedRef.current = false;
      directoryExplorerSizeRef.current = 50;
      isOuterPanelCollapsingRef.current = false;
      panelRef.current?.collapse();
      directoryExplorerPanelRef.current?.collapse();
    }

    const nextDirectoryFiles = Array.from(
      new Set([...(thread.values.artifacts ?? []), ...extraDirectoryFiles, ...sandboxOutputFiles]),
    );
    if (!sameStringArray(directoryFiles, nextDirectoryFiles)) {
      setDirectoryFiles(nextDirectoryFiles);
    }
  }, [
    directoryFiles,
    directoryExplorerPanelRef,
    deselect,
    extraDirectoryFiles,
    panelRef,
    sandboxOutputFiles,
    setDirectoryFiles,
    thread.values.artifacts,
    threadId,
  ]);

  useEffect(() => {
    setIsPanelCollapsed(true);
    isOuterPanelCollapsingRef.current = false;
    panelRef.current?.collapse();
  }, [isNewThread, panelRef]);

  useEffect(() => {
    if (!directoryOpen) {
      if (activeTab === "directory") {
        setActiveTab("activity");
      }
      return;
    }
    setActiveTab("directory");
    setIsPanelCollapsed(false);
    if (activityDirectoryOpenedRef.current) {
      panelRef.current?.resize(`${activityDirectorySizeRef.current}%`);
    } else {
      activityDirectoryOpenedRef.current = true;
      panelRef.current?.resize("30%");
    }
    restoreDirectoryExplorerIfOpen();
  }, [activeTab, directoryOpen, panelRef, restoreDirectoryExplorerIfOpen]);

  useEffect(() => {
    const shouldPollDirectories =
      activeTab === "directory" &&
      directoryOpen &&
      !isPanelCollapsed &&
      document.visibilityState === "visible";
    if (!shouldPollDirectories) {
      return;
    }

    let active = true;
    let timer: number | null = null;
    let inFlight = false;

    const load = async () => {
      if (inFlight || !active) {
        return;
      }
      inFlight = true;
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
          (payload.files ?? []).filter((file) => isDirectoryArtifactPath(file)),
        );
      } catch {
        // Keep current directory view on transient poll failures.
      } finally {
        inFlight = false;
        if (active) {
          timer = window.setTimeout(() => {
            void load();
          }, ARTIFACTS_POLL_INTERVAL_MS);
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
  }, [activeTab, directoryOpen, isPanelCollapsed, threadId]);

  const handleArtifactsRefresh = async () => {
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/threads/${threadId}/artifacts-list`,
      );
      if (!response.ok) {
        throw new Error("Failed to list thread directory files");
      }
      const payload = (await response.json()) as { files?: string[] };
      setSandboxOutputFiles(
        (payload.files ?? []).filter((file) => isDirectoryArtifactPath(file)),
      );
    } catch {
      // Keep current state if manual refresh fails.
    }
  };


  const handleCollapse = () => {
    isOuterPanelCollapsingRef.current = true;
    setIsPanelCollapsed(true);
    panelRef.current?.collapse();
  };

  const handleExpand = () => {
    setIsPanelCollapsed(false);
    isOuterPanelCollapsingRef.current = false;
    if (activityDirectoryOpenedRef.current) {
      panelRef.current?.resize(`${activityDirectorySizeRef.current}%`);
    } else {
      activityDirectoryOpenedRef.current = true;
      panelRef.current?.resize("30%");
    }
    restoreDirectoryExplorerIfOpen();
  };

  const handleCollapseDirectoryExplorer = () => {
    setIsDirectoryExplorerCollapsed(true);
    directoryExplorerPanelRef.current?.collapse();
  };

  const handleExpandDirectoryExplorer = () => {
    setIsDirectoryExplorerCollapsed(false);
    if (directoryExplorerOpenedRef.current) {
      directoryExplorerPanelRef.current?.resize(`${directoryExplorerSizeRef.current}%`);
    } else {
      directoryExplorerOpenedRef.current = true;
      directoryExplorerPanelRef.current?.resize("50%");
    }
  };

  const handleTabChange = (value: string) => {
    const next = value === "directory" ? "directory" : "activity";
    setActiveTab(next);
    setDirectoryOpen(next === "directory");
  };

  return (
    <div className="relative size-full">
      <ResizablePanelGroup
        orientation="horizontal"
        id="workspace-chat-panel-group"
      >
        <ResizablePanel
          panelRef={panelRef}
          defaultSize={0}
          minSize={30}
          collapsible
          collapsedSize={0}
          id="activity-directory"
          onResize={(size) => {
            const collapsed = size.asPercentage < 1;
            setIsPanelCollapsed(collapsed);
            if (!collapsed) {
              activityDirectoryOpenedRef.current = true;
              activityDirectorySizeRef.current = size.asPercentage;
            }
          }}
        >
          <Tabs
            value={activeTab}
            onValueChange={handleTabChange}
            className="flex size-full flex-col"
          >
            <div className="flex items-center gap-2 border-b p-2">
              <TabsList className="grid w-full grid-cols-2">
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
              </TabsList>
              <Button
                size="icon-sm"
                variant="ghost"
                onClick={() => {
                  void handleArtifactsRefresh();
                }}
                title="Refresh directories"
              >
                <RefreshCwIcon className="size-4" />
              </Button>
              <Button size="icon-sm" variant="ghost" onClick={handleCollapse}>
                <ChevronLeftIcon className="size-4" />
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
              <div className="size-full p-3">
                <ResizablePanelGroup orientation="horizontal" id="workspace-directory-panel-group">
                  <ResizablePanel
                    panelRef={directoryExplorerPanelRef}
                    defaultSize={0}
                    minSize={24}
                    collapsible
                    collapsedSize={0}
                    id="workspace-directory-explorer"
                    onResize={(size) => {
                      const collapsed = size.asPercentage < 1;
                      setIsDirectoryExplorerCollapsed(collapsed);
                      if (!collapsed && !isOuterPanelCollapsingRef.current) {
                        directoryExplorerOpenedRef.current = true;
                        directoryExplorerSizeRef.current = size.asPercentage;
                      }
                    }}
                  >
                    <div className="flex size-full flex-col rounded-md border">
                      <div className="flex shrink-0 justify-end border-b p-1">
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          onClick={handleCollapseDirectoryExplorer}
                          aria-label="Collapse directory explorer"
                          title="Collapse directory explorer"
                        >
                          <ChevronLeftIcon className="size-4" />
                        </Button>
                      </div>
                      <ArtifactFileList
                        className="min-h-0 flex-1 p-2"
                        files={directoryFiles ?? []}
                        threadId={threadId}
                      />
                    </div>
                  </ResizablePanel>
                  <ResizableHandle
                    id="workspace-directory-panel-separator"
                    withHandle
                    className={cn(
                      "mx-1 w-2 bg-muted/85 opacity-100 transition-colors hover:bg-muted",
                      isDirectoryExplorerCollapsed && "pointer-events-none opacity-0",
                    )}
                  />
                  <ResizablePanel defaultSize={100} minSize={24} id="workspace-directory-preview">
                    <div className="relative size-full overflow-y-auto rounded-md">
                      {isDirectoryExplorerCollapsed && (
                        <div className="absolute top-2 left-2 z-10">
                          <Button
                            size="icon-sm"
                            variant="secondary"
                            className="border shadow-sm"
                            onClick={handleExpandDirectoryExplorer}
                            aria-label="Open directory explorer"
                            title="Open directory explorer"
                          >
                            <ChevronRightIcon className="size-4" />
                          </Button>
                        </div>
                      )}
                      {selectedFile ? (
                        <ArtifactFileDetail
                          className="size-full"
                          headerClassName={isDirectoryExplorerCollapsed ? "pl-12" : undefined}
                          filepath={selectedFile}
                          threadId={threadId}
                          onSubmitPlanRevision={onSubmitPlanRevision}
                        />
                      ) : (
                        <ConversationEmptyState
                          icon={<FilesIcon />}
                          title="Select a file to preview"
                          description="Choose a file from the explorer to open it in this preview pane."
                        />
                      )}
                    </div>
                  </ResizablePanel>
                </ResizablePanelGroup>
              </div>
            </TabsContent>
          </Tabs>
        </ResizablePanel>
        <ResizableHandle
          id="workspace-chat-panel-separator"
          withHandle
          className={cn(
            "w-2 bg-muted/85 opacity-100 transition-colors hover:bg-muted",
            isPanelCollapsed && "pointer-events-none opacity-0",
          )}
        />
        <ResizablePanel className="relative" defaultSize={66} minSize={40} id="chat">
          {children}
        </ResizablePanel>
      </ResizablePanelGroup>

      {isPanelCollapsed && (
        <div className="absolute top-2 left-2 z-30">
          <Button
            variant="secondary"
            size="icon-sm"
            className="border shadow-sm"
            onClick={handleExpand}
            aria-label="Open activity and directories panel"
          >
            <ChevronRightIcon className="size-4" />
          </Button>
        </div>
      )}
    </div>
  );
};

export { ChatBox };
