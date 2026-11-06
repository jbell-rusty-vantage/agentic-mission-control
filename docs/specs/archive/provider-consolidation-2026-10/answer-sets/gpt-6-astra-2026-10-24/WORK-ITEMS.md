---
type: Specification
title: "Output obligations and application context delivery: issue-ready work items"
description: "Ordered local implementation specifications for output contracts, fulfillment, workflow execution, application context delivery, assurance and qualified provider realization; no external issues filed."
tags: [mission-control, output-contracts, context-transfer, implementation, work-items]
date: 2026-10-24
interview_id: output-obligations-gpt-6-astra-2026-10-24
interviewer_model: "GPT-6-Astra"
model_label_source: "Owner-supplied experiment label; exact serving model not independently exposed in this session"
research_assistant_model: "GPT-6.1-Sol"
source_commit: 8de6fab94fd5d17d79f2ecfd92e55329bb282a36
status: draft
---

# Output obligations and application context delivery work items

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../../sessions/KICKOFF.md); no new interview or runtime completion is implied.


**Sequence update, 2026-10-24:** the owner requires the
[application-knowledge prerequisite interview](../../interview-instructions/INTERVIEW-APPLICATION-KNOWLEDGE-BOUNDARY-2026-10-24.md)
and then the final output-contract/context-transfer interview before creating issues. Review these
local items against the resulting answers and deep-module projection. Their original provenance and
accepted product checkpoint remain intact; implementation details may change.

**Prerequisite clarified by the owner:** required schema refactors/migrations must finish before the
output-contract/context-transfer sprint. Extract that prerequisite work from these draft slices after
the interviews identify the exact impact; do not assume all migrations can wait inside runtime tasks.
The [BellLabs pathway](../../../../../../../../docs/BELLLABS-SEQUENCE.md) distinguishes this initial pass
from later domain-schema optimization and the still-undecided physical deployment topology.

These local IDs are ready for issue conversion, not filed issues or sprint completion claims.
Requirements come from [ANSWERS](ANSWERS.md), [SPECIFICATION](SPECIFICATION.md) and
[CONTEXT-TRANSFER](CONTEXT-TRANSFER.md). New exact data/state protocols are proposed in
[CONTRACTS](CONTRACTS.md); they are implementation design, not claims about current source.
Python source paths beginning `domain/`, `application/` or `adapters/` are relative to
`src/mission_control/`. Other paths are repository-relative unless explicitly marked BellLabs-relative.
Line anchors describe the source checkpoint above and can drift.

The general runtime owns acceptance, identity, transfer and settlement. Application modules own
native resolution, deterministic domain representations and canonical writes. Provider adapters
realize admitted plans. None of these items relocates databases (OC-D77), invents unavailable
application schemas, or designs subagent construction, native tools or new submission tools.
Optional subordinate integration hooks implement accepted accountability rules only (OC-D71).

## Shared definition of done

- Implement the relevant CONTRACTS protocol with closed typed errors, canonical fingerprints,
  scope checks and explicit compatibility behavior. Update public schemas and shared handlers
  together; no transport-specific acceptance rules.
- Every decision binds exact subjects, revisions, contracts, policy and authority. Separate
  authored requirements, observations, assessment, acceptance, materialization and external effects.
- Add focused domain/application tests and the acceptance fixture named below. Persistence claims
  require real local PostgreSQL; workflow durability claims require local Temporal replay/restart
  proof. Paid provider proof is a separately authorized qualification, never a prerequisite hidden
  inside an offline test. Record passed, failed, blocked and unrun checks separately.
- Common SQL changes belong only to `packages/mission-control-db-contract`, through a versioned
  release and authority tests. Runtime never migrates on startup. Preserve dirty/ignored data;
  operator approval/execution rules still govern migrations and live installation changes.
- Replayed mutations are idempotent and digest-stable. Persist new facts immutably; projection
  rebuilds reproduce decisions. Existing histories retain old semantics through an explicit
  version/replay branch where required, rather than changing past acceptance retroactively.
- Update the relevant knowledge concept, implementation status, API/operator examples and honest
  limitations. Run appropriate runtime checks and offline documentation checks. Test fixtures live
  under `tests/fixtures/`, not this specification directory.

## Ordered waves

