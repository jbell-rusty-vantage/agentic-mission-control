---
type: Planning Assessment
title: "Run 2 prioritized findings and minimal design corrections"
description: "Source and retained-evidence findings, independent Sol review, provider semantics and the smallest changes needed before qualification."
---

# Prioritized findings

Read with the [assessment](RUN-2-COMPLETION-ASSESSMENT-2026-10-16.md) and [work packages](RUN-2-COMPLETION-PLAN-2026-10-16.md). Source references are repository-relative at HEAD `a8d69c5b48506c6babcd7f3f74f0b92716423091`, with hashes in the evidence manifest. `B` denotes the ignored `.scratch/materialization-observation-2026-10/run2/resumed/`; `IR` denotes `B/cursor-next-preparation/a8d69-successor-preparation/identity-recovery-preparation/`. Keep raw bodies/tokens/native stores private.

Severity: **P0** blocks new paid/operational work because ownership/accounting containment is unresolved; **P1** blocks a required acceptance/release claim; **P2** is a bounded code/documentation correction. Severity is not a claim of a newly observed production outage.

## F01 — P0 gate: latest Cursor run remains a liability, not a fresh probe

**Evidence:** `IR/post-start-containment-1/normal-cancel-result.json` records HTTP 202, accepted cancellation and resulting version 5; `after-normal-inspection.json` remains cancelling. Native tail receipt `native-helper-tail-1792139393748855200.sanitized.json:14–35` records FINISHED, 926,070 tokens, result 2,946 bytes and SHA256 `2e4aac0d29aae546e783667baef26ec7850b3f34586d62908f1f66171e194a7c`. Cleanup receipt `bridge-root-stop.json` explicitly says `provider_stop_proven=false`. Retained process/cloud receipts establish their observation times only. `RUN-2-REPORT.md:1795–1808` and the handoff agree that final ledger/custody audit failed with TypeError and private capture is unfinished.

**Implication:** do not infer terminal mission state, durable/native usage equality, accepted output or zero remaining spend from native finish/process absence. Never start/resubmit the run or replace its fence. Historical invoice 403 and earlier missing-ledger liabilities remain unknown; a planning token allowance is not a native hard cap.

**Minimal next work:** W0 inventories exact public/internal/Temporal/harness/native identities and saved command/effect/budget/custody joins; repair the diagnostic's serialization/signature usage offline, not the database. W3 prepares normal authenticated reconciliation against actual refusal predicates. Any later read/mutation requiring services or credentials is separately gated. No direct usage insertion or repair SQL.

**Stop/go:** no new inference until current state, outstanding command/effect/usage liabilities, immutable result custody and remaining budget have either been reconciled through approved paths or retained as a named owner-approved exception. Existing irreversible uncertainty cannot be erased by another run.

## F02 — P1 defect: pending projection is classified as inactive after accepted start

**Observed source:** `IR/recovery-v3/controller/control_cursor_a8.py:74–85` returns true only for active/waiting/paused after cancellation checks. At `:210–211`, false becomes `external_cancellation_or_inactive_observed` and exits observation. Synthetic AST-only execution confirmed pending -> false, active -> true, cancelling/terminal -> false. No controller import or runtime action occurred.

**Retained behavior:** the controller journal plus `RUN-2-REPORT.md:1797` records accepted start followed by pending, premature observer stop, then real active/native execution. This is an operational controller defect; it does not show Temporal failed to start.

**Proposed correction:** replace the boolean conflation with explicit decisions for terminal, existing cancellation, open human REVIEW, active and accepted-start-awaiting-projection. Pending after accepted start keeps bounded observation alive; uncertainty refuses a new write and stays observable until its deadline. Preserve genuine REVIEW, ordinary cancellation authority, one cancellation UUID/readback and the global once-only start fence. Do not simply change false to unconditional cancellation.

**Acceptance:** pending->active->REVIEW; persistent pending->one authorized normal cancel; existing accepted/delivered/applied cancel->no duplicate; 403 remains refusal; terminal->no write; claimed start fence->no start. Include slow API reads and finalizer costs in one absolute deadline. Review `controller-lifecycle-repair-preparation/` as unreviewed input, not a runnable repair. W1 owns this.

## F03 — P1 containment gap: observer assumes a direct Node child

**Observed source:** `IR/observer/bridge_ownership.py:142–160` searches only direct worker children, then requires the Node executable, exact argv and `ppid == worker.pid`. `adapters/cursor/bridge_spawn.py:48–100` starts the resolved vendor entrypoint in a new session, returns endpoint discovery, and its failure cleanup signals the immediate `Popen` process. Its public return does not supply a reviewed descendant identity receipt.

**Retained evidence:** `bridge-root-stop.json:10–28` records Node under a shell, not directly under the worker. The handoff records worker watchdog expiry with detached shell/Node surviving. Static inspection also identifies a startup-failure risk if the immediate process is a wrapper; this specific failure path was not reproduced here.

