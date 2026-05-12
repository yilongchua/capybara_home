"use client";

import type { Checkpoint } from "@langchain/langgraph-sdk";
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
import { getBackendBaseURL } from "@/core/config";
import { startAutoresearchObjective } from "@/core/control-plane/api";
import { api } from "@/core/dreamy/api";
import { useFolderPicker } from "@/core/dreamy/hooks/use-folder-picker";
import {
  useMountedFolder,
  useSaveMountedFolder,
} from "@/core/dreamy/hooks/use-mounted-folder";
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
import { textOfMessage } from "@/core/threads/utils";
import { sanitizeThreadId } from "@/core/utils/strings";
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
  AutoresearchDialog,
  FollowupConfirmDialog,
  MountFolderDialog,
  RenameThreadDialog,
} from "./input-box-dialogs";
import { FollowupSuggestionsPanel } from "./input-box-followups";
import {
  PrivacyAndAutoMenu,
  ReasoningEffortMenu,
  WorkflowButton,
} from "./input-box-left-toolbar";
import { useThread } from "./messages/context";
import { TokenRing } from "./token-ring";

type InputMode = "work" | "plan";

export type InputBoxSubmitOptions = {
  queued?: boolean;
  checkpoint?: Omit<Checkpoint, "thread_id">;
  forkSourceMessageId?: string;
  forkSourceBranch?: string;
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
    name: "handoff",
    title: "Create handoff",
    usage: "Generate summary markdown handoff",
    description: "Create handoff files under mounted `.docs/handoffs/` and open a new chat draft.",
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
    description: "Create full mirrored docs structure inside `/mnt/user-data/outputs/.docs` (no mounted writes).",
  },
  {
    name: "publishdocs",
    title: "Publish docs",
    usage: "Copy staged docs to mounted",
    description: "Copy staged docs from `/mnt/user-data/outputs/.docs` to `/mnt/user-data/mounted/.docs` after review.",
  },
  {
    name: "autoresearch",
    title: "Autoresearch",
    usage: "<topic> [| endpoint goal]",
    description: "Start an autoresearch objective tied to this chat thread.",
  },
  {
    name: "rename",
    title: "Rename chat",
    usage: "<new title>",
    description: "Rename current chat title.",
  },
];

function defaultAutoresearchEndpoint(topic: string): string {
  return `Deliver a complete, evidence-backed research brief for ${topic} with actionable next steps.`;
}

