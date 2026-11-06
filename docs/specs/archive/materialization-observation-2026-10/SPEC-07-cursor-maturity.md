---
type: Specification
title: "SPEC-07: Cursor lanes to full maturity — lifecycle, control, accounting and portability for cursor_local and cursor_cloud"
description: "Target semantics for every harness operation on both Cursor profiles, the correctness defects to fix first, accounting and durability work, new control levers (plan gate, custom-tool approvals, model params, no-repo agents) and the CD qualification drills."
tags: [mission-control, specifications, cursor, lanes, lifecycle]
---

**Run 2 close-out disposition (2026-10-18, Gate L):** Gate L: cursor_local S0 cells (S0-03/06/09/12/15/18) and the local-profile CD drills they naturally exercise (CD-01, CD-06, CD-07, CD-10, CD-15 if reached), within the Q/S0 10 USD slice. Carried forward: all cloud-profile CD drills and CM-21 cloud parts (S1). Deferred: CM-06/11/12/14/15/16/17/20/22. Criteria below are unchanged; see [the disposition](runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md) and [close-out instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md).

# SPEC-07: Cursor lanes to full maturity

Owner decision R2: **Cursor programmability is settled; build both profiles to full maturity.**

Evidence: [research/cursor-maturity.md](research/cursor-maturity.md) (33-capability audit with `path:line`) and [research/cursor.md](research/cursor.md).

Environment, cognition and signal work for Cursor lives in SPEC-01 to SPEC-04 (MO-06, MO-13, MO-30, MO-31, MO-41, MO-42). This spec covers lifecycle and control.

## 1. Definition of "full maturity"

Every `AgentHarness` operation (`describe`, `prepare`, `start`, `reattach`, `send_turn`, `cancel_turn`, `observe`, `snapshot`, `usage`, `end_session`), plus the optional lane capabilities, must have:

- honest declared semantics;
- a production composition path;
- conformance-suite coverage (SPEC-06 §3);
- a recorded qualification drill.

The same holds for every workflow form (Stage Graph, Goal Loop, Mission Chains, Parallel Swarm units) and for knowledge missions without a repo. `qualified` flips only on drill evidence.

## 2. Target matrix

| Operation or capability | cursor_local target | cursor_cloud target | Today → work |
| --- | --- | --- | --- |
| start / prepare | N | N (env selection per SPEC-01) | WIRED → MO-06, MO-13 |
| observe + replay | N | N (`Last-Event-ID`; poll after `410`) | WIRED → CM-13 (one SSE vocabulary) |
| reattach after worker crash | **N via detached bridge** | N | local PARTIAL → CM-04, CM-05 |
| send_turn / `409 agent_busy` | N | N | WIRED → CM-18 |
| cancel / immediate cancel | N (+ kernel fence) | N (+ gate hooks, MO-42) | WIRED → CM-19 |
| interrupt_and_inject | E (cancel+replace) | E | WIRED |
| pause | E (boundary) | E | WIRED |
| fork: workspace / conversation | N / E (export; store copy if CD-09 passes) | N (branch) / E (export) | conversation ABSENT → CM-07, CM-06 |
| continuation and compaction | occupancy known; native summary observed | same; agent parity; source archived | PARTIAL → CM-08, CM-14 |
| approvals | workflow gate + **plan gate** + **custom-tool approvals** | workflow gate + plan gate | PARTIAL → CM-15, CM-16 |
| usage tokens | per run, all turns, cache tokens | same | PARTIAL → CM-02 |
| cost | settled from `charged_cents` with a delayed re-read | same | PARTIAL / DESIGNED → CM-01 |
| declared outputs and artifacts | N | **`outputs/` from the branch + artifacts API**; missing-output follow-up | PARTIAL → CM-09 |
| PR collection | via the `repo_pr` effect | `prUrl` persisted before archive | → MO-14, CM-09 |
| model selection | id + params validated against the models list | same | PARTIAL → CM-11 |
| subagents | N | ≤20 inline; refuse beyond that | → CM-12 |
| parallel units in one run | distinct worktrees | distinct `mc/{run}/{unit}` branches | **defect** → CM-10 |
| errors (429, auth, network, archived) | typed, ADR-0011 classifier | typed | → CM-03 |
| webhooks | n/a | v0 `statusChange` as wake (MO-45) | ABSENT |
| Windows worker | **supported** (connect mode) | n/a | refused → CM-04 |
| agent hygiene | bridge sweep | archive orphans | → CM-05, CM-17 |
| knowledge work without a repo | research lease (MO-51) | **no-repo cloud agents** | → CM-22 |
| follow-up images and per-turn mode | N | N | → CM-20 |

