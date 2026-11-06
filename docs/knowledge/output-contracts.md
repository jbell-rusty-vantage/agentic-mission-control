---
type: Concept
category: domain-model
title: Output contracts and the exact transfer of accepted outputs to the next stage
description: How named output promises compile, are submitted, promoted, assessed and fulfilled, how a sealed transfer plan carries exact predecessor outputs to each receiver boundary of every workflow system, and which forms, boundaries and behaviours are built, tested, integrated or still target.
tags: [mission-control, output-contracts, obligations, transfer, knowledge-services, fulfillment]
aliases: [output obligations, output promises, sealed transfer plan, exact context, fulfillment, downstream delivery, stage-to-stage transfer]
questions:
  - How are named output promises submitted, assessed and fulfilled?
  - What does each workflow system owe and what does its receiver get?
  - How does a stage get its predecessor's exact output?
  - How is an accepted result delivered to the downstream stages?
  - Why was my output submitted but not accepted?
  - Which transfer boundaries are built and which refuse?
updated: 2026-11-01
---

# Output contracts and exact context transfer

Two contracts meet at every workflow boundary. What a node **owes** is a set of named, pinned promises; what a
receiver **gets** is one sealed transfer plan of exact predecessor outputs. Both are provider-neutral; Deep Agents
renders them first ([Deep Agents lane](deep-agents-lane.md)). Normative target: the deleted `OUTPUT-CONTRACTS.md`
(harvested at `66185d2e`) and ADR-0058..0062; the work map is the [Sprint OC packet](../specs/provider-consolidation-2026-10/sprint-oc/README.md).

## 1. What a workflow owes

A manifest output is an exact promise: `form` (`text, structured, file, collection, reference, code_change,
effect_receipt, control_record`, `domain/outputs/contracts.py:38`), `enforcement` (`required/expected/optional`),
`cardinality`, `coverage`, declared `requirements`, nested `members`, `media_type`, `repository`, pinned `schema`
(`domain/authoring/manifest.py`). Lowering emits one `OutputObligation@2` per output at the owner's position
(`manifest_lowering.py`, `output_promises`): the stage for a Stage Graph stage, a path for a nested body (never flattened),
with `evaluation_scope` of `invocation, cycle, iteration, activation, accumulated_stage, goal, mission`. Completion is a
closed AST (`all, any, obligation, assessment, integrity, human_resolution, criterion`; ADR-0010) in which every
required promise is a conjunct, so an unmet required promise can never coexist with a satisfied completion; the
compiler copies the set, position-checked, into the configuration (`EffectiveRunConfiguration.output_promises`).
Goals are owned explicitly (`unowned_goal` refuses instead of assigning the last stage).

| System | What it owes (built) |
| --- | --- |
| [Stage Graph](stage-graph.md) | Per-stage promises at the stage position; the root owes none of its own: each root output is an export of one stage's promise (`exports: [{output, from: <stage>.<output>}]` or the one same-named stage output; `root_output_unbound` refuses otherwise, OVE-169); routes may skip a branch visibly but required promises survive unless applicability proves otherwise |
| [Goal Loop](goal-loop.md) | The root's promises, judged by the verifier over the whole required current set; `converge` promotes and decides before the verdict; later executors receive them |
| [Parallel Swarm](parallel-swarm.md), [Evaluator Optimizer](evaluator-optimizer.md) | Decided: ordinary per-member/convergence and per-round obligations on Stage Graph and Goal Loop machinery; not built |
| [Nested bodies](recursive-composition.md) | The composite's declared outputs at the stage position; the body's own run owes what it produces; exports adopt explicitly |
| [Mission chains](mission-chains.md) | Each member owes its own; delivery never adopts |

## 2. Submission, promotion, assessment, fulfillment

**One submission act.** `SubmissionService.submit_output` (`application/outputs/submission_service.py:282`) takes
`SubmitOutput@2`, returns `SubmissionAck@1` or a typed `OutputError@1`. The host supplies attribution, position and
admitted bindings and pins promise revisions at invocation start (`pin_invocation`). Pure rules
(`domain/outputs/rules.py`) refuse an undeclared promise, foreign position, wrong form, digest mismatch
(`DIGEST_MISMATCH`), wrong schema version/shape, an index member without an exact digest, a code change without exact
repository/base/head-or-patch scope, a control record naming authority keys, and an ambiguous bare native id. Same
scoped key with other bytes is `SUBMISSION_CONFLICT`; an identical retry returns the same receipt. An accepted act
records drafts only.

