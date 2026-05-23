import type { AgentThreadContext } from "../threads";
import { DEFAULT_TOOL_ICON_BY_TOOL } from "../tools/presentation";

export const DEFAULT_LOCAL_SETTINGS: LocalSettings = {
  notification: {
    enabled: true,
  },
  context: {
    model_name: undefined,
    mode: undefined,
    reasoning_effort: undefined,
  },
  layout: {
    sidebar_collapsed: false,
  },
  toolPresentation: {
    iconByTool: DEFAULT_TOOL_ICON_BY_TOOL,
  },
};

const LOCAL_SETTINGS_KEY = "capybara-home.local-settings";
const LEGACY_REMOVED_TOOL_KEYS = new Set(["tavily_search_results_json"]);

export interface LocalSettings {
  notification: {
    enabled: boolean;
  };
  context: Omit<
    AgentThreadContext,
    "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
  > & {
    mode: "work" | "plan" | undefined;
    reasoning_effort?: "minimal" | "low" | "medium" | "high";
  };
  layout: {
    sidebar_collapsed: boolean;
  };
  toolPresentation: {
    iconByTool: Record<string, string>;
  };
}

function sanitizeToolIconMap(iconByTool: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(iconByTool).filter(([toolName]) => !LEGACY_REMOVED_TOOL_KEYS.has(toolName)),
  );
}

export function getLocalSettings(): LocalSettings {
  if (typeof window === "undefined") {
    return DEFAULT_LOCAL_SETTINGS;
  }
  const json = localStorage.getItem(LOCAL_SETTINGS_KEY);
  try {
    if (json) {
      const settings = JSON.parse(json);
      const mergedSettings = {
        ...DEFAULT_LOCAL_SETTINGS,
        context: {
          ...DEFAULT_LOCAL_SETTINGS.context,
          ...settings.context,
        },
        layout: {
          ...DEFAULT_LOCAL_SETTINGS.layout,
          ...settings.layout,
        },
        toolPresentation: {
          ...DEFAULT_LOCAL_SETTINGS.toolPresentation,
          ...settings.toolPresentation,
          iconByTool: sanitizeToolIconMap({
            ...DEFAULT_LOCAL_SETTINGS.toolPresentation.iconByTool,
            ...(settings.toolPresentation?.iconByTool ?? {}),
          }),
        },
        notification: {
          ...DEFAULT_LOCAL_SETTINGS.notification,
          ...settings.notification,
        },
      };
      return mergedSettings;
    }
  } catch {}
  return DEFAULT_LOCAL_SETTINGS;
}

export function saveLocalSettings(settings: LocalSettings) {
  const nextSettings: LocalSettings = {
    ...settings,
    toolPresentation: {
      ...settings.toolPresentation,
      iconByTool: sanitizeToolIconMap(settings.toolPresentation.iconByTool),
    },
  };
  localStorage.setItem(LOCAL_SETTINGS_KEY, JSON.stringify(nextSettings));
}
