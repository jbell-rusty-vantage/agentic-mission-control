---
type: Session Instruction
title: "Tracing Stage 3: adversarial review, simplification, test gaps and documentation of Stages 1 and 2"
description: "Handoff from Stage 2 (sprint/tracing-stage-1, nine Stage 2 commits after 720545a4, 0.804 USD on GPT-6 Sol and Luna): the review scope of TRACING-PROPOSAL §C.3 extended by what Stage 2 built, the Stage 2 findings in priority order with their commits and their open questions, the per-fixture commits to review one by one, the live re-proof left open, and the documentation pass."
tags: [mission-control, providers, consolidation, deep-agents, tracing, stage-3, handoff]
status: archived
archived: 2026-10-23
archived_from: providers/deep_agents/SESSION-STAGE-3.md
archived_reason: "Tracing Stage 3 done"
---

> **Archived 2026-10-23** (Tracing Stage 3 done). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Tracing Stage 3: review, clean code, tests, documentation

**Done (2026-10-22).** The outcome, every review finding with its disposition, the checks and the
deferred list are the ledger's [Turn 7, Stage 3](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md#turn-7-stage-3-2026-10-22-adversarial-review-clean-code-test-gaps-documentation)
entry. The owner chose: F-S2-12 terminalize, F-S2-10 default to the source's baseline, merge and
push. The next session is the [owner interview](../interview-instructions/OWNER-INTERVIEW-2026-10-22.md).

Run under [PROCESS.md](../../../provider-consolidation-2026-10/PROCESS.md) against [TRACING-PROPOSAL.md](../proposals/TRACING-PROPOSAL.md)
§C.3, on `sprint/tracing-stage-1` as Stage 2 left it (not pushed, not merged). Read first the
ledger's [Stage 2 finish](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md#stage-2-finish-2026-10-22-what-to-read-first), then the
[Stage 1 finish](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md#stage-1-finish-2026-10-22-the-parts-to-read-the-sequence-the-owners-commands).
The owner reads every Stage 2 fixture's `transcript.md` in full before this stage starts (the
list is in the Stage 2 session's final message and in each fixture's ledger entry), and the
§4b parking lot of [SESSION-STAGE-2.md](SESSION-STAGE-2.md) is the input of the output-contracts
session, not of this one.

## 1. What Stage 2 left

- Every fixture of SESSION-STAGE-2 §2, §4 and §4c ran on GPT-6 Sol (parent) and GPT-6 Luna (sync
  child) through the production OpenAI factory, except FX-TR-REMOTE (T0 by design).
- Twelve findings, eleven fixed in the stage (F-T3-1, F-S2-1..11), one open (F-S2-12); the
  output-contracts problem (OC-D4) observed live three times and parked.
- New test surfaces: `tests/acceptance/mission_control/test_tracing_live.py` (the paid fixtures,
  gate `BELLABS_RUN_TRACING_LIVE=1`), `test_tracing_stream.py` (four T0 twins: stream,
  reconcile after an inject, cancel, disconnect), `test_goal_output_unparseable.py` (F-T3-1 T0),
  `tests/fixtures/{live_models,stage2_outputs,stream_capture}.py`, `tcp_proxy.ConnectProxy`.

## 2. The commits to review, one by one

| Commit | Fixture | What to review first |
| --- | --- | --- |
| `17bd1abf` | documents | nothing to review in code |
| `2f81b977` | 1, F-T3-1 | `application/programs/goal_directed.py::_parsed/_executor_observation/_verifier_observation` (a typed `failed`/`rejected` observation whose `irrecoverable_failure_ref` is `output_unparseable:<digest>`); the activity's non-retryable `goal_output_invalid` and the workflow's `RECONCILE_MAX_ATTEMPTS = 5` (replay safety of a retry-policy change); `adapters/deep_agents/adapter.py::_structured_output` (pydantic instance); `application/frames/transcript.py::_with_request_bodies` and `domain/frames/render.py` (the Markdown renderer); `unit_failures` on inspect |
| `15ee2747` | 2, the Stage Graph mission | `application/streams/service.py` + `adapters/realtime/stream_source.py` (`unit_key` from attempt -> activation key per execution); `mc.event.v1` gains `unit_key`/`point_ref` (signed webhook bodies change for unit events); `keep_expired` (placeholders from the persisted projection; the read path while the projection is behind); `domain/execution/cognition_points.py::frames_of_point` and its use in the settlement writer (`adapters/postgres/operations/cognition_points.py::_resolve`, one extra read per keyless root point inside the settlement transaction); `_entry_excerpt` (full-body kinds keep the stored body: projection row sizes) |
| `11c56dcd` | 3, BUDGET | `adapters/deep_agents/budget.py::BudgetStopMiddleware` (a `wrap_model_call`, exceeded not reached; the stop message is not a model turn); `_ModelCallObserver.spent`; the result point's `budget_snapshot` fields; `BudgetView` on inspect |
| `5e4a9509` | 4, CANCEL | `FenceStopMiddleware` and `StopFenceGate.run_fenced`; `operation_execution._fenced_after_turn` (a turn that returns under a persisted fence for its generation settles `cancelled` when the cancel is journaled): check the generation semantics and the interaction with `_settle_cancelled` and the stop-fence milestones |
| `e1dd436e` | 5, the fork from S2 cycle 2 | `missionctl run fork --baseline-reservation` |
| `47f8b171` | 6, the Goal Loop and its fork | ledger only |
| `5f7a3b45` | 7, REMOTE | the owner's files from a T0 proof |
| `0b9727b1` | 8, DISCONNECT | `RuntimeInvocationFailure.usage/cognition_points`, the adapter's failure path collecting points (best effort, a broad `except`), the failed settlement using them |
| the finish | documents | the ledger, this handoff, §4b |

