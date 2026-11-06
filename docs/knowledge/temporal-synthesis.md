---
type: Concept
category: execution
title: Temporal synthesis of provider lifecycles
description: How each provider's native lifecycle becomes Temporal workflows over mission state snapshots - the root, family and operation workflows, bounded lane.turn segments, commands as Updates, durable waits, forks from snapshots - and how Stage Graph and Goal Loop (GoalDirected) execute, settle and fail on it; per-policy mutation is a goal.
tags: [mission-control, temporal, workflows, lifecycle, snapshots, stage-graph, goal-loop, implementation]
aliases: [lifecycle synthesis, lane.turn, mc.mission_run.v1, operation workflow, family workflow]
questions:
  - How do provider lifecycles run as Temporal workflows over snapshots?
  - How do Stage Graph and GoalDirected runs execute on Temporal?
  - How does a queued message, inject or fork reach a running provider?
  - How does a workflow wait durably for something outside Temporal?
  - Which control over a running workflow is a goal, not built?
updated: 2026-11-01
---

# Temporal synthesis of provider lifecycles

Each provider has its own lifecycle: a LangGraph thread with checkpoints (Deep Agents), a bridge or Cloud Agents run with offsets (Cursor),
an SDK or app-server thread (Claude Agent SDK, Codex), a remote session (Managed Agents, Codex Agents). Mission Control does not
adopt any of them as the schedule. A harness maps the native lifecycle onto one neutral protocol ([lanes and harness](lanes-and-harness.md)),
and **Temporal alone schedules** (ADR-0004): workflows wrap provider turns in activities, persist what was observed, and let the
workflow read and write *mission state snapshots* so it can fork, queue a message, inject context and interrupt. The owner's next step
is to *mutate per policy*, for example change a workflow mid-workflow: a goal, not built (below). Reducers own lifecycle and
settlement; an accepted command, a delivered signal and an applied effect are three different facts.

## The workflow tree

| Workflow (registered name) | Role | Source |
| --- | --- | --- |
| `mc.mission_run.v1` | root of a new scoped run; id `mc/{installation}/{application}/run/{run_id}` | `adapters/temporal/workflows/mission_run.py:53` |
| `belllabs.stagegraph`, `belllabs.goal-directed` | the family: schedules the program | `workflows/stagegraph.py:167`, `goal_directed.py:209` |
| `belllabs.operation.v2`, `mc.operation.v1` | one bounded operation attempt: admission, binding, cognition, settlement | `workflows/operation.py:296,1280` |
| `mc.human_gate.v1`, `mc.watchers.v1`, linked-run and nested-body workflows | human tasks, watchers, linked missions, nested bodies | `workflows/human_gate.py:48`, `watchers.py:109` |

`belllabs.run.v1` (`belllabs_run.py:39`) is the older root; new roots use `mc.mission_run.v1`, scoped operation children use
`mc.operation.v1`. Ids carry installation, application and run (`contracts/identities.py:53`); an operation's id is `<root id>/operation/<semantic attempt>` and a family's `<root id>/family/<epoch>`; family inputs must match the root's
scope, Compiled Program (`EffectiveRunConfiguration`, ERC), workflow type and epoch, and cross-parent operation requests fail before child
launch. Typed search attributes (`mc_mission_id`, `mc_run_id`, `mc_lane`, `mc_phase`, `ForkedFromRunId`) make run listing a visibility query
(`adapters/temporal/search_attributes.py`). Replay never touches a provider; every I/O lives in an activity, and `workflow.patched` guards changes.

## Scheduling: Stage Graph and Goal Loop

*Stage Graph* interprets a dependency graph and reconciles runnable stages as operations settle; unrelated work does not wait for a
slow stage. Stages run concurrently up to `max_concurrency`, which a manifest sets with `concurrency` and which defaults to 1
(`domain/authoring/manifest_lowering.py`). A declared wait in front of stages that can never be released no longer parks the run: when a
required producer failed and every waiting stage is unreleasable the family proposes the concluded failure (patch
`tracing-s3-stagegraph-skip-unreachable-wait`). *GoalDirected* (the built subset of the Goal Loop system) prepares executor/verifier
iterations and reconciles durable results until convergence or stopping rules decide ([workflow systems](workflow-systems.md),
[goal loop](goal-loop.md)). Both launch governed operations; Deep Agents receives an exact materialized binding and cannot become a
second scheduler or bypass the budget ledger. Result decisions are family mutations whose fingerprint excludes set iteration order
(`FamilyAdmissionCommit`, `contract_fingerprint(mutation, exclude={"decided_at"})`, Run 2 P5d `5149bcbb`), so Postgres replay verifies
in any process. Long families continue-as-new at iteration boundaries when `is_continue_as_new_suggested()` is true, after handlers drain,
carrying handled command ids; mission chains advance through the outbox, not child workflows (ADR-0029, ADR-0031).

