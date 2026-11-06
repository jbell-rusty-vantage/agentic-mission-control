---
type: Recovery Qualification Plan
title: "Run 2 remaining family/root closure: reviewed bounded proposal"
description: "Canonical completion retry repair, joined qualification evidence and the separately held one-shot cancellation closure."
---

# Remaining family/root closure

**Historical proposal; current frontier superseded.** The later coordinated
invocation committed run9/cancelled/family3 but left family/root delivery open.
The original intent is now consumed. Read the
[actual partial-closure diagnosis](RUN-2-PARTIAL-CLOSURE-DIAGNOSIS-2026-10-17.md)
before any action; do not execute this original proposal or replace its intent.
The held-state descriptions below are dated preparation evidence.

The canonical retry repair is merged locally through **d106d0c7**. The remaining
operation is one normal cancellation completion of the existing run, followed by
the existing root's typed-result materializer. **Owner approval was received at
18:07 UTC; the single launch refused before live clients at the memory gate.**
The [18:14 UTC observation](RUN-2-APPROVED-CLOSURE-REFUSAL-2026-10-17.md)
verified unchanged run8/family2. No automatic retry occurred.

Read the [current integration](RUN-2-CURRENT-INTEGRATION-2026-10-17.md),
[phase-one result](RUN-2-R2B-PHASE-ONE-RESULT-2026-10-17.md) and
[exact evidence](RUN-2-REMAINING-CLOSURE-EVIDENCE-2026-10-17.json).
Earlier assessment and phase-one records retain their original provenance.

## Canonical correction and its limits

`StageGraphDecisionService.complete` now resolves the bounded completion command
identity and verifies an exact committed request before checking the current
family head. New mutations include a canonical digest of the whole request.
Receipt/journal identity, fingerprint, projection and versions must agree;
changed requests and stale uncommitted requests still refuse. A PostgreSQL-shaped
JSON regression protects tuple/list equivalence without changing ordered values.

Accepted historical mutations without full request evidence fail closed; no
receipt is rewritten or backfilled. Historical rejected proposals preserve their
original representation only after both normal command and family fingerprints
match. Later proposals retain bounded retry suffixes. The private recovery cache
is an additional fence; application retry correctness no longer depends on it.

Source commits: `b505f277` and `d106d0c7`. Validation: **65 focused in-memory
tests**, Ruff, focused mypy on the first repair, normal ty/dependency/security/
format hooks on both commits, and independent GPT-6.1 Sol static review. The final
one-line canonical comparison passed the new JSON regression and normal hooks.
No workflow request schema, deterministic workflow code, SQL release or applied
migration changed. JSON fixtures prove representation behavior, not SQL acceptance.

## Inspected current state

Public run `60f44a50-c0e4-5edb-ac13-0fb0436aaedb` remains **run8/cancelling,
family2**. Protected28-domain digest:
`sha256:e4cbbcc91db9dabeb976b40233bb519ee8f6e41a185606adf8bc30a44e4024d1`.
Original claim is settled; generation1/owner_epoch2,252 frames and explicit native
926,070 tokens remain. Dollar cost remains unknown. Typed result is absent in
the read-only capture. Exact observation times and newer receipts are in the
evidence manifest; saved receipts are not perpetual freshness guarantees.

The family has42 events and a pending unstarted workflow task; root has16 events
and waits for that original family. The failed operation has22 events. Retained
foreign maintenance workflow has2 events and must remain unchanged.
Current/default remains `mission-control/0.1.0-a8d69c5b4850`, revision10, no ramp;
the shared task16 service remains stopped. R2A and R2B phase one are consumed.

## Qualification result

The frozen candidate passed **57 joined checks** at 2026-10-17T12:46:36 UTC;
guardian88.378s, memory-only/read-only, all three pools closed and child reaped.
The distinct actual observer passed in **35.523s under78s**, including deliberately
expired execution authority. It verified the unchanged held state and typed-result
absence. Final envelope qualification passed six activation/intent cases plus two
guardian sequencing/interruption cases in16.629s. These selections overlap; do not
sum them into a broad-suite claim. Actual installed Temporalio is1.34.0.

Independent GPT-6.1 Sol review found no remaining P1/P2 and judged the exact
bundle **preparation-ready for specific owner approval**. Proposed bytes SHA256:
`ded2af8090e729139128390f0bfe40a0ea8dae3ee512437ff55f78010f1732a8`. The stable envelope digest after omitting only
the refreshable expiry is `sha256:f82bf605e66a7d03bb0e3fa3b85d14365a7f0f7ae165fce216b8136bade5561a`.
At proposal publication no approved-action file existed. The later owner-approved
file and prelaunch refusal are retained in the linked execution record; no live
closure ran.

Retained refused candidates remain evidence. They exposed audit JSON type drift,
missing operator imports and an incorrect protobuf map access; all stopped with
zero shared writes and owned cleanup. The actual descriptor and ten focused
positive/negative history cases verified the final correction before the joined
proof. Source/service JSON persistence handling received its own application
regression and independent review.

