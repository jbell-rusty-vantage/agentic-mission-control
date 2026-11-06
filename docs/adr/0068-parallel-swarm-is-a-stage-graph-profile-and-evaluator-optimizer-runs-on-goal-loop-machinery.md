---
type: Decision Record
title: "Parallel Swarm is a Stage Graph profile and Evaluator Optimizer runs on Goal Loop machinery"
description: "Accepted 2026-11-01 (owner approval AS-D34, recording OC-D204 and OC-D205 of 2026-10-29): Swarm is a reusable Stage Graph composition/profile over common scheduling and transfer, Evaluator Optimizer reuses the GoalDirected machinery with distinct producer and evaluator identities and host acceptance; the decided workflow behaviours are three, and the code's four-family vocabulary changes to match."
tags: [mission-control, adr, accepted, workflow-systems, stage-graph, goal-loop, swarm, evaluator-optimizer]
status: accepted
date: 2026-11-01
source: docs/specs/provider-consolidation-2026-10/answers/SPRINT-OC-RECOVERY-SITTING-1-2026-10-29-ANSWERS.md (OC-D204, OC-D205); docs/specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md:347-348; docs/specs/agentic-sdlc-2026-11/answers/AGENTIC-SDLC-SITTING-II-2026-11-02-ANSWERS.md (AS-D34)
---

# Parallel Swarm is a Stage Graph profile and Evaluator Optimizer runs on Goal Loop machinery

**Status: accepted 2026-11-01.** The owner approved the decisions on 2026-10-29 (OC-D204 "Approved", OC-D205 "Yes
approved.") and approved recording them and rewriting the workflow concepts on 2026-11-01 (AS-D34, "MC-2: Yes
approved"). Nothing in the runtime is built by this record; no qualification gate is released.

## Context

The specification named four workflow systems: Stage Graph, Goal Loop, Parallel Swarm and Evaluator Optimizer
(`workflow-types/00` to `04`, since deleted with the spec pack). The code followed with four families in the
resolution vocabulary (`Family` in `domain/resolution/configuration.py`), a lane declaration row per family, a
behavior-to-family map (`FAMILY_OF_BEHAVIOR`) and, on two unreviewed recovery branches (`sprint-oc-wi14`,
`sprint-oc-wi15`), separate Swarm and Evaluator Optimizer runtimes with their own migrations. Reading them against
the working Stage Graph (release groups with `all`/`any`/quorum selection, coverage, impossibility, exact sealed
transfer) and GoalDirected (executor/verifier alternation, pinned rubric, host fulfillment, typed repair feedback)
showed that Swarm's scheduling, selection and transfer and EO's produce/evaluate/repair loop are those
mechanisms with additional policy, and that a separate family would duplicate scheduling, settlement and transfer.

## Decision

1. **Parallel Swarm is a reusable Stage Graph composition/profile**, usable as a whole graph or a nested subgraph, not a
   separate workflow-system primitive (OC-D204). Members and convergence are ordinary stages; any swarm authoring
   shorthand compiles into the common Stage Graph representation and execution path; scheduling releases eligible work
   under actual capacity, concurrency and budget limits, and serial capacity does not change the profile's semantics.
   Preserved as profile policy and proof obligations: group activation identity and budgets, member isolation, `all`,
   first-accepted, quorum and best-effort selection, exact selected output transfer, surplus cancellation by default
   (ordinary graphs keep continuation by default) and settlement. Convergence consumes selected exact outputs, findings
   and gaps through the common sealed transfer plan and attempt receipts; late arrivals cannot mutate sealed inputs;
   cancellation never erases incurred cost or pending effects.
2. **Evaluator Optimizer runs on GoalDirected machinery** (OC-D205): bounded produce, evaluate and accept-or-repair rounds
   over the same execution core, with distinct producer and evaluator node, execution and session identities, a sealed
   exact candidate, rubric and evidence for the evaluator, full typed prior reports to the next producer, host-computed
   acceptance (the evaluator's disposition is an input), and unavailable evaluation that waits or retries rather than
   rejects. EO keeps its classification as a workflow system; this decision reclassifies nothing else.
3. **The decided workflow behaviours are three**: Stage Graph, Goal Loop and Evaluator Optimizer, plus Swarm as a Stage
   Graph profile. Linked workflows remain mission chains with independent goals, budgets and grants (ADR-0029);
   nested and linked workflows keep their distinct lifecycle and authority boundaries.

## Rejected

A separate Swarm family and runtime (duplicate scheduling, transfer and settlement; the shape of `sprint-oc-wi14`); a
separate Evaluator Optimizer family and round table (the shape of `sprint-oc-wi15`); merging EO into a Stage Graph
revisit region (annex `workflow-types/04` §1: the route is fixed, but evaluation must be independent and bounded by
rounds, which a known repeated route is not);
keeping four families "for qualification clarity" (OC-D204 governs older four-family terminology).

## Consequences

- **Code vocabulary change (four families to three behaviours; issue to file in Sprint OC, AS-D34):** the code still
  names four families. The `Family` literal, the per-family lane declaration rows (`adapters/<lane>/describe.py`),
  `FAMILY_OF_BEHAVIOR` and `V2_LANE_BEHAVIORS` should stop treating `ParallelSwarm` and `EvaluatorOptimizer` as families
  (executable families `StageGraph` and `GoalDirected`, the Goal Loop subset), the manifest's `parallel_swarm` and
  `evaluator_optimizer` behaviours become shorthand that compiles into the Stage Graph profile and the Goal Loop
  evaluator configuration, and lane qualification is then recorded against what is proven. The unreviewed branches and
  their migration keys must be reconciled, not integrated as is (`0070_swarm_activations`, `0071_evaluator_optimizer_rounds`; key 0071
  also collides with the unregistered `0071_nested_program_activations`).
- **Open defect surfaced by the audit:** a `parallel_swarm` or `evaluator_optimizer` root currently compiles on Deep Agents
  with no blocker or warning and lowers to a one-stage Stage Graph (`manifest_lowering.py:709-712`). Until the profile
  exists, compile should block these behaviours with a typed `UNSUPPORTED_BEHAVIOR`.
- Swarm and EO behavioural proof obligations remain open; nothing here is runtime completion evidence. ADR-0063's
  consequence "Swarm and Evaluator Optimizer family support stays `unqualified` until WI-14 and WI-15" is superseded by
  "until the profile and the evaluator configuration are proven on Stage Graph and Goal Loop machinery".
- The glossary already carries the decision (Workflow System, Parallel Swarm, Evaluator Optimizer). The concepts
  `workflow-systems`, `stage-graph`, `goal-loop`, `parallel-swarm` and `evaluator-optimizer` describe the code as it is
  and the decision as decided.
- Output-contract semantics for both profiles stay those of the deleted `OUTPUT-CONTRACTS.md` §9 (harvested into
  `parallel-swarm`, `evaluator-optimizer` and `output-contracts`).
