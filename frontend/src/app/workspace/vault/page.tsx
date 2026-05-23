"use client";

import {
  ChevronDownIcon,
  ChevronRightIcon,
  CopyIcon,
  DownloadIcon,
  FileTextIcon,
  FolderIcon,
  Loader2Icon,
  PanelRightCloseIcon,
  PanelRightOpenIcon,
  PlayIcon,
  RefreshCwIcon,
  SaveIcon,
  Trash2Icon,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { usePanelRef } from "react-resizable-panels";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownContent } from "@/components/workspace/messages/markdown-content";
import { VaultEntityBrowser } from "@/components/workspace/vault/vault-entity-browser";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import {
  useDeleteVaultFile,
  useRefreshVaultExplorer,
  useSaveVaultFile,
  useStartVaultIngest,
  useVaultExplorer,
  useVaultFile,
  useVaultIngestStatus,
  useVaultStatus,
} from "@/core/control-plane";
import type { VaultExplorerResponse } from "@/core/control-plane";
import { useI18n } from "@/core/i18n/hooks";
import { streamdownPlugins } from "@/core/streamdown";

type TreeNode = {
  name: string;
  path: string;
  kind: "directory" | "file";
  children?: TreeNode[];
};

function sortTree(nodes: TreeNode[]): TreeNode[] {
  return [...nodes]
    .sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === "directory" ? -1 : 1;
      return a.name.localeCompare(b.name);
    })
    .map((item) => ({
      ...item,
      children: item.children ? sortTree(item.children) : undefined,
    }));
}

