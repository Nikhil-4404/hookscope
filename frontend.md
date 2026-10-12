# Hookscope frontend contract

Reviewed 2026-10-12. Main screens: login/invitation acceptance, event inbox/detail, endpoint cards/edit, quick start, workspace settings. Each account owns one workspace. Settings include write-once secret storage, password change and delivery health. Endpoint settings include incoming verification, outgoing signing, bounded retries and receiving-URL rotation.

API results own statistics and lists. Five management requests refresh approximately every 2.5 seconds while live. Only the latest refresh applies; logout clears cached workspace records and invalidates pending refreshes. Authenticated response headers identify the workspace; the client rejects a mismatched account response and reloads identity. Detail requests stop applying after selection/session changes. JSON export includes exact Base64 bytes and full attempt history. All values render as React text, not injected HTML.

Test/demo labels are visible. Demo controls are hidden in production; simulator timings are excluded from the real HTTPS response average. Automatic retries are labeled separately from initial/manual delivery, with due times. Replay/rotation/deletion explain their consequences. HTTP errors appear in forms or reconnect state.

Dialogs take focus, trap Tab/Shift+Tab, close on Escape when idle and restore the trigger. Reduced-motion CSS is included. A topbar sign-out control remains visible on narrow screens. Long endpoint dialogs scroll within the viewport.

Observed browser evidence covers login, endpoint creation, test capture, failed initial attempt/successful replay, distinct history, export bytes, dialog keyboard behavior and responsive layouts. It does not establish every browser engine, screen-reader behavior, invitation/password-entry submission or all errors. Registration/password/security logic has API test coverage; browser credential changes require user handoff under the computer-use policy.
