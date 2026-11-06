# RUN-2 continuation state and next packages - 2026-10-16

This is the current candidate-work checkpoint. It supplements the eight operational records and [live-family recovery proposal](RUN-2-LIVE-FAMILY-RECOVERY-2026-10-16.md); it does not authorize shared reconciliation, activate workers or qualify the sprint. The original completion plan and acceptance criteria remain binding.

## Provenance and validated state

Both checkouts remain at `a8d69c5b48506c6babcd7f3f74f0b92716423091`: canonical branch `mo/run2-integration`, isolated branch `mo/run2-completion-offline-20261016`. At **19:44:45Z**, all **45 canonical v4 owned-file hashes matched**, with no canonical writes. v5 remains isolated. Historical v1-v4 manifests, archives, reviews, inherited dirty files and other worktrees remain intact. Evidence below is under `.scratch/run2-completion-20261016/continuation-v5/` unless stated otherwise.

| Evidence | Verified result and limit |
|---|---|
| `combined-final-r4.json` / `.txt`, 19:40Z | **677 passed, 10 skipped**, seven dependency warnings, 119.70s pytest /125.047s wrapper. Credential-scrubbed, provider-free selected regression; source hashes unchanged. Fresh short local Temp root removed. This replaces the four long-path Git fixture failures as the final selected-suite outcome. |
| `linux-final-tests.json` / `.txt`, 19:29Z | **28 passed, 4.02s**: actual POSIX private-reader10 and registry18. Exact temporary fixture removed; source hashes pinned. These cover platform-specific checks skipped on Windows, not every Linux/native acceptance case. |
| `postgres-context-r3/postgres-receipt.json` | **1 passed, 27.58s**, actual PostgreSQL17 restricted-role context fixture. Production admission/frame/binding/journal/context joins and historical projection are exercised; no shared database. Exact nonce-owned512MiB/0.5CPU container/network removed. |
| `mypy-final-r3.json` | **18 source targets passed**, imports followed with `--follow-imports=silent`, 3.234s. Not a repository-wide type qualification. |
| Final Ruff/check-format and owned diff check | Eleven edited files passed; inherited `RUN-2-REPORT.md` CRLF/trailing-whitespace findings remain untouched. |
| `private-retained-reader-final.json` | Approved original POSIX R1 custody unchanged:2946 bytes, response digest `2e4aac0d29aae546e783667baef26ec7850b3f34586d62908f1f66171e194a7c`, total926070 tokens, costNone. No raw result export, original SQLite access, artifact stage or native/provider action. |
| `installed-pending-context-dryrun-r3.json`, 19:12Z | Actual installed read-only typed context validated: CLOSED failed operation, RUNNING family, original activity3/event33/attempt27 and delivered cancellation. No adoption, owner claim or shared write. |
| `recovery-principal-read.json`, 19:27Z | Existing AWS principal and runtime/family database logins verified read-only. Exact response destination HEAD404. Does not prove S3 PUT rights or application actor authority. |
| `installed-effect-plan-read-r4.json`, 19:51Z | Actual context revalidated, pure original-host prediction verified all three payloads: response2946B/output1657B/manifest881B. All three exact destinations HEAD404. One settlement ID, known926070 tokens/unknown cost and slot1/attempt1 release predicted; zero payload/shared writes. |
| `r2a-operator-receipt-2.json` / `root-operator-review.json` | Default-off ignored operator composition: **11 focused checks passed, 21.21s**. Real core constructors with recording/fake ports; exact source/module origins, request/proof, two command IDs and three content/address/media pins. Not an installed I/O test or application grant. |
| `exact-history-replay.json` / command receipt, 20:06Z | Exact family38/root16 events replayed locally with candidate workflows and production sandbox, one executor, **10.625s** total. Recorded frontiers/source unchanged; no live poller, workflow mutation, DB/S3/provider call or raw history export. Past-command compatibility only; build routing and future task guards remain open. |
| Independent Sol reviews | Pending-mode invariants, canonical typed-blueprint correction, final typing delta, private pure-prediction equivalence and W0-W10 inventory reviewed. Review limits and final hashes are retained. |

