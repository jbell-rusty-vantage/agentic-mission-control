---
type: Implementation Evidence
title: "Sprint V proof log"
description: "Executed baseline checks, limitations and future proof receipts; never treats planned tests as passing tests."
tags: [mission-control, knowledge-services, sprint-v, proof]
date: 2026-10-24
status: active
---

# Sprint V proof log

## 2026-10-24: specification baseline

No runtime implementation, database migration, live research or paid model experiment was executed.
Four direct KS test commands were executed from `platform/knowledge-services` against the existing
source, demonstrating that component testing does not require Mission Control:

| Package / command after `corepack pnpm --filter <package> exec vitest run` | Files | Tests | Result |
| --- | --- | --- | --- |
| `@aiengineer/knowledge-verification` — `src/report/decomposition.test.ts src/report/report-wide.test.ts` | 2 | 15 | Passed |
| `@aiengineer/knowledge-application` — `src/verification/operations/verification-claims.test.ts` | 1 | 6 | Passed |
| `@aiengineer/knowledge-worker` — `src/verification-claims-sealer.test.ts src/verification-claims-semantic-stage.test.ts` | 2 | 13 | Passed |
| `@aiengineer/knowledge-verification-executor` — `src/knowledge/evidence-oracle.test.ts src/knowledge/report-assessment.test.ts` | 2 | 34 | Passed |

**Total: 68 tests across 7 files passed.** They establish current component behavior, including its
known limitations. They do not prove the new contracts, independent census, clinical quality, database
atomicity, Biotech parity or MC runtime integration. Test clocks are host-local; session date here is
the owner's America/New_York date.

Documentation baseline: KS generator check passed (405 inputs). MC baseline passed six checks and
failed the link check on three existing links. Those references were repaired without changing sprint
completion claims. Final MC check passed all seven checks (OKF, index, three program ledgers, links,
shipped skill manifests); KS check remained clean. Git diff whitespace checks passed after retaining
the existing files' mixed newline conventions. New implementation proofs are pending; operational-use
gate remains closed.

The 18-item work graph was validated as acyclic and its dependencies compared with the plan table.
Independent read-only reviews identified and resolved async operation lookup/cancel semantics,
authoritative revocation high-water checks, core-record-before-SQL ordering, AI-proof-before-Biotech
qualification, and removal of duplicate DDL/install/type ownership in the clean baseline. These are
specification reviews, not runtime tests of the proposed contracts.

## 2026-10-24: acceptance and agent navigation

The owner accepted the specification and workspace (SV-D13) and requested minimal initial navigation
(SV-D14). START-HERE.md now separates both application Supabase targets, AI Engineer domain schemas,
Biotech Aura data/Fly services, standalone saver, Agent Server and Temporal persistence. A second
read-only topology review found no material conflict with the inspected source/configuration evidence.
No fresh live-deployment probe was performed.

After finalization, all seven MC documentation checks passed; KS's 405-input documentation check was
clean. A focused check resolved all 35 local links in the start guide, answers and AI Engineer guide.
All 18 work items form an acyclic graph and exactly match the plan's dependency table; specification
status is accepted, claims remain empty and the operational-use gate remains closed. Repository
whitespace checks passed. These navigation checks do not upgrade any implementation proof.

## 2026-10-24/25: first implementation session (integrator plus four Opus 5.5 helper tracks)

Nothing was committed or pushed; every repository stays on its single `main` checkout with the work as dirty files.
Database proofs ran on the disposable container `sprint-v-pg17` (pgvector/pgvector:pg17, 127.0.0.1:55433, throwaway
credentials); every test creates and drops its own database. No paid model call was made (T2 unrun). The real-work
gate stays closed. Tracker: parent OVE-150, children OVE-151..159.

