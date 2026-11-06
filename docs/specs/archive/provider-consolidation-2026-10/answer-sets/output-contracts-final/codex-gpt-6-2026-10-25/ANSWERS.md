---
type: Interview Answers
title: "output-contracts-final, sitting I: the owner's answers"
description: "The decisions the owner took in sitting I of INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md on 2026-10-25, each with its id, the owner's words, what it changes, what it becomes (ADR, spec section, glossary term, Linear issue) and where it was folded in. Open while the sitting runs; final when every decision has a destination."
tags: [mission-control, interview, answers]
interview: ../../../INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md
sitting: "I"
date: 2026-10-25
status: final
---

# output-contracts-final, sitting I: answers

<!-- final-output-contracts-2026-10-26 -->
**Final conversion, 2026-10-26:** [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) and the [implementation packet](../../../../../provider-consolidation-2026-10/sprint-oc/README.md) now carry the final specification, five ADRs and 31 published work items. [Every decision destination](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) is recorded; source quotes and historical checkpoint language are retained. No runtime qualification is claimed. F20-18/19 remain unselected, with no fabricated answers. Older resume/planning instructions below are historical.


**Current entry point:** [final specification/issue synthesis handoff](FINAL-SPEC-AND-ISSUE-SYNTHESIS-HANDOFF-2026-10-26.md),
through OC-D181, next OC-D182. The owner now requests synthesis/publication and supplied the fast-path
mandate, post-sprint stress fixtures, evaluation loops and quality requirements. The
[latest complete owner message](OWNER-DIRECTION-AND-STRESS-FIXTURES-2026-10-26.md) controls.
The capped round remains 17 asked/15 answered; Q16/Q17 (F20-18/19) have no direct answers and F20-20
was not asked. Do not fabricate acceptance or restart the old question sequence automatically.
[Earlier resumed-session owner record](SESSION-ANSWERS-2026-10-26.md) preserves the preceding chat.
Earlier stop/resume paragraphs below are historical. F20-01..03 and F20-05..07 are answered as
OC-D162..167; F20-07 corrects the proposal: cross-application linking is unadopted, not deferred.

**Fresh final-interview research, 2026-10-26:** [source recheck and dispositions](FINAL-INTERVIEW-RESEARCH-2026-10-26.md)
completed before questioning. Existing effective configuration/preflight are extension points;
all four runtime workflow behaviors and actual coordinator-host wake still require qualification.
F20-04 remains skipped as settled. No recommendation in this research is an owner answer.

Instruction: `INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md` (front matter `interview:`). Recorded by the interviewing agent on
2026-10-25. **Status `open`** while the sitting runs; set `final` when every decision below has a
**Becomes** and a **Folded** entry, which `program_ledger.py check` then enforces.

How to fill it: one row per decision, in the order asked. Quote the owner's words in **Answer**; put
the agent's reading in **What it changes**, never in **Answer**. A decision the owner did not answer
goes under *Assumptions*, not in the table.

**Owner-requested overnight stop, 2026-10-25:** answers are saved through OC-D125. The interview
remains open. Resume only when the owner messages to continue; start from the exact
[checkpoint](CHECKPOINT-2026-10-25.md). FC-Q20b and FC-Q12 were asked but not answered.

**Resumed at the owner's request, 2026-10-26:** FC-Q20b and FC-Q12 are now answered as OC-D126/127.
The overnight paragraph records the historical stop. OC-D128 permits real qualification fixtures;
OC-D129/130 settle checkpoint sequencing and independent review/release. OC-D131 clarifies flexible
fixture mapping; OC-D132 adds detailed workflow/hook/coordinator-output rounds before FC-Q15. No
final model confirmation has been requested or inferred. OC-D133/134 now settle the GoalDirected
working-set views and independent progress during goal-scoped waits. The owner stopped this session
for context length and requested a new-session handoff: OC-D135/136 add Linked Workflows and deep
intra/inter-workflow context, with GPT 6 Astra discovery subagents permitted. Resume from the
[detailed handoff](INTERVIEW-HANDOFF-2026-10-26.md). Before moving sessions, the owner answered
FC-Q22c/d as OC-D137/138 and requested that they be documented. Start the next session with StageGraph,
then linked/nested composition (FC-Q26), hooks and coordinator delivery. Next unused decision ID:
OC-D139 at that checkpoint. The resumed session has now accepted FC-Q23a/b as OC-D139/140.
FC-Q23c/d are accepted as OC-D141/142; OC-D143 records the owner's explicit scope limit.
FC-Q23e is accepted as OC-D144; FC-Q23f/g as OC-D145/146; FC-Q23h/i as OC-D147/148.
OC-D149 requests source-backed conditional-routing explanation and justification. OC-D150 adds
the large-workload Stage Graph/map-reduce interview branch FC-Q27. FC-Q27a/b/c are accepted as
OC-D151..153: transformation extensibility, partition/member accountability and bounded scheduling.
FC-Q27d/e/f are accepted as OC-D154..156: conflicts, independent group readiness and qualified
deterministic reduction trees. Next unused ID: OC-D157.
The owner subsequently requested a critical coordinator-level review before further feature questions
(OC-D157/158). OC-D159..161 now constrain the final interview and request its transfer packet.
Next unused ID is OC-D162; no additional product defaults are inferred.
The remaining interview agenda is still open.

