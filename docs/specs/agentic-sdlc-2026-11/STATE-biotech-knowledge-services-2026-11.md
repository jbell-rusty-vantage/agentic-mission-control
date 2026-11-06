---
type: Working Draft
title: "State inventory: biotech/biotech-knowledge-services (sprint-oc, 2026-11-01)"
description: "What Biotech Knowledge Services built since 2026-10-20 on sprint-oc, each item labelled implemented / tested / integrated / qualified with its proof path; schema release and pins with file:line; active programs; dirty files; candidate knowledge facts; doc-versus-code discrepancies. Input to Sitting II, item 1."
tags: [biotech-knowledge-services, agents, sdlc, state]
date: 2026-11-01
status: draft
---

# State inventory: Biotech Knowledge Services (BKS)

Repository `biotech/biotech-knowledge-services`, branch `sprint-oc`, HEAD `8e8d3d1` (2026-10-29),
level with `origin/sprint-oc` (local tracking ref, no fetch made). No BKS commit since 2026-10-29: the
2026-10-31 provenance sprint did not touch BKS. Label meanings follow
`platform/mission-control/docs/specs/provider-consolidation-2026-10/sprint-oc/provenance-2026-10-31/REPORT.md:64-65`.
**Nothing here is qualified.**

## 1. What remains toward the goal for this repository

- Biotech W1 has not run; W2-W4 are unqualified (`.../sprint-oc/NEXT-SESSION.md:121`). The Qualia
  fixtures used standalone KS roles and do not qualify the production per-invocation Biotech authority
  mapping (`NEXT-SESSION.md:93-96`).
- The Biotech mirror of provenance slices 3 and 4 is not started: run id, generation and lane on
  `RunContextV2` and the Activity node; mission coordinates in the admission payload; a Biotech
  read-intent port over the BKS `/kg/read` client (`REPORT.md:20,87-88`). The KS `biotech-graph`
  binding has no `read_intent` capability.
- The Qualia native-intent helper that the fixtures depend on is untracked (section 5); the board asks
  to preserve it (`NEXT-SESSION.md:97`), so it needs a commit-or-retire decision.
- Deployment truth for `biotech-schema-v2.2.0` is contradictory across documents (section 7).

## 2. Versions

| Thing | Version | Source |
| --- | --- | --- |
| Pinned schema release (the "BKS SDL") | **`biotech-schema-v2.2.0`**, `version` 2.2.0, status `frozen`, pinned 2026-10-25 | `schema/pinned/PIN.json:3,20`; `schema/pinned/release/release.json:827` |
| Release digest / DDL digest | `sha256:2df9d3bc…5a74` / `sha256:f0622dba…ddb3` | `schema/pinned/PIN.json:4,7` |
| Parent release | `biotech-schema-v2.1.0` | `release.json` `parentRelease` |
| Pin format / release format | `bks-pin.v2` / `bks-schema-release.v1` | `PIN.json:2`; `release.json` `releaseFormat` |
| Pin provenance | `sourceHead` `3ea0148`, `sourceReleaseDirClean: false` | `schema/pinned/PIN.json:16-18` |
| Size | 69 node types, 106 relationship types | `README.md:5` |
| KS component pin (installer) | 2.5.0, `sha256:00550d59…8b88` | `scripts/install-biotech.mjs:77` |
| Mission Control common release pin (installer) | 1.9.0, lock `sprint-oc/release/locks-190` | `scripts/install-biotech.mjs:80-89` |
| Native contracts in the release | apply/plan/receipt `…v2`, typed read `biotech-knowledge-read-intent.v2`, cypher read `…v1` | `release.json` `contractVersions.nativeContracts` |
| Admission and v3 read contracts (SV-11) | `biotech-knowledge-admission.v1` (+ ack, consume), `biotech-knowledge-read-intent.v3` / `-read-result.v3` | `docs/plans/schema-v2-service-release/STATUS.md:32` |
| npm packages (root, contracts, kg-ops, schema-workspace, apps) | all 0.1.0 (not used as release identity) | `package.json:3`; `packages/*/package.json:3`; `apps/*/package.json:3` |
| Deployed graph per README | `biotech-schema-v2.0.2` (2026-10-12) | `README.md:186` (contested, section 7) |

## 3. Recent work (since 2026-10-20; 18 commits incl. merges, about 2,630 file-changes, mostly generated release/workspace)

