---
type: Concept
category: domain-model
title: Durable controls and human tasks
description: The four durable controls (Event Wait, Timer, Human Gate, Proof Gate) as program nodes that wait rather than work, the human task and review vocabulary, and the run-level waits, held exhaustion waits and task rows that exist today while Timer and Proof Gate remain authoring-only.
tags: [mission-control, durable-controls, waits, human-task, event-wait, implementation]
aliases: [event wait, timer, proof gate, wait condition, durable wait]
questions:
  - How does a run wait on an event, a timer or a proof gate?
  - Which durable controls are real program nodes and which are only authored?
  - What kinds of run-level wait exist and who satisfies them?
  - How does a held route-exhausted wait get resolved?
  - What does a Human Task resolution vocabulary look like?
updated: 2026-11-01
---

# Durable controls and human tasks

A [Durable Control](../../GLOSSARY.md) is a program node that waits rather than works.
It has identity, the shared activation lifecycle, receipts and a terminal outcome, and
other nodes may depend on it. Gate conditions on stages are predicates over the facts
these nodes record; the compiler may synthesize a control from an inline gate
declaration, but the compiled program always contains it explicitly, so there are no
hidden waits (`mission-control-general/workflow-types/05-EXECUTORS_AND_DURABLE_CONTROLS.md` (deleted 2026-11-01; last at `66185d2e`),
section 6; `01-STAGE_GRAPH.md`, section 6).

## The four controls

- Event Wait: an `event_type`, a match predicate over the typed payload, an optional
  timeout with `on_timeout: skip | fail | keep_waiting | escalate`, and a mode of
  `once` or `rearm { max_firings, cooldown, expiry }`. Each firing writes an event
  receipt artifact; in `rearm` mode each firing creates a new activation of the
  dependent subprogram under the same revision (section 6.1).
- Timer: `duration | until`; completes `accepted` when the instant passes. Recurrence
  is a mission-level run schedule, never a node, because a run must be able to
  complete (section 6.2).
- Human Gate: raises exactly one human task and waits on its resolution (section 6.3).
- Proof Gate: gates a consumer's release on evidence recorded elsewhere, through an
  `evidence_ref` or `verification_intent_ref`, a `required_disposition` and
  `on_reject: skip | fail | wait_for_remediation | escalate`. A completion contract
  gates a producer's acceptance; a proof gate gates a consumer's release (section 6.4).

## Human tasks

A [Human Task](../../GLOSSARY.md) has a kind of `APPROVAL`, `QUESTION`, `SELECTION`,
`REVIEW` or `POLICY_OVERRIDE` (`CREDENTIAL` is deferred), a prompt, context refs,
options for `SELECTION`, an assignee policy and a timeout with
`on_timeout: keep_waiting | escalate | default_answer | stop`. Its lifecycle is
`open → claimed → resolved | expired | cancelled`. Its resolution is one attributed
action: `approved`, `denied`, `answered`, `selected`, `review_accept`,
`review_reject` or `overridden`; the answer is an artifact, and an answer cannot
smuggle a policy change (section 6.3).

A [Review Decision](../../GLOSSARY.md) of `approve`, `reject`, `request_changes` or
`abstain` is the payload of a review-kind task, not a second state machine: the task
still resolves as `review_accept` or `review_reject`. No remote UI can resolve a task
without an attributed action, and every embedded review surface has a plain text or
link fallback (ADR-0016). Required human review is never satisfied by notification
delivery (ADR-0008).

The gate's outcome follows the resolution: `approved`, `answered`, `selected`,
`review_accept` and `overridden` give `accepted`; `denied` and `review_reject` give
`not_accepted`; `expired` follows `on_timeout` (`stop` gives `stopped_by_policy`,
`default_answer` gives `accepted` with the default recorded).

## Implemented today

**Human Gate** runs as the `mc.human_gate.v1` control activation over the common Human Task rows,
resolved through one `HumanTaskService` from HTTP, the `/missions` socket and MCP tools; the
StageGraph gate stage and the GoalDirected review sit behind the `mp10-stagegraph-human-gate` and
`mp10-goal-human-review` workflow patches. The production launch lowers manifest gates (an
undeclared Goal Loop reviewer is the `owner` role), a denied gate fails the run, and native
provider approvals and governed effects open `approval:<origin>` tasks on the same service (MP-11).
Detail, evidence and open gaps are in [Human Gates](human-gates.md). An **Event Wait** that is a
Stage Graph stage holds on a declared StageGraph wait and is released by its implied watcher when an
event of its `event_type` whose payload equals its scalar `match` commits (MO-44,
[Watchers](watchers.md)); its `timeout` is not enforced and `rearm` is refused, and the released
stage still runs its stage operation. Timer and Proof Gate are still not program nodes: the manifest parses `TimerNode` and `ProofGateNode`
(`domain/authoring/manifest.py:1063-1075`) but lowering has no stage or wait for them. Stage Graph exhaustion holds
are durable waits of kind `external_result`: `route-exhausted:<route>` and `revisit-exhausted:<region>`, woken only
by an operator command ([stage graph](stage-graph.md)). What else exists:

