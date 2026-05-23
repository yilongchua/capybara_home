import {
  BrainIcon,
  ChevronUp,
  CpuIcon,
  FileWarningIcon,
  WorkflowIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ExecutionTraceEvent } from "@/core/traces";
import { cn } from "@/lib/utils";


const VISIBLE_EVENT_TYPES = new Set([
  "plan_created",
  "skipped_trivial",
  "tool_call_start",
  "tool_call_end",
  "task_started",
  "task_running",
  "task_completed",
  "task_failed",
  "task_timed_out",
  "llm_verdict",
  "rule_fail",
  "background_followup_started",
  "model_response",
]);

function formatTimestamp(timestamp: number) {
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString();
}

function statusClassName(status: string) {
  if (status === "failed") {
    return "bg-red-100 text-red-700 border-red-200";
  }
  if (status === "warning") {
    return "bg-amber-100 text-amber-700 border-amber-200";
  }
  if (status === "completed") {
    return "bg-emerald-100 text-emerald-700 border-emerald-200";
  }
  if (status === "running") {
    return "bg-blue-100 text-blue-700 border-blue-200";
  }
  return "bg-secondary text-secondary-foreground";
}

function aggregateTokenUsage(events: ExecutionTraceEvent[]) {
  let input = 0;
  let output = 0;
  let total = 0;
  for (const event of events) {
    input += event.token_usage?.input_tokens ?? 0;
    output += event.token_usage?.output_tokens ?? 0;
    total += event.token_usage?.total_tokens ?? 0;
  }
  if (input === 0 && output === 0 && total === 0) {
    return null;
  }
  return { input, output, total };
}

function prettifyPayload(payload: Record<string, unknown> | undefined) {
  if (!payload || Object.keys(payload).length === 0) {
    return null;
  }
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return "[payload unavailable]";
  }
}

function asString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  return null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter((item) => item.length > 0);
}

function isGenericFallback(text: string): boolean {
  return text.startsWith("No raw reasoning was exposed by the provider.");
}

function summarizeEvent(event: ExecutionTraceEvent): string | null {
  const payload = event.payload ?? {};
  const toolName = asString(payload.tool) ?? asString(payload.subagent_type);
  const toolInput =
    asString(payload.tool_input) ??
    asString(payload.query) ??
    asString(payload.command) ??
    asString(payload.prompt);
  const toolOutput = asString(payload.tool_output_preview);
  const resultPreview = asString(payload.result_preview);

  if (event.event_type === "model_response") {
    const toolNames = asStringArray(payload.tool_names);
    const toolCallsCount = asNumber(payload.tool_calls_count);
    if (toolNames.length > 0) {
      return `Identified tools: ${toolNames.join(", ")}.`;
    }
    if (toolCallsCount !== null && toolCallsCount > 0) {
      return `Identified ${toolCallsCount} tool call${toolCallsCount === 1 ? "" : "s"} for this step.`;
    }
    return "Prepared the final response.";
  }

  if (event.event_type === "plan_created") {
    return "Planning response.";
  }

  if (event.event_type === "skipped_trivial") {
    return "Skipping the heavy planning path for a simple request.";
  }

  if (event.event_type === "tool_call_start") {
    if (!toolName) {
      return "Started a tool call.";
    }
    if (toolName === "web_search" || toolName === "query_knowledge_vault") {
      return "Checking sources.";
    }
    if (toolInput) {
      return `Using tool: ${toolName}\nSent ${toolName} query: ${toolInput}`;
    }
    return `Using tool: ${toolName}`;
  }

  if (event.event_type === "background_followup_started") {
    return "Deepening in background.";
  }

  if (event.event_type === "rule_fail") {
    return "Evaluator requested a follow-up correction.";
  }

  if (event.event_type === "llm_verdict") {
    const verdict = asString(payload.verdict);
    return verdict ? `Evaluator verdict: ${verdict}.` : "Evaluator completed.";
  }

  if (event.event_type === "tool_call_end") {
    if (!toolName) {
      return "Received tool response.";
    }
    if (toolOutput) {
      return `Received response from ${toolName}: ${toolOutput}`;
    }
    return `Received response from ${toolName}.`;
  }

  if (event.event_type === "title_generation_start") {
    const userMessagePreview = asString(payload.user_message_preview);
    if (userMessagePreview) {
      return `Generating title from initial request: ${userMessagePreview}`;
    }
    return "Generating conversation title.";
  }

  if (event.event_type === "title_generation_completed") {
    const generatedTitle = asString(payload.generated_title) ?? asString(payload.title);
    if (generatedTitle) {
      return `Generated conversation title: ${generatedTitle}`;
    }
    return "Conversation title generated.";
  }

  if (event.event_type === "title_generation_failed") {
    return `Title generation failed${asString(payload.error) ? `: ${asString(payload.error)}` : "."}`;
  }

  if (event.event_type === "task_started") {
    const description = asString(payload.description);
    if (description && toolName) {
      return `Started subagent (${toolName}) for: ${description}`;
    }
    if (description) {
      return `Started subagent task: ${description}`;
    }
    return "Started subagent task.";
  }

  if (event.event_type === "task_running") {
    const messageIndex = asNumber(payload.message_index);
    const totalMessages = asNumber(payload.total_messages);
    if (messageIndex !== null && totalMessages !== null) {
      return `Subagent progress: step ${messageIndex} of ${totalMessages}.`;
    }
    return "Subagent is processing.";
  }

  if (event.event_type === "task_completed") {
    if (resultPreview) {
      return `Subagent completed. Result preview: ${resultPreview}`;
    }
    return "Subagent completed.";
  }

  if (event.event_type === "task_failed") {
    return `Subagent failed${asString(payload.error) ? `: ${asString(payload.error)}` : "."}`;
  }

  if (event.event_type === "task_timed_out") {
    return `Subagent timed out${asString(payload.error) ? `: ${asString(payload.error)}` : "."}`;
  }

  const decision = asString(payload.decision);
  if (decision && toolName) {
    return `${decision.toUpperCase()}: ${toolName}`;
  }
  if (decision) {
    return `Decision: ${decision}`;
  }

  const signal = asString(payload.signal);
  if (signal) {
    return `Signal: ${signal}`;
  }

  if (toolName) {
    return `Tool event: ${toolName}`;
  }
  return null;
}

