---
type: Concept
category: execution
title: Watchers and the Watcher Evaluator
description: How a manifest declares watchers (trigger, closed condition, typed actions, mandatory boundaries), how they compile into watcher descriptors, how the per-run mc.watchers.v1 evaluator fires them through admitted Commands and records watcher.fired or watcher.failed exactly once, how controls.notifications and event_wait use them, and what is not built (MO-44, proposed ADR-0046).
tags: [mission-control, watchers, manifest, temporal, coordinator-inbox, implementation]
aliases: [Watcher Evaluator, mc.watchers.v1, event_wait, watcher descriptor]
questions:
  - How do I declare a watcher that fires on a signal or a stall?
  - What can a watcher do when it fires and what is it forbidden to do?
  - How does the Watcher Evaluator stay deterministic and replay safe?
  - Which watcher actions and triggers are not built?
updated: 2026-11-01
---

# Watchers and the Watcher Evaluator

A [Watcher](../../GLOSSARY.md) turns an observed fact into a bounded, admitted reaction
([SPEC-04 §5](../specs/archive/materialization-observation-2026-10/SPEC-04-watchers-and-callbacks.md),
proposed [ADR-0046](../adr/0046-watchers-as-compiled-bounded-deterministic-descriptors.md)). It
replaces ad hoc supervisors, poll loops, stop files and callbacks with a declaration that compiles,
is checked, and runs on Temporal with the journal as its only state.

## Declaring watchers

`mission/v2` `controls.watchers[]` entries (`domain/programs/watchers.py`, `WatcherDeclaration`):

```yaml
controls:
  commands_allowed: [pause, cancel, queue_instruction, satisfy_wait]
  watchers:
    - id: ci-red-fix
      on:
        signal: github.check_suite.completed
        where: "event.conclusion == 'failure' and startswith(event.head_branch, run.branch_prefix)"
      then:
        - instruct: { text: "CI is red; fix it.", include: [event.summary] }
      limits: { max_fires: 3, min_interval: 10m }
    - id: stalled
      on: { absence: { of: [frame, signal], for: 20m }, while: "run.phase == 'active'" }
      then: [ { notify: { kind: blocked, text: "No progress for 20 minutes" } }, { probe: {} } ]
      limits: { max_fires: 2 }
    - { id: stall, pin: "stall-detector@1#sha256:…", limits: { max_fires: 1 } }
  notifications: { on: [run.completed, blocked], channel: inbox }
```

- **Trigger** (`on`), exactly one: `event` (a mission event type or `family.*`, public aliases such
  as `run.completed` included), `signal` (an ingested signal type), `absence` (`of` events, frames
  and/or signals, `for` a duration) or `schedule` (`every` a duration).
- **Conditions**: `where` filters a fact trigger, `while` gates on the run. Both are the closed AST
  of ADR-0010 (`domain/programs/watcher_conditions.py`): paths under `event`, `run` (`id`,
  `lifecycle`, `phase`, `outcome`, `version`, `branch_prefix`), `unit` (`key`) and `watcher` (`id`,
  `fires`); `== != < <= > >=`, `in`, `not in`, `and`, `or`, `not`, `exists(path)`,
  `startswith(a, b)`; string, decimal, boolean, null and list literals. A missing path is null;
  anything else is a schema error, as is a literal outside the vocabulary of `run.phase` (`pending active waiting paused cancelling terminal`), `run.lifecycle` (`pending running paused
  completed`) or `run.outcome`. SPEC-04's `run.branch`, `run.phase == 'executing'` and `instruct.text_ref` are refused: use `startswith(event.head_branch, run.branch_prefix)`, `'active'` and `text`.
- **Actions** (`then`, one to eight): `notify {kind, text}`, `instruct {text, include, delivery:
  queue_instruction | interrupt_and_inject, boundary}`, `satisfy_wait {node}`, `command {kind:
  pause | cancel | request_continuation, urgency}`, `probe {}`.
- **Limits** (`limits`) and lifetime (`until: {event} | {deadline}`).
- **Pins**: a published `mc.watcher.v1` template (definition kind `watcher`, catalog asset kind
  `policy`) supplies `on` and `then`; the entry may only narrow its limits.