| Item | What it is | Label | Proof path | Linear |
| --- | --- | --- | --- | --- |
| Schema authoring moves into BKS; v2.1.0 source + release | SV-D10: BKS becomes schema author; `schema/source/biotech-schema-v2.1.0/` from verified v2.0.2 inputs | **tested** (generate `--check` v2.1.0 regenerates unchanged) | `3ea0148`; `STATUS.md:31` | OVE-150 |
| `biotech-schema-v2.2.0` pin (SV-11) | `ReportKind.STUDY_APPRAISAL`; `useDecisionDigest` on Activity/Assessment; KsIntentMarker dispatch indexes; no label/relationship change | **integrated** (graph-release applied to Aura `8032ec07` in the W0 remote reinstall, 2026-10-28) | `c398177`; `PIN.json`; `RELEASE-BUNDLE.md:31,80,125` (receipts in BKS ignored `.scratch/sprint-oc/evidence/`) | OVE-150, OVE-168 |
| Admission dispatch consumer (SV-11) | `packages/kg-ops/src/admission/*`; `applyAdmittedV2` in the single apply transaction; `POST /kg/admission/dispatch/consume`; CLI `bks admission consume --once` | **tested** (T0 `dispatch.test.ts` 15/15; T1 `dispatch.integration.test.ts` 9/9 on disposable Neo4j 5.26 + PG17 with component 2.1.0) | `c398177`; `STATUS.md:33`; receipts `.scratch/sprint-v/proofs/SV-11/run-1/` (ignored) | OVE-150 |
| Eligibility-aware official reads (v3) | Typed reads with `marker` op revalidated against the component; authority unavailable holds | **tested** (T0 + T1 eligible / revoked / unavailable) | `c398177`; `STATUS.md:34` | OVE-150 |
| Installer wipe step + remote-reinstall confirm-target gate (WI-24) | All-or-nothing wipe, dry-run bound to graph host, strict cascades, identity evidence | **integrated** (W0 wipe/dry-run receipts, 832 graph nodes dropped) | `7fa0afb`, `d7ad384`, `de25df0`, `ac2dec4`; `RELEASE-BUNDLE.md:123-124` | OVE-168 |
| KS 2.5.0 and MC 1.7.0 pins | Single `KS_COMPONENT_PIN` line; MC 1.7.0 locks | **integrated** (W0 fresh install, upgrade applying 0008 only, repeat `changed: false`) | `6971fed`, `9a15727`, `1e17036`; `RELEASE-BUNDLE.md:50,125-127` | OVE-168 |
| Component-grants step | Component login may SET the bounded `knowledge_verification` roles | **integrated** (W0 installer commit recorded) | `9902ea7`, merge `a43f325`; `scripts/install-target.test.mjs`; `RELEASE-BUNDLE.md:50` | OVE-168 |
| MC 1.8.0 and 1.9.0 pins | Sprint OC W1 target locks (`locks-180`, `locks-190`) | **tested** (`install-target.test.mjs`); 1.8.0 is the installed W1 state per installer comment | `1ee1655`, `e23af2d`; `scripts/install-biotech.mjs:80-89` | OVE-169 |
| Seal-key installer step (W1 D25) | Registers the KS executor's seal key; required on remote reinstall; scrubbed error tails | **tested** (`install-target.test.mjs`) | `d69f863`, `4e7573a`, merge `8e8d3d1` | OVE-169 |
| Qualia native-intent fixture helper (untracked) | Builds `biotech-knowledge-intent.v2` from retained source text for the Qualia StageGraph fixtures; partial-schema selection over v2.2.0 labels | **tested, uncommitted** (`native-intent.test.ts`; board reports "BKS projection checks 18", mapping to this file not verified) | `scripts/fixtures/qualia/README.md`; `NEXT-SESSION.md:66-97` | none (OVE-162 board) |
| Biotech mirror of provenance slices 3/4 | RunContextV2/Activity coordinates, admission coordinates, read-intent port | **not started** | `REPORT.md:87-88` | OVE-204 (follow-up) |

## 4. Programs and specs