| Wave | Work items | Exit evidence |
| --- | --- | --- |
| 1: contracts and custody | OO-1, OO-2, AC-1 | Typed identities, authored contracts and immutable ledger exercised by generic fixtures |
| 2: checks and source access | OO-3, AC-2, AC-3, AC-4 | Exact captured inputs, applicable checks, retained access and deterministic exports |
| 3: workflows and transfer | OO-4, OO-5, OO-6, AC-5 | Stage cycles, goal-wide verification and dependency delivery against sealed current sets |
| 4: governance and domain effects | OO-7, OO-8, AC-6 | Explicit adoption, bounded revision authority and receipt-backed lineage |
| 5: inspection and qualification | OO-9, QR-1, QA-1 | Replayable public views, provider receipts and actual application binding proof |

These are dependency waves, not dates, staffing promises or instructions to start parallel heavy
jobs. AC-6 can proceed alongside AC-4/5 after its prerequisites. Generic fixture application proof
comes before actual domain-service proof. Domain binding and provider qualification remain visible
gates; a generic fixture passing does not qualify AI Engineer, Biotech or another lane.

## OO-1 — Compile composable output contracts

**Problem/result.** Current `OutputDeclaration` is not the accepted obligation composition model.
Compile common forms plus composable application/purpose contracts and inline schemas into exact
versioned obligations without requiring a graph-wide final contract or obligations on ordinary helpers.

**Scope/seams.** `domain/authoring/manifest.py:732`, `domain/programs/completion.py:41-80`,
`domain/authoring/manifest_lowering.py`, `application/authoring/manifest_launch_inputs.py`.
Specify required/optional enforcement (mapping legacy expected-only status explicitly), count/coverage distinctions, accumulation scope,
layered reference guarantees and explicit final selection. Follow CONTRACTS rather than copying the
older proposal's mandatory-every-agent rule.

**Dependencies.** CONTRACTS identity/contract definitions; no runtime dependency on AC source modules.

**Acceptance.** Compile a stage with two distinct obligations plus an optional final view. An index
with correct JSON shape but missing report guarantees cannot compile as equivalent to those reports.
An uncontracted helper is valid. Reject contradictory composition and unsupported required extension.

**Persistence/replay.** Freeze compiled contracts/digests into admitted revision; no mutable catalog
lookup during replay. Additive protocol compatibility must be explicit. **Provenance:** OC-D32,
OC-D35..42, OC-D45..48, OC-D71, OC-D76.

## OO-2 — Persist submissions, deliverable revisions and fulfillment

**Problem/result.** Loose output references cannot distinguish three reports from three revisions
of one report. Introduce the immutable ledger and deterministic fulfillment projection in CONTRACTS.

**Scope/seams.** New neutral output module beside `domain/programs/completion.py`; application
orchestration under `application/programs/`; `domain/policies/contracts.py:1170` accepted evidence
and `:364-375` terminal proposal; postgres repositories and common SQL release.

**Dependencies.** OO-1.

**Acceptance.** Duplicate delivery is idempotent; conflicting reuse of a submission identity fails.
Three accepted revisions count as one logical deliverable. Subject coverage remains independent of
deliverable count. Retain valid A when required B is missing; current and historical fulfillment differ.
Canonical subject digests exclude later assessment/status facts and the digest field itself; equivalent
serialization order is stable. Verification cannot change the identity of its own subject.

**Persistence/replay.** New immutable records, scoped indexes and authority constraints require a
versioned migration. Rebuild current projection from historical facts; settlement binds evidence
frontier/obligation revision. Do not silently backfill old results as newly checked. **Provenance:**
OC-D34, OC-D45..47, OC-D49, OC-D51.

## OO-3 — Validate custody and layered guarantees; reuse applicable assessments

**Problem/result.** Model claims and technical completion cannot establish output validity. Make
registered custody authoritative and compute fulfillment from exact checks and applicable evidence.

**Scope/seams.** `application/artifacts/artifact_promotion.py:64-108`,
`application/programs/completion_validation.py:30-177`, `domain/programs/completion.py`,
`adapters/temporal/workflows/stagegraph.py:775-778` structured-output overlay. Keep semantic work
behind admitted assessment capabilities; expose its declared scope.

**Dependencies.** OO-1, OO-2; AC-3 for externally retained representations.

