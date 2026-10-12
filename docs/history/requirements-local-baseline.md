# Hookscope requirements

Baseline: 2026-10-12. These requirements describe the current local increment unless explicitly marked later. Verification coverage and limitations are in [status.md](status.md).

| ID | Requirement | Acceptance criterion |
|---|---|---|
| REQ-01 / AC-01 | Protect workspace management | Unauthenticated management returns 401; one-time setup accepts a 12–128-character password; correct login grants a session; logout revokes it. |
| REQ-02 / AC-02 | Manage receiving endpoints | Create named endpoints with secret URLs; update destination/name; pause rejects new receipt; deletion removes associated history. |
| REQ-03 / AC-03 | Capture requests faithfully | Valid POST is persisted before 202; body bytes remain unchanged; configured sensitive headers are redacted; unknown URL returns 404. |
| REQ-04 / AC-04 | Deduplicate explicitly identified events | Repeated `X-Hookscope-Idempotency-Key` on one endpoint returns the same event ID and does not add a delivery attempt. |
| REQ-05 / AC-05 | Inspect and find events | Filter by endpoint/latest status, search type/ID/endpoint name, and return at most 50 records per page; expose payload, headers, and attempts. |
| REQ-06 / AC-06 | Record delivery outcomes | Simulator failure is recorded as 503/failed; success as 200/delivered. Distinct attempts retain their destination, timing, and response/error. |
| REQ-07 / AC-07 | Replay deliberately | Replay keeps original body/event identity, creates a distinct attempt, and preserves prior outcomes; one pending attempt per event is enforced. UI warns about duplicate actions. |
| REQ-08 / AC-08 | Recover interrupted work | Expired sending lease can be reclaimed; concurrent worker claims do not process the same live attempt twice. Receiver deduplication remains necessary. |
| REQ-09 / AC-09 | Bound captures and storage | Payload over 256 KiB returns 413; quota exhaustion returns 507; receiving rate/retention follow the documented limits. See backend contract for exact scope. |
| REQ-10 / AC-10 | Restrict destinations | Reject local/private destinations, mixed public/private DNS answers, URL credentials, non-HTTPS schemes, and unsupported ports; never follow redirects. |
| REQ-11 / AC-11 | Preserve exact export bytes | Event export includes Base64 body data that decodes to captured bytes. Browser download must work in supported browsers. |
| REQ-12 / AC-12 | Provide usable inspection UI | First-run setup, create, send, inspect, replay, filters, empty/error states, mobile layout, and keyboard dialog interaction work in the browser. |
| REQ-13 / AC-13 | Provide reproducible startup | Windows script builds and serves one local origin, health responds 200, and management remains protected. Docker startup requires a separate check. |

## Security boundaries

Management uses a session cookie; receiving endpoints use possession of the URL rather than verified provider identity. Passwords and sessions are stored as hashes. Cookies are HttpOnly/SameSite=Strict; enable Secure when serving HTTPS. Host validation and browser-origin checks are implemented. Login throttling is process-local and is not a distributed enforcement guarantee.

Bodies and receiver responses may contain secrets. Header redaction does not establish complete secret removal. Do not record receiving URL tokens in access logs. Do not expose the management surface publicly until deployment protections and the relevant readiness criteria are verified.

## Non-functional expectations and constraints

- Initial architecture is a single backend process, single user, SQLite WAL, and bounded sequential delivery worker.
- Logical limits: 30 endpoints, 120 new events/minute/endpoint, 50,000 retained events, 512 MiB retained body bytes, 7-day retention with hourly cleanup. These are not filesystem or infrastructure quotas.
- HTTPS port 443 only; no forwarding credentials, relay signing, local network delivery, or automatic retries of HTTP failures.
- Socket timeout is 10 seconds. Body reading checks a 20-second deadline measured from connection initiation; DNS/header processing is not established as an absolute whole-request deadline.
- Polling is approximately 2.5 seconds while live mode is active. Capture latency, throughput, storage growth, and sustained-load budgets are not benchmarked yet; no performance SLA is claimed.
- Windows/Python 3.14/Node 22 were exercised. Other documented runtime versions and Docker are intended compatibility, not tested platform claims.

## Important edge cases

Non-JSON/binary bodies use text replacement only for display; delivery preserves bytes. Capture-only events have no attempts. Replays use the current endpoint destination; existing queued attempts keep their snapshot. Deleting a record cannot recall a request already in flight. Crashes can cause repeat receiver effects even though queue claims are atomic. TLS/DNS failures are recorded as failed attempts. Synthetic events are labeled, but currently participate in workspace statistics.

## Later requirements

Provider authenticity, signed relay requests, destination credentials, rotation, infrastructure enforcement, multi-user authorization, measured load budgets, and verified backup/restore are later work. They must not be silently treated as complete because local tests pass.
