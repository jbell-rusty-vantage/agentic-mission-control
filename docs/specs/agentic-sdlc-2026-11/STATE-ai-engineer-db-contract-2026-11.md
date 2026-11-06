---
type: Working Draft
title: "State inventory: aiengineer/ai-engineer-db-contract (sprint-oc, 2026-11-01)"
description: "What the AI Engineer database contract (AIDB) built since 2026-10-20 on sprint-oc, each item labelled implemented / tested / integrated / qualified with its proof path; contract version, migration head and pins with file:line; active programs; dirty files; candidate knowledge facts; doc-versus-code discrepancies. Input to Sitting II, item 1."
tags: [ai-engineer-db-contract, agents, sdlc, state]
date: 2026-11-01
status: draft
---

# State inventory: AI Engineer database contract (AIDB)

Repository `aiengineer/ai-engineer-db-contract`, branch `sprint-oc`, HEAD `44c980c` (2026-10-31),
local branch **ahead of `origin/sprint-oc` by 1 commit** (the slice-3 migration is unpushed; local
tracking ref, no fetch made). Label meanings follow
`platform/mission-control/docs/specs/provider-consolidation-2026-10/sprint-oc/provenance-2026-10-31/REPORT.md:64-65`.
**Nothing here is qualified.** Never write the AI Engineer Aura graph `4773dc72`; nothing below did.

## 1. What remains toward the goal for this repository

- Migration `20261031010000_operation_receipt_targets` exists only on the local disposable
  `supabase_db_disposable-overnight-20261029`. Applying it to the remote AI Engineer project is
  owner-gated: "when quality ingestion starts" (`REPORT.md:82-84`; `docs/knowledge-model/SCHEMA-SUMMARY.md:45-47`).
- W1 qualification against coordinated builds is open (`.../sprint-oc/NEXT-SESSION.md:119-121`).
- The contract version did not move with the schema (still 0.5.0), and KS consumes a gitignored 0.5.0
  tarball that predates slice 3 (section 7). Until the version is bumped and re-vendored, consumers
  cannot pin the slice-3 schema.
- The documented contracts lag the schema: `docs/schema-workspace/INTENT_AND_EXECUTOR_CONTRACTS.md` has
  no `targets`/`origin_digest`, and the assertion-subject projection path has no test (`REPORT.md:95-97`).

## 2. Versions

| Thing | Version | Source |
| --- | --- | --- |
| Contract package `@aiengineer/database-contract` | **0.5.0** | `package.json:2-3` |
| Migration head | **`20261031010000`** (`…_operation_receipt_targets.sql`); 187 migration files in `supabase/migrations/` | `scripts/install-manifest.json:6,16`; `supabase/migrations/` listing |
| Head at the W0 release | `20261025010200` (186 migrations), contract 0.5.0 | `.../sprint-oc/release/RELEASE-BUNDLE.md:30` |
| KS component pin (installer) | 2.5.0, `sha256:00550d59…8b88` | `scripts/install-ai-engineer.mjs:67` |
| Mission Control common release pin (installer) | 1.9.0, release root `packages/mission-control-db-contract/releases/1.9.0/component`, lock `locks-190` | `scripts/install-ai-engineer.mjs:75-84` |
| Install manifest format | `ai-engineer-wipe-manifest.v1`, 19 schemas | `scripts/install-manifest.json` (`format`, `schemas`) |
| Last cloud-deployed contract documented in README | 0.4.0, head `20260913020000` | `README.md:14` |
| Packed tarballs in tree | 0.2.7, 0.2.11, 0.3.0, 0.4.6 (no 0.5.0) | repository root listing |

## 3. Recent work (since 2026-10-20; 18 commits incl. merges, about 2,302 file-changes, mostly regenerated `workspace/`)

