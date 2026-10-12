# Technology and deployment

Reviewed: 2026-10-12. Canonical dependency inventories: [frontend/package.json](frontend/package.json), [frontend/package-lock.json](frontend/package-lock.json), [backend/requirements.txt](backend/requirements.txt), and [backend/requirements.lock](backend/requirements.lock).

| Component | Current choice | Rationale / limitation |
|---|---|---|
| UI | React 19.3.0, TypeScript 5.7.3 | Typed interactive inbox; current source is one large component, with modularization debt. |
| Build/dev | Vite 6.4.4 | Static build; loopback dev server proxies API and hooks. |
| Icons/fonts | Lucide 0.468.0, bundled Fontsource fonts | No runtime dependency on external font hosting. |
| API | Python, FastAPI 0.143.0, Pydantic 2.14.1 | Validation and management/receiving routes. |
| Serving | Uvicorn 0.54.0 | Single process serves API and compiled UI. |
| Storage | SQLite, SQLAlchemy 2.1.4 | Small persistent self-hosted setup; WAL and foreign keys; not a multi-tenant scale claim. |
| Outbound | Python socket/ssl/http.client | Validate public DNS answers, pin IP, preserve TLS hostname; no redirects. |
| Queue | attempts table and in-process worker | Durable attempts without a separate broker; lease recovery can duplicate receiver effects. |
| Tests | Pytest 9.1.1, FastAPI TestClient, HTTPX 0.28.1 | Isolated temporary DB; controlled delivery doubles; current upstream deprecation warning. |

## Runtime support

Documented intended baseline: Python 3.11+ and Node.js 22+. Tested locally: Python 3.14 and Node.js 22.21.1. Dockerfile uses Python 3.13; that image has not been executed here. Do not claim all runtime combinations pass.

## Dependency policy

Use `npm ci` with the frontend lockfile and the backend lock for reproducible installs. `requirements.txt` expresses ranges; `requirements.lock` pins the resolved environment and is used by startup/Docker. Verify both after upgrades. Current backend production image includes test dependencies; split runtime/development requirements when deployment work justifies it. No dependency changes are part of this documentation adoption.

## Architecture and execution

The backend loads the UI build from `frontend/dist`, stores SQLite data under `backend/data` unless configured, and starts the worker through FastAPI lifespan. No independent service, broker, cache, AI model, or hosted Sites project exists.

Windows entrypoint: `powershell -ExecutionPolicy Bypass -File .\start.ps1` from the project root. Development uses backend port 8787 and Vite 5173. Docker Compose publishes host loopback and mounts a named data volume; configure the workspace password through `python -m app.configure` before container UI login.

Configuration names/purposes and startup commands remain canonical in [README.md](README.md). Relevant variables are `HOOKSCOPE_DATA`, `HOOKSCOPE_ALLOWED_HOSTS`, `HOOKSCOPE_ORIGINS`, `HOOKSCOPE_SECURE_COOKIES`, and the test-only `HOOKSCOPE_DISABLE_WORKER`. Never document actual secret values.

## Schema and operations

Schema creation is currently `CREATE TABLE IF NOT EXISTS` in `backend/app/store.py`; there is no versioned migration system. Introduce migrations before changing persisted schema. Public deployment, reverse-proxy trust, independent workers, backups, restoration, metrics, and rollback need an explicit implementation/verification increment.
