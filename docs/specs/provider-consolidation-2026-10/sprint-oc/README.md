---
type: Sprint Workspace
title: "Sprint OC final specification and implementation workspace"
description: "Canonical target, published tracker graph, team plan, proof gates, decision conversion and immediate kickoff."
tags: [mission-control, output-contracts, knowledge-services, sprint]
date: 2026-10-26
---

# Sprint OC: output contracts, exact context and knowledge services

**Current entry point (2026-11-01):** [NEXT-SESSION](NEXT-SESSION.md) is the live control board; the packet below is the
Sprint OC specification and its preparation snapshot, both historical for state. The recovery material is the [source/worktree/evidence audit](../../archive/provider-consolidation-2026-10/docs/RECOVERY-AUDIT-2026-10-29.md) and
[Codex Astra/Sol controlled recovery instruction](../../archive/provider-consolidation-2026-10/sessions/SESSION-CODEX-RESUME-2026-10-29.md). Preserve existing
sprint branches and dirty worktrees. The following preparation snapshot and published work map remain
historical; they do not instruct a fresh start from `main` or certify current gate completion.

## Preparation snapshot (2026-10-26)

**Ready for implementation.** [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) is the published specification with **31 child
issues, 56 verified native blocking relationships and one related link to OVE-150**. The new runtime
is unbuilt/unqualified. Historical Sprint V evidence is a source baseline with first-use gaps, not
automatic acceptance of this sprint. Start with [KICKOFF.md](../../archive/provider-consolidation-2026-10/sessions/KICKOFF.md). The sprint-start interview of
2026-10-27 fixed the operating rules (commit when complete, disposable remote targets, model pins,
USD 40 ceiling, coordinator host, escalation): [DECISIONS §5](DECISIONS.md#5-sprint-start-operating-decisions-2026-10-27).

| Read | Purpose |
| --- | --- |
| [Application ports and schema navigation](APPLICATION-PORTS.md) | Read before selecting an application slice: store boundaries, current versus planned context hops, then one AI Engineer or Biotech schema card. |
| [Canonical target](../../../knowledge/output-contracts.md) | One authoritative behavior specification: typed contracts, ownership, lifecycles, exact delivery, four workflows and worked cases. |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Source seams and removals, migrations, repository ownership, dependency frontiers, claims, review and commands. |
| [PROOFS.md](PROOFS.md) | W0–W5, RV-01–08, both apps, eight forms, all families, Deep Agents/host/backend/native proofs; then F1/F2/F3 and evaluation. |
| [DECISIONS.md](DECISIONS.md) | All 195 owner decisions, 28 older recommendations, five canonical ADRs and explicit unselected options. |
| [WORK-ITEMS.json](WORK-ITEMS.json) | Machine-readable 31-item scope, dependencies, real Linear IDs/URLs, acceptance and publication time. |
| [KICKOFF.md](../../archive/provider-consolidation-2026-10/sessions/KICKOFF.md) | Paste-ready integrator assignment for Codex or Claude Code. |
| [ESCALATION.md](ESCALATION.md) | Where a blocked question goes and the heuristics applied when the owner is away; the sprint moves on. |
| [SELECTION-AND-ROUTING-DESIGN.md](../../archive/provider-consolidation-2026-10/specs/SELECTION-AND-ROUTING-DESIGN.md) | Accepted 2026-10-27 (OC-D197 to OC-D202): the adaptation mechanism, one resolution seam, registries, ports, depth test, conformance strategy and the R0–R7 breakdown that precedes WI-02/03/04/05/23/24; [interfaces](../../archive/provider-consolidation-2026-10/specs/SELECTION-AND-ROUTING-INTERFACES.md); ADR-0063 accepted. Issues OVE-194 to OVE-202 below. |

## Execution order

Begin [OVE-195](https://linear.app/overtonbell/issue/OVE-195) (OC-R0, the interface freeze) and
[OVE-163](https://linear.app/overtonbell/issue/OVE-163/oc-compile-and-fulfill-explicit-named-output-promises) (WI-01, common authoring/submission
contract) in parallel; they do not share files. The older cards OVE-69/73/75/77/78 are handled seam-only
with a W0 baseline audit (OC-D195). After WI-01, transfer (WI-02) and durable settlement (WI-04) can split. The remainder follows
the ready frontier in the table. Coordinate shared protocol/schema files through one integrator.

Proof release is W0 → W1 → W2 → W3 → W4 → W5. Independent implementation may proceed earlier;
a blocked proof gate is not permission to claim qualification. Every sprint item feeds W5. The seven
post-sprint items run afterward: capability readiness, independent evaluation, F1, F2, F3 ingestion,
F3 retrieval/ranking/routing and final feedback closure. Full product architecture follows the stress
results and is not designed here as a prerequisite.

## Published work and native blockers

The `ready-for-agent` label means prepared for assignment; only issues whose blockers are done are
currently executable. All new cards are Backlog except the first ready contract item (Todo).

| Key / phase | Published issue and result | Blocked by |
| --- | --- | --- |
| WI-01 / sprint | [OVE-163](https://linear.app/overtonbell/issue/OVE-163/oc-compile-and-fulfill-explicit-named-output-promises): Compile and fulfill explicit named output promises | None |
| WI-02 / sprint | [OVE-164](https://linear.app/overtonbell/issue/OVE-164/oc-deliver-exact-admitted-inputs-with-one-sealed-plan): Deliver exact admitted inputs with one sealed plan | OVE-163 |
| WI-03 / sprint | [OVE-165](https://linear.app/overtonbell/issue/OVE-165/oc-compose-trusted-report-assessment-and-use-review): Compose trusted report assessment and use review | OVE-164 |
| WI-04 / sprint | [OVE-166](https://linear.app/overtonbell/issue/OVE-166/oc-settle-saved-provider-results-without-repeated-cognition): Settle saved provider results without repeated cognition | OVE-163 |
| WI-05 / sprint | [OVE-167](https://linear.app/overtonbell/issue/OVE-167/oc-recover-native-commits-across-missing-protocol-receipts): Recover native commits across missing protocol receipts | OVE-165, OVE-166 |
| WI-24 / sprint | [OVE-168](https://linear.app/overtonbell/issue/OVE-168/oc-release-w0-four-owner-schema-and-trusted-runtime-foundations): Release W0 four-owner schema and trusted-runtime foundations | OVE-165, OVE-167 |
| WI-06 / sprint | [OVE-169](https://linear.app/overtonbell/issue/OVE-169/oc-prove-the-first-ordinary-goaldirected-report): Prove the first ordinary GoalDirected report | OVE-168 |
| WI-07 / sprint | [OVE-170](https://linear.app/overtonbell/issue/OVE-170/oc-assess-report-collections-and-accumulate-current-accepted-sets): Assess report collections and accumulate current accepted sets | OVE-169 |
| WI-08 / sprint | [OVE-171](https://linear.app/overtonbell/issue/OVE-171/oc-execute-explicit-graph-routes-and-alternative-input-release): Execute explicit graph routes and alternative input release | OVE-169 |
| WI-09 / sprint | [OVE-172](https://linear.app/overtonbell/issue/OVE-172/oc-execute-typed-transforms-with-explicit-join-populations): Execute typed transforms with explicit join populations | OVE-170 |
| WI-10 / sprint | [OVE-173](https://linear.app/overtonbell/issue/OVE-173/oc-schedule-bounded-inventory-and-governed-partition-successors): Schedule bounded inventory and governed partition successors | OVE-172 |
| WI-11 / sprint | [OVE-174](https://linear.app/overtonbell/issue/OVE-174/oc-close-groups-and-qualify-reductions-with-coverage): Close groups and qualify reductions with coverage | OVE-173, OVE-171 |
| WI-12 / sprint | [OVE-175](https://linear.app/overtonbell/issue/OVE-175/oc-reassess-synthesis-for-the-selected-source-changes): Reassess synthesis for the selected source changes | OVE-170, OVE-171 |
| WI-13 / sprint | [OVE-176](https://linear.app/overtonbell/issue/OVE-176/oc-execute-recursive-goal-loops-and-subgraphs): Execute recursive Goal Loops and subgraphs | OVE-170, OVE-171 |
| WI-14 / sprint | [OVE-177](https://linear.app/overtonbell/issue/OVE-177/oc-execute-swarm-members-and-exact-convergence): Execute Swarm members and exact convergence | OVE-176 |
| WI-15 / sprint | [OVE-178](https://linear.app/overtonbell/issue/OVE-178/oc-execute-independent-evaluator-optimizer-repair-rounds): Execute independent Evaluator Optimizer repair rounds | OVE-176, OVE-165 |
| WI-16 / sprint | [OVE-179](https://linear.app/overtonbell/issue/OVE-179/oc-transfer-exact-linked-exports-within-each-application): Transfer exact linked exports within each application | OVE-170, OVE-171 |
| WI-17 / sprint | [OVE-180](https://linear.app/overtonbell/issue/OVE-180/oc-prepare-hook-context-through-scoped-reads-and-staged-files): Prepare hook context through scoped reads and staged files | OVE-164 |
| WI-18 / sprint | [OVE-181](https://linear.app/overtonbell/issue/OVE-181/oc-preserve-validated-context-and-historical-repair-fork-inputs): Preserve validated context and historical repair-fork inputs | OVE-180, OVE-170, OVE-75 |
| WI-19 / sprint | [OVE-182](https://linear.app/overtonbell/issue/OVE-182/oc-deliver-exact-coordinator-inspection-and-bounded-selected-content): Deliver exact coordinator inspection and bounded selected content | OVE-164, OVE-78 |
| WI-22 / sprint | [OVE-183](https://linear.app/overtonbell/issue/OVE-183/oc-execute-bounded-durable-transition-reactions): Execute bounded durable-transition reactions | OVE-163, OVE-166 |
| WI-23 / sprint | [OVE-184](https://linear.app/overtonbell/issue/OVE-184/oc-deliver-dynamic-async-child-bindings-and-check-time-result): Deliver dynamic async child bindings and check-time result admission | OVE-164, OVE-166 |
| WI-32 / sprint | [OVE-185](https://linear.app/overtonbell/issue/OVE-185/oc-release-w4-integrated-revision-composition-and-recovery-checkpoint): Release W4 integrated revision composition and recovery checkpoint | OVE-174, OVE-175, OVE-179, OVE-181, OVE-183 |
| WI-21 / sprint | [OVE-186](https://linear.app/overtonbell/issue/OVE-186/oc-qualify-the-full-workflow-version-and-both-applications): Qualify the full workflow version and both applications | OVE-185, OVE-177, OVE-178, OVE-182, OVE-184, OVE-73 |
| WI-25 / post-sprint | [OVE-187](https://linear.app/overtonbell/issue/OVE-187/oc-qualify-the-complete-stress-fixture-skills-and-interactive-browser): Qualify the complete stress-fixture skills and interactive browser profiles | OVE-186 |
| WI-26 / post-sprint | [OVE-188](https://linear.app/overtonbell/issue/OVE-188/oc-establish-independent-mission-work-evaluation-and-versioned): Establish independent mission-work evaluation and versioned evidence | OVE-186 |
| WI-27 / post-sprint | [OVE-189](https://linear.app/overtonbell/issue/OVE-189/oc-run-generation-lab-exhaustive-discovery-and-report-intent-stress): Run Generation Lab exhaustive discovery and report-intent stress mission | OVE-187, OVE-188 |
| WI-28 / post-sprint | [OVE-190](https://linear.app/overtonbell/issue/OVE-190/oc-run-qualia-life-product-ingredient-study-verification-stress-graph): Run Qualia Life product-ingredient-study verification stress graph | OVE-187, OVE-188 |
| WI-29 / post-sprint | [OVE-191](https://linear.app/overtonbell/issue/OVE-191/oc-ingest-the-model-and-benchmark-dataset-with-exact-native-provenance): Ingest the model and benchmark dataset with exact native provenance | OVE-187, OVE-188 |
| WI-30 / post-sprint | [OVE-192](https://linear.app/overtonbell/issue/OVE-192/oc-evaluate-database-grounded-model-retrieval-ranking-and-routing): Evaluate database-grounded model retrieval ranking and routing | OVE-191 |
| WI-31 / post-sprint | [OVE-193](https://linear.app/overtonbell/issue/OVE-193/oc-close-stress-feedback-loops-and-hand-off-product-architecture): Close stress feedback loops and hand off product-architecture evidence | OVE-189, OVE-190, OVE-192 |

## Prerequisite seam: OC-R (accepted 2026-10-27)

The [selection-and-routing design](../../archive/provider-consolidation-2026-10/specs/SELECTION-AND-ROUTING-DESIGN.md) precedes the affected sprint items.
All deterministic work, USD 0 of the budget.

| Key | Published issue and result | Blocked by | Blocks |
| --- | --- | --- | --- |
| OC-R | [OVE-194](https://linear.app/overtonbell/issue/OVE-194): parent, related to OVE-162 | None | children |
| R0 | [OVE-195](https://linear.app/overtonbell/issue/OVE-195): freeze the resolution interfaces, refusal codes and conformance fixtures (Todo) | None | R1, R5 |
| R1 | [OVE-196](https://linear.app/overtonbell/issue/OVE-196): the resolver and the three registries; Deep Agents lane package owns its compile adapter | OVE-195 | R2, R3, R4, R6 |
| R2 | [OVE-197](https://linear.app/overtonbell/issue/OVE-197): one sealed lane binding slot replaces the three typed slots | OVE-196 | OVE-164, OVE-166 |
| R3 | [OVE-202](https://linear.app/overtonbell/issue/OVE-202): mechanical relocation of the other lanes; compile conformance for Deep Agents | OVE-196 | OVE-186 |
| R4 | [OVE-198](https://linear.app/overtonbell/issue/OVE-198): Application Profile as data; the knowledge gateway stops branching on application | OVE-196 | OVE-165, OVE-168 |
| R5 | [OVE-199](https://linear.app/overtonbell/issue/OVE-199): Knowledge Services backend registry, bindings export their backend, backend conformance suite | OVE-195 | OVE-165, OVE-167 |
| R6 | [OVE-200](https://linear.app/overtonbell/issue/OVE-200): Model Catalog as files, model routes on the describe, coordinator-facing model listing | OVE-196 | OVE-169 |
| R7 | [OVE-201](https://linear.app/overtonbell/issue/OVE-201): independent review of R1 to R6; OKF, glossary and operator documentation | OVE-196 to OVE-200, OVE-202 | OVE-168 |

## Reuse and scope boundaries

OVE-75 supplies continuation machinery to WI-18; OVE-78 supplies subscriptions to WI-19; OVE-73
supplies the existing human-gate seam to W5. Existing OVE-69/77 dependencies remain. Sprint V
OVE-151/152/153/154/155/156/157/158 provide reviewed source seams; their current In Review states are
not silently changed. W0 verifies the actual install/service readiness needed here. OVE-160's temporary
collection refusal is replaced by WI-07, and OVE-161's file-byte guard is subsumed by WI-02's complete
budget/readiness proof. Existing issue bodies/statuses remain intact.

Do not block this sprint on all of OVE-150: its downstream SV-18 gate is completed by WI-21. No
duplicate baseline engine is introduced. WI-20 and specialized automatic code integration are
unselected; no tickets were filed for them. Cross-application links and new computation caching are
outside adopted scope. Required migrations and disposable-target cutovers belong to delivering issues.

## Preparation verification

The tracker was read before publication (bodies/comments/native directions), then all 32 published
issues and 56 blocker relations were read back; exact titles, descriptions, labels, project, parentage,
directions, external reuse and acyclic dependencies were checked. OVE-73/75/78/150 bodies/statuses
were preserved. The original four answer records retain their quotes and now carry final destinations.
New runtime evidence remains **unrun**. See PROOFS for required acceptance, and the dated knowledge
log for documentation verification. No runtime code, schema application/reset, paid fixture, commit
or push occurred in this preparation session.

Final preparation checks: `agents_docs_index.py` regenerated the index; `check_docs.py` passed
all seven checks (OKF, generated index, three program ledgers, Markdown links and shipped skills);
`git diff --check` passed. Three independent final reviews passed for workflow/decision/graph,
knowledge/schema/fixtures and provider/coordinator scope. All 181 OC and 14 SV rows, plus 14 DP
and 14 CS dispositions, were counted and checked against the published work map. Linear's Markdown
serializer changed list/table formatting only; normalized content and native relationships matched.