| Item | Tier | What ran | Result |
| --- | --- | --- | --- |
| SV-02 K01 | T0 | `@aiengineer/knowledge-operation-protocol` vitest; biome lint; build; `pnpm generate` | 23 passed; 13 JSON Schemas + golden vectors |
| SV-02 K01 Python | T0 | MC `tests/conformance/test_knowledge_protocol_golden.py` | 9 passed: identical canonical bytes and digests across TS/Python; vectors validate against the published schemas |
| SV-04 K02/K03 | T0 | `@aiengineer/knowledge-research-core` vitest (8 files) | 48 passed |
| SV-03 K09 | T1-KS | `@aiengineer/knowledge-db-contract` vitest with `KNOWLEDGE_DB_CONTRACT_ADMIN_DSN` | 8 passed: two fresh installs (ai-engineer, biotech), idempotent repeat, byte/receipt/installation refusals, forced RLS, bind_effect, seal_run CAS, reviewer grants, admit_exact_use epoch/closure/invalidation, receipts, outbox revocation in transit |
| SV-03 AIDB binding | - | `supabase/migrations/20261024010000_knowledge_component_binding.sql` + `supabase/tests/knowledge_component_binding.sql` | authored, UNRUN (needs the local Supabase stack; carries the E09 tenant-bound submit_intent + PUBLIC revoke) |
| SV-05 K04/K05 | T0 | `@aiengineer/knowledge-application` `src/research` vitest | 5 passed over the in-memory binding |
| SV-05 K04/K05 | T1-KS | `@aiengineer/knowledge-binding-aiengineer-postgres` vitest | 3 passed: the complete fixture (open run, evidence, report frozen into custody, producer + judge observations, verification_snapshot seal, assertion use decision, bind_effect + admit_exact_use + receipt, receipt lookup, edited bytes refused; Checkpoint A correction 2026-10-25: admitExactUse ran in its own transaction, not one native transaction, see the continuation entry) |
| SV-01 | T0 | MC `tests/unit/orchestration/test_live_invocation_origin.py` | 16 passed; shared helper `domain/execution/live_invocation.py` |
| M01 | T0 | MC `tests/unit/domain/knowledge` | 58 passed |
| SV-13 | T1-MC | `mission-db release-build` 1.5.0 from the 1.4.4 prefix; `tests/integration/postgres/test_sprint_v_release_150.py` | built (fingerprint `sha256:e18dc014f5c1b3a22d661da44356156ff1e2c0c24fae89275ab7ab96003d79d4`); 4 passed |
| SV-14/15 | T0+T1-MC | MC `tests/unit/knowledge`, `tests/integration/postgres/test_knowledge_gateway_postgres.py`, `tests/architecture` | 17 + 4 passed; architecture clean; combined MC selection 120 passed |
| SV-10 | T0 (+ local Neo4j) | BKS generate/verify/pin, build, workspace:build/verify, api:generate/check, unit tests; integration on a fresh test Neo4j | pinned biotech-schema-v2.1.0 (`schemaDigest sha256:fe5c5992…41b97`, `schemaReleaseDigest sha256:29e11824…661a7`); unit 356 passed / 1 failed test + 2 unloadable test files, all pre-existing biotech-meta absence (Checkpoint A correction) / 78 skipped; integration 155 passed sequentially; EXPLAIN evidence inherited |

Documentation checks: KS `node .agent-docs/cli.mjs check --repo .` and MC `python docs/tools/check_docs.py` results are
recorded at the end of this entry by the session that ran them (see the ledger row DOC-11 for the latest).

### As-built deviations worth a decision

- research-core records carry no self `ref`; `recordRef(kind, record)` derives it. Occurrences bind the frozen body
  artifact, not the report revision (digest cycle). Obligation weights are integer basis points; money is a decimal
  string. Open questions OQ1..5 from the K02 track: BKS acceptance of basis-point weights and body-bound occurrences;
  `UseDecision.normalizedValues` primitives only; negation/question screening as a review flag; forecast/recommendation
  policy undefined; `test-support.ts` placement.
- The component stores K02 records as JSON (`record` columns) beside indexed columns; the run record is written at seal
  time and the trigger refuses rewriting it. Observations carry an insertion `seq`.
- MC release version is 1.5.0, not the 1.4.5 placeholder. MC domain `InvocationOrigin` (snake_case, mc.invocation_origin.v1)
  is mapped once to the K01 wire `Origin` in `application/knowledge/access.py`; the domain `EffectIdentity` digest differs
  from K01 `bind_effect` and the journal stores the K01 digest. `RecoveryGrant` is explicit; `cancel()` was added.
- BKS renamed three requested fields that already existed with another meaning (`reportKindRef`, `useDisposition`) and
  skipped duplicates; ingest skill examples and dated benchmarks still name v2.0.2.

### Not done (honest frontier)

SV-06 beyond render/ledger/census/aggregation (independent auditor discovery pass, report-kind catalogue data, hosted
assess operation); SV-07 (authority/challenge frontier, scientific appraisal); SV-08 (AIDB plan/apply/receipt integration
and exact-use human review wiring); SV-09 (locked fixture harness, T2 metered model control); SV-11/12 (Biotech binding,
outbox acknowledgment from the graph, cross-store faults); SV-16 (real HTTP binding client, bootstrap wiring, parity);
SV-17 (removal of the old truth paths: executor file store, worker sealer, legacy ReportIntent; release bundle); SV-18
(downstream gate). The `ks.knowledge_operation.v2` HTTP/MCP surface is not exposed yet. The old KS verification paths
still run unchanged; no cutover has happened.

