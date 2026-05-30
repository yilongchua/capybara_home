"use client";

import { Loader2Icon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { deleteVaultKnowledgeGraph } from "@/core/control-plane/api";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import {
  useEmbeddingEndpoints,
  useKnowledgeVaultConfig,
  useSaveKnowledgeVaultConfig,
} from "@/core/onboarding";
import { cn } from "@/lib/utils";

import { CanonicalThresholdsSettings } from "./canonical-thresholds-settings";
import { SettingsSection } from "./settings-section";

export function KnowledgeVaultSettingsPage() {
  const { t } = useI18n();
  const { config, isLoading } = useKnowledgeVaultConfig();
  const { mutate: saveConfig, isPending: saving, error: saveError } = useSaveKnowledgeVaultConfig();
  const { models, isLoading: loadingModels } = useModels();
  const { endpoints: embeddingEndpoints, isLoading: loadingEmbeddings } = useEmbeddingEndpoints();

  const [path, setPath] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [graphDeleting, setGraphDeleting] = useState(false);

  useEffect(() => {
    if (!isLoading) {
      setPath(config.path ?? "");
      setLlmModel(config.llmModel ?? "");
      setEmbeddingModel(config.embeddingModel ?? "");
    }
  }, [config.path, config.llmModel, config.embeddingModel, isLoading]);

  const embeddingModelOptions = useMemo(() => {
    const out: string[] = [];
    const seen = new Set<string>();
    for (const ep of Object.values(embeddingEndpoints)) {
      if (!ep.enabled) continue;
      for (const m of ep.models) {
        if (!seen.has(m)) {
          seen.add(m);
          out.push(m);
        }
      }
    }
    return out;
  }, [embeddingEndpoints]);

  const llmModelOptions = useMemo(
    () => models.map((m) => m.name).filter(Boolean),
    [models],
  );

  const dirty =
    path !== (config.path ?? "") ||
    llmModel !== (config.llmModel ?? "") ||
    embeddingModel !== (config.embeddingModel ?? "");

  function handleSave() {
    saveConfig(
      {
        path: path.trim(),
        llmModel: llmModel.trim(),
        embeddingModel: embeddingModel.trim(),
      },
      {
        onSuccess: () => setSavedAt(Date.now()),
      },
    );
  }

  return (
    <SettingsSection
      title={t.settings.knowledgeVault.title}
      description={t.settings.knowledgeVault.description}
    >
      <div className="space-y-6">
        <div className="space-y-2">
          <label className="text-sm font-medium">
            {t.settings.knowledgeVault.folderPath}
          </label>
          <Input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder={t.settings.knowledgeVault.folderPathPlaceholder}
          />
          <p className="text-muted-foreground text-xs">
            {t.settings.knowledgeVault.folderPathHint}
          </p>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium">
            {t.settings.knowledgeVault.llmModel}
          </label>
          <select
            className={cn(
              "border-input bg-background focus-visible:ring-ring w-full rounded-md border px-3 py-1.5 text-sm focus-visible:ring-1 focus-visible:outline-none",
            )}
            value={llmModel}
            onChange={(e) => setLlmModel(e.target.value)}
            disabled={loadingModels}
          >
            <option value="">{t.settings.knowledgeVault.noModelOption}</option>
            {llmModel && !llmModelOptions.includes(llmModel) ? (
              <option value={llmModel}>{llmModel} (current)</option>
            ) : null}
            {llmModelOptions.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <p className="text-muted-foreground text-xs">
            {t.settings.knowledgeVault.llmModelHint}
          </p>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium">
            {t.settings.knowledgeVault.embeddingModel}
          </label>
          <select
            className={cn(
              "border-input bg-background focus-visible:ring-ring w-full rounded-md border px-3 py-1.5 text-sm focus-visible:ring-1 focus-visible:outline-none",
            )}
            value={embeddingModel}
            onChange={(e) => setEmbeddingModel(e.target.value)}
            disabled={loadingEmbeddings}
          >
            <option value="">{t.settings.knowledgeVault.noModelOption}</option>
            {embeddingModel && !embeddingModelOptions.includes(embeddingModel) ? (
              <option value={embeddingModel}>{embeddingModel} (current)</option>
            ) : null}
            {embeddingModelOptions.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <p className="text-muted-foreground text-xs">
            {t.settings.knowledgeVault.embeddingModelHint}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button onClick={handleSave} disabled={!dirty || saving}>
            {saving ? (
              <>
                <Loader2Icon className="size-3.5 animate-spin" />
                {t.settings.knowledgeVault.saving}
              </>
            ) : (
              t.settings.knowledgeVault.save
            )}
          </Button>
          {savedAt && !dirty && !saving && !saveError ? (
            <span className="text-xs text-green-600">
              {t.settings.knowledgeVault.saved}
            </span>
          ) : null}
          {saveError ? (
            <span className="text-destructive text-xs">
              {t.settings.knowledgeVault.saveError}
              {saveError.message ? `: ${saveError.message}` : ""}
            </span>
          ) : null}
        </div>

        <div className="rounded-lg border p-4">
          <CanonicalThresholdsSettings />
        </div>

        <div className="rounded-lg border border-destructive/30 p-4 space-y-3">
          <div className="space-y-2">
            <div className="text-sm font-medium">
              {t.settings.knowledgeVault.deleteGraphTitle}
            </div>
            <p className="text-muted-foreground text-sm">
              {t.settings.knowledgeVault.deleteGraphDescription}
            </p>
            <Button
              variant="destructive"
              onClick={async () => {
                if (!window.confirm(t.settings.knowledgeVault.deleteGraphConfirm)) {
                  return;
                }
                setGraphDeleting(true);
                try {
                  await deleteVaultKnowledgeGraph();
                } catch (err) {
                  window.alert(
                    err instanceof Error
                      ? err.message
                      : "Failed to delete knowledge graph.",
                  );
                } finally {
                  setGraphDeleting(false);
                }
              }}
              disabled={graphDeleting}
            >
              {graphDeleting
                ? t.settings.knowledgeVault.deleteGraphPending
                : t.settings.knowledgeVault.deleteGraphButton}
            </Button>
          </div>
        </div>
      </div>
    </SettingsSection>
  );
}
