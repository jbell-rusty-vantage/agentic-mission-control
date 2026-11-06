---
type: Implementation Report
title: "Run 2 integration and remaining acceptance gates"
description: "Reviewed offline implementation, test evidence, immutable releases, unresolved implementation boundaries and unrun operational qualification."
tags: [mission-control, implementation, qualification, run-2]
---

# Run 2 integration and remaining acceptance gates

## 2026-10-15 resumed b9 qualification checkpoint

The owner resumed the mission. Source `b9eb7f186197e6edaff3b2032a25d0d3dc6c4c90`
contains the requested-cancellation cursor repair; its existing 68 focused unit
tests and real PostgreSQL regression passed. The existing isolated Linux runtime
attestation was independently verified without reinstalling it. A new binding
changes only the Codex workspace identity to that verified source/runtime.

The exact source image, final configuration and operator image passed their
bounded build, configuration and secret-scan checks. Fresh native authentication
proofs and normal owner prerequisite verification passed. AWS task revision 8
is running immutable image
`sha256:928942791aac588b39f2aa73087a5bdaec01966bc8e89dbd65d9b3db374f0a2d`.
The first promotion inspection refused an incomplete queue registration without
mutation; a subsequent inspection verified all 16 required queue/type pairs and
recent matching pollers before promoting build `0.1.0-b9eb7f186197`.

The bounded full3 probe is run `4a7d0b25-ed7e-585d-beba-453db2ed7c0a`, native
session `01a1419b-ee4e-77b0-8d15-40d5667b6fe2`. Independent evidence at 22:09 UTC
confirms authenticated inspection of its actual identity and a native PreToolUse
denial of the harmless force-push canary. The run was active, with no report yet
present and no terminal native marker. Report validation, immutable custody,
genuine human REVIEW, settlement and caller wake remain unproven at this
checkpoint. This does not qualify the full 18-cell S0 matrix or remote S2/S3.

At 22:10 UTC the probe completed normal settlement and reached the declared
REVIEW, task `202902a0-5caf-50eb-ba89-f60cd7f7733c`, assigned to the selected human
actor. The controller stopped observation without cancelling or resolving it.
Persisted native attribution and the ledger agree on **79,383 input + 8,770
output = 88,153 tokens**. No probe usage or effect remains outstanding; the
remaining reservation belongs to the waiting review stage. Runtime cleanup
removed the local native rollout before an independent final capture, so the
earlier 37,526-token snapshot is only an independent lower bound.

The report is registered as
`workspace-candidate://2def77d4-663c-52b0-b4cc-b3c4fc7d5812`. Its 1,356 bytes were
retrieved from durable S3 custody and verified against content SHA-256
`1ff51a84dfec147ff0d8893bd7a8ca0234450474ec45f5d6fe6d60b0d4e3c2fe`.
The review packet's candidate-reference digest is distinct from that content
hash. Validation passed against the actual admitted
`input:stage-output-contract:probe` JSON Schema, resolved through this run's
operation binding. The report records unknown/unrun qualification fields; its path/command
evidence strings require the separate native receipts for corroboration. Human
acceptance and full-matrix qualification remain pending.

At 22:15 UTC, exact PID/start-time guarded shutdown stopped the local lane;
no native descendants or owned processes remained. The base worker and bounded
API remained available for the open human review at this checkpoint. The review
launcher requires a genuine selected-account login and an explicit permitted
decision, rereads the packet/version before one submission, and never defaults
to approval. Five mocked checks passed; no live human login or resolution is
claimed. Read-only inspection also confirmed local Temporal reachability from
Windows and WSL, but that server belongs to the retained Biotech stack and has
no dedicated Mission Control namespace. No local namespace mutation occurred.

The API subsequently stopped at its 900-second bound. AWS shutdown at 22:21 UTC
verified desired/running/pending counts zero and no active tasks. The open review
was preserved. A final read-only audit still found version 9, one review-stage
reservation and no pending probe effects. Three persisted unknown frame types
were `account/login/completed`, `account/updated` and
`remoteControl/status/changed`; no native turn had unknown usage. These retained
notifications are not a claim of complete provider-event mapping.

Further preparation identified the actual installed Claude SDK 0.2.165 and
bundled CLI 2.1.294. Its separate native closure, catalog profile and launch
configuration remain preparation work; the Codex workspace proof is not reused
as Claude qualification. A proposed next Codex control runner passed initial
offline checks but independent review found an active-turn identity defect.
It remains unexecuted pending correction and review. No new model run or full
matrix acceptance is claimed.

The new attempt has a $1 planning reserve in the previously authorized S0 slice;
combined diagnostic reserves are $1.35. These are conditional planning amounts,
not billed cost or provider hard caps. The historical accounting discrepancy and
retained-resource liabilities remain recorded. No S4 funding hold, main merge,
push, ECS Exec or Linear publication was released.

At 22:34 UTC, after correcting and independently reviewing the control helper,
a separate bounded run `15346503-217e-5015-bc2f-17df9ea4809e` started on the same
immutable b9 placement. It ended with a failed outcome at 22:36:55 UTC, version 9.
No injection was submitted. The cleanup cancel was rejected with `stale_version`
while normal settlement advanced; it was not admitted and was not retried after
terminal state. There are no remaining reservations, pending effects, open
turns or ambiguous native dispatches. Persisted native attribution, the ledger
and the independent observer's latest counters agree on **33,526 input + 1,920
output = 35,446 tokens**. The observer retained 11 snapshots, including one
terminal snapshot. This supplies accounting evidence, not inject/replacement,
cancel or caller-wake qualification. The failure remains under diagnosis.

At 22:39 UTC the owned API and exact local worker were stopped, with no native
descendants remaining. AWS readback verified desired/running/pending counts zero
and no active tasks. The full3 human REVIEW remains untouched. Conditional
planning reserves now total $1.85 including this $0.50 control allocation;
known historical native totals including both new runs are 667,800 tokens.
The historical missing-ledger liability remains recorded; billed cost is unknown.

The Claude profile was published through the normal catalog service and its
offline SDK/CLI closure was captured and verified. Its next launch configuration
still requires matching evidence. Inspection found a source gap: the trusted
host prerequisite supports Codex native evidence but no corresponding Claude
operation. A narrowly scoped implementation is underway in an isolated checkout
from b9. File readiness and key resolution will remain distinct from live
authentication and model entitlement. No Claude inference or qualification is
claimed, and the live b9 runtime has not been modified.

At 22:58 UTC a dedicated local Temporal namespace `mc-run2-s0` passed the
normal 14-search-attribute readiness check at `127.0.0.1:17233`. The alternate
loopback port avoids the retained Biotech server on 7233. The first bounded
initialization timed out; its owned volume was retained and exact schema
versions inspected. Temporal's normal update-only procedure completed the
remaining migration, without recreating the database. All owned compute then
stopped; Biotech's five existing containers remained healthy. This is local
infrastructure readiness, not WSL reachability or a local S0 mission result.

The selected human needed clarification of application login versus the
existing PostgreSQL role password. A separate human-operated recovery helper
was independently reviewed and passed 11 mocked checks. It requires explicit
email consent and the human-provided recovery link; it never substitutes an
administrator or launcher identity for report acceptance. No completed password
change or human review resolution is claimed at this checkpoint.

At 23:07 UTC the selected human approved the exact full3 review packet through
the authenticated review helper. Its receipt records HTTP 200, `verified_resolved`
and actor `c92a578e-8607-4182-9ce9-b8d43ac96414`. Independent read-only database
inspection at 23:11 UTC confirms human task version 2 is resolved. The run remains
active version 9 until its background coordinator processes that decision; its
native session has ended, usage remains 88,153 tokens, and only the review-stage
reservation remains. Human approval is now proven; terminal run settlement and
caller wake are not yet proven.

Claude host prerequisite verification is committed separately as
`f70f594c391927bb419f44b5cb9010ab9e7bc7ea`. Its 70 focused tests, 12 architecture
tests, source type/lint checks and commit hooks passed. The isolated Linux runtime,
actual native dependency inventory verification and local source image import
smoke passed. The typed binding preserves unverified host readiness until normal
scoped owner verification. This source is not yet integrated or live-qualified.

At 23:18:23 UTC full3 reached **succeeded**, version 12, after the bounded
restart of the exact b9 base worker processed the genuine human approval.
Independent database inspection confirms zero reservations, pending effects and
outstanding usage. Usage remains 88,153 tokens with no additional provider turn
or dispatch. Final Temporal inspection found zero running workflows and unchanged
b9 routing. AWS shutdown readback at 23:19:55 UTC confirms desired/running/pending
zero and no active tasks. No coordinator notification was recorded for the
existing stream-ticket subscription; actual caller wake remains unproven.
This completes the full3 report approval and settlement, not the S0 matrix.

## 2026-10-15 continuation: Claude host preparation

After the approved full3 probe settled and its worker stopped, `mo/run2-integration` fast-forwarded to `f70f594c391927bb419f44b5cb9010ab9e7bc7ea`. This supersedes the earlier observation that the Claude host proof remained isolated. Main merge and push remain held.

The exact f70 WSL runtime and native host attestation verified successfully. Normal owner verification passed the scoped Claude A8 host and M4 broker checks, followed by ready preflight and successful compilation. These checks establish configured host prerequisites, not provider authentication, model entitlement, or lane qualification.

The verified operator image was published at immutable digest `sha256:ea89e0e8a0c96d781277e2bce7594c67502baec7ee3ec3c2ab48bf052c80cb6f` in the existing Mission Control ECR repository. The build passed its nonroot, network-disabled smoke check and secret sentinel scan; temporary registry credentials were removed. The exact task9 deployment preflight passed against stopped task8. No task9 deployment or Claude inference had occurred at this observation.

A bounded local API replacement and Claude lane startup are in progress. Native CLI transcript capture is being prepared separately from the adapter transcript mirror; missing terminal native evidence will remain an explicit limitation. The next probe retains the 20,000-token, 15-minute, 30-tool declared budget and requires its own genuine human review. Conditional reserves total $2.85 of the authorized $10 slice; actual provider invoice remains unknown, and these reserves are not a provider hard cap.

## Claude task9 startup failure and containment

The task9 deployment was accepted, but its base worker failed during ingress startup because inherited `INGRESS_MANIFEST_PATHS` referenced `/etc/mission-control/manifests/s0-codex-owner.yaml`, absent from the Claude operator image. The offline image smoke check had not covered the task-definition ingress paths. Temporal queue checks refused promotion; no Claude mission was submitted and no inference occurred.

The independently armed watchdog was triggered early and verified task9 at desired/running/pending `0/0/0` with no active tasks. The exact owned local lane process group and API were also stopped and verified. Failed deployment and monitoring receipts are retained. A corrected task-definition successor and an image-level reference check are being prepared; this failure is not lane acceptance.

## First Claude probe: startup incompatibility, cancellation unresolved

The corrected task10 configuration passed an actual offline image reference check, then deployed successfully. All 16 required queue/type pairs had matching recent pollers before f70 became Temporal's current build. A separate read-only snapshot confirmed the routing change and no existing workflows before admission.

Claude run `06399516-e748-51f4-a766-00c377cabd17` was admitted and started. Its sole native creation attempt became `in_doubt`; no native session identity, transcript frames, report, or human review was produced. The lane log records activity cancellation while creation was shielded, followed by a native initialization timeout. Inspection of the pinned SDK and CLI identifies a startup ordering incompatibility: the adapter waits for native initialization before input, while the CLI's local headless path emits that initialization during input processing. A metadata-only bootstrap repair is being developed offline; no provider creation retry occurred.

Normal cancellation `7483db23-f0a6-4ee3-b6cf-250896d08aeb` was durably delivered despite its HTTP timeout. The bounded controller later issued a redundant cancellation `28ed7105-3eae-4e2a-aeb9-e72610f641ee`, also delivered; both receipts are retained. The controller needs to recognize cancellation requested externally before its own deadline. The first cancellation helper had failed before sending a command due to a Windows/Linux JWKS path mismatch; its corrected successor used the verified Windows deployment.

At the final audit, the run remained `cancelling` v6 with one unresolved operation reservation/effect, no provider acknowledgement or settlement, and unknown native usage. Empty consumed usage is not proof of zero billed usage. The independent native watcher saw no CLI transcript. Cloud task10, the exact local lane process group, the API, and controller/waiter processes were stopped and verified. This is containment evidence, not terminal recovery or Claude qualification. No database status repair or fabricated usage was performed.


## Integrated Claude startup and uncertain-cancellation repair (2026-10-16 00:44 UTC)

Commit `ee3e1953a47c51ac19d8c06179f7951419ce80fb` passed commit hooks and was fast-forwarded onto `mo/run2-integration`. Unrelated dirty knowledge index, report changes and stackdump were preserved; no main merge or push. The repaired pinned Claude metadata bootstrap passed the actual SDK 0.2.165 / CLI 2.1.294 credential-free, network-disabled container proof: genuine init and matching zero-turn result, no business input. Proof 3 receipt SHA256 `f5c84d6f4d3d51674836a5235e420e859ba1c1a6aa8d64e08efc530719fbe988`; both earlier schema refusals remain recorded. This does not prove provider authentication or live inference.

The cancellation repair records a genuine ambiguity incident through normal operation authority, applies an accepted operator abandonment through the existing reconciliation policy, preserves unknown native status/usage, and retains unresolved native evidence. It does not fabricate provider acknowledgment or zero cost. Verification: 142 Claude tests; 67 focused recovery/regression tests; real Temporal cancellation, settlement and history replay (1 passed); disposable real PostgreSQL reconciliation (1 passed); 12 architecture tests; focused type checks and commit checks passed. PostgreSQL binding lookup and artifact byte storage use memory fixtures, explicitly limiting that proof. PostgreSQL receipt SHA256 `4976f9dafffc37e517dd48f0ec62610007b340bfc295a5c741c7ac34d776ae5b`; Temporal receipt SHA256 `c5ea943b343217ece71688b35cb1340f9f1846f141bb8c3cc534bab4d6ccc1af`. Owned test servers/containers were stopped and removal verified.

Live read-only Temporal inspection at 00:44 UTC confirms exactly the three workflows of Claude run `06399516-e748-51f4-a766-00c377cabd17`, all AUTO_UPGRADE, no pending activities or workflow task, current build still f70. Receipt SHA256 `b968cc89ed53f4174c4d09a05f35c5de9f0b3eaadca40c54a396e2f1d6401721`. The ee3 repair is not deployed and the live run remains unresolved. A bounded recovery wake and normal operator decision remain required before any new Claude creation attempt. Full3 human approval remains complete; whole-sprint qualification is incomplete.


### 2026-10-16 ee3 actual cancellation recovery

Integrated source ee3e1953a47c51ac19d8c06179f7951419ce80fb was published as immutable
operator image sha256:5148d59b8c91928b2417eb735a866fc19d3d46d2011d8b153f33d87643b17ae4.
Actual task revision11 and the isolated ee3 WSL runtime passed exact source,
configuration and startup checks. Fresh durable, Temporal and retained lease
evidence admitted only existing cancellation recovery. All16 reviewed queue/type
pairs had recent matching pollers before conflict-token promotion at01:18:23UTC.
No provider keys were delivered to the recovery workers; no new native creation
was requested.

One ingress wake of the existing cancellation produced actual incident
unit-in-doubt:72315d7e-49c6-53f9-a550-fdab4d44734a. Normal operator reconciliation
recorded abandon_unit decision e71f6a28-f770-4fbd-b621-dbc0f7c816e8 through the
public API (HTTP202, authority readback verified). The run06399516-e748-51f4-a766-00c377cabd17
reached terminal cancelled version13 at01:19:59UTC. Exact settlement is
cancelled/in_doubt_abandoned; reservations, pending effects and outstanding
usage are empty. Original create dispatch remains in_doubt, attempt1, with no
native session/turn identity. Usage remains UNKNOWN, not measured zero.
No provider_acknowledged milestone was manufactured.

Read-only post-abandon evidence joins the actual resolved incident/decision,
empty settlement usage, no native frames/sessions/turns, and retained original
workspace plus byte-identical115-byte dispatch ledger SHA256
5b95f7a2018d2fbd2ac39ba0c892d75454027773fa96084208b5d055c14b94a4.
The first retention capture failed before reading because WSL Python3.10 lacks
datetime.UTC; a separately retained one-line compatible successor passed.
Artifact-level operator provenance retrieval remains separate from this join.
Temporal metadata at01:20:38UTC showed no running workflows. Own-nonce cloud
shutdown verified desired/running/pending0 and no active tasks; the owned WSL
lane exited under its stop request. Its launcher exit241 represents child
SIGTERM(-15), not a successful ordinary exit. API remains temporarily bounded
for independent caller-delivery checks at this checkpoint.

This is actual uncertain-dispatch recovery proof, not successful Claude native
qualification or completion of the18-cell S0 matrix. Full3 human approval stays
complete. Caller wake, remaining controls/placements, S2/S3 and held S4 criteria
are not newly qualified by this recovery.


At01:24UTC, scoped read-only retrieval verified the actual result manifest
SHA256 ceb86292bd7e86f09eab034e0470aff759a83b0e5d0f80da7349113d46ab7100
and output payload b7c23606b997aa0ccd1db4f09ddc6a73b341ac89d2489b8988e44a2920c0c17a
from durable S3 custody against their persisted size/digest chain. Actual bytes
name the same incident/decision and explicitly record native_status unknown,
usage_disposition unknown and provider_acknowledged false. The earlier
artifact-level provenance limit is now resolved by this separate receipt.

The owned lane PID was independently absent. AWS budget's last published actual
remains$0.763 (forecast$1.52/$40, updated00:43UTC); this delayed budget reading is
not the final recovery bill. Historical221222 missing ledger tokens, the failed
Claude's unknown usage and retained storage/registry liabilities remain.
Polling the existing full3 inbox materialized and returned actual review and
terminal notifications. This is catch-up metadata, not proof of prior caller
resumption; real CLI delivery/handling remains under validation.


