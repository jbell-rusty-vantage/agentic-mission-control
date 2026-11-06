---
type: Concept
category: domain-model
title: Goal Loop and the GoalDirected subset
description: The target Goal Loop model (two loops, Loop Journal, Action Space with proposal and authorization, Progress Review, context health) beside the GoalDirected subset the code runs (executor and verifier alternation, convergence precedence, bounded Goal Revisions, session rollover), at scheduling, output obligations, context transfer and runtime configuration.
tags: [mission-control, workflow-systems, goal-loop, goal-directed, convergence, implementation]
aliases: [GoalDirected, goal directed, goal loop subset, convergence policy, goal revision]
questions:
  - What does the built GoalDirected run versus the target Goal Loop?
  - How does a Goal Loop decide to continue, revise, pause or stop?
  - What is a Goal Revision and what can it never change?
  - What does the verifier see and what does the next executor receive?
  - Is there a Loop Journal or Action Proposal in the code?
updated: 2026-11-01
---

# Goal Loop and the GoalDirected subset

The [Goal Loop](../../GLOSSARY.md) pursues an Objective when the next useful action cannot be compiled in
advance. The code family is `GoalDirected`; the glossary avoids that word in prose because it implements a
subset. [Evaluator Optimizer](evaluator-optimizer.md) is decided to run on this machinery (OC-D205); the
cross-system view is in [workflow systems](workflow-systems.md).

## Target model beside the built subset

| Target (annex `workflow-types/02`, deleted pack at `66185d2e`) | Built in `GoalDirected` | Evidence |
| --- | --- | --- |
| Goal-progress loop `observe, propose, authorize, act, evaluate, review, decide` | Executor operation, then an independent verifier operation, then a convergence decision | `domain/programs/goal_directed.py:154,234,287` |
| Context-health loop `monitor, compact, synthesize, validate, transfer, resume` | Token-threshold session rollover from a typed handoff; continuation phase machine for Session Lanes ([context](context-and-continuation.md)) | `domain/programs/goal_directed.py:415-470`, `domain/context/pressure.py` |
| Loop Journal (sealed entries and segments), Loop State projection | Not built: no `LoopJournal` type in `src/`. Closest: `GoalHandoff`, `GoalContinuationState`, the verification and iteration documents | `domain/programs/contracts.py:1438,1670` |
| Committed Action Space; Action Proposal; Action Authorization (`authorized/denied/pending_human_task`) | Not built as runtime steps. `action_space` aliases are validated at compile only; the five-value side-effect enum exists | `application/authoring/manifest_service.py:1636-1656`, `domain/authoring/manifest.py:350` |
| Progress Review as a typed record at each boundary | The verifier's `progress_made` bit, findings and `blocker_class` feed patience counters | `domain/programs/contracts.py:1582` |
| Completion Candidate, then deterministic validation, then semantic judge, then host verdict | Verifier decision `accepted/rejected/revision_required/repair_required`; host fulfills promises, then converges | `application/programs/goal_directed.py:1399` |
| Revision Proposal when scope expands | Bounded `GoalRevision` inside a protected envelope; wider routes stop the run | `domain/programs/goal_directed.py:573`, `domain/authoring/contracts.py:1480` |
| Governors: iterations, tokens, cost, wall-clock, patience, transfers | `max_iterations`, convergence patience, budget hard/soft, rollover and transfer caps | `domain/authoring/contracts.py:1438,1524` |
| Nested Goal Loops with a subset Action Space | Nested body as a sealed child run with its own governors | [recursive composition](recursive-composition.md) |

## 1. Scheduling

Temporal `belllabs.goal-directed` (`adapters/temporal/workflows/goal_directed.py:209`) runs under the root
`mc.mission_run.v1`. `GoalDirectedInterpreter` (pure) claims an execution, applies its result, applies the
verification and proposes a convergence action. Identities are explicit: `GoalIterationIdentity` (run, iteration,
goal revision, epoch) and `GoalAgentRunIdentity` (agent run, session generation) (`domain/programs/contracts.py:1379,1394`).
Convergence takes the first matching fact in this order:

<!-- snippet: src/mission_control/domain/programs/goal_directed.py:680-694 -->
```python
        if facts.authority_breach:
            action = convergence.authority_breach_action
            reason = "authority_breach"
        elif facts.hard_budget_exhausted:
            action = convergence.hard_budget_action
            reason = "hard_budget_exhausted"
        elif facts.all_required_obligations_verified:
            action = "complete"
            reason = "verified_completion"
        elif facts.irrecoverable_failure:
            action = convergence.irrecoverable_failure_action
            reason = "irrecoverable_failure"
        elif facts.no_progress_threshold_reached:
            action = convergence.no_progress_action
            reason = "no_progress"
```

then soft budget, scope expansion, bounded revision, repair, else `continue` (`domain/programs/goal_directed.py:701-715`).
Actions: `continue, reduce_effort, skip_degradable, revise, repair, pause, escalate, fork, linked_run,
control_revision, new_run, complete, partial_or_fail, fail` (`domain/programs/goal_directed_runtime.py:44-59`). `complete`,
`partial_or_fail` and `fail` build a `GoalTerminalizationProposal` the reducer accepts or refuses; `pause` parks the
run; `escalate/fork/linked_run/control_revision/new_run` set `stopping` (they end this run, nothing continues it).
Patience: `max_no_progress_iterations` and `max_repeated_blockers` default to 3 (`domain/authoring/contracts.py:1438`). The workflow
continues-as-new every `continue_as_new_iterations` (20) and carries pending commands. A rollover cap (K02) pauses,
never fails, when no handoff can seed a fresh session. Typed failures: an unusable executor or verifier answer
settles as `output_unparseable:<sha256>` (observation `failed`, or verifier `rejected` with no progress), not a
retry; reconcile retries are bounded (`RECONCILE_MAX_ATTEMPTS` 64, `adapters/temporal/workflows/goal_directed.py:159`; request cap
1,900,000 bytes, `domain/programs/goal_directed_runtime.py:77`). A deterministically failed verifier unit becomes a typed
`rejected` verification so convergence terminates the run.

