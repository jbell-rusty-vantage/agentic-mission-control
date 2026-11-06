---
type: Working Draft
title: "Mission Control state inventory on sprint-oc, 2026-11"
description: "Preparation item 1 of sitting II for Mission Control: what remains to the Deep Agents goal, versions with file:line, the recent work labelled implemented / tested / integrated / qualified with proof paths, programs by ledger status, dirty files, concept-eligible facts versus program-only facts, and stale claims found against code and git."
tags: [mission-control, agents, sdlc, state]
date: 2026-11-01
status: draft
---

# Mission Control state inventory (sprint-oc, 2026-11-01)

Read from `sprint-oc` HEAD `ce9d2f13` (equal to `origin/sprint-oc`, 262 commits ahead of `main`
`3e5043ed`). Paths are relative to `platform/mission-control/` unless they start with a repository name.
Labels follow the provenance report's definitions (`sprint-oc/provenance-2026-10-31/REPORT.md:64-65`):
**implemented** = in source on the branch; **tested** = unit/PostgreSQL tests recorded as passing;
**integrated** = exercised through the real composed path against a disposable target on this host;
**qualified** = a released W-gate. Nothing here was rerun; labels rest on the cited records and commits.
`NS` = `docs/specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md`; `PC` =
`docs/specs/provider-consolidation-2026-10/`; `PROV` = `PC/sprint-oc/provenance-2026-10-31/`.

## 1. What remains to reach the goal

- Nearest unmet checkpoint: **W1 qualification** (OVE-169) on coordinated MC/KS builds for both
  applications. W1 is unreleased; the last AI Engineer W1 run failed fulfillment; D27–D30 fixes are
  locally integrated but the full regression and real rerun remain; **Biotech W1 has never run** (NS:119-121).
- Sprint OC is paused: it resumes only after the Agentic SDLC program merges (NS:11-15).
- Open proof inside the Deep Agents path: live `knowledge_read_intent` (PROV/REPORT.md:36), charter mount
  in a launched node (REPORT.md:38), production MC→AIDB producer attribution and the KS typed-column
  planner fix (NS:44-47, NS:188), Biotech mirror of provenance slices 3–4 (REPORT.md:87-88).
- Not installable yet: releases 1.10.0–1.12.0, agent-skills 1.0.4, knowledge-tools 1.2.0 have no remote
  install or deployment lock (REPORT.md:82-84); WI-13 nested bodies and B3 native plan decisions sit in an
  unreleased migration directory whose keys collide with released ones (§7 D5).
- Then W2–W4, W5/OVE-186, Swarm/EO (unreviewed recovery homes) and stress (NS:771-773, NS:139-140).

## 2. Versions

