"use client";

import {
  CheckIcon,
  ClipboardListIcon,
  MoonIcon,
  SparklesIcon,
  WorkflowIcon,
  ZapIcon,
} from "lucide-react";

import {
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuItem,
  PromptInputActionMenuTrigger,
  PromptInputButton,
} from "@/components/ai-elements/prompt-input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

type InputMode = "work" | "plan";

export function WorkflowButton({
  active,
  onToggle,
}: {
  active: boolean;
  onToggle: () => void;
}) {
  return (
    <PromptInputButton
      className={cn("gap-1 px-2!", active && "bg-accent text-accent-foreground")}
      type="button"
      title="Prefix message with /workflow to design a batch workflow"
      onClick={onToggle}
    >
      <WorkflowIcon className="size-4" />
      <span className="text-xs">Workflow</span>
    </PromptInputButton>
  );
}

export function ModeSelectorMenu({
  mode,
  onSelect,
  triggerId,
}: {
  mode: InputMode | undefined;
  onSelect: (mode: InputMode) => void;
  triggerId: string;
}) {
  const { t } = useI18n();
  const effectiveMode: InputMode = mode === "plan" ? "plan" : "work";
  return (
    <PromptInputActionMenu>
      <PromptInputActionMenuTrigger id={triggerId} className="gap-1! px-2!">
        <div>
          {effectiveMode === "work" && <ZapIcon className="size-3 text-[#dabb5e]" />}
          {effectiveMode === "plan" && <SparklesIcon className="size-3 text-blue-400" />}
        </div>
        <div className={cn("text-xs font-normal", effectiveMode === "work" ? "golden-text" : "text-blue-400")}>
          {effectiveMode === "work" ? t.inputBox.workMode : t.inputBox.planMode}
        </div>
      </PromptInputActionMenuTrigger>
      <PromptInputActionMenuContent className="w-80">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-muted-foreground text-xs">
            {t.inputBox.mode}
          </DropdownMenuLabel>
          <PromptInputActionMenu>
            <PromptInputActionMenuItem
              className={cn(
                effectiveMode === "work" ? "text-accent-foreground" : "text-muted-foreground/65",
              )}
              onSelect={() => onSelect("work")}
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1 font-bold">
                  <ZapIcon className={cn("mr-2 size-4", effectiveMode === "work" && "text-[#dabb5e]")} />
                  {t.inputBox.workMode}
                </div>
                <div className="pl-7 text-xs">
                  {t.inputBox.workModeDescription}
                </div>
              </div>
              {effectiveMode === "work" ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </PromptInputActionMenuItem>
            <PromptInputActionMenuItem
              className={cn(
                effectiveMode === "plan" ? "text-accent-foreground" : "text-muted-foreground/65",
              )}
              onSelect={() => onSelect("plan")}
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1 font-bold">
                  <SparklesIcon className={cn("mr-2 size-4", effectiveMode === "plan" && "text-blue-400")} />
                  {t.inputBox.planMode}
                </div>
                <div className="pl-7 text-xs">
                  {t.inputBox.planModeDescription}
                </div>
              </div>
              {effectiveMode === "plan" ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </PromptInputActionMenuItem>
          </PromptInputActionMenu>
        </DropdownMenuGroup>
      </PromptInputActionMenuContent>
    </PromptInputActionMenu>
  );
}

export function PrivacyAndAutoMenu({
  mode,
  autoModeEnabled,
  onTogglePlanMode,
  onToggleAutoMode,
  triggerId,
}: {
  mode: InputMode | undefined;
  autoModeEnabled: boolean;
  onTogglePlanMode: () => void;
  onToggleAutoMode: () => void;
  triggerId: string;
}) {
  const { t } = useI18n();
  const planModeEnabled = mode === "plan";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <PromptInputButton
          id={triggerId}
          aria-label="Plan mode and auto mode tools"
          className="gap-1 px-2"
        >
          <ClipboardListIcon className="size-3" />
          <MoonIcon className="size-3" />
        </PromptInputButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72">
        <DropdownMenuLabel className="text-muted-foreground text-xs">
          Plan Mode & Auto Mode
        </DropdownMenuLabel>
        <DropdownMenuItem
          aria-label={`Toggle ${t.inputBox.planMode} mode`}
          onSelect={(event) => {
            event.preventDefault();
            onTogglePlanMode();
          }}
          className={cn(
            "flex items-center justify-between gap-2",
            planModeEnabled && "text-accent-foreground",
          )}
        >
          <span>Plan Mode</span>
          <Switch
            checked={planModeEnabled}
            onCheckedChange={() => onTogglePlanMode()}
            aria-label={t.inputBox.planMode}
          />
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          aria-label="Toggle auto mode"
          onSelect={(event) => {
            event.preventDefault();
            onToggleAutoMode();
          }}
          className={cn(
            "flex items-center justify-between gap-2",
            autoModeEnabled && "text-accent-foreground",
          )}
        >
          <span>Auto Mode</span>
          <Switch
            checked={autoModeEnabled}
            onCheckedChange={() => onToggleAutoMode()}
            aria-label="Auto mode"
          />
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function ReasoningEffortMenu({
  show,
  reasoningEffort,
  onSelect,
  triggerId,
}: {
  show: boolean;
  reasoningEffort: "minimal" | "low" | "medium" | "high" | undefined;
  onSelect: (effort: "minimal" | "low" | "medium" | "high") => void;
  triggerId: string;
}) {
  const { t } = useI18n();
  if (!show) return null;
  return (
    <PromptInputActionMenu>
      <PromptInputActionMenuTrigger id={triggerId} className="gap-1! px-2!">
        <div className="text-xs font-normal">
          {t.inputBox.reasoningEffort}:
          {reasoningEffort === "minimal" && " " + t.inputBox.reasoningEffortMinimal}
          {reasoningEffort === "low" && " " + t.inputBox.reasoningEffortLow}
          {reasoningEffort === "medium" && " " + t.inputBox.reasoningEffortMedium}
          {reasoningEffort === "high" && " " + t.inputBox.reasoningEffortHigh}
        </div>
      </PromptInputActionMenuTrigger>
      <PromptInputActionMenuContent className="w-70">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-muted-foreground text-xs">
            {t.inputBox.reasoningEffort}
          </DropdownMenuLabel>
          <PromptInputActionMenu>
            <PromptInputActionMenuItem
              className={cn(
                reasoningEffort === "minimal"
                  ? "text-accent-foreground"
                  : "text-muted-foreground/65",
              )}
              onSelect={() => onSelect("minimal")}
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1 font-bold">
                  {t.inputBox.reasoningEffortMinimal}
                </div>
                <div className="pl-2 text-xs">{t.inputBox.reasoningEffortMinimalDescription}</div>
              </div>
              {reasoningEffort === "minimal" ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </PromptInputActionMenuItem>
            <PromptInputActionMenuItem
              className={cn(
                reasoningEffort === "low" ? "text-accent-foreground" : "text-muted-foreground/65",
              )}
              onSelect={() => onSelect("low")}
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1 font-bold">
                  {t.inputBox.reasoningEffortLow}
                </div>
                <div className="pl-2 text-xs">{t.inputBox.reasoningEffortLowDescription}</div>
              </div>
              {reasoningEffort === "low" ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </PromptInputActionMenuItem>
            <PromptInputActionMenuItem
              className={cn(
                reasoningEffort === "medium" || !reasoningEffort
                  ? "text-accent-foreground"
                  : "text-muted-foreground/65",
              )}
              onSelect={() => onSelect("medium")}
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1 font-bold">
                  {t.inputBox.reasoningEffortMedium}
                </div>
                <div className="pl-2 text-xs">{t.inputBox.reasoningEffortMediumDescription}</div>
              </div>
              {reasoningEffort === "medium" || !reasoningEffort ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </PromptInputActionMenuItem>
            <PromptInputActionMenuItem
              className={cn(
                reasoningEffort === "high"
                  ? "text-accent-foreground"
                  : "text-muted-foreground/65",
              )}
              onSelect={() => onSelect("high")}
            >
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1 font-bold">
                  {t.inputBox.reasoningEffortHigh}
                </div>
                <div className="pl-2 text-xs">{t.inputBox.reasoningEffortHighDescription}</div>
              </div>
              {reasoningEffort === "high" ? (
                <CheckIcon className="ml-auto size-4" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </PromptInputActionMenuItem>
          </PromptInputActionMenu>
        </DropdownMenuGroup>
      </PromptInputActionMenuContent>
    </PromptInputActionMenu>
  );
}
