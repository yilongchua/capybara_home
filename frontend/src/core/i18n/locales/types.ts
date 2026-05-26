import type { LucideIcon } from "lucide-react";

export interface Translations {
  // Locale meta
  locale: {
    localName: string;
  };

  // Common
  common: {
    home: string;
    settings: string;
    delete: string;
    rename: string;
    share: string;
    openInNewWindow: string;
    close: string;
    more: string;
    search: string;
    download: string;
    thinking: string;
    artifacts: string;
    public: string;
    custom: string;
    notAvailableInDemoMode: string;
    loading: string;
    version: string;
    lastUpdated: string;
    code: string;
    preview: string;
    cancel: string;
    save: string;
    install: string;
    create: string;
  };

  // Welcome
  welcome: {
    greeting: string;
    description: string;
  };


  // Clipboard
  clipboard: {
    copyToClipboard: string;
    copiedToClipboard: string;
    failedToCopyToClipboard: string;
    linkCopied: string;
  };

  // Chat UI (additions for the chat interface improvement plan)
  chatUI: {
    attachmentPopup: {
      tooltip: string;
      attachFiles: string;
      mountFolder: string;
      picking: string;
    };
    mountFolder: {
      mounted: string;
      change: string;
      unmount: string;
      unmounted: string;
      tooltip: string;
      none: string;
    };
    fileMention: {
      placeholder: string;
      noFilesFound: string;
      noFolderMounted: string;
    };
    capyHomeRunner: {
      thinking: string;
      workingOn: string;
      babyThinking: string;
      babyWorkingOn: string;
    };
  };

  // Input Box
  inputBox: {
    placeholder: string;
    addAttachments: string;

    attachDocuments: string;
    noDocumentsAttached: string;
    unnamedDocument: string;
    documentSingular: string;
    documentPlural: string;
    comingSoon: string;

    mode: string;
    fastMode: string;
    fastModeDescription: string;


    workMode: string;
    workModeDescription: string;
    planMode: string;
    planModeBadge: string;
    planModeDescription: string;
    reasoningEffort: string;
    reasoningEffortMinimal: string;
    reasoningEffortMinimalDescription: string;
    reasoningEffortLow: string;
    reasoningEffortLowDescription: string;
    reasoningEffortMedium: string;
    reasoningEffortMediumDescription: string;
    reasoningEffortHigh: string;
    reasoningEffortHighDescription: string;
    searchModels: string;
    surpriseMe: string;
    surpriseMePrompt: string;
    followupLoading: string;
    followupConfirmTitle: string;
    followupConfirmDescription: string;
    followupConfirmAppend: string;
    followupConfirmReplace: string;
    suggestions: {
      suggestion: string;
      prompt: string;
      icon: LucideIcon;
    }[];
    suggestionsCreate: (
      | {
          suggestion: string;
          prompt: string;
          icon: LucideIcon;
        }
      | {
          type: "separator";
        }
    )[];
  };

  // Sidebar
  sidebar: {
    recentChats: string;
    newChat: string;
    chats: string;
    demoChats: string;
    agents: string;
    pipelines: string;
    vault: string;
  };

  // Agents
  agents: {
    title: string;
    description: string;
    newAgent: string;
    emptyTitle: string;
    emptyDescription: string;
    chat: string;
    delete: string;
    deleteConfirm: string;
    deleteSuccess: string;
    newChat: string;
    createPageTitle: string;
    createPageSubtitle: string;
    nameStepTitle: string;
    nameStepHint: string;
    nameStepPlaceholder: string;
    nameStepContinue: string;
    nameStepInvalidError: string;
    nameStepAlreadyExistsError: string;
    nameStepCheckError: string;
    nameStepBootstrapMessage: string;
    agentCreated: string;
    startChatting: string;
    backToGallery: string;
  };

  // Breadcrumb
  breadcrumb: {
    workspace: string;
    chats: string;
    pipelines: string;
    vault: string;
  };

  // Workspace
  workspace: {
    settingsAndMore: string;
  };

  // Conversation
  conversation: {
    noMessages: string;
    startConversation: string;
  };

  // Chats
  chats: {
    searchChats: string;
    deleteAllChats: string;
    deleteAllChatsConfirm: string;
    deleteAllChatsSuccess: string;
    deleteAllChatsFailed: string;
    deleteAllChatsPartialFailure: (count: number) => string;
    deleteChatConfirm: string;
    deleteChatSuccess: string;
    deleteChatFailed: string;
  };

  // Page titles (document title)
  pages: {
    appName: string;
    chats: string;
    newChat: string;
    untitled: string;
    pipelines: string;
    vault: string;
  };

  // Tool calls
  toolCalls: {
    moreSteps: (count: number) => string;
    lessSteps: string;
    executeCommand: string;
    presentFiles: string;
    needYourHelp: string;
    useTool: (toolName: string) => string;
    searchForRelatedInfo: string;
    searchForRelatedImages: string;
    searchFor: (query: string) => string;
    searchForRelatedImagesFor: (query: string) => string;
    searchOnWebFor: (query: string) => string;
    viewWebPage: string;
    listFolder: string;
    readFile: string;
    writeFile: string;
    clickToViewContent: string;
    writeTodos: string;
    skillInstallTooltip: string;
  };

  // Uploads
  uploads: {
    uploading: string;
    uploadingFiles: string;
  };

  // Subtasks
  subtasks: {
    subtask: string;
    executing: (count: number) => string;
    in_progress: string;
    completed: string;
    failed: string;
  };

