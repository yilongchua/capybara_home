const apiBaseInput = document.getElementById("apiBase");
const modeInput = document.getElementById("mode");
const topicInput = document.getElementById("topic");
const notesInput = document.getElementById("notes");
const clipButton = document.getElementById("clipButton");
const statusNode = document.getElementById("status");
const queuePill = document.getElementById("queuePill");
const autoClipToggle = document.getElementById("autoClipToggle");
const autoClipDwell = document.getElementById("autoClipDwell");
const autoClipBlocklist = document.getElementById("autoClipBlocklist");
const autoClipAllowlist = document.getElementById("autoClipAllowlist");

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

async function loadSettings() {
  const saved = await chrome.storage.local.get([
    "apiBase",
    "mode",
    "topic",
    "autoClipEnabled",
    "autoClipDwellMs",
    "autoClipBlocklist",
    "autoClipAllowlist",
  ]);
  if (saved.apiBase) apiBaseInput.value = saved.apiBase;
  if (saved.mode) modeInput.value = saved.mode;
  if (saved.topic) topicInput.value = saved.topic;

  // Auto-clip is opt-out: undefined == on.
  autoClipToggle.checked = saved.autoClipEnabled !== false;
  autoClipDwell.value = Math.max(4, Math.round((saved.autoClipDwellMs ?? 10_000) / 1000));
  autoClipBlocklist.value =
    saved.autoClipBlocklist !== undefined ? saved.autoClipBlocklist : DEFAULT_AUTO_BLOCKLIST;
  autoClipAllowlist.value = saved.autoClipAllowlist ?? "";
}

function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.style.color = isError ? "#b91c1c" : "#57534e";
}

function showQueueConfirmation(title) {
  const trimmed = (title || "Untitled page").slice(0, 70);
  queuePill.textContent = `✓ Queued for ingestion: ${trimmed}`;
  queuePill.classList.add("visible");
  setTimeout(() => queuePill.classList.remove("visible"), 6000);
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error("No active tab found.");
  return tab;
}

async function extractPayload(mode) {
  const tab = await getActiveTab();
  try {
    const response = await chrome.tabs.sendMessage(tab.id, { type: "vault-extract", mode });
    if (!response?.ok || !response?.payload) {
      throw new Error(response?.error || "Could not extract page content.");
    }
    return response.payload;
  } catch (_error) {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["content.js"],
    });
    const response = await chrome.tabs.sendMessage(tab.id, { type: "vault-extract", mode });
    if (!response?.ok || !response?.payload) {
      throw new Error(response?.error || "Could not extract page content.");
    }
    return response.payload;
  }
}

function prependNotes(markdown) {
  const notes = notesInput.value.trim();
  return notes ? `## Operator Notes\n\n${notes}\n\n${markdown}` : markdown;
}

async function persistAutoClipSettings() {
  const dwellSeconds = Math.max(4, Number(autoClipDwell.value) || 10);
  await chrome.storage.local.set({
    autoClipEnabled: autoClipToggle.checked,
    autoClipDwellMs: dwellSeconds * 1000,
    autoClipBlocklist: autoClipBlocklist.value,
    autoClipAllowlist: autoClipAllowlist.value,
  });
}

async function submitClip() {
  const mode = modeInput.value;
  const payload = await extractPayload(mode);
  const markdown = prependNotes(payload.markdown);
  const apiBase = apiBaseInput.value.trim().replace(/\/$/, "");
  await chrome.storage.local.set({
    apiBase,
    mode,
    topic: topicInput.value.trim(),
  });
  const response = await fetch(`${apiBase}/api/vault/clip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: payload.url,
      title: payload.title,
      markdown,
      topic: topicInput.value.trim(),
    }),
  });
  if (!response.ok) {
    const details = await response.text();
    throw new Error(details || `HTTP ${response.status}`);
  }
  return payload;
}

clipButton.addEventListener("click", async () => {
  try {
    clipButton.disabled = true;
    setStatus("Sending clip to vault...");
    const payload = await submitClip();
    setStatus(`Queued "${payload.title}" for ingestion.`);
    showQueueConfirmation(payload.title);
    void chrome.runtime
      .sendMessage({ type: "vault-clip-success", title: payload.title, source: "manual" })
      .catch(() => {});
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Clip failed.", true);
    void chrome.runtime.sendMessage({ type: "vault-clip-failure" }).catch(() => {});
  } finally {
    clipButton.disabled = false;
  }
});

[autoClipToggle, autoClipDwell, autoClipBlocklist, autoClipAllowlist].forEach((el) => {
  el.addEventListener("change", () => void persistAutoClipSettings());
});

void loadSettings();
