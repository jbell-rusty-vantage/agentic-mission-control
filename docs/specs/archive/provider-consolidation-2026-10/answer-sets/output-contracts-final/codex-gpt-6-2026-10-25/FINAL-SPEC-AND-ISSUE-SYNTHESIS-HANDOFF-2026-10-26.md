---
type: Session Instruction
title: "GPT 6 Astra Extra High: final specifications and agent-team issues"
description: "Fast-path synthesis instruction aggregating four interview records, revised contracts, actual source/proof limits, disposable-data implementation authority, post-sprint stress fixtures and per-major-commit quality gates."
tags: [mission-control, handoff, specifications, issues, agent-team, fast-path]
date: 2026-10-26
status: ready
---

# Final specification and issue synthesis session

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../../../sessions/KICKOFF.md); no new interview or runtime completion is implied.


**Intended session:** GPT 6 Astra, Extra High reasoning (`xhigh`), selected by the owner when opening
the session. This document does not create a chat or change its model. The resulting implementation
packet must work for an agent team in **Codex or Claude Code**, without assuming either harness.

**Mission:** explore the current code and evidence, reason across every interview, coalesce the
accepted system into final specifications, publish the actual issues, and leave an immediately
usable implementation-team packet. Finish the conversion. Do not restart the interview, merely
summarize the answers, or stop with an offer to write the issues later.

## 1. Latest owner direction controls

Read [the complete owner message and stress fixtures](OWNER-DIRECTION-AND-STRESS-FIXTURES-2026-10-26.md)
first. It supersedes older “resume interviewing” instructions. The owner has now supplied three
**post-sprint** stress missions. Concrete W0–W5 fixture authoring still follows its accepted checkpoint
criteria; it does not block specification/issue preparation or permit substituting these later missions.

The owner wants a direct path to high-quality coordinator-agent + Mission Control + Knowledge
Services functionality. There are no real users and no production automations. Existing experimental
data and historical runtime records are disposable. Design issues that let agents replace obsolete
files, imports, implementations, schemas and behavior; include migrations and clean rebuilds where
needed. Do not invent a production compatibility program, old-data rescue, alias layer, dual writer,
deprecation period or incremental migration ceremony merely to preserve the existing system.

Necessary changes across MC, shared KS, AI Engineer SQL and Biotech graph belong in this work.
Do not force the functionality around an inadequate schema. Remove stale tests/docs that enforce
retired behavior and replace them with the accepted contract's evidence. Preserve the source
interviews and unrelated user work. Exactness, authority, evidence and recovery in the **new** runtime
remain functional requirements; disposable old data does not waive them.

Scope this session to specifications, architecture/ADRs, documentation, real tracker conversion and
the team handoff. Runtime coding, database reset/application and paid fixture execution are the
implementation team's next phase. The owner asked for this preparation session; do not execute the
three missions while writing their issues.

## 2. Workspace and reading sequence

Workspace: `C:/Users/Pinda/Proyectos/BellLabs`.
Primary owner: `C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control`.
Start with workspace AGENTS, `docs/navigation/SERVICE-INVENTORY.md`, `docs/navigation/RETRIEVAL.md`,
`docs/navigation/WORKTREES.md`, `platform/AGENTS.md`, MC AGENTS and docs/AGENTS. Navigation inventories
contain dated snapshots: inspect live Git/worktree state and the current owning sources.

The [verified source map](INTERVIEW-SOURCE-MAP-2026-10-26.md) gives exact locations and roles for all
four `ANSWERS.md` files, every derivative in their answer directories, the relevant program documents,
canonical destinations, runtime findings, local issue drafts, tracker state and verification commands.
Use it as the retrieval index; do not recursively reread the entire workspace.

Required reading order:

