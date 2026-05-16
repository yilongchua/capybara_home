# Knowledge Vault Clipper

Load this folder as an unpacked Chrome extension.

Default target API:

- `http://127.0.0.1:8001/api/vault/clip`

Features:

- Popup clip flow with preview before submit
- Clip modes: `Article/Main`, `Selection`, `Full Page`
- Persistent settings for API base and topic hint
- Right-click context menu: clip page or clip selection
- Keyboard shortcut: `Alt+Shift+V` clips current page

Workflow:

1. Open any article page.
2. Click the extension icon and choose clip mode.
3. Use `Preview` to inspect the markdown payload.
4. Click `Clip Current Page` to enqueue into the vault.

Notes:

- If a page blocks content scripts, clipping can fail (for example browser internal pages).
- Clips are queued first, then processed by the existing vault ingestion pipeline.
