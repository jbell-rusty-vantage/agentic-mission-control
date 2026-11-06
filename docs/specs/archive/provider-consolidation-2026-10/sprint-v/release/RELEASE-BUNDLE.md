---
type: Implementation Evidence
title: "Sprint V release bundle (SV-17): component, schema and client pins, target locks, installers and the supported-capability matrix"
description: "The reproducible cutover bundle for the AI Engineer and Biotech applications: knowledge_verification 2.4.0, Mission Control common 1.6.0 with new per-app target locks, BKS biotech-schema-v2.2.0, AIDB contract 0.5.0 head 20261025010200 (186 migrations), K01 2.0.0; generated-type owners and consumer pins; grants and custody; the two root installers with their receipts; and an honest capability matrix. Part 1 (F1) and part 2 (F2: KS retirements, fresh-install-from-bundle domain proofs, final capability matrix in section 7), 2026-10-25. Disposable evidence only; the real-work gate is CLOSED."
tags: [mission-control, knowledge-services, sprint-v, sv-17, release, cutover, bundle]
date: 2026-10-25
status: active
---

# Sprint V release bundle (SV-17)

Machine-readable twin: [release-bundle.json](release-bundle.json). Target locks: [locks/ai-engineer](locks/ai-engineer/release.lock.json),
[locks/biotech](locks/biotech/release.lock.json).

**Real-work gate: CLOSED.** Every fact below was observed on disposable targets (a disposable Supabase workdir, databases on the
loopback `sprint-v-pg17` server, the BKS `neo4j-test` container). No live database, Aura graph or Fly service was read or changed.
The new lock files are target-file facts: `deployments/<app>/release.lock.json` still describe the live installations (ai-engineer
1.4.2, biotech 1.3.0) until an approved cutover replaces them.

Status: **part 1** (SV-17 helper F1) and **part 2** (helper F2, sections 6 and 7: Knowledge Services retirements, KS pins,
fresh-install-from-bundle proofs of both domain paths and the final capability matrix).

## 1. Pins and digests

| Unit | Owner | Pin | Digest |
| --- | --- | --- | --- |
| `knowledge_verification` component | KS `packages/knowledge-db-contract` | **2.4.0** (migrations 0001..0007; 0007 = required normalized-values digest, server-clock credentials) | component `sha256:309a8c9b8ac792a9f9cf1d6b9ff1070bba763f6c7113750847680d4c9c5c64c7` (was 2.3.0 `sha256:06951864…53b5`) |
| Mission Control common component | MC `packages/mission-control-db-contract/releases/1.6.0/component` | **1.6.0** (0001..0055; rebuilt in place 16:07 after a 0055 edit, unapplied) | manifest `sha256:f8799abe…29d3`, schema fingerprint `sha256:7eddd430…adcf`, contract `sha256:82797cf5…ca4b` |
| Biotech graph schema | BKS `schema/source/biotech-schema-v2.2.0` (SV-D10) | **biotech-schema-v2.2.0** (pinned 2026-10-25) | release `sha256:2df9d3bc…5a74`, SDL `sha256:de8ab942…6576`, DDL `sha256:f0622dba…ddb3` |
| AI Engineer domain schema | AIDB `supabase/migrations` | contract **0.5.0**, head **20261025010200** (186 migrations; Sprint V: 20261024010000/0100/0200, 20261025010000 withdrawal, 010100 forced RLS, 010200 values-required mapping) | head file `sha256:83085f4b…4849`; withdrawal `sha256:a28c9c1b…f236`; forced RLS `sha256:0da17798…8d8a` |
| K01 protocol | KS `packages/knowledge-operation-protocol` | **2.0.0** | golden `sha256:7bdeb2b120c256a64fcd9ecd0ae526aee266758a102de4e884098acda16cb19d` (re-recorded by F2 after E-KS rounds 3-4; part 1 recorded `sha256:9455c4e7…e5cb1`); MC copy 15/15 byte-identical |

Release source (plan row D0): the MC `releases/<version>/component/` directories are the only release authority. The root
`packages/mission-control-db-contract/component/` (its `release-spec.json` says 1.4.0) is retired frozen input kept for the
historical tests and preparers; it is never a build, lock or install source (package README, AGENTS.md and `releases/README.md`).

### Target locks (old -> new)

