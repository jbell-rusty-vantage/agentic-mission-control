# RUN-2 live-family recovery proposal — 2026-10-16

**Planning proposal; no dispatch or mutation approval is conveyed.** R2A settles one existing operation from retained evidence. R2B separately resumes its genuine pending Temporal family activity. The v5 changes remain isolated and are not integrated into canonical v4; the canonical 45-file hash envelope remains intact.

## Evidence and exact target

Evidence paths below are relative to the isolated checkout. Ignored receipts live under `.scratch/run2-completion-20261016/continuation-v5/`; preserve them independently of Git.

| Join | Exact retained value |
|---|---|
| Request scope | `mc/01a103c0-9a9e-70f3-9398-eb1573a98324/ai-engineer/00000000-0000-7000-8000-000000000001` |
| Public / internal run | `60f44a50-c0e4-5edb-ac13-0fb0436aaedb` / `01a14386-3bb2-7dd0-ba2b-f33d0eaa2053` |
| Harness / generation | `4eb7354d-980a-52f1-93b3-83b6b8863a2b` / `1` |
| Binding / original claim | `7669041e-bf40-58a2-9878-82a85b975b92` / `c0d3b676-9738-59c7-9b47-01566d1a9420` |
| Native session / turn | `agent-73162e55-750b-4f76-8762-ebee7c6dcead` / `run-2df4a451-c80c-4814-843c-3cc542048c2f` |
| Family Temporal execution | `01a143c9-1e58-7e14-9d5d-8da6ec22a0ee`, RUNNING |
| Operation Temporal execution | `01a143c9-295a-7d84-8b47-89e40f34df00`, FAILED |
| Root Temporal execution | `01a143c9-1e17-72b3-9698-9c3f20a1a12c`, RUNNING |
| Pending activity | `stagegraph.decide_result`, activity ID `3`, scheduled event `33`, pinned attempt `27` |
| Exact queue | `mc-ai-engineer-coordinator-family-stagegraph` |
| Cancel command | `6a5398e3-2a73-4351-a354-a24a9a4ddc4b`, delivered, receipt ordinal `2` |
| Run / harness / owner frontier | cancelling v5 / harness revision140 / owner epoch1, expired |

`installed-pending-context-dryrun-r3.json` at **19:12:45Z** passed typed-input and pure context validation. It called no adoption method, claimed no owner, staged no artifact and made no shared writes.

| Pinned digest | Value |
|---|---|
| Authority | `sha256:4ecd961ea953e4778a1bf69b3e0f51d9bf5fc204948ffbcf5782253a65b94966` |
| Original/current family projection | `sha256:fe2905b2abaace9136235108132ede15f887259a00d9c86013e9005764815785` |
| Genuine original failed-result request | `sha256:05894ea94bf49ae533d292e41d05fa59655b5e0ccb404455b9d2f53e67c0c720` |
| Pending input proof, including attempt | `sha256:a9f5a5e73a76107a8b087513ebab32bb15384d44c2a8d1eb0d8e134ea3a10ca0` |
| Normalized retained capture | `sha256:eb9a2190dc36283f3065e86429ed7ae4c04641addb3f215d1baab387de78d465` |
| Retained response | `sha256:2e4aac0d29aae546e783667baef26ec7850b3f34586d62908f1f66171e194a7c` |

The approved private R1 evidence is 2946 bytes, native FINISHED, explicit total926070 tokens and cost **None**. Source counters are separately pinned; no cost estimate, zero or provider acknowledgment is inferred. The actual binding reserves only one concurrency slot and one operation attempt, with admitted currency0 and no pending financial settlement at the dry-run read.

At the **18:46Z** namespace inventory there were only two Running workflows (root/family), one unresolved activity3/event33, no pollers, and ECS desired/running/pending0. Build compatibility returned `PERMISSION_DENIED`: compatibility remains unknown, and no access elevation is proposed. Visibility is not an atomic quiescence barrier; these observations must be refreshed before any consequential step.

## R2A — one evidence-based operation settlement

Proposed invocation: `TerminalEvidenceAdoptionService.adopt(prepared_request, actor)` through explicit `bootstrap/terminal_adoption.py` composition, with `pending_family_result_digest` selecting **settlement only**. Actor must already hold `workflow_run.reconcile_unit`. The retained dry-run request ID is `8fa03e94-d29a-4d46-9531-cf870cb41872`; the complete reviewed payload is in the r3 receipt, including capture reference `reviewed-r1-private-local-60f44a50-20261016` and the digest joins above.

Bounds: one service invocation, 30-second cooperative application deadline, bounded I/O and an owned outer process, one existing binding/claim and generation; no new operation admission, dispatch, session creation, send, resubmit, provider call or workflow termination. The asyncio deadline is not hard interruption of synchronous OS/SDK calls. A partial failure is not authorization for an automatic second invocation.

