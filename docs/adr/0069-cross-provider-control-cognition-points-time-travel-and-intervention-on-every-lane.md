---
type: Decision Record
title: Cross-provider control - cognition points, time travel and intervention on every lane
description: Proposed 2026-11-05 (owner direction of the same day) - every Session Lane writes one cognition point per step boundary of a turn from its persisted Provider Frames in the lane.turn settlement, reads state as of a point and seeds forks at the restore level its provider reaches (R1 reconstructed transcript, R2 plus workspace, R3 native session or thread), and steers or cancels-and-replaces through its native lifecycle; the kernel index, reads, fork saga and transcript joins are shared, the native semantics stay lane-owned.
tags: [mission-control, adr, proposed, lanes, cognition-points, time-travel, interventions, cross-provider]
status: proposed
date: 2026-11-05
source: docs/specs/provider-consolidation-2026-10/providers/cross-provider-control/DESIGN.md; Linear OVE-224; owner direction 2026-11-05 ("the same type of control ... for our other providers")
---

# Cross-provider control - cognition points, time travel and intervention on every lane

**Status: proposed 2026-11-05; the shared contracts and the per-lane adapters are being built under
OVE-224.** Extends [ADR-0031](0031-temporal-lifecycle-synthesis-observe-activity-updates-seeded-forks.md),
[ADR-0032](0032-interventions-real-queue-inject-cancel-fork-and-subscriptions.md) and
[ADR-0057](0057-the-precise-fork-closure-family-position-and-the-seed-head.md); keeps
[ADR-0005](0005-deep-agents-first-extend-not-fork.md) (Deep Agents is the reference shape).

## Context

Deep Agents is the only lane whose lifecycle is indexed at the granularity the owner's architecture
promises: one `mc.cognition_point.v1` row per LangGraph root checkpoint, written by the Temporal
settlement, read back as the state at that point, seeded into a derived unit by a fork, and steered by
queue, interrupt-and-inject and the Stop Fence. The other eight lane profiles run through the same
`lane.turn` segment loop and persist every Provider Frame, but their settlement writes no points
(`settle_lane_session` passes none), the cognitive seed contract names a LangGraph checkpoint key only,
and the time-travel registry registers one lane. The schema (0045/0047) and the domain union
(`checkpoint`, `session_cursor`, `thread_item`, `workspace_snapshot`) already anticipated every lane; what
was missing was the plumbing and the per-lane semantics.

## Decision

1. **The point boundary of a Session Lane is a step frame.** A lane folds the persisted frames of one
   native turn into points at `turn_started`, `message`, `tool_call_completed|failed`, `approval_resolved`,
   `after_compaction`, `subagent_ended`, `turn_ended`, `run_result` and `error`
   (`application/execution/harness/points.py::frame_boundary_points`, `STEP_KINDS`); every other frame
   belongs to the next boundary's frame range. The fold is deterministic over persisted frames, so the
   settlement's rows and the reconciler's re-derivation agree. The locator is the lane's native identity
   plus a step reference (`SessionCursorPoint.step_ref`, `ThreadItemPoint.item_ref`); a workspace point
   (`WorkspaceSnapshotPoint`) may name the session and turn it closed.
2. **Points are written by the settlement, as evidence.** `LaneTurnService._settle` asks a lane that
   implements `PointCollectingLane` for the turn's points and `settle_lane_session(points=...)` records
   them in the settlement transaction (`written_by: adapter`); a points failure never fails the settlement
   (the existing savepoint rule). Cancelled and interrupted turns write their points too, with the roles
   `interrupted` and `replacement_start` carried across the inject.
3. **A seed names any point.** `CognitivePointSeed(unit_key, point)` sits beside the unchanged
   `CognitiveSeed(unit_key, checkpoint)` (`AnyCognitiveSeed`); the kernel resolves the row by `(kind,
   locator)`. For a non-checkpoint head the fork saga records a `LaneSeedHead` (`mc.lane_seed_head.v1`)
   on the derived run's `fork_seed` point and the derived unit's first `prepare`/`start` receives it; the
   lane restores it in its own namespace (a new session, thread, branch or lease). The source is never
   written and a repeated seeded fork is idempotent.
4. **Restore levels are declared, admitted and recorded, not assumed.** A lane declares
   `time_travel: {read, fork}` at the level it reaches: R1 the transcript to the point reconstructed from
   frames (`history: reconstructed`), R2 plus the workspace as of the turn's snapshot, R3 the provider's
   own state (a forkable thread or session). A seed is admitted at any declared fork level at or above R1;
   the receipt's `restore_level` and `history` are recorded on the `fork_seed` point.
5. **Intervention follows the provider's native surface.** A provider that steers a running turn
   (Codex `turn/steer`, Managed Agents and the Agents API by a message during the turn) may declare
   `cooperative_inject` through `SteeringLane`; the others keep `cancel_and_replace`. The Stop Fence reaches a
   lane through its Kernel Hooks where they exist, through custom tools on hosted APIs, and only through the
   API cancel where no fail-closed hook runs (Cursor Cloud); each describe states which.
6. **Lane-owned semantics, kernel-owned index.** Each lane package owns `cognition_points.py`,
   `time_travel.py` and its describe cells; `TimeTravelRegistry` is the one router; nothing in the
   application branches on a lane name for a point read, seed or re-derivation.

## Consequences

- One operator surface (`run points`, `state-as-of`, `run fork --point`, `transcript --by step`, queue,
  inject, cancel) behaves the same on every lane, differing only in the declared restore level and
  delivery semantics.
- No new SQL in the first slice; `point_kind` and `lane_profile` already partition the index.
- Local-to-cloud continuity in one session ([goals](../knowledge/goals.md#goal-local-cloud-one-session))
  becomes a fork from a point of one lane seeded into another lane's namespace at the lower of the two
  restore levels; it is not built by this record.
- Provider-hosted products without a documented lifecycle (`claude_cloud`, `codex_cloud`) get the
  architecture and `unqualified` cells only.

# Citations

- [Design and work split](../specs/provider-consolidation-2026-10/providers/cross-provider-control/DESIGN.md),
  [per-lane control architecture records](../specs/provider-consolidation-2026-10/providers/).
- Code: [shared fold and port](../../src/mission_control/application/execution/harness/points.py),
  [cognition point contracts](../../src/mission_control/domain/execution/cognition_points.py),
  [seed contracts](../../src/mission_control/domain/policies/forks.py),
  [lane seed head](../../src/mission_control/domain/execution/lanes.py),
  [cognitive seed service](../../src/mission_control/application/recovery/cognitive_seed.py),
  [time-travel port](../../src/mission_control/application/execution/harness/time_travel.py).
- Concepts: [precise fork](../knowledge/precise-fork.md), [interventions](../knowledge/interventions.md),
  [recovery](../knowledge/recovery.md), [lanes and harness](../knowledge/lanes-and-harness.md).