## 2026-10-25 continuation audit (preparation only)

The pre-checkpoint statement above that nothing was committed was superseded by the four checkpoint
commits: MC `3aabe91b`, KS `ae593410`, AIDB `25f82ede`, BKS `3ea01488`. All four were clean on `main`
with one registered checkout when this audit began. Remote/deployment state was not revalidated.

Three GPT-6.1 Sol read-only reviewers checked MC, KS/AIDB and BKS. Their source findings are retained
in [NEXT-SESSION.md](NEXT-SESSION.md), including missing cryptographic sealing, the native transaction
integration point, absent runtime transport/tool wiring, M03/M04 gaps, and BKS outbox/read eligibility.
This is a continuation audit, not the full second acceptance review for any SV work item; states stay unchanged.

Fresh command from MC:

```powershell
.venv/Scripts/pytest.exe tests/conformance/test_knowledge_protocol_golden.py tests/unit/knowledge tests/unit/domain/knowledge tests/unit/orchestration/test_live_invocation_origin.py tests/architecture -q
```

**Passed:** 112 tests, one dependency deprecation warning, 33.59 seconds. Documentation baseline:
`.venv/Scripts/python.exe docs/tools/check_docs.py` passed 7/7 before edits and again after the
continuation packet was added and the index regenerated. MC `git diff --check` passed. Two reviewers
rechecked the continuation for MC scope/dependencies and KS/AIDB correctness; neither found a
remaining correction. This review covers the instructions, not acceptance of unbuilt runtime work.
**Unrun:** fresh PostgreSQL/Neo4j/Temporal integration, live-state probes and T2 model tests.
No runtime code, data, deployment locks or tracker state changed; no paid calls, commits or pushes.

## Required release evidence

For each WORK-ITEMS.json item, append commit/schema digests, exact commands and tier, observed counts,
artifact digests, result (passed/failed/blocked/unrun), cost and reviewer. Retain raw receipts in ignored
owning-repository scratch. Never fill these fields from a proposed command or a subagent's confidence.

## 2026-10-25 continuation session (checkpoints A-F)

Integrator Claude Fable 5.1 with Opus 5.5 helpers (at most three concurrent), one `main` checkout per repository, base
commits MC `3aabe91b`, KS `ae593410`, AIDB `25f82ede`, BKS `3ea01488`. Every PostgreSQL proof ran on the disposable
container `sprint-v-pg17` or on a disposable Supabase database created and destroyed by the helper; Neo4j proofs on the
BKS `scripts/neo4j-test.sh` container, removed after each run. Raw receipts live in each repository's ignored
`.scratch/sprint-v/proofs/<item>/`. Full helper reports are retained by the integrator session. Nothing was committed,
pushed or deployed by this entry unless a later line says so. Counts are the helper's observed counts; "pre-existing"
failures were reproduced at HEAD.

### Checkpoint A: second review of the foundations