The exact effect sequence is private capture verification  ->  response custody  ->  expired-owner takeover  ->  owner-fenced intent/result/turn-ended frames  ->  original journal settlement and normal budget/effect post-effects  ->  usage-disposition observation. The genuine family journal is deliberately untouched; result must report `normal_family_activity_pending`. No alternate `decide_result()` call is permitted in R2A.

`installed-effect-plan-read-r4.json` at **19:51Z** validated the current context and pure three-payload prediction. Existing bucket is `mc-payloads-ai-engineer-298199649527-use1`; each exact key is `artifacts/sha256/<digest>` below. All three HEADs returned404, not write permission. No S3 GET/PUT, owner claim or database mutation occurred; retained private metadata was unchanged and no raw result/binding was emitted.

| Payload / exact SHA256 suffix | Bytes |
|---|---:|
| Response: `2e4aac0d29aae546e783667baef26ec7850b3f34586d62908f1f66171e194a7c` | 2946 |
| Operation output: `6349c4bbc0ffcb5bdb48ce05f116e8435102b0807d04c4c8f055d4fec274e323` | 1657 |
| Result manifest: `34e6ebc2ba1c285c1c46db362994bb0d1a8d6dab05d30ad052d67d656b72c948` | 881 |

Predicted immutable settlement ID is `455d3427-622a-5e0d-9dbc-b8acbc0caa42`, status completed, settled_at `2026-10-16T15:07:02.904315+00:00`. Normal usage attribution is input456013/output14072/total926070; pending external amounts are empty for this currency0 binding. Release exactly `concurrency.slots:1` and `operation.attempts:1`. This prediction does not accept a family/product output or acknowledge provider cancellation.

Pin command issuer `operation-journal`, observation command `operation-effect-observation:455d3427-622a-5e0d-9dbc-b8acbc0caa42`, observation ID `observation:455d3427-622a-5e0d-9dbc-b8acbc0caa42`, and authority command `operation-authority-settlement:455d3427-622a-5e0d-9dbc-b8acbc0caa42:revision:1`. Actual stage also sets artifact metadata and may create object versions. The executable envelope must bound that behavior and stop on a new/conflicting destination; a stale HEAD snapshot is not an overwrite guard.

`recovery-principal-read.json` at **19:27:53Z** verified AWS principal `arn:aws:iam::298199649527:user/overtonadmin` and taskdef16's existing database references. Session/current users were `mc_ai_engineer_runtime_login` (runtime member, not family-writer) and `mc_ai_engineer_family_login` (family-writer member, not runtime); both probes enforced read-only transactions against the pinned Supabase project/CA. Exact response HEAD returned404. This does not prove S3 PUT permission or an application actor grant. No credentials were saved, no `SET ROLE` or grants ran, and no S3 GET/PUT or database DML occurred. Settlement-only R2A should use the minimal runtime/journal role; no family-writer mutation is needed.

The actual trusted actor must be pinned in the consequential-action envelope: `workflow_run.reconcile_unit` for adoption plus the normal journal actor's required observation/usage/effect/output-evidence authority. AWS/database authentication alone does not establish those application permissions. A separately authorized one-time local operator composition may explicitly name its audit actor and permissions without creating persistent access; do not silently mint a self-authorized principal or require a new HTTP route by assumption.

Before-image custody must cover scoped run projection/version; command/receipt frontier; budget reservations/usage/pending/outstanding amounts; effect claim; operation binding/journal/settlement/outbox identities; harness native identity/dispatch/owner/version; frame cursor/key/digests; family head/admission journal; exact workflow descriptions, pending activity and history digests; and destination HEAD metadata. Retain private payload bytes only in existing approved private custody, never raw secrets or response bytes in Windows reports.

The machine-readable `continuation-v5/r2a-action-envelope.json` is **prepared, not execution-ready**. The new ignored `r2a_operator_composition.py` composes the real runtime-role RunControl/binding/atomic-journal/adoption path from supplied trusted ports, defaults off and permits one instance call. Eleven focused fake/recording-port checks and independent root review passed; exact content/ID/address/media pins, loaded module origins and original two-command identities are enforced. This does not prove the supplied external payload/private/DB I/O bounds, destination race/overwrite behavior, complete before-image/readback or actor authority. Those concrete gates remain before an approval request or invocation.

After the call, independently read back the same domains. Require one immutable matching settlement, one usage attribution, released slot/attempt exactly once, preserved claim identity, explicit total926070/costNone, no fabricated currency or cancellation acknowledgment, and no family decision. Positive admitted currency or actual pending liability must remain retained and prevent a closure claim.

