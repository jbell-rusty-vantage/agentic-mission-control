---
type: Decision Record
title: "Watchers are compiled, bounded, deterministic descriptors evaluated by one Temporal-scheduled evaluator"
description: "Accepted for the materialization-observation packet (SPEC-04 §5, MO-44, gap G7): manifests declare watchers (a closed trigger, an ADR-0010 condition, typed actions, mandatory boundaries) that compile into watcher descriptors on the mission definition; one Watcher Evaluator per run, scheduled only by Temporal, plans firings from the journal, signals and its clock, acts only through admitted Commands and records watcher.fired or watcher.failed keyed by (watcher_id, trigger_key)."
tags: [mission-control, adr, accepted, watchers, manifest, temporal, coordinator-inbox]
status: accepted
source: docs/specs/archive/materialization-observation-2026-10/SPEC-04-watchers-and-callbacks.md (§5); GAP-REPORT G7; research/codebase-observation.md §4, §6 and §7 (G3, G11); ADR-0004; ADR-0010; ADR-0032; ADR-0040; ADR-0049; domain/programs/watchers.py; application/watchers/; adapters/temporal/workflows/watchers.py
---

# Watchers are compiled, bounded, deterministic descriptors evaluated by one Temporal-scheduled evaluator

**Status: accepted 2026-11-01; implemented by the materialization-observation Run 2 finish (`b95ae4aa` completion summary; `152a3dcb` finish records, 2026-10-20) and the 1.4 database release (`b434e573`).** Previously proposed. 

A manifest could not declare what should happen when something is observed. `controls.notifications`
was parsed and ignored, `channel: mcp` subscriptions were never delivered, and an `event_wait` node was
released only by an operator's `satisfy_wait`. The owner's previous automation filled the gap with
supervisors, scheduled wakeups, HTTP callbacks, poll loops, stop hooks and ledgers, each rebuilding
durability, dedupe and stop semantics, and each failing on races, wrong targets and orphaned loops.

We make a watcher a declared, compiled and bounded part of the program. `controls.watchers` (mission/v2)
names exactly one trigger (`event`, public aliases included; `signal`; `absence` of events, frames or
signals for a duration; an interval `schedule`), an optional `where` over the trigger and `while` over
the run in the closed condition AST of ADR-0010 (paths over `event`, `run`, `unit` and `watcher`,
comparisons, `in`, `exists`, `startswith`; no names, calls or code), one to eight typed actions and
its limits. Reusable bodies are published as the catalog Capability Kind `watcher` (`mc.watcher.v1`)
and named by exact pin; the entry may only narrow the template's limits. Compilation resolves every
boundary (`max_fires`, `min_interval`, a rate, recursion depth, a usage budget for `instruct`, the
minimum signal trust tier, an optional `until`), filling defaults from the coordinator profile's
defaults, and stores each watcher as an immutable `mc.watcher_descriptor.v1` on the mission
definition (the Compiled Program), checked against the mission's command grants, its `event_wait`
stages and its budget. `controls.notifications` becomes sugar for notify-only watchers on public
event types or significance kinds with `channel: inbox` only; mission/v2 rejects `channel: mcp`, and
mission/v1 compiles with warnings for both dead fields. Every `event_wait` stage now holds on a
declared StageGraph wait and carries an implied watcher whose `match` is its condition and whose one
action satisfies that wait. Because the StageGraph declares that wait only on reaching the stage, a
`satisfy_wait` firing is held, neither issued nor counted, until the run's inspection shows the wait
active; the workflow carries the held trigger between passes, so an event that comes before the stage
still releases it.

Actions map onto existing paths only: `notify` is one coordinator inbox notification of a
significance kind (never a second notification of a fact the inbox already notifies as that kind),
`instruct` is `queue_instruction` or `interrupt_and_inject`, `satisfy_wait` releases an `event_wait`
stage, `command` is `pause`, `cancel` or `request_continuation`, and `probe` reads the run's
inspection. Every action is an admitted Command through `MissionControlService` under the evaluator's
own principal; signals and provider outcomes stay evidence, never authority, and signal payloads reach
an instructed agent only as quoted, labelled data.

One Watcher Evaluator runs per run as the `mc.watchers.v1` workflow, started by manifest start on its
own task queue; Temporal alone schedules it (ADR-0004). Each pass is one activity that reads the
journal and signal frames after its cursor, the run's firing history and inspection, plans with the
pure `plan_watchers`, issues each firing's actions with request ids derived from
`(watcher_id, trigger_key, action index)` and appends one `watcher.fired` (every action admitted) or
`watcher.failed` event under the event id `watcher.<outcome>:<run>:<watcher>:<trigger_key>`, which is
also the ledger commit key and the outbox delivery key. Between passes the workflow sleeps until the
earliest absence or schedule deadline, or its poll interval, and never less than a second. A due
clock that `min_interval` or the rate holds fires at the moment they allow, which is its deadline,
so a reported deadline always lies after the pass. The journal is the only state: a
replayed history issues nothing, a retried pass re-plans the same facts and its commands replay by
request id, and a fresh evaluator over the same journal finds every firing in history. Firings past a
boundary are suppressed and reported by the pass; a failing action is retried within the pass and
then dead-lettered as `watcher.failed`, which the inbox classifies as `failed`.

We rejected running watchers in the API's subscription relay loop (absence and schedule need durable
timers, and a loop in the API process would be a second scheduler), storing watcher state in new
tables (the journal already orders, dedupes and replays it), and free-form expressions or webhooks to
agent-written code (not replayable, auditable or injection-proof).

## Consequences

- `launch` (child mission or chain link through a Spawn Grant), `human_task`, `webhook` and
  `run_check` actions, the S6 `watch` trigger, cron schedules, debounce and batch windows and
  node-level `controls` are not in the schema yet; a manifest that names them is rejected, so no
  declared field is dead. `launch` needs a Spawn Grant and a mission template or remote launch path
  that do not exist yet.
- Signals are observed as Native Event Store frames whose native kind is `signal.<type>` with a JSON
  body carrying `data` and `trust_tier` (the IngressDrainer's representation, SPEC-04 §3, MO-40/41).
  A signal without a recognised tier is the lowest tier, and an environment key never drives
  `instruct` or `command`.
- An `event_wait` stage still runs its stage operation after release; its `timeout` and `rearm` are
  not enforced (compile warns, and refuses `rearm`). Every chain member the chain relay starts gets
  an evaluator, which ends on its first pass when the member declares no watchers.
- A run whose definition declares watchers is not started where no evaluator is composed. Manifest
  start and the chain relay start the evaluator before they launch the run. The start is idempotent,
  so a start that fails between the two is retried in full, and a launched run always has its
  evaluator. A launch that is refused leaves an evaluator polling a pending run until the run is
  launched or completes.
- No new SQL: descriptors live in the definition snapshot, history in the journal. The catalog
  records a watcher template under the coarse asset kind `policy` with definition kind `watcher`.