| What | Value | Where |
| --- | --- | --- |
| Common component, newest built | **1.12.0** (last key `0070_workspace_closure`; fingerprint `sha256:729c2e9d…4cce`) | `packages/mission-control-db-contract/releases/1.12.0/component/release-spec.json:21`, `…/manifest.json:328,366` |
| Built, earlier | 1.10.0 (`0068_exact_linked_exports`), 1.11.0 (`0069_linked_export_family_writer`) | `releases/1.10.0/`, `releases/1.11.0/`; commit `abac1fde` |
| Newest deployment locks | 1.9.0 | `PC/sprint-oc/release/locks-190/ai-engineer/release.lock.json:4`, `…/biotech/release.lock.json:4` |
| W0 release locks | 1.7.0 | `PC/sprint-oc/release/locks/ai-engineer/release.lock.json:4`; `RELEASE-BUNDLE.md:29` |
| Installed on both remotes | 1.8.0 (with tenants and logins) as of 2026-10-28; 1.9.0 remote install **unverified** | `PC/sprint-oc/HANDOFF-2026-10-28-S3.md:4,42` |
| `deployments/<app>/release.lock.json` | 1.4.2 (AI Engineer), 1.3.0 (Biotech) — stale, known | `deployments/ai-engineer/release.lock.json:4`, `deployments/biotech/release.lock.json:4`; `RELEASE-BUNDLE.md:41` |
| Retired root component | 1.4.0, never a build source | `packages/mission-control-db-contract/component/manifest.json:9`; `releases/README.md:3-8` |
| Python distributions | `mission-control` 0.1.0; `mission-control-db-contract` 1.0.0 (not release numbers) | `pyproject.toml:7`; `packages/mission-control-db-contract/pyproject.toml:7` |
| Seeds, newest | agent-skills 1.0.4 (both apps; not frozen under `bundle-sources/`, last frozen 1.0.3); knowledge-tools 1.2.0; workflow-parity 1.0.5; runtime-profiles 1.0.1; artifact-schemas 1.0.1; storage mission-payloads 1.0.0 | `packages/mission-control-db-contract/seeds/{ai-engineer,biotech,common}/`; `docs/knowledge/capability-seeds.md:21-27` |
| Provider pins | deepagents 0.7.5; langchain 1.3.14; langgraph 1.2.10; langgraph-api 0.12.0; temporalio >=1.34,<2 | `pyproject.toml:18,26,32,33,55` |
| Companions (W0 bundle) | KS knowledge_verification 2.5.0; AIDB contract 0.5.0; BKS biotech-schema-v2.2.0 | `PC/sprint-oc/release/RELEASE-BUNDLE.md:4` |
| Companion heads now | KS `6a4dd30` (clean); AIDB `44c980c` (clean, head migration `20261031010000`); BKS `8e8d3d1` (1 dirty path) | `git rev-parse` on each `sprint-oc`; `PROV/CHANGES.md:20` |

## 3. Recent work (since 2026-10-20)

Git: 299 commits (45 merges) since 2026-10-20, concentrated on 10-27 (94), 10-28 (96), 10-29 (52);
10-30 (11), 10-31 (12), 11-01 (2, docs only). Phases: tracing/Deep Agents turns 3–8 (10-20..23), Sprint V
(10-24..25), Sprint OC R0–R7 and WI merges (10-27..28), W0 release and W1 D1–D30 repair loop (10-28..29),
recovery/consolidation and overnight workflows (10-29..30), Qualia/AI Engineer fixtures, Selection
Workspace and provenance sprint (10-31), Agentic SDLC docs (11-01).