export default function VaultPage() {
  const { t } = useI18n();
  const { vaultStatus } = useVaultStatus({ refetchInterval: 20_000 });
  const { explorer, isLoading: explorerLoading } = useVaultExplorer({
    refetchInterval: 10_000,
    listenForRefreshEvents: true,
  });
  const refreshExplorer = useRefreshVaultExplorer();
  const saveVaultFile = useSaveVaultFile();
  const deleteVaultFile = useDeleteVaultFile();
  const { ingestStatus } = useVaultIngestStatus();
  const startIngest = useStartVaultIngest();
  const ingestRunning = ingestStatus?.status === "running" || startIngest.isPending;
  const ingestProgressLabel = (() => {
    if (!ingestStatus) return "";
    if (ingestStatus.status === "running") {
      const total = ingestStatus.total || 0;
      const current = ingestStatus.current_index || 0;
      const title = (ingestStatus.current_title || "").trim();
      const truncated = title.length > 48 ? `${title.slice(0, 48)}…` : title;
      const totalLabel = total > 0 ? String(total) : "?";
      return `Source ${current}/${totalLabel} ingesting${truncated ? ` ${truncated}` : "..."}`;
    }
    if (ingestStatus.status === "success" && ingestStatus.processed > 0) {
      return `Last ingest: updated ${ingestStatus.updated} / ${ingestStatus.processed}`;
    }
    if (ingestStatus.status === "failed" && ingestStatus.last_error) {
      return `Ingest failed: ${ingestStatus.last_error}`;
    }
    return "";
  })();
  const [rootCollapsed, setRootCollapsed] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [previewTab, setPreviewTab] = useState<"preview" | "entities">("entities");
  const [editorCollapsed, setEditorCollapsed] = useState(false);
  const editorPanelRef = usePanelRef();
  const [expandedPaths, setExpandedPaths] = useState<Record<string, boolean>>({});
  const { vaultFile, isLoading: vaultFileLoading } = useVaultFile(selectedPath);
  const [editableContent, setEditableContent] = useState("");
  const effectiveExplorer: VaultExplorerResponse | null = explorer;

  const filesTree = useMemo(
    () =>
      sortTree(
        (effectiveExplorer?.files ?? []).map((node) => ({
          name: node.name,
          path: node.path,
          kind: node.kind === "directory" ? "directory" : "file",
          children: node.children as TreeNode[] | undefined,
        })),
      ),
    [effectiveExplorer?.files],
  );

  const togglePath = (path: string) => {
    setExpandedPaths((current) => ({ ...current, [path]: !current[path] }));
  };

  const renderTree = (nodes: TreeNode[], depth = 0): ReactNode =>
    nodes.map((node) => {
      const isDir = node.kind === "directory";
      const isOpen = Boolean(expandedPaths[node.path]);
      const hasChildren = Boolean(node.children && node.children.length > 0);
      return (
        <div key={node.path}>
          <button
            className="flex w-full items-center gap-1 rounded px-2 py-1 text-left hover:bg-muted"
            style={{ paddingLeft: `${8 + depth * 14}px` }}
            onClick={() => {
              if (isDir) {
                togglePath(node.path);
                return;
              }
              setSelectedPath(node.path);
              setPreviewTab("preview");
            }}
          >
            {isDir ? (
              <>
                {hasChildren ? (
                  isOpen ? <ChevronDownIcon className="size-3.5" /> : <ChevronRightIcon className="size-3.5" />
                ) : (
                  <span className="inline-block size-3.5" />
                )}
                <FolderIcon className="size-3.5" />
              </>
            ) : (
              <>
                <span className="inline-block size-3.5" />
                <FileTextIcon className="size-3.5" />
              </>
            )}
            <span className={selectedPath === node.path ? "font-medium" : ""}>{node.name}</span>
          </button>
          {isDir && isOpen && hasChildren ? renderTree(node.children ?? [], depth + 1) : null}
        </div>
      );
    });

  useEffect(() => {
    document.title = `${t.pages.vault} - ${t.pages.appName}`;
  }, [t.pages.appName, t.pages.vault]);

  useEffect(() => {
    setEditableContent(vaultFile?.content ?? "");
  }, [vaultFile?.content, vaultFile?.path]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="flex size-full flex-col overflow-hidden p-6">
          <div className="grid min-h-0 flex-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div className="flex min-h-0 flex-col md:col-span-2 xl:col-span-3">
              <div className="mb-3 flex shrink-0 flex-row items-center justify-between gap-3">
                <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
                  <h2 className="text-base font-semibold">
                    Knowledge Vault · Sources {Number(vaultStatus?.counts?.sources_total ?? 0)} · Queued{" "}
                    {Number(vaultStatus?.counts?.queued_search_results ?? 0)}
                  </h2>
                  {ingestProgressLabel ? (
                    <span
                      className={`flex items-center gap-1 truncate text-xs ${
                        ingestStatus?.status === "failed" ? "text-destructive" : "text-muted-foreground"
                      }`}
                      title={ingestStatus?.current_title ?? ingestProgressLabel}
                    >
                      {ingestRunning ? <Loader2Icon className="size-3.5 animate-spin" /> : null}
                      <span className="truncate">· {ingestProgressLabel}</span>
                    </span>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      if (ingestRunning) {
                        toast.message("Ingest already running.");
                        return;
                      }
                      startIngest.mutate(undefined, {
                        onSuccess: (payload) => {
                          if (payload.accepted === false) {
                            toast.message(payload.message ?? "Vault ingest already running.");
                          } else {
                            toast.success("Vault ingest started.");
                          }
                        },
                        onError: (error) => toast.error(error.message),
                      });
                    }}
                    disabled={ingestRunning}
                  >
                    {ingestRunning ? (
                      <Loader2Icon className="mr-2 size-4 animate-spin" />
                    ) : (
                      <PlayIcon className="mr-2 size-4" />
                    )}
                    {ingestRunning ? "Ingesting..." : "Run Ingest"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      toast.message("Vault refresh started. Cached snapshot will update when complete.");
                      refreshExplorer.mutate(undefined, {
                        onSuccess: () => toast.success("Vault cache refreshed."),
                        onError: (error) => toast.error(error.message),
                      });
                    }}
                    disabled={refreshExplorer.isPending}
                  >
                    <RefreshCwIcon className={`mr-2 size-4 ${refreshExplorer.isPending ? "animate-spin" : ""}`} />
                    {refreshExplorer.isPending ? "Refreshing..." : "Refresh Cache"}
                  </Button>
                </div>
              </div>
              <div className="min-h-0 flex-1">
                <ResizablePanelGroup
                  id="vault-main-panel-group"
                  orientation="horizontal"
                  className="h-full gap-1"
                >
                  <ResizablePanel
                    id="vault-left-panel"
                    defaultSize={25}
                    minSize={15}
                    className="flex h-full flex-col space-y-3 rounded-md border p-3"
                  >
                    <p className="text-xs text-muted-foreground">/backend/.capybara-home/knowledge_vault/</p>
                    <div className="min-h-0 flex-1 overflow-y-auto space-y-1 text-xs">
                      <button
                        type="button"
                        className="flex w-full items-center gap-1 rounded px-2 py-1 text-left font-medium hover:bg-muted"
                        onClick={() => setRootCollapsed((current) => !current)}
                        aria-expanded={!rootCollapsed}
                        title={rootCollapsed ? "Expand root" : "Collapse root"}
                      >
                        {rootCollapsed ? (
                          <ChevronRightIcon className="size-3.5" />
                        ) : (
                          <ChevronDownIcon className="size-3.5" />
                        )}
                        <FolderIcon className="size-3.5" />
                        <span>vault</span>
                      </button>
                      {!rootCollapsed && renderTree(filesTree, 1)}
                      {!explorerLoading &&
                      (effectiveExplorer?.files?.length ?? 0) === 0 && (
                        <p className="text-muted-foreground px-1">No cached vault items yet.</p>
                      )}
                    </div>
                  </ResizablePanel>
                  <ResizableHandle id="vault-main-handle" withHandle className="mx-2 bg-transparent" />
                  <ResizablePanel
                    id="vault-right-panel"
                    defaultSize={75}
                    minSize={30}
                    className="flex h-full flex-col space-y-3 rounded-md border p-3"
                  >
                    <div className="flex gap-2">
                      <Button size="sm" variant={previewTab === "preview" ? "default" : "outline"} onClick={() => setPreviewTab("preview")}>Preview</Button>
                      <Button size="sm" variant={previewTab === "entities" ? "default" : "outline"} onClick={() => setPreviewTab("entities")}>Entity Browser</Button>
                    </div>
                    {previewTab === "entities" ? (
                      <VaultEntityBrowser
                        onSourceOpen={(sourceId) => {
                          // Best-effort: try to locate the corresponding compiled source file
                          // and switch to the preview tab. The compiled source path lives at
                          // sources/{source_id}.md inside the explorer tree.
                          const targetName = `${sourceId}.md`;
                          const findInTree = (
                            nodes: TreeNode[] | undefined,
                          ): TreeNode | null => {
                            if (!nodes) return null;
                            for (const node of nodes) {
                              if (node.kind === "file" && node.name === targetName) return node;
                              if (node.children) {
                                const hit = findInTree(node.children);
                                if (hit) return hit;
                              }
                            }
                            return null;
                          };
                          const match = findInTree(filesTree);
                          if (match) {
                            setSelectedPath(match.path);
                            setPreviewTab("preview");
                          } else {
                            toast.message("Source file not yet compiled.");
                          }
                        }}
                      />
                    ) : previewTab === "preview" ? (
                      <div className="flex min-h-0 flex-1 flex-col space-y-2">
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-muted-foreground truncate text-xs">{selectedPath ?? "Preview"}</p>
                          <div className="flex items-center gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={async () => {
                                await navigator.clipboard.writeText(editableContent);
                                toast.success("Content copied.");
                              }}
                              disabled={!vaultFile?.path}
                            >
                              <CopyIcon className="mr-1 size-3.5" />
                              Copy
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                if (!vaultFile?.path) return;
                                const blob = new Blob([editableContent], { type: "text/markdown;charset=utf-8" });
                                const url = URL.createObjectURL(blob);
                                const anchor = document.createElement("a");
                                anchor.href = url;
                                anchor.download = vaultFile.path.split("/").pop() ?? "vault-source.md";
                                anchor.click();
                                URL.revokeObjectURL(url);
                              }}
                              disabled={!vaultFile?.path}
                            >
                              <DownloadIcon className="mr-1 size-3.5" />
                              Download
                            </Button>
                            {vaultFile?.editable && !editorCollapsed ? (
                              <Button
                                size="icon-sm"
                                variant="outline"
                                onClick={() => {
                                  if (!vaultFile?.path) return;
                                  saveVaultFile.mutate(
                                    { path: vaultFile.path, content: editableContent },
                                    {
                                      onSuccess: () => toast.success("Raw source updated."),
                                      onError: (error) => toast.error(error.message),
                                    },
                                  );
                                }}
                                disabled={saveVaultFile.isPending}
                                title="Save changes"
                                aria-label="Save changes"
                              >
                                {saveVaultFile.isPending ? (
                                  <Loader2Icon className="size-4 animate-spin" />
                                ) : (
                                  <SaveIcon className="size-4" />
                                )}
                              </Button>
                            ) : null}
                            {vaultFile?.editable ? (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                  if (!vaultFile?.path) return;
                                  if (!window.confirm("Delete this raw source file? This cannot be undone.")) return;
                                  deleteVaultFile.mutate(vaultFile.path, {
                                    onSuccess: () => {
                                      toast.success("Raw source deleted.");
                                      setSelectedPath(null);
                                      setEditableContent("");
                                    },
                                    onError: (error) => toast.error(error.message),
                                  });
                                }}
                                disabled={deleteVaultFile.isPending}
                              >
                                <Trash2Icon className="mr-1 size-3.5" />
                                Delete Source
                              </Button>
                            ) : null}
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              onClick={() => {
                                if (editorCollapsed) {
                                  editorPanelRef.current?.expand();
                                } else {
                                  editorPanelRef.current?.collapse();
                                }
                              }}
                              title={editorCollapsed ? "Show editor" : "Hide editor"}
                              aria-label={editorCollapsed ? "Show editor" : "Hide editor"}
                            >
                              {editorCollapsed ? (
                                <PanelRightOpenIcon className="size-4" />
                              ) : (
                                <PanelRightCloseIcon className="size-4" />
                              )}
                            </Button>
                          </div>
                        </div>
                        <ResizablePanelGroup
                          id="vault-preview-panel-group"
                          orientation="horizontal"
                          className="min-h-0 flex-1"
                        >
                          <ResizablePanel
                            id="vault-markdown-preview-panel"
                            defaultSize={60}
                            minSize={30}
                            className="min-h-0 overflow-y-auto rounded border p-3 text-sm"
                          >
                            <MarkdownContent
                              content={editableContent}
                              isLoading={vaultFileLoading}
                              rehypePlugins={streamdownPlugins.rehypePlugins}
                              className="prose prose-sm max-w-none"
                            />
                          </ResizablePanel>
                          <ResizableHandle
                            id="vault-preview-editor-handle"
                            withHandle
                            className={`mx-2 bg-transparent ${editorCollapsed ? "pointer-events-none opacity-0" : ""}`}
                          />
                          <ResizablePanel
                            id="vault-editor-panel"
                            panelRef={editorPanelRef}
                            defaultSize={40}
                            minSize={20}
                            collapsible
                            collapsedSize={0}
                            onResize={(size) => setEditorCollapsed(size.asPercentage < 1)}
                            className="min-h-0"
                          >
                            <Textarea
                              value={editableContent}
                              onChange={(event) => setEditableContent(event.target.value)}
                              className="size-full min-h-0 resize-none font-mono text-xs"
                              readOnly={!vaultFile?.editable}
                              placeholder={vaultFileLoading ? "Loading..." : "No file selected"}
                            />
                          </ResizablePanel>
                        </ResizablePanelGroup>
                      </div>
                    ) : null}
                  </ResizablePanel>
                </ResizablePanelGroup>
              </div>
            </div>
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
