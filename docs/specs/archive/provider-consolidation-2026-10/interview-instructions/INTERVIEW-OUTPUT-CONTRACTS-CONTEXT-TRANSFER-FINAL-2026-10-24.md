---
type: Interview Instruction
title: "Final output-contract and context-transfer interview: close the design on the Sprint V baseline and settle the issue breakdown"
description: "The last interview of the output-contract/context-transfer thread. It runs after Sprint V (verification, ingestion, reports, the port) and reconciles the accepted checkpoint (OC-D27..78), the prerequisite answers (OC-D79..105), the Sprint V answers (SV-D) and what Sprint V actually built into the complete contract and workflow design, then settles the implementation issues for the output/transfer runtime sprint."
tags: [mission-control, interview, output-contracts, context-transfer, final]
date: 2026-10-24
prepared_by_model: "Claude Fable 5.1"
prerequisite_checkpoint: answers/gpt-6-astra-2026-10-24/ANSWERS.md
prerequisite_answers: answers/application-knowledge-boundary/claude-fable-5-1-2026-10-24/ANSWERS.md
prerequisite_sprint: SPRINT-V-PLAN.md
status: archived
archived: 2026-11-02
archived_from: INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md
archived_reason: "interview held and converted (AS-D25)"
---

> **Archived 2026-11-02** (interview held and converted (AS-D25)). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Final output-contract and context-transfer interview

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../sessions/KICKOFF.md); no new interview or runtime completion is implied.


**Current direction, 2026-10-26, OC-D177–181:** proceed to the owner-requested
[GPT 6 Astra Extra High synthesis handoff](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/FINAL-SPEC-AND-ISSUE-SYNTHESIS-HANDOFF-2026-10-26.md).
It maps all four answer records and derivatives, direct replacement/migration scope, per-major-commit
quality, three stress missions after W0–W5, mission-work evaluation and subsequent full product
architecture. Earlier questioning instructions below are history; unasked/unanswered choices are
recorded honestly rather than treated as acceptance.

## 1. Purpose and place in the sequence

Written on **2026-10-24** at the owner's request, after the prerequisite application-knowledge-boundary
interview closed (OC-D105). It runs **after Sprint V** ([IQ-06](INTERVIEW-SPRINT-V-VERIFICATION-INGESTION-PORT-2026-10-24.md))
so that it reads the system as built, not as projected: origin bound at the service, `submit_output`,
qualified handles, the report core, the migrations A0/A/B/D and the Knowledge Services protocol.

Owner's framing of what follows it (OC-D102): "After this then we can reliably begin the advanced output
contract , the accumulation of them and context transfer ."

Order:

1. IA-06 accepted checkpoint; IA-07 prerequisite answers; IA-08 Sprint V answers and `SPRINT-V-PLAN.md`.
2. Sprint V checkpoint reviewed; its evidence, defects and unfinished service seams explicitly recorded.
3. **This interview (IQ-07):** close every open frontier item, revise where Sprint V taught otherwise,
   and settle the issue breakdown.
4. File the output/transfer runtime issues; run that sprint.

Decision numbering continues in the `OC-D` family after the last verified id (OC-D105 at preparation
time; recheck). A revision of an earlier OC-D keeps the original quote and is recorded as a new row
linked to it. Question ids are `FC-Q1..`.

### 1.1 Entry gate clarified 2026-10-25

