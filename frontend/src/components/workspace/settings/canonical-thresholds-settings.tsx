"use client";

import { Loader2Icon, RotateCcwIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useCanonicalThresholds,
  useSaveCanonicalThresholds,
} from "@/core/onboarding";
import type { CanonicalThresholds } from "@/core/onboarding/types";
import { cn } from "@/lib/utils";

type NumericField = Exclude<
  keyof CanonicalThresholds,
  "reviewAbbreviationAlone"
>;

const NUMERIC_FIELDS: ReadonlyArray<{
  key: NumericField;
  label: string;
  hint: string;
  tier: "auto" | "review";
}> = [
  {
    key: "autoLexicalStrong",
    label: "Auto: lexical alone",
    hint: "Auto-merge when lexical similarity is at or above this score (e.g. 'JP Morgan' ↔ 'J.P. Morgan').",
    tier: "auto",
  },
  {
    key: "autoLexicalHigh",
    label: "Auto: lexical + co-occurrence",
    hint: "Lexical similarity floor that combines with the co-occurrence floor below.",
    tier: "auto",
  },
  {
    key: "autoLexicalHighCooc",
    label: "Auto: lexical + co-occurrence (co-occ floor)",
    hint: "Co-occurrence required alongside the 'lexical + co-occurrence' lexical floor.",
    tier: "auto",
  },
  {
    key: "autoAbbreviationCooc",
    label: "Auto: abbreviation + same-source co-occurrence",
    hint: "Co-occurrence required when an abbreviation match shares at least one source (e.g. 'SG' ↔ 'Singapore').",
    tier: "auto",
  },
  {
    key: "autoLexicalMid",
    label: "Auto: mid lexical + strong co-occurrence",
    hint: "Lexical floor for the moderate-lexical-with-strong-co-occurrence rule.",
    tier: "auto",
  },
  {
    key: "autoLexicalMidCooc",
    label: "Auto: mid lexical + strong co-occurrence (co-occ floor)",
    hint: "Co-occurrence required alongside the moderate lexical floor.",
    tier: "auto",
  },
  {
    key: "reviewAbbreviationCooc",
    label: "Review: abbreviation + co-occurrence",
    hint: "Below the auto bar — surface to the human review inbox instead.",
    tier: "review",
  },
  {
    key: "reviewCoocStrong",
    label: "Review: strong co-occurrence alone",
    hint: "When two surfaces share many sources but lexically look unrelated, queue for review.",
    tier: "review",
  },
  {
    key: "reviewLexical",
    label: "Review: lexical alone",
    hint: "Surface moderate lexical matches with no co-occurrence/abbreviation signal for human review.",
    tier: "review",
  },
];

function approxEqual(a: CanonicalThresholds, b: CanonicalThresholds): boolean {
  for (const { key } of NUMERIC_FIELDS) {
    if (Math.abs(a[key] - b[key]) > 1e-6) return false;
  }
  return a.reviewAbbreviationAlone === b.reviewAbbreviationAlone;
}

