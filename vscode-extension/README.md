# SmartDesk VS Code Extension

Tracks VS Code session activity and sends repo-aware events to the local
SmartDesk backend.

## Create and Install a VSIX

From the repository root:

```powershell
cd vscode-extension
npm install -g @vscode/vsce
vsce package --no-dependencies
code --install-extension .\smartdesk-vscode-2.0.0.vsix
```

Reload VS Code when prompted (`Ctrl+Shift+P` -> `Reload Window`).

## Development Mode

Open `vscode-extension/` in VS Code and press `F5`.

## What It Tracks

| Event | When |
|---|---|
| `started` | VS Code starts or regains focus with a workspace/file |
| `state` | Periodic heartbeat while the session is active |
| `ended` | VS Code loses focus, shuts down, or the workspace changes |

Session payloads include:

- counters for edits, saves, lines added/deleted, file switches, terminal opens,
  debug runs, and idle seconds
- `repo_id`, a SHA-256 hash of the Git remote URL with repo path hash fallback
- `git_branch`, when available
- active file path/name/language
- `extra_data.changed_files`, including workspace file create/change/delete events
  even when files are not open in an editor

AI-generated edits are not labelled separately. If they modify files through VS
Code or the workspace filesystem, they are counted as normal development changes.

## Configuration

In VS Code settings (`Ctrl+,`), search for `SmartDesk`:

| Setting | Default | Description |
|---|---|---|
| `smartdesk.backendUrl` | `http://127.0.0.1:8000` | Backend URL |
| `smartdesk.userId` | `local_user` | User ID |
| `smartdesk.enabled` | `true` | Enable/disable tracking |

## API Endpoint

```text
POST http://127.0.0.1:8000/api/v1/ingest/vscode/event
```