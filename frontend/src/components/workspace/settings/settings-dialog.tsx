"use client";

import {
  BellIcon,
  InfoIcon,
  BrainIcon,
  PaletteIcon,
  ClockIcon,
  FlaskConicalIcon,
  WrenchIcon,
  BotIcon,
  GlobeIcon,
  ImageIcon,
  Share2Icon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { AboutSettingsPage } from "@/components/workspace/settings/about-settings-page";
import { AppearanceSettingsPage } from "@/components/workspace/settings/appearance-settings-page";
import { AutoresearchCleanupSettingsPage } from "@/components/workspace/settings/autoresearch-cleanup-settings-page";
import { BrowserSettingsPage } from "@/components/workspace/settings/browser-settings-page";
import { ComfyuiSettingsPage } from "@/components/workspace/settings/comfyui-settings-page";
import { EmbeddingSettingsPage } from "@/components/workspace/settings/embedding-settings-page";
import { LlmSettingsPage } from "@/components/workspace/settings/llm-settings-page";
import { MemorySettingsPage } from "@/components/workspace/settings/memory-settings-page";
import { NotificationSettingsPage } from "@/components/workspace/settings/notification-settings-page";
import { PipelineCleanupSettingsPage } from "@/components/workspace/settings/pipeline-cleanup-settings-page";
import { ToolSettingsPage } from "@/components/workspace/settings/tool-settings-page";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

type SettingsSection =
  | "appearance"
  | "memory"
  | "pipelineCleanup"
  | "autoresearchCleanup"
  | "tools"
  | "notification"
  | "llm"
  | "embedding"
  | "browser"
  | "comfyui"
  | "about";

type SettingsDialogProps = React.ComponentProps<typeof Dialog> & {
  defaultSection?: SettingsSection;
};

export function SettingsDialog(props: SettingsDialogProps) {
  const { defaultSection = "appearance", ...dialogProps } = props;
  const { t } = useI18n();
  const [activeSection, setActiveSection] =
    useState<SettingsSection>(defaultSection);

  useEffect(() => {
    // When opening the dialog, ensure the active section follows the caller's intent.
    // This allows triggers like "About" to open the dialog directly on that page.
    if (dialogProps.open) {
      setActiveSection(defaultSection);
    }
  }, [defaultSection, dialogProps.open]);

  const sections = useMemo(
    () => [
      {
        id: "appearance",
        label: t.settings.sections.appearance,
        icon: PaletteIcon,
      },
      {
        id: "notification",
        label: t.settings.sections.notification,
        icon: BellIcon,
      },
      {
        id: "memory",
        label: t.settings.sections.memory,
        icon: BrainIcon,
      },
      {
        id: "pipelineCleanup",
        label: t.settings.sections.pipelineCleanup,
        icon: ClockIcon,
      },
      {
        id: "autoresearchCleanup",
        label: t.settings.sections.autoresearchCleanup,
        icon: FlaskConicalIcon,
      },
      { id: "tools", label: t.settings.sections.tools, icon: WrenchIcon },
      { id: "llm", label: t.settings.sections.llm, icon: BotIcon },
      {
        id: "embedding",
        label: t.settings.sections.embedding,
        icon: Share2Icon,
      },
      { id: "browser", label: t.settings.sections.browser, icon: GlobeIcon },
      { id: "comfyui", label: t.settings.sections.comfyui, icon: ImageIcon },
      { id: "about", label: t.settings.sections.about, icon: InfoIcon },
    ],
    [
      t.settings.sections.appearance,
      t.settings.sections.memory,
      t.settings.sections.pipelineCleanup,
      t.settings.sections.autoresearchCleanup,
      t.settings.sections.tools,
      t.settings.sections.notification,
      t.settings.sections.llm,
      t.settings.sections.embedding,
      t.settings.sections.browser,
      t.settings.sections.comfyui,
      t.settings.sections.about,
    ],
  );
  return (
    <Dialog
      {...dialogProps}
      onOpenChange={(open) => props.onOpenChange?.(open)}
    >
      <DialogContent
        className="flex h-[75vh] max-h-[calc(100vh-2rem)] flex-col sm:max-w-5xl md:max-w-6xl"
        aria-describedby={undefined}
      >
        <DialogHeader className="gap-1">
          <DialogTitle>{t.settings.title}</DialogTitle>
          <p className="text-muted-foreground text-sm">
            {t.settings.description}
          </p>
        </DialogHeader>
        <div className="grid min-h-0 flex-1 gap-4 md:grid-cols-[220px_1fr]">
          <nav className="bg-sidebar min-h-0 overflow-y-auto rounded-lg border p-2">
            <ul className="space-y-1 pr-1">
              {sections.map(({ id, label, icon: Icon }) => {
                const active = activeSection === id;
                return (
                  <li key={id}>
                    <button
                      type="button"
                      onClick={() => setActiveSection(id as SettingsSection)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                        active
                          ? "bg-primary text-primary-foreground shadow-sm"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground",
                      )}
                    >
                      <Icon className="size-4" />
                      <span>{label}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
          <ScrollArea className="h-full min-h-0 rounded-lg border">
            <div className="space-y-8 p-6">
              {activeSection === "appearance" && <AppearanceSettingsPage />}
              {activeSection === "memory" && <MemorySettingsPage />}
              {activeSection === "pipelineCleanup" && <PipelineCleanupSettingsPage />}
              {activeSection === "autoresearchCleanup" && <AutoresearchCleanupSettingsPage />}
              {activeSection === "tools" && <ToolSettingsPage />}
              {activeSection === "notification" && <NotificationSettingsPage />}
              {activeSection === "llm" && <LlmSettingsPage />}
              {activeSection === "embedding" && <EmbeddingSettingsPage />}
              {activeSection === "browser" && <BrowserSettingsPage />}
              {activeSection === "comfyui" && <ComfyuiSettingsPage />}
              {activeSection === "about" && <AboutSettingsPage />}
            </div>
          </ScrollArea>
        </div>
      </DialogContent>
    </Dialog>
  );
}
