# Product brief

## Maintained specification index

Adopted and updated 2026-10-12. The user subsequently selected an invitation-only multi-user SaaS and a zero-cost deployment proposal. The original brief below is historical context. Current authoritative specifications are:

- [Product intent](prd.md)
- [Requirements and acceptance criteria](requirements.md)
- [Technology and deployment](techstack.md)
- [Workflows and lifecycle](flow.md)
- [Status and verification evidence](status.md)
- [Backend contracts](backend.md)
- [Frontend specification](frontend.md)
- [Operations and recovery](operations.md)
- [Free hosting proposal](deploy/free-hosting.md)

[README.md](README.md) remains the startup/operator guide. Do not treat the historical workflow below as a completed browser acceptance test.

## Original brief

Hookscope helps developers answer three questions: Did my webhook arrive? What did the receiver return? Can I replay it after fixing the receiver?

The first release is a self-hosted development tool for one user. It captures incoming POST requests, provides a searchable inspector, and forwards to explicitly configured public HTTPS destinations. Payment, deployment, and support examples are demonstrations rather than real provider integrations.

## Acceptance workflow

1. Start the server and choose a workspace password.
2. Create an endpoint and copy its receiving URL.
3. Send a request and locate it in the inbox.
4. Inspect the body and redacted headers.
5. With `demo://flaky`, observe HTTP 503.
6. Replay, observe HTTP 200, and retain both attempts.
7. Pause the endpoint, verify new requests are rejected.
8. Delete an event and verify its attempt history disappears.

## Product boundaries

No chatbot, third-party credentials, automatic code fixes, cloud deployment, or multi-user tenancy is needed for the first workflow. Inbound authenticity is not verified yet. Forwarding changes the transport context and strips credentials/signatures; payload bytes are preserved. Real integrations must account for this behavior.

Success is a developer completing the workflow on their own integration and choosing to use the tool again. The next iteration should be based on that feedback rather than a larger feature list.
