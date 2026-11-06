---
type: Concept
category: execution
title: Provider batch inference (goal)
description: The goal of making provider batch API requests (Anthropic Message Batches, OpenAI Batch) from a mission and letting a workflow wait durably on the output and continue - what batch would add, the existing Temporal wait patterns it would reuse, the proposal that exists outside this repository, and the fact that nothing is built.
tags: [mission-control, provider-batch, goal, batch, anthropic, openai, temporal, proposal]
aliases: [batch API, Message Batches, OpenAI Batch, inference executor, batch wait]
questions:
  - Can a workflow submit a provider batch and wait for the output?
  - What exists today for Anthropic or OpenAI batch requests?
  - How would a Temporal workflow wait on a provider batch?
  - Why is a provider batch not a lane?
updated: 2026-11-01
---

# Provider batch inference (goal)

**Goal (owner, 2026-11-01):** "The Provider batch prototype and proposal should be included as well. This includes making batch api requests to
anthropic and openai and getting the output. In a workflow the workflow could wait on the output and then continue. Again this is a goal."

**Status: proposal only. Nothing is built.** Searching the workspace on 2026-11-01 (`platform/knowledge-services`, `platform/agentic-sdlc`,
`aiengineer`, `biotech`, every scratch folder, hidden folders included) found a written proposal and its evidence register, and no prototype or
code: no `messages/batches`, `/v1/batches`, `msgbatch_`, `batch_collect` or inference-executor symbol in `src/`, `packages/` or any other
repository. The `batch` hits in `biotech-knowledge-services` are OpenAI vector-store file batches, unrelated. The owner's word "prototype"
therefore points at the proposal's phase P0 ("standalone core"), which has not been started.

- Proposal: [the proposal](../specs/proposals-2026-10/PROVIDER-BATCH-INFERENCE-PROPOSAL-2026-10-18.md) (382 lines, dated 2026-10-18, status *proposal*, "post-sprint work") and
  [the evidence register](../specs/proposals-2026-10/PROVIDER-BATCH-INFERENCE-EVIDENCE-2026-10-18.md) (74 rows). Copied into the [proposals program](../specs/proposals-2026-10/LEDGER.md) on 2026-11-01; the originals stay in the umbrella `platform/` directory, **which is not a git
  repository**; the vendor facts are copied into [batch APIs](../research/provider-batch/batch-apis.md).
- Parent design: [the next-stage contract design](../specs/proposals-2026-10/MISSION-CONTROL-NEXT-STAGE-CONTRACT-DESIGN-2026-10-16.md) section 6 ("Durable external workloads, batches and cache economics").

## What batch would add

Batch is 50% of standard price on both providers, uses separate rate-limit pools, and fits many independent items where latency of
minutes to hours is acceptable (research, ingestion, evaluation, maintenance). A batch item is one stateless bounded unit of cognition;
Anthropic items may run a server-side agent loop (web search, code execution). Batch cannot stream, pause, call client tools mid-item or hold a
conversation, so anything multi-turn is built as *waves* (map, validate, reduce, next wave). Neither provider is ZDR or HIPAA eligible, so PHI and
regulated data are denied and `confidential` data needs short expiry plus deletion after custody
([batch APIs](../research/provider-batch/batch-apis.md)).

## Why it is not a lane

A [lane](lanes-and-harness.md) implements the session and turn protocol (`prepare`, `send_turn`, `cancel_turn`, `observe`, `snapshot`...). A batch has no
session, no turns, no pause and no client-tool callback. The proposal models it as an **Inference Executor** program behavior with a `dispatch` mode
(`batch` first; `sync`, `flex`, `background` later) instead of an Agent Executor with a `direct_model` lane. No `direct_model` lane exists
(`domain/execution/lanes.py` has no such profile) and the choice needs an ADR (proposal section 11, decision 2).

## How a workflow would wait (patterns already in the code)

1. **Sleep with a hint, then re-read.** `HumanGateWorkflow` (`adapters/temporal/workflows/human_gate.py:48`) waits on `workflow.wait_condition` over a
   resolution-hint signal and a poll/deadline timer, holds no activity slot, and on every wake re-reads the persisted task, the only authority.
   Operation workflows do the same with `ingress_wake` (`operation.py:497`) and a bounded `lane.status` read.