Failure paths that must terminate (W1, OVE-169): an unusable executor or verifier answer settles as a typed `output_unparseable`
outcome, not a retry (`application/programs/goal_directed.py::_parsed`); reconcile retries are bounded (`RECONCILE_MAX_ATTEMPTS = 64`,
`goal_directed.py:159`); a verifier unit that failed deterministically settles a recorded `rejected` verification so convergence ends
(`_undelivered_verification`); a reconciliation request over 1,900,000 bytes fails the family typed (`goal_reconciliation_oversize`);
run-control fields keep an 8192-character bound while `bounds_own_payload` contracts scan up to 2,000,000
(`domain/policies/payload_bounds.py`); a family that ends without terminalizing is terminalized by the root (patch
`w1-d15-root-terminalizes-failed-family`, `application/execution/family_failure.py`). An operator ends a stuck family by terminating the
*family* workflow, never the root ([lifecycle](lifecycle.md)).

## Output-contract obligations

A Deep Agents unit that completed saves its exact result (`mission_control.invocation_settlement`, release 1.7.0) before the settlement pass
(assessment handoff, effect receipts, reviews). When that pass waits, `operation.execute`, `operation.cancel` or a governed `lane.turn`
returns `waiting` with a typed `SettlementWait`; `mc.operation.v1` sleeps on a durable timer (`operation.py::_wait_settlement`, patch
`oc-wi04-saved-settlement-wait`, `DEFAULT_SETTLEMENT_WAITS_PER_RUN = 500`) and runs the boundary again, which settles the saved result with no
model call ([saved-result settlement](saved-result-settlement.md)). Families see only the terminal disposition. Completion is never
acceptance ([completion](completion.md), [output contracts](output-contracts.md)).

## Context transfer and snapshots

Each family binds a frozen template to one live attempt without reading the lane's bytes (OC-R2): the template carries one sealed
`lane_binding` plus `lane_dispatch`, and the preparation services (`StageGraphOperationPreparationService.materialize`,
`GoalDirectedOperationPreparationService.prepare`) hand it with the live coordinates to `LaneRebinders.rebind`
(`application/resolution/lane_bindings.py`); heartbeat class, segment bounds and the activity queue come from `lane_dispatch`
(`domain/execution/heartbeats.py`). The state the workflow can read and write is evidence the kernel keeps beside the provider's:
checkpoint lineage, **cognition points** (one row per observable point of a unit generation), Snapshots (validated safe boundaries with
immutable manifests) and workspace closures. A **fork** creates a new run from a sealed snapshot through the fork saga, seeds an
instruction and, where the lane declares `time_travel.fork: R3`, a cognition point; Temporal reset is excluded because it terminates the run
and re-applies signals that paid for effects ([recovery](recovery.md), [precise fork](precise-fork.md), ADR-0031). A packet fed to the next stage:
[context and continuation](context-and-continuation.md).

## Runtime: provider turns as bounded segments

`lane.turn` activities (`adapters/temporal/activities/lane_turn.py`) prepare or reattach, send the turn, persist every Provider Frame, heartbeat the
provider cursor and return only closing facts; a segment ends at its bound or a terminal frame, with `lane.status` as reconciler and
`lane.cancel` idempotent. Persisted frames are the resume truth, the throttled heartbeat a hint; a lost native turn makes the unit `in_doubt`,
never a duplicate send ([session ownership](session-ownership-and-dispatch.md)). Deep Agents runs `operation.execute` unless
`MISSION_CONTROL_LANE_SEGMENT_LOOP=true`. Provider-limit waits sleep on a Temporal timer bounded by the segment budget
(`operation.py::_wait_out_capacity`, `wait_for_limit_reset`, `domain/execution/usage_admission.py:249`).

