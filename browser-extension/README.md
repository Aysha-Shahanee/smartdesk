# SmartDesk Browser Extension

Tracks active browser tab sessions and sends them to the SmartDesk backend.

## Install

**Chrome / Edge / Brave:**

1. Open `chrome://extensions/` (or `edge://extensions/`)
2. Enable **Developer mode** (top right toggle)
3. Click **Load unpacked**
4. Select this folder (`browser-extension/`)

**Firefox:** Load as temporary extension via `about:debugging`.

## What It Tracks

| Event | When |
|---|---|
| `started` | User switches to a new tab or URL changes |
| `ended` | Tab closes, URL changes away, or browser loses focus |
| `state` | Heartbeat every 30 seconds while tab is active |

Sessions shorter than **3 seconds** are silently dropped (matches backend filter).

## Domain Categories

| Category | Examples |
|---|---|
| `Focused` | github.com, stackoverflow.com, docs.*, jira.* |
| `Distracted` | youtube.com, reddit.com, twitter.com, instagram.com |
| `Communication` | slack.com, discord.com, mail.google.com, zoom.us |
| `Neutral` | Everything else |

## Popup Settings

Click the extension icon to configure:

| Setting | Default | Description |
|---|---|---|
| Backend URL | `http://127.0.0.1:8000` | SmartDesk backend URL |
| User ID | `local_user` | User ID sent with events |
| Enabled | `true` | Enable/disable tracking |

The popup shows a **green dot** when the backend is reachable, **red** when not.

## API Endpoint

```
POST http://127.0.0.1:8000/api/v1/ingest/browser/event
```

Example payload:
```json
{
  "user_id": "local_user",
  "event": "started",
  "browser_name": "Chrome",
  "timestamp": "2026-05-12T11:30:00Z",
  "browser_window_id": 1,
  "tab_id": 42,
  "domain": "github.com",
  "url": "https://github.com/user/repo",
  "title": "user/repo — GitHub",
  "category": "Focused"
}
```
