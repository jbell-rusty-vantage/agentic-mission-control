---
type: Implementation Plan
title: "Run 2 completion work packages and release gates"
description: "Dependency-ordered, compute-bounded work for the current 40 non-funding issues, with exact ownership, acceptance, validation and live authority gates."
---

# Completion work packages

**Current status (2026-10-17):** Read the [integrated main and recovery record](RUN-2-CURRENT-INTEGRATION-2026-10-17.md) and [later human authority](RUN-2-PERMISSIONS-AND-ACTIONS-2026-10-17.md) first. The assessment/plan below retains its October16 snapshot and does not revoke subsequent authorization.

**Proposed work only.** The current request authorizes planning documents, not these implementation or runtime actions. See [assessment](RUN-2-COMPLETION-ASSESSMENT-2026-10-16.md), [findings](RUN-2-COMPLETION-FINDINGS-2026-10-16.md) and [Sol-only team prompt](RUN-2-SOL-EXECUTION-2026-10-16.md). No calendar estimates are assigned. Compute classes: **R** bounded reads/static analysis; **U** small offline unit process; **D** one disposable PG/Temporal fixture; **B** one package/container build; **L** separately authorized finite live drill. These are work sizes, not permission.

**Documentation pointer only - excluded from execution:** AF-FOLLOWON-01: agent-facing Mission Control consolidation is **NOT SCHEDULED / MANUAL FOLLOW-ON**, for AFTER this sprint and only upon the user's separate manual initiation. Its private source is `.scratch/agent-facing-consolidation-follow-on/issues/01-agent-facing-mission-control-consolidation.md`; that ignored artifact is provenance, not a portable repository link. It is not part of W0-W10, their dependency graph, acceptance/release gates or automatic continuation. Finishing this plan does not start it.

## Dependency and compute map

```text
W0 provenance + existing liability inventory (R)
 ├─ W1 controller / observer ownership proof (U)
 ├─ W2 Cursor accounting correction (U)
 ├─ W4 ingress + data/release readiness preparation (R/U -> D)
 └─ W5 standalone CLI closure (U -> L, independent product)
W1 + W2 -> W3 integrated control/recovery/caller proof (U -> D)
W3 + current readiness/authority -> W6 S0 cells (L; serial)
W3 + W4 -> W7 R / S1 remote proof (B/L; S1 separate stream)
W7 applicable ingress/R joins + existing HL prerequisites -> W8 S2 (L)
W8 + HL-13/17 + OpenAI readiness -> W9 S3 (L)
all applicable packages -> W10 integration / documentation / release closure
```

W4/W5 read-only preparation can overlap a blocked runtime proof. W1/W2 have disjoint candidate file sets, but **default to lead + one active worker** at measured memory pressure. A second worker is allowed only for a disjoint bounded read task with sufficient freshly measured headroom. No nested delegation. One U/D/B/L process at a time on this host; no xdist, concurrent dependency installs, image builds or multiple fixture clusters. Pause queued work when memory pressure rises; never reclaim resources by killing another session or stopping an unrelated service. No new worktrees are needed for this assessment; later choose a suitable retained checkout only after verifying its exact base and planning overlay.

## W0 — Integrator: establish a truthful starting record

**Scope:** R. Read-only runtime/source evidence; new planning/claim records only. Own this planning set and the later ignored claim/evidence manifest. Inputs: exact two session-end handoffs under B, current HEAD/status, current issue `run2_plan`, installed package metadata and saved receipts. Record source/build/wheel/image/configuration/prerequisite identities separately. Inspect branch/worktree metadata without fetch/reset/clean/stash.

**Deliverable:** criterion ledger for the 40 issues below, each criterion marked implemented / offline-tested / exact-placement-qualified / failed / blocked / unrun with source/test/receipt hash and applicable identity. Latest Cursor identity table must retain public key, internal UUID, root/execution, harness/generation, session/run, lease/fence separately. Pin the existing global start fence; `maximum_new_runs=0` for its reconciliation. Preserve Full3 approval and historical unknown costs.

