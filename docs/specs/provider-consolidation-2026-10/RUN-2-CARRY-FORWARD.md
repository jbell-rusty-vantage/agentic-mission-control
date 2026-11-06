---
type: Sprint Disposition
title: "Run 2 carry-forward register: deferred, blocked and parked work entering provider consolidation (2026-10-20)"
description: "One list of everything the materialization-observation sprint (Run 2) did not finish: parked runs and live liabilities, the defects found and not fixed, all 64 open issues grouped by the consolidation sprint that owns them, fixtures, owner decisions and the environment state needed to restart live work. Built from the Run 2 finish records on main at 6c539d33."
tags: [mission-control, providers, consolidation, run-2, carry-forward, backlog]
---

# Run 2 carry-forward register (2026-10-20)

Run 2 of the materialization-observation sprint is **finished**. This page is the intake for the
[provider consolidation program](README.md). It gathers in one place everything that was deferred,
blocked, moved or found and left unfixed, and assigns each item to the sprint that owns it.

It is derived from these records, which remain the authority:
- [completion summary](../archive/materialization-observation-2026-10/runs/RUN-2-COMPLETION-SUMMARY-2026-10.md), section "Finish (2026-10-20)";
- [finish disposition](../archive/materialization-observation-2026-10/runs/RUN-2-FINISH-DISPOSITION-2026-10.md);
- the [status ledger](../archive/materialization-observation-2026-10/runs/RUN-2-CLOSE-STATUS.md), "Finish" W1–W6 and "Stock-take";
- [Gate L disposition](../archive/materialization-observation-2026-10/runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md);
- [issue acceptance appendix](../archive/materialization-observation-2026-10/runs/FINAL-CAPABILITY-ISSUE-ACCEPTANCE-APPENDIX.json) (`finish_2026_10`).

The destinations below are the finish's E-decision destinations where one exists. Where the finish
recorded none, the destination is this register's proposal, marked *(proposed)*.

## 1. Starting point

| Item | State on 2026-10-20 |
| --- | --- |
| Repository | `platform/mission-control`, branch `main`. Run 2 finished at `6c539d33`; this register and the documentation refresh are committed on top and pushed to `origin/main` (2026-10-20) |
| Source | Unchanged since `6fcb4f82` (P8). The only change since the baseline's `eb36f3f6` is one unit test. Every [baseline](../archive/provider-consolidation-2026-10/docs/BASELINE-2026-10-19.md) citation still holds |
| Worktrees | Only the canonical checkout. The retained offline worktree (`mo/run2-completion-offline-20261016`, merged) was removed on 2026-10-20. Its tracked and untracked files were byte-identical to `main` or older versions of them. Its ignored run evidence was moved to `.scratch/archive/run2-completion-offline-worktree/` (about 510 MB, git-ignored) |
| Branches | `main` only. One old stash is kept: `stash@{0}` "hl21-before-latest-integration" (2026-10-14, HL-21 pre-integration snapshot; superseded by later HL-21 work, not applied) |
| Checks at finish | lock, ruff, format, deptry, mypy (822 files), ty, architecture (12), conformance (149), schemas/seeds/skills and docs all pass. Unit tests: 5,176 passed and 36 failed. Of the failures, 6 are pre-existing (2 `control_plane` digest-guard, 4 `harness` closing-facts) and 30 are environment-only (22 need PowerShell 7, 8 need the Biotech SDL). Integration tests were not run |
| Wheel | `mission_control-0.1.0-py3-none-any.whl` sha256 `c0cd2300…15fc`, built and not installed |

## 2. Live evidence Run 2 established

| Lane | Live result | What it proves |
| --- | --- | --- |
| `claude_agent_sdk` | **MR-01** local `e7d24a4b…`, **MR-11** Temporal Cloud `37ce4f20…`, cancel run `cc6d5594…`; earlier F1 run k `554d2b2a…` | Stage Graph diagnose → patch → review → Human Gate to `completed`. Shown in use: skills, plugin cognition, disallowed-tool refusal, child-environment allowlist, typed approval allow/deny, inject (cancel_and_replace), wait/wake/peek, immediate cancel with no orphan, `lane.cleanup` |
| `codex` | **MR-02** local `a901422d…`, **MR-12** Temporal Cloud `60cca228…`, cancel run `235fcc73…` | The same Stage Graph shape with `gpt-6-luna` on the API key. Plugin skills read, sandbox shell, `network: none` enforced, usage **settles** (budgets bind), wait/wake/peek, cancel (about 2 min, waits for `turn/completed`) |
| `cursor_local` | **MR-03 blocked** `7132d2de…` (one attempt) | Compile, preflight, C9/M4 attestation and the bridge start on WSL. The SDK `observe_run` is rejected and the native agent runs on unobserved. Memory is not the blocker (bridge peak 199 MB) |
| `claude_managed`, `codex_agents` | Run 1 only (HL-09/HL-21 controlled projection; 5 failed `codex_agents` approval attempts) | No Run 2 live cell |
| `deep_agents`, `cursor_cloud` | None in Run 2 (`cursor_cloud`: MO-13 probe only) | — |
| `claude_cloud`, `codex_cloud` | No adapter | — |

