---
type: Interview Answers
title: "Output obligations across workflows: GPT-6-Astra interview, sitting I"
description: "Independent interview record for the model-comparison experiment: verbatim owner answers, source-grounded recommendations, open decisions and destinations for sprint specifications."
tags: [mission-control, interview, answers, output-contracts, context-transfer]
interview: ../../providers/deep_agents/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md
interview_id: output-obligations-gpt-6-astra-2026-10-24
sitting: "I"
date: 2026-10-24
timezone: America/New_York
interviewer_model: "GPT-6-Astra"
model_label_source: "Owner-supplied experiment label; exact serving model not independently exposed in this session"
research_assistant_model: "GPT-6.1-Sol"
comparison_counterpart: "Anthropic Fable 5.1 (owner-supplied label)"
comparison_status: "Independent; counterpart interview not read or merged"
repository: platform/mission-control
source_branch: main
source_commit: 8de6fab94fd5d17d79f2ecfd92e55329bb282a36
status: final
checkpoint_status: accepted
checkpoint_date: 2026-10-24
future_revision_policy: "Accepted checkpoint; owner may revise decisions in a subsequent session"
---

# Output obligations across workflows: interview answers

<!-- final-output-contracts-2026-10-26 -->
**Final conversion, 2026-10-26:** [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) and the [implementation packet](../../../../provider-consolidation-2026-10/sprint-oc/README.md) now carry the final specification, five ADRs and 31 published work items. [Every decision destination](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) is recorded; source quotes and historical checkpoint language are retained. No runtime qualification is claimed. F20-18/19 remain unselected, with no fabricated answers. Older resume/planning instructions below are historical.


Recorded by the interviewing assistant on 2026-10-24. The owner's current brief controls this
sitting. The linked output-contract document and the existing sitting-I instruction are source
material, not authorization to assume their recommendations were accepted or expand this interview
into unrelated upgrade work. This exact `ANSWERS.md` filename follows the owner's request; the
model/date directory keeps the experiment's records separate.

This sitting is finalized as an accepted checkpoint, subject to revisions in the next session (OC-D78).
Owner answers are quoted verbatim; interpretations and recommendations are
labelled separately. No unanswered recommendation is an accepted decision. Existing decision IDs
remain intact; new output-contract decisions continue after OC-D26 and are scoped by `interview_id`
when compared with another interview. No implementation, issue creation or issue-status change has
occurred in this sitting.

## Decisions

OC-D27..31 are explicit instructions in the opening brief. Subsequent rows record interview answers;
multiple decisions expressed in one reply have separate rows with exact quoted excerpts.

