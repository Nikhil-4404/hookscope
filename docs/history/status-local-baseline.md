# Hookscope status

Baseline and documentation adoption: 2026-10-12, Asia/Calcutta client date. Current milestone: a working local development increment, with broader acceptance and production work still pending. No feature code was changed during workflow adoption.

## Legend

`[ ] Planned` · `[-] Active` · `[i] Implemented — Verification Pending` · `[x] Verified Complete` · `[!] Blocked` · `[~] Deferred`.

Completion applies to the explicitly stated scope, not to every behavior of a subsystem.

## Current roadmap

| State | Task / scope | Acceptance and evidence | Next step / limitation |
|---|---|---|---|
| `[x] Verified Complete` | Management auth/login/logout contract exercised by tests | AC-01, E-01 | Does not establish full deployment security or session-expiry edge coverage. |
| `[x] Verified Complete` | Byte-preserving receipt and configured header redaction | AC-03, E-01 | Only the documented header policy; body privacy is a separate boundary. |
| `[x] Verified Complete` | Explicit ingestion deduplication in tested cases | AC-04, E-01 | Empty-key and retention-expiry behavior remain edge cases. |
| `[x] Verified Complete` | Simulator failure/replay and persisted attempt history | AC-06, API portion of AC-07, E-01 | No actual provider delivery or browser confirmation checked. |
| `[x] Verified Complete` | Atomic worker claims, lease recovery, concurrent replay rejection | AC-08 and API replay concurrency, E-01 | Receiver effects can be duplicated; not exactly-once. |
| `[x] Verified Complete` | Tested destination-policy rejection and controlled forwarding semantics | Tested AC-10 cases, E-01 | TLS/pinning path is not verified against a real destination. |
| `[x] Verified Complete` | Search/capture-only filtering and endpoint deletion cascade tested | Tested AC-02/AC-05 portions, E-01 | Not comprehensive pagination/edit/delete-event coverage. |
| `[x] Verified Complete` | Oversized-payload and logical event-count quota rejection tested | Tested AC-09 portions, E-01 | Byte quota, rate window, retention timing, and load behavior need checks. |
| `[x] Verified Complete` | Windows launch and compiled asset serving smoke check | Local part of AC-13, E-03 | Historical startup check; no Docker or public hosting validation. |
| `[x] Verified Complete` | Specification baseline and persistent workflow installed | E-05 | This is documentation completion, not app acceptance completion. |
| `[i] Implemented — Verification Pending` | Endpoint/form/dialog interactions and full inspection journey | AC-12 | Browser walkthrough, keyboard interaction, mobile layout, and errors need observation. |
| `[i] Implemented — Verification Pending` | Exact-byte export and browser download | AC-11 | Check Base64 recovery and actual download behavior. |
| `[i] Implemented — Verification Pending` | Real public HTTPS forwarding | Full external part of AC-10/AC-06 | Use a controlled authorized receiver and verify TLS/body/headers/timeouts. |
| `[i] Implemented — Verification Pending` | Retention, byte quota, rate limits, and sustained workload | Remaining AC-09 | Add meaningful boundary/load checks before performance claims. |
| `[i] Implemented — Verification Pending` | Docker configuration | Container part of AC-13 | Build image, initialize account, verify persistence and restart. |
| `[!] Blocked` | Browser acceptance check in this chat | E-04 | Previous browser access was denied. Needs renewed explicit authorization or user-reported observations; do not bypass the denial. |
| `[ ] Planned` | Define and validate next public-ingestion increment | PRD later scope | Choose hosting/privacy boundary, provider authenticity, signing, and destination auth. |
| `[~] Deferred` | Multi-user workspaces, PostgreSQL, independent worker, retries | PRD later scope | Revisit after initial integrations establish requirements. |

## Verification records

