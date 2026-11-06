---
type: Decision Record
title: Retention follows the mission
description: Accepted - frames carry a retention class, deltas expire on a short clock while step frames live as long as the mission's evidence, an expired frame leaves a placeholder, and retention projects a run before it deletes anything.
tags: [mission-control, adr, accepted, retention, transcript, tracing]
status: accepted
source: docs/specs/archive/provider-consolidation-2026-10/proposals/TRACING-PROPOSAL.md (P8a, TR-D1, TR-D17); src/mission_control/adapters/postgres/frames/retention.py
---

# Retention follows the mission

**Status: accepted 2026-11-01; implemented by tracing Stages 1-3 (`6b3f172f`, `05d92929`, `4a281b36`; Stage 3 finish `34d968ee`, merged 2026-10-22).** Previously proposed.  Refines the retention of
[ADR-0028](0028-native-event-store-provider-frames-and-materialized-transcript.md).

## Context

One retention clock for every frame deleted the evidence of a mission 30 days after it was
observed, while the bulk of storage is streaming deltas that no one rereads. A deleted frame
also made the Transcript silently shorter, and a retention pass could remove a body the
projection had not yet summarized.

## Decision

1. A frame has a generated `retention_class` (release 1.4.4). `delta` is `message_delta`,
   `thinking_delta`, `tool_call_delta`, `heartbeat` and `status`; every other frame is `step`.
   Mission events and the other ledger rows are never expired by this policy.
2. Deltas expire after `retain_days` (default 30). Step frames and their promoted bodies are
   kept for the mission's evidence life: `step_retain_days` is NULL by default, and when an
   application sets it (at least 30 days) only frames of terminal runs are deleted. The policy
   is per application; there is no lane-profile retention field (TR-D1).
3. `prune_mode` (`delete`, or `tombstone`, reserved) and the `body_state` vocabulary exist so
   degradation (TR-D17: tombstones, lowering `restore_level`, pins for live fork seeds) can be
   built without another schema change. Until the tombstone writer exists, `tombstone` prunes
   nothing.
4. An expired delta is shown as an `expired` placeholder at its own cursor. A placeholder carries
   no artifact reference, so `--full` cannot reach it.
5. Retention projects before it expires: `expire` brings every run with expiring frames to a
   current projection first. A run that cannot be projected keeps its frames (the cutoff drops
   below its oldest expiring frame; counted as `skipped_unprojected`). In the delete transaction
   the run's projection state is invalidated and a re-projection is queued, so rows holding the
   deleted bodies are never served as current.

## Consequences

- Evidence lives as long as the mission; storage is governed mostly by the delta clock.
- A transcript after expiry is complete in shape: deltas become placeholders, step frames remain.
- A stuck projector delays retention instead of losing history.
- Open: the degradation writer and pins (TR-D17) are not built; saver state ages under the saver's
  own policy, which `point_state_missing` and `restore_level` report honestly.

## Addendum 2026-10-31: Workspace Closures (OVE-204 slice 5)

Workspace Closures (release 1.12.0, [concept](../knowledge/workspace-closure.md)) follow the same
rule with their own clock: a closure row carries `retain_until`, NULL by default (the Application
Profile's `[workspace] closure_retention = "mission"`, the mission's evidence life) or recorded
time plus at least 30 days. The frames `expire` pass calls the definer
`expire_workspace_closures(now)`, which deletes only closures of completed runs past
`retain_until` (entries cascade) and reports `expired_closures`. Retention removes rows, so the
closure stops being readable; promoted bodies are content-addressed and shared across runs, so their
bytes stay until a reference-counted cleanup exists (not built).

# Citations

- [Retention policy and expiry](../../src/mission_control/adapters/postgres/frames/retention.py),
  [expiry job](../../src/mission_control/adapters/temporal/activities/frames_expire.py),
  [frame contracts](../../src/mission_control/domain/frames/contracts.py),
  [projection state](../../src/mission_control/adapters/postgres/frames/transcript_entries.py).
- Concept: [Transcript v2 and its projection](../knowledge/provider-frames-and-transcript.md). Related:
  [ADR-0054](0054-the-mission-transcript-is-the-replayable-record.md).
