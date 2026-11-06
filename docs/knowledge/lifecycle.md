---
type: Concept
category: domain-model
title: Run admission and lifecycle
description: How authenticated scope, immutable admission and durable command effects connect, how accepted, delivered and applied commands differ, how a run is terminalized or recovered when its family cannot progress, and where the specified mission lifecycle differs from the schema's.
tags: [mission-control, lifecycle, admission, commands, reducer, implementation]
aliases: [run lifecycle, admission, command effects, terminal liability, run phases]
questions:
  - How is a run admitted and its lifecycle controlled?
  - What is the difference between an accepted, delivered and applied command?
  - How do I end a run whose family workflow cannot progress?
  - How does an operator reconcile a terminal liability?
  - Which lifecycle values do the spec and the schema disagree on?
updated: 2026-11-01
---

# Run admission and lifecycle

The API authenticates a signed identity and resolves a trusted installation,
application and tenant binding. A route cannot select another pool or grant itself
permissions. The bound service's request scope must match the resolved identity.

Admission injects actor and scope from trusted context, validates the immutable Compiled Program (code: ERC)
and workflow references, and delegates to the existing run-control reducer.
Launch verifies the admitted family and exact input binding before Temporal start.
Repeated starts verify the actual first history event and immutable root payload.

Commands carry a stable request ID, target, expected version and generation.
Permission checks precede replay lookup. Exact repeats replay the receipt; changed
content conflicts. The reducer commits accepted commands and the delivery ledger;
Temporal later receives and applies them at supported boundaries.

Accepted, delivered and applied are different facts. Pause/resume/satisfy-wait
follow persisted boundary semantics; normal-urgency cancellation delegates to the
existing runtime contract. Pause, resume, satisfy-wait, cancel and the mailbox commands (`queue_instruction`, `add_context`,
`interrupt_and_inject`) are admitted as Reducer actions (`application/missions/service.py::_action`, `:412-423`;
[interventions](interventions.md)); any other control is refused `unsupported_control` rather than pretending to
enqueue unsupported work.

A run never outlives its family silently (W1 D15): when the family workflow ends without
terminalizing, the root terminalizes the run with the typed cause (`failed`, or `cancelled` after
an accepted cancel); see [temporal synthesis](temporal-synthesis.md). A normal cancel that the family cannot reach
(its workflow makes no progress) is recovered by the operator, bounded: an immediate cancel
(`workflow_run.admin` while work is active or cancelling; the disposable Sprint OC operator holds
it) persists the Stop Fence, and if the family still cannot act, terminating the family workflow
(`temporal workflow terminate --workflow-id <root id>/family/<epoch> --reason ...`) lets the root
record `cancelled` with cause `terminated`. Terminating the root instead leaves the run open.
A unit whose budget or effect never settles (for example a saved settlement still waiting on its
evaluators) no longer holds the run open (W1 D26). From activity attempt 8 ([ADR-0011](../adr/0011-distinct-retry-counters-and-retry-classifier.md):
the activity's own attempt counter), and only when the previous attempt was refused at the same
run version (no settlement progressed; a progressing one keeps waiting within the root's 32
attempts), the terminalization names every unsettled reservation, pending settlement and effect
as a terminal liability (`TerminalizationProposal.unsettled_liabilities`; evidence
`budget_unsettled_at_failure:<kind>:<id>:<amounts>`). The reducer closes the run `failed`
(`cancelled` after an accepted cancel) only when the names are exactly what is outstanding;
nothing is released on the unit's behalf and a late settlement is refused (`run_is_terminal`).

Operator reconciliation of a terminal liability: (1) the close journals an actionable blocked
notice (`workflow_run.terminalize` with `condition_kind=operator_reconciliation`), and the closed
run keeps one `operator_reconciliation` wait per liability (condition
`operator-reconciliation:terminal-liability:<name>:gen:1`, scope `{<name>}`), listed by run
inspection as `operator_reconciliation_waits`; (2) the operator reconciles the provider and native
side (the recorded evidence names reservation amounts, effect operation and reservation);
(3) with `workflow_run.reconcile_unit` they POST `/run-control/v1/runs/{run_id}/commands` with a
`reconcile_terminal_liability` action carrying a non-empty `attestation` (journaled as the
event's reason): a `reservation:<id>` is `released` (nothing consumed; refused as
`unsettled_usage_on_reservation` while recorded usage against it is unsettled) or `settled` with
the confirmed `actual_amounts` within what remains (an overrun is refused,
`settlement_exceeds_reservation`), the rest released, through the usage ledger; `pending_settlement`
and `effect:<id>` are `acknowledged`, recorded in the run's `acknowledged_liabilities` so they are
no longer listed as unexplained. The command removes that wait and never changes the outcome.

Inspection reports execution lifecycle and outcome separately. A completed
execution is not a new proof of the general architecture's mission acceptance.

## Three lifecycles and the spec drift

Every aggregate follows a three-field law: a `lifecycle`, an optional `phase` and a separate `terminal_outcome`.
The run's reducer phases are `pending, active, waiting, paused, cancelling, terminal` with outcome `completed,
partially_completed, failed, cancelled` (`RunPhase`, `RunOutcome`, `domain/policies/contracts.py:108-121`; acceptance
is separate, [completion](completion.md)). Family boundary commands are `pause, resume, satisfy_wait`
(`domain/programs/contracts.py:115`). The mission lifecycle in the schema is `draft, admitted, active, paused,
closing, closed` with `closure_outcome` `succeeded, failed, cancelled, abandoned`
(`0002_authoring.sql:22-36`); the deleted annex `workflow-types/07` §10a specified `drafting, ready, running,
dormant, closed` with `closure_outcome` `mission_accepted, not_accepted, abandoned, superseded`, and that vocabulary
is not what the code uses. The activation vocabulary is the same story (see [completion](completion.md)).
Mission-level `paused` and `blocked` are run or activation facts in the specification, not mission lifecycle.

Built / specified / goal: admission, ordered commands, boundary delivery, family-failure terminalization and operator reconciliation built, tested on PostgreSQL and real Temporal (`tests/integration/temporal/test_w1_family_failure_root.py`); the specified mission and run state machines are specified only; changing a run's policy mid-run is a goal ([revisions](revisions.md)).

# Citations

- [Mission lifecycle facade](../../src/mission_control/application/missions/service.py).
- [Admission wrapper](../../src/mission_control/application/missions/admission.py).
- [Run reducer service](../../src/mission_control/application/execution/service.py).
- [Boundary relay](../../src/mission_control/application/execution/boundary_relay.py).
- [PostgreSQL HTTP lifecycle proof](../../tests/integration/postgres/test_mission_control_lifecycle_postgres.py).
- [Family failure terminalization](../../src/mission_control/application/execution/family_failure.py)
  and its proof `tests/integration/temporal/test_w1_family_failure_root.py`.