Read-only Opus 5.5 review of SV-01/02/03/04/05/10/13/14/15 against design section 9 with the proofs rerun: KS
23/48/8/3/5 passed (protocol, research-core, component, binding, coordinator), MC 120 passed in 50 s, BKS unit 356
passed / 1 failed test + 2 unloadable files (all the absent `biotech-meta`, pre-existing). Verdicts and every deviation
are in [SPRINT-V-DESIGN.md section 10.1](../specs/SPRINT-V-DESIGN.md#101-conformance-after-checkpoint-a-second-review-2026-10-25);
OQ1..OQ5 decisions in section 10.2. Two earlier claims were corrected in this log and WORK-ITEMS: the SV-05 binding
fixture had admitted exact use in its own transaction (not one native transaction), and the SV-10 BKS run had three
pre-existing `biotech-meta` failures, not one.

### Checkpoint B: one complete AI Engineer service path

| Item | Tier | What ran | Result |
| --- | --- | --- | --- |
| SV-06 | T0+T1-KS | research-core, application `src/research`, knowledge-db-contract, binding vitest | 60 / 22 / 9 / 11 passed. Auditor census observation is the only census input; report kinds `evidence_report` and `study_appraisal` as K08 catalogue data; `ReportAssessmentService` with K01 handles, idempotent cancel; component **2.1.0** (`0004_operations`: operation table with CAS transitions, report kind columns, `report_assessment`, occurrence key per revision); deterministic atomic seal with failure-injection and concurrent-seal tests; weights sum to 10000; unmet holds, contradiction or L0 rejects |
| SV-07 | T0+T1-KS | same packages after the second helper | 73 / 34 / 10 / 21 passed; application full suite 476 passed + 1 pre-existing failure (`verification-benchmark-registered-replay`, reproduced at HEAD). Authority/challenge observations with pinned `catalog/research/source-authority` rules and an on-demand Crossref adapter (recorded fake in tests); gating `authority_missing/authority_adverse/challenge_missing/challenge_unresolved` for critical and scientific official use; Ed25519 detached seal signatures verified before write and on every load; reviewer grants scoped by use/audience/report kind, adjudication binds exact digests, signed successor decisions, correction closure; component **2.2.0** (`0005`: nullable qualifiers digest, normalized values + digest, subject/scope checks, invalidated = rejected, signature columns + key table, `enqueue_dispatch`/`settle_dispatch`/`claim_dispatches(target_binding)`/stored ack/`check_use_eligibility`) |
| SV-08 (KS) | T1-KS + T1-AIDB | knowledge-db ingestion vitest on `sprint-v-pg17`; AIDB executor tests on a disposable Supabase database with component 2.2.0 + 182 AIDB migrations | 365 passed + 21 skipped without Supabase; AIDB 14 passed (admitted; rollback on stale epoch / unknown decision / edited effect; one receipt under concurrency; recovery after a lost commit response). `exact-use-admission.ts` is the single admission path, executed on the executor's own connection inside `temporal.begin_batch ... commit_batch`, running `research.assert_admitted_use` on AI Engineer installations and writing the effect receipt before commit |
| SV-08 (AIDB) | T1-AIDB | disposable Supabase db: component install (2.0.0, 2.1.0 upgrade, fresh 2.1.0) -> `supabase migration up` -> `knowledge_component_binding.sql` + `research_report_v2_projection.sql` + two-session concurrency script | all passed on three runs; install receipts `sha256:0dc1dbc4...` (2.0.0) and `sha256:0c860e16...` (2.1.0), repeat installs idempotent. New `20261024010100_research_report_v2_projection.sql` (projection tables, admission record, `research.read_report_package`, `research.assert_admitted_use`, receipt decision columns, commit-time `ADMISSION_REQUIRED`, SQLSTATE KSA01..07); binding migration tightened to a superset key check; workspace rebuilt after raising `search_index_bytes` 524288 -> 720896. Follow-up for 2.2.0 fixtures and the normalized-values argument recorded in WORK-ITEMS |

### Checkpoint D: the same path for Biotech

| Item | Tier | What ran | Result |
| --- | --- | --- | --- |
| SV-11 (BKS) | T0+T1 | BKS unit/contract/executor/python tests; graph + PostgreSQL proof on disposable Neo4j 5.26 and a throwaway Biotech component install | stub 15, contracts 3, executor 2, python 91; 9/9 graph proof (both kinds, duplicate, reordered, revoked in transit, invalidated, lost ack, graph down then retry, rollback before marker, official reads); full unit 376 passed / 1 failed / 87 skipped and integration 178 / 1 / 12 (pre-existing `biotech-meta`). `biotech-knowledge-admission.v1`, read v3 with eligibility block, `DispatchConsumer` (effect + `KsIntentMarker` in one Neo4j transaction), `POST /kg/admission/dispatch/consume` under a `service` principal, official reads holding when the authority is unreachable. New SDL release **biotech-schema-v2.2.0** pinned (schemaReleaseDigest `sha256:2df9d3bc...25a74`, schemaDigest `sha256:de8ab942...6576`) |
| SV-11 (KS) | T0+T1-KS | `@aiengineer/knowledge-binding-biotech-graph` vitest, stub consumer, then against component 2.2.0 | 13; 24/24 (x4). One PostgreSQL transaction for admit + inline payload custody + `enqueue_dispatch`; receipt `applied` only after a verified acknowledgment; official reads via v3 with digest recheck; no Neo4j driver in KS |
| SV-12 | T1 cross-store | `sv12-harness.sh` with the real BKS executor + disposable Neo4j + throwaway Biotech PostgreSQL (component 2.2.0), two rounds | round 1: 3 passed / 6 failed (`MARKER_MISMATCH` on acknowledgment) / 2 skipped; after the approved BKS acknowledgment patch (recomputed component digest for `ks-intent-marker.v1` rows) and the repaired D1 seed: **9 passed / 0 failed / 2 skipped** (lost ack after graph commit, native rollback: need an in-process fault hook; covered by the D1 in-process test in the same run). BKS 381 passed / 1 pre-existing / 87 skipped; dispatch 20/20 |

### Checkpoint E: connect the current MC runtime

| Item | Tier | What ran | Result |
| --- | --- | --- | --- |
| SV-08 (AIDB, 2.2.0) | T1-AIDB | fresh disposable Supabase db: component 2.2.0 -> 183 AIDB migrations (head `20261024010200`) -> both SQL suites -> concurrency script -> repeat install; then the knowledge-db AIDB executor tests after the guard-lookup fix | component receipt `sha256:29bf068a...` (identical to the KS receipt); both suites 0 errors; one receipt under concurrency; AIDB executor 14/14 with every admission row carrying the normalized-values digest; binding 21/21 on `sprint-v-pg17` incl. the `AIDB_GUARD_REQUIRED` refusal. New `20261024010200_research_admission_normalized_values.sql` (5-argument guard; digest mismatch -> EFFECT_CONFLICT) |
| SV-16 (KS) | T0+T1-KS | K01 vitest; executor knowledge-operation vitest over the wire and on `sprint-v-pg17`; full executor suite; MC's real minter + HTTP client against the executor on 127.0.0.1:4310 | K01 26; knowledge-operation 20 (16 wire conformance, 3 native-port, 1 PostgreSQL: register, concurrent duplicates one receipt, assess to `held`, `receipt.get`, restart keeps status/receipt/read); executor 259 passed / 40 skipped; MC conformance 51 on byte-identical vectors; MC client end to end (register, retry with effect grant, assess held, receipt found). Routes `/knowledge-operation/v2/{invoke, operations/{id}, operations/{id}/cancel, receipts/{effectKey}, describe, artifacts/{id}}` + MCP mirrors; K07 `auth.ts` (EdDSA/ES256 allowlist, pinned issuer, JWKS with retiring key, unknown kid fails closed, 30 s skew, audience, single-use jti, installation/tenant/binding/grant/dispatch checks, `ORIGIN_MISMATCH`); K01 amended with the effect-scoped recovery grant and four new golden vectors. Round-2 follow-ups (biotech binding in the factory, real `knowledge.apply` over the wire with stored K01 receipts, `report.derive`, durable replay nonce in component 0006) recorded below when they return |
| SV-16 (MC) | T0+T1-MC | MC knowledge-scoped selection (222 passed), ruff, mypy 892 files, docs check; `test_knowledge_gateway_runtime.py` on local Temporal + PostgreSQL 1.6.0 with the in-process fake binding | StageGraph (2 stages), GoalDirected (4 operations) and StageGraph with the assessment held in review: journal prepared -> dispatched -> applied with the live attempt as origin, submissions assessed with basis `assessed`, stop leaves the handle cancelled with one `operation.cancel`. Built: `adapters/knowledge/http_client.py`, `adapters/knowledge/credentials.py` (Ed25519 via joserfc, rotation, JWKS), strict Python K01 models, `iss` check, effect-scoped recovery claim on retry, `compose_knowledge_lane` (fail-closed settings, describe digest in the startup receipt), six Deep Agents tool components incl. `submit_output`, M03 assessing/assessed states with `outcome_basis`, M04 `application/context/{resolution,representation,delivery}.py`, **MC release 1.6.0** (`0055`: durable handles, assessment columns, outcome basis, delivery attempts + readiness guard; fingerprint `sha256:57a1abee...`; locks unchanged). Defect fixed: `mint_effect_key` ignored the run. Real-executor parity, run-level stop of open assessments, lineage persistence and manifest projection of the tools are the round-2 follow-ups |

### Checkpoint C: AI Engineer fixture and the bounded T2 control slice

| Item | Tier | What ran | Result |
| --- | --- | --- | --- |
| SV-09 | T0 | KS `scripts/experiments/sprint-v/run.ts --mode t0` on `sprint-v-pg17` (runs `t0-final4`, then `t0-b1b-sv09fix` after the four fixes below) | passed. Locked corpus `catalog/research/fixtures/` (26 files; final digest `sha256:c5285484...`): 7 synthetic sources with a planted contradiction, negations, a table and a caption; two frozen tasks (6 obligations each); labels; provenance per fixture. Chain: freeze task -> fragments -> register (both kinds) -> judge -> recorded authority/challenge -> `report.assess` with auditor census -> signed seal -> derive -> report and assertion decisions -> native admission + effect receipt -> exact read. Final T0: evidence report rejected on the grounded contradiction with census holds (uncited heading in a factual section), 4 effects admitted; study appraisal admitted 7/7; an `ai-engineer` installation without the AIDB projection refuses every effect with `AIDB_GUARD_REQUIRED`; exact reads 4/4 |
| SV-09 | T2-control | `run.ts --mode paid` (`paid-2`) with routes discovered by authenticated models/list calls and pinned without substitution: producer `gpt-6-sol`, judge `gpt-6-luna`, second-family judge and census auditor `claude-sonnet-5-5`; reservation before every call from a persisted meter | **USD 0.15** (0.149489) of the 6.00 helper ceiling (15.00 session ceiling), 39 calls, none blocked. All four report-level decisions held or rejected (census differences, 2 unsupported, 1 contradicted, 1 unmet optional); 19 assertion-level admissions with receipts; 4/4 exact reads; census recall 6/6 and 6/6 on the locked reference bodies; judge vs second-family agreement 4/5 (evidence report) and 0/6 (study); median latency producer 14.4 s, judges 2-3.6 s, auditor 7.5 s. Recorded as a control slice with `INDEPENDENCE_UNPROVEN`; no evaluator-quality or operational claim. Defects it exposed were fixed in research-core/application before the final T0: judge disagreement holds (`disputed_verdict`) instead of rejecting; framing sections excluded from the factual census with recorded reasons; derive mapping accepts the declared camelCase fields and projects appraisal domains; identical re-registration is idempotent by digest |

### Checkpoint E, round 2 and 3 (Knowledge Services side)

| Item | Tier | What ran | Result |
| --- | --- | --- | --- |
| SV-16 (KS) | T0+T1-KS+T1-AIDB | executor knowledge-operation vitest on `sprint-v-pg17` (component 2.3.0) and on a disposable Supabase database (2.3.0 + 183 AIDB migrations); installer tests; full executor suite; live interop with MC's real minter and client against `kvop_serve_sv16` | knowledge-operation 23 (then 22 + 1 blocked until the binding idempotency fix landed, then 1/1); full executor 261 passed / 0 failed; K01 27; installer 12 (2.2.0 -> 0006-only upgrade; three concurrent uses of one credential, one accepted); bindings 21 and 24 on 2.3.0; AIDB SQL suites pass on 2.3.0 without AIDB edits. Component **2.3.0** (`0006`: `credential_use` single-use across restarts, `protocol_receipt` with bound-digest check). `knowledge.apply` returns a receipt (plan-level bound effect digest); K01 outcome `pending_dispatch` and an optional `delivery` block on receipt lookups composed at read time from the outbox acknowledgment (applied only when the ack digest equals the expected marker digest); `biotech-graph` wired into the factory (apply = admission + enqueue in one transaction; stub consumer acknowledged; receipt lookup pending -> applied); real AIDB apply over the wire (admitted on the guard path, duplicate same receipt, `STALE_DECISION`, `EFFECT_CONFLICT`); `report.derive` exposed (`research-report-derive/v1`, independent observations only); registration reuse -> `EFFECT_CONFLICT`. Interop: register applied, retry without grant `ORIGIN_MISMATCH`, retry with the effect grant same receipt, assess held, receipt found live and via read-only recovery. Limitation: the apply protocol receipt is written right after the native commit, not inside it |

### Checkpoint F, part 1 (AIDB withdrawal, installers, locks, Biotech references, bundle)

| Item | Tier | What ran | Result |
| --- | --- | --- | --- |
| SV-17 (part 1) | T1 | AIDB: fresh disposable Supabase database with component 2.3.0 first -> 184 migrations incl. `20261025010000` withdrawal -> both SQL suites + concurrency + withdrawal test; `scripts/install-ai-engineer.mjs` (self-interrupt after the component step; external kill at migration 70/184; rerun; repeat); BKS `scripts/install-biotech.mjs` on throwaway PostgreSQL + Neo4j (interrupt during the graph schema; rerun; repeat); BKS build/test/workspace/api checks; ingest skill examples | passed. AIDB withdrawal drops 22 tables, 1 view, 1 column and 22 functions with their grants, tightens three kept functions, closes the v1 report packages (`REPORT_V1_WITHDRAWN`); contract 0.5.0; 6 SQL tests fail identically before and after (pre-existing); typecheck, `npm test` 15/15, workspace build/check/validate pass. Both installers complete after interruption and apply nothing on repeat; the AI Engineer installer refuses the shared project, the Biotech installer refuses a missing variable or an Aura URI. MC `releases/<version>/component` documented as the only release authority (root `component/` retired input); new 1.6.0 locks written to `sprint-v/release/locks/` (ai-engineer `508d0415...` -> `7269ccdf...`, biotech `baf54ed0...` -> `d5b2a74b...`), `deployments/<app>` untouched. BKS active references now say v2.2.0; 381 passed / 1 pre-existing. `RELEASE-BUNDLE.md` + `release-bundle.json` written. Open until part 2: KS still pinned AIDB types 0.4.16 and read withdrawn tables; installers do not apply MC seeds or the runtime descriptor; CI `contract.yml` installer job unrun |

### Checkpoint E, rounds 2-4 (Mission Control side, real executor)

| Item | Tier | What ran | Result |
| --- | --- | --- | --- |
| SV-16 (MC) | T1-MC real | `test_knowledge_gateway_runtime.py` in real mode against a KS executor started from current source (component 2.3.0, later 2.4.0) on loopback ports 4310/4311 with MC's Ed25519 issuer; a Biotech toolset harness on 4312; Postgres suites; full unit run; ruff; mypy; docs check | passed. StageGraph and GoalDirected on `aiengineer-postgres` (register applied, `report.assess` held with the scripted auditor, finalization on an `assessed` basis); Biotech path through the toolset 12/12 (apply -> `pending_dispatch` -> stub consumer -> receipt lookup `applied` -> settled; bound digest MC = KS); receipt attribution over the wire 6/6; stop during review proven with a test-double review gate in a throwaway component database (the executor never puts `report.assess` into `waiting_review` by itself; review is carried by the use decision as `REVIEW_REQUIRED`); run-level stop cancels open assessments; lineage facts written; the six knowledge tools are catalog `tool` rows a manifest can bind; manifest search filtered by declared kind; `knowledge_apply` takes a decision handle and the host supplies `exactUse` and the native contract; `pending_dispatch` effects block finalization until delivery `applied`/`revoked`. Round 4 (after the R2 review): exact resolve/represent/deliver wired before a dependent invocation starts (stage 2 started only after stage 1's report was delivered and digest-checked, 3/3 files; tampered bytes -> stage 2 never started, run failed `context_delivery_blocked`); production `RecoveryGrant` minted per uncertain effect at attempt 2+ (attempt 2 without the grant refused before sending; with it, the same receipt); fresh single-use credential per transmission; failed attempts reconcile and record basis `attempt_failed`. Full unit run 5855 passed / 36 known pre-existing or environment failures. Release 1.6.0 rebuilt in place twice before the freeze; the bundle locks were re-verified against the final bytes (52 files, 0 mismatches). Open: in-process decision store, linked missions receive no delivery yet, blocked reason text only in the result manifest |

