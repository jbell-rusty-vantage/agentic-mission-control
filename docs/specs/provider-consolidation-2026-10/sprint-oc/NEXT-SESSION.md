---
type: Handoff
title: "Sprint OC control board: functional Deep Agents workflows and partial fixtures"
description: "The live checkpoint of Sprint OC: state and authority (W0 released, W1 open), versions and remote install state, completed fixtures, source custody, the remaining implementation and qualification map by work item, open proofs and owner-gated items, and the next action. The dated batch logs are archived."
date: 2026-11-01
status: active
---

# Sprint OC control board

Live part only (reconciled 2026-11-01, OVE-206). The dated batch logs of 2026-10-29..31 (overnight fixtures, foundation
detour, B3-B4c) are in [SPRINT-OC-LOG-2026-10-29-31](../../archive/provider-consolidation-2026-10/docs/SPRINT-OC-LOG-2026-10-29-31.md);
retrieve them by section, not in full. Reading order for current state: this board, then
[W1 evidence](release/W1-EVIDENCE.md) and the W1 rows of [PROOFS](PROOFS.md), then the concepts for behaviour
([qualification](../../../knowledge/qualification.md), [database-component](../../../knowledge/database-component.md),
[output-contracts](../../../knowledge/output-contracts.md), [temporal-synthesis](../../../knowledge/temporal-synthesis.md)).

## Status

- **Resumed 2026-11-02** (owner: "knock two birds with one stone"): Sprint OC work runs again and doubles as the Agentic SDLC
  real-task navigation experiment ([handoff](../../agentic-sdlc-2026-11/HANDOFF-2026-11-02.md) §4.1). The SDLC program's
  remaining passes (KS, BKS, AIDB, NAVIGATION-DESIGN, S1) run beside it, no longer ahead of it.
- **Owner direction (2026-10-31):** W0/W1 and general refinement may run locally before cloud coding-environment setup.
  Direction: cloud development environments (Cursor, Claude Code, Codex) for MC/KS first, then Deep Agents / Agent Server /
  Temporal deployment architecture and owner education, then the W0/W1 checkpoint, a likely remote-readiness coding sprint and
  the first major local-and-cloud deployment ([roadmap](CLOUD-ENVIRONMENTS-AND-DEEP-AGENTS-DEPLOYMENT-2026-10-31.md), planning
  only; no infrastructure choice or gate release follows). Biotech source/capability optimization is a later effort.
