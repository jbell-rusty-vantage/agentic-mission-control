---
id: observe
title: Check in on a run and accept its results
summary: Wait on your coordinator inbox, inspect on a wake, read evidence on demand, and tell execution from acceptance.
---
Wait; never poll. Your coordinator inbox is the wake channel, inspection is the authoritative state, and the transcript and outputs are the evidence.

## The loop

1. Wait. Block on {op:inbox_wait} with the inbox `subscription_id` from the start receipt (find it again with {op:inbox_list}). The wait returns when a notification is pending, or an empty page at its deadline: an empty page is not a failure, so wait again. Name `kinds` to wake only for what you act on.
2. Inspect once. On a wake, read the run with {op:inspect}: `lifecycle`, `phase` and `execution_outcome`, with the `version` and `execution_generation` a later command must name.
3. Decide, then acknowledge. Handle the notification, then acknowledge it by id with {op:inbox_ack}. An unacknowledged notification is delivered again.

{{generated}}

## What each notification asks of you

- `review_required`: a Human Task is open. Read it with {op:human_task_list}; resolve it with {op:human_task_resolve} only on the reviewer's decision, never on your own.
- `blocked`: the run waits on a condition, an approval or owner setup. Inspect, find the wait, tell the user.
- `failed`: read the cause in the inspection and the transcript before proposing a retry or a fork (topic `control`).
- `terminal_result`: execution ended. Report the outcome and the acceptance separately.

## Evidence on demand

- {op:transcript}: what the run did, in order, behind a cursor. {op:run_search} finds entries by text.
- {op:outputs}: the outputs the mission promised, their accepted revisions, the assessments and what is still unmet.
- {op:points}: the recorded positions a fork can start from (topic `control`).
- {op:chain}: the members and links of a Mission Chain. {op:run_list}: runs by state.

## Execution is not acceptance

`execution_outcome: completed` says the agents finished. The mission is accepted only when its success criteria are: an assessment passed, or a reviewer resolved the Human Task its criterion opened. Report three facts apart: how execution ended, which promised outputs are accepted, and what still waits for review. A provider's own finished status is evidence, never a result.
