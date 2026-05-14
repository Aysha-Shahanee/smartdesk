# SmartDesk VS Code Extension

Tracks IDE activity and sends session events to the SmartDesk backend.

## Install

### Option 1 — VSIX (recommended, one command)

From the `vscode-extension/` folder:

```powershell
# 1. Install vsce (one time only)
npm install -g @vscode/vsce

# 2. Package
vsce package --no-dependencies

# 3. Install into VS Code
code --install-extension smartdesk-vscode-2.0.0.vsix
```

Reload VS Code when prompted (`Ctrl+Shift+P` → **Reload Window**).

> **Already done** — `smartdesk-vscode-2.0.0.vsix` is already built and installed.
> Only re-run steps 2–3 after making code changes.

### Option 2 — Development mode (F5)

Open the `vscode-extension/` folder in VS Code and press **F5**.  
A new Extension Development Host window opens with the extension loaded.

---
## What It Tracks

| Event | When |
|---|---|
| `started` | VS Code gains focus / file opened / workspace opened |
| `ended` | VS Code loses focus / window closed / workspace changes |

Each `ended` event includes **counters** accumulated during the session:
- `edit_count` — number of text edits
- `save_count` — number of file saves  
- `lines_added` / `lines_deleted`
- `file_switch_count` — number of editor tab switches
- `terminal_command_count` — terminal opens
- `debug_run_count` — debug sessions started
- `idle_sec` — seconds with no keyboard/mouse activity

## Configuration

In VS Code settings (`Ctrl+,`), search for **SmartDesk**:

| Setting | Default | Description |
|---|---|---|
| `smartdesk.backendUrl` | `http://127.0.0.1:8000` | Backend URL |
| `smartdesk.userId` | `local_user` | User ID |
| `smartdesk.enabled` | `true` | Enable/disable tracking |

## API Endpoint

```
POST http://127.0.0.1:8000/api/v1/ingest/vscode/event
```

Example payload:
```json
{
  "user_id": "local_user",
  "event": "ended",
  "instance_id": "uuid-here",
  "timestamp": "2026-05-12T11:30:00Z",
  "workspace_name": "smartdesk",
  "active_language": "python",
  "counters": {
    "edit_count": 42,
    "save_count": 7,
    "lines_added": 120,
    "lines_deleted": 30
  }
}
```
