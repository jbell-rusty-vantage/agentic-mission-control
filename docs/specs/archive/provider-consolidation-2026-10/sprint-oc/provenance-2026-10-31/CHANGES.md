---
type: Change Ledger
title: "Provenance sprint 2026-10-31: what each slice built"
description: "Dated entries per slice; each states implemented, tested, integrated and qualified separately, with commits and evidence paths."
date: 2026-10-31
status: active
---

# Change ledger

(entries added as slices land)

## Slice 3 (2026-10-31): AIDB coordinates, receipt targets, report_v2 writer

- **Implemented and tested** (AIDB `44c980c`): migration `20261031010000_operation_receipt_targets` adds the origin digest and
  `mc_*` coordinates to `orchestration.operation_intent`, `origin_digest` to `operation_receipt`, the table
  `orchestration.operation_receipt_target` (one row per native row created/reused/superseded/staged, written in the apply
  transaction), `evidence.claim.producer_origin_digest` (attempt now optional, one producer identity required) and the view
  `orchestration.mission_run_effects`. SQL suites `operation_receipt_targets.sql` and `research_report_v2_projection.sql` pass;
  types, workspace (head `20261031010000`) and install manifest regenerated; `npm test` 15/15.
- **Applied** on the disposable AI Engineer database only (`supabase_db_disposable-overnight-20261029`); no remote project touched.
- **Implemented and tested** (KS `2564226`): `applyPlan` attributes every write to its proposal and records targets; the executor
  writes origin and coordinates on the intent, `origin_digest` on the receipt, the targets and `research.report_v2_{revision,
  assertion,ingestion}` after the receipt row; claims carry `producer_origin_digest`; `ATTEMPT_REQUIRED` becomes
  `PRODUCER_REQUIRED`. knowledge-db typecheck clean, 359 unit tests pass; exact-use 5/5 and executor 10/10 on the disposable;
  verification-executor `aidb-apply` 8/8. Three pre-existing `PROMOTION_SELECTION_REQUIRED` failures are unchanged.
- **Not integrated / not qualified:** no live Mission Control run has produced rows in `mission_run_effects` yet; that is slice 2's
  proof. Follow-ups: AIDB `docs/schema-workspace/INTENT_AND_EXECUTOR_CONTRACTS.md` lacks the new `targets`/`report` receipt
  fields; the assertion-subject projection path is untested; KS `.agent-docs/provenance.json` is rebuilt at sprint close.

## Slice 1 (2026-10-31): origins carry the ledger mission id and the real activation id

- **Defect:** `KnowledgeToolset.access()` set `mission_id = run_id` and synthesized the activation id, so no Knowledge Services
  origin ever carried true mission coordinates.
- **Implemented and tested** (MC, staged; commit pending the shared tree settling): `InvocationLocator` port with a Postgres adapter
  (`mission_run` LEFT JOIN `activation` by `activation_key`) and an in-memory locator; `LiveInvocation`/`InvocationAccess` carry
  `mission_id`, `activation_id`, `unit_key`; `access()` fails closed without a located mission; `locate()` runs at every toolset
  entry; `unit_key` fills journal, handle and submission rows; the reviewer origin uses the ledger mission id. `InvocationOrigin`
  dump shape and the K01 wire unchanged. Unit 907 passed (3 failures belong to concurrent slices), conformance 64 passed,
  Postgres integration 25 passed on `sprint-v-pg17`, mypy clean on touched modules.
- **Not integrated:** no live Deep Agents run on it yet; slice 2's paid run is the proof.

## Slice 2 (2026-10-31): AI Engineer fixture through the production gateway

- **Implemented and tested** (KS `5727a4b`; MC uncommitted): Mission Control owns the issuer key and JWKS; producer-side K01
  calls (`report.register`, `knowledge.plan_preview`, `report.seal`, `report.decide`, `decision.resolve`, `knowledge.apply`)
  go through `KnowledgeGateway` with MC-minted `mission_invocation` credentials after `toolset.locate()`; the host verifies a JWKS
  file holding MC's key and its own evaluator key, takes the MC wire origin for intent and report building, derives producer
  attribution from it, and logs every served call with its minter kid; judge and auditor remain host-minted standalone roles with
  distinct subjects. Driver gains `--evidence-root`, `--model-cap-usd`, `--web-cap-usd`. MC unit 113 passed; KS node tests 10/10.
- **Zero-cost smoke (integrated at smoke level):** real host booted with MC's key against the disposable AIDB at head
  `20261031010000`; `report.register` under a `mission_invocation` origin answered 200; `knowledge_verification.origin` holds a
  row with the true mission id (distinct from the run id), activation, attempt, generation and lane `deep_agents`.
- **Pending:** the paid StageGraph run (model cap USD 7, web cap USD 8, authorized USD 15) after the shared MC tree settles.

## Slice 4, KS side (2026-10-31): `knowledge.read_intent`, a recorded synchronous read

- **Implemented and tested** (KS `6a4dd30`): new K01 result operation with native contract `knowledge-read-intent/v1`; request/result
  schemas and golden vectors; `KnowledgeReadIntentPort` and the `read_intent` backend capability; the AIDB port over `ReadExecutor`
  plus workspace search/get with the eight-query allowlist and tenant guard; executor injection; the host records every served read in
  `knowledge_verification.operation` with the verified origin digest (replay-safe; refused reads record nothing); bodies withheld past
  a 256 KiB canonical budget with digests kept; HTTP 200 marker and MCP description. Protocol 78/78, host 74, aiengineer-postgres 9,
  biotech-graph 19, executor typecheck ok.
