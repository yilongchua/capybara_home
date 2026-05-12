"use client";

import {
  BotIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  GlobeIcon,
  HammerIcon,
  PlusIcon as PlusSmallIcon,
  PlusIcon,
  TerminalIcon,
  Trash2Icon,
  DatabaseIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemFooter,
  ItemTitle,
} from "@/components/ui/item";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useCommunityTools, useToggleCommunityTool } from "@/core/community-tools";
import type { CommunityTool } from "@/core/community-tools";
import { useI18n } from "@/core/i18n/hooks";
import {
  useAddMCPServer,
  useEnableMCPServer,
  useMCPConfig,
  usePreviewMCPServer,
  useRemoveMCPServer,
  useUpdateToolExclusions,
} from "@/core/mcp/hooks";
import type { MCPPreviewResult, MCPServerConfig } from "@/core/mcp/types";
import { useLocalSettings } from "@/core/settings";
import { DEFAULT_TOOL_ICON_BY_TOOL, TOOL_ICON_OPTIONS, type ToolIconKey } from "@/core/tools/presentation";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

// ─── Top-level page ───────────────────────────────────────────────────────────

export function ToolSettingsPage() {
  const { t } = useI18n();
  return (
    <SettingsSection
      title={t.settings.tools.title}
      description={t.settings.tools.description}
    >
      <ToolIconMappingPanel />
      <div className="space-y-6">
        <div className="space-y-3">
          <h3 className="text-sm font-medium">{t.settings.tools.mcpServers}</h3>
          <MCPServersPanel />
        </div>
        <div className="space-y-3">
          <h3 className="text-sm font-medium">{t.settings.tools.builtinTools}</h3>
          <CommunityToolsPanel />
        </div>
      </div>
    </SettingsSection>
  );
}

function iconLabel(key: ToolIconKey) {
  if (key === "web") return "Web";
  if (key === "vault") return "Knowledge Vault";
  if (key === "assistant") return "Assistant";
  if (key === "terminal") return "Terminal";
  return "Generic Tool";
}

function buildCandidateUrls(input: string): string[] {
  const trimmed = input.trim().replace(/\/+$/, "");
  if (!trimmed) return [];
  if (trimmed.endsWith("/mcp")) return [trimmed];
  return [trimmed, `${trimmed}/mcp`];
}

function renderIconPreview(key: ToolIconKey) {
  if (key === "web") return <GlobeIcon className="size-3.5" />;
  if (key === "vault") return <DatabaseIcon className="size-3.5" />;
  if (key === "assistant") return <BotIcon className="size-3.5" />;
  if (key === "terminal") return <TerminalIcon className="size-3.5" />;
  return <HammerIcon className="size-3.5" />;
}