1. Latest owner direction above; current [ANSWERS](ANSWERS.md), especially OC-D106–181 and assumptions.
2. IA-06 OC-D27–78, IA-07 OC-D79–105 and IA-08 SV-D1–14 in full. Read the exact quotes, not only an
   assistant summary. The source map links each and distinguishes historical status.
3. Current [CONTRACTS](CONTRACTS.md), starting §§1–5, 11–15, then 16–17;
   [WORK-ITEMS](WORK-ITEMS.md) and [DESIGN-DECISIONS](DESIGN-DECISIONS.md).
4. Earlier contract/transfer/architecture derivatives; resolve deltas rather than concatenate them.
   Read original OC/DP/CS decisions through the current disposition tables.
5. Sprint V source/proof baseline, readiness audit/repairs and RV-01–08, plus relevant current code
   and tests in all four owning repositories. Read actual evidence before preserving a “done” claim.
6. Canonical spec/workflow annexes and ADRs that final target decisions amend. Keep target requirements,
   source implementation and actual installed/qualified evidence visibly separate.

Use research subagents for bounded parallel ownership audits if helpful. A good split is workflow/
contracts, KS/native schemas, and provider/coordinator/fixtures/quality. One integrator owns the final
model and issue graph. Subagents return cited findings and conflicts, not competing versions or
parallel owner interviews. The final packet cannot depend on private chat memory.

## 3. Decision precedence and unfinished interview accounting

Latest explicit owner direction → later recorded owner decisions → retained earlier accepted decisions.
Reconcile their intended changes into canonical specs/ADRs. Implementation defaults and proposed
alternatives are not owner answers. Canonical source authority determines current behavior; it does
not forbid the owner-directed target amendments you are preparing.

At transfer: OC-D1–176 are recorded across the mapped sources; OC-D177–181 capture this latest mandate.
IA-09 remains open because final conversion is unfinished. The capped round asked 17 questions,
received 15 answers, skipped F20-04/15, and did not ask F20-20. These two choices lack direct answers:

- Q16 / F20-18: specialized automatic branch-merge/test/conflict-resolution engine. Generic typed
  code-change outputs, ordinary execution and repository checks are already included.
- Q17 / F20-19: integrated preflight/revision-impact preview extending existing preflight. Focused
  effective-configuration, input/output/receipt inspection is already included; WI-20 is conditional.

Do not fabricate those answers or claim F20-20 was accepted. The new instruction is to finish
synthesis and issues efficiently. Build the mandatory packet from adopted requirements; unselected
extra engines/previews need not block it and must not silently become mandatory implementation.
Record a clear disposition for each, including whether an already-required inspection needs a
particular integration as an engineering choice. Keep any genuinely additional product option out
of ready-to-implement mandatory scope unless the owner supplies a decision. Do not reopen settled
questions or request a generic permission round merely to publish the requested specs/issues.

The final owner fixture message is **new steering**, not blanket acceptance of every existing draft.
You may improve the architecture, issue granularity and dependency graph by reasoning from the
accepted functionality. Label engineering choices as such and explain consequential tradeoffs.

## 4. Non-negotiable functional spine

The final specification must present one coherent author → admitted configuration → execution →
submission → assessment/fulfillment → receiving-context → acceptance model across these areas:

- **Common authoring:** general output forms with pinned/inline substantive contracts; explicit
  named obligations, required/expected/optional enforcement, distinct identity/cardinality/coverage,
  evaluation scope and closed completion expressions. Extend existing EffectiveRunConfiguration.
- **Submission and settlement:** one progressive/final `submit_output` protocol, with a qualified
  degraded declared-file route through the same module; no final-message/output_refs authority.
  Separate submissions/revisions, independent assessments, current accepted sets, fulfillment and
  invocation finalization. Retain completed cognition across review/effect waits.
- **KS/domain boundary:** MC owns orchestration; shared KS owns reusable report/evidence/verification/
  permitted-use/native-operation semantics; AIDB owns native SQL, BKS owns authored SDL/native graph
  execution. Authenticate origin before sealing. Preserve producer/caller/receipt/revision/adopter/
  assessor/consumer roles, exact native commit and required readback/reconciliation.
