import { Brain, Code2, FileSearch, Globe, Hammer, Search, Terminal } from "lucide-react";
import { useEffect, useState, useMemo } from "react";
import Image from "next/image";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

const DOTS_INTERVALS = [".", "..", "...", " .", "  ."];

function getTaskIcon(taskDescription: string | undefined): React.ReactNode {
  if (!taskDescription) return <Brain className="size-3.5" />;

  const lower = taskDescription.toLowerCase();

  if (
    lower.includes("search") ||
    lower.includes("find") ||
    lower.includes("query") ||
    lower.includes("look up")
  ) {
    return <Search className="size-3.5" />;
  }
  if (
    lower.includes("code") ||
    lower.includes("write") ||
    lower.includes("implement") ||
    lower.includes("edit") ||
    lower.includes("create")
  ) {
    return <Code2 className="size-3.5" />;
  }
  if (
    lower.includes("read") ||
    lower.includes("file") ||
    lower.includes("open") ||
    lower.includes("analyze")
  ) {
    return <FileSearch className="size-3.5" />;
  }
  if (
    lower.includes("web") ||
    lower.includes("browse") ||
    lower.includes("fetch") ||
    lower.includes("visit")
  ) {
    return <Globe className="size-3.5" />;
  }
  if (
    lower.includes("command") ||
    lower.includes("run") ||
    lower.includes("shell") ||
    lower.includes("exec")
  ) {
    return <Terminal className="size-3.5" />;
  }
  if (lower.includes("tool") || lower.includes("use")) {
    return <Hammer className="size-3.5" />;
  }

  return <Brain className="size-3.5" />;
}

export function CapybaraRunner({
  className,
  taskDescription,
  size = "md",
  actor = "capybara",
}: {
  className?: string;
  taskDescription?: string;
  size?: "sm" | "md" | "lg";
  actor?: "capybara" | "baby_capy";
}) {
  const { t } = useI18n();
  const [dotIndex, setDotIndex] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setDotIndex((prev) => (prev + 1) % DOTS_INTERVALS.length);
    }, 400);
    return () => clearInterval(interval);
  }, []);

  const dotText = DOTS_INTERVALS[dotIndex % DOTS_INTERVALS.length];
  const icon = useMemo(() => getTaskIcon(taskDescription), [taskDescription]);
  const showWorkingGif = actor === "capybara" || actor === "baby_capy";
  const gifClassName = cn(
    "shrink-0 object-contain",
    size === "sm" && "size-4",
    size === "md" && "size-5",
    size === "lg" && "size-6",
  );

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 text-sm",
        size === "sm" && "text-xs",
        size === "lg" && "text-base",
        className,
      )}
    >
      {taskDescription ? (
        <>
          {showWorkingGif && (
            <Image
              src="/capybara-working.gif"
              alt={actor === "baby_capy" ? "Baby Capy working" : "Capybara working"}
              width={20}
              height={20}
              unoptimized
              className={gifClassName}
            />
          )}
          <span className="text-muted-foreground font-medium">
            {actor === "baby_capy"
              ? t.chatUI.capybaraRunner.babyWorkingOn
              : t.chatUI.capybaraRunner.workingOn}
            :
          </span>
          <span className="text-accent">{icon}</span>
          <span className="text-foreground">
            {taskDescription}
            <span className="animate-pulse">{dotText}</span>
          </span>
        </>
      ) : (
        <>
          {showWorkingGif && (
            <Image
              src="/capybara-working.gif"
              alt={actor === "baby_capy" ? "Baby Capy thinking" : "Capybara thinking"}
              width={20}
              height={20}
              unoptimized
              className={gifClassName}
            />
          )}
          <span className="text-muted-foreground animate-pulse">
            {actor === "baby_capy"
              ? t.chatUI.capybaraRunner.babyThinking
              : t.chatUI.capybaraRunner.thinking}
            <span className="animate-pulse">{dotText}</span>
          </span>
        </>
      )}
    </div>
  );
}
