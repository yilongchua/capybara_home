"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { MountedFolderFile } from "@/core/dreamy/hooks/use-mounted-folder-files";

interface FileMentionState {
  active: boolean;
  query: string;
  startIndex: number;
  cursor: number;
}

const INACTIVE: FileMentionState = {
  active: false,
  query: "",
  startIndex: -1,
  cursor: 0,
};

function detectMention(value: string, cursor: number): FileMentionState {
  if (cursor < 1) return INACTIVE;
  for (let i = cursor - 1; i >= 0; i--) {
    const ch = value[i];
    if (ch === "@") {
      const prev = i > 0 ? value[i - 1] : undefined;
      const atWordBoundary =
        prev === undefined || prev === " " || prev === "\n" || prev === "\t";
      if (!atWordBoundary) return INACTIVE;
      const query = value.slice(i + 1, cursor);
      if (/\s/.test(query)) return INACTIVE;
      return { active: true, query, startIndex: i, cursor };
    }
    if (ch === " " || ch === "\n" || ch === "\t") {
      return INACTIVE;
    }
  }
  return INACTIVE;
}

export interface UseFileMentionParams {
  textarea: HTMLTextAreaElement | null;
  value: string;
  setValue: (next: string) => void;
}

export function useFileMention({
  textarea,
  value,
  setValue,
}: UseFileMentionParams) {
  const [state, setState] = useState<FileMentionState>(INACTIVE);
  const dismissedAtRef = useRef<number>(-1);

  const recompute = useCallback(() => {
    if (!textarea) return;
    const cursor = textarea.selectionStart ?? 0;
    const next = detectMention(textarea.value, cursor);
    if (next.active && next.startIndex === dismissedAtRef.current) {
      setState((prev) => (prev.active ? INACTIVE : prev));
      return;
    }
    if (!next.active) {
      dismissedAtRef.current = -1;
    }
    setState(next);
  }, [textarea]);

  useEffect(() => {
    recompute();
  }, [value, recompute]);

  useEffect(() => {
    if (!textarea) return;
    const handler = () => recompute();
    textarea.addEventListener("click", handler);
    textarea.addEventListener("keyup", handler);
    textarea.addEventListener("focus", handler);
    return () => {
      textarea.removeEventListener("click", handler);
      textarea.removeEventListener("keyup", handler);
      textarea.removeEventListener("focus", handler);
    };
  }, [textarea, recompute]);

  const dismiss = useCallback(() => {
    dismissedAtRef.current = state.startIndex;
    setState(INACTIVE);
  }, [state.startIndex]);

  const accept = useCallback(
    (file: MountedFolderFile) => {
      if (!state.active) return;
      const before = value.slice(0, state.startIndex);
      const after = value.slice(state.cursor);
      const insertion = `@${file.name} `;
      const next = `${before}${insertion}${after}`;
      setValue(next);
      const newCursor = before.length + insertion.length;
      requestAnimationFrame(() => {
        if (!textarea) return;
        textarea.focus();
        textarea.setSelectionRange(newCursor, newCursor);
      });
      dismissedAtRef.current = -1;
      setState(INACTIVE);
    },
    [state, value, setValue, textarea],
  );

  return {
    isActive: state.active,
    query: state.query,
    accept,
    dismiss,
  };
}