| App | Old lock (`deployments/<app>`) | New target lock (this bundle) |
| --- | --- | --- |
| ai-engineer | 1.4.2, lock digest `sha256:508d0415…d0bc`, file `sha256:df0d714e…9409` | 1.6.0, lock digest `sha256:03d5cc07…4564`, file `sha256:ce8f69d8…9dca` |
| biotech | 1.3.0, lock digest `sha256:baf54ed0…d314`, file `sha256:0562a6ed…1212` | 1.6.0, lock digest `sha256:582dbf27…bc49`, file `sha256:3677fa00…e222` |

Written with `mission-db lock --app <app> --component-root packages/mission-control-db-contract/releases/1.6.0/component
--deployments-root docs/specs/archive/provider-consolidation-2026-10/sprint-v/release/locks` (52 payload files each).

## 2. Generated types: owner and consumer pins

| Artifact | Owner | Consumer pin | State |
| --- | --- | --- | --- |
| AIDB `src/database.generated.ts` (`sha256:ecd1b06d…62b8`) | ai-engineer-db-contract | KS persistence, knowledge-db, verification-executor: `vendor/aiengineer-database-contract-0.5.0.tgz` (`sha256:c2f6c68b…8f7b`) | **current** (part 2); part 1 recorded the stale 0.4.16 pin |
| MC `releases/1.6.0/component/generated/contract.json` | mission-control-db-contract | MC runtime bindings pin an exact component version | built; deployment locks unchanged |
| K01 `schemas/*.json`, golden fixture | K01 | MC `tests/fixtures/knowledge_protocol` byte copy | identical |
| BKS GraphQL executable/registry | BKS | `packages/graphql-client`; KS `bindings/biotech-graph` mirrors contracts (no TS import) | `api:check` current |

## 3. Grants and custody

- AI Engineer: nine capability-role grants (`knowledge_verification_{reader,writer,reviewer,outbox_worker}` to app_reader,
  pipeline_agent, executor_service, verifier_agent, control_plane) are owned by `20261024010000`; the installer verifies them and
  never re-issues them. Binding pin `knowledge_service.verification_component_binding` = component 2.x with keys contained in the
  installed receipts. Custody `knowledge_verification.artifact_custody` has forced RLS and no anon/authenticated read. The native
  guard `research.assert_admitted_use` is executor_service only. `20261025010000` withdrew 22 legacy relations, one view and the
  drift functions; their grants went with them.
- Biotech: component installed for application `biotech`, binding `biotech-graph`; dispatch payloads are inline component
  `artifact_custody` rows (D2). MC runtime roles as in the 1.6.0 manifest. The graph carries the pinned `KsReleaseMarker` and writer
  DDL; BKS plan/receipt custody remains file-based under `BKS_RUNS_DIR`.

## 4. Installers and receipts

| App | Command (repository root) | Order |
| --- | --- | --- |
| AI Engineer | `node scripts/install-ai-engineer.mjs --workdir <disposable supabase workdir> --component-installation-id <uuid> --mc-installation-id <uuid>` (AIDB) | preflight (disposable identity, pins) -> component (KS CLI, version + digest) -> domain migrations -> custody/grants verify -> MC 1.6.0 `plan/apply/verify` -> receipt |
| Biotech | `node scripts/install-biotech.mjs --pg-admin-dsn-env <NAME> [--create-database] --neo4j-uri neo4j://localhost:7690 --neo4j-password-env <NAME> --component-installation-id <uuid> --mc-installation-id <uuid> --state-dir <dir>` (BKS) | preflight (pins, BKS release byte-verified) -> component (biotech) -> MC 1.6.0 (release extensions provisioned first) -> graph release check/install -> executor config by name -> receipt |

The Biotech recipe lives in BKS: that repository owns the Biotech domain schema (SV-D10) and executor configuration, mirroring
AIDB for AI Engineer; MC `deployments/` carries only app-neutral common-component manifests.

**Release path (integrator decision, 2026-10-25).** The two root installers are the only release and fresh-install paths. AIDB
`db:start`, `db:migrate` and `scripts/apply-disposable-migration.mjs` stay as disposable development tools, never a release, cutover
or startup path (stated in the AIDB README and AGENTS.md).

Both are idempotent and interrupt-safe (state lock with dead-owner takeover; every step re-observes and applies only what is
missing). Proofs:

