---
type: Concept
category: domain-model
title: Parallel Swarm as a Stage Graph profile
description: Peer member variants and one convergence step decided (OC-D204) to be a reusable Stage Graph profile over common scheduling and transfer, mapped member by member onto the Stage Graph mechanics that exist (joins, release groups, coverage, impossibility) and the pieces that do not (profile shorthand, variant identity, surplus cancellation, deterministic convergence kinds).
tags: [mission-control, workflow-systems, parallel-swarm, stage-graph, profile, specified]
aliases: [swarm, member variants, quorum members, convergence step, swarm profile]
questions:
  - How does Parallel Swarm run as a Stage Graph profile?
  - How do quorum, first-accepted and best-effort map onto Stage Graph groups?
  - What happens to surplus swarm members when the policy is satisfied?
  - Can a manifest run a parallel_swarm node today?
  - What would a swarm convergence step receive?
updated: 2026-11-02
---

# Parallel Swarm as a Stage Graph profile

[Parallel Swarm](../../GLOSSARY.md) runs several bounded, isolated member variants toward the same objectives on
the same immutable inputs, then brings selected exact results together through one explicit convergence step.
Members are peers, not dependencies: the work benefits from coverage, competition, comparison, redundancy or
judgment diversity. **Decided (OC-D204, owner 2026-10-29): Swarm is a reusable Stage Graph composition/profile,
usable as a whole graph or a nested subgraph, not a separate workflow-system primitive.** Members and convergence
are ordinary stages; any swarm shorthand compiles to the common Stage Graph representation; scheduling releases
eligible work under actual capacity, so serial capacity does not change the profile's semantics. Group identity,
budgets, member isolation, all/first-accepted/quorum/best-effort selection, exact selected output transfer and
settlement stay as profile policies and proof obligations ([ADR-0068](../adr/0068-parallel-swarm-is-a-stage-graph-profile-and-evaluator-optimizer-runs-on-goal-loop-machinery.md);
decision text in [DECISIONS](../specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md) `:347`). Nothing else about the
profile is built; read [stage graph](stage-graph.md) for the mechanics it reuses.

## 1. Scheduling: profile concept to Stage Graph mechanism

| Swarm concept (annex `workflow-types/03`) | Stage Graph mechanism | State |
| --- | --- | --- |
| Static member list; each member an executor or subprogram | Sibling stages with no `from:` between them; a subprogram is a [nested body](recursive-composition.md) | built (authoring-level) |
| Fan-out members from a committed template over a source output | Dynamic fan-out | specified only (`fan_out` governor only, `domain/authoring/manifest.py:588`) |
| `all` / `first_accepted` | Join `all` / `any` (`JoinKind`, `domain/authoring/manifest_lowering.py:459`) | built, tested (WI-08) |
| `quorum { required_accepted: k }`, converge at the k-th acceptance | Join `minimum` or a `JoinGroup` quorum over exact members | built, tested (`domain/authoring/graph_routes.py:195`) |
| `best_effort { min_accepted }`, wait for every terminal member | No direct form; an optional input pending at release is omitted visibly | not built |
| Only accepted members count; "first accepted", never "first finished" | Group thresholds count distinct accepted members in acceptance order | built |
| Feasibility `accepted + running >= k`, else `quorum_unreachable` | `JoinDisposition.IMPOSSIBLE` (`domain/programs/interpreter.py:253-275`) skips dependents visibly | built; the outcome name `quorum_unreachable` is not |
| Coverage across members (a quorum never proves all subjects) | `coverage_subjects`, `member_coverage` on the group | built |
| `on_resolution: cancel_remaining` (swarm default), `finish_best_effort`, `finish_required` | Graph default is surplus continues; surplus producers are never sealed inputs (`EdgeSelection` `surplus`, `domain/programs/interpreter.py:76`) | cancellation not built |
| Governors `max_members`, `member_budget`, `swarm_budget`, `member_timeout`, `swarm_wall_clock`, `straggler_grace` | `max_concurrency`, per-slot `reservation`; the rest absent | partly |

Manifest authoring accepts `behavior: parallel_swarm` with free-form `params` (`ParallelSwarmNode`) and the lane
support check treats it as a declared family; Deep Agents declares `ParallelSwarm: unqualified`:

<!-- snippet: src/mission_control/domain/authoring/manifest.py:986-991 -->
```python
class ParallelSwarmNode(ProgramNodeBase):
    behavior: Literal["parallel_swarm"] = "parallel_swarm"
    objective: Slug | None = None
    action_space: tuple[Slug, ...] = ()
    params: dict[str, Any] = Field(default_factory=dict)

```

