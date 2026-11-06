---
type: Specification
title: "General and application-specific output obligations: GPT-6-Astra interview specification"
description: "Evolving specification from the independent output-obligations interview, separating confirmed requirements from proposed contract composition, reference guarantees and workflow semantics."
tags: [mission-control, output-contracts, obligations, context-transfer, interview]
date: 2026-10-24
interview_id: output-obligations-gpt-6-astra-2026-10-24
interviewer_model: "GPT-6-Astra"
model_label_source: "Owner-supplied experiment label"
source_commit: 8de6fab94fd5d17d79f2ecfd92e55329bb282a36
status: draft
product_checkpoint: "Accepted 2026-10-24, OC-D78; subject to future-session revisions"
---

# General and application-specific output obligations

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../../sessions/KICKOFF.md); no new interview or runtime completion is implied.


This is a working specification derived from [the interview answers](ANSWERS.md). It does not
supersede the canonical specification pack, accept previous recommendations or certify implementation.
Confirmed product decisions are distinguished from proposed implementation mechanics. The complete
local pack comprises [verbatim answers](ANSWERS.md), [context-transfer requirements](CONTEXT-TRANSFER.md),
[proposed records, protocols and worked examples](CONTRACTS.md), [17 issue specifications](WORK-ITEMS.md)
and [three ADR candidates](DESIGN-DECISIONS.md). The owner accepted the consolidated model as a revisable
checkpoint (OC-D78); engineering mechanics remain proposals. No runtime implementation or external
issue publication is claimed.

## 1. Confirmed scope and ownership

**Confirmed: OC-D27, OC-D28, OC-D29, OC-D33, OC-D35, OC-D37.** Mission Control must describe output
obligations from general forms through application-specific content and purposes. It must work with
any application and its knowledge services; AI Engineer and Biotech are worked examples rather than
an exhaustive application enum.

Coverage includes codebase work, knowledge work and content work. Domain examples include real market
content about biotech companies and AI-native/innovative companies; financial and economic analyses;
AI Engineer curricula, courses, challenges and projects; and evidence-backed reports in both domains.
These categories may overlap: a market analysis can itself be an evidence-backed report, and a course
can include reports, datasets and code. Do not make educational content the default model for all work.

Missing domain content models are assumed to exist for design. Their exact future bindings remain
implementation dependencies, not a reason to exclude their requirements or claim they already exist.
AI Engineer owns its PostgreSQL content semantics; Biotech owns its Neo4j content semantics. New
applications retain their own domain models and services. Generic runtime obligations must not move
those authorities into Mission Control.

**Confirmed: OC-D30, clarified by OC-D36.** Output production and ingestion are distinct concerns.
An output may nevertheless describe content already ingested. A stage's output contract can therefore
refer to successful ingestion as a fact to establish, without making every output automatically ingest.
The operation performing an ingestion still uses the domain service's admitted write contract.

## 2. Confirmed obligation ownership and partial results

**Confirmed: OC-D32.** Each stage can declare a set of deliverable obligations. This includes a cycling
stage executed by Deep Agents. A Stage Graph may additionally declare final deliverables for the whole
graph in scenarios that require them; intermediate outputs are preserved. A graph-wide final contract
does not replace stage contracts and is not mandatory merely because the program is a Stage Graph.

**Confirmed scope detail: OC-D45..48.** A stage may combine per-cycle submission obligations with
accumulated stage obligations. Distinct deliverable identities, accepted revisions, subject coverage,
consumer release and stopping rules are specified in §9. Current output views, downstream staleness
and goal-wide GoalDirected verification are confirmed in §10. Proposed schemas are in CONTRACTS §2–4.

**Confirmed: OC-D34.** When a valid deliverable exists but another required deliverable is missing,
retain the usable deliverable while marking the mission incomplete. Downstream consumption of partial
results must be explicit. This policy does not by itself waive data dependencies, resolve uncertain
effects, authorize publication, or declare the whole mission accepted. Exact status names and when a
live stage may release a result are refined by OC-D47: explicit incremental delivery is distinct
from consumption of partial results after an incomplete mission stops.

## 3. Output spectrum and contract composition

**Confirmed extension model: OC-D38 and OC-D40.** Separate representation, content semantics, purpose and
fulfillment guarantees instead of treating every business noun as a new runtime kind. The rows below
are a design vocabulary, not a committed enum or an implemented public API.

