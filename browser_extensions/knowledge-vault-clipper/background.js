const MENU_CLIP_PAGE = "vault-clip-page";
const MENU_CLIP_SELECTION = "vault-clip-selection";
const DEFAULT_API_BASE = "http://127.0.0.1:8001";
const BADGE_OK_COLOR = "#0f766e";
const BADGE_ERR_COLOR = "#b91c1c";
const BADGE_CLEAR_MS = 3500;
const DEFAULT_AUTO_DWELL_MS = 10_000;
const AUTO_DEDUP_TTL_MS = 24 * 60 * 60 * 1000;
// Auto-clip is opt-out: enabled by default, with a default blocklist of
// hosts that are likely to contain private or sensitive content. Empty
// allowlist + non-empty blocklist => clip every http(s) page except blocked.
const DEFAULT_AUTO_CLIP_ENABLED = true;
const DEFAULT_AUTO_BLOCKLIST = [
  "mail.google.com",
  "accounts.google.com",
  "login.live.com",
  "outlook.live.com",
  "outlook.office.com",
  "chrome.google.com",
  "127.0.0.1",
  "localhost",
].join("\n");

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_CLIP_PAGE,
      title: "Clip page to Knowledge Vault",
      contexts: ["page"],
    });
    chrome.contextMenus.create({
      id: MENU_CLIP_SELECTION,
      title: "Clip selection to Knowledge Vault",
      contexts: ["selection"],
    });
  });
});

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error("No active tab.");
  return tab;
}

async function extractFromTab(tabId, mode) {
  const response = await chrome.tabs.sendMessage(tabId, { type: "vault-extract", mode });
  if (!response?.ok) {
    throw new Error(response?.error || "Could not extract page.");
  }
  return response.payload;
}

async function getApiBase() {
  const saved = await chrome.storage.local.get(["apiBase"]);
  return String(saved.apiBase || DEFAULT_API_BASE).replace(/\/$/, "");
}

