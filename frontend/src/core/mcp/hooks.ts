import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { loadMCPConfig, previewMCPServer, updateMCPConfig } from "./api";
import type { MCPPreviewRequest, MCPPreviewResult, MCPServerConfig } from "./types";

export function useMCPConfig() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["mcpConfig"],
    queryFn: () => loadMCPConfig(),
  });
  return { config: data, isLoading, error };
}

export function useEnableMCPServer() {
  const queryClient = useQueryClient();
  const { config } = useMCPConfig();
  return useMutation({
    mutationFn: async ({
      serverName,
      enabled,
    }: {
      serverName: string;
      enabled: boolean;
    }) => {
      if (!config) throw new Error("MCP config not found");
      if (!config.mcp_servers[serverName])
        throw new Error(`MCP server ${serverName} not found`);
      await updateMCPConfig({
        mcp_servers: {
          ...config.mcp_servers,
          [serverName]: { ...config.mcp_servers[serverName], enabled },
        },
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mcpConfig"] });
    },
  });
}

export function useAddMCPServer() {
  const queryClient = useQueryClient();
  const { config } = useMCPConfig();
  return useMutation({
    mutationFn: async ({
      serverName,
      serverConfig,
    }: {
      serverName: string;
      serverConfig: MCPServerConfig;
    }) => {
      const current = config?.mcp_servers ?? {};
      await updateMCPConfig({
        mcp_servers: { ...current, [serverName]: serverConfig },
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mcpConfig"] });
    },
  });
}

export function useRemoveMCPServer() {
  const queryClient = useQueryClient();
  const { config } = useMCPConfig();
  return useMutation({
    mutationFn: async (serverName: string) => {
      if (!config) throw new Error("MCP config not found");
      const updated = { ...config.mcp_servers };
      delete updated[serverName];
      await updateMCPConfig({ mcp_servers: updated });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mcpConfig"] });
    },
  });
}

export function useUpdateToolExclusions() {
  const queryClient = useQueryClient();
  const { config } = useMCPConfig();
  return useMutation({
    mutationFn: async ({
      serverName,
      excludedTools,
    }: {
      serverName: string;
      excludedTools: string[];
    }) => {
      if (!config) throw new Error("MCP config not found");
      if (!config.mcp_servers[serverName])
        throw new Error(`MCP server ${serverName} not found`);
      await updateMCPConfig({
        mcp_servers: {
          ...config.mcp_servers,
          [serverName]: {
            ...config.mcp_servers[serverName],
            excluded_tools: excludedTools,
          },
        },
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["mcpConfig"] });
    },
  });
}

export function usePreviewMCPServer() {
  return useMutation<MCPPreviewResult, Error, MCPPreviewRequest>({
    mutationFn: (request) => previewMCPServer(request),
  });
}