At01:26UTC the actual Windows Codex caller invoked the real CLI wait over the
existing full3 inbox and received terminal notification
706672c5-3ca3-5b8c-a6f8-b89e1ccf18aa, sequence5, canonical event
01a141dc-0f53-7de4-9a51-e34945e7425f. CLI exit0 and typed stdout were retained.
Root read that result and continued with a separate explicit acknowledgement.
HTTP200 and pending-page readback confirmed only that notification acknowledged;
five unrelated pending notifications were preserved and the contiguous
acknowledged cursor correctly remained0. The original helper's incorrect
cursor-equals5 expectation was caught before any acknowledgement call; a
separately reviewed successor passed realistic gap tests and performed one POST.
This establishes actual catch-up delivery and caller continuation for this
Windows Codex/Cloud path, not retrospective background wake or other callers.

The temporary API stopped by exact owned nonce; independent process/listener
absence now passes. Recovery cloud/base/lane/API compute is stopped. Existing
data, retained ambiguous workspace and immutable artifacts are preserved.
No main merge/push, ECS Exec, Linear publication or S4 release occurred.
## 2026-10-16 fresh ee3 Claude admission and Cursor C9 implementation

Fresh ee3 host attestation was captured and independently verified against the
existing installed runtime. The new `s0-claude-ee3-full1` manifest compiled;
normal owner verification returned HTTP 200 for both scoped A8 and M4, followed
by normal preflight `ready: true` at 01:49:04 UTC. This proves admission readiness,
not provider authentication, successful execution or full S0 qualification.
The final configuration contains 145 pinned public files; owner evidence stays
outside the worker image. Both temporary preliminary API processes were stopped
through their own stop nonces before image preparation.

The first observer invocation refused an output-directory mismatch before
writing observation evidence. Its failed receipt is retained. A byte-identical
reviewed observer was copied into the new preparation directory; a separately
reviewed wrapper changed only that path and unique output/receipt names. The
second capture and offline verifier passed with zero provider calls or sessions.
Final generation report SHA-256 is
`ddf0deefccc0a43defa572a47f8a06ff79833ba1b56a5f1e8a1521d84047fd0c`;
observation SHA-256 is
`ae3046a3dec1fba79be25812218437345993665cbc42b7871105762930054687`.
Private receipts remain under `claude-next-preparation/ee3-native-qualification`
in the retained resumed evidence directory.

Cursor C9 implementation has passed 43 focused tests, focused type/lint checks
and independent source review in a separate retained checkout. It binds selected
host admission evidence to the existing sealed Cursor configuration subset,
checks the actual repository commit and protected-root cleanup snapshots, and
refuses stale or mismatched evidence. It does not change canonical Cursor binding
fields or claim authentication/model entitlement. Actual host observation and
live Cursor qualification remain unrun; the canonical qualification source stays
ee3 while the fresh Claude probe is prepared.

## 2026-10-16 Claude native result and blocked Human Gate

The fresh ee3 probe actually admitted and started run
`0f609fde-238d-5bab-b59a-52d07289ea9d` on the WSL Claude lane with
Temporal Cloud/task13. Native session `2f9c63d1-71e4-458d-89e7-26ed1740faaa`
completed one turn and three tool calls. The immutable report candidate
`acb7a2ad-ec4c-530d-95d7-1a548c187465` was accepted and its S3 bytes were
independently retrieved: 1404 bytes, SHA256
`d0eaff962123e266535654a6435452b923a6ab57343200713face8d2824304d6`.
The report itself marks its evidence claims unknown; registration does not
turn those declarations into qualified controls.

Canonical settlement records 111507 input/cache tokens plus 1469 output,
112976 total, with no pending usage or reserved effects. Four deduplicated
independent native API-message observations total the same 112976. The native
file was removed after observation, so the watcher explicitly does not claim
an independently proven final tail; invoice cost remains unknown.

The probe exceeded its 20000-token ledger limit. Actual family history event37
then rejected the noncognitive review stage with `budget_hard_cap_exceeded`.
The family and root workflows failed with `stagegraph_blocked`, leaving the
public run projection active. No human REVIEW task was opened or approved.
The bounded controller submitted one cancel request
`81d239c3-9d32-4788-90a6-e3e736061ac2`; its delivery was rejected `stale_target`
while the durable projection remained cancelling version9. This is an unresolved
recovery liability, not terminal cancellation. Further provider work is stopped.

Both cloud and local owned workers were stopped and independently checked:
task13 desired/running/pending zero, no active cloud tasks, API/lane PIDs absent,
and the local API listener closed. The source fix must give Human Gates their
specified noncognitive admission and prevent failed budget admission from
leaving a live projection. No budget increase or global admission bypass has
been applied. S0 matrix acceptance remains incomplete.

Evidence remains in ignored `ee3-native-qualification/deployment-window2`,
`durable-report-window2`, and
`durable-window2-readonly-1792118418757956700.sanitized.json` (SHA256
`ed23d9eda56f39fa182697bd5912b7483358a1eb827b9bfd958b66b959190393`).
The two first-window launch refusals occurred before admission and all their
workers were stopped; the next window preserved its separate failed readiness
and default-plan attempts before its single actual controller execution.

Read-only inspection retained 54 kernel hook invocation/result facts. The exact
force-push canary reached PreToolUse, where the recorded kernel callbacks allowed
it. These callbacks are separate from the catalog policy script in the projected
settings; its denial is not proven by these facts. The seven unknown frames are
`system.thinking_tokens`, not missing hook-result mappings. Tool-denial acceptance
remains open. Sanitized receipts are `window2-hook-facts-1792119299216334400`
(SHA256 `fc304a7ee9ee49df197c05e0ba927e688c96c89b251a7fb458bf82c166df3dd0`)
and `window2-hook-facts-v2-1792119433066544500`
(SHA256 `3b597ceffa05cccd7c9c295c7e5afd0e69a1ee23ba74b7e028e2ec73fba6dbfa`),
both `.sanitized.json` under the same qualification evidence directory.

A subsequent bounded read of the native failed-tool result narrows that gap:
frame `01a1428e-a8ff-77f0-a46c-cdc8b4b5806b`, ordinal48, names the same
`toolu_01CGfsepDYP8sMx1su63C7om` as the exact canary callbacks and contains
`PreToolUse` plus the policy's exact reason, `policy: force push is forbidden`.
It does not contain the ordinary Git repository-failure marker. This is actual
native tool-result corroboration of denial for this attempt, distinct from the
kernel callbacks' allow decisions and from a separately captured policy-script
receipt. Sanitized v3 receipt SHA256 is
`18d591bb5d63cebdd206fac221607beeb7550f967fe4f74aeadbdc79b795de4c`;
no new provider action occurred. Full control and placement qualification remains
incomplete.

The noncognitive Human Gate repair is now locally integrated at
`0b964858711f599b81d0b5dc4eececa5e92fb134`, following the Cursor C9 readiness
implementation at `b4091222`. It verifies the committed manifest, immutable
operation template, selected configuration and exact reviewer policy before
atomic admission, with no cognitive reservation. Existing pauses, waits and
cancellation still constrain admission; ordinary cognition remains budget-bound.
Fork-derived bindings explicitly retain legacy admission behavior and are not
qualified by this repair.

The isolated gate patch passed 154 focused unit tests, 12 architecture checks,
11-file authoritative typing, 31 historical replays and all three actual Window2
histories. Its real PostgreSQL test persisted gate admission and review-result
acceptance across repository reconstruction. The fresh tmpfs database was removed
and absence verified; no existing database was accessed. Normal commit hooks
passed after pointing the isolated checkout at the existing tooling environment;
an explicit ty run checked 808 files with 11 existing warnings. These are source
and offline proofs: the new build is not deployed, the stranded run is not yet
recovered, and ordinary cognitive admission-denial terminalization is a separate
repair in progress. The integrated C9, gate-regression and architecture selection
also passed 80 tests with one dependency deprecation warning.

## Earlier implementation and recovery evidence

Date: 2026-10-14. **The end-to-end mission is not accepted or live-qualified.** This
report records an offline implementation checkpoint and the remaining work. It does
not change issue acceptance, weaken prerequisites or release funding-gated scope.

The first bounded e309 recovery attempt failed before the local lane process was
created because C: had zero free bytes. Independent inspection confirmed that no
new native turn started and the retained rollout was unchanged. At 19:35 UTC,
AWS task 7 was returned to desired/running/pending zero with no active tasks; the
exact local API process was stopped. Shutdown evidence was emitted to tool output
while storage was full and transcribed into an explicitly marked private receipt
after space returned. This did not settle the run or alter its ledger.

The owner cleared temporary files and authorized minimal cache cleanup. Normal
`pnpm store prune` removed unreferenced cache entries, reporting 27,522 files,
461 packages and 1.6 GB removed; C: then had 7.24 GiB free. Database volumes,
native sessions, source archives and runtime evidence were preserved. Fresh
Temporal and database inspections still found only the exact pending cancellation
on the existing e309 build. The second recovery used that retained session and the
same 600-second lane bound; it admitted no new mission or native turn.

The second recovery completed normal settlement at 20:05:58 UTC and reached
terminal version 9, outcome `cancelled`, at 20:06:05. The ledger records
137,425 input + 9,533 output = **146,958 tokens**, matching both persisted native
attribution and the previously retained independent native rollout. No unknown
native turns, outstanding usage, reservations or pending effects remain. The
harness is ended with no open turn; history replay closed the original turn
without another create/send dispatch. This is a cancellation/recovery proof,
not S0 acceptance. Terminal audit SHA-256:
`368e9f7cc3ad070072136aabd53df0ed48833d37a22bcee16c39350a6391eba5`.
The exact local worker was stopped at 20:06:47 with no remaining owned processes.
AWS shutdown at 20:06:52 verified desired/running/pending zero and no active tasks.

## 2026-10-15 full S0 attempt: native proof, cancelled with settlement pending

Source `e309c58e9889fc050dd418067930578414b4239b` passed source/runtime
attestation, fresh API-key authentication, normal owner prerequisite verification
and all 16 matching Temporal queue/poller checks. AWS task revision 7 used image
`sha256:89ce3d9d7e052cc65be538e6f9247a0721661868361a06a98ea9926bc645b652`.
The full S0 run was `f260cfb5-3b6c-5b6b-a275-043437d854f8`, native session
`01a140e7-5690-7fe0-a273-0ef07b9883fd`, model `gpt-6-luna`.

Independent native rollout evidence confirms the full stage instruction arrived,
the corrected authenticated `missionctl` inspection returned the actual run, and
the harmless force-push canary received a native PreToolUse hook denial. The first
inspection failed because `jq` was missing; it was not an observer-credential
failure. Six tool calls occurred. No report-write attempt, output file, immutable
report custody, human REVIEW or caller-wakeup proof was established. Catalog-hook
denial does not establish kernel tool-family blacklist enforcement.

At 18:53:06 UTC the controller's five-second inspection read timed out. Its next
inspection succeeded in 3.618 seconds, found active execution with no open REVIEW,
and the controller issued one normal cancellation. The native rollout records
`turn_aborted` / `interrupted` at **18:53:35.067 UTC**; the durable provider
acknowledgement followed at 18:53:35.077814. No later native records were found.
Final independent native usage was **137,425 input + 9,533 output = 146,958 tokens**.
The declared 100,000-token ledger limit was not a provider hard cap. The native
evidence receipt SHA-256 is
`e86b596518cf02c6fb2a48d85aebef364ef491d1fe4f86a98b74f3727b46b373`.

Durable settlement did not finish before the 900-second worker lease ended.
The 19:02:44 audit still showed cancelling version 5, one reservation and one
pending effect, with no final ledger equality claim. Audit SHA-256:
`1b7867ec24b4a283ba45f58c386d75cff4a79795a548ae9b4b9e0df353a97703`.
Cursor readbacks showed progress through already-persisted frames during the
cancellation drain. Source inspection identified a requested-cancellation branch
that skips the normal segment cursor flush. This remains a recovery liability;
native cancellation alone does not establish terminal settlement.

Both local leases stopped at their bounds. Independent PID/start-time and
lease-directory checks at 19:03:35 found the API, worker and all three native child
processes absent. The workspace and native rollout remain retained for recovery.
AWS shutdown readback at 19:03:18 found desired/running/pending counts zero and no
active tasks. Retained storage and secrets may still incur charges. The conditional
public-rate token estimate is $0.0913132, reserved as $0.10; cumulative diagnostic
planning reserves are $0.35, not invoice costs. No automatic paid retry was issued.

A private controller successor tolerates at most two consecutive read-only
timeouts within its original deadline, preserving at-most-once writes and the
human REVIEW guard. Nine offline transport scenarios passed. This is controller
validation, not live S0 qualification. The mission remains incomplete.

The requested-cancellation cursor repair passed 68 focused unit tests and one real
PostgreSQL ownership regression; the disposable databases and roles were removed.
It saves only successfully persisted progress and checks ownership atomically
inside the existing state-store lock before updating the cursor. Takeover, no
progress, nonrequested cancellation and unknown-usage cases are covered. Source
mypy, Ruff and independent review passed. This repair was not installed into the
live e309 run; no live claim is inferred from these tests.


## 2026-10-15 stage instruction and terminal lifecycle live evidence

Integrated source `3e9129473c3b12041aee4ef0df0399ee38c1268b` passed source-image
and native-runtime verification, fresh native API authentication, normal owner
prerequisite verification, and all 16 matching Temporal queue/poller checks.
AWS task revision 6 ran immutable image
`sha256:9328f63505652caaa6b868b58860240203f7aa9144bdb44c501a24f8b45fbf6f`.
Run `22452c1a-7a40-5e19-9e3e-0c8263c8fb34` received the exact authored stage
instruction in its original native user-message frames. Its replacement turn
received the injected instruction in the same native thread. One native tool
call started and completed. No callback-error frames were found in the scoped
durable observation. These are actual integrated-path receipts, not fixture claims.

The diagnostic controller ended with a read timeout. Injection was observed, but
the controller did not complete its replacement-usage check before its deadline.
Normal cancellation settled the mission at 18:08:08 UTC: cancelled, version 9,
**77,354 input + 2,070 output = 79,424 tokens**, no reservations or pending effects,
and the harness correctly **ended** with no open turn. Persisted native attribution
and the ledger agree; independent native rollout totals were unavailable after
normal workspace cleanup. No durable provider-cancellation acknowledgement was
recorded. Terminal settlement must not be relabelled as native cancellation proof.
The terminal audit SHA-256 is
`79f3d1310cace18f2ce254bb945ba1d9b9a41ff01d5ab6e5056039d0af53826d`;
the instruction/turn observation SHA-256 is
`bae8f353eeca269a3ea3a9fc1334a8c61500df3475754410c68e5592e94d6ae6`.

AWS shutdown readback at 18:09:47 UTC found desired/running/pending counts zero
and no active tasks. The exact local API and lane worker were stopped; independent
PID/start-time checks found all recorded native processes absent. The conditional
public-rate token estimate is $0.0459602, reserved as $0.05; cumulative diagnostic
planning reserves are $0.25, not invoice costs. AWS separately reported $0.685
actual/$1.463 forecast with delayed billing data. Historical accounting liability
and retained resource costs remain visible. Full S0, human REVIEW by the selected
owner `johnoverton743@gmail.com`, and remaining acceptance rows are still unrun.

Full-S0 preparation identified a separate credential-delivery boundary: passing
an agent-phase alias into the app-server environment does not prove that native
model tools receive it. A pinned 0.162.1 synthetic probe of `command/exec` and
`thread/shellCommand`, without inference, verified a names-only exact environment
allowlist. Observer aliases arrived; provider and unrelated credentials did not;
generated files contained no sentinel secret values. The repair pairs native
default-filter replacement with a mandatory allowlist of safe platform variables
and explicitly delivered agent-phase aliases. MCP-only credentials remain excluded
from shell tools. Delivered values also join launcher stderr redaction. Actual
model-tool credential visibility remains a live full-S0 criterion, not a claim
established by these direct command RPC probes.

The repair passed 76 focused Codex tests; the final inheritance-policy change
passed the nine-test focused selection. Source mypy and Ruff passed. Independent
review confirmed that MCP-only credentials remain excluded and no secret values
enter launch arguments. These overlapping test selections are not added together.

## 2026-10-15 repaired-build diagnostic and complete token settlement

Source `d4476f50acadc7654ee4fd88f205871ae50c7a95` passed source/runtime
attestation, fresh native API-auth prerequisite verification, and matching
versioned poller checks. AWS task revision 5 used immutable image digest
`sha256:450395288aee85a868b50571d2f54838aed9039e6549d6abd3d9ca230a68d7eb`.
The bounded diagnostic admitted run `9f474aab-6e21-5ab1-be8b-4a8eb81822cd`.
It did not complete the requested replacement-turn proof: the controller reached
its deadline and issued normal cancellation; the injection expired with no
acknowledged replacement turn. This is not S0 acceptance.

The native rollout, persisted attributable usage, and final settlement agree on
**71,488 input + 1,842 output = 73,330 tokens**. Raw and companion usage records
were not added together. The terminal read-only audit found cancelled outcome,
version 9, no reservations, no unsettled effects, no outstanding usage, and only
zero amounts in pending settlement. Its SHA-256 is
`799ef29034ce9a4b28b9380f785166e02e935d8b8d9aa765b75d212b0e8df484`.
This validates this run's token accounting; exact billed dollars remain unknown
and the earlier 244,489-token run's historical undercount remains unresolved.

The first audit at 17:24:55 UTC still showed cancellation pending. Normal retry
settled the operation at 17:26:10; operation, family and root workflows completed
by 17:26:19. That delay is retained as a cancellation-performance defect, not
rewritten as immediate settlement. The terminal audit still labels the harness
as live despite its closed session and terminal mission; that projection defect
is retained separately from settled accounting. AWS shutdown verified desired, running
and pending counts zero with no active tasks. The exact owned local API and lane
worker were stopped; independent process inspection found no remaining owned
native processes. Retained storage, images, logs and secrets can still incur costs.

The diagnostic also exposed missing authored stage input: the manifest retained
its instruction, but production template construction emitted only the goal
objective. Native read its context and operating contract; neither supplied the
missing stage text. The empty privileged operating contract itself is not an
authority defect: manifest stage text must reach the admitted user-input channel
without being promoted to a published instruction. The repair now adds a separate
admitted-input segment before immutable operation binding. Its exact text and
provenance affect the operation fingerprint; privileged asset digests stay unchanged.
Provider, Cursor and deep-agent stage paths share this behavior. The authoring,
context-handoff and authority selection passed 138 tests; the added operation
fingerprint regression also passed.

