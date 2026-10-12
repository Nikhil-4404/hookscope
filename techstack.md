# Hookscope technology choices

Reviewed 2026-10-12. React/TypeScript/Vite frontend; FastAPI/Pydantic/Uvicorn backend; SQLAlchemy with SQLite WAL. Major dependencies are pinned in frontend/package-lock.json and backend/requirements.lock. Cryptography 50.0.2 supplies AES-GCM; secrets are application-encrypted, while payloads require host/disk protection.

Observed local environment: Windows, Python 3.14, Node 22.21.1. Image targets Python 3.13 and Node 22. Linux/amd64 image build, 52 tests inside Linux and production container smoke passed. Linux/arm64 image build and the same smoke passed under Docker Desktop emulation; actual OCI runtime/native resource capacity remain unverified. Current Desktop is 4.95.0, Engine 29.8.2, WSL 2.6.3 after local repair. Lockfiles, not this document, own the complete dependency inventory. Run pip check, pip-audit and npm audit after dependency changes; advisories are time-dependent.

The Dockerfile uses a Node build stage and non-root Python runtime; no prebuilt frontend files are required. Runtime has one application process and a sequential delivery coordinator. Real delivery runs in a short-lived spawn child so blocking network work can be terminated. Database transactions maintain tenant/instance usage counters and latest event status.

Production compose adds Caddy for certificate/HTTPS handling and Nginx for bounded ingress. Only the HTTPS edge publishes ports; application and gateway are internal. Application runtime has read-only root, tmpfs, no added capabilities, process/memory/CPU/log limits and persisted data. These are infrastructure roles, not domain microservices. See operations.md.

Zero-cost proposal: OCI Always Free A1 VM and DuckDNS hostname, subject to current allowance, account verification, capacity and reclamation. Persistent local SQLite avoids the data loss of ephemeral free web hosting. Move to PostgreSQL with explicit migration when independent workers, multiple hosts or sustained tenant load justify it; do not run SQLite on shared network storage.

The public source repository is [Nikhil-4404/hookscope](https://github.com/Nikhil-4404/hookscope). CI verifies tests/build/audits/image/start/restart/proxy configuration. [Ubuntu run 38260836303](https://github.com/Nikhil-4404/hookscope/actions/runs/38260836303) passed all steps after the smoke network was given an explicit subnet for engine portability; see E-11 in status.md. Image tags must be resolved/tested on the release host and pinned by digest for a hosted promotion.
