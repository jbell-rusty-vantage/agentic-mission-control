---
type: Concept
category: domain-model
title: Context, state handoff and continuation
description: The sealed Context Packet and deterministic packer, where each workflow system hands context across stage, iteration, chain, queued-instruction and fork boundaries, the context selection record, checkpoint lineage and in-doubt classification, and the Continuation Checkpoint with its persisted phase machine (merged from the former continuation-checkpoint concept).
tags: [mission-control, context, checkpoints, continuation, compaction, handoff, implementation]
aliases: [context packet, continuation checkpoint, compaction, state handoff, checkpoint lineage]
questions:
  - How is a Context Packet built and handed to the next stage?
  - How does a long-running unit continue in a fresh session?
  - What does each workflow system hand over between activations?
  - What is an in-doubt unit and how is it reconciled?
  - Which state handoff and memory contracts exist only on paper?
updated: 2026-11-01
---

# Context, state handoff and continuation

ADR-0007 separates authoritative state (journal, typed state, command frontier, effect receipts, acceptance) from
advisory memory and from runtime graph checkpoints, which only recover graph execution. This concept covers the
[Context Packet](../../GLOSSARY.md), [Context Selection](../../GLOSSARY.md), [State Handoff](../../GLOSSARY.md),
[Checkpoint Lineage](../../GLOSSARY.md), [Continuation](../../GLOSSARY.md) and [Compaction](../../GLOSSARY.md).
Exact predecessor *outputs* travel in the sealed transfer plan ([output contracts](output-contracts.md)); the packet
carries host state around them. Snapshots and forks are in [recovery](recovery.md).

## 1. Scheduling: when a packet is sealed

Every handoff produces one sealed `mc.context_packet.v1` and every attempt consumes one (ADR-0027).
`domain/context/packet.py::pack` is pure (no I/O, clock or randomness); capture happens beforehand in
`application/context/pack_service.py::ContextPackService`. Purposes: `stage_start, iteration_start, continuation,
fork, chain_link, follow_up_turn`.

| Workflow system | Handoff (built unless stated) |
| --- | --- |
| [Stage Graph](stage-graph.md) | `pack_for_stage` before a stage operation is admitted; upstream accepted outputs appear as `/inputs/...` files with digests (`application/programs/service.py`, `stage_inputs.py`) |
| [Goal Loop](goal-loop.md) | `pack_for_iteration` replaces a stringified handoff; fresh sessions seed from a typed `GoalHandoff`; token-threshold rollover (cap pauses, never fails) |
| [Mission chains](mission-chains.md) | The consumer's first packet carries supplied outputs (`purpose: chain_link`, `application/chains/packet.py`) |
| Queued instruction, inject | Mailbox entries claimed at a boundary become mandatory `queued_instruction` items; `interrupt_and_inject` seals a `follow_up_turn` packet ([interventions](interventions.md)) |
| Fork | `application/recovery/fork_seed.py` writes the optional instruction and an `add_context` with `expand: workspace`; the first boundary seals a `fork` packet ([precise fork](precise-fork.md)) |
| Swarm member, EO round | Decided to use the same boundaries; not built |

## 2. Output-contract obligations in the packet

The packet carries `goals_and_criteria`, `pending_commitments`, `operating_contract` and `accepted_output` items; an
output is `accepted_output` only when acceptance-gated (`accepted_output` and `chain_supply` are). Retrieved content is
data with provenance, never instructions. Obligation state itself is authoritative in the fulfillment tables, not in the
packet. A continuation that crosses a pending obligation keeps the sealed plan; omissions stay visible.

## 3. Context transfer: the packet itself

