---
type: Concept
category: execution
title: Snapshots forks and reconciliation
description: How recovery preserves immutable lineage and distinguishes uncertain work, including forks that carry a queued instruction, seed a cognition point inside the fork saga and restore a Cursor Local lane snapshot, what a Cursor Cloud fork still lacks, and how local workspace leases are kept, cleaned and continued from their custody snapshots.
tags: [mission-control, implementation]
aliases: [snapshot, fork, reconciliation, cognition points]
questions:
  - How do I snapshot, fork or reconcile an uncertain run?
  - What is a cognition point and how do I read the state at one?
  - Why does a fork never copy the source mailbox or children?
  - How are local workspace leases kept, cleaned and continued?
updated: 2026-11-06
---

# Snapshots forks and reconciliation

Snapshots capture validated safe boundaries and immutable manifests. A fork names
the exact snapshot digest, applies admitted patch policies, records lineage and
reuses only work that remains valid. Changed work is rerun through the normal
operation engine. Fork admission is scoped and idempotent; it is not a direct copy
of provider state into authoritative completion.

Checkpoint lineage is evidence. Unknown or foreign checkpoints cannot silently
become trustworthy results. The existing incident path classifies uncertain units
as in doubt and requires an authorized reconciliation decision. Actions retain
generation fences and settlement receipts.

The public runtime adapter delegates to real snapshot, fork and reconciliation
services. It does not synthesize a successful retry or expose an unimplemented
generic retry command. Immediate intervention semantics are limited to mapped,
supported controls.

## Forks seeded with an instruction and a lane snapshot

A fork never copies the source run's mailbox, children or in-flight commands
(REQ-CP-EXEC-012). After the fork saga admits the derived run, `application/recovery/fork_seed.py`
writes into the derived run's own [command mailbox](events-and-commands.md) two ordinary,
reducer-admitted commands with ids derived from the fork request, so a retried fork re-reads
them: the optional operator instruction as a `queue_instruction` (boundary `next_turn`,
attributed to the forking actor), and the Snapshot restore as a kernel `add_context` with
`expand: workspace`, which the first boundary seals into a `fork`-purpose Context Packet as its
single `workspace` item ([context and continuation](context-and-continuation.md)). Nothing is
launched: `run start` stays separate. Surfaces: `POST /runs/{id}/forks` (the latest safe Snapshot
by default, optional instruction), `missionctl run fork --instruction-file`, MCP
`mission_run_fork`; sponsorship and approvals are the principal's own claims, never the
request's. A fork is findable with `run list --query "forked_from='<run>'"` through the
`ForkedFromRunId` search attribute.

Restore is lane specific. `cursor_local` freezes a lease as `mc.cursor_snapshot.v1` and
`end_session` records the `cursor-snapshot:<ref>` on the released lease; the Snapshot service
puts that ref first in `sandbox_snapshot_refs` (else `run-snapshot://<id>`, which the lane
refuses with `CHECKPOINT_INVALID`), and the derived run's first lease re-applies the patch and
files with every digest verified ([cursor lane](cursor-lane.md)). Deep Agents runs have no
leases and their snapshots are unchanged. `cursor_cloud` fork restore is not built: the lane
expects a `branch:<branch>@<sha>` ref that nothing records yet.

## Cognition points and forks from a point

Since 2026-10-21 (P1 turn 4) the kernel indexes every provider lifecycle as **cognition
points** (`mc.cognition_point.v1`, `mission_control.cognition_point`): one row per observable
point of a unit generation, named by an `mc.cognition_coordinate.v1` whose `point` is a tagged
union the lane reads exactly (`checkpoint` for Deep Agents root checkpoints; `session_cursor`,
`thread_item` and `workspace_snapshot` reserved for the other lanes). A row carries the unit's
location (stage or role, iteration or workflow cycle, stage cycle, session generation) so a
coordinator filters by them, the Temporal activity attempt that wrote it (with its task
queue), the session turn, the frames recorded while the step ran, redacted state facts and
its roles (`input`, `intermediate`, `leaf`, `result`, `interrupted`, `replacement_start`,
`fork_seed`). The Deep Agents adapter returns the points with its `RuntimeResult`
(`adapters/deep_agents/cognition_points.py`); the settlement records them beside the
transition and result (`CheckpointLineageService.record_result`): points are evidence and
never settle anything. Reads: `GET /v1/applications/{app}/runs/{id}/points` with filters,
`GET .../points/{point_id}/state-as-of` (the lane's `read_as_of` through the time-travel
registry, `workflow_run.read_checkpoint_summary`), `missionctl run points | state-as-of`, MCP
`mission_run_points | mission_run_state_as_of`. On Deep Agents `state-as-of` reaches R3: the
graph state at the point with secrets and oversized content hidden.

A fork may name a `cognitive_seed` (a seedable point of a settled unit) when its lane declares `time_travel.fork: R3`. The lane's `seed_fork` restores the point into the derived unit's own
namespace and a `fork_seed` point on the derived run names the source coordinate and restore level (`application/recovery/cognitive_seed.py`). The seed runs inside the fork saga before the
receipt, so a seeded fork without its seed refuses to launch (`fork_seed_pending`, retryable), an unreachable saver is `503 cognitive_seed_unavailable`, and repeating the same seeded fork is idempotent.
Positions, frontier closure, `start_position`, the Goal Directed rules, trusted manifest-provenance admission and the typed refusals are in [the precise fork](precise-fork.md). A fork without
`--baseline-reservation` holds the source run's admitted baseline. The kernel route `POST /run-control/v1/runs/{id}/forks` records the closure honestly and refuses a `message`; `state-as-of` for a
point whose saver state is gone is `404 point_state_missing`.

