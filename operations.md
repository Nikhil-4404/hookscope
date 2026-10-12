# Hookscope operations and recovery

Release 1.0, reviewed 2026-10-12. Public deployment is pending; this runbook describes the prepared release, not an already running cloud service.

## Host and configuration

Use one Linux host with persistent local disk, Docker Engine/Compose, an HTTPS hostname and at least 2 GB available RAM (4 GB or more recommended for builds). The proposed free A1 VM has enough allowance, subject to account capacity. Do not place SQLite on a network/shared filesystem or scale the application to several hosts. A cross-process service lock enforces one server per database and blocks restore while the server runs.

Copy `deploy/production.env.example` to `deploy/production.env`, set the domain and generate a fresh 32-byte Base64 encryption key for a new installation. If moving an existing development database with secrets, encode its `backend/data/development.key` in Base64 and use that same key instead. Protect this file, preserve the key in a separate password manager/off-host location, and never commit it. Production startup verifies that stored secrets decrypt. Changing the key without re-encrypting existing secrets makes them unreadable. Endpoint secret rotation uses replacement workspace secrets, not master-key replacement.

For Linux, create the backup directory before the first compose run:

```sh
mkdir -p backups
sudo chown 1000:1000 backups
chmod 700 backups
chmod 600 deploy/production.env
docker compose --env-file deploy/production.env -f compose.production.yaml config --quiet
docker compose --env-file deploy/production.env -f compose.production.yaml build
docker compose --env-file deploy/production.env -f compose.production.yaml run --rm --no-deps hookscope python -m app.configure --email you@example.com
```

The current runtime image's application user is UID 1000. Confirm this if changing the image. Account configuration prompts without printing the password. Production startup requires configured ownership, HTTPS URL, explicit host allowlist, Secure cookies, encryption key and built frontend; it pauses existing simulator endpoints.

Starting `up -d` publishes ports 80/443 and obtains certificates for the domain. Execute only after pointing DNS at the chosen host and intentionally allowing that public exposure. The application and gateway publish no host port. Firewall/OCI security rules should expose 80/443 publicly and restrict SSH to operator addresses. Do not expose 8787, gateway 8080 or Caddy administration.

```sh
docker compose --env-file deploy/production.env -f compose.production.yaml up -d
docker compose --env-file deploy/production.env -f compose.production.yaml ps
```

Caddy provides automatic TLS and strips request URI/headers from its configured operational logs. Nginx enforces per-client request and connection budgets; request access logs are off. Application logs contain outcome metadata and hide SQL bind parameters. Keep host/system logs restricted too. Verify log policy on the actual images before promotion.

## Onboarding and recovery

```sh
docker compose --env-file deploy/production.env -f compose.production.yaml exec hookscope python -m app.accounts invite --email user@example.com --origin https://YOUR_DOMAIN
docker compose --env-file deploy/production.env -f compose.production.yaml exec hookscope python -m app.accounts list
docker compose --env-file deploy/production.env -f compose.production.yaml exec hookscope python -m app.accounts revoke-sessions --email user@example.com
docker compose --env-file deploy/production.env -f compose.production.yaml exec hookscope python -m app.configure --reset --email user@example.com
```

Invitations are private capabilities for a specific email, valid once for 24 hours. The operator shares them itself; no SMTP sender or email verification is claimed. Verify the recipient's identity through an established trusted channel before issuing an invitation or reset. Reset revokes only that account's sessions. Terminal/filesystem access grants operator access to the entire installation; there is no web super-admin browsing customers' data.

## Backups and restore

Take a daily online backup and one before every upgrade, using a unique path:

```sh
docker compose --env-file deploy/production.env -f compose.production.yaml exec hookscope python -m app.maintenance backup /backups/hookscope-YYYYMMDD-HHMM.db
docker compose --env-file deploy/production.env -f compose.production.yaml exec hookscope python -m app.maintenance check /backups/hookscope-YYYYMMDD-HHMM.db
```

Backup uses SQLite's online backup API, including committed WAL content. Check verifies integrity, foreign keys, supported schema and workspace/instance counters. Store encrypted off-host copies with the matching release and separately preserved encryption key. A same-VM backup cannot survive host/volume loss. Suggested off-host retention: seven daily snapshots plus one pre-upgrade snapshot. Keep only the latest checked local daily snapshot plus the needed pre-upgrade copy once off-host recovery is proven; the operator controls deletion/privacy requirements. Automatic pre-migration/pre-restore snapshots also consume disk and require retention management. Use an existing local backup disk if cloud storage allowances are insufficient; do not silently add paid object storage.

