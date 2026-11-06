---
type: Specification
title: "IQ-07 work items, dependencies and proof gates"
description: "Draft vertical implementation slices for the accepted workflow/output/context version, with schema owners, existing issue mapping and real functional qualification gates."
tags: [mission-control, work-items, dependencies, qualification, contracts]
date: 2026-10-26
status: draft
---

# Work items and proof gates

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../../../sessions/KICKOFF.md); no new interview or runtime completion is implied.


**Latest direction, OC-D177–181:** this 22-slice matrix is an input to the
[final synthesis session](FINAL-SPEC-AND-ISSUE-SYNTHESIS-HANDOFF-2026-10-26.md), not a frozen issue count.
Fold the direct replacement/disposable-data posture, per-major-commit quality, and separate post-sprint
F1/F2/F3 plus mission-work evaluation/feedback loops into the final work. Existing W0–W5 stays first.
The owner now requests synthesis/publication rather than another automatic interview/approval round.

This is a **draft for final integrated confirmation**, not implementation authorization or tracker
completion. The [contract](CONTRACTS.md) and [exact answers](ANSWERS.md) govern scope.
The current question count and unresolved candidates are in the [instrument](FINAL-INTERVIEW-20-QUESTIONS-2026-10-26.md).
No new issue identifiers are invented here. Final publication follows the owner's integrated confirmation.

## 1. Delivery model and ownership

Deliver vertical slices through authoring, durable records, execution, inspection and proof.
Each slice owns the schema changes needed for its behavior; there is no detached schema-only phase
that allows behavior to work around a missing invariant. Necessary scoped refactors are included;
a broad module reorganization is excluded.

| Authority | Responsibility in every affected slice |
| --- | --- |
| MC runtime/common SQL | Effective configuration, admission/lifecycle, obligations/submissions/fulfillment, exact transfer/delivery, waits/governors, events and effect coordination. |
| Shared KS/operational component | Reusable knowledge/report/evidence/verification/use semantics, trusted semantic ingress/sealing/review and native-operation protocol. |
| AI Engineer DB contract | Authored application SQL and native projections; consume versioned schema changes through its owner. |
| Biotech KS | Authored graph SDL and admitted native read/plan/apply, commit/lineage/readback; no duplicate shared verification authority. |
| Provider lane | Actual bounded cognition/tool/backend materialization and provider qualification; stop is not acceptance or permission for effects. |

Every slice records a **four-owner schema-fit row**: required invariant; existing representation;
change or justified no-change; migration/release/types/projections; actual disposable-installation
proof and reviewer. Source inventory is not live installation evidence. Do not reserve future release
numbers. The user supplies real fixtures after the interview.

## 2. Proposed vertical slices

IDs are local planning keys. “Blocked by” names whole-slice dependencies; conditional use gates
are explicit in the proof/checkpoint sections and must be enforced before the relevant behavior runs.
There are no circular dependencies. Independent work may overlap. A use gate does not prevent a
generic slice completing with protected behavior visibly refused until its authority is available.
W0 establishes shared mechanisms; W1–W5 qualify successively broader real mission cases, so a W2
functional transfer proof is not a hidden prerequisite for W1's initial evaluator isolation.

