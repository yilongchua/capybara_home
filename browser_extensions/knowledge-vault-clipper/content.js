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
