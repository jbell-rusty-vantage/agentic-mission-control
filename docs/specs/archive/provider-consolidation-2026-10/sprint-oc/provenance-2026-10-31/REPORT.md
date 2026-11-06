---
type: Report
title: "Provenance sprint 2026-10-31: final report"
description: "What remains toward the Deep Agents configuration goal, which gaps this sprint closed, the proof per slice with implemented / tested / integrated / qualified labels, commits, spend, and the next blocker."
tags: [mission-control, sprint, knowledge-services, provenance, deep-agents, report]
date: 2026-10-31
status: done
---

# Provenance sprint 2026-10-31: final report

## 1. What remains toward the goal

The owner goal is complete workflow and agent configuration logic for Deep Agents on deep, provider-neutral
modules. Before this sprint the provenance chain from a Deep Agents attempt to the native knowledge it produced had
three breaks: the origin Mission Control signed carried the run id in the mission slot, the AI Engineer fixture never
used the production gateway, and nothing recorded what an agent read or what its workspace held. After this sprint the
chain is closed in code and proven by one real Deep Agents StageGraph run on disposable targets. What remains is the
W1 qualification against coordinated builds, the owner-gated rollout steps in section 5, a live exercise of the new
read-intent tool, and the Biotech mirror.

## 2. Gaps closed, with their proof

The proof run is `source-mc-origin-01` (StageGraph, seven stages, `gpt-6.1-sol` stages, KS judge `gpt-6.1-terra`,
auditor `gpt-6.1-sol`), Mission Control run key `56e53118-0dcd-568f-806b-1dc1361a7cdb`, mission id
`01a194cc-6879-7a28-bcc1-652c0f985703`, lifecycle **completed**. Evidence stays private under
`.scratch/provenance-2026-10-31/aieng/source-mc-origin-01/` (readable exports `04-workflow-transcript.md`,
`ENGINEERING-EVIDENCE.md`, `knowledge-results.json`, `mc-knowledge-calls.json`, `ks-host.jsonl`, the captured
`06-evidence/inspection.0000.json` and `transcript.000*.json`). Query script: `.scratch/provenance-2026-10-31/evidence_queries.sh`.

| Gap | Before | After, with the row that proves it |
| --- | --- | --- |
| Origin identity (slice 1) | `mission_id = run_id`, synthesized activation | AIDB `knowledge_verification.origin`: two `mission_invocation` rows for the run with mission id `01a194cc-6879…` distinct from run key `56e53118…`, real activation ids (`01a194ce-6e38…` verify, `01a194d0-1ffd…` ingest), attempt 1, generation 1, lane `deep_agents`, installation `…a1e11`. MC `knowledge_operation_journal`: three applied rows with the same mission, activation and a filled `unit_key`. |
| Production path (slice 2) | Fixture host self-minted a standalone origin | `mc-knowledge-calls.json`: seven gateway calls minted by Mission Control (`report.register` ×2, `knowledge.plan_preview`, `report.seal`, `report.decide`, `decision.resolve`, `knowledge.apply`); `ks-host.jsonl`: 14 served calls with minter `mission-control`, 24 with the host's evaluator key (judge/auditor); `credential_use.issuer = mission-control`. KS verification: 15 claims fully supported after one semantic repair; exact-use admission; native receipt `01a194d0-a893…`; readback 2/2, knowledge sequence 6→7. |
| Native attribution (slice 3) | Fabricated producer attempt, no coordinates | `orchestration.operation_intent` row for the run with `origin_kind = mission_invocation` and the `mc_*` coordinates; `orchestration.mission_run_effects` returns 29 rows for the run (subject reused, provenance created, projection created); `research.report_v2_*` populated (6 revisions, 15 assertions, 21 ingestions across all fixtures); claims now carry `producer_origin_digest`. |
| Recorded reads (slice 4) | No record of any read | KS: `knowledge.read_intent` recorded in `knowledge_verification.operation` (conformance check `read_intent_recorded` passed on the disposable). MC: writer and tool implemented and unit/Postgres tested; **not exercised live**, because the fixture manifest binds only its own research tools, so `retained_read_observation` has 0 rows for the run. |
| Workspace evidence (slice 5) | Capped candidates only; files invisible to MC | Mission Control's own inspection of the run reports `workspace_closures: count 8, incomplete 0, promoted_bytes 22195`, latest `workspace-closure://dd159473…#sha256:3764e758…`; 9 cognition points carry closure refs; closure entries list `/.mission/transfer.json` and the mounted skill as promoted bodies in the payload store and the Context Packet inputs as `withheld_input`. One `attempt_failed` closure was recorded for the fork run. |
| Domain goals (slice 6) | None anywhere | Charter skills exist and compile-mount on knowledge missions; **not mounted in this run** (the fixture pins its own capabilities). |
| Object store (slice 7) | AWS S3 or local directory | Local Supabase S3 round trip passed (stage, retrieve, presigned GET); this run used the local payload directory because the fixture does not set an S3 endpoint. |