**Bounded Goal Revisions.** A verifier `revision_required` carries a `GoalRevision` (tactics, subgoals, coverage
emphasis; applicability `next_iteration` or `remaining_run`). `_accept_revision` (`domain/programs/goal_directed.py:573`) requires
it to extend the active revision by exactly one, match the launch `envelope_digest` and its own canonical digest;
`GoalProtectedScopePolicy` protects objective, acceptance, invariants, admitted inputs, authority, budget,
prohibited work, required outputs and linked-run permissions, and a wider change routes to `control_revision`,
`fork`, `linked_run` or `new_run` (default `new_run`). This is the nearest built relative of
[per-policy mutation](revisions.md#3-per-policy-mutation-goal): it changes tactics, never the program.

## 2. Output-contract obligations

The blueprint carries `required_output_contracts`, `required_obligation_refs` and `output_promises`
(`domain/authoring/contracts.py:1524`). The verifier evaluates exactly the root's promised outputs; the executor of a later
iteration receives them (the first none). On a verifier acceptance, `OutputFulfillmentService.converge` promotes
requirement-free promises from the executor's finalized submission, leaves requirement-bearing ones to their
assessment, pins the set and decides fulfillment; `bind_fulfillment` keeps acceptance only when every required
promise is fulfilled, otherwise the verification becomes a rejection naming `output:<key>`
(`application/programs/goal_directed.py:1399`). A rejected iteration's output never becomes a head; iteration caps are never success.
Human review of a verified completion (`acceptance.human`) runs behind patch `mp10-goal-human-review`
([human gates](human-gates.md)). See [output contracts](output-contracts.md), [completion](completion.md).

## 3. Context transfer

`application/programs/goal_directed.py:1470-1484` selects the boundary: `first_invocation` for iteration one, `next_iteration` with
predecessors bound to the iteration's exact producer, `evaluator` (`authorized_subjects`) for the verifier with only
its nominated finalized subject, `repair` for a repair iteration. Verifier feedback reaches the next executor in
full, persisted (`application/programs/goal_context.py`). A fresh session needs the current iteration's typed
`GoalHandoff` (accepted facts, attempted and rejected tactics, unresolved obligations, blockers, budgets, protected
context fact classes); the missing-progress-note rule of the target is not enforced. Queued instructions arrive at
the iteration boundary ([interventions](interventions.md)).

## 4. Agent runtime and capability configuration

A Goal Loop lowers to two templates, executor and verifier, each with its own sealed lane binding, model profile
and workspace; independence is enforced (the verifier is never offered `submit_output`, `ROLE_SEPARATION`,
`application/knowledge/toolset.py:805`). `GoalVerifierPolicy` pins `rubric_ref`, `rubric_version`,
`acceptance_version`, `binding_ref` and the output contract; a result with another pin is refused
(`domain/authoring/contracts.py:1450`). The executor phase may instead be a nested Stage Graph or Goal Loop. Deep Agents declares
`GoalDirected: native` (`adapters/deep_agents/describe.py:157`). Session policy: `session_mode`
(`reuse/fresh/fresh_from_handoff`), token threshold 100,000, `max_rollovers`, workspace snapshot policy
(`domain/authoring/contracts.py:1401,1415`).

Built / specified / goal: executor/verifier iterations, convergence, Goal Revisions, rollover, review and fulfillment built and integrated locally, W1 not released; Loop Journal, Action Proposal/Authorization, Progress Review records and Context Health catalog specified only; mid-run policy mutation beyond tactics is a goal.

# Citations

- Spec (harvested at `66185d2e`): `workflow-types/02-GOAL_LOOP.md` §§3-15; OUTPUT-CONTRACTS §7.
- Code: [GoalDirected interpreter](../../src/mission_control/domain/programs/goal_directed.py),
  [runtime contracts](../../src/mission_control/domain/programs/goal_directed_runtime.py),
  [program contracts](../../src/mission_control/domain/programs/contracts.py),
  [blueprint and policies](../../src/mission_control/domain/authoring/contracts.py),
  [application services](../../src/mission_control/application/programs/goal_directed.py),
  [goal context](../../src/mission_control/application/programs/goal_context.py),
  [workflow](../../src/mission_control/adapters/temporal/workflows/goal_directed.py),
  [human review rules](../../src/mission_control/domain/programs/human_review.py).
- Tests: [GoalDirected](../../tests/unit/orchestration/test_wp_bp_020_goal_directed.py),
  [W1 failure paths](../../tests/unit/orchestration/test_w1_goal_failure_paths.py),
  [fulfillment at the boundary](../../tests/unit/orchestration/test_w1_goal_fulfillment.py),
  [convergence fulfillment](../../tests/unit/outputs/test_w1_convergence_fulfillment.py),
  [PostgreSQL fulfillment](../../tests/integration/postgres/test_w1_fulfillment_postgres.py),
  [unparseable answers](../../tests/acceptance/mission_control/test_goal_output_unparseable.py),
  [family failure root](../../tests/integration/temporal/test_w1_family_failure_root.py).
- Proof status: [control board](../specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md) (`:199-215` GoalDirected bounded gates, `:119-121` W1 unreleased).