**Acceptance / G0:** baseline status and hashes recorded, unrelated dirty files owned elsewhere; each liability has an owner and smallest next observation. No stale narrative becomes a runnable instruction. If HEAD or inspected source changes, rebase conclusions/review on new bytes before dependent implementation. Fresh runtime state is not available from a saved receipt; prepare scoped read commands and authority separately.

## W1 — Operational owner: repair the qualification controller before spending

**Scope:** U. Exact candidate lease: `IR/controller-lifecycle-repair-preparation/controller/{control_cursor_a8.py,controller_guards.py,test_execute_prestart_timeout.py}`, `IR/controller-lifecycle-repair-preparation/{pending_authority.py,public_authority.py,start_fence.py}`; and a **new reviewed preparation copy** of `IR/observer/{bridge_ownership.py,native_supervisor.py}` with adjacent offline tests. Frozen REC3 and historical receipts are read-only. Preserve the one actual global start fence across all helper revisions. Do not execute the prepared controller's live branch.

If the installed wrapper topology cannot be proven from that observer, submit the smallest proposed product seam to the integrator: `src/mission_control/adapters/cursor/bridge_spawn.py` plus `tests/unit/cursor/test_run2_bridge.py`. No specialist edits shared product paths without that explicit lease. The seam should produce an opaque, private, secret-free spawn identity record, not add broad process authority.

**Acceptance / G1:** F02/F03 regressions: accepted-start pending survives projection lag; REVIEW preserved; deadline leads to at most one properly authorized normal cancellation; accepted cancellation never duplicates; 403 never becomes success; global fence refuses start; direct/wrapper topology is recognized only with exact lease/generation/boot/start/executable/argv/script identity; wrong/stale identity refuses; independent final tail is captured before cleanup; read/shutdown costs fit absolute deadlines. All process tests are fake/read-only. Independent Sol review approves exact helper hashes and public/private output schema. No live call or process signal follows automatically from offline approval.

## W2 — Cursor owner: correct only attributable usage normalization

**Scope:** U, CM-02/01/13. Writable candidate lease: `src/mission_control/application/execution/harness/cursor_usage.py`, `src/mission_control/adapters/cursor/frames.py`, `tests/unit/runtime/test_run2_cursor_usage.py`, `tests/unit/cursor/test_run2_cost.py`. Inspect `adapters/cursor/{bridge,cloud,local,cost}.py`, `application/execution/harness/{cursor_costs,lane_turns}.py` and relevant fixtures read-only first. Integrator exclusively owns any required shared-helper change to `adapters/remote_session/usage.py`; prefer a Cursor-specific normalization policy/caller rather than changing every provider's semantics. If `cloud.py` requires a caller adjustment, add that exact file to the reviewed lease before editing.

**Correction:** F04 source precedence/unknown handling/cache totals; retain explicit provider totals, current wire identities, scopes, semantic-attempt keys and bounded delayed cost settlement. Do not remove the already integrated local Send fix. No SQL migration or retroactive ledger write is assumed.

**Acceptance / G2:** regression cases listed in F04, with cancelled `_turn_usage` and provider read success/failure paths. Old `UsageReport`/binding fixtures still round-trip; absent fields and digests unchanged. Two turns, replacement and continuation count native runs once; delayed cost/zero/403/unknown/replay remain distinct. Targeted lint/mypy plus exact unit tests pass on integrated bytes. If facts are irrecoverable, expose unknown/partial rather than manufacture totals. Past-run repair is a separate W3/W4 authority/data question.

## W3 — Integrator: prove shared joins, recovery and caller communication