- **One transfer authority:** exact selected outputs/revisions/current sets feed one sealed plan;
  prompt, sandbox and retrieval follow it with attempt-specific receipts. Host state stays mandatory.
  Validate actual receiving backend access, use/purpose and aggregate context/file/resources. History
  is bounded opt-in. Do not replace required bytes with an unqualified path or summary.
- **Stage Graph:** explicit all-matching or ordered first-match condition mode; unknown is not false;
  exact named all/any/quorum groups and optional omissions; independently required coverage remains.
  Later results cannot mutate a running plan; graph surplus continues unless cancellation is selected.
- **Goal Loop:** whole current accepted set, retained successes, selected repair work and required
  continuing-profile progress notes; goal-scoped waits permit independent work without accepting the
  blocked goal. Nested Goal Loops/subgraphs execute recursively with explicit exports, not flattening.
- **Swarm and EO:** implement actual family control and context semantics. Swarm all/quorum/best-effort,
  isolated members, convergence and its surplus-cancel default differ from Graph. EO has independent
  producer/evaluator identity, exact rounds/findings and bounded repair; hard gates remain hard.
- **Large work:** typed standard/custom deterministic transforms, explicit join population, exact
  partition membership/coverage, durable inventory and bounded activation windows, group-closure
  witnesses, typed conflicts, qualified deterministic trees and explicit semantic preservation/
  cross-partition coverage. Coordinator or admitted agentic steps propose governed successors.
- **Evolution and links:** independently eligible early exports versus final composite acceptance;
  exact same-application links and explicit adoption; purpose-scoped held/draft repair/review;
  running chain consumer continuation unless propagation is selected; spawned cancel and attached
  detach remain separate. Include the two scoped synthesis reassessment cases without inventing a
  general freshness engine.
- **Hooks/context:** bounded durable-transition reactions through ordinary admitted executions;
  scoped reads, staged candidates and host validation/installation; model/external effects as normal
  operations. Consume bounded preservation proposals at compaction. Preserve distinct continuation
  and exact historical repair-fork inputs. No second scheduler or automatic authoritative memory.
- **Coordinator:** focused operational inspection, controls and durable actionable attention; selected
  bounded content only when configured. Prove notice, transport, actual selected-host wake,
  model-visible delivery, acknowledgment and content retrieval separately.

Cross-application linking is **unadopted**, not deferred delivery. New automatic computation caching
is excluded. Pressure-aware scheduling is undecided pending the dedicated deployment worker's local
evidence; existing ceilings/fairness/windows remain required. Broad surface redesign and unrelated
refactoring do not become prerequisites merely because this is a clean implementation mandate.

## 5. Checkpoints, then three stress missions, then full product architecture

Preserve OC-D106/107/128–131 and CONTRACTS §§11–11.2:

| Phase | What must happen |
| --- | --- |
| W0 | Four-owner schema fit, trusted interfaces, exact evaluator isolation, durable settlement and first-use prerequisites. |
| W1 | First real ordinary GoalDirected report and independent assessment/settlement, with applicable native-write variant. |
| W2 | Exact producer-output → consumer delivery, actual backend readiness and aggregate budgets. |
| W3 | Collections, current sets, accumulation/synthesis, transformations and bounded inventory. |
| W4 | Revisions/reassessment, review, adoption, linked workflows and advanced recovery. Basic durability is not postponed until here. |
| W5 | Remaining workflow/composition/control boundaries, all four families, full Deep Agents qualification and both applications. |
| **After this sprint/checkpoints** | F1 Generation Lab GoalDirected discovery; F2 Qualia Life Biotech graph; F3 model/benchmark ingestion and AI Engineer retrieval/ranking/routing. Explicit mission-work evaluation and feedback loops begin in this stress phase. |
| **After those stress fixtures** | Fully architect AI Engineer education content/features and Biotech knowledge/recommendation services, informed by findings. Experimental content need not survive into the final products. |

