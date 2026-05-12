"use client";

import { XIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";

import { Suggestion, Suggestions } from "../ai-elements/suggestion";

export function FollowupSuggestionsPanel({
  disabled,
  isNewThread,
  followupsHidden,
  followupsLoading,
  followups,
  onSelect,
  onHide,
}: {
  disabled?: boolean;
  isNewThread?: boolean;
  followupsHidden: boolean;
  followupsLoading: boolean;
  followups: string[];
  onSelect: (suggestion: string) => void;
  onHide: () => void;
}) {
  const { t } = useI18n();

  if (disabled || isNewThread || followupsHidden || (!followupsLoading && followups.length === 0)) {
    return null;
  }

  return (
    <div className="pointer-events-none absolute right-0 bottom-full left-0 z-20 mb-4 flex items-center justify-center">
      <div className="pointer-events-auto flex flex-col items-center gap-2">
        {followupsLoading ? (
          <div className="text-muted-foreground bg-background/80 rounded-full border px-4 py-2 text-xs backdrop-blur-sm">
            {t.inputBox.followupLoading}
          </div>
        ) : (
          <Suggestions
            vertical
            className="bg-background/80 max-h-64 w-fit items-center rounded-2xl border p-2 shadow-lg backdrop-blur-md"
          >
            {followups.map((s) => (
              <Suggestion
                key={s}
                suggestion={s}
                className="h-auto w-full max-w-sm justify-start whitespace-normal border-none px-4 py-2.5 text-left hover:bg-accent/50"
                onClick={() => onSelect(s)}
              />
            ))}
            <div className="mt-1 flex justify-center border-t pt-1">
              <Button
                aria-label={t.common.close}
                className="text-muted-foreground h-6 cursor-pointer rounded-full border-none px-3 text-[10px] font-normal uppercase tracking-wider shadow-none transition-colors hover:bg-destructive/10 hover:text-destructive"
                variant="ghost"
                size="sm"
                type="button"
                onClick={onHide}
              >
                <XIcon className="mr-1 size-3" />
                {t.common.close}
              </Button>
            </div>
          </Suggestions>
        )}
      </div>
    </div>
  );
}