`controls.notifications` is sugar: each `on` entry is a public event type or a significance kind
(`review_required`, `review_closed`, `blocked`, `failed`, `terminal_result`, `accepted_output`,
expanded to its event set) and becomes a notify-only watcher (`notifications:<entry>:<n>`); the only channel is `inbox` (mission/v2 rejects `channel: mcp` on `controls.subscriptions`;
mission/v1 parses both unchanged and compile warns `notifications_unconsumed`, `mcp_channel_undelivered`).

## Compilation

`domain/authoring/mission_watchers.py` compiles a mission's watchers into
`mc.watcher_descriptor.v1` (`WatcherDescriptor`) on `MissionDefinition.policies.watchers` (an
additive field: definitions without watchers keep their digest). Every boundary is resolved:
`max_fires` (default 12), `min_interval`, a rate (default 12 per 300 s), `max_depth` (default 2),
a `budget` (`tokens`, `usd`) checked for `instruct`, `min_trust` (`provider_signed` when the
watcher can `instruct` or `command`, otherwise `environment_key`; driving actions never accept less)
and `until`. Compile blocks a `satisfy_wait` naming no `event_wait` stage, an action kind
`commands_allowed` does not grant, a budget above the mission budget and a duplicate id. Pinned
entries resolve through the catalog in `ManifestCompileService._watchers`.

Every `event_wait` stage (a Stage Graph child, or a one-stage root) now lowers with a declared
StageGraph wait (`manifest_lowering.py`) and carries an implied watcher `event_wait:<node>`: its
trigger is the node's `event_type`, its condition the scalar `match` fields, its one action `satisfy_wait` on `stagegraph-wait:<node>`, `max_fires: 1`, no extra grant. `rearm` and nested
`match` values are refused; `timeout` is accepted with a warning and not enforced. The StageGraph declares the wait only when it reaches the stage, so a `satisfy_wait` firing is held while the
run has no such active wait (an event that comes first is neither issued nor counted; the first pass that sees the wait active releases it); a due `absence` or `schedule` clock stays due likewise.

## The Watcher Evaluator

`mc.watchers.v1` (`adapters/temporal/workflows/watchers.py`) runs once per run on
`<root task queue>-watchers`, started by manifest start (`TemporalWatcherStarter`, id
`mc/<installation>/<application>/run/<run>/watchers`, reject-duplicate) and by the chain relay for
every released member. A run with watchers is not started where no starter is composed. Both
start the evaluator before they launch the run, so a retried start whose first attempt failed
between the two still gets its evaluator (a launched run answers `run_not_pending`). Each pass
is one `watchers.evaluate` activity (`application/watchers/service.py`):

1. read the descriptors from the committed definition snapshot, the run's inspection, the journal
   events and signal frames after the cursor (events by sequence, signals by insertion time, so a
   spooled signal uploaded late is still read), the firing history, the last event/frame/signal
   time and the run's budget usage (`adapters/postgres/watchers.py`);
2. plan with the pure `plan_watchers`: per fact in order, then the absence and schedule clocks.
   A firing is keyed by `(watcher_id, trigger_key)` (`event:<id>`, `signal:<frame>`,
   `absence:<baseline>`, `schedule:<tick>`); an absence is measured from the latest of arming, the
   last observed source and the last firing, so one silence fires once. A due clock that
   `min_interval` or the rate holds fires at the moment they allow it, which is its deadline;
   every reported deadline lies after the pass;
3. refuse past a boundary (`recursion_bound`, `trust_tier`, `max_fires`, `min_interval`,
   `rate_limited`, `budget_exhausted`; failed firings count too). Depth is the trigger's depth plus
   one: a fact caused by a watcher's command inherits that firing's depth;
4. issue every action as a Command through `MissionControlService` under
   `system:watcher-evaluator`, with request id uuid5 of the run, watcher, trigger key and action
   index; a stale frontier is rebuilt, a refusal is recorded, a request id run control already
   answered under an older frontier (`IdempotencyConflict`) is `replayed`, and a transient
   failure is retried `attempts` times and then dead-lettered;
5. append one `watcher.fired` (every action admitted or replayed) or `watcher.failed` event under
   `watcher.<outcome>:<run>:<watcher>:<trigger_key>`, the ledger commit key and outbox delivery key.

The workflow keeps only the cursor, the retired watchers, the held `satisfy_wait` triggers and the
arming time, sleeps until the earliest clock deadline or its poll interval (at least one second),
ends after the pass that finds the run terminal and its journal read (a notify on `run.completed` fires before that), and continues as new every 500 passes. A replayed history issues nothing, a retried pass replays its
commands by request id, and a fresh evaluator over the same journal finds every firing in history.

