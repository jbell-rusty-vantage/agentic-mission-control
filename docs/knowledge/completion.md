---
type: Concept
category: domain-model
title: Completion and acceptance
description: Why execution completion, output validity, evidence disposition, activation acceptance, mission acceptance, domain admission and publication are seven different facts; the closed completion expression that computes acceptance over output promises; and how the reducer and each workflow system settle a run today.
tags: [mission-control, completion, acceptance, evidence, fulfillment, implementation]
aliases: [acceptance, completion contract, completion decision, terminalization, run outcome]
questions:
  - Is this work complete, valid, accepted or admitted?
  - Who decides acceptance when an agent says it is finished?
  - What closed expression computes completion over output promises?
  - How does the reducer terminalize a run and when is it partial?
  - Where are completion candidates and decisions recorded?
updated: 2026-11-01
---

# Completion and acceptance

Mission Control must distinguish execution completion, output validity, evidence disposition, activation acceptance,
mission acceptance, downstream domain admission and publication, and must never accept a result because an agent,
provider, Temporal workflow or tool reports success (ADR-0010; owner invariant in `AGENTS.md`: execution completion
is not mission acceptance). The target vocabulary is annex `workflow-types/00` §6 (harvested at `66185d2e`).

## Seven facts, not one status

| Fact | Who records it | Vocabulary |
| --- | --- | --- |
| Execution completion | the attempt, from the lane's native end | `succeeded`, `failed` with a failure class, `cancelled` |
| Output validity | submission rules and schema/integrity checks on declared outputs | accepted draft, or a typed `OutputError` / `SUBMITTED_NOT_ACCEPTED` |
| Evidence disposition | a registered assessment capability | typed disposition, e.g. `satisfied`, `unsatisfied`, `inconclusive` |
| Activation acceptance | the completion contract of that node, evaluated by the host | `satisfied / waiting / blocked` over the closed expression |
| Mission acceptance | aggregate disposition over goals | target: `mission_accepted`, `not_accepted`, `abandoned`, `superseded`; run outcome today |
| Domain admission | the application's domain service, by intent and receipt | `applied`, `rejected`, `noop`, `partial` |
| Publication | an explicit domain capability with its own policy | its own side-effect class and receipt |

A native `FINISHED` is never `accepted`. A completed provider result is saved before any post-execution wait
(WI-04): its execution outcome and settlement state are separate from operation settlement and from obligation
fulfillment; a review or receipt wait never reruns cognition ([saved-result settlement](saved-result-settlement.md)).
Child mission success supplies evidence, never the parent's acceptance ([mission chains](mission-chains.md)).

## 1. Scheduling: who proposes and who decides

Agents and verifiers propose; reducers decide. The reducer's `_terminal_outcome` (`domain/policies/reducer.py`) accepts a
`TerminalizationProposal` (`domain/policies/contracts.py`) only when it binds the current run version, workflow type
digest, obligation revision and evidence frontier; when `required_obligations_accepted` matches the authoritative
`AcceptedObligationEvidence` (each with `accepted_by_authority_ref`); when `valid_output_refs` equals the authoritatively
accepted outputs; when no wait, link or required asynchronous subordinate remains; and when budget and effects are
settled. The `RunOutcome` is `completed`, `partially_completed` (degradable failures with some valid output), `failed` or
`cancelled`; the run phases are `pending, active, waiting, paused, cancelling, terminal` ([lifecycle](lifecycle.md)).
Stage Graph results are decided `ADMIT/REJECT/QUARANTINE` and a `StageGraphCompletionProposal` terminalizes only with
required obligations accepted, no pending dependency and no open producer liability. `GoalDirected` carries an
independent `GoalVerificationResult` and a `GoalTerminalizationProposal` (`complete | partial_or_fail | fail`). The
unreachable-stage and family-failure cases are in [stage graph](stage-graph.md) and [lifecycle](lifecycle.md).

A [Completion Candidate](../../GLOSSARY.md) is the executor's claim (annex `workflow-types/05` §3.4: activation and attempt
identity, named outputs bound to artifact refs, evidence refs, optional criteria mapping, concise notes, no chain of
thought); the [Completion Decision](../../GLOSSARY.md) is Mission Control's computed verdict on it. If a turn ends without
a candidate, `missing_output_policy` allows one bounded follow-up turn, then `not_accepted(outputs_missing)`; today the
follow-up is realized on the Cursor lanes (`adapters/cursor/local.py:207`, `cloud.py:977`), the Claude and Codex harnesses
compute `missing_outputs` closing facts (`adapters/claude/harness.py:368`), and it is not found for Deep Agents, where the output-promise reminder and association steps ([output contracts](output-contracts.md)) play that role.
Simple/standard/full agent binding levels of the old executor contract are superseded by the resolution seam (ADR-0063).

## 2. Output-contract obligations: the closed expression

