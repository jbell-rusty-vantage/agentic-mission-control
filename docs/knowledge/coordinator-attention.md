---
type: Concept
category: execution
title: "Coordinator attention: six delivery stages, bounded content and exact output inspection"
description: "How a coordinator notice is recorded as six separate observations (notice, transport, host-attested idle wake and model-visible payload bound to a delivery nonce, explicit ack, retrieval) in server receive order, how output/transfer transitions reach the inbox, how bounded excerpts are scoped to a declared purpose and referenced promises, the exact output/fulfillment/transfer inspection surfaces, and the runnable C14 procedure for the selected host (WI-19)."
tags: [mission-control, coordinator-inbox, output-contracts, qualification, sprint]
aliases: [coordinator inbox, delivery stages, notice ack, attention verdict]
questions:
  - Did the coordinator actually see this notice, and when?
  - What are the six observations a notice can have?
  - Why is a webhook 2xx not an acknowledgment?
  - How do output and transfer transitions reach the coordinator inbox?
updated: 2026-11-01
---

# Coordinator attention

The rule (WI-19, OVE-182; [output contracts](output-contracts.md)): durable notice, transport receipt, actual idle-host wake, model-visible payload, acknowledgment and
content retrieval are **six separate observations**; a deterministic client or a callback 2xx cannot
certify them. WI-19 (OVE-182) builds that on the one coordinator inbox of
[wake channels](wake-channels.md) and [events and commands](events-and-commands.md) (ADR-0040, OVE-78).

## The six stages and what each proves

| Stage | Recorded by | What it establishes |
| --- | --- | --- |
| notice | server, at materialization (`sealed_at`) | the notice is durable in the inbox |
| transport | server: an HTTP or MCP answer (`http`, `mcp`) or a webhook attempt (`webhook`: delivered / failed / dead_lettered) | the payload left the server in that answer; a 2xx proves the endpoint answered, never acknowledgment |
| wake | **host-attested** (`background_task_exit`, `monitor_event`, `session_prompt`; `connected_poll` = not idle) | the reporter holds a delivered payload (its nonce) and *says* it was idle since `idle_since` and woken through the channel; channel and `idle_since` are attestations the server cannot check |
| visible | **host-attested** (`task_output`, `tool_result`, `session_prompt`) | the reporter holds that delivered payload and *says* it reached the model; it does not prove a model read or understood it |
| ack | the coordinator's explicit acknowledgment (`acknowledged_at/_by`) | the coordinator closed the notice |
| retrieval | server, at an explicit content retrieval (`delivered`, or `refused` when everything was omitted) | exact revisions were returned to the coordinator |

**Delivery nonce.** Each delivery (every poll/wait answer per notice, every webhook attempt) carries a
fresh 128-bit `delivery_nonce` inside the delivered payload only (`delivery_nonces` on a page, the
signed webhook body, each `missionctl wait` line). The server keeps only its sha256 on the transport
row; attention reads, receipts and listings never return a nonce or the internal notice digest. Wake
and visible must echo a nonce of a *delivered* transport of that notice (`delivery_nonce_unknown`,
`transport_undelivered` otherwise) and are stored with that `transport_key`. So a script that only
saw a webhook 2xx or reads `attention` cannot attest visible.

**Order on server receive time.** `received_at` (server clock) orders stages; host `observed_at` and
`idle_since` are kept as attested data (`attested_*` evidence). A visible report needs an earlier wake
report (`stage_order_violated`); the database guard enforces the same. In the verdict, wake must
follow its delivered transport, visible the wake and ack the visible report, else
`STAGE_ORDER_VIOLATED`: `ack --through` never qualifies a notice without its own visible. Other gaps:
`IDLE_WAKE_UNOBSERVED`, `IDLE_WAKE_UNAVAILABLE` (connected poll only), `VISIBLE_UNOBSERVED`,
`ACK_NOT_EXPLICIT` (a pre-WI-19 callback ack), `TRANSPORT_DEAD_LETTERED`, `RETRIEVAL_UNOBSERVED`.
A `qualified` verdict is consistency between server facts and host attestations, not proof of what
the host did not attest. Trust boundary: the inbox owner, and any actor holding `workflow_run.admin`
(`ADMIN_PERMISSION`), can poll the inbox and so receive nonces; such actors are trusted for the
host-attested stages. A replayed observation key must echo the same delivery's nonce
(`observation_conflict` otherwise), so a key alone reveals nothing. Rules: [domain/coordinator/attention.py](../../src/mission_control/domain/coordinator/attention.py).