**Acceptance.** Empty model `output_refs` cannot erase registered candidates. Correct index shape
does not prove referenced content or ingestion. Reuse exact-subject valid assessments; reject stale,
wrong-contract or insufficient-authority evidence and run only missing checks. Producer-declared
assertion checking is never presented as independent coverage. Where coverage is promised, require
an applicable coverage-review receipt with method, scope and gaps.

**Persistence/replay.** Persist check/assessment identity and applicability inputs; no semantic model
call inside reducer/replay. Assessment receipt schemas may require common SQL extension. **Provenance:**
OC-D38..40, OC-D50, OC-D73, OC-D75.

## OO-4 — Govern Stage Graph obligations and cycles

**Problem/result.** Current cycle cap raises and aggregate refs do not express accumulated stage
fulfillment. Add authored per-cycle and accumulated obligations with governed stopping/cap outcomes.

**Scope/seams.** `domain/programs/interpreter.py:568`, `:808`, `:978-994`,
`application/programs/service.py`, `adapters/temporal/workflows/stagegraph.py`; manifest lowering.
Preserve intermediate submissions, authoritative handoff/state and explicit continuation conditions.

**Dependencies.** OO-2, OO-3; AC-5 for complete transfer integration.

**Acceptance.** Cycle 1 produces A, cycle 2 produces B; accumulated obligation retains A. Required
fulfillment stops productive work by default; authored continuation obeys governors. Exhausted cap
settles typed incomplete outcome and retains usable work. A revision does not inflate distinct count.

**Persistence/replay.** Persist cycle ordinal, contract/current-set identity and governed decision;
introduce explicit Temporal compatibility branch for changed historical behavior. **Provenance:**
OC-D32, OC-D34, OC-D45..48, OC-D52.

## OO-5 — Verify the GoalDirected whole current set

**Problem/result.** State accumulates refs while terminalization currently uses only current executor
outputs. Bind each verifier decision to the sealed goal-wide current set, retaining iteration history.

**Scope/seams.** `domain/programs/contracts.py:1457-1476`,
`domain/programs/goal_directed.py:281`, `:754`, `application/programs/goal_directed.py:676`, `:1170`;
GoalDirected Temporal workflow and context preparation.

**Dependencies.** OO-2, OO-3; AC-5 for findings/handoff delivery.

**Acceptance.** Iteration 1 accepts A/B, iteration 2 repairs C: verifier and terminal proposal cover
A/B/C, with reusable evidence on unchanged items. Concurrent A revision invalidates an old set verdict
for current completion. Malformed verifier output remains a typed failure, not an infinite retry.

**Persistence/replay.** Persist set digest/revision members and verifier receipt; reject stale decision
application by compare-and-set. Version workflow semantics for old histories. **Provenance:** OC-D49..52,
OC-D73.

## OO-6 — Release exact bound inputs and track downstream revision impact

**Problem/result.** Release conditions and data selection need separate contracts; accepted upstream
revisions must not silently leave downstream work current. Implement typed dependency/link rules.

**Scope/seams.** `domain/programs/interpreter.py`, `domain/composition/chain.py:121-143`,
`application/chains/reducer.py`, `application/chains/packet.py`,
`application/programs/linked_runs.py:407-430`; named input lowering.

**Dependencies.** OO-2..5, AC-5. Shared current-set primitives can be implemented before family integration.

**Acceptance.** Default release waits for required complete fulfillment; authored incremental release
delivers only qualified subset. A1 consumer result remains historical when A2 is accepted; current
affected work becomes stale until revalidated/rebuilt. Explicit snapshot consumer intentionally keeps
A1. No automatic descendant rerun or external write replay; control-only edge transfers no implicit data.

**Persistence/replay.** Freeze actual input revision membership and invalidation/revalidation facts;
extend chain/dependency persistence and migration only where needed. Replay event ordering gives the
same release/stale result. **Provenance:** OC-D47, OC-D49, OC-D53..56, OC-D60.

## OO-7 — Adopt contributions and settle qualifying alternatives

**Problem/result.** Child technical admission is not parent fulfillment. Provide optional contribution
and explicit adoption hooks, retaining parent accountability and settlement after any/quorum selection.

