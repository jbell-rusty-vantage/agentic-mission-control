---
type: Concept
category: execution
title: "Durable transition reactions: capture, admission and ordinary dispatch"
description: "How a reaction bound to an output, assessment, fulfillment, delivery or settlement transition is captured in that transition's transaction, admitted under its limits with its outbox dispatch intent, and started as the ordinary mc.operation.v1 by the run-derived id (WI-22); what is not wired yet."
tags: [mission-control, reactions, outbox, temporal, output-contracts, sprint]
aliases: [transition reaction, outbox dispatch, WI-22, reaction relay]
questions:
  - How do I react durably to an output or settlement transition?
  - Why is a duplicate transition event only one reaction?
  - What stops a reaction from triggering itself forever?
  - Which parts of durable reactions are not composed in production?
updated: 2026-11-01
---

# Durable transition reactions

The decision is [ADR-0062](../adr/0062-durable-reactions-and-host-validated-context-contributions.md): a
reaction is an ordinary admitted operation scheduled by Temporal, its admission and dispatch
intent persist together, a duplicate event is one logical reaction, a crash after admission resumes
dispatch, and stale generations and cancellation fences apply. Temporal stays the only scheduler
([ADR-0004](../adr/0004-temporal-sole-scheduler-transactional-outbox.md)): there is no reaction
scheduler, only the transactional outbox and a relay that hands work to Temporal. This page explains
how current source realizes that (Sprint OC WI-22, OVE-183).

**Five distinct transitions.** A reaction binds one `TransitionKind`
([`domain/reactions/contracts.py`](../../src/mission_control/domain/reactions/contracts.py)) at
version 1: `output.submitted` (an `output_revision`), `assessment.recorded` (an
`output_assessment`), `fulfillment.decided` (an `obligation_fulfillment`), `delivery.recorded` (a
`transfer_delivery_receipt`) or `settlement.settled` (an `invocation_settlement` reaching
`settled`, once). Each kind carries only its own facts (`TRANSITION_FACTS`); a condition reading a
fact of another kind refuses at compile, so the five never blur. A provider stop is none of them.