function buildDisplayThinking(event: ExecutionTraceEvent): {
  label: string;
  content: string;
} | null {
  const thinking = event.thinking;
  if (thinking?.source === "raw" && thinking.content.trim()) {
    return { label: "Raw Thinking", content: thinking.content };
  }

  const summary = summarizeEvent(event);
  if (summary) {
    return { label: "Summary Fallback", content: summary };
  }

  if (thinking?.content?.trim()) {
    if (isGenericFallback(thinking.content)) {
      return {
        label: "Summary Fallback",
        content: `Raw thinking unavailable for this step. ${thinking.content}`,
      };
    }
    return { label: "Summary Fallback", content: thinking.content };
  }

  return null;
}

export function ExecutionTracePanel({
  title,
  events,
  defaultCollapsed = true,
  className,
}: {
  title: string;
  events: ExecutionTraceEvent[];
  defaultCollapsed?: boolean;
  className?: string;
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const sortedEvents = useMemo(
    () =>
      events
        .filter((event) => VISIBLE_EVENT_TYPES.has(event.event_type))
        .sort((a, b) => {
        if ((a.seq ?? 0) !== (b.seq ?? 0)) {
          return (a.seq ?? 0) - (b.seq ?? 0);
        }
        return a.timestamp - b.timestamp;
      })
        .slice(-12),
    [events],
  );
  const usage = useMemo(() => aggregateTokenUsage(sortedEvents), [sortedEvents]);

  if (sortedEvents.length === 0) {
    return null;
  }

  return (
    <div className={cn("w-full rounded-lg border", className)}>
      <Button
        className="w-full justify-between rounded-b-none px-3 py-2 text-left font-normal"
        variant="ghost"
        onClick={() => setCollapsed((prev) => !prev)}
      >
        <span className="flex items-center gap-2">
          <WorkflowIcon className="size-4" />
          {title}
          <Badge variant="secondary">{sortedEvents.length}</Badge>
        </span>
        <span className="flex items-center gap-2 text-xs">
          {usage && (
            <span className="text-muted-foreground flex items-center gap-1">
              <CpuIcon className="size-3" />
              {usage.total > 0 ? usage.total : usage.input + usage.output} tokens
            </span>
          )}
          <ChevronUp
            className={cn("size-4 transition-transform", collapsed ? "rotate-180" : "")}
          />
        </span>
      </Button>
      {!collapsed && (
        <div className="space-y-3 border-t p-3">
          {sortedEvents.map((event) => {
            const payloadText = prettifyPayload(event.payload);
            const displayThinking = buildDisplayThinking(event);
            return (
              <div
                key={event.id ?? `${event.run_id}:${event.seq ?? event.timestamp}`}
                className="space-y-2 rounded-md border p-2"
              >
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge variant="secondary">{event.stage}</Badge>
                  <Badge variant="secondary">{event.event_type}</Badge>
                  <Badge className={cn("border", statusClassName(event.status))}>
                    {event.status}
                  </Badge>
                  <span className="text-muted-foreground ml-auto">
                    {formatTimestamp(event.timestamp)}
                  </span>
                </div>
                {displayThinking && (
                  <div className="bg-muted/50 space-y-1 rounded-md border p-2">
                    <div className="text-muted-foreground flex items-center gap-1 text-xs">
                      <BrainIcon className="size-3" />
                      {displayThinking.label}
                    </div>
                    <div className="text-sm whitespace-pre-wrap">
                      {displayThinking.content}
                    </div>
                  </div>
                )}
                {payloadText && (
                  <details className="text-xs">
                    <summary className="text-muted-foreground cursor-pointer">
                      Payload
                    </summary>
                    <pre className="bg-muted mt-1 overflow-x-auto rounded p-2">
                      {payloadText}
                    </pre>
                  </details>
                )}
                {event.payload_truncated && (
                  <div className="text-amber-700 flex items-center gap-1 text-xs">
                    <FileWarningIcon className="size-3" />
                    Payload truncated ({event.payload_original_chars ?? "?"} chars).
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
