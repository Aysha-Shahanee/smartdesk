# SmartDesk GitHub data collection

The live collector exposes a framework-neutral integration boundary:

```python
from github_data_collection.webhook_handler import handle_github_webhook_event

# The host backend owns routing, signature verification, and GitHub App auth.
handle_github_webhook_event(payload, headers, token=installation_token)
```

`handle_github_webhook_event` detects logical transitions only. Full issue
metadata is fetched immediately afterward by `TaskMetadataService` and is not
taken from the webhook payload.

## Configure statuses

The integrating backend can call:

```python
from github_data_collection.status_mapping import set_status_mapping

set_status_mapping("PVT_project_node_id", {
    "Backlog": "NOT_STARTED",
    "Development": "ACTIVE",
    "Released": "DONE",
})
```

Valid logical states are `NOT_STARTED`, `ACTIVE`, `DONE`, and `OTHER`.
For local setup, edit `status_mapping.example.json`, then run:

```powershell
py -3 -m github_data_collection.configure_status_mapping PVT_project_node_id github_data_collection/status_mapping.example.json
```

Call `initial_sync.initial_sync(...)` when connecting or restarting. It walks
all cursor pages, records current state, and immediately fetches metadata for
items already mapped to `ACTIVE`. Run `python -m github_data_collection.main`
from the SmartDesk repository root, or use the installed
`github-data-collector` command, to start the polling
mode but now runs this sync and sends detected changes through the same core
handler.

SQLite access is isolated in `repositories.py`. The webhook, mapping, metadata,
and synchronization services accept repository/service dependencies so the
main SmartDesk backend can supply Postgres implementations later.

## Authentication assumption

This module accepts an already-issued token through service entry points or
falls back to `GITHUB_TOKEN`. GitHub App installation and token issuance are
intentionally outside this module and belong to the integrating backend.

Run from the SmartDesk repository root:

```powershell
py -3 -m github_data_collection.main
py -3 -m unittest discover -s github_data_collection/tests -v
```

Configuration follows SmartDesk's Pydantic Settings convention while remaining
independent. It reads `github_data_collection/.env` regardless of the current
working directory. Supported settings are `GITHUB_TOKEN`, `GITHUB_OWNER`,
`PROJECT_NUMBER`, `POLL_INTERVAL_SECONDS`, `GITHUB_DATABASE_URL`, and `LOG_LEVEL`.

## Public integration interface

SmartDesk imports the package rather than copying collector logic. Public APIs
are exported from `github_data_collection`, including OAuth helpers, project and
Status-option discovery, status mapping, initial sync, and event handling.

Collected lifecycle rows use distinct `started_at` and `completed_at` fields.
The legacy `detected_start_time` field remains populated for compatibility.
Schema upgrades are additive and existing start values are backfilled without
dropping stored rows.