Cancellation now reuses an exact durable Codex terminal record after owner and
current-state checks, while ordinary usage validation retains unknown liabilities.
Frame registration preserves ended lifecycle for the same or stale generation;
real new turns and higher generations can reopen it. All eight real PostgreSQL
lifecycle tests passed with no retained test databases or roles. The final cancellation
selection passed 46 tests; scoped authoritative mypy and Ruff passed. Independent
reviews found no blocking defect in either repair. These offline results do not
retroactively change the diagnostic's immutable inputs or historical projection.

A dedicated observer identity was provisioned with tenant-scoped run-read access
only and verified through genuine Supabase authentication and the normal CLI.
The diagnostic worker received no observer token. Human REVIEW remains reserved
for the owner's selected existing account and has not occurred. Private receipts
remain under `run2/resumed/s0-observer-auth/`, `s0-launch-binding/`,
`base-worker-closure/` and `aws-resources/`; they are excluded from source commits.

## 2026-10-15 offline repair of native observation and accounting

The repair against `64da4cc739fcdcd4cf4b4c956164ef3275a1fc1c` is offline-tested.
Frame append now assigns a collision-free ordinal range under the existing
execution-row lock, preserving generation fencing and provider-key deduplication.
The real PostgreSQL contention reproduction originally exhausted retries for
8 of 12 writers; the repaired selection passed 13 PostgreSQL/writer tests.

Session projection reopens an identified replacement turn and prevents delayed
old results from closing it. Turn usage retains permitted child usage within
the original root-turn window without inheriting replacement children. All six
focused PostgreSQL lifecycle tests passed in 13.93 seconds. Disposable database
and role inventories showed no retained test resources.

Codex accounting now uses attributable cumulative counter differences, preserves
raw native events, and persists separate provenance-bearing usage observations.
Settlement includes all turns of the semantic attempt, including interrupted
predecessors. Missing baselines, incomplete terminal tails, regressions or
contradictory evidence retain unknown consumption and its unsettled claim.
Cancellation drains a bounded terminal tail before cleanup and rechecks ownership.
Context occupancy continues to use the provider's per-call counter.

The full Codex unit selection passed 162 tests; the harness/frame/runtime selection
passed 491 tests in 212.87 seconds, including the added accounting negatives.
Scoped Ruff checks and authoritative mypy passed for all eight changed production
files. Independent reviews found no remaining blocking accounting or ordinal
issue. The PostgreSQL lifecycle receipt digest is
`sha256:9123ca5ef35bc473ab3b41e2d3baeaff4e3ac38928649e608a44a5b3292d1540`.

These checks do not repair the already-terminal historical ledger, establish its
dollar cost, or qualify the repaired build live. The discrepancy below remains
recorded; no direct database correction, terminal reopening or further paid
probe was performed during this repair. Paid workers remain stopped.

## 2026-10-15 native Codex probe and accounting discrepancy

Source `64da4cc739fcdcd4cf4b4c956164ef3275a1fc1c` was built and verified
on AWS and WSL. The operator image passed the credential scan and nonroot smoke
check; task revision 4 used immutable ECR digest
`sha256:ca5ea15dea8e0166bbb2ff29ab351dc567e5e2855e16443bffee97d3bffa0db7`.
Fresh native API-auth observations and normal prerequisite verification passed.
All 16 recent versioned poller pairs matched before guarded Temporal promotion.
These are build/readiness observations, not S0 acceptance.

Normal CLI submission and start admitted run
`5d530048-41f4-59fd-820c-f54ee6e73bc1`. A real native Codex session executed
an original turn and an interrupt-and-inject replacement. Concurrent hook and
lane frame writers encountered `FrameOrdinalConflict`; the original errors are
retained. The bounded controller issued normal immediate cancellation. The run
reached terminal `cancelled`, version 9, and both Temporal root and family
completed at 15:43:51 UTC. Readback found no remaining reservations, nonzero
pending usage or unsettled effects. Harness-scoped inspection found 282 persisted
frames. Its database execution run ID differs from the public mission run key;
the initial public-ID frame query therefore missed actual provider activity.

Terminal accounting is materially incomplete despite those empty pending maps.
The settlement recorded 22,564 input and 703 output tokens, totaling 23,267:
exactly the final model call. The retained native rollout records 12 calls,
241,511 input and 2,978 output tokens, totaling **244,489**. The original turn
used 15,667 and the replacement used 228,822. The missing 221,222 tokens match
the preceding persisted cumulative native counter. Duplicate rollout reporting
was not summed. The Codex adapter used `last` (one model call) for accounting;
that counter is appropriate for context occupancy, not total consumption.
Actual dollar cost remains unknown. The authored 20,000-token ledger limit was
not a hard provider spending cap and did not prevent this overage. No further
paid probe is authorized by an assumption of zero or fully settled cost.

AWS shutdown verified desired/running/pending counts of zero and no active tasks.
The exact owned WSL worker was stopped; process inspection found no remaining
owned worker or native app-server processes. The loopback operator API was also
stopped. Retained storage, logs, images and secrets remain possible charges.
Native control evidence, frame persistence and accounting need repair/review;
no human REVIEW or S0 qualification is claimed.

Private references under `run2/resumed/` include the controller journal in
`s0-launch-binding/control-attempt-source-64da4-control1/`, the exact-handle and
usage-audit receipts in `base-worker-closure/`, the native usage comparison and
owned-worker shutdown receipts in `s0-host-binding/revisions/64da4cc739fc/`,
and `aws-resources/shutdown-task4-observation-closed.sanitized.json`.

## 2026-10-15 cancellation recovery and reviewed rejection repair

The rejection repair is committed as `64da4cc739fcdcd4cf4b4c956164ef3275a1fc1c`.
Final verification passed 58 focused tests, two disposable PostgreSQL crash tests,
scoped authoritative mypy, and all commit hooks. Independent review found no
remaining actionable issue. Main and local origin/main were not changed or pushed.

Normal cancellation continuation preserved the original operator attempt identity
and explicitly selected the scoped S3 credentials. It completed settlement, but
its final helper guard incorrectly rejected a pending-usage map containing only
zero amounts. No cancellation retry followed. Separate read-only verification
matched the cancelled claim, effect, journal, lineage result, immutable S3 manifest
and empty output payload; the reservation was fully released. The original failed
checks remain retained. The acknowledgement is the service's before-dispatch
classification, not a native provider RPC or S0 control qualification.

One bounded 120-second task-3 base-worker window let the existing family retry
consume that settlement. Run `03021545-55f4-52de-ba80-8d13ecc89bf8` became terminal
`cancelled`, version 9; its root and family workflows completed at 15:30:06 UTC.
There were no remaining reservations, nonzero pending usage, outstanding usage,
unsettled effects, active waits or children. The window then verified desired,
running and pending compute counts of zero with no active tasks.

Private recovery references under `run2/resumed/base-worker-closure/` are
`normal-cancel-authoritative-verification-1792078062833458700.json` and
`base-reconciliation-state-readonly-1792078234173132900.json`. The bounded compute
receipt is `run2/resumed/aws-resources/task3-reconciliation-window.sanitized.json`.
These supersede the earlier cancelling-state observations below.

## 2026-10-15 repaired build and pre-provider rejection

The subsequent operator cancellation attempt passed immutable-runtime and
read-only state checks, then stopped with `ProfileNotFound` while using the
normal cancellation service. Readback found a partial normal transition:
version 5, one claimed effect and operator-origin lineage, the reservation still
held, and no usage or settlement. This is not a successful cleanup or a native
provider acknowledgement. The original attempt and its receipts remain retained;
continuation must validate that exact partial state and preserve its identity.
The private runner removed `AWS_PROFILE`, which exposed the Settings default
named profile. Its repair must explicitly select environment credentials and
verify S3 access before continuing settlement. No direct SQL repair is used.

The narrow source repair settles only an explicit lane qualification rejection
before any durable harness execution exists. A distinct authority command
competes for the same effect identity as normal dispatch, so prior dispatch,
unknown usage and conflicting authority retain their liabilities. Exact replay
recovers the persisted rejection timestamp and its own accepted settlement;
it does not require a second reservation after the first settlement released it.
The initial focused regression selection passed 58 tests. Independent review
found no actionable defects, and scoped authoritative mypy passed after a local
variable rename. Two PostgreSQL crash-recovery cases passed on the authorized
disposable PG17 fixture, covering authority-before-claim-journal and
authority-settlement-before-settlement-journal failures. Reconstructed
coordinators preserved the original timestamp, refused normal dispatch, and
recorded one failed receipt and one full release. No new fixture databases or
roles remained afterward.

Source `70424b48417fb48e1102b0746d08bcd6f12e9e96` was built and attested on
both hosts. The operator image passed the credential scan and nonroot offline
smoke check, and was published as ECR digest
`sha256:5e281ee68c47e31de3d66cffaf75422b517a9aadde959868e5974d7e19b5b03d`.
AWS task revision 3 changed only the image and build ID from revision 2. Fresh
native metadata and ephemeral API-login observations started no thread or turn;
all three normal API prerequisite verifications passed and preflight was ready.
The first queue inspection preceded complete base-worker registration and refused
promotion. A subsequent inspection found all 16 matching recent versioned
poller pairs, and guarded promotion read back `0.1.0-70424b48417f` as current.

Resubmitting the unchanged S0 manifest correctly returned its existing failed
run. Start and cancellation were refused for that terminal run; it stayed at
version 3. The private controller now inspects every admitted run before start
and refuses an unchanged fresh submission. A distinct mission key, with only the
key and title changed, admitted run `03021545-55f4-52de-ba80-8d13ecc89bf8`.
Its pending state was verified before normal start at 14:48 UTC.

That run reached the WSL `lane.turn` activity, getting past the previous S3
failure. The lane refused execution with `LaneNotQualified` before creating a
native session: the bounded local proof launcher had omitted the documented
local-proof opt-in. No Codex app-server process, session, frame or provider turn
was observed. No qualification record was changed. A private launcher correction
is prepared but has not been executed.

The rejected operation exposed a separate accounting defect: its family-admitted
binding and reservation remained unsettled after the operation child failed.
`stagegraph.decide_result` correctly refused to apply a result without authoritative
settlement. Normal immediate cancellation was accepted at version 4 and persisted
a stop fence, but the run remains `cancelling`; neither a native acknowledgement
nor terminal settlement is claimed. Restricted readback found one reservation,
holding one concurrency slot and one operation attempt, with zero usage records,
effects, claims, asynchronous children and accepted operation settlements.

The 900-second WSL worker stopped and an actual process check found its PID absent
and zero native Codex processes. AWS was scaled to zero, with desired, running and
pending counts zero and no active tasks. This is compute shutdown, not run
terminalization. The existing cancellation-service recovery and a narrow
pre-dispatch rejection repair remain in preparation. No direct SQL cleanup,
invented zero-usage settlement, acceptance or paid retry has occurred.

Private receipts are retained under `run2/resumed/`, including
`s0-launch-binding/control-attempt-source-70424-{first,new-mission}/`,
`s0-host-binding/revisions/70424b48417f/`, `aws-resources/`, and
`base-worker-closure/rejected-operation-state-readonly-1792075984500464900.json`.
The latest AWS budget read reports account-wide month-to-date spend of $0.639,
updated by AWS at 06:05 UTC and observed at 14:29 UTC. It is delayed, excludes
provider charges, and is not a remaining-spend guarantee.

## 2026-10-15 live startup and first admitted probe

The owner selected the main account for human REVIEW; a read-only Supabase Auth
lookup confirmed the existing subject already used in the S0 manifest. No REVIEW
decision was made. The earlier owner identity-selection question is resolved.

Source `1dc6852eae9e3485b40b9d56f35f142f3fc82a1d` reached actual AWS and WSL
worker startup. The immutable ECR image digest is
`sha256:3f8c4890194375d4c7c0075d10536c114cac06b0d432da706571154426115819`.
Task revision 1 failed because hosted providers were enabled without their signal
ingress binding. Revision 2 disables only those two provider opt-ins for the
Codex-only configuration. Fifteen base queue/type pairs and the WSL lane's
sixteenth pair had matching recent versioned pollers; guarded Temporal promotion
read back build `0.1.0-1dc6852eae9e` as current. This does not qualify the hosted
providers. The service remains one 0.5-vCPU/2-GiB task with zero inbound ports.

Private preparation failures are retained: the installed AWS CLI rejected the AZ
rebalancing field before service creation; the supported SDK created the service
once, then a comparison falsely rejected reordered subnet IDs. Read-only set
comparison confirmed the unchanged network. The WSL launcher needed the explicit
execution-enable flag and correction of its child exit-code propagation. A later
runtime-byte verification exceeded 180 seconds; only its timeout was raised to
600 seconds, after which verification passed. The worker lifetime stayed bounded
at 900 seconds. The deprecated enhanced Temporal query was replaced with the
default query that exposes the actual deployment/build/versioned poller identity.

Normal API prerequisite verification was renewed without inference. The first
submission was denied for missing sponsorship; restricted readback proved zero
orphan records. A scoped operator configuration added the launcher's sponsorship.
The next submission admitted run `7f0b5f90-92cc-54bc-81d8-01717a0a4756`.
The private controller initially misparsed the successful public CLI envelope;
the receipt was preserved, the existing pending run was inspected, and it was
started without resubmission at 14:06 UTC.

Both Temporal workflows subsequently failed during context-pack staging with
`ProfileNotFound`: the SDK treated `AWS_PROFILE=''` as an explicit empty profile.
This happened before native provider execution. The immediate-cancel attempt was
denied because the launcher lacks `workflow_run.admin`; no cancellation
acknowledgement is claimed. Restricted runtime readback found no reservations,
usage records, effects, asynchronous children, accepted operations or outputs.
The WSL worker was stopped and a fresh process check found no Mission Control
worker or Codex app-server process. One guarded `TerminalizeAction` through the
normal run-control service reconciled the database projection from version 2 to
version 3, terminal outcome `failed`. Exact failure evidence, empty liabilities
and compare-and-swap checks passed; command and projection readback agreed. No
direct SQL status edit, additional cancellation grant or acceptance occurred.

The S3 repair ignores only empty profile environment values in a session-local
SDK resolver. Explicit named settings profiles and nonempty ambient profiles,
including SDK precedence, remain supported without mutating the process
environment. Seven focused offline tests, Ruff and adapter mypy passed; the lock
adds the already resolved aiobotocore dependency without changing versions.
The repaired source still requires a new immutable build and live qualification.

Actual receipts remain ignored under this sprint's `run2/resumed/` directory:
`aws-resources/`, `base-worker-closure/`, `s0-host-binding/revisions/1dc6852eae9e/`,
`s0-sponsorship/`, and `s0-launch-binding/control-{attempt,resume-attempt}/`.
The exact reconciliation receipt is
`base-worker-closure/failed-s0-terminalization-execution.json`.
The first S0 probe has not passed; no immutable mission report, native control
acknowledgement, human acceptance, full matrix qualification or settled provider
cost is claimed. Historical checkpoints below retain their original scope.

## Earlier checkpoint: verified live release and supporting infrastructure

The owner authorized infrastructure/authentication setup and approved the exact
AI Engineer 1.3.0 to 1.4.2 plan after a verified recovery point. That condition is
satisfied. A consistent, private PG17 export of the three common schemas was
restored into a fresh disposable database: all 146 tables/417 rows, sequences,
schema fingerprints, owners and effective permissions matched. Ten raw ACL
representations normalized from explicit owner defaults to equivalent implicit
defaults; this was checked and retained. The archive SHA256 is
`07c51d1f9c516f219701baea44a6c2cc99f25ea6dcce8aafb63e9a40e2bd0530`.
The recovery reference is the ignored `run2/resumed/recovery-point/manifest.json`
under this sprint's `.scratch` directory. This is scoped logical recovery, not PITR.
The disposable database was removed and the original database/role inventory preserved.

The exact previously reviewed plan digest `sha256:f29ea141f6c3cf2786d1e09a45e58686e85e23a6b1699ca60c45175822b2609a`
was revalidated and applied on 2026-10-15 UTC. Independent verification confirms
AI Engineer 1.4.2, all 37 migration receipts and fingerprint
`sha256:1d6dcd1a96b44b7c3635ffd34cec7703703160b04bf52c24643157c72a472cc3`.
Protected comparison permits exactly the new NOLOGIN ingress role and its
ADMIN-only creator membership; zero other protected changes occurred. Runtime
persistence was already complete and needed no mutation. The tracked AI Engineer
lock now locates the immutable 1.4.2 release; Biotech remains unchanged.
Private apply, verification and comparison receipts are retained in `resumed/live-apply-142/`.

AWS stack `mission-control-ai-engineer-run2` completed its exact 16-resource
CREATE plan in account `298199649527`, region `us-east-1`. Readback confirms the
immutable ECR repository, private encrypted payload bucket, restricted IAM roles,
seven empty secrets, zero-inbound security group, 14-day logs, FARGATE cluster
and $40 monthly alerts. There are no worker tasks/services or local-user access
keys at this checkpoint. The budget remains an alert, not a spending cap.
Vercel project `mission-control-ingress` was created in `overtons-projects` with
FastAPI/Fluid settings; 102 source files were staged from `69a18960ad7f` without
credentials. No ingress deployment or paid provider execution is claimed yet.
Restricted credentials and final runtime configuration remain in preparation.
Supabase issuer trust is now authorized; selecting the actual existing human
reviewer is still required. Routine scoped policy preparation has been completed.

The subsequent credential phase is complete. Three distinct worker LOGINs and one
ingress LOGIN passed certificate/hostname verification, exact capability membership,
non-elevation and ownership checks. Runtime/family installation readiness, checkpoint
readiness and session-pooler LISTEN/NOTIFY passed. The ingress role can execute its
seven functions and cannot SELECT the credential table. The public Supabase CA was
obtained through its maintained dashboard source and independently verified; no
global trust setting or verification bypass was introduced. Seven AWS secrets and
four production-only Vercel variables hold the intended configuration.

