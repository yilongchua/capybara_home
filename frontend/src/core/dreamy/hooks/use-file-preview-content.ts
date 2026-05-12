import { useQuery } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";
import { FILE_PREVIEW_STALE_TIME } from "@/core/dreamy/constants";

export function useFilePreviewContent({
  artifactUrl,
  enabled,
  version,
}: {
  artifactUrl: string;
  enabled: boolean;
  version?: number;
}) {
  return useQuery({
    queryKey: ["file-preview-content", artifactUrl, version ?? 0],
    queryFn: async () => {
      const url = artifactUrl.startsWith("http")
        ? artifactUrl
        : `${getBackendBaseURL()}${artifactUrl}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Failed to fetch file: ${res.status}`);
      return res.text();
    },
    enabled,
    staleTime: version !== undefined ? 0 : FILE_PREVIEW_STALE_TIME,
  });
}