| Dimension | Generic expression | Application or purpose examples |
| --- | --- | --- |
| Text/document | Plain text, Markdown, authored document | Market commentary, lesson, evidence report, company analysis |
| File/media | PDF, image, chart, slide deck, archive | Research publication, teaching assets, presentation of market findings |
| Structured value | Scalar, record, table, dataset with a declared schema | Comparison of companies, financial metrics with units and observation dates, challenge definition |
| Collection/bundle | Named components, membership rules and relationships | Report set, course plus challenges, project with code and instructions |
| External reference | Typed reference to content held by another authority | Ingested report, company record, course revision, dataset or code-host artifact |
| Code change | Patch or repository/base/head identity with declared checks | Application change, reusable analysis script, educational project implementation |
| Effect evidence | Receipt of an admitted external operation | Ingestion applied/noop/partial result, publication, PR creation |
| Control evidence | Verdict, handoff, findings or decision | Review of a report, cycle decision, next-iteration repair instructions |

Collection is composition over members, not automatically a new byte-storage kind. A reference is an
identity/access contract, not proof that the target exists or an instruction to ingest it. A receipt
proves only its attributed operation outcome, not automatically report quality. A document's subject
and intended use may add independent constraints: evidence-backed, market-facing, educational, etc.

Confirmed extension path: common output form -> reusable content contract -> application specialization
and purpose requirements -> named obligation on a unit. Authors can also declare one-off contracts
using supported schemas and validators. All reused definitions must be pinned at admission; proposed
composition and conflict rules are in CONTRACTS §3. Do not assume arbitrary JSON Schema proves
content quality, or allow a schema/prompt to install arbitrary validation code or acquire permissions.

Provider-specific adapters realize collection, submission and materialization. OC-D76 confirms qualified,
versioned namespaced extensions and explicit refusal/allowed-alternative rules (§13.2).
The domain meaning of a market report must not silently change when the execution provider changes.

## 4. Layered report-index scenario

**Confirmed requirement: OC-D36.** A stage can declare a structured output referencing reports that
have already been ingested. The delivered index is one layer of an output contract; the underlying
reports are substantive outputs with their own locations and properties.

The stage may expose only the structured index. The design must not force report copies and ingestion
receipts to be additional top-level output slots merely to express requirements over the referenced
reports. Whether those are nested requirements of one output or separately reusable obligations is a
contract-composition decision; the owner's example requires that the index-only surface be expressible.

**Confirmed guarantee selection: OC-D39.** A contract explicitly selects its guarantees:

1. **Index shape:** required entries and fields are present and well formed.
2. **Referenced content:** each report resolves at the required identity/revision and satisfies the
   referenced report contract, with the required validation or assessment evidence.
3. **Domain ingestion:** authoritative receipts establish the declared ingestion outcome for those
   report identities/revisions. Existing reports require an appropriate existing-state or reuse proof,
   rather than inventing an ingestion by this stage.

An obligation that explicitly promises ingested, valid reports requires all relevant layers. A generic
reference-list obligation can require only its declared guarantees. Passing the index schema cannot
substitute for missing proof at another required layer. Validation happens before the corresponding
fulfillment decision. CONTRACTS §3.3–4 defines assessment records, applicability and batching boundaries;
semantic work remains behind admitted assessment capabilities.

Candidate reference information, not yet a schema: issuing application/service and scope; typed entity
identity; revision/snapshot or other truthful freshness guarantee; retrieval capability; content and
contract identity; ingestion receipt where required; producer provenance where applicable. URLs alone
cannot necessarily establish version, permission or receipt correlation. A bytes digest is not a
substitute for a mutable domain entity's identity.

Worked scenario, elaborated in CONTRACTS §9.1: a cycling research stage creates or revises a biotech
market report, invokes an admitted domain ingestion operation, and submits an index entry referring to
the resulting report and receipt. Another stage can consume the index or request the reports themselves
under its input/transfer contract. The index does not silently copy the whole graph into Mission Control.

## 5. Implementation design and explicit deferrals

CONTRACTS §2–5 proposes identity, obligation scopes, conditional branch applicability, candidate versus
accepted sets, revision concurrency, release and assessment protocols. §6–8 proposes source modules,
sealed transfers, logical API operations and rollout. §9–10 supplies worked scenarios and failure
acceptance criteria, including partial ingestion. These are engineering proposals derived from the
confirmed choices, not unasked product decisions or claims of existing endpoints.

Subagent construction and special tools remain in the separate interview requested by OC-D71.
Physical storage relocation and Agent Server production qualification are deferred by OC-D77.
Application capability/schema availability and provider realization must be proved individually;
assuming a domain model for design does not qualify a missing implementation.

## 6. Issue boundaries and acceptance examples

