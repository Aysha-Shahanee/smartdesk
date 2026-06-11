# SmartDesk IDE Extension

Tracks IDE session activity and sends repo-aware events to the local
SmartDesk backend. Works in any VS Code-based IDE: **VS Code, Antigravity,
Cursor, Windsurf**, and others — the IDE identity is reported in `ide_name`.

## Build and Install

From this folder:

```powershell
npx --yes @vscode/vsce package --allow-missing-repository
```

This creates `smartdesk-ide-<version>.vsix`. Install it:

- **VS Code:** `code --install-extension .\smartdesk-ide-3.1.0.vsix`
- **Antigravity / other VS Code-based IDEs:** Extensions panel
  (`Ctrl+Shift+X`) → `···` menu → **Install from VSIX…** → pick the file

Restart the IDE (or run `Developer: Reload Window`) after installing.

## Collection Rules

| Situation | Behavior |
|---|---|
| IDE window focused | Collected normally (`is_foreground=1`) |
| IDE blurred, AI still editing | Collected as a separate row, `is_foreground=0`, `collection_reason="background_ai"` |
| IDE blurred, idle 60s | Session ends; nothing is collected |

Sessions split at every focus boundary — one row never mixes foreground and
background time.

## Events

| Event | When |
|---|---|
| `started` | Activation, focus gained, or first edit (incl. background AI edit) |
| `state` | Heartbeat every 45 seconds while a session is open |
| `ended` | Blur, refocus boundary, blur-idle timeout, workspace change, shutdown |

Payloads include:

- `ide_name`, `process_id` **and** `parent_process_id` (the backend matches
  either against the OS foreground PID)
- counters: edits, saves, lines added/deleted, file switches, terminal opens,
  debug runs, idle seconds
- per-file edit detail (`edited_files_json`) including files edited by AI
  while the window was blurred, language breakdown, and `dominant_language`
- `repo_id` (SHA-256 of the Git remote URL), `git_branch`
- active file path/name/language (last-known value is kept when focus sits on
  a non-editor panel)
- disk-level file create/change/delete events from the workspace watcher

## Configuration

In IDE settings (`Ctrl+,`), search for `SmartDesk`:

| Setting | Default | Description |
|---|---|---|
| `smartdesk.backendUrl` | `http://127.0.0.1:8000` | Backend URL |
| `smartdesk.userId` | `local_user` | User ID |
| `smartdesk.enabled` | `true` | Enable/disable tracking |

## API Endpoint

```text
POST http://127.0.0.1:8000/api/v1/ingest/ide/event
```