Neither Run 2 nor Run 1 proved a **Goal Directed** program live on any lane. Every live proof is a Stage Graph.

## 3. Parked runs and live liabilities

**Settled on 2026-10-20 by owner decision ("terminate them so I can move on").** Receipts are in
private `run2-close-20261018/settle-20261020/`.

| Run | Before | Action | Result |
| --- | --- | --- | --- |
| `ec193a1e-9e4f-574f-992d-a6ad16733ff2` | `cancelling`, unit `in_doubt` (pre-create secret refusal, RF-01) | `reconcile_unit` `abandon_unit` by `service:run2-reconciliation-operator` (incident `unit-in-doubt:c77af779…`) | **Terminal** in Mission Control: lifecycle `completed`, outcome `cancelled` (v12) |
| `eaa586c3-2fe5-5108-ab51-2de0fab19b1c` | active, review unit `in_doubt` (Codex sub-agent usage, RF-14), no reconciliation incident | Immediate cancel accepted (v17), then all open Temporal workflows terminated (root, family, review operation) | Temporal **terminated**. The Mission Control record stays `cancelling` |
| `7132d2de-88f2-5c20-9b57-58a183dd6424` | `cancelling`; family `decide_result` retried 59+ times on an unsettled usage reservation (RF-18) | Temporal root and family terminated (the operation had already failed) | Temporal **terminated**. The Mission Control record stays `cancelling` |

Nothing will execute these runs again. The two Mission Control records cannot be made terminal
without new code. There is no operator action that writes off an unsettled usage reservation or
decides an `in_doubt` unit that has no incident, and closed-workflow recovery refuses while a
reservation or producer liability is open. Faking usage figures or editing the shared application
database by hand was ruled out. These two inert `cancelling` records are **K20** scope: add a
governed write-off for reservations and incident-less units, then apply it to them.

The reconciliation grant lives in G1's private `config/deployment*.json` (the authentication the API
serves) and `config/operator-auth.json` (the minting copy). Earlier copies are kept as
`*.pre-reconcile.json`.

Run j `831f33f4…` is terminal `cancelled` (E4). Other retained state:
- the WSL lease directories `~/mc-leases/{claude,codex,cursor}`, which hold the parked units and the cancelled units' worktrees (RF-17);
- the local Temporal containers `mc-run2-s0-temporal{,-postgres}-1`, stopped with their data retained;
- the Temporal Cloud namespace `mission-control-dev.ih0e7`, whose finish queues are idle.

## 4. Defects found and not fixed