[WORK-ITEMS.md](WORK-ITEMS.md) is the issue-conversion pack: OO-1..9 cover general output contracts,
ledger/assessment, Stage Graph and GoalDirected semantics, dependencies/adoption, revision governance
and inspection; AC-1..6 cover typed application sources, modules, retention, representations, transfer
plans and ingestion lineage; QR-1 and QA-1 qualify provider realization and real application bindings.
Each includes scope, source seams, dependencies, observable acceptance, persistence/replay and decision
provenance. They are unscheduled local specifications, not filed issues or implementation claims.

CONTRACTS §9–10 provides shared examples and failure fixtures. Runtime proof belongs to implementation:
real disposable PostgreSQL/Temporal checks where those guarantees are claimed, and separately qualified
provider/application evidence. This sitting validates documentation only.

## 7. Decision log and provenance

**Subsequent-session decisions (2026-10-24):** OC-D79..105 were taken in the prerequisite
application-knowledge-boundary interview and are recorded in
[its answers](../application-knowledge-boundary/claude-fable-5-1-2026-10-24/ANSWERS.md) and folded into
the [boundary projection](../../specs/APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md). They extend this checkpoint;
OC-D83 revises the OC-D4/D5 two-channel wording (one act `submit_output`); CONTRACTS §9.2's Biotech
`revision_7` example is corrected to content-addressed uid exactness. No OC-D27..78 quote is changed.

- 2026-10-24, OC-D27: span general-to-specific output contracts across mission units, workflows and providers (§1).
- 2026-10-24, OC-D28: assume missing domain models for design, without claiming implementation (§1).
- 2026-10-24, OC-D29: cover curricula, courses, challenges, projects and evidence-backed reports in their owning domain models (§1).
- 2026-10-24, OC-D30: output production is distinct from ingestion (§1).
- 2026-10-24, OC-D31: resolve feature detail into answers and sprint-convertible specifications (§6).
- 2026-10-24, OC-D32: stages own deliverable sets, including cycling stages; graph-wide final contracts
  are available for specific scenarios and preserve intermediate outputs (§2).
- 2026-10-24, OC-D33: general forms and application/purpose content must span the full output range (§1, §3).
- 2026-10-24, OC-D35: include financial/economic market content for biotech and AI-native companies (§1).
- 2026-10-24, OC-D37: Mission Control must work with any application and its knowledge services (§1, §3).
- 2026-10-24, OC-D36: support layered output contracts, including structured references to already
  ingested reports (§4); selected guarantees were subsequently confirmed in OC-D39.
- 2026-10-24, OC-D34: retain usable deliverables, mission incomplete, explicit partial consumption (§2).
- 2026-10-24, OC-D38: composable application/purpose contracts extend common forms (§3).
- 2026-10-24, OC-D39: validate each declared reference guarantee (§4).
- 2026-10-24, OC-D40: inline mission-specific contracts coexist with pinned reusable definitions (§3).
- 2026-10-24, OC-D41: include report/provenance verification in the design, using the research process
  as context; current code claims independently checked rather than assumed (§8).
- 2026-10-24, OC-D42: support governed contract revision during execution; exact contract version per
  submission and no silent retrospective acceptance (§8).
- 2026-10-24, OC-D43: require declared evidence/provenance independently of workflow shape (§8).
- 2026-10-24, OC-D44: report acceptance uses faithful provenance and purpose-specific verdict/coverage policy (§8).
- 2026-10-24, OC-D45: support per-cycle and accumulated stage obligations (§9.1).
- 2026-10-24, OC-D46: count distinct identities, retain revisions and declare subject coverage separately (§9.2).
- 2026-10-24, OC-D47: wait for completion by default; allow explicitly configured incremental delivery (§9.3).
- 2026-10-24, OC-D48: stop on required fulfillment by default with additional authored completion conditions (§9.4).
- 2026-10-24, OC-D49: track accepted upstream revisions, preserve exact historical provenance and mark
  affected current results stale; explicit snapshot bindings remain available (§10.1).
- 2026-10-24, OC-D50: GoalDirected verification assesses the whole current goal set with valid prior
  evidence reuse, separately from each iteration's submissions (§10.2).
