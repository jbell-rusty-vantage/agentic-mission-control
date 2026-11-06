---
type: Decision Record
title: Agents never write tables
description: Accepted - a working agent is never responsible for a table write; cognition points, the result point and the completion rows are written by the harness and the family decision path, and the agent-facing surfaces (submission, progress note) are single idempotent calls the harness completes.
tags: [mission-control, adr, accepted, tracing, points, completion]
status: accepted
source: docs/specs/archive/provider-consolidation-2026-10/proposals/TRACING-PROPOSAL.md (P7, TR-D6, TR-D9); src/mission_control/application/execution/operations/checkpoint_lineage.py
---

# Agents never write tables

**Status: accepted 2026-11-01; implemented by tracing Stages 1-3 (`6b3f172f`, `05d92929`, `4a281b36`; Stage 3 finish `34d968ee`, merged 2026-10-22).** Previously proposed. 

## Context

A model that must call a tool to record where it is, or to create its own completion row, can
forget, repeat, name a point it never reached or write something the platform then trusts.
Tracing needs points and decisions that exist whether or not the agent cooperates.

## Decision

1. Cognition points are written by the harness. A Deep Agents turn collects its points and the
   settlement records them with the transition and result (`CheckpointLineageService.record_result`).
   If the points write fails, the transition and result still commit and the result carries
   `points_status: incomplete`; the reconciler repairs it and `run inspect` reports it
   (`points_incomplete`). A point never settles anything.
2. The agent names no point. The harness stamps the result point on the settlement. The
   `completion_candidate` and `completion_decision` rows are written by the family decision path
   (a Stage Graph `result_decided` commit, the Goal Directed verifier reconciliation), idempotent by
   key, never by the agent.
3. Agent-facing surfaces are single idempotent calls the harness completes. Submission belongs to
   the queued output-contracts work: declared outputs arrive as the `run_result` frame body and
   the settlement's output payload. `progress_note` (an optional Deep Agents tool that would emit
   a frame keyed by thread, step and counter) has a reserved frame kind (`progress_note`); the
   tool is not built.
4. Anything an agent says is data in the Transcript, never authority for a state change.

## Consequences

- Missing points are a reconciliation gap with a marker, not an agent failure.
- Output contracts and submission can be designed later without changing the point model.
- Agents get no table-shaped tools; a lane that cannot emit a custom stream event simply has no
  progress note.
- Rejected: an agent tool that records a point or a decision (forgettable, forgeable).

# Citations

- [Point lineage contract](../../src/mission_control/application/execution/operations/checkpoint_lineage.py),
  [Postgres lineage writer](../../src/mission_control/adapters/postgres/operations/checkpoint_lineage.py),
  [Deep Agents point collector](../../src/mission_control/adapters/deep_agents/cognition_points.py),
  [completion writers](../../src/mission_control/adapters/postgres/orchestration/completion_repository.py),
  [frame kinds](../../src/mission_control/domain/frames/contracts.py).
- Concept: [Recovery](../knowledge/recovery.md) (cognition points). Related:
  [ADR-0054](0054-the-mission-transcript-is-the-replayable-record.md).