**Scope:** U -> D after G1/G2. Read-only-first boundaries: `application/execution/harness/{lane_turns,budget_controls,state,dispatch,sessions}.py`; `adapters/temporal/{deployment_composition,operation_activities,closed_workflow}.py`, `activities/lane_turn.py`, `workflows/{operation,stagegraph,goal_directed,budget_controls}.py`; `application/recovery/closed_workflow.py`, `adapters/postgres/closed_workflow.py`; `application/subscriptions/{launcher,coordinator_service}.py`, `interfaces/cli/wait.py`. Integrator assigns exact failing-seam patches only; existing correct behavior closes by evidence.

**Tests/acceptance:**

- Add one actual production composition->budget activity->service->controlled provider fake test; preserve deterministic StageGraph/GoalDirected replay and interrupted/partial fanout liabilities. Existing fake-activity family tests remain useful but are not the whole join.
- Reproduce Full3-shaped public/internal-run/subscription actor/scope/cursor/filter joins using deterministic events before any model turn. Verify late wait, terminal/review/blocked notification, reconnect replay, explicit ack and actual caller task resumption separately. Existing `test_mo43_wake_channels.py` and acceptance fixture are starting points, not automatic S0 qualification.
- Audit actual closed-recovery eligibility. It requires cancelling StageGraph, closed families, no wait/pause/continuation/child liabilities, settled budget/effects/usage, ended exact harness/current generation, resolved dispatch and command states. Historical external signal/cancel initiation is currently refused. Do not bypass these guards to recover latest Cursor. Add a fixture for its precise safely captured refusal/eligibility when available.
- Protect existing tests for crash-before/after child submit, live submission fence, old-generation late child result, paused/cancelling parent, checkpoint descendant selection, concurrent recovery, sealed fork bytes/origin, absent conversation and continuation phase activation. No new child protocol is required by evidence.

**G3:** exact integrated unit/architecture checks and selected disposable PG/Temporal tests pass, with no shared DB/provider calls. The old real recovery receipts prove their original run only. If latest Cursor still has unresolved commands/usage, produce an exact refused-readback/reconciliation proposal and keep G-paid closed. No operator abandonment, native restart, command clearing or accounting insertion is implicitly authorized.

## W4 — Integrator + leased ingress owner: data and remote readiness

**Scope:** R/U -> D; MO-74/75/76/79, MO-77/78 preparation. Exact ingress candidate boundaries: `application/signals/{drainer,launch,artifacts,wake,service,verification}.py`, `bootstrap/{ingress,ingress_drainer,worker_ingress}.py`, `adapters/postgres/{ingress,ingress_drainer}.py`, `interfaces/http/ingress.py`; corresponding `tests/unit/signals/`, `tests/unit/runtime/test_run2_ingress_{wake,composition}.py`, `tests/integration/postgres/test_run2_ingress_{drainer_postgres,request_idempotency}.py`, `tests/integration/temporal/test_remote_mission_admission.py`. Lease exact files, not all directories. Deployment/SQL/lock changes stay integrator-only and are not presumed needed.

**Current-data gate G4a:** fresh read-only app-bound installed identity/fingerprint/37 receipts versus **1.4.2** lock; restricted runtime/family/checkpointer/ingress roles; seed/catalog/pin/describe compatibility including Codex0.162.1; existing recovery reference remains accessible. Verify current environment/profile/prerequisite expiries and queues/builds. Preserve Biotech's separate installation and stores. No repeat apply from stale prose.

**Readiness/backfill gate G4b:** produce counts/identities by exact scope/run/generation for unresolved dispatch, ended/open native sessions/turns, effects, reservations/pending usage, artifact/conversation digests, projection/command versions, inbox/dead rows and native history cursors. Missing legacy identity or final tail remains a named incident. A needed backfill must have an idempotency key, expected version/generation, dry-run diff, provenance for every fact, no duplicate charge/effect, rollback/recovery plan and explicit mutation authority. Reconcile via application services; no synthesized native acknowledgement or direct usage SQL.

