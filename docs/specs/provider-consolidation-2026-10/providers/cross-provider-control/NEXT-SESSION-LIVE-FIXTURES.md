---
type: Handoff
title: "Next session: real workflow fixtures on cursor_local, claude_managed and codex_agents, with the Deep Agents frontier kept intact"
description: "Owner instruction of 2026-11-06 after the cross-provider control commit 0d2cc6b5: run real (paid, bounded) workflow fixtures on the Cursor local SDK lane, Anthropic Managed Agents and the OpenAI Agents API, prove the new points, state-as-of and seeded forks on each, and lose nothing of the Deep Agents Sprint OC frontier (W1 at the verifier, experiment loop iteration 3). State at start, the Deep Agents frontier to preserve, per-lane preflight and runners, the recommended order, budget, decisions for the owner, evidence to record and the known pre-existing failures."
tags: [mission-control, providers, cross-provider, live-fixtures, cursor, managed-agents, agents-api, deep-agents, handoff]
status: active
date: 2026-11-06
---

# Next session: real workflow fixtures on three lanes, Deep Agents frontier intact

**Owner (2026-11-06):** "I am most concerned with running real workflow fixtures with cursor local sdk, anthropic
managed agents and openai agents. I also do not want to lose where we were at with deep agents." Read this file, then
[DESIGN](DESIGN.md) §1-§5, the [concept](../../../../knowledge/cross-provider-control.md), the three lane records
([cursor](../cursor/CONTROL-ARCHITECTURE.md), [claude_managed](../anthropic_managed/CONTROL-ARCHITECTURE.md),
[codex_agents](../openai_agents/CONTROL-ARCHITECTURE.md)) and the Sprint OC board
([NEXT-SESSION](../../sprint-oc/NEXT-SESSION.md)). Standing rules: [decisions](../../../../knowledge/decisions.md#owner-directives-by-date);
budgets: [budgets and usage](../../../../knowledge/budgets-and-usage.md). Before any database or environment work read BellLabs
`docs/navigation/DATA-PLANES-AND-CREDENTIALS.md`. **Nothing in this handoff authorizes a paid call**: the owner names the
budget and the models at session start (§6).

## 1. State at start (2026-11-06)

- Mission Control `main` was at `0d2cc6b5` when this was written. **Update 2026-11-06:** the repository moved to the
  jbell-rusty-vantage account as a clean slate, so that ID and the others below are pre-move labels and are not in this history
  ([repository history](../../../../REPOSITORY-HISTORY.md)). The source is unchanged. Push to the new `origin`; the Overton77
  remote is legacy. Linear OVE-224 In Progress.
- Every session lane now writes one `mc.cognition_point.v1` row per step boundary at `lane.turn` settlement, reads
  `state-as-of` and seeds forks at its declared level: `cursor_local`/`cursor_cloud` R2, `claude_agent_sdk` R3, `codex` R3,
  `claude_managed` R1, `codex_agents` R1. Steering is implemented (Codex `turn/steer`, Managed Agents and the Agents API by a
  message during the turn) but every lane still declares `interrupt_and_inject: cancel_and_replace`. Nothing is qualified;
  no paid call was made on 2026-11-05.
- Release **1.14.0** (`0073_cross_provider_lane_describes.sql`) is built locally and proven (fresh and upgrade); **not
  installed** on any remote. The AI Engineer remote holds 1.13.0, Biotech 1.9.0. The runtime's `REQUIRED_MIGRATIONS` stop at
  0072, so a worker runs against 1.13.0 remotes; the local disposable gets 1.14.0 through the proof test or `mission-db`.
- Local stack recipe that worked: `make infra-up` (compose PostgreSQL 16 on 55432, Redis 16379, Temporal 7233, UI 8080) and
  `docker start mc-ft-disposable-pg17` (PostgreSQL 17 on 55433; `MISSION_CONTROL_TEST_ADMIN_DSN` from the container's
  `POSTGRES_PASSWORD`, never printed). Run pytest **one process at a time**: two concurrent suites plus Docker exhaust the
  15 GB host and Claude Code kills background jobs (seen twice on 2026-11-06).
- Credentials present in `platform/mission-control/.env` by name: `CURSOR_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
  (values never printed). Owner model pins for paid work are in `sprint-oc/PROOFS.md` §6 (producer `claude-sonnet-5-5`,
  probes `gpt-5.6-luna`); the HL-23 smoke used `claude-sonnet-5-5` and `gpt-6-luna`; the owner names the models.

## 2. The Deep Agents frontier to preserve (do not reopen, do not lose)

Deep Agents is still the principal provider and its Sprint OC state is unchanged by 2026-11-05/06:

- **W1 (AI Engineer) is at the verifier.** Next, in the board's order: D41 (bound a verifier turn; owner decided in-turn run
  budget), D39, D40 test-first; rerun the Sonnet report for the first verdict; Fulfillment@1 (D28/D29), D27; a kill during an
  activity; the D30 probe; the native write with aieng-db readback; then Biotech (remote still 1.9.0). Evidence:
  `sprint-oc/release/W1-EVIDENCE.md`. Spend so far at most USD 1.407 of the 6.00 loop cap.
- **Experiment loop iteration 3** (`sprint-oc/experiments/ITER-2-2026-11-03.md` "Iteration 3 plan"): test-first L2-03,
  L2-01, L2-04, L2-05, L2-06, L2-07, L2-08, L2-09, L2-10, then rerun E2-E5 with E1 as regression; **L2-02 waits on the
  owner's decision** on where operator instructions go and what "applied" must prove.
- The cross-provider work touched the kernel paths Deep Agents shares (`lane_turns.py`, `operation_execution.py`
  `_settle`, `cognitive_seed.py`, time-travel registry composition). Proof that Deep Agents is unaffected: its unit suites
  pass; `tests/integration/temporal/test_lane_turn.py` (15), the inject/fork/lineage PostgreSQL suites (24) pass; the Deep Agents
  acceptance drill (`tests/acceptance/mission_control/test_cognition_points.py`) could **not** run because the local
  `.runtime/capability-bundles` custody no longer holds manifest `4cf3e239…` (environment, not code). **First Deep Agents
  action of the next session: restore that custody and run the drill** before any W1 step. The digest is not pinned in the
  repository: it comes from the skill pins the worker's `.env` names (`CapabilityPins.from_settings`), and the bundle bytes were
  published to the local store (`capability_bundle_local_root`, `bootstrap/bundle_custody.py`) by
  `scripts/publish_skill_bundle.py <skills/<bundle>> --asset-id ... --version ...` on 2026-10-21; republish the pinned bundles
  from `skills/` (manifests under `skills/*/manifest.json`, `make skills-check`) or point the root at a copy that still holds them.
- The AI Engineer schema program runs in its own session (Builds 01-07 accepted; next RV19 / service increment 2 / MC
  integration) and does not touch Mission Control runtime; leave it be.

## 3. What a "real workflow fixture" must prove on each lane (new since 0d2cc6b5)

Beside the lane's existing live drill, every fixture adds the cross-provider assertions, in this order, on the same run:

1. the mission completes on the lane (Stage Graph first; a two-stage draft/review manifest is enough);
2. `missionctl run points RUN` lists one row per step boundary (tool close, model message, turn end) with the lane's native
   identity, `frame_from/to_ordinal`, `usage_delta` and `message_count`; the transcript `--by step` joins them;
3. `missionctl run state-as-of RUN --point ID` returns the declared level (R2 files for Cursor, R1 messages for the hosted
   lanes), `history: reconstructed`;
4. `missionctl run fork --point ID --inject FILE` on a seedable point produces a derived run whose first turn starts from
   the seed head (the hydration transcript or restored lease) and whose `fork_seed` point carries `seed_head`;
5. an inject into a running turn (`cancel_and_replace`) marks the interrupted turn's last point `interrupted` and the
   replacement's first `replacement_start`; an immediate cancel settles `cancelled` with its points written.

Evidence goes under `.scratch/cross-provider-live-<date>/<lane>/` (receipts, `run inspect`, points JSON, state-as-of JSON,
the transcript) and the lane's `CONTROL-ARCHITECTURE.md` table moves the rows from "tested" to "integrated (live)" with the
run ids; nothing flips `qualified` (that is a reviewed release citing `docs/qualification/lanes/<profile>-<date>.md`).

## 4. Per-lane preflight and runners

### 4.1 `cursor_local` (owner's first)

- **Host:** refused on Windows (`LANE_UNSUPPORTED_OS`); needs the WSL2 worker. Ubuntu WSL2 is installed and running. Runbook:
  `docs/WSL2_WORKER_RUNBOOK.md` (host layout, configuration files, secrets, owner prerequisites per lane, memory, gotchas) and
  `docs/MISSION_CONTROL_LOCAL_API.md` "WSL2 worker for the local Claude and Codex lanes"; toolchain
  `scripts/wsl/install_worker_toolchain.sh`; `cursor-sdk==1.0.37` with its own bundled Node bridge; explicit `CURSOR_LEASE_ROOT`.
- **Configuration:** launch bindings `mc.manifest_launch_bindings.v2` with a `providers.cursor_local` entry (`repositories`
  keyed by the manifest's `repo.path`, `pins` = `REQUIRED_CURSOR_PINS`, `lease_root`, `hook_callback.listen`); auth profiles
  `mc.auth_profile.v1` with `env:CURSOR_API_KEY`; examples under `deployments/examples/manifest-launch-bindings.multi-provider*.json`
  and `provider-auth-profiles.example.json`. Admission needs `MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES=true`.
- **Known blocker to reproduce first:** RF-18 / MR-03 (`7132d2de`, 2026-10-20): the SDK rejected `observe_run` six seconds
  into the first turn and the native agent ran unobserved. Nothing since has touched that path. Reproduce with the cheapest
  run: `MC_CURSOR_LOCAL_LIVE=1` `tests/integration/cursor/test_cursor_local_live.py` (one agent, one tiny turn). If it
  reproduces, diagnose there (`adapters/cursor/bridge.py`, `local.py` observe path, SDK `observe_run` signature on 1.0.37)
  before spending on a mission.
- **Then:** `make lane-qualify PROFILE=cursor_local LIVE=1` (`MC_LIVE_CURSOR_QUALIFICATION=1`, finite `MC_PAID_BUDGET_USD`;
  the repeated cancel-latency and busy drills need `MC_LANE_DRILL_APPROVAL_URL`), then the Stage Graph mission
  `tests/fixtures/manifests/multi-provider/cursor-local.stage-graph.mission.yml` with §3's assertions. Pre-existing local
  fixture failure to ignore: `test_cursor_local_fixtures.py[precompact]`.

### 4.2 `claude_managed` (Anthropic Managed Agents)

- **Host:** any; HTTPS from the Windows worker. Worker opt-in `MISSION_CONTROL_CLAUDE_MANAGED_LANE=true` on the hosted queue
  `mc-ai-engineer-lane-hosted`; the checked-in pack `deployments/hosted-packs/ai-engineer/claude_managed/pack.yaml`; the
  application is AI Engineer (its remote holds 1.13.0 and the packs); `MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES=true`.
- **Runners, cheapest first:** `MC_CLAUDE_MANAGED_LIVE=1` `tests/integration/anthropic_managed/test_pack_sync_live.py` (sync
  twice, no session, no tokens; labels every resource `mc_run=$MC_RUN_LABEL`, cleans up unless `MC_CLAUDE_MANAGED_KEEP=1`,
  evidence at `MC_CLAUDE_MANAGED_EVIDENCE`); then `test_session_lifecycle_live.py` (a full turn and an interrupted turn on
  the real `OperationWorkflow`; `MC_TEMPORAL_TEST_ADDRESS` for the local server); then a Stage Graph mission on the lane:
  **the HL-24 end-to-end drill has never run.** Budget pause (`hold_budget`) is unproven.
- **Provider facts (HL-23 smoke, 2026-10-12):** `user.message` during `running` is consumed mid-turn (Q-M1 yes, the basis of
  the implemented steer); `list_cost` settles usage. Unverified: session fork or history import (R3 refused by design).
- **Pre-existing failure to avoid:** `test_managed_segment_loop_real_services.py::test_a_worker_killed_mid_turn...` fails on
  `history close execution is no longer live` (`adapters/postgres/lanes/execution_state.py:151`) on HEAD too; do not plan a
  worker-kill variant on this lane until that is triaged.

### 4.3 `codex_agents` (OpenAI Agents API)

- **Host:** any; `MISSION_CONTROL_CODEX_AGENTS_LANE=true`, same hosted queue, pack
  `deployments/hosted-packs/ai-engineer/codex_agents/pack.yaml`; `OPENAI_API_KEY`; model per the owner (HL-23 accepted `gpt-6-luna`).
- **Runners, cheapest first:** `MC_HL21_PROJECTION_LIVE=1` `tests/integration/openai_agents/test_projection_live.py` (control
  plane projection and readback, no inference); `test_function_tools_live.py` (approval and recovery through the real API,
  `MC_PAID_BUDGET_USD`); then the Stage Graph mission: **the HL-25 end-to-end drill has never run.** Only Mission Control
  function tools raise `required_actions`; built-in shell and file tools are ungated (missions needing per-command approval
  resolve to `codex`).
- **Pre-existing failure to avoid:** `test_agents_worker_recovery.py::test_worker_loss_restores_items...` (same
  `history close execution is no longer live`).

## 5. Recommended order (and why)

1. Restore the Deep Agents acceptance custody and run `test_cognition_points.py` (§2) so the reference lane is green before
   anything else; zero spend.
2. Zero-token hosted preflights in parallel with the WSL toolchain install: `test_pack_sync_live.py` (Managed) and
   `test_projection_live.py` (Agents API). They prove credentials, packs and the control plane without model spend.
3. `cursor_local` smoke to confirm or clear RF-18 (one tiny paid turn). If RF-18 reproduces, fix it test-first; the Cursor
   mission waits for that.
4. First real mission on whichever lane is ready: hosted lanes need no WSL, so `claude_managed` is the likely first full
   workflow fixture, then `codex_agents`, then `cursor_local` once RF-18 is clear. Each with §3's five assertions.
5. Record: `.scratch` evidence, the lane records, a ledger row per run, `docs/qualification/lanes/<profile>-<date>.md`
   where a drill completed, and this file's §1 updated in place.

The owner's stated order (Cursor, Managed, Agents) stands for priority; step 4 only sequences by readiness within one
session. If the owner prefers Cursor strictly first, do steps 1-3 and spend the remaining budget on RF-18 and the Cursor mission.

## 6. Decisions for the owner at session start

1. **Budget and models** for this session (standing: USD 15 per session; the Sprint OC loop cap is separate at USD 6).
   Recommendation: USD 10 for the three lanes, at most USD 3 per lane, models per PROOFS §6 unless the owner names others.
2. **Application** for the hosted missions: AI Engineer (packs and the 1.13.0 remote exist) or Biotech (1.9.0, no packs).
   Recommendation: AI Engineer; keep the AI Engineer graph `4773dc72` untouched as always.
3. **Install 1.14.0 on the AI Engineer remote** before the hosted runs (describe refresh only, data; the runtime does not
   require it)? Recommendation: yes, through `mission-db` with a receipt, since the worker's declared matrices now differ from
   the remote's rows and `lane list` would disagree with admission otherwise.
4. **Declare steering** (`cooperative_inject`) on `codex_agents`/`claude_managed` after a live steer proof, or keep
   `cancel_and_replace`? Recommendation: keep `cancel_and_replace` this session; prove the steer path live, then flip with
   the conformance pin change in a reviewed change.
5. **GitHub**: decided 2026-11-06. Mission Control lives on jbell-rusty-vantage as a clean-slate, `main`-only repository;
   do not push to Overton77 ([repository history](../../../../REPOSITORY-HISTORY.md)).

## 7. Pre-existing failures (reproduced on a detached HEAD worktree 2026-11-06; not caused by 0d2cc6b5)

Unit: `tests/unit/harness/test_cursor_local.py::test_closing_facts_map_every_run_result_status` (4),
`tests/unit/operations/test_rrm_008_cancellation.py::test_cancel_before_dispatch_settles_cancelled_without_cognition`,
`tests/unit/recovery/test_terminal_evidence_adoption.py::test_finished_evidence_adopts_without_native_control_and_normal_family_quarantines`,
`tests/unit/control_plane/test_digest_set_order_guard.py` (2), `tests/unit/runtime/test_run2_worker_deploy_script.py` (22),
`tests/unit/schema/*` (7), `tests/unit/orchestration/{test_completion_requirements,test_mp20_stagegraph_concluded_failure,test_wi08_graph_routes,test_wi08_revisit_regions}.py` (6),
`tests/unit/prerequisites/test_setup.py` (1). Integration: the three `cursor` real-services tests (telemetry drill, mp09 cloud
segment loop ×2), the `precompact` local fixture, the Managed and Agents worker-loss reattach tests, and
`test_mp08_codex_lane_turns.py` (3; the child-environment `OPENAI_API_KEY` assertion and two that follow). File OVE issues
for the worker-loss reattach defect and the mp08 assertion before relying on either path live.

## 8. Open cross-provider items carried (from the ledger)

A Cursor, Codex or Claude unit through `OperationWorkflow` with the Postgres lineage (the live fixtures above are that
proof); `session_turn.point_ref` for session lanes; the reconciler walking session-lane generations
(`list_run_generations` walks checkpoint transitions only); declared steering; `codex_cloud`/`claude_cloud` stay
architecture only; retention of session-lane points follows the mission (no pruning policy change).
