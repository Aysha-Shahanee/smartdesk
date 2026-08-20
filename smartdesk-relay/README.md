# SmartDesk GitHub Relay

An independent, stateless Phase 1 relay. It verifies GitHub webhooks and sends a
minimal project-item notification to currently connected desktop clients. It
does not fetch issue metadata, perform predictions, store tasks, or queue events.

## Run

Set the variables shown in `.env.example`, then:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Run those commands from `smartdesk-relay/`. Environment files are not loaded by
the service itself; inject them through the process supervisor or shell.

## Endpoints and authentication

- `GET /health` returns only `{"status":"ok"}`.
- `POST /github/webhook` requires GitHub's `X-Hub-Signature-256` HMAC.
- `WS /ws` waits up to 10 seconds for a registration JSON message.

Registration format:

```json
{"type":"register","installation_id":123456,"token":"v1.<unix-expiry>.<hmac>"}
```

The token HMAC-SHA256 signs `v1:<installation_id>:<unix-expiry>` with
`SMARTDESK_RELAY_CLIENT_AUTH_SECRET`. Tokens should be minted locally by a
trusted SmartDesk component, use a short lifetime, and never be logged. The
installation ID is part of the signature, so changing it invalidates the token.

Every active connection registered to the matching installation receives the
notification. Failed and disconnected sockets are removed. With no active
client, the webhook is still accepted; Phase 1 has no offline queue.

For browser clients, configure `SMARTDESK_RELAY_ALLOWED_ORIGINS`. Native desktop
clients commonly omit `Origin`; authentication is still mandatory. Deploy only
behind TLS (`https`/`wss`) and a proxy with sensible request/rate limits.

## Tests

```powershell
python -m pytest -q
python -m tests.local_smoke
```