- Run-level waits. `WaitCondition.kind` in
  `src/mission_control/domain/policies/contracts.py` is `dependency`, `timer`,
  `approval`, `resource`, `budget`, `external_result` or `operator_reconciliation`;
  the reducer in `src/mission_control/domain/policies/reducer.py` sets and satisfies
  waits, and `satisfy_wait` is one of the three family boundary commands
  (`FamilyBoundaryCommandKind` in `src/mission_control/domain/programs/contracts.py`,
  delivered through [lifecycle](lifecycle.md)). An `operator_reconciliation` wait
  blocks terminalization until the typed `reconcile_unit` command resolves an
  in-doubt unit; see [recovery](recovery.md).
- Durable human-task rows. `mission_control.human_task` and `human_resolution` in
  `packages/mission-control-db-contract/component/migrations/0005_commands_effects_recovery.sql`
  hold a typed request packet, `kind`, `assignee_scope`, `deadline_at`, `on_timeout`
  and a lifecycle check of `open | resolved | expired | cancelled`; a resolution
  stores the attributed `actor_ref`, the `answer` JSON with its digest and the
  `expected_task_version`, exactly once per task. Four writers use them: the Human Gate
  repository (`adapters/postgres/human_tasks/repository.py`, kind `human_gate:<KIND>`), the MP-11
  approval task repository (`adapters/postgres/approvals/tasks.py`, kind `approval:<origin>`),
  `PostgresDecisionRepository` in
  `src/mission_control/adapters/postgres/runtime/stage3_kernel_repository.py`
  (kind prefix `runtime_decision:`) and `PostgresRedisApprovalGateway` in
  `src/mission_control/adapters/realtime/postgres_redis.py` (kind `runtime_approval`).
  The older two are tested in
  `tests/integration/postgres/test_stage3_kernel_postgres_integration.py` and
  `tests/unit/runtime/test_runtime_decisions_stage3.py`.
- An `event_receipt` table (`wait_key`, `source_event_key`, `matched_at`,
  `rearm_ordinal`) in the same migration, with no writer in `src/`.

The schema does not enforce the spec's `claimed` lifecycle value, the task-kind
vocabulary or the resolution vocabulary. The Human Gate rules use `approved`, `denied`,
`review_accept` and `review_reject`; `answered`, `selected` and `overridden` have no writer, and
the two older writers record their own request types. Proof Gate has no code or table beyond
`evidence_assessment` (see [completion](completion.md)).

At the four levels: *scheduling* is the wait itself (a Temporal condition, never a held slot); *output obligations* are
untouched (a control gates release, completion or acceptance but fulfills nothing); *context transfer* is the frozen
packet or event receipt the wait carries; *runtime* needs no lane (no cognition runs while waiting).

Built / specified / goal: Human Gate, run-level waits, `satisfy_wait`, held exhaustion waits and Event Wait stages built and tested; Timer, Proof Gate, `rearm` and the `claimed` task state specified only.

# Citations

- `mission-control-general/workflow-types/05-EXECUTORS_AND_DURABLE_CONTROLS.md` (deleted 2026-11-01; last at `66185d2e`) (sections 6-7).
- `mission-control-general/workflow-types/01-STAGE_GRAPH.md` (deleted 2026-11-01; last at `66185d2e`) (section 6, gate conditions).
- `mission-control-general/general-mission-control/SPECIFICATION.md` (deleted 2026-11-01; last at `66185d2e`) ("Public skill CLI MCP and dashboard contract", human decisions).
- [ADR-0008](../adr/0008-ordered-commands-with-urgent-stop-fence.md),
  [ADR-0016](../adr/0016-required-ui-surfaces-with-fallback.md).
- [Policy contracts](../../src/mission_control/domain/policies/contracts.py) (`WaitCondition`),
  [reducer](../../src/mission_control/domain/policies/reducer.py),
  [program contracts](../../src/mission_control/domain/programs/contracts.py) (`FamilyBoundaryCommandKind`).
- [Decision repository](../../src/mission_control/adapters/postgres/runtime/stage3_kernel_repository.py),
  [approval gateway](../../src/mission_control/adapters/realtime/postgres_redis.py),
  [kernel decision contracts](../../src/mission_control/domain/graph_runtime/kernel.py).
- [Human Gates](human-gates.md) for the control activation, service and evidence.
- [Stage-3 kernel PostgreSQL proof](../../tests/integration/postgres/test_stage3_kernel_postgres_integration.py),
  [decision tests](../../tests/unit/runtime/test_runtime_decisions_stage3.py).
- [`0005_commands_effects_recovery.sql`](../../packages/mission-control-db-contract/component/migrations/0005_commands_effects_recovery.sql).