| Proof (part 1, component 2.3.0; the 2.4.0 reruns are in section 6) | AI Engineer (`aiengineer/ai-engineer-db-contract/.scratch/sprint-v/proofs/SV-17/run-2/`) | Biotech (`biotech/biotech-knowledge-services/.scratch/sprint-v/proofs/SV-17/F1/biotech-run-3/`) |
| --- | --- | --- |
| Simulated crash after the component step (`--interrupt-after component`, SIGKILL) | exit 1, lock left behind | exit 1, lock left behind |
| External `taskkill /T /F` mid-step | killed at 70 of 184 migrations | killed during the graph DDL install |
| Rerun completes | `receipt-C.json`: resumed, migrations applied 114, MC applied 48 | `receipt-C.json`: resumed, graph release applied |
| Repeat applies nothing | `receipt-D.json`: `changed: false` | `receipt-D.json`: `changed: false` |
| Refusals | shared `aiengineer` workdir -> `DISPOSABLE_PROJECT_REQUIRED` | missing env name -> `EXECUTOR_CONFIG_MISSING`; Aura URI -> `DISPOSABLE_NEO4J_REQUIRED` |

Executor configuration names checked by the Biotech installer (values never printed): KS executor `KS_KNOWLEDGE_BINDINGS_JSON`
(biotech/biotech-graph entry with the component installation id and its `databaseUrlEnv`), `KS_BIOTECH_EXECUTOR_URL`,
`KS_BIOTECH_EXECUTOR_TOKEN`, `KS_BIOTECH_EXECUTOR_READ_TOKEN`; BKS executor `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`,
`BKS_EXECUTOR_TOKENS`, `BKS_VERIFICATION_DSN`, `BKS_VERIFICATION_TENANTS`.

## 5. Supported-capability matrix (part 1, 2026-10-25; historical, superseded by section 7)

| Capability | State | Evidence |
| --- | --- | --- |
| AI Engineer fresh install (component 2.3.0, 184 migrations, grants/custody, MC 1.6.0) | supported | installer run-2 with two interruptions; repeat `changed: false` |
| AI Engineer native exact-use admission, report v2 projection, exact package read, same-key concurrency | supported | `knowledge_component_binding.sql`, `research_report_v2_projection.sql`, `research_report_v2_concurrency.mjs` on the fresh install |
| Verified claims only under an admission-bound receipt | supported | `legacy_verification_withdrawal.sql` W3/W4 |
| Biotech fresh install (component, MC 1.6.0, graph v2.2.0, executor config names) | supported | installer biotech-run-3 with two interruptions; repeat `changed: false` |
| BKS ingest skill worked examples on v2.2.0 via the executor HTTP path | supported | `skill-examples.integration.test.ts` 10/10, disposable Neo4j |
| v1 report packages | degraded | read-only history; inserts raise `REPORT_V1_WITHDRAWN` |
| Retrieval history claim authorization | degraded | now requires a `research.use_admission`; claims verified only through the withdrawn path are not authorized |
| Legacy AIDB verification runs, adjudication, drift outbox, recovery ledger, v1 seals/assessments/ingestion links | unsupported | withdrawn by `20261025010000`; KS code still calling them fails until part 2 retires it |
| MC knowledge lane: delivery gating of a dependent invocation | supported | for invocations that use the knowledge tools (E-MC D1, R3 section 4) |
| MC knowledge lane: real AIDB `knowledge.apply` driven from MC over the wire | unrun | E-MC 11.5 |
| MC knowledge lane: `verify_claims` tool | unsupported | K01 `verify.claims` answers `SCHEMA_UNSUPPORTED` |
| Live cutover of shared/cloud databases, Aura, Fly | unsupported | out of scope; owner go required |
| KS executor and both domain paths from the bundle (SV-09 T0, SV-12) | unrun | part 2 |
| MC runtime descriptor (`runtime-apply`) and seed bundles on the fresh installs | unrun | installers stop at plan/apply/verify |
| Interrupted MC apply inside the `mission-db` transaction | unrun | relies on its one-transaction apply |
| CI fresh chain (`contract.yml`) | unrun | needs `vars.KS_COMPONENT_REF` and `secrets.KS_READ_TOKEN` |

## 6. Part 2: Knowledge Services retirements (SV-17 helper F2)

