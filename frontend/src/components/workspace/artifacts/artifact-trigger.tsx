import { FilesIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/workspace/tooltip";

import { useDirectory } from "./context";

export const ArtifactTrigger = () => {
  const { directoryFiles, setOpen: setDirectoryOpen } = useDirectory();

  if (!directoryFiles || directoryFiles.length === 0) {
    return null;
  }
  return (
    <Tooltip content="Show directories of this conversation">
      <Button
        className="text-muted-foreground hover:text-foreground"
        variant="ghost"
        onClick={() => {
          setDirectoryOpen(true);
        }}
      >
        <FilesIcon />
        Directories
      </Button>
    </Tooltip>
  );
};
