---
type: Concept
category: operations
title: Budgets and usage
description: "How a budget envelope is reserved before work and settled after, which rules the reducer enforces today, how a Session Lane settlement charges token usage to the run and how provider capacity limits stay separate from budget, and where the spec's integer-micros and unknown-usage rules are still only specified."
tags: [mission-control, budgets, usage, settlement, implementation]
aliases: [budget envelope, usage settlement, capacity limit, spend rule]
questions:
  - How is a budget reserved before work and settled after?
  - What is the current spend rule for paid runs?
  - Why was a model call refused for budget?
updated: 2026-11-02
---

# Budgets and usage

A [Budget](../../GLOSSARY.md) is admitted as a ceiling, reserved before work and settled after. The reducer owns
every ledger transition; nothing else changes a balance. Governors that stop work on depth, rounds or iterations
live in the program interpreters and are not covered here.

## Current spend rule for paid work (OC-D189)

Mission Control's engine rules below are about run budgets; the **owner's spend ceiling for paid model and web
calls** is a separate, standing rule. Sprint OC (OC-D189, DECISIONS) allows at most USD 40 for the sprint,
distributed through the plan (W0 1, W1 6, W2 4, W3 7, W4 5, W5 10, reserve 7), with USD 15 per session inside it
and models chosen from the cost-effective set (OC-D185). Bounded fixture assignments carried their own ceilings and
are finished: up to USD 10 per fixture overnight (OC-D208), USD 100 for the Qualia fixtures (2026-10-30) and USD 60 for
the AI Engineer fixtures (USD 40.94 accounted; NEXT-SESSION lines 25-60). None renews or transfers: the deployment roadmap
states it inherits no spending authority. Any new paid run needs an explicit ceiling in its brief; the root `AGENTS.md` keeps
spend within the owner's stated ceiling. Fixture drivers keep their own USD ledger (the provenance proof's USD 2 per-call
reservation refused parallel stages at a USD 7 cap); no Mission Control code enforces a USD ceiling for a run.

## Specified rules

Admission and child reservation are serialized in the application database; runs stop at a [Governor](../../GLOSSARY.md)
rather than retrying for funds; unknown usage cannot count as zero; cancellation retains reservations until costs settle.
Not built: a usage ledger keyed by `(provider, native_request_id, usage_component)` with a settled, estimated or
unknown disposition, exact rational unit rates in micros and `ProofBudget@1` for authorized live experiments
([qualification](qualification.md)).

## Envelope and state as implemented

`BudgetEnvelope` (`domain/policies/contracts.py`) declares at least one `BudgetDimensionLimit`: a free-form
dimension name (`^[a-z][a-z0-9_.:-]*$`), `applicability` of `bounded`, `unbounded` or `not_applicable`, an
optional `soft_limit` and a `hard_cap` that bounded dimensions must carry. `BudgetState` holds `reserved`,
`consumed` and `pending_settlement` per dimension, reservations by id, usage and settlement records and
`outstanding_usage_ids`. Ledger kinds are `reservation`, `consumption`, `release`, `pending_settlement`,
`settlement` and `adjustment`. Amounts are plain integers; a binding chooses its own dimension names (micros are
not fixed as the money unit).

## Reserve, record, settle, terminalize

The reducer (`domain/policies/reducer.py`) grants `reserve_budget`, `record_usage` and
`settle_pending_usage` only to actors holding `workflow_run.reserve_budget`,
`workflow_run.report_usage` and `workflow_run.settle_usage`. A reservation is checked by
`_enforce_hard_caps` over reserved + consumed + pending and rejected as
`budget_hard_cap_exceeded`. `_record_usage` requires an existing reservation
(`reservation_required`), draws actual, pending-external and release amounts from it,
refuses a release larger than the unused reservation and moves external amounts to
`pending_settlement`. Settlement resolves pending amounts; finalization is rejected with
`budget_not_settled` while any reservation or pending charge remains. A resume must prove
it can re-reserve its next unit (`_probe_reservation`, `insufficient_budget`).

`domain/policies/budget.py::roll_up_child_budget` applies one child account's deltas to
its locked parent: consumption can never decrease, totals can never go negative, parent
hard caps are enforced on new reservations, and parent ledger entries are written per
kind with a child-scoped idempotency id, the serialized child reservation through the parent's own account.

## Unknown usage