AWS automatically attached AWSCURRENT to the first explicitly pending secret, causing
the first role transaction to roll back. AWS then rejected removing AWSCURRENT without
another version. Both failures were retained. The corrected reviewed sequence reused
that exact credential/version, required zero compute while credentials were provisional,
and removed pending markers only after all role/readiness checks passed. No password
rotation or dummy version was used; no worker service is running.

Nine pending production seed bundles applied and verified: 37 asset versions,
37 asset decisions and 24 plugin memberships. All 21 production bundles now report
replay; exact record checks passed and existing receipts/installation identity are
unchanged. No tenant, human grant, provider execution or Biotech write is implied.
The first ingress build produced a 21.4 MB function in iad1, but startup failed because
its thin dependency list omitted PyYAML. The failed deployment/logs are retained;
dependency repair and a declared-import regression check are in progress.

That repair is integrated at `b762a31a2df6df08da5d8718ee138d3a702c9e0c`:
PyYAML 6.0.3 is pinned in the slim lock and the vendor step rejects undeclared
external imports. The regression check passed, and all 97 closure modules imported
in an isolated frozen slim environment. Replacement deployment
`dpl_CcirMUUT69bkwNhWy7RsMuvJKw54` passed startup and was promoted to
`https://mission-control-ingress.vercel.app`. Unauthenticated public checks returned
200 with the expected liveness body and 401/missing_credential for mission-request
status. Default deployment protection remains enabled; no bypass secret is used in
the public origin. The CLI generated its project-scoped automation bypass for the
protected deployment's startup test; it was not placed in any provider URL.
These checks prove ingress startup/authentication refusal, not admitted remote missions,
provider callbacks, artifact custody or the latency distribution.

Owner identity was resolved by exact email equality between the authenticated
`overton77` Vercel identity in the selected team and exactly one existing Supabase
user. The private correlation receipt retains the matched subject; the human's
review decision remains outstanding until an actual output exists.

Owner onboarding then completed with one active tenant, the matched human binding,
and seven scoped launch/read/control grants. Existing Supabase metadata was preserved.
The proof configuration uses the verified public ES256 issuer/JWKS; static transport
grants do not inherit database expiry, so they must be retired with the proof runtime.
No human session was manufactured and no REVIEW was resolved.

The normal control-plane publisher verified the actual observation skill revision 3
and report schema revision 1, then published `agent-profile.local-codex` revision 1
and six linked S0 definitions. The effective configuration digest is
`sha256:cb8e9477887b0c04bb89ca14aa950c7dd45db559d8acc0de337b4b9f1ee6d644`.
All seven returned references were read back. This creates no run or provider execution.
Production bundle custody materialized 96 immutable local objects; an independent
readback verified all 96, with zero new objects and no seed drift. Identical bundle
bytes can be packaged for each host without new storage credentials.

The existing bucket-only IAM user now has one task-private credential. Current-user-only
Windows ACLs protect its separate credentials file; global AWS configuration was not
changed. Initial verification immediately after key creation failed with a client error;
the same retained key subsequently authenticated as the exact expected IAM user.
A restricted S3 put/get/list/delete round trip passed and the fresh probe object is
verified absent. The key remains a retained operational credential, not cleanup success.

A new noneditable WSL environment was installed from the frozen lock and preserved
root wheel, leaving the previous environments untouched. Python 3.12.11 imports the
worker from the new environment; source inputs remained unchanged. Wheel SHA256:
`0c6f5f9747db6ce884a87ae3e97e5588300c741a8c81b18a0f40f7a432e2cd60`.
Native distribution attestation and full runtime configuration are still in progress.
No base worker, lane worker or paid S0 run is claimed at this checkpoint.

The explicitly machine-owned S0 launcher was then provisioned with one service
binding and seven scoped grants, independently read back. Its random password is
held in AWS Secrets Manager; genuine Supabase password sign-in and pinned-JWKS
verification passed. Access/refresh tokens were not persisted, no email was sent,
and the machine has no human-review authority. A bounded loopback API launcher is
prepared with process-only secrets and separate restricted S3 credential custody.

Actual operator configuration exposed a Codex-only launch dependency on an unused
Deep Agents scaffold. The narrow repair allows v2 provider bindings to omit it;
v1 and any actual Deep Agents launch still require it. Present-scaffold serialized
content remains unchanged. Independent review passed, the affected launch/deployment
suite passed 88 tests, operator/readiness tests passed 29, and authoritative mypy
passed both changed source files. Ruff lint and formatting passed all five code files.
The AWS renderer also fixes and validates the two local bundle-custody settings.
Runtime artifacts must be rebuilt from this repair before the live probe; the earlier
WSL/image receipts remain preserved and are not evidence for the repaired build.

Native Codex 0.162.1 probing then showed that the configured API key alone does not
authenticate app-server. The isolated API-key route now uses its supported account
login RPC with ephemeral credential storage before hooks or threads. The probe
confirmed API-key account type and no `auth.json`; it did not execute inference.
Login failure or lost response terminates the process with a sanitized typed error,
and the selected key is redacted from stderr before retention/logging. Owner ChatGPT
authentication is unchanged. Independent review passed. The full Codex selection
passed 147 tests and exposed three stale handshake-order assertions; those three
were corrected and passed on targeted rerun. Mypy passed all three changed source
files. This is not a new broad-suite claim.

The first full API startup refused a missing trusted catalog scope. After adding the
actual installation scope to public configuration and the validated AWS task plan,
all three environment-tamper cases passed. The bounded loopback API returned ready
with `production_common`, component 1.4.2 and launch configuration present. Genuine
machine-authenticated CLI compilation of the S0 Codex manifest passed with zero
blockers/warnings and the actual published observation skill. This preliminary
configuration is not eligible for final image promotion. No mission was submitted,
no provider turn ran, and human REVIEW remains unresolved.

Commit `6a9b2d4d246b13a07fc8dc1ca8fec7f4519969d3` then produced a verified
source image and a fresh WSL wheel. A WSL service timeout interrupted the first
installation after dependency synchronization; source hashes matched independently,
and the remaining wheel/install/import steps resumed without repeating that sync.
The native wheel SHA256 is `346f5e747dc04546b3533d8800f6bf1bf4a103551c64b807b73d72260d913b57`.
The final configuration API again reported production readiness. A single read-only
OpenAI model retrieval verified access to the configured `gpt-6-luna`; it did not
establish account balance or execute inference. Restricted database and Temporal
inventories found no pending selected-tenant work or running selected-queue executions.

The initial operator image build failed because BuildKit treated a local image ID
as a registry name. The reviewed correction uses the existing source tag with exact
image/platform/user checks before and after build and verifies its base layers.
The resulting image passed public-input loading and a 22,590-file credential scan
with zero matches. Its never-started scan container was removed. ECR publication
verified immutable digest `sha256:951173ed64ecfb855344c48bf68424123eb127f349a18bafd91aae4e72afec8c`;
temporary Docker credentials were removed. This image is retained, not deployed.

Full authenticated preflight then refused unverified M4/X4/X6 prerequisites. Inspection
found no trusted native Codex X4/X6 verifier for the selected API-key route. The reviewed
repair accepts only operator-pinned, bounded, fresh native observations of ephemeral
API login, account readback and selected-model metadata access. Scoped prerequisites
include workspace, host, authentication, CLI and model identity, so another selection
cannot reuse their evidence. Baseline catalog definitions and old binding serialization
are preserved. Thirty-four focused tests, Ruff and authoritative typing passed;
independent review found and corrected a selected-model identity gap. Actual fresh
observations and normal prerequisite verification remain outstanding. These prerequisites
have not been waived or falsely attested. The private lane launcher now selects the attested venv on
PATH: its former clean PATH had no `python`, which would prevent kernel hooks from
running. The corrected path passed an actual Python 3.12.11 resolution check. No
base/lane worker or paid S0 execution has started. Runtime artifacts must include the
prerequisite repair before final qualification.

The first `b66411e5` API preflight exposed a missing production join: public
preflight and the pre-start check do not yet have sealed templates, so they still
returned the old prerequisite identities. That failed observation is preserved.
The reviewed follow-up resolves exact selected identities from trusted deployment
bindings and rejects disagreement with sealed launch templates. Thirty-nine focused
tests, Ruff and authoritative typing passed, including the actual manifest-service
and bootstrap composition paths. A restarted API using the working repair returned
the expected new X4/X6 identities with no other blockers. They remain unmet until
fresh native evidence is verified; this preliminary check is not worker qualification.

## Previous checkpoint: live readiness and final Cursor joins

This section supersedes older pending attribute, credential and Cursor implementation
statements below. The owner approved the exact Temporal attribute update and bounded
no-op. Operation `b86fdc54-5073-4b69-9214-2e06fa0fee28` fulfilled; all 14 types were
verified on `mission-control-dev.ih0e7`. Cloud also mirrors attributes into a legacy
map, initially tripping the strict comparison. Verifying that exact mirror and excluding
both added maps reproduced the original full-spec hash; other settings are unchanged.
No update retry occurred. The sole no-op `run2-probe-6c75bd7ea57d4f22987a32946b53e777`
completed under its 60-second execution limit. This proves connection, not worker qualification.

The existing AI Engineer credential was located in its owning environment and loaded
only in process. Read-only qualification passed with zero holds and zero mutations;
the computed live fingerprint matches retained 1.3.0. The exact nine-migration plan is
`sha256:f29ea141f6c3cf2786d1e09a45e58686e85e23a6b1699ca60c45175822b2609a`.
Private protected-object evidence is retained. Live apply and a current recovery decision
await the owner. Biotech was not touched. The owner confirmed no deployment/auth files
exist and authorized configuration preparation; reviewer grants remain explicit inputs.

CM-05 now classifies active holders under scoped lease/execution locks, validates native
journal anchors and stored cluster/operation identity, and notifies only the matching
running Temporal execution. Notification is not recovery completion. Live owners,
ambiguous evidence and unfinished custody retain their leases; no active holder is
released by this sweep. Focused units passed 37 tests in 2.38 seconds after five fixture
mkdir errors were fixed. Active/released/race PostgreSQL tests passed all ten cases in
21.18 seconds with no retained resources. The installed-provider kill drill remains unrun.

CM-01 now uses an independently owned read-only local billing HTTP connection after
bridge cleanup. Exact persisted native attribution remains required; responses are
bounded to 15 seconds, 1 MiB and 5,000 entries. Missing, partial, duplicate or mismatched
cost remains unknown. No bridge or agent is created for billing. The affected unit files
passed 67 tests in 3.17 seconds; production composition registers cleanup and routes local
settlement through the reader. Composition/architecture checks passed 64 tests in 32.01
seconds. Full mypy passed 804 sources; Ruff passed and 1,821 files are formatted. Counts
overlap and are not summed. Live cost availability remains unqualified.

The owner requested only GPT-6.1 Sol for further subagent work to conserve the weekly
allowance. Existing Astra agents finished these bounded repairs; further delegation uses Sol.

Source commit `69a18960ad7f2061e44e6999affb9020a82c80b8` includes both Cursor joins
and passed all applicable commit hooks. Its Linux/amd64 source image is
`sha256:c1ad6c0a2ce3c37725277dcef8ae95a3e23b3818fe9d665b18fe09769925655c`.
All 880 allowlisted context files are bound by manifest
`sha256:e132f99692f0334e9f82f5f4294715b35c056f04e4512461ec5e82324ec757bf`.
Import smoke passed as UID 10001 with read-only filesystem, no network, host mounts or
credentials. The smoke container was removed; the image/context remain local. No push,
operator-image startup or worker deployment is implied. Private configuration proposals
reuse the actual tenant and selected model/auth route while retaining missing grants,
policy/catalog references and restricted credentials. The live snapshot confirms common
capability roles are NOLOGIN with only migration-admin memberships; a separate narrow
worker-login proposal is prepared, not applied. Unrelated dirty files remain preserved.
Read-only configuration inventory also found that the configured tenant UUID is not yet
registered in Mission Control. Registration and actual principal grants therefore remain
explicit onboarding work. The existing Supabase public JWKS exposes one ES256 key and
was retained as observed public material; fetching it does not grant issuer trust.

## Resumed work after owner decisions (2026-10-14)

This section supersedes the earlier checkpoint's unresolved SDL, default-VPC,
disposable-fixture and artifact-schema decisions below; the original failures remain
part of the record. The owner authorized the existing disposable PostgreSQL fixture,
the disposable successor build, an additive artifact-schema definition, and creation
of the standard default VPC. The owner selected the currently deployed Biotech
Knowledge Services schema and subsequently approved Astra agents for complex work.
Two agents explicitly assigned `gpt-6-astra` handled accounting and release integration;
Sol handled the bounded catalog, Biotech and probe-manifest work.

- **Biotech authority resolved:** owning Git revision
  `d042678cb06de3c3c8b8f85e8ff9dff99858ad84`, release `biotech-schema-v2.0.2`,
  source SDL 389,072 bytes, SHA-256
  `fe2cc50afb4a48e16a2b5c3c37378b4d00a679a06d37bf312676c45c65c6589a`.
  The public Fly identity matches that source and its separately identified executable
  API. Versioned source-reference and semantic-overlay v2 preserve v1 bytes. The
  integration maps actual v2 nodes/relationships and retains complete topology while
  bounding Tier 0 summaries to 50 KiB; full descriptions remain in detail cards.
  The schema suite passed **85 tests**, followed by the strengthened topology/detail
  regression. Source agreement does not certify every stored graph record.
- **Default VPC created and verified:** account `298199649527`, `us-east-1`,
  `vpc-04db3b23ff1cee487`, six available default public subnets, gateway
  `igw-07a2dba78ee35c1c2`, route table `rtb-0f3620aab23618093` with an active
  internet route. No worker compute, secret value or provider resource was created.
- **Real persistence failure repaired:** the first authorized selection passed five
  tests and failed cost recording because 1.4.0 did not admit
  `mc.cursor-cost-observation/1`. Review also found partial billing-history attribution.
  The repair uses the strict bounded semantic-attempt reader with a consistent database
  snapshot, current-generation coverage and complete top-level session/run evidence.
  Legacy, drifted, missing and overflowing history retain the pending reservation.
- **Complete successor built:** additive
  `packages/mission-control-db-contract/releases/1.4.1/component/` contains unchanged
  frozen history, 0042's exact Codex update, 0043's single document-contract addition,
  and artifact-schema seed compatibility. Contract digest:
  `sha256:f1d3b86d8412e7217d2628533f149735109eb8ff4c1fc51f11c2ffc76a8ee719`;
  manifest digest:
  `sha256:3feb18ce8171319280c9db578343da38edea731ba17ae5305f4c9b3b0bf03039`;
  fingerprint:
  `sha256:e92a2562185c280db9eedf4fa9faef074e00d901a306a67236076be2720b1b93`.
  The frozen 1.4.0 and original Codex-only candidate remain unchanged. Deployment
  locks remain 1.3.0; no live installation is implied.
- **Successor persistence proof:** **18 tests passed in 75.82 seconds**, including
  fresh installation, upgrade, replay, seed compatibility, drift refusal, RLS,
  immutable records, delayed cost settlement, attribution negatives, ingress and
  released-bridge cleanup. Both build and tests left **no new databases or roles**.
  Baseline fixture resources were preserved. Release/lane unit selection then passed
  **34 tests in 3.76 seconds**.
- **Current host prerequisites:** Ubuntu has Codex CLI 0.162.1, Claude Code 2.1.296
  and the existing Python 3.12 environment. This version inventory is not an auth or
  lane qualification receipt. Required remote database credential and deployment-binding
  settings are absent. The refreshed Temporal Cloud key reads the exact dev namespace.
  The earlier `PermissionDenied` came from server Operator API attribute inventory,
  not namespace access. Cloud Ops inventory now confirms an active namespace with
  all 14 required custom attributes absent; the tested additive plan awaits approval.

The final resumed selections additionally passed **92 accounting/schema-validation
unit tests**, **18 lane-release/accounting PostgreSQL tests** (45.64 seconds, no new
retained resources), and **36 S0/compiler/schema/deployment tests**. The S0 templates
compile only from actual committed catalog revisions; their repository, immutable
ref, reviewer and launch bindings still need owner selection. Independent review
found cross-kind schema-reference ambiguity; compilation now refuses it in either
listing order. Static reference-expansion bounds reject recursive/exponential schemas
before artifact capture. This is not a universal validator execution-time guarantee.

Authoritative mypy passed all **797 source files** after repairing one optional-schema
annotation. Ruff lint and formatting passed **1,798 files**; manifest schema drift,
documentation links and the 45-document knowledge validation passed. The entire broad
suite has not been rerun. Earlier S0 test attempts had an invalid import and an
unsupported `action_space` authoring field; these were repaired without weakening
required outputs or review criteria.

Read-only queries of both live projects confirmed active installation identities and
stored **1.3.0** attestations on 2026-10-14. This was an attestation read, not a fresh
computed-fingerprint verification or migration. The first-service deployment path
now explicitly selects the approved VPC, verifies the egress-only group and public
subnets, disables zone rebalancing and preserves one task. It has not run against AWS.

The deployment script's real PowerShell entrypoint additionally passed **29 hermetic
deployment tests** (22 script cases plus seven plan cases). These check both service
paths, topology/network drift, uncertain creation, late task identities, drain failure
and terminal old-task waits before replacement. Every AWS call was mocked; these are
not AWS deployment receipts.

A local S0 fixture now exists at `/home/overton/mc-fixtures/run2-s0` in Ubuntu, pinned
at `740e5e370c728c10901b2aeeadb1542124faf6c5`; its integrity test passed and its working
tree is clean. This does not select or admit a provider binding. The owner selected
the configured API-key route, superseding the earlier ChatGPT-login prerequisite.
A private `mc.auth_profile.v1` profile and mission overlay now pass structural
auth admission with the configured Settings key held only in memory. Neither the
Windows nor Ubuntu login process originally had the required key environment variable;
a reviewed stdin-to-child-environment wrapper is prepared, not executed. Native
`--version` succeeds with the selected Node directory explicitly on PATH; the original
PATH attempt failed to find Node. No login, worker or model was invoked. R22 already
selects `gpt-6-luna`; reviewer/grants, runtime/storage bindings and finite paid authority
remain unresolved.

