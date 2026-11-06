---
type: Decision Record
title: The Mission Transcript is the replayable record
description: Accepted - the run's Transcript (mc.transcript_entry.v2, a persisted projection of frames and ledger facts placed by unit and point) is the one record an operator reads, searches, joins to events and replays a model call from, without a second journal.
tags: [mission-control, adr, accepted, transcript, tracing, replay]
status: accepted
source: docs/specs/archive/provider-consolidation-2026-10/proposals/TRACING-PROPOSAL.md (P1, P3.3, P4, P4.3, TR-D2, TR-D3, TR-D7, TR-D10, TR-D11); ADR-0028; src/mission_control/application/frames/transcript.py
---

# The Mission Transcript is the replayable record

**Status: accepted 2026-11-01; implemented by tracing Stages 1-3 (`6b3f172f`, `05d92929`, `4a281b36`; Stage 3 finish `34d968ee`, merged 2026-10-22).** Previously proposed.  Builds on
[ADR-0028](0028-native-event-store-provider-frames-and-materialized-transcript.md), which keeps
provider frames native and the Transcript a materialized view.

## Context

After a run, an operator needs to answer who ran, what the model saw, what it produced, what
the environment held and why the run moved, and a coordinator needs the same to fork or
evaluate. The pieces existed apart: mission events, provider frames, cognition points and
settlements, joined by guesswork. The system prompt and prior messages of a model call were not
recorded, so a call could not be explained, and a second journal beside the Native Event Store
would have two truths.

## Decision

1. The Transcript is the record. Entries are `mc.transcript_entry.v2`, each placed by unit and
   point, built from provider frames and ledger facts. It is a projection and decides nothing
   (ADR-0028 still holds): the reducer does not read it.
2. The projection is persisted (`mission_control.transcript_entry` with a
   `transcript_projection_state` row). Every settlement writes a `transcript_projection` outbox
   intent in its own transaction; a relay starts the idempotent `transcript.project` job, so
   the projection is seconds behind, can be refreshed on demand, and a repeat delivery rebuilds
   the same rows (TR-D10). Live tails stay on the frame view.
3. What the model saw is recorded as a `model_request` frame taken at the chat-model boundary,
   with message bodies promoted once by digest and the batch digest on every call. Bodies live
   in the content-addressed payload store behind the `frame-body://sha256:...` reference, read
   under `workflow.result.read` and bound to the path's run (TR-D2, TR-D3).
4. Replay is a dry run: the model input of one step is rebuilt from the Transcript alone and its
   digest compared with the recorded batch digest (`mc.replay_report.v1`, `exact` only when
   every message resolved and the digests agree). Nothing is sent to a model; a paid replay is a
   separate decision (TR-D11).
5. Joinability: `unit_key` and `point_ref` travel on mission events and stream envelopes, and
   `point_id` on entries, so events, frames and points join by stable keys, never by text
   (TR-D7).

## Consequences

- One record to read, search (`run transcript`, `run search`), group (`--by`) and download
  bodies from; reads and replay need no extra writer in the settlement path beyond the outbox
  intent.
- The projection must be current before retention deletes anything it summarizes (see
  [ADR-0055](0055-retention-follows-the-mission.md)).
- Replay proves the input was recorded exactly; it is not a reproduction of a nondeterministic
  model answer.
- Capture cost is a deployment profile (`standard` by default), not a manifest field.
- Rejected: a second journal table for model inputs (two truths), a middleware that records
  inputs (it misses the prompt-caching tail), and mission events for every frame (ADR-0028).

# Citations

- [Transcript service and `--full`](../../src/mission_control/application/frames/transcript.py),
  [replay dry run](../../src/mission_control/application/frames/replay.py),
  [projection trigger](../../src/mission_control/application/frames/projection_trigger.py),
  [persisted entries](../../src/mission_control/adapters/postgres/frames/transcript_entries.py),
  [projection job](../../src/mission_control/adapters/temporal/activities/transcript_projection.py),
  [artifact and frame-body download](../../src/mission_control/interfaces/http/artifacts.py).
- Concepts: [Transcript v2 and its projection](../knowledge/provider-frames-and-transcript.md),
  [unit and point joinability](../knowledge/unit-and-point-joinability.md).
