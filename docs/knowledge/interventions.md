---
type: Concept
category: domain-model
title: Interventions
description: The four ways an operator or coordinator steers a running mission (queue an instruction or context at a boundary, interrupt and inject, immediate cancel behind a persisted Stop Fence, fork from a recorded point) plus request_continuation, with each lane's declared delivery semantics, what the reports guarantee and what no intervention changes.
tags: [mission-control, commands, mailbox, stop-fence, interventions, fork, implementation]
aliases: [queue instruction, interrupt and inject, command mailbox, stop fence, steering a run]
questions:
  - How do I queue an instruction, inject, or cancel a run now?
  - What is the difference between queue, inject, interrupt and fork?
  - Does an interrupt-and-inject reach the model and how do I know?
  - What does the Stop Fence guarantee for an immediate cancel?
  - What can an intervention not change in a running workflow?
updated: 2026-11-01
---

# Interventions

An [Intervention](../../GLOSSARY.md) is a privileged operator [Command](../../GLOSSARY.md)
whose delivery semantics are declared by the lane and reported back in a
[Delivery Report](../../GLOSSARY.md). Receipt states, endpoints and events are in
[events and commands](events-and-commands.md); the lane matrices are in
[lanes and harness](lanes-and-harness.md). Decisions: ADR-0008 and ADR-0032.

The owner's model: each provider has a native lifecycle that Temporal wraps so Mission Control can read and write
mission state snapshots and **queue** a message, **inject** context, **interrupt** and **fork**. All four are built
for Deep Agents (queue and inject live-proven on paid fixtures); only a fifth, mutating a workflow per policy mid-run,
is a goal ([revisions](revisions.md)). Interventions change content, timing and which run continues, never the program,
policy, authority or budget of the run they steer. At the four levels: *scheduling* is the boundary an entry is
claimed at (`next_turn`, `next_iteration`, the stage-admission boundary); *output obligations* are untouched (an inject
never fulfills or waives a promise); *context transfer* is a mandatory `queued_instruction` item or a `follow_up_turn`
packet; *runtime* is the lane's declared delivery semantics.

**Fork** is the fourth intervention and has its own concept: a derived run from a recorded position and cognition point
with an optional injected message and typed patch ([precise fork](precise-fork.md), [recovery](recovery.md)).

**Mailbox** (FT-F1, `domain/policies/mailbox.py`, `application/execution/mailbox.py`,
`adapters/postgres/run_control/mailbox.py`, migration 0029). `queue_instruction` and
`add_context` are admitted as pending Commands and each writes one durable
`command_mailbox` entry for the run's current generation in its own `mailbox:<generation>`
space, in the transaction that admits the Command. The family boundary (Stage Graph
admission of the next operation, Goal Loop iteration boundary) claims undelivered entries in
admission order, once per delivery key, and hands them to the packer as mandatory
`queued_instruction` items ([context and continuation](context-and-continuation.md)); the lane
marks them consumed when the carrying turn starts. Entries are never deleted: a cancel
supersedes, a moved generation expires with `stale_generation`, a passed deadline with
`deadline_passed`. Boundaries are `next_turn` and `next_iteration`. A `next_turn` entry is taken at a native completion before
the operation finalizes (`_queued_follow_up`, `application/execution/harness/inject.py:323-340`) when the lane declares
`queue_instruction: turn_boundary_guaranteed`; own delivered or consumed entries are reconstructed after a worker loss
and a stable native message key keeps a replay from appending the same input twice (Qualia bounded queued turns, `0eccfa2d`).