**Minimal correction/tradeoff:** first support the pinned installed wrapper->Node grammar in bounded read-only observation, joined to the durable lease/harness/generation and boot/start/executable/argv/script/workspace/state-root. Recheck exact identity before any permitted containment. Never use process-name killing or treat expiry as orphan proof. Prefer a small **secret-free sidecar spawn-identity receipt** if static topology cannot establish ownership safely; adding that product seam needs a separately reviewed integrator lease to `bridge_spawn.py` and its tests. Do not rewrite bridge orchestration or create a generic process supervisor.

**Acceptance:** direct/wrapper topologies; wrong PID/start/boot/argv/lease/generation refusal; wrapper exit/Node survival; observer restart; lost discovery; capture native final tail before lease cleanup. No process is signalled during offline checks. W1 precedes every new native qualification.

## F04 — P2 code defect: Cursor usage source precedence and missing totals

**Observed/reproduced:** `application/execution/harness/cursor_usage.py:25–58` overwrites one native-run report for each TURN_ENDED/USAGE/RUN_RESULT frame and derives absent total as input + output even with cache counters. Pure production-function probes returned:

| Synthetic observation | Result |
| --- | --- |
| input 10 / output 5 / cache read 20 / cache write 4 / explicit total 39 | 39 retained |
| Same fields, total absent | 15 derived, caches still 20/4 |
| Cumulative result 39 followed by smaller per-turn USAGE 3 | 3 |
| Reverse order | 39 |

**Production relevance:** cancelled-turn `_turn_usage` consumes this at `lane_turns.py:2083–2097`; semantic-attempt aggregation consumes it at `:2957`. Current closing facts (`:2970`) and a successful exact provider usage read (`:2997`) can override it; read failure at `:2980–2985` retains the observation. Thus the synthetic risk is reachable, but no actual latest-run ledger error was established. Its native receipt explicitly contains total 926,070.

**Correction:** qualify event granularity from the pinned SDK and recorded fixtures; choose attributable cumulative run/result evidence ahead of per-turn events regardless of arrival order. Do not sum per-turn values without stable turn identity and complete deduped coverage. Preserve explicit vendor totals, including explicit zero; for absent total either derive documented cache-inclusive total only when all required dimensions are known, or keep unknown/partial evidence. Reasoning is already included in output. Do not change canonical binding bytes or “correct” provider explicit totals to a guessed formula.

**Sibling paths:** `adapters/cursor/frames.py:191–208` has the same absent-total fallback and zero-filled missing input/output; `adapters/cursor/cloud.py` calls `adapters/remote_session/usage.py:29–46`. Audit only affected Cursor callers. A global cache rule for all providers would be unsafe; give a provider-specific policy or explicit pre-normalized counters. Existing tests with equal duplicate values (`tests/unit/runtime/test_run2_cursor_usage.py:29–48`) miss mixed-source precedence.

**Acceptance:** cache-inclusive missing total; unknown missing input/output/cache; mixed per-turn/cumulative order; duplicate replay; missing cumulative result; cancelled path; authoritative read success/failure; no double reasoning; explicit provider total preserved; delayed cost still charged once. Independent Sol review confirmed the defect and the authoritative-read limitation. W2 owns the minimal correction; unresolved F01 still blocks new paid work.

## F05 — P1 qualification gap, P2 stale claims: managed budget wiring exists

**Observed:** `adapters/temporal/workflows/stagegraph.py:508–524`, `goal_directed.py:1221–1263` -> `workflows/budget_controls.py:47–66` -> `activities/lane_turn.py:121–126` -> `application/execution/harness/lane_turns.py:542` -> durable `budget_controls.py:166–330`; production composition at `deployment_composition.py:1370`. Intent, owner/fence/seal rechecks, ambiguous update readback and observed boundary are present. No high-confidence new implementation defect was found in that path.

**Limits:** `tests/integration/temporal/test_managed_budget_families.py:96` substitutes the activity itself. It proves family/replay behavior, not full production composition->activity->service or native budget enforcement. Static declarations remain conservative; `describe.py:657` commentary is factually stale. Old amendments/kickoff/Spec11 assertions of no callers must be reconciled during MO-07, preserving their historical date.

**Minimal plan:** add one controlled-fake production composition/activity/service join and replay test, using existing durable intent records; do not rebuild budget control. Keep native qualification blocked until actual cap readback, fresh `budget_reached`, held/restart/ambiguous update, exact authorized resume, partial fanout, cancellation and liability proof. Do not mark native/hard pause. Anthropic's cap acts between model requests and may overshoot by in-flight work; hold is not instant quiescence. W3/W8 own these distinct checks.

## F06 — P1 acceptance gap: caller notification and actual caller resumption are unjoined

`application/subscriptions/launcher.py:39–68` ensures the actor's inbox before launch; `coordinator_service.py:441` materializes committed events while waiting. `tests/unit/subscriptions/test_mo43_wake_channels.py` covers enqueue/wait, HTTP/MCP, subscription and CLI timeout; `docs/qualification/wake-channels/README.md:14–67` records a historical deterministic Claude/GoalDirected local drill. Therefore “wake machinery absent” would be false.