**Scope/seams.** Neutral CONTRACTS adoption/selection records;
`application/subordinates/service.py:1198-1238`, `:1256-1283`,
`application/subordinates/parent_completion.py:140-194`, `application/programs/linked_runs.py:389-430`.
Do not add subagent tools or prescribe provider-native construction.

**Dependencies.** OO-2, OO-3, OO-6.

**Acceptance.** Explicit exact child-report mapping fulfills compatible parent obligation with original
attribution; mandatory review has a separate receipt. Ordinary uncontracted helper still works.
Qualifying any/quorum selects only valid alternatives; nonselected children cancel/settle or transfer
liability to authorized durable owner. Pending usage cannot disappear when productive work completes.

**Persistence/replay.** Persist adoption, selected set and liability disposition separately. Synthetic
contribution fixtures prove kernel semantics; provider hooks await separate interview/qualification.
Late results remain historical and cannot mutate closed/superseded parent. **Provenance:** OC-D56,
OC-D71..73.

## OO-8 — Admit policy-bounded output-contract revisions

**Problem/result.** A mutable pass condition permits silent self-exemption. Separate proposal,
admission, activation and reassessment with bounded delegated authority and exact impact.

**Scope/seams.** Mission revision application handlers under `application/missions/`,
`domain/policies/contracts.py:364-375`, new output revision policy/records under domain/application
programs; existing public command admission path.

**Dependencies.** OO-1, OO-2, OO-6; integrate OO-4/5/7 at safe boundaries.

**Acceptance.** Executor proposal within delegation can activate; dropping required work without
appropriate authority fails. Authorized revision records actor/reason/version/impact. Old failure
remains old failure; reassessment is new evidence. In-flight sealed packet is unchanged.

**Persistence/replay.** Immutable revision journal and admitted activation frontier; migrate authority
records if necessary. Replaying cannot reconsult current delegation/catalog state. **Provenance:**
OC-D42, OC-D49, OC-D60, OC-D74.

## OO-9 — Inspect current, history and optional final output views

**Problem/result.** Flat output lists obscure ownership, staleness and incomplete work. Provide shared
query projections grouped by stage/goal and obligation, plus separate history and optional final view.

**Scope/seams.** `application/missions/inspection.py`, execution inspection and postgres queries;
HTTP/CLI shared handlers. Include authored/effective contracts, blockers, subject coverage, exact
verification set, adoption/lineage and transfer receipt references.

**Dependencies.** OO-2..8, AC-5; useful incremental views can ship after OO-2.

**Acceptance.** Both families show retained A and missing B; stale/superseded outputs are inspectable
but not current accepted fulfillment. Optional final contract adds a view without hiding intermediate
work or duplicating artifact identity. Pagination/filtering preserves exact point/revision semantics.

**Persistence/replay.** Read-only projection, rebuildable from authoritative records. Real PostgreSQL
and Temporal restart/replay scenario reproduces same view and settlement. **Provenance:** OC-D32,
OC-D34, OC-D49..51, OC-D71.

## AC-1 — Author typed application selectors and resolved sources

**Problem/result.** Current inputs accept only stage output/artifact/value. Add application/source
selectors distinct from resolved exact native revisions or retained results.

**Scope/seams.** `domain/authoring/manifest.py:705-728`, neutral `domain/context/` contracts,
`application/installations/registry.py:126-148`; exact fields in CONTRACTS.

**Dependencies.** OO-1 shared identity/contract model.

**Acceptance.** Pre-existing fixture entity binds without copying agent; unknown binding, denied scope
and unavailable revision differ. Native sequence/version is not replaced by bytes hash. Ordinary URL
content does not implicitly become an application reference.

**Persistence/replay.** Freeze selector and resolved reference separately; future refresh is a new
observation. No domain-specific schema imports in kernel. **Provenance:** OC-D64..68.

## AC-2 — Resolve bounded sources through registered application modules

**Problem/result.** Artifact capture cannot resolve arbitrary domain identities. Add scoped adapter
registry and bounded read/export protocol without turning transfer into autonomous discovery.

**Scope/seams.** New application port beside `application/context/pack_service.py:122-126`;
`adapters/postgres/context/artifact_bytes.py:39-46` remains artifact source; bootstrap application wiring.

**Dependencies.** AC-1.

