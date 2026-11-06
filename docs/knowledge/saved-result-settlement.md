---
type: Concept
category: persistence
title: Saved provider results and durable settlement
description: "How a completed provider result is saved before any assessment, effect or review wait, how one durable record and the unit's operation workflow settle it without dispatching cognition again, and how cancellation, fences and typed waits keep lifecycle, execution outcome, fulfillment and settlement separate (Sprint OC WI-04)."
tags: [mission-control, outputs, settlement, temporal, deep-agents, recovery, implementation]
aliases: [saved result, durable settlement, settlement wait, WI-04]
questions:
  - How is a provider result saved and settled without a rerun?
  - Why is a unit waiting on settlement after the agent finished?
  - What happens to a pending review when a run is cancelled?
updated: 2026-11-01
---

# Saved provider results and durable settlement

Sprint OC WI-04 (OVE-166, RV-01) realizes the settlement half of `InvocationFinalization@1`
(OUTPUT-CONTRACTS §4): completed provider work is saved **before** post-execution assessment,
effect or review settlement, a durable owner settles it, and a review or receipt wait never reruns
successful cognition or repeats a native write.

## The record

`mc.invocation_settlement.v1` ([record](../../src/mission_control/domain/execution/invocation_settlement.py),
[store port](../../src/mission_control/application/execution/operations/invocation_settlement.py),
[PostgreSQL store](../../src/mission_control/adapters/postgres/operations/invocation_settlement.py),
table `mission_control.invocation_settlement`, migration `0058_saved_execution_settlement`, release
1.7.0): one row per bound operation attempt whose cognition completed. Immutable: identity, the exact
`RuntimeResult` (output, usage, captured checkpoint, cognition points) with its digest, the execution
outcome `completed`. Advanced by compare-and-set on `version`: settlement `pending` -> `waiting` (typed
reason `review_pending`, `effect_pending` or `settlement_unavailable`; pending review and effect refs;
next action) -> `settled` (terminal), fulfillment and finalization refs, the recovery owner, the claim
fence and the stop fence (`cancelled`, never lifted). The table guard enforces the same rules; the
runtime role cannot delete a row. Live fence: every advance takes the unit's advisory lock and, in the
same transaction, requires the writer's claim fence to be the unit generation's current
`attempt.fencing_token`, so a holder fenced out by a takeover is refused (`StaleSettlementHolder`) even
before the new holder writes. `invocation_settlement_event` is the append-only durable event log: a
`review_alarm` per configured interval while a review holds the result and the `effect_deadline`.

## The flow

1. `OperationExecutionService._dispatch_and_settle` **saves** the lane's completed result first, before
   the stop-fence and usage checks. A result over the bound (8 MiB) settles `failed`
   (`saved_result_too_large`) with its usage and checkpoint retained; another saved result for the
   binding parks the unit `in_doubt` (`unrecoverable_result_manifest`). Neither retries.
2. `_settle_saved_checked` checks the stop fence on the saved record (journaled: the fenced path,
   shielded against the in-flight cancel; pending: retry), so an error after the save neither loses nor
   redispatches the result. Usage over the bound settles `failed` (`budget_exceeded`) from the saved
   record after an evaluation-free pass.
3. One settlement pass: the lane's `SettlesInvocation.settle_invocation` (Deep Agents:
   `KnowledgeLaneSupport.settle` -> `KnowledgeToolset.settle_saved`: reconcile effects receipt-first,
   finalize once, poll open assessments). Its typed `SettlementOutcome` is consumed: an unresolved effect
   is an effect wait (nothing finalized), an assessment without a verdict a review wait, a raising pass
   `settlement_unavailable`.
4. `settled`: the operation settles from the saved result (the record's time makes a restarted
   settlement rebuild the same manifest). `waiting`: the boundary returns `waiting` with a
   `SettlementWait` (5 s doubling to the configured cap, default 1 h) and settles nothing. An effect wait
   older than the configured deadline (default 24 h) becomes an `in_doubt` incident
   (`unsettled_effect_claims`, the pending effects named) for `reconcile_unit`; it never settles
   silently. The deadline's anchor is durable on the record (`effect_wait_since`): the start of the
   effect wait (not the save, so a long review does not count), restarted once per operator decision
   that resumes the result (`effect_wait_decision`). An `abandon_unit` settles `failed`
   (`in_doubt_abandoned`; `cancelled` on the saga) charging the saved usage; the abandonment closed the
   lineage, so its checkpoint key is evidence, not a transition. A review wait has no deadline and
   records alarms.