| Item | What it is | Label (highest proven) | Proof path | Linear |
| --- | --- | --- | --- | --- |
| Sprint OC W0 | Four-owner schema fit, installs on disposable remotes, refusals, seeds, live describe 15/15 | **qualified** (W0 released *with recorded limitations*) | `PC/sprint-oc/release/RELEASE-BUNDLE.md:22,198`; `c1087d90` | OVE-168 |
| Sprint OC W1 | First ordinary GoalDirected report per app; D1–D30 fixes | integrated (fixes, local); **W1 not qualified** | NS:119-121; `release/W1-EVIDENCE.md:20`; merges `b494b810`…`f9168027` | OVE-169 |
| R0–R7 selection/routing seam | Resolution seam, lane/model/app registries, Model Catalog, agent-skills 1.0.3 | tested (merged 10-27) | `cb7faf4a`, `2a905506`, `50498d67`; ADR-0063 | OVE-194..202 |
| WI-07 / WI-08 | Report collections and current sets; explicit graph routes, release groups, revisit regions | tested (incl. PostgreSQL) | `2f8523d1`, `76a3fd39`; `docs/knowledge/collections-and-current-sets.md:123` | OVE-170, OVE-171 |
| WI-19 / WI-23 | Coordinator attention and inspection; sealed async child bindings | tested | `958957e6`, `6cd793a7` | OVE-182, OVE-184 |
| WI-13 nested bodies | Nested family bodies as child runs | tested; migration **unregistered** (not installable) | `159f38d4`; `scripts/release_200/0068_nested_program_activations.sql`; `docs/knowledge/recursive-composition.md:82` | OVE-176 |
| B3/B3-R native write | Fresh preview, redecision, receipt-first recovery | integrated (focused restart proof); 0069 migration unreleased | NS:856-895; `ecdba045`, `f3274e77`; `tests/integration/postgres/test_native_plan_decisions_postgres.py:34` | OVE-169 |
| Overnight workflows | StageGraph, GoalDirected, same-app linked chains, scripted cognition over real PG/Temporal | integrated (local; model spend USD 0) | NS:217-416; `965e7aa5`, `d2378a0c`, `29acf3f7`, `abac1fde`, `6f4eb9c6`; private `.scratch/overnight-2026-10-29-a/INDEX.md` | OVE-162 (SE-16) |
| Releases 1.10.0 / 1.11.0 | Exact linked exports; family-writer export grant | integrated locally (fresh + upgrade, 10 checks); no remote install | NS:285-312, NS:399-408 | OVE-162 |
| Qualia Biotech fixtures | Seven-stage Deep Agents StageGraph, KS verification, Aura `8032ec07` writes, queued/inject, Tavily fork | integrated (live paid models, disposable/registered targets); not qualified | NS:66-98; `0eccfa2d`; private `.scratch/qualia-stagegraph-2026-10-30/READ-FIRST.md` | none found |
| AI Engineer fixtures | GitHub/arXiv/Context7 StageGraph, KS repair, exact-use apply to disposable AIDB | integrated (USD 40.94 spent) | NS:32-47; `e8eea445`, `3e974b75`; private `.scratch/aieng-stagegraph-2026-10-31/` | none found |
| Selection Workspace | `missionctl search`, `workspace check`, MCP `mission_search`/`selection_check`, HTTP | tested (unit, in-memory ports only) | `016d27a1`, `79525ed4`; `tests/unit/selection/` (16 test functions; NS:51-52 says 21); `docs/knowledge/selection-workspace.md:33` | none found |
| Provenance slice 1 | True origin: ledger mission id, real activation id, unit key | integrated (live run) | `PROV/REPORT.md:33,56`; `03f11594` | OVE-204 |
| Provenance slice 2 | AI Engineer fixture through the production gateway | integrated (live run) | REPORT.md:34,57; MC `03f11594`, KS `5727a4b` | OVE-204 |
| Provenance slice 3 | AIDB receipt targets, `report_v2` writer, `mission_run_effects` | integrated (29 effects) | REPORT.md:35,58; AIDB `44c980c`, KS `2564226` | OVE-204 |
| Provenance slice 4 | `knowledge.read_intent` | KS integrated on disposable; **MC tested only** (0 live rows) | REPORT.md:36,59 | OVE-204 |
| Provenance slice 5 | Workspace closure; db-contract 1.12.0 | integrated (8 closures in live run) | REPORT.md:37,60 | OVE-204 |
| Provenance slice 6 | Knowledge charter skills, agent-skills 1.0.4, default mount | tested (local bundle publish; not mounted live) | REPORT.md:38,61 | OVE-204 |
| Provenance slice 7 | S3 endpoint, mission-payloads bucket | integrated at smoke level (local Supabase S3 round trip, not in a mission) | REPORT.md:39,62; private `.scratch/provenance-2026-10-31/s3-roundtrip.json` | OVE-204 |
| Agentic SDLC sitting I and II prep | SPEC-01, ADR-0064..0067, interview instrument, grammar draft | documents only (below implemented) | `7ca4f550`, `ce9d2f13` | OVE-205, OVE-206 |

Failed or partial runs retained: provenance Tavily fork refused by the fixture model ledger
(REPORT.md:46-50); Qualia fork04 refusal (NS:81). Known red checks: three stale owner-manifest goldens in
`tests/unit/authoring/test_manifest_compile.py` (REPORT.md:94-95); broad mypy over imported legacy test
helpers, 188 errors in 14 files (NS:244-246); broad legacy failures "not presented as green CI" (NS:89-90).

## 4. Programs by ledger status

`python docs/tools/program_ledger.py check` passes for all four ledgers (109, 6, 2 and 19 rows, 0 problems)
at HEAD plus the dirty ledger diff; the tool has no list/status subcommand (`--help`).

