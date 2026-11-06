---
type: Implementation Evidence
title: "IQ-07 as-built briefing: the Sprint V baseline the final output-contract/context-transfer interview reads"
description: "Projected versus actual modules, common and domain tables and graph fields, SP-10 assumptions S1..S6, identity joins, what submission coverage means, remaining obligation/transfer records, schema changes the runtime sprint still needs, one disposable trace per application, and verified release facts. Prepared 2026-10-25 at the end of the Sprint V continuation session; evidence, not deployment."
tags: [mission-control, knowledge-services, sprint-v, iq-07, briefing, as-built]
date: 2026-10-25
status: active
---

# IQ-07 as-built briefing

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../sessions/KICKOFF.md); no new interview or runtime completion is implied.


**Repair delta:** [READINESS-REPAIRS-2026-10-25.md](READINESS-REPAIRS-2026-10-25.md) records the
subsequent local RV-02 restriction and RV-05 aggregate file-byte preflight. Read it with the review;
collection aggregation, unified prompt planning and the other runtime prerequisites remain open.

**Readiness correction, independent review 2026-10-25:** read
[ADVERSARIAL-READINESS-2026-10-25.md](ADVERSARIAL-READINESS-2026-10-25.md) before the historical gate
table below. IQ-07 may discuss and decide the remaining design, but the normal end-to-end agent path
is not qualified. RV-01..06 and RV-08 identify ignored blocked finalization, incomplete collection assessment,
run-wide delivery, missing trusted decision/verification composition, aggregate budget gaps and the
native-commit/protocol-receipt recovery window, and operational reads being confused with native
official-use reads. These are not waivers or new owner decisions.

