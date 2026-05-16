"use client";

import {
  CalendarClockIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  FileTextIcon,
  FolderIcon,
  ListChecksIcon,
  NetworkIcon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { getBackendBaseURL } from "@/core/config";
import {
  useAutoresearchObjectives,
  useDeleteAutoresearchObjective,
  useIntegrationStatus,
  useRunSchedulerJob,
  useRefreshVaultExplorer,
  useSaveToVault,
  useSaveVaultFile,
  useStartAutoresearchObjective,
  useUpdateRuntimeSchedulerJob,
  useUpdateRuntimeSchedulerJobTime,
  useVaultExplorer,
  useVaultFile,
  useVaultGraph,
  useVaultSearch,
  useVaultStatus,
} from "@/core/control-plane";
import { useI18n } from "@/core/i18n/hooks";
import { formatTimeAgo } from "@/core/utils/datetime";

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

const SCHEDULE_OPTIONS = Array.from({ length: 96 }, (_, i) => {
  const h = Math.floor(i / 4).toString().padStart(2, "0");
  const m = ((i % 4) * 15).toString().padStart(2, "0");
  return `${h}:${m}`;
});

function EndpointInput({
  initialValue,
  placeholder,
  onSave,
}: {
  initialValue: string;
  placeholder: string;
  onSave: (value: string) => void;
}) {
  const [value, setValue] = useState(initialValue);
  const savedRef = useRef(initialValue.trim());

  useEffect(() => {
    setValue(initialValue);
    savedRef.current = initialValue.trim();
  }, [initialValue]);

  const commit = () => {
    const trimmed = value.trim();
    if (trimmed === savedRef.current) return;
    savedRef.current = trimmed;
    onSave(trimmed);
  };

  return (
    <Textarea
      className="max-h-36 min-h-24 overflow-y-auto text-xs"
      placeholder={placeholder || "Enter endpoint goal…"}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") e.currentTarget.blur();
      }}
    />
  );
}

