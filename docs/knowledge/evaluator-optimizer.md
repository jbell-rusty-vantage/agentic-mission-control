---
type: Concept
category: domain-model
title: Evaluator Optimizer on Goal Loop machinery
description: How one deliverable improves through bounded produce, evaluate and repair rounds with an independent evaluator, a pinned rubric and host-computed acceptance, decided (OC-D205) to run on GoalDirected machinery; which subset the verifier loop already provides and which round, score and abstention mechanics are not built.
tags: [mission-control, workflow-systems, evaluator-optimizer, goal-loop, rubric, specified]
aliases: [EO, evaluator loop, optimization rounds, producer evaluator, rubric rounds]
questions:
  - How would an Evaluator Optimizer improve one deliverable?
  - How does Evaluator Optimizer reuse the Goal Loop verifier?
  - What does the evaluator see and what does the next producer receive?
  - Is acceptance the evaluator's accept or a host decision?
  - Can a manifest run an evaluator_optimizer node today?
updated: 2026-11-02
---

# Evaluator Optimizer on Goal Loop machinery

[Evaluator Optimizer](../../GLOSSARY.md) (EO) raises the quality of one deliverable through repeated production
and independent evaluation. Its route is fixed (produce, evaluate, decide), which separates it from a
[Goal Loop](goal-loop.md) (the next action is adaptive) and from a Stage Graph revisit region (a known route
repeats). **Decided (OC-D205, owner 2026-10-29): bounded produce/evaluate/accept-or-repair EO reuses GoalDirected
machinery**, keeps distinct producer and evaluator node/execution/session identities, seals the exact candidate,
rubric and evidence for the evaluator, passes full typed prior reports to the next producer, leaves acceptance to
the host and makes an unavailable evaluation wait or retry rather than become rejection. EO keeps its own
classification as a workflow system; the decision reclassifies nothing and claims no runtime completion
([ADR-0068](../adr/0068-parallel-swarm-is-a-stage-graph-profile-and-evaluator-optimizer-runs-on-goal-loop-machinery.md);
[DECISIONS](../specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md) `:348`).

## 1. Scheduling

Target round (annex `workflow-types/04` §§7-10): phases `producing, evaluating, deciding`; cycle decision `accept`,
`continue`, `stop` (`max_rounds` gives `threshold_not_reached`; exhausted `no_improvement_patience` gives
`no_progress`), `await_input` or `revise`; a round improves only when the aggregate score rises by
`min_improvement_delta`; governors `max_rounds`, patience, `round_budget`, `system_budget`, `wall_clock`,
`max_evaluator_retries`; at the cap the best candidate is lineage and is projected only with `accept_best_at_cap`
and passing hard gates. On GoalDirected machinery the mapping is: producer = executor role, evaluator = verifier
role, round = iteration, rounds cap = `max_iterations`, patience = `max_no_progress_iterations`, host decision =
`decide_convergence` (`domain/programs/goal_directed.py:671`). Built: that loop. Not built: score aggregation,
`min_improvement_delta`, `accept_best_at_cap`, `await_input`, an explicit `round` record or phase names.

## 2. Output-contract obligations

Acceptance is computed, not reported: the evaluator's disposition is an input to the system's completion contract
evaluated over the round's reports (minimum score, zero blocking findings), never the verdict ([completion](completion.md),
ADR-0010). Built: the verifier decision `accepted | rejected | revision_required | repair_required`
(`GoalVerifierDecision`, `domain/programs/contracts.py`) is an input; `OutputFulfillmentService.converge` then decides the
declared promises and `bind_fulfillment` turns an acceptance into a rejection when a required promise is unfulfilled
(`application/programs/goal_directed.py:1399`). Assessments of an exact output are recorded through the host-access
interface (an assessor never judges its own output) and the trusted knowledge bridge, which is the production
evaluator in the integrated fixtures ([trusted judgment](trusted-judgment.md)). For code or extraction deliverables
the target puts a deterministic check before any model judge and forbids a later judgment reversing it: not built
(the deterministic executor kinds are absent).

## 3. Context transfer

