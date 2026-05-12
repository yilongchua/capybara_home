"use client";

import { useEffect, useMemo } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AuroraText } from "../ui/aurora-text";

let waved = false;

export function Welcome({
  className,
  mode,
}: {
  className?: string;
  mode?: "work" | "plan";

}) {
  const { t } = useI18n();
  const isPlan = useMemo(() => mode === "plan", [mode]);
  const colors = useMemo(() => {
    if (isPlan) {
      return ["#efefbb", "#e9c665", "#e3a812"];
    }
    return ["var(--color-foreground)"];
  }, [isPlan]);
  useEffect(() => {
    waved = true;
  }, []);
  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-2 px-8 py-4 text-center",
        className,
      )}
    >
      <div className="text-2xl font-bold">
        <div className="flex items-center gap-2">
          <div className={cn("inline-block", !waved ? "animate-wave" : "")}>
            {isPlan ? "🗺️" : "👋"}
          </div>
          <AuroraText colors={colors}>{t.welcome.greeting}</AuroraText>
        </div>
      </div>
      <div className="text-muted-foreground text-sm">
        {t.welcome.description.includes("\n") ? (
          <pre className="whitespace-pre">{t.welcome.description}</pre>
        ) : (
          <p>{t.welcome.description}</p>
        )}
      </div>

    </div>
  );
}
