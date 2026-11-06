---
type: Specification
title: "Output contracts and context transfer: IQ-07 integrated version"
description: "Integrated target contract for four workflow families, linked missions, obligations, exact context delivery, selected hooks and coordinator capabilities, pending the remaining scope answers and final confirmation."
tags: [mission-control, contracts, outputs, context-transfer, interview]
date: 2026-10-25
status: draft
---

# Output contracts and context transfer: integrated version

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../../../sessions/KICKOFF.md); no new interview or runtime completion is implied.


**Latest owner steering:** OC-D177–181 adds the direct replacement/disposable-data mandate,
per-major-commit quality and three stress fixtures **after** this sprint's W0–W5 checkpoints,
followed by full product architecture. Read [the complete direction](OWNER-DIRECTION-AND-STRESS-FIXTURES-2026-10-26.md)
and [new synthesis instruction](FINAL-SPEC-AND-ISSUE-SYNTHESIS-HANDOFF-2026-10-26.md). This draft is
the accumulated target input; the next session performs final consolidation/publication. The old
final-question reservation is historical, not an instruction to restart the interview.

This is an **in-progress design**, not a statement that the APIs below are implemented. The
[answers](ANSWERS.md) preserve the owner's exact words and distinguish accepted decisions from
tentative approval. The base remains the earlier [contracts](../../gpt-6-astra-2026-10-24/CONTRACTS.md),
[output specification](../../gpt-6-astra-2026-10-24/SPECIFICATION.md),
[transfer specification](../../gpt-6-astra-2026-10-24/CONTEXT-TRANSFER.md) and
[application-boundary design](../../../specs/APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md), as explicitly revised
by this sitting. Unresolved sections, schema-fit/conformance tables and work-item conversion are
completed through the [interview](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md).

**Review entry point, 2026-10-26:** §15 presents the integrated author/executor/coordinator model
across direct dependencies, recursive workflows, collections/reduction, Swarm, Evaluator Optimizer,
linked missions, hooks and recovery. §§1–14 and 16–17 retain the detailed rules and decision links.
§18 is the earlier critique, with accepted consequences identified; it is not an additional feature
list. [WORK-ITEMS](WORK-ITEMS.md) supplies dependencies, schema owners and proof gates;
[DESIGN-DECISIONS](DESIGN-DECISIONS.md) supplies ADR dispositions. F20-18/19 and the final integrated
confirmation remain open. Source findings are not implementation or release evidence.

## 1. Accepted common model

| Concern | Accepted requirement | Decisions |
| --- | --- | --- |
| Proof gates | Stop at agreed checkpoints, run owner-supplied real-world fixtures, inspect Transcript/output evidence against functional goals, repair every necessary layer and rerun. Exact fixtures arrive after the interview. | OC-D106/107 |
| Semantic evaluation | Separate MC-hosted Deep Agents judge/auditor operations; KS owns trusted evidence sealing and use decisions. | OC-D108 |
| Recovery and review | Preserve work; bounded retry then durable block. MC owns review waits; KS checks authority and writes exact-use successor decisions. Ungrounded disagreement holds. | OC-D109..111 |
| Judgment outputs | Explicit recommendation/forecast contracts under admitted use-specific policy and required review; never convert judgment approval into fact entailment. Constrained policy selection preserves application minimums and current revocations. | OC-D112/113 |
| Output records | Submissions, fulfillment decisions and invocation finalization remain separate. | OC-D114 |
| Content model | Eight general forms with pinned templates or explicit inline contracts and admitted validators. | OC-D115 |
| Transfer authority | One sealed transfer plan, with separate attempt-specific delivery/readiness receipts. | OC-D116 |
| Native effects | General step-output/effect-receipt contracts retain exact native commit and required readback proof. | OC-D117 |
| Enforcement and state | Required/expected/optional completion consequences are separate from validity. Host always supplies authoritative boundary state; semantic handoffs are explicit contracted outputs. | OC-D118/119 |
| Consumer purpose | Review/repair and official-use requirements are explicit; native ingestion/readback requirements apply when promised by the consumer contract. | OC-D121 |
| Materialization | One host-owned entry point with boundary-specific builders; admitted instructions/contracts, state, selected inputs, receiver and budgets produce a sealed plan/index, receipts and readiness/refusal. | OC-D122 |

**Clarification closed:** OC-D120 recorded tentative approval and authoring/placement questions.
After the walkthrough, OC-D123/124 explicitly accepted sections 2–5's configuration model and defaults,
including `report-review@v1` as the first reusable profile. Later accepted decisions below complete
the workflow, hook and coordinator rules; the remaining scope choices are explicitly marked.

OC-D118 explicitly replaces the earlier checkpoint's `mc.output_obligation.v1.required` boolean
with the three-valued enforcement level `required`, `expected`, or `optional`. This governs the
consequence of an unmet obligation; required validity/use checks on submitted content remain separate.

## 2. What is being transferred

Transfer means delivering selected data and required state to a receiving invocation: another stage,
a later cycle/iteration, a verifier, a review/repair operation, a continuation or a linked mission.
An initial invocation uses the same materialization entry point with its admitted starting inputs and
no invented predecessor. Optional helper contracts retain their own scoped rules.

`report-review@v1` is the accepted first named profile of the **common transfer schema**, specialized for
reviewing report material. It is neither the report's content type nor a new kernel transfer type.
The same exact report can reach a reviewer as files and a small-answer consumer inline under two
different admitted input contracts, retaining its source identity and attribution.

## 3. Configuration, activation, submission and resolution

Accepted by OC-D123, building on OC-D54/55/60/83 and OC-D116/122:

| Stage | What it records or does |
| --- | --- |
| Register a reusable profile | Makes a versioned definition available for selection. Registration alone does not activate it for a run. An inline-authored definition supports the same schema without requiring prior global registration. |
| Author a mission revision | Selects a profile or inline definition, mission defaults, named output-to-input bindings, release/revision rules, and consumer/input overrides. The producer describes its outputs/representations; the receiver declares required access and purpose. |
| Validate and admit | Resolves profile aliases to immutable pins/digests; validates effective requirements against application/system constraints, grants, budgets and receiver capabilities. Inline definitions receive a compiled identity too. |
| Activate the admitted revision | Binds the effective transfer configuration to the run at the admitted activation boundary. Expose effective settings, inherited origins and hard constraints for inspection. No produced report revision need exist yet. |
| Submit an output | The agent names the obligation and exact candidate handles/paths. Submission does not select another agent's transfer policy, grant access, declare fulfillment or rewrite run configuration. |
| Resolve for a receiver | Once release conditions hold, the host resolves the named selector to exact eligible revisions, adds authoritative state and seals the receiving invocation's plan. Record optional omissions and conflicts. |
| Deliver and start | Materialize/validate inputs and record receipts. Start the receiver only when its readiness contract is met. |

Accepted default/preference precedence is profile → mission → unit → consumer input; link constraints
restrict the allowed result. **Hard constraints combine**: a specific preference cannot override
required access, application minimums, source export restrictions or mandatory state. Conflicts refuse
admission/readiness with an actionable reason. Expose the origin of every effective setting.

An authorized policy change uses a governed mission/configuration revision applied at a safe future
boundary. It cannot mutate a used plan, redirect a completed submission retroactively or silently
grant new access. A coordinating agent with that authority uses the control/revision surface;
`submit_output` keeps its narrow output-submission role.

### 3.1 Worked authoring example

**Illustrative authoring notation, not a manifest accepted by the current parser.** The profile alias
is resolved to an exact version/digest during admission; the report identity resolves later.

```yaml
transfer_defaults:
  profile: report-review@v1

review_stage:
  inputs:
    report:
      from: research_stage.outputs.report
      purpose: review
      revision_policy: track
      release: complete
      delivery:
        body:
          required_form: sandbox_file
        assertions:
          preferred_form: inline
          allowed_forms: [inline, sandbox_file]
        evidence:
          access: on_demand
          required_form: qualified_handle
      history: none
```

The producer submits report revision R7 for its `report` obligation. The host evaluates that output;
the review stage's contract may explicitly allow held material. When its release rule is satisfied,
the host pins R7 and its exact digest in the receiver's plan. It delivers R7's body as a read-only
file, puts the bounded assertion selection inline if it fits, or uses the expressly allowed file
alternative. The next receiver may have different requirements for the same report.

### 3.2 Common transfer-profile fields

This is the versioned schema design accepted in OC-D123; wire names remain implementation design.

| Field group | Required meaning |
| --- | --- |
| Definition | Exact reusable profile pin or equivalent inline definition; compiled identity and transitive pins. Explicit specialization is compiled, not a second runtime authority. |
| Boundary/source/target | Invocation boundary, named source-to-input bindings, source/output/member selector and receiver purpose/contract. |
| Release/revisions | Complete by default; explicit incremental trigger. Track by default; explicit exact snapshot. |
| Selection | Bounded members/fields/relationships, stable ordering/deduplication, item/depth/byte limits. |
| Delivery | Per-consumer required access/forms, explicit alternatives and separate ordered preferences. |
| Availability/history | Retention/recovery window, authorized custody/access and explicit history ranges; broader history off. |
| Preparation | Separately admitted, budgeted and attributed semantic preparation, if selected; faithful deterministic representations are distinguished. |
| Resources/readiness | Aggregate prompt/file/count/time/spend/retrieval bounds, generation/tool reserves and the four readiness checks. |
| Change/repair | Authorized successor configuration at safe boundaries; bounded retries/permitted alternatives, then block. |

## 4. What enters the prompt versus the sandbox

"Inline-authored profile" in section 3 means where the configuration is written. **Inline content**
below means bytes placed directly into the model's context. They are different uses of the word.

| Material | Accepted default (OC-D124) | Permitted specialization |
| --- | --- | --- |
| Admitted objective/instructions, own output obligations, current blockers, compact authoritative state and access instructions | Inline, in their appropriate trust layers | Mandatory state cannot be removed by a profile; exact required detail is boundary-specific. |
| Selected assertion records and concise verifier findings | Bounded exact inline selection | An authored file/handle alternative may be used when allowed. If full inline is required and cannot fit, repair or block. No silent selection loss. |
| Report body and substantial source material | Exact read-only sandbox files with a small inline access index | A consumer can require body inline, a selected exact section, or a qualified retrieval handle if that satisfies its contract. |
| Evidence not required inline or pre-mounted | Qualified, authorized on-demand handles | Pre-materialize or inline when the consumer requires it; bounded expansion selects exact members, not an automatic whole-run dump. |
| Broader transcripts/history | Off by default | Explicit scoped ranges/refs/files, with retention and budget limits. Required current state is still present. |

A file or folder reference is an **access index**, not its full contents in the prompt. It names the
selected manifest/members, paths, source revisions, digests, sizes, purpose and available read method.
The files must exist and be readable through the actual receiver backend before a required local-file
input is ready. A path string or a successful storage readback alone does not prove that permission.
Arbitrary folders do not imply recursive expansion; explicit selectors and bounds govern their members.

On-demand references require an admitted working retrieval capability and current access validation.
They cannot substitute for a required local file or full inline body unless the contract allows that
alternative. Reading the file later brings tool-result content into the model context; filesystem
storage does not eliminate that token cost. Retrieval/tool-result bounds and context reserves are part
of the receiver resource plan.

Source/report prose remains data even if assessed or inline. It cannot become host instructions through
placement. A semantic summary is a separate attributed preparation output, not a hidden transformation
performed by the materializer.

## 5. Aggregate budgets, readiness and replay

Accepted FC-Q19 closure (OC-D124): account across the **whole receiving invocation**, including host/task/state
text, tool/skill schemas, indexes, all inline content and reserved generation/tool-result capacity.
Track prompt-token and file-byte/count ceilings separately. File accounting covers every selected
report package, not a fresh full allowance for each report.