**Durability/security G4c:** one ingress request->one normal admitted run across conflict/replay/crash; stale/forged/expired/revoked/cross-scope refusal; history wake never supplies completion authority; crash after persist/before wake/drained; poll fallback and bounded dead-row telemetry; actual >4.5 MB upload bypasses edge, bounded byte/size/digest/expiry verification, immutable version registration and stale-review refusal. Reuse existing tests. Remote fixture's technical root/zero-digest limits must be reported; it cannot replace scoped deployment qualification.

**If a schema change is actually necessary:** stop for an integrator-owned additive release design. Preserve applied migration/seed bytes, allocate a new slot, verify old-binding absent-field round trip and approval seals, fresh/upgrade/repeat/drift/refusal/role/RLS tests and protected-object diff on a disposable target. Produce exact `mission-db plan`/verification and backup/restore evidence before seeking live apply authority. There is no planned new migration in this assessment.

## W5 — CLI owner: close the independent CLI product efficiently

**Scope:** U, then separately L. Only `.agents/skills/{coding-cli-jobs,claude-code-headless,codex-exec,cursor-agent-headless}/`; schema, runner, adapters, docs and fake fixtures/tests. No `mission_control` imports, catalog publication, global config/login changes or cloud-lane wiring. Start by mapping existing implementation to LS-01..06, not rewriting the runner.

**G5-offline:** verifier owns completion; explicit configuration survives resume; unsupported options before spawn; subscription keys scrubbed before auth guards; unknown cost retained; file/worktree bounds, redaction, cancellation, owned process containment and result identity match schema. Fake CLI suite passes once under bounded process controls. **G5-live:** only with renewed exact native CLI/auth/quota/model authority, LS-07 resolves selected native unknowns; LS-08 runs its required Codex fix + Cursor review jobs in isolated worktrees, background wake and verifier result read. Agent workers for the implementation remain Sol-only; historical CLI/provider test selections do not authorize model substitution or new paid calls in this task.

## G-paid — shared gate before any native or remote drill

Require current scoped authority, exact reviewed script/hash, target account/app/region/namespace/resource/build/configuration, actual prerequisite freshness, retained spending reconciliation and explicit remaining allowance. Unknown does not become zero or remaining budget. Include worst credible in-flight work/overshoot, tool and cleanup liabilities. A local wall clock/token reservation is not a provider hard cap. Paid/control-plane paths remain default-off and finite; no broad retry or new model/account/region/size. Prepare capture before work: native final tail, cost, result bytes/schema/custody and command/effect/cleanup receipts. Unexpected inference, lost identity, ambiguous effect, budget drift, missing observer, secret exposure or failed cleanup stops progression; preserve the incident and complete only unaffected work.

## W6 — Integrator-run S0 exact placement cells

**Scope:** L only after G0–G3/G-paid and relevant G4a/b. MO-63..72 plus existing MO-08/43/04/05. Do not reuse latest Cursor run as a new start. Fresh immutable build requires matching Windows API/WSL/AWS code where involved. One base worker per namespace/application; WSL lane-only with runtime role when AWS base participates. Local namespace17233 stays separate from Biotech7233; verify actual selected addresses before work.

Retain all **18 caller × lane × Temporal cells**. Use very small control fixtures rather than another extensive report for each defect. Each cell records submit/start identity, caller inbox and actual resumption, one delivered/applied interrupt-and-inject, clean cancel/completion, real tools/credentials/instruction/skill evidence as required, usage/cost disposition, immutable output and custody-before-cleanup. Include specific fork/continuation/native recovery drills only where issue acceptance requires them; do not silently expand every cell. A separately required report/review contract still needs its real output and human decision; reuse completed Full3 evidence only within its exact applicability. Auto and Grok are separate selections, and SDK/CLI/default is not an observed serving model.

**G6:** exact criterion receipt per cell or explicit blocked/unrun; final capture independently precedes cleanup; no unresolved session/dispatch/budget/effect liability is hidden. One passing cell never flips all profile/placement flags. Current planning does not waive any cell.