| ID / earliest wave | Observable result and primary module owner | Blocked by | Schema focus and done evidence | Decisions / issue disposition |
| --- | --- | --- | --- | --- |
| WI-01 / W0 | Author and compile exact named output promises, enforcement, coverage and explicit completion; inspect pinned effective configuration. MC authoring/compiler/contracts. | Reviewed Sprint V prerequisite inventory | MC obligation/revision identity and completion witnesses. Compile → persist → ordinary launch of a bounded non-knowledge output; missing required blocks, expected shortfall stays visible, optional absence follows policy. Last-stage success cannot satisfy unrelated goals. | OC-D114/115/118/123/162/163; new runtime contract slice, related to OVE-151/152/158. |
| WI-02 / Mechanisms W0; broader proof W2 | Deliver exact selected initial/dependent/reviewer inputs through one plan to prompt, files and handles, with attempt receipts and aggregate budgets. MC context/materializer plus KS exact-read port. | WI-01 | MC plan/receipt identity; KS custody/read representation. Demonstrate generic delivery and evaluator isolation, wrong slot/sibling/generation exclusion, denied backend read, corrupt/missing bytes and combined-budget refusal; replay preserves pins. Missing protected-use authority refuses. Protected success is WI-03/21 evidence, not a completion prerequisite for this slice. | OC-D116/119/122–124; RV-03/05. New expansion beyond OVE-161's bounded byte guard. |
| WI-03 / W0–W1 | Ordinary independent Deep Agents judgments reach trusted KS sealing/use/review decisions and resumable MC waits. MC knowledge bridge + shared KS research/host, both native bindings. | WI-01, WI-02 | KS exact assessment/use/reviewer successors, MC durable wait binding, native current-use projections. No test-populated decision cache; unavailable evaluator blocks, ungrounded disagreement holds, unauthorized review/revoked official use refuse, permitted repair read remains possible. Judgment approval never becomes fact entailment. | OC-D108–113/121; RV-04/08. Reuse Sprint V services; new missing composition/qualification only. |
| WI-04 / W0–W1 | Retain completed provider result through assessment/effect waits and settle without repeated cognition. MC output/Deep Agents/Temporal/reducer path. | WI-01 | MC saved result, finalization and durable reconciliation ownership. Crash after completion, late acknowledgment, cancellation and restart produce one logical execution result and truthful settlement without cognition redispatch. Use controlled durable waits for this seam; WI-03 proves actual KS resolution and WI-05 proves native no-duplicate-application. | OC-D109/114/127; RV-01. New repair slice. |
| WI-05 / Before first native-write claim | Recover committed native effects whose protocol receipt was not acknowledged. Shared KS protocol + AIDB/BKS native binding, MC wait bridge. | WI-03, WI-04 | Native effect key/commit marker and protocol receipt/readback. Fault after native commit, restart/reconcile exact result, prove no duplicate application and required readback in both domains. | OC-D79/85/89/99/101/117; RV-06. Extend existing port evidence; do not rebuild Sprint V wholesale. |
| WI-06 / W1 | Complete the first ordinary GoalDirected report with explicit fulfillment, trusted use, required progress note and restart-safe controls. MC GoalDirected/Deep Agents + KS report pipeline. | WI-01–04 | Goal/iteration/accepted-result links and note attribution; four-owner fit reviewed. Owner's actual report fixture through ordinary launch, retained Transcript/output/receipt evidence and independent functional review. WI-05 gates any native write promised by the fixture. | OC-D106–130/133/137; first W1 functional checkpoint. New scoped integration/qualification slice. |
| WI-07 / W3 | Assess report collections per member and maintain exact current accepted heads/coverage across Goal Loop iterations. MC outputs/sets/GoalDirected + KS assessment bindings. | WI-01–04, WI-06 | Set/frontier/accepted-head/fulfillment records. Mixed held/accepted results, duplicate identities, competing revisions, missing members, concurrent promotion and restart. Verifier gets the complete required current set; revision is not another deliverable. | OC-D114/133/134/152; RV-02. New collection support; OVE-160 stays the historical temporary guard. |
| WI-08 / W2–W3 | Execute explicit conditional modes, unknown waits, any/quorum exact selection and optional omissions. MC compiler/interpreter/Temporal. | WI-01, WI-02 | Predicate/evidence, applicability, branch disposition and sealed selection. Replay overlapping conditions, unknown earlier exclusive branch, explicit else, separately required inputs and late arrivals; unused branch does not silently erase a goal. Collection-dependent cases additionally require WI-07. | OC-D139–148/162; new routing/selection slice. |
| WI-09 / W3 | Run standard and admitted custom typed deterministic transformations, including explicit data-join populations. MC executor catalog/dispatch; KS when a reusable knowledge capability owns the algorithm. | WI-01, WI-02, WI-07 | Exact implementation/schema/input pins and ordinary intent/result receipts. End-to-end union/group/join/partition examples, schema/version drift refusal, duplicate-match conflict and unmatched-population accounting. No new cache. | OC-D151/154/163/170; new dispatcher/library integration. |
| WI-10 / W3–W4 | Schedule exact durable inventory in bounded windows; inspect and replace poor partitions through coordinator or admitted agentic planning. MC inventory/admission/revision/inspection. | WI-07, WI-09 | Frozen members, atomic groups, plan lineage, activation ownership. Restart mid-window without lost/duplicate members; preserve successes; reject out-of-bounds successor; refuse indivisible item with no viable realization. | OC-D148/152/153/168. Worker-evidence review for OC-D169 belongs here; pressure policy is not adopted. |
| WI-11 / W3–W5 | Release independently closed groups, retain uncontested results/conflicts, and qualify deterministic trees and semantic decomposition. MC closure/coverage/reduction plus KS/domain assessment. | WI-07, WI-09, WI-10 | Contributor closure witnesses, exact derivation and preservation/coverage terms. Missing/late contributor, cross-partition dependency, rare evidence and order-sensitive reduction probes; no semantic-completeness claim from item count alone. | OC-D154–156/164; new bounded reduction slice. |
| WI-12 / W4 | Reassess synthesis after tracked report revision or exact unchanged held-source acceptance under the selected bounded policies. MC revision/readiness + KS assessments/use. | WI-02, WI-03, WI-04, WI-07 | Source/consumer revision pins, historical/current eligibility and reassessment lineage. Running synthesis keeps its sealed inputs; pending arrivals coalesce; unavailable checks block; source acceptance alone never approves derived work. | OC-D142–146; new scoped evolution slice, not general freshness engine. |
| WI-13 / W5, earlier where used | Execute a Goal Loop/subgraph recursively with unchanged external promises and explicit exports. MC hierarchical compiler/runtime/control scopes. | WI-01, WI-02, WI-04, WI-06, WI-07, WI-08 | Nested activation/governor/output projection identity. Actual nested execution, not flattening warning; restart/control propagation; independently eligible export survives incomplete composite without accepting it. | OC-D34/47/119/133/135; new recursive execution slice. |
| WI-14 / W5 | Execute Swarm members and convergence with distinct all/quorum/best-effort and surplus-cancellation semantics. MC Swarm runtime plus admitted convergence operations. | WI-07, WI-09, WI-13 | Member/selected-set/convergence/governor lineage. Real unequal member results, isolated member context, quorum without false coverage, convergence failure, late results and bounded cancellation/restart. Use WI-11 before any qualified reduction-tree claim. | Existing canonical Swarm + accepted common protocol; new runtime family/qualification. |
| WI-15 / W5 | Execute independent Evaluator Optimizer production, findings-directed repair and bounded reassessment. MC optimizer runtime + KS judge/use semantics. | WI-03, WI-04, WI-07, WI-13 | Round, candidate, assessment and distinct producer/evaluator identity. Real reject→repair→reassess, stale/unavailable evaluation, no-progress/budget stop and hard-gate preservation. | Canonical EO + OC-D108–113; new runtime family/qualification. |
| WI-16 / W4–W5 | Transfer exact exports between missions within an application, including held repair and changed running-consumer cancellation default. MC chains/linked runs + KS receiving use/read. | WI-01–04, WI-07 | Link policy/export/receiver/explicit-adoption/cancellation lineage. Both apps independently: source acceptance gates, required held repair bytes, launch vs result readiness, cancellation before/after start, revocation and restart. Nested bodies require WI-13. | OC-D165–167; new extension to existing chain code. No cross-application feature. |
| WI-17 / W4–W5 | Give admitted operation hooks scoped reads, staged preparation files and requests for separate ordinary operations. MC hooks/context/effects; KS when requested operations use it. | WI-01, WI-02 | Versioned event capability and read/install/output receipts. Refuse denied reads and attempts to overwrite host state/sealed inputs; race same-path candidates; recheck source/grant before install; recover crash after install before receipt. Files do not self-fulfill; post-effect denial cannot undo effects. WI-03/04/05 gate relevant protected/model/native-effect cases. | OC-D173–175; new hook boundary extension; historical OVE-26 baseline. F20-15 is a consequence. |
| WI-18 / W4–W5 | Consume validated preservation proposals and deliver exact notes/references after compaction or continuation; restore selected historical repair-fork drafts. MC Deep Agents/context/recovery. | WI-02, WI-17; OVE-75 baseline continuation integration for that path | Prove hook results are consumed and accepted content reaches actual post-compaction context. Rejected/over-budget proposals cannot displace mandatory state. Historical fork bytes differ from today's files; required unavailable bytes block. Pending effects remain visible and require WI-05 before native recovery claims. Goal/current-set cases require WI-06/07. Reuse existing continuation phase-machine proof. | OC-D137/138/172; preservation/fork delta beyond OVE-75, not duplicate full continuation implementation. |
| WI-19 / W2 onward–W5 | Add exact output/fulfillment/transfer inspection, qualify actual selected coordinator-host delivery and support configured bounded content. MC inspection/subscriptions + admitted KS retrieval. | WI-02; OVE-78 baseline subscription/delivery implementation | Distinct evidence for durable notice, transport, selected-host resume, model-visible payload, explicit ack and later content read. Unavailable/disconnected/dead-letter states stay actionable. Retain exact revision/status/attribution; recheck purpose/grants/budget; reject denied/oversized content. Each feature supplies its own projection and protected cases require WI-03. | OC-D125/126/176. New focused delta plus additive OVE-78 scope note; preserve its baseline machinery, parent and status. |
| WI-20 / If F20-19 accepted | Extend existing preflight into integrated contract/input/resource/revision-impact inspection. MC compiler/manifest/coordinator launch. | WI-01, WI-02; other features only for their corresponding projections | No separate compilation authority. Pin preview inputs/effective configuration; show static checks vs estimates/unknowns and affected future/in-flight work. No model-success prediction. | **Pending owner answer**; no implementation issue before acceptance. |
| WI-21 / W5 release | Qualify the accepted whole version and complete Deep Agents capability matrix in both applications. MC coordinator/worker/lane + KS/AIDB/BKS. | WI-01–19 and WI-22; WI-20 only if selected; inherited required provider work | Actual owner fixtures, all four workflows/compositions, required real acquisition/ingestion/retrieval, controls, failures/recovery/load envelopes and native/schema proof. Independent reviewer passes every declared criterion, repairs/reruns linked. Routine use remains gated. | OC-D106/107/128–131; downstream SV-18 gate. New release-evidence slice; no invented fixture or proof. |
| WI-22 / W4–W5 | Attach bounded durable-transition reactions and execute them through ordinary admitted operations. MC authoring/Temporal/operation dispatch. | WI-01, WI-04 | Reaction/causal-event/activation identity and ordinary output records. Duplicate delivery yields one logical reaction; crash after admission before dispatch recovers; stale-generation cancellation holds. A reaction producing new matching transitions stops at admitted activation/recursion/budget bounds. WI-17 supplies hook-request entry; WI-03/05 gate protected/native effects. | OC-D171; separate durable-dispatch slice keeps local preparation and preservation independent of transition-reaction delivery. |

