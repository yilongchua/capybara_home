"use client";

import { useState } from "react";

import { getBackendBaseURL } from "@/core/config";

interface PickFolderResult {
  path: string | null;
  cancelled: boolean;
}

async function pickFolderFromBackend(): Promise<PickFolderResult> {
  const res = await fetch(`${getBackendBaseURL()}/api/dreamy/pick-folder`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Failed to open folder picker");
  }
  return (await res.json()) as PickFolderResult;
}

export function useFolderPicker() {
  const [isPicking, setIsPicking] = useState(false);

  async function pickFolder(): Promise<string | null> {
    setIsPicking(true);
    try {
      const result = await pickFolderFromBackend();
      return result.cancelled ? null : (result.path ?? null);
    } finally {
      setIsPicking(false);
    }
  }

  return { pickFolder, isPicking };
}
