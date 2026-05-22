"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  BotIcon,
  CheckIcon,
  CpuIcon,
  FlaskConicalIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";
import { useCallback, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import { useI18n } from "@/core/i18n/hooks";
import { testEmbeddingEndpoint } from "@/core/onboarding/api";
import {
  useEmbeddingEndpoints,
  useSaveEmbeddingEndpoints,
  useTestEmbeddingEndpoint,
} from "@/core/onboarding";
import type { UserLlmEndpoint } from "@/core/onboarding/types";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

type ProviderType = "ollama" | "lm-studio" | "custom";

const PROVIDER_DEFAULTS: Record<
  ProviderType,
  { baseUrl: string; icon: React.ReactNode; label: string }
> = {
  ollama: {
    baseUrl: "http://localhost:11434/v1",
    icon: <FlaskConicalIcon className="size-4" />,
    label: "Ollama",
  },
  "lm-studio": {
    baseUrl: "http://localhost:1234/v1",
    icon: <CpuIcon className="size-4" />,
    label: "LM Studio",
  },
  custom: {
    baseUrl: "",
    icon: <BotIcon className="size-4" />,
    label: "Custom",
  },
};

export function EmbeddingSettingsPage() {
  const { t } = useI18n();

  const [provider, setProvider] = useState<ProviderType>("ollama");
  const [displayName, setDisplayName] = useState("");
  const [baseUrl, setBaseUrl] = useState(PROVIDER_DEFAULTS.ollama.baseUrl);
  const [apiKey, setApiKey] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  type RowTestState = { testing: boolean; ok: boolean | null; error?: string | null };
  const [rowTests, setRowTests] = useState<Record<string, RowTestState>>({});

  const handleRowTest = useCallback(
    async (key: string, ep: UserLlmEndpoint) => {
      setRowTests((s) => ({ ...s, [key]: { testing: true, ok: null } }));
      try {
        const result = await testEmbeddingEndpoint(
          ep.base_url,
          ep.api_key,
          ep.default_model || ep.models[0],
        );
        setRowTests((s) => ({
          ...s,
          [key]: { testing: false, ok: result.ok, error: result.error },
        }));
      } catch (err) {
        setRowTests((s) => ({
          ...s,
          [key]: {
            testing: false,
            ok: false,
            error: err instanceof Error ? err.message : String(err),
          },
        }));
      }
    },
    [],
  );

  const queryClient = useQueryClient();
  const { endpoints, isLoading: loadingEndpoints } = useEmbeddingEndpoints();
  const handleRefresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["embeddingEndpoints"] });
  }, [queryClient]);
  const {
    mutate: testEndpoint,
    data: testResult,
    isPending: testing,
    reset: resetTest,
  } = useTestEmbeddingEndpoint();
  const { mutate: saveEndpoints, isPending: saving } = useSaveEmbeddingEndpoints();

  function handleProviderChange(p: ProviderType) {
    setProvider(p);
    setBaseUrl(PROVIDER_DEFAULTS[p].baseUrl);
    resetTest();
    setSelectedModels([]);
  }

  const handleTest = useCallback(() => {
    if (!baseUrl.trim()) return;
    resetTest();
    testEndpoint({ baseUrl: baseUrl.trim(), apiKey });
  }, [baseUrl, apiKey, testEndpoint, resetTest]);

  function toggleModel(modelId: string) {
    setSelectedModels((prev) =>
      prev.includes(modelId)
        ? prev.filter((m) => m !== modelId)
        : [...prev, modelId],
    );
  }

  function buildEndpointKey(): string {
    const base =
      displayName.trim().toLowerCase().replace(/\s+/g, "-") || provider;
    if (!(base in endpoints)) return base;
    let idx = 2;
    while (`${base}-${idx}` in endpoints) {
      idx += 1;
    }
    return `${base}-${idx}`;
  }

  function displayNameCollision(name: string): string | null {
    const normalized = name.trim().toLowerCase();
    if (!normalized) return null;
    for (const [key, ep] of Object.entries(endpoints)) {
      if (editingKey !== null && key === editingKey) continue;
      if (ep.display_name.trim().toLowerCase() === normalized) {
        return ep.display_name;
      }
    }
    return null;
  }

  function handleAdd() {
    if (!displayName.trim() || !baseUrl.trim()) return;
    if (displayNameCollision(displayName)) return;
    const key = editingKey ?? buildEndpointKey();
    const updated: Record<string, UserLlmEndpoint> = {
      ...endpoints,
      [key]: {
        enabled: true,
        provider,
        display_name: displayName.trim(),
        base_url: baseUrl.trim(),
        api_key: apiKey,
        models: selectedModels,
        default_model: selectedModels[0] ?? "",
        supports_thinking: false,
        supports_vision: false,
      },
    };
    saveEndpoints(updated, {
      onSuccess: () => {
        resetForm();
      },
    });
  }

  function resetForm() {
    setProvider("ollama");
    setDisplayName("");
    setBaseUrl(PROVIDER_DEFAULTS.ollama.baseUrl);
    setApiKey("");
    setSelectedModels([]);
    setEditingKey(null);
    resetTest();
  }

  function handleEdit(key: string, ep: UserLlmEndpoint) {
    setEditingKey(key);
    setProvider(ep.provider as ProviderType);
    setDisplayName(ep.display_name);
    setBaseUrl(ep.base_url);
    setApiKey(ep.api_key);
    setSelectedModels(ep.models);
    resetTest();
  }

  function handleDelete(key: string) {
    if (!confirm(t.settings.llm.deleteConfirm)) return;
    const updated = { ...endpoints };
    delete updated[key];
    saveEndpoints(updated);
  }

  function handleToggle(key: string, ep: UserLlmEndpoint) {
    saveEndpoints({
      ...endpoints,
      [key]: { ...ep, enabled: !ep.enabled },
    });
  }

  const collidingDisplayName = displayNameCollision(displayName);
  const canAdd =
    !!displayName.trim() && !!baseUrl.trim() && !collidingDisplayName;
  const isEditing = editingKey !== null;

  return (
    <SettingsSection
      title={t.settings.embedding.title}
      description={t.settings.embedding.description}
    >
      <p className="text-muted-foreground mb-4 text-xs">
        {t.settings.embedding.knowledgeGraphHint}
      </p>

      <div className="mb-6">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-medium">
            {t.settings.llm.configuredEndpoints}
          </h3>
          <Button
            size="sm"
            variant="ghost"
            onClick={handleRefresh}
            disabled={loadingEndpoints}
          >
            {loadingEndpoints ? (
              <Loader2Icon className="size-3.5 animate-spin" />
            ) : (
              <RefreshCwIcon className="size-3.5" />
            )}
            Refresh
          </Button>
        </div>
        {loadingEndpoints && (
          <div className="text-muted-foreground text-sm">{t.common.loading}</div>
        )}
        {!loadingEndpoints && Object.keys(endpoints).length === 0 && (
          <p className="text-muted-foreground text-sm">
            {t.settings.llm.noEndpoints}
          </p>
        )}
        <div className="flex flex-col gap-2">
          {Object.entries(endpoints).map(([key, ep]) => {
            const rowTest = rowTests[key];
            const providerLabel =
              PROVIDER_DEFAULTS[ep.provider as ProviderType]?.label ?? ep.provider;
            return (
              <Item key={key} className="w-full" variant="outline">
                <ItemContent>
                  <ItemTitle>
                    <span>{ep.display_name}</span>
                    <Badge variant="outline" className="text-xs">
                      {providerLabel}
                    </Badge>
                    <Badge
                      variant="outline"
                      className={cn(
                        "text-xs",
                        ep.enabled
                          ? "border-green-500/30 text-green-600"
                          : "text-muted-foreground",
                      )}
                    >
                      {ep.enabled
                        ? t.settings.llm.endpointEnabled
                        : t.settings.llm.endpointDisabled}
                    </Badge>
                  </ItemTitle>
                  <ItemDescription className="font-mono text-xs">
                    {ep.base_url}
                  </ItemDescription>
                  {ep.models.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {ep.models.map((m) => (
                        <Badge
                          key={m}
                          variant="outline"
                          className="text-muted-foreground font-mono text-[10px]"
                        >
                          {m}
                        </Badge>
                      ))}
                    </div>
                  )}
                  {rowTest && !rowTest.testing && rowTest.ok === false && (
                    <p className="text-destructive mt-1.5 text-xs">
                      {t.settings.llm.connectionFailed}
                      {rowTest.error ? `: ${rowTest.error}` : ""}
                    </p>
                  )}
                  {rowTest && !rowTest.testing && rowTest.ok === true && (
                    <p className="mt-1.5 text-xs text-green-600">
                      {t.settings.llm.connectionSuccess}
                    </p>
                  )}
                </ItemContent>
                <ItemActions>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleToggle(key, ep)}
                  >
                    <CheckIcon
                      className={cn(
                        "size-3.5",
                        ep.enabled ? "text-green-600" : "text-muted-foreground",
                      )}
                    />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={rowTest?.testing}
                    onClick={() => void handleRowTest(key, ep)}
                  >
                    {rowTest?.testing ? (
                      <Loader2Icon className="size-3.5 animate-spin" />
                    ) : null}
                    {t.settings.llm.testConnection}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground"
                    onClick={() => handleEdit(key, ep)}
                  >
                    {t.settings.tools.editServer}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive"
                    onClick={() => handleDelete(key)}
                  >
                    <Trash2Icon className="size-3.5" />
                  </Button>
                </ItemActions>
              </Item>
            );
          })}
        </div>
      </div>

      <div className="border-border mb-4 border-t pt-4">
        <h3 className="text-sm font-medium mb-3">
          {isEditing ? t.settings.llm.saveProvider : t.settings.llm.addProvider}
        </h3>
      </div>

      <div className="mb-4">
        <label className="text-sm font-medium mb-2 block">
          {t.settings.llm.providerType}
        </label>
        <div className="flex gap-2">
          {(
            Object.entries(PROVIDER_DEFAULTS) as [
              ProviderType,
              (typeof PROVIDER_DEFAULTS)[ProviderType],
            ][]
          ).map(([key, cfg]) => (
            <button
              key={key}
              type="button"
              onClick={() => handleProviderChange(key)}
              className={cn(
                "flex items-center gap-2 rounded-md border px-4 py-2.5 text-sm font-medium transition-colors",
                provider === key
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border hover:bg-muted text-muted-foreground",
              )}
            >
              {cfg.icon}
              {cfg.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium">
            {t.settings.llm.displayName}
          </label>
          <input
            className={cn(
              "border-input bg-background focus-visible:ring-ring w-full rounded-md border px-3 py-1.5 text-sm focus-visible:ring-1 focus-visible:outline-none",
              collidingDisplayName &&
                "border-destructive focus-visible:ring-destructive",
            )}
            placeholder={t.settings.llm.displayNamePlaceholder}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
          {collidingDisplayName && (
            <p className="text-destructive text-xs">
              Display name already used by &quot;{collidingDisplayName}&quot;.
              Pick a unique name.
            </p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium">{t.settings.llm.baseUrl}</label>
          <input
            className="border-input bg-background focus-visible:ring-ring w-full rounded-md border px-3 py-1.5 text-sm focus-visible:ring-1 focus-visible:outline-none"
            placeholder={t.settings.llm.baseUrlPlaceholder}
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium">{t.settings.llm.apiKey}</label>
          <input
            className="border-input bg-background focus-visible:ring-ring w-full rounded-md border px-3 py-1.5 text-sm focus-visible:ring-1 focus-visible:outline-none"
            placeholder={t.settings.llm.apiKeyPlaceholder}
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
      </div>

      <div className="mb-4 flex items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={!baseUrl.trim() || testing}
          onClick={handleTest}
        >
          {testing ? (
            <Loader2Icon className="size-3.5 animate-spin" />
          ) : (
            <CheckIcon className="size-3.5" />
          )}
          {testing ? t.settings.llm.testing : t.settings.llm.testConnection}
        </Button>
        <Button size="sm" disabled={!canAdd || saving} onClick={handleAdd}>
          <PlusIcon className="size-3.5" />
          {isEditing ? t.settings.llm.saveProvider : t.settings.llm.addProvider}
        </Button>
        {(editingKey !== null || displayName || baseUrl) && (
          <Button size="sm" variant="ghost" onClick={resetForm}>
            <XIcon className="size-3.5" />
          </Button>
        )}
      </div>

      {testResult && !testResult.ok && (
        <div className="text-destructive mb-3 text-sm">
          {t.settings.llm.connectionFailed}: {testResult.error}
        </div>
      )}
      {testResult?.ok && (
        <div className="bg-muted/50 mb-4 rounded-md p-3">
          <p className="text-muted-foreground mb-2 text-xs font-medium">
            {t.settings.llm.discoveredModels(testResult.models.length)}
          </p>
          {testResult.models.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {t.settings.llm.connectionSuccess}
            </p>
          ) : (
            <div className="flex max-h-40 flex-col gap-1.5 overflow-y-auto">
              {testResult.models.map((modelId) => (
                <label
                  key={modelId}
                  className="flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm"
                >
                  <input
                    type="checkbox"
                    className="cursor-pointer"
                    checked={selectedModels.includes(modelId)}
                    onChange={() => toggleModel(modelId)}
                  />
                  <span className="font-mono text-xs">{modelId}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}
    </SettingsSection>
  );
}