All ten original checkout HEADs, statuses and known dirty-file hashes were
verified unchanged. Owned main changed only the two reviewed application/test
paths before this documentation publication. Nothing was pushed. Runtime package
versions/source hashes and the read-only unused-remaining-intent check are in the
evidence manifest. Legacy phase-one *transport schema naming* persists in the
envelope; enforced Action, entrypoint and permanent intent are the remaining
closure. That name supplies no permission to repeat phase one.

## Qualified host and one proposed work package

Private candidate: `.scratch/run2-completion-20261017/continuation-v8/recovery/closure-host-r11/`
in the retained `run2-completion-offline` checkout. The evidence manifest contains
all component, application, interpreter, release/target and proof pins.

1. Recheck exact source/installed1.4.2/37 receipts, roles, E4 beforeimage, running
   inventory, target histories/options, original failed operation, foreign
   history, Current/ramp and stopped shared service. Drift refuses before intent.
2. Claim the permanent **remaining-family-root-closure** key in the existing
   private registry. It is independent of build/helper/expiry. Existing consumed
   keys are read and preserved; no initialization, reclaim or alternate key.
3. Register one truthful nondefault `run2-remaining-closure-d106d0c7-v11` build
   for only root/family workflow queues and family activities. Registration
   workflow pollers stop before overriding **root first, then family**. Global
   Current/ramp does not change. Refresh each boundary before serving.
4. Exact command guards permit only the captured completion chain: family
   `stagegraph.complete`, activity4; root's original child return, then
   `coordinator.materialize_workflow_result`, activity1 on the family queue.
   Validate the complete new command batch before forwarding it. Only the exact
   SDK activation-clock field may differ from the template; all other payload,
   identity, options, queue and patch/search-attribute content remain sealed.
5. Use normal application/reducer/repository paths for **run8->9, family2->3,
   terminal/cancelled**, apply the original cancel receipt, and save one immutable
   typed result. Permit at most one terminal SQL entry and one result-insert
   entry. Persist private expected commit/seals before SQL. Lost replies require
   exact receipt/afterimage readback; uncertainty cannot mint another entry.
6. Stop/reap the serving process, then always attempt a **distinct read-only
   observer process**, including interruption and expired execution authority.
   Verify DB and Temporal independently, retaining partial observations on any
   failure. Verify exact genuine activity/final/child results and a positive
   history allowlist; preserve foreign and failed-operation histories.

Three owned one-connection pools separate runtime reads, family writes and typed
result writes. All are read-only during preparation/observation. Existing roles
already have the required privileges; no grant change is proposed. Serving uses
one workflow executor thread and one concurrent activity. Start requires1.5GiB
free; stop only owned work below1GiB. Never signal other sessions/services.

Active budget240s; primary process hard260s including startup; separate observer
hard78s; combined guardian ceiling340s. Observer's70s reservation includes bounded
DB/Temporal work and8s pool-close reservation. A hard ceiling is not a guarantee
all reads complete: forced containment or incomplete readback is explicit
uncertainty, consumes the intent, and forbids automatic retry.

The normal commit predicts15 changed domains with exact row deltas inside the28
protected domains; the typed-result table is verified separately. This is a
qualified expected scope. Actual SQL/CAS acceptance and server closure remain
unproved until the specifically approved operation runs. No rollback is claimed.

Use one GPT-6.1 Sol operator and one read-only GPT-6.1 Sol reviewer; no nested
delegation. Keep one heavy/native process active at a time. The operator owns
the exact action and evidence; the reviewer verifies pins/results without
editing or activating. Preserve the existing [Sol instructions](RUN-2-SOL-EXECUTION-2026-10-16.md).

## Approval and stop/go gates

The frozen proposed envelope remains default-off. Specific owner approval was
received at18:07 UTC and the exact approved-action file is retained, with only
expiry changed. The memory refusal and actual held-state readback are linked
above. The approved scope covers this one existing family/root closure, source/pins,
exact build, role use, two target overrides, normal terminal commit/result insert,
private permanent intent and bounded independent readback/cleanup. Approval may
refresh only the650-second expiry on the same reviewed envelope; no identity,
scope, source, budget, build or effect widening follows. The resulting literal
action hash is recorded before execution.

Go requires passing fresh gates and the unused remaining intent. Missing roles,
new obligations, drift, unexpected signal/update/command, ambiguous result, lost
identity or cleanup failure stops progression. Retain evidence and inspect
forward; do not repair SQL, retry consumed work, promote, restart services or
admit providers. Publish the actual result and fresh integration state afterward.

## Do not redo or expand scope

Do not rerun R2A/R2B phase one, resubmit the existing Cursor start, repeat Full3's
settled human approval, rewrite historical receipts or fabricate native cost.
Do not add migrations/backfills, new provider/model/account routes, S4 funding,
next-stage capabilities or the separate agent-facing follow-on. Remaining S0,
CLI, ingress and remote acceptance keeps its existing gates; this closure does
not qualify those slices or authorize paid experiments.

Possible later native-quota check: the parent supplied the official
[Claude limit-reset help](https://support.claude.com/en/articles/17007452-what-is-a-limit-reset).
An unused one-time weekly reset may be available in the existing account's
Settings/Usage. Eligibility, expiry and account applicability are **unverified**;
the page/account was not checked during closure work. Keep it distinct from
cloud credits/API grants. Check read-only only through normal existing access;
consuming a reset requires specific user approval. No reset or credit was used.
