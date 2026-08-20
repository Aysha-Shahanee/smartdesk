# Task Duration Prediction deployment handoff

## 1. Component deployment status

The GitHub Task Duration Prediction component is package- and deployment-ready.
Its model, preprocessing, GitHub integration, relay transport, lifecycle logic,
and duration calculations require no redesign.

Creating the final Windows application, bundling and starting the local backend,
hosting the public relay, and coordinating full-application database migrations
remain project-level deployment responsibilities.

## 2. Production architecture

```text
GitHub
  | webhook
  v
Public SmartDesk Relay
  | authenticated WebSocket
  v
Installed SmartDesk
  |
  v
Local GitHub task processing
  |
  v
Local LightGBM P10 / P50 / P90
  |
  v
Local Time Spent / Remaining Estimate
  |
  v
Dashboard
```

The relay is notification transport only. It verifies the GitHub webhook and
forwards minimal identifiers to the matching installation. SmartDesk fetches
authoritative task metadata directly from GitHub and performs all processing,
prediction, time calculation, and persistence locally.

## 3. Development architecture

```text
GitHub
  -> Cloudflare Quick Tunnel
  -> POST /api/v1/integrations/github/webhook
  -> existing local GitHub processing
```

Use:

```dotenv
SMARTDESK_GITHUB_MONITOR_MODE=webhook
```

`start-smartdesk-dev.ps1` and `stop-smartdesk-dev.ps1` remain supported. The
start script launches the backend, frontend, and Quick Tunnel, discovers the
temporary public URL, and updates only the GitHub App webhook URL. The direct
endpoint continues to require `X-Hub-Signature-256` authentication.

## 4. Production relay mode

Use:

```dotenv
SMARTDESK_GITHUB_MONITOR_MODE=relay
```

The installed SmartDesk backend opens an outbound authenticated WebSocket to the
relay; no public local port or Cloudflare tunnel is required for event delivery.
SmartDesk uses its preserved installation ID for registration, then fetches
current status and issue metadata directly from GitHub. Direct and relay event
paths converge on the same processing service and persisted idempotency checks.

`SMARTDESK_GITHUB_MONITOR_MODE` is authoritative. The deprecated
`SMARTDESK_RELAY_ENABLED` setting must not be used to select transport.

## 5. Runtime model artifacts

Bundle these exact files from `backend/model_artifacts/github_effort/`:

| Category | File | Purpose |
|---|---|---|
| P10 model | `model_low.txt` | Low estimate |
| P50 model | `model_typical.txt` | Typical and main Initial Estimate |
| P90 model | `model_high.txt` | High estimate |
| Preprocessing | `tfidf_vectorizer.pkl` | Fitted text vectorizer |
| Preprocessing | `svd_reducer.pkl` | Fitted 40-component text reducer |
| Preprocessing | `label_categories.json` | Label category inventory |
| Fallbacks | `inference_fallbacks.json` | Global and label duration fallbacks |
| History | `repo_stats.json` | Repository history features |
| History | `repo_label_stats.json` | Repository/label history features |
| Manifest | `manifest.json` | Ordered feature schema and model metadata |
| Integrity | `preprocessing_manifest.json` | Preprocessing rules and SHA-256 inventory |

The runtime expects exactly 56 features. P50 remains the main Initial Estimate.
Inference performs no retraining and needs no original training dataset. The
three LightGBM `.txt` files must remain LF-only. Do not disable integrity checks
or regenerate hashes unless an artifact is intentionally replaced and reviewed.

## 6. Model resource path

The source-checkout default is:

```text
backend/model_artifacts/github_effort
```

For a packaged application, either preserve
`<resource-root>/model_artifacts/github_effort` and set the resource root, or
set an explicit model directory:

```dotenv
SMARTDESK_GITHUB_RESOURCE_ROOT=
SMARTDESK_GITHUB_MODEL_ARTIFACT_DIR=
```

An absolute artifact directory is accepted. A relative override resolves from
`SMARTDESK_GITHUB_RESOURCE_ROOT`, not the process working directory. The final
installer resource layout is intentionally left to the project leader.

## 7. Required configuration

Never commit real values for secrets.

### Local model inference

- `SMARTDESK_GITHUB_RESOURCE_ROOT` — optional packaged backend resource root
- `SMARTDESK_GITHUB_MODEL_ARTIFACT_DIR` — optional absolute or resource-relative override

### GitHub App integration

- `SMARTDESK_GITHUB_APP_ID`
- `SMARTDESK_GITHUB_APP_SLUG`
- `SMARTDESK_GITHUB_APP_PRIVATE_KEY`
- `SMARTDESK_GITHUB_CALLBACK_URL`
- `SMARTDESK_GITHUB_OAUTH_CLIENT_ID` — required for organization user authorization
- `SMARTDESK_GITHUB_OAUTH_CLIENT_SECRET` — required for organization user authorization
- `SMARTDESK_GITHUB_USER_CALLBACK_URL` — required for organization user authorization
- `SMARTDESK_FRONTEND_URL`

The human OAuth flow establishes `github_login`; the installation account is
stored separately. Do not substitute an organization or installation-owner
login for the verified human identity used by assignee filtering.

### Production relay

SmartDesk backend:

- `SMARTDESK_GITHUB_MONITOR_MODE=relay`
- `SMARTDESK_RELAY_URL` — use `wss://` in production
- `SMARTDESK_RELAY_CLIENT_AUTH_SECRET`
- `SMARTDESK_RELAY_CONNECT_TIMEOUT_SECONDS` — optional
- `SMARTDESK_RELAY_RECONNECT_MIN_SECONDS` — optional
- `SMARTDESK_RELAY_RECONNECT_MAX_SECONDS` — optional