**Three separate facts.** `OutputFulfillmentService` (`application/outputs/fulfillment.py:327`) *promotes* an accepted head by
expected-head and generation compare-and-set; *records assessments* through a host-access interface (an assessor never
judges its own output; the trusted knowledge bridge supersedes with KS lineage, [trusted judgment](trusted-judgment.md));
and *pins a frontier* whose digest covers promise revisions and exact members, then decides every promise
(`domain/outputs/fulfillment.py:135`). Judgments combine conservatively; required unmet blocks, expected unmet is a
visible shortfall, optional absence is silent, submitted-unaccepted reads `SUBMITTED_NOT_ACCEPTED`. A `file` promise
needs a receiving-backend read-back (`FILE_NOT_REALIZED`); a `reference` needs current official-use evidence
(`REFERENCE_USE_UNPROVEN`); an `effect_receipt` needs its effect settled `applied` by this run (`EFFECT_FOREIGN_RUN`,
`EFFECT_UNRESOLVED`, `EFFECT_NOT_APPLIED`). A missing required submission gets one reminder, one association of an
unambiguous registered candidate, one ambiguity repair, then blocks. A governed successor tightens freely; any other
difference is a weakening needing an explicit grant, and an executor can never self-waive; `activate_at_boundary` moves
the head only at the reported boundary kind. Persistence: release 1.7.0 migration `0056` (store
`adapters/postgres/knowledge/output_contracts.py`). Five distinct durable transitions (submitted, assessed, fulfilled,
delivered, settled) are what [durable reactions](durable-reactions.md) bind; see [collections](collections-and-current-sets.md),
[saved-result settlement](saved-result-settlement.md).

## 3. What a receiver gets: the sealed transfer plan (WI-02, ADR-0061)

A receiver's bindings travel on the operation request as `TransferSelection` (`mc.transfer_selection.v1`). Pure rules
(`domain/context/transfer.py`) and one materializer (`application/context/materialization.py`) resolve each binding
exactly (`produced_output`: the accepted revision of the producer's named promise; `exact_artifact`: pinned digest;
`typed_literal`; `application_selector`: only a registered application port), stage bytes in custody and seal one
immutable plan per receiver boundary (`transfer_plan`, migration 0057). Placement follows `report-review@v1` (index
inline, bodies as read-only files under `/inputs/<binding>/<revision>/`, evidence behind handles); the invocation is
accounted once against the model window. Each attempt realizes the plan on the actual backend, reads every file
back, re-checks current access and appends one `transfer_delivery_receipt`; redelivery reuses the plan and never
resolves today's revision. The boundary is who the receiver is:

<!-- snippet: src/mission_control/domain/context/transfer.py:59-70 -->
```python
class Boundary(StrEnum):
    """Who the receiver is; each has its own builder and none invents a predecessor."""

    FIRST_INVOCATION = "first_invocation"
    NEXT_ITERATION = "next_iteration"
    DEPENDENT_STAGE = "dependent_stage"
    EVALUATOR = "evaluator"
    REPAIR = "repair"
    NESTED_EXPORT = "nested_export"
    LINKED_MISSION = "linked_mission"
    CONTINUATION = "continuation"
    REPAIR_FORK = "repair_fork"
```

| Boundary | Builder (`domain/context/transfer_builders.py`) | State |
| --- | --- | --- |
| `first_invocation` | `first_invocation` (`:71`): bounds from the model's `max_input_tokens`, no inputs | built |
| `dependent_stage` | `dependent_stage` (`:85`): declared `from:` bindings, accepted heads only, required unless authored optional | built, integrated |
| `next_iteration` | `next_iteration` (`:130`): prior outputs, optional, omissions visible | built |
| `evaluator`, `repair` | `evaluator` (`:148`), `authorized_subjects` (`:184`): only the nominated finalized subject, no official use granted | built |
| `continuation` | `continuation` (`:217`): same selection, plan reused, new receipt | built |
| `linked_mission` | `linked_mission` (`:230`): released exports frozen beside local inputs | built (release 1.10.0) |
| `nested_export` | `nested_export` (`:224`) refuses `NESTED_INPUT_UNSUPPORTED` (a body reads nothing from outside itself) | refuses by design |
| `repair_fork` | enum value only | not built |