The table's module ownership is implemented at the existing seams:
MC `application/authoring`, `domain/authoring`, `domain/programs`, `application/programs`,
`application/outputs`, `application/context`, `application/knowledge`, `application/chains`,
`application/subscriptions`, `adapters/temporal`, `adapters/deep_agents` and common DB component;
KS research/host/protocol/core and native bindings; AIDB migrations/types; BKS authored SDL/executor.
Detailed code paths belong in implementation claims, not a frozen promise of new files.

The planning keys are stable references, not execution order: publish WI-22 before the WI-21 release
gate. For each form, WI-01 supplies admission/submission/fulfillment conformance and the later slice
supplies its substantive behavior. WI-21 checks this complete coverage map:

| Form | Required proof |
| --- | --- |
| text | Exact offered text, contract checks and unmet required/expected/optional outcomes. |
| structured | Declared schema/version and value/coverage validation; rejected shape cannot fulfill. |
| file | Exact custody/digest/availability and actual receiving backend readability (WI-02). |
| reference | Resolved issuer/scope/revision, current access and applicable use authority (WI-02/03). |
| collection | Per-member assessment, distinct identities/current heads, coverage and explicit aggregate policy (WI-07). |
| code_change | Exact repository/base/head or patch, declared checks and scope; no inferred push/merge/deploy authority. This remains regardless of F20-18. |
| effect_receipt | Exact admitted effect, native commit and required readback/recovery (WI-05). |
| control_record | Attributed findings/decision/handoff under its contract; submitting it cannot grant command or reviewer authority (WI-01/03/06/18). |