Items have a source kind (`accepted_output, loop_state, journal_digest, progress_review, human_answer, blocker,
continuation_checkpoint, chain_supply, catalog_context, operating_contract, goals_and_criteria, pending_commitments,
budget_remaining, workspace_map, queued_instruction`), a trust label (`authoritative, admitted_input, untrusted_content`)
and an Expansion Tier (`inline, reference, materialize, workspace`; exactly one `workspace` for `continuation` and
`fork`). Ranking is deterministic by source-kind priority; available input is the window minus output, overhead,
control reserve and margin; a mandatory item that does not fit blocks with `CONTEXT_BUDGET_EXCEEDED`, a filtered one
with `CONTEXT_MANDATORY_ITEM_UNAVAILABLE`; nothing is truncated. `domain/context/render.py` renders the same packet on
every lane (`.mission/context.md`, `.mission/inputs.json`, the single `admitted_input` prompt segment, read-only
workspace entries) and builds `mc.context_selection.v1` with `prompt_plan_digest` and `file_plan_digest`.
`mission_control.context_selection` (migration 0027) holds one immutable row per `(run, activation, attempt,
generation, purpose)`; a replay with a different digest is an idempotency conflict. Producer outputs are captured from
custody records (`workspace-candidate://`, `artifact://`), never from a model-emitted string.

**State handoff.** `mc.state_handoff.v1` (base version/digest, typed delta, `STATE_VERSION_CONFLICT`, declared merge
policies), `mc.memory_recall.v1`, the four memory namespaces, `mc.message.v1` and `mc.progress.v1` are specified only
(grep: no hit in `src/`). Lifecycle transitions are owned by `domain/policies/reducer.py` ([lifecycle](lifecycle.md));
goal handoffs reference a checkpoint key plus artifact digest; the Deep Agents materializer composes state channels
with `_replace`, `_append_unique_by_id`, `_merge_by_key`.

**Checkpoint lineage and in-doubt units** (`domain/execution/checkpoint_lineage.py`, `CON-CP-CHECKPOINT-LINEAGE-V1`).
Each unit generation owns a cognitive namespace; every LangGraph checkpoint is stamped with unit key, generation,
invocation id, binding digest and state-schema digest. Before dispatch the lane classifies the generation `settled,
observed_unsettled, not_submitted, interrupted, terminal_unobserved` or `in_doubt`. Transitions are accepted by
compare-and-set on the namespace head; writes under a superseded fence are `LineageWriteRejection`. With no unique safe
case, `CheckpointLineageInDoubt` carries a typed reason and the unit stays `operator_required` until a decision such as
`accept_descendant`: an in-doubt unit is reconciled, never duplicated.

## 4. Runtime: continuation and compaction

[Continuation](../../GLOSSARY.md) resumes work in a fresh session or workspace; compaction reduces carried context
first. A raw transcript is not a checkpoint. `domain/context/checkpoint.py` defines `mc.continuation_checkpoint.v1`
(a sealed `purpose = continuation` packet plus typed state), `reduce_checkpoint` (deterministic; a compactor's
synthesis merges only into rationale summaries and recommended actions, so a corrupted summary cannot drop queued
commands, budgets or open Human Tasks), trigger kinds (`context_health_soft`, `context_health_hard`,
`provider_compaction`, `turn_count`, `workflow_boundary`, `request_continuation`), `CompactionFailurePolicy`
(retry, fallback compactor, human review, fail) and governors:

<!-- snippet: src/mission_control/domain/context/checkpoint.py:897-903 -->
```python
class ContinuationGovernorPolicy(_Contract):
    max_transfers: int = Field(default=8, ge=0)
    max_cumulative_tokens: int | None = Field(default=None, ge=0)
    max_cumulative_cost_micros: int | None = Field(default=None, ge=0)
    max_wall_clock_seconds: int | None = Field(default=None, ge=0)
    max_failed_compactions: int = Field(default=3, ge=0)
    max_no_progress_transfers: int = Field(default=2, ge=0)
```

`ContinuationService` (`application/context/continuation.py`) records a trigger (idempotent by reference), seals at the next
safe boundary (governors, mailbox freeze, workspace snapshot, reduction, validation, `session.checkpoint_sealed`) and
transfers through a lane `SessionHydrator` (Deep Agents `adapters/deep_agents/compaction.py`, Cursor
`adapters/cursor/controls.py`, [cursor lane](cursor-lane.md)). State lives in `continuation_checkpoint` plus its validation
verdict and the `continuation_transfer` saga row (migration 0027); `GET .../runs/{id}/checkpoints[/{id}]` and `missionctl run
checkpoint` read them (bodies above 4 KiB are digests unless `full`). `request_continuation` is a command recorded as
`session.continuation_requested` (`emulated` on every profile). Deep Agents compaction is observed
(`ObservedSummarizationMiddleware` frames become `session.compaction_observed`).