| Program | Ledger | Status | Next step (from the ledger) |
| --- | --- | --- | --- |
| Agentic SDLC | `docs/specs/agentic-sdlc-2026-11/LEDGER.md` | active (opened 11-01) | SE-01 navigation-quality session then S1 CLI (OVE-207); Sprint OC waits for its merge (LEDGER.md:14-17, 77) |
| Provider consolidation / Sprint OC | `PC/LEDGER.md` | active | DOC-38 board: W0/W1 then remote-readiness and first deployment (LEDGER.md:14-18, 118); SE-17 provenance still `active` (LEDGER.md:210) |
| Coordinator surface | `docs/specs/coordinator-surface-2026-10/LEDGER.md` | active, proposal `open` | Owner reads proposal; round R8 / sprint I; focused part shipped as OVE-182 (LEDGER.md:14-23, 35) |
| Fault tolerance | `docs/specs/fault-tolerance-2026-10/LEDGER.md` | active, proposal `draft`, nothing built | Owner answers FT-D1..D22 (LEDGER.md:14-18, 30); last reconciled 10-23 |
| Finished | `docs/specs/archive/` | archived | fast-track, multi-provider, materialization-observation (`AGENTS.md:163`) |

Open items inside provider consolidation that stay open: D1–D9 (`PC/LEDGER.md:81`), sitting I / OVE-149
(LEDGER.md:160,181), Swarm/EO runtime (IA-11, LEDGER.md:188), OpenAI Agents API design SP-15/DOC-40 (draft).

## 5. Dirty files

From `git status --short` in `platform/mission-control` (names only):

- `docs/specs/agentic-sdlc-2026-11/LEDGER.md` — adds row IA-02 for the sitting II answers file (sitting prep).
- `docs/specs/agentic-sdlc-2026-11/answers/AGENTIC-SDLC-SITTING-II-2026-11-02-ANSWERS.md` — untracked, the
  answers file opened by `new-answers` for this sitting.
- `src/mission_control/adapters/prerequisites/cursor_native.py` — **one-character deletion of the closing
  parenthesis on `observed_repository_commit` (line 60); the file no longer parses** (`SyntaxError: '(' was
  never closed`). Modified 2026-11-01 20:56:22, one second after commit `ce9d2f13`. Imported by
  `adapters/prerequisites/probes.py` and `tests/unit/prerequisites/test_cursor_native.py`. Origin unknown;
  looks accidental or a planted defect — the owner should say which before anyone commits.
- Extra worktree: `.claude/worktrees/agent-a3ad8c12b136e094c` on `sprint-oc-selection-workspace` at `6c2cce2e`
  (already merged by `79525ed4`); not dirty-checked here.
- This file, once written, is a new unlisted Markdown file: `program_ledger.py check` will fail until a
  `draft` row is added (not added here; LEDGER.md edits were out of scope).

## 6. Candidate knowledge concepts versus program-only facts

Rule applied (Q1 recommendation): implemented and tested facts may be concepts, stated as such;
integrated/qualified only with the proof path cited; below implemented stays in the program.

May become or already are concepts (label stated):
- Selection Workspace — tested; already `docs/knowledge/selection-workspace.md`.
- Workspace closure and release 1.12.0 — integrated, cite `PROV/REPORT.md:37`; concept exists but understates (§7 D2).
- Invocation origin / mission identity (slice 1) and gateway minting (slice 2) — integrated, cite REPORT.md:33-34.
- Read intent (MC side) — tested; say "not exercised live".
- Knowledge charter skills and the `application:charter` mount — tested; say "not mounted in any run".
- S3 payload store settings and bucket seed — tested; round trip integrated only with the private path cited.
- Linked exports, governed cancellation, adoption, held repair (1.10.0/1.11.0) — integrated locally, cite NS:364-368.
- StageGraph named-output settlement and GoalDirected repair context — integrated locally, cite NS:239-246.
- R0–R7 resolution seam, Model Catalog, WI-07/08/19/23 — tested; most already have concepts.
- W0 release facts (pins, installs, refusals) — qualified, cite `RELEASE-BUNDLE.md:22`.
- Nested bodies (WI-13) and native plan decisions — tested, but a concept must say the migrations are
  unregistered and not installable (`recursive-composition.md:82` already does for 0068).