## 3. Checkpoints and functional proof

| Wave | Required demonstrated capability | Gate and dependencies |
| --- | --- | --- |
| W0 | Fresh installed/source pins, schema fit, trustworthy origin/assessment/review, exact evaluator isolation, saved-result settlement and applicable effect recovery. | Establish each prerequisite before its first use; missing/ambiguous evidence blocks. Reuse Sprint V evidence only at its actual scope. |
| W1 | First ordinary GoalDirected real report, trusted use, progress note and controls. | WI-06 and all applicable prerequisites; real owner fixture, AI Engineer first then Biotech. Native writes require WI-05. |
| W2 | Exact producer-output→consumer transfer, truthful actual backend readiness, aggregate context accounting, focused inspection. | WI-02 plus relevant WI-08/19 behavior; unrelated/stale inputs excluded in real prompt and sandbox. |
| W3 | Collections/current sets, accumulation/synthesis, transformations and bounded inventory. | WI-07–11 as used. Exact member accountability, conflicts/missing coverage and resource bounds are observable. |
| W4 | Revisions/reassessment, linked reuse/repair, governed repartitioning, hooks and recovery. | WI-10/12/16–18/22 as used; basic durability was required earlier, not postponed here. |
| W5 | Remaining families/compositions, full Deep Agents and both-app qualification. | WI-13–22 (WI-20 only if selected) plus inherited capability work. Ordinary research/general use opens only on the accepted full gate. |