### Second reviews and the fixes they required

| Review | Scope | Outcome |
| --- | --- | --- |
| R1 (Sonnet 5.5, read-only) | SV-06/07/08/09/11/12: research-core, application research, component 0004..0006, both bindings, knowledge-db admission, AIDB migrations, BKS admission/read | reruns research-core 75, application research 36, knowledge-db-contract 12, aiengineer-postgres 22, biotech-graph 24, knowledge-db ingestion 365 (+21 Supabase-only skipped), BKS 381 / 1 pre-existing. Invariants hold (L0, census from auditor observations, signatures on write and load, admission in the native transaction, no Neo4j driver in KS, atomic graph apply + marker, immutable sealed history). Fifteen findings; the correctness ones were fixed in-session: BKS eligibility now uses the component `check_use_eligibility` (revoked reviewer grants count), every official v3 operation is eligibility-checked and held when the authority is down, refused dispatches are settled and the consumer claims only its binding, `applied` derives from the PostgreSQL acknowledgment matching the expected marker digest (BKS 385 passed / 1 pre-existing; real-graph run `attempt-152040` 9/11, 2 skipped as before); research-core: a distinct-evaluator disagreement holds (`disputed_verdict`), a report-targeted integrity failure voids obligations, `unable_to_screen` flag, SQL key registry authoritative for revocation, use-class registry (`catalog/research/use-classes.json`) making official-use intents require an exact-use binding; component **2.4.0** (`0007`: mandatory normalized-values digest `NORMALIZED_VALUES_REQUIRED`, server-clock credential functions). Recorded follow-ups before SV-18: non-selected-set contradiction at assertion level; `retrieval.history_claim_authorized` rechecks current eligibility |
| R2-MC (Sonnet 5.5, read-only) | SV-01/02/13/14/15/16 MC half | reruns 195 passed in 90 s, ruff clean, mypy 894 files clean, docs 7/7; every design section 9 MC case has a named test; 1.5.0 untouched; the 8 `test_bundle_custody_composition.py` failures reproduced at HEAD. Deviations D1 (delivery services unwired) and D2 (no production recovery grant) plus the fresh-token and failed-attempt observations were fixed in round 4 above |

