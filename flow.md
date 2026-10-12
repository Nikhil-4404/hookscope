# Hookscope lifecycle flows

Reviewed 2026-10-12.

## Accounts and secrets
Operator configures its email/password in the terminal, issues a private invitation for a verified recipient email, and shares that capability through its existing trusted channel. The browser invitation uses a URL fragment. Registration validates and atomically consumes the invitation, creates the tenant and its usage row, and issues a tenant-bound session. Login derives identity from the stored session; client-supplied workspace IDs never grant access.

Users store secrets once, choose them in endpoint settings, and can replace endpoint references to rotate signing/verification keys. Secret deletion is rejected while an endpoint or pending attempt references it. Password changes revoke only that account's sessions. Forgotten-password recovery is an operator terminal reset after verifying identity outside the application.

## Capture and delivery
Provider POST → bounded body read → current token/active/signature policy check inside transaction → dedupe lookup → workspace and instance admission limits → event, usage counters and optional queued attempt commit → 202.

Worker chooses due work from the least recently served eligible workspace → atomic sending lease/claim → child resolves public DNS and pins HTTPS connection → exact body plus safe headers/stable ID and optional fresh relay signature → bounded response → outcome and quota counters commit. A retryable failure may enqueue a new scheduled attempt in the same transaction, preserving the previous outcome.

Retry delays are 5, 10, 20, 40 and 80 seconds plus 0–4 seconds jitter. 408/425/429, 5xx and transport failures qualify. 2xx succeed; other codes terminate automatic retry. Retry-After is not interpreted; each endpoint caps its own retry budget. After crash, expired leases may repeat receiver effects; ten crash executions terminate the attempt. Receiver idempotency is required.

Pause blocks receipt and future queue claims; resume allows due jobs. Manual replay uses current destination/signing reference/retry policy and preserves original bytes. Already queued attempts retain their snapshot. Deletion cannot retract outbound work already started.

## Failures and operations
Invalid signatures → 401; missing verification key → 503; unknown/foreign management IDs → 404; paused receipt → 410; oversize → 413; traffic/backlog → 429; storage capacity → 507; pending replay → 409. Readiness checks database and recent worker heartbeat. Backup uses SQLite online backup, validates integrity, and restores offline with its matching secret-encryption key. See operations.md for upgrades and launch verification.