Acceptance is computed over promises, not reported. The completion contract is a closed typed AST
(`domain/outputs/contracts.py:296-345`: `all`, `any`, `obligation`, `assessment`, `integrity`, `human_resolution`,
`criterion`) over declared vocabularies; it cannot run SQL, Python or prose predicates, and semantic judgment goes
through a registered assessment and rubric returning a typed disposition (replayable, auditable, immune to prompt
injection). `evaluate_completion` (`domain/outputs/fulfillment.py:476`) returns `satisfied | waiting | blocked`
(expected and optional promises neither block nor satisfy by absence); `OutputFulfillmentService.evaluate_frontier`
(`application/outputs/fulfillment.py:642`) loads the admitted expression itself and accepts none from a caller. Every
required promise is a conjunct, an `assessment` leaf may admit `review` only for a non-required requirement, and an
evaluator's `accept` or a human's `approved` is an input, never the verdict ([human gates](human-gates.md),
[evaluator optimizer](evaluator-optimizer.md)).

At the Goal Loop boundary a verifier reconciliation decides declared promises before recording its verdict
(`OutputFulfillmentService.converge`, `GoalDirectedOperationResultService._with_fulfillment`,
`application/programs/goal_directed.py:1399`): requirement-free promises are promoted from the finalized submission,
requirement-bearing ones by assessment (WI-03), a rejected iteration's output never becomes a head, and
`bind_fulfillment` keeps an acceptance only when every required promise is fulfilled, otherwise it is a rejection naming
`output:<key>`. Production also re-decides after every head move and assessment so `output.fulfilled` /
`output.fulfillment_unmet` events come from real writes.

## 3. Context transfer

A completion decision binds an exact frontier (membership digest over promise revisions and exact members), not
"latest"; findings for an older revision cannot approve a successor, and a pinned frontier keeps its revision
([output contracts](output-contracts.md)).

## 4. Runtime: records and what is not unified

`completion_candidate` (artifact and evidence refs, immutable) and `completion_decision` (`policy_digest`,
`contract_digest`, `result_disposition` `accepted | rejected | needs_more_work | abandoned`, requirement and result
refs, reason codes) are written (`adapters/postgres/orchestration/completion_repository.py:87,128`): by the family
admission commit for a Stage Graph `result_decided` (atomically with the mutation, via
`PostgresRunControlRepository.commit_family_admission`, `adapters/postgres/run_control/run_control_repository.py:823`) and by `PostgresCompletionRepository.record`
for the Goal Directed verifier reconciliation. `evidence_assessment` (assessor identity, capability, rubric and policy
versions) lives in migration `0004`; assessments are recorded through the host-access interface of the fulfillment service.
The coordinator reads a `TerminalWorkflowCompletion` that reports execution completion, not mission acceptance
(`domain/coordinator/launch.py`). Workspace files become artifacts only through captured candidates and immutable
registration ([capabilities](capabilities.md), [recovery](recovery.md)).

Not unified: the per-node `accepted | not_accepted | stopped_by_policy | governor_exhausted | no_progress | ...` terminal
vocabulary of annex `00` §6.3 is not the code's (`RunOutcome` above; schema activation outcomes `succeeded | failed |
cancelled | skipped | superseded`); mission-level acceptance as an aggregate disposition over goals, carry-forward of
accepted work and the `missing_output_policy` follow-up turn (lane-local, above) are specified or lane-local.

Built / specified / goal: closed AST, fulfillment, reducer terminalization and decision records built, tested and integrated on paid Deep Agents fixtures (`NEXT-SESSION.md:32-98`), W1 not released; unified outcome vocabulary and mission-level aggregate acceptance specified only.

# Citations

- ADR: [0010](../adr/0010-completion-expressions-closed-typed-ast.md); spec (harvested at `66185d2e`): `workflow-types/00` §§2.4, 6.3, 6.5, `04` §5, `05` §§3.4, 4.2.
- Code: [reducer](../../src/mission_control/domain/policies/reducer.py), [policy contracts](../../src/mission_control/domain/policies/contracts.py),
  [program contracts](../../src/mission_control/domain/programs/contracts.py), [output contracts](../../src/mission_control/domain/outputs/contracts.py),
  [fulfillment rules](../../src/mission_control/domain/outputs/fulfillment.py), [fulfillment service](../../src/mission_control/application/outputs/fulfillment.py),
  [Goal service](../../src/mission_control/application/programs/goal_directed.py), [decision writers](../../src/mission_control/adapters/postgres/orchestration/completion_repository.py),
  [coordinator result](../../src/mission_control/domain/coordinator/launch.py), [execution contracts](../../src/mission_control/domain/execution/contracts.py).
- Tests: [run control](../../tests/unit/run_control/test_run_control.py), [Stage Graph](../../tests/unit/orchestration/test_stagegraph_v2.py),
  [GoalDirected](../../tests/unit/orchestration/test_wp_bp_020_goal_directed.py), [convergence fulfillment](../../tests/unit/outputs/test_w1_convergence_fulfillment.py),
  [Goal fulfillment](../../tests/unit/orchestration/test_w1_goal_fulfillment.py), [PostgreSQL fulfillment](../../tests/integration/postgres/test_w1_fulfillment_postgres.py).
- Schema: [`0003_execution.sql`](../../packages/mission-control-db-contract/component/migrations/0003_execution.sql), [`0004_capability_artifacts.sql`](../../packages/mission-control-db-contract/component/migrations/0004_capability_artifacts.sql).
