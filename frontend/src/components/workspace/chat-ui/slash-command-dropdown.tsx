"use client";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { cn } from "@/lib/utils";

export type SlashCommandOption = {
  name: string;
  title: string;
  description: string;
  usage: string;
};

export function SlashCommandDropdown({
  visible,
  query,
  commands,
  selected,
  onSelectedChange,
  onExecute,
  className,
}: {
  visible: boolean;
  query: string;
  commands: SlashCommandOption[];
  selected: string;
  onSelectedChange: (value: string) => void;
  onExecute: (name: string) => void;
  className?: string;
}) {
  if (!visible) {
    return null;
  }

  const normalizedQuery = query.toLowerCase();
  const filtered = commands.filter((command) =>
    command.name.toLowerCase().includes(normalizedQuery),
  );

  return (
    <div
      className={cn(
        "bg-background/95 text-popover-foreground absolute bottom-full left-0 z-50 mb-2 w-96 overflow-hidden rounded-lg border shadow-md backdrop-blur-sm",
        className,
      )}
      role="listbox"
    >
      <Command
        shouldFilter={false}
        value={selected}
        onValueChange={onSelectedChange}
        className="max-h-80"
      >
        <div className="border-b px-3 py-2 text-xs">
          <span className="text-muted-foreground">/</span>
          <span className="ml-1 font-mono">{query || "commands"}</span>
        </div>
        <CommandList>
          <CommandEmpty className="px-3 py-2 text-xs text-muted-foreground">
            No matching commands
          </CommandEmpty>
          <CommandGroup>
            {filtered.map((command) => (
              <CommandItem
                key={command.name}
                value={command.name}
                onSelect={() => onExecute(command.name)}
              >
                <div className="flex w-full flex-col gap-0.5">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="font-mono">/{command.name}</span>
                    <span className="text-muted-foreground text-[11px]">
                      {command.usage}
                    </span>
                  </div>
                  <span className="text-muted-foreground text-xs">
                    {command.description}
                  </span>
                </div>
              </CommandItem>
            ))}
          </CommandGroup>
        </CommandList>
      </Command>
    </div>
  );
}
