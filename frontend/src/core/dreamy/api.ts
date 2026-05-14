export const api = {
  threads: {
    steer: (threadId: string) => `/api/threads/${threadId}/steer`,
    compact: (threadId: string) => `/api/threads/${threadId}/compact`,
    executePlan: (threadId: string) => `/api/threads/${threadId}/plan/execute`,
    suggestions: (threadId: string) => `/api/threads/${threadId}/suggestions`,
    checkpoint: (threadId: string) =>
      `/api/threads/${threadId}/artifacts/mnt/user-data/outputs/checkpoint.json`,
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
    dreamy: {
      analyse: (threadId: string) => `/api/threads/${threadId}/analyse`,
      analyseStatus: (threadId: string) => `/api/threads/${threadId}/analyse/status`,
      repoOverviewRefresh: (threadId: string) =>
        `/api/threads/${threadId}/analyse/repo-overview-refresh`,
      repoOverviewRefreshStatus: (threadId: string, jobId: string) =>
        `/api/threads/${threadId}/analyse/repo-overview-refresh/${jobId}`,
      publishDocs: (threadId: string) => `/api/threads/${threadId}/publishdocs`,
      workflow: (threadId: string) => `/api/threads/${threadId}/dreamy/workflow`,
      mountFolder: (threadId: string) =>
        `/api/threads/${threadId}/dreamy/mount-folder`,
      mountFolderFiles: (threadId: string) =>
        `/api/threads/${threadId}/dreamy/mount-folder/files`,
      executor: {
        status: (threadId: string) =>
          `/api/threads/${threadId}/dreamy/executor/status`,
        pause: (threadId: string) =>
          `/api/threads/${threadId}/dreamy/executor/pause`,
        stop: (threadId: string) =>
          `/api/threads/${threadId}/dreamy/executor/stop`,
      },
    },
  },
};