## W7 — Integrator: deployed ingress, remote R and separate S1

**Scope:** B/L only with G4/G-paid. Candidate deployment ownership remains `deployments/{ingress-vercel,worker-aws,cloud_runtime}/`, `scripts/temporal_cloud/`, `docs/qualification/`; no configuration mutation now. Reuse existing exact AWS account298199649527/us-east-1/dev resources and immutable task/build lineage only when renewed authority covers them. Verify actual service state first; prior zero-task receipts are historical.

**G7-R:** deployed authenticated remote request from outside the owner's network reaches normal admission, scoped root/outbox and one base worker; current installation/build/config/queues/S3 custody/readiness match; laptop-off progression; mid-session service restart reattaches without duplicate frames, dispatch or charges; secret sentinel and bounded cleanup; required 24h CPU/memory/spend evidence. Do not stop the owner's sessions/machine without coordinated approval. A controlled isolation alternative must be an explicit acceptance amendment, not silently labelled laptop-off.

**G7-S1:** separate Cursor cloud knowledge and SDLC mission contracts, synced environment/cognition, signals/watcher/gate stop, native branch/PR/custody and caller wake, measured gate p99 <=400 ms as specified, large signed upload and stop within required tool boundary. Join CM-01/05/09/10 and CM-02/08/13 plus CM-19/21 drills. Four-unit isolation/retry/reattach/one-unit cleanup must preserve exact heads and grants. No deferred CM features are promoted. S1 may close independently while S2/S3 progress on their actual deps.

## W8 — Hosted owner + integrator: S2 before S3

**Scope:** L, HL-24. Existing `adapters/{anthropic_managed,remote_session}/`, hosted composition and qualification records; patch only an identified failure with a new lease/review. Required dependencies remain HL-09/17/18/23 + MO-74/77/79. Pin actual saved agent/environment/skills/toolset/network/auth/model/config seals and account placement.

**G8:** both remote knowledge and SDLC Completion Contracts, real native approval deny/allow/timeout with matching effective configuration, authoritative provider history wake, inject, actual fresh budget boundary/held/readback and exact authorized resume, restart/ambiguous update and partial fanout/cancel liabilities, session-level settled list cost, immutable outputs/review and separately authorized verified publication, session deletion only after custody. Do not count a turn boundary or accepted cap PATCH as budget pause. Current official budget semantics allow in-flight overshoot and continued effects; capture their liability. No production flag promotion from the offline composition test. If a required guarantee cannot be provided, present a concrete owner amendment or keep HL-24 blocked.

## W9 — Hosted owner + integrator: S3 with exact hosted product

**Scope:** L, HL-25, after W8 and HL-13/17. Only existing `codex_agents` custom HTTP hosted Agents API, not Agents SDK/direct Responses/subscription cloud. Reconcile prior unknown native spend before a new attempt. Preserve `agents=v1` and schema provenance versus installed standard `openai` dependency distinction.

**G9:** both original remote missions, one attributable session/input, genuine approved function-tool `required_actions` round trip, actual native allow and current-turn/index visibility, steer/cancel, killed-task recovery from authoritative items with no duplicate effects/frames/usage, real bytes/custody/version, separately governed publication and final cleanup/cost. Unsupported shell/file per-command approval refuses before create; a hosted path with no downloadable current-turn bytes cannot count as custody. Do not substitute a model or repeat a paid failure to resolve ambiguous state.

## W10 — Integrator: final regression, release and documentation closure

**G10-source:** freeze exact integrated HEAD/overlay and file hashes; independent Sol reviews exact patches; all changed scopes have tests. Re-run only affected checks after new edits. Run relevant architecture tests, authoritative mypy, Ruff, ty, deptry, format, unit/conformance, skills/schema/seed checks sequentially; then only applicable integration/acceptance/two-project qualification. Missing Biotech SDL is reported as a release blocker, never hidden by skip or dropped assertion. Full broad release suites run only after targeted gates and in a properly provisioned isolated environment, not alongside another heavy process on this laptop.

