const apiBaseInput = document.getElementById("apiBase");
const modeInput = document.getElementById("mode");
const topicInput = document.getElementById("topic");
const notesInput = document.getElementById("notes");
const previewButton = document.getElementById("previewButton");
const clipButton = document.getElementById("clipButton");
const statusNode = document.getElementById("status");
const previewNode = document.getElementById("preview");

async function loadSettings() {
  const saved = await chrome.storage.local.get(["apiBase", "mode", "topic"]);
  if (saved.apiBase) {
    apiBaseInput.value = saved.apiBase;
  }
  if (saved.mode) {
    modeInput.value = saved.mode;
  }
  if (saved.topic) {
    topicInput.value = saved.topic;
  }
}

function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.style.color = isError ? "#b91c1c" : "#57534e";
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

function renderPreview(payload) {
  previewNode.hidden = false;
  const content = prependNotes(payload.markdown);
  const maxChars = 1400;
  previewNode.textContent = content.length > maxChars ? `${content.slice(0, maxChars)}\n\n...` : content;
  setStatus(`Preview ready (${content.length} chars).`);
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

previewButton.addEventListener("click", async () => {
  try {
    previewButton.disabled = true;
    setStatus("Building preview...");
    const payload = await extractPayload(modeInput.value);
    renderPreview(payload);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Clip failed.", true);
  } finally {
    previewButton.disabled = false;
  }
});

clipButton.addEventListener("click", async () => {
  try {
    clipButton.disabled = true;
    setStatus("Sending clip to vault...");
    const payload = await submitClip();
    setStatus(`Queued "${payload.title}" for ingestion.`);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Clip failed.", true);
  } finally {
    clipButton.disabled = false;
  }
});

void loadSettings();
