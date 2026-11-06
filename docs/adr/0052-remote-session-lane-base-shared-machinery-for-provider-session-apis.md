---
type: Decision Record
title: "Remote Session Lane base: provider session APIs share one stream-then-reconcile machinery, and every lane passes the conformance suite"
description: "Accepted for the materialization-observation sprint (SPEC-06 section 3, HL-04): cursor_cloud, claude_managed and codex_agents drive a provider-run agent loop through a session API; the provider-neutral parts of cursor_cloud move to adapters/remote_session (staging, the stream-then-reconcile observe loop, typed HTTP errors, deterministic and metadata reconciliation of creates, turn anchors for sends, usage settled only when reported, provider workspace custody, webhooks as wake-ups); each provider supplies its classifier, cursor codec, request mappings and readers; no new lane merges without the lane conformance suite."
tags: [mission-control, adr, accepted, execution, lanes, providers]
status: accepted
source: docs/specs/archive/materialization-observation-2026-10/SPEC-06-hosted-api-lanes.md (section 3); docs/specs/archive/materialization-observation-2026-10/MANAGED-AGENTS-REMOTE-PATH.md (sections 2-4); docs/specs/archive/materialization-observation-2026-10/research/codebase-new-lanes.md (section 3); DECISIONS Proposed ADRs 0052; HL-04; ADR-0030; ADR-0037; ADR-0045
---

# Remote Session Lane base: shared machinery for provider session APIs; conformance suite required for every lane

**Status: accepted 2026-11-01; implemented by the materialization-observation Run 2 finish (`b95ae4aa` completion summary; `152a3dcb` finish records, 2026-10-20) and the 1.4 database release (`b434e573`).** Previously proposed. 

Three lane profiles drive an agent loop that the provider runs behind a session API:
`cursor_cloud` (Cursor Cloud Agents), `claude_managed` (Anthropic Managed Agents) and
`codex_agents` (the OpenAI Agents API). Each creates a server-side session, sends turns,
streams events over SSE, cancels or interrupts, and must reconcile a lost response by reading
the provider back. `cursor_cloud` already did all of this in one 1,350-line module; building the
two new lanes the same way would duplicate the hardest parts.

We extract the provider-neutral parts of `adapters/cursor/cloud.py` into
`adapters/remote_session/`, and `cursor_cloud` becomes its first client with no behaviour
change (its suites run unchanged). The base owns:

- **Staging and session state.** `RemoteSessionLane` keeps one process-local `RemoteSession` per
  harness execution (identity refreshed per generation, later-turn texts, the continuation
  handover offer, the rehydration receipt, turn anchors, expired streams). Nothing in it is
  authoritative; `LaneTurnService` keeps the dispatch journal, Stop Fence, session ownership and
  persisted frames.
- **Observe as stream, then reconcile.** Read the stream from the stored cursor; key each event
  by its id, or an id-less event by its content; skip keep-alives; stop at the terminal event. A
  refused cursor replays the turn's stream once from the start. Expired retention writes one
  `stream.expired` status frame and the stream is never asked again. Once the stream ended or
  expired, the turn record is the terminal truth and becomes one synthesized final frame; a turn
  still running after expiry is polled from the record at a bounded cadence with one status frame
  per change. Providers without native resume (Managed Agents, the Agents API) open the stream
  first and replay their history after it (`replay_then_stream`), dropping live duplicates by key.
- **Typed HTTP errors.** Each provider declares an ordered `ErrorRule` table over the neutral set:
  `429` is `CapacityLimited` with `Retry-After` (raised as `ProviderCapacityLimited`, so the
  workflow waits on a Temporal timer), `409` is busy (`wait_then_send`), create conflict
  (reattach) or not cancellable, `401`/`403` is `AccessDenied` and non-retryable, `404`, `410`
  and a refused cursor are typed too. Messages carry the operation and provider code only.
- **Reconciling a lost create or send.** A create the lane can name uses a deterministic
  client id (a provider `404` under it is the authoritative "not received"); a create it cannot
  name carries `mc_dispatch` metadata and is found by listing and matching on the client, where
  absence stays `unknown` unless the provider's listing is authoritative. A send is judged by the
  session's latest turn against the turns the lane and the journal acknowledged.
- **Usage settled only when reported**, cost only when a cost source reports it, otherwise
  `unknown`.
- **Provider workspace custody**: the fenced lease of the session's branch, its head recorded as
  `branch:<branch>@<sha>`, release only after custody.
- **Webhooks as wake-ups.** Signal Ingress verifies and deduplicates provider webhooks
  (ADR-0045, MO-40); the lane receives only the event type and resource id (`SessionWake`) and
  re-reads the session from the provider. A payload's status, results or usage are never trusted.

Each provider adapter supplies its session record, its event source, an event classifier (the raw
kinds of its `KIND_TABLES` and dedupe rows), a cursor codec, the turn-record reader, the final
frame key, the create and send reconcilers, the closing-facts reader, its error table and every
request mapping (create, send, cancel, interrupt, usage), in its own words (`cursor_cloud`
keeps "run", `run.final` and `runId`).

**Lane conformance suite.** `tests/conformance/lanes/` (HL-05) runs the same scenarios against
every lane's fake: describe honesty; start, observe and settle; reattach mid-stream with no
duplicate frames; `send_turn` while busy; cancel; `interrupt_and_inject`; approval round trip;
budget stop; fork emulation; continuation hand-over; unknown usage staying unknown. A lane that
does not pass, or does not declare its exception, does not merge.

We rejected copying `cursor_cloud` per provider (three diverging copies of the hardest code),
a shared HTTP client class (authentication, beta headers and SDK pins differ per provider; the
base shares the stream read and the error mapping instead), and a protocol-only base with no
shared loop (the stream-then-reconcile loop is where the subtle defects live).

## Consequences

- The Cloud Agents errors are both the existing `BridgeError` subclasses and the base's neutral
  errors, so existing `cursor_cloud` callers and the shared loop catch the same exceptions. The
  table keeps Cursor's mapping exactly, including `401` and an unrecognised `403` remaining a
  plain `BridgeError`.
- The SSE parser lives only in `adapters/remote_session/sse.py`; the former
  `adapters/cursor/sse.py` path is removed, not shimmed. `cursor/cloud.py` no longer exports
  its private stream-cursor, snapshot-ref and capacity helpers; the base exposes them.
- `AccessDenied` is also a `ValueError`, so `lane.turn` rejects it non-retryable without a new
  activity error type.
- The base gives no lane a qualification. `claude_managed` (HL-08) and `codex_agents` (HL-12)
  build on it; their drills (HL-24, HL-25) decide qualification.