**Acceptance.** Generic fixture resolves selected bounded membership; explicit refresh creates new
identity. SQL snapshot versus graph read result reports truthful consistency. Failed resolution does
not launch research, guess identifiers or select another service. Repair obeys authored bounds.

**Persistence/replay.** Record binding implementation/version, request and actual observation; external
read occurs outside deterministic reducer/workflow replay. **Provenance:** OC-D58, OC-D61, OC-D65..68.

## AC-3 — Retain exact observations and secure required availability

**Problem/result.** A live URL or native pointer alone cannot guarantee later execution/recovery access.
Retain exact bounded read results or verify sufficient external custody commitment.

**Scope/seams.** `application/ports/payloads.py:8-18`,
`application/artifacts/artifact_promotion.py:64-86`, scoped postgres context repositories and common SQL.

**Dependencies.** AC-2; shared retention/availability contract.

**Acceptance.** Restart after capture before sealing reuses exact result. Changed source cannot mutate
it; custody loss invokes bounded repair then blocks required delivery. Reference access covers declared
consumption/recovery window; unrelated application content is not copied.
Authorized erasure/revocation removes protected access and appends permitted unavailability metadata;
recovery blocks rather than serving a forbidden cached copy. Retention is not perpetual payload storage.

**Persistence/replay.** Versioned metadata migration and immutable content address; reconcile metadata
and payload storage without claiming distributed atomic commit. Retention cannot silently delete
required recovery inputs. **Provenance:** OC-D59, OC-D61, OC-D64..66.

## AC-4 — Produce declared deterministic representations

**Problem/result.** Native structured content needs consumer formats without hidden semantic rewriting.
Resolve pinned application exporters/general serializers and retain derived representation lineage.

**Scope/seams.** Application export port; `application/context/pack_service.py:107-126`;
artifact validation/promotion authority. Domain serializers remain application-owned.

**Dependencies.** AC-2, AC-3, OO-3.

**Acceptance.** Pinned structured fixture renders reproducible Markdown. Required omitted field blocks;
renderer/config change yields new identity. Summarization/claim selection requires separate admitted
preparation. Source/result digests differ legitimately with preserved relationship.

**Persistence/replay.** Persist transform/version/config and source/result identities; reuse retained
result rather than rerun nondeterministic parser. **Provenance:** OC-D39, OC-D65, OC-D69.

## AC-5 — Compile and deliver sealed transfer plans

**Problem/result.** Existing expansion hints are partial controls, not the complete accepted transfer
contract. Implement producer/consumer/edge/policy layering, required state/handoff and inspectable plan.

**Scope/seams.** `application/authoring/manifest_launch_inputs.py:2804`,
`application/context/pack_service.py:304`, `:392`, `:1002`, `:1152-1172`,
`domain/context/packet.py:566-617`; lane materialization ports and inspection handlers.

**Dependencies.** OO-1/2, AC-3/4. Deliver the shared transfer core first; OO-4..6 then integrate each
workflow family against it. Family integration is an acceptance gate, not a reverse prerequisite cycle.

**Acceptance.** Stage, cycle, Goal iteration and chain consumer receive required state plus exact
selected inputs. Bounded expansion is explicit; full authorized history accessible on demand. Required
local bytes cannot silently degrade to inaccessible ref. Optional context/live changes affect safe
future boundaries only; prior packet remains exact. Inspect authored versus effective settings,
omissions, repairs and access receipts.

**Persistence/replay.** Persist sealed transfer plan/packet digest and delivery metadata separately;
budget failure typed, mandatory requirements never silently dropped. No model in final assembly.
**Provenance:** OC-D52..61, OC-D65..69.

## AC-6 — Map source artifacts to authoritative domain revisions

**Problem/result.** Ingested entity existence or matching bytes does not prove lineage. Record explicit
receipt-backed native mappings while application retains canonical transaction authority.

**Scope/seams.** `application/artifacts/artifact_promotion.py:41-104`, neutral mapping records,
scoped postgres persistence; application-supplied intent/receipt resolver. Actual domain writers are
outside kernel and require separately inspected application contracts.

**Dependencies.** AC-1..3, OO-3; parallel with AC-4/5 after prerequisites.