E7 allowed no code changes in the finish, so every finding below is open. "K" refers to the
[program's kernel items](README.md#5-kernel-work-sprint-0). K19–K21 were added on 2026-10-20 from
this register and are proposals.

| ID | Finding | Evidence | Destination |
| --- | --- | --- | --- |
| RF-01 | A pre-create secret refusal is classified `in_doubt`, so the run cannot cancel cleanly | run `ec193a1e` | K20 |
| RF-02 | `missionctl wait` does not refresh its token | Run 2 run a | K16 |
| RF-03 | A second `review_required` on the same run does not wake a fresh wait (cause unconfirmed) | run e | K16 |
| RF-04 | An undecided approval auto-denies after 300 s (no `deadline_at`) and the deny cancels the turn | run e | K12 |
| RF-05 | Provider-permission reviewers default to `owner` (worker setting, not mission) | run b; `bootstrap/settings.py:392` | K12 |
| RF-06 | A reused lease keeps the prior `outputs/`, which are re-collected by the next stage | runs h, i | K01 |
| RF-07 | A queued inject aimed at a finished node is neither applied nor refused | run k | K13 |
| RF-08 | P5b residual timeout window (interrupted turn recorded `failed` while the replacement turn runs on) | run c; P5b `aeeda4a4` | K13 |
| RF-09 | P5c gaps: multi-output stages and the Goal Loop output contract | P5c `c7f79b50` review | K04 and the GD proof |
| RF-10 | `config:` values compile but are not delivered to a lane's runtime environment (MR manifests put test paths into the instruction instead) | MR-01/02 manifests | K19 |
| RF-11 | Latent frozenset dump in the `admission_rejected` payload | `application/programs/service.py:530` | K21 |
| RF-12 | The first HTTP call after an idle period fails client-side over WSL loopback forwarding; idempotent retry succeeds | run b–c | WSL2 runbook note; client retry *(proposed)* |
| RF-13 | Codex allowlist egress is `advisory`: with an allowlist network, `curl` to a non-allowlisted host succeeded. Only `network: none` is enforced | MR-02 attempt l; `application/environments/network.py` | P6 codex |
| RF-14 | Codex sub-agent threads carry no usage provenance and park the unit `in_doubt` | run `eaa586c3`; `lane_turns.py:2864` | P6 codex |
| RF-15 | Usage: Codex settles per turn, so mission token budgets bind. Claude and Cursor usage stays `unknown`, so their budgets never bind | MR-01, MR-02 | P3, P5 usage work; F4 remainder |
| RF-16 | `missionctl` has a fixed 30 s HTTP timeout; Cloud preflight exceeds it | `interfaces/cli/main.py:1027` | K21 |
| RF-17 | A cancelled unit's lease is retained: there is no `lane.cleanup` on the cancel path | MR-01 and MR-02 cancel runs | K20 |
| RF-18 | The Cursor SDK rejects `observe_run` six seconds into the first turn. The native agent runs on unobserved, and the provider text is not kept | MR-03 `7132d2de` | P3 cursor |
| RF-19 | The LS fixture's `verify_readonly.py` pins an LF hash and fails on `core.autocrlf=true` checkouts | LS-08 Claude review | K21 |
| RF-20 | 6 pre-existing unit failures (2 `control_plane` digest-guard, 4 `harness` `test_closing_facts_map_every_run_result_status`) | P8, W6 | K21 |
| RF-21 | Transcript and frame bodies are 2 KB excerpts, so the advertised tool list cannot be read through Mission Control | W1 | K15 |
| RF-22 | The accepted diagnosis report recorded disposition `unknown` | MR-01 | P5 *(proposed)* |
| RF-23 | Codex immediate cancel takes about 2 min because the interrupt waits for `turn/completed` | MR-02 cancel run | P6 codex |
| RF-24 | Linux `mypy` flags three Windows-only modules (P8 Windows `mypy` passes) | MR-12 review | K21 |
| RF-25 | Worker lease workspaces default under the checkout's `.workspaces/` and exceed Windows MAX_PATH | Stock-take | K21; set a Linux workspace root meanwhile |

Owner TODO carried with them: multi-agent on code missions (`adapters/anthropic_managed/harness.py`,
the R33 refusal), which belongs in P2 claude_managed (C10).

## 5. Open issues by destination

All 110 Run 2 issues have a disposition. 45 are `fully done`, and the 8 Gate L issues closed by
receipt in the finish are not listed here (LS-05, LS-08, MO-08, MO-67, MO-68, MO-70, MO-71, MO-72).
The 64 below are open. The status is the issue record's own status, and "Remaining" quotes the
record's `next_action`. Counts in the appendix are recounted from the records. The stored
`current_status` fields and the recount differ by one, which the appendix discloses.

How to read the groups:
- **Per-lane groups** close inside that lane's sprint (phase D receipts satisfy their clauses).
- **Cross-lane** issues close once every lane their acceptance names has its native receipt. Each
  provider sprint contributes its lane's row through C01, C07 or C12.
- **Stream R, Signal Ingress and S4** are not lane work. They stay outside the provider sprints
  unless the owner schedules them.
- **Deferred** issues are not started and need an explicit scope change. Several overlap the
  program's capability catalog: CM-11 ↔ C13, CM-12 ↔ C10/C11, CM-14 ↔ C02, CM-15/CM-16 ↔ C08,
  CM-06 and MO-53 ↔ C06, SC-01..03 ↔ decision D3. The P3 sprint should decide in `DESIGN.md`
  whether to pull the CM items in.

### Sprint 0 (kernel and tooling, K21) (2)

| Issue | Status | Remaining (from the issue record) |
| --- | --- | --- |
| [MO-07](../archive/materialization-observation-2026-10/issues/MO-07-reconcile-stale-documentation-and-status-statements.md) Reconcile stale documentation and status statements | active development | Current navigation and evidence reconciled; active documentation closure now includes latest approved refusal. Dated ready-for-agent headers are planning, not current status. |
| [MO-69](../archive/materialization-observation-2026-10/issues/MO-69-binding-digest-tool-for-compose-bindings.md) Binding digest tool for compose-bindings | blocked | Secret-free derived summary exists; reviewed selections/current three-lane tool/model/auth/runtime seals still needed. |

### P2 claude_managed (7)

| Issue | Status | Remaining (from the issue record) |
| --- | --- | --- |
| [HL-07](../archive/materialization-observation-2026-10/issues/HL-07-claude-managed-prepare-agents-skills-environments-and-vaults-from-pack-files.md) claude_managed prepare: agents, skills, environments and vaults from pack files | implemented but unqualified | Managed prepare/controlled reuse exists; full owner-selected native pack/S2 proof incomplete. |
| [HL-08](../archive/materialization-observation-2026-10/issues/HL-08-claude-managed-session-lifecycle-and-frame-classifier.md) claude_managed session lifecycle and frame classifier | implemented but unqualified | Lifecycle/classifier exists; native killed-worker reattach/no-duplicate evidence remains. |
| [HL-09](../archive/materialization-observation-2026-10/issues/HL-09-claude-managed-approvals-mission-control-custom-tools-and-publication.md) claude_managed approvals, Mission Control custom tools and publication | implemented but unqualified | Run1 local native approval/publication passed; local controlled Git/PR gateway narrower than full remote S2. |
| [HL-18](../archive/materialization-observation-2026-10/issues/HL-18-data-class-policy-enforcement-and-session-retention.md) Data-class policy enforcement and session retention | implemented but unqualified | Data-class/retention code exists; exact all-lane native scheduled deletion/custody remains. |
| [HL-21](../archive/materialization-observation-2026-10/issues/HL-21-hosted-lanes-full-cognition-pack-and-secret-broker-projection.md) Hosted lanes: full Cognition Pack and Secret Broker projection | implemented but unqualified | Controlled projection/reuse passed on both APIs; full owner-selected pack/SecretBroker and both mission reruns remain. |
| [HL-23](../archive/materialization-observation-2026-10/issues/HL-23-provider-smoke-managed-agents-and-agents-api-field-confirmation.md) Provider smoke: Managed Agents and Agents API field confirmation | implemented but unqualified | Smokes/wire-shape research exist; null usage/unknown OpenAI dollars does not prove both smokes under1USD. |
| [HL-24](../archive/materialization-observation-2026-10/issues/HL-24-slice-s2-claude-managed-cloud-end-to-end-launched-remotely.md) Slice S2: claude_managed cloud end to end, launched remotely | blocked | Budget wiring+controlled composition/replay exists; both remote missions/native hold/resume/approval/restart/cost/publication/custody remain; depends MO-74/77/79. |

### P3 cursor_local / cursor_cloud (12)

| Issue | Status | Remaining (from the issue record) |
| --- | --- | --- |
| [CM-01](../archive/materialization-observation-2026-10/issues/CM-01-cloud-and-local-cost-settlement.md) Cloud and local cost settlement | implemented but unqualified | Delayed/unknown/single-debit accounting exists; billed dollar/category settlement unknown. R2A technical settlement is not invoice reconciliation. |
| [CM-02](../archive/materialization-observation-2026-10/issues/CM-02-per-run-token-attribution-across-all-turns.md) Per-run token attribution across all turns | implemented but unqualified | Usage precedence/cache/missing-counter/explicit-total accounting corrected and covered by retained accounting regression receipts in current integration. The65 recent focused memory checks concern StageGraph… |
| [CM-04](../archive/materialization-observation-2026-10/issues/CM-04-cursor-local-on-windows-workers.md) cursor_local on Windows workers | implemented but unqualified | Real Windows Selector-loop fake-SDK fixture passed; native installed CD-15/ACL/hooks remains, opt-in guarded. |
| [CM-05](../archive/materialization-observation-2026-10/issues/CM-05-detached-bridge-and-live-reattach.md) Detached bridge and live reattach | implemented but unqualified | Detached discovery/reattach/lease fences and6 real PostgreSQL races exist; native worker-kill same-run/no-duplicate proof remains. |
| [CM-07](../archive/materialization-observation-2026-10/issues/CM-07-conversation-export-for-forks-and-continuations.md) Conversation export for forks and continuations | implemented but unqualified | Source-bound excerpt/snapshot/fork-packet custody and2 real PostgreSQL cases exist; actual Cloud fork/continuation remains. |
| [CM-08](../archive/materialization-observation-2026-10/issues/CM-08-continuation-and-fork-agent-parity-on-cloud.md) Continuation and fork agent parity on cloud | implemented but unqualified | Create/hydrate identity/options parity/idempotent archive exists; native transfer/recovery remains. |
| [CM-09](../archive/materialization-observation-2026-10/issues/CM-09-cloud-declared-output-custody-and-missing-outputs.md) Cloud declared-output custody and missing outputs | implemented but unqualified | Exact-head/missing-output once/custody code exists; native originating-run artifact attribution/review/publication remains. |
| [CM-10](../archive/materialization-observation-2026-10/issues/CM-10-parallel-cursor-units-in-one-run-get-distinct-workspaces.md) Parallel Cursor units in one run get distinct workspaces | implemented but unqualified | Per-operation branches/leases exist; four-unit exact-placement retry/cleanup/CD-14 remains. |
| [CM-21](../archive/materialization-observation-2026-10/issues/CM-21-cursor-qualification-drills-cd-01-cd-20.md) Cursor qualification drills CD-01..CD-20 | blocked | Some native attempts/recovery exist; complete applicable CD records/describe promotion absent; CM-01/05/09/10 still open. |
| [LS-07](../archive/materialization-observation-2026-10/issues/LS-07-live-smoke-checklist-for-the-cli-open-items.md) Live smoke checklist for the CLI open items | blocked | Native attempts exist: Claude429/current quota unknown; Codex bootstrap fixed only through non-inference marker/write-denial; Cursor CLI unauthenticated; inclusive spend/reserves/remainder unknown. |
| [MO-13](../archive/materialization-observation-2026-10/issues/MO-13-cursor-environments-and-secrets-rest-adapter-bind-sync-with-environment-json-own.md) Cursor environments and secrets REST adapter (bind/sync) with environment.json ownership check | implemented but unqualified | REST sync/ownership refusal exists; required two-mission native reuse/foreign-file drill incomplete. |
| [MO-31](../archive/materialization-observation-2026-10/issues/MO-31-evidence-based-hook-event-mapping-and-cursor-binding-v2.md) Evidence-based hook event mapping and Cursor binding v2 | implemented but unqualified | Hook mapping/binding v2 exists; Missions2/3 exact native launch/tool-enforcement remains. |

### P4 codex_agents (4)

| Issue | Status | Remaining (from the issue record) |
| --- | --- | --- |
| [HL-11](../archive/materialization-observation-2026-10/issues/HL-11-codex-agents-prepare-saved-agents-environment-templates-prewarm-and-vaults-from.md) codex_agents prepare: saved agents, environment templates, prewarm and vaults from pack files | implemented but unqualified | Hosted prepare/controlled unchanged sync creates0 resources; full owner-selected native acceptance remains. |
| [HL-12](../archive/materialization-observation-2026-10/issues/HL-12-codex-agents-session-lifecycle-recovery-recipe-and-frame-classifier.md) codex_agents session lifecycle, recovery recipe and frame classifier | implemented but unqualified | Hosted lifecycle/recovery exists; native worker-kill/items/no-duplicate proof remains. |
| [HL-13](../archive/materialization-observation-2026-10/issues/HL-13-codex-agents-function-tool-effect-gating-and-custody.md) codex_agents function-tool effect gating and custody | implemented but unqualified | Function-tools/custody/publication code exists; five native attempts failed accepted-approval proof. Genuine required_actions allow/current-turn bytes and cost reconciliation remain. |
| [HL-25](../archive/materialization-observation-2026-10/issues/HL-25-slice-s3-codex-agents-hosted-end-to-end-launched-remotely.md) Slice S3: codex_agents hosted end to end, launched remotely | blocked | Hosted HTTP AgentsAPI exists; accepted HL-24 then genuine function approval/killed-task recovery/cost and both remote missions remain. No SDK/Responses substitution. |

### P5 claude_agent_sdk (1)

| Issue | Status | Remaining (from the issue record) |
| --- | --- | --- |
| [MO-73](../archive/materialization-observation-2026-10/issues/MO-73-verify-claude-sessionstore-restore-with-the-custom-transport.md) Verify Claude SessionStore restore with the custom transport | implemented but unqualified | Transport SessionStore restore exists; native fresh-worker/no-lost-turn proof remains. |

### P6 codex (1)

| Issue | Status | Remaining (from the issue record) |
| --- | --- | --- |
| [MO-03](../archive/materialization-observation-2026-10/issues/MO-03-back-codex-kernel-hooks-and-handle-codex-hook-trust.md) Back Codex kernel hooks and handle Codex hook trust | implemented but unqualified | Kernel hooks implemented; exact native before_tool deny and release qualification still needed. |

### Cross-lane: closed lane by lane (9)

| Issue | Status | Remaining (from the issue record) |
| --- | --- | --- |
| [MO-11](../archive/materialization-observation-2026-10/issues/MO-11-secret-broker-port-sources-minting-per-lane-delivery-and-redaction.md) Secret Broker port, sources, minting, per-lane delivery and redaction | implemented but unqualified | Broker/scoped token/redaction exists; selected all-lane native delivery/sentinel proof incomplete. |
| [MO-12](../archive/materialization-observation-2026-10/issues/MO-12-environment-kit-capability-kind-mission-layer-and-bootstrap-entrypoint.md) Environment Kit capability kind, mission layer and bootstrap entrypoint | implemented but unqualified | Kit/catalog/bootstrap exists; exact native prepared receipts for required selected lanes incomplete. |
| [MO-14](../archive/materialization-observation-2026-10/issues/MO-14-git-write-path-scoped-credentials-pre-push-guard-repo-pr-effect-and-head-sha-art.md) Git write path: scoped credentials, pre-push guard, repo_pr effect and head SHA artifacts | implemented but unqualified | Governed publication/branch guards exist; controlled Git/PR-host fixture is not live remote draft-PR qualification. |
| [MO-22](../archive/materialization-observation-2026-10/issues/MO-22-missionctl-setup-wizard-probe-missions-and-attestations.md) missionctl setup wizard, probe missions and attestations | implemented but unqualified | Wizard/probes and prior owner setup exist; current exact Cursor+Anthropic selected setup not blanket-qualified. |
| [MO-33](../archive/materialization-observation-2026-10/issues/MO-33-ambient-cognition-inventory-and-policy.md) Ambient cognition inventory and policy | implemented but unqualified | Ambient inventory/policy exists; observed per-local-lane native receipt/discovery incomplete. |
| [MO-34](../archive/materialization-observation-2026-10/issues/MO-34-discovery-proof-per-lane.md) Discovery proof per lane | implemented but unqualified | Discovery service exists; delivered/read-back/exercised are distinct; all required native discovered receipts incomplete. |
| [MO-41](../archive/materialization-observation-2026-10/issues/MO-41-telemetry-hook-pack-mc-signal-cli-and-signal-emit-tool.md) Telemetry Hook Pack, mc-signal CLI and signal_emit tool | implemented but unqualified | Telemetry pack/CLI/tool exists; native ordered cloud started/materialized/stop stream remains. |
| [MO-42](../archive/materialization-observation-2026-10/issues/MO-42-gate-hooks-and-remote-stop-fence.md) Gate hooks and remote stop fence | implemented but unqualified | Gate/stop fence exists; real one-tool cancellation and fail-closed deployed evidence remains. |
| [MO-51](../archive/materialization-observation-2026-10/issues/MO-51-knowledge-workspaces-and-output-channels.md) Knowledge workspaces and output channels | implemented but unqualified | Workspace/output contracts exist; native accepted no-code mission on cloud/managed/local still required. |

### Stream R and Signal Ingress (not lane work) (7)

| Issue | Status | Remaining (from the issue record) |
| --- | --- | --- |
| [MO-63](../archive/materialization-observation-2026-10/issues/MO-63-lane-only-worker-role.md) Lane-only worker role | implemented but unqualified | Lane-only role/queue exclusion exists; actual WSL lane+one AWS base worker complete operation remains. |
| [MO-64](../archive/materialization-observation-2026-10/issues/MO-64-split-host-payload-custody-preflight.md) Split-host payload custody preflight | implemented but unqualified | Split-host marker/S3 preflight exists; actual cross-host byte/custody roundtrip remains; equal marker strings insufficient. |
| [MO-77](../archive/materialization-observation-2026-10/issues/MO-77-thin-temporal-worker-on-aws-ecs-fargate-us-east-1.md) Thin Temporal worker on AWS ECS Fargate (us-east-1) | implemented but unqualified | Actual immutable AWS task/build/queue/poller/sentinel precedent exists; latest service0 tasks. Outside-network/laptop-off/restart24h/cost acceptance remains. |
| [MO-79](../archive/materialization-observation-2026-10/issues/MO-79-remote-launch-request-route-on-the-signal-ingress.md) Remote launch-request route on the Signal Ingress | implemented but unqualified | Normal-handler idempotency/PG/Temporal fixture exists; actual outside-network AWS admission/status still unqualified. |
| [MO-74](../archive/materialization-observation-2026-10/issues/MO-74-vercel-ingress-project-slim-import-closure-and-deployment.md) Vercel ingress project, slim import closure and deployment | implemented but unqualified | Slim closure/deployment code/release exists; installed1.4.2 verified. Deployed health/auth/latency/size/two-project qualification remain; do not rerun original migration. |
| [MO-75](../archive/materialization-observation-2026-10/issues/MO-75-ingressdrainer-worker-role.md) IngressDrainer worker role | implemented but unqualified | Scoped replay/claim/dedupe/dead/history reconciliation has real PostgreSQL evidence; deployed LISTEN latency/native complete history remains. |
| [MO-76](../archive/materialization-observation-2026-10/issues/MO-76-signed-artifact-uploads-with-quarantine-and-custody.md) Signed artifact uploads with quarantine and custody | implemented but unqualified | Signed quarantine byte/digest/scope/custody exists; actual>4.5MB upload/tamper/revoke/cleanup remains. |

### S4 funding hold (8)

| Issue | Status | Remaining (from the issue record) |
| --- | --- | --- |
| [HL-01](../archive/materialization-observation-2026-10/issues/HL-01-daytona-qualification-on-the-current-tier.md) Daytona qualification on the current tier | blocked | Wait for explicit S4 funding release; then deliver the exact SandboxHost/gateway/self-hosted implementation and recorded drill in this acceptance. |
| [HL-02](../archive/materialization-observation-2026-10/issues/HL-02-sandboxhost-port-with-docker-wsl2-and-daytona-adapters.md) SandboxHost port with Docker (WSL2) and Daytona adapters | blocked | Wait for explicit S4 funding release; then deliver the exact SandboxHost/gateway/self-hosted implementation and recorded drill in this acceptance. |
| [HL-03](../archive/materialization-observation-2026-10/issues/HL-03-model-gateway-keyless-model-access-from-sandboxes.md) Model Gateway: keyless model access from sandboxes | blocked | Wait for explicit S4 funding release; then deliver the exact SandboxHost/gateway/self-hosted implementation and recorded drill in this acceptance. |
| [HL-10](../archive/materialization-observation-2026-10/issues/HL-10-claude-managed-self-hosted-placement-on-sandboxhost.md) claude_managed self_hosted placement on SandboxHost | blocked | Wait for explicit S4 funding release; then deliver the exact SandboxHost/gateway/self-hosted implementation and recorded drill in this acceptance. |
| [HL-14](../archive/materialization-observation-2026-10/issues/HL-14-codex-agents-self-hosted-executor-on-sandboxhost.md) codex_agents self_hosted executor on SandboxHost | blocked | Wait for explicit S4 funding release; then deliver the exact SandboxHost/gateway/self-hosted implementation and recorded drill in this acceptance. |
| [HL-15](../archive/materialization-observation-2026-10/issues/HL-15-claude-agent-sdk-on-sandbox-host-real-claude-code-harness.md) claude_agent_sdk on Sandbox Host (real Claude Code harness) | blocked | Wait for explicit S4 funding release; then deliver the exact SandboxHost/gateway/self-hosted implementation and recorded drill in this acceptance. |
| [HL-16](../archive/materialization-observation-2026-10/issues/HL-16-codex-app-server-with-remote-exec-server-executor.md) codex app-server with remote exec-server executor | blocked | Wait for explicit S4 funding release; then deliver the exact SandboxHost/gateway/self-hosted implementation and recorded drill in this acceptance. |
| [HL-20](../archive/materialization-observation-2026-10/issues/HL-20-self-hosted-placement-and-sandbox-host-qualification-drills-funding-gated.md) Self-hosted placement and Sandbox Host qualification drills (funding-gated) | blocked | Wait for explicit S4 funding release; then deliver the exact SandboxHost/gateway/self-hosted implementation and recorded drill in this acceptance. |

### Deferred by the owner (not started) (13)

| Issue | Status | Remaining (from the issue record) |
| --- | --- | --- |
| [CM-06](../archive/materialization-observation-2026-10/issues/CM-06-local-store-and-conversation-fork-drill-gated.md) Local store and conversation fork, drill-gated | genuinely not started | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |
| [CM-11](../archive/materialization-observation-2026-10/issues/CM-11-model-selection-with-params-and-validation.md) Model selection with params and validation | genuinely not started | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |
| [CM-12](../archive/materialization-observation-2026-10/issues/CM-12-subagent-honesty.md) Subagent honesty | genuinely not started | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |
| [CM-14](../archive/materialization-observation-2026-10/issues/CM-14-context-occupancy-for-cursor.md) Context occupancy for Cursor | genuinely not started | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |
| [CM-15](../archive/materialization-observation-2026-10/issues/CM-15-plan-then-approve-gate.md) Plan-then-approve gate | genuinely not started | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |
| [CM-16](../archive/materialization-observation-2026-10/issues/CM-16-local-approval-and-question-channel-through-custom-tools.md) Local approval and question channel through custom tools | genuinely not started | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |
| [CM-17](../archive/materialization-observation-2026-10/issues/CM-17-cloud-agent-hygiene-sweep.md) Cloud agent hygiene sweep | genuinely not started | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |
| [CM-20](../archive/materialization-observation-2026-10/issues/CM-20-follow-up-prompt-images-and-per-turn-mode-passthrough.md) Follow-up prompt images and per-turn mode passthrough | genuinely not started | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |
| [CM-22](../archive/materialization-observation-2026-10/issues/CM-22-no-repo-cursor-cloud-agents-for-knowledge-work.md) No-repo cursor_cloud agents for knowledge work | genuinely not started | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |
| [MO-53](../archive/materialization-observation-2026-10/issues/MO-53-cross-lane-forks-between-cloud-and-local.md) Cross-lane forks between cloud and local | genuinely not started | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |
| [SC-01](../archive/materialization-observation-2026-10/issues/SC-01-qualification-probes-for-subscription-cloud-surfaces.md) Qualification probes for subscription cloud surfaces | blocked | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |
| [SC-02](../archive/materialization-observation-2026-10/issues/SC-02-claude-cloud-experimental-launch-and-observe-lane.md) claude_cloud experimental launch-and-observe lane | genuinely not started | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |
| [SC-03](../archive/materialization-observation-2026-10/issues/SC-03-codex-cloud-experimental-launch-and-collect-lane.md) codex_cloud experimental launch-and-collect lane | genuinely not started | Keep outside current execution; require an explicit scope change before implementing or drilling this specific deliverable. |

## 6. Fixtures and cells

| Item | State | Destination |
| --- | --- | --- |
| F0 full configuration compilation, F1 representative SDLC | passed | — |
| F2 | deferred (owner D6) | unscheduled |
| F3 negative composition controls (conflicting skill, hook removal, overwritten AGENTS.md) | partial; negatives not run | each provider sprint's C01 (FX-GD1) |
| F4 controls, restart and accounting | partial: inject, typed allow/deny, cancel and worker-restart redelivery are evidenced. Usage figures were not | C07, C08 (FX-GD4) and the usage work (RF-15) |
| MR-03 / MR-13 cursor_local local and Cloud | blocked / not run | P3 |
| 18 original S0 cells | superseded by E1 (`FINAL-CAPABILITY-S0-18-CELLS.json`) | — |
| S0-01 promotion (inject applied on the completing run, attributable usage) | not promoted | C07 and the usage work in P5 |

## 7. Owner decisions and holds still open

| Item | State |
| --- | --- |
| Program decisions D1–D9 ([README §9](README.md#9-owner-decisions-needed)) | Open. On 2026-10-20 the owner decided to proceed **one provider at a time**, which is the program's shape. The individual decisions remain to be taken |
| Streams R, S1, S2, S3 | Carried forward (Run 2 D1); S2/S3 are the P2/P4 hosted proofs |
| S4 (SandboxHost, Daytona, Model Gateway, self-hosted placement) | Funding hold |
| AF-FOLLOWON-01 agent-facing Mission Control consolidation | Not scheduled; starts only on the owner's initiation |
| Owner TODO: multi-agent on code missions | P2 (C10) |
| Spend reconciliation | Done: the owner checked the OpenAI dashboard on 2026-10-20 and accepted the spend. Anthropic is about 1.0 USD, native-reported. The 5 USD Anthropic planning reservation from the S0 slice is still held |

## 8. Restarting live work

Run 2's serving tooling is private and lives outside the repository. Before a provider sprint's
first live tier (T2/T3):

1. Read the [WSL2 worker runbook](../../WSL2_WORKER_RUNBOOK.md). It covers the owner prerequisites
   per lane (A8 Claude, X4/X6 Codex, C9 Cursor, M4 all), their attestation, re-pointing to Temporal
   Cloud and the memory notes.
2. The private G1 WSL venv `~/.venvs/mc-run2-close` was reinstalled on 2026-10-20 from
   `platform/mission-control` (`uv sync --frozen --inexact --group biotech --group dbcontract`). The
   same 214 distributions are installed, and the three editable packages point at the canonical
   checkout. The G1 scripts' `MAIN` paths were repointed to it as well (backups in
   `run2-close-20261018/pre-canon-20261020/`). After any `uv.lock` change, re-run the sync.
3. Private tooling: `C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-close-20261018/g1/`. It
   contains `restart_g1.py`, `serve.py`, `mint_token.py`, the attestors, `mr_run.py`,
   `policy.py`, and `config/` with local and `*.cloud.json` sets. Receipts are in `w1/`–`w6/`.
4. Credentials live only in the canonical checkout's git-ignored `.env`. Cite them by name, never
   by value. The Temporal Cloud API key is in AWS Secrets Manager
   `mission-control/ai-engineer/TEMPORAL_CLOUD_API_KEY`.
5. Host limits: about 15 GB RAM. Run one heavy job at a time behind the memory guard. Docker Desktop
   restarts the Biotech ingestion containers, and the WSL page cache must be dropped after large
   hashing. The Cursor SDK bridge needs about 200 MB on WSL. The Windows `cursor-agent` CLI commits
   about 3.6 GB.
6. The parked runs were settled on 2026-10-20 (§3). For future `in_doubt` units, use the reconciliation
   grant (`g1/mint_token.py --actor reconciler`) rather than the launcher. Spend for Run 2 was reconciled by the owner on
   2026-10-20.

## 9. How a provider sprint uses this register

In phase A (audit), the sprint copies its group from §5, its RF rows from §4 and its parked runs
from §3 into `providers/<lane>/AUDIT.md`. In phase E (close), it records each item as closed by
receipt, moved, or deferred with the owner's reason, and updates this register's destination column
to point at the sprint's `CLOSE.md`.
