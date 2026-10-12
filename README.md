# Hookscope 1.0

An invitation-only webhook platform with private accounts/workspaces, exact-byte capture, signature verification, HTTPS forwarding, retries and replay. Source: `D:\Gpt projs\Hookscope`.

## Run locally on Windows

Python 3.14 and Node 22 were tested locally. From the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Open http://127.0.0.1:8787. New installations choose a local operator password; default operator identifier is `owner@localhost`. Existing installation passwords remain unchanged and old records belong to that owner. No default password is installed. For a real email on first terminal setup:

```powershell
Set-Location -LiteralPath 'D:\Gpt projs\Hookscope\backend'
& '..\.venv\Scripts\python.exe' -m app.configure --email you@example.com
```

Invite another account (this prints a private one-use URL, not an email):

```powershell
& '..\.venv\Scripts\python.exe' -m app.accounts invite --email friend@example.com --origin http://127.0.0.1:8787
```

Share the invitation privately with its intended recipient. The invite expires in 24 hours. Each new account starts empty. Demo simulators are explicitly labeled and available only in development; they do not call an external receiver.

## Production deployment

Follow [operations.md](operations.md) and [deploy/free-hosting.md](deploy/free-hosting.md). Build requires Docker with a running Linux engine:

```text
docker compose --env-file deploy/production.env -f compose.production.yaml build
docker compose --env-file deploy/production.env -f compose.production.yaml run --rm --no-deps hookscope python -m app.configure --email you@example.com
docker compose --env-file deploy/production.env -f compose.production.yaml up -d
```

These commands publish the HTTPS service only when executed on the selected host with its domain configured. The application remains inaccessible directly from the host network. Configure the encryption key before entering tenant secrets; retain it separately from database backups.

## Use
1. Create an endpoint with capture-only or public HTTPS forwarding.
2. Add verification/signing secrets in Workspace settings and select the policy in endpoint settings.
3. Send to the copied receiving URL; sign exact bytes if verification is enabled.
4. Inspect payload/headers/history. Fix the receiver, then replay deliberately; real actions can repeat.
5. Configure 0–5 automatic retries if your receiver handles duplicate effects. Rotate receiving URLs when exposed.

HMAC format and GitHub behavior are in [backend.md](backend.md). Endpoint URLs and invitations are secret capabilities. Payload and response bodies may contain sensitive content; selected credential headers are redacted.

## Verification

```powershell
Set-Location -LiteralPath 'D:\Gpt projs\Hookscope\backend'
& '..\.venv\Scripts\python.exe' -m pytest -q
Set-Location -LiteralPath '..\frontend'
npm.cmd ci
npm.cmd run build
npm.cmd audit
```

From root, `.venv\Scripts\python.exe scripts\benchmark.py` runs a disposable near-quota benchmark without modifying project data. `scripts/container_smoke.py` checks a disposable `hookscope:verify` image/volume after building that tag; it never uses production volumes. For an ARM build tagged `hookscope:verify-arm64`, pass `--image hookscope:verify-arm64 --platform linux/arm64`. Both architectures passed the container smoke locally (ARM under emulation). GitHub CI is supplied but has not run remotely.

Current evidence, missing checks and readiness are in [status.md](status.md). Docker/WSL startup is repaired; the Linux/amd64 image, 52 containerized backend tests and live production smoke passed, including proxy recovery after the app IP changed. The implemented SaaS release is not yet a verified public deployment: OCI provisioning/runtime, public TLS, provider traffic and cloud recovery remain to be checked. The free host has no availability SLA.