function ToolIconMappingPanel() {
  const [settings, setSettings] = useLocalSettings();
  const iconByTool = settings.toolPresentation.iconByTool;
  const entries = Object.entries(iconByTool).sort(([a], [b]) => a.localeCompare(b));

  const updateToolIcon = (toolName: string, icon: ToolIconKey) => {
    const key = toolName.trim().toLowerCase();
    if (!key) return;
    setSettings("toolPresentation", {
      iconByTool: {
        ...iconByTool,
        [key]: icon,
      },
    });
  };

  const renameTool = (prevToolName: string, nextToolName: string) => {
    const nextKey = nextToolName.trim().toLowerCase();
    if (!nextKey) return;
    const prevValue = iconByTool[prevToolName] as ToolIconKey | undefined;
    const nextMap = { ...iconByTool };
    delete nextMap[prevToolName];
    nextMap[nextKey] = prevValue ?? "tool";
    setSettings("toolPresentation", { iconByTool: nextMap });
  };

  const removeTool = (toolName: string) => {
    const nextMap = { ...iconByTool };
    delete nextMap[toolName];
    setSettings("toolPresentation", { iconByTool: nextMap });
  };

  const addTool = () => {
    const base = "new_tool";
    let candidate = base;
    let idx = 1;
    while (iconByTool[candidate]) {
      idx += 1;
      candidate = `${base}_${idx}`;
    }
    setSettings("toolPresentation", {
      iconByTool: {
        ...iconByTool,
        [candidate]: "tool",
      },
    });
  };

  const resetDefaults = () => {
    setSettings("toolPresentation", {
      iconByTool: DEFAULT_TOOL_ICON_BY_TOOL,
    });
  };

  return (
    <div className="mb-4 rounded-lg border p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium">Tool Icon Mapping</div>
          <div className="text-muted-foreground text-xs">
            Configure which icon each tool uses in Activity Timeline and task cards.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={resetDefaults}>
            Reset
          </Button>
          <Button size="sm" variant="outline" onClick={addTool}>
            <PlusSmallIcon className="size-3.5" />
            Add
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {entries.map(([toolName, icon]) => {
          const iconKey = TOOL_ICON_OPTIONS.includes(icon as ToolIconKey)
            ? (icon as ToolIconKey)
            : "tool";
          return (
            <div
              key={toolName}
              className="bg-background flex items-center gap-2 rounded-md border px-2 py-2"
            >
              <input
                className="border-input bg-background focus-visible:ring-ring min-w-0 flex-1 rounded-md border px-2 py-1.5 text-xs focus-visible:ring-1 focus-visible:outline-none"
                value={toolName}
                onChange={(e) => renameTool(toolName, e.target.value)}
                placeholder="tool_name"
              />
              <Select
                value={iconKey}
                onValueChange={(value) => updateToolIcon(toolName, value as ToolIconKey)}
              >
                <SelectTrigger className="w-[180px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TOOL_ICON_OPTIONS.map((option) => (
                    <SelectItem key={option} value={option}>
                      <span className="inline-flex items-center gap-2 text-xs">
                        {renderIconPreview(option)}
                        {iconLabel(option)}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="text-muted-foreground inline-flex w-7 justify-center">
                {renderIconPreview(iconKey)}
              </div>
              <Button
                size="icon-sm"
                variant="ghost"
                className="text-destructive"
                onClick={() => removeTool(toolName)}
                aria-label={`Remove ${toolName}`}
              >
                <Trash2Icon className="size-3.5" />
              </Button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── MCP Servers panel ────────────────────────────────────────────────────────

function MCPServersPanel() {
  const { t } = useI18n();
  const { config, isLoading, error } = useMCPConfig();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<
    { name: string; config: MCPServerConfig } | undefined
  >(undefined);

  function openAddDialog() {
    setEditingServer(undefined);
    setDialogOpen(true);
  }

  function openEditDialog(name: string, cfg: MCPServerConfig) {
    setEditingServer({ name, config: cfg });
    setDialogOpen(true);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <Button
          size="sm"
          variant="outline"
          disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
          onClick={openAddDialog}
        >
          <PlusIcon className="size-4" />
          {t.settings.tools.addServer}
        </Button>
      </div>

      {isLoading && (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      )}
      {error && <div className="text-destructive text-sm">{error.message}</div>}
      {config &&
        Object.entries(config.mcp_servers).map(([name, cfg]) => (
          <MCPServerCard
            key={name}
            name={name}
            config={cfg}
            onEdit={() => openEditDialog(name, cfg)}
          />
        ))}

      <AddMCPServerDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        initial={editingServer}
      />
    </div>
  );
}

// ─── MCP server card ──────────────────────────────────────────────────────────

function MCPServerCard({
  name,
  config,
  onEdit,
}: {
  name: string;
  config: MCPServerConfig;
  onEdit: () => void;
}) {
  const { t } = useI18n();
  const { mutate: enableServer } = useEnableMCPServer();
  const { mutate: removeServer } = useRemoveMCPServer();
  const { mutate: updateExclusions } = useUpdateToolExclusions();
  const { mutateAsync: preview } = usePreviewMCPServer();

  const [expanded, setExpanded] = useState(false);
  const [previewResult, setPreviewResult] = useState<
    MCPPreviewResult | undefined
  >(undefined);
  const [previewing, setPreviewing] = useState(false);

  const isStatic = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
  const excluded = config.excluded_tools ?? [];

  async function handleExpand() {
    const next = !expanded;
    setExpanded(next);
    if (next && !previewResult) {
      setPreviewing(true);
      try {
        const result = await preview({
          type: config.type,
          command: config.command,
          args: config.args,
          env: config.env,
          url: config.url,
          headers: config.headers,
          description: config.description,
        });
        setPreviewResult(result);
      } finally {
        setPreviewing(false);
      }
    }
  }

  function handleToolToggle(toolName: string, checked: boolean) {
    const next = checked
      ? excluded.filter((t) => t !== toolName)
      : [...excluded, toolName];
    updateExclusions({ serverName: name, excludedTools: next });
  }

  return (
    <Item className="w-full flex-col" variant="outline">
      <div className="flex w-full items-center gap-4">
        <ItemContent>
          <ItemTitle>{name}</ItemTitle>
          <ItemDescription className="line-clamp-4">
            {config.description}
          </ItemDescription>
        </ItemContent>
        <ItemActions>
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            onClick={onEdit}
            disabled={isStatic}
          >
            {t.settings.tools.editServer}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive"
            onClick={() => removeServer(name)}
            disabled={isStatic}
          >
            <Trash2Icon className="size-3.5" />
          </Button>
          <Switch
            checked={config.enabled}
            disabled={isStatic}
            onCheckedChange={(checked) =>
              enableServer({ serverName: name, enabled: checked })
            }
          />
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            onClick={handleExpand}
          >
            {expanded ? (
              <ChevronUpIcon className="size-4" />
            ) : (
              <ChevronDownIcon className="size-4" />
            )}
          </Button>
        </ItemActions>
      </div>

      {expanded && (
        <ItemFooter className="flex-col items-start gap-2 pt-2">
          <p className="text-muted-foreground text-xs">
            {t.settings.tools.excludeToolsDescription}
          </p>
          {previewing && (
            <div className="text-muted-foreground text-sm">
              {t.settings.tools.testingConnection}
            </div>
          )}
          {previewResult && !previewResult.ok && (
            <div className="text-destructive text-sm">
              {t.settings.tools.connectionError}: {previewResult.error}
            </div>
          )}
          {previewResult?.ok && previewResult.tools.length === 0 && (
            <div className="text-muted-foreground text-sm">
              {t.settings.tools.noToolsFound}
            </div>
          )}
          {previewResult?.ok && previewResult.tools.length > 0 && (
            <div className="flex flex-col gap-1.5 w-full">
              <p className="text-muted-foreground text-xs">
                {t.settings.tools.toolsDiscovered(previewResult.tools.length)}
              </p>
              {previewResult.tools.map((tool) => {
                const isEnabled = !excluded.includes(tool.name);
                return (
                  <label
                    key={tool.name}
                    className={cn(
                      "flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2 text-sm transition-colors",
                      isEnabled ? "border-border" : "border-border/50 opacity-60",
                    )}
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5 cursor-pointer"
                      checked={isEnabled}
                      disabled={isStatic}
                      onChange={(e) =>
                        handleToolToggle(tool.name, e.target.checked)
                      }
                    />
                    <div className="flex flex-col gap-0.5">
                      <span className="font-medium">{tool.name}</span>
                      {tool.description && (
                        <span className="text-muted-foreground text-xs">
                          {tool.description}
                        </span>
                      )}
                    </div>
                  </label>
                );
              })}
            </div>
          )}
        </ItemFooter>
      )}
    </Item>
  );
}

// ─── Add / Edit MCP server dialog ────────────────────────────────────────────

interface ServerFormState {
  name: string;
  url: string;
}

type DetectedEndpoint = {
  type: "http" | "sse";
  url: string;
};

function serverConfigToForm(
  name: string,
  cfg: MCPServerConfig,
): ServerFormState {
  return {
    name,
    url: cfg.url ?? "",
  };
}

function formToServerConfig(
  form: ServerFormState,
  excludedTools: string[],
  detected: DetectedEndpoint | null,
): MCPServerConfig {
  const endpoint = detected ?? { type: "http" as const, url: form.url.trim() };
  return {
    enabled: true,
    type: endpoint.type,
    description: "",
    url: endpoint.url,
    excluded_tools: excludedTools,
  };
}

function AddMCPServerDialog({
  open,
  onOpenChange,
  initial,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  initial?: { name: string; config: MCPServerConfig };
}) {
  const { t } = useI18n();
  const { mutate: addServer, isPending: isSaving } = useAddMCPServer();
  const { mutateAsync: preview } = usePreviewMCPServer();

  const defaultForm: ServerFormState = {
    name: "",
    url: "",
  };

  const [form, setForm] = useState<ServerFormState>(
    initial ? serverConfigToForm(initial.name, initial.config) : defaultForm,
  );
  const [previewResult, setPreviewResult] = useState<
    MCPPreviewResult | undefined
  >(undefined);
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [detectedEndpoint, setDetectedEndpoint] =
    useState<DetectedEndpoint | null>(null);
  const [previewing, setPreviewing] = useState(false);

  // Reset on open/close
  function handleOpenChange(v: boolean) {
    if (!v) {
      setForm(
        initial ? serverConfigToForm(initial.name, initial.config) : defaultForm,
      );
      setPreviewResult(undefined);
      setSelectedTools([]);
      setDetectedEndpoint(null);
    }
    onOpenChange(v);
  }

  function set(field: keyof ServerFormState) {
    return (
      e: React.ChangeEvent<
        HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
      >,
    ) => {
      setForm((prev) => ({ ...prev, [field]: e.target.value }));
      setPreviewResult(undefined);
      setSelectedTools([]);
      setDetectedEndpoint(null);
    };
  }

  const detectTools = useCallback(async (nextUrl: string) => {
    const trimmedUrl = nextUrl.trim();
    if (!trimmedUrl) {
      setPreviewResult(undefined);
      setSelectedTools([]);
      setDetectedEndpoint(null);
      return;
    }

    setPreviewing(true);
    try {
      const candidateUrls = buildCandidateUrls(trimmedUrl);
      const candidates: Array<DetectedEndpoint> = [];
      for (const url of candidateUrls) {
        candidates.push({ type: "http", url });
        candidates.push({ type: "sse", url });
      }

      let lastResult: MCPPreviewResult | undefined;
      let matchedEndpoint: DetectedEndpoint | null = null;

      for (const candidate of candidates) {
        const result = await preview({
          type: candidate.type,
          url: candidate.url,
          description: "",
        });
        lastResult = result;
        if (result.ok) {
          matchedEndpoint = candidate;
          setPreviewResult(result);
          setDetectedEndpoint(candidate);
          setSelectedTools((prev) => {
            if (prev.length === 0) return result.tools.map((t) => t.name);
            const nextNames = new Set(result.tools.map((t) => t.name));
            const kept = prev.filter((name) => nextNames.has(name));
            return kept.length > 0 ? kept : result.tools.map((t) => t.name);
          });
          break;
        }
      }

      if (!matchedEndpoint) {
        setPreviewResult(lastResult);
        setSelectedTools([]);
        setDetectedEndpoint(null);
      }
    } finally {
      setPreviewing(false);
    }
  }, [preview]);

  useEffect(() => {
    const id = window.setTimeout(() => {
      void detectTools(form.url);
    }, 500);
    return () => window.clearTimeout(id);
  }, [detectTools, form.url]);

  function handleSave() {
    if (!form.name.trim() || !form.url.trim() || !previewResult?.ok) return;
    const discovered = previewResult.tools.map((t) => t.name);
    const excluded = discovered.filter((name) => !selectedTools.includes(name));
    const cfg = formToServerConfig(form, excluded, detectedEndpoint);
    addServer(
      { serverName: form.name.trim(), serverConfig: cfg },
      { onSuccess: () => handleOpenChange(false) },
    );
  }

  const canSave = !!form.name.trim() && !!form.url.trim() && !!previewResult?.ok;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {initial
              ? t.settings.tools.editServer
              : t.settings.tools.addServer}
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          {/* Server name */}
          {!initial && (
            <Field label={t.settings.tools.serverName}>
              <input
                className="border-input bg-background focus-visible:ring-ring w-full rounded-md border px-3 py-1.5 text-sm focus-visible:ring-1 focus-visible:outline-none"
                placeholder={t.settings.tools.serverNamePlaceholder}
                value={form.name}
                onChange={set("name")}
              />
            </Field>
          )}

          {/* Transport */}
          <Field label={t.settings.tools.serverUrl}>
            <input
              className="border-input bg-background focus-visible:ring-ring w-full rounded-md border px-3 py-1.5 text-sm focus-visible:ring-1 focus-visible:outline-none"
              placeholder={t.settings.tools.serverUrlPlaceholder}
              value={form.url}
              onChange={set("url")}
            />
          </Field>

          {/* Preview section */}
          <div className="flex flex-col gap-2">
            {previewing && (
              <p className="text-muted-foreground text-sm">
                {t.settings.tools.testingConnection}
              </p>
            )}

            {previewResult && !previewResult.ok && (
              <p className="text-destructive text-sm">
                {t.settings.tools.connectionError}: {previewResult.error}
              </p>
            )}

            {previewResult?.ok && (
              <div className="bg-muted/50 rounded-md p-3">
                <p className="text-muted-foreground mb-2 text-xs font-medium">
                  {t.settings.tools.toolsDiscovered(
                    previewResult.tools.length,
                  )}
                </p>
                {previewResult.tools.length === 0 ? (
                  <p className="text-muted-foreground text-sm">
                    {t.settings.tools.noToolsFound}
                  </p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {previewResult.tools.map((tool) => (
                      <label
                        key={tool.name}
                        className="flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2 text-sm"
                      >
                        <input
                          type="checkbox"
                          className="mt-0.5 cursor-pointer"
                          checked={selectedTools.includes(tool.name)}
                          onChange={(e) => {
                            const checked = e.target.checked;
                            setSelectedTools((prev) =>
                              checked
                                ? [...prev, tool.name]
                                : prev.filter((name) => name !== tool.name),
                            );
                          }}
                        />
                        <div className="flex flex-col gap-0.5">
                          <span className="font-medium">{tool.name}</span>
                          {tool.description && (
                            <span className="text-muted-foreground text-xs">
                              {tool.description}
                            </span>
                          )}
                        </div>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleOpenChange(false)}
            >
              {t.common.cancel}
            </Button>
            <Button size="sm" disabled={!canSave || isSaving} onClick={handleSave}>
              {t.common.save}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium">{label}</label>
      {children}
    </div>
  );
}

// ─── Community tools panel ────────────────────────────────────────────────────

function CommunityToolsPanel() {
  const { t } = useI18n();
  const { tools, isLoading, error } = useCommunityTools();
  const { mutate: toggleTool } = useToggleCommunityTool();
  const isStatic = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";

  if (isLoading) {
    return (
      <div className="text-muted-foreground text-sm">{t.common.loading}</div>
    );
  }
  if (error) {
    return <div className="text-destructive text-sm">{error.message}</div>;
  }

  return (
    <div className="flex flex-col gap-3">
      {tools.map((tool: CommunityTool) => (
        <Item key={tool.name} className="w-full" variant="outline">
          <ItemContent>
            <ItemTitle>
              <span>{tool.display_name}</span>
              <Badge
                variant="outline"
                className="text-muted-foreground text-xs"
              >
                {tool.source === "builtin"
                  ? t.settings.tools.sourceBuiltin
                  : t.settings.tools.sourceConfig}
              </Badge>
            </ItemTitle>
            <ItemDescription>{tool.description}</ItemDescription>
          </ItemContent>
          <ItemActions>
            <Switch
              checked={tool.enabled}
              disabled={isStatic}
              onCheckedChange={(checked) =>
                toggleTool({ name: tool.name, enabled: checked })
              }
            />
          </ItemActions>
        </Item>
      ))}
    </div>
  );
}
