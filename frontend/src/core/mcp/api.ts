import { getBackendBaseURL } from "@/core/config";

import type { MCPConfig, MCPPreviewRequest, MCPPreviewResult } from "./types";

export async function loadMCPConfig() {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`);
  return response.json() as Promise<MCPConfig>;
}

export async function updateMCPConfig(config: MCPConfig) {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  return response.json();
}

export async function previewMCPServer(
  request: MCPPreviewRequest,
): Promise<MCPPreviewResult> {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return response.json() as Promise<MCPPreviewResult>;
}