Must stay in program documents:
- W1 status, the D1–D30 defect series and its rerun plan (NS, `W1-EVIDENCE.md`).
- Swarm/EO recovery homes `sprint-oc-wi14`/`wi15` — unreviewed, not in primary (NS:139-140).
- Coordinator-surface proposal beyond OVE-182, fault tolerance, OpenAI Agents API design, cloud
  environments roadmap, Agentic SDLC slices S1–S8 — nothing built.
- Remote rollout steps and owner-gated items (REPORT.md:78-97), spend ledgers, fixture run identities.
- Paid fixture evidence whose only proof is under ignored `.scratch/` — usable as concept citations only if
  the owner accepts private paths as proof; otherwise keep in programs.

## 7. Discrepancies (docs vs code/git)

- **D1** `docs/knowledge/log.md:24,35` say slices 5 and 1 have "no live mission … yet"; the proof run
  `source-mc-origin-01` exercised both (`PROV/REPORT.md:33,37`). Same for
  `docs/knowledge/workspace-closure.md:87-89`.
- **D2** `PC/LEDGER.md:110` (DOC-30) says selection/routing design "Nothing built" and DOC-31 (:111) says
  "Next: R1, R5"; R0–R7 merged on 10-27 (`2a905506`, `50498d67`, `cb7faf4a`, OVE-202 commits).
- **D3** `PC/LEDGER.md:104` (DOC-24 PROOFS) "Required new runtime proof is unrun"; W0 is released
  (`RELEASE-BUNDLE.md:22`) and PROOFS itself now routes to NS (`PROOFS.md:12-13`).
- **D4** `PC/LEDGER.md:43-44` "Current source baseline is MC 1863017c …" — HEAD is `ce9d2f13`.
- **D5** `scripts/release_200/` holds `0068_nested_program_activations.sql` and `0069_native_plan_decisions.sql`,
  while released 1.10.0/1.11.0 already use keys `0068_exact_linked_exports` and `0069_linked_export_family_writer`
  (`releases/1.12.0/component/manifest.json`). NS:887 still calls 0069 "a future-release candidate"; it
  must be renumbered before any release includes it.
- **D6** `packages/mission-control-db-contract/releases/README.md` has sections only through 1.9.0 (`:263`);
  1.10.0–1.12.0 are built but undocumented there.
- **D7** `docs/MISSION_CONTROL_IMPLEMENTATION_STATUS.md:4` describes release 1.0.0 "installed live";
  last touched `bcc90f2e` (10-24). It is fourth in the precedence order (`AGENTS.md:145`).
- **D8** `PC/providers/deep_agents/CHANGES.md:15` newest entry is 2026-10-29; the Qualia runtime repairs
  (NS:85-90), Selection Workspace and provenance slices are not appended, although DOC-09 says each
  build session appends (`PC/LEDGER.md:89`).
- **D9** `PROV/REPORT.md:7` frontmatter `status: active` while its ledger row is `done` (`PC/LEDGER.md:123`);
  SE-17 stays `active` (:210) though the sprint closed.
- **D10** `AGENTS.md:153` index note says the coordinator-surface program has "nothing built"; its focused
  part shipped as WI-19/OVE-182 (`958957e6`), as its own ledger says (`coordinator-surface…/LEDGER.md:20`).
- **D11** NS:52-54 says Selection guidance needs agent-skills 1.0.4 "because 1.0.3 is the released W0
  seed"; 1.0.4 now exists for the charters (`capability-seeds.md:23-27`) without that guidance
  (no `skills/` match for `mission_search`/`selection_check`). Whether it goes into 1.0.4 or 1.0.5 is open.
- **D12** NS:142-146 "consolidation verified complete: 58 to four"; a fifth registration now exists
  (`.claude/worktrees/agent-a3ad8c12b136e094c`, created after consolidation).
- **D13** `PC/LEDGER.md:88` (DOC-08) "0.7.5 installed, 0.7.30 latest" — still pinned at 0.7.5
  (`pyproject.toml:18`); the "latest" figure is from 10-22 and unrefreshed.

Not verified: whether 1.9.0 (or later) was installed on either remote; current Linear states for any id;
private `.scratch/` evidence contents; test pass counts (nothing rerun); who or what edited `cursor_native.py`.