## 3. Defects to fix first (P0)

1. **Parallel unit isolation (CM-10).** The original baseline shared workspace identity. Current cloud prepare already uses the operation ID for per-unit branches. Verify remaining local/cloud production and qualification evidence against SPEC-03 §1; fix only demonstrated gaps.
2. **Cloud declared outputs are never registered (CM-09).** Only `artifacts/` is staged, while output registration accepts `outputs/`. The fix reads `outputs/` at the branch head, adds a `missing_outputs` fact, and allows an optional single follow-up.
3. **The continuation agent drops subagents, env and metadata, and never archives its source (CM-08).** Factor a shared `_create_body` used by both start and hydrate.
4. **A missing staged turn text silently resends the original prompt (CM-18).** The fix raises `NativeTurnLost`.
5. **Both SSE vocabularies are persisted (CM-13).** First prove whether this double-counts, then keep one transcript-bearing family.

## 4. Design notes

- **Detached bridge (CM-05).**
  - The bridge runs as a sidecar per lease, with a 0600 discovery file under the lease state root.
  - The worker connects through `AsyncClient.connect`, so a worker crash no longer kills the run, and reattach observes the same live run from the stored offset.
  - Reconciliation uses `list_runs` against the dispatch journal anchor.
  - Bridges are terminated at `end_session` and by the startup sweep.
- **Windows (CM-04).** `Bridge.launch` is synchronous `Popen`, so it runs in `asyncio.to_thread` followed by a connect. This removes the event-loop constraint. Hook commands use the resolved interpreter path. Windows is gated by a setting until drill CD-15 passes.
- **Plan gate (CM-15).** Turn 1 runs in `mode: plan`. A `workflow_gate` Human Task shows the plan. Approve sends turn 2 in `agent` mode; deny ends the unit `not_accepted`. This is Cursor's strongest native pre-execution approval lever and works on both profiles.
- **Custom-tool approvals (CM-16), local only.** SDK custom tools `mc_request_approval` and `mc_ask` call back into the worker, open a Human Task and wait (capped at 600 s, per MP-11). This gives `provider_question` and per-action approval on cursor_local. Cloud stays unsupported.
- **Cost (CM-01).** Usage comes from `get_usage(run_id)`. It stays `estimated` until `charged_cents` arrives and is re-read at bounded delays, because Cursor settles it late. The budget is charged once. It is never zero-filled.
- **No-repo cloud agents (CM-22).** Cursor cloud agents can run without a repo (this corrects SPEC-03 §3). Knowledge missions use the packet in the prompt plus an ingress fetch, and outputs come back through the artifacts API or ingress.

## 5. Work items and drills

Work items CM-01 to CM-22 have files, acceptance and dependencies in [research/cursor-maturity.md §Work items](research/cursor-maturity.md) and are issued in [ISSUES](ISSUES.md).

Order:

1. P0: CM-10, 09, 08, 18, 13.
2. P1: CM-02, 01, 03, 04, 05, 06, 07.
3. P2: CM-11, 12, 15, 16, 17, 19, 20, 22, 14.

Qualification drills CD-01 to CD-20 (owner-run, paid, finite budget) are defined in the same research file and recorded under `docs/qualification/lanes/cursor_{local,cloud}/`. The open drills from the existing qualification READMEs carry over.

## Run 2 approved refinements (2026-10-14)

CM-01/02/03/08/13/21 now require attributable identity, truthful usage/control declarations, single-charge replay and complete admitted continuation configuration. CM-09 joins immutable output custody to review/publication separation. CM-10's cloud branch defect is partly superseded: current prepare passes operation_id to run_branch; verify local and production evidence before fixing anything. Use each issue's Run 2 plan for negative cases and minimum checks. CM-11 model params and every other handoff-deferred CM issue remain deferred; full-maturity aspiration does not admit them. No native-tool catalog or model catalog is added.

[Detailed approved rules and issue mapping](runs/RUN-2-PLANNING-AMENDMENTS.md). These refine remaining acceptance and grant no new execution, spending or deployment authority.