| Item | What it is | Label | Proof path | Linear |
| --- | --- | --- | --- | --- |
| Receipt targets, MC coordinates, `mission_run_effects` (provenance slice 3) | `origin_digest`/`origin_kind` and `mc_*` coordinates on `orchestration.operation_intent`; `origin_digest` on `operation_receipt`; table `orchestration.operation_receipt_target` (written in the apply transaction, forced RLS); `evidence.claim.producer_origin_digest` with `claim_producer_identity` (attempt now optional); view `orchestration.mission_run_effects` | **integrated (disposable)**: live run `source-mc-origin-01` produced 29 `mission_run_effects` rows | `44c980c`; `supabase/tests/operation_receipt_targets.sql`, `research_report_v2_projection.sql`; `npm test` 15/15; `provenance-2026-10-31/CHANGES.md:13-29`; `REPORT.md:35,58` | OVE-204 |
| KS→AIDB disposable ingestion, AI Engineer StageGraph fixtures (2026-10-31) | Seven-stage Deep Agents StageGraph runs on GitHub/arXiv/Context7 sources; admitted exact-use `knowledge.apply` into the disposable AIDB; last fork wrote a paper, a repository, a technique and three relationships, 17/17 rows read back | **integrated (fixture, disposable)**; no AIDB commit (schema consumed as-is) | `NEXT-SESSION.md:33-46`; KS `3e3d8a7`/`8a38b0f`; MC driver `scripts/aieng_stagegraph.py`; private `.scratch/aieng-stagegraph-2026-10-31/INDEX.md` (MC) | none in commit (board OVE-162) |
| Installer wipe step + remote-reinstall confirm-target gate (WI-24) | Manifest-bounded, all-or-nothing wipe; dry-run; kept extras hold; legacy identity evidence bound to the database; Supabase test stub isolation | **integrated** (W0: wipe of remote disposable `wkythqbofmckbuoothhn`, 18 domain schemas + 41 `public` tables dropped; fresh install `changed: true`) | `17c7821`..`1a2c0a0`; `scripts/install-target.test.mjs`; `RELEASE-BUNDLE.md:123-127` | OVE-168 |
| KS 2.5.0 pin and MC 1.7.0 pin | Single `KS_COMPONENT_PIN` line; MC 1.7.0 locks | **integrated** (W0 upgrade applied 0008 only, repeat `changed: false`) | `1dbc810`, `17d57f8`, `0d49bb5`; `RELEASE-BUNDLE.md:49,126-127` | OVE-168 |
| MC 1.8.0 and 1.9.0 pins | W1 target locks; 1.8.0 upgrades in place with 0066/0067 | **tested** (`install-target.test.mjs`) | `edba7bf`, `b2cfff0`; `install-ai-engineer.mjs:75-84` | OVE-169 |
| Seal-key installer step (W1 D25) | Pins the public half of the KS run-seal key in `knowledge_verification.seal_signing_key`; required on remote reinstall | **tested** | `d6d5a38`, `0e02009`, merge `74fd2c3`; `README.md:42-47` | OVE-169 |
| Sprint V cutover, contract 0.5.0 | `20261025010000_withdraw_legacy_verification_truth` (legacy verification truth moves to the KS component); `report_v2` projection and guards; forced RLS; root installer | **integrated** (installed on the W0 remote disposable at head `20261025010200`) | `25f82ed`, `306efd7`; `README.md:16-27`; `RELEASE-BUNDLE.md:30,125` | OVE-150 |

## 4. Programs and specs

AIDB keeps no program ledger of its own; its live programs are rows in Mission Control ledgers.

| Program / spec | Status | Source |
| --- | --- | --- |
| Provenance sprint 2026-10-31 (SE-17, DOC-42) | active; remote apply of 20261031010000 owner-gated | `provider-consolidation-2026-10/LEDGER.md:122,210`; `REPORT.md:82-84` |
| Sprint OC W0 bundle (DOC-33) and runtime environment (DOC-32, DOC-35) | active; W0 released with recorded limitations | `LEDGER.md:112-115`; `RELEASE-BUNDLE.md:22` |
| AI Engineer schema card (DOC-27) | active, source evidence only | `LEDGER.md:107` |
| Schema workspace materialization spec | accepted (per generated guide) | `AGENTS.md` task routes; `docs/SCHEMA_WORKSPACE_MATERIALIZATION_SPEC.md` |
| Experiment 3 A/B/C protocol | reference; claims no run has occurred | `AGENTS.md` task routes; `docs/schema-workspace/EXPERIMENT_PROTOCOL.md` |
| Sprint V (OVE-150) | AIDB half integrated; superseded by Sprint OC pins | `LEDGER.md:91-95` |

