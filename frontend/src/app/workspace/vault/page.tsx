"use client";

import {
  ChevronDownIcon,
  ChevronRightIcon,
  CopyIcon,
  DownloadIcon,
  FileTextIcon,
  FolderIcon,
  Loader2Icon,
  NetworkIcon,
  PanelRightCloseIcon,
  PanelRightOpenIcon,
  PlayIcon,
  RefreshCwIcon,
  Trash2Icon,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { usePanelRef } from "react-resizable-panels";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownContent } from "@/components/workspace/messages/markdown-content";
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

function insertTreePath(nodes: TreeNode[], path: string) {
  const clean = path.trim().replace(/^\/+/, "");
  if (!clean) return;
  const parts = clean.split("/").filter(Boolean);
  let cursor = nodes;
  let full = "";
  parts.forEach((part, index) => {
    full = full ? `${full}/${part}` : part;
    let node = cursor.find((item) => item.path === full);
    if (!node) {
      node = {
        name: part,
        path: full,
        kind: index === parts.length - 1 ? "file" : "directory",
        children: [],
      };
      cursor.push(node);
    }
    if (index < parts.length - 1) {
      node.kind = "directory";
      node.children = node.children ?? [];
      cursor = node.children;
    }
  });
}

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
  const [leftSection, setLeftSection] = useState<"raw" | "knowledge" | "files">("raw");
  const [rootCollapsed, setRootCollapsed] = useState<Record<string, boolean>>({});
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [previewTab, setPreviewTab] = useState<"preview" | "graph">("preview");
  const [editorCollapsed, setEditorCollapsed] = useState(false);
  const editorPanelRef = usePanelRef();
  const [expandedPaths, setExpandedPaths] = useState<Record<string, boolean>>({});
  const { vaultFile, isLoading: vaultFileLoading } = useVaultFile(selectedPath);
  const [editableContent, setEditableContent] = useState("");
  const effectiveExplorer: VaultExplorerResponse | null = explorer;

  const rawTree = useMemo(() => {
    const root: TreeNode[] = [];
    (effectiveExplorer?.raw_sources ?? []).forEach((item) => {
      if (item.raw_path) insertTreePath(root, item.raw_path);
    });
    return sortTree(root);
  }, [effectiveExplorer?.raw_sources]);

  const knowledgeTree = useMemo(() => {
    const groups: Array<{ label: string; key: "entities" | "concepts" | "sources" | "others" }> = [
      { label: "Entities", key: "entities" },
      { label: "Concepts", key: "concepts" },
      { label: "Sources", key: "sources" },
      { label: "Others", key: "others" },
    ];
    return groups.map((group) => ({
      name: group.label,
      path: `knowledge/${group.key}`,
      kind: "directory" as const,
      children: sortTree(
        (effectiveExplorer?.knowledge?.[group.key] ?? []).map((node) => ({
          name: node.name,
          path: node.path,
          kind: node.kind === "directory" ? "directory" : "file",
          children: (node.children ?? []).map((child) => ({
            name: child.name,
            path: child.path,
            kind: child.kind === "directory" ? "directory" : "file",
            children: child.children as TreeNode[] | undefined,
          })),
        })),
      ),
    }));
  }, [effectiveExplorer?.knowledge]);

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

  const graphLayout = useMemo(() => {
    const rawNodes = effectiveExplorer?.graph?.nodes ?? [];
    const rawEdges = effectiveExplorer?.graph?.edges ?? [];
    const MAX_GRAPH_NODES = 80;
    const MAX_CONCEPT_SEEDS = 28;
    const normalizeGraphKind = (value: string) => {
      const kind = value.toLowerCase();
      if (kind.includes("source")) return "source";
      if (kind.includes("concept")) return "concept";
      if (kind.includes("entity")) return "entity";
      return "other";
    };

    const normalized = (value: string) =>
      value
        .toLowerCase()
        .replace(/[^a-z0-9\s]/g, " ")
        .replace(/\s+/g, " ")
        .trim();

    const dedupByLabel = new Map<string, (typeof rawNodes)[number]>();
    for (const node of rawNodes) {
      const key = normalized(node.label || node.id || "");
      if (!key) continue;
      const existing = dedupByLabel.get(key);
      if (!existing || (node.degree ?? 0) > (existing.degree ?? 0)) {
        dedupByLabel.set(key, node);
      }
    }
    const dedupedNodes = [...dedupByLabel.values()].sort((a, b) => (b.degree ?? 0) - (a.degree ?? 0));
    const byId = new Map(dedupedNodes.map((node) => [node.id, node] as const));
    const connectedEdges = rawEdges.filter((edge) => byId.has(edge.source) && byId.has(edge.target));

    const conceptSeeds = dedupedNodes
      .filter((node) => normalizeGraphKind(node.kind || "other") === "concept")
      .slice(0, MAX_CONCEPT_SEEDS);

    const selectedNodeIds = new Set<string>(conceptSeeds.map((node) => node.id));
    if (selectedNodeIds.size > 0) {
      const neighborScore = new Map<string, number>();
      for (const edge of connectedEdges) {
        const sourceSelected = selectedNodeIds.has(edge.source);
        const targetSelected = selectedNodeIds.has(edge.target);
        if (!sourceSelected && !targetSelected) continue;
        const neighborId = sourceSelected ? edge.target : edge.source;
        if (selectedNodeIds.has(neighborId)) continue;
        const neighbor = byId.get(neighborId);
        if (!neighbor) continue;
        const score = Number(neighbor.degree ?? 0) + 1;
        neighborScore.set(neighborId, (neighborScore.get(neighborId) ?? 0) + score);
      }
      const rankedNeighbors = [...neighborScore.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([nodeId]) => nodeId);
      for (const nodeId of rankedNeighbors) {
        if (selectedNodeIds.size >= MAX_GRAPH_NODES) break;
        selectedNodeIds.add(nodeId);
      }
    }
    const selectedNodes =
      selectedNodeIds.size > 0
        ? dedupedNodes.filter((node) => selectedNodeIds.has(node.id))
        : dedupedNodes.slice(0, MAX_GRAPH_NODES);
    const nodeIdSet = new Set(selectedNodes.map((node) => node.id));
    const edges = connectedEdges.filter((edge) => nodeIdSet.has(edge.source) && nodeIdSet.has(edge.target));

    const width = 900;
    const height = 520;
    const cx = width / 2;
    const cy = height / 2;
    const radiusByKind: Record<string, number> = {
      concept: Math.min(width, height) * 0.18,
      entity: Math.min(width, height) * 0.28,
      source: Math.min(width, height) * 0.36,
      other: Math.min(width, height) * 0.46,
    };

    const nodesByKind = new Map<string, typeof selectedNodes>();
    for (const node of selectedNodes) {
      const kind = normalizeGraphKind(node.kind || "other");
      const bucket = nodesByKind.get(kind) ?? [];
      bucket.push(node);
      nodesByKind.set(kind, bucket);
    }

    const kindOrder = ["concept", "entity", "source", "other"];
    const positioned = kindOrder.flatMap((kind) => {
      const bucket = nodesByKind.get(kind) ?? [];
      return bucket.map((node, index) => {
        const angle = (index / Math.max(1, bucket.length)) * Math.PI * 2;
        const radius = radiusByKind[kind] ?? radiusByKind.other ?? 180;
        return {
          ...node,
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
        };
      });
    });

    const label = (text: string) => {
      const clean = text.replace(/\s+/g, " ").trim();
      return clean.length > 24 ? `${clean.slice(0, 24)}...` : clean;
    };

    const colorForKind = (kind: string) => {
      const normalizedKind = kind.toLowerCase();
      if (normalizedKind.includes("source")) return "#0f766e";
      if (normalizedKind.includes("concept")) return "#1d4ed8";
      if (normalizedKind.includes("entity")) return "#7c3aed";
      return "#64748b";
    };

    const positionedById = new Map(positioned.map((node) => [node.id, node] as const));
    const visibleEdges = edges
      .map((edge) => {
        const source = positionedById.get(edge.source);
        const target = positionedById.get(edge.target);
        if (!source || !target) return null;
        return {
          ...edge,
          source,
          target,
        };
      })
      .filter((edge): edge is NonNullable<typeof edge> => Boolean(edge));
    return { width, height, nodes: positioned, edges: visibleEdges, label, colorForKind };
  }, [effectiveExplorer?.graph?.edges, effectiveExplorer?.graph?.nodes]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="flex size-full flex-col overflow-y-auto p-6">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <div className="md:col-span-2 xl:col-span-3">
              <div className="mb-3 flex flex-row items-center justify-between gap-3">
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
              <div>
                <ResizablePanelGroup
                  id="vault-main-panel-group"
                  orientation="horizontal"
                  className="min-h-[78vh] gap-1"
                >
                  <ResizablePanel
                    id="vault-left-panel"
                    defaultSize={25}
                    minSize={15}
                    className="flex h-full flex-col space-y-3 rounded-md border p-3"
                  >
                    <div className="flex gap-2">
                      <Button size="sm" variant={leftSection === "raw" ? "default" : "outline"} onClick={() => setLeftSection("raw")}>Raw Sources</Button>
                      <Button size="sm" variant={leftSection === "knowledge" ? "default" : "outline"} onClick={() => setLeftSection("knowledge")}>Knowledge</Button>
                      <Button size="sm" variant={leftSection === "files" ? "default" : "outline"} onClick={() => setLeftSection("files")}>Files</Button>
                    </div>
                    <div className="min-h-0 flex-1 overflow-y-auto space-y-1 text-xs">
                      {(() => {
                        const rootLabels: Record<string, string> = {
                          raw: "01_raw",
                          knowledge: "02_knowledge",
                          files: "vault",
                        };
                        const isCollapsed = rootCollapsed[leftSection] ?? false;
                        const activeTree =
                          leftSection === "raw" ? rawTree : leftSection === "knowledge" ? knowledgeTree : filesTree;
                        return (
                          <>
                            <button
                              type="button"
                              className="flex w-full items-center gap-1 rounded px-2 py-1 text-left font-medium hover:bg-muted"
                              onClick={() =>
                                setRootCollapsed((current) => ({
                                  ...current,
                                  [leftSection]: !isCollapsed,
                                }))
                              }
                              aria-expanded={!isCollapsed}
                              title={isCollapsed ? "Expand root" : "Collapse root"}
                            >
                              {isCollapsed ? (
                                <ChevronRightIcon className="size-3.5" />
                              ) : (
                                <ChevronDownIcon className="size-3.5" />
                              )}
                              <FolderIcon className="size-3.5" />
                              <span>{rootLabels[leftSection]}</span>
                            </button>
                            {!isCollapsed && renderTree(activeTree, 1)}
                          </>
                        );
                      })()}
                      {!explorerLoading &&
                      (effectiveExplorer?.raw_sources?.length ?? 0) === 0 &&
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
                      <Button size="sm" variant={previewTab === "graph" ? "default" : "outline"} onClick={() => setPreviewTab("graph")}>Knowledge Graph</Button>
                    </div>
                    {previewTab === "preview" ? (
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
                        {vaultFile?.editable && !editorCollapsed ? (
                          <Button
                            size="sm"
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
                            className="self-start"
                          >
                            {saveVaultFile.isPending ? "Saving..." : "Save Changes"}
                          </Button>
                        ) : null}
                      </div>
                    ) : (
                      <div className="min-h-0 flex-1 space-y-2 text-xs">
                        <p className="text-muted-foreground">
                          <NetworkIcon className="mr-1 inline size-3.5" />
                          Nodes {graphLayout.nodes.length} (trimmed) · Edges {graphLayout.edges.length}
                        </p>
                        <div className="h-full min-h-0 overflow-auto rounded border p-2">
                          <svg
                            viewBox={`0 0 ${graphLayout.width} ${graphLayout.height}`}
                            className="h-full min-h-[420px] w-full"
                            role="img"
                            aria-label="Knowledge graph"
                          >
                            {graphLayout.edges.map((edge, index) => (
                              <line
                                key={`${edge.source.id}-${edge.target.id}-${index}`}
                                x1={edge.source.x}
                                y1={edge.source.y}
                                x2={edge.target.x}
                                y2={edge.target.y}
                                stroke="currentColor"
                                strokeOpacity={0.22}
                                strokeWidth={1}
                              />
                            ))}
                            {graphLayout.nodes.map((node) => (
                              <g key={node.id}>
                                <title>{`${node.label} (${node.kind})`}</title>
                                <circle
                                  cx={node.x}
                                  cy={node.y}
                                  r={Math.max(5, Math.min(10, 5 + ((node.degree ?? 0) / 4)))}
                                  fill={graphLayout.colorForKind(node.kind ?? "other")}
                                  fillOpacity={0.9}
                                />
                                <text x={node.x + 10} y={node.y + 3} fontSize={10} fill="currentColor" fillOpacity={0.85}>
                                  {graphLayout.label(node.label)}
                                </text>
                              </g>
                            ))}
                          </svg>
                        </div>
                      </div>
                    )}
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
