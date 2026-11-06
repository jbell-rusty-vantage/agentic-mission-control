---
type: Working Draft
title: "Sprint OC reshaped: the Deep Agents experiment loop (stress fixtures, coordinator inspection, critique, fix, rerun)"
description: "Owner direction 2026-11-02: replace one-gate-at-a-time W1 debugging with a loop of 4-5 stress workflows on Deep Agents (Goal Loop, Stage Graph variants, linked chain, nested body) with fault injection, a Mission Control coordinator agent inspecting live, and transcript-based critique of the workflow, context-transfer and materialization lifecycles. States where the system is (cited), what to fix or create, the experiment matrix, the critique rubric, budget and the loop protocol."
tags: [mission-control, sprint-oc, deep-agents, experiments, fixtures, recovery, inspection]
date: 2026-11-02
status: active
---

# The Deep Agents experiment loop

Owner, 2026-11-02: "architect fixtures that really stress test the system so that we can use that as a feedback loop so
we can fix things, improve things and/or create things ... start integrating recovery and fault tolerance, inspect and
update system prompt and possibly messages updates and lifecycle, test how a mission control agent ... can read and
inspect mission control during a mission, and generally use the transcript and deeper inspection to critique the
workflow lifecycle and the context transfer and materialization lifecycle." The W gates (W1-W5) stay the release
criteria; the loop is how we reach them. Status words: implemented, tested, integrated (ran live), qualified.

## 1. Where Deep Agents workflows stand (2026-11-02, `sprint-oc` `a31bac27`)

Only **W0 is qualified**. The overnight fixtures of 2026-10-29/30 ran real PostgreSQL, Temporal, Deep Agents and KS but
**scripted cognition** (USD 0); paid live evidence is Qualia, the AI Engineer Stage Graph packet and W1 sessions 9-12.

| Area | State | Evidence |
| --- | --- | --- |
| Stage Graph: parallel branches, joins (all/any/minimum, quorum, coverage), exact transfers | integrated, paid (7 stages, both apps) | `.scratch/qualia-stagegraph-2026-10-30/READ-FIRST.md`; `.scratch/aieng-stagegraph-2026-10-31/READ-FIRST.md` |
| Stage Graph routes, revisit regions | tested; **no paid live run** | [stage graph](../../../knowledge/stage-graph.md); fixtures `tests/fixtures/manifests/sprint-oc-w2/graph.*` |
| Goal Loop: executor, verifier, repair feedback, convergence | integrated with scripted cognition; paid: executor parses, verifier starts, **no verdict** (D41) | [W1 evidence](release/W1-EVIDENCE.md) sessions 11-12 |
| Trusted judgment: register, judge+auditor, seal, decide, held review, 403, separate approve, promote | **integrated, paid** (AI Engineer) | W1 sessions 11-12 |
| Linked chains: supplies/depends_on, release conditions, cancel modes, exports, adoption | integrated with scripted cognition; **no paid linked run** | [mission chains](../../../knowledge/mission-chains.md); `.scratch/overnight-2026-10-29-a/INDEX.md` |
| Nested bodies (Goal Loop in a stage, Stage Graph as executor) | tested on real Temporal + PostgreSQL, deterministic cognition | [recursive composition](../../../knowledge/recursive-composition.md); fixtures `sprint-oc-w5/*` |
| Swarm, Evaluator Optimizer | refused at compile (`behavior_not_built`, OVE-215); branches unintegrated | ADR-0068 |
| Context Packets, sealed transfer plans, delivery receipts | integrated (paid Stage Graph) | [context](../../../knowledge/context-and-continuation.md), [output contracts](../../../knowledge/output-contracts.md) |
| Continuation / compaction, state-handoff and memory contracts | tested on fixture lanes / specified | context concept §continuation |
| Materializer (exact pins, middleware, sandboxes state/docker/langsmith) | integrated | [Deep Agents lane](../../../knowledge/deep-agents-lane.md) |
| Children (sync/async subagents) C10-C13 | integrated locally; paid proofs unrun | [children](../../../knowledge/deep-agents-children.md) |
| Queued instruction, add_context, interrupt_and_inject | **integrated, paid** (Qualia source09, AI Engineer) | [interventions](../../../knowledge/interventions.md) |
| Precise fork, snapshots, reconciliation, Stop Fence | integrated (paid forks) / tested | [precise fork](../../../knowledge/precise-fork.md), [recovery](../../../knowledge/recovery.md) |
| Fault tolerance (fault registry, `mc.error.v1`, governed retry/fallback, `fault_policy`) | **specified, not built** (program parked) | `docs/specs/fault-tolerance-2026-10/FAULT-TOLERANCE-PROPOSAL.md` |
| Coordinator inspection: transcript (full bodies), cognition points, state-as-of, outputs, transfer plans, checkpoints; missionctl; MCP servers | implemented; never exercised by a live coordinator agent during a mission | [interfaces](../../../knowledge/interfaces.md), [coordinator surface](../../../knowledge/coordinator-surface.md) |

## 2. What is broken, missing or worth creating

**Fix (blocking the loop):**
- **D41** a verifier turn is unbounded: the run budget (`tool_calls`, `tokens`) is not an in-turn limit; `call_limits`
  applies only when selected (`adapters/deep_agents/features/builders.py:230-249`). Live: 69 model / 71 tool calls, no verdict.
- **D38** the run budget ledger records 0 consumed, so no budget stop ever trips.
- **D39** `operation.execute` retries (3, about 3 s, `adapters/temporal/workflows/operation.py:1181,1262`) end long
  before the claim lease; a worker lost mid-activity loses the unit (`operation_execution.py:1568`).