- **Integrated on the disposable:** read-intent integration 3/3 against the real `ReadExecutor` and pinned workspace; backend conformance
  29 passed including the new `read_intent_recorded` check (a real operation row).
- **Pending:** the MC side (tool, gateway method, `retained_read_observation` writer, catalog seed) and a re-captured live-describe
  fixture for the MC conformance suite (seven tests red until then).

## Slices 6 and 7 (2026-10-31): knowledge charter skills, seed 1.0.4, object-store endpoint

- **Implemented and tested** (MC, uncommitted at the time of writing): `skills/biotech-knowledge-charter` and
  `skills/ai-engineer-knowledge-charter` 0.1.0 (SKILL.md plus `references/research-procedure.md` and `references/ingestion-guide.md`,
  promoted from the Qualia and AI Engineer fixtures and the domain sources); agent-skills seed 1.0.3 frozen and 1.0.4 generated (one charter
  row per application, revision 1); `KnowledgePortBinding.charter_skill` with digest-neutral exclusion; both application profiles name their
  charter (revision 2); the manifest service mounts `skill.<app>-knowledge-charter@latest` on knowledge missions with provenance
  `application:charter` (6 new unit tests). Seeds check/validate/publish-check clean; local bundle publish under
  `.scratch/provenance-2026-10-31/bundles/` (biotech 133 objects, ai-engineer 104; rerun idempotent).
- **Implemented and tested:** S3 endpoint, path-style, region and explicit-key settings; client config with SigV4 and checksums only when
  required; preflight `s3_endpoint_issues`; config surfaces; storage bucket seed `mc.storage.mission-payloads-1.0.0` (private, 50 MiB).
  17 unit tests pass in `test_s3.py`.
- **Integrated on the disposable:** bucket applied to the disposable Supabase stack through the seed contract's `apply_bucket`; a real
  `S3ArtifactPayloadStore` stage + retrieve + presigned GET round trip against `http://127.0.0.1:54821/storage/v1/s3` passed (4096-byte
  object; wrong digest refused). Evidence `.scratch/provenance-2026-10-31/s3-roundtrip.json`.
- **Not done:** remote custody upload and seed-apply of 1.0.4 and the bucket seed; proof that a launched Deep Agents node actually receives the
  charter at `/skills` (needs a run); hosted lanes cannot mount the charter (host support lists the five published lane profiles only).

## Slice 5 (2026-10-31): workspace closure at settled boundaries

- **Implemented and tested** (MC, uncommitted at the time of writing): contract `mc.workspace_closure.v1`
  (`domain/execution/workspace_closure.py`); `[workspace]` profile (`closure_enabled`, `closure_max_files` 512, `closure_max_bytes` 64 MiB,
  `closure_retention` "mission" or days) on both applications; `capture_closure` records every agent-visible file at `attempt_settled`,
  `attempt_failed` and `attempt_cancelled` with raw-byte digests, bodies promoted within caps, sensitive/secret/input bodies withheld,
  degrading past caps instead of failing; the result point's `workspace_checkpoint_ref` becomes `workspace-closure://<id>#<digest>`; the
  candidate cap no longer fails the attempt; Docker writable slots get their own host subdirectory; Postgres store
  `PostgresWorkspaceClosures`; `closure-body://` downloads through the run-bound artifact reader (4 MB per body); routes
  `GET /runs/{run}/points/{point}/closure` and `GET /runs/{run}/closures`; `/inspection` and run evidence carry a closure summary;
  CLI `missionctl run closure RUN --point ID | --list`; state-as-of lists closure files; retention expiry
  `expire_workspace_closures` reported as `expired_closures`. db-contract release **1.12.0** built (migration `0070_workspace_closure`,
  fingerprint `sha256:729c2e9d…34cce`). Unit 367 + 22 passed, profile conformance 16, release prefix 1, common_db release fresh/upgrade 2,
  closure store 1, candidates/lineage 5, retention 6; mypy clean on touched modules.
- **Not integrated / not qualified:** no live sandbox attempt has recorded a closure yet (the paid run is the proof); payload bytes are
  never deleted (retention removes rows); no MCP surface; deployment locks for 1.12.0 are owner-gated.

## Proof run (2026-10-31): `source-mc-origin-01` through the production gateway

- **Integrated (live run, disposable targets):** StageGraph run `56e53118…` (mission `01a194cc-6879…`) completed; seven
  Mission Control-minted K01 calls; two `mission_invocation` origins with the true mission id and real activation ids in the
  disposable AIDB; MC journal rows with mission, activation and unit key; `mission_run_effects` 29 rows; 15 claims fully supported,
  exact-use admission, native receipt, readback 2/2; eight workspace closures reported by Mission Control's own inspection.
- **Not exercised:** `knowledge_read_intent` (not bound by the fixture manifest); the charter skill (fixture pins its own capabilities).
- **Failed:** the Tavily fork run on the fixture's model-ledger reservation rule (USD 2 per call against the USD 7 cap); the driver
  was then reaped by the harness for host memory pressure. Nothing rerun. Spend: model est. USD 3.07, web 19 calls.
- Report: [REPORT.md](REPORT.md).
