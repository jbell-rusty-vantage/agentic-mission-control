---
type: Recovery Execution Evidence
title: "R2B phase one delivered once; next family workflow task held"
description: "Exact renewed action, normal SQL acceptance, server completion, confinement readback and remaining recovery boundaries."
---

# Phase-one delivery verified

The specifically approved R2B phase-one action completed once at **October17
11:12:07 UTC**. Normal SQL accepted **run7->8, family1->2**; the server completed
the original waiting activity. The run remains **cancelling**. The next family
workflow task is **pending and unstarted**. This is not full cancellation or
permission to serve that next task.

Current/default routing stayed on `mission-control/0.1.0-a8d69c5b4850`, revision10,
with no ramp. Root, unrelated workflow and failed-operation histories were
unchanged. No provider/native request, R2A action, direct SQL repair, object write,
grant, credential change or unrelated service deployment was performed.

Read the [current integration](RUN-2-CURRENT-INTEGRATION-2026-10-17.md),
[original phase-one plan](RUN-2-R2B-PHASE-ONE-PLAN-2026-10-17.md),
[permissions/action record](RUN-2-PERMISSIONS-AND-ACTIONS-2026-10-17.md) and
[companion evidence](RUN-2-R2B-PHASE-ONE-EVIDENCE-2026-10-17.json).
The earlier automatic-review denial remains historical evidence. Specific
bounded authority was subsequently received at11:04 UTC; the renewed reviewed
action executed without a second denial or an alternate-route workaround.

## Source, renewal and fresh gates

Execution bound clean local main
`9c8bea3f43e7460b7eb21d8350f86b075b8365c5`. Relevant product, AI Engineer1.4.2
contract/target and operator pins still matched the original reviewed closure.
The new immutable private sibling `continuation-v8/recovery/r2-host-r4/`
changed only `run_host.py`'s expected-main binding from `a9012e69` to `9c8bea3f`;
the other six host components and shared `r3/` serving/intent sources remained
byte-identical. Frozen earlier actions and sources were preserved.

Renewed action SHA256:
`78c4512036514bb944214cd92c450e619d8ed20ad29a02cfa810edf6f34c24b7`.
The321-member source manifest stayed
`d17d608fd916f70a14ef3b7533c8a58c980beba9219df966d3aef47a45c56e9d`.
Expiry was11:19:38.575 UTC. Request, computed commit, effect scope, limits,
interpreters, original recovery build, registry root/pin and one-shot phase key
were unchanged. No new identity was minted to evade the once-only gate.

Fresh preparation passed in68.563s outer: genuine original request/attempt27,
family/root/failed-operation histories, three-running-workflow inventory,
Current-old/revision10/no ramp, zero checked family/root pollers, recovery-version
NOT_FOUND, existing separate restricted roles/effective grants, installed1.4.2
contract/attestation, exact replay and genuine memory-only normal commit. All28
database domains retained the R2A afterimage. No worker, intent, mutation or SQL
commit occurred during preparation. A separate existing-route STS read matched
the expected AWS account and `overtonadmin` principal. The private registry read
at11:08:19 verified0700/0600 root/header custody and intent absence.

Independent GPT-6.1 Sol review cleared the exact renewed action, all nine
host/serving pins and fresh evidence hashes with no P1/P2. No unchanged broad
suite or full-duration stress test was repeated. Immediate freshness/source/
history/authority checks still ran four times in the executing host.

## Actual effects and mandatory readback

The original build `run2-r2b-recovery-a9012e69-p1-20261017a` was registered
honestly without promotion. Its workflow registration poller shut down and
joined before the family-only override. Only its guarded activity worker then
served the exact original activity3, scheduled event33, attempt27 through normal
StageGraphActivities -> StageGraphDecisionService -> RunControl -> repository SQL.

