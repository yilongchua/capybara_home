"use client";

import { createContext, useContext, useEffect, useState } from "react";

let _isDocumentVisible = true;

if (typeof document !== "undefined") {
  _isDocumentVisible = document.visibilityState === "visible";
  document.addEventListener("visibilitychange", () => {
    _isDocumentVisible = document.visibilityState === "visible";
  });
}

export function isDocumentVisible(): boolean {
  return _isDocumentVisible;
}

type PollingGovernorContextValue = {
  isVisible: boolean;
};

const PollingGovernorContext = createContext<PollingGovernorContextValue>({
  isVisible: true,
});

export function PollingGovernorProvider({ children }: { children: React.ReactNode }) {
  const [isVisible, setIsVisible] = useState(() => _isDocumentVisible);

  useEffect(() => {
    const handler = () => {
      setIsVisible(_isDocumentVisible);
    };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, []);

  return (
    <PollingGovernorContext.Provider value={{ isVisible }}>
      {children}
    </PollingGovernorContext.Provider>
  );
}

export function usePollingGovernor() {
  return useContext(PollingGovernorContext);
}

export function useDocumentVisible(): boolean {
  return usePollingGovernor().isVisible;
}