export default function VaultPage() {
  const { t } = useI18n();
  const { integrationStatus } = useIntegrationStatus();
  const { objectives, isLoading } = useAutoresearchObjectives({
    refetchInterval: 20_000,
  });
  const { vaultStatus } = useVaultStatus({ refetchInterval: 20_000 });
  const { vaultGraph } = useVaultGraph({ refetchInterval: 20_000, limit: 120 });
  const { explorer, isLoading: explorerLoading } = useVaultExplorer();
  const refreshExplorer = useRefreshVaultExplorer();
  const saveVaultFile = useSaveVaultFile();
  const startAutoresearch = useStartAutoresearchObjective();
  const runSchedulerJob = useRunSchedulerJob();
  const saveToVault = useSaveToVault();
  const deleteAutoresearchObjective = useDeleteAutoresearchObjective();
  const updateSchedulerJobTime = useUpdateRuntimeSchedulerJobTime();
  const updateSchedulerJob = useUpdateRuntimeSchedulerJob();
  const [openCreateDialog, setOpenCreateDialog] = useState(false);
  const [newTopic, setNewTopic] = useState("");
  const [endpointGoal, setEndpointGoal] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [saveTitle, setSaveTitle] = useState("");
  const [saveContent, setSaveContent] = useState("");
  const [objectiveProgress, setObjectiveProgress] = useState<Record<string, number>>({});
  const [leftSection, setLeftSection] = useState<"raw" | "knowledge" | "files">("raw");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [previewTab, setPreviewTab] = useState<"preview" | "graph">("preview");
  const [expandedPaths, setExpandedPaths] = useState<Record<string, boolean>>({});
  const { vaultFile, isLoading: vaultFileLoading } = useVaultFile(selectedPath);
  const [editableContent, setEditableContent] = useState("");
  const toText = (value: unknown) => (typeof value === "string" ? value : "");
  const firstNonEmpty = (...values: string[]) =>
    values.map((item) => item.trim()).find((item) => item.length > 0) ?? "";
  const { results: vaultSearchResults, isLoading: isSearchLoading } = useVaultSearch(searchQuery, {
    enabled: searchQuery.trim().length > 1,
    limit: 8,
  });
  const rawTree = useMemo(() => {
    const root: TreeNode[] = [];
    (explorer?.raw_sources ?? []).forEach((item) => {
      if (item.raw_path) insertTreePath(root, item.raw_path);
    });
    return sortTree(root);
  }, [explorer?.raw_sources]);

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
        (explorer?.knowledge?.[group.key] ?? []).map((node) => ({
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
  }, [explorer?.knowledge]);

  const filesTree = useMemo(
    () =>
      sortTree(
        (explorer?.files ?? []).map((node) => ({
          name: node.name,
          path: node.path,
          kind: node.kind === "directory" ? "directory" : "file",
          children: node.children as TreeNode[] | undefined,
        })),
      ),
    [explorer?.files],
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

  const handleSaveToVault = () => {
    const title = saveTitle.trim();
    const content = saveContent.trim();
    if (!title || !content) {
      toast.error("Enter both a title and content to save.");
      return;
    }
    saveToVault.mutate(
      { title, content, topic: title },
      {
        onSuccess: () => {
          toast.success("Saved to Knowledge Vault.");
          setSaveTitle("");
          setSaveContent("");
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  const handleCreateObjective = () => {
    const topic = newTopic.trim();
    const endpoint = endpointGoal.trim();
    if (!topic) {
      toast.error("Enter a topic first.");
      return;
    }
    if (!endpoint) {
      toast.error("Enter an endpoint goal.");
      return;
    }
    startAutoresearch.mutate(
      { topic, endpoint_goal: endpoint, bootstrap: true },
      {
        onSuccess: () => {
          toast.success("Autoresearch objective created.");
          setOpenCreateDialog(false);
          setNewTopic("");
          setEndpointGoal("");
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  const suggestEndpoint = (topic: string) =>
    `Deliver a complete, evidence-backed research brief for ${topic || "this topic"} with actionable next steps.`;

  const scheduleJobByObjectiveId = useMemo(() => {
    const entries = (integrationStatus?.scheduler.jobs ?? []).filter(
      (job) => (job.schedule_type ?? "interval") === "daily_time",
    );
    return new Map(
      entries
        .map((job) => [toText(job.inputs?.objective_id).trim(), job] as const)
        .filter(([objectiveId]) => objectiveId.length > 0),
    );
  }, [integrationStatus?.scheduler.jobs]);

  useEffect(() => {
    let cancelled = false;
    async function loadProgress() {
      const entries = await Promise.all(
        objectives.map(async (objective) => {
          const link = `${getBackendBaseURL()}/api/vault/objectives/${encodeURIComponent(
            objective.objective_id,
          )}/progress.md`;
          try {
            const response = await fetch(link);
            if (!response.ok) return [objective.objective_id, 0] as const;
            const markdown = await response.text();
            const percentPattern = /- Percent:\s*`?([0-9]+(?:\.[0-9]+)?)%`?/i;
            const match = percentPattern.exec(markdown);
            const parsed = match ? Number(match[1]) : 0;
            return [objective.objective_id, Number.isFinite(parsed) ? parsed : 0] as const;
          } catch {
            return [objective.objective_id, 0] as const;
          }
        }),
      );
      if (cancelled) return;
      setObjectiveProgress(Object.fromEntries(entries));
    }
    void loadProgress();
    return () => {
      cancelled = true;
    };
  }, [objectives]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="flex size-full flex-col overflow-y-auto">
          <div className="border-b px-6 py-4">
            <h1 className="text-xl font-semibold">{t.pages.vault}</h1>
            <p className="text-muted-foreground mt-0.5 text-sm">
              Knowledge Vault
              {" · "}
              Sources {Number(vaultStatus?.counts?.sources_total ?? 0)}
              {" · "}
              Queued {Number(vaultStatus?.counts?.queued_search_results ?? 0)}
              {" · "}
              Objectives {objectives.length}
            </p>
          </div>

          <div className="grid gap-4 p-6 md:grid-cols-2 xl:grid-cols-3">
            <Card className="md:col-span-2 xl:col-span-3">
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="text-base">Knowledge Vault Directory</CardTitle>
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
              </CardHeader>
              <CardContent>
                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="space-y-3 rounded-md border p-3">
                    <div className="flex gap-2">
                      <Button size="sm" variant={leftSection === "raw" ? "default" : "outline"} onClick={() => setLeftSection("raw")}>Raw Sources</Button>
                      <Button size="sm" variant={leftSection === "knowledge" ? "default" : "outline"} onClick={() => setLeftSection("knowledge")}>Knowledge</Button>
                      <Button size="sm" variant={leftSection === "files" ? "default" : "outline"} onClick={() => setLeftSection("files")}>Files</Button>
                    </div>
                    <div className="max-h-80 overflow-y-auto space-y-1 text-xs">
                      {leftSection === "raw" && renderTree(rawTree)}
                      {leftSection === "knowledge" && renderTree(knowledgeTree)}
                      {leftSection === "files" && renderTree(filesTree)}
                      {!explorerLoading && !(explorer?.raw_sources?.length || explorer?.files?.length) && (
                        <p className="text-muted-foreground px-1">No cached vault items yet.</p>
                      )}
                    </div>
                  </div>
                  <div className="space-y-3 rounded-md border p-3">
                    <div className="flex gap-2">
                      <Button size="sm" variant={previewTab === "preview" ? "default" : "outline"} onClick={() => setPreviewTab("preview")}>Preview</Button>
                      <Button size="sm" variant={previewTab === "graph" ? "default" : "outline"} onClick={() => setPreviewTab("graph")}>Knowledge Graph</Button>
                    </div>
                    {previewTab === "preview" ? (
                      <div className="space-y-2">
                        <p className="text-muted-foreground text-xs">{selectedPath ?? "Select a file to preview."}</p>
                        <Textarea
                          value={editableContent}
                          onChange={(event) => setEditableContent(event.target.value)}
                          className="min-h-72 font-mono text-xs"
                          readOnly={!vaultFile?.editable}
                          placeholder={vaultFileLoading ? "Loading..." : "No file selected"}
                        />
                        {vaultFile?.editable && (
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
                          >
                            {saveVaultFile.isPending ? "Saving..." : "Save Raw Source"}
                          </Button>
                        )}
                      </div>
                    ) : (
                      <div className="space-y-2 text-xs">
                        <p>Nodes: {Number(explorer?.graph?.counts?.nodes ?? vaultGraph?.counts?.nodes ?? 0)}</p>
                        <p>Edges: {Number(explorer?.graph?.counts?.edges ?? vaultGraph?.counts?.edges ?? 0)}</p>
                        <div className="max-h-72 space-y-1 overflow-y-auto rounded border p-2">
                          {(explorer?.graph?.nodes ?? vaultGraph?.nodes ?? []).slice(0, 40).map((node) => (
                            <div key={node.id} className="text-muted-foreground">
                              {node.kind}: {node.label}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="xl:col-span-1">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <SearchIcon className="size-4" />
                  Vault Search
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <Input
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="Search cached research, clips, and syntheses"
                />
                <div className="space-y-2">
                  {isSearchLoading ? (
                    <p className="text-muted-foreground text-xs">Searching…</p>
                  ) : vaultSearchResults?.items?.length ? (
                    vaultSearchResults.items.map((item) => (
                      <div key={`${item.path}-${item.rank}`} className="rounded-md border p-2">
                        <p className="text-sm font-medium">{item.title ?? item.path}</p>
                        <p className="text-muted-foreground mt-1 line-clamp-3 text-xs">
                          {item.snippet ?? "No snippet available."}
                        </p>
                      </div>
                    ))
                  ) : (
                    <p className="text-muted-foreground text-xs">
                      {searchQuery.trim().length > 1
                        ? "No cached matches yet."
                        : "Search the local vault to reuse previous research."}
                    </p>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card className="xl:col-span-1">
              <CardHeader>
                <CardTitle className="text-base">Save To Vault</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <Input
                  value={saveTitle}
                  onChange={(event) => setSaveTitle(event.target.value)}
                  placeholder="Short title"
                />
                <Textarea
                  value={saveContent}
                  onChange={(event) => setSaveContent(event.target.value)}
                  className="min-h-32"
                  placeholder="Paste a useful answer, summary, or curated note"
                />
                <Button onClick={handleSaveToVault} disabled={saveToVault.isPending}>
                  {saveToVault.isPending ? "Saving..." : "Save"}
                </Button>
              </CardContent>
            </Card>

            <Card className="xl:col-span-1">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <NetworkIcon className="size-4" />
                  Vault Graph
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-md border p-2">
                    <p className="text-muted-foreground">Nodes</p>
                    <p className="text-sm font-semibold">{Number(vaultGraph?.counts?.nodes ?? 0)}</p>
                  </div>
                  <div className="rounded-md border p-2">
                    <p className="text-muted-foreground">Edges</p>
                    <p className="text-sm font-semibold">{Number(vaultGraph?.counts?.edges ?? 0)}</p>
                  </div>
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium">Most connected</p>
                  <div className="space-y-1">
                    {Array.isArray(vaultGraph?.highlights?.top_connected) &&
                    vaultGraph.highlights.top_connected.length > 0 ? (
                      vaultGraph.highlights.top_connected.slice(0, 5).map((node) => {
                        const typedNode = node as { id?: string; label?: string; degree?: number; kind?: string };
                        return (
                          <div
                            key={typedNode.id}
                            className="flex items-center justify-between rounded-md border px-2 py-1 text-xs"
                          >
                            <span>{typedNode.label ?? typedNode.id}</span>
                            <Badge variant="outline">
                              {(typedNode.kind ?? "node").toString()} · {Number(typedNode.degree ?? 0)}
                            </Badge>
                          </div>
                        );
                      })
                    ) : (
                      <p className="text-muted-foreground text-xs">Graph connections will appear as the vault grows.</p>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>

            {isLoading ? (
              <Card>
                <CardContent className="pt-6 text-sm">{t.common.loading}</CardContent>
              </Card>
            ) : (
              objectives.map((objective) => {
                const nextQueries = objective.recommended_queries ?? [];
                const nextTasks = objective.recommended_tasks ?? [];
                const markdownPath = objective.progress_markdown_path ?? "";
                const progressLink = `${getBackendBaseURL()}/api/vault/objectives/${encodeURIComponent(
                  objective.objective_id,
                )}/progress.md`;
                const progressPercent = objectiveProgress[objective.objective_id] ?? 0;

                return (
                  <Card key={objective.id} className="h-full">
                    <CardHeader className="space-y-1">
                      <div className="flex items-start justify-between gap-2">
                        <CardTitle className="text-base">
                          {objective.topic || objective.objective_id}
                        </CardTitle>
                        <Badge
                          variant={
                            objective.status === "active" ? "secondary" : "outline"
                          }
                        >
                          {objective.status}
                        </Badge>
                      </div>
                      <div className="space-y-1">
                        <div className="flex items-center justify-end text-xs">
                          <span className="text-muted-foreground">{progressPercent.toFixed(1)}%</span>
                        </div>
                        <Progress value={Math.max(0, Math.min(100, progressPercent))} className="h-1.5" />
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3 text-sm">
                      {(() => {
                        const job = scheduleJobByObjectiveId.get(objective.objective_id);
                        if (!job) return null;
                        const currentTime = job.daily_time ?? "02:00";
                        const endpointPlaceholder = firstNonEmpty(
                          objective.endpoint_goal ?? "",
                          toText(job.inputs?.endpoint_goal),
                          "Enter endpoint goal…",
                        );
                        const endpointValue = firstNonEmpty(
                          toText(job.inputs?.endpoint_goal),
                          objective.endpoint_goal ?? "",
                        );

                        return (
                          <div className="space-y-3 rounded-md border p-3">
                            <p className="flex items-center gap-1 text-xs font-medium">
                              <CalendarClockIcon className="size-3.5" />
                              Scheduled Pipeline Controls
                            </p>
                            <div className="flex items-center gap-2 text-xs">
                              <span className="text-muted-foreground shrink-0">Schedule:</span>
                              <Select
                                value={currentTime}
                                onValueChange={(value) =>
                                  updateSchedulerJobTime.mutate(
                                    { jobId: job.id, dailyTime: value },
                                    {
                                      onSuccess: () => toast.success(`Schedule updated to ${value}.`),
                                      onError: (error) => toast.error(error.message),
                                    },
                                  )
                                }
                              >
                                <SelectTrigger className="h-7 w-28 text-xs">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent className="max-h-56">
                                  {SCHEDULE_OPTIONS.map((time) => (
                                    <SelectItem key={time} value={time} className="text-xs">
                                      {time}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                              <span className="text-muted-foreground">(workspace timezone)</span>
                            </div>
                            <div className="space-y-1">
                              <p className="text-muted-foreground text-xs">Endpoint:</p>
                              <EndpointInput
                                initialValue={endpointValue}
                                placeholder={endpointPlaceholder}
                                onSave={(newValue) =>
                                  updateSchedulerJob.mutate(
                                    { jobId: job.id, patch: { endpoint_goal: newValue } },
                                    {
                                      onSuccess: () => toast.success("Endpoint updated."),
                                      onError: (error) => toast.error(error.message),
                                    },
                                  )
                                }
                              />
                            </div>
                            <div className="flex gap-2">
                              <Button
                                className="flex-1"
                                size="sm"
                                onClick={() =>
                                  runSchedulerJob.mutate(job.id, {
                                    onSuccess: () => toast.success("Run started."),
                                    onError: (error) => toast.error(error.message),
                                  })
                                }
                                disabled={runSchedulerJob.isPending}
                              >
                                <PlayIcon className="size-4" />
                                Run
                              </Button>
                            </div>
                          </div>
                        );
                      })()}

                      <Button
                        variant="destructive"
                        size="sm"
                        className="w-full"
                        onClick={() => {
                          if (!window.confirm("Delete this objective and all its vault tracking files? This cannot be undone.")) return;
                          deleteAutoresearchObjective.mutate(objective.objective_id, {
                            onSuccess: () => toast.success("Objective deleted."),
                            onError: (error) => toast.error(error.message),
                          });
                        }}
                        disabled={deleteAutoresearchObjective.isPending}
                      >
                        <Trash2Icon className="size-4" />
                        Delete Objective
                      </Button>

                      <div className="rounded-md border p-3">
                        <p className="text-xs font-medium">Tracking Markdown</p>
                        <a
                          className="text-primary mt-1 inline-flex items-center gap-1 text-xs underline"
                          href={progressLink}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <FileTextIcon className="size-3.5" />
                          {markdownPath || "Open objective ledger"}
                        </a>
                      </div>

                      <Collapsible>
                        <CollapsibleTrigger className="flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-xs font-medium">
                          <span className="inline-flex items-center gap-1">
                            <ListChecksIcon className="size-3.5" />
                            Action Items / Next Queries
                          </span>
                          <ChevronDownIcon className="size-4" />
                        </CollapsibleTrigger>
                        <CollapsibleContent className="mt-2 rounded-md border p-3">
                          {nextTasks.length > 0 && (
                            <div className="mb-2">
                              <p className="mb-1 text-[11px] font-medium">Action items</p>
                              <ul className="space-y-1">
                                {nextTasks.map((task, idx) => (
                                  <li key={`${objective.id}-task-${idx}`} className="text-xs">
                                    {idx + 1}. {task}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                          {nextQueries.length === 0 ? (
                            <p className="text-muted-foreground text-xs">
                              No next queries yet.
                            </p>
                          ) : (
                            <ul className="space-y-1">
                              {nextQueries.map((query, idx) => (
                                <li key={`${objective.id}-query-${idx}`} className="text-xs">
                                  {idx + 1}. {query}
                                </li>
                              ))}
                            </ul>
                          )}
                        </CollapsibleContent>
                      </Collapsible>

                      <p className="text-muted-foreground text-[11px]">
                        Updated {formatTimeAgo(objective.updated_at)}
                      </p>
                    </CardContent>
                  </Card>
                );
              })
            )}
          </div>

          <div className="pointer-events-none fixed right-6 bottom-6">
            <Button
              className="pointer-events-auto h-12 w-12 rounded-full shadow-lg"
              size="icon"
              onClick={() => {
                setOpenCreateDialog(true);
                if (!endpointGoal.trim()) {
                  setEndpointGoal(suggestEndpoint(newTopic.trim()));
                }
              }}
            >
              <PlusIcon className="size-5" />
            </Button>
          </div>

          <Dialog open={openCreateDialog} onOpenChange={setOpenCreateDialog}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add Autoresearch Topic</DialogTitle>
                <DialogDescription>
                  Create a new objective to start tracking research progress.
                </DialogDescription>
              </DialogHeader>
              <Input
                value={newTopic}
                onChange={(event) => {
                  const value = event.target.value;
                  setNewTopic(value);
                  if (!endpointGoal.trim()) {
                    setEndpointGoal(suggestEndpoint(value));
                  }
                }}
                placeholder="e.g. maritime fuel decarbonization regulations"
              />
              <Input
                value={endpointGoal}
                onChange={(event) => setEndpointGoal(event.target.value)}
                placeholder="Suggested endpoint goal"
              />
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => setOpenCreateDialog(false)}
                  disabled={startAutoresearch.isPending}
                >
                  Cancel
                </Button>
                <Button
                  onClick={handleCreateObjective}
                  disabled={startAutoresearch.isPending}
                >
                  {startAutoresearch.isPending ? "Creating..." : "Create"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