Choose only authored acceptable alternatives within time/spend limits. A required full inline body
cannot silently become a file, a required file cannot silently become a URL, and required content
cannot silently become a summary or truncated extract. If no allowed realization fits, return the
unmet requirement and bounded repair/replan options, then block.

Receipts bind the exact plan to the receiver attempt and show actual materialization, digests,
readability, access validation and readiness. They do not prove that the model read or understood the
content. Output assessments and the owner's transcript-based fixture gates evaluate those functional
goals. Restart/compaction redelivery uses the sealed selection and records new delivery facts; it does
not silently resolve today's different report or enlarge history.

## 6. Current implementation evidence and limits

Source review on MC `1863017c`, not a new runtime qualification:

- `src/mission_control/application/knowledge/toolset.py:152`: `SubmitArgs` contains `obligation`
  and `items`; transfer configuration is not part of this tool contract.
- `src/mission_control/adapters/deep_agents/adapter.py:1686`: `_prompts` assembles admitted trust
  segments; it is not the complete proposed dynamic compiler.
- `src/mission_control/adapters/deep_agents/adapter.py:823`: `_context_seed_files` combines ordinary
  Context Packet slots and separately delivered knowledge inputs, retrieving and verifying their bytes.
- `src/mission_control/application/knowledge/toolset.py:376`: current report selection is run-wide,
  not the proposed explicit dependency selection. Aggregate report-file byte preflight exists at `:392`.
- `src/mission_control/application/context/delivery.py:140`: the current report plan has no token
  budget. Full effective prompt accounting and selected-backend readability qualification remain work.

The common transfer-profile schema, activation compilation, comprehensive output/transfer records,
current-use purpose checks and focused materialization contract must be integrated and proven. The
ordinary packet machinery is useful existing code; its presence does not prove this whole contract.

## 7. Earlier decisions carried forward without re-asking

These are existing owner decisions, not new answers inferred from code. Their detailed record remains
in [IA-06](../../gpt-6-astra-2026-10-24/ANSWERS.md) and
[IA-07](../../application-knowledge-boundary/claude-fable-5-1-2026-10-24/ANSWERS.md).

| Frontier | Retained contract | Provenance |
| --- | --- | --- |
| FC-Q7 accumulation | Per-cycle and accumulated stage obligations coexist; count distinct deliverable identities, not revisions; subject coverage is separate. Use durable fulfillment decisions over the exact current set. | OC-D45/46, OC-D114 |
| FC-Q7 release | Wait for producer completion by default; incremental release requires an explicit trigger and revision treatment. Resource/cycle caps are not success. | OC-D47/48 |
| FC-Q7 revisions | Track by default, record exact consumed versions, mark affected work stale until revalidated/rebuilt; explicitly pinned snapshots are distinct. Do not silently reverse native effects. | OC-D49, OC-D101 |
| FC-Q7 goal state | Goal verification covers the current goal-wide set and reuses applicable prior evidence; current and historical views remain separate. | OC-D50/51 |
| FC-Q9 guarantees | Shape, provenance, coherence, declared coverage and ingestion remain separately named requirements. Verify the layers promised by the contract, not every possible layer for every output. | OC-D39/75/91 |
| FC-Q9 assessment reuse | Exact subject/revision or selected-set digest, applicable method/policy/authority, evidence and freshness must match; current revocations apply. Reuse valid work and run missing/changed checks. | OC-D73/95/101 |
| FC-Q10 provider | Deep Agents first; common semantics with explicit versioned provider extensions. Required access unsupported by a lane refuses unless an authored satisfying alternative is qualified. Both application bindings remain required. | OC-D76/99, SV-D6/12 |

Implementation records, field schemas, namespaced mount metadata and proof tests must realize those
requirements. A convenient current table shape or provider fallback cannot revise them implicitly.

## 8. Schema-fit inventory (source-backed engineering input)

This inventory is read-only source analysis by GPT 6.1 Sol explorers, not a migration or installed
database proof. Allocate release versions from live heads when implementation begins. At every wave,
review source contracts **and actual disposable installations**, then migrate the owning schema where
needed. No owner needs to rediscover the existing tables to authorize this standing schema-fit rule.

| Authority | Existing foundations | Required design/implementation fit |
| --- | --- | --- |
| MC common SQL | Submissions/finalization, exact content lineage, transfer plans/receipts, durable human_task/human_resolution and versioned gate packets | Fulfillment and exact output/revision/frontier records; per-guarantee assessment/adoption bindings; unified sealed plan; persisted post-execution waits saving provider result and pending effects; typed KS review request/successor references; joinable frames/events. Reuse human tasks instead of creating a second review system. |
| Shared KS verification component/core | Assertion kinds, exact qualifiers, observations, sealed runs, use decisions, scoped reviewer grants, successors and revocation epochs | Typed judgment assessment of premises/rationale/assumptions/uncertainty/horizon; admitted review-policy selection/minimums/tightening and provenance; authenticated semantic observation/seal/decision/review route; current-use enforcement. Existing records may carry some facts; new tables are not assumed without need. |
| AI Engineer domain contract | Exact shared-record projections, normalized-value/effect guards and transactional native admission | Project judgment/policy data where consumers need it; ensure admitted judgment is not presented as verified factual truth; preserve exact native admission and read semantics. |
| Biotech domain SDL/native service | Recommendation speech acts, KS assertion/qualifier refs, policy/decision/seal lineage, graph dispatch marker and current eligibility | Map typed judgments into domain speech-act/projection rules without inventing fact entailment; keep shared policy authority referenced; preserve current eligibility and readback semantics. Author changes in BKS source releases, not pinned generated bundles. |

Source anchors (relative to BellLabs):

- MC `packages/mission-control-db-contract/component/migrations/0005_commands_effects_recovery.sql:206`
  under `platform/mission-control`: existing human tasks/resolutions;
  `src/mission_control/domain/programs/human_gate.py:467` checks version/packet digest;
  `src/mission_control/adapters/temporal/workflows/human_gate.py:75` waits durably.
- KS `platform/knowledge-services/packages/research-core/src/records/assertion.ts:8`,
  `support/algebra.ts:349`, `records/observation.ts:321`, `records/decision.ts:18`, and
  `authority/rules.ts:74`: existing assertion/premise semantics, observation union, decision pins and
  coarse review classes. `verification/aggregate.ts:178` still carries the old official-use exclusion.
- KS `packages/knowledge-db-contract/component/migrations/0003_admission_revocation_and_outbox.sql:9`
  and `0005_signatures_review_and_outbox.sql:241` under that repository: scoped grants and exact review.
- AIDB `aiengineer/ai-engineer-db-contract/supabase/migrations/20261024010100_research_report_v2_projection.sql:269`
  and `20261025010200_research_admission_values_required.sql:31`: projection and native guard.
- BKS `biotech/biotech-knowledge-services/schema/source/biotech-schema-v2.2.0/sdl/assembled.graphql:684`
  and `:770`: recommendation speech act and shared assertion refs;
  `packages/kg-ops/src/admission/dispatch.ts:236` checks current eligibility before effects.

## 9. Focused coordinator scope

Accepted 2026-10-25 by OC-D125: retain the operational router/control path and add inspection of
effective node configuration, exact inputs/outputs, fulfillment, sealed transfer plans and delivery
receipts. Expose attributable output/transfer events with the relevant mission/run/unit/point and
exact record references. Availability and blocked or missing evidence must be explicit; a read surface
must not invent delivery, acceptance or official-use authority.

The broader CLI grammar migration, new skill bundles/scripts, automated provider-sheet upkeep,
Socket.IO CLI client, legacy API retirement and global HTTP cleanup are deferred to their own
decisions. The detailed CS-D1..14 reconciliation remains a final-pack task; this scope decision does
not accept every proposed command spelling, event shape or ADR-0049 deprecation policy.

FC-Q20b and FC-Q12 were unanswered at the [overnight checkpoint](CHECKPOINT-2026-10-25.md).
The owner resumed and accepted them on 2026-10-26 as OC-D126/127 below.

### 9.1 Durable notification defaults

OC-D126: wake the coordinator for actionable assessment holds/rejections, blocked input delivery,
required human review, unresolved native effects, checkpoint readiness and completion/failure.
Persist routine submission/transfer events for inspection and batch ordinary progress. Authors may
configure admitted subscriptions. Notification is observation; it grants no command or review authority.

Use the existing durable inbox with stable identities/cursors and explicit acknowledgment. Prove
actual wake-up in the selected coordinator host, reconnect/replay, acknowledgment, duplicate handling
and cancellation before claiming callbacks work. Inbox persistence or a connected-client hint alone
does not establish that the coordinator received model-visible input or resumed. Retain a visible
unavailable/failed delivery state and actionable recovery information when the selected path fails.

### 9.2 Optional automatic coordinator content

Accepted 2026-10-26, OC-D176: mission setup may explicitly admit automatic delivery of selected
excerpts or small designated outputs into coordinator context, under the coordinator's current grants,
selected purpose and aggregate context budget. Default notices remain bounded references/status/gaps;
other content is retrieved on demand. Preserve exact source identity, revision, status and attribution
for delivered content. This is the coordinator subscription/retrieval/delivery mechanism, not expansion
of the Child Portal, which retains its bounded reference/status/blocker/budget projection.

Persisted notice, transport delivery, actual host wake, model-visible delivery, acknowledgment and
content read remain separate evidence. A delivered reference or successful webhook does not prove
the coordinator received the report body, and delivery does not prove analytical understanding.

## 10. Output and transfer error contract

OC-D127 accepts the relevant common error-envelope semantics for this sprint's output/transfer
surfaces. It does **not** accept the entire fault-tolerance program or require a global error refactor.
The envelope records stable code, affected position/field, safe explanation, retry status, recovery
action and correlation ID. Preserve native cause metadata for diagnosis without leaking credentials
or raw sensitive exception content. Expose whether the host is already handling recovery.

| Failure class | Repair responsibility and retained facts |
| --- | --- |
| Correctable submission/reference/content failure | Give the responsible model safe, actionable detail for bounded repair under the admitted contract; preserve submitted revisions and findings. |
| Infrastructure, unavailable evaluator or access/authority failure | Host owns retry, wait/block and recovery routing under existing bounds and grants; the model cannot repair these by inventing authority or an evidence verdict. |
| Uncertain native effect or missing acknowledgment | Host reconciles the existing effect identity/receipt before considering another dispatch. Preserve committed work and separate native commit from protocol receipt recovery. |

Execution outcome, obligation fulfillment and invocation settlement remain distinct. Recovering a
post-execution failure must not blindly rerun successful cognition or committed writes. Bounded repair
and retry exhaustion follow the accepted durable-block rules. Give only recovery actions that are
actually available in the current state and authorized interface.

Source grounding: `application/subscriptions/coordinator_service.py:1–25` and `launcher.py:1–55`
provide current inbox foundations; the proposed common envelope is in
`docs/specs/fault-tolerance-2026-10/FAULT-TOLERANCE-PROPOSAL.md:748`. These sources establish design
inputs, not new implementation or selected-host qualification evidence.

## 11. Real fixtures and the general-use gate

OC-D128, accepted 2026-10-26, explicitly amends SV-D12 for bounded qualification runs. Once a
checkpoint's prerequisites are ready, run the owner's supplied real tasks with real agents and the
actual acquisition, ingestion and retrieval paths required by that fixture. Retain the Mission
Transcript, outputs and receipts; assess them against the stated functional goals. Repair any failing
owning layer, including schema/migration and service/runtime code, and rerun before advancing.

Synthetic, scripted and deterministic fault tests support diagnosis and engineering proof; they
cannot replace the required real functional acceptance. Mark which components are real and which
are doubles in every proof. A successful provider response, test suite or file-delivery receipt is
not itself a functional pass.

