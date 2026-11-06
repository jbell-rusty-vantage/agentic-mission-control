"""Remote Session Lane base: shared machinery for provider session APIs (ADR-0052; SPEC-06 §3).

`cursor_cloud` is the first client; `claude_managed` and `codex_agents` build on the same base.

- `lane`: `RemoteSessionLane` (staging, stream-then-reconcile observe, dispatch reconciliation
  routing, later-turn texts and handover) and `RemoteSession`;
- `stream`: `open_event_stream`, `replay_then_stream`, stream cursor codecs;
- `sse`: the event-stream wire parser;
- `errors`: the typed HTTP error set, per-provider `ErrorRule` tables, the `429` signal;
- `dispatch`: deterministic create ids, metadata reconciliation, dispatch keys, turn anchors;
- `usage`: usage settled only when reported;
- `custody`: the provider workspace lease and `branch:<branch>@<sha>` snapshots;
- `retention`: the session deletion ordered after custody (non-ZDR profiles, SPEC-06 §8);
- `wake`: provider webhooks reduced to wake-ups.

Importing this package imports no provider SDK.
"""