What exists is `pending_external_amounts` on a usage record: an amount the provider has not confirmed stays
reserved and pending, so usage is never counted as zero, but there is no `unknown` marker, native usage identity
or price-sheet reference. Agent Server child usage is attributed in
`adapters/deep_agents/async_subagents.py::attribute_usage` ([lanes](lanes-and-harness.md)).

## Session Lane usage and capacity

A manifest Stage Graph unit reserves only `operation.attempts` and `concurrency.slots` (a Goal Loop iteration `goal.iterations`), so a lane settlement charging only bound dimensions recorded no tokens (found by MP-20). Now a Session Lane settlement charges its closing token usage (`LANE_TOKEN_DIMENSIONS`: `tokens.input`, `tokens.output`, `tokens.total`) once to the dimensions the unit reserved or the run declared (`RunBudgetDimensionsPort`, `operation_execution.py`); unknown usage charges nothing and is never recorded as zero, and subagent usage is not counted twice. Open: only the final turn's usage is charged (continuations are not summed) and cost is not charged.
A Deep Agents unit run in `operation.execute` charges the same way (W1 D38): its invocation carries the run's declared in-turn dimensions (`RuntimeInvocation.run_budget_dimensions`: `model.turns`, `tokens.total`, `tool.calls.total`, from `in_turn_run_budget`), the lane reports its spend on them, and the settlement validates them as unreserved run dimensions; before, a Goal Loop iteration (reserving only `goal.iterations`) recorded 0 consumed. Declared dispositions per lane are in the lane describes ([lanes and harness](lanes-and-harness.md)).

## In-turn budget stop, the result point and inspection (tracing Stages 2-3)

The kernel checks usage against an operation's bound limits at settlement (`operation_execution._validate_bound_usage`: `failed/budget_exceeded`, amounts plus pending external amounts compared with `>`). A Deep Agents turn used to run past its reservation to its natural end (live: 25 892 tokens and 8 calls on a 5 000-token reservation). Now `BudgetStopMiddleware` answers instead of the model at the next model call once the invocation's spend, counting what a resumed turn's lineage already spent, **exceeds** a bounded dimension (`tokens.total`, `model.turns`, `tool.calls.total`); reaching a limit exactly stays within budget. The overrun is at most the call that crossed the cap, and the attempt still settles `failed/budget_exceeded` ([Deep Agents lane](deep-agents-lane.md)).

