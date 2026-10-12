# Hookscope product specification

Reviewed 2026-10-12. The user selected a multi-user SaaS release and requested a zero-cost hosting option. Previous local scope is preserved in docs/history/.

## Problem and users
Developers integrating webhooks need to see what arrived, diagnose receiver failures, and replay exact payloads without mixing one customer's data with another's.

## Value and release scope
Invitation-only accounts each own one private workspace. Users create receiving URLs, optionally verify GitHub or timestamped HMAC signatures, inspect exact payloads, forward to public HTTPS receivers with optional relay signatures, configure bounded retries, and deliberately replay events. Storage, rate and attempt limits apply per workspace and across the instance.

This is a small SaaS beta on one persistent server. The application, worker and database form a modular monolith. The operator controls onboarding, account recovery, backups and hosting. No external service is represented by a simulator in production.

## Goals and success measures
- Prove cross-account isolation across every management route.
- Preserve raw bytes, durable acknowledgement and independent attempt history.
- Exercise migrations, encrypted-secret recovery, TLS and deadline behavior.
- Target capture p95 below 500 ms in the documented local near-quota benchmark. This is a local engineering target, not a cloud SLA.
- Complete container, ARM and public integration checks before declaring the hosted release ready.

## Future scope and non-goals
Public signup with email verification, organization membership and roles, billing, OAuth/MFA, Stripe-specific verification, PostgreSQL/horizontal scaling and commercial availability commitments are separate releases. The present invitation and operator-recovery flows are implemented, not placeholders for an absent email service. No exactly-once receiver-effect guarantee is made.

See requirements.md for acceptance and status.md for evidence. Hosting selection does not establish account availability or free-tier uptime.
