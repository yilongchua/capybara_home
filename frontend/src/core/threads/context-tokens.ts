import type { Model } from "@/core/models/types";
import type { ExecutionTraceState } from "@/core/traces/types";

export const DEFAULT_CONTEXT_WINDOW_FALLBACK = 128_000;

export interface ContextTokenState {
  currentTokens: number;
  maxTokens: number;
  contextWindow: number;
  isContextWindowApproximate: boolean;
  percentage: number;
  isCompacting: boolean;
}

export type ContextTokenAction =
  | { type: "context_tokens"; tokenCount: number }
  | { type: "compaction" }
  | {
      type: "set_context_window";
      contextWindow: number;
      isApproximate: boolean;
    }
  | { type: "clear_compacting" };

function clamp01(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(1, value));
}

export function resolveContextWindowFromModels(
  models: Model[] | undefined,
  modelName: string | undefined,
): { contextWindow: number; isApproximate: boolean } {
  if (models && modelName) {
    const match = models.find((model) => model.name === modelName);
    const value = match?.context_window;
    if (typeof value === "number" && Number.isFinite(value) && value > 0) {
      return { contextWindow: value, isApproximate: false };
    }
  }
  return {
    contextWindow: DEFAULT_CONTEXT_WINDOW_FALLBACK,
    isApproximate: true,
  };
}

export function buildInitialContextTokenState(options: {
  models?: Model[];
  modelName?: string;
}): ContextTokenState {
  const resolved = resolveContextWindowFromModels(options.models, options.modelName);
  return {
    currentTokens: 0,
    maxTokens: 0,
    contextWindow: resolved.contextWindow,
    isContextWindowApproximate: resolved.isApproximate,
    percentage: 0,
    isCompacting: false,
  };
}

export function reduceContextTokenState(
  state: ContextTokenState,
  action: ContextTokenAction,
): ContextTokenState {
  if (action.type === "context_tokens") {
    const nextCurrentTokens = Math.max(0, Math.floor(action.tokenCount));
    const nextMaxTokens = Math.max(state.maxTokens, nextCurrentTokens);
    const nextWindow = state.contextWindow > 0 ? state.contextWindow : DEFAULT_CONTEXT_WINDOW_FALLBACK;
    const nextPercentage = clamp01(nextCurrentTokens / nextWindow);
    if (
      state.currentTokens === nextCurrentTokens &&
      state.maxTokens === nextMaxTokens &&
      state.percentage === nextPercentage
    ) {
      return state;
    }
    return {
      ...state,
      currentTokens: nextCurrentTokens,
      maxTokens: nextMaxTokens,
      percentage: nextPercentage,
    };
  }

  if (action.type === "compaction") {
    if (state.maxTokens === 0 && state.isCompacting) {
      return state;
    }
    return {
      ...state,
      maxTokens: 0,
      isCompacting: true,
    };
  }

  if (action.type === "set_context_window") {
    const nextWindow = action.contextWindow > 0 ? action.contextWindow : DEFAULT_CONTEXT_WINDOW_FALLBACK;
    const nextPercentage = clamp01(state.currentTokens / nextWindow);
    if (
      state.contextWindow === nextWindow &&
      state.isContextWindowApproximate === action.isApproximate &&
      state.percentage === nextPercentage
    ) {
      return state;
    }
    return {
      ...state,
      contextWindow: nextWindow,
      isContextWindowApproximate: action.isApproximate,
      percentage: nextPercentage,
    };
  }

  if (!state.isCompacting) {
    return state;
  }
  return {
    ...state,
    isCompacting: false,
  };
}

export function formatTokenCompact(value: number): string {
  const tokens = Math.max(0, Math.floor(value));
  if (tokens >= 1_000_000) {
    return `~${Math.round(tokens / 1_000_000)}M`;
  }
  if (tokens >= 1_000) {
    return `~${Math.round(tokens / 1_000)}K`;
  }
  return tokens.toLocaleString();
}

export function extractLatestContextTokensFromTrace(
  trace: ExecutionTraceState | undefined,
): { tokenCount: number; messageCount?: number } | null {
  const runs = trace?.runs;
  if (!runs || typeof runs !== "object") {
    return null;
  }

  let best: { tokenCount: number; messageCount?: number } | null = null;
  let bestTimestamp = Number.NEGATIVE_INFINITY;
  let bestSeq = Number.NEGATIVE_INFINITY;

  for (const run of Object.values(runs)) {
    if (!run || !Array.isArray(run.events)) {
      continue;
    }
    for (const event of run.events) {
      if (event?.event_type !== "context_tokens") {
        continue;
      }
      const payload = event.payload;
      const tokenCount = payload?.token_count;
      if (typeof tokenCount !== "number" || !Number.isFinite(tokenCount)) {
        continue;
      }
      const timestamp = typeof event.timestamp === "number" ? event.timestamp : Number.NEGATIVE_INFINITY;
      const seq = typeof event.seq === "number" ? event.seq : Number.NEGATIVE_INFINITY;
      if (timestamp < bestTimestamp) {
        continue;
      }
      if (timestamp === bestTimestamp && seq <= bestSeq) {
        continue;
      }
      bestTimestamp = timestamp;
      bestSeq = seq;
      const messageCount = payload?.message_count;
      best = {
        tokenCount,
        messageCount:
          typeof messageCount === "number" && Number.isFinite(messageCount)
            ? messageCount
            : undefined,
      };
    }
  }

  return best;
}