Restore a verified **schema 3** snapshot using release 1.0. Stop the service first; a live service lock rejects restore. This replaces current data, first preserves a pre-restore backup, and revokes restored sessions:

```sh
docker compose --env-file deploy/production.env -f compose.production.yaml stop hookscope
docker compose --env-file deploy/production.env -f compose.production.yaml run --rm --no-deps hookscope python -m app.maintenance restore /backups/hookscope-YYYYMMDD-HHMM.db --offline
docker compose --env-file deploy/production.env -f compose.production.yaml up -d hookscope
```

Use the matching old release for earlier migration snapshots; do not manually mix old tables with new triggers. In a separate host/volume, restore the same encryption key and confirm a stored secret decrypts, an exact payload exports, and a controlled event delivers. Local tests cover this behavior; cloud recovery time remains unmeasured. Daily backup targets an RPO of at most 24 hours; no achieved cloud RTO is claimed.

## Upgrade and rollback

Record the exact running image digest/source bundle, back up and check the DB, stop application writes, retain the previous image, build the candidate and start it. Additive migrations back up automatically, but do not replace the operator pre-upgrade backup. Validate readiness, login, tenant separation, capture and a controlled receiver before promoting. On failure, stop the candidate and use the previous image with its matching pre-upgrade snapshot and key. A code-only rollback against a newer schema is unsupported. Never run `down -v` on a production stack.

## Monitoring and budgets

Check public `/api/health` for liveness and `/api/ready` for DB/recent delivery heartbeat. Authenticated Workspace settings/`/api/operations` expose the caller's usage, backlog age and queue counts. Alert on readiness failure, sustained oldest-pending age over five minutes, repeated failed deliveries, available disk under 10 GB, certificate expiry/renewal failure and missed daily backups. Configure these alerts on the chosen host; no external monitor has been installed.

Logical workspace and instance budgets are in requirements.md. Physical disk also includes indexes, WAL, pre-migration/restore backups, image layers and logs. Compose bounds application memory/CPU/process count and log growth; corresponding application flags were exercised by the disposable Linux smoke check. Nginx limits login-family routes to 5/minute/client with burst 5, webhooks to 20/second/client with burst 40, management to 10/second/client with burst 40, and 20 connections/client. It refreshes Docker DNS every five seconds so application recreation can recover without gateway restart. Adjust measured budgets deliberately; sending IPs may be shared by providers or offices. Uvicorn caps concurrent connections/tasks at 100.

## Windows Docker recovery record

On 2026-10-12, WSL's service pointed at a missing C:\\Program Files\\WSL\\wslservice.exe. A signed/checksummed Microsoft WSL 2.6.3 MSI repair with installer recaching restored the files. Docker's disk and WSL registration were preserved first. Stale zero-byte Unix sockets in Docker/run and docker-secrets-engine were quarantined while Docker was stopped; no data reset/unregister was performed. Desktop restart, hello-world and release checks now pass. A recovery disk copy remains in the chat's private work/docker-repair folder; it is excluded from source archives.

If startup breaks again, inspect WSL version/status, the registered service executable and recent Docker backend logs before changing anything. Preserve stopped data disks and use the signed installer matching the installed product; an administrator prompt is necessary for service repair. Do not blindly delete runtime folders containing other data or reset/unregister distributions. Startup repair is local system evidence, not hosted readiness.

## Hosted launch gate

- Build/run image on target architecture; test gateway/Caddy configs and actual public TLS.
- Verify readiness, secure cookies, origin/host checks and two-account isolation through the deployed origin.
- Send a real provider event and a signed relay to a controlled receiver; confirm bytes, identities and retry behavior.
- Exercise service restart and persistent volume; restore a backup and key on a separate disposable volume.
- Enable alerts/off-host backups, verify free-tier quotas/charges and restrict infrastructure access.
- Start with a small invited beta and measured receiver capacity. Free hosting has no uptime commitment; do not sell an availability SLA on this evidence.

Technical reference: [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy), [Caddy global options](https://caddyserver.com/docs/caddyfile/options), [Nginx rate limiting](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html).
