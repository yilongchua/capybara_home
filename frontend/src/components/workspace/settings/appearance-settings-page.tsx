"use client";

import { MoonIcon, SunIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { useMemo, type ComponentType, type SVGProps } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

type ThemeMode = "light" | "dark" | "capyhome";

function CapyHomeIcon({ className }: SVGProps<SVGSVGElement>) {
  return (
     
    <img
      src="/icon.png"
      alt=""
      aria-hidden
      className={cn("object-contain", className)}
    />
  );
}

export function AppearanceSettingsPage() {
  const { t } = useI18n();
  const { theme, setTheme } = useTheme();
  const currentTheme = (theme ?? "light") as ThemeMode;

  const themeOptions = useMemo(
    () => [
      {
        id: "light" as const,
        label: t.settings.appearance.light,
        description: t.settings.appearance.lightDescription,
        icon: SunIcon,
      },
      {
        id: "dark" as const,
        label: t.settings.appearance.dark,
        description: t.settings.appearance.darkDescription,
        icon: MoonIcon,
      },
      {
        id: "capyhome" as const,
        label: t.settings.appearance.capyhome,
        description: t.settings.appearance.capyHomeDescription,
        icon: CapyHomeIcon,
      },
    ],
    [
      t.settings.appearance.capyhome,
      t.settings.appearance.capyHomeDescription,
      t.settings.appearance.dark,
      t.settings.appearance.darkDescription,
      t.settings.appearance.light,
      t.settings.appearance.lightDescription,
    ],
  );

  return (
    <div className="space-y-8">
      <SettingsSection
        title={t.settings.appearance.themeTitle}
        description={t.settings.appearance.themeDescription}
      >
        <div className="grid gap-3 lg:grid-cols-2">
          {themeOptions.map((option) => (
            <ThemePreviewCard
              key={option.id}
              icon={option.icon}
              label={option.label}
              description={option.description}
              active={currentTheme === option.id}
              mode={option.id}
              onSelect={(value) => setTheme(value)}
            />
          ))}
        </div>
      </SettingsSection>
    </div>
  );
}

function ThemePreviewCard({
  icon: Icon,
  label,
  description,
  active,
  mode,
  onSelect,
}: {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  label: string;
  description: string;
  active: boolean;
  mode: ThemeMode;
  onSelect: (mode: ThemeMode) => void;
}) {
  const previewClasses =
    mode === "dark"
      ? "border-neutral-800 bg-neutral-900 text-neutral-200"
      : mode === "capyhome"
        ? "border-amber-900/30 bg-[oklch(0.945_0.035_75)] text-[oklch(0.28_0.045_55)]"
        : "border-slate-200 bg-white text-slate-900";
  const dotClass =
    mode === "dark"
      ? "bg-emerald-400"
      : mode === "capyhome"
        ? "bg-amber-700"
        : "bg-emerald-500";
  return (
    <button
      type="button"
      onClick={() => onSelect(mode)}
      className={cn(
        "group flex h-full flex-col gap-3 rounded-lg border p-4 text-left transition-all",
        active
          ? "border-primary ring-primary/30 shadow-sm ring-2"
          : "hover:border-border hover:shadow-sm",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="bg-muted rounded-md p-2">
          <Icon className="size-4" />
        </div>
        <div className="space-y-1">
          <div className="text-sm leading-none font-semibold">{label}</div>
          <p className="text-muted-foreground text-xs leading-snug">
            {description}
          </p>
        </div>
      </div>
      <div
        className={cn(
          "relative overflow-hidden rounded-md border text-xs transition-colors",
          previewClasses,
        )}
      >
        <div className="border-border/50 flex items-center gap-2 border-b px-3 py-2">
          <div className={cn("h-2 w-2 rounded-full", dotClass)} />
          <div className="h-2 w-10 rounded-full bg-current/20" />
          <div className="h-2 w-6 rounded-full bg-current/15" />
        </div>
        <div className="grid grid-cols-[1fr_240px] gap-3 px-3 py-3">
          <div className="space-y-2">
            <div className="h-3 w-3/4 rounded-full bg-current/15" />
            <div className="h-3 w-1/2 rounded-full bg-current/10" />
            <div className="h-[90px] rounded-md border border-current/10 bg-current/5" />
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-md bg-current/10" />
              <div className="space-y-2">
                <div className="h-2 w-14 rounded-full bg-current/15" />
                <div className="h-2 w-10 rounded-full bg-current/10" />
              </div>
            </div>
            <div className="flex flex-col gap-1 rounded-md border border-dashed border-current/15 p-2">
              <div className="h-2 w-3/5 rounded-full bg-current/15" />
              <div className="h-2 w-2/5 rounded-full bg-current/10" />
            </div>
          </div>
        </div>
      </div>
    </button>
  );
}