**Acceptance.** Normalized/split report maps one artifact to multiple exact entity revisions without
inflating deliverable count. Lost response reconciles original effect/receipt identity. Original,
domain version and export are independently selectable. Unknown/partial receipt cannot claim complete
ingestion fulfillment; retain per-item native disposition and explicit policy decision.

**Persistence/replay.** Immutable lineage journal, no cross-database transaction assumption. Reconcile
uncertain effects before acceptance; do not replay domain writes on projection rebuild. **Provenance:**
OC-D39, OC-D64, OC-D70.

## QR-1 — Qualify provider output/delivery realization and namespaced extensions

**Problem/result.** A common protocol does not prove every lane can satisfy it. Qualify one lane at a
time; expose versioned native extensions with unchanged common acceptance semantics.

**Scope/seams.** General support/describe and authoring admission; Deep Agents-specific work under
`adapters/deep_agents/` and `application/authoring/lanes/deep_agents.py`; other lanes separate increments.
Current backend seeding is `adapters/deep_agents/materializer.py:1237-1257`.

**Dependencies.** OO-3/4/5, AC-5; no dependency on deferred subagent shape interview for main-agent proof.

**Acceptance.** Text-only StateBackend refuses required binary; byte-capable sandbox receives digest-
verified file. Unsupported required extension refuses unless explicit qualified alternative satisfies
it. Extension receipt identifies lane/version/portability limits; switching provider cannot silently
weaken requirement. Native final-message claims cannot forge custody or semantic acceptance.

**Persistence/replay.** Persist describe/version/materialization receipts and native observations;
common reducer remains SDK-free. Offline fixtures first; real provider proof separately budgeted and
reported. No topology relocation or implicit Agent Server production qualification. **Provenance:**
OC-D53, OC-D65, OC-D71, OC-D76..77.

## QA-1 — Bind actual application services and prove assurance/effect boundaries

**Problem/result.** Generic fixtures alone cannot qualify application content/export/receipt contracts.
Deliver explicit binding increments for each available service after source inspection, retaining
declared assurance scope and application authority.

**Scope/seams.** Bootstrap registered modules plus application-owned integrations. BellLabs-relative
candidate owners: `platform/knowledge-services/`, `aiengineer/ai-engineer-db-contract/`,
`biotech/biotech-knowledge-services/`. Read each owner AGENTS before work. Existing bridge evidence
is catalogued in CONTEXT-TRANSFER §12.6; it is not a ready general adapter. Register only implemented
and authorized read/export/receipt capabilities; missing schema/API is a visible blocked dependency.

**Dependencies.** AC-1..6, OO-3/6/9, QR-1 for chosen delivery lane. Generic fixture application first.

**Acceptance.** For each real binding: exact authorized read/export into a sealed packet; original
artifact through canonical domain receipt to revision/export; denied tenant and unavailable revision
failure; uncertain response reconciled without duplicate write. Research fixture distinguishes
producer-declared assertion checks from promised material-claim/question coverage review; records
method/gaps and rejects insufficient assurance. Code fixture separates produced patch from push/PR/
merge/deploy receipts. Record unavailable service proof as blocked, never fabricated pass.

**Persistence/replay.** Application owns migrations/transaction and receipts; MC owns immutable
mapping/settlement. Replay never invokes canonical writer. No app content authority moves into
checkpoint/store; no database relocation. **Provenance:** OC-D39..40, OC-D64..70, OC-D75..77.

## Conversion and remaining limits

The 17 items above cover nine obligation-runtime slices, six application-delivery slices, provider
qualification and actual application/assurance integration. Exact protocol choices belong in CONTRACTS
and should be referenced from external issues rather than copied into diverging descriptions.
Before filing, assign repository owner, migration release where needed, concrete fixture filenames,
and the exact public endpoint/schema changes. No OVE identifier is allocated by this document.

Partial ingestion follows the proposed explicit default in CONTRACTS §10: retain native per-item
dispositions, require proven success for every required member, and permit subset use only when authored
without waiving remaining count/coverage or unresolved effects. Qualified source/export
support must be established per application, and native provider extensions per lane. Subagent shapes,
tool APIs and provider-native construction remain a separate interview. Storage topology remains the
current baseline; separate standalone saver and Agent Server limitations are documented in
CONTEXT-TRANSFER §11.2. None of the acceptance examples here has been executed by writing this file.