A reused unit's settlement copies the source result; under output contracts its outputs are
accepted obligation revisions of the source run, so the operation boundary first carries them,
still accepted, into the derived run (`application/recovery/fork_outputs.py`); a derived run of a
manifest Stage Graph starts through `missions:start` from its source's submission, and a concluded
Stage Graph failure names its rejected and dependency-starved stages in `run inspect`
`unit_failures` (all in [the precise fork](precise-fork.md), 2026-11-06).

## Local workspace custody and cleanup

Every local lane (`cursor_local`, `claude_agent_sdk`, `codex`) leases through
`WorkspaceAllocator.acquire` under its binding's admitted `workspace.policy` (MO-05, SPEC-03
section 2); a `cursor_local` binding sealed before the policy existed keeps the per-generation
`CURSOR_LOCAL_POLICY`. Under `shared_checkout` the run's first holder leases the parent and a
later holder continues it in place once the parent released it. A writable session never joins a
live parent (`WORKSPACE_LEASE_HELD`): each local lane writes its own packet, hook context,
callback token and state roots at fixed worktree paths, and no coordination model is declared.
Only a `read_only` request joins the live parent through `join_shared`; the parent lease records
it until it leaves (`leave_shared`), and the parent's cleanup refuses meanwhile
(`WORKSPACE_SHARED_ACTIVE`, retained). No lane issues a read-only request yet.
`end_session` registers the worktree's custody snapshot (`workspace_snapshot` and
`workspace_snapshot_ref` on the lease, beside the lane's own restorable `snapshot_ref`) and
releases the lease, keeping the worktree. After a `completed` unit settles, the operation workflow
runs `lane.cleanup` (patch marker `mo05-workspace-cleanup`): the lane (`WorkspaceLeasingLane`)
removes the worktree only while it is exactly what the custody froze; a refusal keeps it and
names its code, and failed or cancelled work is never cleaned. The next holder of a reused slot
takes a remaining worktree over in place (the predecessor's cleanup then records
`not_required`), or starts a fresh one from the newest holder's retained
custody snapshot, so cleanup never loses the slot's work; a newest holder whose worktree lies
under another lane's root without custody is refused (`WORKSPACE_CUSTODY_MISSING`). Nothing
sweeps retained worktrees after a retention interval yet.

A failed operation may retry according to its exact execution contract. That is
different from inventing a new mission-level command or replaying uncertain side
effects. Review effect/journal state before changing retry or recovery behavior.

Built / specified / goal: snapshots, forks, cognition points, reconciliation and lease cleanup built and integrated (live paid forks, `NEXT-SESSION.md:69-98`); since 2026-11-05 every Session Lane writes points and seeds forks at its declared level ([cross-provider control](cross-provider-control.md), built and tested on PostgreSQL and Temporal, not live); `cursor_cloud` fork restore and
retention sweeps of retained worktrees not built; cross-lane (local to cloud) forks are a goal; Temporal reset is never used for forks (ADR-0031).

## Citations

- [Public runtime service](../../src/mission_control/application/missions/runtime.py).
- [Fork saga](../../src/mission_control/application/recovery/run_forks.py).
- [Fork persistence](../../src/mission_control/adapters/postgres/runtime/run_forks.py).
- [Fork seed](../../src/mission_control/application/recovery/fork_seed.py),
  [cognitive seed](../../src/mission_control/application/recovery/cognitive_seed.py),
  [precise fork](precise-fork.md).
- Cognition points: [contracts](../../src/mission_control/domain/execution/cognition_points.py),
  [index and composition](../../src/mission_control/application/execution/cognition_points.py),
  [Postgres index](../../src/mission_control/adapters/postgres/operations/cognition_points.py),
  [Deep Agents collector](../../src/mission_control/adapters/deep_agents/cognition_points.py),
  [Deep Agents time travel](../../src/mission_control/adapters/deep_agents/time_travel.py),
  [time-travel port](../../src/mission_control/application/execution/harness/time_travel.py),
  [HTTP](../../src/mission_control/interfaces/http/cognition_points.py);
  tests [unit](../../tests/unit/operations/test_cognition_points.py),
  [collector](../../tests/unit/deep_agents/test_cognition_points_collector.py),
  [acceptance on the production stack](../../tests/acceptance/mission_control/test_cognition_points.py).
- [Cursor snapshot and restore](../../src/mission_control/adapters/cursor/snapshot.py).
- [Workspace allocator](../../src/mission_control/application/workspaces/service.py),
  [`lane.cleanup`](../../src/mission_control/adapters/temporal/workflows/operation.py),
  [local lane workspaces](../../tests/unit/workspaces/test_local_lane_workspaces.py),
  [cleanup on real Temporal](../../tests/integration/temporal/test_mo05_workspace_cleanup.py).
- Spec: [SPEC-06](../specs/archive/fast-track-2026-10/SPEC-06-interventions-inspection-subscriptions.md) (Fork),
  [ADR-0032](../adr/0032-interventions-real-queue-inject-cancel-fork-and-subscriptions.md).
- [Real fork and reconciliation tests](../../tests/unit/run_control/test_mission_control_runtime.py).
- [Fork with instruction](../../tests/unit/run_control/test_ft_f4_fork_instruction.py),
  [fork in PostgreSQL](../../tests/integration/postgres/test_ft_f4_fork_postgres.py),
  [lane controls in PostgreSQL](../../tests/integration/postgres/test_ft_g4_lane_controls_postgres.py).