Mission Control check-in: the fixture captured `run inspect` and `run transcript` through the API before the stack
shut down (inspection shows `lifecycle: completed`, the closure summary above, no unit failures; the transcript export
has four pages). The stack is not left running, so re-issuing `missionctl` against the run requires starting the
offline operator stack on database `mct_a4e60490a4` (still present on `mc-overnight-20261029-pg17`).

What did not complete: the retained-source Tavily fork run (`614b094d…`) failed when the fixture's model ledger
refused a reservation ("shared model dollar budget exhausted"). The ledger reserves USD 2 per call against the USD 7
cap, and the fork's parallel frameworks/literature stages hit that ceiling. The driver process was then stopped by the
Claude Code harness for host memory pressure while the session was idle. The source run and all its exports were
already complete; nothing was rerun.

## 3. Per-slice status

| # | Slice | Implemented | Tested | Integrated | Qualified |
| --- | --- | --- | --- | --- | --- |
| 1 | True origin (ledger mission id, real activation id, unit key) | MC `03f11594` | unit 907, Postgres 25 | yes, live run | no |
| 2 | AI Engineer fixture through the production gateway | KS `5727a4b`, MC `03f11594` | unit 113, node 10 | yes, live run | no |
| 3 | AIDB coordinates, receipt targets, `report_v2` writer, `mission_run_effects` | AIDB `44c980c`, KS `2564226` | SQL suites, knowledge-db 359 + 15, executor 8 | yes, live run (29 effects) | no |
| 4 | `knowledge.read_intent` recorded on both sides | KS `6a4dd30`, MC `03f11594` | KS 78/74/9/19 + 3 + 29; MC 746 + 72 + 2 | KS on the disposable; MC not exercised live | no |
| 5 | Workspace closure at settled boundaries, db-contract 1.12.0 | MC `03f11594` | unit 389, common_db 10 | yes, live run (8 closures) | no |
| 6 | Knowledge charter skills, agent-skills 1.0.4, default mount | MC `03f11594` | unit 6 + seed suites | local bundle publish only | no |
| 7 | S3 endpoint, mission-payloads bucket | MC `03f11594` | unit 17 | local Supabase S3 round trip | no |

"Integrated" means exercised through the real composed path against a disposable database on this host. "Qualified"
is reserved for the W1 packet against coordinated builds; nothing in this sprint claims it.

## 4. Spend

| Item | Amount |
| --- | --- |
| Model calls (OpenAI), estimated upper bound | USD 3.07 across 77 calls (source run 2.39, judge 0.10, auditor 0.15, fork 0.42) |
| Web tool calls | 19 calls, USD 3.80 reserved at USD 0.20 each (actual vendor billing may be lower) |
| Authorized for the run | USD 15 (model cap 7, web cap 8) |
| Session ceiling | USD 15 |

Ledgers: `.scratch/provenance-2026-10-31/aieng/budget/model-usage.jsonl` and `web-usage.jsonl`.

## 5. Owner-gated and follow-up items

- Rotate the remote Supabase pooler password that a helper printed into its own local transcript on 2026-10-31 while
  reading `.scratch/sprint-oc/runtime/ai-engineer/ks-executor.env`. It never reached a file or a commit.
- Remote rollout: publish agent-skills 1.0.4 bundles and apply the seed; apply `mc.storage.mission-payloads-1.0.0` and
  knowledge-tools 1.2.0; lock db-contract 1.12.0 per deployment; apply the AIDB migration on the remote AI Engineer
  project when quality ingestion starts.
- Exercise `knowledge_read_intent` in a live mission (bind `tool.knowledge-read-intent` in the fixture manifest and add it
  to `KNOWLEDGE_MISSION_CAPABILITIES` so the charter mounts too).
- Biotech mirror of slices 3 and 4: run id, generation and lane on `RunContextV2` and the Activity node; mission
  coordinates in the admission payload; a Biotech read-intent port over the BKS `/kg/read` client.
- Fixture ledger granularity: a USD 2 reservation per model call makes small caps refuse parallel stages; lower the
  reservation or raise the cap before the next fork proof.
- Payload bytes are never deleted; closure and frame retention remove rows only. A reference-counting cleanup job is the
  follow-up.
- The charter is unavailable on hosted lanes (host support lists the five published lane profiles).
- Three owner-manifest golden tests in `tests/unit/authoring/test_manifest_compile.py` fail at HEAD before this sprint
  (stale goldens); not regenerated here. KS `.agent-docs/provenance.json` shows drift and has no rebuild script in
  `package.json`; AIDB `docs/schema-workspace/INTENT_AND_EXECUTOR_CONTRACTS.md` lacks the `targets`/`report` receipt
  fields; the assertion-subject projection path has no test.

## 6. Method notes

Six read-only explorers produced the per-slice briefs; six Opus 5.5 helpers implemented in parallel on one shared
checkout per repository. Lessons: Mission Control's commit hook stashes unstaged changes and type-checks the index plus
untracked modules, so slices sharing a tree cannot be committed separately while helpers run (hence one combined MC
commit); helpers must never run `git stash` (one did, briefly reverting another helper's files); and long paid runs must
be launched as background jobs with the host above about 3 GB free, or the harness reaps them.