The remaining production joins continue. The mission is not accepted or live-qualified.

### Cloud-fork custody join

The cloud ordinary-fork path now captures a scrubbed, bounded conversation envelope
before releasing its workspace lease. Its origin binds request scope, source run,
repository, branch and exact commit, native session and native run. Both branch HEAD
and native run are checked again across capture. The lease atomically supplies the
branch reference and evidence to the sealed RunSnapshot; the deterministic fork seed
then queues a snapshot reference. Context packing resolves the scoped snapshot and
verifies locator metadata, actual bytes, digest and origin before including mandatory
conversation context. Missing evidence on new snapshots fails closed; snapshots without
the new field preserve their prior canonical bytes and behavior.

Focused tests cover changed origins, corruption, absent custody, the full end-session
to fork-packet path and mandatory token-budget refusal. The affected final selection
passed **15 tests** after two fixture errors in the first selection were repaired.
The authorized PostgreSQL fork suite passed **both legacy and conversation cases** in
14.65 seconds, through restricted runtime roles, with no new retained databases or
roles. These are offline implementation and persistence proofs; real Cursor Cloud
fork qualification remains unrun.

### Budget control, workspace fencing and Cloud readiness

Managed budget controls now have production StageGraph and GoalDirected callers and
an owner-fenced durable intent/readback journal. A hold lowers the native cap within
the immutable ceiling and requires a fresh native budget-boundary observation before
application. Resume names its exact hold and requires current command authority,
approval, stop-fence and retained currency reservation. An ambiguous update is never
blindly repeated; readback proves observed state, not causal exactly-once execution.
Partial fan-out retains per-child receipts and liabilities. Cancellation never lifts
the cap. Legacy boundary-pause payloads retain their canonical bytes, and provider
qualification flags remain unchanged.

The first budget unit selection passed 46 tests. Both real isolated Temporal family
tests passed and replayed their newly recorded histories; their native provider was
a deterministic fixture. The authorized restricted-PostgreSQL budget journal proof
passed in 3.61 seconds with no new retained databases or roles. Subsequent family
rejection and replay proof is recorded below; these are not HL-24 live receipts.

Cursor local operations now revalidate the exact lease before bridge access and
instruction/continuation file access. An expired active Cursor holder cannot be replaced
on expiry alone, including through another profile. Same-holder recovery and explicit
release preserve the safe path. The six PostgreSQL workspace race tests passed in
14.03 seconds with no new retained resources. Focused local tests passed after fixing
one test-only absent-file chmod setup. Autonomous active-orphan classification and
the installed-provider worker-kill drill remain unrun.

Cloud readiness uses the Cloud Ops namespace inventory; local-server readiness keeps
its existing Operator API. The dev attribute planner copies the complete namespace
spec and adds only missing declared attributes. Exact namespace, region, active state,
resource version and full-spec hash are checked before an apply. Independent review
found no material defect; 13 tests passed, including no-write planning, request shape,
configuration drift, conflicting types and unchanged local defaults. No Cloud update
or no-op workflow has run at this checkpoint.

The final budget and recorded-history selection passed **95 tests in 17.24 seconds**,
including four actual family-workflow cases and replay of their new histories, plus
the four existing captured-history test files. The StageGraph rejection regressions
verify that held-child projection changes only after authoritative acceptance. The
full authoritative type check passed **804 source files**; dependency analysis also
passed 804 files. Final broader verification is still pending.

The expanded successor selection passed **16 tests and failed four ingress tests** in
68.70 seconds. The exact retained-byte **AI Engineer 1.3.0-to-1.4.1 upgrade passed**,
including eight expected migrations, preserved old receipts, replay and security.
The failures exposed SQL NULL handling in the new retry filter: fresh inbox rows with
no outcome were excluded. This was repaired without weakening the deferred retry
rule. The run left no new databases or roles. Independent review also required binding
revocation checks before a new history acknowledgment and a bounded full-turn OpenAI
item rescan because item completion order need not match list order.

A second selection passed **19 tests and failed four new webhook variants** in
74.69 seconds, again retaining no new databases or roles. Existing ingress tests passed
after the NULL fix. The new fixture omitted the native session state column that
production startup records, so strict admission correctly rejected it. The fixture was
corrected. Review additionally found that rejecting an expired/revoked inbox hint alone
left the owner journal pending forever. A separate owner-fenced rejection disposition
now permits native closure without manufacturing acknowledgment. The repaired selection
passed **99 focused unit tests** and **all eight PostgreSQL ingress tests** (30.25 seconds,
no new retained databases or roles). The final takeover selection then passed **32 focused
unit tests** (4.84 seconds) and **all nine PostgreSQL ingress tests** (31.98 seconds), again
without new retained resources. Only the current fenced owner can reject the exact older
generation's request; neither that rejection nor a stale owner can acknowledge or wake it.

The history owner persists native frames before its durable acknowledgment; the drainer
then delivers wake and settles the inbox. The journal retains up to 64 successful receipts
and one current rejection, while the original inbox retains rejection audit evidence.
New acknowledgment checks the exact live binding under a shared lock, serializing
revocation. A previously successful acknowledgment can still support delivery retry.
Timeout, overflow and incomplete native history remain pending. Provider history is
bounded; Cursor Cloud proves a terminal native record, not complete SSE history.

Current S0 preparation uses the mission's recorded R22 Codex model `gpt-6-luna` and
the newly selected API route. A private agent-profile candidate validates with canonical
digest `sha256:8d8da6f3ecfc05e34bd9677584cfd273ef15feb15d153d67ddbc81aa56c101f0`.
It is unpublished and has no assigned catalog revision. Partial application/provider
bindings explicitly retain missing reviewer/grants, policy references and actual worker
attestations; no placeholder digest is represented as authority. Current migration and
restricted runtime/checkpointer credential references are absent, preventing a fresh
live before-plan. The reviewed upgrade proposal and exact successor lock remain private.

### Remote admission and additive idempotency correction

The real ingress-to-admission proof exposed a stored-function bug: a reused launch
idempotency key returned the original request even when its body changed. The new
immutable **1.4.2** successor adds only `0044_ingress_mission_request_idempotency`.
Both the ordinary lookup and concurrent insert-conflict path compare the stored digest
and JSON payload; conflicts return `dedupe_conflict` with no request ID. Payload equality
also refuses a restricted SQL caller supplying an old digest with changed content.
The function signature, SECURITY DEFINER search path, owner and grants are preserved.
All 46 files in 1.4.1 and its 36 SQL migrations were verified byte-for-byte unchanged.

The authorized PostgreSQL 17 release build passed with no new retained database or role.
Contract digest: `sha256:356f26ed7f942a04cdae746cbe5923c5be8b9630cccba944261fab1806fb6f80`;
manifest: `sha256:4953934315aad0804d74d0ace4277b9b43f211adcd265810126ab02f0083d892`;
fingerprint: `sha256:1d6dcd1a96b44b7c3635ffd34cec7703703160b04bf52c24643157c72a472cc3`.
All four installer cases passed: fresh installation, exact 1.3.0 and 1.4.1 upgrades,
and drift refusal, preserving prior receipts, data, function identity/ACL and RLS.
The combined selection passed five tests and failed two concurrency fixtures because
their transaction reused a cached PostgreSQL statistics snapshot. Clearing that
snapshot before each bounded observation fixed the synchronization barrier; the
focused serial/concurrent idempotency suite then passed all three cases in 17.39 seconds.
Both selections retained no new databases or roles. The SQL bytes did not change.
Tracked live deployment locks remain 1.3.0; no live migration ran.

`test_remote_mission_admission.py` passed in **22.24 seconds**, using real restricted
PostgreSQL ingress, HTTP status responses, normal manifest admission/preflight, durable
run/outbox records and a real isolated Temporal server. It covers forged, expired,
wrong-app and revoked credentials, stale installation readiness, missing model binding,
identical replay, conflicting body, and process loss after the real start but before
the drain receipt commits. Retry resolves one run and one actual Temporal root, matching
the stored cluster binding. Missing launch bindings now produce a terminal governed
rejection rather than an indefinitely retried infrastructure failure.

The test uses explicit disposable grants/catalog/model fixtures and the technical
`belllabs-run/{run_key}` root. Its zero-digest fixture attestation is not release
qualification; it does not prove scoped remote root identity, paid model behavior,
outside-network reachability or mission acceptance. The existing cached Temporal CLI
was selected explicitly (CLI 1.9.1/server 1.32.0), with a fresh SQLite file and loopback
port. No executable was downloaded. The selection retained no new database or role.
Earlier failed attempts remain recorded: a fixture lacked `catalog.read`, followed by
the real idempotency defect. Neither is represented as a passing run.

## Source and authority

### Current acceptance delta

This table supersedes the named initial-checkpoint blockers below. It does not mark
the issues accepted; exact provider, account and placement qualification remains separate.

| Criteria | Current implementation and evidence | Remaining gate |
| --- | --- | --- |
| MO-71 | Approved artifact-schema catalog definition, exact published revision compiler resolution, ambiguity and bounded expansion tests; additive production seed. | Publish through the reviewed live release and admit real bindings. |
| MO-65/66/69/72 | Current deployed Biotech SDL integrated; Codex 0.162.1 and R22 model identified; clean Ubuntu fixture, API-route structural admission and private configuration drafts. | Actual worker environment, real reviewer/grants and complete bindings; finite paid S0 authority and exact-placement receipts. |
| CM-01/02 | Strict delayed-cost attribution and immutable 1.4.1 successor; disposable accounting and exact 1.3.0 upgrade proof. | Live plan, migration/recovery decision and actual provider accounting/cost settlement. |
| CM-05 | Exact active-lease fences at bridge/file operations and refusal to replace expired active holders; six real PostgreSQL race tests. | Installed-provider restart/kill recovery; active-orphan classification remains outside the implemented released-holder sweep. |
| CM-07 | Source-bound conversation custody through released lease, snapshot, fork seed and verified mandatory context packet; two real PostgreSQL cases. | Actual Cursor Cloud fork and custody qualification. |
| MO-75 | Durable native-history request/acknowledgment/rejection, bounded owner reconciliation, ack-before-wake and original inbox audit; nine real PostgreSQL ingress cases including takeover; frozen-source independent review clear. | Deployed provider recovery/latency proof. |
| MO-77/78 | Approved default VPC exists. Worker deployment script, Cloud Ops readiness and exact additive search-attribute plan tested offline. | Attribute/no-op approval, immutable build/config, restricted credentials, exact resource/spend plan and remote service qualification. |
| HL-24 | Governed Managed budget controls wired through both workflow families; durable PostgreSQL journal, actual isolated workflow execution and replay. | Both remote missions, native budget/approval/recovery, publication, settled cost and cleanup. |
| MO-74/76/79, HL-25 | Existing ingress, custody and normal admission implementation retained; successor release and dependency proofs improved. | Live restricted deployment/storage/admission; HL-25 follows accepted HL-24 and reconciliation of prior unknown spend. |

All other initial-table live drills remain unrun. All eight funding-held issues and S4
remain unchanged. No provider qualification flag was promoted.

The final MO-75 independent review found no remaining actionable defect in the frozen
20-file source/test selection. Its private manifest and review are retained with digest
`7af356a9b10036b53866ba06d4c86cf0cfca8ce2724526ee2ebee9373442c9ce`.
Final authoritative mypy passed all 804 sources, Ruff lint passed, formatting passed
1,815 files, and dependency analysis passed. Documentation checks passed 399 files with
zero broken links, 45 valid knowledge documents and a current generated index. One
documentation-check attempt named a nonexistent script; rerunning the correct
`docs/tools/check_links.py` produced the stated pass. The broad unit/conformance/
architecture suite finished with **4,718 passed, seven failed, 20 skipped and two
expected failures in 1,133.43 seconds**. Four seed assertions omitted the approved
artifact-schema bundle or mistook its `usage` schema property for fabricated usage
records. Two Cursor conformance cases exposed use of the initial native-run anchor
after a later turn was acknowledged; the foreign-run negative also needs to assert
the new strict custody refusal. These failures are retained. The repaired affected selection passed 153 tests and
failed four new seed negative assertions because typed validation rejected their
extra fields before the structural assertion. Correcting only those expected exception
types yielded all 19 seed tests passing. The affected selection includes both full
Cursor conformance files, exact native-run continuation/recovery/custody cases, real
managed-budget action fixtures and all four isolated workflow/replay cases.
The skips remain missing AgentServer endpoints and older Python interpreters; the
two expected failures remain the pre-existing RRM-012 authority-journal gap.

A separate post-commit budget selection passed 23 tests and failed 21 because its
test doubles used `SimpleNamespace` actions rather than real `PauseAction` and
`ResumeAction` contracts. The production type narrowing is retained; the fixture now
constructs real validated action contracts. Its repaired tests passed in the 153-test affected selection above.

### Release and admission checkpoint

Commit `4db354b07ae0bfb1d545f5b2d415de4e46f42ad5` records 60 reviewed paths for
the 1.4.2 release, real admission proof and the targeted regression repairs. Every
applicable hook passed, and all 37 committed migration blobs match the release
manifest. Generated Python caches remain ignored and untracked. The source image
below is for the earlier commit, so it does not yet prove this checkpoint's build.

The remaining offline audit identified two required Cursor joins: startup active-holder
classification and delayed local billing after bridge cleanup. These repairs are in
progress under disjoint Astra leases. Neither expiry nor a native terminal status alone
authorizes active lease release; unknown billing retains the reservation.

### Resumed implementation checkpoint

Commit **`e76684781cb6d3d55dd9f98af51c613a5e220cbf`** records the 72 reviewed
mission paths for budget controls, native history, fork custody, workspace fencing,
Cloud readiness and deployment hardening. The first commit attempt exposed an
unresolved union attribute in the fast type checker; explicit pause/resume narrowing
fixed it without widening authority. The next attempt sorted that import. The final
commit passed every applicable hook. Authoritative scoped typing also passed the
changed service. Unrelated `docs/knowledge/index.md` edits and `issues/bash.exe.stackdump`
remain preserved and excluded. Main and origin/main were not changed; nothing was pushed.

The exact committed source also built successfully as Linux/amd64 using the Dockerfile's
digest-pinned base images and frozen dependency lock. Local image identity:
`sha256:9148c8b8d511573d84aaf16b585a48eb2d450da73b9674f4d117b911cdd8400d`
(906,638,407 bytes), retained tag `mission-control:source-e76684781cb6-0c2f653f26`.
The allowlisted Git archive contained 880 files; the context manifest digest is
`sha256:1cfb30fabc623e0d8c29a80f8a72bc0fbbb7544fd3f4cfa8a069f9099c8b2a6c`.
Runtime imports passed with UID 10001, read-only filesystem, dropped capabilities,
no host mounts, no credentials and networking disabled. The smoke container was removed;
the local image, source context and private receipt remain retained. This is a source
image/import proof, not a configured operator image, worker startup, image push or deployment.

The next executable live boundary remains the reviewed, additive 14-attribute Temporal
Cloud plan plus one bounded no-op on `mission-control-dev.ih0e7`, pending owner approval.
The new key can read the namespace; no new key or guessed permission change is needed.
An exact live database plan additionally needs the local credential reference for
`MC_AI_ENGINEER_MIGRATION_DATABASE_URL`; the value must remain private. Existing deployment
and S0 binding paths, or real owner authentication/reviewer/grant selections, are still
needed to complete the prepared configuration. These requests do not authorize migration,
secret writes, worker deployment or provider inference. Those actions require their
subsequent concrete plans and allowances under the kickoff.

Implementation branch: `mo/run2-integration`, canonical `platform/mission-control`.
Planning base: `5b03afc4f214d335b5ef5dc96ba33100f1fb4d67`; original main/local
origin-main: `a2527f6f3c385a7f55272c41d90e6860b44781d0`. The user authorized local
implementation commits. No main update, push, deployment, provider inference,
credential write, installation, live database apply or Linear publication was performed.
The implementation revision and final verification are recorded at closeout below.

Three isolated workers were explicitly assigned `gpt-6.1-sol`: Cursor, CLI/local host,
and Events. The lead remained the session's configured model; prompt text did not
change it. Their fresh branches/worktrees were based on the planning commit. Source
manifests and selective patches were verified before integration. Workers reviewed
lead joins; the lead independently reviewed worker changes and repaired production
accounting, queue, wake, auth and composition gaps. Heavy tests were coordinated through
a shared slot; an earlier overlap was identified and corrected.

Private claims, raw receipts and failed-run details remain under ignored
`.scratch/materialization-observation-2026-10/run2/`. Worktrees are retained under
`platform/.worktrees/run2-{cli,cursor,events}`. The unrelated untracked
`issues/bash.exe.stackdump` is preserved and excluded from commits.

## Initial checkpoint criterion-to-evidence map

Paths below are repository-relative. A passed fixture proves only the stated offline
behavior. Every live provider/placement drill below remains **unrun**. Requested model
identity stays separate from provider-observed identity; no qualification flag changed.
This table preserves the initial checkpoint. The resumed evidence above supersedes its
SDL, VPC, artifact-schema, successor-build and named PostgreSQL-test blockers; it does
not supersede its unrun live acceptance requirements.

