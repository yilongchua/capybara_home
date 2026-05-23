import { ChevronLeftIcon, ChevronRightIcon, FilesIcon, RefreshCwIcon } from "lucide-react";
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

  const {
    directoryFiles,
    open: directoryOpen,
    setOpen: setDirectoryOpen,
    setDirectoryFiles,
    deselect,
    selectedFile,
  } = useDirectory();

  const [sandboxOutputFiles, setSandboxOutputFiles] = useState<string[]>([]);
  const [createdDirectoryPath, setCreatedDirectoryPath] = useState("");
  const [mountedDirectoryPath, setMountedDirectoryPath] = useState("");

  const [activeTab, setActiveTab] = useState<"activity" | "directory">("activity");
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(isNewThread);
  const stableThreadId = sanitizeThreadId(threadId);
  const tabsActivityTriggerId = `chatbox-tabs-trigger-activity-${stableThreadId}`;
  const tabsDirectoryTriggerId = `chatbox-tabs-trigger-directory-${stableThreadId}`;
  const tabsActivityContentId = `chatbox-tabs-content-activity-${stableThreadId}`;
  const tabsDirectoryContentId = `chatbox-tabs-content-directory-${stableThreadId}`;

  useEffect(() => {
    if (threadIdRef.current !== threadId) {
      threadIdRef.current = threadId;
      deselect();
      setCreatedDirectoryPath("");
      setMountedDirectoryPath("");
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
    if (isNewThread) {
      setIsPanelCollapsed(true);
      panelRef.current?.collapse();
    } else {
      setIsPanelCollapsed(false);
      panelRef.current?.expand();
    }
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
    panelRef.current?.expand();
  }, [activeTab, directoryOpen, panelRef]);

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
    setIsPanelCollapsed(true);
    panelRef.current?.collapse();
  };

  const handleExpand = () => {
    setIsPanelCollapsed(false);
    panelRef.current?.expand();
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
        <ResizablePanel className="relative" defaultSize={66} minSize={40} id="chat">
          {children}
        </ResizablePanel>
        <ResizableHandle
          id="workspace-chat-panel-separator"
          withHandle
          className={cn(
            "w-2 bg-muted/85 opacity-100 transition-colors hover:bg-muted",
            isPanelCollapsed && "pointer-events-none opacity-0",
          )}
        />
        <ResizablePanel
          panelRef={panelRef}
          defaultSize={isNewThread ? 0 : 34}
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
              <div className="size-full p-3">
                <ResizablePanelGroup orientation="horizontal" id="workspace-directory-panel-group">
                  <ResizablePanel defaultSize={42} minSize={24} id="workspace-directory-explorer">
                    <div className="size-full overflow-y-auto rounded-md border p-2">
                      <ArtifactFileList
                        className="size-full"
                        files={directoryFiles ?? []}
                        threadId={threadId}
                        createdPath={createdDirectoryPath}
                        onCreatedPathChange={setCreatedDirectoryPath}
                        mountedPath={mountedDirectoryPath}
                        onMountedPathChange={setMountedDirectoryPath}
                      />
                    </div>
                  </ResizablePanel>
                  <ResizableHandle
                    id="workspace-directory-panel-separator"
                    withHandle
                    className="mx-1 w-2 bg-muted/85 opacity-100 transition-colors hover:bg-muted"
                  />
                  <ResizablePanel defaultSize={58} minSize={24} id="workspace-directory-preview">
                    <div className="size-full overflow-y-auto rounded-md border">
                      {selectedFile ? (
                        <ArtifactFileDetail
                          className="size-full"
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