| Evidence | Actual result |
| --- | --- |
| Genuine request | `sha256:05894ea94bf49ae533d292e41d05fa59655b5e0ccb404455b9d2f53e67c0c720` |
| Normal SQL | Exactly1 call, returned successfully; run8/cancelling and family2 |
| Persisted receipt | `sha256:306bbe3df32b4481de4995a661641a92698a9a879b0157f5649e4892a228a3b7`, equal to the computed accepted receipt |
| Before28-domain digest | `sha256:bfe708e20d3d03f172adff1a42ba9a28276458a32c6f2c80e1ccf590eb7dd775` |
| After28-domain digest | `sha256:e4cbbcc91db9dabeb976b40233bb519ee8f6e41a185606adf8bc30a44e4024d1` |
| Server result | `sha256:75972458109de3e8ad25ae71e913a073619743072c91c146dbe3f200566816cc`, equal to handler result |
| Family history |38->42; only options update39, activity start40, activity completion41, workflow-task schedule42 |
| Held boundary | No pending activity; next workflow task pending/state1 and unstarted; exact target-only recovery override |
| Other histories | Root16, unrelated2, failed operation22 events; original digests unchanged |
| Routing | Current-old/revision10/no ramp unchanged |
| Process/pools | Exact child reaped, no forced kill, private sender joined, both pools closed |

Exactly these12 snapshot domains changed as expected: run, family_head,
family_journal, family_results, request_receipts, transitions, outbox, budgets,
effects, mission, mission_events and ledger_commits. There was one added family
journal/result/command receipt/transition/ledger commit and two added outbox/
mission-event rows. Budget/effect row versions changed through normal SQL,
while semantic authority and entry counts stayed equal. All other snapshot
domains and protected facts matched their beforeimages: native identity,
binding/claim/settlement,252 frames, existing technical attempt, budget/effect
entries and cancellation command/delivery were preserved. No manual usage was
inserted; reported926070 explicit tokens and unknown dollars remain unchanged.

The host attempted database and Temporal readback separately and verified both;
local handler completion alone was not accepted. The126.797s outer run comprised
126.364s guardian and110.255s worker, with106.275s active work, within the reviewed
135s active/50s readback/5s pool-close reservations and210s guardian ceiling.
Both preparation and execution retained a617-byte stderr digest; this is not an
error-free-log claim. There was no reported refusal, partial effect, timeout,
forced kill, automatic retry or missing readback. Independent Sol inspection of
the completed receipt found no P1/P2 and confirmed the confinement/count checks.

At11:13:02 UTC, a separate read-only registry inspection verified the same private
header/root and **phase intent present**. The action is consumed. Do not rerun
either this action or R2A, renew it as a retry, initialize/reclaim the registry,
or choose a new build/key to evade the permanent phase fence. Registered recovery
metadata and the target override remain intentionally; no worker remains to serve
the held workflow task. Do not delete or repoint them as casual cleanup.

## Remaining work and independent continuation

The next recovery boundary is separate: inspect/replay and constrain the actual
family/root workflow commands before any later serving action. Keep the next
task held until its concrete envelope has applicable authority. The current
phase-one approval does not authorize family/root terminalization, broad queue
polling, default promotion or an unbounded worker. Existing run8/family2 and the
new afterimage are the starting frontier for any future read-only preparation;
old run7/family1 prepare/execute scripts must now refuse.

Independent W10 evidence/documentation/index/link/source-preservation gates
continue after this action. Product code is unchanged, so previously passing
source suites are not repeated without a changed source or material concern.
The original G1/LS/S0/R/S1/S2/S3 and data/release criteria remain. Cursor
interactive login and unverified inclusive billing headroom were not resolved
by this approval; no new paid/provider qualification was attempted. Use the
[prerequisite ledger](RUN-2-PREREQUISITE-CLOSURE-2026-10-17.md) for category
allocation, selective seed effects and remaining native limits. Preserve
original worktrees and receipts; no push or unrelated deployment follows.