  // Settings
  settings: {
    title: string;
    description: string;
    sections: {
      appearance: string;
      memory: string;
      pipelineCleanup: string;
      autoresearchCleanup: string;
      tools: string;
      notification: string;
      llm: string;
      embedding: string;
      browser: string;
      browserExtension: string;
      comfyui: string;
      about: string;
    };

    memory: {
      title: string;
      description: string;
      empty: string;
      rawJson: string;
      markdown: {
        overview: string;
        userContext: string;
        work: string;
        personal: string;
        topOfMind: string;
        historyBackground: string;
        recentMonths: string;
        earlierContext: string;
        longTermBackground: string;
        updatedAt: string;
        facts: string;
        empty: string;
        table: {
          category: string;
          confidence: string;
          confidenceLevel: {
            veryHigh: string;
            high: string;
            normal: string;
            unknown: string;
          };
          content: string;
          source: string;
          createdAt: string;
          view: string;
        };
      };
    };
    appearance: {
      themeTitle: string;
      themeDescription: string;
      system: string;
      light: string;
      dark: string;
      systemDescription: string;
      lightDescription: string;
      darkDescription: string;
      capyhome: string;
      capyHomeDescription: string;
      languageTitle: string;
      languageDescription: string;
    };
    tools: {
      title: string;
      description: string;
      mcpServers: string;
      builtinTools: string;
      addServer: string;
      editServer: string;
      deleteServer: string;
      deleteServerConfirm: string;
      testConnection: string;
      testingConnection: string;
      previewTools: string;
      noToolsFound: string;
      connectionError: string;
      addServerSuccess: string;
      serverName: string;
      serverNamePlaceholder: string;
      transportType: string;
      command: string;
      commandPlaceholder: string;
      arguments: string;
      argumentsPlaceholder: string;
      envVars: string;
      envVarsPlaceholder: string;
      serverUrl: string;
      serverUrlPlaceholder: string;
      serverDescription: string;
      descriptionPlaceholder: string;
      excludeTools: string;
      excludeToolsDescription: string;
      toolsDiscovered: (count: number) => string;
      sourceBuiltin: string;
      sourceConfig: string;
    };
    skills: {
      title: string;
      description: string;
      createSkill: string;
      emptyTitle: string;
      emptyDescription: string;
      emptyButton: string;
    };

    notification: {
      title: string;
      description: string;
      requestPermission: string;
      deniedHint: string;
      testButton: string;
      testTitle: string;
      testBody: string;
      notSupported: string;
      disableNotification: string;
    };
    llm: {
      title: string;
      description: string;
      providerType: string;
      providerOllama: string;
      providerLmStudio: string;
      providerCustom: string;
      displayName: string;
      displayNamePlaceholder: string;
      baseUrl: string;
      baseUrlPlaceholder: string;
      apiKey: string;
      apiKeyPlaceholder: string;
      testConnection: string;
      testing: string;
      connectionFailed: string;
      connectionSuccess: string;
      discoveredModels: (count: number) => string;
      addProvider: string;
      saveProvider: string;
      noEndpoints: string;
      configuredEndpoints: string;
      deleteConfirm: string;
      endpointEnabled: string;
      endpointDisabled: string;
    };
    embedding: {
      title: string;
      description: string;
      knowledgeGraphHint: string;
    };
    browser: {
      title: string;
      description: string;
      quickAddDescription: string;
      quickAddButton: string;
      quickAddSuccess: string;
      quickAddError: string;
      manualTitle: string;
      manualDescription: string;
      url: string;
      urlPlaceholder: string;
      testConnection: string;
      testing: string;
      connectionFailed: string;
      connectionSuccess: string;
      addAsMcp: string;
    };
    browserExtension: {
      title: string;
      description: string;
      aboutTitle: string;
      aboutDescription: string;
      autoClipTitle: string;
      autoClipDefaultBadge: string;
      autoClipDescription: string;
      autoClipDwellNote: string;
      autoClipBlocklistNote: string;
      autoClipDedupNote: string;
      autoClipOptOutNote: string;
      queueSignTitle: string;
      queueSignBody: string;
      installTitle: string;
      step1Title: string;
      step1Description: string;
      step2Title: string;
      step2Description: string;
      step3Title: string;
      step3Description: string;
      step4Title: string;
      step4Description: string;
      copyPath: string;
      copyUrl: string;
      copied: string;
      usageTitle: string;
      usageClick: string;
      usageRightClick: string;
      usageShortcut: string;
      shortcutMac: string;
      shortcutWin: string;
      shortcutOr: string;
      troubleshootingTitle: string;
      troubleshootingBody: string;
    };
    comfyui: {
      title: string;
      description: string;
      baseUrl: string;
      baseUrlPlaceholder: string;
      testConnection: string;
      testing: string;
      connectionFailed: string;
      connectionSuccess: string;
      enableTool: string;
      enableToolDescription: string;
      toolEnabled: string;
      toolDisabled: string;
    };
    acknowledge: {
      emptyTitle: string;
      emptyDescription: string;
    };
  };

  // Steering dialog
  steering: {
    title: string;
    description: string;
    inputPlaceholder: string;
    apply: string;
    applying: string;
    steerNext: string;
    steering: string;
  };

  queue: {
    title: string;
    queuedCount: (count: number) => string;
    steer: string;
    dismiss: string;
    pending: string;
    retrying: string;
    failedRetrying: string;
    emptyMessageFallback: string;
  };

  // Chat activity panel
  chatActivity: {
    title: string;
    noActivity: string;
    trimmedNotice: (count: number) => string;
    runStatus: {
      run: string;
      idle: string;
    };
  };
}