async function enqueueClip(payload, topic) {
  const apiBase = await getApiBase();
  const response = await fetch(`${apiBase}/api/vault/clip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: payload.url,
      title: payload.title,
      markdown: payload.markdown,
      topic: topic || "",
    }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
}

const NOTIFICATION_ICON = chrome.runtime.getURL("Logo.png");

function notifyQueued(title, source = "manual") {
  try {
    const trimmed = (title || "Untitled page").slice(0, 80);
    chrome.notifications.create(
      `vault-queued-${Date.now()}`,
      {
        type: "basic",
        iconUrl: NOTIFICATION_ICON,
        title: source === "auto" ? "Auto-clipped to Knowledge Vault" : "Saved to Knowledge Vault",
        message: `Queued for ingestion: ${trimmed}`,
        priority: 0,
      },
      () => void chrome.runtime.lastError,
    );
  } catch (_e) {
    // notifications optional; ignore failures
  }
}

let badgeTimer = null;
function flashBadge(text, color) {
  try {
    chrome.action.setBadgeBackgroundColor({ color });
    chrome.action.setBadgeText({ text });
    if (badgeTimer) clearTimeout(badgeTimer);
    badgeTimer = setTimeout(() => {
      chrome.action.setBadgeText({ text: "" });
    }, BADGE_CLEAR_MS);
  } catch (_e) {
    // ignore — badge is decorative
  }
}

async function clipCurrent(mode, source = "manual") {
  const tab = await getActiveTab();
  const payload = await extractFromTab(tab.id, mode);
  await enqueueClip(payload, "");
  flashBadge("✓", BADGE_OK_COLOR);
  notifyQueued(payload.title, source);
  return payload;
}

chrome.contextMenus.onClicked.addListener(async (info) => {
  try {
    if (info.menuItemId === MENU_CLIP_PAGE) {
      await clipCurrent("article", "manual");
    } else if (info.menuItemId === MENU_CLIP_SELECTION) {
      await clipCurrent("selection", "manual");
    }
  } catch (error) {
    flashBadge("!", BADGE_ERR_COLOR);
    console.error("Knowledge Vault clip failed", error);
  }
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "clip-page-to-vault") return;
  try {
    await clipCurrent("article", "manual");
  } catch (_error) {
    flashBadge("!", BADGE_ERR_COLOR);
  }
});

// --- Auto-clip support --------------------------------------------------
// content.js dispatches `vault-auto-clip` after a dwell timeout when the
// current host matches the user's allowlist. Background does the actual
// extract + enqueue so credentials and dedup live in one place.

function normalizeHost(value) {
  return String(value || "").trim().toLowerCase().replace(/^https?:\/\//, "").replace(/\/.*$/, "");
}

function parseAllowlist(raw) {
  return String(raw || "")
    .split(/\r?\n|,/)
    .map(normalizeHost)
    .filter(Boolean);
}

function hostMatches(host, patterns) {
  if (!host || patterns.length === 0) return false;
  return patterns.some((pattern) => {
    if (pattern === host) return true;
    return host.endsWith(`.${pattern}`);
  });
}

async function shouldAutoClip(tabUrl) {
  const settings = await chrome.storage.local.get([
    "autoClipEnabled",
    "autoClipAllowlist",
    "autoClipBlocklist",
    "autoClipSeen",
  ]);
  // Auto-clip is opt-out: undefined means "on" so first-run users get the
  // automatic behaviour the product promises until they explicitly disable it.
  const enabled = settings.autoClipEnabled !== false;
  if (!enabled) return { allow: false, reason: "disabled" };
  let parsed;
  try {
    parsed = new URL(tabUrl);
  } catch {
    return { allow: false, reason: "bad-url" };
  }
  if (!/^https?:$/.test(parsed.protocol)) {
    return { allow: false, reason: "non-http" };
  }
  const host = parsed.host.toLowerCase();
  const allowlist = parseAllowlist(settings.autoClipAllowlist);
  const blocklist = parseAllowlist(
    settings.autoClipBlocklist !== undefined
      ? settings.autoClipBlocklist
      : DEFAULT_AUTO_BLOCKLIST,
  );
  if (hostMatches(host, blocklist)) {
    return { allow: false, reason: "host-blocked" };
  }
  // Empty allowlist => clip everything (subject to the blocklist above).
  if (allowlist.length > 0 && !hostMatches(host, allowlist)) {
    return { allow: false, reason: "host-not-allowed" };
  }
  const seen = settings.autoClipSeen || {};
  const now = Date.now();
  const last = seen[tabUrl];
  if (last && now - last < AUTO_DEDUP_TTL_MS) {
    return { allow: false, reason: "deduped" };
  }
  return { allow: true };
}

async function markAutoClipped(tabUrl) {
  const { autoClipSeen } = await chrome.storage.local.get(["autoClipSeen"]);
  const seen = autoClipSeen || {};
  const now = Date.now();
  for (const key of Object.keys(seen)) {
    if (now - seen[key] > AUTO_DEDUP_TTL_MS) delete seen[key];
  }
  seen[tabUrl] = now;
  await chrome.storage.local.set({ autoClipSeen: seen });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message) return;
  if (message.type === "vault-auto-clip-check") {
    void (async () => {
      const url = sender.tab?.url || message.url;
      const decision = await shouldAutoClip(url);
      sendResponse(decision);
    })();
    return true;
  }
  if (message.type === "vault-auto-clip-submit") {
    void (async () => {
      try {
        const payload = message.payload;
        if (!payload) throw new Error("Missing payload");
        const decision = await shouldAutoClip(payload.url);
        if (!decision.allow) {
          sendResponse({ ok: false, reason: decision.reason });
          return;
        }
        await enqueueClip(payload, "");
        await markAutoClipped(payload.url);
        flashBadge("✓", BADGE_OK_COLOR);
        notifyQueued(payload.title, "auto");
        sendResponse({ ok: true });
      } catch (error) {
        flashBadge("!", BADGE_ERR_COLOR);
        sendResponse({
          ok: false,
          error: error instanceof Error ? error.message : "Auto-clip failed",
        });
      }
    })();
    return true;
  }
  return false;
});

// Allow popup to share enqueue-success signals so badge/notification fire even
// when the popup made the network call directly.
chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "vault-clip-success") {
    flashBadge("✓", BADGE_OK_COLOR);
    notifyQueued(message.title, message.source || "manual");
  } else if (message?.type === "vault-clip-failure") {
    flashBadge("!", BADGE_ERR_COLOR);
  }
});

void (async () => {
  const existing = await chrome.storage.local.get([
    "autoClipDwellMs",
    "autoClipEnabled",
    "autoClipBlocklist",
  ]);
  const seed = {};
  if (typeof existing.autoClipDwellMs !== "number") {
    seed.autoClipDwellMs = DEFAULT_AUTO_DWELL_MS;
  }
  if (existing.autoClipEnabled === undefined) {
    seed.autoClipEnabled = DEFAULT_AUTO_CLIP_ENABLED;
  }
  if (existing.autoClipBlocklist === undefined) {
    seed.autoClipBlocklist = DEFAULT_AUTO_BLOCKLIST;
  }
  if (Object.keys(seed).length > 0) {
    await chrome.storage.local.set(seed);
  }
})();
