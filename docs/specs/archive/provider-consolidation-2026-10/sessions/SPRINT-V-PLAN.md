---
type: Session Instruction
title: "Sprint V: clean refactor of verification, reports and knowledge ports"
description: "Implementation waves, schema ownership, proof tiers, work items and operational release gate for AI Engineer followed immediately by Biotech in the same sprint."
tags: [mission-control, knowledge-services, verification, migrations, release, sprint-v]
date: 2026-10-24
status: archived
archived: 2026-11-02
archived_from: SPRINT-V-PLAN.md
archived_reason: "Sprint V executed 2026-10-25"
---

> **Archived 2026-11-02** (Sprint V executed 2026-10-25). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Sprint V implementation plan

Read [ANSWERS.md](../answer-sets/sprint-v/codex-gpt-6-2026-10-24/ANSWERS.md),
[research findings](../docs/SPRINT-V-RESEARCH.md), [contract projection](../specs/SPRINT-V-DESIGN.md), then
[team workspace](../sprint-v/TEAM-WORKSPACE.md). Owner decisions SV-D1..14 supersede older interview
recommendations where identified. The owner accepted the specification and workspace in SV-D13;
engineering defaults below are accepted recommendations, not owner quotations. Agents begin at
[repository/database navigation](../sprint-v/START-HERE.md).

## 1. Scope and the two completion gates

**Sprint V builds the new foundation:** one verification core, one operational schema component, one
report core, AI Engineer PostgreSQL and Biotech Neo4j bindings, versioned schema releases, trusted MC
ports, direct verification harness and controlled integration proofs. AI Engineer is proved first;
Biotech follows immediately **in the same sprint**. Two complete report types: evidence report and study
appraisal; the rest of the catalogue extends the same envelope.

**Routine/general-use gate is later and conjunctive:** routine real research, ingestion, retrieval
and retrieval experiments wait until all four canonical workflow systems (Stage Graph, Goal Loop, Parallel Swarm,
Evaluator Optimizer), their output contracts and context transfer, and Deep Agents as a provider are
fully qualified. Required composition, linked-mission, continuation, review, cancellation and recovery
boundaries are part of that gate. Sprint V completion alone never opens it (SV-D12, explicitly amended
for qualification by OC-D128 below).