`notify` needs no command: the coordinator inbox classifies `watcher.fired` with `notify_kind` as
that kind (with `watcher_id`, `trigger_type` and `message` as facts) unless its trigger already is
that notification there; `watcher.failed` is `failed`. `instruct` appends included facts as a
quoted block labelled untrusted data. Signals are frames whose native kind is `signal.<type>`; the
body's `data` is what conditions read and `trust_tier` its tier (absent: the lowest).

## Not built

`launch` (a child mission or chain link needs a Spawn Grant and a mission template or the remote
launch route), `human_task`, `webhook` and `run_check` actions, the S6 `watch` trigger, cron
schedules, debounce and batch windows, `event_wait` timeouts and rearm, node-level `controls`, and
the standard watcher library (MO-46). A released `event_wait` stage still runs its stage operation.

Built / specified / goal: declaration, compile, evaluator, `notify`/`instruct`/command actions and external source watches built and tested on real PostgreSQL and Temporal; the actions above are specified, not built.

## External sources
MO-45 registers trusted sources through `MISSION_CONTROL_SOURCE_WATCHES` (JSON list, max 16).
Entries bind `id`, `request_scope`, `run_key`, `harness_execution_id`, `generation` to a live execution.
`kind`: `github_checks` requires `repository`, `ref`; `github_pull` requires `repository`,
`pull_number`; `worker` requires `worker_host` (hostname), `watch: {kind, resource, pattern?}`. GitHub uses
repository-scoped App credentials. Worker resources are operator-owned absolute file/log paths,
positive process PIDs or credential-free HTTPS URLs. Literal log matching reads a 64 KiB tail;
persisted evidence contains metadata, never log text. GitHub checks polling reads at most 100 suites.
The existing Temporal watcher activity samples before evaluating; durable timers own repetition.
Stable evidence keys deduplicate retries. Non-closing STATUS frames at conservative `provider_signed`
trust cannot settle runs. Existing schedule/absence descriptors need no separate poller.
The manifest `watch` trigger and cron syntax remain closed. Verified GitHub check_suite/pull_request/push
and Cursor v0 statusChange persist normalized `source_signal` inbox envelopes; Cursor's watcher name
is `cursor.status_change`, with FINISHED/ERROR as data. HTTP does not bind executions or write frames.
MO-75 (Run 2) owns inbox draining. Ingress persistence and trusted sink/evaluator proofs are separate;
real PG/Temporal source tests: `tests/integration/postgres/test_mo45_source_watches.py`.

## Citations
- Spec: [SPEC-04 §5 and §8](../specs/archive/materialization-observation-2026-10/SPEC-04-watchers-and-callbacks.md), [MO-44](../specs/archive/materialization-observation-2026-10/issues/MO-44-watchers-schema-compiled-descriptors-evaluator-actions-and-boundaries.md); ADRs [0004](../adr/0004-temporal-sole-scheduler-transactional-outbox.md), [0010](../adr/0010-completion-expressions-closed-typed-ast.md), [0040](../adr/0040-native-frames-normalized-lifecycle-lineage-graph-bounded-coordinator-subscriptions.md), [0046](../adr/0046-watchers-as-compiled-bounded-deterministic-descriptors.md) (proposed), [0049](../adr/0049-deprecate-mission-subscribe-push-in-favour-of-inbox-wait-channels.md) (proposed).
- Code: [conditions](../../src/mission_control/domain/programs/watcher_conditions.py), [watchers and planner](../../src/mission_control/domain/programs/watchers.py), [mission watchers](../../src/mission_control/domain/authoring/mission_watchers.py), [evaluator](../../src/mission_control/application/watchers/service.py), [PostgreSQL store](../../src/mission_control/adapters/postgres/watchers.py), [workflow](../../src/mission_control/adapters/temporal/workflows/watchers.py), [activity](../../src/mission_control/adapters/temporal/activities/watchers.py), [starter](../../src/mission_control/adapters/temporal/watcher_starter.py), [worker composition](../../src/mission_control/adapters/temporal/watcher_composition.py), [inbox classification](../../src/mission_control/application/subscriptions/coordinator.py).
- Tests: [unit](../../tests/unit/watchers/), [Temporal](../../tests/integration/temporal/test_mo44_watchers_workflow.py), [PostgreSQL](../../tests/integration/postgres/test_mo44_watchers_postgres.py).
