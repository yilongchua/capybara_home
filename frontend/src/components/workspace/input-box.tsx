"use client";

import type { Checkpoint } from "@langchain/langgraph-sdk";
import { useQueryClient } from "@tanstack/react-query";
import type { ChatStatus } from "ai";
import { CheckIcon, SquareIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { toast } from "sonner";

import {
  PromptInput,
  PromptInputAttachment,
  PromptInputAttachments,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputAttachments,
  usePromptInputController,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { clearThreadClientCache, getAPIClient } from "@/core/api/api-client";
import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/workspace-io/api";
import { useFolderPicker } from "@/core/workspace-io/hooks/use-folder-picker";
import {
  useMountedFolder,
  useSaveMountedFolder,
} from "@/core/workspace-io/hooks/use-mounted-folder";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import type { AgentThreadContext } from "@/core/threads";
import {
  clearPendingChatLaunchPayload,
  getPendingChatLaunchPayload,
  setPendingChatLaunchPayload,
} from "@/core/threads/chat-launch-payload";
import type { ContextTokenState } from "@/core/threads/context-tokens";
import { useRenameThread } from "@/core/threads/hooks";
import {
  isSupportedSlashCommand,
  parseLeadingSlashCommand,
  type SlashCommandName,
} from "@/core/threads/slash-commands";
import { pathOfThread, textOfMessage } from "@/core/threads/utils";
import { sanitizeThreadId } from "@/core/utils/strings";
import { publishWorkspaceRefresh } from "@/core/workspace-refresh";
import { cn } from "@/lib/utils";

import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "../ai-elements/model-selector";
import { Button } from "../ui/button";

import { AttachmentPopup } from "./chat-ui/attachment-popup";
import { FileMentionDropdown } from "./chat-ui/file-mention-dropdown";
import {
  SlashCommandDropdown,
  type SlashCommandOption,
} from "./chat-ui/slash-command-dropdown";
import {
  FollowupConfirmDialog,
  RenameThreadDialog,
} from "./input-box-dialogs";
import { FollowupSuggestionsPanel } from "./input-box-followups";
import {
  PrivacyAndAutoMenu,
  ReasoningEffortMenu,
} from "./input-box-left-toolbar";
import { useThread } from "./messages/context";
import { TokenRing } from "./token-ring";

type InputMode = "work" | "plan";

export type InputBoxSubmitOptions = {
  queued?: boolean;
  checkpoint?: Omit<Checkpoint, "thread_id">;
  forkSourceMessageId?: string;
  forkSourceBranch?: string;
  extraContext?: Record<string, unknown>;
};

function getResolvedMode(
  mode: InputMode | undefined,
  _supportsThinking: boolean,
): InputMode {
  if (mode === "work" || mode === "plan") {
    return mode;
  }
  return "work";
}

const SLASH_COMMANDS: SlashCommandOption[] = [
  {
    name: "compact",
    title: "Compaction",
    usage: "Compress current chat context",
    description: "Force deterministic context compaction for this thread.",
  },
  {
    name: "recover",
    title: "Recover todos",
    usage: "[-todo]",
    description: "Recover stalled todo execution by clearing stale blocking runs.",
  },
  {
    name: "handoff",
    title: "Create handoff",
    usage: "Fork into a new thread",
    description: "Create a structured handoff package under `/mnt/user-data/workspace/.handoff` and open the forked thread.",
  },
  {
    name: "new",
    title: "New chat",
    usage: "Open a fresh chat",
    description: "Start a new chat in the current workspace surface.",
  },
  {
    name: "mount",
    title: "Mount folder",
    usage: "Pick a local folder",
    description: "Open native folder picker and mount a folder for file access.",
  },
  {
    name: "analyse",
    title: "Analyse repo",
    usage: "Stage `.docs` mirror",
    description: "Create mirrored docs in `/mnt/user-data/workspace/.docs` and analysis artifacts in `/mnt/user-data/workspace/.analyse` (no mounted writes).",
  },
  {
    name: "publishdocs",
    title: "Publish docs",
    usage: "Copy staged docs to mounted",
    description: "Copy staged docs from `/mnt/user-data/workspace/.docs` to `/mnt/user-data/mounted/.docs` after review.",
  },
  {
    name: "rename",
    title: "Rename chat",
    usage: "<new title>",
    description: "Rename current chat title.",
  },
];

function dedupeTodoLines(lines: string[]): string[] {
  const seen = new Set<string>();
  const deduped: string[] = [];
  for (const line of lines) {
    const normalized = line.trim().replace(/\s+/g, " ").toLowerCase();
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    deduped.push(line.trim());
  }
  return deduped;
}

function formatTodoList(todos: string[]): string {
  return todos.map((todo, index) => `${index + 1}. ${todo}`).join("\n");
}

function getMountedFolderDisplayName(path: string): string {
  const normalized = path.trim().replace(/[\\/]+$/, "");
  if (!normalized) {
    return "Mounted Folder";
  }

  const segments = normalized.split(/[\\/]/).filter(Boolean);
  return segments[segments.length - 1] ?? normalized;
}

const CAPY_PLACEHOLDERS = [
  "Start chatting with Capy",
  "Spill the tea, Capy's listening",
  "What's the vibe today?",
  "Drop your wildest idea",
  "Ask Capy literally anything",
  "No question is too sus",
  "Capy's down for whatever",
  "Hit me with your best shot",
  "Lock in. Let's go.",
  "What's the side quest today?",
  "Today's the day. What's the move?",
  "Plot twist: you're the main character",
  "Big brain energy starts here",
  "Say less, do more",
  "Touch grass later, chat with Capy now",
  "Manifest your goals here",
  "Make it iconic",
  "You got this. What's first?",
  "Capy believes in you",
  "Let's get this bread with nutella",
  "Rise -> grind -> prompt -> sleep",
  "What're we cooking today?",
  "Drop a thought, change the day",
  "Low-key genius hours, let's go",
];

export function InputBox({
  className,
  disabled,
  autoFocus,
  status = "ready",
  context,
  extraHeader,
  isNewThread,
  threadId,
  newChatHref,
  initialValue,
  onContextChange,
  onSubmit,
  onStop,
  onCompaction,
  contextTokenState,
  ...props
}: Omit<ComponentProps<typeof PromptInput>, "onSubmit"> & {
  assistantId?: string | null;
  status?: ChatStatus;
  disabled?: boolean;
  context: Omit<
    AgentThreadContext,
    "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
  > & {
    mode: "work" | "plan" | undefined;
    reasoning_effort?: "minimal" | "low" | "medium" | "high";
  };
  extraHeader?: React.ReactNode;
  isNewThread?: boolean;
  threadId: string;
  newChatHref?: string;
  initialValue?: string;
  onContextChange?: (
    context: Omit<
      AgentThreadContext,
      "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
    > & {
      mode: "work" | "plan" | undefined;
      reasoning_effort?: "minimal" | "low" | "medium" | "high";
    },
  ) => void;
  onSubmit?: (
    message: PromptInputMessage,
    options?: InputBoxSubmitOptions,
  ) => void;
  onStop?: () => void;
  onCompaction?: (event: {
    messagesCompressed?: number;
    messagesKept?: number;
  }) => void;
  contextTokenState?: ContextTokenState;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [modelDialogOpen, setModelDialogOpen] = useState(false);

  const { models } = useModels();
  const { thread, isMock, forkDraft, setForkDraft } = useThread();
  const { textInput } = usePromptInputController();
  const attachments = usePromptInputAttachments();
  const promptRootRef = useRef<HTMLDivElement | null>(null);

  const [followups, setFollowups] = useState<string[]>([]);
  const [followupsHidden, setFollowupsHidden] = useState(false);
  const [followupsLoading, setFollowupsLoading] = useState(false);
  const lastGeneratedForAiIdRef = useRef<string | null>(null);
  const wasStreamingRef = useRef(false);
  const contextRef = useRef(context);
  const onContextChangeRef = useRef(onContextChange);
  const messagesRef = useRef(thread.messages);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingSuggestion, setPendingSuggestion] = useState<string | null>(null);
  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameInput, setRenameInput] = useState("");
  const [slashSelected, setSlashSelected] = useState<string>("compact");
  const [hasStagedDocs, setHasStagedDocs] = useState(false);
  const repoOverviewPollRef = useRef<number | null>(null);
  const repoOverviewPollJobRef = useRef<string | null>(null);
  const saveMountedFolder = useSaveMountedFolder(threadId);
  const { data: mountedFolder } = useMountedFolder(threadId);
  const renameThread = useRenameThread();
  const { pickFolder, isPicking } = useFolderPicker();
  const launchPayloadAppliedRef = useRef<string | null>(null);
  const stableThreadId = sanitizeThreadId(threadId);
  const attachmentMenuTriggerId = `input-attachment-menu-trigger-${stableThreadId}`;
  const privacyMenuTriggerId = `input-privacy-menu-trigger-${stableThreadId}`;
  const reasoningMenuTriggerId = `input-reasoning-menu-trigger-${stableThreadId}`;
  const modelSelectorTriggerId = `input-model-selector-trigger-${stableThreadId}`;
  const modelSelectorDialogId = `input-model-selector-dialog-${stableThreadId}`;
  const slashState = useMemo(
    () => parseLeadingSlashCommand(textInput.value ?? ""),
    [textInput.value],
  );
  const [placeholderText, setPlaceholderText] = useState<string>(t.inputBox.placeholder);
  useEffect(() => {
    const pick =
      CAPY_PLACEHOLDERS[Math.floor(Math.random() * CAPY_PLACEHOLDERS.length)];
    if (pick) setPlaceholderText(pick);
  }, []);
  const refreshAnalyseStatus = useCallback(async () => {
    try {
      const response = await fetch(
        `${getBackendBaseURL()}${api.threads.workspaceIO.analyseStatus(threadId)}`,
      );
      if (!response.ok) {
        setHasStagedDocs(false);
        return;
      }
      const payload = (await response.json()) as { staged_available?: boolean };
      setHasStagedDocs(payload.staged_available === true);
    } catch {
      setHasStagedDocs(false);
    }
  }, [threadId]);
  const repoOverviewJobStorageKey = useMemo(
    () => `repo_overview_refresh_job.${threadId}`,
    [threadId],
  );
  const stopRepoOverviewPolling = useCallback(() => {
    if (repoOverviewPollRef.current) {
      window.clearInterval(repoOverviewPollRef.current);
      repoOverviewPollRef.current = null;
    }
    repoOverviewPollJobRef.current = null;
  }, []);
  const startRepoOverviewPolling = useCallback(
    (jobId: string) => {
      const normalized = jobId.trim();
      if (!normalized) return;
      window.localStorage.setItem(repoOverviewJobStorageKey, normalized);
      stopRepoOverviewPolling();
      repoOverviewPollJobRef.current = normalized;
      repoOverviewPollRef.current = window.setInterval(() => {
        void (async () => {
          try {
            const statusRes = await fetch(
              `${getBackendBaseURL()}${api.threads.workspaceIO.repoOverviewRefreshStatus(threadId, normalized)}`,
            );
            if (!statusRes.ok) return;
            const statusPayload = (await statusRes.json()) as {
              status?: string;
              error?: string;
            };
            if (statusPayload.status === "succeeded") {
              stopRepoOverviewPolling();
              window.localStorage.removeItem(repoOverviewJobStorageKey);
              toast.success("repo_overview.md analysis completed.");
            } else if (statusPayload.status === "failed") {
              stopRepoOverviewPolling();
              window.localStorage.removeItem(repoOverviewJobStorageKey);
              toast.error(
                statusPayload.error
                  ? `repo_overview.md analysis failed: ${statusPayload.error}`
                  : "repo_overview.md analysis failed.",
              );
            }
          } catch {
            // Ignore transient polling errors.
          }
        })();
      }, 2500);
    },
    [repoOverviewJobStorageKey, stopRepoOverviewPolling, threadId],
  );
  const slashCommands = useMemo(
    () =>
      SLASH_COMMANDS.filter((command) =>
        command.name.includes(slashState.query || ""),
      ),
    [slashState.query],
  );
  const visibleSlashCommands = useMemo(
    () =>
      slashCommands.filter((command) => {
        if (command.name === "publishdocs") {
          return hasStagedDocs;
        }
        return true;
      }),
    [hasStagedDocs, slashCommands],
  );
  const slashMenuVisible = useMemo(() => {
    return (
      slashState.isSlash &&
      slashState.showMenu &&
      !Boolean(disabled) &&
      status !== "streaming"
    );
  }, [disabled, slashState.isSlash, slashState.showMenu, status]);

  useEffect(() => {
    contextRef.current = context;
  }, [context]);

  useEffect(() => {
    void refreshAnalyseStatus();
  }, [refreshAnalyseStatus]);

  useEffect(() => {
    onContextChangeRef.current = onContextChange;
  }, [onContextChange]);

  useEffect(() => {
    messagesRef.current = thread.messages;
  }, [thread.messages]);

  useEffect(() => {
    if (visibleSlashCommands.length === 0) {
      setSlashSelected("");
      return;
    }
    if (!visibleSlashCommands.some((command) => command.name === slashSelected)) {
      setSlashSelected(visibleSlashCommands[0]!.name);
    }
  }, [slashSelected, visibleSlashCommands]);

  useEffect(() => {
    if (models.length === 0) {
      return;
    }

    const currentModel = models.find((m) => m.name === context.model_name);
    const fallbackModel = currentModel ?? models[0]!;
    const supportsThinking = fallbackModel.supports_thinking ?? false;
    const nextModelName = fallbackModel.name;
    const nextMode = getResolvedMode(context.mode, supportsThinking);

    if (context.model_name === nextModelName && context.mode === nextMode) {
      return;
    }

    const latestContext = contextRef.current;
    onContextChangeRef.current?.({
      ...latestContext,
      model_name: nextModelName,
      mode: nextMode,
    });
  }, [models, context.model_name, context.mode]);

  useEffect(() => {
    if (!initialValue) {
      return;
    }
    if ((textInput.value ?? "").trim().length > 0) {
      return;
    }
    textInput.setInput(initialValue);
  }, [initialValue, textInput]);

  useEffect(() => {
    if (!forkDraft) {
      return;
    }
    textInput.setInput(forkDraft.sourceMessageText);
  }, [forkDraft, textInput]);

  useEffect(() => {
    const payload = getPendingChatLaunchPayload();
    if (payload?.targetThreadId !== threadId) {
      return;
    }
    if (launchPayloadAppliedRef.current === threadId) {
      return;
    }
    launchPayloadAppliedRef.current = threadId;
    if (payload.source !== "handoff") {
      return;
    }
    clearPendingChatLaunchPayload();
    if (payload.prefill?.trim()) {
      textInput.setInput(payload.prefill);
    }
  }, [textInput, threadId]);

  const selectedModel = useMemo(() => {
    if (models.length === 0) {
      return undefined;
    }
    return models.find((m) => m.name === context.model_name) ?? models[0];
  }, [context.model_name, models]);

  const supportReasoningEffort = useMemo(
    () => selectedModel?.supports_reasoning_effort ?? false,
    [selectedModel],
  );
  const autoModeEnabled = context.auto_mode === true;
  const isPlanMode = context.mode === "plan";
  const toolbarIconButtonClass =
    "rounded-md border border-border/60 bg-muted/70 hover:bg-muted text-foreground";

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Tab" && e.shiftKey) {
        e.preventDefault();
        if (disabled) {
          return;
        }
        onContextChange?.({
          ...context,
          mode: context.mode === "plan" ? "work" : "plan",
        });
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [disabled, onContextChange, context]);

  const handleReasoningEffortSelect = useCallback(
    (effort: "minimal" | "low" | "medium" | "high") => {
      onContextChange?.({
        ...context,
        reasoning_effort: effort,
      });
    },
    [onContextChange, context],
  );

  const handleToggleAutoMode = useCallback(() => {
    onContextChange?.({
      ...context,
      auto_mode: !context.auto_mode,
    });
  }, [onContextChange, context]);

  const handleTogglePlanMode = useCallback(() => {
    onContextChange?.({
      ...context,
      mode: context.mode === "plan" ? "work" : "plan",
    });
  }, [onContextChange, context]);

  const handleModelSelect = useCallback(
    (modelName: string) => {
      const selected = models.find((m) => m.name === modelName);
      const supportsThinking = selected?.supports_thinking ?? false;

      onContextChange?.({
        ...context,
        model_name: modelName,
        mode: getResolvedMode(context.mode, supportsThinking),
      });
      setModelDialogOpen(false);
    },
    [models, onContextChange, context],
  );

  const emitMountedNotice = useCallback(
    (mountedDir: string, targetThreadId = threadId) => {
      if (typeof window === "undefined") return;
      window.dispatchEvent(
        new CustomEvent("chat-mounted-notice", {
          detail: {
            threadId: targetThreadId,
            content: `Directory : ${mountedDir} Mounted, recommend to perform '/analyse'`,
          },
        }),
      );
    },
    [threadId],
  );

  const createThreadForMountedFolder = useCallback(
    async () => {
      const apiClient = getAPIClient(isMock);
      const createdThread = await (
        apiClient.threads.create as (payload?: { graphId?: string }) => Promise<{
          thread_id: string;
        }>
      )({ graphId: "lead_agent" });
      const createdThreadId = createdThread.thread_id;
      const title = "mount-drive";

      await apiClient.threads.updateState(createdThreadId, {
        values: { title },
      });

      await queryClient.invalidateQueries({
        queryKey: ["threads", "search"],
        exact: false,
      });
      publishWorkspaceRefresh(["threads", `thread:${createdThreadId}`], {
        source: "mount-folder-create-thread",
      });

      return { createdThreadId, title };
    },
    [isMock, queryClient],
  );

  const handleMountFolder = useCallback(async () => {
    try {
      const path = await pickFolder();
      if (path === null) return;
      if (isNewThread) {
        const { createdThreadId } = await createThreadForMountedFolder();
        setPendingChatLaunchPayload({
          source: "mount",
          targetThreadId: createdThreadId,
          mountedPath: path,
          createdAt: Date.now(),
        });
        await fetch(`${getBackendBaseURL()}${api.threads.workspaceIO.mountFolder(createdThreadId)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path }),
        }).then(async (response) => {
          if (!response.ok) {
            const message = await response.text();
            throw new Error(message || "failed to mount folder");
          }
        });
        toast.message(`Mounting files from ${getMountedFolderDisplayName(path)}...`);
        router.push(pathOfThread(createdThreadId));
        return;
      }
      const savedPath = await saveMountedFolder.mutateAsync(path);
      toast.success(`Mounted: ${savedPath}`);
      emitMountedNotice(savedPath);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to mount folder";
      toast.error(message);
    }
  }, [
    createThreadForMountedFolder,
    emitMountedNotice,
    isNewThread,
    pickFolder,
    router,
    saveMountedFolder,
  ]);

  const getNewChatHref = useCallback(() => {
    if (newChatHref) {
      return newChatHref;
    }
    return "/workspace/chats/new";
  }, [newChatHref]);

  const runCompact = useCallback(async () => {
    try {
      const response = await fetch(
        `${getBackendBaseURL()}${api.threads.compact(threadId)}`,
        {
          method: "POST",
        },
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const payload = (await response.json()) as {
        status?: string;
        message?: string;
        compressed_messages?: number;
        kept_messages?: number;
      };
      if (payload.status === "no_op") {
        toast.message(payload.message ?? "Nothing to compact right now.");
        return;
      }
      clearThreadClientCache(threadId);
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
      publishWorkspaceRefresh(["threads", `thread:${threadId}`], {
        source: "manual-compaction",
      });
      onCompaction?.({
        messagesCompressed: payload.compressed_messages,
        messagesKept: payload.kept_messages,
      });
      const countSuffix =
        typeof payload.compressed_messages === "number"
          ? ` (${payload.compressed_messages} compressed, ${payload.kept_messages ?? 0} kept)`
          : "";
      toast.success(`${payload.message ?? "Compaction completed."}${countSuffix}`);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to compact context.";
      toast.error(message);
    }
  }, [onCompaction, queryClient, threadId]);

  const collectIncompletePlanTodos = useCallback((): {
    incomplete: string[];
    completed: string[];
  } => {
    const todos = thread.values.todos ?? [];
    const incompleteFromTodos = todos
      .filter((todo) => todo.content?.trim() && todo.status !== "completed")
      .map((todo) => todo.content!.trim());
    const completedFromTodos = todos
      .filter((todo) => todo.content?.trim() && todo.status === "completed")
      .map((todo) => todo.content!.trim());

    const phaseResults = thread.values.phase_execution?.phase_results ?? [];
    const incompleteFromPhases = phaseResults
      .filter((phase) => phase.content?.trim() && phase.status !== "completed")
      .map((phase) => phase.content.trim());
    const completedFromPhases = phaseResults
      .filter((phase) => phase.content?.trim() && phase.status === "completed")
      .map((phase) => phase.content.trim());

    return {
      incomplete: dedupeTodoLines([...incompleteFromTodos, ...incompleteFromPhases]),
      completed: dedupeTodoLines([...completedFromTodos, ...completedFromPhases]),
    };
  }, [thread.values.phase_execution?.phase_results, thread.values.todos]);

  const runRecoverTodo = useCallback(async (): Promise<{
    cancelled: number;
    hadPending: boolean;
  } | null> => {
    const client = getAPIClient(isMock);
    try {
      const runs = await client.runs.list(threadId, { limit: 50 });
      const runningRuns = runs.filter((run) => run.status === "running");
      const pendingRuns = runs.filter((run) => run.status === "pending");

      if (runningRuns.length === 0 && pendingRuns.length === 0) {
        toast.message("No running or pending runs found for this thread.");
        return { cancelled: 0, hadPending: false };
      }

      const pendingNewestTs = pendingRuns.reduce((latest, run) => {
        const ts = Number(new Date(run.created_at).getTime()) || 0;
        return Math.max(latest, ts);
      }, 0);

      const staleRunning = runningRuns.filter((run) => {
        const createdAtTs = Number(new Date(run.created_at).getTime()) || 0;
        return pendingNewestTs > 0 && createdAtTs > 0 && createdAtTs < pendingNewestTs;
      });

      const candidates = staleRunning.length > 0 ? staleRunning : runningRuns;
      if (candidates.length === 0) {
        toast.message("No stale blocking runs found.");
        return { cancelled: 0, hadPending: pendingRuns.length > 0 };
      }

      await Promise.all(
        candidates.map((run) => client.runs.cancel(threadId, String(run.run_id), false, "interrupt")),
      );

      toast.success(
        candidates.length === 1
          ? "Recovered todo execution. Cancelled 1 blocking run."
          : `Recovered todo execution. Cancelled ${candidates.length} blocking runs.`,
      );
      return { cancelled: candidates.length, hadPending: pendingRuns.length > 0 };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to recover todo execution.";
      toast.error(message);
      return null;
    }
  }, [isMock, threadId]);

  const runRename = useCallback(
    async (title: string) => {
      const nextTitle = title.trim();
      if (!nextTitle) {
        toast.error("Please provide a non-empty title.");
        return;
      }
      if (isNewThread) {
        toast.error("Start the chat first, then rename it.");
        return;
      }
      try {
        await renameThread.mutateAsync({ threadId, title: nextTitle });
        toast.success("Chat renamed.");
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to rename chat.";
        toast.error(message);
      }
    },
    [isNewThread, renameThread, threadId],
  );

  const runAnalyse = useCallback(async () => {
    if (!mountedFolder) {
      toast.error("Mount a folder first to run /analyse.");
      return;
    }
    try {
      const response = await fetch(
        `${getBackendBaseURL()}${api.threads.workspaceIO.analyse(threadId)}`,
        { method: "POST" },
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const payload = (await response.json()) as {
        generated_docs?: number;
        failed?: number;
        index_virtual_path?: string;
        repo_overview_refresh_job_id?: string;
      };
      toast.success(
        `Analysis complete. Generated ${payload.generated_docs ?? 0} docs with ${payload.failed ?? 0} failures.`,
      );
      if (payload.index_virtual_path) {
        toast.message(`Index: ${payload.index_virtual_path}`);
      }
      setHasStagedDocs(true);
      const refreshJobId = payload.repo_overview_refresh_job_id?.trim();
      if (refreshJobId) {
        toast.message("Background repo_overview.md analysis started.");
        startRepoOverviewPolling(refreshJobId);
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to run /analyse.";
      toast.error(message);
    }
  }, [mountedFolder, startRepoOverviewPolling, threadId]);

  useEffect(() => {
    const existingJobId = window.localStorage.getItem(repoOverviewJobStorageKey)?.trim();
    if (existingJobId) {
      startRepoOverviewPolling(existingJobId);
    }
    return () => {
      stopRepoOverviewPolling();
    };
  }, [repoOverviewJobStorageKey, startRepoOverviewPolling, stopRepoOverviewPolling]);

  useEffect(() => {
    return () => {
      stopRepoOverviewPolling();
    };
  }, [stopRepoOverviewPolling]);

  const runPublishDocs = useCallback(async () => {
    if (!mountedFolder) {
      toast.error("Mount a folder first to run /publishdocs.");
      return;
    }
    try {
      const response = await fetch(
        `${getBackendBaseURL()}${api.threads.workspaceIO.publishDocs(threadId)}`,
        { method: "POST" },
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const payload = (await response.json()) as {
        copied_files?: number;
        overwritten_files?: number;
        index_virtual_path?: string;
      };
      toast.success(
        `Published docs. Copied ${payload.copied_files ?? 0} files (${payload.overwritten_files ?? 0} overwritten).`,
      );
      if (payload.index_virtual_path) {
        toast.message(`Published index: ${payload.index_virtual_path}`);
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to run /publishdocs.";
      toast.error(message);
    }
  }, [mountedFolder, threadId]);

  const executeSlashCommand = useCallback(
    async (commandName: SlashCommandName, rawArgs = "") => {
      const args = rawArgs.trim();
      if (Boolean(disabled) || (status === "streaming" && commandName !== "recover")) {
        toast.error("Commands are unavailable while the chat is busy.");
        return;
      }

      if (commandName === "compact") {
        await runCompact();
        return;
      }
      if (commandName === "recover") {
        if (args && args !== "-todo") {
          toast.error("Usage: /recover or /recover -todo");
          return;
        }
        const { incomplete, completed } = collectIncompletePlanTodos();
        const recovery = await runRecoverTodo();
        if (incomplete.length === 0) {
          toast.message("No incomplete todos found in the current plan. Cleared blockers if any.");
          textInput.setInput("");
          return;
        }
        if (recovery === null) {
          return;
        }
        const recoveryPrompt = [
          "User command: /recover",
          "Recover the existing work-mode plan from current thread state.",
          "Read the plan file first: /mnt/user-data/workspace/plan.md",
          "If plan.md is unavailable, use the in-memory plan/todo_graph from thread state.",
          "Only execute the incomplete todos listed below, in order.",
          "Do not redo completed todos.",
          "",
          "Incomplete todos:",
          formatTodoList(incomplete),
          "",
          ...(completed.length > 0
            ? [
                "Already completed todos (for reference, do not redo):",
                formatTodoList(completed.slice(0, 20)),
                "",
              ]
            : []),
          "Continue execution until all incomplete todos are completed, updating todo statuses as you go.",
        ].join("\n");

        onSubmit?.(
          {
            text: recoveryPrompt,
            files: [],
          },
          {
            queued: true,
            extraContext: {
              recover_todo_command: true,
              recover_todo_incomplete_count: incomplete.length,
              recover_todo_completed_count: completed.length,
              recover_todo_plan_path: "/mnt/user-data/workspace/plan.md",
            },
          },
        );
        toast.success(`Recovering ${incomplete.length} incomplete todo${incomplete.length === 1 ? "" : "s"}.`);
        textInput.setInput("");
        return;
      }

      if (commandName === "new") {
        router.push(getNewChatHref());
        return;
      }

      if (commandName === "mount") {
        await handleMountFolder();
        return;
      }

      if (commandName === "rename") {
        if (args) {
          await runRename(args);
          textInput.setInput("");
          return;
        }
        setRenameInput("");
        setRenameDialogOpen(true);
        return;
      }

      if (commandName === "analyse") {
        await runAnalyse();
        textInput.setInput("");
        return;
      }

      if (commandName === "publishdocs") {
        await runPublishDocs();
        textInput.setInput("");
        return;
      }

      if (commandName === "handoff") {
        try {
          const response = await fetch(
            `${getBackendBaseURL()}${api.threads.handoff(threadId)}`,
            {
              method: "POST",
            },
          );
          if (!response.ok) {
            throw new Error(await response.text());
          }
          const payload = (await response.json()) as {
            new_thread_id: string;
            handoff_root_virtual_path?: string;
            prefill?: string;
            copied_file_count?: number;
          };
          setPendingChatLaunchPayload({
            source: "handoff",
            targetThreadId: payload.new_thread_id,
            handoffRootVirtualPath: payload.handoff_root_virtual_path,
            prefill: payload.prefill,
            createdAt: Date.now(),
          });
          router.push(pathOfThread(payload.new_thread_id));
          if (typeof payload.copied_file_count === "number") {
            toast.success(`Created handoff and copied ${payload.copied_file_count} file(s) into the new thread.`);
          } else {
            toast.success("Created handoff and opened the forked thread.");
          }
        } catch (error) {
          const message =
            error instanceof Error ? error.message : "Failed to create handoff.";
          toast.error(message);
          return;
        }
        textInput.setInput("");
      }
    },
    [
      disabled,
      getNewChatHref,
      handleMountFolder,
      router,
      runAnalyse,
      runPublishDocs,
      runCompact,
      collectIncompletePlanTodos,
      runRecoverTodo,
      runRename,
      status,
      textInput,
      threadId,
      onSubmit,
    ],
  );

  const handleSubmit = useCallback(
    async (message: PromptInputMessage) => {
      if (!message.text) {
        return;
      }
      const slash = parseLeadingSlashCommand(message.text);
      if (slash.isSlash && slash.commandName && isSupportedSlashCommand(slash.commandName)) {
        await executeSlashCommand(slash.commandName, slash.args);
        return;
      }
      const messageWithoutForkAttachments = forkDraft
        ? { ...message, files: [] }
        : message;
      const finalMessage = messageWithoutForkAttachments;
      const submitOptions: InputBoxSubmitOptions = { queued: true };
      if (forkDraft) {
        submitOptions.checkpoint = forkDraft.checkpoint;
        submitOptions.forkSourceMessageId = forkDraft.sourceMessageId;
        submitOptions.forkSourceBranch = forkDraft.sourceBranch;
      }
      setFollowups([]);
      setFollowupsHidden(false);
      setFollowupsLoading(false);
      onSubmit?.(finalMessage, submitOptions);
      if (forkDraft) {
        setForkDraft?.(null);
      }
    },
    [executeSlashCommand, forkDraft, onSubmit, setForkDraft],
  );

  const requestFormSubmit = useCallback(() => {
    const form = promptRootRef.current?.querySelector("form");
    form?.requestSubmit();
  }, []);

  const handleInputSpecialKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
      if (!slashMenuVisible) {
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        textInput.setInput("");
        return;
      }
      if (visibleSlashCommands.length === 0) {
        return;
      }
      const selectedIndex = visibleSlashCommands.findIndex(
        (command) => command.name === slashSelected,
      );
      if (event.key === "ArrowDown") {
        event.preventDefault();
        const next =
          visibleSlashCommands[(selectedIndex + 1) % visibleSlashCommands.length] ??
          visibleSlashCommands[0];
        if (next) setSlashSelected(next.name);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        const prev =
          visibleSlashCommands[
            (selectedIndex - 1 + visibleSlashCommands.length) % visibleSlashCommands.length
          ] ?? visibleSlashCommands[0];
        if (prev) setSlashSelected(prev.name);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        const target =
          visibleSlashCommands.find((command) => command.name === slashSelected) ??
          visibleSlashCommands[0];
        if (!target) {
          return;
        }
        void executeSlashCommand(target.name as SlashCommandName, "");
        textInput.setInput("");
      }
    },
    [
      executeSlashCommand,
      visibleSlashCommands,
      slashMenuVisible,
      slashSelected,
      textInput,
    ],
  );

  const handleFollowupClick = useCallback(
    (suggestion: string) => {
      if (status === "streaming") {
        return;
      }
      const current = (textInput.value ?? "").trim();
      if (current) {
        setPendingSuggestion(suggestion);
        setConfirmOpen(true);
        return;
      }
      textInput.setInput(suggestion);
      setFollowupsHidden(true);
      setTimeout(() => requestFormSubmit(), 0);
    },
    [requestFormSubmit, status, textInput],
  );

  const confirmReplaceAndSend = useCallback(() => {
    if (!pendingSuggestion) {
      setConfirmOpen(false);
      return;
    }
    textInput.setInput(pendingSuggestion);
    setFollowupsHidden(true);
    setConfirmOpen(false);
    setPendingSuggestion(null);
    setTimeout(() => requestFormSubmit(), 0);
  }, [pendingSuggestion, requestFormSubmit, textInput]);

  const confirmAppendAndSend = useCallback(() => {
    if (!pendingSuggestion) {
      setConfirmOpen(false);
      return;
    }
    const current = (textInput.value ?? "").trim();
    const next = current ? `${current}\n${pendingSuggestion}` : pendingSuggestion;
    textInput.setInput(next);
    setFollowupsHidden(true);
    setConfirmOpen(false);
    setPendingSuggestion(null);
    setTimeout(() => requestFormSubmit(), 0);
  }, [pendingSuggestion, requestFormSubmit, textInput]);

  const lastMessageId = thread.messages[thread.messages.length - 1]?.id ?? null;

  useEffect(() => {
    const streaming = status === "streaming";
    const wasStreaming = wasStreamingRef.current;
    wasStreamingRef.current = streaming;
    if (!wasStreaming || streaming) {
      return;
    }

    if (disabled || isMock) {
      return;
    }

    const messages = messagesRef.current;
    const lastAi = [...messages].reverse().find((m) => m.type === "ai");
    const lastAiId = lastAi?.id ?? null;
    if (!lastAiId || lastAiId === lastGeneratedForAiIdRef.current) {
      return;
    }
    lastGeneratedForAiIdRef.current = lastAiId;

    const recent = messages
      .filter((m) => m.type === "human" || m.type === "ai")
      .map((m) => {
        const role = m.type === "human" ? "user" : "assistant";
        const content = textOfMessage(m) ?? "";
        return { role, content };
      })
      .filter((m) => m.content.trim().length > 0)
      .slice(-6);

    if (recent.length === 0) {
      return;
    }

    const controller = new AbortController();
    setFollowupsHidden(false);
    setFollowupsLoading(true);
    setFollowups([]);

    fetch(`${getBackendBaseURL()}${api.threads.suggestions(threadId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: recent,
        n: 3,
        model_name: context.model_name ?? undefined,
      }),
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          return { suggestions: [] as string[] };
        }
        return (await res.json()) as { suggestions?: string[] };
      })
      .then((data) => {
        const suggestions = (data.suggestions ?? [])
          .map((s) => (typeof s === "string" ? s.trim() : ""))
          .filter((s) => s.length > 0)
          .slice(0, 5);
        setFollowups(suggestions);
      })
      .catch(() => {
        setFollowups([]);
      })
      .finally(() => {
        setFollowupsLoading(false);
      });

    return () => controller.abort();
  }, [context.model_name, disabled, isMock, status, threadId, lastMessageId]);

  return (
    <div ref={promptRootRef} className="relative">
      <FileMentionDropdown threadId={threadId} />
      <SlashCommandDropdown
        visible={slashMenuVisible}
        query={slashState.query}
        commands={visibleSlashCommands}
        selected={slashSelected}
        onSelectedChange={setSlashSelected}
        onExecute={(name) => {
          if (!isSupportedSlashCommand(name)) {
            return;
          }
          void executeSlashCommand(name);
          textInput.setInput("");
        }}
      />
      <PromptInput
        className={cn(
          "bg-background/85 rounded-2xl backdrop-blur-sm transition-all duration-300 ease-out *:data-[slot='input-group']:rounded-2xl",
          isNewThread &&
            "*:data-[slot='input-group']:border-2 *:data-[slot='input-group']:border-solid *:data-[slot='input-group']:border-[#4a2d1a] *:data-[slot='input-group']:bg-background/95 *:data-[slot='input-group']:shadow-none",
          className,
        )}
        disabled={disabled}
        globalDrop
        multiple
        onSubmit={handleSubmit}
        {...props}
      >
        {forkDraft && (
          <div className="mb-2 flex items-center justify-between rounded-lg border bg-amber-50/70 px-3 py-2 text-xs text-amber-900">
            <div className="min-w-0">
              <p className="font-medium">Editing earlier message (fork)</p>
              <p className="truncate">
                {forkDraft.sourceCreatedAt
                  ? `${new Date(forkDraft.sourceCreatedAt).toLocaleString()} - ${forkDraft.sourcePreview}`
                  : forkDraft.sourcePreview}
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setForkDraft?.(null)}
            >
              Cancel fork
            </Button>
          </div>
        )}
        {extraHeader && (
          <div className="absolute top-0 right-0 left-0 z-10">
            <div className="absolute right-0 bottom-0 left-0 flex items-center justify-center">
              {extraHeader}
            </div>
          </div>
        )}
        <PromptInputAttachments>
          {(attachment) => <PromptInputAttachment data={attachment} />}
        </PromptInputAttachments>
        <PromptInputBody className="absolute top-0 right-0 left-0 z-3">
          <PromptInputTextarea
            className={cn("size-full")}
            disabled={disabled}
            placeholder={placeholderText}
            autoFocus={autoFocus}
            defaultValue={initialValue}
            onSpecialKeyDown={handleInputSpecialKeyDown}
          />
        </PromptInputBody>

        <PromptInputFooter className="flex w-full min-w-0 flex-wrap items-center gap-2">
          <PromptInputTools className="min-w-0 flex-wrap">
            <AttachmentPopup
              triggerId={attachmentMenuTriggerId}
              onAttachFiles={() => attachments.openFileDialog()}
              onMountFolder={() => void handleMountFolder()}
              isPicking={isPicking}
              className={toolbarIconButtonClass}
            />
            <PrivacyAndAutoMenu
              mode={context.mode}
              autoModeEnabled={autoModeEnabled}
              onTogglePlanMode={handleTogglePlanMode}
              onToggleAutoMode={handleToggleAutoMode}
              triggerId={privacyMenuTriggerId}
              triggerClassName={toolbarIconButtonClass}
            />
            <ReasoningEffortMenu
              show={supportReasoningEffort}
              reasoningEffort={context.reasoning_effort}
              onSelect={handleReasoningEffortSelect}
              triggerId={reasoningMenuTriggerId}
              triggerClassName={toolbarIconButtonClass}
            />
          </PromptInputTools>
          <PromptInputTools className="ml-auto min-w-0 flex-wrap justify-end">
            {isPlanMode ? (
              <div className="rounded-full border border-yellow-300 bg-yellow-100 px-2 py-1 text-[11px] font-medium text-yellow-700 dark:border-yellow-600/70 dark:bg-yellow-900/35 dark:text-yellow-300">
                Plan mode
              </div>
            ) : null}
            {contextTokenState ? (
              <TokenRing
                currentTokens={contextTokenState.currentTokens}
                maxTokens={contextTokenState.maxTokens}
                contextWindow={contextTokenState.contextWindow}
                percentage={contextTokenState.percentage}
                isContextWindowApproximate={contextTokenState.isContextWindowApproximate}
                isCompacting={contextTokenState.isCompacting}
                modelName={selectedModel?.display_name ?? selectedModel?.name}
                size="sm"
                labelStyle="remaining"
                showLabel
              />
            ) : null}
            <ModelSelector open={modelDialogOpen} onOpenChange={setModelDialogOpen}>
              <ModelSelectorTrigger asChild>
                <PromptInputButton
                  id={modelSelectorTriggerId}
                  aria-controls={modelSelectorDialogId}
                  className={toolbarIconButtonClass}
                  disabled={models.length === 0}
                >
                  <ModelSelectorName className="max-w-[8.5rem] truncate text-xs font-normal sm:max-w-[12rem]">
                    {selectedModel?.display_name ?? selectedModel?.name ?? "Select model"}
                  </ModelSelectorName>
                </PromptInputButton>
              </ModelSelectorTrigger>
              <ModelSelectorContent id={modelSelectorDialogId}>
                <ModelSelectorInput placeholder={t.inputBox.searchModels} />
                <ModelSelectorList>
                  {models.map((m) => (
                    <ModelSelectorItem
                      key={m.name}
                      value={m.name}
                      onSelect={() => handleModelSelect(m.name)}
                    >
                      <ModelSelectorName>{m.display_name}</ModelSelectorName>
                      {m.name === context.model_name ? (
                        <CheckIcon className="ml-auto size-4" />
                      ) : (
                        <div className="ml-auto size-4" />
                      )}
                    </ModelSelectorItem>
                  ))}
                </ModelSelectorList>
              </ModelSelectorContent>
            </ModelSelector>
            {status === "streaming" && (
              <PromptInputButton
                type="button"
                className={cn("gap-1 px-2", toolbarIconButtonClass)}
                onClick={onStop}
                aria-label="Stop current response"
              >
                <SquareIcon className="size-3.5" />
                <span className="text-xs">Stop</span>
              </PromptInputButton>
            )}
            <PromptInputSubmit
              className="rounded-full"
              disabled={disabled}
              variant="outline"
              status={status === "streaming" ? "ready" : status}
            />
          </PromptInputTools>
        </PromptInputFooter>

        {!isNewThread && (
          <div className="bg-background absolute right-0 -bottom-[17px] left-0 z-0 h-4" />
        )}
      </PromptInput>

      <FollowupSuggestionsPanel
        disabled={disabled}
        isNewThread={isNewThread}
        followupsHidden={followupsHidden}
        followupsLoading={followupsLoading}
        followups={followups}
        onSelect={handleFollowupClick}
        onHide={() => setFollowupsHidden(true)}
      />

      <RenameThreadDialog
        open={renameDialogOpen}
        onOpenChange={setRenameDialogOpen}
        value={renameInput}
        onChange={setRenameInput}
        onConfirm={() => {
          void runRename(renameInput);
          setRenameDialogOpen(false);
          setRenameInput("");
          textInput.setInput("");
        }}
      />

      <FollowupConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        onReplace={confirmReplaceAndSend}
        onAppend={confirmAppendAndSend}
      />
    </div>
  );
}