5. The recovery owner, the unit's `mc.operation.v1` workflow, sleeps on a durable timer (woken early by a
   cancel; patch `oc-wi04-saved-settlement-wait`) and runs `operation.execute` again (governed `lane.turn`
   on the segment path). After `settlement_waits_per_run` waits (default 500) or on the server's
   suggestion it continues as new carrying the wait (`settlement_wait`; the next run sleeps on it first;
   patch `oc-wi04-saved-settlement-continue-as-new`). `_recover_or_dispatch` finds the saved record
   (after any incident decision) and settles it: cognition is never dispatched again.
   `GenericArtifactWorkflow` waits the same way (patch `oc-wi04-generic-artifact-settlement-wait`).

Cancellation (`_cancel_or_settle`) sets the stop fence: the fenced pass cancels open handles and starts
or polls no assessment, so a pending review no longer holds the result, but an unresolved effect and an
unavailable pass still wait; the unit settles `cancelled` with its completed outcome, output and usage
once committed work is reconciled. A verdict or receipt arriving afterwards reopens nothing. Lifecycle
(the operation settlement), execution outcome (the record), fulfillment (the finalization report and
decisions) and settlement (the record's state) stay four facts. Settings:
`SETTLEMENT_WAIT_CAP_SECONDS`, `SETTLEMENT_EFFECT_DEADLINE_SECONDS`, `SETTLEMENT_REVIEW_ALARM_SECONDS`.

The Deep Agents live invocation also carries its host-bound position, pins the promise revisions at
start and declares the pinned promises its position owns; the lane's `submit_output` serves inline text,
structured values and code changes (see [output contracts](output-contracts.md)).

## Limits

The proofs of this section use generic durable waits (`tests/fixtures/saved_settlement.py`); the real KS review waits are WI-03, shipped ([trusted judgment](trusted-judgment.md)).
WI-05 bridges native receipt reconciliation into the effect wait. A refused dispatch carries
`details.dispatch` (KS 2.5.0): a first dispatch is rejected for `not_journaled`, and for a
fenced (`details.fenced`) `journaled_uncommitted` only once `receipt.get` proves no commit; `committed`, `unknown`, a retry's
refusal or an unstated `UNRESOLVED_EFFECT`/`INTERNAL` leaves it `uncertain`, the settlement waits on
it and it settles from the receipt KS reconstructs for the original dispatch
(`tests/unit/knowledge/test_wi04_lane_settlement.py`); the fresh-process native proofs are in KS. The async-children completion still runs inside `execute`, and
a crash between cognition and the save is recovered model-free by the checkpoint classification
(`terminal_unobserved`). The segment-loop path (opt-in `deep_agent_segment_loop`) and
`GenericArtifactWorkflow` wait durably but do not continue as new. The PostgreSQL live-fence proof covers
the missing-attempt refusal; the differing-token branch is proven in memory only. A result too large to save settles without a settlement pass (committed effects
are left to the KS recovery lookup). No operator read surface lists waits and events yet (WI-19,
OVE-182; whether WI-19 lists settlement waits was not checked). The migration's credential-key check is
top-level only, and identity columns are duplicated in the `record` document (kept equal by checks).
Promotion exists: GoalDirected promotes an accepted iteration's output to the accepted head
(`application/programs/goal_directed.py:1423`, `promote=observation.decision == "accepted"`) and a Stage
Graph stage's exact named submissions are settled before its family consumes output references
(`application/programs/named_outputs.py`); WI-02 family inputs stay optional. The B3 native plan decisions
join the settlement pass through candidate migration 0072, unregistered ([database component](database-component.md)).

Built / specified / goal: the saved record, settlement waits, cancellation and recovery are implemented and
tested on PostgreSQL and Temporal restart (below); integrated with real KS review only locally; qualified: no.

## Citations

- Unit: `tests/unit/operations/test_wi04_saved_settlement.py` (real `create_deep_agent`; crash after
  completion, before the save, review wait, effect wait, late acknowledgment, unavailable settlement,
  cancellation with a pending review and a pending effect), `tests/unit/knowledge/test_wi04_lane_settlement.py`.
- PostgreSQL 17: `tests/integration/postgres/test_wi04_saved_settlement_postgres.py`,
  `tests/integration/postgres/test_sprint_oc_release_170.py`.
- Temporal + PostgreSQL: `tests/integration/temporal/test_wi04_saved_settlement_restart.py`.
- [Output contracts](output-contracts.md);
  [submission and finalization decision](../adr/0058-composable-output-obligations-and-one-submission-act.md);
  [Temporal sole scheduler](../adr/0004-temporal-sole-scheduler-transactional-outbox.md);
  [distinct retry counters](../adr/0011-distinct-retry-counters-and-retry-classifier.md).