Routine research and general use remain gated until all four workflow systems, output contracts,
context transfer and full Deep Agents realization qualify for both AI Engineer and Biotech, including
the required composition/control/recovery boundaries. A qualification pass at one checkpoint does not
authorize general use, remove exact-use restrictions or certify unrelated workflows/providers.

The owner supplied three stress fixtures in OC-D178/179, explicitly **after this sprint's checkpoints**.
They do not replace the intermediate qualification below. Integrate their inputs, expected functional
criteria, applicable boundaries and bounded resource plan before execution. Preserve the actual task
and acceptance goals; any partial fixture slice proves only its explicitly identified scope. Required
human review and native-effect authority remain governed by their existing contracts. OC-D129/130
settle checkpoint placement and release below.

### 11.1 Accepted wave sequence

OC-D129 requires an evidence checkpoint after each wave. This orders implementation/proof; it is
not a calendar promise or a claim that every earlier fixture can exercise a later capability.

**OC-D131 clarification:** the waves are a capability/proof progression. Map the owner's later complex
fixtures to increasingly demanding checkpoints; do not simplify their actual goals to fit six fixed
task shapes. Adjust the detailed mapping transparently while preserving mandatory review/repair/rerun
and the general-use gate. Passing a partial slice never certifies the whole task.

| Wave | Required checkpoint result |
| --- | --- |
| W0 | Prerequisite schemas, trusted interfaces and durable settlement barriers fit together. Prove the foundations with deterministic/service/persistence checks before dependent runtime work. |
| W1 | One GoalDirected report with declared obligations, independent evaluation, settlement and the applicable native-write variant. First real workflow fixture; omission, held/unavailable evaluation and relevant recovery cases included. |
| W2 | Two-stage graph delivers only the exact selected report revision with required host state, purpose, placement, aggregate budgets, access and readiness. Exercise corrupt/missing bytes, denied access, budget refusal and held-input policy. |
| W3 | Multiple reports, per-member assessment, current-set accumulation and synthesis. Prove distinct identities versus revisions, coverage, mixed verdicts and exclusion of unrelated siblings. |
| W4 | Advanced recovery/evolution: source revisions, revocation, review, restarts, late receipts, assessment reuse, adoption and linked missions. Required exact replay and no duplicate effects. |
| W5 | Remaining workflow/composition/control boundaries, including Parallel Swarm and Evaluator Optimizer, and full Deep Agents qualification in both applications. Assess the general-use gate only with the complete required proof matrix. |

Basic durability, exact-use review, uncertain native-effect recovery, access and aggregate budgets
precede their **first affected use**; the W4 label cannot postpone them. Run AI Engineer then Biotech
at each applicable service boundary. Identify inapplicable cells with a reason, not a fabricated pass.
Map the owner's fixtures after they arrive; a slice's pass proves only its retained declared scope.

### 11.2 Engineering checkpoint release

OC-D130: a separate reviewing agent inspects retained Transcript, outputs, receipts and declared
functional criteria. The implementation coordinator may record a pass and release progression only
when every required criterion is met. Missing or ambiguous evidence keeps the checkpoint blocked.
Bring unresolved goals or required human decisions to the owner; a fixture may require owner release.

The review record binds fixture/version and criteria, relevant source/build/schema/configuration pins,
run/attempt identities, real versus doubled components, evidence links, criterion-level findings,
failed/blocked/unrun checks, repairs and rerun lineage, reviewer identity and release decision. A change
invalidating earlier evidence requires appropriate regression/review before relying on that pass.

Engineering release is separate from KS report-use decisions, native effect admission and scientific
review. A reviewing agent cannot grant reviewer authority or waive an application policy. A failed
functional criterion is repaired at its owning layer; required schema/code/service fixes are not
excluded merely because they span repositories. Unrelated broad redesign remains deferred.

## 12. Record and service contract revision

This section and §§1–11 explicitly revise the earlier [record design](../../gpt-6-astra-2026-10-24/CONTRACTS.md).
Its exact identities, canonicalization, concurrent revision, retention/erasure, adoption and closed
completion-expression requirements remain in force. The target protocols below are not current APIs.

### 12.1 Identity and records

Every record has a versioned closed schema, installation/application/tenant scope, attributable actor,
immutable identity/digest and exact referenced pins. Host coordinates include mission/run/activation,
unit/point, cycle/iteration when applicable, invocation/attempt/generation. Native entity identity,
native revision, retained observation and bytes digest remain separate. Permission is checked from
current authority, never inferred from a copied scope field.

| Record | Required contents and authority |
| --- | --- |
| Output contract | General form, media/schema constraints where applicable, conjunctive pinned templates/inline definitions, named guarantees and admitted validators/methods/policies, reference/member requirements and qualified extensions. |
| Output obligation | Identity/revision, owner, evaluation scope, exact contract, enforcement `required/expected/optional`, distinct-identity cardinality, coverage, applicability and explicit qualifying alternative/quorum rules. Required validity checks remain separate from enforcement. |
| Submission/revision | Idempotency key, original producer coordinates, logical deliverable/revision identity, exact candidate handles/custody, obligation/contract bindings, derivation and expected accepted head. The service binds origin; the producer offers candidates. |
| Assessment | Exact subject/revision or selected-set digest, requirement IDs and coverage scope, evaluator/method/policy/authority pins, retained evidence, findings/gaps and validity/freshness conditions. Preserve native evidence verdicts separately from common pass/fail/review/unavailable outcomes. |
| Output set/frontier | Versioned ordered exact members and obligation bindings, contract pins and set digest. The digest excludes assessments and mutable status, so attaching an assessment does not change the set assessed. |
| Fulfillment | Obligation revision and evaluation frontier, exact eligible members/check references, distinct count, coverage witness, disposition and unmet reasons. Missing submissions cannot erase declared obligations. |
| Invocation finalization | Saved execution result, settlement status, exact fulfillment references and pending effects/reviews. A blocked settlement survives restart and does not imply provider failure or authorize re-execution. |
| Sealed transfer plan | Effective configuration and selection authority, exact sources/representations, host state, consumer use, forms, resources, retention/recovery commitments, approved omissions and digest. Replaces overlapping canonical selection/delivery-plan authorities. |
| Delivery/readiness receipt | Plan and receiver-attempt identity, actual delivered members/digests/paths/read methods, permission probes/current access and readiness result. New attempts append receipts without mutating used plans. |
| Effect/lineage/adoption records | Exact admitted operation, current caller and effect key, native results/receipt, source revision and explicit adopter/consumer. Preserve producer, caller, receipt, revision, adopter, assessor and consumer as separate facts. |
| Review binding | Existing MC human task binds exact KS decision/use/audience/effect/policy and resolution/successor references. KS checks live reviewer authority; MC owns the durable wait and resumes only after successor/current-eligibility validation. |

Common fulfillment outcomes remain fulfilled, unfulfilled, blocked or canonically not-applicable;
expected/optional levels change completion consequences, not the evidence. A revision does not count
as a new deliverable. New drafts do not replace an accepted head. Promote with expected-head/generation
checks; conflicting successors stay inspectable. A reused idempotency key with different bytes refuses.
Revocation, withdrawal and staleness append facts and never silently select an older head.

### 12.2 Trusted service path

1. Admission pins contracts, capabilities, policies, evaluator roles and bounded resources. The host
   mints a per-live-invocation credential; KS authenticates it and binds origin before native intent
   canonicalization. Model-supplied role names cannot confer judge/reviewer authority.
2. A producing operation uses admitted KS steps to capture/prepare evidence, assemble assertions and
   register the exact report. Submitting that handle is an attributable offer, not verification or use
   approval. The final assistant message is not an output-reference channel.
3. Separate MC-hosted Deep Agents judge/auditor operations receive exact selected inputs under their
   own roles and budgets. They return independently attributable observations through trusted KS
   ingress. Deterministic assessment, evidence sealing and use decisions stay in KS.
4. KS records the exact report revision/use/audience/effect decision and authenticated reference.
   Required review creates an MC durable wait; an authorized KS review records a successor. Ungrounded
   disagreement holds. Unavailable evaluation is not evidence of falsity.
5. Native application admission rechecks exact use and normalized intent; apply produces native effect
   proof. Pending graph dispatch is not completed ingestion. Recover native-commit/protocol-receipt
   gaps by the same effect identity; perform required readback separately.
6. MC evaluates each declared guarantee/obligation and records fulfillment/finalization. A consumer
   checks its own use/readiness requirements and reuses only still-applicable assessments. Operational
   byte retrieval alone never proves official-use eligibility or native projection.

Judgment contracts retain premises, rationale, assumptions, uncertainty and relevant time horizon.
Use-specific policies define assessment and required review. A judgment's approval never changes its
fact-entailment flag. Shared KS owns this semantics; domain projections preserve it without inventing
a second policy authority. Exact thresholds and fixture expectations are authored explicitly when the
owner's fixtures arrive; none are manufactured as interview answers.

### 12.3 Materialization, revision and recovery

The one host operation accepts admitted task/instructions/contracts, effective activated profile,
authoritative workflow state, explicitly selected exact sources, receiver model/backend and resources.
It returns a sealed plan plus compact input/access index, attempt delivery/readiness receipts, or a
typed refusal. Boundary-specific builders supply first-invocation, next-cycle/iteration, dependent-stage,
review, continuation/fork and linked-mission state; there is no invented initial predecessor.

Authoritative mandatory state includes the current objective/contract, accepted set, unmet obligations,
verifier findings, invalidations, blockers and applicable effect/budget facts. A linked mission retains
its own goal, authority, budget and obligations; it revalidates selected handles under its credential.
Content transfer does not automatically adopt obligations or publication rights. Preparation outputs
retain their own producers and assessments. History is bounded opt-in; source prose remains data.

Governed revision proposals bind expected prior version, actor/authority, reason and affected subjects.
Admission checks delegated bounds; activation occurs at a recorded safe future boundary. Dispatched
invocations retain their sealed inputs unless explicitly interrupted/restarted. Requirement weakening
needs its proper authority; an executor cannot self-waive. Preserve prior failures and contract pins.
Track consumers become stale when relevant upstream revisions change, pending revalidation/rebuild;
snapshots retain exact historical inputs only while their policies/access permit. External corrections
are newly admitted effects, never rewritten receipts.

Crash/compaction redelivery uses retained exact sources and the sealed plan with a new receipt. Expired,
erased or revoked inputs append unavailable facts; a cache cannot bypass current restrictions. Required
recovery blocks or receives newly admitted inputs. Secure required availability for the declared
execution/recovery period without promising perpetual payload retention.

## 13. Sprint V conformance and required proof

Source rechecked on MC `1863017c` during this interview; no new runtime/paid qualification is claimed.
Historical tests retain their original limits. Full results/issue dependencies are in the work-item pack.

| Finding | Current status | Required repair/proof and earliest boundary |
| --- | --- | --- |
| RV-01 | Open: Deep Agents discards finalization result (`adapter.py:280`). | W0 durable settlement barrier, saved provider result and reconciler owner; W1 actual adapter/reducer proof, including late acknowledgment/restart without duplicate cognition/write. |
| RV-02 | One-report refusal fixed (`submission_service.py:258,477`); collection assessment absent. | Preserve truthful W0/W1 bound. Before W3 collection use: per-member revisions/assessments, mixed verdicts, reorder/duplicates/revisions and explicit aggregate policy. |
| RV-03 | Run-wide selection remains (`knowledge/toolset.py:376`). | Independent evaluator isolation before W1; full explicit predecessor/output/member/frontier selection before W2. Exclude disconnected siblings and stale generations; expand for W3/W4. |
| RV-04 | Trusted observation/seal/decision/review path uncomposed; memory decision store (`composition.py:588`). | W0 authenticated routes, durable exact decision resolution and review successors; W1 ordinary real-agent launch for both apps without test-only decision population. |
| RV-05 | Aggregate report-file allowance repaired (`toolset.py:392`); unified prompt plan absent. | Mandatory-state budgets/backend access before first affected invocation. W2 unified token/file/reserve accounting and exact readability/replay; W3 whole-collection budgets. |
| RV-06 | KS native apply precedes protocol receipt (`service.ts:606`). | Before first native-write claim: crash after commit, restart, reconstruct/recover exact native/protocol receipt, no duplicate write. W4 adds broader fault coverage. |
| RV-07 | Documentation corrected; no new runtime proof. | W0 current pins/source inventory; every gate preserves historical versus fresh proof and independent functional review. |
| RV-08 | Operational report read is not native/current-use proof (KS `service.ts:497`). | Before first official/native fixture: separate review and official purpose, exact admission/lineage/current eligibility; revoked official use blocks while authorized review remains possible. |

