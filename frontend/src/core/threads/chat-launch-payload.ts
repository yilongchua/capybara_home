export type PendingChatLaunchPayload = {
  source: "handoff";
  mountedPath?: string;
  prefill?: string;
  createdAt: number;
};

const STORAGE_KEY = "capybara:pending-chat-launch";

function hasWindow(): boolean {
  return typeof window !== "undefined";
}

export function setPendingChatLaunchPayload(payload: PendingChatLaunchPayload): void {
  if (!hasWindow()) return;
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

export function getPendingChatLaunchPayload(): PendingChatLaunchPayload | null {
  if (!hasWindow()) return null;
  const raw = window.sessionStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as PendingChatLaunchPayload;
    if (parsed?.source !== "handoff") return null;
    if (typeof parsed.createdAt !== "number") return null;
    return parsed;
  } catch {
    return null;
  }
}

export function clearPendingChatLaunchPayload(): void {
  if (!hasWindow()) return;
  window.sessionStorage.removeItem(STORAGE_KEY);
}
