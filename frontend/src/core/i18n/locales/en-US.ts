import {
  CompassIcon,
  GraduationCapIcon,
  ImageIcon,
  MicroscopeIcon,
  PenLineIcon,
  ShapesIcon,
  VideoIcon,
} from "lucide-react";

import type { Translations } from "./types";

export const enUS: Translations = {
  // Locale meta
  locale: {
    localName: "English",
  },

  // Common
  common: {
    home: "Home",
    settings: "Settings",
    delete: "Delete",
    rename: "Rename",
    share: "Share",
    openInNewWindow: "Open in new window",
    close: "Close",
    more: "More",
    search: "Search",
    download: "Download",
    thinking: "Thinking",
    artifacts: "Directory",
    public: "Public",
    custom: "Custom",
    notAvailableInDemoMode: "Not available in demo mode",
    loading: "Loading...",
    version: "Version",
    lastUpdated: "Last updated",
    code: "Code",
    preview: "Preview",
    cancel: "Cancel",
    save: "Save",
    install: "Install",
    create: "Create",
  },

  // Welcome
  welcome: {
    greeting: "Welcome to Capybara Home!",
    description:
      "Welcome to Capybara, an open source super agent. Capybara helps you search on the web, analyze data, and generate artifacts like slides, web pages and do almost anything while you sip on coffee",
  },


  // Clipboard
  clipboard: {
    copyToClipboard: "Copy to clipboard",
    copiedToClipboard: "Copied to clipboard",
    failedToCopyToClipboard: "Failed to copy to clipboard",
    linkCopied: "Link copied to clipboard",
  },

  // Chat UI (chat interface improvement plan)
  chatUI: {
    attachmentPopup: {
      tooltip: "Attach files or mount a folder",
      attachFiles: "Attach Files",
      mountFolder: "Mount Folder",
      picking: "Picking…",
    },
    mountFolder: {
      mounted: "Mounted",
      change: "Change",
      unmount: "Unmount",
      unmounted: "Unmounted folder",
      tooltip: "Mounted folder — click to change",
      none: "No folder mounted",
    },
    fileMention: {
      placeholder: "Search files…",
      noFilesFound: "No files found",
      noFolderMounted: "Mount a folder to reference files",
    },
    capybaraRunner: {
      thinking: "Capybara is thinking",
      workingOn: "Capybara is working on",
      babyThinking: "Baby Capy is working on",
      babyWorkingOn: "Baby Capy is working on",
    },
  },

  // Input Box
  inputBox: {
    placeholder: "How can I assist you today?",
    addAttachments: "Add attachments",

    attachDocuments: "Attach documents",
    noDocumentsAttached: "No documents attached",
    unnamedDocument: "Untitled document",
    documentSingular: "document attached",
    documentPlural: "documents attached",
    comingSoon: "Coming soon",

    mode: "Mode",
    fastMode: "Fast",
    fastModeDescription:
      "Reasoning, planning and executing, get more accurate results, may take more time",
    workMode: "Work",
    workModeDescription:
      "Direct execution. Simple requests run immediately; complex tasks create a plan and execute phases automatically.",
    planMode: "Plan",
    planModeBadge: "Plan Mode",
    planModeDescription:
      "Plan first, then execute after approval. Generates a structured execution plan with editable phases before running.",
    reasoningEffort: "Reasoning Effort",
    reasoningEffortMinimal: "Minimal",
    reasoningEffortMinimalDescription: "Retrieval + Direct Output",
    reasoningEffortLow: "Low",
    reasoningEffortLowDescription: "Simple Logic Check + Shallow Deduction",
    reasoningEffortMedium: "Medium",
    reasoningEffortMediumDescription:
      "Multi-layer Logic Analysis + Basic Verification",
    reasoningEffortHigh: "High",
    reasoningEffortHighDescription:
      "Full-dimensional Logic Deduction + Multi-path Verification + Backward Check",
    searchModels: "Search models...",
    surpriseMe: "Surprise",
    surpriseMePrompt: "Surprise me",
    followupLoading: "Generating follow-up questions...",
    followupConfirmTitle: "Send suggestion?",
    followupConfirmDescription:
      "You already have text in the input. Choose how to send it.",
    followupConfirmAppend: "Append & send",
    followupConfirmReplace: "Replace & send",
    suggestions: [
      {
        suggestion: "Write",
        prompt: "Write a blog post about the latest trends on [topic]",
        icon: PenLineIcon,
      },
      {
        suggestion: "Research",
        prompt:
          "Conduct a deep dive research on [topic], and summarize the findings.",
        icon: MicroscopeIcon,
      },
      {
        suggestion: "Collect",
        prompt: "Collect data from [source] and create a report.",
        icon: ShapesIcon,
      },
      {
        suggestion: "Learn",
        prompt: "Learn about [topic] and create a tutorial.",
        icon: GraduationCapIcon,
      },
    ],
    suggestionsCreate: [
      {
        suggestion: "Webpage",
        prompt: "Create a webpage about [topic]",
        icon: CompassIcon,
      },
      {
        suggestion: "Image",
        prompt: "Create an image about [topic]",
        icon: ImageIcon,
      },
      {
        suggestion: "Video",
        prompt: "Create a video about [topic]",
        icon: VideoIcon,
      },
    ],

  },

  // Sidebar
  sidebar: {
    newChat: "New chat",
    chats: "Chats",
    recentChats: "Recent chats",
    demoChats: "Demo chats",
    agents: "Agents",
    pipelines: "Scheduled Pipeline",
    approvals: "Approvals",
    vault: "Knowledge Vault",
    integrations: "Integrations",
    dreamy: "Dreamy",
  },

  // Agents
  agents: {
    title: "Agents",
    description:
      "Create and manage custom agents with specialized prompts and capabilities.",
    newAgent: "New Agent",
    emptyTitle: "No custom agents yet",
    emptyDescription:
      "Create your first custom agent with a specialized system prompt.",
    chat: "Chat",
    delete: "Delete",
    deleteConfirm:
      "Are you sure you want to delete this agent? This action cannot be undone.",
    deleteSuccess: "Agent deleted",
    newChat: "New chat",
    createPageTitle: "Design your Agent",
    createPageSubtitle:
      "Describe the agent you want — I'll help you create it through conversation.",
    nameStepTitle: "Name your new Agent",
    nameStepHint:
      "Letters, digits, and hyphens only — stored lowercase (e.g. code-reviewer)",
    nameStepPlaceholder: "e.g. code-reviewer",
    nameStepContinue: "Continue",
    nameStepInvalidError:
      "Invalid name — use only letters, digits, and hyphens",
    nameStepAlreadyExistsError: "An agent with this name already exists",
    nameStepCheckError: "Could not verify name availability — please try again",
    nameStepBootstrapMessage:
      "The new custom agent name is {name}. Let's bootstrap it's **SOUL**.",
    agentCreated: "Agent created!",
    startChatting: "Start chatting",
    backToGallery: "Back to Gallery",
  },

  // Breadcrumb
  breadcrumb: {
    workspace: "Workspace",
    chats: "Chats",
    pipelines: "Scheduled Pipeline",
    approvals: "Approvals",
    vault: "Knowledge Vault",
    integrations: "Integrations",
  },

  // Workspace
  workspace: {
    settingsAndMore: "Settings",
  },

  // Conversation
  conversation: {
    noMessages: "No messages yet",
    startConversation: "Start a conversation to see messages here",
  },

  // Chats
  chats: {
    searchChats: "Search chats",
    deleteAllChats: "Delete all chats",
    deleteAllChatsConfirm:
      "Are you sure you want to delete all chats? This action cannot be undone.",
    deleteAllChatsSuccess: "All chats deleted",
    deleteAllChatsFailed: "Failed to delete all chats",
    deleteAllChatsPartialFailure: (count: number) =>
      `${count} chat${count === 1 ? "" : "s"} could not be deleted`,
    deleteChatConfirm:
      "Are you sure you want to delete this chat? This action cannot be undone.",
    deleteChatSuccess: "Chat deleted",
    deleteChatFailed: "Failed to delete chat",
  },

  // Page titles (document title)
  pages: {
    appName: "Capybara Home",
    chats: "Chats",
    newChat: "New chat",
    untitled: "Untitled",
    pipelines: "Scheduled Pipeline",
    approvals: "Approvals",
    vault: "Knowledge Vault",
    integrations: "Integrations",
  },

  // Tool calls
  toolCalls: {
    moreSteps: (count: number) => `${count} more step${count === 1 ? "" : "s"}`,
    lessSteps: "Less steps",
    executeCommand: "Execute command",
    presentFiles: "Present files",
    needYourHelp: "Need your help",
    useTool: (toolName: string) => `Use "${toolName}" tool`,
    searchFor: (query: string) => `Search for "${query}"`,
    searchForRelatedInfo: "Search for related information",
    searchForRelatedImages: "Search for related images",
    searchForRelatedImagesFor: (query: string) =>
      `Search for related images for "${query}"`,
    searchOnWebFor: (query: string) => `Search on the web for "${query}"`,
    viewWebPage: "View web page",
    listFolder: "List folder",
    readFile: "Read file",
    writeFile: "Write file",
    clickToViewContent: "Click to view file content",
    writeTodos: "Update to-do list",
    skillInstallTooltip: "Install skill and make it available to Capybara Home",
  },

  // Subtasks
  uploads: {
    uploading: "Uploading...",
    uploadingFiles: "Uploading files, please wait...",
  },

  subtasks: {
    subtask: "Subtask",
    executing: (count: number) =>
      `Executing ${count === 1 ? "" : count + " "}subtask${count === 1 ? "" : "s in parallel"}`,
    in_progress: "Running subtask",
    completed: "Subtask completed",
    failed: "Subtask failed",
  },

  // Settings
  settings: {
    title: "Settings",
    description: "Adjust how Capybara Home looks and behaves for you.",
    sections: {
      appearance: "Appearance",
      memory: "Memory",
      pipelineCleanup: "Pipeline Cleanup",
      autoresearchCleanup: "Autoresearch Cleanup",
      tools: "Tools",
      notification: "Notification",
      llm: "LLM Providers",
      embedding: "Embedding Models",
      browser: "Browser Tool",
      comfyui: "ComfyUI",
      about: "About",
    },

    memory: {
      title: "Memory",
      description:
        "Capybara Home automatically learns from your conversations in the background. These memories help Capybara Home understand you better and deliver a more personalized experience.",
      empty: "No memory data to display.",
      rawJson: "Raw JSON",
      markdown: {
        overview: "Overview",
        userContext: "User context",
        work: "Work",
        personal: "Personal",
        topOfMind: "Top of mind",
        historyBackground: "History",
        recentMonths: "Recent months",
        earlierContext: "Earlier context",
        longTermBackground: "Long-term background",
        updatedAt: "Updated at",
        facts: "Facts",
        empty: "(empty)",
        table: {
          category: "Category",
          confidence: "Confidence",
          confidenceLevel: {
            veryHigh: "Very high",
            high: "High",
            normal: "Normal",
            unknown: "Unknown",
          },
          content: "Content",
          source: "Source",
          createdAt: "CreatedAt",
          view: "View",
        },
      },
    },
    appearance: {
      themeTitle: "Theme",
      themeDescription:
        "Choose how the interface follows your device or stays fixed.",
      system: "System",
      light: "Light",
      dark: "Dark",
      systemDescription: "Match the operating system preference automatically.",
      lightDescription: "Bright palette with higher contrast for daytime.",
      darkDescription: "Dim palette that reduces glare for focus.",
      languageTitle: "Language",
      languageDescription: "Switch between languages.",
    },
    tools: {
      title: "Tools",
      description: "Manage MCP servers and built-in community tools.",
      mcpServers: "MCP Servers",
      builtinTools: "Built-in Tools",
      addServer: "Add Server",
      editServer: "Edit Server",
      deleteServer: "Remove",
      deleteServerConfirm: "Are you sure you want to remove this MCP server?",
      testConnection: "Test Connection",
      testingConnection: "Testing…",
      previewTools: "Preview Tools",
      noToolsFound: "No tools found on this server.",
      connectionError: "Connection failed",
      addServerSuccess: "Server added",
      serverName: "Server name",
      serverNamePlaceholder: "e.g. github",
      transportType: "Transport",
      command: "Command",
      commandPlaceholder: "e.g. npx",
      arguments: "Arguments",
      argumentsPlaceholder: "One argument per line",
      envVars: "Environment variables",
      envVarsPlaceholder: "KEY=value, one per line",
      serverUrl: "Server URL",
      serverUrlPlaceholder: "https://…",
      serverDescription: "Description",
      descriptionPlaceholder: "What does this server provide?",
      excludeTools: "Excluded tools",
      excludeToolsDescription: "Uncheck tools to hide them from the agent.",
      toolsDiscovered: (count: number) => `${count} tool${count === 1 ? "" : "s"} found`,
      sourceBuiltin: "Built-in",
      sourceConfig: "Config",
    },
    skills: {
      title: "Capabilities",
      description: "Manage the configuration and enabled status of individual capabilities.",
      createSkill: "Create Skill",
      emptyTitle: "No skills yet",
      emptyDescription: "Create a skill to extend the agent's capabilities.",
      emptyButton: "Create Skill",
    },

    notification: {
      title: "Notification",
      description:
        "Capybara Home only sends a completion notification when the window is not active. This is especially useful for long-running tasks so you can switch to other work and get notified when done.",
      requestPermission: "Request notification permission",
      deniedHint:
        "Notification permission was denied. You can enable it in your browser's site settings to receive completion alerts.",
      testButton: "Send test notification",
      testTitle: "Capybara Home",
      testBody: "This is a test notification.",
      notSupported: "Your browser does not support notifications.",
      disableNotification: "Disable notification",
    },
    llm: {
      title: "LLM Providers",
      description: "Add and manage OpenAI-compatible LLM endpoints (Ollama, LM Studio, or custom).",
      providerType: "Provider Type",
      providerOllama: "Ollama",
      providerLmStudio: "LM Studio",
      providerCustom: "Custom",
      displayName: "Display Name",
      displayNamePlaceholder: "e.g. My Local LLM",
      baseUrl: "Base URL",
      baseUrlPlaceholder: "http://localhost:11434/v1",
      apiKey: "API Key (optional)",
      apiKeyPlaceholder: "sk-...",
      testConnection: "Test Connection",
      testing: "Testing connection...",
      connectionFailed: "Connection failed",
      connectionSuccess: "Connection successful",
      discoveredModels: (count: number) => `${count} model${count === 1 ? "" : "s"} found`,
      addProvider: "Add Provider",
      saveProvider: "Save Provider",
      noEndpoints: "No LLM endpoints configured yet. Add one above.",
      configuredEndpoints: "Configured Endpoints",
      deleteConfirm: "Are you sure you want to remove this endpoint?",
      endpointEnabled: "Enabled",
      endpointDisabled: "Disabled",
    },
    embedding: {
      title: "Embedding Models",
      description: "Add and manage OpenAI-compatible embedding endpoints used by the knowledge graph (Ollama, LM Studio, or custom).",
      knowledgeGraphHint: "These endpoints feed the knowledge graph vector index. The first enabled embedding endpoint is used.",
    },
    browser: {
      title: "Browser Tool",
      description: "Configure browser automation via Playwright MCP.",
      quickAddDescription: "Add a Playwright MCP server for browser automation capabilities (web scraping, form filling, etc.).",
      quickAddButton: "Add Playwright MCP",
      quickAddSuccess: "Playwright MCP server added successfully!",
      quickAddError: "Failed to add Playwright MCP server",
      manualTitle: "Manual Configuration",
      manualDescription: "For SSE/HTTP Playwright servers, enter the URL below.",
      url: "Server URL",
      urlPlaceholder: "https://...",
      testConnection: "Test Connection",
      testing: "Testing...",
      connectionFailed: "Connection failed",
      connectionSuccess: "Server is reachable",
      addAsMcp: "Add as MCP Server",
    },
    comfyui: {
      title: "ComfyUI",
      description: "Connect to your local ComfyUI instance for image generation.",
      baseUrl: "ComfyUI Base URL",
      baseUrlPlaceholder: "http://127.0.0.1:8188",
      testConnection: "Test Connection",
      testing: "Testing connection...",
      connectionFailed: "Connection failed",
      connectionSuccess: "ComfyUI is reachable",
      enableTool: "Enable ComfyUI Generate Tool",
      enableToolDescription: "When enabled, the agent can use ComfyUI to generate images and videos.",
      toolEnabled: "ComfyUI generate tool is enabled",
      toolDisabled: "ComfyUI generate tool is disabled",
    },
    acknowledge: {
      emptyTitle: "Acknowledgements",
      emptyDescription: "Credits and acknowledgements will show here.",
    },
  },
  steering: {
    title: "Steer Next Turn",
    description: "Add one steering message that will be applied to the next model turn.",
    inputPlaceholder: "e.g. Be concise and focus on tradeoffs.",
    apply: "Apply",
    applying: "Applying...",
    steerNext: "steer next",
    steering: "steering...",
  },
  queue: {
    title: "Queued Messages",
    queuedCount: (count: number) => `${count} queued`,
    steer: "Steer",
    dismiss: "Dismiss",
    pending: "Steering...",
    retrying: "Retrying...",
    failedRetrying: "Steering failed. Will retry after queue progress.",
    emptyMessageFallback: "(empty message)",
  },

  dreamy: {
    directory: {
      noFilesYet: "No files yet",
      noFilesDescription: "Uploaded files and files created during the workflow will appear here.",
      noFilesInFolder: "No files in folder",
      mountedFolder: "Mounted Folder",
      filesSection: "Files",
    },
    filePreview: {
      previewUnavailable: "Preview unavailable",
      liveRows: (count: number) => `live · ${count} rows`,
    },
  },

  chatActivity: {
    title: "Activity Timeline",
    noActivity: "No activity yet.",
    trimmedNotice: (count: number) => `Showing last ${count} events. Earlier history trimmed.`,
    runStatus: {
      run: "run",
      idle: "idle",
    },
  },
};