**G10-data:** current installed fingerprint/roles/seeds/config and approved release locks match; no unsanctioned migration/backfill; all liabilities either reconciled or separately accepted as an explicit remaining blocker. Current acceptance must not rely on stale native IDs, approval seals or expired prerequisites. No inferred zero cost or pending command relabelled applied.

**G10-operational:** current external state is verified with scoped authority; only owned transient resources are cleaned after custody/settlement, with exact identity/nonce before signal; no blanket teardown. Preserve retained histories/failed receipts/unknown costs, worktrees, ignored environments and recovery points. Record native stop vs process exit vs workflow terminal vs billing settlement separately.

**G10-docs/release:** MO-07 reconciles active summaries/kickoff/qualification docs with current source and 1.4.2 receipt; preserve dated old evidence and annotate supersession. Do not run the baseline issue generator. Keep `issues.json` and issue Markdown `run2_plan` consistent when a later authorized edit changes plans/status. Record per-criterion source/test/live evidence and correct exact profile/placement flags only through reviewed release. Main merge/push, issue/Linear publication, production namespace/actions and S4 remain separately gated. Documentation says what passed, failed, blocked and was unrun; no overlapping test-count sum.

## Exact issue/dependency ledger for this completion scope

This maps the original 40 non-funding remainder; **it does not mark 40 features missing or change issue status/deps**. `—` means no direct issue deps, not absence of acceptance gates. Current `issues.json`/issue Markdown remains authoritative. Implementation already present closes with evidence.

| Issues | Existing direct dependencies | Primary package / remaining work |
| --- | --- | --- |
| MO-07 | — | W0/W10, current factual documentation reconciliation |
| CM-10 / CM-09 / CM-08 / CM-18 / CM-13 | — | W2/W3/W7; prove existing isolation, outputs, hydrate, staged text and stream behavior |
| CM-02 / CM-03 / CM-04 | — | W1/W2/W6/W7; accounting, typed failure, exact bridge host proof |
| CM-01 | CM-02, CM-04 | W2/W7; exact billed attribution/single settlement |
| CM-05 / CM-07 | CM-04 | W1/W3/W7; detached recovery and conversation custody |
| CM-19 | — | W1/W3/W7; native cancellation timestamps/fence/cleanup evidence |
| CM-21 | CM-01, CM-05, CM-09, CM-10 | W7/W10; only in-scope implemented cells |
| LS-01 | — | W5; job/result contract already implemented, map evidence |
| LS-02 / LS-03 / LS-04 / LS-05 / LS-06 | LS-01 | W5; adapters/router/doctor/config/env and fake proof |
| LS-07 | LS-02, LS-03, LS-04 | W5 live native unknowns |
| LS-08 | LS-05, LS-06, LS-07 | W5 required two-job native caller demo |
| MO-63 / MO-64 / MO-65 / MO-66 / MO-68 / MO-69 / MO-70 | — | W3/W4/W6; worker roles/custody/auth/pin/release/bindings/token evidence |
| MO-71 | MO-69 | W6 probe manifests, current config/skill/tool evidence |
| MO-72 | MO-08, MO-43, MO-04, MO-05, MO-65, MO-66, MO-68, MO-69, MO-70, MO-71 | W6 local S0 original nine cells |
| MO-67 | MO-72, MO-78 | W6 Cloud S0 original nine cells |
| MO-74 / MO-75 | MO-40 | W4/W7 slim ingress/deployed service and durable drain |
| MO-76 | MO-40, MO-75 | W4/W7 byte custody and signed upload |
| MO-78 | — | W4/W7 current Temporal namespace/build/queue/promotion evidence |
| MO-77 | MO-63, MO-64, MO-78 | W7 remote base worker laptop-off/restart/resources |
| MO-79 | MO-40, MO-75, MO-70 | W4/W7 existing normal launch path, conflict/crash/deployed evidence |
| HL-24 | HL-09, HL-17, HL-18, HL-23, MO-74, MO-77, MO-79 | W8 S2 two-mission/control/cost qualification |
| HL-25 | HL-13, HL-17, HL-24 | W9 S3 qualification |