The Context Packet (`context_selection`) stays the host-state rendering; the plan names it as `host_state_ref`.
Corrupt, unreadable or revoked members refuse; omissions are always rendered; every KS member re-reads at each
realization ([context and continuation](context-and-continuation.md)).

## 4. Runtime and capability configuration

Every launch route registers the run's promises or refuses `promises_unwired` (`application/execution/run_launch.py:313`,
`bootstrap/launch_promises.py`). On the Deep Agents lane the live invocation carries its host-bound position and ledger
identity, pins promises at start and declares the pinned promises its position owns, so finalization iterates them,
omitted submissions included; the tool serves every form (`handle`/`path` items, inline text, structured values,
`code_change`). An independent evaluator is never offered `report_register`, `knowledge_apply` or `submit_output`
(`ROLE_SEPARATION`, `application/knowledge/toolset.py:805`) and declares none of the producer's promises.
Operational transfer, native reads and effect reconciliation are distinct authorities (
[Knowledge Services boundary](knowledge-services.md); [ports](../specs/provider-consolidation-2026-10/sprint-oc/APPLICATION-PORTS.md)).

## 5. Evolution (specified) and limits

Specified, not built (annex §10): sources are tracked by default and exactly consumed revisions are recorded; a changed
upstream marks affected current eligibility stale without rerunning descendants automatically. Two automatic cases
only: a tracked report revision arranges bounded authorized revalidation of affected synthesis (a running synthesis
finishes on sealed inputs, then revalidates before it is current), and an exact held source later accepted may schedule
independent reassessment of retained provisional synthesis under an authored policy; incremental arrivals coalesce into one
pending successor. Limits:

Required alternatives or quorum (`any(required A, required B)`) are refused at compile; a successor breaking that rule
is `SUCCESSOR_BREAKS_COMPLETION`. `boundary_ref` is host-asserted (the database checks only the kind prefix). The
target Goal Loop progress note at each handoff is not enforced. Every form has its proof; W1 is not released and
production per-invocation Biotech authority is unproven ([control board](../specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md) `:69-87,119-121`).

Built / specified / goal: promises, submission, fulfillment and the transfer boundaries above built, tested on PostgreSQL and Temporal, integrated on paid Deep Agents fixtures, not qualified; Swarm/EO obligations specified; `repair_fork` and nested-input transfer not built.

# Citations

- ADRs: [0058](../adr/0058-composable-output-obligations-and-one-submission-act.md), [0059](../adr/0059-application-content-and-shared-knowledge-authority.md),
  [0061](../adr/0061-one-sealed-transfer-plan-and-attempt-receipts.md), [0010](../adr/0010-completion-expressions-closed-typed-ast.md).
- Code: [contracts](../../src/mission_control/domain/outputs/contracts.py), [rules](../../src/mission_control/domain/outputs/rules.py),
  [fulfillment rules](../../src/mission_control/domain/outputs/fulfillment.py), [submission](../../src/mission_control/application/outputs/submission_service.py),
  [fulfillment service](../../src/mission_control/application/outputs/fulfillment.py), [transfer](../../src/mission_control/domain/context/transfer.py),
  [builders](../../src/mission_control/domain/context/transfer_builders.py), [materializer](../../src/mission_control/application/context/materialization.py),
  [store](../../src/mission_control/adapters/postgres/knowledge/output_contracts.py), [lowering](../../src/mission_control/domain/authoring/manifest_lowering.py).
- Tests: [fulfillment](../../tests/unit/outputs/test_output_fulfillment.py), [compile](../../tests/unit/authoring/test_output_promises_compile.py),
  [PostgreSQL](../../tests/integration/postgres/test_output_contracts_postgres.py), [release 1.7.0](../../tests/integration/postgres/test_sprint_oc_release_170.py),
  [lane settlement](../../tests/unit/knowledge/test_wi04_lane_settlement.py).
- Specs: [application ports](../specs/provider-consolidation-2026-10/sprint-oc/APPLICATION-PORTS.md), [implementation](../specs/provider-consolidation-2026-10/sprint-oc/IMPLEMENTATION.md),
  [proofs](../specs/provider-consolidation-2026-10/sprint-oc/PROOFS.md), [report/source foundation](../REPORT_SOURCE_FOUNDATION.md).