### Checkpoint F, part 1 follow-up

| Item | Tier | What ran | Result |
| --- | --- | --- | --- |
| SV-17 (part 1, 2.4.0) | T1 | AIDB fresh disposable database with component 2.4.0 first -> 186 migrations (incl. `20261025010100_research_force_rls`, `20261025010200_research_admission_values_required`) -> five SQL suites + concurrency + withdrawal; `install-ai-engineer.mjs` fresh then repeat; BKS `install-biotech.mjs` fresh then repeat | passed; AI Engineer fresh `changed: true` (186 migrations, MC 1.6.0 verified) then `changed: false`; Biotech fresh then repeat `changed: false`; component pin 2.4.0 digest `sha256:309a8c9b...64c7`; MC 1.6.0 target locks rewritten after the in-place rebuild (ai-engineer `ce8f69d8...`, biotech `3677fa00...`) and verified by the integrator against the final release bytes |

### Checkpoint F, part 2 (Knowledge Services retirements, documentation, fresh installs from the bundle)

| Item | Tier | What ran | Result |
| --- | --- | --- | --- |
| SV-17 (part 2) | T1 | KS build (26 tasks), typecheck (47), lint, agent-docs, skills check, examples, sandbox pack, full test run; `install-ai-engineer.mjs` on a throwaway Supabase (fresh 186 migrations, repeat, interrupted at the component step and at migration 20/186 then resumed); executor + persistence suites on the installed database; SV-09 T0 harness; `install-biotech.mjs` fresh/repeat/interrupted; SV-12 KS T1 suite against the real BKS executors on the installed database | passed. 346 tracked files removed (94,550 lines; backups under KS `.scratch/sprint-v/proofs/SV-17/F2/removed/`); the executor file store holds no verification result (capture/artifact tools kept); worker sealer, legacy `ReportIntent`, evidence oracle and every reader of the withdrawn AIDB objects removed; vendored AIDB pin 0.5.0; retired settings fail at startup; use classes wired; lint baseline 4384 -> 2553; full test run 46/48 tasks (2 pre-existing). AI Engineer from the bundle: executor 116 passed, persistence 242, T0 harness passed; Biotech from the bundle: SV-12 9 passed / 2 skipped (no HTTP fault hook). `verify.claims` refuses typed (judge hosting is a runtime-sprint provider decision). Docs: KS verification README, INTEGRATION-GUIDE, current-state, admission and recovery concepts, executor README; MC `MISSION_CONTROL_LOCAL_API.md` (`KNOWLEDGE_*` settings, K01 annex), `REMOVAL_GUIDE.md`; bundle sections 6-7 |