- **The authored run budget is the limit (W1 D41, owner decision 2026-11-02).** Each limit is the tighter of the unit's reservation and what the run's hard cap leaves for it (`in_turn_run_budget`: hard cap less consumed, pending and reserved, with the unit's own reservation and own recorded usage added back; read through `RunBudgetStatePort` when the invocation is built; `adapter.py::_turn_limits`). A manifest's `budget: { tokens, tool_calls }` therefore bounds every Deep Agents turn, a Goal Loop verifier included (live f243e3d8 made 71 tool calls against `tool_calls: 20`). No default `call_limits` feature is involved.
- **Tool calls.** A tool call past `tool.calls.total` is refused before it runs (`ToolMessage(status="error")` marked `mc_budget_stop`; parallel calls are admitted one by one, so they cannot overrun together); the next model call is answered by the stop. Only tool calls that ran are charged (refused and hook-denied ones are marked and never counted).
- **Typed outcome.** The lane returns `RuntimeResult.budget_stop` (dimension to limit and spent); the settlement (inline, saved result or queued turn) settles `failed/budget_exceeded` whenever it is present, and the saved record keeps it, so a re-settlement refuses it the same way. A Goal Loop verifier that fails `budget_exceeded` keeps the family's typed failure (`NON_JUDGED_VERIFIER_FAILURES`).

- **Result point.** `budget_snapshot` carries `usage`, `reservation_id`, the bound `limits`, the
  `exhausted` dimensions (amount plus pending external amount **greater than** the limit, the
  stop rule's `>`; spending exactly the limit exhausts nothing) and the settlement's
  `failure_code` (`settlement_budget_snapshot`).
- **`run inspect`** gains a `budget` section (`BudgetView`, read by `PostgresBudgetViewReader`
  from `canonical.budget_state`): per dimension the hard cap, reserved, consumed, pending and
  `exhausted`, plus the run-level list. The account view marks a dimension exhausted once
  consumption **reached** its cap (`>=`), a different question from the unit stop rule.
- **A provider failure mid-turn keeps its spend.** `RuntimeInvocationFailure` carries the usage of
  every completed model call (parent and in-process children, in the bound dimensions) and the
  partial lineage's points, and the failed settlement records both; before it the unit settled
  with `usage: {}` and no points (`adapter.py::_observed_usage`). T0 proof only
  (`test_fx_tr_disconnect_t0`); the live re-proof was not run.
- **The lane reports no cost.** Usage is `model.turns` and `tokens.total`; no `cost_micros` is
  produced, so the declared `usage.cost: estimated` is not what the lane does, and `currency.*`
  and the run's `external.openai` dimension are never charged by it. The resolved pin carries list
  prices ([model catalog](model-catalog.md), OC-R6); the only reader is the trusted evaluator runner, which prices
  `usage.costUsd` from the `models.toml` row (`adapters/deep_agents/evaluators.py:22-24,183-190`); the run budget
  charges no cost.

Provider capacity limits are not budget: a lane's `ProviderCapacityLimited` becomes a bounded
Temporal wait under the deployment's `MISSION_CONTROL_CAPACITY_*` policy, carried on every operation
request, with no automatic switch to another auth route
([session ownership and dispatch](session-ownership-and-dispatch.md)). A subscription-backed turn
still consumes the run's resource budget.

## Reads

`GET /run-control/v1/runs/{run_id}/budget` returns `BudgetState` on the technical facade;
the application-scoped prefix exposes budget only through inspection
([interfaces](interfaces.md)). No `budget.consumed`, `threshold_crossed` or `exhausted` events exist in `src/`; a live budget view for a dashboard is a goal
([coordinator surface](coordinator-surface.md)).

Built / specified / goal: envelope, reserve/record/settle, lane token charging and the in-turn stop (the run budget
included, W1 D38/D41) are implemented and unit-tested, not yet re-proved live; the unknown-usage ledger, cost charging and budget events are specified or goals; the USD spend rule is a
human and driver rule, not a runtime gate.

## Citations

- ADR: [0011](../adr/0011-distinct-retry-counters-and-retry-classifier.md).
- Code: [budget policy](../../src/mission_control/domain/policies/budget.py),
  [policy contracts](../../src/mission_control/domain/policies/contracts.py),
  [reducer](../../src/mission_control/domain/policies/reducer.py),
  [technical run control](../../src/mission_control/interfaces/http/run_control.py),
  [usage attribution](../../src/mission_control/adapters/deep_agents/async_subagents.py),
  [lane settlement usage and result-point snapshot](../../src/mission_control/application/execution/operations/operation_execution.py),
  [budget stop](../../src/mission_control/adapters/deep_agents/budget.py),
  [observed usage on failure](../../src/mission_control/adapters/deep_agents/adapter.py),
  [runtime failure](../../src/mission_control/domain/execution/errors.py),
  [inspection budget view](../../src/mission_control/application/missions/inspection.py),
  [budget view reader](../../src/mission_control/adapters/postgres/run_control/inspection_repository.py).
- Tests: [boundary commands, resume re-reserve](../../tests/unit/run_control/test_boundary_commands.py),
  [async child parent budget](../../tests/unit/operations/test_async_child_parent_budget.py),
  [RRM-008 cancellation settlement](../../tests/unit/operations/test_rrm_008_cancellation.py),
  [atomic family admission](../../tests/unit/run_control/test_atomic_family_admission.py),
  [lane settlement usage](../../tests/unit/harness/test_lane_settlement_usage.py),
  [budget stop](../../tests/unit/deep_agents/test_budget_stop.py),
  [in-turn run budget](../../tests/unit/deep_agents/test_in_turn_run_budget.py),
  [run budget through the boundary](../../tests/unit/operations/test_in_turn_run_budget.py),
  [turn stops and resumed spend](../../tests/unit/deep_agents/test_turn_stops.py),
  [exactly at the limit exhausts nothing](../../tests/unit/operations/test_fenced_turn.py),
  [disconnect keeps usage and points](../../tests/acceptance/mission_control/test_tracing_stream.py),
  [inspection sections](../../tests/unit/run_control/test_ft_f6_inspection.py),
  [capacity wait on Temporal](../../tests/integration/temporal/test_mp05_limit_wait.py).