The latest handoff's Full3 section records no notification for its stream-ticket subscription and no native caller resumption. That exact miss is not diagnosed here. Audit the real public run key->internal ID->subscription actor/scope->journal cursor->notification kind->wait filter/exit chain before changing code. Do not repeat model report generation merely to test a cursor. Use a deterministic terminal/review event with the same public surface and then the actual caller harness. Preserve explicit acknowledgement and terminal/late/stale-child rules. W3 builds the proof; W6 qualifies each caller/placement.

## F07 — P1 release/data gate: stale migration prose can cause a harmful redo

Current `deployments/ai-engineer/release.lock.json:4,50–51` selects 1.4.2. Checked all 41 locked files with no mismatch. `B/live-apply-142/verify-receipt.json` reports verified identity/attestation, 37 migrations, restricted roles and the 1.4.2 fingerprint. `completed.json` reports verified. This independently corroborates `RUN-2-REPORT.md:838–857`; it does not query today's database.

**Correction:** W4 starts with read-only installed fingerprint/lock/seed/runtime-role/readiness comparison. Treat base `component/manifest.json` 1.4.0, immutable release 1.4.2, and per-app installed state as different identities. Do not edit frozen 0035/0040/0041/0042/0043/0044 bytes or reuse 0039. Do not rerun migration on the strength of old “unapplied” wording. A future actual schema change needs a new integrator-owned release, allocated slot, upgrade plan, backup/restore proof and explicit apply authority.

**Data readiness:** inventory unresolved dispatches, sessions/turns, effects, reservations/pending usage, frame cursors, context/custody refs, inbox/dead rows and exact catalog/binding/approval versions. Partition by application/tenant/run/generation and avoid exposing secrets. Legacy or missing native identities are named liabilities; no fabricated backfill. Only a separately reviewed idempotent application reconciliation/backfill may change data; never write a usage total manually.

## F08 — P1 qualification gaps: infrastructure and fixtures do not prove remote completion

`application/signals/drainer.py:113–153` persists before wake, retries boundedly and commits deferred receipts before enqueue. Seven in-memory tests passed here. `signals/wake.py:1–16,47–64` deliberately drops webhook completion/usage/action claims. Artifact custody validates generation, size, digest and actual bytes (`signals/artifacts.py:70–116`). These are implemented strengths, not fresh missing features.

`tests/integration/temporal/test_remote_mission_admission.py:1–10` explicitly limits its real PG/Temporal proof to fixture admission/start with technical root IDs; it cannot qualify scoped AWS/outside-network/native completion. Task16/14 attributes/poller receipts likewise do not prove HL-24 laptop-off/restart. W4/W7 must join current build/roles/queue/config to deployed route, authoritative native history drain and actual immutable outputs. W8 precedes W9. Preserve the separate S1 gate p99, >4.5 MB upload, stop and watcher requirements.

## F09 — P2 execution risk: obsolete kickoff, broad tests and false parity

Old team docs prescribe an Astra lead and many concurrent streams. The current user requires every lead/worker/reviewer `gpt-6.1-sol`. About 2.84 GiB RAM was free at baseline; importing one focused process is a different cost from multiple Temporal/DB/build suites. Use one active worker plus lead by default, one heavy process total, and stop expansion under resource pressure. Never stop another session/service to make room.

Keep nine profile identities and native/emulated/unsupported/unqualified declarations. Local SDK, standalone CLI, subscription cloud, provider-hosted Agents API, Agents SDK and model transport are different products. Current official docs describe broader/newer surfaces; do not repin the installed adapters or add deferred features. Final `qualified` changes require exact live receipt/release review, not a green mock suite.

## Current official documentation checks, 2026-10-16 UTC

These are external contract evidence, not installed/account qualification. Summaries are intentionally narrow; pinned source and exact request fixtures govern implementation.

| Official source | Verified contract and planning consequence |
| --- | --- |
| [Cursor SDK: usage and messages](https://cursor.com/docs/sdk/typescript) | Run/result totals are cumulative; usage events are per turn. Total includes input/output/cache read/cache write; reasoning is a subset of output. Billed per-run cost may arrive later, and agent totals can include additional work. Use source precedence and exact attribution; missing cost is not zero. |
| [Anthropic session budgets](https://platform.claude.com/docs/en/managed-agents/budgets) | Budget only attaches at creation; changes can resume budget-paused work. Enforcement is between requests, with in-flight overshoot. A pending ask can take precedence in multi-thread state. Current cap/usage and authoritative boundary events matter; never raise/remove cap casually during cancel. |
| [Anthropic session observability](https://platform.claude.com/docs/en/managed-agents/session-observability) | Session usage is cumulative; per-thread rounded figures need not sum to session cost. Reconcile session authority instead of summing overlapping thread receipts. |
| [OpenAI Agents API overview](https://developers.openai.com/api/docs/guides/agents-api/overview) | Confirms provider-managed Codex harness sessions. This corroborates the existing custom HTTP lane's product taxonomy, not account enablement or its wire compatibility. |

The installed Cursor Python pin is 1.0.37. Current generic TS `idempotencyKey` documentation is not evidence that local Send on that pin supports it. The installed SDK bridge source and integrated request regression are the specific evidence. Do not expand CM-11/model params or other deferred work from current manuals.