**A webhook 2xx is transport, never acknowledgment.** `deliver_callbacks` posts each pending notice
until a 2xx carries it and records every attempt (`webhook:<attempt>`). Without migration 0063 nothing
is posted, one warning is logged per process and pages and listings report
`attention: attention_unavailable` (polling keeps working). Migration
[`0063_coordinator_delivery_observations.sql`](../../scripts/release_180/0063_coordinator_delivery_observations.sql)
is registered in the built 1.8.0 component (`releases/1.8.0/component/manifest.json:294`; `releases/README.md:226-236`): immutable, forced RLS, stage/channel/observer/nonce checks, a guard binding host
stages to a delivered transport and visible to an earlier wake. [Service](../../src/mission_control/application/subscriptions/coordinator_service.py),
[store](../../src/mission_control/adapters/postgres/subscriptions/attention.py).

## Output and transfer transitions reach the inbox

The output stores journal the default actionable transitions **in the transaction of the state
change** through the canonical writer ([attention_events](../../src/mission_control/adapters/postgres/knowledge/attention_events.py)):
`output.fulfilled` / `output.fulfillment_unmet` when a promise's disposition changes (unmet only for
required or expected; the run's final evaluation is how an unmet promise surfaces),
`output.assessment_held` / `_rejected`, `transfer.delivery_refused` / `_waiting`. The inbox classifies
them (`OUTPUT_ATTENTION_KINDS`: accepted_output, blocked, failed) with their facts (`obligation_key`,
`disposition`, `result`, `transfer_plan_id` ...). A run without a `mission_run` row emits nothing.

## Bounded content

Default notices carry references. The **purpose is declared at subscribe time**
(`profile.content.purpose`: `coordinator_review` or `coordinator_triage`); a retrieval cannot assert
another (`purpose_undeclared` when none). Excerpts and retrievals are limited to the promises the
notice itself references (its `obligation_key`; `not_referenced` otherwise), then to the profile's
designation for automatic page excerpts. [`NoticeContentService`](../../src/mission_control/application/subscriptions/notice_content.py)
reads only accepted heads (WI-01), checks the content digest, and names revision, digest, status,
issuer and producer. Gaps are omissions: `GRANT_MISSING` (no `workflow.result.read`),
`NO_ACCEPTED_REVISION`, `NOT_TEXTUAL`, `DIGEST_MISMATCH`, `BUDGET_EXHAUSTED`, `ITEM_LIMIT`,
`KNOWLEDGE_ACCESS_UNAVAILABLE` (no coordinator KS read origin is admitted; integrator open item).

## Exact output inspection

[`OutputInspectionService`](../../src/mission_control/application/outputs/inspection.py) projects the
immutable WI-01/02 rows: promises, accepted heads, the newest set's decisions, assessments, plans and
receipts, actionable items, revision history and the transition feed behind stable cursors
(`workflow_run.read`).

| Surface | HTTP (`/v1/applications/{app}`) | missionctl | Operator MCP |
| --- | --- | --- | --- |
| outputs | `GET runs/{id}/outputs` | `outputs show RUN` | `mission_run_outputs` |
| history | `GET runs/{id}/outputs/{key}/revisions` | `outputs revisions RUN KEY` | `mission_run_output_revisions` |
| events | `GET runs/{id}/output-events` | `outputs events RUN` | `mission_run_output_events` |
| plans | `GET runs/{id}/transfer-plans`, `GET transfer-plans/{id}` | `outputs plans RUN`, `outputs plan ID` | `mission_transfer_plan` |
| host stage | `POST coordinator-inboxes/{s}/notifications/{n}/observations` | `inbox observe` | `coordinator_inbox_observe` |
| content | `POST .../notifications/{n}/content` | `inbox content` | `coordinator_inbox_content` |
| verdicts | `GET coordinator-inboxes/{s}/attention` | `inbox attention` | `coordinator_inbox_attention` |