Stop on changed run/generation/binding/dispatch/claim/cancel or pending proof, unproved custody, live competing owner, CAS failure, expired authority, unexpected write/destination or incomplete readback. Preserve every partial receipt. Recovery is forward-only exact-request replay after inspecting durable effects; never direct SQL rollback, deletion of evidence, replacement claim, regenerated request or guessed settlement.

## R2B — separately bounded normal Temporal replay

R2B requires a separate reviewed execution envelope after R2A readback. Preserve the original **failed** activity request digest above even though native retained evidence is FINISHED and the operation journal becomes completed. The normal cancelling-family decision quarantines the original result; synthesizing a completed family request would poison its immutable replay identity.

The initial activity/function allowlist is only `stagegraph.decide_result` on `mc-ai-engineer-coordinator-family-stagegraph`. A subsequent workflow worker must be pinned to the exact existing `belllabs.stagegraph` execution and reviewed compatible implementation/build. Root handling, if required, is a distinct exact `mc.mission_run.v1` workflow/queue envelope; its queue and allowed transitions must be proven before activation, not guessed. Do not register operation/lane/provider activities or additional family functions by convenience.

Require single activity/workflow concurrency, finite wall-clock/process lifetime and an exact unexpected-task refusal/stop design. Queue polling cannot request only workflow/activity3: the plan must show how an unexpected task is refused **before effects** and how worker exit is proved. No shared consumer activation until compatibility/version routing and these stop semantics are reviewed. Namespace inventory and empty pollers alone cannot enforce exclusivity.

At **20:06Z**, `exact-history-replay.json` passed local SDK replay of the exact family38/root16 recorded events against candidate workflows and the production sandbox runner, one executor. Histories were bounded, contiguous and unchanged at readback; no raw history was saved, no live task was polled and no workflow/DB/S3/provider mutation occurred. This removes the untested past-history replay assumption for those exact hashes. It does not establish current version routing, future-command behavior, unexpected-task guards or permission to activate a worker. The denied compatibility query remains unknown.

Normal Temporal delivery must own activity completion, family journal replay and subsequent workflow progress. An out-of-band application call does not complete Temporal activity3. Read back original request acceptance/quarantine, producer closure, cancellation receipt application only at the actual terminalizing commit, and final workflow/run/budget/effect states. Never equate family progress with complete run closure or provider cancellation acknowledgment.

## Current gates and qualification limits

- Final candidate validation passed: dependency-aware mypy18 source targets; Ruff/format11 edited files; combined selected regression **677 passed/10 POSIX skips**; actual Linux private-reader/registry **28 passed**; actual disposable PostgreSQL context **1 passed**. Source hashes were stable and exact owned fixtures were removed. These selected proofs do not qualify every original native/release criterion.
- Ordinary WSL/Docker startup authorized at19:19 restored the same five protected container identities. Headroom later recovered without process/session/service teardown; the final combined run began with2.76GiB and ended with3.06GiB available. Initial memory refusals and sandbox/path failures remain retained. Keep the1.5GiB start gate and serial leases; do not increase caps or change protection automatically.
- Existing approved AWS test-infrastructure allowance is inclusive USD10; it is not a blanket prohibition on disposable validation and does not authorize production reconciliation by itself. Production principal/destination and R2A/R2B remain separate.
- Full G1 is **not qualified** by the three real SDK host cases, registry18 or private-file10 source checks. The original18 S0 cells, LS07/08, two-mission scenarios and remote qualifications are unchanged. AF-FOLLOWON remains excluded.

See the [current continuation matrix and execution packages](RUN-2-CONTINUATION-STATE-2026-10-16.md) for the final selected-suite receipts, independent W0-W10 review, exact G1 joins and candidate integration boundary. R2A remains unexecuted and not approval-ready until its complete writer/before-image/readback/actor envelope is reviewed. Earlier scratch predictor failures are preserved: a truncated hardcoded pin caused refusal before private capture, then the corrected64-character pin passed. Production context and source were unaffected; do not invent a cross-platform product defect from that scratch error.

## Related records

[Reconciliation](RUN-2-CURRENT-RECONCILIATION-2026-10-16.md)  |  [Execution ledger](RUN-2-EXECUTION-LEDGER-2026-10-16.md)  |  [Qualification envelopes](RUN-2-QUALIFICATION-ENVELOPES-2026-10-16.md)  |  [Remaining gates](RUN-2-REMAINING-GATES-2026-10-16.md)  |  [G1 acceptance](RUN-2-G1-ACCEPTANCE-2026-10-16.md)  |  [Operations boundaries](RUN-2-OPERATIONS-BOUNDARIES-2026-10-16.md)  |  [Resumption/approvals](RUN-2-RESUMPTION-AND-APPROVALS-2026-10-16.md)  |  [Integration](RUN-2-INTEGRATION-2026-10-16.md)
