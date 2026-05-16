export type SlashCommandName =
  | "compact"
  | "dreamy"
  | "dreamy-exit"
  | "handoff"
  | "new"
  | "mount"
  | "analyse"
  | "publishdocs"
  | "autoresearch"
  | "rename"
  | "vault-save"
  | "vault-search";

export type SlashCommandParseResult = {
  isSlash: boolean;
  commandName: string | null;
  args: string;
  isRecognized: boolean;
  query: string;
  showMenu: boolean;
};

const SUPPORTED_COMMANDS: SlashCommandName[] = [
  "compact",
  "dreamy",
  "dreamy-exit",
  "handoff",
  "new",
  "mount",
  "analyse",
  "publishdocs",
  "autoresearch",
  "rename",
  "vault-save",
  "vault-search",
];

export function isSupportedSlashCommand(commandName: string): commandName is SlashCommandName {
  return SUPPORTED_COMMANDS.includes(commandName as SlashCommandName);
}

export function parseLeadingSlashCommand(value: string): SlashCommandParseResult {
  const leadingTrimmed = value.trimStart();
  if (!leadingTrimmed.startsWith("/")) {
    return {
      isSlash: false,
      commandName: null,
      args: "",
      isRecognized: false,
      query: "",
      showMenu: false,
    };
  }

  const withoutSlash = leadingTrimmed.slice(1);
  const firstWhitespace = withoutSlash.search(/\s/);
  const commandPart =
    firstWhitespace === -1 ? withoutSlash : withoutSlash.slice(0, firstWhitespace);
  const normalizedCommand = commandPart.toLowerCase();
  const args = firstWhitespace === -1 ? "" : withoutSlash.slice(firstWhitespace + 1).trim();
  const isRecognized = isSupportedSlashCommand(normalizedCommand);

  return {
    isSlash: true,
    commandName: normalizedCommand || null,
    args,
    isRecognized,
    query: normalizedCommand,
    showMenu: firstWhitespace === -1,
  };
}
