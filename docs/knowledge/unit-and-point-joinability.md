---
type: Concept
category: surfaces
title: Unit and point joinability of events and stream envelopes
description: "How a mission event and a stream envelope name the unit and cognition point they belong to - unit_key and point_ref on mc.event.v1 (omitted when empty), unit_key on provider-frame envelopes, after_point_ref on Deep Agents frames - and how a client resumes from a point."
tags: [mission-control, events, streams, tracing, joinability, implementation]
aliases: [unit_key, point_ref, resume from point, event position]
questions:
  - How do I join an event to its unit and cognition point?
  - What is a unit key and who computes it?
  - How do I resume a stream from a point?
updated: 2026-11-01
---

# Unit and point joinability of events and stream envelopes

Tracing Stage 2 (F-S2-4) made events and stream envelopes say whose they are, so a consumer can
join them to the [transcript](provider-frames-and-transcript.md) without reading it. The event ledger is in
[events and commands](events-and-commands.md); the Socket.IO namespace is in
[mission stream](mission-stream.md).

## Events

Since release 1.4.4 an event row can name the unit and the cognition point it belongs to
(`unit_key`, `activation_id`, `point_ref` on `DomainEventEnvelope`,
`domain/policies/contracts.py`; the reducer stamps them from the command). Stage 2 carries
`unit_key` and `point_ref` to the delivered `mc.event.v1` envelope
(`MissionEventEnvelope`, `domain/subscriptions/contracts.py`, built by `envelope_from_row` in
`adapters/postgres/subscriptions/store.py`). Both are omitted from the body while empty
(`exclude_if`), so a run-level event and its signed webhook body are unchanged; a unit event
names its unit and a point event the point.

## Stream envelopes

- A `mission_events` envelope is that same `mc.event.v1` body, so it carries `unit_key` and
  `point_ref` when the row has them.
- A `provider_frames` envelope carries `unit_key`, the activation key of its execution's attempt,
  read once per execution by `PostgresStreamSource.executions` into `ExecutionRef.unit_key` and
  `StreamPosition.unit_key` (`adapters/realtime/stream_source.py`,
  `application/streams/{ports,service}.py`), and, for a Deep Agents frame, `after_point_ref`, the
  point the frame followed (`application/frames/streams.py::deep_agents_after_point_ref`).
- The stream has no `after_point_ref` subscribe parameter. A client resumes from a point by
  subscribing with the cursor of the last frame before the first frame whose `after_point_ref` is
  that point, and receives exactly the remainder of that execution.
- Turn-opening frames are written before the first checkpoint and have no `after_point_ref`; a
  sync child's frames arrive with `include_descendants`.

`test_fx_tr_stream_t0` compares what a client received (every frame, points in order, resume from
a point boundary exact) with the projected transcript.

Built / specified / goal: the unit and point fields on events and envelopes are implemented and integrated locally; a `location`
object and program-level events are not built ([coordinator surface](coordinator-surface.md)).

## Citations

- Ledger: [CHANGES.md](../specs/provider-consolidation-2026-10/providers/deep_agents/CHANGES.md)
  (Turn 6 Stage 2 row 6.8); ADR: [0036](../adr/0036-mission-stream-is-socket-io-over-shared-handlers-postgres-replay-redis-fanout.md).
- Code: [policy contracts](../../src/mission_control/domain/policies/contracts.py),
  [subscription contracts](../../src/mission_control/domain/subscriptions/contracts.py),
  [subscription store](../../src/mission_control/adapters/postgres/subscriptions/store.py),
  [stream source](../../src/mission_control/adapters/realtime/stream_source.py),
  [stream service](../../src/mission_control/application/streams/service.py),
  [frame envelopes](../../src/mission_control/application/frames/streams.py).
- Tests: [stream equals transcript](../../tests/acceptance/mission_control/test_tracing_stream.py),
  [capture client](../../tests/fixtures/stream_capture.py),
  [stream service](../../tests/unit/streams/test_stream_service.py).
