---
type: Interview Answers
title: "Sprint OC recovery: architecture approvals and source consolidation"
description: "Owner architecture approvals and later full recoverable checkout consolidation authorization; source preservation and W1 harness recovery do not qualify runtime behavior."
tags: [mission-control, interview, answers]
interview: ../../archive/provider-consolidation-2026-10/sessions/SESSION-CODEX-RESUME-2026-10-29.md
sitting: "1"
date: 2026-10-29
status: open
---

# Sprint OC recovery: owner answers

Source: this Codex conversation on 2026-10-29. The owner asked whether independent StageGraph
stages feeding convergence should implement Swarm, including as part of a larger graph.

## Decisions

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D204 | Approve “Swarm is a StageGraph composition/profile, not a separate workflow-system primitive; preserve its group policies and use common scheduling and transfer machinery”? | "Approved" | 2026-10-29 | Reclassify Swarm as a reusable StageGraph profile/subgraph; preserve group behavior and proof requirements; consolidate execution machinery. EO and integration patches remain separate decisions. | spec OUTPUT-CONTRACTS §9; workflow annexes 00/01/03; OVE-177; qualification terminology OVE-186 | [Decision register](../sprint-oc/DECISIONS.md#7-recovery-architecture-decisions-2026-10-29), [control board](../../archive/provider-consolidation-2026-10/docs/SPRINT-OC-LOG-2026-10-29-31.md#current-control); [canonical amendment](../../../knowledge/output-contracts.md) |
| OC-D205 | Approve bounded produce/evaluate/accept-or-repair EO using GoalDirected machinery, distinct producer/evaluator node/execution/session identities, sealed exact candidate/rubric/evidence, full typed prior reports and host acceptance? | "Yes approved." | 2026-10-29 | Retain EO semantics while sharing execution machinery; repair reduced feedback, role-as-node identity and broad evaluator access. Unavailable evaluation waits/retries rather than becoming rejection. | spec OUTPUT-CONTRACTS §§6/9; workflow annex 04 §§3–7; OVE-178 | [Decision register](../sprint-oc/DECISIONS.md#7-recovery-architecture-decisions-2026-10-29), [control board](../../archive/provider-consolidation-2026-10/docs/SPRINT-OC-LOG-2026-10-29-31.md#current-control); existing canonical semantic requirements retained, runtime repairs pending |
| OC-D206 | Proceed through cleanup, documentation/navigation and reliable test wrappers now, returning to W1? | "Can you do everything up until 4 now. Returning to W1's critical path. You can use GPT 6 Astra subagents." | 2026-10-29 | Authorizes execution/integration of the bounded recovery steps 1–3 in this run without another approval pause for each prepared sub-batch. Preserve independent review, source custody and recovery checks; stop unsafe cleanup. W1 runtime repairs and paid/remote runs remain separate. | recovery B1a/B1b/B2; NEXT-SESSION current control | [Control board](../../archive/provider-consolidation-2026-10/docs/SPRINT-OC-LOG-2026-10-29-31.md#current-control) |
| OC-D207 | Consolidate all 58 registered checkouts into the four canonical primary owners while preserving unfinished source and evidence? | "I want them integrated and removed or something like that. Please just do it." | 2026-10-29 | Authorizes the full 58-to-four custody/removal scope, superseding retention of the five physical unfinished checkouts once their source/evidence homes are verified. Preserve original/recovery refs, bundles and ignored material; W1 nine-file source recovery is separate from native/Swarm/EO runtime integration. Verified 2026-10-29: ordinary removal completed, four primary registrations on sprint-oc remain, all 54 nonprimary paths are absent and source/evidence homes retained. | recoverable full consolidation; W1 source custody; NEXT-SESSION control board | [Decision register](../sprint-oc/DECISIONS.md#7-recovery-architecture-decisions-2026-10-29), [control board](../../archive/provider-consolidation-2026-10/docs/SPRINT-OC-LOG-2026-10-29-31.md#full-consolidation-and-w1-source-recovery-oc-d207) |

## Approved recommendation and mental model

Swarm is a reusable StageGraph profile/subgraph, usable as an entire graph or inside a larger one.
Any Swarm shorthand compiles into the common graph representation. Members and convergence are
ordinary stages, with nested bodies where supported. Convergence may be deterministic, agent-based
or human-controlled. Concurrency obeys available capacity and configured limits; serial execution
does not change the pattern's semantics.

Preserve group activation identity, budget, membership, selection and settlement. Retain
all/first-accepted/quorum/best-effort policies, member isolation and the Swarm profile's default
surplus cancellation; ordinary graphs retain continuation by default. Convergence receives selected
exact outputs/findings/gaps through the common sealed plan and attempt receipts. Late outputs cannot
mutate its inputs. Cancelling surplus work does not erase costs or pending effects.

Recover useful reducers, records and tests from interrupted work and consolidate duplicated control
machinery through separately reviewed integration batches. OC-D204 approves no source deletion;
later OC-D207 separately authorizes physical checkout retirement after recoverable source custody.
Linked missions retain independent goals, budgets, grants and lifecycle, with explicit exports and
release gates through the same transfer mechanism; delivery alone does not adopt obligations.
Classification changes do not waive behavioral qualification requirements.

## EO approval and sprint orientation

The owner approved the preceding recommendation with "Yes approved.": reuse GoalDirected execution
machinery for a bounded produce → evaluate → accept-or-repair loop. Producer and evaluator retain
separate node, execution and session identities. The evaluator receives the exact candidate, rubric
and permitted evidence through the common sealed transfer mechanism; the next producer receives the
selected prior candidate and full typed evaluation reports. Acceptance remains host-controlled;
unavailable evaluation waits or retries. This requires repairs to the interrupted implementation.

The owner then requested worktree cleanup, documentation updates and a return to output contracts and
context transfer across workflows in both applications, concentrating on Deep Agents while retaining
multiple-provider support through deep reusable modules. The stated outcome is complex workflows
"FOR REAL". This is the delivery objective; local checks and cleanup do not constitute qualification.
Later OC-D206/207 authorize the specified recovery and full checkout consolidation without repeated
cleanup approval pauses. Other runtime integration batches and paid-run checkpoints remain controlled.

## Assumptions (asked, not answered)

EO approval does not reclassify EO as a StageGraph profile or remove its semantic identity. OC-D207
explicitly authorizes full recoverable checkout consolidation; it does not authorize unreviewed
native/Swarm/EO runtime integration, paid fixtures or remote installations.

## Conversion checklist

- [x] Actual answer recorded in the decision register and control board.
- [x] Canonical contract patch independently reviewed and applied as B0-Swarm after owner reply "Yes I approve" (2026-10-29). Exact patch and source hashes verified; documentation checks recorded on the control board.
- [ ] Reconcile glossary/ADR and authoring/runtime impact during bounded implementation planning.
- [ ] Tracker sync queue: OVE-177 scope, OVE-178 EO repair direction and OVE-186 terminology; no remote update or completion claimed.
- [x] Ledger entry added.
- [x] OC-D207 full-consolidation authorization and W1 source-recovery limits recorded.
- [x] Final bulk removal verified: 58 to four primary registrations on `sprint-oc`; 54 original checkout paths absent, branches/recovery refs retained, 6,254 ignored objects preserved (11 links), four bundle and five source-ZIP hashes passed.

Status stays open until conversion completes. Architecture approval does not approve a frozen
integration or cleanup batch.