- 2026-10-24, OC-D51: expose owner/obligation current views, history and optional contracted final view (§10.3).
- 2026-10-24, OC-D52: handoffs retain mandatory state/findings and reliable required input access (§9.5).
- 2026-10-24, OC-D53: prioritize context transfer within and between missions (§11).
- 2026-10-24, OC-D54: callers/coordinators author versioned transfer settings under system enforcement (§11).
- 2026-10-24, OC-D55: required delivery forms and acceptable alternatives constrain automatic packing (§11).
- 2026-10-24, OC-D56: cross-mission transfer maps outputs/provenance; broader history and obligation adoption are explicit (§11).
- 2026-10-24, OC-D57: optional budgeted context preparation supplements required inputs; final assembly is deterministic (§11).
- 2026-10-24, OC-D58: explicit bounded content/relationship expansion is separate from output validation (§11).
- 2026-10-24, OC-D59: required inputs need guaranteed declared execution/recovery availability (§11).
- 2026-10-24, OC-D60: governed live changes apply at safe boundaries while preserving sealed history (§11).
- 2026-10-24, OC-D61: automatic repair stays within authored policy and otherwise blocks (§11).
- 2026-10-24, OC-D62: prioritize modular application-storage reads and content custody to preserve generality (§11).
- 2026-10-24, OC-D63: ground storage questions in Sol inspection; distinguish database topology evidence from the owner's premise (§11).
- 2026-10-24, OC-D64: application-owned content plus selective retained results, including external custody (§11).
- 2026-10-24, OC-D65: application modules behind common contracts make reading/materialization/transfer deterministic and seamless (§11).
- 2026-10-24, OC-D66: reuse exact bounded read results until explicit/authored refresh records a new result (§11).
- 2026-10-24, OC-D67: agent knowledge acquisition through Knowledge Services is distinct from context delivery; possible service packaging remains undecided (§11).
- 2026-10-24, OC-D68: typed references resolve through application modules for automatic transfer (§11).
- 2026-10-24, OC-D69: declared deterministic representations retain source/transformation/result identity (§11).
- 2026-10-24, OC-D70: preserve original artifact and ingested domain identities with receipt-backed lineage (§11).
- 2026-10-24, OC-D71: subordinate output obligations are optional; direct adoption is permitted with parent checks/accountability; subagent shape/tools get a separate interview (§12.2, §12.6).
- 2026-10-24, OC-D72: authored qualifying-any/quorum alternatives preserve child settlement responsibility (§12.3).
- 2026-10-24, OC-D73: reuse applicable exact-subject assessments while each consumer checks its own requirements (§12.2).
- 2026-10-24, OC-D74: policy-bounded revisions require explicit authority for weakening and retain actor/reason/version/impact (§12.5).
- 2026-10-24, OC-D75: declare assurance scope; separate material-claim/question coverage review is required when promised (§13.1).
- 2026-10-24, OC-D76: common acceptance semantics with explicitly qualified namespaced provider extensions (§13.2).
- 2026-10-24, OC-D77: defer physical persistence changes and preserve current baseline (§13.3).
- 2026-10-24, OC-D78: accept the consolidated model as a checkpoint, explicitly subject to potential revisions in the next session (ANSWERS checkpoint/next-session disposition).

All owner wording lives in [ANSWERS.md](ANSWERS.md). Existing source anchors and differences between
implemented and proposed behavior are recorded there. All 39 product questions and checkpoint
confirmation Q40 have answers. This sitting is finalized; future revisions retain their lineage to
this checkpoint. Proposed implementation details and qualification work are in CONTRACTS and WORK-ITEMS.

## 8. Dynamic contracts and research assurance

### 8.1 Inline authoring and governed evolution

**Confirmed: OC-D40 and OC-D42.** A mission can declare an inline output contract suited to its dataset
or content needs. It can also propose a revised contract during execution when discovery changes the
appropriate shape. Every submission binds an exact contract version. A revision cannot silently turn
an earlier failed result into a pass. Reusable contracts are versioned/pinned, and new semantic
validators or external resolvers still require admitted capabilities.

Pending details: who can propose/activate which changes, optional versus required additions, changes
to success criteria, in-flight units, parent/consumer compatibility, and explicit reassessment of old
submissions. The existing mission-revision model is a starting seam, not evidence that output-contract
revision is implemented. Proposal, admission, activation and reassessment must be distinguishable facts.

### 8.2 The research process and the output contract

**Confirmed: OC-D43.** A research output contract can require declared source/assertion/judgment/verdict
provenance without forcing each step to be a distinct Mission Control stage. One stage, multiple
stages, subagents and reuse of existing verified material are allowed when the declared requirements
are met through admitted services. A separate workflow template may prescribe sequence where needed.

**Confirmed: OC-D44.** A report can be accepted when it faithfully describes a contradicted claim or
inconclusive evidence. Its purpose-specific policy determines admissible verdicts, qualifiers and
coverage gaps. Acceptance of the report does not turn a reported hypothesis into an accepted fact,
nor grant permission for an unrelated downstream use such as canonical fact admission or publication.