The `evaluator` boundary gives the independent evaluator only its nominated subject, bound to the exact producer
attempt (`transfer_builders.evaluator`, `authorized_subjects`, `domain/context/transfer_builders.py:148,184`); a
fallback binds to the iteration's exact executor, and the evaluator's report-handle tools are scoped to its plan's
reports and purpose. The `repair` boundary delivers the held subject and the full persisted verifier findings to
the next producer (`application/programs/goal_context.py`; linked run-14 delivered 6,882 bytes of findings). Findings for
an older revision cannot approve a successor because verification is bound to the admitted executor evidence
frontier and stale-frontier digest (`domain/programs/goal_directed.py:287-340`). Not built: a typed prior-report list across rounds
beyond the iteration's feedback, and `abstain` handling.

## 4. Agent runtime and capability configuration

Producer and evaluator must have distinct program-node identity, execution identity and agent session;
`evaluator_independence` may tighten this to `model` or `runtime`. Built: executor and verifier are separate
templates with separate sealed lane bindings; the verifier is refused `submit_output`, `report_register` and
`knowledge_apply` (`ROLE_SEPARATION`, `application/knowledge/toolset.py:805`); `GoalVerifierPolicy` pins
`rubric_ref`, `rubric_version`, `acceptance_version` and `binding_ref`, and a result with another pin is refused
(`domain/authoring/contracts.py:1450`). The rubric schema belongs to Knowledge Services; Mission Control pins it by
reference and version; a rubric change is a revision proposal and in-flight rounds finish on the old one
([revisions](revisions.md)). The manifest accepts `behavior: evaluator_optimizer` (`EvaluatorOptimizerNode`,
`domain/authoring/manifest.py:993`) with free-form `params`, but lowering has no path for it, so compile refuses it (`UNSUPPORTED_BEHAVIOR` `behavior_not_built` on every lane,
`application/authoring/manifest_service.py`, OVE-215, as for a swarm node; before 2026-11-02 it silently lowered to a one-stage
Stage Graph, `domain/authoring/manifest_lowering.py:709-712`); Deep Agents declares
`EvaluatorOptimizer: unqualified` (`adapters/deep_agents/describe.py:159`). The unreviewed branch `sprint-oc-wi15`
(`0c14071a`, migration 0071, `evaluator_optimizer.py`) is a separate-family implementation, preserved source only
(note its migration key 0071 also appears in [recursive composition](recursive-composition.md)).

Built / specified / goal: the Goal Loop verifier-with-pinned-rubric subset and host fulfillment are built and integrated locally; rounds, scores, patience, abstention, deterministic-first panels and the EO manifest lowering are specified only; Deep Agents support is `unqualified`.

# Citations

- Decision: [OC-D205](../specs/provider-consolidation-2026-10/answers/SPRINT-OC-RECOVERY-SITTING-1-2026-10-29-ANSWERS.md) (`:22`), [ADR-0068](../adr/0068-parallel-swarm-is-a-stage-graph-profile-and-evaluator-optimizer-runs-on-goal-loop-machinery.md), [ADR-0010](../adr/0010-completion-expressions-closed-typed-ast.md).
- Spec (harvested at `66185d2e`): `workflow-types/04-EVALUATOR_OPTIMIZER.md` §§3-11; OUTPUT-CONTRACTS §9 (EO paragraph).
- Code: [GoalDirected interpreter](../../src/mission_control/domain/programs/goal_directed.py), [verifier contracts](../../src/mission_control/domain/programs/contracts.py),
  [policies](../../src/mission_control/domain/authoring/contracts.py), [application service](../../src/mission_control/application/programs/goal_directed.py),
  [transfer builders](../../src/mission_control/domain/context/transfer_builders.py), [manifest node](../../src/mission_control/domain/authoring/manifest.py).
- Tests: [verifier loop](../../tests/unit/orchestration/test_wp_bp_020_goal_directed.py), [fulfillment at convergence](../../tests/unit/outputs/test_w1_convergence_fulfillment.py),
  [lane support](../../tests/unit/authoring/test_manifest_compile.py).
- Evidence (integrated, not qualified): [control board](../specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md) (`:69-87` independent KS verification with real repair; `:362-366` held-repair delivery).
