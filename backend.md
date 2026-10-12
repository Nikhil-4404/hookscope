# Hookscope backend contract

Reviewed 2026-10-12. app/main.py owns HTTP, app/security.py signatures/budgets, app/tenancy.py tenant identity/AES-GCM, app/delivery.py network/job behavior, app/store.py migrations/counters. requirements.md owns limits and flow.md owns lifecycle.

## API
Public: GET /api/health, /api/ready, /api/auth; POST /api/login, /api/register; POST /hooks/{token}. POST /api/setup is development loopback-only and disabled in production. API bodies are JSON except raw webhook receipt.

Authenticated: GET/POST /api/endpoints; PATCH/DELETE /api/endpoints/{id}; POST /api/endpoints/{id}/rotate and /test; GET /api/events and /api/events/{id}; DELETE /api/events/{id}; POST /api/events/{id}/replay; GET /api/stats and /api/operations; GET/POST /api/secrets; DELETE /api/secrets/{id}; POST /api/password and /api/logout. POST /api/demo is development-only.

Login: email/password. Register: email/password/invitation. Password change: current_password/password. Endpoint replacement PATCH accepts name,destination,active,verify_mode (none/github/hmac), incoming_secret_ref, signing_secret_ref,retries (0–5). It is a complete replacement, not a partial patch. Secret creation accepts name/value and returns only id/name. Tenant secret references are sec_ identifiers; legacy operators can also use restricted HOOKSCOPE_SECRET_ environment references. Non-legacy accounts cannot access operator environment secrets.

## Storage and migrations
Version 1 adds policy/scheduling/auth-limit/heartbeat data. Version 2 adds tenants, invitation hashes, encrypted secrets and endpoint/session ownership, assigning old records to legacy. Version 3 maintains usage totals and latest event status through triggers, including explicit child cleanup before cascades. Existing bytes and password hashes are preserved. Every additive migration first writes a consistent pre-migration backup. Unknown newer schema versions fail startup.

Schemas are executable in store.py; migration versions are immutable after release. For release promotion, back up before replacing the application. Migrations have been tested against disposable legacy schemas, not a user's cloud dataset. The maintenance check compares integrity, foreign keys, schema and usage totals.

Production startup validates that every stored tenant secret decrypts with the configured master key. The service holds an exclusive cross-process database lock; maintenance restore requires offline mode and rejects a running service. Restore validates schema 3/counters, preserves a pre-restore snapshot and revokes restored sessions. Details are in operations.md.

## Authenticity

GitHub: X-Hub-Signature-256 = sha256=HMAC(secret, raw body). HMAC relay: X-Hookscope-Timestamp plus X-Hookscope-Signature = v1=HMAC-SHA256(secret, timestamp + '.' + raw body); incoming timestamps must be within five minutes. Stable event ID/Idempotency-Key identify receiver effects; attempt IDs identify executions. These signatures authenticate Hookscope, not the original provider after forwarding. No arbitrary inbound Authorization/Cookie/provider-signature forwarding.

Network policy rejects local/private/mixed DNS answers, unsupported ports, credentials, fragments and control characters; validates TLS hostname/certificate; never follows redirects. A killed child enforces the total 20-second outbound deadline. Response bodies and raw event bodies can contain secrets; workspace authorization and host encryption/backup access remain important.

## Operations
Health is process liveness; ready includes DB/worker heartbeat. Authenticated operations return only workspace usage/queue data plus instance worker health. Delivery logs include attempt ID/status/code/execution count, not URL/body/secret. SQLAlchemy hides bind parameters in exception logs. Hourly retention uses bounded batches. No request access logging. Infrastructure limits and backup lifecycle are in operations.md.
