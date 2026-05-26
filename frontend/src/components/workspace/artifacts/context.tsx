import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

import { useSidebar } from "@/components/ui/sidebar";
import { env } from "@/env";

export interface DirectoryContextType {
  directoryFiles: string[];
  setDirectoryFiles: (files: string[]) => void;

  selectedFile: string | null;
  autoSelect: boolean;
  select: (file: string, autoSelect?: boolean) => void;
  deselect: () => void;

  open: boolean;
  autoOpen: boolean;
  setOpen: (open: boolean) => void;
}

const DirectoryContext = createContext<DirectoryContextType | undefined>(
  undefined,
);

interface DirectoryProviderProps {
  children: ReactNode;
}

export function DirectoryProvider({ children }: DirectoryProviderProps) {
  const [directoryFiles, setDirectoryFiles] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [autoSelect, setAutoSelect] = useState(true);
  const [open, setOpen] = useState(
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true",
  );
  const [autoOpen, setAutoOpen] = useState(true);
  const { setOpen: setSidebarOpen } = useSidebar();

  const select = useCallback(
    (file: string, autoSelect = false) => {
      setSelectedFile(file);
      // Only close the sidebar on explicit user selections — not on automatic
      // selections triggered by streaming tool results (present_files, write_file).
      // Auto-closing on every agent file write breaks the sidebar experience.
      if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && !autoSelect) {
        setSidebarOpen(false);
      }
      if (!autoSelect) {
        setAutoSelect(false);
      }
    },
    [setSidebarOpen, setSelectedFile, setAutoSelect],
  );

  const deselect = useCallback(() => {
    setSelectedFile(null);
    setAutoSelect(true);
  }, []);

  const value: DirectoryContextType = {
    directoryFiles,
    setDirectoryFiles,

    open,
    autoOpen,
    autoSelect,
    setOpen: (isOpen: boolean) => {
      if (!isOpen && autoOpen) {
        setAutoOpen(false);
        setAutoSelect(false);
      }
      setOpen(isOpen);
    },

    selectedFile,
    select,
    deselect,
  };

  return (
    <DirectoryContext.Provider value={value}>
      {children}
    </DirectoryContext.Provider>
  );
}

export function useDirectory() {
  const context = useContext(DirectoryContext);
  if (context === undefined) {
    throw new Error("useDirectory must be used within a DirectoryProvider");
  }
  return context;
}