Recommended representation, developed in CONTRACTS §3 and §6: the report points to assertions, selected source
fragments and capture identities; assessments carry checker identity, rubric/policy version, evidence
and subject version/digests, independent judgment dimensions, verdict and supported downstream uses.
Mission Control evaluates the declared requirements over attributable evidence; Knowledge Services and
application adapters own semantic judgment, storage and domain admission. A schema verifies structure;
it does not become a semantic checker merely by including a `verified` field.

### 8.3 Verified implementation boundaries

Read-only source inspection, 2026-10-24; no live or test claims:

- Shared Knowledge Services defines semantic verdicts separately from policy outcomes in
  `platform/knowledge-services/packages/contracts/src/verification/model.ts:310` and `:328`.
- Its report algorithm accepts report text and typed assertion/citation assessments, without direct
  application table identities: `packages/verification/src/report/report-wide.ts:7-50`. It checks
  citation/pointer integrity, qualifier loss, contradictions and consistency at `:127-245`.
- The public application path hydrates exact registered report and ledger bytes. Its result explicitly
  declares `coverageScope: producer_declared_assertions_only` in
  `packages/application/src/verification/operations/verification-claims.ts:460-466`.
- The algorithm itself retains unobserved-claim recall as a review concern (`report-wide.ts:52-55`).
  This is not independent proof that every important assertion or research question was captured.
- AI Engineer report persistence projects into `research.*` in
  `packages/knowledge-db/src/ingestion/reports/projections.ts:28-95`; that mapping remains a domain
  binding rather than part of the general report algorithm.
- Biotech graph apply/readback contracts (`biotech/biotech-knowledge-services/packages/contracts/src/apply-v2.ts:93-155`)
  establish declared mutation effects/recovery. Successful graph readback is not proof of semantic
  support, report coverage or source authority.

Paths with the platform/biotech prefix are BellLabs-relative; unprefixed package paths in this subsection
are relative to platform/knowledge-services. Exact code citations are starting evidence at this date.

### 8.4 Assurance design disposition

OC-D75 resolves assurance scope: a promised material-claim/question coverage review needs its own
assessment, method and gaps. The authored purpose contract names required questions, reviewer authority
and any independence requirement. Admitted Knowledge Services/reviewer capabilities perform that work;
Mission Control enforces the declared proof. It does not promise perfect recall or require every report
to use a stronger review. CONTRACTS §3.3–3.4 specifies results, stale/revoked applicability and reuse;
§5 preserves identity/provenance across dynamic schema revisions. QA-1 qualifies actual service proof.

## 9. Cycling-stage obligations and accumulation

### 9.1 Scope

**Confirmed: OC-D45.** Obligations may apply to each cycle or to the stage's accumulated deliverables.
A cycling research stage may owe a report index each cycle and five qualifying reports across its
execution. Producing an index does not fulfill a separate report obligation merely because the index
has five rows; declared layered guarantees and coverage rules still apply.

A cycle can finish its own submission requirements while accumulated stage obligations remain open.
Do not misclassify that normal progress as final stage acceptance or as a technical failure.
CONTRACTS §4.1 proposes same-cycle repair followed by block/incomplete when required submission fails.

### 9.2 Identity, revisions and coverage

**Confirmed: OC-D46.** Count distinct deliverable identities. A newly accepted revision replaces the
same identity in the current deliverable view; preserve older revisions and their evidence in history.
The appearance of a new draft does not itself supersede an accepted revision. Subject coverage is a
separate declared condition, not an assumption derived from the number of report objects.

Acceptance example:

| Cycle | New accepted contributions | Current reports | Distinct report count |
| --- | --- | --- | --- |
| 1 | A revision 1; B revision 1 | A1, B1 | 2 |
| 2 | A revision 2; C revision 1 | A2, B1, C1 | 3 |

Five reports about one company do not prove coverage of five companies. Conversely, whether one
multi-company report can satisfy five-company coverage depends on the declared coverage contract; it
does not automatically count as five reports. CONTRACTS §2 specifies proposed identity issuer/key,
tenant/application scope, concurrent supersession and withdrawal/revocation rules.

### 9.3 Consumer release

**Confirmed: OC-D47.** A dependent stage waits for producer-stage completion by default. An explicit
incremental binding can release individually accepted deliverables while the producer is still
cycling. Such a binding must specify its trigger and treatment of later revisions. Neither a new
submission nor a registered but unaccepted artifact silently releases a consumer.

Incremental delivery while a stage is active and explicit consumption of partial results after an
incomplete mission stops are different policies. Authoring one must not silently enable the other.
CONTRACTS §4.3 proposes exact trigger identities, batching and duplicate-event handling; external writes
already performed are not presumed to roll back.

