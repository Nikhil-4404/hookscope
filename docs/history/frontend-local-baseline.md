# Frontend specification

Observed baseline: 2026-10-12, `frontend/src/main.tsx` and `styles.css`. Build/type checks passed historically; no browser acceptance pass is recorded. API contracts are in [backend.md](backend.md).

## Screens and workflow

- Authentication: initial setup or login, validation errors, loading and unavailable-server states.
- Inbox: real retained counts, event activity, delivery rate, failed-event count, average attempt latency; searchable/paginated table and endpoint/status filters.
- Inspector: payload, redacted headers, attempts/responses/errors, replay confirmation, export, and deletion confirmation.
- Endpoints: create/edit, copy secret URL, pause/activate, send test event, delete with history.
- Quick start: generated PowerShell curl command and workflow guidance.
- Settings: retention/resource boundaries, transport restrictions, demo behavior, and local-release limitations.

## State and data

API data are fetched from the same origin; Vite proxies development traffic. No project records are stored in browser localStorage. Live polling is roughly 2.5 seconds; paused polling does not affect backend receipt/worker processing. Search matches type, endpoint name, or ID, not payload text. Detail shows the latest fetched attempt history.

`DEMO` and `TEST` labels identify synthetic receipt sources. Demo/test events participate in totals and success/latency statistics; simulator latency is synthetic. Metrics must not be presented as real-provider benchmarks. Browser dates use the visitor's locale/timezone; activity bucketing is UTC in the backend. Empty datasets show dashes/empty states rather than invented traffic.

## Interaction and accessibility intent

Use semantic inputs/buttons, accessible labels on icon controls, visible focus, Escape handling, and dialog focus wrapping. Replay explains duplicate side effects. URLs are masked until explicitly copied. A binary body has a lossy UTF-8 display preview and Base64 export for recovery. Keyboard focus behavior, responsive layouts, clipboard/download actions, and initial setup remain browser-verification items.

## Error and loading behavior

Unavailable startup offers reconnect. API errors show notifications or form errors. Failed polling shows a connection warning, session expiry returns to login, and an unselected/loading inspector shows a loading state. Backend validation remains authoritative. Main component/API calls currently have no browser interaction test suite; overlapping refresh responses and focus timing need browser exercise before completion.

## Architecture debt

One large component currently owns auth, inbox, endpoint management, and dialogs. Extract components/data hooks during substantive changes, preserving behavior and adding meaningful interaction checks. Do not refactor solely to satisfy a file-count convention. The compiled frontend is served by FastAPI; no cloud UI or Sites deployment exists.
