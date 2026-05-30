"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarClockIcon, ExternalLinkIcon, FileTextIcon, FolderIcon, Loader2Icon, PlayIcon, PlusIcon, SquareIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownContent } from "@/components/workspace/messages/markdown-content";
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
  useRunAutoresearchObjective,
  useStartAutoresearchObjective,
  useStopAutoresearchObjective,
  useUpdateRuntimeSchedulerJob,
  useUpdateRuntimeSchedulerJobTime,
} from "@/core/control-plane";
import { useI18n } from "@/core/i18n/hooks";
import { formatTimeAgo } from "@/core/utils/datetime";

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
      placeholder={placeholder || "Enter endpoint goal..."}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === "Enter") e.currentTarget.blur();
      }}
    />
  );
}

export default function PipelinesPage() {
  const { t } = useI18n();
  const { integrationStatus } = useIntegrationStatus();
  const [anyRunning, setAnyRunning] = useState(false);
  const { objectives, isLoading } = useAutoresearchObjectives({
    refetchInterval: anyRunning ? 3_000 : 20_000,
  });
  useEffect(() => {
    setAnyRunning(objectives.some((obj) => Boolean((obj.running_run_id ?? "").trim())));
  }, [objectives]);
  const startAutoresearch = useStartAutoresearchObjective();
  const runAutoresearchObjective = useRunAutoresearchObjective();
  const stopAutoresearchObjective = useStopAutoresearchObjective();
  const deleteAutoresearchObjective = useDeleteAutoresearchObjective();
  const updateSchedulerJobTime = useUpdateRuntimeSchedulerJobTime();
  const updateSchedulerJob = useUpdateRuntimeSchedulerJob();
  const [openCreateDialog, setOpenCreateDialog] = useState(false);
  const [newTopic, setNewTopic] = useState("");
  const [endpointGoal, setEndpointGoal] = useState("");
  const [ledgerObjectiveId, setLedgerObjectiveId] = useState<string | null>(null);

  const previewObjective = useMemo(
    () => objectives.find((obj) => obj.objective_id === ledgerObjectiveId) ?? null,
    [objectives, ledgerObjectiveId],
  );
  const ledgerPreviewUrl = previewObjective
    ? `${getBackendBaseURL()}/api/vault/objectives/${encodeURIComponent(previewObjective.objective_id)}/ledger.md`
    : "";

  const ledgerPreviewQuery = useQuery({
    queryKey: ["autoresearch-ledger-preview", ledgerObjectiveId],
    queryFn: async () => {
      const response = await fetch(ledgerPreviewUrl);
      if (!response.ok) {
        throw new Error(`Failed to load ledger: ${response.statusText}`);
      }
      return response.text();
    },
    enabled: Boolean(ledgerObjectiveId) && Boolean(previewObjective?.ledger_markdown_path),
  });

  const toText = (value: unknown) => (typeof value === "string" ? value : "");
  const firstNonEmpty = (...values: string[]) =>
    values.map((item) => item.trim()).find((item) => item.length > 0) ?? "";

  useEffect(() => {
    document.title = `${t.pages.pipelines} - ${t.pages.appName}`;
  }, [t.pages.appName, t.pages.pipelines]);

  const suggestEndpoint = (topic: string) =>
    `Deliver a complete, evidence-backed research brief for ${topic || "this topic"} with actionable next steps.`;

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

  // Progress is now expressed as cluster coverage breadth (covered / 12).
  // The novelty rate sits beside it as a separate signal.
  const objectiveProgress = useMemo<Record<string, number>>(() => {
    const totalClusters = 12;
    const entries = objectives.map((objective) => {
      const coverage = objective.cluster_coverage ?? {};
      const covered = Object.keys(coverage).length;
      const percent = (covered / totalClusters) * 100;
      return [objective.objective_id, percent] as const;
    });
    return Object.fromEntries(entries);
  }, [objectives]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="flex size-full flex-col overflow-y-auto">
          <div className="border-b px-6 py-4">
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              <CalendarClockIcon className="size-5" />
              {t.pages.pipelines}
            </h1>
            <p className="text-muted-foreground mt-0.5 text-sm">
              Manage autoresearch objectives, schedules, and progress here.
            </p>
          </div>

          <div className="grid gap-4 p-6 md:grid-cols-2 xl:grid-cols-3">
            {isLoading ? (
              <Card>
                <CardContent className="pt-6 text-sm">{t.common.loading}</CardContent>
              </Card>
            ) : (
              objectives.map((objective) => {
                const progressPercent = objectiveProgress[objective.objective_id] ?? 0;
                const noveltyPercent = ((objective.last_novelty_rate ?? 1) * 100).toFixed(0);
                const job = scheduleJobByObjectiveId.get(objective.objective_id);
                const hasLedger = Boolean((objective.ledger_markdown_path ?? "").trim());
                const isRunning = Boolean((objective.running_run_id ?? "").trim());
                const currentActivity = (objective.current_activity ?? "").trim();

                return (
                  <Card key={objective.id} className="h-full">
                    <CardHeader className="space-y-1">
                      <div className="flex items-start justify-between gap-2">
                        <CardTitle className="text-base">{objective.topic || objective.objective_id}</CardTitle>
                        {isRunning ? (
                          <span
                            className="text-primary inline-flex shrink-0 items-center gap-1 text-[11px]"
                            title={currentActivity || "Running"}
                          >
                            <Loader2Icon className="size-3 animate-spin" />
                            <span className="max-w-[180px] truncate">
                              {currentActivity || "Running"}
                            </span>
                          </span>
                        ) : (
                          <span className="text-muted-foreground shrink-0 text-[11px]">
                            Updated {formatTimeAgo(objective.updated_at)}
                          </span>
                        )}
                      </div>
                      <div className="space-y-1">
                        <div className="flex items-center justify-end text-xs">
                          <span className="text-muted-foreground">{progressPercent.toFixed(1)}%</span>
                        </div>
                        <Progress value={Math.max(0, Math.min(100, progressPercent))} className="h-1.5" />
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3 text-sm">
                      {job ? (
                        <div className="space-y-3 rounded-md border p-3">
                          <p className="flex items-center gap-1 text-xs font-medium">
                            <CalendarClockIcon className="size-3.5" />
                            Scheduled Pipeline Controls
                          </p>
                          <div className="flex items-center gap-2 text-xs">
                            <span className="text-muted-foreground shrink-0">Schedule:</span>
                            <Select
                              value={job.daily_time ?? "02:00"}
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
                              initialValue={firstNonEmpty(
                                toText(job.inputs?.endpoint_goal),
                                objective.endpoint_goal ?? "",
                              )}
                              placeholder={firstNonEmpty(
                                objective.endpoint_goal ?? "",
                                toText(job.inputs?.endpoint_goal),
                                "Enter endpoint goal...",
                              )}
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
                        </div>
                      ) : null}

                      <div className="flex gap-2">
                        {isRunning ? (
                          <Button
                            className="flex-1"
                            size="sm"
                            variant="secondary"
                            onClick={() =>
                              stopAutoresearchObjective.mutate(objective.objective_id, {
                                onSuccess: () => toast.success("Stop requested."),
                                onError: (error) => toast.error(error.message),
                              })
                            }
                            disabled={stopAutoresearchObjective.isPending}
                          >
                            <SquareIcon className="size-4" />
                            Stop
                          </Button>
                        ) : (
                          <Button
                            className="flex-1"
                            size="sm"
                            onClick={() =>
                              runAutoresearchObjective.mutate(objective.objective_id, {
                                onSuccess: () => toast.success("Run started."),
                                onError: (error) => toast.error(error.message),
                              })
                            }
                            disabled={runAutoresearchObjective.isPending}
                          >
                            <PlayIcon className="size-4" />
                            Run
                          </Button>
                        )}
                        <Button
                          variant="destructive"
                          size="sm"
                          className="flex-1"
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
                          Delete
                        </Button>
                      </div>

                      <div className="rounded-md border p-3 space-y-1">
                        <p className="text-xs font-medium">Question Ledger</p>
                        {hasLedger ? (
                          <button
                            type="button"
                            className="text-primary inline-flex items-center gap-1 text-xs underline"
                            onClick={() => setLedgerObjectiveId(objective.objective_id)}
                          >
                            <FileTextIcon className="size-3" />
                            Open ledger.md
                          </button>
                        ) : (
                          <p className="text-muted-foreground text-xs">
                            No ledger yet — run an iteration to populate.
                          </p>
                        )}
                        <p className="text-muted-foreground text-[11px]">
                          Iteration #{objective.loop_iteration} · novelty {noveltyPercent}%
                          {objective.last_stop_reason ? ` · ${objective.last_stop_reason}` : ""}
                        </p>
                      </div>
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

          <Sheet
            open={ledgerObjectiveId !== null}
            onOpenChange={(open) => {
              if (!open) setLedgerObjectiveId(null);
            }}
          >
            <SheetContent side="right" className="w-full sm:max-w-xl">
              <SheetHeader className="border-b">
                <SheetTitle className="flex items-center gap-2 text-base">
                  <FileTextIcon className="size-4" />
                  {previewObjective?.topic ?? "Question Ledger"}
                </SheetTitle>
                <SheetDescription className="truncate text-xs">
                  ledger.md preview · iteration #{previewObjective?.loop_iteration ?? 0}
                </SheetDescription>
              </SheetHeader>

              <div className="px-4 pb-2">
                <p className="text-xs font-medium mb-2 inline-flex items-center gap-1">
                  <FolderIcon className="size-3.5" />
                  Directories
                </p>
                <div className="flex flex-col gap-1 text-xs">
                  <Link
                    href="/workspace/vault"
                    className="text-primary inline-flex items-center gap-1 underline"
                  >
                    <ExternalLinkIcon className="size-3" />
                    Open Knowledge Vault
                  </Link>
                  {previewObjective?.ledger_markdown_path ? (
                    <span
                      className="text-muted-foreground truncate"
                      title={previewObjective.ledger_markdown_path}
                    >
                      {previewObjective.ledger_markdown_path}
                    </span>
                  ) : null}
                  {ledgerPreviewUrl ? (
                    <a
                      href={ledgerPreviewUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-primary inline-flex items-center gap-1 underline"
                    >
                      <ExternalLinkIcon className="size-3" />
                      Open raw ledger.md
                    </a>
                  ) : null}
                </div>
              </div>

              <ScrollArea className="flex-1 border-t">
                <div className="p-4 text-sm">
                  {ledgerPreviewQuery.isLoading ? (
                    <div className="text-muted-foreground inline-flex items-center gap-2 text-xs">
                      <Loader2Icon className="size-3 animate-spin" />
                      Loading ledger...
                    </div>
                  ) : ledgerPreviewQuery.isError ? (
                    <p className="text-destructive text-xs">
                      {ledgerPreviewQuery.error?.message ?? "Failed to load ledger."}
                    </p>
                  ) : ledgerPreviewQuery.data ? (
                    <MarkdownContent
                      content={ledgerPreviewQuery.data}
                      isLoading={false}
                      rehypePlugins={[]}
                    />
                  ) : (
                    <p className="text-muted-foreground text-xs">No ledger content available.</p>
                  )}
                </div>
              </ScrollArea>
            </SheetContent>
          </Sheet>

          <Dialog open={openCreateDialog} onOpenChange={setOpenCreateDialog}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add Autoresearch Topic</DialogTitle>
                <DialogDescription>Create a new objective to start tracking research progress.</DialogDescription>
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
