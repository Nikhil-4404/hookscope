# Hookscope product specification

Baseline reviewed: 2026-10-12. Product intent is maintained here; observed contracts are in [backend.md](backend.md) and [frontend.md](frontend.md), with evidence in [status.md](status.md).

## Problem and users

Developers integrating event-producing services need to establish whether requests arrived, inspect their contents, understand receiver failures, and reproduce an event after fixing the receiver. The initial audience is an individual developer working on a local integration. A hosted team product is later scope, not an existing capability.

## Value and goals

Provide a single investigation workflow from receiving URL to payload and delivery history. Preserve captured body bytes, expose delivery outcomes, and make manual replay explicit. Keep self-hosted setup small and avoid requiring an external AI service or message broker.

## MVP

- A password-protected, single-user workspace.
- Endpoint management and secret receiving URLs.
- POST capture, searchable event history, body/header inspection, and JSON export.
- Forwarding to public HTTPS destinations, durable attempt records, and manual replay.
- Labeled demo/test events for learning the workflow.
- Data/resource boundaries and documented startup.

The app is a local development increment. Browser acceptance and real external integrations remain unverified; it is not a production SaaS release.

## Later scope

Prioritize provider authenticity verification, relay signing, token rotation, and destination authentication before wider exposure. Then consider bounded retries, local forwarding/tunnels, independent workers, PostgreSQL, multiple workspaces, and operations tooling based on actual users. Roadmap status is in [status.md](status.md).

## Non-goals

No universal provider compatibility, exactly-once effects, AI diagnosis, automatic code repair, payment processing, microservices, or cloud hosting in the current increment. Provider signature headers are not preserved as usable authentication for the relay.

## Success measures

Measure time to first captured event, time to diagnose a controlled receiver failure, successful recovery through replay, and repeat use on real integrations. Record real-provider coverage separately from simulated outcomes. No adoption, time-saving, or willingness-to-pay measurements have been collected; target thresholds should be set after observing initial users.
