"use client";

import { formatTokenCompact } from "@/core/threads/context-tokens";
import { cn } from "@/lib/utils";

type TokenRingSize = "sm" | "md";

function colorClassForRatio(ratio: number): string {
  if (ratio >= 0.9) return "text-red-500";
  if (ratio >= 0.7) return "text-amber-500";
  return "text-emerald-500";
}

function displayPercent(ratio: number): string {
  return `${Math.round(Math.max(0, Math.min(1, ratio)) * 100)}%`;
}

export function TokenRing({
  currentTokens,
  maxTokens,
  contextWindow,
  percentage,
  isContextWindowApproximate,
  isCompacting,
  modelName,
  size = "sm",
  showLabel = true,
  labelStyle = "remaining",
}: {
  currentTokens: number;
  maxTokens: number;
  contextWindow: number;
  percentage: number;
  isContextWindowApproximate: boolean;
  isCompacting: boolean;
  modelName?: string;
  size?: TokenRingSize;
  showLabel?: boolean;
  labelStyle?: "usage" | "remaining";
}) {
  const ratio = Math.max(0, Math.min(1, percentage));
  const colorClass = colorClassForRatio(ratio);
  const diameter = size === "sm" ? 13 : 17;
  const strokeWidth = size === "sm" ? 1.5 : 2;
  const radius = (diameter - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - ratio);

  const labelText =
    labelStyle === "usage"
      ? `${formatTokenCompact(currentTokens)}/${formatTokenCompact(contextWindow)}`
      : `${formatTokenCompact(currentTokens)} (${displayPercent(ratio)})`;
  const contextLimitText = `${contextWindow.toLocaleString()} tokens${isContextWindowApproximate ? " (approximate)" : ""}`;
  const tooltipText = [
    "Context Window Usage",
    `Current: ${currentTokens.toLocaleString()} tokens`,
    `Peak: ${maxTokens.toLocaleString()} tokens (session)`,
    `Limit: ${contextLimitText}`,
    modelName ? `Model: ${modelName}` : null,
    `Usage: ${displayPercent(ratio)}`,
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5",
        isCompacting && "animate-pulse",
      )}
      aria-label={`Context window ${displayPercent(ratio)} full`}
      title={tooltipText}
    >
      <svg
        width={diameter}
        height={diameter}
        viewBox={`0 0 ${diameter} ${diameter}`}
        className="shrink-0"
        aria-hidden="true"
      >
        <circle
          cx={diameter / 2}
          cy={diameter / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-muted-foreground/25"
        />
        <circle
          cx={diameter / 2}
          cy={diameter / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          transform={`rotate(-90 ${diameter / 2} ${diameter / 2})`}
          className={cn("transition-all duration-300 ease-out", colorClass)}
        />
      </svg>
      {showLabel ? (
        <div className={cn("text-[11px] font-medium tabular-nums", colorClass)}>{labelText}</div>
      ) : null}
    </div>
  );
}