## 3. The adversarial review scope

TRACING-PROPOSAL §C.3 as written (correctness first: the settlement transaction, the idempotency
keys of §P8, the closure algorithm, the seed head, the typed outcomes), extended to what Stage 2
added, in this order:

1. **Settlement paths that changed**: the typed Goal observations (F-T3-1, F-S2-2) and their
   effect on convergence and on `run inspect`; the fenced-turn `cancelled` settlement (F-S2-9);
   the failed settlement with usage and points (F-S2-11); the settlement writer's range fallback
   (F-S2-6). For each: is the outcome idempotent on a retried activity, and does the journal
   still agree with the run-control ledger?
2. **The two turn stops** (budget, fence): no graph node is added (`wrap_model_call`); confirm
   the step numbering, the checkpoints and every point position are unchanged on the recovery
   suites, and decide whether a sync child's calls should also be stopped inside the child.
3. **The read model**: `keep_expired` (a run never projected before its expiry still loses its
   deltas silently), the full-body excerpt and the nested-body resolution under `--full` (sizes,
   redaction of resolved bodies), the stream envelope additions.
4. **The test gaps the review names**, starting with the live re-proof below and a unit test for
   `_fenced_after_turn`.

## 4. Open questions and items, in priority order

1. **F-S2-12 (open)**: a Stage Graph run whose required producer failed sets a declared human
   wait for a consumer that can never be admitted and waits there (FX-TR-BUDGET, FX-TR-DISCONNECT
   attempt 1). Decide the family semantics (terminalize, or skip the wait of an unreachable
   stage) before any manifest with waits runs live.
2. **The live re-proof of F-S2-11**: `BELLABS_RUN_TRACING_LIVE=1 pytest
   tests/acceptance/mission_control/test_tracing_live.py::test_live_provider_disconnect`
   (about 0.003 USD); the fixture now also asserts the recorded usage.
3. **F-S2-10's default**: should a fork default its baseline reservation to the source run's
   admitted baseline, so the owner's command needs no flag?
4. **Describe matrix flips** (the Stage 2 finish lists them): `cancel` enforced at the model call,
   `usage.cost` not `estimated` on this lane, structured output through the tool strategy.
5. **The maintenance queue on `TemporalDeployment`** (Stage 1's carry-forward, unchanged).
6. **`missionctl run points --limit`** above the route's cap of 500 (the §4a instruction used
   5000): page in the CLI or document the cap.
7. **Transcript usability** for the owner's reading: the kernel hook pairs dominate every
   transcript; a collapsed rendering of the kernel ports in `transcript.md` is a candidate.

## 5. Documentation pass (§C.3)

The ledger consolidation; the knowledge concepts (`provider-frames-and-transcript`,
`events-and-commands`, `recovery`, `deep-agents-lane`, `execution`, `budgets-and-usage`,
`interventions`) with Stage 2's behaviour (the turn stops, the typed Goal outcomes, the expiry
placeholders, the stream fields, the fork baseline flag); the ADR candidates of §C.3; the
operator guide for `run transcript --full` (now with prompt bodies), `run inspect`
(`unit_failures`, `budget`) and `run fork --baseline-reservation`; `validate_okf.py`,
`agents_docs_index.py`.

## 6. Non-goals

Output contracts, transfer policy, K04, K05, middleware adoption and everything in the §4b
parking lot (the output-contracts session takes them, OC-D1..D18); the `deepagents` version bump
(OC-D17); new live fixtures beyond the re-proof above. No push, no merge, no deployment until the
owner says so.