2. **Provider webhook to wake.** `POST .../provider/{provider}` (`interfaces/http/ingress.py:118`) verifies Standard Webhooks, dedupes on
   `webhook-id` and stores a `ProviderWake` (event type and resource id only; `application/signals/wake.py`); the drainer signals the workflow
   (`bootstrap/ingress_drainer.py:355`). OpenAI's `batch.*` events fit this path; the wake map lists only `anthropic` and `openai` envelopes and no
   batch event catalog, and the drainer resolves a wake to a **lane session** by `native_session_ref` (`ingress_drainer.py:300-313`), so a batch id
   needs its own binding.
3. **Anthropic has no completion notice** (register row AB16). It needs a scheduled **Batch Observer** (a Temporal schedule that lists in-flight
   batches per provider account, newest first, and emits a wake on change). Not built.
4. **Bounded waits and capacity.** `wait_for_limit_reset` (`domain/execution/usage_admission.py:249`) and `_wait_out_capacity` already turn a provider
   limit into a Temporal timer bounded by the unit's budget; `_wait_settlement` is the durable-timer pattern for saved results.
5. **Ambiguous submit.** The dispatch journal pattern (park `in_doubt`, never blind re-create; [session ownership](session-ownership-and-dispatch.md))
   is the model; OpenAI can match a created batch by `metadata`, Anthropic cannot (dedicated workspace plus fingerprint, or park).

Wait strategies the proposal names, expressed in vocabulary the code already has: *await all* (`required` dependency, join `all`), *await enough*
(`degradable`, join `minimum` plus deadline), *submit and continue* (a ticket output, a later `batch_collect` durable control or dependent stage),
*progressive* (per-shard release), *detached* (`advisory`, ticket to a successor mission). The code's `DependencyClass` is
`required|degradable|optional|advisory` and `JoinKind` is `all|any|minimum` (`domain/authoring/contracts.py:328,335`); the proposal's
`required_blocking`/`nonblocking` names are not code. Key law: a provider terminal state is not acceptance; release depends on item dispositions, validation
and the completion contract ([completion](completion.md)). Spend uses `reserve`/`settle` (`domain/execution/usage_admission.py:422,437`), with missing usage
`unknown`, never zero.

## Proposed phases (none started)

P0 standalone core (envelope, both adapters, sharding and `custom_id`, estimator, journal, list-based observer, one live tiny batch per provider);
P1 MCP server and a `provider-inference` skill; P2 Mission Control integration (Inference Executor, `batch_collect` control, Batch Observer schedule, OpenAI
webhook catalog, artifact custody, ledger settlement, data-class gate); P3 waves and pooling; P4 direct-API modes on the same envelope. Open decisions:
library placement, executor-versus-lane, Anthropic ambiguous-create policy, hosted tools inside batch (OB8), shard size, webhook secret custody,
cost reconciliation keys, `confidential` policy.

Built / specified / goal: **goal**, with a written proposal (uncommitted) and a vendor evidence register; no code, no ADR, no tests.

## Citations

- Proposal and evidence: [proposals ledger](../specs/proposals-2026-10/LEDGER.md) (copies made 2026-11-01; the originals stay in the workspace root `platform/`, outside git); research: [batch APIs](../research/provider-batch/batch-apis.md).
- Code seams: [human gate workflow](../../src/mission_control/adapters/temporal/workflows/human_gate.py), [operation workflow](../../src/mission_control/adapters/temporal/workflows/operation.py), [ingress route](../../src/mission_control/interfaces/http/ingress.py), [provider wake](../../src/mission_control/application/signals/wake.py), [ingress drainer](../../src/mission_control/bootstrap/ingress_drainer.py), [usage admission](../../src/mission_control/domain/execution/usage_admission.py), [dependency classes](../../src/mission_control/domain/authoring/contracts.py).
- Related: [temporal synthesis](temporal-synthesis.md), [signal ingress](signal-ingress.md), [budgets and usage](budgets-and-usage.md), [durable controls](durable-controls.md).
