function buildMarkdown(payload) {
  const lines = [`# ${payload.title}`, "", `Source URL: ${payload.url}`, ""];
  if (payload.mode === "selection" && payload.selectedText) {
    lines.push("## Selected Text", "", payload.selectedText, "");
  }
  if (payload.articleText) {
    lines.push("## Article", "", payload.articleText, "");
  }
  if (payload.pageText && payload.mode === "full") {
    lines.push("## Full Page", "", payload.pageText, "");
  }
  return lines.join("\n").trim();
}

function extractPayload(mode) {
  const normalizedMode = mode === "selection" || mode === "full" ? mode : "article";
  const selection = window.getSelection ? String(window.getSelection()).trim() : "";
  const article = document.querySelector("article, main");
  const articleText = (article?.innerText || "").trim();
  const pageText = (document.body?.innerText || "").trim();
  const title = document.title || location.href;

  const payload = {
    url: location.href,
    title,
    mode: normalizedMode,
    selectedText: selection,
    articleText,
    pageText,
  };
  payload.markdown = buildMarkdown(payload);
  payload.charCount = payload.markdown.length;
  return payload;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "vault-extract") return;
  try {
    const payload = extractPayload(message.mode);
    sendResponse({ ok: true, payload });
  } catch (error) {
    sendResponse({
      ok: false,
      error: error instanceof Error ? error.message : "Failed to extract page",
    });
  }
});

// --- Auto-clip ----------------------------------------------------------
// Once per page load, ask the background whether this URL/host is eligible
// for auto-clipping. If so, wait the configured dwell time (so the user has
// a chance to leave) and then submit. Each tab/load triggers at most once.

const MIN_DWELL_MS = 4_000;

let autoClipScheduled = false;
let autoClipTimer = null;

function clearAutoClipTimer() {
  if (autoClipTimer) {
    clearTimeout(autoClipTimer);
    autoClipTimer = null;
  }
}

async function scheduleAutoClip() {
  if (autoClipScheduled) return;
  autoClipScheduled = true;
  let decision;
  try {
    decision = await chrome.runtime.sendMessage({
      type: "vault-auto-clip-check",
      url: location.href,
    });
  } catch (_e) {
    return;
  }
  if (!decision?.allow) return;

  const { autoClipDwellMs } = await chrome.storage.local.get(["autoClipDwellMs"]);
  const dwell = Math.max(MIN_DWELL_MS, Number(autoClipDwellMs) || 10_000);

  autoClipTimer = setTimeout(async () => {
    if (document.visibilityState === "hidden") return;
    try {
      const payload = extractPayload("article");
      if (!payload.markdown || payload.markdown.length < 200) return;
      await chrome.runtime.sendMessage({
        type: "vault-auto-clip-submit",
        payload,
      });
    } catch (_e) {
      // background reports failures via badge; nothing to do here
    }
  }, dwell);
}

// Cancel pending auto-clip if user navigates away or hides the tab early.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") clearAutoClipTimer();
});
window.addEventListener("beforeunload", clearAutoClipTimer);

if (document.readyState === "complete") {
  void scheduleAutoClip();
} else {
  window.addEventListener("load", () => void scheduleAutoClip(), { once: true });
}