`manifest_lowering.py` has no swarm path: any root that is neither Stage Graph nor Goal Loop lowers to a one-stage
graph whose only stage is the root node itself (`_stage_children`, `domain/authoring/manifest_lowering.py:709-712`). Since
2026-11-02 compile refuses every `parallel_swarm` node before lowering: `UNSUPPORTED_BEHAVIOR` with reason `behavior_not_built`
on every lane, although Deep Agents declares the family `unqualified` (`UNBUILT_PROGRAM_BEHAVIORS`,
`application/authoring/manifest_service.py`; test `test_unbuilt_program_behaviors_are_refused_not_lowered_to_one_stage`;
OVE-215). Before that fix a swarm root silently ran as one agent stage. The unreviewed branch `sprint-oc-wi14` (`cf2575d6`, migration 0070,
`swarm_body.py`) implements a separate family with member/convergence reducers; OC-D204 reclassified that shape, so
it needs reconciliation into the Stage Graph path, not integration as is.

## 2. Output-contract obligations

Target: each member may carry a member-level completion contract and an importance (`required`, `optional`,
`best_effort`); convergence has its own completion contract and only its projected outputs are the swarm's outputs;
member outputs stay inspectable lineage with their variant attached; member exports need explicit selection. A
convergence that rejects leaves the swarm `not_accepted` without silently re-running members. Built today only as
ordinary Stage Graph obligations per stage ([output contracts](output-contracts.md)); "quorum alone does not prove
independent all-subject coverage" is enforced by group coverage.

## 3. Context transfer

Members receive isolated admitted inputs: the same sealed `first_invocation`/`dependent_stage` selections, and no
member reads another's output. Convergence receives the selected members, findings and gaps through the ordinary
`dependent_stage` plan, with `release_omissions` for what was left out; late arrivals cannot mutate a sealed plan
(`domain/context/transfer_builders.py:85`, `application/programs/service.py:2819`). Cancellation never erases incurred cost or a
pending effect (effects reconcile under their original identity). Built as Stage Graph transfer; swarm-specific
member variant records are not.

## 4. Agent runtime and capability configuration

A Member Variant (`variant_key`, optional model, runtime, instruction variant, input slice) is part of member
identity and is recorded on every member output, receipt and evaluation report; experiments such as model or
harness comparison are swarms whose members differ by variant, with no separate experiment engine. Today a variant
is just a stage whose node `environment` selects another lane, model profile or capability set
([mission manifest](mission-manifest.md), ADR-0063); no `variant_key` is recorded. Convergence may be a
Deterministic Executor (`coalesce`, `agreement_check`: kinds not built), an [Evaluator Optimizer](evaluator-optimizer.md)
or direct-model ranking with recorded judge identity, or a human `SELECTION` task ([human gates](human-gates.md)).

Built / specified / goal: Stage Graph group, quorum, coverage and impossibility mechanics built and integrated locally; the swarm profile, variant identity, surplus cancellation, best-effort and convergence kinds specified only; the owner's swarm proof obligations remain open and Deep Agents support is `unqualified`.

# Citations

- Decision: [OC-D204](../specs/provider-consolidation-2026-10/answers/SPRINT-OC-RECOVERY-SITTING-1-2026-10-29-ANSWERS.md) (`:21`), [ADR-0068](../adr/0068-parallel-swarm-is-a-stage-graph-profile-and-evaluator-optimizer-runs-on-goal-loop-machinery.md).
- Spec (harvested at `66185d2e`): `workflow-types/03-PARALLEL_SWARM.md` §§3-10; OUTPUT-CONTRACTS §9 (Swarm classification amendment).
- Code: [manifest behaviors](../../src/mission_control/domain/authoring/manifest.py), [interpreter](../../src/mission_control/domain/programs/interpreter.py),
  [groups and coverage](../../src/mission_control/domain/authoring/graph_routes.py), [nested extension point](../../src/mission_control/domain/programs/nested.py),
  [Deep Agents declaration](../../src/mission_control/adapters/deep_agents/describe.py).
- Tests: [route and group semantics](../../tests/unit/orchestration/test_wi08_graph_routes.py), [lane support matrix](../../tests/unit/authoring/test_manifest_compile.py),
  [behaviors parse](../../tests/unit/authoring/test_manifest_schema.py); experiments are not the kernel ([experiment](../../tests/experiments/test_dynamic_research_swarm.py)).
- Unreviewed source: branch `sprint-oc-wi14`, commits `cf2575d6`, `4fa865b7`, `6c558096` (see [control board](../specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md) `:695`).