| ID | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- |
| OC-D27 | How broad is the output-contract design? | "The output contracts and obligations need to span general to specific application content." | 2026-10-24 | Design common contracts plus domain-specific content semantics; work out workflow and provider boundaries. | spec SPECIFICATION.md §1; GLOSSARY Output Contract; final conversion: OUTPUT-CONTRACTS §§1, 2; OVE-163, OVE-186 | [Specification §1](SPECIFICATION.md#1-confirmed-scope-and-ownership); [glossary](../../../../../../GLOSSARY.md); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D28 | May absent content models block this design? | "I don't yet have all the content modeled in the databases (neo4j for biotech, postgres for ai engineer) -- for the knowledge/content databases I mean. You need to assume that it exists ." | 2026-10-24 | Treat domain models as a design premise, while avoiding claims that their schemas or services are implemented. | spec SPECIFICATION.md §1; final conversion: OUTPUT-CONTRACTS §§1, 2, 12; OVE-168, OVE-186 | [Specification §1](SPECIFICATION.md#1-confirmed-scope-and-ownership); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D29 | Which concrete domain examples must the design cover? | "Curriculum, Courses, Challenges, Projects for ai engineer. Evidence backed reports are common among the two though modeled in their respective databases." | 2026-10-24 | Include worked AI Engineer content examples and evidence-backed report examples for both domain stores. | spec SPECIFICATION.md §1; final conversion: OUTPUT-CONTRACTS §§2, 13; OVE-163, OVE-186 | [Specification §1](SPECIFICATION.md#1-confirmed-scope-and-ownership); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D30 | Does producing an output imply ingestion? | "Now an output contract doesn't equal ingestion. It still has to be ingested. This is actual helpful as a separation of concerns." | 2026-10-24 | Preserve independent output production, validation/acceptance and domain ingestion outcomes. | spec SPECIFICATION.md §1; GLOSSARY Output Obligation; final conversion: OUTPUT-CONTRACTS §§2, 5, 13; OVE-163, OVE-165, OVE-167, OVE-189 | [Specification §1](SPECIFICATION.md#1-confirmed-scope-and-ownership); [glossary](../../../../../../GLOSSARY.md); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D31 | What must this interview produce? | "Our goal is to resolve as much detail about these features as possible and produce an ANSWERS.md and specifications that can be translated into exact issues in a sprint." | 2026-10-24 | Keep an attributable answer record and derive specifications with testable acceptance criteria and issue boundaries. | This record and spec SPECIFICATION.md §6; final conversion: OUTPUT-CONTRACTS §§1, 12; OVE-162 (synthesis disposition) | This file; [issue boundaries](SPECIFICATION.md#6-issue-boundaries-and-acceptance-examples); [17 issue specifications](WORK-ITEMS.md), proposed implementation; [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D32 | Round 1 Q1: What should total output mean? | "We need to permit stages having a set of deliverables. In specific scenarios we can contract final deliverables of the entire stage graph (while preserving intermediate output) but we want stages to be able to encode deliverable obligations. Think about a deep agents cycling stage." | 2026-10-24 | Corrects the interviewer's final-package framing: stage obligations are first-class; aggregate Stage Graph deliverables are additional and scenario-dependent. Cycle accumulation was subsequently resolved by OC-D45..48. | spec SPECIFICATION.md §2; GLOSSARY Output Obligation; final conversion: OUTPUT-CONTRACTS §§2, 7, 9; OVE-163, OVE-170, OVE-171, OVE-176 | [Specification §2](SPECIFICATION.md#2-confirmed-obligation-ownership-and-partial-results); [glossary](../../../../../../GLOSSARY.md); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D33 | Round 1 Q2: Must content production always yield a structured domain package? | "That is what we are developing now -- structured packages or documents for content types or purpose types. I think I wasn't clear enough." | 2026-10-24 | Does not accept a single prescribed package shape; requires the interview to develop a spectrum of content/purpose contracts. | spec SPECIFICATION.md §1 and §3; final conversion: OUTPUT-CONTRACTS §§2; OVE-163, OVE-186 | [Specification §1](SPECIFICATION.md#1-confirmed-scope-and-ownership); [output spectrum](SPECIFICATION.md#3-output-spectrum-and-contract-composition); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D35 | Round 1 Q2 clarification: Which application purposes were missing? | "Remember that each application I build has a financial / economic side to it. biotech companies and ai native/innovative companies. We are going to produce real market content. Then there is education for ai engineer. There is biotech evidence reports." | 2026-10-24 | Expands worked examples to financial/economic and market content in both domains, alongside education and biotech evidence; these are not exclusive work classes. | spec SPECIFICATION.md §1; final conversion: OUTPUT-CONTRACTS §§2, 5, 13; OVE-163, OVE-165, OVE-186 | [Specification §1](SPECIFICATION.md#1-confirmed-scope-and-ownership); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D36 | Round 1 Q2 clarification: Can an output reference other already-ingested outputs? | "But what about the spectrum of outputs. What if one stage's output declaration is just a structured output of the reports they create. So that is a layered output contract. Actual ingested reports -> structured output referencing their location." | 2026-10-24 | Requires layered contracts: a structured index can refer to substantive reports held in the domain store. Exact guarantee selection was subsequently resolved by OC-D39. | spec SPECIFICATION.md §4; GLOSSARY Output Contract; final conversion: OUTPUT-CONTRACTS §§2, 5, 8, 13; OVE-163, OVE-165, OVE-167, OVE-170 | [Specification §4](SPECIFICATION.md#4-layered-report-index-scenario); [glossary](../../../../../../GLOSSARY.md); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D37 | Round 1 Q2 clarification: Is the architecture limited to the two present applications? | "Can you please concentrate on this range of output types GENERAL TO APPLICATION SPECIFIC. You know mission control is supposed to be general and able to work with any application and its knowledge services." | 2026-10-24 | Any application must be able to participate; no closed AI Engineer/Biotech-only semantics in the generic output model. | spec SPECIFICATION.md §1; final conversion: OUTPUT-CONTRACTS §§1, 2, 5; OVE-163, OVE-164, OVE-168 | [Specification §1](SPECIFICATION.md#1-confirmed-scope-and-ownership); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D34 | Round 1 Q3: What happens to usable deliverables when another required output is missing? | "Keep usable deliverables; mission incomplete; explicit partial consumption (Recommended)" | 2026-10-24 | Accepts retaining individually usable deliverables without treating the mission as complete; downstream partial consumption is explicit. | spec SPECIFICATION.md §2; final conversion: OUTPUT-CONTRACTS §§4, 7, 9, 10; OVE-166, OVE-170, OVE-171, OVE-176, OVE-179 | [Specification §2](SPECIFICATION.md#2-confirmed-obligation-ownership-and-partial-results); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D38 | Round 2 Q4: How do common output forms become application/purpose contracts? | "Common forms + composable application/purpose contracts (Recommended)" | 2026-10-24 | Accepts composable, versioned specialization rather than a new kernel kind for every domain content type. | spec SPECIFICATION.md §3; final conversion: OUTPUT-CONTRACTS §§2; OVE-163 | [Specification §3](SPECIFICATION.md#3-output-spectrum-and-contract-composition); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D39 | Round 2 Q5: Which layers of a reference output must be checked? | "Declare required guarantees; validate each declared layer (Recommended)" | 2026-10-24 | The contract explicitly selects guarantees over shape, referenced content and ingestion; every declared layer must pass. | spec SPECIFICATION.md §4; GLOSSARY Output Guarantee; final conversion: OUTPUT-CONTRACTS §§2, 4, 5; OVE-163, OVE-165, OVE-167, OVE-170 | [Specification §4](SPECIFICATION.md#4-layered-report-index-scenario); [glossary](../../../../../../GLOSSARY.md); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D40 | Round 2 Q6: May a mission use an inline contract without prior reusable-template registration? | "Great question. I choose 1. YES we want these kind of inline dynamic output contracts possible because the \"right\" dataset or output shape might depend on the mission . So Yes." | 2026-10-24 | Accepts mission-specific inline schemas/requirements as well as reusable contracts; new validator/resolver authority still comes from admitted capabilities. Runtime revision scope is settled separately by OC-D42. | spec SPECIFICATION.md §3 and §8.1; GLOSSARY Inline Output Contract; final conversion: OUTPUT-CONTRACTS §§2, 3; OVE-163 | [Specification §3](SPECIFICATION.md#3-output-spectrum-and-contract-composition); [dynamic contracts](SPECIFICATION.md#81-inline-authoring-and-governed-evolution); [glossary](../../../../../../GLOSSARY.md); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D41 | Round 2 Q6 clarification: How does research verification connect to output contracts? | "Furthermore verification , evidence adjudication -- effectively the path from search/discovery -> assertion -> verification/judgement -> verdict -> report is kind of a standard validated research process. Right now the verification module in knowledge services has general processes but writes to specific tables/nodes in postgres and neo4j. I suppose this is a more of a report and report provenance verification question than output contracts but you see how they might together." | 2026-10-24 | Adds report/provenance assurance to the design frontier. The owner's description motivates inspection; it does not establish identical implemented verification pipelines for both databases. | spec SPECIFICATION.md §8.2-8.4; final conversion: OUTPUT-CONTRACTS §§5; OVE-165, OVE-167, OVE-168 | [Research assurance](SPECIFICATION.md#82-the-research-process-and-the-output-contract); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D42 | Round 3 Q7: Can output contracts evolve during execution? | "Inline contracts plus governed revisions during execution (Recommended)" | 2026-10-24 | Supports governed runtime revisions in addition to inline authoring; each submission binds a contract version and historical failures cannot silently become passes. | spec SPECIFICATION.md §8.1; final conversion: OUTPUT-CONTRACTS §§3, 4, 10; OVE-163, OVE-175, OVE-179 | [Dynamic contracts](SPECIFICATION.md#81-inline-authoring-and-governed-evolution); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D43 | Round 3 Q8: Must a traceable research process use one fixed workflow shape? | "Require declared evidence/provenance; allow different workflow shapes (Recommended)" | 2026-10-24 | Declared provenance requirements can be fulfilled in one/multiple stages, through subagents or by reusing verified material; an explicit workflow template may impose sequence. | spec SPECIFICATION.md §8.2; final conversion: OUTPUT-CONTRACTS §§5, 9; OVE-165, OVE-176, OVE-177, OVE-178, OVE-186 | [Research assurance](SPECIFICATION.md#82-the-research-process-and-the-output-contract); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D44 | Round 3 Q9: Can a validated report faithfully describe contradicted or inconclusive claims? | "Faithful provenance plus purpose-specific verdict and coverage policy (Recommended)" | 2026-10-24 | Report acceptance does not equal every underlying claim being positively supported; each intended use controls admissible verdicts and coverage gaps. | spec SPECIFICATION.md §8.2; final conversion: OUTPUT-CONTRACTS §§4, 5; OVE-165, OVE-169, OVE-186 | [Research assurance](SPECIFICATION.md#82-the-research-process-and-the-output-contract); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D45 | Round 4 Q10: Can a cycling stage combine per-cycle and accumulated obligations? | "Allow both per-cycle and accumulated stage obligations (Recommended)" | 2026-10-24 | Supports an index every cycle alongside deliverables accumulated over the whole stage. Cycle progress is distinct from stage completion. | spec SPECIFICATION.md §9.1; final conversion: OUTPUT-CONTRACTS §§2, 7; OVE-163, OVE-170, OVE-171 | [Cycle obligation scope](SPECIFICATION.md#91-scope); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D46 | Round 4 Q11: How do report revisions and company coverage count? | "Count distinct identities; retain revisions; declare subject coverage separately (Recommended)" | 2026-10-24 | New accepted revisions replace the current view without increasing distinct-item count; history remains; subject coverage is an independent condition. | spec SPECIFICATION.md §9.2; final conversion: OUTPUT-CONTRACTS §§2, 4, 8; OVE-163, OVE-170, OVE-174 | [Identity, revisions and coverage](SPECIFICATION.md#92-identity-revisions-and-coverage); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D47 | Round 4 Q12: When may downstream stages consume a cycling stage's work? | "Wait by default; allow explicitly declared incremental delivery (Recommended)" | 2026-10-24 | Default producer-completion gate; optional incremental binding requires trigger and revision treatment. Distinct from partial consumption after incomplete termination. | spec SPECIFICATION.md §9.3; final conversion: OUTPUT-CONTRACTS §§3, 7, 10; OVE-171, OVE-175, OVE-176, OVE-179 | [Consumer release](SPECIFICATION.md#93-consumer-release); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D48 | Round 4 Q13: Does fulfillment stop cycling? | "Default stop on fulfillment; allow additional completion conditions (Recommended)" | 2026-10-24 | Required fulfillment is the default stopping rule; additional authored review/coverage conditions apply; resource/cycle limit does not imply success. | spec SPECIFICATION.md §9.4; final conversion: OUTPUT-CONTRACTS §§2, 4, 7; OVE-163, OVE-169, OVE-170, OVE-171, OVE-186 | [Completion and limits](SPECIFICATION.md#94-completion-and-limits); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D49 | Round 5 Q14: What happens when a producer revision changes a consumer's inputs? | "Track revisions by default; mark affected work stale; allow explicit snapshots (Recommended)" | 2026-10-24 | Preserve exact consumed-version provenance; affected work is stale for the current view until revalidated/rebuilt, unless an explicit snapshot binding pins the earlier version. External effects are not silently undone. | spec SPECIFICATION.md §10.1; final conversion: OUTPUT-CONTRACTS §§4, 6, 10; OVE-164, OVE-175, OVE-179 | [Revision impact](SPECIFICATION.md#101-tracked-revisions-and-historical-snapshots); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D50 | Round 5 Q15: What should the GoalDirected verifier assess? | "Verify the current goal-wide set; reuse valid prior evidence (Recommended)" | 2026-10-24 | Verifier and terminal output cover the current goal-wide set, including earlier valid work; retain iteration-specific results/findings. | spec SPECIFICATION.md §10.2; final conversion: OUTPUT-CONTRACTS §§4, 7; OVE-165, OVE-169, OVE-170 | [GoalDirected verification](SPECIFICATION.md#102-goaldirected-verification); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D51 | Round 5 Q16: What should total output expose? | "Current deliverables by owner/obligation, history separate, optional final view (Recommended)" | 2026-10-24 | Default current grouped view plus historical view; an explicit final contract adds a selected final view. | spec SPECIFICATION.md §10.3; final conversion: OUTPUT-CONTRACTS §§3, 4, 9, 12; OVE-170, OVE-182 | [Output views](SPECIFICATION.md#103-total-output-views); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D52 | Round 5 Q17: What context is mandatory between cycles/iterations? | "I choose 1." | 2026-10-24 | Accepts the recommended mandatory current-state handoff, reliable declared inputs and on-demand history; missing required context blocks/repairs rather than silent omission. | spec SPECIFICATION.md §9.5; spec CONTEXT-TRANSFER.md §1; final conversion: OUTPUT-CONTRACTS §§6, 7, 11; OVE-164, OVE-169, OVE-170, OVE-181 | [Cycle transfer](SPECIFICATION.md#95-context-for-the-next-cycle); [transfer guarantees](CONTEXT-TRANSFER.md#1-confirmed-requirements); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D53 | Round 5 Q17 steering: What should the interview prioritize next? | "Now I now you are going through your sequence and resolving as many details as you can. Please focus considerable effort on how context transfer works both contractually and in the mission and between missions so between workflows. Do we contract out context transfer and allow for configuration or is it completely system policy based and a coordinator agent or client caller doesn't control context transfer" | 2026-10-24 | Prioritizes transfer contracts within and between missions and caller/coordinator configuration. Answered through source inspection and round 6; this steering is not itself acceptance of a particular authority model. | spec CONTEXT-TRANSFER.md; final conversion: OUTPUT-CONTRACTS §§3, 6, 9, 10; OVE-164, OVE-176, OVE-179 | [Dedicated transfer specification](CONTEXT-TRANSFER.md); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D54 | Round 6 Q18: Who can author transfer behavior and at which levels? | "Authorable transfer contracts with defaults/overrides and system enforcement (Recommended)" | 2026-10-24 | Same versioned contract for callers/coordinators; reusable/inline settings, mission defaults and per-input/link overrides; enforce policy and refuse conflicting hard requirements. | spec CONTEXT-TRANSFER.md §1 and §3; final conversion: OUTPUT-CONTRACTS §§3, 6, 12; OVE-163, OVE-164, OVE-182 | [Transfer requirements](CONTEXT-TRANSFER.md#1-confirmed-requirements); [authority and configuration](CONTEXT-TRANSFER.md#3-authority-and-configuration); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D55 | Round 6 Q19: May packing downgrade a consumer's required delivery form? | "Declare required access/form and allowed alternatives explicitly (Recommended)" | 2026-10-24 | Separate requirement from preference; choose among authored alternatives only; a summary or unusable ref cannot replace required content. | spec CONTEXT-TRANSFER.md §4; final conversion: OUTPUT-CONTRACTS §§3, 6; OVE-164, OVE-184 | [Transfer agreement](CONTEXT-TRANSFER.md#4-transfer-agreement-proposed-fields); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D56 | Round 6 Q20: What crosses a mission/workflow boundary by default? | "Explicit outputs + required provenance/state; broader history opt-in (Recommended)" | 2026-10-24 | Explicit output mappings and required proof/state; scoped opt-in history; receiving mission keeps its own authority/goals/budget/obligations; unfinished work needs explicit adoption. | spec CONTEXT-TRANSFER.md §5; final conversion: OUTPUT-CONTRACTS §§6, 9, 10; OVE-164, OVE-176, OVE-179 | [Boundary semantics](CONTEXT-TRANSFER.md#5-boundary-semantics); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D57 | Round 6 Q21: Can an agent prepare context? | "Allow explicit, budgeted context-preparation operations (Recommended)" | 2026-10-24 | Optional declared preparation has its own budget, source refs and output contract; supplements authoritative state and required inputs; deterministic final assembly. | spec CONTEXT-TRANSFER.md §6; final conversion: OUTPUT-CONTRACTS §§3, 6, 11; OVE-164, OVE-180, OVE-183 | [Preparation and delivery](CONTEXT-TRANSFER.md#6-preparation-sealing-and-delivery); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D58 | Round 7 Q22: How far should a referenced index expand during transfer? | "Explicit bounded expansion of selected content and relationships (Recommended)" | 2026-10-24 | Select named members/relationships with explicit bounds; output guarantee validation does not imply recursive transfer of every referenced object. | spec CONTEXT-TRANSFER.md §10.1; final conversion: OUTPUT-CONTRACTS §§3, 6, 8; OVE-164, OVE-170, OVE-173 | [Bounded expansion](CONTEXT-TRANSFER.md#101-bounded-expansion); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D59 | Round 7 Q23: How long must required inputs remain usable? | "Guarantee required availability for the declared consumption/recovery period (Recommended)" | 2026-10-24 | Secure retention or a permitted immutable snapshot/export for consumer execution and configured recovery/replay; refuse if neither can satisfy the declared period. | spec CONTEXT-TRANSFER.md §10.2; final conversion: OUTPUT-CONTRACTS §§4, 6, 11; OVE-164, OVE-181, OVE-168 | [Availability](CONTEXT-TRANSFER.md#102-availability-and-recovery); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D60 | Round 7 Q24: What transfer control is available during execution? | "Governed live changes at safe boundaries; preserve sealed history (Recommended)" | 2026-10-24 | Permit optional additions and authorized future-plan changes; preserve used packets and apply revision/staleness rules to required input replacement/removal. | spec CONTEXT-TRANSFER.md §10.3; final conversion: OUTPUT-CONTRACTS §§3, 6, 10; OVE-163, OVE-164, OVE-175, OVE-179 | [Live changes](CONTEXT-TRANSFER.md#103-live-changes); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D61 | Round 7 Q25: Can the runtime repair a failed transfer automatically? | "Bounded automatic repair within the authored policy, then block (Recommended)" | 2026-10-24 | Bound retries, allowed alternatives and preparation by delegated capability/budget; block when unmet; do not weaken requirements, change provider or increase budget implicitly. | spec CONTEXT-TRANSFER.md §10.4; final conversion: OUTPUT-CONTRACTS §§3, 4, 6, 12; OVE-164, OVE-166, OVE-182 | [Repair](CONTEXT-TRANSFER.md#104-bounded-repair); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D62 | Owner steering: Which boundary is critical to keeping Mission Control general? | "Mission control is its own system with potential relationships to the applications entities and content. So when it comes to context transfer how can we modularize pulling from one application's storage correctly to pass on context through workflows" | 2026-10-24 | Prioritize application-owned storage, modular content access and workflow transfer; do not assume all application content must be copied into Mission Control. Custody was subsequently resolved by OC-D64..66. | spec CONTEXT-TRANSFER.md §11; final conversion: OUTPUT-CONTRACTS §§1, 5, 6; OVE-164, OVE-168 | [Application storage boundary](CONTEXT-TRANSFER.md#11-application-storage-boundary); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D63 | Owner steering: What investigation precedes the next questions? | "I need a line of questioning for this. I would suggest spinning up a sol subagent to go look at how specific application (really two postgres databases are needed per application. One for mission control one for deep agents persistence)" | 2026-10-24 | Reuse authorized GPT-6.1-Sol research assistants to inspect application/domain and Mission Control/Deep Agents storage separately; distinguish observed topology from the owner's two-database premise before deciding a target. | spec CONTEXT-TRANSFER.md §11.2; final conversion: OUTPUT-CONTRACTS §§1, 12; OVE-168 | [Storage topology evidence](CONTEXT-TRANSFER.md#112-storage-topology-evidence); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D64 | Round 8 Q26: Where should application content and retained workflow copies live? | "Application-owned content + selective retained results (Recommended)" | 2026-10-24 | Keep canonical application content in the owning service; Mission Control registers exact references/provenance and selected retained results, whose bytes may stay in authorized application custody. | spec CONTEXT-TRANSFER.md §11.3; final conversion: OUTPUT-CONTRACTS §§1, 4, 6; OVE-164, OVE-168 | [Application modules](CONTEXT-TRANSFER.md#113-application-modules-and-retained-results); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D65 | Round 8 Q27: What does an application implement to supply context? | "Yes Application modules behind common contracts and we need to make this deterministic and seamless in terms of mission control reading , materialization and context transfer. GREAT RECOMMENDATION!" | 2026-10-24 | Versioned application modules implement common read/export contracts; delivery integrates deterministic resolution/materialization/transfer without domain-specific kernel queries or manual agent copying. | spec CONTEXT-TRANSFER.md §11.3 and §12; GLOSSARY Application Context Adapter; final conversion: OUTPUT-CONTRACTS §§1, 3, 5, 6; OVE-164, OVE-165, OVE-168 | [Application modules](CONTEXT-TRANSFER.md#113-application-modules-and-retained-results); [delivery boundary](CONTEXT-TRANSFER.md#12-knowledge-discovery-and-deterministic-delivery); [glossary](../../../../../../GLOSSARY.md); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D66 | Round 8 Q28: How do mutable application reads become stable workflow inputs? | "Retain exact results; refresh explicitly or by authored policy (Recommended)" | 2026-10-24 | Retain bounded exact read results and truthful backend consistency; reuse until explicit/authored refresh creates a new recorded version under revision rules. | spec CONTEXT-TRANSFER.md §11.3 and §12.2; final conversion: OUTPUT-CONTRACTS §§3, 6, 10; OVE-164, OVE-175 | [Retained results](CONTEXT-TRANSFER.md#113-application-modules-and-retained-results); [determinism](CONTEXT-TRANSFER.md#122-meaning-of-deterministic-and-seamless); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D67 | Round 8 Q29 correction: Where does agent-directed additional knowledge acquisition belong? | "Okay now we are stepping into knowledge services (which might split into Financial Services, Content Services, Research and Evidence Services with general parts being part of each. I'm not saying that's the final split I'm just giving you insight) -- when agents need additional knowledge for a mission they will know how to navigate and read from the specific application database through knowledge services. This is different from context materialization and transfer." | 2026-10-24 | Separate agent-directed knowledge discovery/navigation through Knowledge Services from deterministic context delivery. Possible service decomposition is illustrative, not an approved deployment or taxonomy. Do not treat this answer as blanket approval of Q29's proposed automatic capture/transfer of every discovery read. | spec CONTEXT-TRANSFER.md §12.1; GLOSSARY Context Transfer Contract; final conversion: OUTPUT-CONTRACTS §§1, 5, 6; OVE-164, OVE-187 | [Discovery versus delivery](CONTEXT-TRANSFER.md#121-distinct-operations-shared-infrastructure); [glossary](../../../../../../GLOSSARY.md); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D68 | Round 9 Q30: What makes application-backed content machine-resolvable for transfer? | "Typed references resolved by application modules (Recommended)" | 2026-10-24 | Require typed application/source and exact revision/result identity for automatic application-content transfer; module resolves metadata, and both produced outputs and pre-existing inputs use the same path. | spec CONTEXT-TRANSFER.md §12.3; final conversion: OUTPUT-CONTRACTS §§2, 3, 5, 6; OVE-163, OVE-164, OVE-167 | [Typed references](CONTEXT-TRANSFER.md#123-typed-application-references); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D69 | Round 9 Q31: May transfer automatically generate a requested representation? | "Allow declared deterministic representations (Recommended)" | 2026-10-24 | Permit declared versioned deterministic renderers/projections with source/transformation/result lineage; semantic preparation remains explicit and separate; required content must survive. | spec CONTEXT-TRANSFER.md §12.4; final conversion: OUTPUT-CONTRACTS §§3, 6, 8, 11; OVE-164, OVE-172, OVE-180, OVE-183 | [Representations](CONTEXT-TRANSFER.md#124-deterministic-representations); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D70 | Round 9 Q32: How does a mission artifact relate to its ingested domain version? | "Preserve both with explicit ingestion lineage (Recommended)" | 2026-10-24 | Preserve source artifact and domain entity/revision identities with a receipt-backed native mapping; downstream bindings select original, ingested revision or permitted export. Normalization may change bytes or split entities. | spec CONTEXT-TRANSFER.md §12.5; final conversion: OUTPUT-CONTRACTS §§2, 5, 10; OVE-167, OVE-179, OVE-168 | [Ingestion lineage](CONTEXT-TRANSFER.md#125-ingestion-lineage); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D71 | Round 10 Q33: Can a parent directly adopt a subordinate's contracted output? | "Yes let but let's be careful here. I expect to have another interview related to subagents. We haven't yet created our special subagent tools. Providers (like deep agents) have their own ways of constructing subagents that we utilize for our main subagents config. Subagents have mostly been about assisting the main agent, context offloading, or specialized skills , especially ones that are token-heavy like Browser Control. Let's allow the subagent obligation but it is not required. With that being said let's discuss subagent shape at one point . Deep agents is a special example of subagents because of their built in interfaces." | 2026-10-24 | Permit optional subordinate output obligations and explicit adoption with parent accountability; ordinary assistance/offloading/specialist helpers need no deliverable contract. Reserve special tools, provider construction and subagent shape for a separate interview; do not impose one new shape here. | spec SPECIFICATION.md §12.2 and §12.6; final conversion: OUTPUT-CONTRACTS §§2, 5, 10; OVE-163, OVE-179, OVE-184, OVE-187, OVE-189 | [Optional obligations/adoption](SPECIFICATION.md#122-optional-subagent-obligations-adoption-and-verification-reuse); [deferred shape](SPECIFICATION.md#126-subagent-shape-and-tools-deferred); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D72 | Round 10 Q34: Can alternative subagents finish productive work before every child completes? | "Allow authored alternatives; retain settlement accountability (Recommended)" | 2026-10-24 | Permit explicit qualifying-any/quorum selection; all declared required obligations otherwise. Child effects/usage must settle or move to an authorized durable owner before full settlement. | spec SPECIFICATION.md §12.3; final conversion: OUTPUT-CONTRACTS §§4, 7, 9, 10; OVE-166, OVE-171, OVE-177, OVE-179 | [Productive completion and settlement](SPECIFICATION.md#123-productive-completion-and-settlement); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D73 | Round 10 Q35: Can consumers reuse verification from child/producer work? | "Reuse applicable assessments; check remaining requirements (Recommended)" | 2026-10-24 | Reuse assessments applicable to exact subjects/revisions, evidence, policy, authority and freshness; each consumer independently checks its own requirements and performs missing/changed checks. | spec SPECIFICATION.md §12.2; final conversion: OUTPUT-CONTRACTS §§4, 5, 10; OVE-165, OVE-170, OVE-175, OVE-179 | [Assessment reuse](SPECIFICATION.md#122-optional-subagent-obligations-adoption-and-verification-reuse); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D74 | Round 10 Q36: Who may activate a revised output contract? | "Policy-bounded revisions; explicit authority for weakening (Recommended)" | 2026-10-24 | Admit changes within explicit delegated revision bounds; weakening/dropping/changing promised outcomes needs authorized action under policy; executor cannot self-grant a waiver. Retain actor/reason/version/impact. | spec SPECIFICATION.md §12.5; final conversion: OUTPUT-CONTRACTS §§3, 4, 10; OVE-163, OVE-175, OVE-179, OVE-182 | [Revision authority](SPECIFICATION.md#125-governed-output-contract-revision-authority); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D75 | Round 11 Q37: Must report contracts distinguish supplied-assertion checks from separate coverage review? | "Declare coverage scope; require review when promised (Recommended)" | 2026-10-24 | Express assurance scope; require separate material-claim/question coverage assessment only when promised. Knowledge Services/admitted reviewer records method, findings and gaps; Mission Control checks the evidence without claiming infallibility. | spec SPECIFICATION.md §13.1; final conversion: OUTPUT-CONTRACTS §§4, 5, 12; OVE-165, OVE-186, OVE-188 | [Coverage assurance](SPECIFICATION.md#131-declared-research-coverage-assurance); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D76 | Round 11 Q38: How may provider-specific output/delivery features extend common contracts? | "Common semantics + explicit qualified provider extensions (Recommended)" | 2026-10-24 | Shared obligation/acceptance semantics plus versioned namespaced native capabilities/metadata; declare lane support/portability, qualify realization and refuse unsupported requirements absent explicit satisfying alternatives. | spec SPECIFICATION.md §13.2; final conversion: OUTPUT-CONTRACTS §§1, 2, 3, 6, 12; OVE-163, OVE-164, OVE-184, OVE-186 | [Provider extensions](SPECIFICATION.md#132-provider-extensions); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D77 | Round 11 Q39: Does this sprint relocate Deep Agents persistence? | "Defer topology changes; preserve current baseline (Recommended)" | 2026-10-24 | No physical persistence migration in this output/transfer scope; preserve current baseline and record broader isolation/Agent Server qualification for provider/subagent/deployment follow-up. | spec SPECIFICATION.md §13.3; spec CONTEXT-TRANSFER.md §11.2; final conversion: OUTPUT-CONTRACTS §§1, 12; OVE-168, OVE-184 | [Topology scope](SPECIFICATION.md#133-persistence-topology-scope); [current evidence](CONTEXT-TRANSFER.md#112-storage-topology-evidence); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |
| OC-D78 | Q40: Does the consolidated model capture the owner's intent? | "I am confirming the consolidation at this point. I still have things to go over but this is an accepted checkpoint and I accept those decisions pursuant to potential revisions in the next session" | 2026-10-24 | Accept the consolidated product model as this sitting's checkpoint; preserve future revisions as explicit subsequent-session decisions. Finalize this answer record without treating technical proposals as implemented or the wider design as permanently closed. | spec SPECIFICATION.md §7; this record checkpoint and next-session disposition; final conversion: OUTPUT-CONTRACTS §§1, 12; OVE-162 (synthesis disposition) | [Decision log](SPECIFICATION.md#7-decision-log-and-provenance); [next session](#next-session); [final reconciliation](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) |

## Mental model restated

**After round 1 (2026-10-24).** The interviewer framed the first round too narrowly around a final
course package. The owner corrected it: every stage can owe a set of deliverables, including a cycling
stage; an entire Stage Graph can additionally have a final output contract for specific scenarios.
Generic output forms must support application content and purpose types, including real financial and
economic market content, education and biotech evidence. A stage can deliver a structured index that
points to reports already ingested by an application's knowledge service. The index and its referenced
reports form a layered contract. Ingestion remains a separate concern even when an obligation promises
already-ingested content. Keep usable deliverables when the mission is incomplete; downstream partial
consumption must be explicit.

**After rounds 2 and 3 (2026-10-24).** Common forms support composable application/purpose contracts.
Authors can declare mission-specific inline contracts; governed revisions can adapt them during
execution while each submission remains pinned to its exact contract version. Layered contracts check
every declared guarantee. Research contracts can require source/assertion/judgment/verdict provenance
without prescribing one workflow shape. Report acceptance follows faithful representation and a
purpose-specific verdict/coverage policy; an accepted report need not positively support every claim
it discusses. The owner accepted these recommendations via the question tool.

**After round 4 (2026-10-24).** A cycling stage can owe something every cycle and accumulate other
deliverables over the stage. Revising report A does not make another report; subject coverage is
declared separately. Consumers wait for stage completion unless an incremental binding says otherwise.
Required fulfillment stops cycling by default, with optional additional conditions; limits never
pretend unmet requirements passed. These defaults are now confirmed.

**After rounds 5 and 6 (2026-10-24).** Track accepted revisions and mark affected consumers stale unless
explicitly snapshot-bound. GoalDirected verification covers the whole current goal set using still-valid
prior evidence. Total-output inspection groups current deliverables by owner/obligation, keeps history,
and optionally adds a contracted final view. Mandatory current state and required input access survive
every applicable handoff. Transfer is configurable by coordinator/client through versioned profiles or
inline settings, defaults and input/link overrides, under enforced system constraints. Required delivery
forms and allowed alternatives are explicit. Cross-mission transfer carries mapped outputs and required
provenance/state, with scoped opt-in history and explicit obligation adoption. Optional context-preparation
agents produce budgeted, attributed outputs; final packet assembly is deterministic.

**After round 7 (2026-10-24).** Transfer selects bounded content and relationships independently of
output validation. Required inputs remain usable for declared execution/recovery periods through
retention or permitted immutable exports; refuse unfulfillable promises. Caller/coordinator changes
apply at safe boundaries as new plans, preserving sealed history. Automatic repair uses only authored
alternatives, capability and budget bounds, then blocks. Giving another agent context does not itself
transfer an obligation; agent composition is the next frontier.

**Owner redirection after round 7 (2026-10-24).** Prioritize the boundary between Mission Control and
application entities/content: modular reads from application storage versus retaining content in
Mission Control for workflow reuse. The owner called this the most critical piece for generality and
extensibility. Agent-composition questions have not been asked and move later. Two GPT-6.1-Sol research
assistants inspected domain readers and runtime persistence without edits, secrets, connections or probes.

**After round 8 (2026-10-24).** Application content remains application-owned; workflows reuse exact
selected read results retained in suitable custody. Versioned application modules integrate with common
Mission Control contracts to make reading, materialization and transfer deterministic and seamless.
Refresh is explicit or authored and creates a new result. The owner corrected the interviewer's attempt
to include exploratory agent reads in transfer: agents obtain additional knowledge through Knowledge
Services. Transfer delivers selected inputs; it is not that discovery process. Financial, Content,
Research and Evidence Services are possible future boundaries, not a decided service split.

**After round 9 (2026-10-24).** Application-backed inputs use typed references, resolved by application
modules. Declared deterministic renderers can produce required representations while preserving source,
transformation and result identity; semantic work stays separate. Ingestion preserves the original
artifact plus an explicit receipt-backed mapping to native domain entities/revisions. A consumer can
select the original, the ingested content or a permitted export without confusing them as one object.

**After round 10 (2026-10-24).** Subagent output obligations are optional. Assistance, context offloading
and specialist work can remain ordinary provider-native helper tasks. Where an obligation is declared,
explicit adoption can fulfill a mapped parent requirement while preserving attribution and checks.
Any/quorum alternatives are authorable without abandoning settlement responsibility. Applicable prior
assessments can be reused across consumers, which still check their own requirements. Contract revisions
follow delegated policy; an executor cannot authorize its own requirement weakening. Subagent shape,
special tools and provider-native construction belong to a separate interview.

**After round 11 (2026-10-24).** Report contracts distinguish supplied-assertion verification from
separate material-claim/question coverage review, requiring the latter only when promised. Provider
extensions preserve common acceptance semantics and explicitly declare support/portability; unsupported
requirements refuse unless an allowed alternative satisfies them. Physical persistence changes are
deferred; the current inspected topology remains the baseline for this scope. The remaining work is
technical specification/issue conversion and owner confirmation of the consolidated model, completed
subsequently at the accepted checkpoint below.

**Accepted checkpoint, Q40 (2026-10-24).** The owner confirmed the consolidated model while explicitly
reserving revisions in the next session. The model comprises general obligations and acceptance;
application-owned canonical content with typed modular resolution and selected retained observations;
configurable, sealed context transfer; stage/cycle and goal-wide current-set semantics; layered proof;
optional subordinate obligations; and qualified provider extensions. Detailed subagent construction/tools
and physical topology remain deferred. Engineering schemas/protocols and issue specifications remain
proposed implementations of these accepted choices. The checkpoint does not authorize runtime work.

## Source evidence and disagreements

- `GLOSSARY.md:70`: a Program Node has its own inputs, outputs, policies, budget and completion contract.
- `GLOSSARY.md:215`: a Completion Contract expresses acceptance; execution success is insufficient.
- `docs/knowledge/completion.md:19-26`: output validity, evidence disposition, activation acceptance,
  mission acceptance, domain admission and publication are distinct facts. Current runtime paths are
  being re-verified by the workflow research assistant before behavior-dependent questions.
- `docs/specs/archive/provider-consolidation-2026-10/specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md:161-195` proposes obligation
  cardinality and accumulation across units/cycles/iterations/missions. This is a design proposal,
  not evidence that a selectable final mission output bundle exists in the runtime.
- Provenance conflict: program `LEDGER.md` SP-04 / IA-03 calls OC-D1..26 decided/accepted, whereas
  `SESSION-INTERVIEW-SITTING-I-2026-10-24.md:27` and its interview instruction call them recommendations
  to confirm. This interview does not infer owner approval from either label; no earlier sprint claim
  or issue status is changed.
- Live source checked at the recorded commit: `src/mission_control/domain/programs/interpreter.py:978`
  builds Stage Graph completion output references from every projected stage instance; GoalDirected
  accumulates historical references at `src/mission_control/domain/programs/goal_directed.py:281`
  but proposes terminal output from the current execution at `:754`. These differ and do not define
  one explicit final deliverable selection contract.
- `mission-control-general/general-mission-control/expansion/KNOWLEDGE-SERVICES.md:15` (deleted 2026-11-01; last at `66185d2e`) keeps domain
  schemas and canonical writers application-owned; `:72-76` separates native domain transactions
  and recovery from mission settlement. `docs/adr/0012-coding-effects-are-separate-capabilities.md:12`
  likewise separates code production from push, PR, merge and deployment authority.
- Read-only cross-repository check, 2026-10-24: Shared Knowledge Services report verification explicitly
  returns `coverageScope: producer_declared_assertions_only` in
  `platform/knowledge-services/packages/application/src/verification/operations/verification-claims.ts:460-466`.
  Its reusable report checker separates mechanical failures and review concerns, including unobserved
  claim recall (`packages/verification/src/report/report-wide.ts:52-81` relative to that service).
  Semantic verdict and downstream policy outcome are distinct in `packages/contracts/src/verification/model.ts:310-338`.
  Domain report persistence is a separate projection into AI Engineer `research.*` tables; Biotech graph
  readback is verification of declared mutations, not evidence of equivalent semantic report checks.
  See specification §8.3 for source anchors. No algorithm or persistence refactor has been performed.

Paths in this section are relative to the repository unless a program-relative path is explicitly
named. The linked source instrument lives two directories above this record, under `providers/`.

## Assumptions (asked, not answered)

| ID | Question | Assumption taken | Risk if wrong |
| --- | --- | --- | --- |
| — | No unanswered question in this sitting. | Q40 confirmed the checkpoint, expressly allowing later revision. | Proposed engineering details still need implementation review and qualification. |

No unanswered design choice has been adopted. The owner's statement "I'm assuming that output
obligations have a relationship with context transfer" is a hypothesis to refine, not acceptance
of the existing transfer proposal.

## Interview frontier

The sitting's frontier is closed at the accepted checkpoint (OC-D78). The technical draft and issue
conversion are written. The owner has further topics for the next session; no future answer is assumed.

## Converted artifacts and decision routing

- [SPECIFICATION.md](SPECIFICATION.md): product requirements and dated decision log, OC-D27..78.
- [CONTEXT-TRANSFER.md](CONTEXT-TRANSFER.md): within/between-mission delivery and application storage
  boundaries, including source evidence and the owner's discovery/materialization correction.
- [CONTRACTS.md](CONTRACTS.md): proposed exact records, identity/digests, lifecycle, adapter operations,
  transfer plans, revisions, worked authoring fragments and failure/recovery matrix.
- [WORK-ITEMS.md](WORK-ITEMS.md): 17 local issue specifications with dependencies, source seams,
  acceptance scenarios, persistence/replay requirements and provenance. They are not filed OVE issues.
- [DESIGN-DECISIONS.md](DESIGN-DECISIONS.md): DC-OBL, DC-APP and DC-XFER, three local ADR candidates.

| Confirmed decision range/theme | Primary implementation destinations |
| --- | --- |
| OC-D27..37: scope, ownership, output spectrum, partial results | OO-1, OO-2, OO-4, OO-9, QA-1 |
| OC-D38..44: composition, layers, inline/revised contracts, research | OO-1, OO-3, OO-8, AC-6, QA-1; DC-OBL |
| OC-D45..52: cycles, identity, release, revisions, goal-wide sets, handoff | OO-2..6, OO-9, AC-5 |
| OC-D53..61: configurable transfer, expansion, availability, live control, repair | AC-2..5, OO-6, OO-8; DC-XFER |
| OC-D62..70: application custody/modules, discovery separation, typed refs, representations, lineage | AC-1..6, QA-1; DC-APP |
| OC-D71..74: optional contributions, settlement, assessment reuse, revision authority | OO-3, OO-7, OO-8; deferred subagent construction/tools retained |
| OC-D75..77: coverage assurance, provider extensions, unchanged topology | OO-3, QR-1, QA-1; no topology migration item |
| OC-D78: accepted checkpoint with future revisions | Finalized sitting record; SPECIFICATION §7; next-session revision lineage |

The per-decision **Becomes** and **Folded** destinations above are complete. This crosswalk adds local
implementation routing without substituting agent interpretations for the quoted answers. No Fable
material was supplied or merged. The schema field names and protocols are proposed engineering choices.

## Parking lot

- Comparison/merge with Fable: preserve independent provenance; no counterpart material supplied yet.
- Existing upgrade, capability catalog, fault-tolerance and sprint sequence decisions enter this
  interview only where they affect the requested output/transfer design.
- External issue publication/commenting is outside this deliverable: the owner requested specifications
  translatable into exact issues. The local pack is ready for that later conversion; no issue status changed.
- Research assurance follow-up: the current verifier checks producer-declared assertions, so independent
  material-claim/question coverage must be an explicit contract choice; do not claim it is already proved.
- Potential Financial/Content/Research and Evidence service decomposition is illustrative only. The
  transfer boundary must permit multiple capability modules without requiring this particular split.
- Separate subagent interview, explicitly requested in OC-D71: provider-native construction (including
  Deep Agents interfaces), special subagent tools, helper/offloading/specialist shapes and exact tool/API
  exposure. This interview defines optional output obligations and acceptance/transfer boundaries only.
- Physical persistence topology/relocation and Agent Server production qualification are deferred by
  OC-D77; preserve the inspected baseline in this scope, without claiming the deferred topology is solved.

## Conversion checklist

- [x] Owner confirms the consolidated restated model as a revisable checkpoint (OC-D78); prior corrections are retained above.
- [x] Every answer received through round 11 is recorded verbatim with a dated interpretation.
- [x] Decisions received through round 11 folded into draft specification sections with links in **Folded**.
- [x] Resolved terminology added to the glossary; three ADR candidates written for durable trade-offs.
- [x] Seventeen issue specifications include scope, dependencies, acceptance criteria, test requirements and provenance.
- [x] External issue creation/commenting disposition: local specifications only in this sitting; no sprint status changes.
- [x] This record has a program ledger row.
- [x] Initial documentation checks run; open decisions and conversion gaps recorded below.

## Validation of this record

2026-10-24, after all 39 product answers and technical conversion: compiled documentation index check
passed; program ledger passed with 47 rows and zero problems. Explicit nested-answer validation passed:
52 unique decision rows, OC-D27..78, with destinations. The work-item count is 17 unique local IDs.
`git diff --check` passed. Aggregate documentation check: six passed; the link check failed only on
three pre-existing links: `providers/deep_agents/CHANGES.md:1386` (`NEXT-SESSION.md`), domain supplement
`:17` and sprint sequence `:21` (missing human-review supplement). No failure points to this interview.

GPT-6.1-Sol read-only review checked source paths and dependency order and identified three protocol
ambiguities corrected in CONTRACTS: stable assessment subjects, non-self-referential digest projections
and authorized payload erasure. The final source-path check found all 27 cited Python paths present.
Runtime tests and paid probes were not run: this sitting changes documentation only. No secrets,
database connections or production configuration were inspected or changed. Q40 explicitly confirms
the checkpoint. All product decisions have
destinations, and subagent shape/tools and physical topology remain explicitly deferred.

## Next session

**Navigation update following the owner's 2026-10-24 preparation request:** run the
[application-knowledge prerequisite interview](../../interview-instructions/INTERVIEW-APPLICATION-KNOWLEDGE-BOUNDARY-2026-10-24.md)
next, producing its own ANSWERS.md and completing the
[deep-module projection](../../specs/APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md). It precedes the final
output-contract/context-transfer interview and subsequent issue creation. This pointer does not alter
the recorded answers or imply acceptance of the new projection's proposed mechanics.

Start from this accepted checkpoint and the owner's remaining topics. Record any changed decision as
a subsequent-session revision linked to its original OC-D identifier; preserve the original quote and
update affected specifications/work items explicitly. Subagent shape/tools and physical topology remain
available for their deferred interviews. Compare Fable material only when supplied, retaining each
interview's independent origins. Implementation starts in a later authorized sitting.