| Issue | Integrated source and offline evidence | Remaining acceptance |
| --- | --- | --- |
| MO-07 | Current knowledge, author/observe guidance and release page reconcile product identity, versions, watchers/inbox and qualification. Operator guide documents new entrypoints. | Complete only as documentation for this checkpoint; historical receipts are not current proof. |
| LS-01 | Standalone `coding-cli-jobs` schemas/runner; closed schema selector, verifier-owned completion, cumulative budgets, bounded iteration/deadline. 73 fake-CLI tests passed. | Actual CLI output/version behavior belongs to LS-07. |
| LS-02 | Claude adapter: structured result, explicit permissions/model/auth, typed terminal results; fixture tests. | Actual quota/subscription/status/max-budget behavior unrun. |
| LS-03 | Codex adapter: isolated worktree, explicit resume/profile, Windows descendant containment and WSL ext4/env/process-group path; fixtures. | Actual selected WSL distro, native Git/CLI/home/login and Windows sandbox unrun. |
| LS-04 | Cursor CLI adapter: stdin prompt, explicit permission/profile, sealed resume, last assistant result; fixtures. | Actual stdin/read-only/denial/usage behavior unrun. |
| LS-05 | Four `.agents/skills/` bundles, recipes, schema/reference and provenance; no runtime/catalog dependency. | Actual caller skill discovery is part of LS-08. |
| LS-06 | Environment allowlist, redaction, auth refusal, cleanup liabilities, finite budgets and `doctor`; negative tests. | Owner auth/quota facts and native process containment require exact-host proof. |
| LS-07 | Default-off live checklist in `references/live-handoffs.md`. | Blocked on exact job/account/model/auth authority and remaining spend; no smoke run claimed. |
| LS-08 | Reviewed two-job demo procedure with independent verification and retained cleanup. | Follows LS-07; actual Claude Code discovery/background completion wake unrun. |
| CM-01 | `cursor/cost.py`, domain billing contracts, application reconciler, Postgres repository and Temporal child workflow; opt-in same-journal initial/pending settlement. Unit tests cover unknown/zero/delayed/replay/overage and exception sanitization. | Real PG crash/replay proof unrun. Cloud per-run billing live-unverified; local read-only billing after bridge shutdown remains incomplete. Unknown liabilities stay reserved. |
| CM-02 | `cursor_usage.py`, optional semantic-attempt frame reader and exact scoped multi-generation query. V2 tests use distinct predecessor/target harness identities; duplicate runs count once, legacy/drift/missing/overflow evidence yields unknown. | Actual forced-RLS PostgreSQL query and live continuation/cancel replacement billing unrun. |
| CM-03 | Typed SDK/HTTP configuration/auth/transient/capacity errors and sanitized correlation metadata; fixtures. | Provider wire taxonomy and exact retry behavior live-unverified. |
| CM-04 | Opt-in Windows bridge via detached `Popen` and loopback client. Real Windows Selector-loop fake-SDK subprocess/reconnect/shutdown fixture passed. | Installed Cursor, native hooks, ACL/privacy and Windows CD-15 unrun; flag remains false. |
| CM-05 | Private discovery, ping/version validation, detached log, no blind ambiguous respawn and same-session reattach. Opt-in startup cleanup enumerates released host-owned leases, serializes with acquisition, rechecks holders, bounds endpoint shutdown and preserves files. | Real PG lock/RLS proof and worker-kill/same-run/offset proof unrun. Expired active holders require workflow/session reconciliation before release and are never swept by expiry alone. |
| CM-07 | Bounded scrubbed 32 KiB conversation excerpt with digest/native provenance; local forks and both profiles' continuation snapshots. | Cloud ordinary branch fork lacks admitted conversation sidecar custody; shared snapshot-to-packet design below remains required. |
| CM-08 | Shared cloud create body preserves model/options/environment/MCP/subagent identity through hydration. Source archive/offer handling is idempotent; parity fixtures. | Actual provider transfer, archive and recovery/custody drills unrun. |
| CM-09 | Exact-head branch outputs plus admitted API artifacts; missing-required-output detection, one budget/fence/journal-governed followup, PR provenance. | API artifacts remain agent-scoped when provider supplies no originating run; real immutable registration and review/publication drills unrun. |
| CM-10 | Existing per-unit run/operation branch and common lease allocation preserved; isolation/retry/reattach fixtures. | Four-unit Stage Graph exact-placement cleanup/CD-14 unrun. |
| CM-13 | Rich duplicate SSE text/tool updates retained as raw frames and excluded from materialized transcript; simplified family is canonical. | Live dual-family protocol drill unrun. |
| CM-18 | Required staged followup/continuation text refuses missing refs; explicit authored empty text is distinct. Tests cover both profiles. | Provider end-to-end staged-context proof unrun. |
| CM-19 | Acknowledged cancellation tolerates subsequent native-run disappearance; timestamps/native identity retained when available. | Real four-timestamp CREATING/running cancellation drill unrun; unavailable provider timestamps remain unknown. |
| CM-21 | Offline suite and explicit drill disposition; no blanket profile promotion. | Applicable CD drills unrun. Deferred CM-06/11/12/14/15/16/17/20/22 stay deferred. |
| MO-63 | Lane-only worker rejects every base/family/artifact/watcher/linked-run/maintenance queue and avoids base runtime composition; regression tests. | Actual WSL lane worker + exactly one AWS base worker unrun. |
| MO-64 | Split-host filesystem marker/identity guard or S3 selection before dispatch; negative tests. | Real cross-host S3/mount round trip unrun; equal marker strings do not prove a shared mount. |
| MO-65 | Explicit owner `CODEX_HOME` topology and selected-home/configured-binary readiness; isolated API auth remains separate. | Actual owner login on selected Windows/WSL host unrun. |
| MO-66 | Codex 0.162.1 pin, deterministic generated schema fixture set, before-create/reattach compatibility guard and new versioned example. Old fixtures/examples unchanged. | Installed exact CLI/schema/host qualification unrun. |
| MO-67 | Exact-target Temporal probe procedure and existing S0 orchestration seams retained. | Blocked by MO-72/78, actual selected host and namespace write authority. |
| MO-68 | Optional profile-relative `deployment_dir`, selected target/release lock, absent-field compatibility tests. | Owner's actual local deployment-root readiness unrun. |
| MO-69 | Explicit reviewed pointer selections, file-byte SHA-256 inputs, deterministic secret-free identity summary; no canonical binding shape change. | Actual owner selections, image/runtime/agent-profile evidence and fully valid three-lane bindings absent. File hashing is not automatic resolution of all 62 owner values. |
| MO-70 | Local asymmetric JWT minting constrained to configured subject/tenant/permissions, expiry and verifier; new-file-only secret output. Negative tests. | Actual ingress verifier round trip using owner keys unrun; Windows directory ACL is an owner setup requirement. |
| MO-71 | Inspected real compiler/schema authority; no fabricated catalog entries or optionalized outputs added. | Blocked: production seed MCP tool outputs have no required artifact schemas. Needs real published schema authority or approved additive artifact-schema design. S0 manifests not falsely claimed valid. |
| MO-72 | Existing S0 implementation retained; auth, binding and worker prerequisites extended. | Blocked by MO-69/71, missing Biotech SDL, actual WSL/auth/repository/selected tools and finite paid proof authority. |
| MO-74 | Slim edge factory, restricted TLS PG pool, provider auth/OIDC, optional upload custody and Vercel closure/lock/plan. Source closure: 95 files, 1,079,049 bytes. | Isolated slim dependency build, deployed latency/size, restricted DB and delivery proofs unrun. No Vercel deployment/webhook registration. |
| MO-75 | Scoped SKIP LOCKED claim transaction, separate runtime effects, frame dedupe, retry/dead state, LISTEN + 5s poll; base-worker composition and failure propagation. | New real PG cases are supplied but unrun. Wake provides bounded status reads; complete native-history drain/reconciliation after wake remains incomplete. |
| MO-76 | Signed quarantine storage, actual byte/digest/size/scope/expiry checks, normal registration and retry-safe cleanup. Negative fixtures. | Real storage upload/register/revoke/large-body/cleanup proof and deployed worker custody settings unrun. |
| MO-77 | Exact AWS task renderer/validator, existing-service update/rollback script, immutable-image Dockerfile and infrastructure proposal. Lane-role/base separation preserved. | No VPC exists. Network decision, config/secrets, first-service provisioning, build/sentinel/role/S3/laptop-off/restart/24h cost evidence remain outstanding. |
| MO-78 | Read-only exact dev namespace probe; finite no-op write explicitly separate. Read-only AWS inventory and CloudFormation template validation performed. | Temporal connection/search attributes and no-op unrun; selected namespace credentials/authority still required. |
| MO-79 | Launch request resolves trusted registered manifest, ordinary actor grants/prerequisites/admission and root-slot refs; scoped idempotency fixtures. No new SQL slot. | Actual restricted PostgreSQL/isolated Temporal remote admission/crash/replay proof unrun; depends on live 1.4.0 installation. |
| HL-24 | Existing Managed hosted code retained; configuration/approval/wake/custody boundaries reviewed. | Both remote S2 missions blocked by MO-74/77/79 and governed budget pause gap. Boundary hold is not provider budget hold. Native approval/deny/wake/publication/cost receipts unrun. |
| HL-25 | Existing hosted HTTP Agents API identity preserved; no SDK/Responses substitution. | Follows accepted remote S2. Prior S3 acceptance and spend uncertainty unresolved; new finite native-function-approval proof unrun. |

All eight additional funding-held issues remain blocked and unchanged: **HL-01, HL-02,
HL-03, HL-10, HL-14, HL-15, HL-16, HL-20**. No S4 release or inferred funding occurred.

## Initial checkpoint identities and custody

Common component **1.4.0 remains unapplied live**. No migration, release lock or existing
seed bytes changed. Migration 0035 already owns `mission_request`; 0039 is not allocated
by this work, and 0040/0041 are not reused. Old canonical bindings and approval seals are
preserved; optional usage-cache fields are excluded when absent. The explicit new
semantic-attempt marker is derived execution metadata, not a rewrite of old rows.

The runtime Codex 0.162.1 describe differs from immutable 0040's 0.162.0 reference.
Two lane-contract tests remain failed. A reviewed, integrity-checked **1.4.1 candidate**
is prepared outside the source package; it is unbuilt and unapplied. Its six tests pass.
See [the successor plan](CODEX-DESCRIBE-SUCCESSOR.md) for the exact proposed migration,
disposable build, cleanup and additive release completion. No frozen reference was edited
to obtain a passing test. The `mcdb_release_*` build requires its own fixture authority.

Current author/observe skills advance to 0.3.1. Their old 0.3.0 source files were archived
byte-for-byte from `5b03afc` under `bundle-sources/agent-skills-1.0.1/`, preserving fetchable
historical custody. Additive per-application `agent-skills-1.0.2` bundles publish revision 3.
Additive `workflow-parity-1.0.3` records asset version 4 and the billing workflow. Existing
1.0.0/1.0.1 skill and 1.0.2 workflow bundles remain frozen. Nothing was uploaded or applied.

New source-only deployment plans are not build or installation receipts. Generated Vercel
closure and private task/config receipts remain ignored. The AWS renderer intentionally
does not enable Cursor cost settlement or provide quarantine/custody credentials; those
require an additional reviewed deployment configuration before those features can qualify.

## Verification record

Use the repository's existing `.venv/Scripts/python.exe`; no dependency installation was
performed. Counts overlap and must not be summed.

- Ruff lint and formatting: passed on integrated source before closeout.
- Authoritative `python -m mypy`: **797 source files passed** after the original three errors
  were repaired (workflow predicate typing, variable-length activity tuple, nullable wake ID)
  and the final released-bridge closure's optional-path annotation was narrowed.
- `python -m deptry src`: passed, 797 scanned source files.
- Fast `python -m ty check`: exit 0 with 11 warnings in unchanged files. An initial
  incompatible billing-reader override and new auth-output type warning were repaired;
  the affected cost/auth/operator/cancellation/digest selection passed **94 tests in 33.77s**.
- Skill manifests: all 15 current bundles passed. Seed generation check, 172 published
  capability definitions, and manifest schema drift check passed.
- Documentation: generated index current, 45 knowledge documents valid, 398 documents
  checked with zero broken relative links. Vendored ingress import loaded all 85 imported
  Mission Control modules from its closure using existing environment dependencies;
  no startup/network or isolated slim dependency installation was performed.
- Integrated Cursor/Codex/conformance selection: **419 passed in 239.06s**, before Cursor
  v2 accounting repair. Worker v2 selections: **23 passed in 19.34s**, frame writer/order
  **13 passed in 1.01s**; five-source scoped mypy passed. Later integrated checks supersede
  earlier subsets only where they cover the same source.
- Standalone CLI suite: **73 passed in 14.74s**, frozen hashes verified after integration.
- New integration/seed/architecture selection initially **86 passed, 2 failed**: immutable
  seed comparison included a loader-added digest; billing workflow directly imported an
  application module. Corrected test comparison and moved pure payloads into the domain.
- Repair + cost/queue/seed/architecture + captured-history suite: **70 passed in 30.62s**,
  including all **15 captured lane histories**. This is real SDK replay of recorded histories,
  not a live namespace execution or proof of newly exercised runtime branches.
- Final Cursor, released-bridge startup, workspace allocation/lease ledger, cancellation
  composition and architecture selection: **205 passed in 216.87s**. This includes the
  reviewed canonical-path, receipt-progress, protection, cancellation and redaction cases.
  The preceding attempt found one closure type annotation error and referenced a nonexistent
  test filename; no pytest cases ran in that attempt. Both were corrected before this pass.
- Earlier integration checks: 31 passed in 10.91s after correcting fixture workflow ID,
  test-only workflow construction and obsolete example pin. An earlier target had 93 passed
  and four failures; those failures were retained rather than labelled all-green.
- New PostgreSQL tests use production drainer/frame/journal adapters and are deliberately
  **unrun** until the exact disposable fixture is authorized. All **six tests collected
  successfully in 10.53s**; collection does not execute their fixtures. No skip manufactures proof.
- Broad unit/conformance/architecture/captured-replay command:
  `python -m pytest tests/unit tests/conformance tests/architecture tests/integration/temporal/test_lane_replay_histories.py -q -m 'not common_db' --tb=short`:
  **4,490 passed, 28 failed, 21 skipped, 2 xfailed in 1,030.63s**. This failed run is retained.
  Failures exposed deterministic-set hashing, missing bridge state-root creation, outdated
  staged-text/auth/error/cost fixtures, Windows checkout/Bash setup, two Codex release
  mismatches and six missing-authoritative-Biotech-SDL tests.
- Repairs preserve production refusal rules: unknown Cursor run costs remain unknown;
  owner Codex homes receive no generated hook trust; busy requests require staged text;
  HTTP access denial remains typed. Skill bytes were restored to the existing lock's LF
  bytes without changing any lock. Bash checks used the existing Git Bash through only
  the test process's PATH. The repair selection first yielded **134 passed, 5 failed**;
  three cost expectations and two owner-home telemetry fixtures then needed correction.
  The corrected fixture/standalone-CLI selection passed **122 tests in 81.25s**.
  The remaining broad-suite blockers are the **two release mismatches and six SDL tests**;
  the entire broad suite has not been rerun and is not claimed green.
  Existing skips cover unavailable AgentServer endpoints (19), unavailable older Python
  interpreters (1), and a POSIX shell case (1). The two expected failures concern the
  pre-existing RRM-012 stage-0/2 reference authority-journal gap.
- AWS `validate-template` accepted the infrastructure document and reported the expected
  named-IAM capability and VPC/email parameters. This read-only check created no resources.
- No live provider, Vercel, ECS, Temporal Cloud write, remote storage or live migration check
  passed in this run. No paid provider inference was executed; historical unknown
  S3/provider liabilities remain unknown.

## Remaining implementation decisions and owner boundaries

1. **S0 schema authority:** inspection found 44/44 common and 13/13 AI Engineer production
   seed MCP tools with null output schemas; qualification adds none. Compiler output schemas
   come from admitted published tool definitions. Test-only schema publishers cannot supply
   production authority. Either publish the genuine required tool schema or approve a
   versioned artifact-schema capability/compiler design. Required outputs must remain required.
2. **Cloud conversation fork:** export should be stored under a durable content ref/digest
   bound to exact source branch SHA and native session/run, then admitted through snapshot
   evidence, fork seeding and the mandatory context packet. Current branch-only restore refs
   carry no such identity. Do not mutate the source branch or invent an input-ref convention.
3. **Bridge orphan recovery:** released-holder cleanup now has explicit scoped startup
   composition, host/path checks, acquisition-lock protection and bounded endpoint shutdown.
   A scoped, fenced detail receipt distinguishes confirmed stop from missing discovery and
   excludes completed candidates from future batches. Review repaired candidate starvation,
   a workspace-alias race and test-task cleanup; no remaining material finding was identified.
   Active/recoverable holders still require workflow/session reconciliation before release.
   Expiry or filesystem scans alone cannot distinguish an orphan from a reattachable session.
4. **Managed budget hold:** existing helper has transient held-cap state, lacks readback,
   defaults missing cost to zero and is not called by production controls. Restoring a cap
   can resume cognition without `send_turn`. A scoped design must journal/reconcile the
   control, check current authority/fence/generation/approval/remaining budget, preserve the
   immutable ceiling and recover cancellation after restart. Replay, ambiguous PATCH,
   duplicate/rejected release and actual budget-boundary receipts are required. The current
   unsupported declaration is correct and unchanged.
5. **Fixture and input decisions requested:** exact Biotech SDL path/ref; authority for fresh
   `mct_*` databases/roles only on existing disposable PG17 `mc-ft-disposable-pg17` at
   loopback port 55433; actual owner binding selections; selected WSL/auth/repository setup.
   No answer was treated as consent. Existing app/Temporal databases and volumes were untouched.
6. **AWS and deployment:** read-only inventory found no VPC, cluster or ECR repository for
   this service. Select the network before concrete first-service creation. Fixed proposal
   target is account `298199649527`, `us-east-1`, namespace `mission-control-dev.ih0e7`,
   service `mc-worker-ai-engineer`, 0.5 vCPU/2 GiB, one base worker, zero inbound ports.
   Supply exact public config/image/build/binding, secret ARNs, origin and trusted manifests;
   review actual spend, resource creation and cleanup before any apply. `$40/month` and
   prior `$10` slices are ceilings, not current authority or known remaining funds.

Retained AWS/S3/secrets/provider sessions may incur charges after compute is stopped.
Unknown spend, missing cleanup and unresolved acceptance remain liabilities, not success.
The remaining sequence is to finish these named joins and exact owner prerequisites, execute the
authorized disposable proofs, then qualify S0, remote S2 and S3 in dependency order.

## Closeout

