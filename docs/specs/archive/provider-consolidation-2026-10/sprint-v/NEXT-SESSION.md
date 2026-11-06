---
type: Session Instruction
title: "After Sprint V: run IQ-07 on the as-built baseline, then the output/context runtime sprint"
description: "Outcome of the 2026-10-25 continuation (checkpoints A-F executed, proven on disposable targets and second-reviewed), what is still unproven, and the exact instruction for the next session: commit the baseline when told, run the final output-contract/context-transfer interview, file the runtime-sprint issues. Not deployment evidence."
tags: [mission-control, knowledge-services, sprint-v, handoff, iq-07, context-transfer]
date: 2026-10-25
status: active
---

# After Sprint V: the next session runs IQ-07

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../sessions/KICKOFF.md); no new interview or runtime completion is implied.


**Subsequent bounded repairs:** read [READINESS-REPAIRS-2026-10-25.md](READINESS-REPAIRS-2026-10-25.md)
for OVE-160/161: RV-02 now refuses unsupported report collections; RV-05 now preflights aggregate
report-file bytes. Other runtime gaps and the unified receiver plan remain open. These local repairs
are distinct from the committed Sprint V checkpoint below.

**Independent readiness review, 2026-10-25:** start with
[ADVERSARIAL-READINESS-2026-10-25.md](ADVERSARIAL-READINESS-2026-10-25.md), which qualifies the
continuation claims below. The interview is prepared; the complete normal agent/service path is not
qualified. Carry RV-01..06 and RV-08 into the repair wave and proof matrix. The baseline is already committed;
there is no pending Sprint V commit step. This review changes no work-item or tracker completion state.

The continuation prepared on 2026-10-25 was executed the same day. Checkpoints A-F are done: foundations reviewed,
one complete AI Engineer service path, the AI Engineer fixture with a bounded paid control slice, the same path for
Biotech, the current Mission Control runtime connected through the real transport, and the clean cutover bundle.
Everything was proven on disposable PostgreSQL/Supabase/Neo4j/Temporal targets and second-reviewed; nothing was
deployed, and the real-work gate (SV-D12) stays closed. The owner's standing rules (PROCESS §1.3-1.5) were applied:
schemas were evolved where the system needed it (component 2.0.0 -> 2.4.0, MC 1.5.0 -> 1.6.0, BKS SDL 2.1.0 -> 2.2.0,
three new AIDB migrations plus the withdrawal), the broad deep-module refactor was not started, and paid calls stayed at
USD 0.15 of the 15 USD session ceiling.

