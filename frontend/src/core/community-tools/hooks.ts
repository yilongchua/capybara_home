import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { loadCommunityTools, toggleCommunityTool } from "./api";
import type { CommunityTool } from "./types";

export function useCommunityTools() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["communityTools"],
    queryFn: loadCommunityTools,
  });
  return { tools: data ?? [], isLoading, error };
}

export function useToggleCommunityTool() {
  const queryClient = useQueryClient();
  return useMutation<CommunityTool, Error, { name: string; enabled: boolean }>({
    mutationFn: ({ name, enabled }) => toggleCommunityTool(name, enabled),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["communityTools"] });
    },
  });
}
