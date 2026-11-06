---
type: Implementation Evidence
title: "Sprint OC W1 evidence: first ordinary GoalDirected report (OVE-169), runner sessions 1-12"
description: "Per-criterion, per-application status of W1 across runner sessions 1-12 (newest first): session 12 reached the first live verifier and stopped on D39-D41; session 11 promoted a report live and failed on D35/D36 (fixed); session 9 reached seal, decide, held review, separate-reviewer approval and promotion and failed fulfillment (D27-D30, since fixed and unit-tested); session 10 found the remote schema behind the code (D31-D33) and stopped before any paid call. Cumulative W1 at most USD 1.407 of 6.00. Locators and digests only."
tags: [mission-control, sprint-oc, w1, wi-06, evidence]
status: active
date: 2026-10-28
---

# Sprint OC W1 evidence (OVE-169 / WI-06)

## Source recovery and qualification (2026-10-29)

The nine W1 harness, fixture and evidence source files were selectively recovered from
`sprint-oc-w1` at `a5fd52868d24d7449ed71799d8df9b84a3b8a468` into the canonical
Mission Control checkout. The historical sessions below remain their original evidence.
The pack builder's default Knowledge Services path now resolves the canonical sibling checkout;
`--ks-root` remains available as an explicit override.

**W1 remains unreleased.** This source recovery does not qualify the current runtime. Native-write
repairs and independent W1 qualification are still required before release. Recovery validation is
limited to offline Python syntax/lint, JavaScript syntax and YAML parsing; no provider cognition,
runner execution, database operation or W1 release gate was performed.

## Session 12 (2026-11-02, MC `76725ee9`, KS `77c6f35`, aieng-db 1.13.0)

**Status: the executor result parses live (D35 fixed) and the Goal Loop verifier ran for the first time; no run
accepted.** Three Sonnet report runs, each stopped by a different new defect: `eb311192` (failed: worker killed
mid-verifier, D39), `e947fa8e` (failed: transient connection error, D40; no report), `f243e3d8` (cancelled by the runner:
the Haiku verifier made 69 model and 71 tool calls without a verdict, D41). Spend at most USD 0.646 (about 0.29 with cache
pricing); cumulative W1 at most **USD 1.407 of 6.00**.

| Criterion | AI Engineer |
| --- | --- |
| Online compile 0 blockers; stack at HEAD | pass |
| Executor observation parses as `output:report` (D35) | **pass, live** (x2) |
| Register, judge+auditor, seal, decide, held review, launcher 403, separate reviewer approve, promote | **pass, live** (x2) |
| Verifier runs | partial: started, no verdict (D41) |
| Fulfillment@1 (D28/D29), D27 live, run accepted | blocked / partial (counts hold) / fail |
| Kill during an activity | fail (D39); no duplicate producer cognition or revision |
| Missing-key probe (D30), native write | unrun (memory below floor; paid work stopped at D41) |

- **D39.** A worker lost mid-activity is unrecoverable: `operation.execute` retries (3 attempts, about 3 s,
  `adapters/temporal/workflows/operation.py:1181`, `:1262`) end long before the 5-minute claim lease
  (`checkpoint_lineage.py:78`); every retry is refused "in progress" (`operation_execution.py:1568`).
- **D40.** A connection failure before the request reached the provider ends the run: the lane builds models with no
  retries (`adapters/deep_agents/materializer.py:341`, `:406`) and GoalDirected raises non-retryable
  (`goal_directed.py:562-569`); evaluators already separate unsent from billed failures (`evaluators.py:266-270`).
- **D41 (needs a design decision).** Nothing bounds a verifier turn: the run budget (`tool_calls 20`, `tokens 300000`,
  lowered at `manifest_lowering.py:172`) is not an in-turn limit; call limits exist only when the `call_limits` lane feature
  is selected (`features/builders.py:230-249`), and D38 (the ledger records 0 consumed) means no later check trips.
- Observations: the cancel POST blocks while no worker polls (the cancel and Stop Fence persist; `missionctl` reports
  `service_unavailable`); `/inspection` shows `unit_failures: []` on failed runs; the cause is only in Temporal history.
  Proposed (untested) patches: private `.scratch/sprint-oc/evidence/w1/s12/D39..D41-*.diff`.

## Session 11 (2026-11-02, MC `e3f39bdb`, aieng-db upgraded to 1.13.0)