- **E-01, 2026-10-12:** `..\.venv\Scripts\python.exe -m pytest -q` from `backend/`. 24 passing tests, including parameterized destination cases. Uses temporary isolated DB and disabled background worker. One upstream warning: HTTPX with Starlette TestClient is deprecated. Controlled connection doubles do not establish external provider interoperability.
- **E-02, 2026-10-12, historical earlier build:** `npm.cmd run build` from `frontend/` passed TypeScript and Vite production build. Browser behavior was not checked. Source and lockfiles have not been changed during this adoption.
- **E-03, 2026-10-12, historical startup:** root `start.ps1` built/started loopback Uvicorn; HTTP smoke checks returned health 200, frontend 200, unconfigured auth state, and protected events 401. Does not verify UI interactions or database recovery.
- **E-04, 2026-10-12:** browser tool denied opening the local preview because permission was denied. No visual or browser workflow pass is recorded. An ambient open tab is not new authorization to bypass that denial.
- **E-05, 2026-10-12:** `quick_validate.py` accepted the installed `project-workflow` skill. Manual scenario review covered new CLI, existing docs, narrow fixes, simulation, denied checks, and destructive migrations. Structural validation is not independent agent evaluation or proof of universal skill quality.
- **E-06, 2026-10-12, historical audit:** `npm.cmd audit --json` returned zero known frontend vulnerabilities at that time. This is time-bound dependency metadata, not a security certification. No Python dependency audit or comprehensive security review is recorded.

### Source snapshot

SHA256 prefixes recorded on adoption (recompute to test applicability):

| Source | Fingerprint prefix |
|---|---|
| backend/app/main.py | 70288DB0C66397B8 |
| backend/app/delivery.py | 8ACD96B77E32BF38 |
| backend/app/store.py | D83FC0DA76CE489B |
| frontend/src/main.tsx | D13D0E54A8E61F91 |
| frontend/src/styles.css | 45F2E1402FCC3FDF |
| frontend/package-lock.json | 395040C840BB6E4D |
| backend/requirements.lock | 4E7551F8F7DCB2C4 |

## Technical debt and readiness gaps

- TD-01: No versioned migrations; bootstrap cannot safely evolve an existing schema. Introduce migrations before schema changes.
- TD-02: Large frontend component and partially typed Python dictionaries/helpers. Improve during relevant work without a blanket rewrite.
- TD-03: Stats/capture quota checks perform aggregate scans; load limits and latency are unmeasured. Profile representative workloads before optimization claims.
- TD-04: Simulator responses use synthetic timing and enter normal statistics. Keep labels clear and isolate demo measurements before reporting real performance.
- TD-05: No provider-signature verification, relay signing, destination auth, receiving-token rotation, or forgotten-password recovery flow. Needed scope depends on actual integrations/exposure.
- TD-06: Health is liveness-only; no queue readiness/metrics, verified backups/restoration, deployment rollback, or public infrastructure controls.
- TD-07: Process-local login throttling, non-atomic endpoint-count/demo creation across requests, and attempts/responses not included in body quotas need review before broader scale/exposure claims.
- TD-08: DNS/header processing is not proven to respect a whole-operation deadline. Strengthen/verify before promising bounded end-to-end delivery time.
- TD-09: Retention/deletion remove active rows, not historical filesystem backups or every freed SQLite page; define operational lifecycle before sensitive use.

These are observed limits or unverified risks, not findings from a completed penetration test.

## Meaningful decisions

- **DEC-01:** Modular monolith and SQLite for a single-user local tool reduce setup burden. Reconsider when team authorization, scale, or independent availability is required.
- **DEC-02:** Database-backed attempts are justified by durable capture/delivery and crash recovery. No broker is required for current scale.
- **DEC-03:** Preserve exact bodies, redact selected headers, and block private destinations. This sacrifices transparent provider-auth forwarding; add explicit relay trust instead of silently passing old signatures.
- **DEC-04:** Five core documents plus backend/frontend contracts fit this application. No services/model/pipeline files are needed. README owns operations, PROJECT indexes current contracts, and historical brief remains available.