Read, in order: this page; [IQ-07-BRIEFING.md](IQ-07-BRIEFING.md) (the as-built picture the interview reads);
[PROOFS.md](PROOFS.md) 2026-10-25 continuation entry (every count, command and limitation); [WORK-ITEMS.json](WORK-ITEMS.json)
(state and proofs per item); [SPRINT-V-DESIGN.md §10.1-10.3](../specs/SPRINT-V-DESIGN.md#10-alternatives-pending-choices-and-conformance)
(conformance, OQ decisions, in-session decisions); [release/RELEASE-BUNDLE.md](release/RELEASE-BUNDLE.md) (pins, installers,
capability matrix). [START-HERE.md](START-HERE.md) remains the topology map; [HANDOFF-2026-10-25.md](HANDOFF-2026-10-25.md) is
the pre-continuation checkpoint, kept for its proof commands.

## 1. State of the four repositories at session end

The owner authorized the checkpoint at session end: every repository is **committed and pushed on `main`** (clean
working trees). Checkpoint commits: KS `b45adf5`, AIDB `306efd7`, BKS `c398177`, MC = the commit carrying this page
(base commits were MC `3aabe91b`, KS `ae593410`, AIDB `25f82ede`, BKS `3ea01488`). Raw receipts live in each
repository's ignored `.scratch/sprint-v/proofs/`; the helper reports of this session are in the integrator's session
scratchpad (paths in the session memory). Nothing is deployed.

| Authority | Version at session end | What changed |
| --- | --- | --- |
| KS component `knowledge_verification` | **2.4.0** (migrations 0001..0007) | 0004 operations/report kinds/assessment; 0005 decisions, signatures, outbox functions, eligibility; 0006 single-use credentials, protocol receipts; 0007 mandatory normalized-values digest, server clock |
| KS protocol `ks.knowledge_operation.v2` | amended 2026-10-25 | effect-scoped recovery grant; `knowledge.apply` returns a receipt; outcome `pending_dispatch`; `delivery` block on receipt lookups; envelope `use`/`audience`; new golden vectors mirrored byte-for-byte in MC |
| KS packages | new | `bindings/biotech-graph`; `host/src/knowledge-operation` (K01 service, K07 auth); `catalog/research/{report-kinds,source-authority,use-classes.json,fixtures}`; `scripts/experiments/sprint-v` |
| KS retirements | done | executor file store as truth, worker sealer, legacy `ReportIntent`, evidence oracle, AIDB-table readers: 346 files removed; lint baseline 4384 -> 2553 |
| MC common release | **1.6.0** built (0055) | durable handles, assessment columns, `outcome_basis`, delivery attempts + readiness guard, recovery grant column; new target locks under `release/locks/` (live `deployments/*` locks untouched) |
| MC runtime | new | `adapters/knowledge/{http_client,credentials}.py`, `compose_knowledge_lane`, six Deep Agents knowledge tools incl. `submit_output`, M03 assessment handoff, M04 exact delivery gating dependent invocations, production recovery grants |
| AIDB | head `20261025010200` (+ withdrawal `20261025010000`, RLS `20261025010100`) | binding pin (superset check), report v2 projection + guard, normalized-values guard, legacy verification objects withdrawn, contract 0.5.0, root installer `scripts/install-ai-engineer.mjs` |
| BKS | SDL **v2.2.0** pinned | `biotech-knowledge-admission.v1`, read v3 with eligibility, dispatch consumer (one Neo4j transaction with the marker), official reads rechecking the component, root installer `scripts/install-biotech.mjs`, references reconciled to v2.2.0 |

## 2. What is proven and what is not

Proven on disposable targets (details in PROOFS): both report kinds through evidence -> assertions -> independent census
-> signed seal -> decision -> native admission in one transaction -> receipt -> exact read (AI Engineer); the same through
the outbox -> Neo4j apply + marker -> verified acknowledgment -> eligibility-aware official read (Biotech, 9/11 real-graph
cases, 2 covered in-process only); MC StageGraph and GoalDirected through local Temporal/PostgreSQL and the real KS executor
with origin binding, retry with a recovery grant, cancel, receipt attribution, assessment handoff and delivery gating; fresh,
repeated and interrupted installs of both applications from the bundle.

Still unproven or limited (carry into IQ-07 and the runtime sprint, not inferred waivers):

- `report.assess` never enters `waiting_review` by itself; review is carried by the use decision (`REVIEW_REQUIRED`). The
  stop-during-review case was proven with a test-double gate.
- The MC decision-handle store is in-process; linked missions receive no delivery yet; the blocked-delivery reason is only in
  the result manifest; nothing schedules the post-run settle of a `pending_dispatch` effect.
- `verify.claims` is declared but refuses typed: judge hosting in the executor is a provider decision for the runtime sprint.
- Real AIDB apply through MC's tools was not run (needs the AI Engineer knowledge database behind the executor); it was run
  directly against the executor.
- Lost-ack-after-commit and native rollback for Biotech are proven in-process only (no fault hook over HTTP).
- The paid SV-09 receipts predate the dispute rule; the T0 harness was rerun after it, the paid slice was not.
- Pre-existing failures named in PROOFS (BKS `biotech-meta`, MC bundle custody tests, KS benchmark replay checkpoint,
  PowerShell-on-PATH tests) are unchanged.
- Nothing is deployed; locks in `deployments/*` still describe the live installs.

## 3. Owner decisions parked (ask at IQ-07 or before SV-18)

- OQ4: may `recommendation` assertions (for example Biotech supplement/compound recommendations) ever be admitted for official
  consumer use, and under which reviewer authority? Sprint V never admits them for official use.
- Whether the review rules (which uses and risks need review, what a hold means operationally) become K08 policy data
  beyond the use-class registry.
- Whether a second-family judge can ever reject on its own (today: a dispute holds).

## 4. Prompt for the next session

```text
Start from docs/specs/archive/provider-consolidation-2026-10/sprint-v/ADVERSARIAL-READINESS-2026-10-25.md,
NEXT-SESSION.md and the corrected IQ-07-BRIEFING.md. The four Sprint V baseline commits already exist.
Then run the final output-contract/context-transfer interview from
INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md on the as-built baseline: read the code before asking,
record implementation facts without treating deviations as owner decisions; ask FC-Q1..21 in the instrument's
dependency order in batches of at most four with a recommendation first,
reserve future versions from live HEAD (MC 1.7.0 / 0056, component 2.5.0 / 0008, BKS v2.3.0, AIDB next timestamp).
End with IA-09 final, the revised CONTRACTS/WORK-ITEMS pack with its conformance table, the prompt-materialization
contract and progressive report-fixture matrix, a disposition for RV-01..08, SP-04 §8 and CS-D1..14 marked,
ADR candidates promoted or retired, and the runtime-sprint issues filed with provenance. Building starts in the session after.
The real-work gate stays closed until SV-18.
```