**Interrupt and inject** (FT-F2, `application/execution/harness/inject.py`). By the lane's
declared semantics: `cooperative_inject` (Deep Agents since 2026-11-06: the steer joins the next model call, below), `cancel_and_replace`
(both Cursor profiles and the other session lanes: cancel the running turn, settle uncertain effects within a grace
period or park the unit `in_doubt` with an incident and run no replacement, then run a
replacement turn on the same session from a `follow_up_turn` packet), or `unsupported` (typed
rejection, the turn continues). Since MP-06, `resolve_interrupt_mode` picks exactly one mode: the
per-profile `LANE_COMMAND_SEMANTICS` and the lane describe must agree, and `cooperative_inject`
also needs a lane implementing `SteeringLane` (a `stale_target` answer returns the entry to
`queued` for the next boundary); any disagreement is `unsupported`, never a fallback. Deep Agents steers in-process: `inject()` queues the segment,
`OperatorSteerMiddleware` (`adapters/deep_agents/steering.py`) adds it to the next model call and the checkpointed thread in one step, and a steer the turn never drained runs as its next turn. The replacement send is journaled
and Stop-Fence admitted like every native dispatch, and a cancel already requested starts no
steer or replacement ([session ownership and dispatch](session-ownership-and-dispatch.md)).
Since Run 2 P5b (`aeeda4a4`), the turn that an applied inject interrupted no longer settles the
attempt. The frame-fact projection receives the turns the dispatch journal records as replaced
(stop-fenced replacements excluded) and records their cancelled run result without an attempt
outcome, so the replacement turn settles it (`application/frames/reducer.py`,
`application/execution/harness/lane_turns.py`). Live on `claude_agent_sdk`, inject was applied on
runs b, c, d and j. Two gaps are open and carried to provider consolidation. An inject aimed at a
node that has already finished is neither applied nor refused; it stays queued (run k). A narrow
timing window remains in the P5b fix.

**Immediate cancel and the Stop Fence** (FT-F3, `domain/policies/stop_fence.py`,
`application/execution/stop_fence.py`, `adapters/postgres/run_control/stop_fence.py`).
`cancel` with `urgency: immediate` persists an insert-only fence for the run and generation
before any provider cancel; every Kernel Hook (Deep Agents `wrap_tool_call`, the Cursor hook
callback) asks the fence before admitting an effect and a fenced admission is denied
`STOP_FENCED`. Fence writes and effect admissions of one run serialize on an advisory lock, so
an effect admitted before the fence stays admitted and one after it is denied. It does not halt
a tool already dispatched, and every report says so. Every new native create or send is also
admitted against the fence before it is issued (MP-06), so a fence that lands while
`cancel_and_replace` drains denies the replacement and the unit settles `cancelled`. Permission: `workflow_run.admin` while
side-effecting work may be active, `workflow_run.cancel` otherwise. The report has four
separate timestamps (requested, fence persisted, provider acknowledged, recorded when the
provider acknowledges rather than at settlement, and settled) at
`GET /runs/{id}/stop-fence` and in inspection. On `cursor_cloud` there is no fail-closed
Kernel Hook, so the fence reaches the run only through the API cancel
([cursor lane](cursor-lane.md)).

**What the fence does to a running Deep Agents turn** (tracing Stages 2-3). An immediate cancel
reaches the operation Activity only through its next heartbeat, so a short turn used to finish
first: the fence denied the next tool call, the model was then called once more and the unit
settled `completed` under a persisted fence (live FX-TR-CANCEL-LIVE). Now:

- An immediate cancel **stops the next model call**. The lane asks the fence before every model
  call (`FenceStopMiddleware`, [Deep Agents lane](deep-agents-lane.md)); a fenced run calls the
  model no more, and the stop message closes the turn. A denied tool call still closes with its
  `hook_result`. The stop only applies to a fence **backed by a journaled cancel** (the run is
  `cancelling` or `cancelled`): the fence is written before the cancel command is recorded
  (ADR-0008), so a fence whose cancel the reducer then rejected stays behind and must not end
  work (`domain/policies/stop_fence.py::cancel_journaled`, `run_fence_stops`;
  `application/execution/stop_fence.py::KernelHookFenceGate.run_fence`). A fence that cannot be
  read fails open and the kernel hook still gates every effect.
- A turn that returns under a fence persisted for its run generation **and** backed by a
  journaled cancel settles the unit `cancelled` through the existing cancelled settlement, not
  `completed`: the usage of the completed calls and the turn's cognition points are recorded and
  the fence milestones are written (`operation_execution.py::_settle_fenced_turn`).
- A turn that returns under a persisted fence whose cancel is **not** journaled (in transit, or
  rejected by the reducer) is never settled `completed`. The attempt raises
  `OperationStopFencePending`, releases its lease and retries once the cancel lands, when the
  cancellation saga settles the unit `cancelled`; the retry finds the cancel rejected otherwise.
- The fence generation is the **run's execution-target generation**
  (`domain/policies/stop_fence.py::run_fence_generation`: `ExecutionTarget.execution_generation`,
  1 while no target is bound), not a unit's `execution_generation`. A unit's axis advances with a
  `start_new_generation` reconciliation of that one unit, so comparing it with the fence let a
  generation-2 unit escape the fence. Every reader asks `fence.covers(run_fence_generation(run))`;
  `run_fence_stops` combines that with the journaled cancel.