The full [owner fixture contracts](OWNER-DIRECTION-AND-STRESS-FIXTURES-2026-10-26.md#4-stress-fixture-contracts--owner-requirements-and-engineering-completion-criteria)
must become separate concrete work and proof plans. Do not substitute them for the existing earlier
checkpoints or prematurely design the final product services as a dependency of these experiments.

F1 requires exhaustive test/biomarker discovery, reports and ingestion intents, all Tavily and all
Firecrawl skills plus Vercel browser, a general helper and an asynchronous interactive browser helper;
native Biotech ingestion is not required. F2 requires every current product, all ingredients,
per-product foundational reports, three of the most important qualifying connected studies/trials and actual KS evidence
verification/provenance, with capabilities/contracts distributed per stage. F3 requires up to 50
models, preferably 2025–2026, actual entity/relationship ingestion and database-grounded multidimensional
model selection/routing experiments. Keep these exact differences.

Treat these missions as system stressors. Discover and ticket capability, schema, output/context,
subagent, retrieval or evaluation gaps needed to run them. Do not reduce the mission to fit today's
API. Evaluation must inspect mission outcomes, not merely that tools returned successfully: coverage,
evidence quality, output usefulness, retrieval/ranking, agent behavior, cost/latency and recovery.
Define independent evaluation, failure classification, owning-layer fixes, versioned reruns and
regression cases. Do not presume the report's own producer is an adequate independent evaluator.

Existing provider spend guidance is in PROCESS (15 USD per session unless superseded). This handoff
does not choose a new stress-fixture budget or grant unlimited looping. Author bounded operating
limits for execution; unfinished exhaustive work remains resumable/blocked with truthful gaps rather
than being accepted as complete. Preserve the requested task objective.

## 6. What to produce in this synthesis session

Produce a small, navigable final pack rather than another layer of overlapping drafts:

1. **Final specification and architecture projection:** one source of target behavior, typed public
   and internal contracts, schema ownership, lifecycle/state/recovery rules, exact context paths and
   all-family worked cases. Use existing modules where suitable; replace inadequate ones directly.
   Name removals/cutovers, required migrations, projections/types and release/install proof.
2. **Decision reconciliation:** map every owner decision to the final section/ADR/work item, preserve
   revisions and explicitly dispose of obsolete OC/DP/CS recommendations. Resolve the seven older
   ADR candidates into the existing five proposed groups or a better justified arrangement; allocate
   actual canonical numbers only after rechecking. Update glossary/spec annexes without claiming code
   exists. Do not silently promote still-proposed unrelated ADRs.
3. **Implementation plan and team workspace:** vertical slices, real blockers, owner repository and
   module boundaries, parallel frontiers, shared-contract integration owner, claims/handoffs and
   independent review. State migrations/code changes/checkpoint runs as required work, not optional
   follow-ups needing routine reapproval. Make each slice independently reviewable in a fresh context.
4. **Proof and evaluation matrix:** W0–W5, RV-01–08 before first use, eight-form conformance, both
   applications, all workflow families, full Deep Agents capabilities, actual coordinator host and
   real backend/native proof. Then separate post-sprint F1/F2/F3 plus mission-work evaluation and
   feedback-loop issues. Mark what is real versus doubled and how missing evidence blocks a claim.
5. **Published Linear specification and issues:** read existing cards/comments/relationships; refine
   and de-duplicate local drafts, create actual issues with native blockers and provenance, then read
   back identifiers/relationships. Do not stop at Markdown drafts or report imaginary IDs.
6. **Updated documentation and handoff:** canonical amendments, answer Becomes/Folded destinations,
   ledger and downstream entrypoint, final checks, tracker map and a concise launch instruction for
   the implementation integrator in either Codex or Claude Code.

The 22 existing WI drafts are a head start, not an approved fixed decomposition or ceiling. They
predate the latest fixture/evaluation/quality mandate. Merge/split as needed; add missing prerequisite,
fixture and evaluation work. A special schema-only backlog must not let runtime work evade necessary
migrations; assign each invariant and its native proof to a concrete delivering slice.

Use a short per-issue shape: problem/observable result; owning repos and interfaces; explicit removal/
schema/cutover scope; real blocking issues; acceptance/negative/recovery proof; quality/docs done
definition; relevant decisions/provenance. Avoid long repeated policy boilerplate or tickets that
only say “investigate” when source inspection can settle the implementation now.

## 7. Agent-team execution contract to embed in the issues

One integrator maintains the dependency graph, shared protocol shapes, claims and final integration.
Implementers claim bounded repository/path scope and work on the ready frontier. Coordinate shared
files instead of serializing independent work. Use an integration branch for inseparable cutovers
when that is the fastest way to a coherent green system. Do not preserve obsolete behavior just to
keep every intermediate commit independently shippable.

Each assignment supplies the goal, contracts/decision sources, checkout/base, writable scope,
blockers, expected migrations, verification commands and required evidence. The agent is authorized
to make ordinary necessary code/schema/import/file changes within that assignment and the owner's
disposable-data direction. Escalate actual missing authority, credentials, contradictory product
goals or unavailable external prerequisites, not routine engineering choices.

At each major commit/integration milestone, run clean-code/spec review and update semantic docs:
AGENTS navigation, affected OKF concepts/logs, schema/workspace/API docs, glossary/ADRs/operator guides
and program progress as applicable. Use the owning generator, not hand edits to generated indexes.
The [source map §7](INTERVIEW-SOURCE-MAP-2026-10-26.md#7-verified-quality-entrypoints) gives verified
commands. Fix findings and run affected checks again before calling the milestone complete.

A turn-end automation may assist, but it is not the required gate. No universal quality configuration
was found in the four repos. Use direct review agents if automation is absent; do not turn framework
installation into a prerequisite for working functionality. A reviewer other than the implementer
assesses functional checkpoint evidence. The coordinator advances only when all required criteria
pass, with fixes/reruns linked. A passing functional gate does not grant unrelated KS use authority.

## 8. Tracker conversion and completion

Use the existing **overtonbell / OVE / Mission Control** project. The source map lists known cards
and the working GraphQL fallback. Reuse baseline issues OVE-75/78 and relevant Sprint V seams; add
distinct new behavior instead of duplicating callback/continuation engines. Preserve existing parent
bodies/statuses and unrelated work. Do not block the new sprint on all of OVE-150: its downstream
SV-18 release depends on this work and would create a cycle.

Read exact current scopes, native incoming/outgoing blockers and comments before changes. Apply the
repository category/state labels and provenance. Publish blockers before dependents. Distinguish
mandatory work from genuinely unselected options. Record actual IDs in the work matrix and answer
destinations. If access truly fails, retain exact publication-ready drafts and the actual blocker;
do not claim conversion complete. Prior read-only access worked.

Completion means the final pack is internally consistent, required canonical amendments and ADR
dispositions are made, every accepted requirement has a concrete work/proof destination, actual
issues and native edges are verified, documentation checks pass, and an implementation team can
begin the ready frontier without another planning interview. IA-09 becomes final only when its
required conversion is genuinely complete; unresolved optional choices retain an honest disposition.

For this repository run `python docs/tools/agents_docs_index.py`,
`python docs/tools/check_docs.py` and `git diff --check` after the document changes. Use the local
`.venv/Scripts/python.exe` when appropriate. Do not run runtime suites to imply behavior was built
by this specification session. End with final pack paths, actual issue links, next ready work and
any concrete unresolved external constraint. Keep the final report direct.
