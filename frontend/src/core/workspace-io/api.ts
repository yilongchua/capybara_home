export const api = {
  threads: {
    steer: (threadId: string) => `/api/threads/${threadId}/steer`,
    compact: (threadId: string) => `/api/threads/${threadId}/compact`,
    hardStop: (threadId: string) => `/api/threads/${threadId}/hard-stop`,
    handoff: (threadId: string) => `/api/threads/${threadId}/handoff`,
    executePlan: (threadId: string) => `/api/threads/${threadId}/plan/execute`,
    clarifyPlan: (threadId: string) => `/api/threads/${threadId}/plan/clarify`,
    suggestions: (threadId: string) => `/api/threads/${threadId}/suggestions`,
    checkpoint: (threadId: string) =>
      `/api/threads/${threadId}/artifacts/mnt/user-data/workspace/checkpoint.json`,
    artifacts: (threadId: string, path: string) =>
      `/api/threads/${threadId}/artifacts${path}`,
    uploads: (threadId: string, filename: string) =>
      `/api/threads/${threadId}/artifacts/mnt/user-data/uploads/${filename}`,
    files: {
      reveal: (threadId: string) => `/api/threads/${threadId}/files/reveal`,
      open: (threadId: string) => `/api/threads/${threadId}/files/open`,
      thumbnail: (threadId: string, path: string) =>
        `/api/threads/${threadId}/files/thumbnail?path=${encodeURIComponent(path)}`,
    },
    workspaceIO: {
      analyse: (threadId: string) => `/api/threads/${threadId}/analyse`,
      analyseStatus: (threadId: string) => `/api/threads/${threadId}/analyse/status`,
      repoOverviewRefresh: (threadId: string) =>
        `/api/threads/${threadId}/analyse/repo-overview-refresh`,
      repoOverviewRefreshStatus: (threadId: string, jobId: string) =>
        `/api/threads/${threadId}/analyse/repo-overview-refresh/${jobId}`,
      publishDocs: (threadId: string) => `/api/threads/${threadId}/publishdocs`,
      mountFolder: (threadId: string) =>
        `/api/threads/${threadId}/dreamy/mount-folder`,
      mountFolderFiles: (threadId: string) =>
        `/api/threads/${threadId}/dreamy/mount-folder/files`,
    },
  },
};