Owner fixtures are integrated **after the interview**. They may span waves and be more complex than
illustrations. Each proof record retains exact inputs/outputs, Transcript, plans/receipts, actual
native/schema observations, functional criteria, independent reviewer and repair/rerun lineage.
A different reviewing agent evaluates evidence; the implementation coordinator records release only
when every criterion passes. Human decisions/required owner release are escalated explicitly.
Engineering release does not confer KS permitted-use or scientific-review authority.

Protocol negative proof is mandatory alongside functional proof: wrong selection, missing input,
bad digest, unavailable content, revoked grant/use, duplicate/late event, concurrent head change,
restart at durable boundaries, held/rejected output, cancellation and uncertain native effect.
Numerical load/model/budget targets follow the selected fixtures and worker evidence, not interviewer examples.

## 4. Runtime-gap coverage

| Gap | Required slices / earliest relevant proof |
| --- | --- |
| RV-01 saved provider result and settlement | WI-04 before W1 completion claim. |
| RV-02 collection assessment | WI-07 before collection use; retain OVE-160 bound until replaced with proof. |
| RV-03 exact predecessor/current-generation selection | WI-02 reviewer isolation before W1; dependent transfer before W2. |
| RV-04 trusted semantic/review service composition | WI-03 before ordinary report-use claims. |
| RV-05 unified budgets/backend readiness | WI-02 before applicable receiving invocation; OVE-161 is only file-byte preflight. |
| RV-06 native commit/receipt recovery | WI-05 before the first applicable native-write fixture. |
| RV-07 honest source/build/installed evidence | Every slice/checkpoint, no separate runtime subsystem. |
| RV-08 official-use versus operational read | WI-03/05/16 before protected consumption/native effect; preserve permitted repair reads. |

## 5. Existing tracker reconciliation

Read live on 2026-10-26 through the documented authenticated GraphQL fallback. No mutation occurred.
The complete Mission Control project title index and relevant bodies/comments/relations were read.
OVE-75/78 were additionally checked for incoming native relations and parent: both belong to OVE-63;
OVE-75 is blocked by OVE-65/69 and OVE-78 by OVE-76/77. All relation pages were complete. Preserve
these edges; historical body text alone was not used as proof of current native blockers.
Snapshots are local working evidence under `.scratch/iq07-final-interview/`, not secrets or release proof.