## Decisions

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D106 | Owner opening directive: how must checkpoint acceptance work? | "WE MUST stop at certain checkpoints and run real fixtures -> analyze the transcription -> determine if it meets our functional goals -> IF NOT we fix it at every level (That includes database migration, code change, etc)" | 2026-10-25 | Mandatory fixture, transcript, functional-goal and repair gates in the runtime plan; fixes may change any owning layer and schema. Checkpoint placement and pass criteria are settled in FC-Q13/21; no fixture execution is claimed here. | spec IQ-07 §1.3; revised CONTRACTS/WORK-ITEMS checkpoint matrix at interview close; final conversion: OUTPUT-CONTRACTS §§12; OVE-169, OVE-186, OVE-168, OVE-185 | [IQ-07 §1.3](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#13-mandatory-fixture-and-repair-checkpoints-owner-directive-2026-10-25); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D107 | Owner opening directive: who supplies the fixtures and when? | "I will provide those exact fixtures after the interview and then you can integrate them. They are real world knowledge work fixtures concerning ai engineering / ai companies and biotech science and companies." | 2026-10-25 | Reserve explicit owner-fixture integration after the interview for both domains. Do not substitute invented tasks for the owner's fixtures or claim their acceptance before they arrive. FC-Q21 must resolve their relationship to SV-D12 explicitly. | spec IQ-07 §1.3; revised CONTRACTS/WORK-ITEMS fixture inputs at interview close; final conversion: OUTPUT-CONTRACTS §§12; OVE-169, OVE-186, OVE-189, OVE-190, OVE-191, OVE-192 | [IQ-07 §1.3](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#13-mandatory-fixture-and-repair-checkpoints-owner-directive-2026-10-25); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

`Becomes`: `ADR-NNNN`, `spec <file> §n`, `GLOSSARY <term>`, `OVE-n`, or `none (reason)`.
`Folded`: the link to the document edited to carry the decision, or `n/a`.

### Round 0: semantic execution host

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D108 | FC-Q16a: first semantic judge/auditor host? | "Yes — separate MC-hosted Deep Agents judge/auditor operations; KS owns evidence sealing and use decisions. (Recommended)" | 2026-10-25 | First composition uses separate MC-hosted Deep Agents evaluation operations and authenticated KS ingress. KS retains sealing and use-decision authority. Implements one host choice allowed by OC-D98; evaluator failure/review policies remain to be answered. | spec IQ-07 §1.4; revised CONTRACTS service composition at interview close; final conversion: OUTPUT-CONTRACTS §§5; OVE-165 | [IQ-07 §1.4](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#14-first-semantic-execution-host-oc-d108); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round 0: recovery, review and disagreement

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D109 | FC-Q16b: evaluator timeout/unavailability and cancellation? | "Preserve work, retry within policy, then durably block for recovery. (Recommended)" | 2026-10-25 | Preserve report/completed work; bound retries by authored time/spend policy; exhaustion durably blocks affected work with reason and recovery action. Evaluation unavailability is not an evidence verdict. Cancellation stops further evaluation and fences late results from automatically reopening acceptance. | spec IQ-07 §1.5; revised CONTRACTS recovery contract; final conversion: OUTPUT-CONTRACTS §§4, 5; OVE-165, OVE-166 | [IQ-07 §1.5](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#15-recovery-review-and-disagreement-oc-d109111); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D110 | FC-Q17a: exact-use decisions and durable review wait? | "MC owns the durable review wait; KS owns reviewer authority and successor decisions. (Recommended)" | 2026-10-25 | KS persists the exact revision/use/audience/effect decision and supplies an authenticated reference resolvable after restart. MC owns durable review wait/notification. KS checks reviewer authority and records the successor; MC resumes after verifying it and current eligibility. | spec IQ-07 §1.5; revised CONTRACTS service and review contract; final conversion: OUTPUT-CONTRACTS §§5; OVE-165 | [IQ-07 §1.5](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#15-recovery-review-and-disagreement-oc-d109111); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D111 | FC-Q17b: may evaluator disagreement alone reject? | "Disagreement holds; automated rejection needs grounded evidence or an integrity failure. (Recommended)" | 2026-10-25 | Preserve disputed/held disposition for ungrounded model disagreement, with bounded evidence repair or authorized adjudication. Automated rejection requires grounded contrary evidence or a failed integrity check. This does not remove an authorized human reviewer's separate rejection authority. | spec IQ-07 §1.5; revised CONTRACTS assessment/dispute contract; final conversion: OUTPUT-CONTRACTS §§5; OVE-165, OVE-178 | [IQ-07 §1.5](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#15-recovery-review-and-disagreement-oc-d109111); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round 0: judgment outputs and review policies

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D112 | FC-Q17c: may official outputs contain recommendations/forecasts under a distinct judgment contract? | "Allow explicit judgment contracts with use-specific policy and required review. (Recommended)" | 2026-10-25 | Revises the Sprint V OQ4 blanket official-use exclusion: permit exact judgments only under an admitted use policy, with supporting premises, rationale, assumptions, uncertainty, relevant time horizon and independent assessment plus required review. Judgment approval is not fact entailment. Qualified human sign-off for consequential scientific use remains required. | spec IQ-07 §1.6; Sprint V design §10.2 OQ4 revision pointer; revised CONTRACTS judgment/use-policy contract; final conversion: OUTPUT-CONTRACTS §§2, 5; OVE-165 | [IQ-07 §1.6](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#16-judgment-outputs-and-review-policies-oc-d112113); [Sprint V OQ4 disposition](../../../specs/SPRINT-V-DESIGN.md); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D113 | FC-Q17d: may authorized mission authors/coordinators select review policy? | "Allow constrained policy selection and stricter requirements; enforce application minimums. (Recommended)" | 2026-10-25 | KS maintains admitted, versioned policies for required review and qualifying reviewer grants. Authorized authors/coordinators select within application/use constraints or tighten requirements; cannot weaken mandatory review or grant authority. Pin the selected policy in the decision; current revocations apply. MC presents/waits on the resulting task. | spec IQ-07 §1.6; revised CONTRACTS policy admission and review contract; final conversion: OUTPUT-CONTRACTS §§3, 5; OVE-163, OVE-165 | [IQ-07 §1.6](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#16-judgment-outputs-and-review-policies-oc-d112113); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round A: fulfillment, forms and transfer authority

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D114 | FC-Q1a: durable fulfillment distinct from submission and finalization? | "Persist submissions, fulfillment decisions and invocation finalization separately. (Recommended)" | 2026-10-25 | Preserve attributable submissions/revisions; persist system fulfillment per obligation/evaluated result with exact accepted members, checks, count, coverage and unmet requirements. Keep invocation execution/settlement separate. Omitted submissions cannot remove declared promises. Reconciles OC-D6 with Sprint V's submission/finalization tables. | spec IQ-07 §1.7; revised CONTRACTS records; GLOSSARY Obligation Fulfillment; final conversion: OUTPUT-CONTRACTS §§2, 4; OVE-163, OVE-166, OVE-170 | [IQ-07 §1.7](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#17-fulfillment-forms-and-transfer-authority-oc-d114116); [glossary](../../../../../../../GLOSSARY.md); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D115 | FC-Q4: kernel forms versus domain kinds? | "Use general forms with pinned templates or explicit inline contracts. (Recommended)" | 2026-10-25 | Use text, structured, file, collection, reference, code_change, effect_receipt and control_record forms. Domain/report/judgment/handoff types use pinned templates or inline contracts with admitted validators; preserve control authority/invariants. Revises closed domain-kind wording in OC-D2/19, preserving composability and admitted validation. | spec IQ-07 §1.7; SP-04 §8 revision; revised CONTRACTS forms; GLOSSARY Output Form; final conversion: OUTPUT-CONTRACTS §§2; OVE-163 | [IQ-07 §1.7](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#17-fulfillment-forms-and-transfer-authority-oc-d114116); [SP-04 §8](../../../specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md#8-decisions-for-the-owner-recommendation-marked); [glossary](../../../../../../../GLOSSARY.md); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D116 | FC-Q1b: consolidate selection and delivery planning? | "Use one canonical sealed transfer plan, with separate delivery/readiness receipts. (Recommended)" | 2026-10-25 | Replace overlapping context_selection and M04 planning authorities with a canonical sealed plan preserving exact selected revisions, selection authority, required state, delivery forms and budgets. Separate attempt receipts prove delivery/readability. Clean rebuild does not waive new-system restart/replay. | spec IQ-07 §1.7; revised CONTRACTS transfer plan and receipts; final conversion: OUTPUT-CONTRACTS §§6; OVE-164 | [IQ-07 §1.7](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#17-fulfillment-forms-and-transfer-authority-oc-d114116); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round A: native effects, enforcement and handoffs

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D117 | FC-Q1c: general step outputs versus special domain_effect kind? | "Use general step outputs and effect-receipt contracts with explicit native-effect proof. (Recommended)" | 2026-10-25 | Retire the proposed special domain_effect output kind in favor of qualified step-output handles and effect_receipt contracts. Preserve exact admitted operation, native result and receipt provenance. Produced report, authorized use, committed native effect and readback are distinct; pending dispatch cannot satisfy applied-write requirements and required readback is independently checked. | spec IQ-07 §1.8; DP-D4 disposition; revised CONTRACTS effect guarantees; final conversion: OUTPUT-CONTRACTS §§2, 5; OVE-167 | [IQ-07 §1.8](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#18-native-effects-enforcement-and-handoffs-oc-d117119); [domain supplement](../../../proposals/DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D118 | FC-Q3a: preserve three enforcement levels? | "Keep required, expected and optional, separate from output-validity checks. (Recommended)" | 2026-10-25 | Confirm OC-D3: required unmet obligations gate completion; expected unmet obligations record visible nonblocking shortfalls; optional absence neither blocks nor warns. Levels do not make invalid/unauthorized outputs acceptable; required validity/use checks apply before acceptance or consumption. | spec IQ-07 §1.8; SP-04 §8 disposition; revised CONTRACTS obligation enforcement; final conversion: OUTPUT-CONTRACTS §§2; OVE-163, OVE-170 | [IQ-07 §1.8](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#18-native-effects-enforcement-and-handoffs-oc-d117119); [SP-04 §8](../../../specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md#8-decisions-for-the-owner-recommendation-marked); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D119 | FC-Q3b: host state versus agent-authored semantic handoff? | "Always assemble authoritative host state; require semantic handoffs where explicitly contracted. (Recommended)" | 2026-10-25 | Host always assembles boundary-required objective, accepted outputs, verifier findings, unresolved obligations, blockers and applicable effect/budget state. Agent explanations/summaries are attributable checked outputs when explicitly required by workflow/profile. Clarifies OC-D14; retains OC-D71 optional ordinary-helper obligations. | spec IQ-07 §1.8; SP-04 §8 disposition; revised CONTRACTS boundary state/handoff; final conversion: OUTPUT-CONTRACTS §§6, 7; OVE-164, OVE-169 | [IQ-07 §1.8](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#18-native-effects-enforcement-and-handoffs-oc-d117119); [SP-04 §8](../../../specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md#8-decisions-for-the-owner-recommendation-marked); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round B: tentative profile and accepted consumer/materialization decisions

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D120 | FC-Q6: tentative approval and requested configuration/placement clarification | "I tentatively approve 1. You are talking about transfer between workflow parts to agents correct ? And you are talking about a versioned, distinct report-review as a unique type of transfer policy? Is that correct ? Please listen to this because I forgot to provide this exact consideration -- Will the transfer policies be expressed in the contract as registered and activated like in the effective run configuration or will it be expressed in the output submission tool ? Or something else ? Furthermore what are the policies for what goes directly into the agent's context expanded and what is provided as a reference to a folder or file in the sandbox ?" | 2026-10-25 | At this answer, profile approval was tentative pending the concrete authoring/activation/submission and placement walkthrough. This row preserves that steering; later OC-D123/124 explicitly close it without rewriting the original answer. | spec CONTRACTS §§2–5; resolved by OC-D123/124; final conversion: OUTPUT-CONTRACTS §§3, 6; OVE-163, OVE-164 | [working contract](CONTRACTS.md#3-configuration-activation-submission-and-resolution); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D121 | FC-Q8: review/repair versus official-use inputs? | "Distinguish review/repair and official-use requirements explicitly per consumer. (Recommended)" | 2026-10-25 | Authorized review/repair may receive exact draft/held material with status/gaps; official use needs exact-use policy and current eligibility. Native ingestion, lineage and readback are additional when promised by the consumer contract. Operational read proves bytes, not use authority. | spec IQ-07 §1.9; revised CONTRACTS consumer readiness; final conversion: OUTPUT-CONTRACTS §§5, 6, 10; OVE-164, OVE-165, OVE-179 | [IQ-07 §1.9](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#19-consumer-purpose-materialization-and-profile-clarification-oc-d120122); [working contract](CONTRACTS.md#1-accepted-common-model); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D122 | FC-Q18: one materialization entry point? | "Use one host-owned entry point with boundary-specific builders behind it. (Recommended)" | 2026-10-25 | Admit instructions/task/contracts, host state, explicit selected sources, receiving model/backend and budgets through one host entry point. Return sealed effective prompt plan/index, separate receipts and readiness/typed refusal. First invocation invents no predecessor; dependent inputs are explicitly selected exact revisions. | spec IQ-07 §1.9; revised CONTRACTS materialization interface; final conversion: OUTPUT-CONTRACTS §§6; OVE-164 | [IQ-07 §1.9](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#19-consumer-purpose-materialization-and-profile-clarification-oc-d120122); [working contract](CONTRACTS.md#1-accepted-common-model); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round B: profile activation and placement confirmed

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D123 | FC-Q6r: close tentative profile approval after configuration walkthrough? | "Confirm this configuration/activation model and report-review@v1 as the first profile. (Recommended)" | 2026-10-25 | Resolves OC-D120's tentative status. Register a reusable profile or author an equivalent inline definition; admission pins/compiles effective settings; activation binds the run revision. Preferences specialize profile → mission → unit → input with link/hard constraints enforced. Resolve exact output revisions into receiver plans later. Submission names candidates; policy changes use authorized revisions at safe future boundaries. | spec CONTRACTS §§2–3; IQ-07 §1.10; transfer profile v1; final conversion: OUTPUT-CONTRACTS §§3, 6; OVE-163, OVE-164 | [contract](CONTRACTS.md#3-configuration-activation-submission-and-resolution); [IQ-07 §1.10](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#110-profile-activation-and-placement-confirmed-oc-d123124); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D124 | FC-Q19: placement defaults, alternatives and whole-invocation accounting? | "Use these defaults with explicit per-consumer placement requirements and alternatives. (Recommended)" | 2026-10-25 | Compact task/state, obligations, selected assertions and access index inline; exact report bodies as readable sandbox files; evidence as validated on-demand handles; broader history opt-in. Consumers may require other placement/allowed alternatives. Aggregate prompt/file accounting reserves generation/tool-result capacity; future file reads consume context. Only authored satisfying alternatives may replace a required form; otherwise repair/block. | spec CONTRACTS §§4–5; IQ-07 §1.10; final conversion: OUTPUT-CONTRACTS §§3, 6; OVE-164 | [placement](CONTRACTS.md#4-what-enters-the-prompt-versus-the-sandbox); [budgets](CONTRACTS.md#5-aggregate-budgets-readiness-and-replay); [IQ-07 §1.10](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#110-profile-activation-and-placement-confirmed-oc-d123124); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round C: focused coordinator scope

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D125 | FC-Q5/11/20a: focused operational surface or whole coordinator redesign? | "Build the focused operational surface; explicitly defer the broader redesign. (Recommended)" | 2026-10-25 | Include effective-node configuration, exact input/output, fulfillment, transfer-plan/receipt inspection and attributable output/transfer events through the existing router/control path. Defer broader CLI grammar migration, new skill bundles/scripts, automated provider-sheet upkeep, Socket.IO CLI, legacy API retirement and global HTTP cleanup to their own decisions. This is a scope decision, not proof of implementation or acceptance of every CS-D detail. Notification defaults and error routing remain unanswered. | spec IQ-07 §1.11; CONTRACTS §9; final CS-D1..14 disposition and work-item mapping; final conversion: OUTPUT-CONTRACTS §§1, 3, 12; OVE-182 | [IQ-07 §1.11](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#111-focused-coordinator-scope-oc-d125); [contract](CONTRACTS.md#9-focused-coordinator-scope); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round C continued, 2026-10-26: notifications and error routing

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D126 | FC-Q20b: default coordinator notification policy? | "Wake on actionable changes and checkpoints; batch routine progress. (Recommended)" | 2026-10-26 | Default durable wakes cover actionable assessment holds/rejections, blocked input delivery, required review, unresolved native effects, checkpoint readiness and completion/failure. Persist routine events and batch ordinary progress. Admitted subscriptions are configurable. Prove actual selected-host wake, reconnect/replay, acknowledgment, duplicates and cancellation before claiming callbacks work. | spec CONTRACTS §9.1; IQ-07 §1.12; coordinator observation work item at final conversion; final conversion: OUTPUT-CONTRACTS §§12; OVE-182 | [contract](CONTRACTS.md#91-durable-notification-defaults); [IQ-07 §1.12](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#112-notifications-and-error-routing-oc-d126127); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D127 | FC-Q12: common output/transfer error envelope and responsible repair layer? | "Use the shared envelope and route repair to the responsible layer. (Recommended)" | 2026-10-26 | Use a typed envelope with stable code, position/field, safe explanation, retry state, recovery action, correlation and retained native causes. Bounded model repair handles correctable submission/content failures; the host handles infrastructure, authority and uncertain-effect recovery. Keep execution, fulfillment and settlement distinct; do not repeat successful cognition or committed writes. Accepts this subset, not the whole fault-tolerance program. | spec CONTRACTS §10; IQ-07 §1.12; focused error/recovery work item at final conversion; final conversion: OUTPUT-CONTRACTS §§3, 4, 5; OVE-163, OVE-164, OVE-165, OVE-166, OVE-167 | [contract](CONTRACTS.md#10-output-and-transfer-error-contract); [IQ-07 §1.12](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#112-notifications-and-error-routing-oc-d126127); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round D: real qualification fixtures

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D128 | FC-Q21a: explicitly amend the earlier real-work gate for progressive qualification? | "Allow real fixture qualification at checkpoints; keep routine use gated. (Recommended)" | 2026-10-26 | Explicitly amends SV-D12 to allow bounded qualification runs of the owner's actual fixtures at progressive checkpoints once their prerequisites are ready. Use real agents and required actual acquisition/ingestion/retrieval paths; analyze Transcript/results against functional goals, repair any failing layer and rerun before progression. Synthetic/scripted tests aid diagnosis but do not replace functional acceptance. Routine research/general use remains gated on all four workflows, output/context contracts and full Deep Agents qualification for both apps. | spec CONTRACTS §11; IQ-07 §1.13; Sprint V plan §1 gate amendment; fixture work items at conversion; final conversion: OUTPUT-CONTRACTS §§12; OVE-169, OVE-186, OVE-168 | [contract](CONTRACTS.md#11-real-fixtures-and-the-general-use-gate); [IQ-07 §1.13](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#113-real-fixture-qualification-exception-oc-d128); [Sprint V plan](../../../sessions/SPRINT-V-PLAN.md#1-scope-and-the-two-completion-gates); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round D: checkpoint sequence and release

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D129 | FC-Q13: six-wave implementation sequence with mandatory evidence checkpoints? | "Adopt this sequence and mandatory checkpoints. (Recommended)" | 2026-10-26 | W0 prerequisite schemas/trusted interfaces/settlement barriers; W1 one GoalDirected report; W2 exact two-stage transfer; W3 multiple reports/accumulation/synthesis; W4 advanced recovery/revisions/review/linked reuse; W5 remaining workflows/compositions/full Deep Agents qualification. Basic durability, access and aggregate budgets precede first use. Real workflow fixtures start W1; map supplied tasks after interview, prove AI Engineer then Biotech at each applicable boundary, and repair/rerun before advancing. | spec CONTRACTS §11.1; IQ-07 §1.14; WORK-ITEMS wave/checkpoint matrix; final conversion: OUTPUT-CONTRACTS §§12; OVE-169, OVE-186, OVE-168, OVE-185 | [contract](CONTRACTS.md#111-accepted-wave-sequence); [IQ-07 §1.14](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#114-checkpoint-sequence-and-release-oc-d129130); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D130 | FC-Q21b: engineering-checkpoint release responsibility? | "Coordinator releases after independent evidence review; escalate unresolved decisions. (Recommended)" | 2026-10-26 | A separate reviewing agent assesses retained Transcript, outputs, receipts and declared functional criteria. The implementation coordinator records pass/advances only when every required criterion is met. Missing/ambiguous evidence blocks. Escalate unresolved goals or required human decisions; a fixture may explicitly require owner release. Engineering checkpoint release is distinct from KS report-use decisions and scientific-review authority. | spec CONTRACTS §11.2; IQ-07 §1.14; independent checkpoint review work item; final conversion: OUTPUT-CONTRACTS §§12; OVE-169, OVE-186, OVE-168, OVE-185 | [contract](CONTRACTS.md#112-engineering-checkpoint-release); [IQ-07 §1.14](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#114-checkpoint-sequence-and-release-oc-d129130); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Owner steering: fixture mapping and detailed workflow/hook rounds

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D131 | Owner clarification: must complex fixtures fit the six-wave outline literally? | "I am going to provide the exact knowledge work fixtures at the end. I don't know if they will so cleanly fold into the 6 stage sequence you recommended. I am going to prescribe something complex and real world. Generally we can probably just increase in complexity throughout the stages. That makes sense. You'll be able to fold my fixture desires into your proof checkpoint sequence." | 2026-10-26 | Preserve the actual complex tasks supplied at the end. Treat W0–W5 as capability/proof progression; map prerequisites and increasing complexity to the fixtures rather than simplify them into fixed task shapes. Detailed mapping stays adaptable and explicit; partial slices never certify the whole task. Mandatory functional review/repair/rerun remains. | spec CONTRACTS §11.1; IQ-07 §1.15; later fixture integration; final conversion: OUTPUT-CONTRACTS §§12; OVE-169, OVE-186, OVE-189, OVE-190, OVE-191, OVE-192 | [contract](CONTRACTS.md#111-accepted-wave-sequence); [IQ-07 §1.15](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#115-fixture-flexibility-and-detailed-workflowhook-rounds-oc-d131132); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D132 | Owner expands the interview before final confirmation | "I need you to go into workflow specific context transfer (Goal Directed, Stage Graph [different types of stage dependencies]) and hammer down those details to my liking ." / "We also need to discuss hooks with deep agents more precisely." | 2026-10-26 | Add explicit GoalDirected and StageGraph dependency/retrieval/transfer rounds, Deep Agents hook event/state/context semantics, and coordinator on-demand versus automatic output delivery. Audit code before recommendations. This is a scope instruction, not acceptance of proposed hook authority or workflow detail. Defer FC-Q15 until these rounds and the worked model are complete. | spec CONTRACTS §16; IQ-07 §1.15/new rounds; workflow/hook evidence record; final conversion: OUTPUT-CONTRACTS §§7, 9, 10, 11, 12; OVE-169, OVE-170, OVE-171, OVE-176, OVE-179, OVE-180, OVE-181, OVE-182, OVE-183 | [contract](CONTRACTS.md#16-workflow-specific-context-and-hooks-detailed-round); [discussion record](WORKFLOW-CONTEXT-HOOKS.md); [IQ-07 §1.15](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#115-fixture-flexibility-and-detailed-workflowhook-rounds-oc-d131132); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round E: GoalDirected working views and independent progress

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D133 | FC-Q22a: what does the next GoalDirected executor receive? | "Use these three views with bounded inline state and an exact accessible index. (Recommended)" | 2026-10-26 | Distinguish current accepted work, actionable repair work and optional history. Put objective, obligation/coverage summary, blockers and bounded repair queue inline. Require the complete exact current-set index as a readable file or authorized retrieval handle; selected report bodies follow consumer contracts. Held/draft/rejected material remains labelled and enters working context only when selected for that task. Explicit consumer placement requirements may differ. | spec CONTRACTS §16.1; IQ-07 §1.16; GoalDirected materialization work item; final conversion: OUTPUT-CONTRACTS §§6, 7; OVE-164, OVE-169, OVE-170 | [contract](CONTRACTS.md#161-goaldirected-working-views-and-independent-progress); [IQ-07 §1.16](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#116-goaldirected-working-views-and-independent-progress-oc-d133134); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D134 | FC-Q22b: continue unrelated goal work while an obligation awaits review/reconciliation? | "Continue independent work; preserve affected waits and completion barriers. (Recommended)" | 2026-10-26 | Continue independently runnable work within admitted budgets while preserving affected goal-scoped obligations' durable waits. Waiting required obligations still block final goal acceptance. Do not retry the waiting work or duplicate its pending effect to manufacture progress. Required invocation-level barriers and declared global pauses still hold; loop readiness must track affected obligations separately. | spec CONTRACTS §16.1; IQ-07 §1.16; GoalDirected readiness/recovery work item; final conversion: OUTPUT-CONTRACTS §§4, 7; OVE-166, OVE-170 | [contract](CONTRACTS.md#161-goaldirected-working-views-and-independent-progress); [IQ-07 §1.16](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#116-goaldirected-working-views-and-independent-progress-oc-d133134); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Owner steering: new-session handoff and linked workflows

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D135 | Owner adds Linked Workflows and deeper intra/inter-workflow context scope | "In addition to goal directed and stage graph we need to resolve this." / "How do Linked Workflows pass context ?" / "We need to go deep into how workflows inter and intra pass context as we are doing." | 2026-10-26 | Add explicit FC-Q26 covering linked/nested workflow input/output projections, release, receiving authority, revisions, adoption, recovery and context placement. Distinguish nested ProgramNodes, Child Mission Invocation, linked runs, mission chains, continuation/fork and provider subagents. This requests a deep interview, not acceptance of any proposed answer. | spec IQ-07 §1.17 / Round E FC-Q26; CONTRACTS §16.2; SE-11 handoff §10; final conversion: OUTPUT-CONTRACTS §§6, 9, 10; OVE-176, OVE-179 | [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#117-new-session-handoff-and-linked-workflow-scope-oc-d135136); [contract](CONTRACTS.md#162-linked-and-intrainter-workflow-interview-scope); [handoff](INTERVIEW-HANDOFF-2026-10-26.md#10-linked-workflows-and-nested-composition-explicit-new-frontier-fc-q26); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D136 | Owner stops for context length and requests detailed handoff plus next-session discovery support | "Your context has simply filled up too much. I need to continue this in another session." / "I need you to write an extremely detailed interview handoff file." / "The next agent session can use subagents as needed (GPT 6 Astra permitted) to help with context discovery , exploration and/or research." / "Please write that handoff now. Please provide quality context. Remember the difference and porting/extension of knowledge services and mission control ." | 2026-10-26 | Produce the detailed source-backed resumption file, preserve the two unanswered questions exactly, carry accepted decisions and unresolved conversion work, emphasize MC/KS/domain ports and ownership, and permit GPT 6 Astra discovery/exploration/research in the next session. Stop asking interview questions in this session; no answer is inferred for Q22c/d and no implementation is authorized by the handoff. | SE-11 detailed handoff; IQ-07 §1.17; current checkpoint/ledger pointers; final conversion: OUTPUT-CONTRACTS §§1, 12; OVE-162 (synthesis disposition) | [handoff](INTERVIEW-HANDOFF-2026-10-26.md); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#117-new-session-handoff-and-linked-workflow-scope-oc-d135136); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round E: semantic progress notes and repair-fork content

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D137 | FC-Q22c: require a compact progress note in the continuing GoalDirected default profile? | "Require a compact progress note in the continuing GoalDirected default profile. (Recommended)" | 2026-10-26 | The default continuing GoalDirected profile explicitly requires a compact attributed progress note at each normal iteration handoff: work/sources tried, useful findings, unsuccessful approaches worth avoiding, unfinished work and suggested next actions with exact references. Host state remains authoritative; the note cannot rewrite facts or authorize actions. A crash preserves host checkpoint and records a missing note; contract governs recovery. Applies OC-D119 to this profile; ordinary helpers remain unaffected. | spec CONTRACTS §16.3; IQ-07 §1.18; GoalDirected semantic continuity work item; final conversion: OUTPUT-CONTRACTS §§7, 11; OVE-169, OVE-181 | [contract](CONTRACTS.md#163-goaldirected-progress-notes-and-repair-fork-defaults); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#118-goaldirected-progress-notes-and-repair-fork-defaults-oc-d137138); [handoff §4](INTERVIEW-HANDOFF-2026-10-26.md#4-last-two-questions-now-answered-do-not-re-ask); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D138 | FC-Q22d: include exact working drafts/files in an explicitly requested repair-fork default? | "Include the selected exact working drafts and files in the repair-fork default. (Recommended)" | 2026-10-26 | Repair-fork default includes accepted-set index/findings plus exact task-relevant working drafts/files from the selected historical point, labelled for repair. Verify receiving access and availability; never substitute today's workspace for missing historical snapshot. Pending effects stay visible for reconciliation; context copying does not adopt obligations, duplicate writes or transfer authority. Broader history remains off. Existing precise-fork identity/lineage constraints remain. | spec CONTRACTS §16.3; IQ-07 §1.18; repair-fork materialization work item; final conversion: OUTPUT-CONTRACTS §§6, 11; OVE-181 | [contract](CONTRACTS.md#163-goaldirected-progress-notes-and-repair-fork-defaults); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#118-goaldirected-progress-notes-and-repair-fork-defaults-oc-d137138); [handoff §4](INTERVIEW-HANDOFF-2026-10-26.md#4-last-two-questions-now-answered-do-not-re-ask); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round E: Stage Graph alternative selection and unfinished branches

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D139 | FC-Q23a: default exact input selection for authored any/quorum joins? | "Select the first qualifying set; allow an authored bounded wait/ranking policy. (Recommended)" | 2026-10-26 | Select and seal the first qualifying set in MC's recorded eligibility order, with stable tie-break for simultaneous qualification. Authors may declare bounded wait/ranking instead. Coverage, separately required inputs, access and permitted-use constraints remain; late arrivals do not silently enter sealed receiver inputs. | spec CONTRACTS §16.4; IQ-07 §1.19; exact join-selection work item in final conversion; final conversion: OUTPUT-CONTRACTS §§7; OVE-171 | [contract](CONTRACTS.md#164-stage-graph-alternative-selection-and-unfinished-branches); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#119-stage-graph-alternative-selection-and-unfinished-branches-oc-d139140); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D140 | FC-Q23b: default policy for unfinished branches after alternative release? | "Continue within existing budgets; require explicit cancellation policy. (Recommended)" | 2026-10-26 | Unfinished branches continue within admitted budgets by default. Cancellation requires explicit policy and must respect other consumers/obligations. Assess and retain later outputs without silently changing running synthesis inputs. Usage/effect reconciliation remains required; cancellation cannot undo committed work. | spec CONTRACTS §16.4; IQ-07 §1.19; join/late-result lifecycle work item in final conversion; final conversion: OUTPUT-CONTRACTS §§7, 9; OVE-171 | [contract](CONTRACTS.md#164-stage-graph-alternative-selection-and-unfinished-branches); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#119-stage-graph-alternative-selection-and-unfinished-branches-oc-d139140); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round E: optional inputs and scoped synthesis revalidation

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D141 | FC-Q23c: optional input pending when the consumer is otherwise ready? | "Proceed with a recorded omission; wait only under an authored bounded policy. (Recommended)" | 2026-10-26 | Proceed when required inputs and release conditions pass; record optional omission visibly to receiver. Bounded waiting must be authored. Preserve separate ordering prerequisites; no undeclared required-input fallback. Source may continue; late arrival cannot silently alter sealed inputs. | spec CONTRACTS §16.5; IQ-07 §1.20; input-readiness work item in final conversion; final conversion: OUTPUT-CONTRACTS §§6, 7; OVE-171 | [contract](CONTRACTS.md#165-optional-inputs-and-scoped-synthesis-revalidation); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#120-optional-inputs-and-scoped-synthesis-revalidation-oc-d141143); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D142 | FC-Q23d: bounded automatic revalidation of completed synthesis after a tracked report revision? | "Yes I choose 1. We are going to handle only a certain scope of these stale/invalidation types of automatic processes. So these synthesis types will become aware of report revisions and active a bounded authorized revalidation. Yes this is good. Later sprints will explicitly deal with data freshness and invalidation but this and possibly others might go into this sprint" | 2026-10-26 | For the synthesis/report-revision case, MC automatically arranges bounded authorized revalidation first. Reuse applicable evidence; KS retains evidence/use authority. Restore current eligibility only with justified checks; rebuild only if needed and authorized. Missing capability/exhaustion blocks actionably; preserve historical inputs/effects and revocation constraints. Scope is explicitly limited by OC-D143. | spec CONTRACTS §16.5; IQ-07 §1.20; bounded synthesis revalidation work item in final conversion; final conversion: OUTPUT-CONTRACTS §§10; OVE-175 | [contract](CONTRACTS.md#165-optional-inputs-and-scoped-synthesis-revalidation); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#120-optional-inputs-and-scoped-synthesis-revalidation-oc-d141143); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D143 | Owner scope limit on automatic freshness/invalidation work | "We are going to handle only a certain scope of these stale/invalidation types of automatic processes." / "Later sprints will explicitly deal with data freshness and invalidation but this and possibly others might go into this sprint" | 2026-10-26 | Include synthesis reacting to report revisions. Defer general data-freshness/invalidation automation to later sprints. Other cases are candidates requiring explicit inclusion, not an open-ended current-sprint mandate. Preserve already accepted exact lineage, staleness and current-use checks. | spec CONTRACTS §16.5; IQ-07 §1.20; final WORK-ITEMS scope/disposition matrix; final conversion: OUTPUT-CONTRACTS §§1, 10; OVE-175 | [contract](CONTRACTS.md#165-optional-inputs-and-scoped-synthesis-revalidation); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#120-optional-inputs-and-scoped-synthesis-revalidation-oc-d141143); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round E: report revision during running synthesis

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D144 | FC-Q23e: ordinary accepted report revision during running synthesis? | "Finish against sealed inputs, then revalidate; interruption/restart requires explicit policy. (Recommended)" | 2026-10-26 | When A2 arrives and selected A1 remains permitted, let synthesis finish within existing budget against sealed A1 inputs, retain result and perform bounded authorized revalidation before admitting it as current. Interruption/restart requires explicit authored policy at a supported safe boundary. Preserve exact consumption history; revocation, cancellation and mandatory stops remain independent. Within OC-D143's synthesis/report-revision scope. | spec CONTRACTS §16.6; IQ-07 §1.21; synthesis revision work item in final conversion; final conversion: OUTPUT-CONTRACTS §§6, 10; OVE-175 | [contract](CONTRACTS.md#166-report-revision-during-running-synthesis); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#121-report-revision-during-running-synthesis-oc-d144); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round E: incremental batching and provisional reassessment scope

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D145 | FC-Q23f: batching explicitly incremental synthesis? | "Combine arrivals into one pending next synthesis; per-increment runs require explicit policy. (Recommended)" | 2026-10-26 | For an authored incremental binding, keep one active synthesis and combine new qualifying report arrivals into one pending next activation. Seal exact eligible membership at release; preserve trigger/coverage/budget limits and immutable running inputs. Separate per-increment activations require explicit policy. Distinct from report revision handling. | spec CONTRACTS §16.7; IQ-07 §1.22; incremental dispatch work item in final conversion; final conversion: OUTPUT-CONTRACTS §§10; OVE-175 | [contract](CONTRACTS.md#167-incremental-batching-and-provisional-reassessment-scope); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#122-incremental-batching-and-provisional-reassessment-scope-oc-d145146); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D146 | FC-Q23g: include authored reassessment after exact held source acceptance? | "Include this specific case, with automatic reassessment only under an authored policy. (Recommended)" | 2026-10-26 | Explicitly add this case under OC-D143: when an exact held report becomes accepted without byte changes, an authored policy may schedule bounded independent reassessment of retained provisional synthesis. Derived work still needs its own checks/use decision; otherwise held or authorized repair. Without policy await explicit action. General freshness/invalidation remains deferred. | spec CONTRACTS §16.7; IQ-07 §1.22; provisional reassessment work item and scope matrix in final conversion; final conversion: OUTPUT-CONTRACTS §§10; OVE-175 | [contract](CONTRACTS.md#167-incremental-batching-and-provisional-reassessment-scope); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#122-incremental-batching-and-provisional-reassessment-scope-oc-d145146); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round E: conditional unknown, dynamic membership and routing justification

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D147 | FC-Q23h: unknown evidence versus conditional else? | "I choose 1." / "Yes I choose 1 and I want this feature justified." | 2026-10-26 | Accept default durable wait under authored limits while condition evidence is unavailable; else requires conclusive false. Exhaustion blocks/escalates. Explicit unavailable-evidence route preserves unknown and cannot bypass evidence/use gates. Does not settle branch multiplicity or prove existing runtime support; justification is OC-D149. | spec CONTRACTS §16.8; IQ-07 §1.23; conditional release work item in final conversion; final conversion: OUTPUT-CONTRACTS §§7; OVE-171 | [contract](CONTRACTS.md#168-conditional-unknown-and-dynamic-expansion-membership); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#123-conditional-unknown-and-dynamic-expansion-membership-oc-d147149); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D148 | FC-Q23i: dynamic fan-out membership cutoff? | "Freeze each expansion's member set; incremental additions require explicit policy. (Recommended)" | 2026-10-26 | Freeze exact source collection revision and member set for each expansion. Further bounded additions require authored incremental policy. Preserve stable identities, no silent duplicate/removal/restart, committed template and limits. | spec CONTRACTS §16.8; IQ-07 §1.23; dynamic expansion work item in final conversion; final conversion: OUTPUT-CONTRACTS §§7, 8; OVE-171, OVE-173 | [contract](CONTRACTS.md#168-conditional-unknown-and-dynamic-expansion-membership); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#123-conditional-unknown-and-dynamic-expansion-membership-oc-d147149); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D149 | Owner asks whether conditional routing is built and requests behavior/benefit justification | "I can't quite recall any conditional routing logic inside stage graph workflows. Is that part of the data structure we built ?" / "routing based on some condition / even some discovery (configurable through some contract that specifies these things)." / "Yes I choose 1 and I want this feature justified. Knowledge work and codebase work. Deep agents is likely exclusively knowledge and content work. I say that as a prelude to asking this ? What is the behavior and benefit of this routing ?" | 2026-10-26 | Explain current structures versus specified/proposed routing; justify with knowledge/content and codebase cases, typed discovery contracts, benefits and boundaries. Deep Agents remark is tentative intended usage, not an inferred exclusive lane restriction. Concrete examples/syntax are explanatory proposals, not separately accepted requirements. | CONTRACTS §16.9 source-backed explanation and illustrative rationale; final conversion: OUTPUT-CONTRACTS §§7, 13; OVE-171 | [routing explanation](CONTRACTS.md#169-conditional-routing-current-state-and-rationale); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Owner steering: large-workload Stage Graph expressiveness

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D150 | Owner expands Stage Graph interview to optimization, obligations, dependencies and map-reduce | "Okay can you please start a line of questioning related to optimization of this Stage Graph and output contracts / obligations, dependencies , map-reduce type of behavior. Please help me think of structure and behavior that I think I'm missing. I want this stage graph to be expressive and work well." / "Is there any type of deterministic reducer type node that we should make part of this ?" / "Imagine multiple source discovery stages all feeding a reducer/consolidator node and then passing on a slice of the sources all to stages and then hitting another reducer node." / "Don't overfit to what I am saying. Let's touch on the stage graph in particular and make it able to handle BIG workloads." | 2026-10-26 | Add FC-Q27 before final confirmation: typed deterministic/semantic reduction, large collection representation, map partitioning, grouping/fan-in, obligations/coverage, selective recovery, resource backpressure, and justified optimizer limits. Treat the example as representative, not a prescribed architecture or real fixture. Existing deterministic-executor semantics and old proposal are inputs to inspect; no new design choices or runtime qualification inferred. | CONTRACTS §17 interview scope; IQ-07 §1.24 / FC-Q27; final conversion: OUTPUT-CONTRACTS §§8; OVE-172, OVE-173, OVE-174 | [contract](CONTRACTS.md#17-large-workload-stage-graph-and-map-reduce-interview); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#124-large-workload-stage-graph-interview-expansion-oc-d150); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round F: large-workload transformation, partition and scheduling foundations

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D151 | FC-Q27a: deterministic transformation extensibility? | "Provide the standard library plus admitted, versioned custom transformations. (Recommended)" | 2026-10-26 | Standard versioned exact-key union/dedup, filter, sort, group, join, project, partition and validation operations plus explicitly admitted custom typed transformations with declared effects. Deterministic Executor stages, not a new workflow type; semantic decisions remain distinct admitted knowledge/model operations. | spec CONTRACTS §17.1; IQ-07 §1.25; deterministic executor/library work in final conversion; final conversion: OUTPUT-CONTRACTS §§8; OVE-172 | [contract](CONTRACTS.md#171-transformation-partition-and-scheduling-foundations); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#125-large-workload-foundations-oc-d151153); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D152 | FC-Q27b: batch/member accountability? | "Keep exact partitions and per-member accountability; allow explicitly indivisible groups. (Recommended)" | 2026-10-26 | Exact partition members, coverage and permitted overlap; per-member outcomes and lineage by default. Preserve successes for targeted authorized repair. Explicitly indivisible groups allowed; retry same logical slice, repartition via new explicit plan with lineage. Illustrated counts are not a qualification target. | spec CONTRACTS §17.1; IQ-07 §1.25; partition/member obligation and recovery work in final conversion; final conversion: OUTPUT-CONTRACTS §§4, 8; OVE-170, OVE-173 | [contract](CONTRACTS.md#171-transformation-partition-and-scheduling-foundations); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#125-large-workload-foundations-oc-d151153); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D153 | FC-Q27c: total versus active workload? | "Use durable work inventory and bounded activation/admission windows. (Recommended)" | 2026-10-26 | Retain complete exact durable work inventory, create/admit executable activations in bounded windows under capacity, budget, provider limits and fairness. Coordinator inspects total/queued/active/completed/blocked work; no need for all tasks/workspaces to be active or fully materialized at once. | spec CONTRACTS §17.1; IQ-07 §1.25; durable inventory/windowed scheduler work in final conversion; final conversion: OUTPUT-CONTRACTS §§8; OVE-173 | [contract](CONTRACTS.md#171-transformation-partition-and-scheduling-foundations); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#125-large-workload-foundations-oc-d151153); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Round F: conflict scope, group readiness and qualified trees

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D154 | FC-Q27d: unresolved structural consolidation conflicts? | "Preserve uncontested results and explicit conflicts; block only affected requirements. (Recommended)" | 2026-10-26 | Keep uncontested results and typed conflict records; block only outputs/uses requiring resolution. Authored precedence records rule/source; arrival order cannot silently choose. Preserve faithful contradictory-evidence reports and avoid compulsory human resolution for every conflict. | spec CONTRACTS §17.2; IQ-07 §1.26; reducer conflict/partial-output work in final conversion; final conversion: OUTPUT-CONTRACTS §§8; OVE-172, OVE-174 | [contract](CONTRACTS.md#172-conflicts-independent-group-readiness-and-qualified-trees); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#126-reducer-conflicts-readiness-and-tree-optimization-oc-d154156); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D155 | FC-Q27e: independently ready grouped reductions? | "Release independently ready groups when closure and their own input contract are satisfied. (Recommended)" | 2026-10-26 | Permit independent group release with proven closure and qualifying input contract. Closure needs exact contributor set or trusted no-more-contribution facts from relevant producer/input channels; otherwise discovery barrier remains. Missing/failed required data stay gaps. Quorum/partial coverage remains distinct; global budgets/capacity still apply. | spec CONTRACTS §17.2; IQ-07 §1.26; keyed group closure/readiness work in final conversion; final conversion: OUTPUT-CONTRACTS §§8; OVE-174 | [contract](CONTRACTS.md#172-conflicts-independent-group-readiness-and-qualified-trees); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#126-reducer-conflicts-readiness-and-tree-optimization-oc-d154156); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D156 | FC-Q27f: automatic reduction trees? | "Allow qualified deterministic tree optimization; author semantic hierarchy explicitly. (Recommended)" | 2026-10-26 | Admit automatic regrouping only when versioned contract qualifies result preservation; reordering separately qualified and order preserved where sensitive. Duplicate/effect rules remain. Semantic hierarchy explicitly authored. If even a small group cannot fit, use admitted alternative or block; no dropped required input or forced minimum fan-in. | spec CONTRACTS §17.2; IQ-07 §1.26; optimizer qualification/limits work in final conversion; final conversion: OUTPUT-CONTRACTS §§8; OVE-174 | [contract](CONTRACTS.md#172-conflicts-independent-group-readiness-and-qualified-trees); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#126-reducer-conflicts-readiness-and-tree-optimization-oc-d154156); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Owner steering: contract critique from the coordinator's perspective

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D157 | Owner requests critique of accumulated Stage Graph contract cohesion | "Okay I hope I didn't worsen the system through bringing up this consideration." / "It is the context transfer at that point that is most important. Getting the context into the agent and the sandbox and completing the mission." / "So it really is the cohesion between our output contract obligations and submission tools -> contracts that specify outputs and specify dependencies and specify how context transfers conditionally" / "Critique the contract that has shaped up. You must critique the stage graph (and any equality to goal directed if so) contract expression and behavior at the reduce / context transfer / composability / contractual structure" | 2026-10-26 | Pause further default questions for a source-backed critical review of authoring/compiled expression, obligation/submission/transfer lifecycle, reduction meaning, context/sandbox realization and Graph/Goal Loop composition. A/B/C entity reports to D relationships is a representative test, not the exclusive target. Preserve accepted decisions; critique recommendations are not silently accepted amendments. | CONTRACTS §18 critical review; final conversion: OUTPUT-CONTRACTS §§2, 3, 4, 6, 7, 8, 9, 10, 13; OVE-162 (synthesis disposition) | [critique](CONTRACTS.md#18-coordinator-perspective-critical-review); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D158 | Owner insists on broad ambitious coordinator perspective | "Don't just use that case ! We want to build ONE OF THE BEST systems. We want to build it right ? Take the stance of a coordinator agent. What powers would you want !" | 2026-10-26 | Evaluate general coordinator powers to express, compile, inspect, optimize, adapt, recover and verify complex work. Do not reduce critique to the four-stage example or equate simplicity with reduced capability. Recommendations do not by themselves authorize broad coordinator redesign, implementation, or reversal of prior scope limits. | CONTRACTS §18 coordinator capability critique; final conversion: OUTPUT-CONTRACTS §§1, 3, 8, 12, 13; OVE-162 (synthesis disposition) | [critique](CONTRACTS.md#18-coordinator-perspective-critical-review); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Owner steering: bounded final interview and transfer

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D159 | Per-mission setup and finish the current interview/issues process | "Before a mission is ever spawned trust me I will be going through interviews and extensive set up with the coordinator agent." / "We can't do everything at once. We need to finish this interview -> issues process that we are on." / "I am going to accept some version of the stage graph (and the other workflow and linked workflows) now . By now I mean throughout the sessions that produce the specs and issues." | 2026-10-26 | Finish an explicit coherent current version across workflows/linked workflows; do not turn the contract interview into all future mission-specific planning. Extensive mission-specific coordinator setup precedes launch. Prior accepted capabilities remain, but critique does not automatically expand implementation scope. | final handoff and 20-question protocol; CONTRACTS §19 scope steering; final conversion: OUTPUT-CONTRACTS §§1, 3, 12; OVE-162 (synthesis disposition) | [handoff](FINAL-INTERVIEW-HANDOFF-2026-10-26.md); [contract](CONTRACTS.md#19-final-interview-limit-and-conversion-direction); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D160 | Final interview question budget and preparation | "I am constraining the next interview's number of questions to 20. The agent I use in this session should research and explore in order to have the context and then to be able to draft the most relevant and crucial 20 questions." | 2026-10-26 | Research now and draft a prioritized final question set; next interview has a hard maximum of 20 substantive questions including follow-ups and final confirmation. Avoid repeated decisions and engineering questions the agent can resolve. No answer to drafted questions is inferred. | final interview instrument and budget ledger; final conversion: OUTPUT-CONTRACTS §§1; OVE-162 (synthesis disposition) | [20-question instrument](FINAL-INTERVIEW-20-QUESTIONS-2026-10-26.md); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D161 | Transfer deliverable and next-session ownership | "You are going to set up this transfer. Please write out all answers I have given concerning our current session. Please do some further exploration and reasoning and set me up for the final interview session. I will go start that in another GPT 6 Astra session." | 2026-10-26 | Produce complete current-session verbatim answer/steering record, source-backed frontier, final interview plan and conversion instructions. User starts the next GPT 6 Astra session manually; do not create/message another chat or run interview questions now. This handoff does not authorize runtime implementation, fixtures, commits or deployment. | current-session record; final interview handoff/instrument; final conversion: OUTPUT-CONTRACTS §§1; OVE-162 (synthesis disposition) | [session record](SESSION-ANSWERS-2026-10-26.md); [handoff](FINAL-INTERVIEW-HANDOFF-2026-10-26.md); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Final capped interview: routing, data joins and semantic decomposition

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D162 | F20-01: require an explicit conditional branching mode? | "Require an explicit branching mode or preset. (Recommended)" | 2026-10-26 | Every authored conditional route selects all matching branches or first matching branch in declared order, directly or through a reusable preset. Compile the effective mode/order; no universal silent default. Preserve accepted unknown/else rules. | spec CONTRACTS §16.8; IQ-07 §1.29; conditional routing work item at final conversion; final conversion: OUTPUT-CONTRACTS §§3, 7; OVE-163, OVE-171 | [contract](CONTRACTS.md#168-conditional-unknown-and-dynamic-expansion-membership); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#129-final-routing-join-population-and-semantic-coverage-decisions-oc-d162164); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D163 | F20-02: require an explicit data-join result population policy? | "Require an explicit population policy or preset. (Recommended)" | 2026-10-26 | Data joins explicitly preserve a named primary collection, reconcile both collections, or intentionally select matched records, directly or by preset. Policy includes match cardinality and unmatched treatment; unexpected duplicate matches stay conflicts. Distinguish dataset population from workflow release joins. | spec CONTRACTS §17.1; IQ-07 §1.29; deterministic join contracts/proof at final conversion; final conversion: OUTPUT-CONTRACTS §§8; OVE-172 | [contract](CONTRACTS.md#171-transformation-partition-and-scheduling-foundations); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#129-final-routing-join-population-and-semantic-coverage-decisions-oc-d162164); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D164 | F20-03: require preservation and coverage terms for semantic decomposition? | "Require preservation and coverage terms for semantic decomposition. (Recommended)" | 2026-10-26 | Semantic partitioning/intermediate summaries declare task-relevant preservation and cross-partition coverage through justified independence, reconciliation/validation obligations, or an explicit limitation on the final claim. Reusable profiles are allowed. Mechanical item completion is insufficient; this does not demand universal factual completeness. | spec CONTRACTS §17.3; IQ-07 §1.29; semantic decomposition/assessment proof at final conversion; final conversion: OUTPUT-CONTRACTS §§8; OVE-174 | [contract](CONTRACTS.md#173-semantic-decomposition-preservation-and-coverage); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#129-final-routing-join-population-and-semantic-coverage-decisions-oc-d162164); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Final capped interview: linked review, cancellation and application scope

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D165 | F20-05: allow exact held/draft content across a mission boundary for authorized repair/review? | "Allow purpose-scoped linked repair/review of exact held or draft reports. (Recommended)" | 2026-10-26 | Explicitly extend the cross-mission acceptance restriction for admitted repair/review within one application. Pin exact exports, preserve held/draft status/findings, require receiving grants/budget and required-input readiness. Ordinary use still requires the source owning-Goal or explicit Mission Acceptance gate plus applicable use approval; neither transfer nor review launch implies success. | spec CONTRACTS §16.2; IQ-07 §1.30; linked-transfer contract/qualification work at final conversion; final conversion: OUTPUT-CONTRACTS §§5, 6, 10; OVE-179 | [contract](CONTRACTS.md#162-linked-and-intrainter-workflow-interview-scope); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#130-linked-review-cancellation-and-application-scope-oc-d165167); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D166 | F20-06: default after upstream cancellation once a chain consumer is running with valid sealed inputs? | "Continue the running chain consumer unless cancellation propagation was explicitly selected. (Recommended)" | 2026-10-26 | Change the chain default for an already started consumer to independent continuation within its own limits, subject to current input-use eligibility, revocation and mandatory stops. Propagation requires explicit link policy. Preserve spawned-child cancel and attached-child detach defaults; do not infer new release behavior for a not-yet-started consumer. | spec CONTRACTS §16.2; IQ-07 §1.30; chain cancellation/default and recovery proof at final conversion; final conversion: OUTPUT-CONTRACTS §§10; OVE-179 | [contract](CONTRACTS.md#162-linked-and-intrainter-workflow-interview-scope); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#130-linked-review-cancellation-and-application-scope-oc-d165167); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D167 | F20-07: application boundary and status of hypothetical cross-application linking? | "I appreciate the forward thinking. There may be a day where ai engineer feeds biotech or something like that. but no linked workflows in one application. We are not deferring cross-application transfer or connection we literally haven't decided that is even a feature." / "Yes you read that correctly" | 2026-10-26 | Qualify linked workflows within each application, covering both AI Engineer and Biotech independently. Cross-application transfer/connection is an unadopted possibility, not an accepted feature awaiting qualification or a deferred implementation commitment. No cross-application API/contract/work item is inferred. A future feature needs a fresh decision. | spec CONTRACTS §16.2; IQ-07 §1.30; final current-scope/unadopted disposition matrix; final conversion: OUTPUT-CONTRACTS §§1, 10; OVE-179 | [contract](CONTRACTS.md#162-linked-and-intrainter-workflow-interview-scope); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#130-linked-review-cancellation-and-application-scope-oc-d165167); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Final capped interview: repartitioning and optimization scope

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D168 | F20-08: how should a poor research partition receive a successor plan? | "I would like to allow the coordinator agent to see the bad partition and succeed it with a chance to change it OR make it an agentic step. Partitioning research workloads seems very difficult deterministically (Unless we use the system one model Jev or something special like that)." | 2026-10-26 | Provide coordinator inspection and governed replacement of poor partitions, or an explicitly configured agentic partition-planning step. Its proposal is validated against admitted bounds, exact membership/coverage, preserved successes and indivisible groups; a successor is new semantic work with lineage, not a mutated retry. Do not infer acceptance of the proposed autonomous deterministic replanner. Existing mechanical transforms remain; Jev/model choice is not selected. | spec CONTRACTS §17.4; IQ-07 §1.31; partition planning/inspection/revision proof at final conversion; final conversion: OUTPUT-CONTRACTS §§8; OVE-173 | [contract](CONTRACTS.md#174-partition-repair-and-optimization-scope); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#131-partition-repair-and-optimization-scope-oc-d168170); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D169 | F20-09: adopt pressure-aware producer throttling/consumer priority now? | "How about we wait and see about this once we spin up the dedicated worker locally that will be deployed." | 2026-10-26 | Postpone this scheduling-policy decision until the dedicated deployment worker runs locally and provides evidence. Pressure-aware prioritization is undecided, not accepted implementation or a promised later feature. Existing admitted capacity/resource ceilings, bounded inventory windows, fairness and safe refusal remain required. Record a worker-evidence review point; no worker launch is authorized by this answer. | spec CONTRACTS §17.4; IQ-07 §1.31; undecided policy/worker evidence review in final work matrix; final conversion: OUTPUT-CONTRACTS §§1, 8; OVE-173 | [contract](CONTRACTS.md#174-partition-repair-and-optimization-scope); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#131-partition-repair-and-optimization-scope-oc-d168170); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D170 | F20-10: exclude new automatic computation caching from this version? | "Exclude new automatic computation caching from this version. (Recommended)" | 2026-10-26 | Exclude the proposed same-run pure-transformation memoization subsystem. Preserve required idempotency, recovery, selective carry-forward and explicit recorded reuse. No cross-run cache or model-answer equivalence is introduced; exclusion creates no future delivery commitment. | spec CONTRACTS §17.4; IQ-07 §1.31; current-version scope/exclusion matrix; final conversion: OUTPUT-CONTRACTS §§1, 8; OVE-172 | [contract](CONTRACTS.md#174-partition-repair-and-optimization-scope); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#131-partition-repair-and-optimization-scope-oc-d168170); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Final capped interview: durable reactions and compaction preservation

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D171 | F20-11: allow bounded reactions attached to durable workflow/output transitions? | "Allow durable transition reactions through ordinary admitted executions. (Recommended)" | 2026-10-26 | Authors may attach bounded reactions to durable transitions, compiled/dispatched through ordinary admitted execution with obligations, budgets, identity and restart/replay handling. Temporal remains scheduler; operation/provider stop is distinct from durable submission, assessment, fulfillment, delivery and settlement. No parallel hook scheduler or implicit acceptance authority. | spec CONTRACTS §16.10; IQ-07 §1.32; durable reaction execution/proof at final conversion; final conversion: OUTPUT-CONTRACTS §§11; OVE-183 | [contract](CONTRACTS.md#1610-durable-reactions-and-compaction-preservation); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#132-durable-reactions-and-compaction-preservation-oc-d171172); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D172 | F20-16: allow compaction preservation proposals validated by the host? | "Allow bounded preservation proposals validated by the host. (Recommended)" | 2026-10-26 | Add consumed bounded candidate notes/exact references for host validation at compaction; required authoritative state is preserved independently. No arbitrary summary replacement or sealed-input rewrite. Keep in-session compaction and continuation identity, triggers, budgets and validation distinct. | spec CONTRACTS §16.10; IQ-07 §1.32; compaction preservation proposal/validation proof at final conversion; final conversion: OUTPUT-CONTRACTS §§11; OVE-181 | [contract](CONTRACTS.md#1610-durable-reactions-and-compaction-preservation); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#132-durable-reactions-and-compaction-preservation-oc-d171172); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Final capped interview: hook read, preparation and effect boundaries

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D173 | F20-12: may hooks use scoped reads in addition to their event/state projection? | "Allow the event snapshot plus explicitly scoped, host-mediated reads. (Recommended)" | 2026-10-26 | Admit selected output/workspace read handles alongside the bounded versioned event/state snapshot. Host mediation checks authority and accounts for access/resources. No implicit whole-workspace/KS/private middleware access. | spec CONTRACTS §16.11; IQ-07 §1.33; hook access capability and receipt proof at final conversion; final conversion: OUTPUT-CONTRACTS §§11; OVE-180 | [contract](CONTRACTS.md#1611-hook-access-preparation-and-effect-boundaries); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#133-hook-access-preparation-and-effect-boundaries-oc-d173175); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D174 | F20-13: stage hook-produced files for host installation? | "Stage candidate files for host-validated installation. (Recommended)" | 2026-10-26 | Hook outputs such as indexes/working notes are staged candidates. The host validates and installs them at supported boundaries with attribution and coordinated execution. A created file alone does not establish fulfillment, acceptance or a sealed transfer; qualifying outputs use admitted submission/validation. Direct mutation of the live agent workspace is not selected. | spec CONTRACTS §16.11; IQ-07 §1.33; staged preparation/install and recovery proof at final conversion; final conversion: OUTPUT-CONTRACTS §§11; OVE-180 | [contract](CONTRACTS.md#1611-hook-access-preparation-and-effect-boundaries); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#133-hook-access-preparation-and-effect-boundaries-oc-d173175); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D175 | F20-14: route hook-requested model work/external writes through ordinary operations? | "Dispatch model work and external writes as ordinary admitted operations. (Recommended)" | 2026-10-26 | Hook scripts perform bounded observation, guards and local preparation; requested model work/external effects are separately admitted operations with identity, grants, budgets, effects and recovery. Do not add a directly effectful hook-script executor. KS retains evidence/use/native-operation authority. | spec CONTRACTS §16.11; IQ-07 §1.33; hook-to-operation dispatch/effect recovery proof at final conversion; final conversion: OUTPUT-CONTRACTS §§5, 11; OVE-180, OVE-183 | [contract](CONTRACTS.md#1611-hook-access-preparation-and-effect-boundaries); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#133-hook-access-preparation-and-effect-boundaries-oc-d173175); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

F20-15 is skipped as a consequence of OC-D171/174/175: configured persistent candidate notes/indexes
use the selected ordinary admitted output path with validation and exact attribution. This records
no new owner answer, replaces neither authoritative state nor the required Goal Loop progress note,
and does not adopt a separate automatic memory subsystem.

### Final capped interview: automatic coordinator content

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D176 | F20-17: allow explicitly configured bounded output content delivery to the coordinator? | "Allow explicitly configured, bounded content delivery; keep default notices reference-oriented. (Recommended)" | 2026-10-26 | Mission setup may admit selected excerpts or small designated outputs into coordinator context under receiving grants and context budgets. Default notices remain references/status/gaps, with content retrieved on demand. Use the coordinator subscription/delivery path, not an expanded Child Portal. Prove host wake, model-visible delivery, acknowledgment and content read separately. | spec CONTRACTS §9.2; IQ-07 §1.34; coordinator delivery/wake work at final conversion; final conversion: OUTPUT-CONTRACTS §§12; OVE-182 | [contract](CONTRACTS.md#92-optional-automatic-coordinator-content); [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md#134-optional-automatic-coordinator-content-oc-d176); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

### Owner steering: final synthesis, fast implementation and post-sprint experiments

The [complete message](OWNER-DIRECTION-AND-STRESS-FIXTURES-2026-10-26.md#1-owners-complete-message-verbatim)
preserves every fixture detail and all wording; short exact excerpts below identify each decision.

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D177 | Owner's implementation posture | "I purposefully want a kind of destructive strategy regarding implementation. No trying to save historical data. I don't want extra caution related to files and imports and behavior. I want to slice through and achieve the system." / "We have no real users. We have no automations in production." | 2026-10-26 | Directly replace obsolete files/imports/implementation/schema/behavior and rebuild disposable experimental data. Necessary migrations and cross-layer changes belong in delivering issues; no invented production compatibility/data-rescue program. Preserve new-system correctness, decision records and unrelated user work. This turn prepares the instruction, not runtime implementation. | final handoff §§1/6/7; owner direction §2; implementation issue scope; final conversion: OUTPUT-CONTRACTS §§1; OVE-162 and all delivering children | [direction](OWNER-DIRECTION-AND-STRESS-FIXTURES-2026-10-26.md#2-implementation-mandate--interpretation); [handoff](FINAL-SPEC-AND-ISSUE-SYNTHESIS-HANDOFF-2026-10-26.md); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D178 | Three supplied stress fixtures and mission-work evaluation | "These fixtures are meant to stress our system , expose gaps and incentivize any additions." / "In addition to running these fixtures this is when we start EVALUATION AND FEEDBACK LOOPS. Evaluation of the mission work." | 2026-10-26 | Preserve full F1/F2/F3 from the verbatim source: Generation Lab GoalDirected reports/intents and general/async browser helpers without required native ingestion; Qualia Life staged products/ingredients/three connected studies with evidence provenance; up-to-50 model/benchmark native ingestion plus AI Engineer retrieval/ranking/routing. Add concrete post-sprint fixture and independent evaluation/fix/rerun work. No live research or execution is claimed. | owner direction §§1/4/5; final fixture/evaluation issues; final conversion: OUTPUT-CONTRACTS §§12; OVE-187, OVE-188, OVE-189, OVE-190, OVE-191, OVE-192, OVE-193 | [full fixtures and evaluation](OWNER-DIRECTION-AND-STRESS-FIXTURES-2026-10-26.md); [handoff](FINAL-SPEC-AND-ISSUE-SYNTHESIS-HANDOFF-2026-10-26.md#5-checkpoints-then-three-stress-missions-then-full-product-architecture); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D179 | Larger sequence and disposable experiment outputs | "These fixtures are going to run AFTER the fixture checkpoints that should be outlined in one of the ANSWERS.md . They are real tests after this sprint. AFTER THESE FIXTURES we are going to architect the content types and features of the ai engineer education services and the biotech knowledge and recommendation services FULLY. It is totally fine to produce reports and ingestion that don't end up as final parts of our released services. It's all in the pursuit of the final product." | 2026-10-26 | W0–W5 precedes the three stress missions; they do not replace intermediate qualification. Evaluation/feedback accompanies the stress phase. Full education/knowledge/recommendation product architecture follows; experimental outputs need not become released product data. | owner direction §3; BellLabs pathway; final dependency/proof plan; final conversion: OUTPUT-CONTRACTS §§12; OVE-186, OVE-189, OVE-190, OVE-191, OVE-192, OVE-193 | [sequence](OWNER-DIRECTION-AND-STRESS-FIXTURES-2026-10-26.md#3-required-sequence); [pathway](../../../../../../../../../docs/BELLLABS-SEQUENCE.md); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D180 | Required quality cadence | "Documentation updates (AGENTS.md, OKF docs) and clean code updates should run effectively for every major commit." | 2026-10-26 | Require explicit clean-code/spec review and affected semantic documentation/generator/check completion at each major commit/integration milestone. Optional turn-end hooks are not proof of this gate. Include in team/issue done definitions, using each owner's actual mechanisms; no automation installed now. | owner direction §6; team quality gate; source map §7; final conversion: OUTPUT-CONTRACTS §§12; OVE-186 | [quality](OWNER-DIRECTION-AND-STRESS-FIXTURES-2026-10-26.md#6-quality-at-every-major-commit); [verified commands](INTERVIEW-SOURCE-MAP-2026-10-26.md#7-verified-quality-entrypoints); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D181 | Final synthesis handoff and team-independent implementation packet | "Now I want you to create a final instruction for a GPT 6 Astra Extra High Session. I need you to accumulate all the various ANSWERS.md and any other document derivatives that have stemmed from the 4 or so interviews I have conducted. The agent's mission is to coalesce everything into final specifications and issues." / "I am adamant about directness and efficiency. I want these issues to permit the agents to work unimpeded and get the functionalities up and running. Migrations made. Code added and mutated. Checkpoints ran." / "I will use codex or claude code . I don't know yet. An agent team generally." / "Fast path." | 2026-10-26 | Produce exact source map and actionable instruction for owner-started GPT 6 Astra Extra High. Next session explores/reasons/synthesizes and publishes final specs/issues/team packet. Supersedes automatic resumption of old interview questions and redundant generic permission; unanswered options stay honest and cannot silently expand mandatory scope. No chat/model change requested here. | final synthesis handoff/source map; current ledger and entrypoints; final conversion: OUTPUT-CONTRACTS §§1, 12; OVE-162 (synthesis disposition) | [handoff](FINAL-SPEC-AND-ISSUE-SYNTHESIS-HANDOFF-2026-10-26.md); [source map](INTERVIEW-SOURCE-MAP-2026-10-26.md); [final reconciliation](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

## Mental model restated

After OC-D176: routine notices remain bounded references, status and gaps. Mission setup can
explicitly select a short findings brief or small output for automatic coordinator-context delivery,
subject to receiving grants and context limits. A large report still requires selected retrieval,
and the Child Portal retains its existing bounded projection.

After OC-D173..175: a hook receives a bounded event snapshot, reads only explicitly permitted content,
and stages candidate files. The host validates installation at an appropriate boundary. A request for
model work or an external write becomes a normal admitted operation with its own controls. Persistent
notes can follow this output path when configured; the hook cannot rewrite authoritative workflow state.

After OC-D171/172: a durable assessment can trigger a configured ordinary preparation operation
with its own contract, budget and replay identity. A compaction hook can nominate bounded working
notes and exact references to retain; the host validates them and independently preserves required
state. These are two distinct boundaries, and neither grants scripts general workflow authority.

After OC-D168..170: the coordinator can inspect a poor partition and propose its successor, or
the mission can include an agentic planning step. Deterministic checks validate the resulting
membership, coverage and limits; they do not substitute for research judgment. Jev is a possible
approach mentioned by the owner, not a chosen dependency. Pressure-aware scheduling awaits evidence
from the dedicated local worker. New automatic computation caching is excluded from this version;
required recovery and explicit reuse are unchanged.

After OC-D165..167: within an application, an authorized separate review mission can receive the
exact held draft with findings and status before source-goal acceptance. Official use still waits
for its acceptance/use gates. Cancelling further upstream work does not by default stop a running
chain consumer using valid sealed inputs. Links work within each application; AI Engineer-to-Biotech
linking has not been selected as a feature. The owner explicitly confirmed this scope interpretation.

After OC-D162..164: setup determines whether overlapping conditions launch all matches or the first
match in declared order; it determines which populations a data join must account for; and it states
what must survive semantic partitioning or summaries. Processing every item does not establish
cross-item coverage. A reusable profile can carry these terms, with the effective choices inspectable.
These are accepted design requirements, not claims that runtime implementation is complete.

After OC-D159..161: the next session is a bounded final interview and specs/issues conversion,
not an unbounded architecture exploration. Mission-specific objectives, data choices and detailed
setup will be worked through with the coordinator before real launches. Prepare at most 20 questions
covering only decisive remaining choices; preserve accepted work and explicitly separate deferred scope.

After OC-D154..156: a collision on one key need not discard uncontested results. A fully supplied,
closed company group can reduce while another waits, but an empty queue alone never proves closure.
MC may build a deterministic reduction tree only under qualified result-preserving rules; a model
summary tree must be authored because regrouping can change meaning. Coverage and resource limits persist.

After OC-D151..153: a typed deterministic consolidation/partition stage can use a standard or
admitted custom transformation. Large collections retain exact member identities and outcomes across
execution batches; success need not be lost because another member failed. MC retains all planned
work durably but creates/admits bounded activation windows. Atomic groups remain explicitly authorable.

After OC-D147..149: missing condition evidence keeps a decision unknown and waiting, not false.
A fan-out freezes the exact company-list membership for that expansion; later additions need policy.
The owner requests justification of conditional routing before further design questions. Explain
specified capability versus actual data structures, with examples labelled illustrative.

After OC-D145/146: three new qualifying reports arriving during an incremental synthesis produce
one pending next synthesis by default, not three automatic parallel syntheses. Its exact eligible
membership is sealed at release. Separately, acceptance of unchanged held source A1 may trigger
authored bounded reassessment of retained provisional S1; S1 is never approved merely because A1 is.
This additional status-change case is explicitly in scope; general freshness automation remains deferred.

After OC-D144: A2 arriving during synthesis does not replace sealed A1 or automatically interrupt
the operation. Finish within budget, retain the result, then revalidate before current admission.
This applies while A1 remains permitted; revocation and mandatory stops keep their own force.

After OC-D141..143: a ready synthesis proceeds without a still-pending optional report and sees the
recorded omission. If an accepted revision of a tracked source report later makes completed synthesis
stale, arrange bounded authorized revalidation before rebuilding where needed. This sprint includes
that synthesis/report-revision case; general freshness/invalidation automation belongs to later sprints.
Other automatic cases require explicit inclusion. Historical input pins and effects remain preserved.

After OC-D139/140: if synthesis explicitly needs two interchangeable qualifying investigations,
seal the first qualifying pair to exact revisions. The third investigation continues within its
budget and its result may be retained for later explicit use. It does not silently change the
running synthesis. An authored bounded wait/ranking policy can trade latency for selection quality;
explicit cancellation never abandons other promises or effect/usage reconciliation.

After OC-D137/138: a normal continuing GoalDirected handoff includes a compact attributed work
summary alongside the host's authoritative state. An explicitly requested repair fork receives
selected exact drafts/files at its historical point plus accepted-set index and findings; their repair
status stays visible, and neither obligations nor effect authority transfer just because bytes do.

After OC-D133/134: with A1 accepted, B1 awaiting review and C missing, the next executor receives
compact goal/gap/wait state, an exact accessible accepted-set index and task-selected content.
It can work on C while B's durable wait remains. B1 enters context only for an authorized selected
purpose with its held status visible; neither C's progress nor a new invocation resolves B's wait.

Opening requirement, restated for review: at each agreed checkpoint, stop progression, run the
owner's applicable fixtures, inspect the Mission Transcript and referenced outputs/receipts against
the functional goals, repair the owning implementation or schema, and rerun before the gate passes.
The fixture inputs arrive after this interview. The concrete checkpoints and acceptance criteria
remain interview decisions.

After FC-Q16a (OC-D108): an AI-company report or biotech study appraisal is produced by one operation,
then independent judge/auditor operations run through MC's Deep Agents lane. They return attributable
observations to KS, which owns evidence sealing and use decisions. Temporal retains durable scheduling;
the producer cannot approve its own work.

After OC-D109..111: if evaluation times out, the report and completed work survive bounded retries
and a durable block; the system does not label the report false because an evaluator was unavailable.
If evaluators disagree without grounded contradiction, the assessment is held for repair/adjudication.
If review is required, MC retains the wait across restart while KS verifies the reviewer and appends
the exact successor decision. MC rechecks that decision and current eligibility before resuming.
Cancelling work does not let a late evaluator response silently reopen acceptance. No new numeric
retry limit or spend ceiling was chosen; those are supplied by the authored policy.

After OC-D112/113: a contract may ask for a recommendation or forecast for an explicitly allowed use.
Its evidence, reasoning, assumptions, uncertainty and horizon are assessed as a judgment; approval
does not make it an entailed fact. The mission selects an admitted review policy within application
minimums, with the required qualified reviewer. Policy selection cannot grant reviewer authority,
waive missing evidence or bypass current revocation. These are design changes to implement and prove.

After OC-D114..116: if three reports are promised and two valid reports are submitted, both candidates
and their assessments survive while fulfillment still identifies the missing third deliverable.
A study appraisal and an AI-company report share general output forms but enforce different pinned
content contracts. The next operation receives only the exact selection named in its sealed transfer
plan; separate receipts establish that those inputs actually arrived and were accessible.

After OC-D117..119: an ingestion obligation waits for native effect proof and any required readback;
neither a report nor an authorization substitutes for the effect. A missing expected report is a
visible shortfall, while a missing required report prevents completion. Every required transfer gets
host-assembled authoritative state; an agent's semantic handoff supplements it when contracted.

After OC-D121/122: a held report can reach an authorized repair consumer without satisfying an
official-use contract. Both initial and dependent invocations use the same materialization entry
point, with boundary-specific state. OC-D120 was tentative until the configuration/placement
walkthrough in [CONTRACTS.md](CONTRACTS.md); OC-D123/124 now explicitly close that clarification.

After OC-D123/124: the active run revision owns transfer policy. The producer submits R7; the host
later resolves the receiver's named input to R7, applies that receiver's effective placement rules,
and seals/delivers its plan. The producer's submission does not choose the receiver's context policy.
Files are available content, not full bytes in the initial prompt; their later reads consume context.

After OC-D125: the coordinator can inspect what each node was configured to receive, what was
submitted/fulfilled, and how exact inputs were delivered. The sprint adds those operational reads and
events through the existing control path; the broader coordinator redesign is deferred. The two
remaining questions in this batch concern when to wake the coordinator and how to route errors.

After OC-D126/127, answered the next morning: a blocked required input creates an actionable durable
notification with the exact affected operation and recovery information. Routine transfers remain
inspectable without waking the coordinator on every transition. A correctable submitted handle goes
back for bounded model repair; an uncertain native write goes to host reconciliation under its existing
effect identity. The report/provider result survives; a delivery or settlement problem does not imply
that successful cognition or an already committed write must run again.

After OC-D128: once a checkpoint's prerequisites are ready, run the supplied real AI-company or
biotech task through its actual required agents/services, inspect the Transcript and outputs against
the functional goals, repair and rerun. This is permitted qualification work before the full runtime
is finished. It does not open routine research/general use or label synthetic plumbing proof as
functional acceptance. The exact fixtures still arrive after this interview.

After OC-D129/130: each W0–W5 checkpoint stops progression. The implementation coordinator supplies
the retained evidence to a separate reviewing agent; only an evidence-backed pass on every required
criterion permits the coordinator to record release. Failures are fixed and rerun; unclear criteria
or required human decisions come to the owner. This engineering release never substitutes for a KS
use decision, native admission or qualified scientific review.

Here, the owner's "transcription" is read as the existing glossary's **Transcript**: the replayable
view joining mission events, provider frames and artifact references. Whether those observations
prove a functional goal must be assessed explicitly; provider success alone cannot pass the gate.

## Verified opening baseline

OC-D131/132 continuation: the actual fixtures determine the eventual task mapping. The common
foundation remains accepted, but workflow-specific and hook behavior needs the requested deeper
interview. An emitted hook event does not imply state access or return-value enforcement, and parsed
dependency syntax does not prove ordinary runtime lowering. Coordinator notices and content retrieval
are distinct. The working walkthrough remains provisional until these details are resolved.

Read-only source inspection on 2026-10-25, MC `main` at
`1863017c779a1b138951c19a0abfcadc4f839a84`, one registered checkout, initially clean.
GPT 6.1 Sol explorers checked MC, KS and Biotech seams. No runtime tests, paid fixtures, migrations,
deployments or tracker mutations were performed in this opening round. Prior proof counts remain
historical evidence.

Paths in this table are relative to BellLabs; MC prefix is `platform/mission-control/` and KS prefix
is `platform/knowledge-services/`.

| Fact | Source checked |
| --- | --- |
| RV-01 remains open: adapter discards the completion report. | MC `src/mission_control/adapters/deep_agents/adapter.py:280` |
| RV-02 has a bounded repair: report selections must contain one member. Collection assessment remains absent. | MC `src/mission_control/application/outputs/submission_service.py:477` |
| RV-03 remains open: delivery starts with run-wide finalized selections, not explicit predecessors. | MC `src/mission_control/application/knowledge/toolset.py:376` |
| RV-05 is partially repaired: aggregate file bytes preflight before staging; no unified prompt/token plan. | MC `src/mission_control/application/knowledge/toolset.py:392`; `src/mission_control/application/context/delivery.py:140` |
| RV-04 remains open: ordinary MC composition uses an in-memory use-decision store with no production populator found. | MC `src/mission_control/bootstrap/composition.py:588`; `src/mission_control/application/knowledge/gateway.py:293` |
| KS has trusted internal observation, audit, seal and decision methods, but its published switch does not compose the whole route. | KS `packages/application/src/research/coordinator.ts:364`, `:371`, `:526`, `:649`; `packages/host/src/knowledge-operation/service.ts:194` |
| `report.assess` audits and aggregates; it does not itself seal or decide the use. Without an injected auditor or explicit proof double, assessment is unavailable. | KS `packages/application/src/research/assessment.ts:155`; `packages/host/src/knowledge-operation/config.ts:109`; `service.ts:223` |
| RV-06 native-commit/protocol-receipt crash recovery still needs its exact fault proof; RV-08 operational reads do not prove native official-use eligibility. | KS `packages/host/src/knowledge-operation/service.ts:606`, `:497`; MC `src/mission_control/application/context/resolution.py:133` |
| Release 1.6.0 has output_submission and invocation_finalization, no obligation_fulfillment table. Full transfer profiles and typed handle/receipt frame joins remain unfinished. | MC `packages/mission-control-db-contract/releases/1.6.0/component/migrations/0053_submissions.sql:9`, `:115`; `src/mission_control/domain/frames/contracts.py:164`; `src/mission_control/application/context/delivery.py:129` |

OC-D98 already allows either semantic host and requires independent identity, pinned step contracts
and KS deterministic execution. Both choices need trusted KS ingress, sealing, exact-use decisions,
review and durable decision resolution. MC hosting additionally needs separate evaluator operations
and their context/lifecycle; KS hosting additionally needs provider-backed evaluator/auditor adapters
and their model lifecycle. The MC-first recommendation reuses the chosen execution lane; it is not
a claim that fewer missing modules have been proven.

## Assumptions (asked, not answered)

**Final capped interview, first round, 2026-10-26:** F20-01..03 are answered and folded as
OC-D162..164. Second round Q4..6 (F20-05..07) is answered as OC-D165..167, including explicit
confirmation of the single-application scope interpretation. Third round Q7..9 (F20-08..10) is
answered as OC-D168..170: coordinator/agentic partition repair, scheduling-policy decision postponed
for local worker evidence, and automatic computation caching excluded. No question is pending at this
checkpoint; the pressure-aware policy remains explicitly undecided. Fourth round Q10/Q11
(F20-11/F20-16) is answered as OC-D171/172, and fifth round Q12..14 (F20-12..14) as OC-D173..175.
F20-15 is skipped as a redundant consequence. Sixth round Q15 (F20-17) is answered as OC-D176.
Q16/Q17 (F20-18/19) remain pending: specialized code-integration scope and integrated preflight
extension. Neither recommendation is assumed accepted. Latest owner steering OC-D177–181 now
requests synthesis/publication; the next unused decision is OC-D182. Do not restart the queue automatically.
Research and engineering consequences remain separately recorded in
[DOC-20](FINAL-INTERVIEW-RESEARCH-2026-10-26.md).

FC-Q22c/d were answered as OC-D137/138 before the owner moved sessions; do not re-ask them.
FC-Q23a..i are answered through OC-D148; OC-D149 requests the conditional-routing explanation.
No answer is inferred for the remaining Stage Graph, linked/nested workflow, hook or coordinator agenda.

FC-Q27a/b/c are answered as OC-D151..153. The illustrative 20,000 sources/200 slices is not a fixture
or scale acceptance target. No pending proposal is assumed accepted.

FC-Q27d/e/f are answered as OC-D154..156. No pending proposal is assumed accepted.

FC-Q27d/e/f grounding: compute proposal `:227–294` proposes conflict/tree policies, not accepted
semantics. Earlier OC-D44 (`SPECIFICATION.md:259–263`) permits faithful contradictory/inconclusive
reports. Fixed dependency joins (`domain/authoring/contracts.py:533–599`, interpreter `:185–214`)
do not implement keyed grouping/closure. `03-PARALLEL_SWARM.md:84–104` distinguishes all, quorum,
best effort and qualifying accepted members; do not import its sibling cancellation default over
OC-D140. No typed algebra declaration or qualified tree planner is established by deterministic
executor syntax or the versioned handler seam. The old fan-in formula's minimum-two clamp cannot
waive resource/readiness limits. Two GPT 6 Astra explorers provided read-only evidence.

FC-Q27 source grounding, 2026-10-26: deterministic executor/coalesce is canonical in
`05-EXECUTORS_AND_DURABLE_CONTROLS.md:134–153`; manifest declares it at `manifest.py:824–838`.
No named deterministic-kind dispatcher was found in the ordinary stage launch path
(`application/authoring/manifest_launch_inputs.py:1726–1748,1808–1834`). Versioned handlers exist
at `application/programs/orchestration_routing.py:54–108,122–164`, but do not prove manifest wiring.
Current frontier scans/sorts projection candidates (`domain/programs/interpreter.py:229–259`);
Temporal rollover waits for no active children (`adapters/temporal/workflows/stagegraph.py:1010`).
Two GPT 6 Astra read-only explorers checked reducer and scale seams. No workload benchmark or
runtime qualification was run. Later questions must address reduction algebra/order, conflicts,
hierarchy, hot groups/stragglers, resource caps and safe optimization without assuming answers here.

Stage Graph frontier audit, 2026-10-26 (GPT 6 Astra, read-only): `01-STAGE_GRAPH.md:64,85–87,175`
establishes typed facts/waits but leaves conditional semantics open; `domain/authoring/contracts.py:533–599`
and `domain/programs/interpreter.py:180–215` implement dependency joins, not arbitrary conditionals.
Dynamic templates/identity/cardinality are normative at `01-STAGE_GRAPH.md:123–127`; membership cutoff
still needs the owner choice above. Carry forward without re-asking: explicit permitted degradation;
complete collections versus authored subset/coverage under OC-D58; bounded Revisit Regions with
progress and activation lineage (`01-STAGE_GRAPH.md:97–119,165–169`). Current static cycle rejection
(`domain/authoring/manifest.py:1568–1574`) is an implementation gap, not a scope deferral.

Source check for FC-Q23f/g, 2026-10-26: earlier `SPECIFICATION.md:336–345` accepts incremental
release but leaves batching details proposed; earlier `CONTRACTS.md:211–217` proposes dispatch/coalescing.
Paths here refer to `answers/gpt-6-astra-2026-10-24/`. Normative Stage Graph `01-STAGE_GRAPH.md:135`
preserves provisional derived status and its gate restrictions. OC-D121 permits authorized draft/held
review/repair, not automatic derived approval. Current `domain/context/packet.py:330–331,796–798`
rejects mandatory provisional items or forces them nonmandatory; `domain/programs/interpreter.py:1202`
emits provisional=False. Required delivery and use eligibility must be separated under existing policy;
these gaps are implementation consequences, not new owner questions. GPT 6 Astra reviewed source;
no runtime proof is claimed.

Source check for FC-Q23c/d, 2026-10-26: Stage Graph specification `01-STAGE_GRAPH.md:56–64`
requires resolution of required inputs; current `domain/programs/interpreter.py:163–178` nevertheless
waits for unresolved optional dependencies. `CONTRACTS.md` §3 records optional omissions without
settling the pending-source cutoff. Earlier OC-D49 (`answers/gpt-6-astra-2026-10-24/ANSWERS.md:69`)
already requires tracked staleness and no automatic rerun of every descendant; OC-D101 preserves
revocation/reconciliation constraints. `domain/programs/interpreter.py:584–654` implements cycle
invalidation and new candidates, not proof of dependency-scoped compatibility revalidation.
GPT 6 Astra performed the read-only source review. No runtime qualification claimed.

Source recheck at MC `1863017c`, 2026-10-26: `mission-control-general/workflow-types/01-STAGE_GRAPH.md:34–41` (deleted 2026-11-01; last at `66185d2e`)
already separates dependency edges, data bindings and release gates; this is not a new question.
`src/mission_control/domain/authoring/contracts.py:552–579` exposes slow-sibling policies and joins;
`src/mission_control/domain/programs/interpreter.py:179–220` counts qualifying dependency dispositions.
`src/mission_control/domain/authoring/stagegraph_builder.py:67–100` still selects the first producer
output and builds required/all joins, so these source mechanisms do not prove full authored any/quorum
input selection. OC-D72 already preserves settlement accountability. No runtime qualification claimed.

Source grounding for FC-Q17c/d, rechecked 2026-10-25: KS
`packages/research-core/src/records/assertion.ts:8-13` distinguishes recommendations/forecasts from
fact entailment; `packages/research-core/src/verification/aggregate.ts:176` gates non-entailed
assertions for official use. MC `SPRINT-V-DESIGN.md:476` records OQ4 as open: draft/internal use may
require review; official/critical use remains excluded. KS `catalog/research/use-classes.json:6-8`
already contains coarse use/risk classes; this does not settle the complete review policy catalogue.
KS `packages/application/src/research/review.ts:23-30,83-139` binds review to exact decisions and
live grants; approval cannot waive mechanics. Scientific consequential human sign-off is already
required by SV-D9 and is not reopened by these questions. OC-D112 now changes the target OQ4
policy; the implementation inspected above still enforces the old exclusion.

Round A source checks (2026-10-25, same MC HEAD):

- `src/mission_control/application/outputs/submission_service.py:265` falls back to submitted
  obligations when the declared set is empty; current release 1.6.0 has `output_submission` and
  `invocation_finalization`, no `obligation_fulfillment`. This is an implementation gap, not a revision
  of previously accepted required-output semantics.
- Checkpoint `CONTRACTS.md` §3.1..3.3 distinguishes the eight forms, domain content constraints,
  immutable submissions, per-requirement assessments and fulfillment at an evaluation frontier.
- `src/mission_control/adapters/postgres/context/selection_repository.py:47` still stores sealed
  packets and authority selections; `src/mission_control/application/context/delivery.py:129`
  creates M04 delivery plans separately. Consolidation must preserve both sets of facts.
- The HG supplement was located at BellLabs `platform/HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md`;
  its proposed decisions and the current human-task implementation are being compared for FC-Q2.

## Parking lot

- FC-Q27 (OC-D150): explore large-workload Stage Graph structure before moving past this topic;
  reducers, collection manifests, partitioning/grouping, obligations, partial failure/selective repair,
  hierarchical reduction, scheduling/backpressure, and optimizer semantics. Carry original linked,
  conditional multiplicity, hooks and coordinator scope forward; no silent deferral or premature kickoff.

- FC-Q2/3: fold the source-backed schema inventory and old OC-D dispositions into the final pack; no owner answer is needed to rediscover existing tables. Existing MC human tasks carry typed KS review bindings; no second human-task system is assumed.
- FC-Q5/20: OC-D125 accepts focused operational scope; OC-D126 now accepts notification defaults. CS-D1..14 are coordinator-surface decisions, not fourteen transfer fields. Complete the per-row scope disposition without marking deferred designs accepted. OC-D127 accepts the relevant error contract only, not the whole FT program.
- FC-Q13/21: OC-D128 permits real qualification fixtures; OC-D129/130 accept the waves and independent checkpoint release. Integrate exact owner fixtures after the interview; preserve mandatory repair/rerun and both-app proof.
- FC-Q15: finish the full contract/work-item conversion, ADR dispositions and issue filing after the decision frontier is answered. Interview remains open.
- FC-Q22..26 (OC-D132/135): detailed workflow/context rounds precede FC-Q15. Q22c/d are now accepted as OC-D137/138. Resume via SE-11 with StageGraph, then linked/nested intra/inter-workflow transfer, Deep Agents hook event/state/context and coordinator output/subscription details. No final confirmation is inferred; further GoalDirected choices are asked only when genuinely unresolved.

## Conversion checklist

- [x] Decisions folded into the decision logs of the specification and supplements (links in **Folded**)
- [x] ADR candidates written for decisions with a lasting reason
- [x] Glossary terms added through `domain-modeling`
- [x] Linear: a comment on each decided issue; an issue filed for each accepted piece of work, ids in **Becomes**
- [x] Ledger: this file's row and the instruction's row updated
