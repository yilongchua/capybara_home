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
  SaveIcon,
  Trash2Icon,
} from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
  const [previewTab, setPreviewTab] = useState<"preview" | "graph">("graph");
  const [editorCollapsed, setEditorCollapsed] = useState(false);
  const [graphNodeLimit, setGraphNodeLimit] = useState(80);
  const deferredGraphNodeLimit = useDeferredValue(graphNodeLimit);
  const editorPanelRef = usePanelRef();
  const graphContainerRef = useRef<HTMLDivElement | null>(null);
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

  useEffect(() => {
    if (previewTab === "graph") {
      graphContainerRef.current?.scrollTo({ top: 0 });
    }
  }, [previewTab, selectedPath]);

  const graphLayout = useMemo(() => {
    const rawNodes = effectiveExplorer?.graph?.nodes ?? [];
    const rawEdges = effectiveExplorer?.graph?.edges ?? [];
    const MAX_CONCEPT_SEEDS = 28;
    type GraphKind = "source" | "concept" | "entity" | "other";
    const normalizeGraphKind = (value: string): GraphKind => {
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

    const seedBudget = Math.min(MAX_CONCEPT_SEEDS, deferredGraphNodeLimit);
    const conceptSeeds = dedupedNodes.filter((node) => normalizeGraphKind(node.kind || "other") === "concept");
    const entitySeeds = dedupedNodes.filter((node) => normalizeGraphKind(node.kind || "other") === "entity");
    const interleavedSeeds: typeof dedupedNodes = [];
    const seedCursor = Math.max(conceptSeeds.length, entitySeeds.length);
    for (let i = 0; i < seedCursor && interleavedSeeds.length < seedBudget; i += 1) {
      const c = conceptSeeds[i];
      if (c && interleavedSeeds.length < seedBudget) interleavedSeeds.push(c);
      const e = entitySeeds[i];
      if (e && interleavedSeeds.length < seedBudget) interleavedSeeds.push(e);
    }

    const selectedNodeIds = new Set<string>(interleavedSeeds.map((node) => node.id));
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
        if (selectedNodeIds.size >= deferredGraphNodeLimit) break;
        selectedNodeIds.add(nodeId);
      }
    }
    const selectedNodes =
      selectedNodeIds.size > 0
        ? dedupedNodes.filter((node) => selectedNodeIds.has(node.id)).slice(0, deferredGraphNodeLimit)
        : dedupedNodes.slice(0, deferredGraphNodeLimit);
    const nodeIdSet = new Set(selectedNodes.map((node) => node.id));
    const edges = connectedEdges.filter((edge) => nodeIdSet.has(edge.source) && nodeIdSet.has(edge.target));

    const width = 900;
    const height = 520;
    const cx = width / 2;
    const radiusByKind: Record<GraphKind, number> = {
      concept: Math.min(width, height) * 0.18,
      entity: Math.min(width, height) * 0.28,
      source: Math.min(width, height) * 0.36,
      other: Math.min(width, height) * 0.46,
    };
    const activeMaxRadius = Math.max(
      ...selectedNodes.map((node) => radiusByKind[normalizeGraphKind(node.kind || "other")] ?? radiusByKind.other),
      radiusByKind.concept,
    );
    const topPadding = 36;
    const cy = topPadding + activeMaxRadius;

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
    return {
      width,
      height,
      nodes: positioned,
      edges: visibleEdges,
      label,
      colorForKind,
      totalAvailable: dedupedNodes.length,
      rawNodeCount: rawNodes.length,
    };
  }, [deferredGraphNodeLimit, effectiveExplorer?.graph?.edges, effectiveExplorer?.graph?.nodes]);

  const graphLegend = useMemo(
    () => [
      { kind: "concept", label: "Concept", color: "#1d4ed8" },
      { kind: "entity", label: "Entity", color: "#7c3aed" },
      { kind: "source", label: "Source", color: "#0f766e" },
      { kind: "other", label: "Other (syntheses / queries)", color: "#64748b" },
    ],
    [],
  );

  const graphKindCounts = useMemo(() => {
    const counts = { concept: 0, entity: 0, source: 0, other: 0 };
    for (const node of graphLayout.nodes) {
      const kind = (node.kind || "other").toLowerCase();
      if (kind.includes("concept")) counts.concept += 1;
      else if (kind.includes("entity")) counts.entity += 1;
      else if (kind.includes("source")) counts.source += 1;
      else counts.other += 1;
    }
    return counts;
  }, [graphLayout.nodes]);

  const effectiveSliderMax = Math.max(10, Math.min(160, graphLayout.totalAvailable || 160));

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
                    ) : (
                      <div className="min-h-0 flex-1 space-y-2 text-xs">
                        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                          <p className="text-muted-foreground">
                            <NetworkIcon className="mr-1 inline size-3.5" />
                            Showing {graphLayout.nodes.length} of {graphLayout.totalAvailable} nodes
                            {graphLayout.rawNodeCount > graphLayout.totalAvailable
                              ? ` (deduped from ${graphLayout.rawNodeCount})`
                              : ""}
                            {" · "}Edges {graphLayout.edges.length}
                          </p>
                          <label className="flex items-center gap-2 text-muted-foreground">
                            <span>
                              Max nodes:{" "}
                              {Math.min(graphNodeLimit, effectiveSliderMax)}
                              {graphNodeLimit > effectiveSliderMax ? ` (cap ${effectiveSliderMax})` : ""}
                            </span>
                            <input
                              type="range"
                              min={10}
                              max={160}
                              step={10}
                              value={graphNodeLimit}
                              onChange={(event) => setGraphNodeLimit(Number(event.target.value))}
                              className="w-32"
                              aria-label="Knowledge graph max node count"
                              title="Maximum nodes to render. Actual count may be lower after dedup/connectivity filtering."
                            />
                          </label>
                        </div>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-muted-foreground">
                          <span className="font-medium">Legend:</span>
                          {graphLegend.map((item) => (
                            <span key={item.kind} className="flex items-center gap-1.5">
                              <span
                                className="inline-block size-2.5 rounded-full"
                                style={{ backgroundColor: item.color }}
                                aria-hidden
                              />
                              <span>
                                {item.label} ({graphKindCounts[item.kind as keyof typeof graphKindCounts]})
                              </span>
                            </span>
                          ))}
                        </div>
                        <div ref={graphContainerRef} className="h-full min-h-0 overflow-auto rounded border p-2">
                          <svg
                            viewBox={`0 0 ${graphLayout.width} ${graphLayout.height}`}
                            preserveAspectRatio="xMidYMin meet"
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