| Existing issue | Observed state / scope | Draft disposition |
| --- | --- | --- |
| OVE-150 | In Progress; Sprint V implementation parent. | Preserve parent and status. Reference prerequisite work and downstream SV-18 gate; do not pretend this new runtime scope is already fully ticketed. |
| OVE-151/152/157/158 | In Review; live origin/common schema/gateway/minimal submission seams. | Reuse source/proof where applicable; reconcile before dependent implementation. Do not duplicate or mark done from this interview. |
| OVE-160 | Backlog; temporary refusal of report collections. | Preserve bounded repair; new WI-07 adds per-member support and retires the limit only with proof. |
| OVE-161 | Backlog; aggregate receiver report-file byte allowance. | Preserve bounded repair; WI-02 adds exact selection, prompt/tool reserves, backend readability and sealed-plan authority. |
| OVE-78 | Backlog; coordinator subscriptions/callbacks, native dependencies and existing parent. | Prefer an additive accepted-scope update/comment and linked new delta only if needed. Do not duplicate its existing callback work or rewrite historical completion claims. |
| OVE-75 | Backlog; continuation/compaction workflow integration. | Preserve baseline work/dependencies; WI-18 adds validated preservation proposals and target-context conformance. |
| OVE-26/30/31/32/38/39/40 | Done, historical hook/context/chain slices. | Reference implemented baseline; the new semantic extensions need new scope/proof. A historical Done card does not prove this version. |

Publish approved scope to existing **overtonbell / OVE / Mission Control**, with Bug or Feature and
ready-for-agent labels, native blocking relations and `## Provenance`. No new tracker project is needed.
A single current-version specification issue can anchor the new slices; existing parent issue bodies
and statuses are preserved. Published identifiers replace local planning keys without fabricating completion.

Exact review drafts exist locally in `.scratch/iq07-final-interview/spec.md` and one file per slice
under `.scratch/iq07-final-interview/issues/`, with `issue-drafts.json` mapping publication order.
There are 22 proposed slices, including conditional WI-20. These drafts are not published issues;
pending answers and final review must be folded before publication. No tracker mutation has occurred.

## 6. Scope dispositions and pending decisions

| Topic | Disposition |
| --- | --- |
| Cross-application linking | Unadopted possibility (OC-D167), not deferred implementation/qualification. No ticket. |
| Autonomous deterministic research repartitioner | Not selected; coordinator or admitted agentic planning proposes the successor (OC-D168). Mechanical transformations remain. |
| Pressure-aware prioritization | Policy decision postponed until the dedicated deployment worker runs locally with evidence (OC-D169). Retain a review point, not an implementation ticket. |
| New automatic computation caching | Excluded (OC-D170); required recovery/idempotency/explicit reuse stay. |
| Generic freshness/invalidation engine | Outside accepted scope; only the two selected synthesis reassessment cases are included. |
| Broad coordinator grammar/bundle/API redesign | Previously deferred under OC-D125; focused inspections/wakes and OC-D176 content delivery remain. |
| Specialized automated code-integration engine | F20-18 pending. Generic code contracts/execution/checks remain regardless. |
| Integrated preflight extension | F20-19 pending; WI-20 is conditional and must not be published without selection. |
| Final version confirmation | F20-20 not yet asked. Complete worked model and ADR/old-decision dispositions first. |
| Real fixtures | Owner supplies after the interview; no invented functional qualification. |

Full per-slot accounting remains in the instrument. F20-04 and F20-15 are skipped as settled or
consequences of accepted paths; neither creates a new answer or consumes a question.

## 7. New downstream work to add at final synthesis

OC-D178/179 supplies the actual [stress-fixture goals](OWNER-DIRECTION-AND-STRESS-FIXTURES-2026-10-26.md).
After this sprint's checkpoint/release gate, plan distinct work for Generation Lab exhaustive
GoalDirected discovery and report/intents; Qualia Life per-product/ingredient/study Stage Graph with
verified provenance; AI model/benchmark ingestion plus use-case retrieval/ranking/routing; and shared
mission-work evaluation, feedback, owning-layer repairs and versioned reruns. Wire prerequisite
browser/skills/MCP/native/evaluation gaps to the appropriate implementation slice or a new concrete
one. Do not weaken the tasks to match today's capability inventory.

These are not replacements for W0–W5 and are not evidence that WI-21 has passed. Full AI Engineer
education and Biotech knowledge/recommendation product architecture follows the stress phase.
Add clean-code and affected AGENTS/OKF/documentation verification at every major commit/milestone,
using the actual repository mechanisms. No compatibility/data-rescue work is needed for disposable
experimental history merely to preserve old behavior. Existing drafts under .scratch predate these
new requirements and must be revised before publication.
