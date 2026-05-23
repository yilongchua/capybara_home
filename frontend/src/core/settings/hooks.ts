import { useCallback, useEffect, useLayoutEffect, useState } from "react";

import {
  DEFAULT_LOCAL_SETTINGS,
  getLocalSettings,
  saveLocalSettings,
  type LocalSettings,
} from "./local";

const SETTINGS_CHANGE_EVENT = "CapyHome:local-settings-change";

export function useLocalSettings(): [
  LocalSettings,
  (
    key: keyof LocalSettings,
    value: Partial<LocalSettings[keyof LocalSettings]>,
  ) => void,
] {
  const [mounted, setMounted] = useState(false);
  const [state, setState] = useState<LocalSettings>(DEFAULT_LOCAL_SETTINGS);
  useLayoutEffect(() => {
    if (!mounted) {
      setState(getLocalSettings());
    }
    setMounted(true);
  }, [mounted]);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onChange = () => setState(getLocalSettings());
    window.addEventListener(SETTINGS_CHANGE_EVENT, onChange);
    return () => window.removeEventListener(SETTINGS_CHANGE_EVENT, onChange);
  }, []);
  const setter = useCallback(
    (
      key: keyof LocalSettings,
      value: Partial<LocalSettings[keyof LocalSettings]>,
    ) => {
      if (!mounted) return;
      setState((prev) => {
        const prevSlice = prev[key] as Record<string, unknown>;
        const nextPatch = value as Record<string, unknown>;
        const changed = Object.entries(nextPatch).some(
          ([patchKey, patchValue]) => !Object.is(prevSlice[patchKey], patchValue),
        );
        if (!changed) {
          return prev;
        }

        const newState = {
          ...prev,
          [key]: {
            ...prevSlice,
            ...nextPatch,
          },
        };
        saveLocalSettings(newState);
        if (typeof window !== "undefined") {
          // Defer cross-instance notification so listeners' setState calls
          // don't run during another component's render phase.
          queueMicrotask(() =>
            window.dispatchEvent(new CustomEvent(SETTINGS_CHANGE_EVENT)),
          );
        }
        return newState;
      });
    },
    [mounted],
  );
  return [state, setter];
}