Do not sum overlapping test selections. Earlier505/163/PG/Temporal receipts keep their original scope and source revisions. The combined-r3 sandbox attempt reached its180s bound after four tests and refused redirected-Temp cleanup; host inspection found no owned leftover process/directory. That failed attempt is retained, not counted as passing coverage. The final r4 used the approved short Temp parent and completed successfully.

## Current capability matrix

| Package | Current state | Remaining gate / exact next owner boundary |
|---|---|---|
| W0 provenance | Done for retained snapshots; candidate freeze pending | Integrator: new v5 manifest, final source/doc/review pins, fresh exact canonical preimages; preserve v4. |
| W1 controller/R1/G1 | R1 verified; component proofs partial; full G1 unqualified | Host owner: new ignored supervisor adapter/tests, then explicit registry + normal API + independent capture/custody + exact owned-pair cleanup composition. Existing fixture/live gates stay closed. |
| W2 accounting | Implemented and selected regression checked | Integrator: preserve exact total/cache/cumulative semantics, unknown dollars and attributable prior spending; original native accounting acceptance still applies. |
| W3 managed/recovery/caller joins | Isolated settlement-only source checked; protected recovery unexecuted | Recovery owner: finish actual bounded R2A writer/principal/effect/before-image/readback envelope; R2B separately owns normal Temporal delivery of the original failed request. |
| W4 data/ingress/release readiness | Installed1.4.2/37 receipts/six roles previously read; current context schema verified | Recovery/integrator: exact scoped liabilities, seeds/config/queues/checkpointer/ingress/custody and final deployment readiness. No migration reapply or generic backfill is indicated. |
| W5 standalone CLI | Source partial; LS07/08 unqualified | Existing CLI worktree owner: status/verifier truth, Codex sandbox setup diagnosis, Cursor CLI auth and Claude subscription limit under existing account constraints. Preserve other owners' dirty files. |
| W6 S0 | Unqualified | Qualification owner: original18 local/Cloud caller-lane-placement cells after full G1/R2 and exact build/principal/readiness. No protected rerun. |
| W7 remote R/S1 | API authentication/catalog ready; runtime unqualified | Deployment owner: exact disposable test deployment/rollback, compatibility and normal API/custody; original laptop-off24h and two-mission acceptance. |
| W8 S2 | API ready; Managed runtime unqualified | Qualification owner: actual saved object/environment/tools, approval behavior, held-budget/readback/resume, restart/cancel/cost and both original missions. |
| W9 S3 | API ready; hosted runtime unqualified | Qualification owner: exact original hosted API/model envelope, required actions/approval/steer/cancel/current-turn bytes/restart/cost and both missions, after S2 prerequisites. |
| W10 integration/release | v4 integrated; v5 candidate checked; release unqualified | Integrator: guarded candidate apply, applicable full source/type/architecture/data/native/remote/cost/cleanup/doc gates. Missing Biotech SDL/data remains explicit. |

## Dependency-ordered work packages

