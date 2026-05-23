# Knowledge Vault Clipper

Load this folder as an unpacked Chrome extension.

Default target API:

- `http://127.0.0.1:8001/api/vault/clip`

## Features

- **Auto-clip mode (on by default)** — every public page you dwell on long enough is automatically captured and enqueued; opt out from the popup toggle.
- Manual clip modes: `Article/Main`, `Selection`, `Full Page` with preview.
- Right-click context menu: clip page or clip selection.
- Keyboard shortcut: `Alt+Shift+V` on Windows/Linux, `⌘+Shift+V` on macOS.
- Queue confirmation: green ✓ toolbar badge, desktop notification, and an in-popup pill on every successful clip.
- Persistent settings for API base, topic hint, dwell time, allowlist, and blocklist.

## Auto-clip behaviour

- Enabled by default on every http(s) page; sensitive hosts are blocked out of the box (`mail.google.com`, `accounts.google.com`, `login.live.com`, `outlook.*`, `chrome.google.com`, `127.0.0.1`, `localhost`).
- Dwell time defaults to 10 seconds — the extension waits this long before sending so transient navigations don't clip.
- Each URL is auto-clipped at most once every 24 hours.
- To opt out, open the popup and switch the "Auto-clip pages" toggle off.

## Install

1. Open `chrome://extensions` (Chrome blocks websites from opening this URL directly, so paste it into the address bar).
2. Toggle **Developer mode** on (top-right).
3. Click **Load unpacked** and pick the `browser_extensions/knowledge-vault-clipper` folder from this repo.
4. Open the popup and confirm the API Base matches your backend.

## Manual clipping

1. Open any article page.
2. Click the extension icon and choose a clip mode.
3. Use `Preview` to inspect the markdown payload.
4. Click `Clip Current Page` to enqueue into the vault.

## Notes

- If a page blocks content scripts (e.g. browser-internal pages), clipping fails on that page.
- Clips are queued first, then processed by the existing vault ingestion pipeline.
- The extension uses `chrome.notifications` for the queued confirmation — Chrome may prompt for permission the first time.