export function CanonicalThresholdsSettings() {
  const { data, isLoading } = useCanonicalThresholds();
  const {
    mutate: save,
    isPending: saving,
    error: saveError,
  } = useSaveCanonicalThresholds();

  const [form, setForm] = useState<CanonicalThresholds | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    if (data?.effective) {
      setForm(data.effective);
    }
  }, [data?.effective]);

  const defaults = data?.defaults ?? null;
  const dirty = useMemo(() => {
    if (!form || !data?.effective) return false;
    return !approxEqual(form, data.effective);
  }, [form, data?.effective]);

  const matchesDefaults = useMemo(() => {
    if (!form || !defaults) return true;
    return approxEqual(form, defaults);
  }, [form, defaults]);

  if (isLoading || !form) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2Icon className="size-3.5 animate-spin" />
        Loading thresholds…
      </div>
    );
  }

  function updateNumeric(key: NumericField, raw: string) {
    if (!form) return;
    const parsed = Number(raw);
    if (Number.isNaN(parsed)) return;
    const clamped = Math.max(0, Math.min(1, parsed));
    setForm({ ...form, [key]: clamped });
  }

  function handleSave() {
    if (!form) return;
    save(form, {
      onSuccess: () => setSavedAt(Date.now()),
    });
  }

  function handleResetToDefaults() {
    if (!defaults) return;
    setForm(defaults);
  }

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold">Canonical alias merge thresholds</h3>
        <p className="text-muted-foreground text-xs">
          Controls how vault lint collapses entity/concept variants. Auto-merge
          rules apply silently; review rules surface in the alias inbox. Each
          value is a minimum score from 0.00 to 1.00; the engine fires the first
          matching rule in order.
        </p>
      </div>

      <div className="space-y-3">
        <div className="text-xs font-semibold tracking-wide text-emerald-600 uppercase">
          Auto-merge rules
        </div>
        {NUMERIC_FIELDS.filter((f) => f.tier === "auto").map((field) => (
          <ThresholdRow
            key={field.key}
            label={field.label}
            hint={field.hint}
            value={form[field.key]}
            defaultValue={defaults?.[field.key]}
            onChange={(v) => updateNumeric(field.key, v)}
          />
        ))}
      </div>

      <div className="space-y-3">
        <div className="text-xs font-semibold tracking-wide text-amber-600 uppercase">
          Review-queue rules
        </div>
        {NUMERIC_FIELDS.filter((f) => f.tier === "review").map((field) => (
          <ThresholdRow
            key={field.key}
            label={field.label}
            hint={field.hint}
            value={form[field.key]}
            defaultValue={defaults?.[field.key]}
            onChange={(v) => updateNumeric(field.key, v)}
          />
        ))}

        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.reviewAbbreviationAlone}
            onChange={(e) =>
              setForm({ ...form, reviewAbbreviationAlone: e.target.checked })
            }
            className="mt-0.5"
          />
          <span>
            <span className="font-medium">
              Review: abbreviation alone
            </span>
            <span className="text-muted-foreground ml-2 text-xs">
              (default:{" "}
              {defaults?.reviewAbbreviationAlone ? "on" : "off"})
            </span>
            <p className="text-muted-foreground text-xs">
              When off, abbreviation matches without any co-occurrence are
              dropped instead of queued.
            </p>
          </span>
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={handleSave} disabled={!dirty || saving}>
          {saving ? (
            <>
              <Loader2Icon className="size-3.5 animate-spin" />
              Saving…
            </>
          ) : (
            "Save thresholds"
          )}
        </Button>
        <Button
          variant="outline"
          onClick={handleResetToDefaults}
          disabled={matchesDefaults || saving}
        >
          <RotateCcwIcon className="size-3.5" />
          Reset to defaults
        </Button>
        {savedAt && !dirty && !saving && !saveError ? (
          <span className="text-xs text-green-600">Saved.</span>
        ) : null}
        {saveError ? (
          <span className="text-destructive text-xs">
            {saveError.message || "Save failed."}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function ThresholdRow({
  label,
  hint,
  value,
  defaultValue,
  onChange,
}: {
  label: string;
  hint: string;
  value: number;
  defaultValue: number | undefined;
  onChange: (raw: string) => void;
}) {
  const isOverridden =
    defaultValue !== undefined && Math.abs(value - defaultValue) > 1e-6;
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2">
        <label className="text-sm font-medium">{label}</label>
        <span
          className={cn(
            "text-muted-foreground text-xs",
            isOverridden && "text-amber-600",
          )}
        >
          default:{" "}
          {defaultValue !== undefined ? defaultValue.toFixed(2) : "—"}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <Input
          type="number"
          step="0.05"
          min={0}
          max={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-28"
        />
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="flex-1 accent-emerald-600"
        />
      </div>
      <p className="text-muted-foreground text-xs">{hint}</p>
    </div>
  );
}
