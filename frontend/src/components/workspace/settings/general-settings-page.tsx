"use client";

import { useEffect, useMemo, useState } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";

import { SettingsSection } from "./settings-section";

type TimezoneOption = {
  value: string;
  label: string;
};

const TIMEZONE_OPTIONS: TimezoneOption[] = [
  { value: "Asia/Singapore", label: "Singapore (GMT+8)" },
  { value: "Asia/Hong_Kong", label: "Hong Kong (GMT+8)" },
  { value: "Asia/Shanghai", label: "Shanghai (GMT+8)" },
  { value: "Asia/Tokyo", label: "Tokyo (GMT+9)" },
  { value: "Asia/Seoul", label: "Seoul (GMT+9)" },
  { value: "Asia/Kolkata", label: "Kolkata (GMT+5:30)" },
  { value: "Asia/Dubai", label: "Dubai (GMT+4)" },
  { value: "Australia/Sydney", label: "Sydney (GMT+10/+11)" },
  { value: "Europe/London", label: "London (GMT+0/+1)" },
  { value: "Europe/Berlin", label: "Berlin (GMT+1/+2)" },
  { value: "Europe/Paris", label: "Paris (GMT+1/+2)" },
  { value: "America/New_York", label: "New York (GMT−5/−4)" },
  { value: "America/Chicago", label: "Chicago (GMT−6/−5)" },
  { value: "America/Denver", label: "Denver (GMT−7/−6)" },
  { value: "America/Los_Angeles", label: "Los Angeles (GMT−8/−7)" },
  { value: "UTC", label: "UTC (GMT+0)" },
];

function getTimezoneOffsetLabel(timezone: string, date: Date): string {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      timeZoneName: "shortOffset",
    }).formatToParts(date);
    const offset = parts.find((part) => part.type === "timeZoneName")?.value;
    return offset ?? "";
  } catch {
    return "";
  }
}

function getCurrentTimeInZone(timezone: string, date: Date): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: timezone,
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  } catch {
    return "";
  }
}

export function GeneralSettingsPage() {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();
  const currentTimezone = settings.general.timezone;

  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const interval = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(interval);
  }, []);

  const options = useMemo<TimezoneOption[]>(() => {
    const known = new Set(TIMEZONE_OPTIONS.map((opt) => opt.value));
    if (currentTimezone && !known.has(currentTimezone)) {
      return [{ value: currentTimezone, label: currentTimezone }, ...TIMEZONE_OPTIONS];
    }
    return TIMEZONE_OPTIONS;
  }, [currentTimezone]);

  const offset = getTimezoneOffsetLabel(currentTimezone, now);
  const localTime = getCurrentTimeInZone(currentTimezone, now);

  const handleChange = (value: string) => {
    setSettings("general", { timezone: value });
  };

  return (
    <SettingsSection
      title={t.settings.general.timezoneTitle}
      description={t.settings.general.timezoneDescription}
    >
      <div className="flex flex-col gap-2">
        <div className="max-w-sm">
          <Select value={currentTimezone} onValueChange={handleChange}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {offset && localTime && (
          <p className="text-muted-foreground text-xs">
            {t.settings.general.timezoneCurrent(offset, localTime)}
          </p>
        )}
      </div>
    </SettingsSection>
  );
}