Read with [NEXT-SESSION.md section 2](NEXT-SESSION.md#2-what-is-proven-and-what-is-not) (what is proven and what is not),
[PROOFS.md](PROOFS.md) (the 2026-10-25 continuation entry: every count and command), [WORK-ITEMS.json](WORK-ITEMS.json)
(state per item) and [SPRINT-V-DESIGN.md section 10](../specs/SPRINT-V-DESIGN.md#10-alternatives-pending-choices-and-conformance)
(conformance and the OQ decisions). Source and release facts below were observed in this session on disposable
installations; none is a deployed-version claim. The real-work gate (SV-D12) stays closed.

## 1. Prior gate assessment (2026-10-25 continuation; qualified by the review above)

| Gate (the 2026-10-25 entry gate) | Status | Evidence |
| --- | --- | --- |
| SV-01..17 have reviewed evidence | **Met with recorded deviations.** All seventeen items are `complete` in WORK-ITEMS.json after second reviews R1 (KS/AIDB/BKS), R2-MC and R3 (KS protocol, cutover, MC re-verification); the fixes the reviews required were applied and re-proven by the implementing helpers but not independently re-reviewed | PROOFS.md continuation entry; reviewer rows per item |
| Both applications: service and native-store proofs | **Met.** AI Engineer: SV-08 (AIDB install, projection, guard, atomic admission) and SV-09 (T0 + paid control slice). Biotech: SV-11/12 (real BKS executor + Neo4j, 9/11 cases; lost-ack-after-commit and native rollback in-process only) | PROOFS checkpoints B, C, D |
| Real MC transport and tool path demonstrated | **Met.** StageGraph and GoalDirected through local Temporal/PostgreSQL 1.6.0 against the real KS executor (K07 credentials, retry with a recovery grant, cancel, receipt attribution, fresh dispatch ids); Biotech apply through the toolset harness | PROOFS checkpoint E rounds 2-5 |
| M03/M04 seam demonstrated | **Met with limits.** Submission -> independent `report.assess` -> `assessed` basis; exact delivery gates the dependent invocation (tampered bytes block it). Limits: not DAG-scoped, knowledge-tool invocations only, linked missions excluded, in-process decision store, stop-during-review proven with a test-double gate | `test_report_package_extension.py`, acceptance runtime test |
| Reproducible cutover bundle without competing authority | **Met.** Fresh, repeated and interrupted installs of both applications from the bundle on 2.4.0/1.6.0/v2.2.0; 350 legacy KS files removed; no second writer or oracle; pins verified against the files; real-work gate CLOSED | `release/RELEASE-BUNDLE.md`, R3 |

The interview may open on the explicitly limited baseline in the independent review. Nothing above
is a deployed-version claim. `deployments/*` locks remain unchanged; target files do not independently
prove live installed versions. The reviewed baseline is committed: MC `fa1f778a`, KS `b45adf5`, AIDB
`306efd7`, BKS `c398177`; all four were clean at the review's entry.

## 2. Projected versus actual modules

| Design id | Projected (design section 2.1) | Actual | Note |
| --- | --- | --- | --- |
| K01 | `packages/knowledge-operation-protocol/src/{origin,effect,envelope,handle,operation,receipt,capability,errors}.ts` + schemas/fixtures | as projected, plus `canonical.ts`, `credential.ts`, `golden.ts`, `primitives.ts`, `schemas.ts`; `ks.knowledge_operation.v2` amended in-session with the effect-scoped recovery grant, `RECEIPT_OPERATIONS` (`knowledge.apply` returns a receipt), receipt outcome `pending_dispatch` and an optional `delivery` block on receipt lookups; 15 schema/fixture files mirrored byte-for-byte in MC `tests/fixtures/knowledge_protocol/` | MC Python models are strict (TS rules enforced, negative conformance tests) |
| K02/K03 | `research-core/src/{task,assertion,occurrence,evidence,support,observation,authority}.ts`, `report/{revision,render,ledger,census,derive}.ts`, `verification/{run,manifest,seal,aggregate,use-decision,invalidation}.ts`, `ports/*` | `records/*` (task, assertion, occurrence, fragment, support, observation, report, run, decision, mapping), `report/{render,ledger,census,derive,kinds}.ts`, `support/algebra.ts`, `verification/{run,manifest,seal,aggregate,use-decision,invalidation}.ts`, `profiles/*`, `ports/*`, `./testing` export | records carry no self ref (`recordRef` derives it); occurrences bind the frozen body artifact |
| K04 | `application/src/research/{operations,coordinator,review,report-derive}.ts` | `coordinator.ts`, `assessment.ts` (async `report.assess`), `authority-challenge.ts`, `review.ts`, `ports.ts`, `in-memory.ts`, `fixtures.ts` (+ `./testing` export) | derive is exposed by the executor over research-core `derive.ts` |
| K05 | `bindings/aiengineer-postgres/src/{stores,oracle,admission,installer}.ts` | `stores.ts`, `research-binding.ts`, `operations.ts`, `client.ts`; admission lives in `knowledge-db/src/ingestion/exact-use-admission.ts` (single path, also used by the executor's native transaction) | installer is the component's own CLI (`knowledge-db install`) |
| K06 | `bindings/biotech-graph/src/{client,read,report,admission,delivery}.ts` | `@aiengineer/knowledge-binding-biotech-graph`: BKS executor client, admission (one PostgreSQL transaction: `admit_exact_use` + inline payload custody + `enqueue_dispatch`), delivery (receipt `applied` only after a verified acknowledgment), official reads (v3 `officialUse`), descriptor, stub consumer | no Neo4j driver in KS |
| K07 | KS host auth | `packages/host/src/knowledge-operation/{auth,config,backends,service}.ts`; executor `knowledge-operation/*` HTTP/MCP transport; component `credential_use` makes credentials single-use across restarts | retired verification chain is removed; retained capture/artifact surfaces are separate |
| K08 | `catalog/research/{report-kinds,rubrics,source-authority}/` | `catalog/research/report-kinds/{evidence_report,study_appraisal}.json` (with framing sections), `catalog/research/source-authority/*.json`, `catalog/research/use-classes.json` (which use/audience strings are official/critical; official use requires an exact-use binding), `catalog/research/fixtures/` (SV-09 locked corpus) | rubric profiles remain code (`profiles/*`): recorded deviation |
| K09 | `packages/knowledge-db-contract/{component/migrations,types,installer}/` | component `knowledge_verification` 0001..0007, version **2.4.0**, installer + CLI | see section 3 |
| M01 | `domain/knowledge/{origin,handles,effects,lineage}.py` | as projected | `mint_effect_key` now includes the run (defect fixed in-session) |
| M02 | `application/knowledge/{gateway,toolset,access,operations}.py` | all four exist; lane-neutral toolset projected by `adapters/deep_agents/knowledge_tools.py` | router rule: tools projected through the existing materializer path; `verify_claims` advertised by the toolset but unsupported by KS |
| M03 | `application/outputs/{submission_service,acceptance}.py` | `submission_service.py` with states pending -> assessing -> assessed/held/rejected and `outcome_basis`; no `acceptance.py` (five-guarantee assessment is downstream) | |
| M04 | `application/context/{source_bindings,resolution,representation,delivery}.py` | `ContentResolutionService`, `ReportRepresentation`, `DeliveryPlanner` in those three files; source bindings use the 1.5.0 `0052` tables | exact read, three files, one repair then block; selection/budget/packet-integration limits in RV-03/05 |
| M05 | `adapters/postgres/knowledge/{operations,lineage,bindings,observations,submissions,transfers}.py` | `operations.py`, `submissions.py` (+ handles/delivery in the same modules over release 1.6.0) | fewer files, same seams |
| M06 | `adapters/deep_agents/knowledge_tools.py`, `bootstrap/composition.py` | `knowledge_tools.py`; `bootstrap/composition.py::compose_knowledge_lane`; `adapters/knowledge/{http_client,credentials}.py` | |
| BKS | `packages/contracts/src/{intent-v2,admission,read-v2}.ts`, `kg-ops/src/admission/{custody,verification,eligibility}.ts` | `contracts/src/admission.ts` (`biotech-knowledge-admission.v1` + ack + consume), read v3 with eligibility; `kg-ops/src/admission/{dispatch,verification,...}.ts`, `POST /kg/admission/dispatch/consume`, `bks admission consume --once` | SDL release `biotech-schema-v2.2.0` pinned |
| AIDB | `supabase/migrations/` clean baseline/bindings; `scripts/` installer; `src/database.generated.ts` | `20261024010000..10200` binding/projection/guard, then `20261025010000` withdrawal, `20261025010100` forced RLS, `20261025010200` required normalized values; generated types; installer per SV-17 | contract 0.5.0 |

## 3. Tables, graph fields and releases (as installed on disposable targets)

| Authority | Release | Objects added in Sprint V |
| --- | --- | --- |
| KS component `knowledge_verification` | 2.0.0 -> **2.4.0** | 0001 origin/effect/task/run/assertion/fragment/support_set; 0002 custody/report_revision/occurrence/observation/run_manifest + `seal_run`; 0003 reviewer_grant/adjudication/revocation_epoch/dependency_edge/invalidation/use_decision/`admit_exact_use`/effect_receipt/dispatch_outbox; 0004 `operation` (+CAS transitions), report kind columns, `report_assessment`, occurrence key per revision; 0005 nullable qualifiers digest, normalized values + digest, subject/scope checks, invalidated = rejected, signature columns + signing key table, `enqueue_dispatch`/`settle_dispatch`/`claim_dispatches(target_binding)`/stored ack/`check_use_eligibility`; 0006 `credential_use`, `protocol_receipt`; 0007 mandatory normalized-values digest (`NORMALIZED_VALUES_REQUIRED`), server-clock credential functions |
| MC common | 1.5.0 -> **1.6.0** (built, locks unchanged) | 0050 knowledge operation journal; 0051 content lineage; 0052 source bindings/retained reads; 0053 submissions/finalization; 0054 transfer plans/delivery receipts/outbox; 0055 durable operation handles (states incl. waiting_review/cancelling/cancelled, `cancel_request_id`), assessment columns on submissions, `outcome_basis`, delivery receipt `attempt` + outcome code + readiness guard |
| AIDB domain | migrations through `20261025010200` | binding pin table; `research` projection tables, admission record, exact package read, receipt decision columns, commit-time `ADMISSION_REQUIRED`, SQLSTATE KSA01..07; legacy withdrawal, forced RLS and required normalized-values guard |
| BKS SDL | v2.1.0 -> **v2.2.0** | `ReportKind.STUDY_APPRAISAL`, `useDecisionDigest` on Activity/Assessment, marker lookup indexes; `KsIntentMarker` (operational) carries dispatch id, bound effect digest, decision ref, revocation epoch, BKS marker digest |

New 1.6.0 target locks are under `sprint-v/release/locks/{ai-engineer,biotech}/release.lock.json`.
The files under `deployments/{ai-engineer,biotech}` were not replaced. See `release/RELEASE-BUNDLE.md`;
neither set of files is fresh live-deployment evidence.

## 4. SP-10 assumptions S1..S6

| Assumption | Disposition | Evidence |
| --- | --- | --- |
| S1 per-invocation JWT with the origin as a claim acceptable to both executors | **Partly broken, as predicted.** KS accepts it (K07 with the MC issuer JWKS). BKS keeps its opaque-token principal model and adds a `service` principal class with grant `admission.dispatch` for the KS binding caller; the MC issuer profile does not reach BKS directly | E-KS conformance; D1 executor auth |
| S2 Biotech content-addressed report uid is the exact revision for `report` handles | **Confirmed with a stronger rule:** official reads recheck the frozen revision's kind and body/ledger digests and current eligibility; a stale projection cannot authorize use | D2 official reads; SV-12 revoked case |
| S3 one `ReportPackageExtension` over both bindings with `research-report.v2` | **Common exact-package seam exists; native-read equivalence unproven.** K01 `knowledge.read` loads common operational report/custody records for both bindings; it does not call BKS official read v3. Native projection, ingestion and current eligibility require their own evidence | KS host `service.ts::read`; Biotech `research-binding.ts`; RV-08 |
| S4 readability probe on every byte-capable backend | **Partial.** Delivery verifies staged bytes and the lane seeds them; the seam unit tests do not qualify every backend's actual model-tool permissions/readability. Full selected-backend qualification remains required | `test_report_package_extension.py`; RV-05 |
| S5 `submission` and `obligation_fulfillment` in one release | **Open for FC-Q1.** Sprint V built `output_submission` + `invocation_finalization.outcome_basis` (1.6.0); no `obligation_fulfillment` table | E-MC release 1.6.0 |
| S6 common tables fit without per-application variation | **Confirmed:** 0050..0055 carry binding ids as data; no application-specific column | release 1.6.0 tests |

## 5. How the identities join

`origin` (MC `mc.invocation_origin.v1`, mapped once to K01 `Origin` in `application/knowledge/access.py`) -> journal row
(`knowledge_operation_journal`, K01 bound-effect digest) -> credential (`jti`, dispatch id, effect key, bound digest; single-use in
component `credential_use`) -> KS `effect` row (`bind_effect`) -> `operation` row (async handles; MC mirrors it in the 1.6.0 handle
table) -> `protocol_receipt` / `effect_receipt` (K01 receipt by effect key; Biotech adds the outbox acknowledgment as the `delivery`
block of a receipt lookup) -> MC settlement (`applied` / `pending_dispatch` unresolved until delivery) -> submission
(`output_submission`, tool-call key) -> assessment operation handle -> finalization (`outcome_basis`) -> transfer plan and
delivery receipts (`0054`, attempt + outcome code) -> next invocation's packet. Frames: the Deep Agents binding carries no mission or
activation id, so mission id = run id and activation id = UUIDv5(run, operation) (recorded deviation; a frame-level fix is a runtime
sprint item).

## 6. What submission coverage means now

An invocation finalization has an explicit `outcome_basis`: `submission_coverage` counts submitted
obligations; `assessed` means every obligation summary has a terminal assessment. Held/rejected
summaries do not count as fulfilled. Empty declared obligations fall back to the submitted set.
Opening source recheck on MC `1863017c` (2026-10-25): RV-02's first-report-only assessment is now
bounded by refusing multi-report, duplicate-report and mixed report selections before storage and
again during finalization (`submission_service.py:477`). This does not implement collection assessment.
RV-05 also now preflights aggregate file bytes (`toolset.py:392`); unified prompt accounting remains open.
The five-guarantee assessment,
accumulation across cycles and transfer profiles are
not built. The ordinary seam is submission -> assessment handle -> terminal assessment. Actual use
review is a separate decision/adjudication path; stop-during-review used a test-double gate. RV-01/02/04
explain why this cannot yet certify full fulfillment, collection assessment or native admission.

## 7. Remaining obligation/transfer records and schema changes the runtime sprint still needs

- `obligation_fulfillment` (one row per obligation per unit result) and the release rule for incremental consumers (FC-Q1, FC-Q7).
- Assessment records per guarantee with reuse keys (subject digest + policy pin + freshness) (FC-Q9).
- Transfer profile v1 fields (`boundary`, `readiness`, inline/file per consumer) and `report-review@v1` (FC-Q6); `context_transfer_plan`
  carries only the minimal M04 fields today.
- Frame joinability for handles/receipts and the four public events (FC-Q11); a mission/activation id on the Deep Agents binding.
- The use-class registry already exists at KS `catalog/research/use-classes.json`. General review-rule
  policy data and the trusted runtime review/decision route remain open (OQ4, RV-04).
- Component: an apply protocol receipt written inside the native transaction (today right after commit); report-level reuse of identical
  evidence records across reports is idempotent by digest (fixed in-session), but cross-report evidence sharing policy is open.
- Owner policy question parked for before the SV-18 gate: may `recommendation` assertions ever be admitted for official consumer use,
  and under which reviewer authority (OQ4).

Reserve the next versions from live HEAD at the runtime sprint's claim: MC common 1.7.0 (next migration 0056), KS component 2.5.0 (0008),
BKS SDL v2.3.0, AIDB next timestamp after `20261025010200`. These are candidates to recheck, not
version reservations made by this review. The old 1.4.5/1.4.6 placeholders are obsolete.

## 8. One disposable trace per application

| Application | Trace | Where |
| --- | --- | --- |
| AI Engineer | SV-09 harness run `t0-final4` (deterministic) and `paid-2` (routes `gpt-6-sol` producer, `gpt-6-luna` judge, `claude-sonnet-5-5` second family + auditor; USD 0.15): freeze task -> fragments -> producer draft -> `report.register` -> judge/second-family observations -> auditor census -> authority/challenge (recorded fakes) -> signed seal -> derive -> report and assertion decisions -> native admission + effect receipt -> exact package read; MC side: `test_knowledge_gateway_runtime.py` StageGraph and GoalDirected runs with `report_register` + `submit_output` -> `report.assess` -> finalization `assessed` -> exact delivery into the next invocation's packet | KS `.scratch/sprint-v/proofs/SV-09/`, MC `.scratch/sprint-v/proofs/SV-16/` |
| Biotech | SV-12 harness `attempt-124237`: register -> audit -> seal -> decide -> `admit_exact_use` + `enqueue_dispatch` (receipt `pending_dispatch`) -> BKS `consume` (effect + `KsIntentMarker` in one Neo4j transaction) -> `acknowledge_dispatch` with the component's expected digest -> receipt `applied` -> official v3 read shows eligible; revoked-in-transit, duplicate, reordered, lost consume response and graph-unavailable cases in the same run | KS `.scratch/sprint-v/proofs/SV-12/run-bks/attempt-124237/` |

## 9. Verified release facts for the interview

| Fact | Value |
| --- | --- |
| KS component | `knowledge_verification` 2.4.0 (0001..0007); the 2.4.0 installer receipt digest is in `release/release-bundle.json` (2.3.0 was `sha256:06951864...`) |
| MC common release | 1.6.0 built; final schema fingerprint `sha256:7eddd43091ffce59c0e719e7705097d6f5d4bd635e632ca1cab366bddcfeadcf`; review rechecked bundle lock and manifest bytes |
| BKS SDL | `biotech-schema-v2.2.0` (schemaReleaseDigest `sha256:2df9d3bc...25a74`, schemaDigest `sha256:de8ab942...6576`) |
| AIDB head migration | `20261025010200_research_admission_values_required.sql` |
| K01 | `ks.knowledge_operation.v2` with the 2026-10-25 amendments; golden vectors identical in KS and MC |
| Paid proof spend | USD 0.15 (SV-09) of the USD 15 session ceiling |