Standalone relay:

- `SMARTDESK_RELAY_GITHUB_WEBHOOK_SECRET`
- `SMARTDESK_RELAY_CLIENT_AUTH_SECRET` — must match the backend
- `SMARTDESK_RELAY_HOST` — optional
- `SMARTDESK_RELAY_PORT` — optional
- `SMARTDESK_RELAY_MAX_WEBHOOK_BYTES` — optional
- `SMARTDESK_RELAY_REGISTRATION_TIMEOUT_SECONDS` — optional
- `SMARTDESK_RELAY_ALLOWED_ORIGINS` — optional, comma-separated
- `LOG_LEVEL` — optional

### Development only

- `SMARTDESK_GITHUB_MONITOR_MODE=webhook`
- `SMARTDESK_GITHUB_WEBHOOK_SECRET` — verifies the direct local webhook

The development launcher reads the GitHub App credentials above to update the
temporary webhook URL. Do not use a production relay secret as a development
placeholder unless that is an intentional secret-management decision.

## 8. Runtime dependencies

### Model inference

- LightGBM 4.x
- pandas 2.x
- NumPy 1.24+
- scikit-learn 1.3+

### GitHub integration

- `github_data_collection`
- requests
- SQLAlchemy
- pydantic-settings
- python-dotenv
- PyJWT with crypto support
- the existing FastAPI/Pydantic backend runtime

### SmartDesk relay client

- websockets 15-17
- the existing asynchronous backend runtime

### Standalone relay server

- FastAPI
- Pydantic 2.x
- Uvicorn with standard extras

Install the full SmartDesk backend requirements for the final application.
Bundle or install `github_data_collection` as a production Python package; do
not rely on the editable `-e ../github_data_collection` development path at
runtime. Pytest and HTTPX in the relay requirements are test dependencies, not
requirements for serving relay traffic.

## 9. Privacy boundary

The public relay carries only:

- installation ID
- Project item ID
- Project ID
- content ID
- action

The following remain between GitHub and the local SmartDesk installation:

- issue title and description
- labels and assignees
- model features and P10/P50/P90 outputs
- IDE and OS activity
- Time Spent and Remaining Estimate
- SQLite task, lifecycle, and prediction data

The relay must not log or persist full GitHub webhook payloads.

## 10. GitHub App production configuration

Final deployment requires permanent production values for:

- the GitHub App webhook URL, targeting the public relay `/github/webhook`
- the installation callback URL, targeting the installed/deployed backend flow
- the human OAuth callback URL
- the frontend URL used after setup/authorization

Choose these URLs only after the final relay domain and application callback
strategy are known. Do not copy temporary Quick Tunnel URLs into production.

## 11. Relay deployment responsibilities

The project leader must:

- deploy the relay behind HTTPS/WSS;
- provide a permanent relay URL;
- generate, store, and rotate strong independent production secrets;
- configure reverse-proxy request-size and rate limits;
- define the permitted browser-origin policy, if browser clients are used;
- update the GitHub App webhook URL and matching webhook secret;
- monitor relay availability without logging private webhook payloads.

Current limitations:

- relay delivery is ephemeral and has no persistent/offline queue;
- registration tokens have a 60-second replay window;
- artifact hashes detect corruption but do not provide signed authenticity.

## 12. Final application packaging responsibilities

Already ready:

- P10/P50/P90 Task Duration models and preprocessing
- startup readiness and package-relative artifact resolution
- GitHub App integration and authoritative metadata fetching
- verified-human ownership filtering
- direct webhook and relay transport modes
- SmartDesk relay client and standalone relay server
- lifecycle/prediction idempotency
- Time Spent, Remaining Estimate, overrun, and DONE behavior

Still required from the project leader:

- bundle and start the local FastAPI backend with SmartDesk;
- bundle the backend Python runtime and dependencies;
- bundle/install `github_data_collection`;
- bundle all 11 Task Duration runtime artifacts;
- choose and configure the application resource directory;
- create the final Electron/Windows executable and installer;
- deploy and secure the relay;
- configure production secrets and permanent URLs;
- establish application-wide migration execution for install and upgrade.

## 13. Database migration note

The audit found two repository heads:

- `0016_github_identity`
- `0018_reco_shadow`

The Task Duration/GitHub migration path is valid and the audited local database
was current at `0016_github_identity`. `0018_reco_shadow` belongs to the
recommendation subsystem. Converging the full application's migration graph and
deciding when migrations run in installed applications are project-level
deployment responsibilities. Do not create a merge migration solely from this
component handoff without coordinating with the recommendation owner.

## 14. Deployment verification checklist

- [ ] All 11 runtime artifacts are bundled in the configured directory.
- [ ] Startup readiness reports valid hashes, all three models loadable, and 56 features.
- [ ] The three LightGBM model files remain LF-only.
- [ ] The local backend starts automatically with the installed application.
- [ ] The relay is reachable through HTTPS/WSS with production secrets.
- [ ] Permanent GitHub App webhook and callback URLs are configured.
- [ ] Personal installation setup succeeds.
- [ ] Organization installation plus human OAuth authorization succeeds.
- [ ] A signed webhook/relay notification reaches local SmartDesk.
- [ ] Connected-user and connected-user-plus-teammate assignments are tracked.
- [ ] Teammate-only and unassigned items are ignored.
- [ ] An assigned ACTIVE task produces finite P10/P50/P90 once.
- [ ] Time Spent updates with expected attribution and ambiguity behavior.
- [ ] Remaining Estimate and overrun behavior use the P50 baseline.
- [ ] DONE closes the lifecycle, and reopening creates one new lifecycle/prediction.
- [ ] Duplicate direct/relay notifications do not duplicate lifecycle or prediction rows.