| Program / spec | Status | Source |
| --- | --- | --- |
| Schema v2 service release (S0-S9) | S1-S4 `verified`, v2.0.2 deployed 2026-10-12; SV-11 section says "implemented … not deployed, not committed" (stale) | `docs/plans/schema-v2-service-release/STATUS.md:5-12,25-38` |
| v2 release handoff | dated 2026-10-12; open items: 30-minute soak, legacy secret hygiene, custody bucket, Git | `docs/plans/schema-v2-service-release/HANDOFF.md:7-21` |
| Historical schema program (`schema/program/`) | historical | `AGENTS.md:24` |
| Sprint OC (MC ledger): W0 bundle DOC-33 active; Biotech schema card DOC-28 active | W0 released with limitations; Biotech W1 not run | `provider-consolidation-2026-10/LEDGER.md:108,113`; `NEXT-SESSION.md:121` |
| Provenance sprint (SE-17) | BKS slices (mirror) open | `LEDGER.md:210`; `REPORT.md:87-88` |
| Biotech entity/process and source/capability optimization | deferred to a dedicated effort | `NEXT-SESSION.md:29` |

## 5. Dirty files

Untracked directory `scripts/fixtures/qualia/` (7 files):
`README.md`, `generate-vocabulary.ts`, `native-intent.ts`, `native-intent.test.ts`,
`native-vocabulary.json`, `partial-schema.json`, `schema-template.json`. No modified tracked files.

## 6. Candidate knowledge facts vs facts that stay in program documents

Candidate concept facts (implemented/tested, stable shape):
- BKS is the schema author (SV-D10); a release is authored under `schema/source/<release>/`, generated
  and pinned with `scripts/release/*.mjs` and `pnpm schema:pin`; the pin is byte-verified on every load
  (`AGENTS.md:10`).
- v2.2.0 content: `STUDY_APPRAISAL` report kind, `useDecisionDigest`, KsIntentMarker dispatch fields
  and indexes; PostgreSQL (the KS component) owns runs, decisions and the outbox, the graph holds immutable
  references (`release.json` `description`).
- Admission: dispatch consume endpoint and CLI, single apply transaction under `KsIntentMarker`
  (`AGENTS.md` ground rules; `STATUS.md:33`).
- Official v3 reads revalidate eligibility against the component and hold when authority is unavailable.
- The installer is the only path that applies component, MC release, graph release and seal key; it
  refuses unconfirmed remote targets.

Stay in program documents:
- Which Aura instance holds which release and when (deployment claims need fresh evidence).
- W0 receipts, installation ids, wipe counts; Qualia fixture outcomes (claims, effects, readback).
- Open KS-side items for admission (outbox terminal outcome, `claim_dispatches` filter, reader-callable
  exact-use, durable acknowledgment) until resolved (`STATUS.md:38`).

## 7. Doc-vs-code discrepancies

1. **Deployment of v2.2.0.** `README.md:186` ("v2.1.0 and v2.2.0 are repository pins, not
   deployments") and `AGENTS.md:10` ("v2.2.0 is pinned … not deployed") versus the W0 bundle: the
   Biotech remote reinstall applied `graph-release` to Aura `8032ec07` on 2026-10-28
   (`RELEASE-BUNDLE.md:80,121,125`), and the Qualia fixtures wrote to that graph (`NEXT-SESSION.md:61,70`).
   The Qualia README hedges ("neither a schema migration nor evidence that remote Aura has that release
   installed"). Not re-verified live in this inventory.
2. `STATUS.md:27` says SV-11 is "not committed" on branch `main`; it is committed (`c398177`) and the
   repo is on `sprint-oc`.
3. `HANDOFF.md:10,19` says "Nothing is committed anywhere" and "BKS has no remote"; `origin` exists
   (`Overton77/biotech-knowledge-services`) and `sprint-oc` tracks it. `AGENTS.md:24` still routes to this
   file as the "Current v2 release handoff" (with a fresh-verification caveat).
4. `PIN.json:16-18`: the v2.2.0 pin records `sourceHead` `3ea0148` (the v2.1.0 authoring commit) and
   `sourceReleaseDirClean: false`, so the pinned bytes were produced from an uncommitted source tree; the
   source was committed later in `c398177`.
5. `STATUS.md:36` reports 1 pre-existing failure and 3 failed files from the absent `../biotech-meta`
   release-override tests; `AGENTS.md:10` calls `biotech-meta` "not a blocker". The suite is therefore not
   green as committed.
6. Release identity lives only in `release.json:827`/`PIN.json:3`; every npm package stays 0.1.0, so no
   package version distinguishes a v2.0.2 build from a v2.2.0 build.
