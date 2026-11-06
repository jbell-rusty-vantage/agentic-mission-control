---
type: Working Draft
title: "State inventory: platform/knowledge-services (sprint-oc, 2026-11-01)"
description: "What Knowledge Services built since 2026-10-20 on sprint-oc, each item labelled implemented / tested / integrated / qualified with its proof path; versions with file:line; active programs; dirty files; candidate knowledge facts; doc-versus-code discrepancies. Input to Sitting II, item 1."
tags: [knowledge-services, agents, sdlc, state]
date: 2026-11-01
status: draft
---

# State inventory: Knowledge Services

Repository `platform/knowledge-services`, branch `sprint-oc`, HEAD `6a4dd30` (2026-10-31), local
branch **ahead of `origin/sprint-oc` by 14 commits** (unpushed; local tracking ref, no fetch made).
Label meanings follow the provenance report (`platform/mission-control/docs/specs/provider-consolidation-2026-10/sprint-oc/provenance-2026-10-31/REPORT.md:64-65`):
*integrated* = exercised through the real composed path against a disposable database on this
host; *qualified* = the W1 packet against coordinated builds. **Nothing here is qualified.**

## 1. What remains toward the goal for this repository

- W1 qualification of the coordinated MC/KS builds (OVE-169) has not happened; W1 is not released
  (`.../sprint-oc/NEXT-SESSION.md:119-121`). Every KS item below stops at *integrated* or lower.
- `knowledge.read_intent` is integrated on the KS side only; no Deep Agents mission has called it
  (`REPORT.md:36,59,85-86`). The Biotech binding has no read-intent port (`packages/bindings/biotech-graph/src` has no `read_intent`).
- `plan_preview` still admits subjects missing NOT NULL typed columns; only the fixture preflights
  (`NEXT-SESSION.md:45`; KS `8a38b0f`). This is an open KS defect, not a fix.
- Release hygiene: 14 unpushed commits, `.agent-docs/provenance.json` drift, and a gitignored
  vendored AIDB contract that predates slice 3 (section 7).

## 2. Versions

| Thing | Version | Source |
| --- | --- | --- |
| `knowledge_verification` component | **2.5.0** (migrations 0001..0008; 0008 `effect_dispatch_journal`) | `packages/knowledge-db-contract/component/release-spec.json:3`; `packages/knowledge-db-contract/package.json:3` |
| Minimum component accepted by AIDB binding | 2.5.0 | `packages/bindings/aiengineer-postgres/src/component-backend.ts:83` |
| Knowledge operation protocol package (`ks.knowledge_operation.v2`) | 2.0.0 (read_intent added without a package bump) | `packages/knowledge-operation-protocol/package.json:3` |
| `knowledge.read_intent` native contract | `knowledge-read-intent/v1`, request/result `...-request.v1`/`...-result.v1` | `packages/knowledge-operation-protocol/src/read-intent.ts:29-31` |
| research-core | 2.0.0 | `packages/research-core/package.json:3` |
| Binding `aiengineer-postgres` / `biotech-graph` | 2.0.0 / 0.1.0 | `packages/bindings/aiengineer-postgres/package.json:3`; `packages/bindings/biotech-graph/package.json:3` |
| BKS schema release the Biotech binding expects | `biotech-schema-v2.2.0` digest `sha256:2df9d3bc…5a74` | `packages/bindings/biotech-graph/src/descriptor.ts:9` |
| AIDB contract consumed | `@aiengineer/database-contract` 0.5.0 via `vendor/…-0.5.0.tgz` (gitignored) | `packages/knowledge-db/package.json:19`; `.gitignore:87` |
| Root and other packages | 0.0.0 / 0.1.0 (unversioned in practice) | `package.json:3`; `packages/*/package.json:3` |

## 3. Recent work (since 2026-10-20; 55 commits, about 1,386 file-changes)