**Declaration and compile.** `mc.reaction.v1` (`ReactionDeclaration`) binds `on {event, version}`,
an optional `where` (the closed ADR-0010 condition AST of the watchers, over `event.<fact>` only),
`operation {template, purpose}` (an operation request key of the run's admitted templates), the
`outputs` (obligation keys) that operation answers for, `grants` (tools, MCP servers) and `limits`:
`max_activations` (default 4, at most 64), `max_depth` (default 2, at most 8), `rate {count,
window_seconds}`, `time {lifetime_seconds, operation_seconds}` and a mandatory `spend
{tokens_per_activation, max_tokens}`. `compile_reaction` resolves every bound into
`mc.reaction_descriptor.v1` or refuses (`UNSUPPORTED_EVENT_VERSION`, `CONDITION_INVALID`,
`CONDITION_PATH`, `OUTPUT_KEY_INVALID`, `SPEND_ABOVE_CEILING`).
[`ReactionBindingService.attach`](../../src/mission_control/application/reactions/service.py)
attaches descriptors to a run as `reaction_binding` rows; re-attaching another descriptor or
detaching moves the binding to its next **generation** (the same armed descriptor is a no-op).
Arming time and lifetime use the database clock that stamps captured transitions. Attach
also records the run's declared data class (`MissionDefinition.data_class`). Arming is a
cutoff, not a replay: a transition captured before a binding was armed or re-armed is
marked admitted with no activation for that binding.

**Capture in the transition's transaction.** Migration `0061_durable_transition_reactions` adds
`AFTER INSERT` triggers on the four append-only sources and an insert/update trigger on
`invocation_settlement`. Each calls `capture_reaction_transition`, which writes one
`reaction_transition` row only while the run has an armed binding of that kind. Its id is
`md5('mc.durable_transition|' || kind || '|' || source)`, unique per (kind, source), so a duplicate
event is the same row.

**Causes come from authenticated identities.** A transition's `cause_ref` is derived by the capture, never read from a caller field: for an output, the submission's operation (from the
invocation's authenticated origin); for an assessment, the producer of the assessed revision (the assessor's origin is never a cause); for a fulfillment, the producing operation of the decided
set's member made by the deepest reaction activation; for a delivery, the plan's receiver operation; for a settlement, the settled operation. A self-trigger chain therefore keeps its depth
through every kind, and a cause naming `reaction-<id>` that is no activation of the run is refused `CAUSE_UNKNOWN` (fail closed). `PostgresReactionStore.record_transition` is the explicit host
capture for a caller that owns its commit.

**Capture never fails the source write.** Only `mission_control_runtime` writes the five source tables and executes the capture functions; each trigger asks `reaction_armed` first; text facts are cut to
512 characters. A source the capture cannot record (empty or oversized reference, facts that are not an object or carry a forbidden key) is skipped with a visible `reaction_capture_anomaly` row
rather than an exception block that would hide it. The reaction tables refuse updates outside their forward moves, deletion and `TRUNCATE`.

**Admission and dispatch intent together.** `admit_pending` takes one due transition per
transaction (`FOR UPDATE SKIP LOCKED`), locks the run's armed bindings of that kind, reads each
binding's ledger and plans with the pure
[`plan_activation`](../../src/mission_control/domain/reactions/planning.py). An activation is keyed
by (binding, transition), so two racing admitters and a redelivered event produce one row. It is
refused with the first limit it hits (`TIME_LIMIT` past the lifetime, `RECURSION_LIMIT` deeper than
`max_depth`, `ACTIVATION_LIMIT`, `RATE_LIMIT` inside the trailing window, `SPEND_LIMIT` when reserved
plus this reservation exceeds `max_tokens`, after `CAUSE_UNKNOWN`), or admitted with its
`mc.reaction.dispatch` outbox
intent in the same insert transaction. Activations are stamped, and the rate window counted,
by the admission transaction's database clock under the binding lock, so a late-committing source cannot slip into an earlier window. It records depth, causal parent, chain root, binding
generation and the run's execution generation; a transition produced by a reaction's own operation is one level deeper, which bounds the chain.

**Dispatch as an ordinary operation.** [`ReactionRelay.dispatch_once`](../../src/mission_control/application/reactions/service.py)
leases due intents, then checks currency (`dispatch_currency`): a detached or re-attached binding
cancels `stale_generation`, a lifetime that ended since admission `lifetime_ended`, a moved
run generation `stale_run_generation`, a stop fence
`run_fenced`, a finished run `run_terminal`. A current activation goes to the
`ReactionOperationPort`; the production
[`AdmittedReactionOperations`](../../src/mission_control/application/reactions/operations.py)
resolves the run's template, refuses `GRANT_EXCEEDED` (template tools or MCP servers outside the
reaction's grants), `TEMPLATE_UNAVAILABLE`, or `DATA_CLASS_NOT_ADMITTED` / `DATA_CLASS_UNDECLARED`
(the template's lane does not admit the run's data class, the class of the event facts), then
reserves the activation's spend through run control (`RunControlReactionBudget`: attempt-numbered
`reserve_budget` command ids, so a `stale_run_version` answer on a busy run is retried with the
fresh version rather than replayed as a refusal, and a redelivery returns the accepted attempt;
a refusal after the reservation, such as `BINDING_CONFLICT`, releases it with a zero-usage
`record_usage`, so a cancelled activation holds no spend), binds the template
(identity `reaction-<activation>` attempt 1, a stage-operation runtime unit at
`reaction.<reaction id>`, the lane's own rebind of its sealed binding through `LaneRebinders`, the
reservation, one admitted-input prompt segment with the bounded event, purpose and outputs, and
`operation_seconds` as the workflow timeout), persists the operation binding when a repository is
composed, and starts it through
[`TemporalReactionStarter`](../../src/mission_control/adapters/temporal/reaction_dispatch.py): the
ordinary `mc.operation.v1` under `mission_operation_id(scope, run, semantic key)` with
`REJECT_DUPLICATE` and `USE_EXISTING`. The activation's move to `dispatched` (or `cancelled`) and
the intent's acknowledgement commit together; a lost lease rolls both back. A crash after the start
and before that commit re-delivers into the same workflow; a crash before the start leaves a pending
intent that the next relay delivers after the lease expires.