- **D40** a transport failure before the request reached the provider ends the run: model clients `max_retries=0`
  (`materializer.py:341,406`), GoalDirected raises non-retryable (`goal_directed.py:562-569`).
- **Inspection blind spots**: `/inspection` shows `unit_failures: []` on failed runs (activity failures live only in
  Temporal history, `inspection_repository.py:163-200`); D37 the held decision ref/digest is not exposed; approving a
  review does not wake the run; the cancel POST blocks while no worker polls.

**Inspect and probably change (critique targets):**
- **System prompt routing.** Every manifest text (objective, authored instruction, output-contract text) is admitted as
  `ADMITTED_INPUT` and goes into the **user** message; Mission Control puts only one host sentence into the system prompt
  (`adapters/deep_agents/adapter.py:1981-1995`, `manifest_launch_inputs.py:3055-3088`). Whether role instructions belong in
  the system prompt (as a published Prompt source) is a design question the transcripts will answer.
- **Message lifecycle**: what each turn actually sends (packet size, duplicated context, tool schemas), read from
  `transcript --full`.

**Create (fault tolerance, staged into the loop):** the parked FT program's first slices, driven by observed faults
rather than built ahead: FT-0 one fault registry and `mc.error.v1` envelope for activity failures (also fixes the
inspection blind spot), FT-1 vendor error mappers (unsent vs billed), FT-2 governed model retry. Each lands only when an
experiment run shows the fault.

## 3. The experiment matrix

All runs: Deep Agents lane, **AI Engineer** application, local Temporal + KS + API + worker against the disposable AI
Engineer remote (MC 1.13.0), the W1 topology (no Docker). Producer `claude-haiku-5-5` by default (Sonnet only in E1);
judge `gpt-5.6-terra`, auditor `claude-haiku-5-5`. Small, frozen inputs (one to three sources). Biotech joins after its
remote gets the 1.13.0 rollout.

| # | Workflow | Shape | Stresses | Fault / intervention overlay |
| --- | --- | --- | --- | --- |
| E1 | Goal Loop report (W1 fixture) | executor + independent verifier, 2 iterations max, report + text promises, held review | verifier bound (D41), repair feedback, Fulfillment@1, D27-D29 live | worker kill mid-executor activity (D39) |
| E2 | Stage Graph fan-out / join | 4 stages: two parallel collectors → `all` join → synthesizer, exact transfers | Context Packets, `materialize` vs `reference` expansion, per-stage capability pins | queued instruction at a stage boundary |
| E3 | Stage Graph route + revisit | collector → checker with typed route facts → bounded revisit region → writer | routes and revisit (never run paid), carried prior exit output | `interrupt_and_inject` mid-checker |
| E4 | Linked chain | Mission A Stage Graph supplies `evidence_map` → Mission B Goal Loop consumer (`goal_accepted`) | cross-mission transfer, release, consumer context | cancel A after release (`continue`) ; transient transport fault (D40) |
| E5 | Nested body | Stage Graph whose middle stage is a Goal Loop (`sprint-oc-w5` goal-in-graph) | child run, export receipt, adoption, nested context | fork from a cognition point after the nested stage |

**Coordinator agent.** In every run, one Claude Code subagent acts as the Mission Control agent: it has only the
`skills/mission-control` bundle, `missionctl` and the operator HTTP/MCP surfaces (no database, no Temporal CLI). It
watches the mission, answers a fixed question set (what is running, why is it waiting, what did the last turn see,
what failed and why, what will the next stage receive) and issues the overlay's intervention. Every question it cannot
answer from those surfaces is an inspection gap.

## 4. Critique rubric (per run, from the transcript and inspection)

1. **Lifecycle**: phases and waits match the design; terminal outcome and cause are visible from `/inspection`.
2. **Context transfer**: each Context Packet holds what the stage needs, no more (size, duplicates, missing inputs).
3. **Materialization**: mounted skills, tools, MCP and sandbox match the authored node; unused mounts noted.
4. **Prompt and messages**: system vs user placement, instruction clarity, tool-schema weight, turn count per role.
5. **Recovery**: the overlay fault recovers or fails closed with a typed, inspectable cause; no duplicate cognition or write.
6. **Coordinator answerability**: questions answered from public surfaces only; time and calls needed.
7. **Cost**: tokens and USD per stage and role against the declared budget.

Each finding gets one of: **fix** (defect, test-first), **improve** (prompt, packet or doc change), **create** (a missing
capability, filed with a `Goal:` line), or **document** (a concept or runbook gap).

## 5. Loop protocol and budget

**Owner decisions (2026-11-02):** D41 is fixed by enforcing the authored run budget inside the turn (one limit; D38 must
make the ledger record consumption), not by a second per-role call limit. The loop's cap this session is **USD 6**.

- **Iteration 0 (no spend):** fix D41, D38, D39, D40 and the `unit_failures` blind spot test-first; generalise
  `scripts/sprint_oc_w1_driver.py` into a manifest-agnostic driver; author E2-E5 small fixtures; offline compile all five.
- **Iteration n:** run E1-E5 (one runner agent, sequential, memory floor 1.5 GB), coordinator agent per run, critique
  table per run in `.scratch/sprint-oc/experiments/iter-<n>/`, then fix/improve, commit, rerun. Stop a run at a hard
  blocker and still critique what ran.
- **Budget:** about USD 1-2 per iteration with Haiku producers (E1 Sonnet about 0.2); cap USD 6 for the loop this
  session, inside the USD 15 session cap. Every reservation and actual goes to the run ledger.
- **Exit:** two consecutive iterations with no new fix-class finding on a workflow promote it to its W-gate qualification
  run (independent reviewer).