| Item | What it is | Label | Proof path | Linear |
| --- | --- | --- | --- | --- |
| `knowledge.read_intent` (provenance slice 4, KS side) | New K01 result operation; AIDB read port over `ReadExecutor` with an 8-query allowlist and tenant guard; every served read recorded in `knowledge_verification.operation` with the verified origin digest; bodies withheld past 256 KiB | **integrated (KS only, disposable)**; MC side not exercised live | `6a4dd30`; `apps/verification-executor/src/knowledge-operation/read-intent.integration.test.ts` (3/3), conformance check `read_intent_recorded` (`packages/host/src/tests/conformance/backends/suite.ts:100,1611`); `provenance-2026-10-31/CHANGES.md:56-67`; `REPORT.md:59` | OVE-204 |
| Receipt targets, `report_v2` writer, producer origin (slice 3, KS side) | `applyPlan` attributes writes per proposal; executor writes origin + MC coordinates on the intent, targets, `research.report_v2_*`; `ATTEMPT_REQUIRED` became `PRODUCER_REQUIRED` | **integrated** (live run, 29 `mission_run_effects` rows) | `2564226`; `packages/knowledge-db/src/ingestion/receipt-targets.ts`; knowledge-db 359 unit; `CHANGES.md:22-26`; `REPORT.md:35,58` | OVE-204 |
| AI Engineer fixture through the production gateway (slice 2, KS side) | Fixture host verifies MC-minted `mission_invocation` credentials via JWKS; judge/auditor stay host-minted | **integrated** (run `source-mc-origin-01`, mission `01a194cc…` completed) | `5727a4b`; `.../tests/aieng-host-support.test.ts`; `CHANGES.md:43-54`; `REPORT.md:34,57` | OVE-204 |
| AI Engineer StageGraph fixture host + exact-use AIDB ingestion | Host for the 2026-10-31 GitHub/arXiv/Context7 fixtures; KS→AIDB `knowledge.apply` into disposable Supabase; preflight of typed columns | **integrated (fixture, disposable)** | `3e3d8a7`, `8a38b0f`; `NEXT-SESSION.md:33-46`; private `.scratch/aieng-stagegraph-2026-10-31/INDEX.md` (MC) | none in commit (board OVE-162) |
| Qualia fixture host retained | Qualia Deep Agents host, frozen replay, credentials, assessment helpers | **integrated (fixture)**; KS fixture checks 56 | `88397f8`; `NEXT-SESSION.md:66-97` | none in commit (OVE-162) |
| Native-write recovery, reviewed admission, predecessor check (B3/B4) | Approved native-write recovery with restart proof; reviewed native admission keeps the selected effect; exact predecessor before report registration | **integrated (focused, local)**; not W1 | `30171b2`, `9ba70c8`, `998eaae`; `aidb-apply.integration.test.ts`, `report-source-foundation.integration.test.ts`; `NEXT-SESSION.md:854-857,914` | OVE-169 |
| Capture custody bridge and fragment route | Acquired source custody becomes exact research fragments; public capture-fragment route | **integrated (service trace, Phase 0 run-5)**, not a Temporal mission | `f91e3fb`, `d355136`; `capture-bridge.test.ts`; `NEXT-SESSION.md:204-209` | OVE-169 |
| Exact task audience in evaluator context | Evaluator context keeps the task audience | **tested** | `187e7f6`; `assessment-resolution.test.ts`; `NEXT-SESSION.md:377-378` | none |
| W1 seal-key ceremony (D25) | `knowledge-db seal-key`, race-safe registration, typed `seal_key_*` refusal | **tested**; used by installers | `b7de34a`, `daa8970`, merge `22b47d2` | OVE-169 |
| W1 D19/D20 atomic registration | `report.register` preflights every record before any write; typed `EFFECT_CONFLICT` | **tested** | `a7eb76c`, `d82c919`, merge `f8d5e48` | OVE-169 |
| Reviewer grants | `knowledge-verify grant-reviewer`, least privilege, database clock | **tested** | `52e7d62`, `6446da0`, merge `1577c68` | OVE-169 |
| Evaluation context read + Biotech dispatch drain (WI-06) | `evaluation-context-read/v1`; biotech-graph drain of pending `knowledge.apply` dispatches (off unless `KS_BIOTECH_DISPATCH_DRAIN_INTERVAL_MS` set) | **tested** | `7e4ccb8`, `d06adc0`, `fc2b63c`, merge `c061e00` | OVE-169 |
| W0 live describe capture | `capture-live-describe.mjs`; remote describe capture at 2.5.0 | **integrated (W0 released with recorded limitations)** | `9cbcfe1`, `e4589f0`; `.../sprint-oc/release/RELEASE-BUNDLE.md:22,52,197` | OVE-168 |
| WI-05 native commit recovery, component 2.5.0 | Recover native commits across missing protocol receipts; migration 0008 | **integrated (installed on both W0 remote disposables)** | `5d5bcd8`, `704bdef`, `740df8c`, merge `9b52c08`; `RELEASE-BUNDLE.md:28,125-127` | OVE-167 |
| WI-03 trusted assessment / use decision | Report assessment, recorded use decisions, evaluator-role identity | **tested** | `7d12c0f`..`d51671b`, merge `0ef8889` | OVE-165 |
| WI-02 `readSelected` | Exact selected report read with declared purpose | **tested** | `b046088` | OVE-164 |
| R0/R5 backend registry | Frozen backend registration shape; capability-declared port; backend conformance | **tested** | `dc9ba27`, `3ba6834`, `0978a85` | OVE-195, OVE-199 |
| `mc.knowledge_request.v1` removed | Envelope added 10-24, deleted 10-27 (OC-D202) | implemented (deletion) | `25b2d29`, `7a9c8d0` | none |
| Sprint V research core, component 2.4.0, cutover | Protocol v2 host, research core, both bindings | **integrated** in Sprint V bundle (superseded by 2.5.0) | `ae59341`, `b45adf5`; MC ledger DOC-15 (`provider-consolidation-2026-10/LEDGER.md:95`) | OVE-150 |

## 4. Programs and specs

