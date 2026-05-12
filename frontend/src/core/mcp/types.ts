export interface MCPServerConfig extends Record<string, unknown> {
  enabled: boolean;
  description: string;
  type?: "stdio" | "sse" | "http";
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
  excluded_tools?: string[];
}

export interface MCPConfig {
  mcp_servers: Record<string, MCPServerConfig>;
}

export interface MCPToolPreview {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface MCPPreviewResult {
  ok: boolean;
  tools: MCPToolPreview[];
  error: string | null;
}

export type MCPPreviewRequest = Omit<MCPServerConfig, "enabled" | "excluded_tools">;