**Trust model.** The template is one the run already admitted: run admission resolved its lane,
model route, grants and credentials (`RuntimeResolver`, the sealed lane binding). Dispatch does
not resolve them again; it re-checks what the reaction narrows or what can have changed: the
reaction's grant subset, the run's data class against the template's lane, the run's stop
fence, generation and terminal state, and the binding's generation and lifetime. Credentials
reach the operation through its lane when it runs, as for any family operation.

**What does not exist.** There is no reaction scheduler, no script that runs a reaction, and no
fulfillment by a reaction itself: its operation submits through the ordinary output path like any
other invocation, and a refused or cancelled activation never runs.

**Proof and limits.** Unit: `tests/unit/reactions/test_reaction_planning.py` (compile refusals,
identity, distinct kinds, each limit, currency) and `test_reaction_operations.py` (binding as an
ordinary operation, grant and template refusals, one reservation per activation). PostgreSQL:
`tests/integration/postgres/test_wi22_reactions_postgres.py` (the five triggers on real WI-01/02/04
writes, duplicates and racing admitters, both crash windows, stale generation and a real stop fence,
the self-trigger chain through every kind stopping at its depth and through outputs at each other
limit, an assessor origin that is never a cause, `CAUSE_UNKNOWN`, capture anomalies and edge facts
that still commit, writer and executor roles, table guards including `TRUNCATE`); the unit
suite adds a run whose version moves between read and execute (one reservation) and a release
after `BINDING_CONFLICT`.
Temporal: `tests/integration/temporal/test_wi22_reaction_dispatch.py` (the production port starts
`mc.operation.v1` on a time-skipping server, the relay dies after the start, the redelivery attaches,
one cognition, the history replays; the operation boundary is the RRM-004 harness with a scripted
model). Migration 0061 is in the built 1.8.0 component (`releases/README.md:226-232`). Not yet: no manifest surface declares reactions (only the
`ReactionDeclaration` contract and the attach service); production composition runs no
`ReactionRelayPump` and composes no `ReactionTemplatePort` over the families' persisted templates;
hook operation requests (`OperationRequestPort`, WI-17) are not yet admitted through this path; a
dispatched activation's completion is not folded back (Temporal holds the result); a stale
generation cancels only before dispatch, not an operation already running; the reaction's
`outputs` are carried to the operation's prompt, not pinned as its invocation's obligations.

Built / specified / goal: capture, admission, outbox dispatch and the ordinary `mc.operation.v1` start built and tested on real PostgreSQL and Temporal; relay pump, template port and a manifest surface not composed; [output contracts](output-contracts.md) own the obligations.

## Citations

- Code: [contracts](../../src/mission_control/domain/reactions/contracts.py),
  [planning](../../src/mission_control/domain/reactions/planning.py),
  [service and relay](../../src/mission_control/application/reactions/service.py),
  [ordinary operation](../../src/mission_control/application/reactions/operations.py),
  [PostgreSQL store](../../src/mission_control/adapters/postgres/reactions.py),
  [Temporal starter](../../src/mission_control/adapters/temporal/reaction_dispatch.py),
  [migration 0061](../../scripts/release_170/0061_durable_transition_reactions.sql), [release 1.8.0](../../packages/mission-control-db-contract/releases/README.md).
- Tests: [planning](../../tests/unit/reactions/test_reaction_planning.py),
  [operations](../../tests/unit/reactions/test_reaction_operations.py),
  [PostgreSQL](../../tests/integration/postgres/test_wi22_reactions_postgres.py),
  [Temporal](../../tests/integration/temporal/test_wi22_reaction_dispatch.py).
- Related: [watchers](watchers.md) (admitted Commands, not operations), [hook contributions](hook-contributions.md),
  [saved-result settlement](saved-result-settlement.md), [mission chains](mission-chains.md) (outbox relay for runs).
