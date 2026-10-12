# Hookscope release requirements

Reviewed 2026-10-12. Production implementation and deployed readiness are separate acceptance boundaries.

| ID | Observable acceptance |
|---|---|
| AC-01 | Login requires the account email/password; sessions are hashed, expire after 12 hours and are revoked on logout/password reset. Durable per-identity authentication budgets survive process restart. |
| AC-02 | Each account can create/edit/pause/delete endpoints; secret receiving URLs can be rotated. Unknown or foreign management IDs return 404. |
| AC-03 | Persist exact request bytes and redacted headers before 202. Unknown tokens return 404; paused/rotated tokens cannot enqueue new work. |
| AC-04 | Non-empty dedupe keys identify one event per endpoint; verified GitHub delivery IDs also deduplicate. Empty keys do not collapse unrelated events. |
| AC-05 | Search/filter/page/detail/statistics/operations/export reveal only the caller's workspace. |
| AC-06 | Real HTTPS delivery verifies certificates, pins validated public DNS answers and does not follow redirects. Stored outcomes distinguish HTTP responses from transport errors. |
| AC-07 | Manual replay preserves event/body identity and creates a distinct attempt. Only one pending attempt per event is admitted, within attempt quotas. |
| AC-08 | Atomic leases recover interrupted deliveries, bounded crash executions terminate repeated failure, paused work waits, and workspace scheduling interleaves tenants. |
| AC-09 | Enforce payload/rate/event/body+response/attempt/account/secret/backlog/global quotas. Counter changes participate in capture/delivery/delete transactions. |
| AC-10 | Optional incoming signatures reject altered bodies, invalid signatures, unavailable secrets and expired HMAC timestamps. Incoming credentials/signatures are never forwarded. |
| AC-11 | Browser JSON export includes Base64 that recovers exact bytes and retains attempt history. |
| AC-12 | Browser login/create/send/inspect/replay work; dialogs receive/trap/restore focus, Escape closes them, narrow layouts retain logout. |
| AC-13 | Reproducible image builds frontend and backend; production fails closed without explicit HTTPS host, secure cookies, encryption key, owner and compiled assets. |
| AC-14 | Invitations are email-bound, hashed, expire after 24 hours and can be consumed once. Each new account starts with a private workspace. |
| AC-15 | Secret values use AES-256-GCM with tenant/secret identity as associated data, are never returned, and cannot be referenced by another tenant. |
| AC-16 | Additive migrations preserve existing accounts/events/attempts; online backups pass integrity/counter checks; restored data and encrypted secrets reopen with the matching key. |
| AC-17 | Retryable failures schedule at most the chosen 0–5 retries; backoff is exponential with jitter; permanent 4xx do not retry automatically. |
| AC-18 | Total outbound execution is killed after 20 seconds, including blocking DNS/TLS/headers/body; no delivery child remains after timeout. |
| AC-19 | Hosted deployment passes image/runtime/restart/HTTPS/gateway/provider/backup/monitoring checks on the chosen server before public-ready status. |

## Trust and limits
Accounts own separate workspaces; there are no collaborator roles in this release. Receiving URLs are capabilities. Choose signature verification when provider authentication is required. HMAC timestamps alone do not deduplicate replay within the five-minute window: send an idempotency key too. GitHub signatures have no timestamp; GitHub delivery ID dedupe lasts only while the event is retained.

Per workspace: 30 endpoints, 50,000 events, 512 MiB combined payload and response bytes, 150,000 attempts, 100 attempts/event, 1,000 pending deliveries, 60 encrypted secrets. Per instance: 100 accounts, 1,000 invitations, 500,000 events, 4 GiB combined payload/response bytes and 1,000,000 attempts. Captures: 256 KiB, 120 new events/minute/endpoint, 15-second upload deadline. Response preview: 32 KiB before UTF-8 replacement/truncation notice. Logical limits exclude DB indexes/WAL, migration backups, logs and image storage.

Retention: seven days, hourly cleanup in batches of 500. Sessions: maximum 20/account. Login/password/registration identity budgets: 10 accepted checks per five minutes; auth bucket count is capped. Gateway applies additional IP budgets and connection/header/body timeouts. Account lockout can be abused for denial of service; operators can revoke/reset an account locally.

Delivery is at-least-once across crashes. There is no global event ordering. A request already in flight cannot be recalled by pause/delete. Ordinary HTTP retries are opt-in; every retry is visible. Synthetic demonstrations are disabled and existing simulator endpoints paused at production startup. Event counts retain historical demo labels; response averages exclude simulator destinations.

Single SQLite writer and sequential worker constrain this release. The local benchmark does not establish multi-tenant concurrency, internet delivery capacity, Linux/ARM behavior or availability. Public signup, billing and horizontal scaling are not silently included in AC-19.
