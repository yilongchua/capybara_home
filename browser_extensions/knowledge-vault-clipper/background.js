const MENU_CLIP_PAGE = "vault-clip-page";
const MENU_CLIP_SELECTION = "vault-clip-selection";

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

async function enqueueClip(payload, topic) {
  const saved = await chrome.storage.local.get(["apiBase"]);
  const apiBase = String(saved.apiBase || "http://127.0.0.1:8001").replace(/\/$/, "");
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

async function clipCurrent(mode) {
  const tab = await getActiveTab();
  const payload = await extractFromTab(tab.id, mode);
  await enqueueClip(payload, "");
}

chrome.contextMenus.onClicked.addListener(async (info) => {
  try {
    if (info.menuItemId === MENU_CLIP_PAGE) {
      await clipCurrent("article");
    } else if (info.menuItemId === MENU_CLIP_SELECTION) {
      await clipCurrent("selection");
    }
  } catch (error) {
    console.error("Knowledge Vault clip failed", error);
  }
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "clip-page-to-vault") return;
  try {
    await clipCurrent("article");
  } catch (_error) {
    // Keep command handler quiet; popup/context menu gives richer errors.
  }
});
