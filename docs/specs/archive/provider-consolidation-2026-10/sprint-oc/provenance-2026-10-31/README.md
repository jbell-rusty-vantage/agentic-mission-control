---
type: Session Instruction
title: "Provenance sprint 2026-10-31: true mission origin, receipt targets, read intent, workspace closure, knowledge charters, object store"
description: "Organic sprint accepted by the owner on 2026-10-31 after a source-grounded critique of a proposed fourth effect ledger. Seven slices across MC, KS, AIDB and BKS, each with its proof."
tags: [mission-control, sprint, knowledge-services, provenance, deep-agents]
date: 2026-10-31
status: done
---

# Provenance sprint 2026-10-31

**Owner words (2026-10-31):** "Okay implement it now. Consider this an organic sprint that grew out of a
conversation. ... Budgets accepted. Plan accepted. Use mission control to check in on the workflow and
inspect the transcript when complete. Provide me with readable reports and a summary."

## Why this sprint exists

An Opus 5.5 agent proposed a new `provenance.mission_effect` ledger in the AI Engineer database so
that "what did mission X produce" becomes a one-hop query. A source audit the same day found three
effect ledgers already written today (MC `knowledge_operation_journal` / `effect_ledger*`, the shared
`knowledge_verification.effect*` / `origin`, AIDB `orchestration.operation_intent/receipt` with
`affected_refs`). The missing pieces are not a table. They are:

1. MC's knowledge toolset builds the origin with `mission_id = run_id` and a synthesized activation id
   (`application/knowledge/toolset.py`, `KnowledgeToolset.access`). No stored origin has ever carried a
   true mission id.
2. The AI Engineer fixture host sends a hard-coded `standalone` origin with `mission: null` and mints its
   own credentials; the production gateway path has never applied into AIDB.
3. Nothing writes `research.report_v2_*`; AIDB receipts lack MC coordinates; claims carry a fabricated
   producer attempt.
4. Database reads by agents are unrecorded, although MC migration 0052 already defines
   `retained_read_observation` and `context_source_binding`.
5. The agent-visible filesystem is retained only as saver checkpoints (invisible to MC) plus a capped
   end-of-attempt capture (64 files, 4 MB).
6. No per-application statement of knowledge goals exists; domain guidance is fixture-only.
7. Supabase Storage holds only capability bundles and ingress; mission payloads go to AWS S3 or a local
   directory.

## Slices and proofs

| # | Slice | Repos | Proof that closes it |
| --- | --- | --- | --- |
| 1 | True origin: real `mission_id`, real `activation_id`, unit/node key where the contract allows | MC | Unit tests on `access()`/`to_wire_origin`; journal rows carry true ids |
| 2 | AI Engineer fixture through the production gateway with minted credentials | MC, KS | `knowledge_verification.origin.kind = mission_invocation` with the true mission id in the disposable AIDB; `missionctl run inspect`/`transcript` of the run |
| 3 | AIDB coordinates + `operation_receipt_target` + `report_v2_*` writer + claim producer origin | AIDB, KS | Migration applied on the disposable; two-hop readback "everything run X produced" |
| 4 | `knowledge.read_intent` through the gateway; read observations both sides | MC, KS | Rows in `retained_read_observation` and `knowledge_verification.operation` for a live read |
| 5 | Workspace closure at settled boundaries | MC | Closure manifest + bodies readable from `run inspect`/artifact download for a live run |
| 6 | Knowledge charter skills in agent-skills 1.0.4; Biotech coordinate mirror | MC, BKS, KS | Seed JSON + bundle bytes with digests; charter mounted at `/skills` in a run; Biotech RunContext/Activity carry run id, generation, lane |
| 7 | One object store per plane (S3 endpoint setting, buckets provisioned on disposable targets) | MC | Payload round trip through the configured endpoint |

Spend ceiling for this sprint's paid fixtures: USD 15 (the per-session rule); the owner said budgets
accepted. Receipts and model outputs stay under `.scratch/provenance-2026-10-31/`, never in Git.

## Records

- Linear: see LEDGER row (parent issue created 2026-10-31).
- Change ledger: `CHANGES.md` in this directory, one entry per slice with implemented / tested /
  integrated / qualified labels.
- Final report: `REPORT.md` in this directory, written at close.