## C14 host qualification procedure (selected host: this Claude Code session)

Per OC-D187 the selected host is the implementer harness itself. Needs a real API with 0063, a token
with `workflow_run.read` and `workflow.result.read`, and a real run with a promise `P`. Record every
command output in the ignored evidence log; each step names its evidence row.

1. **Inbox.** `POST .../coordinator-inboxes` with `profile.content.purpose = coordinator_review` and
   `kinds` including `accepted_output` (inbox `S`). Evidence: `inbox list` shows `attention: recorded`.
2. **Idle, then transport.** Start `missionctl wait --inbox S --kinds accepted_output` **as a
   background task**, note `T0`, end the turn (idle). When `P` is fulfilled the store journals
   `output.fulfilled`; the long-poll answers (row `transport`, `http:1`, nonce digest only).
3. **Wake.** The task's exit wakes the session; note `T1`. Read the output: `notification_id` `N`,
   `delivery_nonce` `K`. Attest `missionctl inbox observe S --id N --stage wake --channel
   background_task_exit --idle-since T0 --at T1 --nonce K --evidence task=<task id>` (row `wake`).
4. **Visible.** `missionctl inbox observe S --id N --stage visible --channel task_output --nonce K`.
5. **Ack.** `missionctl inbox ack S --id N` (after visible, or the verdict is out of order).
6. **Retrieve.** `missionctl inbox content S --id N --obligation P` (row `retrieval`: the excerpt
   names the exact accepted revision); then `missionctl outputs show RUN`.
7. **Verdict.** `missionctl inbox attention S` reports `qualified`, no codes.

Negative cases, each recorded: **forgery** (attest visible with any value read from `attention`:
`delivery_nonce_unknown`); **disconnect/replay** (kill the wait before step 3; the next wait carries
the same notice with a new nonce, `http:2`); **duplicate** (repeat step 4: `replay: true`; step 5:
`already`); **dead letter** (webhook inbox to a closed loopback port); **cancel** (`DELETE` the inbox:
waits and reports refuse `closed`). Through the operator MCP the host is in a turn: wake is
`connected_poll`, so the verdict is `IDLE_WAKE_UNAVAILABLE` (polling mode, not idle wake). If the host
cannot be woken while idle, record that limit; an unavailable wake blocks the claim.

**State:** source, unit and local PostgreSQL/Temporal proofs pass; the procedure has **not** been run
with the real selected host (real-unrun). The unit rehearsal attests host stages from a test.

Built / specified / goal: six-stage recording, output/transfer notices and bounded content built and tested (unit, PostgreSQL, Temporal); the host-attested stages have not run with a real host
(C14 real run unrun); a richer dashboard review loop is a goal ([human gates](human-gates.md)).

## Citations

- Records: [PROOFS §5 C14](../specs/provider-consolidation-2026-10/sprint-oc/PROOFS.md); DECISIONS OC-D125/126/176/187; ADRs [0040](../adr/0040-native-frames-normalized-lifecycle-lineage-graph-bounded-coordinator-subscriptions.md), [0049](../adr/0049-deprecate-mission-subscribe-push-in-favour-of-inbox-wait-channels.md) (proposed), [0061](../adr/0061-one-sealed-transfer-plan-and-attempt-receipts.md).
- Code: [rules](../../src/mission_control/domain/coordinator/attention.py), [inbox service](../../src/mission_control/application/subscriptions/coordinator_service.py), [content](../../src/mission_control/application/subscriptions/notice_content.py), [inspection](../../src/mission_control/application/outputs/inspection.py), [HTTP inbox](../../src/mission_control/interfaces/http/coordinator_inbox.py), [HTTP outputs](../../src/mission_control/interfaces/http/output_inspection.py), [missionctl outputs](../../src/mission_control/interfaces/cli/outputs.py), [MCP](../../src/mission_control/interfaces/mcp/subscriptions.py).
- Tests: [unit rules and service](../../tests/unit/subscriptions/test_wi19_attention.py), [surfaces](../../tests/unit/subscriptions/test_wi19_interfaces.py), [PostgreSQL](../../tests/integration/postgres/test_wi19_attention_postgres.py), [webhook transport](../../tests/integration/postgres/test_mp15_webhook_callbacks_postgres.py).