Funding-held HL-01/02/03/10/14/15/16/20 are not dispatched. Deferred CM-06/11/12/14/15/16/17/20/22, SC-01..03, MO-53 and broad Deep Agents/new next-stage capabilities remain excluded. Dependencies outside the 40 may already be satisfied by integrated code; verify that evidence rather than reopening their work.

## Validation commands and truthful dispositions

All commands below except the stated assessment test are **proposed future commands**, run from the owning repository with installed dependencies and a bounded wrapper. Use the existing `.venv` interpreter or `uv run --no-sync`; never install implicitly. Read fixtures first. Disable external tracing; select exact explicit disposable fixture targets before any D command. Missing dependencies/SDL/services are blocked, not permission to fetch or use a live DB.

| Package | Smallest starting check / evidence |
| --- | --- |
| W1 | AST/unit-only helper tests from reviewed preparation; no `execute`/live branch. `pytest tests/unit/cursor/test_run2_bridge.py tests/unit/cursor/test_run2_active_bridge_recovery.py` with exact ownership fixtures |
| W2 | `pytest tests/unit/runtime/test_run2_cursor_usage.py tests/unit/runtime/test_run2_cursor_costs.py tests/unit/cursor/test_run2_cost.py`; new source-precedence/cache/cancel regression beside them |
| W3 | `pytest tests/unit/harness/test_managed_budget_controls.py tests/unit/temporal/test_managed_budget_routing.py tests/unit/recovery/ tests/unit/subscriptions/test_mo43_wake_channels.py`; then individually selected `tests/integration/temporal/test_managed_budget_families.py`, `tests/integration/postgres/test_closed_workflow_recovery_postgres.py`, `tests/acceptance/mission_control/test_wake_channels.py` only on isolated targets |
| W3 transfer/child protection | Select from `tests/unit/context/test_fork_conversation_custody.py`, `tests/unit/continuation/test_phase_machine.py`, `tests/unit/operations/test_checkpoint_recovery_classification.py`, `tests/unit/integrations/test_async_subagent_submission_fence.py`; add cases only for changed or unproved seams |
| W4 | `pytest tests/unit/signals/test_drainer.py tests/unit/signals/test_artifact_custody.py tests/unit/runtime/test_run2_ingress_wake.py`; isolated PG/Temporal idempotency/admission tests named above, preserving technical-root fixture limits |
| W5 | `pytest .agents/skills/coding-cli-jobs/tests/test_agentjob.py` after verifying all executions are its fake CLI fixtures; live flags stay off outside specifically approved LS-07/08 |
| W6 | `pytest tests/unit/runtime/test_run2_worker_roles.py tests/unit/authoring/test_manifest_materialization_policy.py`; current host/auth/readiness/manifest receipts, then exact one-cell native script |
| W10 | `uv run --no-sync ruff check <changed Python>`; `uv run --no-sync mypy`; `uv run --no-sync ty check`; `uv run --no-sync deptry src`; Makefile sequential `check` constituents plus authoritative mypy; required format/schema/seed/skills and applicable release qualification. Run doc index/OKF/link checks; do not regenerate issue baseline |

Assessment actually executed only seven in-memory drainer tests with `--confcutdir=tests/unit/signals`, plugin autoload disabled, explicit `pytest_asyncio.plugin`, no bytecode/cache/tracing and outer60s timeout: **7 passed**. Pure controller/usage probes, release hashes and final document/drift checks are separately recorded in the manifest. None of the proposed wider commands is claimed passed here.
