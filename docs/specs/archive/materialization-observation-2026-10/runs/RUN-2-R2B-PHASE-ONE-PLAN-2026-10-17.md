---
type: Implementation Plan
title: "Initial R2B result activity: exact bounded action and remaining host gates"
description: "Target-only recovery version, normal command/effect pins, ownership boundaries, proofs and stop/readback criteria."
---

# Proposed initial R2B phase: one normal family result activity

**Historical plan; phase one is now consumed.** Specific bounded authority was
received at11:04 UTC, followed by fresh state/source/principal/routing gates and
independent Sol review of renewed action78c45120. The
[actual result](RUN-2-R2B-PHASE-ONE-RESULT-2026-10-17.md) verifies one normal
run7->8/family1->2 commit and server completion, with next family WFT held.
Do not run the original or renewed action again. Preexecution statements below
retain their dated evidence and do not describe the current frontier.

Preparation only. No shared override, new Cloud worker, SQL commit or provider
request has been executed by v8. This does not reopen the consumed R2A actions.
Use GPT-6.1 Sol only; lead plus one worker and one runtime lease.

The executable host is now assembled and qualified. Automatic approval review
rejected the exact live delivery command before process creation because broad
sprint permission was judged insufficient for its specific durable mutations.
Specific bounded approval was requested and remains unresolved. The reviewed
action is `3565f88628e5cbaeebb2b2b1aaeb889f163d723f40c2fbce17257aa927f49f57`;
its expiry03:47:45 UTC and main-head/source bindings require renewal before any
later execution. Do not retry it indirectly. See the [current evidence and
blocker](RUN-2-CURRENT-INTEGRATION-2026-10-17.md#executable-host-qualification-and-exact-approval-blocker).

## Exact intended effects

Temporal namespace `mission-control-dev.ih0e7` at TLS
`us-east-1.aws.api.temporal.io:7233`; deployment `mission-control`.
Target only family execution
`mc/01a103c0-9a9e-70f3-9398-eb1573a98324/ai-engineer/run/60f44a50-c0e4-5edb-ac13-0fb0436aaedb/family/1`,
run `01a143c9-1e58-7e14-9d5d-8da6ec22a0ee`, queue
`mc-ai-engineer-coordinator-family-stagegraph`, activity3/scheduled event33.
Fresh attempt must be observed; the last read was27. Keep genuine request digest
`sha256:05894ea94bf49ae533d292e41d05fa59655b5e0ccb404455b9d2f53e67c0c720`.

Register a unique truthful recovery version, with no Current or ramp change.
Register its real StageGraph workflow poller, await its registration, then join
its shutdown **before** setting any target override. Start only the one guarded
activity worker, concurrency1. Use exact workflow ID/run and mask
`versioning_override` to pin the family to that version, retry=False.
Cloud update permission remains unproved: refusal stops without access changes.

Only the actual StageGraphActivities -> StageGraphDecisionService -> normal
RunControl -> PostgresRunControlRepository path may deliver the request. The
read-only genuine pre-SQL proof computed accepted run7->8, family1->2,
quarantine/run_cancelling, one operation-settlement evidence action, two domain
events and zero budget/effect ledger entries or boundary commands/receipts.
Guard the original SQL implementation immediately before its one permitted call:

| Binding | Exact expected value |
| --- | --- |
| Before28-domain digest |`sha256:bfe708e20d3d03f172adff1a42ba9a28276458a32c6f2c80e1ccf590eb7dd775`|
| Command fingerprint (exclude occurred_at) |`sha256:198ab6c07a391df29b80fb78ad3c1b374a13d8fe8237b29d8e3f19aca96277f0`|
| Family fingerprint (exclude decided_at) |`sha256:75d70bf60ad40d16009de5a9af7155d53ef345810d91a8edfe66a8bcefdea60d`|
| Whole computed commit digest |`sha256:85036220557af6e9c76a4aa9fcfb5f9f86a2f2da4d9899d9e1bc99797aab9610`|
| Expected budget authority |`sha256:5865275458cf94f6373b7ff50f2bd3669944d12a5219c46837ba8f57b6b1ebae`|
| Expected effects authority |`sha256:ee9a811087e6e2c60765df6d19b087de1aa5699403bc0a70301d42144d0cfd34`|

Use separate existing runtime/family logins on the same pinned Supabase
project/TLS route as R2A. No new role, grant, credential, ALTER, migration, SQL
repair, seed/backfill, provider invocation or object write is part of phase1.
Actual SQL CAS acceptance and the returned persisted receipt remain unproved.
The original native FINISHED evidence never replaces the genuine failed request.

## Work ownership and dependency order

Keep GPT-6.1 Sol for every worker. Use a lead plus one worker and only one runtime
check at a time. A worker must return exact source and receipt pins, observed
effects and remaining limits. An ambiguous response never enables another call.

| Owner / package | File boundary and dependency | Completion evidence |
| --- | --- | --- |
| Serving owner | Frozen ignored `continuation-v8/recovery/r3/{phase_one,private_once}.py`; preserve all earlier versions | Actual genuine assembled memory gate passed; workflow registration uses two task slots, activity concurrency1 |
| Host integrator | Frozen `r2-host-r3/{pools,readiness,readback,database_readiness,owned_host,host_guard,run_host}.py`, action and manifest | Real role/grant/contract readiness and exact replay passed; full timeout and five failure cases passed; specific live-action authority still blocked |
| Independent critical reviewer | `r2-host-r3/independent-review.md`; complete action and all nine host/serving source pins | No remaining P1/P2 in executable envelope; all321 manifest members match; no live CAS or mutation-permission claim |
| Lead integrator | This plan, current integration/evidence and permissions records, generated documentation index | Fresh document gates and original-worktree/source preservation evidence |

The `continuation-v8/` paths are relative to the retained private
`.scratch/run2-completion-20261017/` evidence root. Do not edit v4-v7, the initial
v8 candidate, consumed actions or original concurrent worktrees. Later family
and root serving depends on the successful phase-one readback below.

## Qualified prerequisites and remaining activation gates

1. Exact source/manifest and executable critical review passed. Preserve the
   frozen nine sources and321 manifest members. Renew only a concrete expiry/
   current documentation-head binding after reviewing its delta; do not broaden
   effects, substitute source or silently recompute an unapproved manifest.
2. Actual read-only prepare passed73.891s outer: genuine typed normal commit,
   memory-only SQL gate, exact past-history replay, separate existing restricted
   roles/effective grants and installed1.4.2 migrations/attestation/fingerprint.
   Five final explicit failure cases passed10.640s. No real SQL CAS is proved.
3. Full145s active/50s readback/5s close stress passed207.250s outer with two
   owned interruptions. Live active work is135s, readback50s, close5s; reserve20s
   source/import/supervision overhead within the guardian210s deadline. Windows
   monitors at 215s, then allows up to 60s guardian-exit fallback and bounded
   exact-client kill/wait/sender cleanup; 215s is not a total outer wall ceiling.
   Catching a reader's ordinary failure must not suppress the other observation;
   the outer readback cancellation propagates and preserves the close reservation.
4. The exact private registry was initialized at
   `/home/overton/.local/state/mission-control/qualification/run2/recovery/registry`,
   header pin `0387e921e61b2f54e68107784f0df87016285396883649205d81e8feee4798a6`.
   Root/header modes are0700/0600; read-only inspection proved the phase-one
   intent absent. Do not initialize, replace or reclaim it again.
5. Specific human approval for this live Temporal mutation plus normal family
   SQL commit is unresolved after automatic review rejection. No command process
   was created; recovery version is absent, Current remains old/revision10 and
   all28 domains remain unchanged. Do not route around the rejection.
6. After specific authority and a renewed reviewed envelope, refresh every exact
   family/root/failed-operation history, original request/attempt, private root,
   role/grant/contract,28-domain digest, namespace inventory/pollers, Current and
   unused recovery version. Visibility is bounded observation, not an atomic
   barrier. Consume one global durable phase intent before registration/override;
   no new build/request/reset after uncertainty. No new credentials, grants,
   migration, privileged fallback, direct SQL repair or provider request.

## Required result / failure readback

Stop the activity worker and prove server activity3 completed, returned expected
normal decision, exact DB command/family receipts and bounded domain changes.
The next family workflow task must be pending and **unstarted**. Root and failed
operation histories and the third workflow remain unchanged. Deployment Current
and ramp remain unchanged. Prove both pool closure and exact owned process exit.
Local handler finished is insufficient server evidence.

Normal SQL increments budget/effect row versions even with zero ledger entries.
Expected changed snapshot domains are run, family_head/journal/results,
request_receipts, transitions, outbox, budgets, effects, mission, mission_events
and ledger_commits. Verify one exact command/family receipt and transition,
one family journal/result/ledger commit, two joined events/outbox entries,
unchanged semantic budget/effect authority and all other domains/facts unchanged.
DB and Temporal readbacks are independently attempted within their shared bound.

On refusal, timeout, lost reply, source/principal/history/authority mismatch or
unknown effect, stop and inspect forward using the same IDs. Do not convert all
refusals to a non-retryable activity failure: it would terminalize the original
pending task and damage recoverability. Preserve retryable server disposition
without authorizing another SQL/provider call. The durable/SQL one-shot gates
remain consumed; no new build/request is a recovery shortcut.

Later family workflow commands, family terminalization and exact root serving
have separate action boundaries after phase1 readback. Full G1 and original
native/remote/data/release acceptance retain their criteria. No next-stage
capability evolution or manual CLI/MCP/skill follow-on is added.

## Do not redo completed component checks

These selectors identify consumed evidence, not instructions to rerun unchanged
passing checks. New host/source changes require a newly reviewed bounded guard
and fresh receipt paths. Keep failed and interrupted attempts beside the passes.

| Existing guard / selector | Evidence boundary already checked |
| --- | --- |
| `check_final_main_v21.py local-r2b-contract activityonly` | Supported local server: register, stop workflow poller, activity-only delivery, next workflow task held |
| `read_modern_temporal_routing.py --guarded-read-only` | Current Cloud deployment/version metadata; no write permission claim |
| `check_proposed_effects_v5.py --guarded-read-only` | Genuine normal reduction and memory-only once gate; no SQL CAS |
| `check_phase_one_r2.py phase-one r2guards` | Seven provider-free guard/order cases with explicit worker doubles |
| `continuation-v8/recovery/r2/check_posix_r2_fast.py --owned-posix-tests` | Seven actual POSIX custody/intent cases via explicit async driver; no pytest collection claim |
| `continuation-v8/recovery/r2-host/run_host.py --prepare prepare1` | Real existing roles/grants/contract/replay and genuine normal memory gate; no SQL write |
| `continuation-v8/recovery/r2-host-r2/run_host.py --qualify envelope1` | Full200.158s worker reservation/207.250s outer under repeated owned interruption; no network or registry |
| `continuation-v8/recovery/host-tests/check_cases.py --owned-posix-tests` | Five final explicit host failure cases; no pytest collection claim |
| `post_rejection_read.py --guarded-read-only` | Actual post-rejection Current/version/28-domain unchanged-state evidence; no mutation attempt |

See the [current integration record](RUN-2-CURRENT-INTEGRATION-2026-10-17.md)
and its [evidence manifest](RUN-2-CURRENT-INTEGRATION-EVIDENCE-2026-10-17.json)
for exact source and receipt hashes, durations and retained nonpasses.