## Controls over a running workflow

- **Commands are Updates with validators** (ADR-0008): family `deliver_boundary_command` (contiguous `target_sequence`, else `gap`) and
  `deliver_cancel` (`stagegraph.py:211,248`, `goal_directed.py:258,286`); operation `cancel_command`, `pause_command`, `resume_command` (`operation.py:358-425`). The ack proves
  *delivered*, never *applied*; the receipt ledger is the authority. Update dedupe holds only within one run, so ids carry across continue-as-new.
- **Queue a message** is consumed once at `next_turn` or `next_iteration`; **inject** at a safe boundary with an exact context artifact; **interrupt**
  is cancel-and-replace where the lane qualifies it, else boundary-only; a Stop Fence supersedes undelivered ordinary messages ([interventions](interventions.md)).
- **Cancel** is activity cancellation, then idempotent `lane.cancel`, then polling to a final state; a cancel reaches an activity only at a heartbeat.
- **Hints, not authority:** `ingress_wake`, `unit_reconciliation_recorded`, `liability_reconciled`, `resolution_committed` only wake a workflow, which re-reads PostgreSQL.

## Durable waits (the pattern a batch wait would reuse)

Workflows wait with `workflow.wait_condition` on a counter or flag plus an optional timeout, holding no activity slot: `HumanGateWorkflow`
(`human_gate.py`: resolution-hint signal, poll/deadline timer, re-read the persisted task), settlement waits, capacity waits, in-doubt waits
(`woken` predicate on a nudge counter, `operation.py:636-655`), and ingress probes (`ingress_wake` triggers a bounded `lane.status` read, patch
`INGRESS_STATUS_PATCH`, `MAX_INGRESS_PROBES_PER_SEGMENT`; drainer `bootstrap/ingress_drainer.py:355`). A wake carries only a resource id. Provider batch
would add one more (goal): [provider batch](provider-batch.md).

Built / specified / goal: workflow tree, segments, Updates, forks, waits built and integrated with real Temporal (`tests/integration/temporal/`);
per-policy mid-workflow mutation is a goal ([revisions](revisions.md)); cross-provider local-to-cloud continuity in one session is a goal
([lanes and harness](lanes-and-harness.md)).

## Citations

- ADRs: [0004](../adr/0004-temporal-sole-scheduler-transactional-outbox.md), [0008](../adr/0008-ordered-commands-with-urgent-stop-fence.md), [0029](../adr/0029-mission-chains-compile-to-linked-missions-released-by-outbox.md), [0031](../adr/0031-temporal-lifecycle-synthesis-observe-activity-updates-seeded-forks.md), [0041](../adr/0041-continuation-is-a-persisted-phase-machine-driven-by-the-operation-workflow.md).
- Code: [mission root](../../src/mission_control/adapters/temporal/workflows/mission_run.py), [StageGraph](../../src/mission_control/adapters/temporal/workflows/stagegraph.py), [GoalDirected](../../src/mission_control/adapters/temporal/workflows/goal_directed.py), [operation](../../src/mission_control/adapters/temporal/workflows/operation.py), [human gate](../../src/mission_control/adapters/temporal/workflows/human_gate.py), [lane activities](../../src/mission_control/adapters/temporal/activities/lane_turn.py), [Goal Directed results](../../src/mission_control/application/programs/goal_directed.py), [manifest lowering](../../src/mission_control/domain/authoring/manifest_lowering.py), [family failure](../../src/mission_control/application/execution/family_failure.py).
- Tests: [scoped identities](../../tests/unit/mission_control/test_temporal_identities.py), [signed API runtime](../../tests/acceptance/mission_control/test_authenticated_scoped_runtime.py), [failed producer behind a wait](../../tests/acceptance/mission_control/test_tracing_stream.py), [unparseable Goal answers](../../tests/acceptance/mission_control/test_goal_output_unparseable.py), [W1 failure paths](../../tests/unit/orchestration/test_w1_goal_failure_paths.py), [family failure root (real Temporal)](../../tests/integration/temporal/test_w1_family_failure_root.py), [lane turn](../../tests/integration/temporal/test_lane_turn.py).