### 9.4 Completion and limits

**Confirmed: OC-D48.** Default to stopping when the stage's required obligations are fulfilled. Authors
may add completion conditions such as review acceptance or coverage. Quantity alone is insufficient
when any other declared required guarantee or completion condition is unmet.

A cycle, budget or other execution limit stops execution without fabricating fulfillment or success.
Retain usable deliverables and record remaining obligations and the stop reason, following OC-D34.
Exact terminal dispositions, human intervention/resume and their mapping to existing run outcomes
remain implementation design work; the contract must distinguish successful completion from a limit.

### 9.5 Context for the next cycle

**Confirmed: OC-D52.** The next cycle/iteration receives a compact authoritative handoff: applicable
contract versions, current deliverable/revision index, unmet obligations, verifier findings,
revision/invalidation facts and reliable access to declared inputs. Full authorized history remains
available on demand. Missing required data or inaccessible required inputs block or trigger repair;
they cannot silently disappear to fit a context budget. Context-transfer configuration and delivery
guarantees are developed in [the dedicated specification](CONTEXT-TRANSFER.md).

## 10. Current output views, revision impact and GoalDirected completion

### 10.1 Tracked revisions and historical snapshots

**Confirmed: OC-D49.** Track revisions by default. If a consumer used A1 and the producer accepts A2,
preserve the consumer result and its exact A1 provenance, but mark affected downstream work stale for
the current result set until revalidated or rebuilt. An explicit snapshot binding may intentionally
continue using A1. Do not automatically rerun every descendant or erase prior acceptance history.
Already-performed external writes remain recorded and are not silently undone.

The affected dependency set, compatible changes, in-flight disposition, revalidation capability and
any later admitted corrective effect require exact implementation design. A stale marker is not proof
that all work must be recomputed, nor authorization to replay external effects.

### 10.2 GoalDirected verification

**Confirmed: OC-D50.** Each verifier assesses the goal-wide current deliverable set, including accepted
work from earlier iterations. Reuse still-valid evidence for unchanged items; maintain separate
per-iteration submissions, observations and findings. An iteration that repairs C cannot silently lose
A and B from the goal's result. Earlier accepted work that has become stale or incompatible is not
carried forward as valid merely because it passed before.

The verifier must identify the exact set it assessed. Implementation must bind its decision to a
sealed subject set of output revisions/contracts with separately linked evidence; CONTRACTS §3.3 and
§4.2 propose the schema and concurrent-update handling. This changes the discrepancy between accumulated state refs and the
current-execution-only terminal output proposal, documented in ANSWERS.md.

### 10.3 Total-output views

**Confirmed: OC-D51.** Without an explicit workflow-wide final-output contract, expose current accepted
deliverables grouped by their owner (stage or goal) and obligation. Keep historical submissions in a
separate view. An explicit final-output contract adds a selected final view rather than replacing the
stage/goal views or erasing intermediate work. Stale and superseded results remain inspectable but
cannot be silently presented as current accepted fulfillment.

An artifact can be referred to from multiple declared views without copying it or multiplying its
identity. Exact API filters and treatment of control outputs are implementation details still to pin.

## 11. Context-transfer contract direction

**Confirmed: OC-D53..57.** Context transfer is a central feature of this interview, with the same
versioned authoring surface for coordinator agents and client callers. Support reusable profiles and
inline settings, mission defaults and per-input/per-link overrides. Required access/form differs from
a preference; automatic packing may choose only allowed alternatives. System authority, integrity,
mandatory state, budget and capability limits remain enforced and conflicting requirements refuse.

Between missions, transfer explicitly mapped outputs, required provenance/evidence and relevant
acceptance/revision/outcome facts; broader history is opt-in and scoped. Receiving missions retain
their own goals, obligations, budgets and authority. Unfinished producer obligations need explicit
delegation/adoption. Optional agent-based context preparation is a declared, budgeted operation with
source references and an output contract; its summary supplements required inputs and authoritative
state. Final assembly remains deterministic. See [CONTEXT-TRANSFER.md](CONTEXT-TRANSFER.md) for the
contract, authority model, boundary matrix, source gaps and proof plan.