## 5. Dirty files

None. `git status --short` is empty on 2026-11-01; `node .agent-docs/cli.mjs check --repo .` is clean
(38 inputs).

## 6. Candidate knowledge facts vs facts that stay in program documents

Candidate concept facts (implemented/tested, stable shape):
- "Everything run X produced" is one query:
  `select * from orchestration.mission_run_effects where mc_run_id = $1` (intent → receipt → target;
  security invoker; `executor_service`, `control_plane`) (`SCHEMA-SUMMARY.md:52`).
- `operation_receipt_target` holds one immutable row per native row a receipt created, reused,
  superseded or staged, with a role (`subject`, `canonical`, `supporting`, `provenance`, `staging`,
  `projection`) (`SCHEMA-SUMMARY.md:50`).
- A claim needs a producer identity: `producer_attempt_id` or `producer_origin_digest`
  (`SCHEMA-SUMMARY.md:51`).
- Verification truth lives in the KS `knowledge_verification` component, not in AIDB; a claim is
  `verified` only under a receipt bound to an admitted use decision; v1 report projection is closed
  (`README.md:18-27`).
- `scripts/install-ai-engineer.mjs` is the only release/fresh-install path; the component must be
  installed before the AIDB migrations (`AGENTS.md`; `README.md:29-31`).

Stay in program documents:
- Which databases hold which head (remote disposable at `20261025010200`; local disposable at
  `20261031010000`), W0 receipts and installation ids, wipe counts.
- Fixture outcomes (rows written, readback counts, spend), the plan_preview NOT NULL gap until KS fixes it.
- The credential rotation follow-up (`REPORT.md:80-81`); never in a concept.

## 7. Doc-vs-code discrepancies

1. `README.md:16` heads the section "Contract 0.5.0: Sprint V cutover (unreleased working tree)". It is
   committed (`25f82ed`, `306efd7`) and was installed on the W0 remote disposable
   (`RELEASE-BUNDLE.md:30,125`).
2. `README.md:20` says the KS component is "pinned **2.4.0**"; the installer pins 2.5.0
   (`scripts/install-ai-engineer.mjs:67`), and the same README says 2.5.0 at `README.md:42`.
3. One version, two schemas: `package.json:3` stays 0.5.0 across `20261025010200` and
   `20261031010000`. KS vendors `aiengineer-database-contract-0.5.0.tgz` (gitignored in KS, dated
   2026-10-25) whose generated types lack `operation_receipt_target`, while KS writes that table
   (KS `packages/knowledge-db/src/ingestion/receipt-targets.ts:32`). The AGENTS.md rule "consumers pin the
   contract" cannot hold for slice 3.
4. `README.md` never mentions head `20261031010000`; only `SCHEMA-SUMMARY.md:45` does (marked
   "disposable only").
5. `docs/schema-workspace/INTENT_AND_EXECUTOR_CONTRACTS.md` has no `targets`, `report` or
   `origin_digest` receipt fields (0 matches), though the executor now writes them (`REPORT.md:96`).
6. The Sprint OC board's gap list (`NEXT-SESSION.md:46`, "no production MC→AIDB producer-attempt
   projection") predates slice 3, which closed it on the disposable via `producer_origin_digest` and
   `mc_*` coordinates; the board line was not updated.
7. `README.md:12-14` describe contracts 0.3.0/0.4.0 as the cloud deployments. The README does not say
   that the W0 wipe (2026-10-28) dropped those schemas on `wkythqbofmckbuoothhn` and reinstalled at 0.5.0
   (`RELEASE-BUNDLE.md:124-125`). Whether that project is the same "identified cloud project" was not
   verified here.