KS keeps no program ledger of its own; its live programs are rows in Mission Control ledgers.

| Program / spec | Status | Source |
| --- | --- | --- |
| Provenance sprint 2026-10-31 (SE-17, DOC-42) | active; report DOC-43 done | `provider-consolidation-2026-10/LEDGER.md:122-123,210` |
| Sprint OC control board (DOC-38) | active; W0 released, W1 open | `LEDGER.md:118`; `NEXT-SESSION.md:119-121` |
| Sprint OC W0 bundle (DOC-33) | active, W0 "released with recorded limitations" | `LEDGER.md:113`; `RELEASE-BUNDLE.md:22` |
| BellLabs Knowledge Platform spec (`docs/specs/belllabs-knowledge-platform/`) | authorized target (2026-10-10); Linear owns delivery status; no `status:` frontmatter | `docs/specs/belllabs-knowledge-platform/README.md`; `AGENTS.md` (Engineering planning) |
| Package cleanup (`docs/operations/package-cleanup/`) | reference handoff; Unit 5/6 slices not delivered | `docs/architecture/current-state.md` "Accepted target and unfinished work" |
| Agentic SDLC (OVE-205) | specified, implementation not started | `agentic-sdlc-2026-11/SESSION-NAVIGATION-QUALITY.md` |

## 5. Dirty files

None. `git status --short` is empty on 2026-11-01. (`node .agent-docs/cli.mjs check --repo .`
reports drift in the committed `.agent-docs/provenance.json`; that is stale content, not a dirty file.)

## 6. Candidate knowledge facts vs facts that stay in program documents

Candidate concept facts (implemented/tested, stable shape):
- `knowledge.read_intent` exists as a K01 result operation: native contract `knowledge-read-intent/v1`,
  eight named queries, tenant guard, read recorded in `knowledge_verification.operation`, refused reads
  record nothing, bodies withheld over 256 KiB (`read-intent.ts:14-44`; `read-intent-port.ts:31-39,116-129`).
  Belongs in `knowledge/schema-read-and-ingestion.md` or a new read concept.
- Apply writes receipt targets and `report_v2` rows in the same transaction; claims carry
  `producer_origin_digest`; error code is `PRODUCER_REQUIRED` (`2564226`).
- Component 2.5.0 owns the effect dispatch journal (0008); bindings require ≥ 2.5.0.
- Backend registry: capability-declared ports and the backend conformance suite (R5).
- Seal-key ceremony and typed `seal_key_*` refusal; reviewer grants are least-privilege.

Stay in program documents (integration/qualification claims, run evidence, dated state):
- Run `source-mc-origin-01` evidence, spend, 29 effects, closures (REPORT.md).
- W0 release receipts and installation ids; W1 status; fixture pass/fail histories.
- Unpushed-commit counts, custody/recovery refs, the plan_preview defect until fixed (then a concept
  can state the corrected rule).

## 7. Doc-vs-code discrepancies

1. `docs/architecture/current-state.md:23` says component **2.4.0** and vendored contract head
   `20261025010000`. Code: component 2.5.0 (`release-spec.json:3`, `component-backend.ts:83`); the
   W0 bundle records AIDB head `20261025010200` (`RELEASE-BUNDLE.md:30`); AIDB head is now
   `20261031010000`.
2. `AGENTS.md:32` says retrieval read ops are skipped and ingestion does not write
   `knowledge_service.operation`. Still true for the bounded executor, but the guide and `knowledge/`
   say nothing about the K01 `knowledge.read_intent` that *does* record reads (in
   `knowledge_verification.operation`). Name collision: the older bounded `knowledge-read-intent.v1`
   (`knowledge/schema-read-and-ingestion.md:58`) versus the K01 contract `knowledge-read-intent/v1`
   (`read-intent.ts:29`).
3. Vendored contract: `packages/knowledge-db/package.json:19` (also `packages/persistence`,
   `apps/verification-executor`) points at `vendor/aiengineer-database-contract-0.5.0.tgz`, which is
   gitignored (`.gitignore:87`; only 0.4.16 is tracked). The local tarball (2026-10-25) has no
   `operation_receipt_target`, while `receipt-targets.ts:32` inserts into it. A fresh clone cannot
   install; slice-3 SQL is not backed by the pinned types.
4. `.agent-docs/provenance.json`: `provenance-2026-10-31/CHANGES.md:29` says it is rebuilt at sprint
   close; the check run today reports drift (`REPORT.md:95` concedes it was not). REPORT says there is no
   rebuild script; `AGENTS.md` documents `node .agent-docs/cli.mjs build --repo .`.
5. `docs/specs/belllabs-knowledge-platform/CURRENT-STATE.md` is a 2026-10-10 snapshot; it is labelled as
   such, but `AGENTS.md` routes to it without a date warning.
6. Protocol package stays 2.0.0 although `knowledge.read_intent` changed the envelope and golden vectors
   (`6a4dd30` touched `operation-envelope.v2.schema.json` and the golden file).