**Confirmed: OC-D58..61 (2026-10-24).** Select bounded content/relationships independently of output
guarantee validation. Required references need retained access or a permitted immutable snapshot/export
covering execution and configured recovery/replay; refuse an unfulfillable availability promise.
Live additions and governed future-plan changes apply at safe boundaries while preserving used sealed
packets. Automatic repair stays within authored alternatives, capabilities and budget, then blocks.
See [transfer details](CONTEXT-TRANSFER.md#10-expansion-availability-live-control-and-repair).

**Owner redirection: OC-D62..63 (2026-10-24).** The next interview line addresses application-owned
storage, the read/export module boundary and retaining exact results versus repeatedly fetching
application state. See [application storage boundary](CONTEXT-TRANSFER.md#11-application-storage-boundary)
for current PostgreSQL/Neo4j read mechanisms and runtime database topology evidence.
The general content contract must not depend on the physical placement of native checkpoint tables.

**Confirmed: OC-D64..67 (2026-10-24).** Canonical content stays application-owned; reuse selected exact
results in suitable custody, refreshing only explicitly or through authored policy. Versioned application
modules implement a common deterministic reading/materialization/transfer contract. Agent-directed
knowledge acquisition belongs to Knowledge Services and is a distinct operation. Possible Financial,
Content, and Research and Evidence service boundaries remain illustrative. See
[discovery and delivery](CONTEXT-TRANSFER.md#12-knowledge-discovery-and-deterministic-delivery) for the
corrected boundary and proposed protocol.

**Confirmed: OC-D68..70 (2026-10-24).** Automatic application transfer uses typed references resolved by
application modules. Declared deterministic renderers/projections may produce required forms while
preserving exact source/transformation/result identities; semantic work remains separate. Ingestion
preserves both the original artifact and receipt-linked domain entity/revision, including normalized
or split content. See [the delivery bridge](CONTEXT-TRANSFER.md#123-typed-application-references).

## 12. Agent contributions and linked accountability

Round 10 confirmed optional subordinate output contracts, adoption, alternatives with settlement,
assessment reuse and revision authority. Exact protocols remain proposed. The owner reserves detailed
subagent shape/tools and provider-native construction for a separate interview (§12.6).

### 12.1 What current execution admission proves

Paths are under `src/mission_control/` unless otherwise stated. Subagent profiles include context mode,
sync/async kind, placement, budgets and capability seeds but no general output-obligation contract
(`domain/capabilities/subagents.py:159-203`). Technical async result admission checks completion and
matching child/generation identity (`application/subordinates/parent_completion.py:57-72`); it does not
prove a report fulfills its parent's content/purpose contract. Blocking child admission permits parent
progression (`application/subordinates/service.py:1376-1383`). Active, in-doubt or undecided effects block
terminalization (`application/subordinates/parent_completion.py:11-15,140-194`); unknown usage remains
unsettled even after native execution ends (`application/subordinates/service.py:1259-1273`).

Linked missions retain separate revision, budget and acceptance (`docs/knowledge/mission-chains.md:10-12`).
Late linked results after parent terminalization are deferred rather than mutating the parent's result
(`application/programs/linked_runs.py:389-405`). Deep Agents currently refuses `kind: linked_run`
(`application/authoring/lanes/deep_agents.py:119-121,292-296`); no proposed obligation contract creates that
missing provider execution capability. An existing output proposal attributes child candidates to the
parent unit and discusses `must_review`/`derives_from`, but direct mapping and review evidence still need
an explicit contract (`docs/specs/provider-consolidation-2026-10/providers/deep_agents/
SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md:351-364`).

### 12.2 Optional subagent obligations, adoption and verification reuse

**Confirmed: OC-D71.** A subagent may have explicit output obligations; they are not mandatory for
every helper. Assistance, context offloading and specialist work such as Browser Control can use the
provider's ordinary helper construction without inventing a deliverable obligation. A missing optional
contract is not a launch failure and does not imply a hidden report/schema requirement.

Where obligations are declared, a parent can delegate named
work and directly adopt an exact child output revision through an explicit mapping after compatibility
and required-guarantee checks. Preserve original producer attribution; do not force a parent to rewrite
a valid report. Parent obligation ownership remains with the parent. A mandatory review is a distinct
assessment record bound to the subject/version; `derives_from` alone proves neither review nor adoption.

**Confirmed: OC-D73.** Assessment reuse can avoid duplicate work when exact subjects/revisions, relevant contracts,
evidence, assessor authority, policy and freshness remain applicable. Each consumer evaluates its own
requirements; perform missing/new checks and reject stale or inapplicable assessments. A successful
producer mission or technically admitted child result is insufficient by itself. This extends the
already confirmed GoalDirected reuse rule to subordinate/linked consumers.

**Proposed elaboration:** an uncontracted helper result may still inform the parent's work. If the parent
nominates a helper artifact as a deliverable, assess it against the parent's contract with original
producer attribution; do not invent a retroactive child obligation or claim fulfillment the child was
never assigned. Preserve ordinary tool/native result provenance without treating every helper message
as a formal accepted output. Provider-specific submission mechanisms remain outside this sitting.

### 12.3 Productive completion and settlement

**Confirmed: OC-D72.** Declared required outputs remain all-required by default. This does not require
outputs from every optional helper. An authored alternative group may specify one
qualifying result or a quorum; every selected result must still satisfy applicable requirements.
Once productive work is fulfilled, unnecessary children may stop, but cancellation/usage/effects must
settle or be handed to an explicitly authorized durable owner. Do not confuse a satisfied selection
predicate with a fully settled parent run. No orphan workers or silent liability/budget transfers.

### 12.4 Existing linked-mission direction

OC-D56 already requires explicit adoption of unfinished work. Context transfer alone does not copy a
producer obligation into the receiver or release the producer from a promise. Proposed implementation
uses a named new receiver obligation with source lineage, its own authority/budget and an explicit
result mapping if completing delegated work for the producer. A producer that has stopped incomplete
does not become historically successful merely because a later independent mission uses its outputs.
Any reopening/amendment follows governed lifecycle rules. This is an elaboration of OC-D56, not a
claim of a currently implemented general delegation contract.

### 12.5 Governed output-contract revision authority

**Confirmed: OC-D74, refining OC-D42.** An executor can propose changes. The runtime can admit changes
within explicit delegated revision bounds; an authorized coordinator/client/human decision is needed
for changes that require that authority under the revision policy. Weakening requirements, dropping required deliverables, changing purpose
or waiving evidence needs authority that permits that change. Self-produced output is not sufficient
authority to lower its own pass condition. Preserve rationale, version, actor, impact and reassessment;
existing recorded failures remain historical. This does not mandate a human click for every revision:
delegation can pre-authorize specified changes, but the executor cannot widen its own delegation.

### 12.6 Subagent shape and tools deferred

**Explicit owner boundary: OC-D71.** The owner expects a separate interview about subagents and their
special tools, which the owner states have not yet been created. Existing provider ways of constructing
subagents feed the main configuration; Deep Agents has distinctive built-in interfaces. This sitting
does not decide a replacement tool API, require one provider-neutral construction shape, or infer that
native provider support implements every proposed output hook.

The later interview must decide helper shapes, construction/configuration, context-offloading behavior,
specialized capability exposure and provider-specific realization. This specification supplies the
optional obligation, provenance, adoption, reuse and settlement requirements that those mechanisms must
honor when applicable. Delivery continues to use the general transfer guarantees; no implicit provider
parity or new subagent-tool implementation is included in this sitting's work.

## 13. Assurance, provider extensions and scope boundary

### 13.1 Declared research coverage assurance

**Confirmed: OC-D75.** Output contracts distinguish supplied-assertion verification from a separate
assessment of material claims in the report and coverage of required research questions. Require that
stronger assessment only when the contract promises it. An admitted Knowledge Services/review capability
does the work; Mission Control checks its identity, scope, applicability and required result.

The record includes exact report/research scope, assessment method, reviewer/capability identity,
findings, coverage and unresolved gaps. It cannot claim infallible completeness. Independence is an
explicit assurance-profile requirement: a separate task is not automatically independent merely because
it uses another label, provider or model. Unsupported required review capabilities block admission or
fulfillment rather than substituting the narrower current supplied-assertion check. Specific algorithms
and any future service split remain owned by Knowledge Services, not implemented in the kernel.

### 13.2 Provider extensions

**Confirmed: OC-D76.** Obligation/acceptance semantics remain common. Versioned namespaced extensions
can express native capabilities and metadata with declared lane support and portability. A lane must
satisfy the contract or refuse it unless an explicit allowed alternative meets the same requirements.
Qualification applies to the actual capability/version and realization, not to a provider name alone.

Extensions cannot redefine fulfilled, verified, ingested or delivered to weaker meanings. Provider-native
content may be nonportable; that is explicit, and a consumer requiring portable bytes needs a declared
qualified export. The existing capability catalog/support-matrix architecture (ADR 0023) is the default
registration seam. This does not decide the deferred subagent construction/tool design.

### 13.3 Persistence topology scope

**Confirmed: OC-D77.** Preserve the inspected current baseline. This output/transfer scope does not
relocate standalone saver tables, deploy Agent Server PostgreSQL, choose a new database provider or
claim production topology qualification. Wider physical isolation belongs to the provider/subagent/
deployment follow-up. Logical authority separation and general application content access are required
regardless of physical placement. See the evidence and documented tension in
[CONTEXT-TRANSFER.md §11.2](CONTEXT-TRANSFER.md#112-storage-topology-evidence).
