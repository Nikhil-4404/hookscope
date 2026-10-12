# Backend contracts

Observed baseline: 2026-10-12. Source: `backend/app/main.py`, `store.py`, `delivery.py`, `configure.py`. Acceptance outcomes are tracked in [requirements.md](requirements.md) and [status.md](status.md).

## Interfaces

All bodies/responses are JSON unless noted. Exceptions normally expose `detail`. Management routes require the session except health/auth/setup/login.

| Route | Purpose / contract |
|---|---|
| `GET /api/health` | `{status, version}` liveness; does not prove worker/database readiness. |
| `GET /api/auth` | `{initialized, authenticated}`; no secret disclosure. |
| `POST /api/setup` | `{password}`; one-time local setup, sets session cookie; 409 if configured. |
| `POST /api/login`, `/api/logout` | Session creation/revocation; login accepts `{password}`. |
| `GET /api/endpoints` | Endpoint metadata, token, active flag, destination, event count; protected. |
| `POST /api/endpoints` | `{name, destination?, active?}` → endpoint, 201. |
| `PATCH /api/endpoints/{id}` | Complete replacement fields for name/destination/active despite PATCH naming. |
| `DELETE /api/endpoints/{id}` | Removes endpoint/history; idempotent `ok` response. |
| `POST /hooks/{token}` | Raw body capture → `{event_id, attempt_id?, duplicate}`, 202. |
| `GET /api/events` | `endpoint`, `status`, `search`, `page` → `{items,total,page}`; 50 per page. |
| `GET /api/events/{id}` | Text preview, Base64 original body, redacted headers, attempts, current destination. |
| `POST /api/events/{id}/replay` | Enqueue replay → `{attempt_id}`, 202; 409 when inactive/no destination/pending. |
| `DELETE /api/events/{id}` | Remove event and its attempts, `ok`. |
| `GET /api/stats` | Retained counts, latest attempt statuses, average attempt latency, hourly activity. |
| `POST /api/demo` | Create labeled simulator endpoints/events, 201; not all-or-nothing across all samples. |
| `POST /api/endpoints/{id}/test` | `{body: string}` through capture pipeline, source `test`, 202. |

Header `X-Hookscope-Idempotency-Key` is optional, at most 200 characters, and deduplicates while the event is retained. Reusing an ID with different content returns the earlier event rather than comparing bodies. Empty-string key behavior requires an explicit edge-case check.

## Data model

| Table | Important fields / invariant |
|---|---|
| settings | key/value, one stored password hash with salt |
| sessions | hash of cookie token, expiry |
| endpoints | ID, name, unique secret token, destination, active, creation time |
| events | ID, endpoint FK, original body BLOB, redacted headers JSON, kind/source, optional external ID |
| attempts | event FK, state, timing/code/response/error, destination snapshot, replay flag, lease, execution count |

Events have `UNIQUE(endpoint_id, external_id)`. Foreign-key deletion cascades endpoint → events → attempts. Receipt/initial enqueue are one transaction; worker claim and completion are separate transactions. Completion uses a lease guard against overwriting a newer claim. See [flow.md](flow.md) for semantics.

## Forwarding boundary

HTTPS port 443, no userinfo/fragment, no private/local/multicast addresses. Reject every resolved answer if any is non-public, connect directly to a validated IP, and preserve hostname for TLS verification. Redirects are not followed. Exact body bytes are POSTed; transport/header identity is not preserved wholesale.

Allowlist: content type, accept, user agent, GitHub event/delivery metadata, event type, request ID. Add stable event/idempotency identity and attempt/replay identity. Provider credentials/signatures are not forwarded; no destination-authentication or relay-signature configuration exists.

Responses are UTF-8 previews capped at 32 KiB. Socket/body timing limits are described in [requirements.md](requirements.md). OS DNS resolution and slow header behavior need stronger whole-operation deadline validation before a broad reliability claim.

## Security and operations

PBKDF2-SHA256 with random salt protects the password. Sessions use random opaque values with database hashes. Header redaction matches configured name fragments and is best-effort; bodies/responses are not redacted. Default loopback serving, host checks, same-origin checks, and response headers support the local boundary; they are not a completed public-deployment security review.

Schema bootstrap has no migrations. Worker exception logging exists; access logs are disabled to avoid token paths. There is no structured audit trail, queue-health endpoint, tested backup/restore, or production telemetry. Logical quotas do not prevent request floods or cap response/attempt accumulation and total SQLite file size. Tests are isolated from real workspace data. See [status.md](status.md) for remaining checks and debt.