The `knowledge_verification` component is now the only run, claims and seal authority in Knowledge Services. The legacy
`verification.v1` surfaces that wrote or read the tables `20261025010000` withdrew were **removed, not commented out**:
350 tracked files, about 95,900 lines (including, after review R3, a dead twin of the persistence proof and the Eve attestation modules), each backed up under `platform/knowledge-services/.scratch/sprint-v/proofs/SV-17/F2/removed/`
and listed with its reason in the F2 report.

| Retired path | Where | Replacement |
| --- | --- | --- |
| `verification.v1` claims, report and metric operations (`verification_claims/report/metric`, `verifyClaims/verifyReport/verifyMetricObservation`) | contracts, application, persistence, host, worker sealers, API routes, MCP `verify_citations/report/metric`, `ks verify citations/report/metric`, client | `report.register` / `report.assess` over K01 |
| Adjudication request/decision and reads; audit-bundle inspection; run/manifest/case/evidence reads; claims/report result reads | all transports, worker activities, persistence, client | component review and `knowledge.read` / `operations/{id}` over K01 |
| Semantic observation/reconciliation, Eve runtime attestation, offline claims/report diagnostics demo | application, host, persistence, CLI | none |
| Internal drift revalidation queue (`verification.drift.consume`, `/v1/system/verification-drift-*`) | API, host | none (outbox withdrawn) |
| Durable verification recovery host, report package service, content-link authority over legacy claim evidence, promotion selection over it | executor, knowledge-db, application, persistence | none; the content-link library stays uncomposed |
| Executor file-store run truth, verifier chain (`verify-claims`, `verify-extraction`, `judge`, `policy`, `seal`, `check-report`, `status`, `/runs/:runId`), legacy intent files, evidence oracle | `apps/verification-executor` | capture/artifact tools over a non-authoritative cache; `exactUseEvidenceOracle` in knowledge-db |
| Recovery skill, 55 proof scripts of retired surfaces, `prove:verification-persistence` | `skills/`, `scripts/`, root `package.json` | none |

Retained `verification.v1`: capture, parse, structured extraction, extraction verification, extraction replay, benchmark run
and compare, and their reads plus provider reconciliation. Retired configuration is refused at startup with
`VERIFICATION_RETIRED_CONFIGURATION:<NAME>` (API, worker) or `EXECUTOR_RETIRED_CONFIGURATION:<NAME>` (executor). The legacy
static bearer remains only for the retained executor capture, artifact and `/knowledge/*` routes; the K01 routes never accept it.

### KS pins after part 2

| Pin | Value |
| --- | --- |
| Vendored AIDB contract (persistence, knowledge-db, executor) | `vendor/aiengineer-database-contract-0.5.0.tgz` `sha256:c2f6c68b127de4d9f51d64a492a09ca0af4ef9aba246564c8a793670180d8f7b` (replaces 0.4.16; generated-types row of section 2 is now current) |
| Component required by the K01 backends (`MIN_COMPONENT_VERSION`) | 2.4.0 (`sha256:309a8c9b…64c7`) |
| K08 use-class registry | `catalog/research/use-classes.json`, executor setting `KNOWLEDGE_USE_CLASSES_FILE` |
| KS source | `ae59341` plus an uncommitted working tree (snapshot fact, like section 7 of F1) |

### Domain-path proofs from the bundle (component 2.4.0)

