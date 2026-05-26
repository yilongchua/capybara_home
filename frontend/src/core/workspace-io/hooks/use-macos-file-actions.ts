"use client";

import { useCallback } from "react";

import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/workspace-io/api";

export function isMacOS() {
  if (typeof navigator === "undefined") return false;
  return navigator.platform.startsWith("Mac") || navigator.userAgent.includes("Macintosh");
}

export function useMacOSFileActions(threadId: string) {
  const revealInFinder = useCallback(
    async (path: string) => {
      await fetch(`${getBackendBaseURL()}${api.threads.files.reveal(threadId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
    },
    [threadId],
  );

  const openInDefaultApp = useCallback(
    async (path: string) => {
      await fetch(`${getBackendBaseURL()}${api.threads.files.open(threadId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
    },
    [threadId],
  );

  const getThumbnailUrl = useCallback(
    (path: string) => {
      return `${getBackendBaseURL()}${api.threads.files.thumbnail(threadId, path)}`;
    },
    [threadId],
  );

  return { revealInFinder, openInDefaultApp, getThumbnailUrl };
}
