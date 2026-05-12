export interface CommunityTool {
  name: string;
  display_name: string;
  description: string;
  enabled: boolean;
  source: "builtin" | "config";
}

export interface CommunityToolsListResponse {
  tools: CommunityTool[];
}