**Persisted phase machine (MP-12, ADR-0041).** Each worker composes one stack (`adapters/temporal/continuation_composition.py`):
phase service (`application/context/phases.py`, rules `domain/context/phases.py`), a `LaneHydratorRegistry` (Cursor local
and cloud, Claude, Codex), the pressure coordinator (`domain/context/pressure.py`; soft 0.70, hard 0.85, reserve 0.15 by
default) and the mailbox hold oracle. At a Session Lane turn's terminal frame `lane.turn` measures occupancy and, when a
transfer is pending, ends the segment without settling the unit. Behind patch `mp12-operation-continuation` the operation
workflow calls `continuation.pending` / `continuation.advance`, one idempotent phase per call: requested, frozen,
snapshotted, sealed, target prepared, hydrated, verified, activated. From `frozen` to activation the source is fenced
(`continuation_in_flight`); a handover the Stop Fence denies settles `cancelled`; an ambiguous one parks `in_doubt`.
Codex alone has native compaction control. Limits: only registered lanes continue; registration never marks continuation
qualified; a Deep Agents request is recorded only (no mid-activity safe boundary); pressure policy is per worker. The Goal
Loop rollover cap is `governors.transfers` (K02). Runtime (LangGraph) checkpoints are evidence only.

Built / specified / goal: packet, selection record, lineage and the continuation phase machine built and tested (fixture lanes; no live continuation drill); packets feed paid Deep Agents runs (integrated, `NEXT-SESSION.md:32-98`); state handoff/memory/message contracts specified only.

# Citations

- ADRs: [0007](../adr/0007-authoritative-state-separate-from-advisory-memory.md), [0027](../adr/0027-context-packet-tiers-and-workspace-materialization.md),
  [0039](../adr/0039-four-independent-progress-mechanisms-compaction-native-first-continuation-sealed.md), [0041](../adr/0041-continuation-is-a-persisted-phase-machine-driven-by-the-operation-workflow.md).
- Spec: [SPEC-02](../specs/archive/fast-track-2026-10/SPEC-02-context-packet.md); deleted annexes `workflow-types/08`, `expansion/CONTEXT-STATE-AND-CONTROL.md` at `66185d2e`.
- Code: [packet](../../src/mission_control/domain/context/packet.py), [pack service](../../src/mission_control/application/context/pack_service.py),
  [render](../../src/mission_control/domain/context/render.py), [checkpoint](../../src/mission_control/domain/context/checkpoint.py),
  [continuation service](../../src/mission_control/application/context/continuation.py), [phases](../../src/mission_control/application/context/phases.py),
  [pressure](../../src/mission_control/domain/context/pressure.py), [lineage](../../src/mission_control/domain/execution/checkpoint_lineage.py),
  [continuation ledger](../../src/mission_control/adapters/postgres/context/continuation_repository.py), [activities](../../src/mission_control/adapters/temporal/activities/continuation.py),
  [Deep Agents compaction](../../src/mission_control/adapters/deep_agents/compaction.py), [Cursor controls](../../src/mission_control/adapters/cursor/controls.py).
- Tests: [packer](../../tests/unit/context/test_packer.py), [stage handoff](../../tests/unit/operations/test_ft_b2_stage_handoff.py), [iteration packet](../../tests/unit/orchestration/test_ft_b3_goal_iteration_packet.py),
  [handoff in PostgreSQL](../../tests/integration/postgres/test_ft_b2_context_handoff.py), [Deep Agents seeding](../../tests/integration/deep_agents/test_ft_b2_packet_seeding.py),
  [lineage](../../tests/unit/operations/test_checkpoint_lineage.py), [classification](../../tests/unit/operations/test_checkpoint_recovery_classification.py),
  [checkpoint](../../tests/unit/operations/test_continuation_checkpoint.py), [service](../../tests/unit/operations/test_continuation_service.py),
  [phase machine](../../tests/unit/continuation/test_phase_machine.py), [lane turn](../../tests/unit/continuation/test_lane_turn_continuation.py),
  [on Temporal](../../tests/integration/temporal/test_mp12_continuation.py), [Deep Agents](../../tests/integration/deep_agents/test_continuation_deep_agents.py).
