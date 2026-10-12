# Hookscope

A working, single-user webhook development workspace. Receive requests, inspect original payloads, forward to a public HTTPS destination, and replay failed events with a separate delivery history.

## Start on Windows

Requirements: Node.js 22+ and Python 3.11+.

```powershell
Set-Location -LiteralPath 'D:\Gpt projs\Hookscope'
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Open **http://127.0.0.1:8787**. On first launch, choose your own password of at least 12 characters. No default account or password is installed. The script builds the frontend, serves it from FastAPI, and binds to loopback. Stop with Ctrl+C. If port 8787 is occupied by the preview from development, stop that process before running the script.

Click **Load demo workspace** to create labeled example events. Open an event from **Deployment listener**, inspect its failed 503 attempt, and replay it: the built-in flaky destination then returns 200. These simulators do not call an external service. Statistics include demo and test events.

## Included

- Password-protected management API with hashed passwords, opaque sessions, expiry, and login throttling.
- Create, edit, pause, delete, and copy receiving URLs for endpoints.
- POST `/hooks/{secret-token}` captures exact body bytes and redacted header metadata.
- Event inbox with search, endpoint/status filters, pagination, and live polling.
- Payload preview, exact-byte Base64 export, headers, responses, timing, and delivery history.
- Public HTTPS forwarding with certificate verification, public-IP validation, and a pinned destination connection.
- Persistent SQLite delivery queue, atomic claims, and recovery of expired worker leases.
- Manual replay with stable event identity, distinct attempt IDs, and a duplicate-action warning.
- Optional ingestion deduplication with `X-Hookscope-Idempotency-Key` (scoped per endpoint).
- Seven-day event retention, payload limits, receiving rate limits, and storage limits.
- Responsive React/TypeScript UI, locally bundled fonts, and integration tests.

## Receive a real event

Create an endpoint, copy its receiving URL, and POST to it from another local process. Quick start generates a PowerShell-compatible `curl.exe` command. Your external webhook provider cannot reach `127.0.0.1`: a real external integration needs a reachable HTTPS server or a tunnel.

The receiving URL is a **secret capability**. Anyone who knows it can submit events. This release does not verify provider-specific signatures; it does not establish who authored an incoming payload. Do not expose the management UI publicly without configuring hosting protections.

Incoming authorization, cookie, token, secret, API-key, and signature headers are redacted. Bodies remain unchanged and may contain sensitive information. Only content type, accept, user agent, and selected event metadata headers are forwarded. Original provider signatures will not authenticate this relay at the destination. Destination credentials and relay signing are planned enhancements.

## Delivery semantics

Capture and enqueue commit in one database transaction before returning HTTP 202. Capture-only endpoints do not enqueue delivery. The background worker makes one request per normal attempt; HTTP failures require manual replay. A redirect is a failed attempt and is never followed.

Each forwarded request carries:

| Header | Meaning |
|---|---|
| `X-Hookscope-Event-Id` | Stable ID for the captured event |
| `X-Hookscope-Attempt-Id` | Unique ID for this delivery attempt |
| `X-Hookscope-Replay` | `true` for a manual replay |
| `Idempotency-Key` | Stable event ID |

**Exactly-once delivery is not promised.** If a worker stops after the receiver accepts a request but before recording the result, lease recovery can deliver it again. The receiver must enforce deduplication. An idempotency header alone does not prevent duplicate side effects. Manual replay snapshots the endpoint's current destination; existing queued attempts retain their original destination.

Limits: 256 KiB per event; 120 newly captured events/minute/endpoint; 30 endpoints; 50,000 retained events; 512 MiB retained body bytes. A workspace quota returns 507. These logical limits do not bound database file growth, journal overhead, network traffic, or every server resource. Use infrastructure limits for public hosting. Retention cleanup runs hourly. Deletion removes active database records; filesystem backups and freed SQLite pages need separate lifecycle handling.

Destinations must use HTTPS port 443. Private, local, multicast, and non-public resolved addresses are rejected. The connection uses the validated IP directly with the hostname retained for TLS certificate verification. DNS resolution uses the operating system resolver. Socket operations have a 10-second timeout; body reading additionally has a 20-second delivery deadline. Response previews are capped at 32 KiB. No local destination forwarding is available yet.

## Development

Backend terminal:

```powershell
Set-Location -LiteralPath 'D:\Gpt projs\Hookscope\backend'
& '..\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload --no-access-log
```

Frontend terminal:

```powershell
Set-Location -LiteralPath 'D:\Gpt projs\Hookscope\frontend'
npm.cmd run dev
```

Open http://127.0.0.1:5173. Vite proxies the API and receiving URLs to the backend. Access logs are disabled because receiving URLs contain endpoint tokens. Do not enable them on a public proxy without masking these paths.

### Verification

```powershell
Set-Location -LiteralPath 'D:\Gpt projs\Hookscope\backend'
& '..\.venv\Scripts\python.exe' -m pytest -q
Set-Location -LiteralPath '..\frontend'
npm.cmd run build
npm.cmd audit
```

The tests use an isolated temporary database and a disabled background worker. They cover access controls, capture, byte preservation, redaction, replay, deduplication, queue recovery/concurrency, filtering, cascading deletion, quotas, and destination validation. The HTTPS transport test uses a controlled connection double; it does not demonstrate compatibility with every external provider. Browser visual verification was unavailable during initial implementation.

## Docker

Build the frontend first, then:

```powershell
docker compose build
docker compose run --rm hookscope python -m app.configure
docker compose up -d
```

The configure command prompts privately for a password. Browser first-run setup is deliberately restricted to loopback clients and cannot normally run through a Docker bridge. Data persists in a named volume, and the published port is bound to host loopback. Docker execution has not been verified on this machine.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `HOOKSCOPE_DATA` | `backend/data` | SQLite data directory |
| `HOOKSCOPE_ALLOWED_HOSTS` | `localhost,127.0.0.1,testserver` | Comma-separated accepted Host names; change for deployment |
| `HOOKSCOPE_ORIGINS` | empty | Additional exact browser origins for management writes |
| `HOOKSCOPE_SECURE_COOKIES` | unset | Set `1` when serving the browser over HTTPS |
| `HOOKSCOPE_DISABLE_WORKER` | unset | Set `1` only for controlled testing |

The deployment process must preserve your database and protect backups. Never commit `backend/data`. Do initial password setup locally or through `python -m app.configure` before exposing the server. Configure forwarded headers only for a trusted proxy. This release is designed for one user and a modest workload; login throttling is process-local.

## Architecture and next milestones

React + TypeScript + Vite → FastAPI → SQLAlchemy/SQLite. A background worker claims durable attempts and sends bounded HTTPS requests. The single backend serves the compiled UI, so the default startup has one origin and one port. SQLite keeps the initial self-hosted setup simple; multi-user hosting is a separate milestone.

Next priorities: provider signature verification; signed relay deliveries; endpoint token rotation; destination authentication; bounded automatic retries and dead-letter handling; public ingestion separated from private management; PostgreSQL and a dedicated worker; workspace membership; local tunnel forwarding. Validate these with actual integrations before expanding scope.