Since 2026-10-21 (P1 turn 4) an inject into Deep Agents cognition is visible on the run's
cognition points ([recovery](recovery.md)): the leaf the cancel interrupted carries the role
`interrupted` and the replacement's first checkpoint `replacement_start`, on the same thread,
with the injected text in the state as of the result point; proven inside a running executor
turn on the production offline stack (`tests/acceptance/mission_control/test_cognition_points.py`).
The delivery report itself still names turns, not points.

**Request continuation** is admitted where continuation is composed and recorded as `session.continuation_requested`.
For Session Lanes the MP-12 phase machine then seals and transfers it; on Deep Agents it is recorded only
([context and continuation](context-and-continuation.md)).

A `lane.cancel` whose journaled dispatch is ambiguous and has no recorded turn now returns
`in_doubt` instead of settling "never sent".

Built / specified / goal: queue, add context, interrupt-and-inject (Deep Agents `cooperative_inject`, release 1.15.0; `cancel_and_replace` on the other lanes; native steering implemented on Codex, Managed Agents and the Agents API but not yet declared, [cross-provider control](cross-provider-control.md)), immediate cancel with Stop Fence and fork built, tested on PostgreSQL and Temporal, integrated live (Run 2 inject; Qualia queued turn and inject; iteration 3 fork with an operator instruction, 2026-11-06). Since 2026-11-06 queued and injected operator text renders as the packet's final Operator instructions section (`ContextTrust.OPERATOR_INSTRUCTION`), not as data. Per-policy mutation is a goal.

# Citations

- Spec: [SPEC-06](../specs/archive/fast-track-2026-10/SPEC-06-interventions-inspection-subscriptions.md).
- ADRs: [0008](../adr/0008-ordered-commands-with-urgent-stop-fence.md),
  [0032](../adr/0032-interventions-real-queue-inject-cancel-fork-and-subscriptions.md).
- Code: [mailbox policy](../../src/mission_control/domain/policies/mailbox.py),
  [mailbox service](../../src/mission_control/application/execution/mailbox.py),
  [mailbox store](../../src/mission_control/adapters/postgres/run_control/mailbox.py),
  [stop fence policy](../../src/mission_control/domain/policies/stop_fence.py),
  [stop fence gate](../../src/mission_control/application/execution/stop_fence.py),
  [fence stop middleware](../../src/mission_control/adapters/deep_agents/budget.py),
  [fenced settlement](../../src/mission_control/application/execution/operations/operation_execution.py),
  [stop fence store](../../src/mission_control/adapters/postgres/run_control/stop_fence.py),
  [stop fence route](../../src/mission_control/interfaces/http/stop_fence.py),
  [interrupt and inject](../../src/mission_control/application/execution/harness/inject.py),
  [dispatch journal](../../src/mission_control/application/execution/harness/dispatch.py),
  [mission service](../../src/mission_control/application/missions/service.py).
- Tests: [mailbox](../../tests/unit/run_control/test_ft_f1_command_mailbox.py), [mailbox in PostgreSQL](../../tests/integration/postgres/test_command_mailbox_postgres.py),
  [mailbox on Temporal](../../tests/integration/temporal/test_command_mailbox.py), [interrupt and inject](../../tests/unit/operations/test_ft_f2_interrupt_and_inject.py),
  [inject in PostgreSQL](../../tests/integration/postgres/test_ft_f2_inject_postgres.py), [inject on Temporal](../../tests/integration/temporal/test_ft_f2_inject.py),
  [stop fence](../../tests/unit/run_control/test_stop_fence.py), [fence backing](../../tests/unit/run_control/test_run_fence_backing.py),
  [fenced turn](../../tests/unit/operations/test_fenced_turn.py), [turn stops](../../tests/unit/deep_agents/test_turn_stops.py),
  [immediate cancel at T0](../../tests/acceptance/mission_control/test_tracing_stream.py) (`test_fx_tr_cancel_t0`),
  [stop fence in PostgreSQL](../../tests/integration/postgres/test_stop_fence.py), [immediate cancel on Temporal](../../tests/integration/temporal/test_ft_f3_immediate_cancel.py),
  [cancel and replace on Temporal](../../tests/integration/temporal/test_mp06_dispatch_recovery.py), [inspection](../../tests/unit/run_control/test_ft_f6_inspection.py),
  [cognition points](../../tests/acceptance/mission_control/test_cognition_points.py).
