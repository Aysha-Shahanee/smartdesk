# GitHub integration architecture and deployment requirements

## Current implementation

SmartDesk uses a GitHub App installation and organization-owned Projects v2.
The integrated application is webhook-driven; the collector's polling mode is
retained only for standalone testing or recovery.

The verified flow is:

1. The SmartDesk user opens Settings and starts GitHub App installation.
2. GitHub redirects to the configured SmartDesk callback after installation.
3. SmartDesk associates the installation with `DEFAULT_USER_ID` (`local_user`).
4. The installation account's projects are discovered directly with
   `organization(login: $login).projectsV2`, including cursor pagination.
5. The user selects one Project and maps its actual Status options to
   `NOT_STARTED`, `ACTIVE`, `DONE`, or `OTHER`.
6. A signed `projects_v2_item` webhook is deduplicated and its authoritative
   field named `Status` is fetched through GraphQL.
7. On entry to ACTIVE, issue metadata is fetched using a short-lived
   installation token, a lifecycle is created, and the retained LightGBM model
   produces one initial duration prediction for that lifecycle.
8. DONE completes the lifecycle without replacing its initial prediction;
   DONE to ACTIVE creates a new lifecycle and prediction.

Installation tokens are minted when required and are never persisted. Draft
issues and pull requests are acknowledged but excluded from issue-duration
prediction. The offline `github_issue_dataset_builder` is not a runtime
dependency.

## GitHub App and deployment configuration

GitHub App permissions are defined by the App developer. The current minimum is
organization **Projects: read-only** and repository **Issues: read-only**, with
the **Project v2 item** event subscribed. During installation, a user or
organization administrator chooses the installation account and allowed
repositories. Organization approval may be required. SmartDesk cannot access an
organization where the App is not installed.

Production configuration must provide:

- `SMARTDESK_GITHUB_APP_ID`
- `SMARTDESK_GITHUB_APP_SLUG`
- `SMARTDESK_GITHUB_APP_PRIVATE_KEY` through secret storage
- `SMARTDESK_GITHUB_WEBHOOK_SECRET` through secret storage
- `SMARTDESK_GITHUB_CALLBACK_URL=https://<backend>/api/v1/integrations/github/callback`
- `SMARTDESK_FRONTEND_URL=https://<frontend>`
- `SMARTDESK_GITHUB_MONITOR_MODE=webhook`
- `VITE_BACKEND_URL=https://<backend>` at frontend build time
- production `CORS_ORIGINS` containing only approved frontend origins

The GitHub App Setup URL must equal the callback URL. Its webhook URL must be
`https://<backend>/api/v1/integrations/github/webhook`. Temporary tunnel URLs
are local-development configuration only and must not be committed. Cloudflare
Quick Tunnel hostnames expire or change whenever the temporary tunnel is
recreated, so local testers must update the GitHub App webhook URL each time.
Production must use a permanent deployed HTTPS backend/webhook URL.

## Current identity boundary

SmartDesk currently has no application login boundary. The backend uses
`DEFAULT_USER_ID=local_user`, and the GitHub connection, selected Project,
collector lifecycle, and prediction are associated with that local identity.
This is intentionally preserved until the main application has real auth.

## Future multi-user authentication requirements

Before multi-user deployment:

- Replace `DEFAULT_USER_ID` with the authenticated SmartDesk user ID.
- Associate each GitHub connection and installation with that authenticated
  user and enforce ownership on every connection, Project, lifecycle, and
  prediction operation.
- Decide whether GitHub user OAuth is also required to verify installer identity
  in addition to GitHub App installation.
- Use managed production secret storage and key rotation.
- Handle organization installation approval and revoked/suspended installations.
- Define disconnect versus GitHub-side revoke behavior.
- Decide whether a user may connect multiple installations and select one or
  multiple Projects; the current schema intentionally supports one selected
  Project per local user.

## Dashboard requirements

Settings is the primary user interface for connection state, connected account,
Project selection, Status mapping, and disconnect/reconnect. The backend-served
`/api/v1/integrations/github/setup` page remains a development/setup diagnostic
utility.

The normal dashboard displays only user-relevant ACTIVE issue information:
title, repository, logical status, lifecycle start, and the typical initial
duration prediction. Internal GraphQL IDs, installation IDs, model version,
prediction errors, and low/high quantiles remain available to backend
diagnostics but are not shown by default.

## Deferred remaining-time work

Remaining-time calculation is not implemented. Future work must define task
attribution, reuse SmartDesk's existing activity/focus and active/idle signals,
calculate remaining time from an agreed contract, and display it alongside—not
in place of—the immutable initial prediction. It must not introduce a separate
active/idle detector.

The Prediction page therefore treats task-specific Time Spent as unavailable.
Before that value can be shown, a backend attribution service must associate
SmartDesk's authoritative activity segments with a specific GitHub lifecycle
(including active/idle boundaries and concurrent-task rules) and expose the
result through an API. Elapsed wall-clock time is not an acceptable substitute.
