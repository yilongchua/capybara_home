"use client";

import { CalendarClockIcon, ChevronDownIcon, ListChecksIcon, PlayIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
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
  useStartAutoresearchObjective,
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
  const { objectives, isLoading } = useAutoresearchObjectives({ refetchInterval: 20_000 });
  const startAutoresearch = useStartAutoresearchObjective();
  const runSchedulerJob = useRunSchedulerJob();
  const deleteAutoresearchObjective = useDeleteAutoresearchObjective();
  const updateSchedulerJobTime = useUpdateRuntimeSchedulerJobTime();
  const updateSchedulerJob = useUpdateRuntimeSchedulerJob();
  const [openCreateDialog, setOpenCreateDialog] = useState(false);
  const [newTopic, setNewTopic] = useState("");
  const [endpointGoal, setEndpointGoal] = useState("");

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
                const coverage = objective.cluster_coverage ?? {};
                const coveredClusters = Object.entries(coverage)
                  .map(([cid, depth]) => `C${cid} L${depth}`)
                  .sort();
                const ledgerLink = `${getBackendBaseURL()}/api/vault/objectives/${encodeURIComponent(
                  objective.objective_id,
                )}/ledger.md`;
                const progressPercent = objectiveProgress[objective.objective_id] ?? 0;
                const noveltyPercent = ((objective.last_novelty_rate ?? 1) * 100).toFixed(0);
                const lastReflection = (objective.last_reflection ?? "").trim();
                const job = scheduleJobByObjectiveId.get(objective.objective_id);

                return (
                  <Card key={objective.id} className="h-full">
                    <CardHeader className="space-y-1">
                      <div className="flex items-start justify-between gap-2">
                        <CardTitle className="text-base">{objective.topic || objective.objective_id}</CardTitle>
                        <Badge variant={objective.status === "active" ? "secondary" : "outline"}>
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
                          <Button
                            className="w-full"
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
                      ) : null}

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

                      <div className="rounded-md border p-3 space-y-1">
                        <p className="text-xs font-medium">Question Ledger</p>
                        <a
                          className="text-primary inline-flex items-center gap-1 text-xs underline"
                          href={ledgerLink}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open ledger.md
                        </a>
                        <p className="text-muted-foreground text-[11px]">
                          Iteration #{objective.loop_iteration} · novelty {noveltyPercent}%
                          {objective.last_stop_reason ? ` · ${objective.last_stop_reason}` : ""}
                        </p>
                      </div>

                      <Collapsible>
                        <CollapsibleTrigger className="flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-xs font-medium">
                          <span className="inline-flex items-center gap-1">
                            <ListChecksIcon className="size-3.5" />
                            Cluster Coverage / Reflection
                          </span>
                          <ChevronDownIcon className="size-4" />
                        </CollapsibleTrigger>
                        <CollapsibleContent className="mt-2 rounded-md border p-3 space-y-2">
                          <div>
                            <p className="mb-1 text-[11px] font-medium">Cluster coverage</p>
                            {coveredClusters.length === 0 ? (
                              <p className="text-muted-foreground text-xs">No clusters covered yet.</p>
                            ) : (
                              <p className="text-xs">{coveredClusters.join(" · ")}</p>
                            )}
                          </div>
                          {lastReflection ? (
                            <div>
                              <p className="mb-1 text-[11px] font-medium">Latest reflection</p>
                              <p className="text-xs">{lastReflection}</p>
                            </div>
                          ) : null}
                        </CollapsibleContent>
                      </Collapsible>

                      <p className="text-muted-foreground text-[11px]">Updated {formatTimeAgo(objective.updated_at)}</p>
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
