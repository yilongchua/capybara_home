import { useEffect, useMemo, useState } from "react";

import { listPipelineRuns } from "@/core/control-plane/api";
import { fetchGenerationJobs } from "@/core/generation/api";
import type { GenerationJob } from "@/core/generation/types";
import { useWorkspaceRefreshSignal } from "@/core/workspace-refresh";

import type { LongRunningTask } from "./types";

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function normalizePipelineStatus(status: string): LongRunningTask["status"] {
  if (
    status === "queued" ||
    status === "submitted" ||
    status === "pending_approval" ||
    status === "approved" ||
    status === "running" ||
    status === "completed" ||
    status === "failed" ||
    status === "cancelled" ||
    status === "rejected"
  ) {
    return status;
  }
  return "running";
}

function mapGenerationJob(job: GenerationJob): LongRunningTask {
  const kind = job.kind === "video" ? "video generation" : "image generation";
  let detail = `job: ${job.id}`;
  if (job.prompt_id) {
    detail = `${detail} | prompt: ${job.prompt_id}`;
  }
  return {
    id: `generation:${job.id}`,
    source: "generation",
    kind: job.kind,
    title: `${kind} (${job.output_name})`,
    status: job.status,
    detail,
    outputPath: job.output_virtual_path ?? undefined,
    error: job.error ?? undefined,
    updatedAt: job.updated_at,
  };
}

function mapPipelineRun(run: {
  id: string;
  status: string;
  template_name: string;
  summary: string;
  inputs: Record<string, unknown>;
  metadata: Record<string, unknown>;
  updated_at: string;
}): LongRunningTask {
  const topic = asText(
    run.metadata?.autoresearch_topic ?? run.inputs?.autoresearch_topic ?? run.metadata?.topic,
  ).trim();
  const objectiveId = asText(run.metadata?.objective_id ?? run.inputs?.objective_id).trim();
  const kind = String(run.metadata?.autoresearch_continuous ? "autoresearch run" : "pipeline run");
  const title = topic ? `${kind}: ${topic}` : `${kind}: ${run.template_name}`;
  const detailParts = [`run: ${run.id}`];
  if (objectiveId) {
    detailParts.push(`objective: ${objectiveId}`);
  }
  if (run.summary) {
    detailParts.push(run.summary);
  }
  return {
    id: `pipeline:${run.id}`,
    source: "pipeline",
    kind,
    title,
    status: normalizePipelineStatus(run.status),
    detail: detailParts.join(" | "),
    updatedAt: run.updated_at,
  };
}

const ACTIVE_POLL_MS = 3_000;
const IDLE_POLL_MS = 30_000;

const ACTIVE_STATUSES = new Set(["queued", "submitted", "pending_approval", "running"]);
const ACTIVE_PIPELINE_STATUSES = ["pending_approval", "approved", "running"] as const;

function hasActiveTasks(tasks: LongRunningTask[]): boolean {
  return tasks.some((t) => ACTIVE_STATUSES.has(t.status));
}

export function useLongRunningTasks(
  threadId: string,
  options?: { enabled?: boolean },
) {
  const [tasks, setTasks] = useState<LongRunningTask[]>([]);
  const [isDocumentVisible, setIsDocumentVisible] = useState(
    () => typeof document === "undefined" || document.visibilityState === "visible",
  );
  const enabled = options?.enabled ?? true;
  const refreshSignal = useWorkspaceRefreshSignal(
    [
      "runs",
      ...(threadId ? ([`thread:${threadId}`] as const) : []),
    ],
  );

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    const onVisibilityChange = () => {
      setIsDocumentVisible(document.visibilityState === "visible");
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

  useEffect(() => {
    if (!enabled) {
      setTasks([]);
      return;
    }
    setTasks([]);
  }, [enabled, refreshSignal, threadId]);

  useEffect(() => {
    if (!enabled || !threadId) {
      return;
    }
    let active = true;
    let timer: number | null = null;

    const schedule = async () => {
      if (!active) return;

      let nextDelay = isDocumentVisible ? IDLE_POLL_MS : 60_000;
      try {
        const [generationJobs, pipelineRuns] = await Promise.all([
          fetchGenerationJobs(threadId),
          listPipelineRuns({
            threadId,
            statuses: [...ACTIVE_PIPELINE_STATUSES],
            limit: 20,
          }),
        ]);
        if (!active) return;

        const mappedGeneration = generationJobs.map(mapGenerationJob);
        const mappedPipeline = pipelineRuns
          .filter((run) => {
            const isAutoresearch =
              Boolean(run.metadata?.autoresearch_continuous) ||
              run.template_id === "knowledge-vault-autoresearch";
            if (!isAutoresearch) return false;
            if (!threadId) return true;
            const sourceThread = asText(run.metadata?.source_thread_id).trim();
            return !sourceThread || sourceThread === threadId;
          })
          .map((run) => mapPipelineRun(run));

        const merged = [...mappedGeneration, ...mappedPipeline];
        merged.sort((a, b) => (b.updatedAt ?? "").localeCompare(a.updatedAt ?? ""));

        setTasks((prev) => {
          const nextJson = JSON.stringify(merged);
          return JSON.stringify(prev) === nextJson ? prev : merged;
        });

        if (!isDocumentVisible) {
          nextDelay = 60_000;
        } else {
          nextDelay = hasActiveTasks(merged) ? ACTIVE_POLL_MS : IDLE_POLL_MS;
        }
      } catch {
        // Swallow transient polling errors; retry at idle cadence.
      }

      if (active) {
        timer = window.setTimeout(() => {
          void schedule();
        }, nextDelay);
      }
    };

    void schedule();

    return () => {
      active = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [enabled, isDocumentVisible, refreshSignal, threadId]);

  const activeCount = useMemo(
    () => tasks.filter((item) => ACTIVE_STATUSES.has(item.status)).length,
    [tasks],
  );

  return useMemo(
    () => ({
      tasks,
      activeCount,
    }),
    [activeCount, tasks],
  );
}