- **Standing rules:** startup delivery mode (commit verified work, migrate disposable targets in-session); paid spend within the
  stated ceiling ([budgets](../../../knowledge/budgets-and-usage.md)); never write the AI Engineer Aura graph `4773dc72`; push only at
  gate release and session end. Owner directives by date: [decisions](../../../knowledge/decisions.md#owner-directives-by-date).

## State and authority

W0 is recorded released (with limitations; [release bundle](release/RELEASE-BUNDLE.md)). **W1 is not released.** The last AI
Engineer W1 run reached independent evaluation, seal, decision, separate review and promotion, then failed fulfillment.
D27-D30 fixes are locally integrated; the complete regression and a real rerun remain. Biotech W1 has not run. W2-W4 are
unqualified. The path is W1 to W4 to the W5 owner checkpoint (OVE-186), with later stress waits. The bounded overnight
engineering fixtures below are separate from W1-W5 qualification.

## Versions and remote install state

MC database component **1.13.0** (0071, 0072) is built and locally proven. The AI Engineer disposable remote carries
**1.13.0** (2026-11-02, from 1.9.0; seeds through agent-skills 1.0.4, knowledge-tools 1.2.0, workflow-parity 1.0.5 and
mission-payloads 1.0.0 applied, custody bytes published, receipts `.scratch/sprint-oc/evidence/w1/s11/`); the Biotech remote
carries **1.9.0** (W1 session 7) and none of those seeds, so it needs the same rollout before Biotech W1. Startup now refuses a
release missing 0070-0072 (D33, `69ac3eea`). Details and the lock files:
[database-component](../../../knowledge/database-component.md). Deployment locks for the two applications still pin 1.4.2 and 1.3.0
(code issue). Keys are assigned by the integrator; `sprint-oc-wi14`/`wi15` carry colliding migration keys.

## Completed fixtures (engineering gates, not qualification)

- **Overnight, 2026-10-30:** the service prerequisite, StageGraph (runs 18-22), GoalDirected (runs 4-9) and same-application linked
  workflows pass the local runtime and readable-evidence gates in both applications (acceptance gating, exact delivery, restart,
  revocation, explicit adoption, cancellation, held-report repair). Evidence is private under `.scratch/overnight-2026-10-29-a/INDEX.md`.
- **Qualia, 2026-10-31:** source08/source09 and the retained-source09 Tavily fork05 pass the full gates on seven Deep Agents stages
  (parallel branches, a two-member coverage join, exact transfers, schema obligations, independent KS verification with repair,
  native admission, acknowledged Biotech Aura writes with 146/146 and 165/165 effects read back). Queued instruction and
  interrupt/inject are proved. Evidence: `.scratch/qualia-stagegraph-2026-10-30/READ-FIRST.md`.
- **AI Engineer, 2026-10-31:** source-02 + fork-01 and source-04 + its Tavily fork pass the same gates against the disposable AI
  Engineer database (never the graph); USD 40.94 of 60 accounted. Driver `scripts/aieng_stagegraph.py`. Gaps exposed:
  `plan_preview` admits subjects missing NOT NULL typed columns; no production MC-to-AIDB producer-attempt projection; judges see titles, not URLs.
- **Provenance, OVE-204:** origin identity, the production gateway path, native attribution, workspace evidence and the object store
  are closed on a real run ([report](../../archive/provider-consolidation-2026-10/sprint-oc/provenance-2026-10-31/REPORT.md)).
- **Selection Workspace:** merged (`missionctl search`, `workspace check`, MCP `mission_search`/`selection_check`); 21 unit tests and
  166 adjacent tests pass, not run against a live catalog. Moving its guidance into `skills/mission-control*` needs agent-skills 1.0.5
  or a late 1.0.4 (undecided).

## Remaining implementation and qualification map

Source presence is not gate release. Status is from recorded local evidence, not a fresh Linear read; `WORK-ITEMS.json` is a
dependency map, not state. The full table with its negatives is in the archived
[recovery audit](../../archive/provider-consolidation-2026-10/docs/RECOVERY-AUDIT-2026-10-29.md) section 5.

| Items | Remaining work and proof |
| --- | --- |
| R0-R7, WI-01-05 | Integrated; run affected regressions. OVE-203 (provider sweep) only if a W5 criterion needs it |
| W0 (OVE-168) | Revalidate new releases at first use; do not repeat the original wipe |
| W1 (WI-06, OVE-169) | Critical path: AI Engineer success and the missing/held/evaluator/review/restart/native variants, then Biotech; release only on all criteria |
| WI-07 (OVE-170) | Production trusted decisions for members of a real collection manifest (`MEMBER_UNASSESSED` limits); W3 proof |
| W2 (WI-08, OVE-171) | Real exact producer-consumer transfer in both apps, every W2 negative, public why-ready inspection |
| WI-09, WI-10 (OVE-172, 173) | Not delivered: deterministic transforms; durable inventory, bounded windows, partitioned slices (serial chain to W3) |
| W3 (WI-11, OVE-174) | Groups closed by exact contributors or trusted closure; multi-report accumulation, oversize and restart challenges |
| WI-12 (OVE-175) | Not delivered: tracked reassessment, exact reuse, sealed running inputs, revocation |
| WI-13 (OVE-176) | Release/install 0068; composed PostgreSQL + Temporal proof; reconcile early exports and human-gate definition readers |
| WI-14, WI-15 (OVE-177, 178) | Swarm and Evaluator Optimizer: unmerged recovery branches; to be reconciled onto the Stage Graph profile and Goal Loop machinery per [ADR-0068](../../../adr/0068-parallel-swarm-is-a-stage-graph-profile-and-evaluator-optimizer-runs-on-goal-loop-machinery.md); no gate approval |
| WI-16 (OVE-179) | Same-app exports/receiving grants, held repair, cancel vs detach, revocation; GoalDirected/StageGraph in each app |
| WI-17, WI-22 (OVE-180, 183) | Hook consumption and durable reactions composed in a W4 fixture (duplicate, crash-after-admission, stale generation) |
| WI-18 (OVE-181) | Consume validated preservation; post-compaction bytes; continuation generation; historical fork bytes |
| WI-19, WI-23 (OVE-182, 184) | Coordinator wake/ack (C14) and real sync/async child tools, skills, MCP and models (C10-C13) in W5 |
| W4 (WI-32, OVE-185) | Independent cross-feature revision/recovery proof after WI-11/12/16/18/22 |
| W5 (WI-21, OVE-186) | Owner checkpoint before paid W5; then all four families, eight forms, C01-C16, both apps |

Order: recovery/integration front, W1, W2 and collections (WI-07, then WI-09, WI-10, WI-11), WI-12/16/18 in parallel, W4, W5-ready handoff.

## Open proofs and owner-gated items

- **Cross-provider control (OVE-224, ADR-0069, 2026-11-05):** every session lane now writes cognition points, reads state as of a point and seeds
  forks at its declared level (release 1.14.0 / 0073 built locally, not installed remotely). Open: a Cursor, Codex or Claude unit through
  `OperationWorkflow` with the Postgres lineage, `run fork --point` on real services, declared steering, the paid drills
  ([concept](../../../knowledge/cross-provider-control.md), [ledger](../providers/cross-provider-control/LEDGER.md)); the live-fixture
  session instruction is [NEXT-SESSION-LIVE-FIXTURES](../providers/cross-provider-control/NEXT-SESSION-LIVE-FIXTURES.md) and keeps this board's
  W1 and iteration-3 order intact.
- Live `knowledge_read_intent` in a mission (bind `tool.knowledge-read-intent`, add to `KNOWLEDGE_MISSION_CAPABILITIES`); charter mount
  (the charter is unavailable on hosted lanes); MC-to-AIDB producer attribution; the KS typed-column planner preflight.
- Biotech mirror of provenance slices 3 and 4 (run id/generation/lane, mission coordinates, a read-intent port over the BKS client).
- Rotate the remote Supabase pooler password a helper printed into its own local transcript on 2026-10-31 (never in a file or commit).
- Remote rollout (owner-gated): publish agent-skills 1.0.4 and apply its seed; `mc.storage.mission-payloads-1.0.0`; knowledge-tools 1.2.0;
  lock db-contract 1.12.0 per deployment; apply the AIDB migration when quality ingestion starts.
- Fixture ledger granularity (USD 2 per call blocks small caps with parallel stages); payload bytes are never deleted (a reference-counting
  cleanup job is the follow-up); KS
  `.agent-docs/provenance.json` drift has no rebuild script.

## Source custody

Paths are relative to BellLabs; recheck live Git. **Clean-slate move 2026-11-06 (supersedes the custody detail below):** MC
history restarts at a single root commit on the jbell-rusty-vantage account. Its tree equals pre-move `main` `ee34bb55`, and only
`main` exists. The `sprint-oc` alias, the archive tags, the recovery refs and the old stash were removed from the repository, so
the commit IDs and tags below exist only in the owner's private local history bundle ([repository history](../../../REPOSITORY-HISTORY.md)).
The rejected `wi14`/`wi15` designs remain described by ADR-0068. KS and the other repositories move one at a time later.

**Branch consolidation 2026-11-05:** MC and KS `main` were fast-forwarded to
`sprint-oc` (MC `1d73eeab`, KS `77c6f35`) and pushed; work now lands on `main` (`sprint-oc` is kept equal to `main` as an alias until
retired). Origin holds only `main` and `sprint-oc`. 62 merged local branches and the merged `sprint-oc-selection-workspace` worktree
were removed; every checkout is a single primary. Pre-change refs are in each repository's
`.scratch/branch-consolidation-2026-11-05/all-refs.bundle` (verified) with `refs-before.txt`.

| Former recovery branch | Now | Disposition (2026-11-05 dry-run merge and content comparison) |
| --- | --- | --- |
| MC `sprint-oc-w1` | tag `archive/2026-11-05/sprint-oc-w1` | superseded: all nine files have later commits on `main` |
| MC `sprint-oc-w1fix-n` | tag `archive/2026-11-05/sprint-oc-w1fix-n` | superseded by `ecdba045` (native-write recovery, 0072 migration); `main` holds every definition plus recovery tests |
| KS `sprint-oc-w1fix-n` | tag `archive/2026-11-05/sprint-oc-w1fix-n` | superseded by `30171b2` (approved native-write recovery); `main` holds every plan-preview export |
| MC `sprint-oc-wi14` | tag `archive/2026-11-05/sprint-oc-wi14` | not merged: ADR-0068 rejects its separate Swarm runtime; reference for the Stage Graph profile rewrite |
| MC `sprint-oc-wi15` | tag `archive/2026-11-05/sprint-oc-wi15` | not merged: ADR-0068 rejects its separate EO round table; reference for the Goal Loop rewrite |

Archive tags (local only) and `refs/recovery/oc-20261029/*-original` keep the originals; per-owner `.scratch/worktree-consolidation-2026-10-29/` holds the
dirty-source ZIPs and manifests (private). Exclude the 98 KS generated contract changes from the native-write integration. Never add KS
`.claude/` or private recovery receipts to Git.

## Next action

**2026-11-03: the first accepted Goal Loop report on Deep Agents** (loop iteration 2, E1 `ecf6e20f` and E1b `1f1f4e0f` with a
worker kill; [iteration 2](experiments/ITER-2-2026-11-03.md)). W1 AI Engineer still needs the independent reviewer, the D30 probe and
the native write; next is loop iteration 3 (L2-01..L2-10; L2-02 owner decision).

**Sprint OC reshaped 2026-11-02 into the [experiment loop](EXPERIMENT-LOOP-2026-11.md)** (E1-E5 stress workflows, coordinator
agent inspection, transcript critique, fix, rerun; USD 6 cap this session). The W gates stay the release criteria.

**W1 (AI Engineer) is at the verifier (2026-11-02, sessions 10-12, at most USD 1.407 of 6.00).** Done this day: release
1.13.0 built and installed on the AI Engineer remote with seeds, custody and regenerated deployment files (owner-approved);
D31-D36 fixed; live through promotion and the first verifier start. Next, in order: decide and fix **D41** (bound a verifier
turn: enforce the run budget in-turn or select `call_limits` by default; D38 the ledger records 0 consumed), fix **D39**
(execute retries must outlast the claim lease) and **D40** (retry unsent transport failures), each test-first; then rerun the
Sonnet report on a fresh report id for the first verdict, Fulfillment@1 (D28/D29), D27 and an accepted run; then a kill
during an activity, the D30 probe (PowerShell 5.1 removes a variable set to `''`: blank keys another way), the native
write with aieng-db readback, then Biotech (its remote is still 1.9.0). Evidence: [W1](release/W1-EVIDENCE.md).

Set by the owner's explicit next-session instruction. Before DB or environment work read BellLabs `docs/navigation/DATA-PLANES-AND-CREDENTIALS.md`.
Then: the W1 packet against coordinated MC/KS builds (finish the D27-D30 regression, rerun AI Engineer, then Biotech). Update these
sections in place after decisions; do not create another competing handoff. Search the packet with
`python docs/tools/okf_search.py "<terms>" --programs`.
