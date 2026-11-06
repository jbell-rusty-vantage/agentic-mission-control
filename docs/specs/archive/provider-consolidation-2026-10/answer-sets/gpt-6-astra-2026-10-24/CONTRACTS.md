---
type: Specification
title: "Output obligations and context transfer: proposed records, protocols and examples"
description: "Implementation design derived from the independent GPT-6-Astra interview: versioned records, identity, state transitions, application adapters, transfer planning, concurrency and worked scenarios."
tags: [mission-control, contracts, outputs, context-transfer, implementation-design]
date: 2026-10-24
interview_id: output-obligations-gpt-6-astra-2026-10-24
interviewer_model: "GPT-6-Astra"
model_label_source: "Owner-supplied experiment label"
source_commit: 8de6fab94fd5d17d79f2ecfd92e55329bb282a36
status: draft
---

# Proposed records, protocols and examples

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../../sessions/KICKOFF.md); no new interview or runtime completion is implied.


This document makes the confirmed requirements in [SPECIFICATION.md](SPECIFICATION.md) and
[CONTEXT-TRANSFER.md](CONTEXT-TRANSFER.md) implementable. The [owner's words](ANSWERS.md) remain the
decision authority. Record/field names and transition mechanics below are the interviewer's proposed
v1 design, not additional owner quotations or claims about existing APIs. Final schema generation and
runtime implementation belong to [the work items](WORK-ITEMS.md). Examples are proposed authoring
fragments, not manifests accepted by the current parser.

## 1. Contract layers and ownership

| Layer | Owns | Does not establish by itself |
| --- | --- | --- |
| Content contract | Shape, content/purpose requirements and declared proof layers | An assigned obligation or an ingestion operation |
| Output obligation | Who owes what, scope, quantity, coverage and applicable completion requirements | That submitted content is valid |
| Submission/revision | Exact candidate content, producer and contract version | Acceptance or current fulfillment |
| Assessment | A check of exact subjects under a pinned method/policy | Applicability to every later purpose/use |
| Fulfillment decision | Which accepted revisions satisfy which obligation at a recorded frontier | Mission settlement or external publication |
| Transfer contract | Selected inputs, required access/form, allowed alternatives and delivery conditions | Knowledge discovery or authority inherited from a producer |
| Application adapter | Native resolution/export/retention/lineage under common interfaces | Kernel ownership of domain content |
| Provider realization | Actual delivery/collection through a qualified lane | Weaker meanings of acceptance, ingestion or required access |

Code, knowledge and content use these same layers. A provider helper can have no output obligations;
that is valid. An uncontracted helper result can inform work or be nominated by a parent as a candidate
under the parent's contract, retaining original attribution. No special subagent tool shape is defined.

## 2. Common primitives and identities

All new records have a `schema_version`, `id`, `scope`, `created_at`, attributable `actor_ref` and
canonical record digest. Each schema defines its immutable digest projection, excluding the digest
field itself, transport envelope and later operational annotations. Recorded creation facts are fixed;
later delivery times, assessments and revocation facts are separate records. `scope` contains
installation/application/tenant; actor permission is checked
at use, not inferred from a copied scope object. Runtime source coordinates include mission/run/unit,
activation/cycle/iteration when relevant, attempt and generation. Native identifiers stay separate.

- A `PinnedRef` contains namespace/identity, version, digest and canonicalization/schema identity.
  Pin the transitive closure of reused definitions. Inline contracts receive the same compiled identity.
- A `SubjectRef` identifies an exact artifact revision, domain entity revision, retained read result,
  representation or sealed set; the discriminant prevents interpreting a digest as a mutable entity ID.
- Digests use the admitted canonicalization algorithm over exact immutable bytes/records. Native
  payload canonicalization is pinned independently; wrapping does not rename native keys or redigest a
  changed payload as if it were the original.
- New generic records are closed-schema. Native payloads and versioned admitted extension namespaces
  are explicit extensibility points, not arbitrary executable configuration.

### 2.1 Logical deliverables are independent of obligations and copies

`deliverable_id` is stable within its declared identity namespace. Mission-produced identities are
scoped to that mission/namespace and an authored logical key; application identities include their
stable issuing authority/native key and scope. The runtime assigns/validates the internal ID and records
aliases explicitly. A deployment URL, filename, content digest, receipt count or subject label alone
does not identify a logical deliverable.

Obligation ownership and bindings are separate records. The same exact deliverable can satisfy two
compatible obligations or appear in multiple views without gaining two identities. Moving custody,
rendering Markdown, adopting a helper result or exposing it through another mission does not invent
a second report. Separate reports about the same company can remain distinct; company coverage is a
separate predicate. Cross-mission reuse retains source identity and explicit adoption/provenance.

### 2.2 Revisions and concurrent acceptance

`revision_id` identifies immutable content/provenance for a logical deliverable. Its native domain
version, MC observation sequence and byte digest are different fields. New drafts do not replace an
accepted head. Promotion uses `expected_current_revision` and generation fencing; two concurrent
successors to A1 cannot both silently become current. A conflict preserves both candidates and requires
an explicit selection/reassessment, never timestamp-based last-writer-wins.

Replaying the same submission key and bytes returns the same record. Reusing that key with different
bytes is a typed conflict. Withdrawals/revocations/staleness append facts; they do not delete history or
silently fall back to an older accepted head. An explicitly bound valid historical snapshot can remain
usable under its policy. Corrections to external effects are new admitted actions, not ledger rewrites.

## 3. Proposed output records

### 3.1 `mc.output_contract.v1`

| Field | Type/rule |
| --- | --- |
| `contract_ref` | Exact compiled `PinnedRef`; source authoring may use resolved local aliases |
| `form` | `text`, `structured`, `file`, `collection`, `reference`, `code_change`, `effect_receipt`, or `control_record` |
| `media_types` | Optional constrained set; incompatible required formats refuse compilation/admission |
| `schema` | Inline supported schema or exact registered schema pin; optional where inappropriate |
| `all_of` | Pinned reusable content/purpose contract components; conjunction, not precedence overwrite |
| `requirements` | Unique named checks with kind, exact subject selection, required/optional flag, admitted validator/assessment binding and pinned policy |
| `reference_requirements` | Bounded member/relationship selectors plus shape/content/assessment/ingestion guarantees required of selected targets |
| `coverage_policy` | Optional native purpose/coverage policy pin and required question/subject references |
| `extensions` | Versioned namespaced capability/metadata requirements with lane support and portability requirements |

Forms describe representation/handling, not an exhaustive application type taxonomy. A Course is a
registered content contract over structured/file/collection forms. A report index can itself be the
only declared top-level output while its reference requirements demand valid, ingested reports.
Receipts and control records do not count as substantive reports unless a contract explicitly says so.

Composition preserves every conjunct. Compiler-detected contradictory constraints report paths to
both declarations. Unsupported schema/validator features refuse admission. This is not a claim of a
general JSON Schema satisfiability solver: executable validation still checks the effective conjunction.
Disjunction exists only in explicit alternative groups with defined qualification rules. Schema content
cannot install validators, acquire permissions, increase budget or override domain authority.

### 3.2 `mc.output_obligation.v1`

| Field | Type/rule |
| --- | --- |
| `obligation_id`, `revision` | Stable obligation identity plus immutable requirement revision |
| `owner` | Mission/program node/stage/goal, or explicitly contracted subordinate task |
| `evaluation_scope` | `invocation`, `cycle`, `stage_accumulated`, `iteration`, `goal_current`, or `workflow_final`; distinct from the record's application/tenant `scope` |
| `contract_ref` | Exact effective content/purpose contract |
| `required` | Boolean, defaults to true for a declared obligation; optional obligations use false; helper contract omission stays valid |
| `cardinality` | Nonnegative minimum, optional maximum; distinct eligible deliverable identities |
| `identity_policy` | Issuer/namespace and admissible logical-key/revision rules |
| `coverage` | Optional subject/question coverage predicates independent of cardinality |
| `applies_when` | Optional closed, admitted condition tied to canonical workflow control state |
| `alternative_group` | Optional group with `all`, `any_qualifying`, or `quorum`; quorum count/independence rules explicit |
| `completion_conditions` | Additional required review/coverage/approval predicates; separate from execution limits |

A conditional branch not activated can be `not_applicable` only with its canonical branch decision.
An agent cannot skip a required stage and declare its obligations inapplicable. A graph-level final
contract is optional and additional; satisfying it does not excuse unmet active stage obligations.

### 3.3 Submission, assessment, fulfillment and output-set records

| Record | Required contents |
| --- | --- |
| `mc.output_submission.v1` | Submission/idempotency key; producer coordinates/generation; deliverable/revision; proposed obligation bindings; exact contract pins; registered subject/custody refs; source/derivation lineage; expected prior accepted head |
| `mc.output_assessment.v1` | Exact subjects/subject-set digest, requirement IDs, method/capability/version/policy pins, assessor identity/authority, evidence references, coverage scope, result/findings/gaps and declared validity/expiry conditions; subsequent revocation is a separate fact |
| `mc.output_fulfillment.v1` | Obligation revision, exact eligible member revisions and check refs, distinct count, coverage witness, evaluation frontier, disposition and unmet reasons |
| `mc.output_set.v1` | Owner/view, monotonically recorded set version, stable ordered member/binding identities, effective contract pins and subject-set digest; assessment and stale/superseded facts are separate linked records |

The **subject-set digest** covers exact member revisions, obligation/input bindings and effective
contract pins, excluding assessments and mutable status annotations. An assessment references this
stable subject identity. A separate evaluation/fulfillment decision references both the subject set and
the assessments used. Adding the verifier's result therefore cannot change the identity it verified.

Assessment results are `pass`, `fail`, `review_required`, `abstain` or `unavailable` at the common layer,
with native semantic verdicts preserved. Supported/contradicted/inconclusive are domain assertions about
evidence; they are not automatically interchangeable with pass/fail. A report can pass while faithfully
describing a contradicted hypothesis if the purpose policy allows it.

Common fulfillment disposition is `unfulfilled`, `fulfilled`, `blocked`, or `not_applicable`.
Unfulfilled describes an unsatisfied promise; blocked records a requirement that cannot presently be
evaluated/delivered under admitted conditions. Both prevent required completion. Stale/revoked evidence
can make a formerly fulfilled obligation unfulfilled/blocked at a later frontier while preserving the
earlier decision. Waiving a promise requires an authorized contract revision, not a new success label.

### 3.4 Coverage and assessment reuse

Record whether an assessment checks `producer_declared_assertions` or a separate material-claim and
research-question coverage requirement. The latter records its review method, scope, reviewer
independence requirement, findings and gaps. It does not certify perfect recall. No universal coverage
review is imposed on every output. Required unavailable review capability blocks rather than borrowing
a narrower check's label.

Reuse is check-specific: exact subject/revision/qualifiers, relevant evidence selectors/digests,
capability/method, applicable policy and authority must still satisfy the consumer. Recheck current
eligibility, revocation, access and freshness at consequential use. A changed purpose may retain shape
checks while requiring new semantic/coverage checks. Report reframing may invalidate coverage even
when individual assertion assessments remain applicable. Producer mission success is not a cached
consumer acceptance decision.

## 4. Runtime evaluation and workflow rules

1. Admit/pin contracts, validators, sources, representations, budgets and policies. Validate feasibility;
   record runtime conditions for not-yet-produced outputs instead of fetching imaginary artifacts.
2. Register exact submissions with custody/provenance; stale generations cannot change current heads.
3. Evaluate required shape, referenced targets, content assessments, coverage and effect proofs. Batch
   checks are permitted but cannot hide unassessed members. Keep each successful member and each failure.
4. Admit eligible revisions and evaluate obligations transactionally against expected heads/versions.
5. Seal the current result set and release declared consumers. Duplicate releases are idempotent.
6. Evaluate productive completion separately from governor stops, unresolved effects/usage, settlement
   and final mission acceptance through existing reducers; new projections cannot bypass them.

### 4.1 Cycling stages and Stage Graphs

Each cycle's required submissions and the stage's accumulated obligations are different scopes. A
completed cycle can make progress without fulfilling the stage. Default successful stopping requires
the applicable current cycle and accumulated requirements plus additional completion predicates.
Proposed missing-per-cycle behavior is bounded repair within that cycle, then block/stop with the
unmet requirement; creating another cycle cannot silently erase it. Attempt retries are not new cycles.

Cycle/time/budget limits produce a governed stop/incomplete disposition, retaining individually usable
deliverables. They never fabricate successful fulfillment. A stage with no output obligations retains
its existing explicit execution/completion policy; the empty set must not auto-stop it before work.

### 4.2 GoalDirected current-set verification

The verifier receives accepted prior heads plus proposed additions/replacements, unmet obligations and
findings. Mark candidates distinctly; pending/failed candidates do not become accepted merely by
appearing in the set. Seal a verification snapshot containing `base_set_version`, proposed changes,
exact members/contracts and subject-set digest. Applicable prior assessment references accompany that
snapshot outside its subject digest. Preserve executor/verifier isolation.

On verifier return, reconcile the same source frontier and required facts before promoting changes
or accepting the goal. A2 accepted while a verifier assessed A1 makes that verdict inapplicable to the
new current set; retain it historically and revalidate. An iteration repairing C cannot drop accepted
A/B. Terminal outputs come from the accepted goal-wide current set, not only the last execution refs.

### 4.3 Release, revisions and linked missions

Default release waits for producer completion. An explicit incremental binding defines accepted-item
or batch/coverage trigger, selected member set, revision behavior and consumer dispatch/coalescing
policy. Release identity includes link/binding, exact selected set digest and trigger generation.
Retries do not duplicate dispatch. Incremental active-producer use and stopped incomplete-producer
partial use are separate flags; neither implies provisional unaccepted input consumption.

Tracking is default; snapshot binding explicitly pins historical revisions. A changed accepted source
marks affected tracked results stale, preserving exact used inputs and external effects. Determine
impact from recorded subject/selection dependencies; absent a qualified compatibility assessment,
conservatively invalidate the affected dependency. Do not blindly rerun every descendant or repeat
external writes. In-flight results remain tied to their original packet and cannot silently count as
current after its tracked inputs become stale.

Linked missions have separate goals, obligations, acceptance, grants and budgets. Map outputs to inputs
explicitly. Unfinished work can become a named receiver obligation with lineage and authorized delegation;
passing a report does not assign the task or release the original owner. Adopted output is checked against
the receiver's requirements. Already-closed incomplete history is not silently rewritten as successful.

### 4.4 Optional subordinate contributions

Ordinary assistance/offloading/specialist helpers remain valid without an obligation declaration.
Optional contracted work can be adopted through an exact child-output-to-parent-obligation mapping.
Parent retains accountability and child attribution; a required parent review needs its own assessment.
Technical provider completion/generation matching is not semantic acceptance.

Alternative groups select only qualifying distinct contributions under declared quorum/independence
rules. Once required productive work is done, remaining activity must cancel/settle or transfer effect/
budget responsibility to an admitted durable owner. Full settlement waits for that responsibility to
be resolved. No new subagent tools, universal construction API or provider-native shape is specified here.

## 5. Contract revision protocol

Proposed operations: `propose_revision`, `admit_revision`, `activate_revision`, `reassess_subjects`.
A proposal names expected prior version, exact change, actor/reason, authority and impact set. Admission
compiles the successor and checks delegated policy. Activation occurs at a recorded safe boundary with
optimistic concurrency; dispatched invocations remain bound to their sealed version unless an admitted
interrupt/restart is performed. New optional fields may be policy-admitted; dropping requirements or
changing promised outcomes needs the relevant explicit authority. The executor cannot self-grant it.

Historical submissions and failed assessments retain old pins. Reassessment creates new records and
can establish fulfillment under a successor contract; it never changes old failure bytes in place.
Preview identifies affected bindings, coverage predicates, assessments, packets and current results.
Contradictory or unsupported revisions fail before activation; budget/provider changes need their own
admitted control path, not a schema change disguised as authority.

## 6. Application content and transfer records

### 6.1 Source records and application adapter protocol

| Record | Required contents |
| --- | --- |
| `mc.application_content_selector.v1` | Application/source binding pin, native kind/identity or admitted retained-result selector, exact-version or declared freshness rule, bounded selected relationships, required contract/representation |
| `mc.application_content_ref.v1` | Issuing authority, scope/binding, native contract and immutable entity revision or retained-result identity, truthful version semantics, metadata/provenance resolution capability |
| `mc.source_resolution.v1` | Selector/request identity, exact resolved refs and membership, native read/result receipts, actual consistency/read interval, missing/truncated dispositions, retained bytes/digest where applicable, access and availability commitments |
| `mc.content_representation.v1` | Exact source refs/result digest, pinned renderer/projection/profile/config, selected fields/membership, media/manifest, representation digest/size and custody |
| `mc.ingestion_lineage.v1` | Original source refs/digests, native intent/plan/effect/receipt identity, per-item disposition, affected typed domain refs/revisions, actor and runtime production coordinates |

The source selector may ask for current content at a declared boundary. Its resolved ref and the packet
never contain an unrecorded moving target. A retained graph read is not a promise of historical graph
reread, and a schema digest is not a data version. An ordinary URL stays ordinary data unless a qualified
module resolves it under an admitted typed contract.

Proposed logical adapter operations, bound to existing capability registration rather than invented
live HTTP paths:

- `describe`: supported native contracts, resolution/export/retention methods, versions, limits and
  actual consistency/portability guarantees. A source binding can expose only a subset.
- `resolve`: consume the declared selector, scope and bounds; return exact identities/membership and
  recorded observations. Required ambiguity, unavailable revision or incompatible consistency fails.
- `export`: return an already-stored representation or run an admitted deterministic renderer/profile
  over exact source results. It does not initiate discovery, semantic summarization or ingestion.
- `ensure_availability`: obtain a retention commitment or permitted exact copy/export for the declared
  execution/recovery period. Unsupported commitments cannot be advertised as secured.
- `read_representation`: retrieve exact authorized bytes/parts or supply an admitted access handle;
  enforce digest/version/scope and current policy. A plan reference is not proof of successful access.
- `resolve_ingestion_lineage`: authenticate/correlate existing native receipts and affected identities;
  it does not apply another write. Native receipt recovery remains a separate admitted capability.

Adapters may share service code with Knowledge Services, but these delivery operations do not select a
new research question. Exploratory agent reads remain separate knowledge work. Multiple bindings/modules
per application are supported; service packaging and Financial/Content/Research naming are not fixed.

### 6.2 `mc.context_transfer.v1`

| Field | Rule/default |
| --- | --- |
| `profile_ref`, `inline` | Same supported versioned settings; exact reusable profile pin plus explicit inline specialization |
| `boundary`, `source`, `target` | Stage/cycle/goal/subordinate/link/continuation/fork/review purpose and exact runtime coordinates |
| `bindings` | Named source obligation/output/typed reference to named consumer input; required flag and consumer contract |
| `release` | Completion by default; explicitly configured incremental/partial conditions |
| `revision_policy` | `track` default; explicit `snapshot` with exact pin |
| `selection` | Declared members/fields/relationships; max depth/items/bytes, stable ordering/deduplication |
| `delivery` | Required access and forms; explicit acceptable alternatives; separate ordered preferences |
| `availability` | Consumption deadline plus configured recovery/replay window and admitted retention/copy terms |
| `history` | Authorized selected ranges/references and on-demand/materialized preference; broader history off by default |
| `preparation` | Optional separately admitted operations with exact inputs, budget and output contracts |
| `resources` | Prompt/file/count/time/retrieval/preparation limits within mission reservations |
| `change_policy` | Authorized changes and safe boundaries; immutable used packets |
| `repair_policy` | Retry count/time/spend, allowed alternative forms/preparation, then block |

Proposed default resolution: system/installation hard constraints plus source and consumer hard
requirements must all hold; defaults specialize profile -> mission -> unit -> input/link. Conflicting
hard constraints refuse. Preferences on the same consumer input specialize input over unit over mission
over profile; a link can restrict the allowed set but cannot override consumer required access. Conflicting
equally-specific preferences use deterministic declared ordering or fail when ambiguous. Expose origins
and the resolved effective settings. Do not implement recursive last-writer-wins on every field.

Mandatory authoritative state is added according to boundary: contract pins, current deliverable set,
unmet obligations, verifier findings, invalidations and reliable required-input access. It cannot be
removed by a profile. Broader transcripts are scoped opt-in. Application content remains data; transfer
does not promote instructions embedded inside it into runtime authority.

### 6.3 Transfer lifecycle and receipts

Proposed persisted states: `admitted` -> `waiting_release` -> `resolving` -> `preparing` (if declared) ->
`planned` -> `delivering` -> `ready`, with `blocked`, `failed` or `cancelled` dispositions retaining all
attempts. A permitted repair retries the same exact source observation or creates an explicitly linked
new plan. Authorized refresh creates a new observation. Resuming never mutates a used packet.

`mc.transfer_plan.v1` records effective configuration, exact source-set and representation refs, required
state, selected delivery forms, authorized optional omissions, availability commitments and plan digest.
`mc.delivery_receipt.v1` binds plan/packet to receiver invocation/attempt, actual representations and
verified digests/access/materialization results. Per-item outcomes remain inspectable. Ready requires
all required start conditions; optional omissions are reported. Receipts prove actual delivery/access
facts, not model attention or comprehension.

Mandatory inputs exceeding a cap block; optional omission is permitted only under the authored policy.
Bounded expansion detects repeated identity/revision to terminate cycles. A required file cannot be
replaced with a reference unless allowed and actually accessible. Retrieval of fixed, declared inputs
may be on-demand if the access requirement permits it; a future agent's hoped-for discovery is not a
delivery guarantee. Unexpected loss/revocation repairs or blocks; retention never overrides current
source authorization. Expired recovery windows need new admission rather than invented availability.

Immutable history does not promise perpetual payload retention. Authorized erasure removes protected
payloads/cached copies according to applicable retention and access policy, while retaining only
permitted metadata and an appended tombstone/unavailability fact. Replay cannot reconstruct deleted
content or bypass revocation through another cache. Required recovery then blocks or needs newly
authorized input admission; a retention promise is never permission to ignore erasure authority.

## 7. Inspection and mutation surface

Extend shared application handlers exposed by HTTP/CLI/MCP rather than defining independent business
logic per transport. Proposed logical operations: inspect/preview effective contract; submit/list exact
revisions; assess/evaluate fulfillment; inspect current/history/final output views; propose/admit
revision; preview/read effective transfer plan; register/inspect application source bindings and
capabilities; inspect source/representation/ingestion lineage; retry blocked transfer within policy.
These are proposed operations, not claims about existing endpoint names.

Writes require expected record/version, idempotency key, scope and authority; the runtime records actor,
reason and coordinates. Views must expose unresolved obligations, per-layer failures, provenance,
assessment applicability, stale/revoked status, effective settings and actual delivery. Use one
canonical current-set projection for StageGraph and GoalDirected, grouped by owner/obligation. History
is separate; optional final view is additional. The same revision referenced twice remains one identity.

## 8. Persistence and rollout requirements

Add append-only contract/submission/revision/assessment/fulfillment/set/source-resolution/representation/
transfer/lineage records and transactional current-head indexes through the common database contract.
The actual table grouping may reuse suitable existing content/event stores; relational integrity,
scope, version/idempotency constraints and replay semantics are mandatory. Domain entity foreign keys
do not enter common SQL. App modules own native identifiers and transactions.

Register capability/schema versions and use compatibility admission for API/worker/DB release skew.
All applications receive the identical common schema release; physical runtime database placement
stays unchanged under OC-D77. Backfill old registered refs as legacy observations with their actual
assurance scope; never fabricate content verification, ingestion, delivery or coverage proof. Existing
uncontracted missions/helpers keep their existing behavior until explicitly revised/migrated.

Crash fixtures must cover observation retained before plan sealing, packet sealed before dispatch,
duplicate submission/receipt, assessment returned after head changed, lost domain receipt, cancellation
with unresolved child usage/effects and invalidation after an external write. Recovery reads original
identities/receipts and never replays an uncertain external effect under a fresh key.

Digest fixtures must prove that equivalent canonical serialization order produces the same digest,
that the digest excludes its own field, and that appended assessments/revocations do not mutate an
already sealed subject identity. Erasure fixtures verify both cache enforcement and blocked recovery.

## 9. Worked authoring examples

The following fragments illustrate the proposed model; aliases stand for pinned registered definitions
or compiled inline definitions. They are not executable against today's manifest parser. Content models
for future courses/projects are assumed for design, as requested, rather than claimed to be installed.

### 9.1 A cycling company-research stage

```yaml
stage: research_companies
obligations:
  - id: cycle_index
    evaluation_scope: cycle
    contract: ingested_report_index_v1
    cardinality: {min: 1, max: 1}
  - id: company_reports
    evaluation_scope: stage_accumulated
    contract: evidence_backed_company_report_v1
    members_from: cycle_index.reports
    cardinality: {min: 5}
    coverage: {subjects: [company_a, company_b, company_c, company_d, company_e]}
completion:
  required_obligations: fulfilled
  additional_conditions: [required_editor_review_passed]
```

`members_from` illustrates a bounded reference selector, not a new application-specific kernel field.
The index can remain the sole top-level submission surface. Referenced report obligations do not force
copies into extra output slots. The index contract requires its shape, qualifying target report
assessments and authenticated ingestion lineage. Empty progress membership is permitted by the cycle
index schema; its entries, if any, must qualify. The stage still owes five covered companies.

Cycle 1 reports A1/B1; cycle 2 revises A to A2 and adds C1. The current report set is A2/B1/C1, with
three logical identities and three covered companies. A1 remains history. Five reports about A cannot
satisfy five-company coverage. A required review still missing prevents completion even when all five
reports exist. A cycle cap preserves accepted members and reports the stage/mission incomplete.

Two later consumers may select different transfer expansions: an index-only monitor receives the
index and necessary guarantee facts; an analyst selects the report bodies as well. The validation
requirements do not require copying all source evidence into both consumers.

### 9.2 Application-backed content into another workflow

```yaml
input: prior_company_report
source:
  binding: biotech_reports_v1
  kind: evidence_report
  native_id: report_a
  revision: revision_7
transfer:
  revision_policy: snapshot
  selection: {fields: [body, conclusions, evidence_links], max_items: 1}
  delivery:
    required_form: local_file
    media_type: text/markdown
    allowed_alternatives: []
  representation: biotech_report_markdown_v2
  availability:
    consume_before: mission_deadline
    recovery_until: configured_recovery_deadline
  repair_policy: {max_attempts: 2, allow_refresh: false}
```

The application binding resolves the exact native revision or an admitted retained result, exports
the declared fields with a pinned deterministic renderer and secures permitted custody. The packet
names the exact result and representation. The lane supplies a digest-checked file before readiness.
Retry reuses that observation; it does not query current revision 8 or commission a new report.

If the application cannot retrieve revision 7 and no exact retained copy is admitted, transfer blocks.
If the lane cannot deliver the required file, it refuses; a URL is not an allowed fallback here.
Availability can be supplied by application custody or a retained copy. Neither choice changes who
owns the canonical report. The target mission gets its own goals, grants and budget, and no producer
transcript unless explicitly selected. Discovery of further companies uses separate Knowledge Services
capabilities. Deterministic delivery means recorded, reproducible selection and assembly from retained
observations, not a claim that repeated reads of mutable storage always return the same data.

### 9.3 Content, knowledge and code obligations

| Scenario | Contract/fulfillment | Observable result |
| --- | --- | --- |
| AI Engineer curriculum | A curriculum references course revisions and relationships; a course package includes lessons, challenges, project specification/assets and required assessments under versioned application contracts. | Missing required project leaves its course/mission obligation unfulfilled; independently accepted lessons/reports remain usable. Ingestion into application storage is a separate admitted operation. |
| Financial company comparison | Inline structured columns include company identity, metric, unit/currency, observation period, source and evidence status; purpose policy pins required coverage/freshness. | Schema-valid numbers without required units, dates or evidence fail the relevant layer. This is a content contract, not a hard-coded financial output kind or investment verdict. |
| Biotech hypothesis report | Evidence chain points to sources, assertions, judgments and verdicts; purpose contract requires material-claim/question coverage review. | A contradicted hypothesis can yield an accepted report when faithfully represented. Supplied-assertion checks alone cannot satisfy the promised coverage review. |
| Codebase change | Repository/base/head or retained patch identity, exact checks, scope and reproducible change bytes; dependencies on evidence/content remain recorded. | A patch can fulfill its authored obligation without a push. Push, PR, merge or deploy is required only if separately declared and authorized; each effect needs its own correlated receipt. |
| Provider browser helper | Parent receives attributed screenshot/observations from an ordinary helper with no named output obligation. | Helper use remains valid. Parent can nominate the result for its own contracted obligation, then run the required checks; helper text cannot self-certify parent acceptance. |

The same pattern supports authored blog posts, charts, PDF reports and market research packages. An
application contract supplies its meaning and content policy; the provider supplies qualified handling.

### 9.4 GoalDirected repair and linked reuse

1. Iteration 1 accepts A1/B1, while C1 fails. Its evidence remains recorded.
2. Iteration 2 submits C2. Verification subjects are A1/B1/C2 plus the goal's effective obligations;
   C2 is a candidate until accepted. Valid checks on A1/B1 can be reused.
3. If A2 becomes current before verification returns, the A1/B1/C2 result remains historical. A
   compare-and-set refuses goal completion against the changed frontier; the next check uses A2/B1/C2.
4. A linked market-analysis mission binds the accepted reports and its own stronger purpose contract.
   It reuses applicable source checks, adds missing review and records exact consumed versions.
5. A subsequent A3 marks affected tracked analysis stale. An explicitly snapshot-bound publication
   draft can intentionally retain A2; any already performed publication remains an external fact.

## 10. Failure and recovery acceptance matrix

| Trigger | Required behavior | Work items |
| --- | --- | --- |
| Duplicate submission key/same bytes | Return original identity; no extra count or second effect | OO-2 |
| Same key/different bytes or competing accepted successors | Typed conflict; retain candidates; explicit reconciliation | OO-2, OO-8 |
| Verifier returns after subject frontier changes | Preserve historical assessment; refuse current acceptance | OO-3, OO-5 |
| Required per-cycle index missing | Bounded same-cycle repair, then block/incomplete; no erasure by starting another cycle | OO-4 |
| Optional final selection satisfied but required active stage unfinished | Final-view availability does not make graph complete | OO-4, OO-9 |
| Inactive conditional branch | Not applicable only with canonical control decision; no self-exemption | OO-1, OO-4 |
| Incremental consumer retry | Same release identity and exact membership; no duplicate dispatch | OO-6, AC-5 |
| Source unavailable after capture | Reuse authorized retained observation; bounded repair or block if custody lost | AC-3, AC-5 |
| Required input exceeds context/storage budget | Block with conflicting requirements; no silent omission/summary/provider switch | AC-5, QR-1 |
| Domain write succeeds but response is lost | Reconcile original effect/receipt key; no blind second write | AC-6, QA-1 |
| Domain reports partial apply | Preserve native per-item outcomes; only explicitly allowed, proven successful members qualify | AC-6, QA-1 |
| Child alternative wins while other child usage/effects are unknown | Productive selection can finish; settlement remains unresolved until cancelled/settled or authorized ownership transfer | OO-7 |
| Erasure/revocation conflicts with stored availability promise | Enforce access/erasure, append permitted unavailability fact, block dependent recovery; never serve forbidden cached content | AC-3, AC-5 |
| Unsupported provider extension or binary delivery | Refuse, unless a declared qualified alternative meets all requirements | QR-1 |

Proposed partial-ingestion default: a promise that every referenced member was successfully ingested
fails if any required member is partial, unknown or failed. A separately authored accepted-subset policy
may expose proven successful members, but it cannot relabel the whole native receipt successful or
waive remaining cardinality/coverage. Changed membership creates a new exact index/result revision.
Unknown effect status remains a settlement concern even when some content is individually usable.

## 11. Design review disposition

Owner-confirmed product choices are recorded through OC-D77. The schema vocabulary, digest projection,
conditional-branch mechanics, concurrency protocol and failure defaults here are proposed implementation
choices. They need engineering review and the named fixture proofs, not another round of owner syntax
questions. Physical deployment changes and special subagent construction/tool design remain deferred.
The issue pack separates shared runtime, application-binding and provider qualification evidence.
