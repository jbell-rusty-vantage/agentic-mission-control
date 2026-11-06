---
name: mission-control-observe
description: Supervise Mission Control runs with durable inbox waits, inspect state after a wake, read transcripts and delivery reports, or declare bounded watchers. Use for launch-then-wait, supervising several runs, recovering pending notifications, investigating a blocked run, or choosing a watcher reaction.
---

# Supervise a run

Use the coordinator inbox as the wake channel. Inspection supplies authoritative
state; notifications and transcripts supply evidence. Report `lifecycle`, `phase`
and `execution_outcome` from inspection separately; notification facts call the last
field `terminal_outcome`. A provider FINISHED status is evidence only.

## Choose the branch

| Need | Read or do |
| --- | --- |
| Launch, then wait; supervise several runs; recover after disconnect | [Wait recipes](references/wait-recipes.md) |
| Explain what the run or a control did | Inspect, then read evidence below |
| React automatically to CI, silence, a marker or an artifact | Declare watchers below |

## Wait, inspect, acknowledge

1. Record the admitted run and launch receipt. Use the launcher's coordinator inbox,
   or let `missionctl wait --run` find/create the caller's durable inbox from sequence 0.
   A run that finishes before the wait starts still wakes it.
2. Block on a bounded wait:

   ```text
   missionctl wait --run RUN_ID --kinds terminal_result,blocked,review_required,failed --wait 600
   ```

   stdout is JSONL notifications; stderr identifies the inbox. Exit 0 means a matching
   notification arrived; exit 6 means the deadline expired. A timeout is not run failure.
   Use the host's background task when other work must proceed; its exit wakes the
   coordinator. In a foreground turn, wait directly. The durable inbox survives
   disconnects; an optional MCP hint is only a wake-up hint.
3. On a wake, inspect the affected run once:

   ```text
   missionctl run inspect RUN_ID --json
   ```

   For blocked/review notifications, identify the active wait, approval or owner step.
   For a terminal result, report the terminal outcome and acceptance separately.
   Before control mutations, read `version` and `execution_generation` and use the
   intervene skill. Done when each notification has a disposition.
4. Acknowledge the handled notification by exact id:

   ```text
   missionctl inbox ack SUBSCRIPTION_ID --id NOTIFICATION_ID
   ```

   One-shot waits replay pending items until acknowledged. Repeating the ack is safe.
   Use wait's `--ack` only when printing is itself sufficient handling. Use `--through`
   only when every earlier inbox item was handled.

## Inspect evidence on demand

```text
missionctl run transcript RUN_ID --format jsonl --since CURSOR
missionctl run search RUN_ID --query "pytest failed" --json
missionctl command list RUN_ID --json
missionctl chain inspect CHAIN_ID --json
```

Read [transcript-format.md](references/transcript-format.md) when interpreting frames
or resuming a transcript cursor. A tool-call transcript proves an attempt; the effect
ledger proves the effect. On `CURSOR_EXPIRED`, resync inspection and obtain a fresh
cursor. Inspect requested, delivered and applied separately in Delivery Reports;
cancellation settles after children, effects and usage reconcile. Estimated usage
is not settled billing. Missing inspection sections indicate an uncomposed source.

## Declare bounded reactions

Use mission/v2 `controls.watchers` before submit. Each watcher declares a closed
trigger/condition, typed actions and limits. Standard catalog templates cover
stall-detector, result-marker-stop, ci-watch, pr-merged-release-wait, artifact-pipeline,
budget-guard and heartbeat-progress. Resolve exact pins with the catalog skill;
pin overrides may only narrow limits. For inline syntax, read the author skill's
`references/manifest-cheatsheet.md`. Compile until the report has no blockers.
`mission/v2` notifications lower to notify-only watchers; `mission/v1` notifications
remain unconsumed and warn (`src/mission_control/domain/authoring/mission_watchers.py`). Use durable
inbox waiting for caller wakeup; a declaration or an MCP push hint is not delivery.

Watchers use admitted commands and the coordinator inbox. Result markers request
cancellation; successful completion remains a reducer decision. Artifact evidence
continues an admitted pipeline; custody and acceptance remain separate. External
polls and worker watches require trusted operator registrations bound to live
executions. Webhook draining requires configured worker ingress and actual
PostgreSQL/Temporal wake proof; webhooks trigger native reconciliation rather than
acceptance or publication. Existing schedule
and absence triggers work; manifest watch/cron and automatic launch actions remain
unavailable.

For diagnostic event consumers, `missionctl events watch` reads the durable event
stream. Coordinator supervision uses wait and acknowledgement. Legacy
`mission_subscribe` push is deprecated; recover through the durable inbox.