### Final rounds after the cutover and the final review

| Item | Tier | What ran | Result |
| --- | --- | --- | --- |
| SV-16 (KS, round 4) | T0+T1-KS | K01, host and executor suites; typecheck/build; depcruise; format:check; agent-docs | K01 28; executor knowledge-operation 23 -> 24 passed / 2 skipped; full executor 112 passed / 6 skipped (legacy tests retired); host 52; boundaries 0 new / 106 known; format clean on 1231 files; lint 2552 vs 2553. K01 envelope gains optional `use`/`audience` (effectful only, both or neither; vector `apply-envelope-declared-use` copied to MC); declared use from the envelope else the intent, no silent default; `report.register` validates the envelope use against the task before binding the effect (a refusal leaves no effect row); the K01 service and K07 auth moved to `packages/host/src/knowledge-operation` |
| SV-16 (MC, round 5) | T1-MC real | knowledge + conformance suites; ruff; mypy; docs check; acceptance fake + real against an executor built from current KS source on loopback 4311 with a throwaway 2.4.0 database | 291 passed (202 conformance incl. two new negative envelope cases); acceptance passed both modes; Python envelope carries `use`/`audience` with the KS rules (off the wire when absent); every `operation.get`/`operation.cancel`/`receipt.get` transmission mints a new jti and dispatch id (two tokens sharing one dispatch id are refused `dispatch_reused`; a cancel whose first answer was lost is retried and accepted); delivery fails closed under `KNOWLEDGE_GATEWAY_REQUIRED`. Runtime-sprint items: lookup/cancel dispatch ids on journal transitions (1.7.0/0056); delivery not DAG-scoped, knowledge-tool invocations only, linked missions excluded |
| R3 final review (Sonnet 5.5, read-only) | review | K01 28, host 52, executor 114 passed / 4 skipped, MC unit + conformance 289; format, lint, typecheck, depcruise, agent-docs clean; bundle pins compared with the files; retirement grep; MC D1/D2 code read | every named K01/K07 case has a test incl. replay surviving a restart; no KS code reads the withdrawn AIDB objects; pins match (component 2.4.0 digest and 7 migration hashes, MC 1.6.0 manifest/fingerprint/contract, 52/52 lock hashes per app, BKS PIN v2.2.0, AIDB head `20261025010200`, vendored 0.5.0) except the K01 golden digest (stale, re-recorded in the F2 narrow fixes); D1 closed with deviations, D2 and O1 closed; the O5 retry defect and the register order were fixed in the rounds above; narrow SV-17 fixes (matrix rows, dead script, Eve modules, two operator docs, AIDB runner as dev-only, lint baseline) applied by F2 |

