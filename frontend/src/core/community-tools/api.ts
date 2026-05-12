import { getBackendBaseURL } from "@/core/config";

import type { CommunityTool, CommunityToolsListResponse } from "./types";

export async function loadCommunityTools(): Promise<CommunityTool[]> {
  const response = await fetch(`${getBackendBaseURL()}/api/tools/community`);
  const json = (await response.json()) as CommunityToolsListResponse;
  return json.tools;
}

export async function toggleCommunityTool(
  toolName: string,
  enabled: boolean,
): Promise<CommunityTool> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/tools/community/${toolName}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
  return response.json() as Promise<CommunityTool>;
}