| Proof | Result | Evidence |
| --- | --- | --- |
| AI Engineer installer, fresh disposable Supabase `disposable-sv17-f2-aidb` | `changed: true`, 186 migrations, grants verified, MC 1.6.0 applied, 25 s; repeat `changed: false`, 4 s | `platform/knowledge-services/.scratch/sprint-v/proofs/SV-17/F2/aidb-run/receipt-{fresh,repeat}.json` |
| AI Engineer interrupted cycle on a fresh volume | A `--interrupt-after component` exit 1; B external `taskkill /T /F` at 20 of 186 migrations; C rerun exit 0 `resumedAfterInterruption: true`, 166 applied, MC applied; D repeat `changed: false` | `aidb-run/receipt-{C-resume,D-repeat}.json` |
| KS suites on the installed AI Engineer database | executor 22 files / 116 passed / 2 skipped (storage-backed suites); K01 `aidb-apply`, `postgres`, `biotech` integration and 18 conformance cases passed; persistence 242 passed / 28 skipped; knowledge-db 380 passed, 3 failed (`PROMOTION_SELECTION_REQUIRED`, **unverified pre-existing**: the throw is the first statement of `persistSelectedProjectionProposal`, before any SQL, and the function and fixture are unchanged from HEAD, but they were not rerun at HEAD) | `aidb-run/*-tests*.log` |
| SV-09 T0 harness (`scripts/experiments/sprint-v/run.ts --mode t0`) | **T0 PASSED**, both report kinds, component 2.4.0, no model calls | `platform/knowledge-services/.scratch/sprint-v/proofs/SV-09/t0-sv17-f2/` |
| Biotech installer on `disposable_sv17_f2_bio_*` + fresh disposable Neo4j | fresh `changed: true` (component, MC, graph release applied); repeat `changed: false` | `platform/knowledge-services/.scratch/sprint-v/proofs/SV-17/F2/bio-run/attempt-170426/` |
| Biotech interrupted cycle (second fresh database, same Neo4j) | `--interrupt-after component` and `--interrupt-after mission-control` exit 1; rerun exit 0 `resumedAfterInterruption: true`; repeat `changed: false` | same |
| SV-12 KS T1 over the real BKS executor on the installed database | **9 passed / 2 skipped** (the two consumer-fault cases need a fault hook over HTTP, as in SV-12) | `bio-run/attempt-170426/vitest.txt` |

All throwaway databases were dropped (including `kvop_serve_sv16`), the Supabase project was stopped without backup and the Neo4j
container removed. `sprint-v-pg17` stays running.

## 7. Final capability matrix (after part 2)

Real-work gate: **CLOSED**.

| Capability | State | Evidence |
| --- | --- | --- |
| AI Engineer fresh/repeat/interrupted install from the bundle (component 2.4.0, AIDB 0.5.0 head, MC 1.6.0) | supported | section 6 |
| Biotech fresh/repeat/interrupted install from the bundle (component 2.4.0, MC 1.6.0, graph v2.2.0) | supported | section 6 |
| AI Engineer report register/assess/derive, exact package read, native exact-use admission | supported | T0 PASSED on 2.4.0 |
| `knowledge.apply` over K01 on the AIDB guard path, receipt found | supported | `aidb-apply.integration.test.ts` on the installed database |
| Biotech admission, dispatch, verified ack, official read, duplicate/reordered/lost-ack/graph-down/revocation | supported | SV-12 KS T1 9 passed over the real BKS executor |
| K08 use classes: official/consequential use without `exactUse` refused `REVIEW_REQUIRED` | supported | conformance case and `native-ports.test.ts` |
| Retained `verification.v1` capture/parse/extraction/replay/benchmark operations | supported | full KS test run, with two pre-existing failing tests (contracts Biotech golden line endings; application registered benchmark replay `SEALED_CHECKPOINT_MISSING`, fixture not in git) and three knowledge-db integration failures labelled **unverified pre-existing** (`PROMOTION_SELECTION_REQUIRED`, not rerun at HEAD) |
| Executor capture/locate/register/artifact (non-authoritative cache) | supported | `offline.mjs` example, executor suite |
| K01 `knowledge.apply` declared use (envelope `use`/`audience` or intent `declaredUse`; no default; missing or conflicting use refuses `SCHEMA_UNSUPPORTED`) | supported | `native-ports.test.ts`; the register-side rule is untested |
| v1 report packages, retrieval-history authorization | degraded | as in section 5 |
| K01 `verify.claims` (MC `verify_claims` tool) | unsupported | retired with the executor file-store verifier chain; answers `SCHEMA_UNSUPPORTED` |
| `verification.v1` claims/report/metric/adjudication/audit/semantic/run-case reads/drift/recovery | unsupported | removed in part 2 |
| Biotech consumer-side native rollback and lost ack after the graph commit | unrun over HTTP, proven in-process | the 2 SV-12 cases skip over HTTP (no consumer fault hook); covered by D1's in-process BKS T1 (`dispatch.integration.test.ts`, D2 report) |
| Storage-backed executor checkpoint/source-discovery integration | unrun | needs Supabase storage credentials |
| MC runtime descriptor and seed bundles on the fresh installs; interrupted MC apply; CI `contract.yml` | unrun | as in section 5 |
| Live cutover of shared/cloud databases, Aura, Fly | unsupported | out of scope; owner go required |