1. **Finish recovery preparation.** Own only the new ignored R2A action envelope/operator composition and the live-family proposal. `r2a-action-envelope.json` now enumerates all three exact payloads, principal/request/proof/source joins, effect order, deterministic settlement/command/frame IDs and before/after domains. The default-off operator composition is reviewed and checked with11 cases. Remaining work is actual bounded payload/private/database I/O and overwrite/race/owned-process proof, complete before-image/readback, and explicitly authorized audit actor. The predictor/prepared composition does not authorize staging or reconciliation. Require fresh pins before any separately approved consequential action.
2. **Complete the actual G1 join.** Own new ignored `g1_host_supervisor.py` and focused tests first, then a separately reviewed orchestration seam. Reuse existing lifecycle ordering, canonical global registry, bounded normal API and retained pair. Demonstrate independent observer health, final native tail, immutable private custody, stop/exit and exact listener absence together. Normal API origin/principal remains a concrete prerequisite; SDK/Temporal authentication is insufficient. Do not label pair containment as all-descendant containment.
3. **Freeze and integrate reviewed v5 source/docs.** Final acceptance evidence above supersedes the earlier path/type/context uncertainties for its exact scope. Prepare a NEW immutable candidate archive/manifest; compare against v4 preimages and all unowned tracked baselines before any owned overlay. Guard new paths against preexistence. Preserve inherited reports, ignored/private custody and other worktree contents. No reset, clean, commit, merge or push follows automatically.
4. **Execute eligible ordinary qualification and exact approved recovery when prerequisites hold.** One heavy/native/test lease, lead plus at most one Sol worker, measured1.5GiB available before start and existing tighter in-flight guards. Native sessions/actions must retain exact IDs after ambiguity. Original budgets are already authorized and inclusive of attributable prior spending; do not ask for them again. R2A shared writes and R2B deployed/shared consumer activation still require their exact reviewed consequential-action authority.
5. **Close original release gates.** G1/R2 precede S0; R precedes S1, then S2/S3 according to their unchanged prerequisites. Require final source/data/migration-readiness/ingress/regression/cost/cleanup/document evidence and every original native/two-project/two-mission/remote acceptance condition. Production actions remain explicitly gated by authority.

The first three packages have independent static portions and disjoint file ownership. Run their actual tests/native checks serially. Detailed static maps are retained as `w0-w10-independent-gates.md`, `g1-assembly-joins.md` and `r2a-composition-map.md`; they distinguish source observations from parent-reported runtime evidence.

## Stop/go and do not redo

- Stop on changed HEAD/preimages/identity/generation/owner/dispatch/cancel/pending proof, unproved private provenance, positive unresolved currency liability, unexpected destination/task, denied access or insufficient measured headroom. Preserve partial receipts and use exact forward readback; no replacement request/claim or direct SQL rollback.
- The last read found only the protected root/family Running, one pending activity and no pollers. This visibility snapshot is not an atomic exclusivity barrier. Build compatibility denial remains unknown and must not be bypassed.
- R2A replay after a later R2B completion/head advance is not qualified by the existing result-head proof. Fail-closed refusal must remain explicit; do not promise automatic replay through arbitrary completed-family descendants or resubmit protected work.
- Preserve all five existing protected Docker containers/volumes. Ordinary startup was authorized; no memory-cap change, WSL shutdown, user-session/process-name kill or service teardown is authorized to manufacture headroom.
- Do not redo proven component suites without a changed input/failure, reapply migrations/seeds generically, reinterpret API catalogs as runtime qualification, or use tests to invoke real providers. Do not spend merely to consume an allowance.
- Do not expand into next-stage capability evolution, Knowledge Services, AF-FOLLOWON-01 or a replacement supervisor framework. AF-FOLLOWON remains excluded and manual.

## Related operational records

[Execution ledger](RUN-2-EXECUTION-LEDGER-2026-10-16.md) | [Remaining gates](RUN-2-REMAINING-GATES-2026-10-16.md) | [G1 acceptance](RUN-2-G1-ACCEPTANCE-2026-10-16.md) | [Reconciliation](RUN-2-CURRENT-RECONCILIATION-2026-10-16.md) | [Qualification envelopes](RUN-2-QUALIFICATION-ENVELOPES-2026-10-16.md) | [Integration](RUN-2-INTEGRATION-2026-10-16.md) | [Resumption and approvals](RUN-2-RESUMPTION-AND-APPROVALS-2026-10-16.md) | [Operations boundaries](RUN-2-OPERATIONS-BOUNDARIES-2026-10-16.md)
