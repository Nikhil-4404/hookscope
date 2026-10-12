# Hookscope release status

Release 1.0.0, reviewed 2026-10-12 (Asia/Calcutta). The invitation-only multi-user release is implemented and locally verified to the boundaries below. **Public production readiness is pending AC-19.** No cloud account, VM, hostname or public service has been provisioned. The previous baseline is preserved in [docs/history/status-local-baseline.md](docs/history/status-local-baseline.md).

## Legend

`[ ] Planned` · `[-] Active` · `[i] Implemented — Verification Pending` · `[x] Verified Complete` · `[!] Blocked` · `[~] Deferred`.

Completion applies to the stated acceptance boundary, not every possible behavior of a subsystem.

## Roadmap and launch gate

| State | Scope | Acceptance / evidence | Remaining boundary |
|---|---|---|---|
| `[x] Verified Complete` | Private accounts, bound invitations, owner-scoped management, session revocation | AC-01/02/05/14, E-01/04 | Operator onboarding; no SMTP/email verification or organization roles. |
| `[x] Verified Complete` | Exact-byte receipt, rotation, dedupe, quotas and counter transactions | AC-03/04/09, E-01/06 | Local workload only; gateway IP limits need deployed checks. |
| `[x] Verified Complete` | Signature verification and encrypted tenant secrets | AC-10/15, E-01 | Credential-changing browser forms were rendered but not submitted. |
| `[x] Verified Complete` | Durable claims, fair scheduling, retry history and hard delivery deadline | AC-07/08/17/18, E-01 | No cloud capacity measurement; delivery remains at-least-once. |
| `[x] Verified Complete` | Controlled real TLS socket path and hostname rejection | Local part of AC-06, E-01 | Controlled loopback TLS is not a real internet/provider integration. |
| `[x] Verified Complete` | Browser capture/inspection/replay/export, account switch, focus and narrow layout | AC-11/12, E-04 | Replay receiver was simulated. Credential submission/permanent deletion were not browser-tested. |
| `[x] Verified Complete` | Migrations, online snapshot, reconciliation and offline restore with matching key | AC-16, E-01 | Disposable local data; hosted recovery time unmeasured. |
| `[x] Verified Complete` | Windows launcher and compiled frontend serving | Local runtime, E-02/05 | Development mode on loopback; existing password preserved. |
| `[x] Verified Complete` | Windows Docker/WSL repair and Linux/amd64 image/runtime checks | Local AC-13, E-08 | Docker engine restarts cleanly; 52 tests pass inside Linux. |
| `[x] Verified Complete` | Production constraints, backup/restart, live Nginx and upstream IP recovery | Local AC-13/16, E-08 | No public ports; disposable fixture data. Caddy configuration validates, public TLS remains pending. |
| `[x] Verified Complete` | Linux/arm64 image and complete container smoke under emulation | Compatibility boundary, E-09 | Actual OCI host/resources are not established by emulation. |
| `[i] Implemented — Verification Pending` | Target OCI runtime and public Caddy TLS | AC-19 | Actual host, provider and cloud recovery still required. |
| `[!] Blocked` | Public hosted launch | AC-19 | User-created Always Free account, available VM, SSH access and hostname needed. Follow operations.md launch gate. |
| `[ ] Planned` | Hosted alerts, off-host backup schedule and measured recovery | AC-19 | Runbook exists; operational installation needs selected host. |
| `[x] Verified Complete` | [Public GitHub source repository](https://github.com/Nikhil-4404/hookscope) | User approved publication; E-10 | main pushed; local and remote commit matched. User data, keys, real environment files and generated dependencies excluded. |
| `[x] Verified Complete` | GitHub-hosted release verification | E-11 | Ubuntu runner passed all checks after the explicit-subnet smoke fix. Public hosted service remains a separate gate. |
| `[~] Deferred` | Public signup, billing, email recovery, team roles, MFA/OAuth, PostgreSQL and multiple workers | PRD later scope | Release is an invited SaaS beta. Revisit with demand or measured limits. |

## Verification records

All current records are dated 2026-10-12 on Windows, Python 3.14 and Node 22.21.1. Fingerprints below identify the checked source. Tests use isolated databases rather than changing user records.

- **E-01:** From backend, `..\.venv\Scripts\python.exe -m pytest -q`: **52 passed**. Covers cross-tenant routes/references, one-use email-bound invitations, exact bytes/signatures, encryption/key mismatch, quotas/counter rollback/cascades, retries/fair claims/paused work, child timeout termination, controlled TLS hostname/body/header/signature checks, migrations and backup/offline restore. One upstream Starlette TestClient/HTTPX deprecation warning. Fixtures/doubles do not prove external provider compatibility. Tests are in backend/tests.
- **E-02:** `npm.cmd run build`: TypeScript/Vite build passed after final UI edits. `npm.cmd audit`: zero known vulnerabilities. Python `pip check` passed; pip-audit found zero known vulnerabilities in requirements.lock after cryptography upgrade to 50.0.2. Audits are time-bound metadata, not a security certification.
- **E-03, historical:** Production Compose parsing passed, but initial Docker startup failed. This local blocker was resolved by E-08; remote CI/public deployment were not verified by that repair.
- **E-04:** User explicitly renewed browser authorization. Separate disposable preview on port 8790 verified fixture login/error/logout, endpoint creation, 51-byte test capture, simulated 503 failure then confirmed manual replay 200 with both attempts retained, JSON download/exact Base64 recovery, modal initial focus/Tab wrapping/Escape/focus return, settings rendering, and 390px mobile layout without horizontal overflow. Second fixture account saw an empty workspace; returning to the first retained its event. Credential creation/change was not submitted through automation. Screenshot shows labeled TEST data and demo://flaky, not provider delivery. Prior denial is historical and resolved by renewed authorization.
- **E-05:** Current start.ps1 built/started actual project on 127.0.0.1:8787. Health reported 1.0.0, readiness passed, frontend returned 200, unauthenticated auth state was correct, protected events returned 401. Additive migrations generated backups. Existing password/data were preserved; no real user body/secret was exported.
- **E-06:** scripts/benchmark.py: disposable 49,000 synthetic existing events, 100 captures, concurrency 10, one workspace, in-process TestClient. Final run: p50 **4.57 ms**, p95 **313.83 ms**, max **835.39 ms**, **118.43 captures/s**. Maximum of five reads: events 11.72 ms, stats 108.36 ms, operations 39.83 ms. Comparable pre-optimization development run had p95 5,917.76 ms. Individual local samples exclude network/TLS/delivery/multiple tenants/cloud hardware; not sustained capacity promises.

- **E-08, Docker repair follow-up:** Restored missing WSL 2.6.3 program/service files and installer cache using Microsoft's signed, SHA256-verified matching MSI. Preserved Docker's offline disk and WSL registration before repair. Quarantined only stale runtime socket directories; no factory reset, unregister, project credential change or user-data deletion. Docker Desktop is now 4.95.0, Engine 29.8.2; Desktop restart and hello-world pass. Linux/amd64 image build passed (image ID sha256:16226e51e96fe6cca0c0f29a14780b0b6cae15d80f192605d8c6ed08b629ebbd). All 52 backend tests also passed inside Python 3.13 Linux, read-only root/tmpfs, network disabled. Extended container smoke passed production flags, secure session, backup/check, restart, live Nginx encoded routes/query/exact capture bytes, and app recreation to a different IP with the same gateway and persistent session/events. Caddy validation passed with a formatting warning; public certificates were not obtained. Nginx now refreshes Docker DNS instead of caching an upstream IP for its lifetime. Windows fixture stdin uses exact LF bytes, avoiding CRLF translation. The first live run was interrupted by Docker updating/restarting; its named disposable leftovers were removed and the subsequent complete run passed.

Initial release handoff: Hookscope-1.0.0-source.zip was inspected with Python ZipFile.testzip (CRC passed), required source/config files were present, and the 56-file allowlist excluded user DBs/backups, keys, real environment files, dependencies and generated assets. A source/archive SHA256 manifest and combined release guide accompany it. Packaging is not hosted validation.

ARM follow-up **E-09:** `docker buildx build --platform linux/arm64 --load -f backend/Dockerfile -t hookscope:verify-arm64 .` passed. Image ID: sha256:dae7312c47a1f4980c116d46794367b1ac95b6ca03ec5a8187786960d26e1611. `scripts/container_smoke.py --image hookscope:verify-arm64 --platform linux/arm64` passed the same production constraints, session, backup, restart, live gateway/encoded query/byte preservation and forced upstream-IP change checks, with ARM application/Nginx/Caddy containers under Docker Desktop emulation. This is compatibility evidence, not measured native ARM capacity or OCI readiness.

**E-10, GitHub publication:** Public repository [Nikhil-4404/hookscope](https://github.com/Nikhil-4404/hookscope) created and initial main commit `1f1dd4c7774d565efacb8d2939b5de12bfe25dc9` pushed on 2026-10-12. `git ls-remote` matched local HEAD; repository metadata confirmed public visibility. The 57-file source allowlist passed staged whitespace/known-token checks; the only URL-credential match was an inert example.com SSRF rejection fixture. Ignore checks confirmed DBs, keys, real environment files, backups and generated directories are excluded. Commit identity uses the account's GitHub noreply address. [Initial CI run](https://github.com/Nikhil-4404/hookscope/actions/runs/38260345800) on Ubuntu 24.04, Python 3.13.16 and Node 22.23.3 passed 52 tests, pip check, dependency audits, frontend build, Compose validation and Docker build. Container smoke failed because that engine disallows a static IP on automatically configured IPAM. The smoke now recreates only its empty disposable network with Docker's chosen subnet explicitly configured before attaching containers; local full smoke passed after the fix; remote rerun remains pending. This publication does not deploy the public service.

**E-11, remote verification:** [GitHub Actions run 38260836303](https://github.com/Nikhil-4404/hookscope/actions/runs/38260836303) completed successfully for commit `ab1fa4a3eb6066e0c76cd9b2f35c592a4103b9fa` on 2026-10-12. All workflow steps passed: 52 backend tests, pip check, pip-audit, frontend install/build/production dependency audit, production Compose validation, Linux/amd64 Docker build and complete container smoke (constraints, secure session, backup/check, restart, live Nginx encoded capture/query/body preservation, forced application IP change with unchanged gateway and Caddy configuration validation). The explicit-subnet fix also passed locally; only named disposable resources were used and cleanup left no smoke containers/networks/volumes. The runner warned that older action versions target deprecated Node 20 and were run on Node 24; tests/build use Python 3.13 and Node 22. Caddy formatting and the upstream Starlette deprecation warnings remain non-fatal. Real provider delivery, OCI/public TLS and hosted recovery remain pending AC-19. Later documentation-only commits do not change this tested application/configuration source.

### Source snapshot

SHA256 prefixes (recompute after changes):

| File | Prefix |
|---|---|
| backend/app/main.py | 81F700CB7CEF63FC |
| backend/app/delivery.py | BD1EF8090D362F71 |
| backend/app/store.py | 34964563997492AE |
| backend/app/tenancy.py | 93FCCA6F90A475B4 |
| backend/app/maintenance.py | E827F92C0D4B0D35 |
| frontend/src/main.tsx | E1A8B44824FBF32A |
| frontend/src/SecuritySettings.tsx | 62BEDE89867C04A5 |
| frontend/package-lock.json | 4C1CB4C299AC6569 |
| backend/requirements.lock | 1C94DD26C03A7E26 |
| deploy/nginx.conf | 07E2C08A296B8E9D |
| scripts/container_smoke.py | F39F4DF745ED8CFE |

## Technical debt and limitations

- TD-01: Large frontend component and partially typed Python dictionaries/helpers. Refactor during relevant work; tests do not imply full static typing.
- TD-02: SQLite and a sequential coordinator constrain capacity and availability. Fair claims do not establish latency under multi-tenant load. Service lock enforces one server per database.
- TD-03: Free-host capacity, idle reclamation, absence of SLA and actual OCI runtime/public TLS remain launch risks. Local container checks do not establish hosted availability. Resolve/pin image digests after target verification.
- TD-04: Host/off-host encryption, alerts, backup scheduling/retention, restore drills and master-key rotation require operations. Row deletion does not erase snapshots or every freed SQLite page.
- TD-05: Browser signup/password/secret submission and permanent-delete flows lack end-to-end coverage. Backend behavior has API tests; secret-delete confirmation was build-checked only.
- TD-06: Provider compatibility beyond GitHub/generic HMAC is unverified. Forwarding uses fresh relay trust; arbitrary destination Authorization configuration is unsupported. Retry-After handling/per-destination concurrency are future work.
- TD-07: Public signup, email verification/recovery, paid plans and organization collaboration are absent by release scope. Commercial self-service readiness is a separate milestone.

These are limits/missing evidence, not a completed penetration-test report.

## Meaningful decisions

- **DEC-01:** User selected multi-user SaaS. Private account/workspace isolation and invitation onboarding first; operator recovery avoids an unconfigured mail service. Revisit public signup/roles with explicit requirements.
- **DEC-02:** Modular monolith, SQLite and durable database queue support an invited beta on one persistent VM. Migrations, quota counters and fair claims address concrete needs without speculative brokers. Reconsider storage/workers when measured demand exceeds this boundary.
- **DEC-03:** Preserve exact bytes, redact selected credential headers, validate public destinations and sign relayed content anew. Old provider credentials/signatures cannot safely be blindly forwarded.
- **DEC-04:** Bounded outbound child prevents DNS/TLS/header stalls from permanently stopping the coordinator. Verify cleanup on target OS before launch.
- **DEC-05:** AES-GCM secret encryption binds owner/id; master key is separate from DB backups. Production fails when secrets cannot decrypt. Recovery needs corresponding key/release.
- **DEC-06:** Oracle Always Free A1 plus DuckDNS is proposed because persistent disk and continuous worker fit the architecture. Engineering choice, not uptime guarantee; Render free persistence/sleep behavior does not fit.
- **DEC-07:** Core/domain specifications own intent/contracts; operations.md owns recovery; deploy/free-hosting.md owns researched hosting. History stays in docs/history; no file-count target.