Implementation checkpoint: **`e3999d85d00b46c8de6d3bc05199819189ab2709`** on
`mo/run2-integration`. It includes 511 changed files; most added lines are the deterministic
Codex 0.162.1 schema fixture set. Local commit hooks passed large-file/conflict/TOML/YAML/JSON,
private-key, whitespace, Ruff lint/format, ty and dependency checks. Main and local origin/main
remain at `a2527f6f3c385a7f55272c41d90e6860b44781d0`; nothing was pushed.

Final targeted runtime/architecture checks passed (205 tests), authoritative typing passed
(797 files), and the remaining release/SDL failures are explicitly retained above. This is
not a passing broad-suite or mission-acceptance claim. The source tree was clean after the
implementation commit except the preserved unrelated `issues/bash.exe.stackdump`; this
report's evidence update is committed separately. Private receipts and all worker worktrees
remain retained. No unanswered owner-boundary request was treated as authorization.


### 2026-10-16 conclusive budget admission failure repair

Integrated source `dcd213a5e16a5be268718fe8970ed710cfa4ef16` (isolated `1c018ff0`) persists a verified hard-cap reserve rejection through a dedicated atomic StageGraph mutation. It marks the unadmitted candidate failed without inventing an execution attempt, producer liability, output or usage, then uses existing dependency/failure completion and reducer terminalization. Only consumed usage plus the proposed reservation beyond a declared hard cap is conclusive; reservation/pending-only refusals retain previous behavior. The existing `stagegraph_blocked` fallback for temporary liabilities without an active releasing child remains outside this repair.

Validation:145focusedunits (19new), authoritative mypy7sourcefiles, Ruff,31legacyhistoryreplays and3actualWindow2histories(16/43/31events), normalcommit hooks including ty/deptry passed. Root fresh restricted-role PostgreSQL test passed1/5.32s, retaining denial, repository restart, terminal FAILED and late activity retry. No provider or existing database access; disposable container removal verified. Replay receipt SHA`46520e184d30c46c1bd7f96a1555ed42041f557ec42a34bfb7c5be4a4d1f81a8`; PG receipt SHA`513c3e95a877908ebf51af0ecd95f6ed31d2a1b5a42658fe69a61910a3ea5dff`, both under ignored ee3-native-qualification validation evidence. Projection shape/digest unchanged; additive admission-request boolean defaults false, without claiming byte-identical request redumps.

Closed-workflow recovery remains unintegrated/unqualified. Final40focusedunits and8filemypy passed; the real observer decoded all3savedWindow2histories offline through a labelled fixture transport and reconstructed required run fields. First realPG test failed before authority reading because the fixture lacked persisted activation/attempt records; failure preserved, owned container removed, fixture correction pending. Existing Claude Window2 remains cancelling v9. No new paid/native execution or recovery mutation has occurred.


### 2026-10-16 closed-workflow recovery integrated, live action pending

Source `b6146b3af768003fc3318de51284d230e2fe169f` (isolated `7a96c511`) adds ordinary authenticated recovery POST/readback GET; guide commit `e5ba37cd1cdda6f3d91b38b8c5d0cb2c55b15469` documents exact permission/request/evidence/refusal limits. Trusted bounded Temporal history and PostgreSQL family/journal/binding/session/turn joins derive facts; the existing reducer owns cancellation terminalization. Request carries only UUID/version, no caller closure assertions. No restart, native dispatch, provider acknowledgement, acceptance or usage adjustment.

Root review corrected missing SELECT fields and the production dedicated native-session/turn column joins.40focusedtests/8filemypy passed before finalschema correction; final13PG-reader cases including unknown-turn/dangling-current-turn/JSON-only identity refused as expected, focusedmypy passed, normalcommit hooks passed. Real observer read all3savedW2histories via explicit fixture transport/reconstructed required fields (not fullDB/liveproof). Root real restricted-role PG4passed1/11.12s using production lineage/run/family/binding/journal/frame repositories, scriptedlane and mockedTemporal only; retained result replay and settled lane replay caused no additional native send. PG receipt SHA`4c219f847b651210dee4479da40b12ed2cbca378ce34b4ad180ac32055325c25`. All four disposable containers removed/absenceverified. PG1missinglineage fixture, PG2actualschema join error and PG3unknown-turn refusal are retained.

Exact-source canonical combined validation is running; liveW2 remains cancellingv9 until fresh authenticated recovery. NewAPI-only runtime/launcher preparation underway, no remote worker/ECS/native/provider start required. Final-source installation not yet performed. Source-only status does not qualify S0/S2/S3.


### 2026-10-16 actual closed Claude Window2 cancellation recovered

Exact integrated `e5ba37cd1cdda6f3d91b38b8c5d0cb2c55b15469` API-only runtime installed from wheel SHA`b5a61b83aee02096a125c85a2d7e8df3e0c50eca068931bccfc23a7e5676533e`,840packagefiles byteverified; combinedcanonical96tests passed. Installer1 refused existingCRLF-only status before writes; preserved, installer2 uses command-local newline normalization and exactrawbefore/afterhash checks. No source/config rewrite or oldenvironment replacement.

Fresh read-only exactW2admission SHA`05f4b6454939f787b71bdb1123f74a70d6db3c2d1fec2a39dd8b6b5bfe05c4d6` verified actual three closed executions and settled authority. The normal JWT API, with only scoped launcher `workflow_run.terminalize` added to a new public deployment projection, accepted request `a0f00ce4-06db-4b52-86fa-52cb9d83a702` (HTTP202). Exact authenticated result GET returned200 and terminal **cancelled v10** for `0f609fde-238d-5bab-b59a-52d07289ea9d`; actionreceipt SHA`cc3300d537601cc16a69d4273e3b6a3204583446ddfc1fbc2e05d0af9781a452`. No new cancel/native call/provider acknowledgement/human acceptance.

Independent restricted read-only PostgreSQL snapshot SHA`9804bdebbc0afe6a52023fabb24d5665563339b727af8a543c02672903250483` confirms cancelledv10, unchangedbudget/effects/providerframes, complete112976settledtokens, no pendingcommands/effects/ambiguousdispatch, no HumanGate, and original stale-target cancel rejection retained. APIownedPID39304 stoppedviaownnonce; exit0supervisor/child-15, processabsence and bothWindows/WSL18080closed independentlyverified (cleanupSHA`9cc5696f3233a805d2ec2613b2c31ad74206c91b27d3b7ddebba662122aaf2e8`). No worker/image/ECS/native/provider launch.

This qualifies the exact closed-workflow cancellation repair, not S0reportacceptance or the18placementmatrix. Full3genuinereview remainsapproved; nativefinaltail/control/fork/caller gaps persist. LatestAWSbudgetread03:54:43Z still reports0.763USDactual/1.52forecast against40, backendlastupdated00:43:14Z; delayednotinvoice. Conditionalproviderreserve remains3.85/10, historical221222missingledgertokens and priorfailedClaudeunknownusage retained. Next independentwork: CursorAuto/Grok4.7 catalogue/preflight preparation, no paid inference yet.


## Actual Cursor catalog and e5 source image checkpoint

Root executed one reviewed read-only Cursor SDK1.0.37 list_models call using existing CURSOR_API_KEY only via anonymous stdin (broker run_catalog_private.py). Receipt cursor-next-preparation/model-catalog/catalog-1/receipt.sanitized.json SHAe31e667980594560414c1523109812b3afdd8e84fa32da8074f4d2e533d0cedf:47models, Auto/default and Grok4.7/grok-4.7 present, agent_calls0; ownedPID54878 exited and port44605closed. Catalog is not inference entitlement/pricing/native qualification. Root selects ID-only as R22 requires; Grok observed catalog default500k/high/fast=true is not an effective-runtime claim. Optional parameter propagation deferred (not required by sprint), no source changes.

Local source build68740exit0 completed: source-image-builds/e5ba37cd1cdd-ad6509e755/receipt.json SHA3285ea387717adff75a6ad380e2e4a298f047f86e25ffff7ba7be2619ec77739, image sha256:7a126aa9dcc1e2df1aaf9360ff96cb77b0822b28b45d982063597c6f068d9083.888committedarchivefiles, uid10001/networknone/read-only/importsmokePASS, exactsmokecontainerabsencechecked. No push/worker/APIstart. C:26GBbeforebuild.

Root readonly published catalog14700exit0:170publisheddefinitions, all3agentprofiles are Claude and2Codex; Cursor absent at this snapshot. Evidence cursor-next-preparation/model-catalog/published-catalog.actual-1.json. Filter included invalid generic template kind, so no workspace-template absence assertion. Acceptance_map preparing normal Cursor registration/config drafts; helper_review inventory/prepared plan ready, C9actualcapture/scopedrecord/config stillpending. GenuineFull3review retained, W2cancelledv10 unchanged, matrix0/18,S2S3unrun,S4held. No paidnativecomputeactive.


## 2026-10-16T04:22:36.800798+00:00 Cursor capture diagnosis

Diagnosticcapture45336exit1 retainedcursor-closure-auto-2/error.sanitized.json: whole_source_worker_differs_from_wheel. Rootreadonly55863exit0 source-wheel-diagnosis-1.json proves840wheel/880source,0sharedbyte mismatches,0missing; extraexact40historicaladapters/postgres/migrations/0001-0040.sql. pyproject95-98 explicitlyexcludes theseSQLfromwheel. NOTnewlinefailure, noapplicationchange/reinstallneeded. Helper_review prepares narrowattestor fix retaining840exactinstalled/sourcewheel equality andindependent40source-onlyimmutableSQLpins; nogenericextraexclusion/guardweakening. Originalv3/v4failedattemptspreserved, noactive rootexecsessions/providerwork.

### e5 Cursor closure independently verified and preliminary config materialized

Independent recomputation passed for the actual Cursor closure on e5ba37cd: `cursor-next-preparation/e5ba-successor-preparation/cursor-closure-auto-verify-1/receipt.json`, SHA256 `97a6b3fd3dc110e91a49584c4cd820702e6f7d3622ccf343136d9fd7ebd92856`. The complete closure matched; no authentication, provider call, session or turn occurred. Actual installed wheel/source join covers 840 package files; the 40 declared historical SQL exclusions and 265 archive/source newline representation differences remain explicitly recorded, not normalized or hidden.

The typed Auto binding is now materialized at `cursor-next-preparation/configuration-preparation/configured-auto-v1/manifest-launch-bindings.json` SHA256 `52ff9fea4ccaa5ed63c162e7c10e75d15c11dc95fcea543a026635b8574711e5`, with host readiness still unverified. Preliminary configuration validation and materialization passed; actual generation report SHA256 `fc6fc036cccf27ae405accfa418a0af8a487d27dd4f455def5b784b13c6c2020`. It is limited to scoped API prerequisite checks, explicitly disallows worker use, preserves common component 1.4.2 and existing grants, and contains no provider credential. C9/M4, live Cursor execution and acceptance remain pending. S0 fully qualified matrix remains 0/18; S4 funding holds remain unchanged.

### Cursor Auto C9/M4 verified through normal API, 2026-10-16 04:49 UTC

The actual e5 native Cursor observer completed and verified its production-allocator cleanup fixture while preserving the protected repository root/files. Native observation SHA256 `deb48cad972de7d53995d1dd33b31ca17851a41a9cdb1fdaa261b4ad1bae804f`; observer receipt SHA256 `40cd6a481a2139df878836c5766f010475b0c0d534117898828a4d8c899ecca8`. No authentication/provider/session/turn was performed by the observer.

Normal authenticated API verification returned200 for actual scoped C9 and M4, followed by200 preflight with ready=true. Original responses and typed records are retained under `cursor-next-preparation/configuration-preparation/scoped-preflight-preparation/owner-verification-preparation/verified-owner-1`. Action receipt SHA256 `71701687803fd41283a8208f9dc2a8a70b49dc9da66a313f5f24ff4c5a992e26`; ready preflight SHA256 `377e3f346b5bc18d1804f11d1e94cc1142218fb0c5f872ce85e2ab945aac10bd`. C9 expires2026-10-17T04:44:35.510402Z; M4 expires2026-10-16T05:47:55.473160Z. M4 proves configured secret-broker resolution only, not provider entitlement or model execution. No human acceptance was created by these service actions.

M4 API PID59762 was stopped through its exact nonce; independent process/listener cleanup passed at04:48:39UTC, receipt SHA256 `038d11b6d4e9d6d66e8b33ec51951cd2fee974e2fc1d014bf13a788ad98fab2b`. No owned API, worker or new provider session remains active. Latest budget read04:47:59UTC reports AWS actual$0.763/forecast$1.52 against$40; backend timestamp remains00:43UTC, so this is not final invoiced cost. Conditional provider reserve$3.85/$10 and unknown historical provider cost remain unchanged.

Current criterion-to-evidence checkpoint: `CRITERIA-CHECKPOINT-2026-10-16-0449.json`. This milestone is prerequisite readiness, not S0 execution acceptance; fully qualified matrix remains0/18. Final worker configuration, bounded local-proof policy, deployment/pollers, native output custody and actual model run remain pending. Existing user authority covers bounded qualification runs; the source local-proof policy must be explicit and scoped, never presented as qualified=True or production qualification.

### Cursor local Send compatibility repair, 2026-10-16 04:56 UTC

Before paid execution, inspection of pinned cursor-sdk1.0.37 found that vendor `sdk-service.js` rejects every nonempty local Send `idempotencyKey` as cloud-only. Mission Control was forwarding its internal dispatch key. Canonical commit `a8d69c5b48506c6babcd7f3f74f0b92716423091` removes only that unsupported vendor-wire argument from SdkLocalBridge.send. Internal dispatch keys, durable journal, sent-key acknowledgements and ambiguous-send reconciliation remain intact; cloud routing is unchanged and no retry was added. Local adapter prose now correctly distinguishes internal idempotency and detached native lifetime.

Validation:47 focused Cursor tests passed (actual AsyncAgent request serialization, both force modes, one Send; local reconciliation/fencing/active-bridge recovery and cloud reconciliation), one existing LangSmith deprecation warning. Ruff check/format and authoritative mypy for both changed source modules passed; normal commit hooks including ty/deptry passed. Independent read-only review found no blockers. No paid model call was used to discover or validate this defect.

All previous e5 captures, C9/M4 verification and ready preflight remain actual historical evidence for e5 only. The e5 final-config validation passed but was NOT materialized. It must not authorize a8 launch. Fresh isolated a8 runtime/source-image/closure/host/config qualification is now required; existing e5 runtime and all receipts are preserved. Current owned API/worker/provider compute remains stopped. Native SQLite observer and detached bridge containment helpers are being prepared before any paid Cursor run. Current Git dirty docs and unrelated index/stackdump remain preserved.

### Repaired a8 runtime and image verified, 2026-10-16 05:05 UTC

The isolated a8d69c5b4850 runtime installation completed: 840 installed package files exactly match wheel SHA256 f1d839112522dfd5b7ced93c475ea7310de847f4993637f3b1c1dc72321447af, frozen dependencies and API/worker/recovery imports passed, source remained unchanged. Runtime receipt SHA256 071fae24116502c6b13eab3c1ae72bd81e6bafd6a68d6a52c0ad11fa44bb4f84, under cursor-next-preparation/a8d69-successor-preparation. Existing runtimes were preserved.

The local committed-source image build/import smoke passed: image sha256:0e28153c6bacc1e10604e14da2935e67f4a0ed597cf0a3baf704b117c4dd61ba; source-image-builds/a8d69c5b4850-0f3462b51a/receipt.json SHA256 42b33b4039b64e8ce2da8fa017160f34a7a57961e9d6032e0b03a42b26cbca2d. Smoke used nonroot UID10001, read-only filesystem, no network, mounts or credentials. Exact smoke-container absence independently checked. Image not published/deployed. No new provider run or active owned API/worker.

Fresh a8 closure and configuration preparation is in progress. Native SQLite observer v1 is explicitly blocked: static vendor schema review found uppercase persisted statuses and additional event-envelope/path/byte-bound checks needed. Temporary WAL fixture passes did not establish compatibility; v1 is preserved and must not run against actual native stores. S0 fully qualified matrix remains 0/18; approval receipt and funding/publication holds remain unchanged.

### a8 closure and scoped API evidence, 2026-10-16 05:21 UTC

The a8 complete Cursor runtime closure captured and independently recomputed equal, with zero provider calls. Closure SHA256 b4e64772fe880aba3cb368894189c87bf1106954732874e24321379e978128f7; verification receipt 3838c28d9260dda498f288676b8d96ede131e993290bd24b785e62b2ee18ce1a. New typed Auto binding SHA256 74e36ce261eb6c3cdfedf6e5dab23d5134ce36982f338d9130b950a734efbf04; preliminary API-only configuration validated/materialized. Final configuration helper review and five offline tests passed, but final owner proof/configuration is still pending.

Normal a8 API compile returned200; preflight422 correctly identifies new C9 cursor_local.owner.c9.9dcb5b0442e90e3bc054f4da as unmet. Existing same-scope M4 remains genuinely verified from earlier normal API evidence, not a newly invented record. Both actual records were retrieved read-only. Keyless API PID63737 stopped via exact nonce and process/Windows/WSL listener absence verified05:19:41UTC. Actual a8 host observer is running under session84726, output e5ba-successor-preparation/cursor-observation-a8-auto-1 (directory location is historical; actual source identity is a8). No paid Cursor run, owned worker or cloud deployment active. Full evidence pins are in CRITERIA-CHECKPOINT-2026-10-16-0521.json; S0 remains0/18.


### 2026-10-16 05:35 UTC — a8 final configuration

Actual a8 host observation completed, followed by normal C9/M4 verification (both HTTP 200) and ready preflight. Both owned verification APIs stopped, with independent PID/listener absence checks. Final configuration materialized successfully; generation report SHA256 `fe9ae0c26e1b7d349f6b7e62b91b8861f2f2d09f168b52e1cf787cd03cfaac41`. Exact references are retained in `CRITERIA-CHECKPOINT-2026-10-16-0535.json` under the resumed evidence directory. This supersedes the earlier running-observer checkpoint without altering its history. No paid Cursor execution, operator image publication, cloud worker start or new human acceptance occurred. S0 remains 0/18 fully qualified cells. Final configuration keeps qualification and worker authorization false. Build-guard path correction and controller/cloud reviews are in progress.


### 2026-10-16 05:43 UTC — a8 immutable operator publication and registration