**2026-10-26, OC-D128 qualification exception:** the owner explicitly permits bounded runs of the
supplied real fixtures at progressive checkpoints, after each checkpoint's prerequisites are ready.
These use real agents and the actual acquisition/ingestion/retrieval paths required by the fixture.
Review the Mission Transcript and results against functional goals, fix any failing owning layer
(including migrations) and rerun before advancing. Synthetic/scripted tests can aid diagnosis but
cannot replace functional acceptance. This does not open routine use. Exact answer and current contract:
[IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md),
[CONTRACTS §11](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md#11-real-fixtures-and-the-general-use-gate).

Testing before that gate includes disposable fixtures, bounded engineering experiments and the explicit
OC-D128 real-fixture qualification exception. A fixed-corpus verification test is not an operational research mission. No production
knowledge is accumulated for future use. Complete BellLabs Knowledge Platform F99 fixtures retain their
own dependency gate; smaller component and integration fixtures do not masquerade as F99.

### Clean refactor stance

All current application data/history is test data and disposable (SV-D8/SV-D12). No legacy seal importer,
dual writer, historical-row backfill, old-client adapter or preservation-driven migration is required.
Delete obsolete paths when the replacement passes its seam proofs. New runtime evidence must still be
immutable and correctly attributable; disposability of old data does not relax new-system invariants.

Preserve source work belonging to other active sessions and avoid deleting secrets or personal files.
Database resets act only on explicitly resolved test installations. Use reset/rebuild receipts and
reproducible target-schema installs. Do not force a legacy upgrade path where clean installation is the
chosen release strategy. Version breaking protocols/components accordingly; first major product release
does not require every already-versioned component to use the number 1.0.

## 2. Wave DAG and first artifacts

Logical dependency order below; independent implementation cells within each wave may run in parallel.
Schema authors and integration coordinator are single writers. There is no later wave that changes an
earlier record's meaning; new capability must satisfy the pinned contract or create an explicit revision.

| Wave | Repositories / modules | First artifact and work | Exit proof / next dependency | Rework avoided |
| --- | --- | --- | --- | --- |
| W0: authority and baseline | MC M01/M06; KS K01; AIDB; BKS | Exact source/target inventory; schemas and operation golden fixtures; fix live attempt coordinates; designate BKS source tree; select common component owner | T0 coordinate/canonicalization tests; signed-off schema ownership inventory; target migration names reserved | Avoids sealing template origins, writing SQL twice, and editing generated SDL as source. |
| W1: unified foundation | KS K01..K05/K07/K09; AIDB; MC M05 release source | Pure core records; new common SQL component; one durable run writer/sealer/oracle; tenancy and exact-effect identity; retire two-run truth paths | T0 contract/support/seal tests; T1 fresh common schema in two disposable app databases; standalone run with null MC linkage | Avoids rebuilding ports around incompatible stores or a second verification authority. |
| W2: AI Engineer complete service path | KS K02/K04/K05/K08; AIDB | Report v2 render/ledger, independent census, aggregation, authority/challenge, exact-use review/revocation; plan/apply/receipt and exact report read | T0 adversarial report fixtures; T1 AI graph-in-Postgres fixtures; bounded T2 direct-model control proof | First complete evidence→assertion→verification→verdict→report→derived proposal→ingestion→exact retrieval **fixture**, independent of unfinished MC workflows. |
| W3: Biotech complete service path | BKS schema/contracts/kg-ops; KS K06 | Versioned SDL, Activity origin, report body/ledger custody, verification binding, sealed decision emitter, outbox/delivery/ack/current eligibility | Same fixtures as W2 over Neo4j; T1 transaction, duplicate/lost reply/revocation races; two report kinds round-trip | Same semantics across stores; no separate graph verification engine or provisional report shape. |
| W4: current MC integration | MC M01..M06; KS K01/K07; BKS | KnowledgeGateway/tools, operation journals, exact handles, minimal submit_output adapter, independent assessment handoff, exact read/export, human task adapter | T0 both program families' admission/context adapters; T1 existing Temporal+Postgres dispatch/reconcile/review; standalone/MC envelope parity | Leaves stable ports for advanced output/transfer instead of coupling service release to that entire feature set. |
| W5: release and clean cutover | All four owners | Pinned compatible component/schema/client set; remove obsolete writers/models; fixture manifest, operator runbooks, reproducible install/reset | T0 checks plus T1 fresh install/cutover interruption; both domain paths passed; explicit unsupported surfaces; no real-work gate opening | Prevents mixed schemas/writers and false operational readiness. |
| W6: downstream qualification gate | MC output/context and provider program; KS consumers | Final OC interview on the new baseline, full output/context implementation, all workflow/provider proof matrix | All required workflow/transfer/control proofs and Deep Agents C01..C16 qualified; owner release review; only then real-work gate opens | Avoids building real research corpora or retrieval experiments on immature workflow semantics. |

Edges: W0→W1→W2→W3→W4→W5→W6. MC adapter scaffolding and fixture authoring may begin after W1;
integration acceptance remains W4 after both service bindings. W6 is downstream scope, made explicit
here as a release prerequisite for real work; it is not falsely marked delivered by this sprint.

## 3. Migration and version authority

Names below are exact **reservations**, not files already built or evidence of schema-owner acceptance
of their contents. Allocate final numbers from live HEAD at the schema cell's claim; update this table
if another session consumes a reservation. Never edit an already-published release in place.

| Work / wave | Owner and proposed artifact | Purpose and proof |
| --- | --- | --- |
| A0 / W0 | AIDB target-schema inventory; MC common release inventory | Eleven untracked AIDB migrations and stale generated head are input evidence. Full reset permits deriving a clean target release rather than first publishing the obsolete tarball. Identify retained domain schema, removed verification ownership, package pins and generated types. |
| A/C-common / W1 | KS `packages/knowledge-db-contract/component/migrations/0001_verification_foundation.sql` | One explicit owner for tenant/origin/effect/run/task/assertion/occurrence/support records and privileges. New package initially authored under a documented ownership transition; no two active migration runners own these objects. |
| A/C-common / W1 | `0002_observations_reports_and_custody.sql` in that component | Append-only observations, report revisions/body/ledger refs, manifest heads, family-seal references and mandatory report/run associations. |
| A/C-common / W1–W2 | `0003_admission_revocation_and_outbox.sql` in that component | Exact-use decisions/review, dependency graph, revocation epoch, effect receipts and dispatch outbox; concurrent transaction proofs. |
| A1/A2/A5 / W1 | AIDB `supabase/migrations/20261024010000_knowledge_component_binding.sql` | Application-specific bindings to common component, explicit tenant-aware submit_intent/grants and canonical effect transaction; no copied common table DDL. Includes PUBLIC privilege review. |
| A3/A4 / W2 | AIDB `20261024010100_research_report_v2_projection.sql` | PostgreSQL domain report/assertion/ingestion projections, exact package read, sealed run foreign binding; use guards execute in native transaction. |
| D0 / W0 | MC package release-source reconciliation | Root component says 1.4.0 while release 1.4.4 has later migrations. Select a complete target source; either preserve published SQL as immutable input or make a deliberately breaking fresh-install component. Never accidentally omit required tables. |
| D / W4 | MC `0050_knowledge_operations.sql`, `0051_content_lineage.sql`, `0052_source_bindings_retained_observations.sql`, `0053_submissions.sql`, `0054_transfer_plans_delivery_receipts.sql` | Existing SP-10 reservations. Author only needed minimal current-runtime records; advanced transfer fields can be added by the later OC release. Correct component semver is selected from actual compatibility, not assumed 1.4.5. |
| B1..B5 / W0,W3 | BKS `schema/source/biotech-schema-v2.1.0/`; generated next release and pin | BKS becomes current schema owner (SV-D10). Initialize from verified versioned SDL modules and registers; modify source then generate/validate/pin. 2.1.0 is the proposed path/version; an incompatible schema requires an explicit major version instead. No invented SQL filename for graph SDL. |
| V07/V08 / W3 | Same BKS source: verification binding, Report/Assessment/Activity fields, generated DDL/rules/query sources | Review exact intended graph effect, selector and snapshot identities; reference the common operational run manifest; native marker and graph writes atomic; current eligibility check mandatory. |

Old A1/A2/A4 tables in SP-10 are **ownership intent**, not duplicate migration instructions: shared
operational records move to the common component; AIDB keeps domain projection/transaction integration.
This is the SV-D8 full-refactor amendment. Both app-local PostgreSQL installations consume one released
component, with domain-specific stores behind K03. Biotech's canonical domain model remains Neo4j SDL.

SV-03 must also remove old shared-object DDL from the active AIDB install path or replace that path with an isolated clean baseline. Deliver one root installer per app that pins and installs the common component before domain bindings, one generated-type producer with consumer pins, and withdrawal of old migration runners/default startup paths. Prove fresh installs in both app-local databases. Inventory can run early; SQL implementation waits for SV-04 record semantics. SV-17 records these exact installer/type/ownership artifacts.

Install order: target common component → app/domain schema bindings → custody/grants → matching
service builds → compatible MC client/runtime → reset fixtures → qualification → release manifest.
Rollback during development is rebuild from the last proven target release and rerun fixtures; no
promise to preserve disposable old histories. Exercise interrupted install and idempotent repeat.

## 4. How to test before full Mission Control maturity

| Tier | Runs now or after implementation | Establishes | Does not establish |
| --- | --- | --- | --- |
| T0 | Pure core, recorded provider responses, protocol ports, mocked clocks and deterministic failure injection | Contracts, support algebra, census mechanics, retries, budgets, sealing and fail-closed behavior | Model quality, database atomicity, deployed runtime |
| T1-KS | Direct KS application/HTTP/MCP calls with disposable PostgreSQL/storage, then Neo4j | Real persistence, tenant boundaries, native receipts, custody, exact read, review/invalidation races; both bindings | MC orchestration or scientific quality |
| T1-MC | Existing MC runtime with local Temporal/Postgres; bounded scripted producer/consumer via real gateway | Live origin, dispatch/reconcile/cancel, review bridge and receipt delivery in current workflows | Unimplemented advanced output/context features or full provider qualification |
| T2-control | Locked evidence-report/study-appraisal fixture corpus with direct metered model calls | Actual provider adapters, independent producer/judge identities, retained responses, hold behavior, latency/cost | Calibrated error bounds, useful real-world research, full-workflow readiness |
| Q | Preregistered independent human-labeled held-out and shifted cases, per use/domain/media/risk | Only the measured evaluator slices and uncertainty bounds | Universal correctness or automatic clinical authority |
| Operational | After W6 real-work gate | Actual research/ingestion/retrieval experiments under fully qualified workflows | Nothing inferred from an earlier fixture alone |

First T2 harness must replace the existing model-card experiment's same-model producer/judge and live
inputs. Discover available provider routes without disclosing credentials; configure pinned producer,
judge and second-family judge identities. Chat subagent model availability does not establish an API
route. Do not silently substitute a model or claim independence from vendor names alone.

Standing spend limit remains **USD 15 per session**, inclusive of retries and all direct provider test
calls. Do not adopt the old instrument's USD 25/run suggestion or automatically commission the USD 300 /
60-hour pilot. Reserve before each request; stop before the remaining ceiling could be exceeded. Record
actual or explicitly estimated billed usage; budget exhaustion holds required checks. Recommended
initial split: ≤3 smoke/discovery, ≤8 paired fixture slice, ≤4 challenges/retries, all within 15.

Qualification measures frozen obligation coverage, census recall against independently reviewed labels,
support precision/error and abstention, eligible-use errors, correction closure precision/recall, source
origin clustering errors, latency, full model/repair/reviewer cost. Human and synthetic labels are
separate. Keep `calibrated` and quality-validation flags false until admitted proof exists. Old 98%/2%/90%
targets remain initial noncritical-engineering promotion targets, not first-release achievements.

## 5. V-issue scope and provenance

Existing IDs are from the local published tracker map; refresh tracker before claiming. No issue is
marked complete or newly filed by this plan. Avoid duplicate V issues; new work items below name the
missing integration/migration deliverable and link their V dependencies.

| Slice | Sprint disposition | Provenance |
| --- | --- | --- |
| V01 / OVE-91 | Full record graph and support-set algebra | OC-D95..98; SV-D3/D8; K01/K02 |
| V02 / OVE-93 | Full independent final census and frozen obligations | OC-D91/D96; SV-D3/D9; E03/E04 |
| V03 / OVE-94 | Full rule router and scientific/engineering profile registry | SV-D3/D9; amendment A5 |
| V04 / OVE-95 | Full common-component refactor and two app-local consumers | SV-D8; E08/E10; no preservation-driven extraction delay |
| V05 / OVE-99 | Authority/origin grouping, bounded challenge and on-demand revision frontier | SV-D3; amendments A2/A4; no live feed required |
| V06 / OVE-100 | Full AI exact-effect admission, review and current-use checks | OC-D91/D95; SV-D6/D9 |
| V07 | Full Biotech verification binding after concrete SDL/kernel contract | SV-D6/D10; Q01 scope resolved through this source-based sprint contract, not inferred historical status |
| V08 | Full cross-store outbox/ack/current eligibility | SV-D6; no distributed transaction claims |
| V09 | Label import, profile schema, honest flags and slice definitions | SV-D3/D9; empirical commissioning remains separate |
| V10/V11 | Exact immutable artifact reuse may be used; semantic cache and semantic batching deferred | Correctness and service refactor first; reuse always rechecks current use authority |
| V12 | Required correction/revocation dependency closure now; advanced refresh optimization later | SV-D3; known corrected evidence must cease authorizing effects |
| V13 | Harness, preregistered analysis format and fixture economics; no automatic empirical qualification | SV-D7/D12; real retrieval experiments remain behind W6 |
| V14 | Parity/capability negotiation for shipped KS/MC/BKS surfaces now; broad consumer rollout later | SV-D6/D7; version breaking changes allowed by SV-D8 |
| V15 | Deferred media/attribution extensions | Separate commission and modality qualification |

Adopt proposal amendments A1..A5 as engineering defaults: complete method provenance, explicit
counterevidence frontier, frozen task obligations, proposed versus verified origin families, pinned
authority/rubric registries. These refine implementation without inventing empirical qualification.

## 6. Complete local work-item map

Each row is a fileable work item. Existing V issues keep their identity; integration cells get new OVE
IDs only at implementation kickoff, with `## Provenance` containing this row and its listed decisions.
The machine-readable DAG and claim states are in [WORK-ITEMS.json](../sprint-v/WORK-ITEMS.json).

| ID | Owner / modules | Deliverable and acceptance | Depends on | Provenance |
| --- | --- | --- | --- | --- |
| SV-01 | MC M01/M06 | Live invocation origin in both program families and local/hosted lane tests | None | E01; OC-D79; SV-D3 |
| SV-02 | KS K01 | Protocol/schema fixtures; frozen effect/current caller; auth/refusal/capability contract | None | OC-D84/85/88; E12; design §5 |
| SV-03 | KS+AIDB K09 | Owned-object inventory, clean common component + two disposable installs | SV-02,SV-04 | V01/V04; SV-D8 |
| SV-04 | KS K02/K03 | Pure records, support algebra, strict profiles and port contracts | SV-02 | V01/V03; OC-D95..98 |
| SV-05 | KS K04/K05 | One run/sealer/oracle; custody and durable concurrency proof; remove old truth paths | SV-03,SV-04 | E02/E03; OC-D95; SV-D8 |
| SV-06 | KS K02/K04/K08 | Report v2, two kinds, independent census and post-observation aggregation | SV-04,SV-05 | V02; OC-D96; SV-D9 |
| SV-07 | KS K04/K08 | Origin grouping, source fitness, scientific appraisal and bounded challenge | SV-04,SV-05 | V03/V05; A1..A5; SV-D3/D9 |
| SV-08 | AIDB+KS K05 | Report derive, tenant-aware plan/apply/receipt, exact-use human review and invalidation | SV-03,SV-06,SV-07 | V06/V12; OC-D85/88/91; SV-D8 |
| SV-09 | Integration | Direct AI Engineer fixture for both report kinds; locked T2 harness | SV-08 | SV-D6/D7/D12; V09/V13 scaffolding |
| SV-10 | BKS schema owner | Current authoring tree, exact kernel/report/evidence SDL version and generated release | SV-02,SV-04 | SV-D6/D10; Q01; B1..B5 |
| SV-11 | BKS+KS K06 | Native graph binding, custody, verification emitter, outbox and current eligibility | SV-08,SV-09,SV-10 | V07/V08; OC-D97; SV-D6 |
| SV-12 | Integration | Biotech counterpart fixtures immediately after AI proof; cross-store faults | SV-09,SV-11 | SV-D6/D7/D12; V08 |
| SV-13 | MC DB M05 | Complete common release source and journals/lineage/submission schemas | SV-02 | D0/D; E10; OC-D102 |
| SV-14 | MC M02/M06 + KS K07 | Authenticated gateway/tools/reconcile and credential conformance | SV-01,SV-05,SV-13 | OC-D79/84/85/88; E12 |
| SV-15 | MC M03/M04 | Minimal submission, assessment/review bridge, exact read/export and delivery seam | SV-06,SV-14 | OC-D83/89..94/99; SV-D7 |
| SV-16 | Integration | Current MC runtime proofs against both bindings, required surface parity | SV-12,SV-15 | V14; SV-D6/D7 |
| SV-17 | All owners | Clean release/cutover bundle, remove obsolete code, docs and receipts | SV-16 | SV-D4/D8/D12; no real-work opening |
| SV-18 | MC downstream program | All four workflows + output contracts/context transfer + complete Deep Agents gate | SV-17 | SV-D12; OC program/C01..C16; operational use remains locked |

## 7. Explicit exclusions and acceptance

No preserved test-data history or backwards-compatible legacy runtime; no live retraction feed,
unqualified semantic cache/batching, embeddings/retrieval-profile promotion, new physical topology,
new subagent tool semantics, or unvalidated automatic scientific admission. The remaining eight report
kinds get extension contracts, not a claim of complete authoring/validation workflows.

Deep Agents full qualification and advanced output/context are **not omitted**: they are the explicit
W6 downstream gate. Real research and retrieval experiments cannot be reclassified as engineering tests
to bypass it. Sprint V's first fixture proves the new service pipeline and its ports, using disposable
data. The owner accepted these boundaries and engineering defaults on 2026-10-24 (SV-D13). That
acceptance does not mark implementation or evaluator calibration complete.