Advanced fulfillment, profile compilation, accepted current sets, assessment reuse, governed revisions,
linked adoption and selected-host wake remain implementation work. Existing records/ports are reused
where they fit; their presence alone does not satisfy these contracts or the general-use gate.

## 14. Earlier decision dispositions

Original rows remain historical in [SP-04 §8](../../../specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md#8-decisions-for-the-owner-recommendation-marked).
This table records later explicit refinements; it does not infer owner acceptance from code behavior.

| Original OC-D | Disposition | Current controlling decisions / retained requirement |
| --- | --- | --- |
| 1 | Revised | OC-D71/119 allow ordinary helpers without obligations; responsible workflow promises remain explicit. SV-D8 removes mandatory legacy auto-obligations. |
| 2 | Revised | OC-D115 general forms and pinned/inline substantive contracts. |
| 3 | Confirmed/clarified | OC-D118 three enforcement levels, separate from validity/use checks. |
| 4 | Revised | OC-D83 registered candidates remain; final message/output_refs is not read. |
| 5 | Revised | OC-D83 one progressive/final submit act; declared paths plus SUBMISSION.json only as a qualified degraded channel. |
| 6 | Durable intent confirmed; implementation revised | OC-D114 submission, fulfillment and finalization separate; historical release number is not reserved. |
| 7 | Confirmed with refined custody | OC-D64/70/114 preserve immutable accepted provenance and native lineage without requiring all canonical application bytes in MC. |
| 8 | Refined | OC-D52/54–61/124 mandatory state, bounded authorable history and per-consumer forms. |
| 9 | Refined | OC-D47/72 explicit release and qualifying any/quorum rules with settlement accountability. |
| 10 | Confirmed/refined | OC-D48 required fulfillment/default stop; a cycle/resource cap is not success. Retain workspace defaults subject to lane qualification. |
| 11 | Confirmed | OC-D52/119 host supplies mandatory verifier findings/current state. |
| 12 | Confirmed intent | OC-D99/101/116 exact sealed replay/readiness; point seeding alone is not delivery proof. |
| 13 | Implementation disposition retained for qualification | Retain required history/recovery under OC-D99/101; inspect actual archive/hydrator before wiring/removal. No new topology decision. |
| 14 | Revised | OC-D119 host state always; agent semantic handoff only where contracted. |
| 15 | Constrained | OC-D55/61/123/124 deterministic packing cannot weaken hard requirements. Heuristics are implementation policy. |
| 16 | Function retained; naming revalidated | Working, truthful retrieval paths required; do not promise a literal mission_fetch tool without qualification. OC-D125 defers global grammar. |
| 17 | Historical schedule retired; capability work retained | Recheck current provider version/adoption needs under OC-D76. Old version/sprint numbers are not current authorization; OC-D125 defers broad upkeep. |
| 18 | Confirmed/refined | OC-D76 common semantics, qualified versioned extensions and truthful refusal. |
| 19 | Revised | OC-D115 forms plus templates/inline contracts, not closed domain kinds. |
| 20 | Retained historical limits | Installation settings retain warning default 8 and cardinality maximum 64 absent explicit revision; no deployment proof implied. |
| 21 | Refined | OC-D83/89/127 reminder, narrow auto-association, bounded repair then block; host failures do not replay successful work. |
| 22 | Revised scope | OC-D71/119 optional contracted helper outputs/adoption; special helper tools/shape remain deferred. |
| 23 | Revised scope | OC-D71/72 retain required-child settlement and parent accountability; no universal report/join/must-review contract on ordinary helpers. |
| 24 | Trust intent confirmed | OC-D79 live service-authenticated origin; OC-D122 host materialization. Model/child state is evidence, never identity authority; exact state channels are engineering choices. |
| 25 | Refined | OC-D39/75/91 required declared guarantees gate; optional review may annotate. OC-D108..113 preserve evaluator/reviewer/use authority. |
| 26 | Confirmed scope | OC-D115 code_change form; no implicit push/merge/deploy authority. Codebase-commit fixtures are outside this first ladder. |

CS-D1..14 belong to the [coordinator proposal](../../../../../coordinator-surface-2026-10/PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md#7-decisions-for-the-owner).
OC-D125 is a scope decision, not blanket acceptance of its original details.

| CS-D | Disposition in this sprint |
| --- | --- |
| 1 | Broad grammar migration and aliases deferred. |
| 2 | New bundle layout/names/count deferred. |
| 3 | New executable bundle scripts deferred. |
| 4 | Effective node/configuration/binding/receipt inspection accepted; exact CLI spelling remains engineering. |
| 5 | Attributable positioned output/transfer events accepted; exact schema fields implement the joins. OC-D126 requires actual wake/replay proof. |
| 6 | Consistent required terms/coordinates in scope; broad glossary/nine-profile sweep deferred. |
| 7 | Unambiguous positions required; global CLI position grammar migration deferred. |
| 8 | Execution-relevant provider constraints/inspection in scope; exact provider-sheet show/hide list not newly accepted. |
| 9 | Generated provider-sheet upkeep/cadence deferred. |
| 10 | Exact input/output/fulfillment/transfer/receipt inspection accepted; full CLI redesign deferred. |
| 11 | Socket.IO CLI client deferred; durable observation/wake requirements accepted separately. |
| 12 | Legacy API retirement deferred. |
| 13 | ADR-0049 remains proposed; selecting durable inbox semantics does not authorize broad deprecation. |
| 14 | Global HTTP cleanup/renames deferred; no inferred approval of a new universal path-style rule. |

FC-Q14 carries forward settled deferrals: special helper tools/shape (OC-D71), physical topology
(OC-D77), broader coordinator redesign (OC-D125) and the global refactor. Necessary cross-layer fixes,
focused prompt materialization and both native application bindings remain required.

## 15. Final author, agent and operator walkthrough

This is the **integrated version for final confirmation**, incorporating accepted decisions through
OC-D176. The specialized code-integration engine and integrated preflight extension remain pending.
The owner has not yet confirmed this whole version or its work breakdown.

**Illustrative target behavior, not executable current manifest syntax, an actual Transcript or a
qualification receipt.** Exact profile/template aliases are resolved to immutable pins at admission.
The cases are explanatory, not substitutes for the owner's real fixtures. AI Engineer and Biotech
each use their own domain contracts/bindings and review rules; no cross-application link is assumed.

### 15.1 Author

The coordinator assembles a mission with the owner, then authors named goals, output promises,
workflow structure, input bindings, capabilities and limits. Reusable definitions and inline
definitions share the same admitted schema. The compiler extends EffectiveRunConfiguration and
exposes resolved pins, inheritance and hard constraints; there is no second configuration authority.

Each promise selects a general form (`text`, `structured`, `file`, `collection`, `reference`,
`code_change`, `effect_receipt`, `control_record`), substantive contract and required guarantees,
distinct-member coverage/cardinality, evaluation scope and enforcement. Required absence blocks;
expected shortfall remains visible under its completion policy; optional absence follows its policy.
None of these levels waives validity, access or permitted-use checks on supplied content.

The author separately specifies ordering prerequisites, named data dependencies, release rules,
conditional branch mode, input purpose and delivery. A satisfied ordering dependency does not
invent an input binding, and a data-ready input does not waive a separate ordering prerequisite.
Goal and mission acceptance explicitly name the required results; the last stage's success does
not automatically satisfy unrelated goals.

```yaml
transfer_defaults:
  profile: report-review@v1
stages:
  research:
    task: Produce the specified company evidence report.
    outputs:
      report:
        enforcement: required
        form: reference
        contract: <pinned evidence-report contract>
        guarantees: [shape, provenance, coherence, declared_coverage]
        cardinality: {min: 1, max: 1}
      native_write:
        enforcement: required
        form: effect_receipt
        requirements: [exact_admitted_effect, native_commit, native_readback]
  synthesis:
    inputs:
      report:
        from: research.outputs.report
        purpose: official_use
        release: complete
        revision_policy: track
        requirements: [exact_use_eligible, native_lineage, native_readback]
        delivery:
          body: {required_form: sandbox_file}
          assertions: {preferred_form: inline, allowed_forms: [inline, sandbox_file]}
          evidence: {access: on_demand, required_form: qualified_handle}
        history: none
    outputs:
      synthesis:
        enforcement: required
        contract: <pinned synthesis contract>
```

The report promise and native-write promise are separate. A report-only workflow omits the latter;
that does not remove the report's required quality checks. The author sees compiled settings and their
origins before activation. Numeric budgets and independent evaluator policy are admitted explicitly;
this example does not invent a new spending allowance or reviewer grant.

### 15.2 Agent and host sequence

```text
ILLUSTRATION — no actual run IDs or proof results
Host → producer: task, contracts, current state and bounded input/access index.
Producer → KS gateway: register exact report R7 and its evidence/ledger.
Producer → submit_output: obligation=report, items=[qualified R7 handle].
Host → independent judge/auditor operations: exact authorized evidence, pinned rubric/policy.
Evaluators → trusted KS ingress: attributable observations; producer cannot impersonate them.
KS → host: sealed assessment and exact-use decision D7, or hold/review-required.
If review required: MC waits durably; KS validates reviewer and writes successor D7b.
Host/admitted step → native service: apply exact authorized effect E7.
Native → host: commit/readback proof; a pending acknowledgment keeps settlement blocked.
Producer/host → submission reconciliation: exact effect receipt matches native_write obligation.
Host: record fulfillment for report and native_write; record invocation finalization separately.
Host → synthesis: seal selected R7 plan; deliver exact files/index; validate current use and readiness.
Synthesis → submit_output: new attributed synthesis S1 referring to consumed R7.
```

The receiver's initial prompt contains compact task/state/obligations/assertions/index. R7's body is
in a readable sandbox file; evidence is available through validated handles. Reading later consumes
context. The receiver gets no automatic whole-run history. If R7 is held, the illustrated official-use
consumer blocks. Other consumers need an explicitly admitted purpose/status contract, including
the permitted provisional-synthesis case in §16.7. The linked-mission exception is narrower: exact
held/draft transfer for authorized repair/review under §16.2.

### 15.3 Operator and dynamic change

Proposed output view (`missionctl run outputs <run>` is illustrative CLI spelling):

| Obligation/input | Exact selection | Evidence and outcome shown |
| --- | --- | --- |
| research.report | R7 | Per-guarantee findings, sealed KS assessment/use decision, fulfillment witness and original producer. |
| research.native_write | E7 → native revision | Native commit and separate readback, current caller/receipt; pending versus committed explicit. |
| synthesis.report input | R7 / plan P7 / receipt L7 | Consumer purpose/current eligibility, required placement, resources and actual backend readability. |
| synthesis.synthesis | S1 derived from R7 | Its own contract/assessments, exact source lineage, current or stale status. |

If the producer later submits R8, historical S1 still names R7. A tracking consumer becomes stale and
must revalidate/rebuild as required; R8 does not appear inside the running sealed R7 plan. A coordinator
may admit a permitted stricter policy for a future activation. An executor trying to weaken its own
required checks is refused. Required compaction recovery re-delivers the sealed selection with a new
receipt. Three revisions of R7 never satisfy a promise of three distinct reports.

A recommendation or forecast uses a distinct judgment contract and permitted-use policy; it is not
approved by calling it a factual report. In all cases, a completed model call, accepted report, allowed
use, committed native write, ready input and passed engineering checkpoint remain separate facts.

### 15.4 Three producers, a dependent consumer, and recursive replacement

Suppose A, B and C each owe a report about a distinct entity and D owes a relationship analysis.
The author binds D's three named inputs to those report obligations and requires coverage of all
three entities. A1/B1/C1 are exact submitted revisions, each assessed under its own contract.
D starts only after its release, coverage, purpose and actual delivery requirements pass. Its prompt
contains its task, promises, required state and a bounded exact input index. Report bodies are
readable files when required; evidence handles work through the receiving backend and grants.
Unrelated sibling reports, arbitrary workspace files and newer unselected revisions are excluded.

If B1 is held, official-use D waits. An explicitly authorized repair operation can receive B1 and its
findings as required inputs under a repair purpose. A and C remain retained successes. Repair B2
is a revision of B's deliverable, not a fourth entity. D's own assessment checks cross-entity
relationships and coverage; three completed producers alone cannot prove that task complete.

An authored two-of-three *alternative* group would be a different contract. It chooses the first
qualifying distinct set in durable eligibility order by default, with stable ties, then seals it.
It cannot satisfy an independent all-three coverage promise. A late result remains available for
later use without entering a running plan. Graph surplus branches continue within their admitted
budgets unless the author selects cancellation. Optional pending inputs are visibly omitted once
the required inputs and release conditions pass; a bounded wait must be authored.

Replace B's single operation with an internal Goal Loop or Stage Graph without changing B's
external promise or D's binding. The nested runtime keeps distinct activations, governor, state and
output lineage. It explicitly exports B's qualifying result; internal drafts are not automatically
parent outputs. An explicitly eligible early export may remain usable while the composite is still
incomplete or later fails, subject to its own use rules. It does not accept the composite. Flattening
the nested loop into stages is insufficient proof of recursive execution.

Within that Goal Loop, each executor sees authoritative goals, unmet promises, accepted current-set
index and selected repair work. The verifier evaluates the required whole current set, including
retained earlier successes. The continuing profile requires an attributed progress note at a normal
iteration handoff. An unrelated obligation may progress during a review wait; final goal acceptance
still requires every required promise. Missing crash-time notes are recorded, never manufactured.

### 15.5 Large collections, grouping and reduction

For discovery → retrieval → analysis → synthesis, discovery emits an exact collection revision.
Expansion freezes its members. A partition plan accounts for each member, permitted overlaps and
indivisible groups. MC keeps the complete durable inventory while admitting bounded activation
windows; all work need not occupy active contexts at once. Each slice uses the same transfer-plan
and readiness path as a single report.

A join of discovered sources to retrieval receipts selects a population policy: preserve the source
population with explicit gaps, reconcile both populations, or deliberately retain matches. Unexpected
duplicate matches produce conflicts rather than an accidental cross-product. Downstream obligations
can still require all discovered sources even when an intermediate join intentionally filters them.
Structural conflicts retain uncontested results and block only the uses requiring resolution.

A grouped reducer releases when that group's contract is met and contributor membership is closed.
The witness identifies exact expected contributors or trusted no-more-for-this-key facts from every
relevant channel. Seeing one finished batch does not close an unknown discovery population. Ready
independent groups can proceed; missing required contributions remain gaps. All-required, explicit
partial and quorum contracts retain distinct meanings.

MC may regroup a deterministic reduction into a tree only when its admitted versioned operation
qualifies that regrouping as result-preserving. Reordering requires its own qualification; effects
and duplicate handling remain separate. Semantic summaries require explicit decomposition with
preservation and coverage terms: justified independence, cross-partition reconciliation/validation,
or a limited final claim. Full item counts do not establish cross-partition semantic completeness.

The coordinator can inspect a skewed or oversized partition and propose a successor, or configure
an admitted agentic planning step to do so. Validate exact membership, preserved successes, atomic
groups, coverage and bounds. A successor is recorded new work; a retry keeps its original inputs.
If an indivisible item has no admitted viable execution/representation, block with the reason.
Pressure-aware prioritization awaits local worker evidence; hard resource ceilings and fairness
already apply. This version adds no automatic computation cache.

### 15.6 Swarm and Evaluator Optimizer

The four workflow families share output, input, authority and settlement contracts while retaining
their own control semantics. They are not alternate names for a flattened Stage Graph.

| Family | Context and release | Acceptance and failure behavior |
| --- | --- | --- |
| Stage Graph | Named dependency selection, explicit conditional all-matching or ordered first-match mode, exact all/any/quorum or incremental release. Unknown is not false; else needs conclusive false. | Explicit goal/composite criteria; surplus work continues by default within limits. Independently eligible exports do not imply final acceptance. |
| Goal Loop / GoalDirected | Next executor gets current accepted set, selected repair work and required progress state; verifier gets the required whole current set. | Goal-scoped waits preserve independent progress and retained results; bounded iteration/recovery rules and required fulfillment gate acceptance. |
| Parallel Swarm | Members get isolated task inputs. Convergence gets the exact selected eligible member set and gaps. All, quorum and best-effort are distinct; quorum may release immediately, best-effort waits for all terminal outcomes. | Default surplus cancellation remains the Swarm rule. Member results are internal unless explicitly exported; convergence output is the ordinary export. Quorum alone does not prove broader coverage. |
| Evaluator Optimizer | Distinct producer/evaluator identities, exact candidate and rubric, then findings-directed repair under bounded rounds. | Unavailable evaluation is not rejection; stale findings cannot accept a new candidate. No-progress/budget policies stop or block. An accept-best policy cannot bypass required hard gates. |

Full qualification demonstrates ordinary runtime execution, exact context, output fulfillment,
failure and restart for each family and the selected compositions. Parser acceptance or an existing
annex does not prove that the compiler/runtime realizes these semantics.

### 15.7 Mission links, child invocations and changing inputs

A mission link names exact eligible exports and a receiving contract. Both missions retain their
own goals, grants, budgets and obligations; content delivery does not adopt the source's obligations.
An explicit adoption records its actor, subject and authority while preserving the original producer.
Launch readiness, child execution completion, output eligibility and parent goal acceptance are
separate facts. Child Portal projections remain bounded; context delivery uses the applicable
receiving path and authority.

Within each application, ordinary supplies requires source owning-Goal acceptance by default or
explicit Mission Acceptance, plus the intended use approval. The explicit held/draft repair/review
exception allows exact selected material earlier under the receiving purpose and authority. Required
repair bytes still must be delivered; relabelling them optional does not make a repair ready.

If a chain consumer already runs on valid sealed inputs, upstream cancellation leaves it running
by default unless propagation was selected. It still obeys revocation, mandatory stops and its own
limits. An unreleased consumer still needs its release gates. Parent-owned spawned children retain
the cancel default; attached missions retain detach. These relationships are not interchangeable.

When an accepted tracked source revision changes during synthesis, the running invocation finishes
against its sealed selection when still permitted. Bounded authorized revalidation determines whether
its result may be current; rebuild only as needed and authorized. New collection arrivals normally
coalesce into one pending incremental activation behind one active synthesis. A permitted provisional
synthesis based on exact unchanged held content can be independently reassessed on later source
acceptance only under its authored policy. Neither case authorizes a generic freshness engine.

### 15.8 Hooks, context preservation and coordinator attention

An author may attach a bounded reaction to a durable output/workflow transition. Temporal dispatches
ordinary admitted execution with its own identity, budgets and replay handling. A duplicate event
cannot create duplicate logical effects. Operation hooks retain their event-specific capabilities:
a before-effect guard can block the effect; a post-effect callback cannot undo what already happened.

Hook scripts receive bounded snapshots plus admitted host-mediated reads. They stage notes/indexes
as candidates; the host validates attribution, content and safe-boundary installation. Model work,
semantic preparation, partition judgment and external writes use separate normal operations. Files
created by a hook do not fulfill output promises or rewrite sealed inputs on their own.

Before actual compaction, a hook may nominate bounded notes/exact references for preservation.
The host validates the proposal and independently preserves authoritative goals, obligations and state.
Continuation has its own identity and recovery process; neither mechanism grants arbitrary summary
replacement or requires hidden chain-of-thought. Repair forks select the historical point's exact
relevant drafts/files plus accepted-set index and findings. Missing historical bytes cause an
explicit readiness/recovery result, not substitution from today's workspace.

The coordinator inspects effective configuration, current outputs/coverage, decisions, waits,
selected plans, delivery receipts, partitions and controls. Default durable notices contain references,
status and gaps. Setup may opt into bounded excerpts or designated small outputs within receiving
grants and context budget. Test the selected host's idle wake, model-visible delivery, acknowledgment
and actual content read separately. A durable inbox row or a deterministic test client proves only
its own step. The integrated preflight extension remains the pending F20-19 choice.

### 15.9 Verification boundary and conversion

WORK-ITEMS maps this version to vertical behavior slices, real schema-fit work and W0–W5 proof gates.
Each slice demonstrates its observable path and relevant refusal/recovery cases. The owner supplies
the real missions after this interview. A separate reviewer assesses retained functional evidence;
all declared criteria must pass, with necessary repairs and reruns, before a checkpoint is released.
Full Deep Agents, all four workflow families and both applications gate ordinary general use.

The final confirmation covers this combined model, current scope, ADR dispositions, work granularity,
blocking relationships and proof seams. It is not a claim that any target behavior has been built,
nor authorization to start fixtures, migrations, runtime implementation or deployment in this session.

## 16. Workflow-specific context and hooks: detailed round

The following accepted subsections now define the target behavior. Interview-round references in
their introductory history preserve provenance; they do not reopen settled questions. The integrated
cross-workflow reading is §15, with scope and proof assignments in WORK-ITEMS.

OC-D132 requests precise workflow transfer/retrieval and hook behavior before final confirmation.
Existing defaults do not settle every join cutoff, incremental release, per-obligation wait, hook
state-access or event-feedback choice. Read the source-backed
[discussion record](WORKFLOW-CONTEXT-HOOKS.md) before asking or implementing these details.

Distinguish authoritative workflow state, exact content delivery, workspace restoration, provider
conversation/compaction, hook feedback and coordinator observation/retrieval. Each has different
authority and lifecycle rules. Provider stop is not durable settlement; a notification reference is
not full report loading; parser acceptance is not proof ordinary lowering executes a dependency.

### 16.1 GoalDirected working views and independent progress

Accepted 2026-10-26, OC-D133/134:

- Each next executor has distinct current accepted work, actionable repair work and optional history
  views. Objective, obligation/coverage summary, blockers and a bounded repair queue go inline.
  The complete exact current-set index must be accessible as a required readable file or authorized
  retrieval handle. Selected report bodies follow their input contracts; explicit per-consumer
  placement requirements may differ.
- Held, draft or rejected content retains its status and gaps. It enters the executor's working
  context only when selected for that task. A compact summary does not claim to contain every body,
  and an omitted inline member does not disappear from the exact current set.
- Independently runnable work may continue within admitted budgets while affected goal-scoped
  obligations durably await review or reconciliation. A waiting required obligation still blocks
  final goal acceptance. No retry or duplicate pending effect is authorized merely by this progress
  rule. Required invocation barriers and declared global pauses retain their force.
- Implement readiness and recovery at the affected-obligation level. This does not turn evaluation
  unavailability into a substantive rejection or discard completed cognition and accepted outputs.

For the A/B/C illustration: A1 remains in the accepted index, B1 remains held with its review wait,
and C can be researched when independent. A task selected to repair B receives B1 and its findings;
an unrelated task does not automatically load B1 or the entire history. Final acceptance still needs
all required obligations satisfied. Subsequent OC-D137/138 settle semantic notes and repair-fork
defaults in §16.3.

### 16.2 Linked and intra/inter-workflow interview scope

Owner steering 2026-10-26, OC-D135/136: explicitly deepen context transfer both within and between
workflows, including Linked Workflows. Before final confirmation, distinguish nested ProgramNodes,
Child Mission Invocation, linked-run composition, mission chains, continuation/fork and provider
subagents. Resolve concrete projections, named input selection, release/readiness, receiving authority,
incremental/revision behavior, explicit adoption, history/workspace access and recovery.

This adds FC-Q26; it does not pre-accept its recommendations. Common exact-selection, use, authority,
placement and budget rules already apply. Preserve the MC scheduling/fulfillment/materialization
boundary, shared KS report/evidence/decision semantics and native application bindings.
The owner requested a new session because of context size. The [detailed handoff](INTERVIEW-HANDOFF-2026-10-26.md)
preserves exact FC-Q22c/d and their subsequent answers, the linked-workflow source audit and the remaining conversion.
GPT 6 Astra discovery/exploration/research subagents are permitted in that session.

Accepted 2026-10-26, OC-D165..167:

- **Purpose-scoped repair/review exception:** an explicitly admitted linked mission within the same
  application may receive an exact selected draft or held report before source-goal acceptance.
  Preserve its status, findings, source identity and export lineage; validate receiving authority,
  purpose, budget and actual delivery. A held input required for repair remains required.
  This explicitly extends the blanket provisional cross-mission restriction in the invocation annex
  §9 for this purpose. Ordinary supplies still requires acceptance of the owning Goal by default,
  or explicit Mission Acceptance, plus applicable use approval. Report acceptance alone does not
  replace that gate, and receiving a draft does not accept an invocation, composite or mission.
- **Running chain consumer on upstream cancellation:** continue by default if the consumer has
  already started with valid sealed inputs, within its own admitted limits. Cancellation propagation
  must be explicitly selected on the link. Revocation, current input-use checks and mandatory stop
  rules remain in force. This changes the existing cancel_downstream default for this case; it does
  not authorize a not-yet-started consumer to bypass release gates. Spawned-child cancellation and
  attached-mission detachment remain the distinct canonical parent-cancellation defaults.
- **Application boundary:** linked workflows are within a single application, fully qualified in
  AI Engineer and in Biotech independently. Cross-application transfer or connection has **not been
  adopted as a feature**. It is not deferred implementation or merely outstanding qualification.
  No cross-application API, contract promise or implementation issue follows from this interview.
  A future proposal requires a separate feature decision. The owner explicitly confirmed this reading.

### 16.3 GoalDirected progress notes and repair-fork defaults

Accepted 2026-10-26, OC-D137/138, before the owner moved to a new session:

- The continuing GoalDirected default profile explicitly requires a compact, attributed progress
  note at each normal iteration handoff. Include work and sources tried, useful findings,
  unsuccessful approaches worth avoiding, unfinished work and suggested next actions with exact
  references. This is an explicit profile requirement under OC-D119; ordinary helpers are unaffected.
- The host continues to supply authoritative goals, accepted outputs, findings, waits and budgets.
  A progress note cannot rewrite those facts or authorize actions. On crash preserve the host
  checkpoint, record any missing note and follow contract-governed recovery; do not fabricate it.
- An explicitly requested repair fork defaults to the accepted-set index and findings plus the
  selected historical point's exact task-relevant working drafts/files, clearly labelled for repair.
  Pin selection and verify receiving access/availability. Missing historical snapshots cannot be
  replaced by today's workspace. Broader history remains off.
- Pending effects remain visible records requiring reconciliation. Copying context does not adopt
  obligations, duplicate writes or transfer authority. Existing precise-fork identity, lineage,
  historical-state and receiving-authority rules remain in force.

These two defaults are now accepted. The next session begins StageGraph and linked-workflow detail;
it must not re-ask FC-Q22c/d as unresolved questions.

### 16.4 Stage Graph alternative selection and unfinished branches

Accepted 2026-10-26, OC-D139/140:

- For an explicitly authored any/quorum alternative group, default to the first qualifying set in
  MC's recorded eligibility order, with a stable tie-break when several qualify together. Select
  the required number of distinct eligible members and seal their exact revisions before delivery.
  This cannot bypass coverage, independently required named inputs, receiving access or permitted use.
- Authors may instead declare a bounded wait and ranking policy. A threshold over alternatives
  does not make all graph inputs interchangeable or turn producer execution completion into acceptance.
- Later reports remain available for explicit later use; they cannot silently expand or replace a
  running receiver's sealed input selection. Revisions retain the existing tracking/staleness rules.
- Unfinished branches continue within existing admitted budgets by default. Cancellation requires
  an explicit author policy, respecting obligations and other consumers that still need the work.
  Assess and retain later outputs according to their contracts. Cancellation cannot erase usage,
  undo committed effects or bypass reconciliation and settlement accountability under OC-D72.

Example: an explicitly interchangeable two-of-three report group selects A1/B1 when they first
qualify. C continues; C1 may be assessed and retained for later selection but is not inserted into
the running synthesis. A bounded wait/ranking policy is an authored alternative to this default.
These are accepted target semantics, not a claim that the current ordinary graph builder implements them.

### 16.5 Optional inputs and scoped synthesis revalidation

Accepted 2026-10-26, OC-D141..143:

- Once required inputs and all release conditions pass, a pending optional input does not delay
  the consumer by default. Record its omission visibly in the receiving context. Waiting requires
  an authored bounded policy. This does not waive a separate ordering prerequisite or authorize
  an undeclared fallback for required content. The source can continue under OC-D140; late arrival
  does not silently alter the receiver's sealed inputs.
- For completed synthesis made stale by an accepted revision of a tracked source report, MC
  automatically arranges bounded, authorized revalidation of the affected result first. Reuse
  applicable prior evidence; KS retains evidence and use-decision authority. Restore current
  eligibility only when checks justify it. Rebuild only where needed and authorized; unavailable
  checks or exhausted limits leave a durable actionable block. Preserve historical source pins,
  results and effect receipts; revalidation neither rewrites past consumption nor waives revocation.
- **Current-sprint automatic revalidation scope is synthesis reacting to report revisions, plus
  the explicitly added held-source acceptance case in §16.7 (OC-D146).** General data freshness and
  invalidation automation are deferred to later sprints. Other automatic cases may be proposed,
  but require explicit inclusion; this decision does not authorize a general invalidation engine.
  Existing exact lineage, staleness, revocation and use checks remain required. The running-synthesis
  default is settled separately in §16.6.

### 16.6 Report revision during running synthesis

Accepted 2026-10-26, OC-D144: when a newer accepted revision of a tracked report arrives during
synthesis and the selected older revision remains permitted, let synthesis finish within its existing
budget against its sealed inputs. Retain the result and arrange the bounded authorized revalidation
under §16.5 before admitting it as current. Do not mutate prior consumption pins or silently inject
the new report body. Interruption/restart requires explicit authored policy at a supported safe boundary.
Revocation, cancellation and other mandatory stop rules apply independently. This remains within
the scoped synthesis/report-revision work; no general freshness or invalidation automation is added.

### 16.7 Incremental batching and provisional reassessment scope

Accepted 2026-10-26, OC-D145/146:

- For an explicitly authored incremental synthesis binding, default to one active synthesis and
  one pending next activation that combines new qualifying report arrivals. Seal its exact eligible
  selected set when released; enforce authored trigger, coverage, activation and budget limits.
  Running inputs remain sealed. Separate synthesis activations for each increment require explicit
  author policy. This addresses new collection members; report revisions retain §16.5–16.6 rules.
- Explicitly include the following additional case under OC-D143's scope rule: a permitted
  speculative synthesis used held report A1 and produced provisional S1; the exact A1 later becomes
  accepted without changed bytes. An authored policy may schedule bounded independent reassessment
  of retained S1. S1 becomes eligible only after its own required assessments and permitted-use
  decision pass; otherwise it stays held or needs authorized repair. Without that policy, await
  explicit action. Preserve exact source/derived lineage and status history; source acceptance is
  not derived-output approval. General freshness/invalidation automation remains deferred.

### 16.8 Conditional unknown and dynamic expansion membership

Accepted 2026-10-26, OC-D147/148:

- Missing/unavailable evidence for a conditional route defaults to a durable wait under authored
  limits. Else applies only when the relevant conditions are conclusively false. Exhaustion
  blocks/escalates. An explicit unavailable-evidence route may be authored, preserving unknown and
  respecting required evidence/use gates. OC-D162 now settles multiple-match routing below.
- Freeze the exact source collection revision and member set when a dynamic expansion starts.
  New discoveries do not silently add tasks. Further bounded incremental expansions require explicit
  policy. Preserve stable member identity, prevent accidental duplicates and do not silently remove
  or restart launched work. Respect the committed template/cardinality and other limits; changes
  requiring a successor Mission Revision retain that requirement.

Accepted 2026-10-26, OC-D162: every conditional route explicitly selects **all matching branches**
or **first matching branch in declared order**, directly or through a reusable admitted preset.
The compiled effective configuration exposes the mode and, for exclusive routing, the order.
Omission cannot silently select a universal mode. Earlier unknown/else semantics remain: an unknown
higher-priority condition cannot be treated as false to choose a lower-priority exclusive branch.
Branch multiplicity remains subject to admitted capabilities, budgets and coverage requirements.

### 16.9 Conditional routing: current state and rationale

OC-D149 asks for this explanation. Source evidence is distinct from accepted target behavior;
the examples below are illustrative design rationale, not owner fixtures or additional accepted syntax.

At the inspected MC `1863017c` baseline, the Stage Graph specification already names conditional
release over canonical typed facts (`01-STAGE_GRAPH.md:34–41,56–64`) and explicitly leaves detailed
conditional-branch semantics under interview (`:175`). The ordinary manifest `ProgramNodeBase`
(`domain/authoring/manifest.py:745–756`) has inputs/outputs, depends_on and all/any/quorum joins;
`ProofGateNode` (`:881–885`) has evidence, required disposition and on_reject. Compiled dependencies
and joins (`domain/authoring/contracts.py:533–599`) do not establish a general typed branch predicate.
`stagegraph_builder.py:67–100` still lowers dependency relationships to required/all bindings using
the first producer output. Interpreter threshold logic (`domain/programs/interpreter.py:180–215`)
is not arbitrary report-content routing. Existing gate types must not be presented as proof of the
complete proposed conditional-routing feature.

The continuation audit confirms no condition-to-branch compiler or runtime path: frozen definitions
(`mission_definition.py:321–336,582–610`), ordinary lowering (`manifest_lowering.py:329–332,367–386`)
and builder specs (`stagegraph_builder.py:27–37`) contain no general branch-selection/else field.
Human gates do execute (`adapters/temporal/workflows/stagegraph.py:1172–1200`). Event matching
(`domain/authoring/mission_watchers.py:271–300`)
uses scalar conditions to satisfy a named wait, not choose arbitrary graph branches. Proof-gate
grammar alone is not runtime support; `docs/knowledge/durable-controls.md` records that no dedicated
proof-gate runtime exists. This audit supports the explicit conclusion: general conditional routing
is specified but is not implemented in the inspected Stage Graph structure/execution path.

Proposed practical behavior: an admitted discovery/classification/assessment operation produces a
typed, attributed result with exact report/evidence references. The host validates the fields and
required assessment status. MC evaluates the authored predicate and records its inputs, result and
released/nonselected/waiting branches. A selected branch still needs its own exact input bindings,
access, use permission and budgets. Discovery prose alone cannot change graph structure or grant
authority; new structure requires a revision, while declared expansion uses its bounded template.

Illustrative benefits and limits:

- Knowledge investigation: a contracted discovery result establishes whether qualifying clinical
  study evidence exists in the declared search scope. A true result releases study appraisal; a
  conclusively false result releases the authored preclinical/evidence-gap analysis. Incomplete
  search is unknown, not proof of absence. KS/domain contracts govern evidence meaning and use;
  MC governs release and records the decision.
- Content: an assessed evidence package can release ordinary drafting or a declared evidence-repair/
  review path. Routing selects work; it never grants publication permission or relaxes the output promise.
- Codebase work: a validated change inventory indicating a schema migration releases migration and
  compatibility checks; a no-migration result follows the ordinary check path. Mandatory tests remain
  mandatory. The general MC workflow can use an admitted coding lane; this does not require assigning
  coding to Deep Agents or declaring that lane exclusively knowledge/content.
- Use routing where paths differ materially in work, capability, budget, required inputs or review.
  It avoids paying for irrelevant branches and provides an auditable, recoverable reason for each
  release. A small tactical choice inside the same task can stay with its executor or Goal Loop.
  Misclassification/unknown handling and maintained branch contracts are real costs; do not split
  every agent decision into a stage. Exact authoring syntax and branch multiplicity remain open.

### 16.10 Durable reactions and compaction preservation

Accepted 2026-10-26, OC-D171/172:

- Authors may attach bounded preparation/reaction steps to durable workflow/output transitions.
  Compile and dispatch them as ordinary admitted executions with explicit identity, authority,
  output obligations, budgets and restart/replay handling. Temporal remains the sole scheduler.
  This can prepare a selected report index or request context preparation after a recorded
  assessment. Hook attachment is an authoring convenience over the common execution path,
  not a second scheduler or authority to accept outputs. Distinguish provider stop from submitted,
  assessed, fulfilled, delivered and settled transitions.
- A compaction hook may propose bounded candidate working notes and exact references for host
  validation and preservation. Consume and validate the proposal explicitly; current observation-only
  callback behavior is insufficient. Preserve required authoritative state and references independently.
  The proposal cannot replace the entire summary, extract private reasoning or rewrite a used sealed
  transfer plan. Keep in-session compaction and continuation identities, triggers, budgets and
  respective validation paths distinct. The applicable host process decides how valid proposals
  enter its admitted preservation mechanism.

Hook read access, workspace write scope and effect execution are settled in §16.11.
Existing kernel-first ordering and event-specific enforcement/recovery requirements remain.

### 16.11 Hook access, preparation and effect boundaries

Accepted 2026-10-26, OC-D173..175:

- An admitted hook receives a bounded versioned event/state snapshot and may use explicitly scoped,
  host-mediated reads of selected outputs/workspace content. Validate current authority and account
  for access/resources. The script's private working directory is not implicit access to the agent
  sandbox, KS, full conversation, private middleware state or credentials.
- Hook-produced files are candidate preparation outputs. Stage them, then let the host validate and
  install them at a supported boundary with exact attribution and coordinated concurrency/recovery.
  Direct writes into live agent files are not selected. A created file cannot itself seal a transfer,
  establish acceptance or fulfill an obligation; qualifying output goes through its admitted
  submission and validation contract.
- Model work and external writes requested by a hook run as separate ordinary admitted operations
  with their own identity, grants, budgets and effect/recovery records. Hook-script execution itself
  is limited to bounded observation, guards and local preparation. This includes a request for
  semantic context preparation or partition planning without adding a directly effectful script
  execution surface. KS continues to own evidence, permitted use and native-operation semantics.

**F20-15 consequence, not another decision:** when configured, attributed persistent candidate
notes/index updates use these admitted output and validation paths, with exact source references.
They may be selected for later context under policy, but do not overwrite authoritative objectives,
obligations, acceptance or liability, and do not replace the required Goal Loop progress note.
No separate automatic memory subsystem is inferred.

## 17. Large-workload Stage Graph and map-reduce interview

**Current reading.** §§17.1–17.4 contain the selected contract and explicit scope dispositions.
The introductory frontier below is the earlier research agenda, not a list of unconditionally
required features. Pressure-aware scheduling remains undecided, caching is excluded and semantic
partition repair uses coordinator/admitted agentic proposals under validated bounds.

OC-D150, 2026-10-26, explicitly expands the interview (FC-Q27) to expressive Stage Graph structure
for big workloads. The owner's discovery → consolidation → source slices → processing → reduction
example is representative, not a requirement to hardcode that topology or an owner-supplied fixture.

The design frontier includes deterministic versus semantic reducers; collection identity and exact
membership; partition sizing and regrouping; per-member/partition/aggregate obligations and coverage;
data-ready dependencies versus global barriers; partial failures and selective repair; bounded fan-in
and hierarchical synthesis; concurrency, backpressure, fairness, budgets and retained state; and
which transformations a planner may apply without changing meaning. These are interview topics,
not preaccepted features or an implementation kickoff. Preserve MC orchestration, shared KS reusable
knowledge capabilities and domain-specific contracts; not all reusable work belongs in the MC kernel.

Existing design evidence to reconcile:

- `05-EXECUTORS_AND_DURABLE_CONTROLS.md` §4 already specifies registered versioned deterministic
  executor kinds with typed inputs/outputs and intent/receipt rules, including coalesce.
- `domain/authoring/manifest.py:824–840` declares deterministic executor kinds and node syntax.
  Syntax/specification do not establish a working distributed reduction implementation.
- `WORKFLOWS-COMPUTE-AND-COMMUNICATION-PROPOSAL-2026-10-23.md` §3.2–3.4 already proposes keyed
  coalescing, conflict/provenance outputs, partial coverage and hierarchical fan-in. It remains a
  proposal: do not copy its whole reducer taxonomy, sampling proof rule or syntax as accepted.
- Current `domain/programs/interpreter.py:229–259` scans/sorts stage candidates and limits releases
  by slots. Concurrency controls alone do not prove large-graph scalability. Scale claims require
  agreed workload envelopes and evidence; the owner's real fixtures still arrive after the interview.

FC-Q27a/b/c are accepted as OC-D151..153 in §17.1 below. Partition/work inventory
must not create a competing context-selection authority: eventual execution slices must feed the
existing canonical sealed transfer plan and its delivery/receipt path. Semantic entity resolution,
rank/judgment and synthesis remain distinct from exact mechanical transformations. Reusable knowledge
algorithms remain KS-owned where appropriate, invoked through admitted bindings.

Remaining frontier after these foundations: grouping/shuffle and multi-input joins; reducer input,
output, conflict/coverage/lineage contracts; algebra and ordering constraints on parallel/tree reduction;
semantic hierarchy and information-loss checks; memory/file/context limits and the case where even
one item does not fit; streaming versus barrier readiness; hot keys/stragglers and skew; selective
repair/repartition semantics; backpressure/fairness/budgets; exact reusable-result validity; and
workload sizing/proof. Prior accepted incremental/revision policies remain in force. Do not infer
blanket optimizer permission, algebraic equivalence of model summaries, or a general freshness engine.

### 17.1 Transformation, partition and scheduling foundations

Accepted 2026-10-26, OC-D151..153:

- Provide a reusable versioned library of exact-key union/deduplication, filtering, sorting, grouping,
  joins, projection, partitioning and validation, plus explicitly admitted custom transformations.
  These run as Deterministic Executor stages with typed input/output contracts and declared effects.
  Semantic entity resolution, evidence judgments and synthesis remain separately identified admitted
  knowledge/model operations. This adds no fifth workflow system and does not move domain logic into MC.
- A partition plan identifies exact members, coverage and permitted overlaps per slice. Preserve
  per-member outcomes and lineage by default so accepted successes remain useful and authorized
  repair can target missing work. Authors can declare indivisible groups when meaning demands it.
  Retry preserves the same logical slice; repartitioning is an explicit new plan with lineage.
  Feed exact slice selections through canonical transfer authority, not a competing delivery plan.
- Retain the complete exact durable work inventory; create/admit executable activations in bounded
  scheduling windows under capacity, budget, provider limits and fairness. Expose total, queued,
  active, completed and blocked work to coordinator inspection. Total workload need not all be active
  or fully materialized at once. Preserve inventory and progress across recovery.

Accepted 2026-10-26, OC-D163: each data join explicitly selects its result-population policy, directly
or through a reusable admitted preset: account for a named primary collection, reconcile both input
populations, or intentionally produce a matched subset. The selected contract specifies match
cardinality and unmatched-member treatment. Unexpected duplicate matches produce explicit conflicts,
not an accidental cross-product; missing required coverage remains visible and blocking where required.
An intentional matched subset does not silently waive a broader downstream coverage obligation.
This is dataset transformation semantics, distinct from a workflow all/any/quorum release join.

The 20,000-source/200-slice illustration is not an accepted scale target or fixture. Runtime sizing,
backpressure details, reducer semantics and functional/load proof remain to be specified and verified.

### 17.2 Conflicts, independent group readiness and qualified trees

Accepted 2026-10-26, OC-D154..156:

- When a structural collision has no authored resolution, preserve uncontested results and emit
  typed conflict records. Block only outputs/uses whose contracts require resolution. Explicit
  merge/precedence rules may choose a value with rule and source recorded; arrival order cannot
  silently decide. A faithful report of contradictory evidence may be acceptable under its own
  contract; do not conflate structural collision, evidence disagreement and universal rejection.
  Human resolution is one admitted route, not compulsory for every conflict.
- Release each grouped reduction when its own input contract is satisfied and membership is
  provably closed. Closure needs exact known contributors or trusted no-more-for-this-key facts
  from all relevant producers/input channels; otherwise the applicable discovery barrier remains.
  Frozen producer membership alone does not establish key completeness. Missing/failed required
  contributions remain gaps; terminal execution is not fulfillment. Preserve distinct all-required,
  explicitly partial and qualifying quorum semantics. Slow groups do not inherently block ready
  independent groups; global budget/capacity and other declared dependencies still apply.
- MC may automatically form a deterministic reduction tree only under an admitted versioned
  transformation contract qualifying grouping changes as result-preserving. Reordering requires
  separate qualification; order-sensitive operations retain order. Duplicate and external-effect
  rules are independent. Model-based hierarchical synthesis requires explicit authoring; summaries
  of summaries are not presumed equivalent. If even small groups cannot fit, select an admitted
  representation/algorithm or block; do not drop required inputs or force a two-member minimum.

These decisions define target contracts and proof obligations, not an implemented reducer engine.

### 17.3 Semantic decomposition preservation and coverage

Accepted 2026-10-26, OC-D164: whenever semantic work is divided into partitions or intermediate
summaries, its contract states which task-relevant information must survive and how cross-partition
dependencies or omissions are handled. Reusable admitted profiles may supply these terms.

The declared method may justify independence, require cross-partition reconciliation/validation, or
explicitly limit the final claim. Preserve the evidence, uncertainty, conflicts and exact original-source
access needed by that method. A worker processing every assigned member does not by itself prove
semantic task completeness, and a summary does not silently replace information the final task requires.
Fulfillment and final assessment check the authored coverage obligations and claim limits.

Examples are cross-company relationships, cross-module code behavior and rare decisive evidence lost
in summaries; none prescribes a specific mission schema. This applies beyond tasks labelled exhaustive,
without requiring proof of all real-world facts. Search/data scope and mission-specific criteria are
authored during setup. The relevant recommendation in §18.3 is now accepted within these bounds;
other critique recommendations remain unaccepted unless separately selected.

### 17.4 Partition repair and optimization scope

Accepted steering and version decisions, 2026-10-26, OC-D168..170:

- **Partition repair:** expose the poor partition, affected members, available evidence and resource/
  coverage problems to the coordinator, which can propose a governed successor, or configure an
  admitted agentic planning step to produce that proposal. Research partition judgment is not assumed
  to be a deterministic algorithm. Validate the proposal against admitted bounds, exact member
  accountability, coverage/preservation terms, retained successful work and indivisible groups.
  Record the replacement plan/activation and lineage; changed inputs are not a retry. Outside
  admitted bounds requires an authorized revision. An indivisible item without a viable admitted
  realization blocks. Existing deterministic mechanical partition transforms remain available;
  the proposed autonomous deterministic replanner is not accepted. Jev or another specific planner/
  model remains unselected, and agentic planning has ordinary admitted operation identity and budgets.
- **Pressure-aware scheduling:** leave the proposed producer-throttling/consumer-priority policy
  undecided until the dedicated worker intended for deployment is running locally and can supply
  representative resource/backlog evidence. Retain a review point in the work/proof matrix.
  This does not postpone existing capacity ceilings, bounded inventory/activation windows, fairness,
  budget enforcement or typed refusal when work cannot safely run. It neither authorizes a worker
  launch now nor promises implementation of this optional policy.
- **Automatic computation caching:** exclude the new same-run pure-transformation memoization
  subsystem from this version. Preserve required idempotency, effect reconciliation, recovery,
  selective carry-forward and explicitly recorded reuse. There is no new cross-run caching,
  model-answer equivalence or future delivery commitment.

## 18. Coordinator-perspective critical review

**Dated critique, with subsequent disposition.** §15 now supplies the integrated worked model
requested here; WORK-ITEMS assigns the implementation/proof gaps. The semantic preservation proposal
was selected as OC-D164; integrated preflight remains pending F20-19. This critique does not silently
adopt further capabilities or declare existing runtime gaps repaired.

Requested by OC-D157/158, 2026-10-26. This section is a critical assessment and recommendations,
**not owner-approved new behavior, a scope rollback or an implementation kickoff**. It considers
research, content, codebase work, mixed workflows and large workloads. The entity-report → relationship
example is one useful probe, not the target architecture. Accepted decisions through OC-D156 remain.

### 18.1 Verdict and coordinator powers

The contract has strong custody, exactness, authority, fulfillment and recovery foundations. It is
not yet one coherent coordinator programming model: the declarations, compilation rules, effective
plans and runtime implementations still diverge. Adding safe capability choices has increased its
potential expressiveness, but a sequence of local choices is not a compositional language. The
interview has advanced beyond its integrated worked model. The corrective move is to unify and
stress-test that model, not remove large-workload capability or install it on every mission.

As coordinator, the desired powers are:

| Power | Contract requirement / critique |
| --- | --- |
| Express outcomes independently of execution strategy | Name output obligations, coverage, quality and acceptance once; choose an executor, graph, Goal Loop or admitted composite without redefining the deliverable protocol. |
| Compile and preview a mission | Show effective bindings, release conditions, selected profile origins, capability fit, resource estimates/unknowns and obligations with no viable producer. Distinguish static guarantees from evidence needed at runtime. Current illustrative syntax is insufficient. |
| Compose independently understandable subprograms | Typed inputs, explicit exports, acceptance and budgets at each boundary; internal iterations/members remain inspectable without becoming implicit external inputs. |
| Control exactly what a receiver knows and can access | One authoritative selection and plan spanning prompt, files and retrieval; inspect inclusion/exclusion, exact revisions, purpose, access and budgets. Readiness and analytical sufficiency remain separate. |
| Choose and optimize execution topology | Conditional routes, fan-out, grouping/joins, per-group release, deterministic/semantic reduction and bounded hierarchy under explicit semantics. Cost optimization cannot quietly change the promised answer. |
| Diagnose and repair only affected work | Explain a blocked input/obligation, identify impacted consumers, retain successes, distinguish retry from repair/replan and recover effects before repeating work. |
| Adapt the admitted plan | Preview the consequences of a revision, apply at supported boundaries, preserve consumed history and distinguish existing, future and successor activations. This is a recommended integrated surface over accepted governance, not permission to mutate live sealed inputs. |
| Judge actual progress and completion | Inspect fulfilled coverage, unresolved conflicts, confidence/assessment limits, missing work and settled cost; compare against mission criteria. Completed nodes and delivered files are not sufficient proof. |

### 18.2 Concrete integration gaps and specification tensions

1. **Authoring expression is behind the target model.** Current manifest inputs/outputs and completion
   (`domain/authoring/manifest.py:707–756`) do not express the accumulated obligation enforcement,
   collection/current-head semantics, coverage/use requirements and transfer policies as one grammar.
   The worked examples in §§3.1 and 15 are explicitly illustrative. Produce one coherent authoring
   expression and compiled interpretation before treating these choices as a finished language.
2. **Named inputs are not reliably realized.** `stagegraph_builder.py:67–100` selects the producer's
   first output and emits required/all dependencies. `application/programs/stage_inputs.py:28–35`
   requires an explicit depends_on even for named sibling data. `application/context/pack_service.py:1163–1172`
   can choose a sole same-producer alias when its output slot does not match. These paths can diverge
   from the named contract; scale planning cannot compensate for wrong-source selection.
3. **Selection still has competing runtime paths.** The packet path consumes dependency bindings,
   but `application/knowledge/toolset.py:365–387` selects run-wide finalized reports except the current
   operation. Unrelated siblings/history may enter delivery. OC-D116's single sealed plan must become
   the actual authority for both prompt and sandbox paths, with exact-membership negative proof.
4. **Collection/submission/fulfillment units are not integrated.** `submission_service.py:477–483`
   explicitly refuses report collections; `:258–268,510–529` assesses latest submissions per obligation.
   The target's distinct members/revisions/coverage/accepted heads (§12.1) needs one operational model
   used by agents, Graph, Goal Loop, reducers and composite exports. Batching must not invent another
   output or fulfillment protocol.
5. **Mission acceptance must be explicit, not topology-derived.** Current lowering assigns required
   goal ownership to the last stage serving it, or the last stage by default
   (`manifest_lowering.py:300–313`). This inspected mapping is an approximation, not proof that any
   last-stage success establishes all upstream or cross-cutting mission obligations. The compiler
   needs an explicit completion/coverage interpretation with observable witnesses.
6. **Incremental exports and final composite acceptance need reconciliation.** Canonical
   `00-EXECUTION_PROGRAM_MODEL.md:199` says accepted is the only outcome projecting outputs; accepted
   incremental delivery allows qualifying deliverables before producer completion. Separate an
   admitted intermediate export from the final composite result and define its liability/eligibility
   consistently. Do not silently remove either earlier rule or treat every inner artifact as exported.
7. **Graph/Goal Loop interchangeability is a target, not baseline proof.** The canonical nesting
   contract (`00-EXECUTION_PROGRAM_MODEL.md:117–132`) permits explicit typed composites. Current
   lowering warns that a nested Goal Loop becomes one graph stage because there is no nested-loop
   family (`manifest_lowering.py:315–326`). Goal execution sends the latest executor refs to the verifier
   (`adapters/temporal/workflows/goal_directed.py:530–545`), not the target goal-wide current set.
   Keep boundary contracts common while preserving different control semantics and required state.

Source findings are read-only at MC `1863017c`; no new runtime test or failure reproduction is claimed.

### 18.3 Semantic correctness that scheduling cannot prove

- A data dependency binds selected content; an ordering dependency constrains release; a gate checks
  recorded facts; delivery makes exact content accessible; fulfillment assesses promises. Do not
  collapse them into a single arrow or giant node-success boolean. Existing common contracts support
  the distinction, but compilation must make it operational.
- Reduction may mean exact mechanical combination, evidence-based entity resolution, semantic
  synthesis or governed code integration. All can be stages with obligations; they do not share
  interchangeable correctness rules. Deterministic execution alone does not establish scientific
  truth, correct entity identity, or suitability for an intended use.
- Exact partition coverage does not prove semantic coverage. Processing every company exactly once
  may miss relationships across partitions; checking every code file may miss cross-module behavior;
  summarizing every document may erase a rare decisive fact. Decomposition requires an explicit
  independence justification or cross-partition reconciliation/validation obligations. This is a
  design requirement now accepted in §17.3 (OC-D164), not proof that a particular task is complete.
- Explicit semantic hierarchy is necessary but insufficient. Intermediate contracts must state what
  information/evidence the final task needs preserved, how uncertainty/conflicts travel and how final
  workers can inspect original exact sources. Sampling or successful delivery alone cannot prove an
  exhaustive claim. Claims of completeness must be bounded by an actual declared search/data scope.
- Context is an executable contract over instructions, current state, input index, exact content,
  retrieval capability and budgets. A readable sandbox is infrastructure readiness; adequate reasoning
  and promised coverage are output-assessment matters. Avoid both whole-run dumps and hidden lossy
  summarization. The coordinator should be able to inspect why each item is present or absent.
- Optional scale capabilities must remain available without becoming mandatory intermediate stages.
  Simple direct transfers, typed reducers, nested loops and large mapped workloads should be instances
  of the same model. The presence of a partition/inventory feature does not require every mission to
  use it. Shared KS reusable/domain responsibilities remain unchanged.

### 18.4 Recommended consolidation and proof work

Before more local defaults, assemble a coordinator-readable contract model separating authored
program, compiled requirements/behavior, sealed invocation inputs and observed outcome/fulfillment.
Use common node boundaries: named typed inputs, chosen behavior, output obligations, acceptance,
governors and revision policy. Bindings express exact source selection, coverage/release, intended use
and delivery requirements; they do not duplicate output promises or transfer authority.

Stress-test the same external contract across an atomic executor, a nested Goal Loop, a multi-stage
subgraph and partitioned execution. Include research, content and codebase examples, required/optional
inputs, held review material, partial success, incremental exports, failures, cancellation and bounded
resource overflow. Preserve the original owner-fixture timing and no invented functional proof.

Recommended proof order: exact named-output → submitted collection/current set → fulfillment →
single transfer selection → real backend readiness → consumer obligation/mission acceptance;
then nested/incremental composition; then load/recovery and semantics-preserving optimizations.
This is an assessment of dependencies to reconcile with the accepted wave plan, not a replacement
schedule or authorization to start implementation. Coordinator inspection should answer why a node
is ready/blocked, what exact evidence it will receive, what a proposed change affects, and what
remains unfulfilled, using the same records the runtime enforces.

## 19. Final interview limit and conversion direction

Owner steering OC-D159..161, 2026-10-26: finish this interview → specifications → issues process.
Select a coherent version of Stage Graph, the other workflow systems and linked workflows now;
extensive mission-specific interviews and coordinator setup will happen before any real launch.
The critical review in §18 is input to that bounded decision, not authority to build every desired
coordinator power or solve all future missions in this sprint.

The final interview has a hard maximum of 20 substantive questions, including follow-ups and final
confirmation. Research/source inspection and specification drafting are agent work, not questions
charged to the owner. The prepared [instrument](FINAL-INTERVIEW-20-QUESTIONS-2026-10-26.md) contains
20 candidate slots, initially unanswered at handoff. F20-01..03 were subsequently accepted as
OC-D162..164 and folded into §§16.8, 17.1 and 17.3; the instrument carries live accounting.
Avoid disguised multi-question bundles; substitute
an unused slot when an essential follow-up arises, and do not ask a twenty-first question. Do not
silently assume acceptance to satisfy the cap. Resolve implementation mechanics from accepted
contracts; keep optional unselected behavior unavailable or explicitly deferred in the proposed version.

The [final handoff](FINAL-INTERVIEW-HANDOFF-2026-10-26.md) preserves the original resumption instructions;
the live instrument owns current accounting. The [session record](SESSION-ANSWERS-2026-10-26.md)
preserves the preceding chat's messages through OC-D161. IA-09 remains the canonical
decision register, now through OC-D181, next OC-D182. The owner now requests final synthesis and actual
issue conversion in the [new session](FINAL-SPEC-AND-ISSUE-SYNTHESIS-HANDOFF-2026-10-26.md). The prior
integrated confirmation question was not asked; no answer is inferred. No separate chat was created.