function parseAutoresearchArgs(rawArgs: string): {
  topic: string;
  endpointGoal: string;
} | null {
  const args = rawArgs.trim();
  if (!args) return null;
  const [topicRaw, endpointRaw] = args.split("|", 2);
  const topic = topicRaw?.trim() ?? "";
  if (!topic) return null;
  const endpointGoalCandidate = endpointRaw?.trim() ?? "";
  const endpointGoal =
    endpointGoalCandidate.length > 0
      ? endpointGoalCandidate
      : defaultAutoresearchEndpoint(topic);
  return { topic, endpointGoal };
}

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
  dreamy,
  onContextChange,
  onSubmit,
  onStop,
  contextTokenState,
  ...props
}: Omit<ComponentProps<typeof PromptInput>, "onSubmit"> & {
  assistantId?: string | null;
  status?: ChatStatus;
  disabled?: boolean;
  dreamy?: boolean;
  context: Omit<
    AgentThreadContext,
    "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
  > & {
    mode: "work" | "plan" | undefined;
    reasoning_effort?: "minimal" | "low" | "medium" | "high";
    mask_sensitive_search?: boolean;
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
      mask_sensitive_search?: boolean;
    },
  ) => void;
  onSubmit?: (
    message: PromptInputMessage,
    options?: InputBoxSubmitOptions,
  ) => void;
  onStop?: () => void;
  contextTokenState?: ContextTokenState;
}) {
  const { t } = useI18n();
  const router = useRouter();
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
  const [workflowPrefixActive, setWorkflowPrefixActive] = useState(false);
  const [mountDialogOpen, setMountDialogOpen] = useState(false);
  const [mountPathInput, setMountPathInput] = useState("");
  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameInput, setRenameInput] = useState("");
  const [autoresearchDialogOpen, setAutoresearchDialogOpen] = useState(false);
  const [autoresearchTopic, setAutoresearchTopic] = useState("");
  const [autoresearchEndpointGoal, setAutoresearchEndpointGoal] = useState("");
  const [autoresearchSubmitting, setAutoresearchSubmitting] = useState(false);
  const [slashSelected, setSlashSelected] = useState<string>("compact");
  const saveMountedFolder = useSaveMountedFolder(threadId);
  const { data: mountedFolder } = useMountedFolder(threadId);
  const renameThread = useRenameThread();
  const { pickFolder, isPicking } = useFolderPicker();
  const launchPayloadAppliedRef = useRef(false);
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
  const slashCommands = useMemo(
    () =>
      SLASH_COMMANDS.filter((command) =>
        command.name.includes(slashState.query || ""),
      ),
    [slashState.query],
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
    onContextChangeRef.current = onContextChange;
  }, [onContextChange]);

  useEffect(() => {
    messagesRef.current = thread.messages;
  }, [thread.messages]);

  useEffect(() => {
    if (slashCommands.length === 0) {
      setSlashSelected("");
      return;
    }
    if (!slashCommands.some((command) => command.name === slashSelected)) {
      setSlashSelected(slashCommands[0]!.name);
    }
  }, [slashCommands, slashSelected]);

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
    if (!isNewThread || launchPayloadAppliedRef.current) {
      return;
    }
    const payload = getPendingChatLaunchPayload();
    if (!payload) {
      return;
    }
    launchPayloadAppliedRef.current = true;
    clearPendingChatLaunchPayload();

    const apply = async () => {
      if (payload.mountedPath) {
        try {
          await saveMountedFolder.mutateAsync(payload.mountedPath);
        } catch (error) {
          const message =
            error instanceof Error
              ? error.message
              : "Failed to mount handoff folder in new chat.";
          toast.error(message);
        }
      }
      if (payload.prefill?.trim()) {
        textInput.setInput(payload.prefill);
      }
    };
    void apply();
  }, [isNewThread, saveMountedFolder, textInput]);

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

  const handleToggleSearchPrivacy = useCallback(() => {
    onContextChange?.({
      ...context,
      mask_sensitive_search: !context.mask_sensitive_search,
    });
  }, [onContextChange, context]);

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

  const handleMountFolder = useCallback(async () => {
    try {
      const path = await pickFolder();
      if (path === null) return;
      const savedPath = await saveMountedFolder.mutateAsync(path);
      toast.success(`Mounted: ${savedPath}`);
    } catch {
      setMountPathInput("");
      setMountDialogOpen(true);
    }
  }, [pickFolder, saveMountedFolder]);

  const handleConfirmMount = useCallback(async () => {
    const path = mountPathInput.trim();
    if (!path) {
      setMountDialogOpen(false);
      return;
    }
    try {
      const savedPath = await saveMountedFolder.mutateAsync(path);
      toast.success(`Mounted folder: ${savedPath}`);
      setMountDialogOpen(false);
      setMountPathInput("");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to mount folder";
      toast.error(message);
    }
  }, [saveMountedFolder, mountPathInput]);

  const getNewChatHref = useCallback(() => {
    if (newChatHref) {
      return newChatHref;
    }
    if (dreamy) {
      return "/workspace/dreamy/new";
    }
    return "/workspace/chats/new";
  }, [dreamy, newChatHref]);

  const submitPromptText = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setWorkflowPrefixActive(false);
      setFollowups([]);
      setFollowupsHidden(false);
      setFollowupsLoading(false);
      onSubmit?.({ text: trimmed, files: [] }, { queued: true });
    },
    [onSubmit],
  );

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
      };
      if (payload.status === "no_op") {
        toast.message(payload.message ?? "Nothing to compact right now.");
        return;
      }
      toast.success(payload.message ?? "Compaction completed.");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to compact context.";
      toast.error(message);
    }
  }, [threadId]);

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

  const runAutoresearch = useCallback(
    async (topic: string, endpointGoal: string) => {
      const nextTopic = topic.trim();
      const nextEndpoint = endpointGoal.trim();
      if (!nextTopic || !nextEndpoint) {
        toast.error("Topic and endpoint goal are required.");
        return;
      }
      if (status === "streaming") {
        toast.error("Wait for the current response to finish.");
        return;
      }
      setAutoresearchSubmitting(true);
      try {
        await startAutoresearchObjective({
          topic: nextTopic,
          endpoint_goal: nextEndpoint,
          thread_id: threadId,
          bootstrap: true,
        });
        toast.success("Autoresearch objective created.");
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Failed to start autoresearch objective.";
        toast.error(message);
      } finally {
        setAutoresearchSubmitting(false);
      }
    },
    [status, threadId],
  );

  const executeSlashCommand = useCallback(
    async (commandName: SlashCommandName, rawArgs = "") => {
      const args = rawArgs.trim();
      if (Boolean(disabled) || status === "streaming") {
        toast.error("Commands are unavailable while the chat is busy.");
        return;
      }

      if (commandName === "compact") {
        await runCompact();
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

      if (commandName === "autoresearch") {
        const parsed = parseAutoresearchArgs(args);
        if (parsed) {
          await runAutoresearch(parsed.topic, parsed.endpointGoal);
          textInput.setInput("");
          return;
        }
        setAutoresearchTopic("");
        setAutoresearchEndpointGoal("");
        setAutoresearchDialogOpen(true);
        return;
      }

      if (commandName === "analyse") {
        if (!mountedFolder) {
          toast.error("Mount a folder first to run /analyse.");
          return;
        }
        submitPromptText(
          [
            `Analyse the mounted repository at /mnt/user-data/mounted and build a complete mirrored docs tree under /mnt/user-data/outputs/.docs.`,
            `Guardrail (mandatory): Do NOT write anything under /mnt/user-data/mounted during this step.`,
            `Requirements:`,
            `1. Mirror the source folder/subfolder hierarchy exactly in .docs.`,
            `2. For each source file, create a corresponding markdown doc that captures the file purpose and full content context.`,
            `3. Keep cross-links between related modules when helpful.`,
            `4. Skip binary outputs and generated caches unless they are critical.`,
            `5. After generation, include a summary index at /mnt/user-data/outputs/.docs/index.md.`,
            `6. End by asking for explicit approval to publish staged docs into /mnt/user-data/mounted/.docs.`,
            `For all further queries in this thread, prefer consulting staged .docs first.`,
          ].join("\n"),
        );
        textInput.setInput("");
        return;
      }

      if (commandName === "publishdocs") {
        if (!mountedFolder) {
          toast.error("Mount a folder first to run /publishdocs.");
          return;
        }
        submitPromptText(
          [
            `Publish staged docs to mounted repository.`,
            `Source: /mnt/user-data/outputs/.docs`,
            `Destination: /mnt/user-data/mounted/.docs`,
            `Requirements:`,
            `1. Validate source exists before copying.`,
            `2. Copy recursively and preserve structure.`,
            `3. If destination exists, merge safely and report overwritten files clearly.`,
            `4. After copy, verify /mnt/user-data/mounted/.docs/index.md exists and present it.`,
          ].join("\n"),
        );
        textInput.setInput("");
        return;
      }

      if (commandName === "handoff") {
        if (!mountedFolder) {
          toast.error("Mount a folder first to run /handoff.");
          return;
        }
        submitPromptText(
          [
            `Create a handoff package in markdown under /mnt/user-data/mounted/.docs/handoffs.`,
            `Requirements:`,
            `1. Create a new timestamped folder.`,
            `2. Summarize the last 10 user messages into individual markdown files.`,
            `3. Create index.md that links each summary file and provides a compact project status overview.`,
            `4. Keep content concise but implementation-useful, with clear assumptions and open items.`,
            `5. Use markdown only.`,
          ].join("\n"),
        );
        const prefill = [
          `Continue from the latest handoff package in /mnt/user-data/mounted/.docs/handoffs.`,
          `Please read index.md first, then proceed with implementation based on those summaries.`,
        ].join("\n");
        setPendingChatLaunchPayload({
          source: "handoff",
          mountedPath: mountedFolder,
          prefill,
          createdAt: Date.now(),
        });
        router.push(getNewChatHref());
        textInput.setInput("");
      }
    },
    [
      disabled,
      getNewChatHref,
      handleMountFolder,
      mountedFolder,
      router,
      runAutoresearch,
      runCompact,
      runRename,
      status,
      submitPromptText,
      textInput,
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
      const finalMessage = workflowPrefixActive
        ? { ...messageWithoutForkAttachments, text: `/workflow ${message.text}` }
        : messageWithoutForkAttachments;
      const submitOptions: InputBoxSubmitOptions = { queued: true };
      if (forkDraft) {
        submitOptions.checkpoint = forkDraft.checkpoint;
        submitOptions.forkSourceMessageId = forkDraft.sourceMessageId;
        submitOptions.forkSourceBranch = forkDraft.sourceBranch;
      }
      setWorkflowPrefixActive(false);
      setFollowups([]);
      setFollowupsHidden(false);
      setFollowupsLoading(false);
      onSubmit?.(finalMessage, submitOptions);
      if (forkDraft) {
        setForkDraft?.(null);
      }
    },
    [executeSlashCommand, forkDraft, onSubmit, setForkDraft, workflowPrefixActive],
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
      if (slashCommands.length === 0) {
        return;
      }
      const selectedIndex = slashCommands.findIndex(
        (command) => command.name === slashSelected,
      );
      if (event.key === "ArrowDown") {
        event.preventDefault();
        const next =
          slashCommands[(selectedIndex + 1) % slashCommands.length] ??
          slashCommands[0];
        if (next) setSlashSelected(next.name);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        const prev =
          slashCommands[
            (selectedIndex - 1 + slashCommands.length) % slashCommands.length
          ] ?? slashCommands[0];
        if (prev) setSlashSelected(prev.name);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        const target =
          slashCommands.find((command) => command.name === slashSelected) ??
          slashCommands[0];
        if (!target) {
          return;
        }
        void executeSlashCommand(target.name as SlashCommandName, "");
        textInput.setInput("");
      }
    },
    [
      executeSlashCommand,
      slashCommands,
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

  const hasStartedChat = useMemo(
    () =>
      thread.messages.some((m) => {
        if (m.type !== "human" && m.type !== "ai") {
          return false;
        }
        const content = (textOfMessage(m) ?? "").trim();
        return content.length > 0;
      }),
    [thread.messages],
  );
  const canStartAutoresearch =
    !Boolean(disabled) &&
    !isMock &&
    !isNewThread &&
    hasStartedChat &&
    status !== "streaming";

  const handleOpenAutoresearch = useCallback(() => {
    if (!canStartAutoresearch) {
      return;
    }
    textInput.setInput("/autoresearch ");
  }, [canStartAutoresearch, textInput]);

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
        dreamy: dreamy ?? false,
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
  }, [context.model_name, disabled, isMock, status, threadId, dreamy, lastMessageId]);

  return (
    <div ref={promptRootRef} className="relative">
      <FileMentionDropdown threadId={threadId} />
      <SlashCommandDropdown
        visible={slashMenuVisible}
        query={slashState.query}
        commands={SLASH_COMMANDS}
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
          isPlanMode &&
            "[&>[data-slot='input-group']]:border-destructive [&>[data-slot='input-group']]:shadow-[0_0_0_1px_hsl(var(--destructive)/0.45)] [&>[data-slot='input-group']]:has-[[data-slot=input-group-control]:focus-visible]:ring-destructive/30",
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
            placeholder={t.inputBox.placeholder}
            autoFocus={autoFocus}
            defaultValue={initialValue}
            onSpecialKeyDown={handleInputSpecialKeyDown}
          />
        </PromptInputBody>

        <PromptInputFooter className="flex">
          <PromptInputTools>
            <AttachmentPopup
              triggerId={attachmentMenuTriggerId}
              onAttachFiles={() => attachments.openFileDialog()}
              onMountFolder={() => void handleMountFolder()}
              isPicking={isPicking}
            />
            {dreamy && (
              <WorkflowButton
                active={workflowPrefixActive}
                onToggle={() => setWorkflowPrefixActive((v) => !v)}
              />
            )}
            {!dreamy && (
              <PrivacyAndAutoMenu
                mode={context.mode}
                autoModeEnabled={autoModeEnabled}
                maskSensitiveSearch={context.mask_sensitive_search}
                canStartAutoresearch={canStartAutoresearch}
                onTogglePlanMode={handleTogglePlanMode}
                onToggleAutoMode={handleToggleAutoMode}
                onToggleSearchPrivacy={handleToggleSearchPrivacy}
                onOpenAutoresearch={handleOpenAutoresearch}
                triggerId={privacyMenuTriggerId}
              />
            )}
            <ReasoningEffortMenu
              show={supportReasoningEffort}
              reasoningEffort={context.reasoning_effort}
              onSelect={handleReasoningEffortSelect}
              triggerId={reasoningMenuTriggerId}
            />
          </PromptInputTools>
          <PromptInputTools>
            {!dreamy && isPlanMode ? (
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
                  disabled={models.length === 0}
                >
                  <ModelSelectorName className="text-xs font-normal">
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
                className="gap-1 px-2"
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

      <MountFolderDialog
        open={mountDialogOpen}
        onOpenChange={setMountDialogOpen}
        value={mountPathInput}
        onChange={setMountPathInput}
        onConfirm={() => void handleConfirmMount()}
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

      <AutoresearchDialog
        open={autoresearchDialogOpen}
        onOpenChange={setAutoresearchDialogOpen}
        topic={autoresearchTopic}
        endpointGoal={autoresearchEndpointGoal}
        onTopicChange={setAutoresearchTopic}
        onEndpointGoalChange={setAutoresearchEndpointGoal}
        isSubmitting={autoresearchSubmitting}
        onConfirm={() => {
          void runAutoresearch(autoresearchTopic, autoresearchEndpointGoal);
          setAutoresearchDialogOpen(false);
          setAutoresearchTopic("");
          setAutoresearchEndpointGoal("");
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