Run `af51473c`: online compile 0 blockers; the worker passed the D33 startup guard; report register, judge (full support)
and auditor, seal, decide, held review, launcher 403, separate reviewer approve and promotion **pass live**; a kill during
the settlement timer caused no repeated cognition or revision. The run failed at verifier preparation: **D35** (the prompt
named only the objective contract, so the executor's valid result was `output_unparseable`; fixed `ba38fe8b`) and **D36**
(`goal_context.py` refused a failed executor subject for the verifier; fixed `32c14d6d`). **D34**: the W1 bindings
generator read knowledge-tools 1.1.0 (fixed `76725ee9`). **D37**: no route returns the held decision ref and bound-effect
digest a review must name (read from the database). **D38**: the run budget ledger shows 0 consumed after a Sonnet turn.
The approve does not wake the run (it resumes on the doubling retry timer). Spend at most USD 0.134.

## Session 10 (2026-11-02, blocked before any paid call)

**Status: no W1 proof ran; USD 0.00 (cumulative W1 USD 0.627 of 6.00).** Stack at MC `4551e533`: Temporal, KS ai-engineer
(4310), API (8010), worker came up; the D27-D30 fixes (merges `f292ee31`, `00c0d0cd`, `f9168027`; tests
`tests/unit/knowledge/test_verifier_role_separation.py`, `tests/unit/outputs/test_w1_d28_d29.py`,
`tests/unit/knowledge/test_w1_d30_uncomposed_evaluators.py`) are implemented and unit-tested, **not integrated**. Fresh pack
`pack-s11` (official/high) built and compiled online, no model call; operator and reviewer bearers re-minted (expired
2026-10-29). No run was submitted.

| Criterion | AI Engineer |
| --- | --- |
| Stack up | pass, but the worker fails against schema 1.9.0 (D31, D33) |
| Sonnet official/high report (D27-D29 live) | blocked (D32 online compile 422; D31 every keyed settlement fails) |
| Missing-key probe (D30 live) | blocked (D32: fixtures fail compile first) |
| Restart/kill, native write with readback | blocked (D31, D32) |

**D31 (hard blocker, environment).** Code reads schema the remote lacks: `adapters/postgres/frames/retention.py:378` calls
`expire_workspace_closures` (0070, release 1.12.0); `adapters/postgres/knowledge/use_decisions.py:128` reads
`invocation_ref` (only `scripts/release_200/0072_native_plan_decisions.sql`, unbuilt). The native-write settle step runs on
every keyed settlement pass (`toolset.py:1159-1162`, `trusted_judgment.py:233-265`), so every keyed report settlement fails.
**D32 (hard blocker, environment).** The aieng-db catalog has `tool.knowledge-submit-output@1` only (the fixture pins `@2`,
`ai-engineer.report.mission.yml:73`) and no `skill.ai-engineer-knowledge-charter`, which `deployments/ai-engineer/application.toml:41`
mounts on every knowledge mission. **D33 (code).** Startup checks only that the pinned version equals the installed one
(`bootstrap/common_installation.py:180-193`, `bootstrap/composition.py:471`); schema-dependent code landed without a version
bump, so the worker starts and fails inside activities. Proposed (not applied) patch: a `REQUIRED_MIGRATIONS` check, private
`.scratch/sprint-oc/evidence/w1/s10/D33-required-migrations.diff`; it must ship with release 2.0.0 or it refuses every local 1.12.0 stack.

Remaining: the remote rollout in [NEXT-SESSION](../NEXT-SESSION.md#next-action), then this sequence unchanged. Private detail:
`.scratch/sprint-oc/evidence/w1/SESSION-10-REPORT.md`.

## Session 9 (MC 2c0738dc merged as 45b86807; seal keys registered)

**Status: the first full trusted path ran, through review and promotion. W1 is still not releasable.**

### Run `9cc17684` (Sonnet, official/high)

It resumed from its recorded observations with no new producer or evaluator call. The sequence:
1. Seal and decide.
2. The decision is held for review: `output.assessment_held`, then a `review_pending` wait.
3. The launcher's review is refused: 403 `unauthorized_review` on the real decision.
4. The reviewer approves: 200, an adjudication is recorded.
5. Assessment `pass`.
6. The report head is promoted (`promoted_by mission-control:trusted-judgment`).

Fulfillment@1 rows were written for all four promises:
- **Progress note:** required, **fulfilled** (`scope: iteration`).
- **Report:** required, **unfulfilled** `REFERENCE_USE_UNPROVEN` despite the approved review (**D28**).
- **Summary:** expected, unfulfilled `MISSING`, though it was submitted (**D29**).
- **Caveats:** optional, silent.

The run terminalized as failed.

The verifier re-submitted the report as revision 2 (**D27**), which produced a second held decision
and a second review.

### Missing-key probe `76ddfa88`

The worker was started with both evaluator keys blank. No assessment and no wait occurred; the report
was recorded as `MISSING` and the run failed (**D30**).

### Spend

Session USD 0.012. Cumulative W1: **USD 0.627 of 6.00**.

### Criterion changes (session 9)

| Criterion | AI Engineer |
| --- | --- |
| KS seal, decide, use decision | **pass** |
| Held report (`review_pending` wait) | **pass** |
| Review approve with a separate reviewer | **pass** |
| Unauthorized review on a real decision | **pass** |
| Promote | **pass** |
| Fulfillment@1 rows written, required progress note fulfilled | **pass** |
| Report fulfillment / run accepted | **fail** (D28) |
| Expected vs optional | partial: the distinction is visible, but submitted expected text is recorded as `MISSING` (D29; fixture now uses `scope: iteration` for summary and caveats) |
| Missing-key evaluator wait | **fail** (D30) |
| Native write with readback | unrun (D28; no production path delivers the decision handle to a later iteration) |

Biotech: not started (same blockers; the first drain-enabled start is still unspent).

### New defects

**D27 – the verifier can submit the producer's promises.**
- The GoalDirected verifier inherits `submit_output` and re-submitted `root.report` (revision 2).
- That started a second assessment, a second KS decision and a second human review.

**D28 – an approved, promoted report still fails reference-promise fulfillment.**
- After review approval and promotion, the reference promise still answers `REFERENCE_USE_UNPROVEN`
  ("no revision with current official use eligibility").
- The reviewed decision is not seen as official-use evidence.

**D29 – the unmet code is misleading.** A submitted but unpromoted invocation-scope text promise is
reported as `MISSING` ("0 accepted").

**D30 – no evaluator credentials means no evaluation at all.**
- Without evaluator keys the worker composes no trusted settlement.
- Promises that declare `knowledge.report.assess@1` then get no assessment and no evaluator wait, and
  the run fails, instead of waiting or being refused at admission.

**Also observed:**
- KS `ReadTimeout` on the first review attempt; the 10 s binding timeout gave a 503 `review_unavailable`, and a retry worked.

## Session 8 (MC 78865e82 merged as 9b8dd693)

**Status: blocked at the KS seal (D25). The independent judge and auditor are now proven real.**

Fresh Sonnet run `9cc17684`:
- Registered `kh:aiengineer-postgres/report/w1-aie-s10-r1@research-report.v2`.
- Submitted the report, the progress note (`scope: iteration`), the summary and the caveats.
- USD 0.127.

In its trusted settlement, MC recorded two `report.observe` handles, so the D22 fix works. KS holds
the real observations:
- **Auditor census:** `claude-haiku-5-5`, 1 call, USD 0.0003.
- **Judge:** `gpt-5.6-terra` on the Responses API, 1 call, USD 0.0031, `full_support` on both support
  sets. The D24 fix works.

**D25 – the seal fails because no seal signing key is registered.**
- `report.seal` fails inside KS with `SEAL_INVALID`.
- `knowledge_verification.seal_signing_key` is empty on both remotes, so the executor's
  `KS_KNOWLEDGE_SEAL_KEY_ID` is unknown to the component.
- The seal key's public half must be registered on both remotes, once each. This is integrator
  provisioning.

**D26 (minor):** the old run `29a1eae9` cannot terminalize; its family failure waits on
`budget_not_settled`.

Budget re-measured from the KS observation `cost_usd` rows: earlier evaluator exposure was cents, not
up to 0.40. Cumulative W1: **USD 0.615 of 6.00**.

### Criterion changes (session 8)

| Criterion | AI Engineer |
| --- | --- |
| Real judge and auditor through KS | **pass** (observations recorded, run `9cc17684`) |
| Seal, decide, review, promote, Fulfillment@1 of the report | blocked (D25) |
| Held report; missing-key evaluator wait; native write | blocked (D25) |

Biotech: not started (the native write needs a decision; D25 affects the Biotech remote too).

## Session 7 (MC f748adaf merged as 4d92630f; remotes on common 1.9.0)

**Status: blocked at the judge (D24).**

Run `042beb7a` resumed from its saved result with no new producer call. Every judge run failed before
billing. `gpt-5.6-terra` (`judge.default`) is called on `/v1/chat/completions` with function tools and
`reasoning_effort`, and OpenAI answers 400: "Function tools with reasoning_effort are not supported
for gpt-5.6-terra in /v1/chat/completions. To use function tools, use /v1/responses or set
reasoning_effort to 'none'."

**The D23 fix works:** the cause is now recorded on the standing `unavailable` assessment and in the
wait detail. The operator reset was not needed, because unbilled failures are not counted as attempts.

Spend: USD 0.00. Cumulative W1: 0.484 (at most 0.934).

**D24 – the pinned judge cannot run.** The evaluator runner's OpenAI path combines function-tool
structured output with `reasoning_effort` on Chat Completions, which `gpt-5.6-terra` rejects. Every
judged report is blocked.

Criteria: unchanged from session 6. Review, promotion, fulfillment of the report, the held report,
the missing-key wait and native write remain blocked. Biotech was not started.

## Session 6 (floor lowered to 0.8 GB available by integrator decision)

**Status: blocked at the first trusted observation (D22).**

**The pinned producer now works (the D18 fix).** Sonnet run `042beb7a`:
- Registered `kh:aiengineer-postgres/report/w1-aie-s9-r1@research-report.v2`.
- Submitted the report, progress note, summary and caveats.
- 3 calls: 41,766 tokens in, 4,521 out, USD 0.129.

**The auditor's census is now accepted by KS (the D20 fix).** But Mission Control cannot record the
resulting `report.observe` handle:
- `knowledge_operation_handle_operation_check` rejects it, because the 1.6.0 migration
  `scripts/release_160/0055_*.sql:65` allows only `knowledge.read`, `knowledge.apply`,
  `report.register`, `report.assess`, `report.derive` and `verify.claims`.
- This is **D22**. It needs a common-release migration.

**The judge is unavailable, with no reason logged.** On the next passes the judge (`gpt-5.6-terra`)
produced no usable output, so an `unavailable` assessment was recorded. No reason is logged (**D23**).

**I stopped the worker** to cap repeated paid evaluator runs. The run is resumable, waiting
`settlement_unavailable`.

**Spend:**
- Sessions 5-6: USD 0.129, plus at most 0.40 of evaluator runs (not visible in the transcript).
- Cumulative W1: 0.484 (at most 0.934).

**Biotech** was not started.

### Criterion changes (session 6)

| Criterion | AI Engineer |
| --- | --- |
| Ordinary report, real producer (pinned Sonnet) | **pass**: registered and submitted (`042beb7a`) |
| Real judge and auditor through KS | **fail**: auditor census accepted by KS but unrecordable (D22); judge unavailable (D23) |
| Review approve, promote, Fulfillment@1 of the report, saved settlement | blocked (D22) |
| Held report; missing-key evaluator wait; native write | blocked or unrun (D22) |

Biotech: every criterion is blocked (not started; D22).

## Session 5 (after the D18-D21 fixes; MC 7fecec96 merged as 926531b2; KS f8d5e48)

**Status: unrun. The host does not have the memory to start the worker.** No cognition ran, so no
criterion changed from session 4. Spend: USD 0.00 this session; cumulative 0.355 (at most 0.405).

- **Fixtures:** progress_note now has `scope: iteration` in all five manifests (the D21 fix); offline
  compile ok. The launch bindings are unchanged.
- **Memory:**
  - The WSL cache drop gave 2.13 GB available.
  - With Temporal, KS and the API running, available memory fell to 1.17-1.38 GB.
  - With nothing of this runner running, it stayed at 1.30 GB.
  - That is below the 1.5 GB floor needed before starting the worker (~500 MB).
- **Pending run:** Sonnet run `042beb7a-27a3-51bf-8846-cc3eae65678f` was compiled, submitted and
  started. Its Temporal root is queued in `stack/temporal-w1-s4.db` and dispatches when a worker next
  starts on that file.

## Session 4 (after the D10-D17 fixes; MC 77783f30 merged as 2081ae6a)

**Status: blocked. A real model-authored KS report was registered and submitted for the first time
(run `29a1eae9`). The real independent auditor then ran, but KS refused its census on every pass
(D20), so the judge, review, promotion and fulfillment of the report were never reached.**

Spend: session 4 USD 0.147, plus at most 0.05 of uncertain auditor reruns. Cumulative W1: 0.355
(at most 0.405) of 6.00.

A fresh local Temporal dev server was started. The old server file is kept as history: its
`1e9b00df` and `e468c75f` family workflows are still Running there (the pre-fix decode loop).

### Runs

| Run | Producer | Result |
| --- | --- | --- |
| `457bd952` | Sonnet (`producer.default`) | 400 "Schema is too complex." (D18). The run terminalized as failed (the D15 fix works). |
| `c859ac2a`, `6bba405c`, `f3f00c28` | Haiku (fallback, recorded) | Typed argument and KS field-path refusals now reach the model (the D11 and D17 fixes work). A refused registration had already written its assertions, so every corrected retry hit `ASSERTION_CONFLICT`, which KS returns as an internal error, giving `UNRESOLVED_EFFECT` (D19). |
| `29a1eae9` | Haiku | Report `kh:aiengineer-postgres/report/w1-aie-s8-r1@research-report.v2` registered; progress note, summary and caveats submitted. Settlement: real auditor census refused, "INVALID_ENVELOPE: the census is not a valid discovery", on 7 passes. Waiting `settlement_unavailable`; the producer is not rerun. |
| `9a1a484e` | Haiku | Required report deliberately omitted. Typed Fulfillment@1 decisions; `output.fulfillment_unmet` events; run terminal failed. Optional `caveats` unfulfilled and not actionable; expected `summary` actionable. |

**Restart test, run `f3f00c28`:**
- The worker was killed during the saved-settlement effect wait and restarted.
- The settlement record resumed (waits 5 to 7, unchanged `saved_at`).
- Exactly one cognition (one turn).

**Biotech:**
- Gateway reviewed: `gateway.py:1101` keeps a `pending_dispatch` effect unresolved until a delivery
  lookup. It is not terminal.
- The Biotech stack was **not started**: the native-write run needs a recorded KS decision, which D20
  prevents. The first drain-enabled start of its KS executor is still unspent.
- `biotech.native-write.mission.yml` is authored (offline compile ok); the Biotech reviewer grant was
  not provisioned.

### Criterion matrix (session 4)

| Criterion | AI Engineer | Biotech |
| --- | --- | --- |
| Ordinary report, real producer | **partial**: registered and submitted by the Haiku fallback (`29a1eae9`). The Sonnet pin is blocked (D18). | blocked (not started; D20/D18) |
| Real judge and auditor through KS | **fail**: auditor ran, census refused (D20); judge not reached | blocked |
| KS use, review approve, promote | blocked (no decision; D20) | blocked |
| Unauthorized review | pass (session 3, real refusal) | unrun |
| Fulfillment@1 and saved settlement | **partial**: Fulfillment@1 rows written for `9a1a484e`; settled. The report path is waiting. | blocked |
| Required progress note | **fail**: submitted, never promoted, so recorded as unmet (D21) | unrun |
| Expected vs optional visible | **pass** (`9a1a484e`: expected actionable, optional silent) | unrun |
| Omitted required gives typed unmet and terminal | **pass** (`9a1a484e`) | unrun |
| Held report | blocked (D20) | blocked |
| Unavailable evaluator wait | **partial**: an evaluator refusal holds the settlement (`settlement_unavailable`, backoff, no producer rerun). The missing-key variant is unrun. | unrun |
| Worker restart during effect wait / after cognition | **pass** (`f3f00c28` kill/restart; `3081b3e4` lease expiry) | unrun |
| Native write with readback | blocked (no decision) | blocked (KS executor never started) |

### New defects

**D18 – the pinned producer still cannot run.** `claude-sonnet-5-5` with provider-native structured
output answers 400 "Schema is too complex." for the GoalDirected executor observation schema.

**D19 – a refused registration poisons its record ids.**
- KS `report.register` writes evidence records before validating the body.
- A retry that reuses the ids then raises `ASSERTION_CONFLICT`. KS treats that as an internal error,
  and MC reports `UNRESOLVED_EFFECT` with no message.
- The saved settlement then waits on the uncertain effect until the 24-hour deadline.

**D20 – KS refuses the live auditor census.**
- KS refuses the census MC builds from the real auditor with "the census is not a valid discovery".
- KS returns `details.issues`, but the MC evaluator path drops them, so the cause is not visible in
  MC logs.
- Blocks every judged report.

**D21 – text promises are never promoted.**
- Inline text promises with no declared requirement are never promoted.
- Required and expected text outputs are therefore unmet even when submitted, and the required
  progress note can never be fulfilled.

**Fixture lessons (not defects):**
- Model-authored record ids must be unique across runs.
- KS label patterns apply.
- The KS evidence pack and instructions must stay well under the 8192-character context bound.

## Session 3 (after the D9 fix; MC f37c6c26 merged as 9540542b)

**Status: blocked. The first real cognition ran, but the producer cannot register a KS report, so
nothing downstream of the report was exercised.** Spend: USD 0.208 at most (list price, no cache
discount) of 6.00.

### Runs

The AI Engineer stack ran on the generated env files. The only addition was the launch-bindings path.

| Run | Producer | Result |
| --- | --- | --- |
| `1e9b00df`, `e468c75f` | Haiku | No cognition. The family workflow loops forever on the 8192-character run-control bound. In `e468c75f` the bound was hit by the context packet (8524 chars) and the sealed lane binding. |
| `361d04a8` | Haiku | Cognition ran. `report_register` returned `INVALID_ENVELOPE` with a null message. The repaired retry replayed the rejected journal. `submit_output` needs `root.*` keys. |
| `3081b3e4` | Haiku | The `report` argument was stringified on every call (D17). The progress note was submitted. A lease expiry after the turn settled from the saved result, with **no second cognition**. |
| `0da30ad0` | Sonnet (`producer.default`) | Provider refused with 400: `tool_choice` "tool"/"any" is not supported for this model (D16). |
| `202c49b2`, `4ad5c958` | Haiku (fallback, recorded) | D17. The progress note, summary (expected) and caveats (optional) were submitted as drafts. |

After every Haiku turn the verifier stopped with `context_delivery_blocked: SOURCE_NOT_ACCEPTED`
(missing report). The family workflow then failed ("verifier reconciliation omitted its typed
result"), and the root workflow failed too. The MC lifecycle nevertheless stays running/active.

**Review route:**
- KS reviewer grant provisioned and scoped to the fixture's use and audience: status `granted`.
- The launcher's bearer on a real run gets 403 `unauthorized_review`.
- The reviewer's bearer gets 409 `decision_not_in_run`.
- No real decision existed to approve.

**Biotech source:** captured live with Firecrawl, scrape `01a18499-…`, HTTP 200.
- URL: `https://www.qualialife.com/shop/qualia-mind`
- Captured at: 2026-10-28T22:20:07Z
- Supplement-facts section sha256: `64a129370c9e7ef102c137e107bbe82d7d6666b588cf0110355221adecf221b3`
- Quote: "Other Ingredients: Hypromellose, Rice Flour, L-Leucine, Calcium Silicate, Silica"
- Pack and the model-authored manifest are written and compile offline.
- The Biotech stack and its KS executor were **not started**: the first drain-enabled start must be
  the native-write run, which needs a registered report.

### Criterion matrix (session 3)

| Criterion | AI Engineer | Biotech |
| --- | --- | --- |
| Ordinary report, real producer | **fail/blocked** (D16, D17, D12) | blocked (same producer rows; stack not started) |
| Real judge and auditor through KS | blocked (no report) | blocked |
| KS use and review | blocked (no decision). Route exists; see the next row | blocked |
| Unauthorized review | **pass (real refusal, probe decision)** | unrun |
| Explicit fulfillment, saved settlement | blocked (D14: no fulfillment decision recorded) | blocked |
| Required progress note | submitted (draft accepted); not promoted or fulfilled (D14) | unrun |
| Expected/optional distinction | partial: both submitted as drafts in the run's output-events; no fulfillment decision shows the distinction (D14) | unrun |
| Omitted required report produces unmet | **fail**: the family workflow fails and the run hangs (D14, D15) instead of a visible unmet | unrun |
| Held report | blocked | blocked |
| Unavailable evaluator, ungrounded disagreement | unrun (no report to evaluate) | unrun |
| Restart after cognition, no repeated cognition | **partial pass (real, natural lease expiry, run 3081b3e4)**; a kill-the-worker proof is unrun | unrun |
| Native-write variant | blocked (no decision) | blocked (KS executor never started) |

### New defects

**D10 – the 8192-character run-control bound blocks ordinary prompts.**
- `domain/policies/payload_bounds.py:67`, via `Contract.bound_persisted_payloads`, applies the bound to
  the prompt segments and the sealed lane binding inside `GoalOperationDispatch`.
- A context packet over 8 KB therefore makes the family workflow fail to decode on every activation.
- Compile, submit and start do not check it, and the run cannot be cancelled to a terminal state.

**D11 – the KS refusal message is dropped.** `report_register` shows `refusal.message` null, so the model
cannot repair.

**D12 – a refused registration cannot be retried in the same attempt.**
- The `report_register` effect key is per invocation.
- A corrected retry replays the rejected journal as `ok:true`, with no handle and no refusal.

**D13 – promise keys are not discoverable from the refusal.** `submit_output` accepts only `root.<promise>`,
and its `OBLIGATION_UNDECLARED` refusal does not list the pinned keys.

**D14 – an omitted required report crashes the run instead of producing unmet.**
- The verifier's transfer plan requires the missing report (`SOURCE_NOT_ACCEPTED`).
- The GoalDirected family then raises "verifier reconciliation omitted its typed result"
  (`adapters/temporal/workflows/goal_directed.py:583`).
- An omitted required output yields a crashed family, not an unmet promise.

**D15 – a failed root workflow is not reflected in the run lifecycle.** The run stays running/active.

**D16 – the pinned producer cannot run on the Deep Agents lane.**
- `claude-sonnet-5-5` (`producer.default`) refuses the `tool_choice` that the lane's structured
  `response_format` uses.
- The pinned producer is unusable on this lane, even though `models.toml` lists
  `supports = ["structured_output", ...]` for it.

**D17 – the model sends `report` as a string.**
- The `report_register` argument `report: dict[str, JsonDocument]` is sent as a JSON string by
  `claude-haiku-5-5` (9 of 10 calls across runs).
- The tool refuses with "Input should be a valid dictionary" instead of accepting canonical JSON text.

Operating note: an operator cancel of active work with `immediate` urgency needs `workflow_run.admin`;
`normal` was accepted.

## Session 2 (rerun after the D1-D8 fixes)

**Status: blocked again, before any paid cognition, by a new defect D9.** Spend is still USD 0.00.

- MC `sprint-oc` 31ba1341 was merged into this branch (19d2cbc0).
- The pack builder now freezes only the task and the sources. The producer authors the assertions,
  support sets and body, and the host computes the digests (D1 fix).
- The launch bindings were regenerated.
- The AI Engineer stack started on the generated env files alone. The API ran on 8010 with
  `--loop mission_control.bootstrap.api:api_loop_factory`. The worker registered 7 queues under
  versioned deployment `mission-control@0.1.0`.
- The dry run (Haiku producer, audience `internal`) passed online compile with 0 blockers.
- Submit admitted run `1e9b00df-54ce-5f56-97ea-6232f02e1756` (mission `01a18486-6bd2-7597-844c-61f7f367c1bd`).
- Start answered **409 `start_unavailable`**: "capability tool.knowledge-report-register@1 binds a
  component this deployment does not serve". The run was never started; nothing was dispatched.
  Digests (sha256, first 16 hex): compile `22b6105638ed1b62`, submit `dd1a61f099c97cb1`, start
  `8b6f3b427eb9ff40`, packs `4f9b9d9f0aef2077` and `a03a51cf536910cb`.

**D9 (hard blocker for every app and run that selects a knowledge tool): no launch author serves the
knowledge tools.**

- `bootstrap/api.py:826` composes `compose_manifest_launch_inputs` without `additional`.
  `served_components` (`bootstrap/manifests.py:262-281`) therefore serves only the pin-file tools.
- The knowledge tool components are registered only in the worker's activity composition
  (`adapters/temporal/deployment_composition.py:1314`).
- The worker's chain-relay author (`bootstrap/worker.py:750`) has the same gap.
- A pin-file tool needs a worker-built `kind`, so no operator file can work around it.
- The launch tests pass only because their fixtures inject `additional`.

Every criterion below therefore remains blocked or unrun in session 2. The rest of this page records
session 1 (2026-10-28, before the fixes).

## Session 1

**Status: blocked. Nothing in W1 passes yet.** No paid cognition ran, and the spend was **USD 0.00** of
the USD 6.00 W1 allocation. No run was admitted, so no MC rows were written: the one submit attempt
rolled back. The Biotech KS executor was never started, so the condition that the first drain-enabled
start is the W1 native-write run still holds. Aura was not touched. The full detail is in the ignored
`.scratch/sprint-oc/evidence/w1/W1-EVIDENCE.md`, and the budget ledger is `.scratch/sprint-oc/evidence/w1/BUDGET.md`.

## What was delivered (branch `sprint-oc-w1`)

| Item | Path | Validation |
| --- | --- | --- |
| AI Engineer report fixture: GoalDirected root with an independent verifier on `producer.fallback`. Named promises: `report` (reference, required, `knowledge.report.assess@1`), `progress_note` (text, required), `summary` (text, expected), `caveats` (text, optional). | `tests/fixtures/manifests/sprint-oc-w1/ai-engineer.report.mission.yml` | Offline compile: ok. **Online compile against the remote catalog through `mcl_runtime`: ok, 0 blockers, 0 warnings.** |
| AI Engineer native-write variant: adds `knowledge_apply` and `native_receipt` (an effect receipt, required) | `.../ai-engineer.native-write.mission.yml` | Offline compile ok. Not run. |
| Biotech report fixture: frozen product name "Qualia Mind". The label capture is **not frozen yet**: no verbatim label text was captured, and none was invented. | `.../biotech.report.mission.yml` | Offline compile ok. Not run. |
| Frozen source pack builder (session 2: only the task and the sources, one verbatim quote each; it authors no claim; `--audience` and `--risk` select a review-requiring task) | `scripts/sprint_oc_w1_pack.mjs` | AI Engineer packs built: Mistral 7B, Gemma 2, Llama 3.1. |
| W1 operator launch bindings (`MANIFEST_LAUNCH_BINDINGS_PATH`). Model profiles come from `models.toml` plus the pinned models, and the 6 knowledge tools are bound to the worker's components. | `scripts/sprint_oc_w1_bindings.py` | `ManifestLaunchBindings` validates; the profile digest is resealed. |
| Driver: render (pack substitution), compile, submit, start, wait and collect (run, outputs, transcript) over the operator HTTP routes. Key names are scrubbed and the token is read from its file. | `scripts/sprint_oc_w1_driver.py` | compile and submit exercised |

## Criterion matrix

Status words: **blocked** means a defect prevents the proof. **unrun** means the step was not reached.
Nothing below is *real* or *doubled*: no proof ran.

| Criterion | AI Engineer | Biotech |
| --- | --- | --- |
| Ordinary GoalDirected report, real producer | blocked (D6, D8) | unrun (same D5/D6/D8 apply by construction; the label is not frozen) |
| Independent real judge and auditor through KS (observe, seal, decide) | blocked (D6) | unrun |
| KS use and review | blocked (D6). The review route does not exist (D2) | unrun |
| Explicit fulfillment, required progress note, saved settlement | blocked (D6, D8) | unrun |
| Native-write variant with readback and no duplicate write | unrun (fixture only) | unrun (drain never started) |
| Omitted required output / expected versus optional distinction | unrun (the fixture declares all three enforcements) | unrun |
| Held report | unrun. An official-use report would hold indefinitely (D2) | unrun |
| Unavailable evaluator | unrun | unrun |
| Ungrounded disagreement | unrun | unrun |
| Unauthorized review | unrun. D2: no production review entry point to refuse from | unrun |
| Worker restart after cognition or commit, no repeated cognition or write | unrun | unrun |

Evidence digests (sha256, first 16 hex): pack `7506839ffbcd280d`, compile `b93b79c225a06842`, submit
`4f46106fb098a452`, rendered manifest `f4d251473dca2daa`, worker logs `29507b06d74a5656`, `c1a51db5d9a20603`,
`de55bf3930528521` and `8c98fc54c90fc4ee`, KS refusal `a5b1190324d923c0`, API log `aaa21fb5003f0872`, PIDs
`88b094cb10d97c21`.

## Defects for the integrator (not fixed by the runner)

1. **D1: no producer authoring aid for KS v2.**
   - `report_register` forwards the model payload verbatim.
   - The KS evaluation context matches support sets and fragments by recordRef digest
     (KS `host/src/knowledge-operation/assessment.ts`, `evaluationContext`).
   - A model cannot compute those digests.
   - W1 uses the frozen pack builder.
2. **D2: no production human-review path.** `TrustedJudgmentBridge.review`
   (`application/knowledge/judgment.py:369`) has no caller. Official and consequential use waits for review
   indefinitely. The fixture uses audience `internal`.
3. **D3: the API on Windows cannot open its saver.** The ProactorEventLoop stops the psycopg async saver
   (`bootstrap/api.py:391`), so time travel is unavailable.
4. **D4: the tracked skill pin is refused under Supabase custody.** In
   `infra/capability-pins/research-capabilities.json`, the agent-browser skill pin is legacy_text_v1 with a
   workspace locator. Worker start refuses it (`adapters/postgres/capability_bundles.py:94`). The runner
   overrode `CAPABILITY_PINS_PATH` with a copy that has no skills.
5. **D5: the generated issuer and audience break MC's name pattern.**
   - The values are `mission-control/<app>` and `knowledge-services-executor/<app>`
     (`scripts/sprint_oc_runtime_env.py:679,683`).
   - They break `Origin.issuer` (`bootstrap/composition.py:699`) and `CredentialClaims.aud`
     (`contracts/knowledge_protocol.py:497`).
   - The runner overrode both sides with dotted names.
6. **D6 (hard blocker, both applications): MC and KS disagree on the installation id.**
   - MC uses its own installation id as the KS origin `installationId` (`bootstrap/composition.py:696`).
   - KS authorizes against the component installation id (KS `auth.ts:384`). The component database pins
     it (`COMPONENT_INSTALLATION_MISMATCH`).
   - No setting maps one to the other.
7. **D7: the restricted logins cannot use hybrid capability search.**
   - The logins (`mcl_*`, `mission_control_runtime`) lack USAGE on schema `extensions`.
   - Hybrid capability search therefore fails with an untyped 500
     (`adapters/postgres/capability/capability_search_repository.py:487`).
   - The fixtures use exact `#sha256` pins.
8. **D8: no tenant rows on either remote.** `mission_control.tenant` is empty on both remotes, so every
   submit fails with an untyped 500 (an FK error in `adapters/postgres/control_plane/mission_revisions.py:67`).

Environment note: TCP 8000 is held by the owner's docling MCP server. The AI Engineer API used 8010.

## Remaining for W1 release

Integrator work:
- Fix D5 and D6 at the source.
- Provision the tenant rows (D8).
- Grant `extensions` USAGE, or qualify the search (D7).
- Fix the pin file or bundle custody pins (D4).
- Decide D2: an operator review route, or W1 scoped to internal use.

Then rerun this runner from step "worker start":
- AI Engineer, in this order: a Haiku dry run, the Sonnet report, the restart/kill proof, the cheap
  negatives, then the native variant with AIDB readback.
- Biotech: freeze the label capture into the pack builder, then the same sequence, with the first
  drain-enabled KS start being the native-write run.

An independent reviewer releases W1 only on every criterion.