Operator image passed public-input smoke and zero secret-sentinel matches; the never-started scan container is independently absent. Published immutable ECR image digest `sha256:a8c0890a7f4bf8bade713757e5b99b8fc5ef80fc7f061040f2899b32a5ea92d3`; temporary registry credential removal verified. Actual task startup reference check passed in a nonroot/read-only/network-none container, with container absence verified. Registered actual task revision 14 exactly once after matching stopped task13 baseline. No cloud compute, local worker or paid Cursor run started. Root reserved an additional conditional $1.00 within the existing $10 slice (aggregate $4.85; actual invoice unknown) for one bounded 480-second local Auto attempt, still requiring real runtime/readiness/custody checks. Full S0 qualification remains 0/18. Exact artifacts retained in resumed `CRITERIA-CHECKPOINT-2026-10-16-0543.json`.


### 2026-10-16 06:02 UTC — first a8 window stopped before native launch

Normal API was healthy and cloud task14 reached RUNNING. Lane execute refused before creating its output directory or worker. Isolated read-only/public precheck and credential validation passed; isolated observer delivery identified exact failure at observer_delivery.py line46: generated deployment omitted the previously authorized service:run2-s0-observer grant (only human and launcher grants present). Refusal occurred before observer sign-in. No mission submit/start, Cursor inference or Temporal promotion occurred; queue inspection correctly refused missing lane queues. Root stopped API PID66408 via owned nonce, independently verified process/listener absence, and stopped cloud through reviewed exact-task shutdown (stopped_verified). Prearmed observer PID66504 interrupted through verified pidfd; absent, no native bridge captured. Independent cloud watchdog given its own early STOP nonce after verified shutdown. Historical receipts preserved; exact checkpoint CRITERIA-CHECKPOINT-2026-10-16-0602.json. Next: restore the existing authorized observer grant with fresh config/proof custody and review dependency changes before a new bounded window. Qualification remains0/18; conditional reserve4.85/$10, actual invoice unknown.

### 2026-10-16 06:12 UTC — observer correction preparation

Prior task14 watchdog confirms stopped_verified, desired/running/pending 0 and no active tasks. Clarification: the original lane invocation did not retain a granular phase record; the isolated observer diagnostic independently proved its missing-grant assertion before authentication. That diagnostic does not prove the original invocation failed at exactly the same phase.

Fresh final-configuration-preparation/deployment.observer-restored-1.json SHA4585029c77b4d820e684f7c7f9d34053974f580f249084ad81432d56abe28238 differs from the actual a8 preliminary Windows deployment only by appending the existing observer grant SHA5e8d195fd81b3926ee947ea22fb46938480d222b728b8cbdd7cb55d90f203bba. Human and launcher grants unchanged. Genuine observer authentication passed with workflow_run.read only; token cleared, never printed/persisted. Receipt observer-auth-restored-1.sanitized.json. No worker/provider inference/mission start. Fresh normal owner verification is required because final generation binds its journal to the exact deployment SHA. Initial proof-refresh public input preparation failed default-only validation (Windows newline hash mismatch); preserve it and use reviewed fresh v2 inputs. Qualification remains 0/18; no new human decision requested.

### 2026-10-16 06:21 UTC — corrected observer configuration ready for next window

Normal API owner verification and fresh preflight passed under corrected deployment4585029... at AV/verified-owner-observer-1; M4 expiry07:13:58.874484Z, unchanged C9 expiry2026-10-17. Verification API PID67673 stopped through own nonce; process absent and WSL18080 closed. Refreshed final report6165a534b9cdb8824956c2f6c3c803bf5fad218c327955002cc44109537ac4ff, environment00e4b5093c4d3d95060f4001bacc5272f8ecab51c312ec13e5b62e33fdf00b13,146files; only deployment.json differs, semantically exact existing observer append (typed set ordering normalized for comparison only). Local policy6424f9547b9c99f3a8b43e92aed57ab04a516ff3f3cf6a1a9569cdc879cea826 binds one480second attempt, expires07:10Z. Conditional reserve unchanged4.85/$10, unconsumed Cursor1.00 reused, actualinvoiceunknown. Fresh AWS read06:16 UTC unchanged. No provider inference or mission.

Verified operator image sha256:d3cfe81298aa37e998fda3d86317bc7dcfa62af1092337e476a534ac1b175851, receipt deployment-preparation/operator-build-1792131359322258800/receipt.json ff1d83079cde04db460c41af60e0147b4896dfc049b3b38533e2234390435b19. New deployment-observer-successor/cloud publication1959eed9bb769c30db86d8857e3fd61c749b893c1ea4df1f2ba294b2a91effd1 points immutable ECR digestsha256:ad7768083ec1b5e1b51a590b5ca51bece108ce120eb4166ab0340199305ce31a. Startup-reference smoke passed nonroot/read-only/networknone; no provider/network/worker; containerabsenceconfirmed. Actual registered task15 receipt9bf062ef2d25e73fbaeb4b2b2fc20804543504b25dc1ce7cbcfd897af1159675; compute NOT started, service remains stoppedtask14 until explicit next start. Local successor sealed receipt e5fcdff15d93fd0a0204cf99a0f5a578704ee09ebdbf4c3e7c84040dfe883a74 independently approved; original/pending helper history preserved.

Next actual ordering: cloud/API ready, then prearm600/lane480, inspect all16queues with matchingpollers, actual promotion/readback, freshreadiness, controller180. Do not inspect full16 before local lane exists; missingWSLqueue is expected. All acceptance remains0/18.


### 2026-10-16 06:30 UTC — first observer-corrected window stopped, timing blocker

All16queues became ready after lane bootstrap; actual Temporal promotion to0.1.0-a8d69c5b4850 verified at deployment-observer-successor/cloud/temporal-promotion-1792131935822273300/receipt.json. Readiness retained passing APIhealth/preflight/compile, ECSexacttask15/image,16currentpollers,readonlyDBzeroadmissions/nativecalls and process/watchdog facts. Final guard refused only insufficient remaining margin:340.623836seconds vs360required. No mission submitted/start/native inference. Full evidence LOCAL/readiness/actual-readiness-1, exact reproduced guard in join-diagnostic-1.json.

API68388/lane68565/observer68486 stopped by exactnonce/pidfd identity; all absent, WSL18080/47555 closed. Cloud shutdown-1792132058799361700.sanitized.json stopped_verified; ownwatchdogSTOP then shutdown_invoked/noactivetasks. Service stoppedtask15; Temporalcurrenta8 remains. No more automaticretry. Root prepared authorized600lane policy4a9fe0de1f18a1b6f14c1ee8f155d201c37ff7356a73c9b9bcf7dea31371e69c, expires07:10 beforeM4expiry07:13:58. Same20k/30tool/singlemission and existingunusedreserve4.85; observation180+cleanup180 preserved. Agents preparing freshlocalwindow2 (armwait900, actualnativeobserve<=600) and exactsame-task15 restart lifecycle; no new image/registration required. Qualification0/18.


### 2026-10-16 06:47 UTC — window2 submission denied; restore historical sponsorship

Window2 passed actual readiness3a4e09e8e39ec9d81bfa2fdc0b5aca01c8aff9692b658594cb493f0254e58b80 with exact600second lane,16queues and margin. Defaultcontroller caught a nested staleobservermanifestpin; root preservedoldguard/spec, fixedonly already-reviewed ownershipSHAe9105836...; independentreview approved, guard e70f9d... spec2 b0336d... . Actualcontroller authenticated, preflight+compilepassed, then submitrequest4ce37290-20ab-49fa-87ad-2425106a23a5 returned AUTHORITY_DENIED/no_sponsorship. No runID/start; source manifests_submit328-339 and regression confirm thisguard precedes run/program persistence. No blind retry. PriorreadyDBzero known; source-backed deniedsubmit not relabelled accepted.

Window2 API69349/lane69588/observer69510 stopped/absent, ports18080/47555closed. deployment-window2-preparation/shutdown-1792133030920438800.sanitized.json stopped_verified; watchdog ownSTOP completed stopped_verified. Cloudremainsstoppedtask15; Temporalcurrenta8 retained. Nativeinference0 fornewCursor attempts; reserves4.85 unchanged.

Bothreviewers traced exacthistorical launcher sponsorship:run2-s0-ai-engineer in successfulb9/f70/ee3 configs and handoff. Root fresh AF/deployment.sponsorship-restored-1.json4376afaf984fc3ab4593e655696205983033b545db86f277c66157c2e92b477f restores ONLY that reference from N/final-ee3/deployment.jsonf51076...; permissions/human/observer unchanged, NOadmin/DB/credentialchange. Fresh sponsored proofAPI starting, finalreport expectedfinal-auto-a8-sponsored. Agents prep newsponsoredlocal600/900packet and cloudtask15baseline; no assumednewrevision. Source/runtime/closure unchanged. Acceptance0/18.


### 2026-10-16 06:59 UTC — sponsorship correction verified and registered

Genuine launcher JWT now verifies existing sponsorship:run2-s0-ai-engineer with mission.author and unchanged permissions, no admin; receipt sponsorship-proof-refresh-preparation/launcher-sponsorship-auth-1.sanitized.json. Normal C9/M4 verification and ready preflight passed under exact corrected deployment4376afaf...; M4 expiry07:48:21.830486Z. Proof API70258 stopped through own nonce; PID absent and port18080 closed. Fresh final reportef61aa405f5e98b75dba363619b37bd44ceab45e5e922982308318645e9cfedf, policy6b78f543... authorizes one600-second local attempt until07:45. Only existing launcher sponsorship restored, observer/human/all permissions preserved.

Operator imageb500ac4e... passed22599-file scan with zero sentinel matches and offline smoke; scan container removed. Immutable publication6f37fe94c8412292f1f4bc13b2207dc430f415c9b074392b8fa97e624c460264 and exact task startup smoke passed; all test containers absent. Actual task16 registered once, receipt79cedbf43292d175e2f2f24c5cf6eea4eac714be4bd7dcbd76b5b1722ebc213f. No cloud compute started. Budget read06:55 confirms service stoppedtask15, AWS actual0.845/forecast1.602/$40 with delayed accounting; reserve4.85/$10 unchanged, invoiceunknown. Sponsored local packet independently approved preparation; sealed actual pins97b8b53... undergoing final review. No new Cursor inference/run/humanacceptance; qualification0/18. Exact checkpointCRITERIA-CHECKPOINT-2026-10-16-0659.json.


### 2026-10-16 07:10 UTC — admitted pending run; observer identity correction

Sponsored readiness307766b0580d3a50a985d217a40eb8cdfcfd4f3761cf05031b2c7ed2ace8f212 passed all16queues/currenta8/actualtask16/API/lane600/margin. Actualsubmit657d723e-7ab4-4368-9509-a7357c612323 succeeded: publicrun60f44a50-c0e4-5edb-ac13-0fb0436aaedb, internalrun_uuid01a14386-3bb2-7dd0-ba2b-f33d0eaa2053. Controller stopped BEFOREstart at native_supervisor_failed_stop_paid_observation: observer wrongly queried mission_run.run_id using publicrun_key. Independent normal scoped readonly canonical.run_row at07:07 confirms actualpending/v1/harness0; no native inference. Do not resubmit or mark failed/cancelled; this is an actual pending admission.

Owned API71101/lane71212 stopped through ownnonce, arm71107 through verifiedidentity/pidfdSIGINT; all three absent,18080/47555closed. RuntimePython lacks pidfd_open; root used systemLinuxPython after initial no-action AttributeError. Task16 shutdown-1792134262508282300.sanitized.json and ownwatchdogab538d... bothstopped_verified. Reserve4.85 unchanged, actualinvoiceunknown. Source/runtime/config/operatorimage unchanged. Two Sol agents preparing isolated identity-correct observer and explicit same-pendingrun recoverycontroller/readiness under identity-recovery-preparation; root prepared same-task16 lifecycle c4a15e... with4mockchecks, no newcompute. Recovery must maximum_new_runs0, one exclusive per-run start fence, fresh exactpending identity/binding/commands/noharness checks, then ordinary API start once. No SQLrepair/identifier substitution/weakeningzero guard. Qualification0/18. CheckpointCRITERIA-CHECKPOINT-2026-10-16-0710.json.

### 2026-10-16 07:36 UTC — continuation error contained before start

The same pending Cursor run was not started. Recovery controller execution failed with UnboundLocalError because an inner asyncio import shadowed the module import before its first use. The preserved journal records start_attempted=false and no cancellation. Exact API72810/lane73041/observer72805 are absent; ports18080/47555 closed. Task16 shutdown-1792135990258440800 and its nonce-triggered watchdog both report stopped_verified. No Cursor inference, new admission, or acceptance occurred.

A separate recovery-v2 removes the inner import. Eight mocked execute tests reproduce the original failure and verify two fresh pending checks, exactly one normal start, zero submissions, and refusal on observer failure. Independent review approved the fix; operational readiness is still pending. Preserve the original per-run start fence across helper versions. Refresh normal prerequisite evidence before a new bounded window; do not extend stale proofs. Source/runtime/config/task16 remain unchanged. Qualification remains 0/18; conditional reserve $4.85/$10 and provider invoice unknown. See CRITERIA-CHECKPOINT-2026-10-16-0736.json.


### 2026-10-16 07:50 UTC — corrected observer verified; pre-start API read timed out

Fresh normal owner verification and preflight passed; C9 original native expiry retained, M4 expiry08:39:04.595223. Explicit fresh-proof join preserves historical config/image/task16. REC2 independently reviewed; readiness27f40bda passed all16queues. Exact pending identity/v1/zero harness/commands/activations/bindings verified07:48:40. Corrected observer DB handshake passed07:48:49. The subsequent pooled final_pending_inspect timed out at5seconds before start; initial CLI inspection succeeded in6.55seconds. Start fence remains absent; no native inference or cancellation. No blind retry. API74422/lane74534/observer74451 absent; ports closed; cloud-v2 shutdown-1792136950060915500 and ownedwatchdog stopped_verified. Diagnosing API read latency/observer interaction before successor. Qualification0/18; reserve4.85 unchanged; invoiceunknown. CheckpointCRITERIA-CHECKPOINT-2026-10-16-0750.json.


### 2026-10-16 07:58 UTC — API-only baseline confirms inspection exceeds five seconds

Reviewed diagnostic helper eb7153b0 performed two normal GET inspections plus commands/reviews reads, no mission mutation/provider call. Actual receipt9a80a6e66df68c698415f1fb4db6c655c7aa8a0d255d61849f8beb48de6e469f: HTTPinspection2.297s and5.266s, both200 exactpendingv1/session0/frame0; commands0/reviews0. Fresh clients and noobserver/lane/cloud isolate baseline but do not diagnose SQL or pooledconnection reuse. Diagnostic API75065 stoppedthroughnonce; PIDabsent/portclosed. All runtime compute stopped. REC3 patch-only preparation will align prestartinspection with boundedCLI30/40, add400sec pre-fence runtime margin, and bound poststartinspection15sec within unchanged180observe/180cleanup deadlines. Preserve original globalfence/source/config/task16; no new nativeattempt or qualification. Freshproof/operationalpolicy will need explicit renewal before nextactualwindow.


### 2026-10-16 08:30 UTC — accepted Cursor start, controller defect, bounded containment

The existing admitted public run `60f44a50-c0e4-5edb-ac13-0fb0436aaedb` started once: Temporal run `01a143c9-1e17-72b3-9698-9c3f20a1a12c`, accepted at 08:16:57 UTC. The global start fence is claimed: no start or submit retry is permitted. REC3 incorrectly classified the first post-start `pending` projection as inactive and exited; the native observer ended before the actual lease appeared. Subsequent normal API reads proved active v4, one harness and native session `agent-73162e55-750b-4f76-8762-ebee7c6dcead`. This is actual native activity, not zero inference.

Immediate cancellation was rejected with HTTP403 because active-work immediate cancellation requires admin. No permission escalation occurred. After fresh command/REVIEW/state checks, normal cancellation `6a5398e3-2a73-4351-a354-a24a9a4ddc4b` was accepted and delivered at 08:25 UTC; last API inspection remains cancelling v5, not terminal. The lane watchdog stopped its owned worker, but a detached Node bridge survived. Root obtained the exact read-only database lease/workspace/harness join, verified pinned executable/script, boot/start/argv identity, and sent SIGTERM through pidfd to Node76907 only. Node76907 and shell76904 were absent afterward. No signal was sent to their unrelated WSL relay parent. Provider-side stop and final usage remain unverified.

Task16 cloud compute is independently stopped_verified (desired/running/pending0 and no active tasks), including its own watchdog. API owned-stop requested; independent local process/port audit pending. All prior receipts preserved. Evidence and hashes: `identity-recovery-preparation/post-start-containment-checkpoint-1.json` and `post-start-containment-1/`. Qualification remains 0/18 S0; this attempt is recovery evidence, not acceptance. Next: finish native usage/custody and durable cancellation settlement; repair pending classification and observer wrapper/process grammar offline before considering any new paid execution.


## 2026-10-16 user-requested session close and fresh-session documents

The owner requested two comprehensive documents and an end to this session after usage exhaustion. Read SESSION-END-2026-10-16-MISSION-HANDOFF.md and SESSION-END-2026-10-16-MULTI-PROVIDER-SURVEY.md in the resumed scratch directory. They consolidate current code, actual evidence, outstanding acceptance and safe continuation. No new live attempt was started for this closeout.

Newer independent evidence supersedes the earlier pending cleanup audit: exact API/worker/observer/Node/shell PIDs absent, ports18080/47555 closed, no readable exact-workspace process match; cloudtask16 and watchdog stopped_verified. Native Cursor SQLite shows FINISHED08:20:51.998UTC for agent-73162e55-750b-4f76-8762-ebee7c6dcead / run-2df4a451-c80c-4814-843c-3cc542048c2f, reported total926070tokens and2946byte result digest. Durable cancellation last cancellingv5; final ledger equality/custody/mission settlement unproved. Readonly ledger diagnostic ended TypeError, no mutation. Private result capture unfinished. The offline controller-lifecycle-repair-preparation was interrupted by agent usage exhaustion and has no completed review/test receipt; do not execute it. Both documents preserve these limits.
