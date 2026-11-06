---
type: Current Recovery Evidence
title: "Run 2 committed cancellation and residual result delivery"
description: "Actual terminal commit, consumed one-shot intent, read-only replay evidence and narrowly bounded next action."
---

# Committed cancellation; result delivery remains open

The actual coordinated closure committed **run9/terminal/cancelled and family3**.
It did not finish family/root delivery. The original remaining-closure intent is
**consumed** and must never be cleared, rerun or replaced to retry that action.
The [machine evidence](RUN-2-PARTIAL-CLOSURE-EVIDENCE-2026-10-17.json) pins the
actual receipts and the inspected main `bbb70c20` with unchanged application and
frozen original operator source. This record supersedes the earlier run8/family2
hold as the current frontier; the earlier evidence remains historical.

## Observed outcome and limits

The 18:07 UTC owner-approved envelope first refused at the Windows memory gate,
before clients or intent creation. A later coordinated invocation used the same
unused semantic authority with an expiry-only refreshed literal action
`7a5a084df2ed1ba629ede82fee9c053b11d02d818e8843f1b88f8314d45171f4`.
It ended 18:31:31 UTC: 306.546s outer/306.219s guardian under 340s; primary 250.683s
under 260s, then a distinct 55.532s read-only observer under 78s. Owned children were
reaped, pools closed, and no forced kill or provider call occurred. The activity
wrapper reported `bounded_remaining_family_refused_or_uncertain`. The private
stderr digest survives; the inner exception bytes were not retained. Its exact
cause cannot be recovered from that receipt.

Focused read-only normal-repository diagnosis finished 18:37:56 UTC, 24.219s outer:

- Accepted receipt, canonical family head/journal, run projection, budget and
  effects exactly match the saved intended normal terminal commit. Receipt:
  `sha256:4a5d9842f64f96abbe7a8cbcbcf9efa1840449f43265f6f8ee4e85b2da895dfc`.
- Original cancellation `6a5398e3-2a73-4351-a354-a24a9a4ddc4b` is applied;
  budget reservations are empty. Usage/settlement facts and 252 native frames
  are unchanged. Explicit native 926,070 tokens and unknown USD remain unchanged.
- Exactly the intended 15 of 28 protected domains changed, with expected row
  deltas; no provider/native frame, technical attempt or settlement addition.
- Canonical `StageGraphDecisionService.complete(exact_saved_request)` returned
  accepted/cancelled/version9 in1.704s with **all three pools read-only**.
  This verifies the existing canonical replay correction against actual persisted
  PostgreSQL data. It establishes no new application defect requiring a fix.
- Typed Workflow Result remains absent. Family history50 events remains Running,
  existing `stagegraph.complete` activity4/scheduled event50 pending at attempt2;
  root history17 events remains Running, waiting for the original family.
- Both targets retain their v11 overrides. DefaultCurrent remains
  `mission-control.0.1.0-a8d69c5b4850`, revision10, no ramp. The original observer
  preserved the failed operation and foreign maintenance history; diagnosis did
  not claim a new service/ECS inspection. Shared service/task16 was not changed.

A second read-only capture at 18:50 UTC completed 13.328s and pinned the exact full
family50/root17 protobuf histories and activity4 payload. No worker, routing
mutation, SQL write, intent claim or provider call occurred. Original intent bytes
remain SHA `068d1d4057e5a5cfed01f65a820df9db7a98dacf24d607f88d6c1979b85a5e98`.

## Minimal next work package

Prepare and independently qualify one **distinct committed-result delivery**
action under the later task-specific authority. It is not another terminal SQL
operation. Before serving, prove these exact boundaries:

1. Pin actual family50/root17 prefixes, exact activity4 payload/options/headers,
   persisted terminal receipt/journal request digest and consumed original intent.
   No semantic rekey may depend on helper/build/expiry/attempt/event-count changes.
2. Use only canonical read-only completion replay for the existing activity4;
   forbid terminal commit entry, provider calls, children, cancellations and
   defaultCurrent/ramp/ECS changes. Preserve original target identities.
3. Permit at most one normal immutable typed-result INSERT through the canonical
   `TerminalWorkflowCompletionService` and scoped result repository. Bind its
   genuine computed and persisted result before allowing root completion.
4. Seed the guard only after independently verifying actual history prefixes;
   distinguish SDK automatic `TemporalChangeVersion` upserts from application
   visibility upserts. Pin complete payload and command options.
5. Positively verify final existing activity4 result, family completion, original
   child7 linkage, root materializer and durable typed result. Preserve all
   protected domains, failed-operation/foreign histories and routing defaults.
6. Retain sanitized inner error type/stage/timing without secrets. Reuse owned
   process supervision, hard deadlines, pool-close reservation and a distinct
   independent read-only observer after the primary has been reaped. Uncertainty
   consumes the new residual intent; do not automatically retry.

Source inspection confirms that the root awaits typed-result materialization but
returns the original family StageGraphRunResult. Its final workflow result and
the materializer's WorkflowResultRecord are separate contracts. Verify the genuine
computed/persisted typed record against the materializer activity result while
preserving the exact family result in the root final command. An early residual
helper assumption conflated these contracts and was corrected before activation;
this establishes no canonical application defect.

Full source verification costs 6.048/5.895s wall per pass (0.770/0.746 CPU), over
264 product modules and 61 contract files. Repeated verification plus normal SQL
must fit the activity/host budget with margin. This measured overhead is a hazard,
not proof that the earlier inner failure was a timeout. Preserve source checks.

## Resource admission and remaining gates

The new stdlib helper lives only in
`.agents/skills/coding-cli-jobs/scripts/resource_admission.py`, with 15 local tests
in the adjacent tests directory. Native Windows lint, focused mypy and 15 tests
passed. Physical availability and system commit headroom are sampled separately;
the default remains 1.5 GiB for both. An OS file mutex is held through caller-owned
cleanup; bounded admission waiting never starts/retries/kills a job or extends an
action expiry. Existing active 1 GiB floor and outer guardian remain required.
Measured admission requires trusted exact-job whole-job evidence and explicit
reserve. The measured 166 MiB Linux process peak is insufficient to lower policy.
There is no ResourceCare/global OS setting or Mission Control scheduler change.

No new residual action has been activated by this diagnosis. The 110-issue audit
and original S0/LS/R/S1/S2/S3 acceptance remain applicable; this closure does not
qualify provider parity or release. Inclusive category spend remains unresolved;
do not launch paid repeats. Knowledge Services and broader manual skill/CLI/MCP
work remain the separate later follow-on.
