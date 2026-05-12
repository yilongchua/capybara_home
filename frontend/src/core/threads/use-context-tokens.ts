import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

import type { Model } from "@/core/models/types";

import {
  buildInitialContextTokenState,
  reduceContextTokenState,
  resolveContextWindowFromModels,
} from "./context-tokens";

export function useContextTokens({
  modelName,
  models,
}: {
  modelName?: string;
  models?: Model[];
}) {
  const initialState = useMemo(
    () => buildInitialContextTokenState({ modelName, models }),
    [modelName, models],
  );

  const [state, dispatch] = useReducer(reduceContextTokenState, initialState);
  const compactingTimerRef = useRef<number | null>(null);

  useEffect(() => {
    const resolved = resolveContextWindowFromModels(models, modelName);
    dispatch({
      type: "set_context_window",
      contextWindow: resolved.contextWindow,
      isApproximate: resolved.isApproximate,
    });
  }, [modelName, models]);

  useEffect(() => {
    return () => {
      if (compactingTimerRef.current !== null) {
        window.clearTimeout(compactingTimerRef.current);
      }
    };
  }, []);

  const onContextTokens = useCallback((tokenCount: number) => {
    dispatch({ type: "context_tokens", tokenCount });
  }, []);

  const onCompaction = useCallback(() => {
    dispatch({ type: "compaction" });
    if (compactingTimerRef.current !== null) {
      window.clearTimeout(compactingTimerRef.current);
    }
    compactingTimerRef.current = window.setTimeout(() => {
      dispatch({ type: "clear_compacting" });
      compactingTimerRef.current = null;
    }, 1500);
  }, []);

  return {
    state,
    onContextTokens,
    onCompaction,
  };
}