Read the [independent readiness review](../sprint-v/ADVERSARIAL-READINESS-2026-10-25.md) first, then
[the corrected as-built briefing](../sprint-v/IQ-07-BRIEFING.md) and
[the continuation's evidence and limits](../sprint-v/NEXT-SESSION.md#2-what-is-proven-and-what-is-not).
The four reviewed commits are MC `fa1f778a`, KS `b45adf5`, AIDB `306efd7`, BKS `c398177`.
Current source releases are MC **1.6.0**, KS **2.4.0**, BKS SDL **2.2.0**, AIDB contract **0.5.0**
with migration head **20261025010200**. They are not deployment claims.

**The interview is ready; runtime qualification is not.** The new review reproduced ignored blocked
finalization, first-report-only assessment of multi-report submissions, run-wide input delivery and
a per-report rather than aggregate byte ceiling. It also found no production writer for MC's decision
store and no complete composed trusted judge/seal/decision/review route. Start by presenting RV-01..06
and RV-08 as evidence, not by asking the owner to rediscover bugs or ratify them as intended semantics.
The earlier “all seams met” assessment must be read with these corrections.

Both native bindings have useful component/service evidence; neither is waived or deferred. IQ-07
must name the repair wave and proof required before each fixture, rather than claim Sprint V already
delivered a complete ordinary-agent path. Advanced obligations and complete transfer semantics are
the design subject of this interview, not prerequisites that must be implemented to ask its questions.
No work-item/tracker completion state is changed by this preparation. The real-work gate remains
closed until all four workflows and Deep Agents are qualified in both domains (SV-D12).

### 1.2 Owner framing for this sitting (2026-10-25)

The owner asks for progressively harder disposable fixtures: one goal-directed workflow producing one
report, then a short StageGraph, then several reports and synthesis. Deep Agents is the first lane;
codebase-commit fixtures are outside this first sequence. Functionality takes priority over the later
global simplification of code, skills and coordinator search/selection. Schema changes are expected
at every wave. This does **not** defer a high-quality first version of prompt materialization.

Keep two questions separate: what the first invocation needs, and what each dependent invocation
needs. A coordinator authors/launches/observes MC through its interfaces; Temporal owns durable
scheduling. Workflow agents perform bounded tasks. Shared KS owns reusable research verification,
reports and use-decision mechanics; AI Engineer and BKS retain their native content/schema authority.
The two app bindings are not two competing verification engines.

### 1.3 Mandatory fixture and repair checkpoints (owner directive, 2026-10-25)

Opening decisions [OC-D106/107](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md)
require explicit stops to run real fixtures, analyze the Mission Transcript against functional goals,
and repair failures at every necessary layer, including database migrations and code. The resulting
CONTRACTS/WORK-ITEMS pack must put those gates into the implementation sequence, with evidence and
repair/rerun criteria; feature implementation alone does not pass a checkpoint.

The owner will supply the exact AI engineering/company and biotech science/company fixtures **after
the interview**. Record their integration as a required next step; do not invent replacements and call
them the owner's fixtures. FC-Q13/21 settle placement and acceptance. FC-Q21 must explicitly reconcile
the intended fixture execution with SV-D12; this opening directive is not recorded as a silent waiver
of the existing real-work gate. No fixtures are run during this interview opening.

### 1.4 First semantic execution host (OC-D108)

Accepted 2026-10-25 in [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md):
separate MC-hosted Deep Agents judge/auditor operations, with KS owning evidence sealing and use
decisions. This selects the first composition permitted by OC-D98. Independent evaluator identities,
pinned inputs/methods and authenticated KS observation ingress are required. Temporal remains the
scheduler; the producing agent cannot act as its own independent evaluator. KS provider hosting is
not required for this first composition. Subsequent failure/review decisions are in §1.5;
FC-Q17 recommendation/forecast eligibility and review policy decisions are in §1.6.
This is an accepted design decision, not implementation or qualification evidence.

### 1.5 Recovery, review and disagreement (OC-D109..111)

Accepted 2026-10-25 in [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md):

- **OC-D109:** preserve reports/completed work when required evaluation is unavailable; retry within
  authored time/spend limits, then durably block affected work with a visible reason and recovery
  action. Unavailability is not an evidence verdict. Cancellation stops new evaluation and prevents
  late results from automatically reopening acceptance. Numeric limits remain authored policy.
- **OC-D110:** KS persists decisions bound to the exact report revision, use, audience and proposed
  effect, returning authenticated references resolvable after restart. MC owns durable human-review
  wait/notification. KS checks reviewer authority and records a successor decision; MC verifies that
  successor and current eligibility before resuming.
- **OC-D111:** unsupported evaluator disagreement holds for bounded repair or authorized adjudication.
  Automated rejection requires grounded contrary evidence or an integrity failure. This preserves
  the separate authorized-human rejection path and never permits approval to waive failed checks.

These are runtime design requirements; no new end-to-end proof is asserted.

### 1.6 Judgment outputs and review policies (OC-D112..113)

Accepted 2026-10-25 in [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md):

- **OC-D112** revises Sprint V's OQ4 blanket official-use exclusion. Recommendations and forecasts
  may be admitted as explicit judgment outputs only where an admitted use policy allows them.
  Retain premises, rationale, assumptions, uncertainty and relevant horizon; assess them independently
  and obtain required review. Approval authorizes the exact judgment for that purpose and does not
  convert it into an entailed fact. Qualified human sign-off for consequential scientific use remains.
- **OC-D113:** KS owns admitted, versioned review policies describing review requirements and
  qualifying reviewer grants. Authorized authors/coordinators may select policies allowed by the
  application/use or tighten requirements. They cannot weaken mandatory review or grant themselves
  authority. Pin the selected policy in the decision, while enforcing current revocations; MC owns
  presentation and the resulting durable wait.

These requirements must be implemented and tested; current source still has the earlier OQ4 guard.

### 1.7 Fulfillment, forms and transfer authority (OC-D114..116)

Accepted 2026-10-25 in [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md):

- **OC-D114:** keep submissions/revisions, fulfillment decisions and invocation finalization as
  separate durable facts. Fulfillment names the declared obligation, exact accepted members, applicable
  checks, count, coverage and unmet requirements at the evaluated result. Missing submissions cannot
  remove promises. This reconciles OC-D6 with Sprint V's existing submission/finalization records.
- **OC-D115:** kernel forms are `text`, `structured`, `file`, `collection`, `reference`, `code_change`,
  `effect_receipt`, `control_record`. Domain types use pinned templates or explicit inline contracts
  with admitted validators. Verdict/handoff authority and invariants remain enforced. This revises
  OC-D2/19's closed domain-kind wording; a form alone never establishes content validity.
- **OC-D116:** one canonical sealed transfer plan preserves exact selection, selection authority,
  required state, forms and budgets. Delivery/readiness receipts remain separate per attempt.
  Replace overlapping selection/M04 planning authorities under the clean rebuild; retain new-system
  restart/replay guarantees. This is consolidation of semantics, not a table rename.

### 1.8 Native effects, enforcement and handoffs (OC-D117..119)

Accepted 2026-10-25 in [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md):

- **OC-D117:** retire the proposed special `domain_effect` output kind in favor of general qualified
  step-output handles and `effect_receipt` contracts. Preserve exact operation/native-result/receipt
  provenance. Report production, use authorization, native commit and readback remain distinct;
  pending dispatch cannot satisfy an applied-write requirement; required readback passes separately.
- **OC-D118:** retain `required`, `expected`, `optional` obligation enforcement, separate from output
  validity. Unmet required obligations gate completion, expected obligations record visible shortfalls,
  and optional absence neither blocks nor warns. Invalid/unauthorized content never becomes accepted
  merely because its obligation is nonblocking. This confirms OC-D3.
- **OC-D119:** host-assembled authoritative state is mandatory at applicable transfer boundaries.
  Agent-authored semantic handoffs are checked, attributable outputs when explicitly contracted by
  workflow/profile. Ordinary helpers may have no obligation. This clarifies OC-D14 with OC-D52/71.

### 1.9 Consumer purpose, materialization and profile clarification (OC-D120..122)

Recorded 2026-10-25 in [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md):

- **OC-D120 is tentative steering, not final profile approval.** The owner asks whether transfer is
  between workflow parts and agents, whether report-review is a distinct versioned policy, where
  policy registration/activation/effective configuration belongs relative to submission, and how
  inline versus sandbox/reference placement is governed. The
  [working contract §§2–5](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md)
  provides the concrete explanation. OC-D123/124 below subsequently close FC-Q6r/19 explicitly.
- **OC-D121 accepted:** authorized review/repair can consume exact draft/held material with its
  status/gaps. Official-use consumers require exact-use/current-eligibility checks plus native
  ingestion/lineage/readback where their contracts promise it. Exact operational reads confer no use authority.
- **OC-D122 accepted:** one host-owned materialization entry point takes admitted instructions,
  task/contracts, authoritative state, explicit selected data, receiver model/backend and budgets;
  it produces a sealed effective plan/index, receipts and readiness/refusal through boundary-specific
  builders. Initial invocations have no invented predecessors; dependent inputs are exactly selected.

### 1.10 Profile activation and placement confirmed (OC-D123..124)

Accepted 2026-10-25 after the OC-D120 clarification, in
[IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md):

- **OC-D123:** `report-review@v1` is the first reusable profile of the common transfer schema;
  equivalent inline authoring is allowed. Admission pins and compiles effective settings; activation
  binds the run revision. Preferences specialize profile → mission → unit → consumer input, with
  link restrictions and all hard requirements enforced. Actual output revisions resolve into sealed
  receiver plans later. `submit_output` selects candidates; policy changes require an authorized
  configuration revision for a safe future boundary.
- **OC-D124:** compact task/state, obligations, selected assertions and the access index default
  inline; exact report bodies default to readable sandbox files; evidence uses validated on-demand
  handles; broader history is opt-in. Each consumer can declare other requirements/alternatives.
  Account for all initial prompt content and file bytes, with generation/tool-result capacity
  reserved. Future file reads consume model context. Use only authored satisfying alternatives;
  otherwise bounded repair/block, never silent truncation, summary or form downgrade.

The [working contract](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md) carries
the concrete authoring/activation/submission and placement walkthrough. FC-Q7/9/10's already accepted
semantics are carried forward there with provenance, without redundant owner questions.

### 1.11 Focused coordinator scope (OC-D125)

Accepted 2026-10-25 in [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md):
build effective-node configuration, exact input/output, fulfillment and transfer-plan/receipt
inspection, plus attributable output/transfer events through the current router/control path. Defer
the broader CLI grammar migration, new skill bundles/scripts, automated provider-sheet upkeep,
Socket.IO CLI, legacy API retirement and global HTTP cleanup to their own decisions. This does not
accept every detail of CS-D1..14 or promote proposed ADR-0049.

The owner requested an overnight stop after this answer. The
[exact checkpoint](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CHECKPOINT-2026-10-25.md)
preserves that stop. The two remaining questions were answered on resumption in §1.12.

### 1.12 Notifications and error routing (OC-D126..127)

Accepted 2026-10-26 in [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md):

- **OC-D126:** durable wakes for actionable assessment holds/rejections, blocked delivery, required
  review, unresolved effects, checkpoint readiness and completion/failure. Retain routine events and
  batch progress. Allow admitted subscriptions; prove actual selected-host wake, replay/reconnect,
  acknowledgment, duplicates and cancellation.
- **OC-D127:** one typed output/transfer error envelope with safe explanation, position/field,
  retry/recovery and correlation plus native cause metadata. Route correctable model errors to bounded
  repair and infrastructure/authority/uncertain effects to the host. Execution, fulfillment and
  settlement stay distinct. This adopts the relevant contract, not the whole FT program.

The fixture/gate question is answered in §1.13. Checkpoint sequencing/release follows in FC-Q13/21b;
existing mandatory repair/rerun rules and both-app requirements are not reopened.

### 1.13 Real fixture qualification exception (OC-D128)

Accepted 2026-10-26 in [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md):
explicitly amend SV-D12 to permit bounded real owner-fixture qualification at progressive checkpoints
once their prerequisites are ready. Use real agents and actual required acquisition/ingestion/retrieval
paths; review the Transcript/results against functional goals, repair failing layers and rerun before
advancing. Synthetic/scripted diagnosis does not replace functional acceptance. Routine research and
general use still require all four workflows, output/context contracts and full Deep Agents
qualification for both applications. The exact fixtures arrive after the interview.

### 1.14 Checkpoint sequence and release (OC-D129..130)

Accepted 2026-10-26 in [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md):
W0 prerequisite schemas/trusted interfaces/settlement barriers → W1 one GoalDirected report →
W2 exact two-stage transfer → W3 multiple reports/accumulation/synthesis → W4 advanced recovery,
revisions, review and linked reuse → W5 remaining workflows/compositions/full Deep Agents qualification.
Each wave has a mandatory evidence checkpoint; basic durability, access and aggregate budgets precede
first use. Start real workflow fixtures at W1; prove AI Engineer then Biotech at applicable boundaries.

A separate reviewing agent assesses retained Transcript, outputs, receipts and declared functional
criteria. The implementation coordinator records pass and advances only when every required criterion
is met; missing/ambiguous evidence blocks. Escalate unresolved goals and required human decisions;
a fixture may explicitly require owner release. This is distinct from KS/scientific-review authority.
Repair and rerun before progression. OC-D132 subsequently adds detailed workflow/hook rounds before
FC-Q15; no final confirmation is inferred.

### 1.15 Fixture flexibility and detailed workflow/hook rounds (OC-D131..132)

Owner steering, 2026-10-26, recorded in [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md):
exact complex real-world fixtures arrive at the end. Adapt the detailed checkpoint mapping to their
actual goals and increasing complexity; do not simplify them into six preselected task shapes.
W0–W5 remains the capability/proof scaffold with mandatory review/repair/rerun.

Before final confirmation, examine GoalDirected accumulation/iteration boundaries; StageGraph
dependency types, joins, selection/revisions and retrieval; executable Deep Agents hooks, event timing,
state access and context effects; and coordinator on-demand versus subscription output delivery.
Read the [source audit](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/WORKFLOW-CONTEXT-HOOKS.md).
These detailed choices remain open; broad earlier defaults do not silently decide them.

### 1.16 GoalDirected working views and independent progress (OC-D133..134)

Accepted 2026-10-26, recorded verbatim in
[IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md): the next executor receives
distinct current accepted work, actionable repair work and optional history views. Keep goal,
obligation/coverage, blocker and bounded repair state inline; require an exact accessible current-set
index and deliver selected bodies according to the input contracts. Held/draft/rejected material
remains labelled and task-selected. Explicit consumer placement requirements may differ.

Independently runnable goal work continues within budget while affected obligations durably wait.
Required waits still block final acceptance; pending work/effects are not retried or duplicated to
make progress. Required invocation barriers and declared global pauses still apply. This requires
obligation-level readiness/recovery; it does not yet settle semantic-note or repair-fork defaults.
The working detail is in [CONTRACTS §16.1](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#161-goaldirected-working-views-and-independent-progress).

### 1.17 New-session handoff and linked-workflow scope (OC-D135..136)

Owner instruction, 2026-10-26: stop this conversation for context length and write an extremely
detailed interview handoff. Explicitly include Linked Workflows and deep intra/inter-workflow
context transfer; preserve Mission Control versus Knowledge Services ports/extensions and ownership.
GPT 6 Astra subagents may help the next session discover, explore and research context.

The [new handoff](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/INTERVIEW-HANDOFF-2026-10-26.md)
is the resume entry point. FC-Q22c/d were unanswered at handoff creation and subsequently answered
as OC-D137/138 below. Add FC-Q26 to Round E without renumbering
existing questions. No final confirmation, new behavioral default or implementation authorization
is inferred from this session change.

### 1.18 GoalDirected progress notes and repair-fork defaults (OC-D137..138)

The owner answered the final two sent questions before moving sessions, 2026-10-26. The continuing
GoalDirected default profile requires a compact attributed progress note at each normal iteration
handoff: work/sources tried, findings, unsuccessful approaches worth avoiding, unfinished work and
suggested next actions with exact references. Host state remains authoritative; the note cannot
rewrite facts or grant authority. Crash preserves the host checkpoint and records any missing note
for contract-governed recovery. Ordinary helpers remain unaffected.

An explicitly requested repair fork defaults to selected exact task-relevant historical drafts/files,
accepted-set index and findings, labelled for repair. Check receiving access and availability; do not
substitute today's workspace for a missing historical snapshot. Pending effects require reconciliation;
context copying neither adopts obligations nor duplicates writes nor transfers authority. History
remains off. See [CONTRACTS §16.3](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#163-goaldirected-progress-notes-and-repair-fork-defaults).

Next session starts with StageGraph and linked/nested workflow transfer, then hooks and coordinator
delivery. Do not re-ask FC-Q22c/d. The resumed session now records OC-D139/140 below;
the latest decisions/steering are now through OC-D161 below. Next unused decision ID is OC-D162.
The interview remains open.

### 1.19 Stage Graph alternative selection and unfinished branches (OC-D139..140)

Accepted 2026-10-26: an explicitly authored any/quorum group selects and seals the first qualifying
set in recorded eligibility order, with a stable tie-break when several qualify together. Authors
may choose bounded wait/ranking instead. Preserve coverage, separately required named inputs,
receiving access and permitted-use constraints. Later arrivals cannot silently alter sealed inputs.

Unfinished branches continue within existing budgets by default; cancellation requires explicit
author policy and respects other consumers and obligations. Assess/retain later outputs for explicit
later use. Usage/effect reconciliation and settlement accountability remain; cancellation cannot
undo committed work. See [CONTRACTS §16.4](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#164-stage-graph-alternative-selection-and-unfinished-branches).

### 1.20 Optional inputs and scoped synthesis revalidation (OC-D141..143)

Accepted 2026-10-26: otherwise-ready consumers proceed with a pending optional input omitted and
the omission visible; waiting requires an authored bounded policy. Independent ordering and required
input constraints remain. Late arrival does not silently alter the sealed selection.

For completed synthesis affected by a tracked report revision, MC arranges bounded authorized
revalidation first, with applicable evidence reuse and KS evidence/use-decision authority. Restore
current eligibility only if justified; rebuild only where needed and authorized. Missing checks or
exhausted limits block actionably. Preserve history/effects and revocation constraints.

The owner explicitly limits current-sprint automatic invalidation work to this synthesis/report-revision
case; general data freshness/invalidation automation belongs to later sprints. Additional cases need
explicit inclusion. See [CONTRACTS §16.5](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#165-optional-inputs-and-scoped-synthesis-revalidation).

### 1.21 Report revision during running synthesis (OC-D144)

Accepted 2026-10-26: when a newer accepted report revision arrives and the selected older revision
remains permitted, let running synthesis finish within its budget against sealed inputs, retain its
result, then revalidate before current admission. Interruption/restart requires explicit authored
policy at a supported safe boundary. Preserve exact history; revocation, cancellation and mandatory
stops apply independently. Scope remains synthesis/report revisions under OC-D143.
See [CONTRACTS §16.6](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#166-report-revision-during-running-synthesis).

### 1.22 Incremental batching and provisional reassessment scope (OC-D145..146)

Accepted 2026-10-26: authored incremental synthesis defaults to one active and one pending next
activation combining new qualifying arrivals. Seal the exact eligible set at release, honoring
triggers, coverage and budgets; per-increment activations require explicit policy.

Explicitly add authored bounded independent reassessment of retained provisional synthesis when its
exact held source report becomes accepted without changed bytes. Derived checks and permitted-use
decisions still gate eligibility; without the policy await explicit action. This adds a specific case
under OC-D143; general freshness/invalidation automation remains deferred.
See [CONTRACTS §16.7](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#167-incremental-batching-and-provisional-reassessment-scope).

### 1.23 Conditional unknown and dynamic expansion membership (OC-D147..149)

Accepted 2026-10-26: unknown conditional evidence defaults to durable bounded wait; else requires
conclusive false, exhaustion blocks/escalates, and explicit unavailable-evidence routing preserves
unknown and required gates. Dynamic expansion freezes exact collection revision/membership;
incremental additions require explicit policy, stable identities and committed limits.

The owner requests a source-backed explanation of conditional routing's built versus specified state
and its behavior/benefits for knowledge, content and codebase work before further design questions.
The Deep Agents usage comment is tentative, not an inferred exclusive lane restriction. See
[CONTRACTS §16.8–16.9](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#168-conditional-unknown-and-dynamic-expansion-membership).

### 1.24 Large-workload Stage Graph interview expansion (OC-D150)

The owner explicitly asks for deeper questioning on expressive Stage Graphs for big workloads:
deterministic reducers, multiple discovery inputs, consolidation, partitioned work, further reduction,
output contracts/obligations and dependencies. Add **FC-Q27** before final confirmation, with
deterministic/semantic computation, collection/partition/grouping, obligations/coverage, selective
recovery, bounded hierarchy, resource/backpressure and safe optimization choices. Do not overfit
to the example or infer accepted architecture. Existing declared deterministic executors and the
older compute proposal are source inputs, not proof of a working scalable runtime.
See [CONTRACTS §17](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#17-large-workload-stage-graph-and-map-reduce-interview).

### 1.25 Large-workload foundations (OC-D151..153)

Accepted 2026-10-26: standard typed/versioned deterministic operations plus admitted custom
transformations; exact partitions with per-member outcomes/lineage and explicit indivisible groups;
complete durable work inventory with bounded activation/admission windows and coordinator counts.
Semantic judgments remain separate admitted operations. Retry preserves logical slices; repartitioning
is explicit and retains lineage. Capacity/provider/budget/fairness constraints remain. Example sizes
are not qualification targets. See [CONTRACTS §17.1](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#171-transformation-partition-and-scheduling-foundations).

### 1.26 Reducer conflicts, readiness and tree optimization (OC-D154..156)

Accepted 2026-10-26: preserve uncontested reducer results and typed conflicts; block only affected
requirements. Independently release groups with provable closure and satisfied input contracts;
failed/missing required inputs remain gaps. Allow automatic deterministic regrouping only under
qualified result-preservation, qualify reordering separately, and author semantic hierarchies explicitly.
Resource/duplicate/effect rules remain; no silent input dropping. See
[CONTRACTS §17.2](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#172-conflicts-independent-group-readiness-and-qualified-trees).

### 1.27 Coordinator-perspective contract critique (OC-D157..158)

The owner requests a critical review before further feature questions: contract expression,
submission/obligations/dependencies, conditional context transfer, reduction and composability with
Goal Loop. The follow-up explicitly demands a broad ambitious coordinator perspective, not a design
limited to the illustrative entity-report/relationship case. Preserve accepted capability choices;
recommendations are not silently accepted amendments or implementation authorization. The review
and source gaps are in [CONTRACTS §18](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#18-coordinator-perspective-critical-review).

### 1.28 Bounded final interview and transfer (OC-D159..161)

The owner requires completion of the interview → specifications → issues process, selecting a
coherent current version of the workflows and linked workflows. Extensive mission-specific setup
with the coordinator precedes mission launch; do not solve all future mission planning here.

The next interview has a hard maximum of twenty substantive questions, including follow-ups and
final model confirmation. Research and prepare the crucial questions first. Resume from the
[final handoff](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/FINAL-INTERVIEW-HANDOFF-2026-10-26.md)
and [twenty-question instrument](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/FINAL-INTERVIEW-20-QUESTIONS-2026-10-26.md),
which carries the live asked/answered count. The [session record](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/SESSION-ANSWERS-2026-10-26.md)
preserves every current-chat substantive owner message/answer. The owner starts GPT 6 Astra manually.
This latest bounded protocol supersedes open-ended question-frontier wording elsewhere in this instrument.

### 1.29 Final routing, join population and semantic coverage decisions (OC-D162..164)

Accepted 2026-10-26 after fresh source research: conditional routes require an explicit mode/preset
(all matching or first matching in declared order); data joins require explicit result-population
policy/preset (named primary population, both populations, or intentional matched subset); semantic
decomposition requires task-relevant preservation and coverage terms, through justified independence,
reconciliation/validation or explicitly limited final claims. Mechanical item completion is insufficient.
Unknown/else rules and required coverage remain; these are design decisions, not runtime qualification.
See [CONTRACTS §16.8](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#168-conditional-unknown-and-dynamic-expansion-membership),
[§17.1](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#171-transformation-partition-and-scheduling-foundations)
and [§17.3](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#173-semantic-decomposition-preservation-and-coverage).

### 1.30 Linked review, cancellation and application scope (OC-D165..167)

Accepted 2026-10-26: purpose-scoped linked repair/review may receive exact held/draft reports before
source-goal acceptance, with receiving authority, status and required-input readiness preserved.
Ordinary supply retains owning-Goal or explicit Mission Acceptance and applicable use gates.
A chain consumer already running with valid sealed inputs continues by default on upstream
cancellation unless propagation was explicitly selected; revocation/mandatory stops still apply.
Spawned-child and attached-mission cancellation defaults remain separate.

The owner explicitly confirms linked workflows **within one application**, qualified independently
in both applications. Cross-application transfer/connection is an unadopted possibility, not a deferred
feature or a promised qualification target. See
[CONTRACTS §16.2](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#162-linked-and-intrainter-workflow-interview-scope).

### 1.31 Partition repair and optimization scope (OC-D168..170)

The owner selects coordinator inspection/replacement of poor partitions or an explicitly configured
agentic planning step, with deterministic validation of the resulting plan and preserved membership,
coverage, successes, limits and lineage. Do not infer an autonomous deterministic research replanner
or selection of Jev. Pressure-aware scheduling remains undecided until the dedicated deployment worker
runs locally and provides evidence; existing capacity/fairness/budget requirements remain.
New automatic computation caching is excluded from this version; required recovery, idempotency
and explicit reuse remain. See
[CONTRACTS §17.4](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#174-partition-repair-and-optimization-scope).

### 1.32 Durable reactions and compaction preservation (OC-D171/172)

Accepted 2026-10-26: authored durable workflow/output reactions run as ordinary admitted executions
with identity, obligations, budgets and restart/replay handling; Temporal remains scheduler.
Compaction hooks may offer bounded candidate notes/exact references for host validation, while
required state is preserved independently. They cannot replace the entire summary or rewrite
sealed input selections; compaction and continuation retain distinct processes. Read/write/effect
permissions remain separate choices. See
[CONTRACTS §16.10](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#1610-durable-reactions-and-compaction-preservation).

### 1.33 Hook access, preparation and effect boundaries (OC-D173..175)

Accepted 2026-10-26: hooks may combine their bounded event snapshot with explicitly scoped,
host-mediated reads. Hook files are staged candidates for host-validated installation at supported
boundaries. Model work/external writes use separate ordinary admitted operations with their own
identity, authority, budgets and recovery. Persistent notes/indexes can use these same configured
output paths, making F20-15 redundant; no new authoritative journal or automatic memory subsystem
is adopted. See
[CONTRACTS §16.11](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#1611-hook-access-preparation-and-effect-boundaries).

### 1.34 Optional automatic coordinator content (OC-D176)

Accepted 2026-10-26: explicitly configured selected excerpts/small outputs may be delivered into
coordinator context within receiving grants and context budgets. Default notices remain references,
status and gaps. Keep the Child Portal bounded and prove wake, model-visible delivery, acknowledgment
and content read distinctly. See
[CONTRACTS §9.2](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#92-optional-automatic-coordinator-content).

## 2. Required session outputs

- **`answers/output-contracts-final/<model>-<YYYY-MM-DD>/ANSWERS.md`** (IA-09), the template shape,
  `final` at close.
- **A revised contracts pack:** `answers/output-contracts-final/<model>-<date>/CONTRACTS.md` and
  `WORK-ITEMS.md`, written as revisions of the checkpoint's
  [CONTRACTS](../answer-sets/gpt-6-astra-2026-10-24/CONTRACTS.md) and [WORK-ITEMS](../answer-sets/gpt-6-astra-2026-10-24/WORK-ITEMS.md)
  through SP-10 §10.5's delta map, with a conformance table against what Sprint V built.
- **A prompt-materialization contract and fixture matrix** in that pack: first invocation and dependent
  invocation, instruction/data trust, inline versus file/handle policy, aggregate resource accounting,
  exact source selection, readability and sealed replay; one concrete two-stage example. Map every
  RV finding to repair/proof or an explicitly justified deferral. No test-double service path is
  labelled full Deep Agents qualification.
- **The issue list** for the output/transfer runtime sprint, one row per issue with repository, wave,
  provenance ids, filed as `OVE` issues at the end of the sitting (this is the sitting where the
  "immediate issue step" of the skill applies again).
- **SP-04 §8** ([SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md](../specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md))
  marked: OC-D1..26 confirmed, revised or retired, each with the id that decides it; CS-D1..14 answered.
- **Glossary and ADRs:** the local candidates DC-OBL/APP/XFER (PR-10) and DC-KOP/ACT/BIND/ROLES (PR-11)
  promoted to `docs/adr/` numbers or retired, through `domain-modeling`.

## 3. Read first

1. The readiness review RV-01..08 and its fresh-test table; then IA-06, IA-07, IA-08 answers;
   SP-10 §10.5 (delta) and §10.6 (frontier); `SPRINT-V-PLAN.md` and the
   change-ledger turn(s) Sprint V wrote; the as-built conformance tables in SP-10 and SP-10 §4.9.
2. SP-04 ([output contracts specification, revision 2](../specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md)):
   §3 obligation model and kinds, §3.3 submission (now revised by OC-D83), §4 Mission State Transfer,
   §8 OC-D1..26, CS-D1..14.
3. Checkpoint pack: SPECIFICATION §9..13, CONTEXT-TRANSFER §4..6 and §10..13, CONTRACTS §3..6 and §9..10.
4. Proposals that touch this thread and are still open: PR-03 (DP-D1..14), PR-05 (HG-D1..24), PR-07
   (CO-D1..18, cards and observation), PR-08 (WC-D11/D12/D14/D15), the fault-tolerance proposal
   (FT-D for the error envelope the transfer refusals use).
5. Live source after Sprint V: the actual common release tables, `SubmissionService`, `KnowledgeGateway`,
   the as-built exact resolution/delivery/readiness modules, the Deep Agents materializer, and the
   `goal_directed`/`stagegraph` submission/tool paths. `ContentResolutionService` and `DeliveryPlanner`
   now exist in `application/context/{resolution,delivery}.py`; `ReportRepresentation` and
   `application/knowledge/toolset.py` also exist. Read `ContextPackService`,
   `adapters/deep_agents/adapter.py::_prompts/_context_seed_files`, and `knowledge_tools.live_invocation`.
   Current finalization distinguishes coverage from terminal assessment, but neither implements the
   full five-guarantee fulfillment contract. Declared obligations are not yet wired into the lane;
   empty declarations fall back to what the agent submitted.
6. KS `packages/host/src/knowledge-operation/{config,service,backends,native-ports}.ts`,
   `packages/application/src/research/{assessment,coordinator,review}.ts`; MC
   `adapters/knowledge/decisions.py`; BKS `packages/kg-ops/src/admission/{dispatch,verification}.ts`.
   Distinguish trusted in-process methods, published transport operations, scripted proof injection,
   and normally composed provider services. `verify.claims` is currently unsupported.

Verify, before asking: which of the SP-10 §10.3 assumptions S1..S6 Sprint V confirmed or broke; whether
`submission` and `obligation_fulfillment` were built as one table or two; which frames carry origin,
handles and receipt refs; which transfer profile fields exist in code.

## 4. The question bank

Dependency-ordered, at most four questions per batch, recommendation first. Facts about implemented
code are not owner decisions: record them as facts, but do not treat an implementation deviation as
overriding an accepted OC-D/SV-D. Skip questions already settled by the owner unless new evidence
requires a clearly labelled revision. New FC-Q16..21 retain FC-Q1..15's stable identifiers.

Suggested sitting order: FC-Q16/17 → FC-Q1..4 → FC-Q5/6/18/19 → FC-Q7/8/9/10 →
FC-Q11/12/20 → FC-Q13/14/21/15. Split a batch further whenever its decisions depend on an answer.

### Round 0 — the missing executable service path

- **FC-Q16 — Who runs the independent semantic steps?** Given RV-04, which first-version composition
  realizes OC-D98: KS provider-hosted judge/auditor steps, or separate MC agent steps submitting
  authenticated observations to KS? Recommend separate MC-hosted Deep Agents judge/auditor operations
  with trusted KS observation ingress and sealing for the first composition, matching the chosen lane.
  Independently identify the evaluator, pin method/rubric, and record the census; the producer's
  registration tool must not impersonate those steps. Reuse the step contracts for a future KS-hosted
  provider if useful. Compare the missing ingress work against a KS provider adapter before accepting
  the host choice. Specify timeout, cancellation, unavailable evaluator and dispute
  behavior. Scripted observations remain proof doubles, not a production fallback.
- **FC-Q17 — How does assessment become an exact-use decision and optional native write?** Recommend
  a trusted KS decision/seal/review service plus a durable qualified decision reference resolved by MC;
  no model-provided grant and no hand-populated MC memory store. Walk evidence → independent assessment
  → seal → use decision → review if required → native admission → receipt/current eligibility for both
  domains. Keep report-only completion possible where ingestion is not an authored obligation. Decide
  where a held decision waits and who resumes it, including OQ4 recommendation assertions, reviewer
  authority, and whether a second-family disagreement can ever reject on its own. Current official-use
  refusal and dispute-holds behavior remain facts until explicitly revised.

### Round A — reconcile the baseline (frontier items 1 and 7)

- **FC-Q1 — Table consolidation.** `submission` vs `obligation_fulfillment` (OC-D6); `transfer_plan` vs
  `context_selection`; `domain_effect` kind (DP-D4) vs step outputs (OC-D98). Recommend: one
  `obligation_fulfillment` row per obligation per unit result derived from `submission` rows in the
  settlement transaction; `transfer_plan` supersedes `context_selection` under the accepted clean
  rebuild strategy (no required old-packet replay branch); `domain_effect` retired in favour of a
  step-output handle on the obligation. New-system recovery/replay still needs its own proof.
- **FC-Q2 — The "tables I surely missed" pass.** Walk SP-10 §7.5 against DP-D1..14 and HG-D1..24 and
  the Sprint V change ledger; name every Mission Control record the runtime sprint still needs (candidate:
  assessment records per guarantee, adoption facts, review-gate decisions bound to exact uses, frame
  joinability for handles). Decide which need the next common release and which fit existing tables;
  allocate that version from the released Sprint V baseline, not the old 1.4.6 placeholder. Apply the
  recurring schema-fit review to shared verification SQL and both domain models as well as MC.
- **FC-Q3 — OC-D1..26 status.** For each: confirmed as decided, revised by a later id, or retired.
  Recommend confirming OC-D1/D3/D6/D7/D8/D9/D10/D11/D12/D14/D15/D17/D18/D20/D21/D24/D25/D26; OC-D2 and
  D19 answered by FC-Q4; OC-D4/D5 revised by OC-D83; OC-D13/D16/D22/D23 answered by their sittings.
- **FC-Q4 — Kind set versus forms (frontier item 2).** OC-D2's closed kinds (`document`, `file_artifact`,
  `structured_record`, `code_change`, `verdict`, `handoff`, `decision_record`) versus CONTRACTS §3.1 forms
  (`text`, `structured`, `file`, `collection`, `reference`, `code_change`, `effect_receipt`,
  `control_record`) and OC-D19 obligation templates. Recommend: forms are the kernel vocabulary; the
  report catalogue's kinds and the Biotech skeleton are obligation templates in the catalog (OC-D19);
  `verdict` and `handoff` are control records; enforcement levels (OC-D3) unchanged.

### Round B — transfer contract closure (frontier items 3 and 4)

- **FC-Q5 — CS-D1..14.** Source clarification, 2026-10-25: these ids belong to the
  [coordinator-surface proposal §7](../../../coordinator-surface-2026-10/PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md#7-decisions-for-the-owner),
  not the transfer-profile fields. Reconcile each against actual coordinator implementation and owner
  answers. CS-D10 inputs/outputs and CS-D4/5 configuration/events directly touch this work; handle
  remaining grammar/skill/provider/transport choices with FC-Q20 and an explicit scope disposition.
  CONTEXT-TRANSFER §4/10 and SP-10 §6.4/6.5 inform transfer behavior but do not themselves decide all CS rows.
- **FC-Q6 — The transfer profile fields and `report-review@v1`.** Recommend the CONTRACTS §6.2 field set
  as the v1 profile schema, with `boundary`, `readiness` and the inline/file choice per consumer added
  from OC-D93/D99/D100; `report-review@v1` shipped as the first reusable profile; inline profiles allowed
  (OC-D40).
- **FC-Q7 — Accumulation against submissions.** How a cycling stage (OC-D45..48) and a goal iteration
  (OC-D50) count distinct deliverables, revisions and coverage from `submission` rows and lineage; the
  release rule for incremental consumers (OC-D47); the staleness mark (OC-D49). Recommend the CONTRACTS
  §4 rules unchanged, computed from fulfilment rows, with the current set published once per frontier.
- **FC-Q8 — Required state per boundary.** Confirm the mandatory-state sets of SP-10 §6.5 and OC-D52,
  and what a linked mission receives (OC-D56) now that handles resolve under the receiving mission's
  credential. RV-08: exact operational report reads do not prove native projection or current official-use
  eligibility. Recommend distinct draft/review versus official-use requirements, with admission/lineage
  and current eligibility checks only where the authored consumer contract requires them.
- **FC-Q18 — First-version prompt-materialization interface.** Recommend one host-owned operation
  accepting the admitted task/contracts, current workflow state, explicit selected source set,
  receiver model/backend and budgets; returning a sealed effective prompt plan, input index, delivery
  receipts and readiness/refusal. Compose the existing packer/resolver/representation/materializer
  behind it. Choose the minimum first-invocation and dependent-invocation fields using section 4.1.
  This is a focused functionality module, not permission to begin the deferred global refactor.
- **FC-Q19 — What must be inline, mounted or available on demand?** Recommend mandatory objective,
  output obligations, current blockers and concise access instructions inline; exact reports/evidence
  as bounded files or qualified handles; optional history only when selected. Explicitly decide any
  inline content exception by consumer/profile. Count total prompt tokens and total file bytes across
  all selected reports, reserve generation/tool overhead, and block or use an authored alternative
  when mandatory context cannot fit. No silent truncation, summarization, or run-wide expansion.

### Round C — assurance, provider realization and observability (frontier item 5)

- **FC-Q9 — The five guarantees as contract vocabulary.** Shape, provenance, coherence, coverage,
  ingestion (OC-D91) as named reusable requirements; which validators are admitted capabilities
  (Knowledge Services step outputs) and which are kernel checks; how assessment reuse (OC-D73) is keyed
  (subject digest + policy pin + freshness).
- **FC-Q10 — Provider realization and extensions (OC-D76, QR-1).** Which lane is qualified for the
  runtime sprint (Deep Agents first), the namespaced extension for the sandbox mount index, and the
  refusal when a lane cannot deliver a required file.
- **FC-Q11 — Tracing housekeeping.** Which frames carry origin, handles, receipt refs, readiness and
  delivery facts, and which public events (`obligation_fulfilled`, `output_submitted`, `transfer_planned`,
  `transfer_ready`) the coordinator reads (PR-07 cards). Recommend the sprint F strawman plus the four
  events, each joinable by `unit_key` and `point_ref`.
- **FC-Q12 — The error envelope.** Transfer and submission refusals use the fault-tolerance proposal's
  one envelope; decide the codes that are agent-visible (repair turn) versus operator-only.
- **FC-Q20 — Coordinator observation for these fixtures.** Inbox wait/launcher subscription/relay
  machinery already exists; new output/transfer event coverage and actual host wake-up are unproven.
  Recommend using those existing surfaces with durable event ids/cursors, explicit acknowledgment and
  bounded summaries/links. Which changes should wake the coordinator: output submitted, assessment
  held/rejected, input delivery blocked, review needed, native effect unresolved, completion? Keep
  observation separate from commands and authority. Prove reconnect/replay/duplicate delivery and a
  meaningful wake in the selected coordinator host before promising callbacks.

### Round D — issue breakdown and confirmation (frontier item 6)

- **FC-Q13 — Waves of the runtime sprint.** Recommend W0 closes RV-01/02 and the trusted service path
  chosen in FC-Q16/17; W1 compiles obligations, settles submissions and proves one report in GoalDirected;
  W2 joins prompt materialization to explicit dependency selection and proves a two-stage graph;
  W3 adds collection/member assessment, aggregate budgets, accumulation and synthesis; W4 completes
  assessment reuse, revisions/adoption, review/recovery and linked missions; W5 qualifies the remaining
  workflow/composition boundaries and Deep Agents for both apps. Keep OO/AC/QR provenance and move
  prerequisite schema changes into the wave that needs them. Each wave names its T0/T1/T2 evidence.
- **FC-Q14 — What stays deferred.** Subagent tools and shape (OC-D71), physical topology (OC-D77),
  and the coordinator redesign beyond the operational router/control path. The broad deep-module
  refactor waits for the working chain (owner direction 2026-10-25). Biotech's verification binding
  remains mandatory. The current binding evidence and RV repair list are inputs to this interview;
  missing end-to-end proof blocks the corresponding runtime fixture/qualification, not discussion
  of how to build it. Do not silently waive either application or the SV-D12 real-work gate.
- **FC-Q21 — Fixture acceptance and stop conditions.** Use the readiness review's six-rung ladder.
  Apply OC-D106/107: mandatory stops, owner-supplied fixtures integrated after the interview,
  transcript-based functional review, repairs at every owning layer and rerun before progression.
  Explicitly settle how these runs relate to SV-D12 rather than infer a gate waiver.
  Recommend each rung has a positive case and a relevant negative/recovery case, with separate
  execution, fulfillment, assessment, admission and delivery results. Run AI Engineer then Biotech
  at each applicable service boundary. Choose what requires a real model/backend versus a deterministic
  proof double; mark those tiers visibly. No codebase-commit fixture is needed for this first sequence.
- **FC-Q15 — Confirmation.** Restate the complete model at the three levels (author, agent, operator)
  with one manifest, one agent transcript excerpt and one `missionctl run outputs` view; the owner
  confirms; issues are filed.

### Round E — workflow-specific transfer and hooks (owner addition, OC-D132)

Run these focused rounds before FC-Q15; at most four independent questions per batch, with concrete
examples and source evidence. Do not reopen settled broad defaults without naming the refinement.

- **FC-Q22 — GoalDirected:** current accepted-set and repair/history views; goal-wide verification
  with applicable assessment reuse; per-obligation waits and independent work; failed revision behavior;
  journal/continuation/compaction and fork-frontier selection. Start with one accepted report, one held
  report and one missing report. Current-execution-only verifier input is a gap, not a policy revision.
- **FC-Q23 — StageGraph:** scheduling/data/state/evidence/workspace relationships; all/any/quorum
  membership/cutoff and slow siblings; incremental publication and exact receiver snapshots;
  conditions/provisional propagation; tracked revisions, cycles and bounded fan-out. Separate manifest
  parsing, low-level interpreter support and ordinary authored execution.
- **FC-Q24 — Deep Agents hooks:** in-turn scripts versus durable workflow boundaries; supported
  events, enforcement/observation, execution location and bounded state access; context cues and
  attributable preparation versus host-owned transfer/compaction; effects, retries and failure policy.
- **FC-Q25 — Coordinator output access:** submitted/assessed/fulfilled/admitted/delivered transitions;
  exact on-demand reads; bounded notice payload versus full content; filtering/batching/ack/replay and
  actual host wake. Refine the already accepted focused inspection and actionable defaults.
- **FC-Q26 — Linked and intra/inter-workflow context (OC-D135):** distinguish nested ProgramNodes,
  Child Mission Invocation, linked runs, mission chains, continuation/fork and provider subagents.
  Resolve explicit composite output projections and named input mappings; launch versus result
  readiness; cross-family transfers; complete/incremental/repair release; revisions and explicit
  unfinished-work adoption; receiving authority/budgets/use; selected history/workspace and durable
  cancellation/recovery. Discuss after StageGraph if helpful; existing question IDs stay stable.
  The [handoff §10](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/INTERVIEW-HANDOFF-2026-10-26.md#10-linked-workflows-and-nested-composition-explicit-new-frontier-fc-q26)
  has the fresh source map and a proposed question bank, not accepted answers.

### 4.1 Worked two-stage prompt/materialization discussion aid

**Illustrative contract, not a new manifest schema or accepted decision.** A produces one evidence
report; B receives that exact selected revision and writes a synthesis. Repeat with two producers
only after per-member assessment and dependency selection are fixed.

| Receiver input | First invocation A | Dependent invocation B | Placement / authority |
| --- | --- | --- | --- |
| Host instructions | Allowed tools, write roots, trust rules, submission procedure | Same, plus consumer role and permitted use of upstream output | Stable trusted instruction layer; never copied from report prose |
| Task | Goal, scope, as-of, audience, report kind and explicit output obligations | Synthesis objective, upstream selection and its acceptance/use policy, own obligations | Concise admitted task/instruction segments; distinct from artifact data |
| Workflow state | Initial frontier, no invented predecessor | Exact accepted or explicitly provisional source frontier, blockers, coverage and revision facts | Mandatory compact host state; provisional/held status labelled |
| Source content | Explicit fixture inputs or admitted discovery capability | Only selected A report revision (later: explicit collection members) | Exact read-only body/ledger/manifest files; qualified on-demand handles where allowed |
| Access index | Logical paths, kinds, sizes/digests, purpose and how to read them | Same plus source identity and disposition | Small inline index; no raw credentials, database URLs or entire schema dump |
| History | Usually none | Only selected state needed for the task | Optional bounded file/reference; no whole predecessor transcript by default |
| Outputs | Own writable output slot; register/submit exact result | Own synthesis slot and obligation; preserve source attribution | Agent submits selection; host checks, assesses and settles; submission is not ingestion |

In the current M04 implementation a report occupies
`/inputs/knowledge/<report-id>@<version>/{body.md,ledger.json,manifest.json}` and uses files only.
`_prompts` assembles admitted segments by trust class; it is not yet the complete dynamic compiler
described above. The `ContextPackService` already handles ordinary stage/iteration packets. Integrate
these paths and declare whether `<version>` is a schema version or immutable content revision; include
the exact handle/digest in identity and collision rules. Files must be readable through the actual
backend permissions before B starts. Report text remains untrusted source content even when verified.

The walkthrough must answer: what A sees before any outputs exist; what changes for B; what happens
when A is held, missing, revised or revoked; how a budget failure is repaired; and how the same sealed
selection is redelivered after restart/compaction. Any semantic summary is a separate attributable
work result, not a hidden transformation performed by the materializer.

## 5. Completion

Complete when IA-09 is `final`; the revised CONTRACTS/WORK-ITEMS pack exists with its conformance table;
SP-04 §8 and CS-D1..14 are marked; ADR candidates are promoted or retired; the runtime-sprint issues are
filed with provenance; `python docs/tools/check_docs.py` passes; and the ledger's next step points at the
runtime sprint's first session instruction. The pack includes section 4.1's concrete walkthrough,
the fixture matrix and a disposition for every RV finding. Interview completion is not runtime
qualification; unresolved repairs remain visible with their proof gates.

## 6. Ready-to-use prompt

```text
Run the final output-contract/context-transfer interview from
docs/specs/archive/provider-consolidation-2026-10/interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md.

Start with sprint-v/ADVERSARIAL-READINESS-2026-10-25.md and the corrected IQ-07-BRIEFING.md, then
IA-06 (OC-D27..78), IA-07 (OC-D79..105), IA-08 (SV-D) and what Sprint V built; read the
code before asking. Preserve every decision unless I revise it; a revision is a new OC-D row linked to the
original. Use grill-with-answers; ask FC-Q1..21 in the instrument's dependency order in batches of at
most four, recommendation first. Record code facts without asking me to rediscover them; implementation
deviations do not silently revise accepted decisions. Start by explaining the RV repair prerequisites.

End with the revised CONTRACTS/WORK-ITEMS pack with its conformance table, the first/dependent invocation
prompt-materialization contract and progressive report-fixture matrix, SP-04 §8 and CS-D1..14 marked,
ADR candidates promoted or retired, and the runtime-sprint issues filed with provenance. Building starts
in the next session, not this one. Both applications remain mandatory and the real-work gate stays closed.
```
