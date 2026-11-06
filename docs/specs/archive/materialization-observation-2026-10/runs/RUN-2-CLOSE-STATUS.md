---
type: Sprint Close-out Status
title: "Run 2 close-out status (in place, appended per phase)"
description: "Single in-place status ledger for the Gate L close-out of Run 2: phase records, leases, commands, results, evidence hashes, spend and blockers. Private receipts stay outside the repository."
---

# Run 2 close-out status

Lead: Claude Code on `claude-opus-5-5` (verified in the session UI and the
model identity reported to the session). Procedure:
[instructions](../RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md),
[sequence](../RUN-2-EXECUTION-SEQUENCE-2026-10-18.md),
[Gate L disposition](RUN-2-GATE-L-DISPOSITION-2026-10-18.md).
Private session evidence directory (outside the repository):
`C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-close-20261018/`.
Statuses here are records of what ran; no issue, SPEC or S0 cell is promoted
except from the receipt that satisfies the exact clause.

## Owner decisions applied (recorded 2026-10-18)

| ID | Decision |
| --- | --- |
| D1 | Run 2 closes at Gate L; R, S1, S2, S3 and funding-held S4 carry forward. |
| D2 | Implementer Claude Code `claude-opus-5-5` (lead, implementers, reviewers); Sonnet 5.5 permitted for exploration/evidence/test-running. |
| D3 | Native local-lane fixtures authorized within fresh ceilings and 10 USD slice caps, one bounded job at a time. |
| D4 | Stale 10 USD Cursor LS hold released on the recorded dashboard evidence. |
| D5 | Report-schema seed release approved end to end including live apply to AI Engineer, strictly under the listed conditions. |
| D6 | F2 deferred (owner-deferred 2026-10-18). |
| D7 | Local commits and local `main` merges authorized; no push, no deployment, no S4 release. |
| Unattended | Owner away; uncovered decisions are recorded as blocked, never asked. |
| Authentication | No interactive authentication; failures recorded as deficiencies and the dependent cells blocked. |

## P0 — Startup and reconciliation (read-only)

- Lease: none.
- Model: `claude-opus-5-5`.
- MAIN `C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main`: branch `main`,
  HEAD `1d081297bde6fd74e9276df45102eef3c0dc746d`, 60 ahead of local `origin/main`.
- Dirty set at P0: 14 modified (packet `README.md` and the eleven SPEC files carrying the
  2026-10-18 Gate L banner, `runs/RUN-2-CURRENT-INTEGRATION-2026-10-17.md`, the
  `cursor_bridge_recovery.py` overlay) and 22 untracked. This differs from the
  3 + 16 recorded in the sequence by exactly the 2026-10-18 preparation bytes (banners,
  four packet documents, the Gate L disposition); nothing else.
- Overlay `src/mission_control/application/execution/harness/cursor_bridge_recovery.py`
  SHA256 `5280d379279cfddc5999ce3be3a95b6c40ec0e20e7b34ae7fe522452775e49c0`: match.
- Packet documents `RUN-2-MISSION.md`, `RUN-2-AGENT-TEAM-HANDOFF-2026-10-17.md`,
  `RUN-2-EXECUTION-SEQUENCE-2026-10-18.md`, `RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md`:
  byte-identical between MAIN and CANON. Eleven SPECs and `README.md` carry the Gate L banner;
  `runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md` exists (21 Gate L / 38 done / 30 carried /
  8 funding-held / 13 deferred).
- Worktrees: 12 (as in the 2026-10-17 handoff section 5).
- Wheel `run2-fresh-session-20261017/g1-current-build/artifacts/mission_control-0.1.0-py3-none-any.whl`
  present, not installed. Skills `.agents/skills/{coding-cli-jobs,claude-code-headless,codex-exec,cursor-agent-headless}` present.
- Checks (MAIN, P0): `git diff --check` passed; `agents_docs_index.py --check` passed;
  `validate_okf.py` passed (45 concepts); `check_links.py` passed (439 files, 0 broken).
- Memory at P0: 2840 MB free physical, 2987 MB commit headroom (floor 1.5 GiB).
- Evidence: `p0/p0-readonly.txt` SHA256 `1ba5f07e02ea63bb58650744ca8fa6cdc5839d9aaa84faab9f01a1ffcf3f95fd`.
- Cost: none.
- Next lease: P1 installation configuration source.

## P1 — Installation configuration source (complete, commit c49862bf)

- Lease: `src/mission_control/bootstrap/{manifests,settings,installation_config}.py`,
  minimal compile-side changes in `application/authoring/{manifest_v2_admission,manifest_service}.py`
  and `domain/authoring/mission_environment.py`, tests in `tests/unit/authoring/`, two knowledge pages,
  `deployments/examples/installation-config.example.json`.
- Implementer: Opus 5.5 in isolated worktree `run2-close-p1` (branch `mo/run2-close-p1-config`, base `af2d24fc`).
- Review round 1 (fresh Opus 5.5 reviewer): CHANGES REQUIRED — single-application file broke multi-application
  API composition; compile-side `config_secret_like` unreachable in production; three suggestions. All fixed.
- Review round 2 (new fresh Opus 5.5 reviewer on the changed diff): APPROVE WITH NITS. Nits not adopted
  (recorded): duplicate-key message prints the full key; UTF-8 BOM file refused as not-JSON; file reloaded
  per composed scope.
- Behavior: one Settings field `mission_control_installation_config_path` names an `mc.installation_config.v1`
  file `{applications: {<app>: {<key>: <value>}}}`; composition passes the composing Application's mapping to
  `CatalogEnvironmentInputs(config=...)`; secret-like keys refused at load and (key-only, first) at compile
  (`config_secret_like`); unknown keys stay `config_unresolved`; values never in reports/templates/errors.
  Known limit (not in lease): configuration values are not delivered to a lane's runtime child environment.
- Reviewed diff `p1/p1-implementer.diff` SHA256 `547051f64773447523f5e800704b0218e4787b85411d3ee4bbd349dc947f4d2f`,
  applied to MAIN byte-identical to the reviewed worktree (12 files).
- Worktree checks (implementer and reviewer, identical bytes): ruff/format passed; mypy (6 modules) passed;
  authoring tests 108 + 67 passed, reviewer 147 passed; worker roles 3 passed; architecture 12 passed; OKF and
  docs index passed.
- MAIN rerun: first attempt stopped by Claude Code under host memory pressure (mypy unrun); the user then directed
  active resource management and approved continuing. Rerun through the memory guard
  (`resources/guard.py`, foreground): ruff, format, mypy (6 modules) passed; pytest 190 passed (authoring, kits,
  worker roles, architecture); OKF and docs index passed (`p1/main-checks-2.txt`). Commit hooks (ruff, format, ty,
  deptry) passed. Commit `c49862bf`. P1 worktree retired (junction unlinked first, shared venv verified intact).
- P2 step 1 (read-only, done early): AI Engineer catalog check as `mc_ai_engineer_runtime_login` in a read-only
  transaction: installation `01a103c0-9a9e-70f3-9398-eb1573a98324`, component 1.4.2, 37 component releases; the
  only published artifact schema is `schema.s0-probe-report@1`; `plugin.cognition-sdlc` present. Diagnosis,
  patch and review report schemas are **absent** → D5 seed release required. Evidence `p2/catalog-check.json`
  SHA256 `b7b986ae13cf0d4a3acfa08ebd750913d1a9ee201a809c60db3e63f78a2067ad` (script `p2/catalog_check.py`
  `869a7dbc…`). D5 implementer brief prepared at `p2/d5-brief.md`, not yet launched.
- Cost so far: none (no provider inference).

## P2 / D5 — report-schema seed release (complete)

- Lease: new seed source `packages/mission-control-db-contract/seeds/sdlc_report_schemas.py`, generator
  registration, generated bundle `seeds/ai-engineer/mc.app.ai-engineer.artifact-schemas-1.0.0.json`, seeds README row,
  `tests/unit/capability/test_sdlc_report_schema_seeds.py`, `tests/integration/postgres/test_ai_engineer_report_schema_seed.py`,
  `tests/unit/control_plane/test_catalog_seed_bundles.py`.
- Implementer Opus 5.5 (worktree `run2-close-d5`). Review 1 (fresh Opus 5.5): CHANGES REQUIRED — three schema-honesty
  defects (unrun tests with counts, diagnosed without identified cause, observed reproduction without exit codes/evidence)
  and an untracked evidence path; fixed. Review 2 (fresh Opus 5.5): APPROVE WITH NITS; nits recorded, not adopted
  (unknown reproduction may list exit codes; not_reproduced with unrun reproduction; approve verdict with defect finding).
- Disposable proofs on PostgreSQL 17 (`mc-ft-disposable-pg17`, loopback): (a) fresh, (b) upgrade 1.3.0→1.4.2,
  (c) repeat, (d) drift, (e) refusal, (f) role — 3 tests passed (implementer and both reviewers). The engine needed the
  synthetic Supabase Storage schema on plain PostgreSQL for the prior cognition-profiles chain (test-only).
  `test_seeds.py` 4 DB tests **blocked** (fixture drops cluster-wide roles; unsafe on the shared disposable container).
- Committed `bb2388b1`. Seed `mc.app.ai-engineer.artifact-schemas@1.0.0`, digest
  `sha256:ce8b5c9298503fc2793c38e1cae8f9f6ff6963c00359f3ce0bcdbdf0fca598fd`; definitions diagnosis `sha256:83f0def6…6805`,
  patch `sha256:427aa03c…d3a8`, review `sha256:8d9c995c…1371`.
- Live (D5, no owner go required; all conditions held), evidence in `p2/live/`:
  1. Absence: `p2/catalog-check.json` `b7b986ae…`.
  2. Additive new slot: two reviews; no existing seed/release/migration bytes changed.
  3. Disposable proofs: above.
  4. Dry run + backup before apply: `seed-plan-new-before.json` `34ed04cb…` (pending, mutations []),
     `seed-plan-full-before.json` `fac0307a…` (21 replay, 1 pending), `snapshot-before.json` `fbbc7101…`,
     `BACKUP-RESTORE-RECORD.md` `7d447141…` (restore = revoke decision in a successor seed or Supabase PITR; never deletion).
  5. Apply once: `seed-apply.json` `e72ba4ab…` — applied, created 6, applied_by `postgres`, component 1.4.2.
     Readback: `seed-plan-new-after.json` `c07da5f9…` replay/no mutations; `verify-after.json` `e28b2b1e…` verified,
     component 1.4.2, 37 migrations, fingerprint `sha256:1d6dcd1a96b44b7c3635ffd34cec7703703160b04bf52c24643157c72a472cc3`
     (mc-pg-catalog-v2); `snapshot-compare.json` `c47ca426…` identical; runtime-role `catalog-check-after.json` `a2519d48…`:
     4 admitted artifact schemas (S0 + three SDLC), 37 component releases. Biotech untouched.
- Afterwards the applied bundle was added to `FROZEN_BUNDLES` (generator `--check` and 39 tests passed).
- Cost: none (database only).

## P2 / F0 — full configuration compilation, zero native create (complete offline; preflight moves to G1)

- Lease: owned offline process (`p2/f0/f0_compile.py` `8c1eeabf…`), MAIN at `b9588f44`, normal `ManifestCompileService`
  over the committed common + AI Engineer + qualification seed records (the S0 production-compile test catalog; the live
  catalog holds the same applied bundles: 21 replay + the D5 bundle), P1 loader, socket connect (non-loopback) and
  process creation refused in-process.
- Manifest `p2/f0/f1-sdlc-config-source.mission.yml` `eebce7e9…` (authored from the S0 claude_agent_sdk template and
  `codex.stage-graph.mission.yml` `54ca8f2d…`): StageGraph diagnose → patch → independent review → human gate on
  claude_agent_sdk; repository MAIN at P1 commit `c49862bf…`; `plugin.cognition-sdlc@1#sha256:a57f772c…` (TDD,
  code-review, PR, diagnosing-bugs skills; reviewer and test-runner subagents); one `config:sdlc.focused_tests`
  variable; outputs on `schema.sdlc-{diagnosis,patch,review}-report@1`; one goal per stage (a goal spanning several
  stages has no completion evaluator — found and fixed during F0). Installation config `p2/f0/installation-config.json`
  `80174932…`.
- Results (`p2/f0/*.json`): `compile.positive.json` `a38b9966…` ok, 0 blockers, 0 start-gate completion issues;
  `compile.repeat.json` `cd441223…` equal canonical digest `sha256:5028736f5fc26ccb60bec30913cc7eb56635ffa9a9fb1b3c78e78124b862bcd0`;
  `no-secret-echo.json` value absent from report/programs; `no-effects-observer.json` catalog unchanged (in-process
  boundary only); `configuration.inventory.json` `09b31fbb…`.
- Negatives, each on a configuration copy, refused at the intended stage: unknown config key (`config_unresolved`),
  secret-like config key supplied by the source (`config_secret_like`), absent required kit secret
  (`kit_requirement_unmet`), stale kit digest (`kit_unresolved`), wrong plugin bundle digest (`digest_mismatch`),
  unsupported hook event (schema `enum`), required hard pause (`LANE_REQUIREMENT_UNSUPPORTED`), provider-wide
  per-command approval on cursor_local (`LANE_REQUIREMENT_UNSUPPORTED`), PHI on a hosted lane
  (`DATA_CLASS_NOT_ADMITTED`), nonexistent report schema (start gate: `output_schema_validator_unavailable`, the
  repository's documented fresh-start blocker stage).
- `preflight.positive.json`: **unrun offline** — same-manifest preflight needs the installation prerequisite store;
  scheduled for G1 through the normal API.
- Cost: none.

## P4 — LS-07 Cursor CLI cell (blocked by host commit headroom) and D4

- D4 recorded: the stale 10 USD Cursor LS reservation is released on the recorded dashboard evidence (zero usage
  events 2026-10-17/18); the consumed earlier Cursor native attempt stays consumed.
- The prepared "missing-result receipt boundary" (`run2-fresh-session-20261017/cursor-receipt-repair/outer_readback.py`)
  belongs to the retained private probe harness, not to repository source; LS cells now run through the repository's
  own SPEC-08 runner `agentjob.py`, whose status/result files already retain a non-result truthfully. Not integrated.
- Fixture: fresh clone of the retained disposable fixture (`380accb`) at `run2-close-20261018/ls/fixture`.
- Doctor (read-only): `ls/ls07-cursor-doctor.json` `25d744fd…` — cursor-agent `2026.10.01-14929f9`, native Windows,
  auth route `api` (CURSOR_API_KEY from the canonical .env into the runner environment only), read-only `--mode ask`,
  native default model.
- Attempt 1 (`ls07-cursor-readonly-close`, `ls/ls07-cursor-run.log` `7bb512ea…`): stopped by the lead's memory guard
  after 46 s when commit headroom fell to 695 MB (physical 2.2 GB); zero frames in `run.jsonl`; no orphan.
- Attempt 2 (`ls07-cursor-readonly-close2`, `ls/ls07-cursor-run2.log` `67b46b7b…`, one fresh bounded attempt because
  attempt 1 ended by the lead's own abort with no inference): stopped after 31 s at 480 MB commit headroom; zero frames.
- Finding: on this host the Windows cursor-agent CLI commits roughly 3.6 GB within 30 s of start, before emitting any
  frame. **LS-07 Cursor cell: blocked (host commit headroom)**; stdin/read-only questions remain unanswered; cost
  unknown, no inference frame observed. No third attempt. Retained worktrees: `ls/fixture/.worktrees/ls07-cursor-readonly-close{,2}`.

## P3 — G1 ordinary local serving (served; zero inference smoke passed)

- Composition (private `run2-close-20261018/g1/`; no secret written): normal `mission_control.bootstrap.api:create_app`
  (uvicorn, WSL loopback 127.0.0.1:18090) and one normal `mission_control.bootstrap.worker` (role base, plus native lane
  queues), both from MAIN source through a fresh WSL venv `~/.venvs/mc-run2-close` (editable install of MAIN; Python
  3.12.11; claude-agent-sdk 0.2.165 with bundled Claude Code 2.1.294; temporalio 1.34.0; cursor-sdk 1.0.37). Local
  disposable Temporal `mc-run2-s0` (127.0.0.1:17233, 14 search attributes). Private fresh queues `mc-run2-close-*`.
  Database: AI Engineer 1.4.2 through the normal restricted runtime/family/checkpoint logins (DSNs from AWS Secrets
  Manager into the child environment over stdin only; `sslmode=verify-full` with the pinned Supabase CA). Payloads:
  same-host ext4 root (no split-host, no S3). Config derived from the retained previously served ee3 (Claude) and e309
  (Codex) operator configurations: `config/deployment.json` `6bb2cd2d…` (binding digest unchanged
  `sha256:4062fdbc…`), `config/launch-bindings.json` `751abfd2…` (Claude workspace re-measured on this host),
  `config/auth-profiles.json` `a25f450a…` (claude-sdk-api env:ANTHROPIC_API_KEY; codex-api-configured env:OPENAI_API_KEY),
  `config/installation-config.json` `4233d650…`, `config/owner-probes.json` `a49f9698…`. Launchers `serve.py` `941024b8…`,
  `linux_exec.py` `99451749…`.
- Pre-serving observer (`queues-before.json` `3aa14cc3…`): 9 private queues × 2 types, zero pollers; no running
  workflow in the namespace. Serving (`queues-serving.json` `a46872a2…`): 15/18 queue types polled (the three without
  pollers are activity-only queues' workflow side). API `/health/ready`: ready, production_common, component 1.4.2,
  launch_configured true.
- Caller identity: one sign-in of the existing service account `service:run2-s0-launcher` (AWS secret
  `S0_LAUNCHER_AUTH`, normal Supabase issuer and pinned JWKS); token held in a private 0600 file outside the repository.
- Zero-inference smoke: live compile of the F1 manifest (`f1.mission.yml` `6a02db4f…`) through the installed catalog:
  ok, 0 blockers (`f1-compile.json` `5bd2cd9f…`). Preflight: not ready, PREREQUISITES with Claude A8 and M4 expired
  (`f1-preflight.json` `e91af066…`). Submit: new mission/revision/run `ec193a1e-9e4f-574f-992d-a6ad16733ff2`, no start
  (`g1-submit-unmet.json` `9ac9badc…`; one transport-level retry with the same request id; HTTP 200 with
  `unchanged:false` recorded — 201 was expected for a first submission; noted, not investigated). Start: HTTP 422
  `PREREQUISITES_UNMET` with exactly the same two items, before any create (`g1-start-unmet.json` `f0dc2ef2…`).
- Prerequisite re-verification through the normal probe path: host closure measured by the owned attestor
  (`attest_claude_host.py` `c632d123…`: 4707 runtime, 19318 venv, 822 source files; no credential, no inference);
  A8 identity derived with the repository's own binding models (`claude_identity.py` `8e58b867…`) equal to the
  record's `sha256:0934ba02…`; `missionctl prereq verify` A8 (`claude_native_host`) and M4 (`broker_names`) both
  verified (`verify-a8….json` `e026e9e7…`, `verify-m4….json` `15ac1121…`); preflight then ready
  (`f1-preflight-3.json` `5af32675…`).
- Cleanup: API and worker stopped by exact PID with SIGTERM (each within 2 s); `ps` shows none; Temporal keeps listing
  recent pollers for a while (`queues-after-stop-1.json` `99301984…`), which is not used as cleanup proof.
- Cost: none (no provider turn).

## P5 — S0-01 / F1 first start: real launch defect found

- Caller wait (this Claude Code session, `missionctl wait --run ec193a1e…`) resolved the existing inbox
  `01a151d3-55fb-7104-82cf-86b03735ce09`; the first registration used invalid kinds (refused, exit 2; valid kinds are
  review_required, blocked, failed, terminal_result, accepted_output, child_lifecycle, review_closed, progress,
  rate_limited).
- `missions:start` with prerequisites ready answered 409 `start_unavailable`: "the claude_agent_sdk host projection is
  refused: capability selected more than once: subagent.mc-cognition-reviewer@1 and plugin.cognition-sdlc@1 >
  subagent.mc-cognition-reviewer@1" (`s0-01/start.json` `7a4a69d1…`). Nothing was created.
- Root cause: the provider-lane (claude_agent_sdk/codex) node pin collection in
  `application/authoring/manifest_launch_inputs.py` (~1110–1132) does not skip plugin members, unlike the Cursor path
  (~1481) and `_provider_capability_pointers` (~2215); the plugin row re-expands them at render. Lease P5a opened
  (Opus 5.5 implementer, worktree `run2-close-p5a`).
- P5a fixed and committed `ac9d5e7e` (reviewed: approve with nits — nits recorded: an unused type-ignore,
  a hard-coded member index in the new test, Stage Graph / hook / MCP plugin-member cases not covered, comment wording).
  The Claude workspace was re-measured for the new source (package digest `sha256:eb62d6b7…`), A8 re-derived
  (`sha256:ee31af9c…`), re-observed with the true worker build commit `ac9d5e7e…`, and A8/M4 re-verified.

### S0-01 attempts (Claude Code caller = this session; claude_agent_sdk; local Temporal) — not yet a complete cell

| Attempt | Run | What happened (receipts in `g1/s0-01*/`) |
| --- | --- | --- |
| a | `ec193a1e…` | Lane create refused before spawn: binding host secret refs need `MC_S0_OBSERVER_{JWT,URL,APPLICATION_ID}` (read-only observer identity) and the worker lacked them (Secret Broker `SecretUnavailable`). The refusal was classified `create_dispatch_ambiguous` / `in_doubt` although no native process started (finding: conservative pre-create classification). The run awaits a privileged `reconcile_unit` (the launcher grant lacks `workflow_run.reconcile_unit`); a normal cancel was accepted and the run is parked `cancelling` on that in-doubt liability. Retained, not forced. The caller wait ended `invalid_token` when the 1-hour launcher token expired (finding: `missionctl wait` does not refresh tokens). |
| b | `519816f2…` | Wait registered before start (inbox `01a1520d…`), start accepted; native session `fefd189f…` live; real wake `review_required` (provider-permission Human Task for a read-only Bash command) and ack. Approval refused `not_reviewer`: provider-permission reviewers default to `owner` (worker setting `mission_control_approval_reviewers`), which this session cannot authenticate as. `interrupt_and_inject` accepted, consumed, delivered `cancel_and_replace` with native refs; the waiting turn was interrupted and the replacement turn acted on the injected text. Skill exercised: `mc-cognition-diagnosing-bugs` invoked. Forbidden tool: `WebFetch` (binding `disallowed_tools`) absent from the native tool set (`ToolSearch select:WebFetch` → "No matching deferred tools found") — denial by absence, not a typed hook deny. **Clean cancel** (`--urgency immediate`): accepted → cancelling → `completed`/terminal `cancelled` in ≈30 s; native turn `cancelled`; no Claude process remained. |
| c | `12627622…` | Disclosed local configuration: worker `MISSION_CONTROL_APPROVAL_REVIEWERS=["service:run2-s0-launcher"]` so the caller can decide provider-permission tasks (live installation grants unchanged). Wait registered before start (inbox `01a15213…`). Caller approved a read-only inspection command (typed allow) and **denied** a command enumerating environment-variable names (typed deny, resolved, no effect). Inject accepted/consumed. Then the attempt was recorded `failed` (`provider_error`, provider status `cancelled`) at the interrupted turn while the replacement turn 2 ran on to `end_turn`; the run terminalized `failed`; caller woken with `failed`. Diagnosis and fix lease P5b opened (Opus 5.5). |

- Additional finding: the first HTTP call after an idle period twice failed client-side with `service_unavailable`
  before reaching the API (WSL loopback forwarding); idempotent retries with the same request id succeeded.
- Spend: three short Claude sessions on the Anthropic API route (`claude-sonnet-5-5`); usage disposition `unknown` in
  the run projection; reserved 5 USD from the S0 slice / Anthropic local category; actual not attributable yet.
- P5c committed `c7f79b50` (session-lane packets now name lease-relative `outputs/<slot>.json`, `inputs/`, `.mission/` and the
  JSON final-answer contract; review approve with nits — multi-output and Goal Loop output-contract gaps, Cursor Cloud
  wording, two latent path cases recorded).

| Attempt | Run | Outcome and finding |
| --- | --- | --- |
| d | `7d65a750…` | diagnose stage **accepted** (first accepted native output; obligation `diagnosed`); patch stage failed after an undecided approval: the caller loop had been stopped by the Claude Code memory reaper and the native turn was cancelled waiting. |
| e | `43cedc61…` | diagnose accepted; an undecided approval auto-resolved `deny` after exactly 300 s (no `deadline_at` on the task) and the denial cancelled the turn → attempt failed. Finding: a second `review_required` on the same run did not wake a fresh `missionctl wait`. |
| f | `bd2899f4…` | binding pre-allows `Bash` (tool-gating evidence retained from b/c/d/e); network egress approval for `files.pythonhosted.org` denied by the caller (typed network deny). diagnose accepted; patch stage failed: two output candidates. |
| g | `14843fd1…` | the inject text asked for a sentence → prose final answer instead of the JSON contract → outputs invalid (authoring error, corrected). |
| h, i | `1f471a52…`, `8b598f4b…` | diagnose accepted; patch failed again with two candidates although the agent wrote one file. Root cause: `reuse: within_run` reuses the worktree, so the upstream `outputs/diagnosis.json` is collected again at the patch stage and validated against the patch schema. Finding: a reused lease does not start an operation with a clean `outputs/`. |
| j | `831f33f4…` | `reuse: none`; diagnose accepted; patch operation **completed**; then the family `stagegraph.decide_result` activity fails on every retry with "family mutation fingerprint does not match mutation content" (`run_control_repository.py:169`). Lease P5d (Opus 5.5) opened; the run is retained retrying. |

- Approval policy used by the caller (logged per decision in `g1/s0-01*/caller-loop.jsonl`): deny network / publish /
  destructive / credential / dependency-sync commands; approve read-only inspection, git read commands, the repository
  test runner and writes under `outputs/`; everything else to manual review by the lead.
- Spend: 10 short F1 sessions (claude-sonnet-5-5, API route); usage disposition `unknown` per run projection; reserved
  5 USD of the S0 slice remains the planning figure, actual not attributable in-session.

## Stock-take 2026-10-19 16:10 UTC (resume point)

- **Committed on `main`:** P0 `af2d24fc`, P1 `c49862bf`, D5 `bb2388b1` + `b9588f44` (seed applied live), F0/LS-07 record
  `2523c007`, P5a `ac9d5e7e`, P5b `aeeda4a4`, P5c `c7f79b50`.
- **In flight (uncommitted in MAIN working tree):** P5d round-0 checker fix (`run_control_repository.py`, digest-guard
  entry removal) applied under the decide_result retry deadline. The complete reviewed-pending P5d (round 1 adds the
  `StageGraphDecisionMutation.decision_payload` set-restoring validator + round-trip tests) is in worktree
  `run2-close-p5d`, diff `p5d/p5d-implementer.diff`; fresh re-review running. Do not restart the G1 worker on MAIN
  until the full P5d is applied (otherwise run `831f33f4…`'s patch row may fail read-back in ~half of hash seeds).
- **G1:** API and worker stopped by exact PID (2026-10-19 ~16:05 UTC). Local Temporal containers `mc-run2-s0-temporal*`
  still up. Restart with `run2-close-20261018/g1/restart_g1.py <manifest>` (re-measures the host, re-derives and
  re-verifies A8/M4, refreshes tokens, starts API + worker detached). The worker writes lease workspaces under
  MAIN `.workspaces/` (default root; paths exceed Windows MAX_PATH) — clean in P8 or set a Linux workspace root.
- **F1:** run `831f33f4…` (key `f1-config-source-review-j`): diagnose, patch and review stages accepted (obligations
  diagnosed/verified/reviewed, 3 accepted outputs; independent review verdict approve_with_nits); parked at
  `owner_gate` (human REVIEW, reviewer `Pinda`, keep_waiting) — needs the owner's decision. Earlier runs retained:
  `ec193a1e…` parked `cancelling` on an in-doubt unit (needs privileged reconcile_unit); others terminal.
- **Remaining for Gate L:** commit P5d after review; S0-01 completion (gate reviewer = caller service, disclosed) or
  owner review of F1; S0-02..09 (codex lane: Codex prerequisites/attestation; cursor_local and the Cursor caller blocked
  by host commit headroom ≈3.6 GB for cursor-agent); Cloud cells S0-10..18 (Temporal Cloud namespace
  `mission-control-dev.ih0e7`: verify search attributes, API key from AWS secret, re-point deployment/worker); LS-08
  (Codex fix + Cursor review — Cursor blocked as above); F3/F4 rows from the F1 evidence; P7 documentation (S0 cells
  JSON, issue appendix, F5 index, README pointer, docs checks); P8 final checks, wheel rebuild, worktree
  classification (running) and reconciliation, canonical folder onto `main`, completion summary.
- **Open findings (carry forward if not fixed):** pre-create secret refusal classified in_doubt; `missionctl wait`
  does not refresh tokens; second review_required not waking a fresh wait; undecided approval auto-denies at 300 s and
  cancels the turn; reused lease keeps prior `outputs/`; P5b residual timeout window; P5c multi-output and Goal Loop
  output contract gaps; config values not delivered to runtime; first HTTP call after idle fails client-side
  (WSL forwarding); provider-permission reviewers default to `owner`.

## P5 outcome — S0-01 / F1 / F3 / F4 (closed for this session)

- P5d committed `5149bcbb` (two fresh reviews; round 2 approve with nits: hand-written set-field list, tuple tolerance;
  latent same-pattern instance: `programs/service.py:530` admission_rejected payload dumps a frozenset-bearing actor).
- **Run k `554d2b2a-3480-550a-b412-0be7900a1029` (`f1k.mission.yml` `c39b3fd7…`) — COMPLETED.** Caller (this session)
  registered the wait before start (inbox `01a154f2…`), was woken by `review_required` for the human REVIEW gate and by
  `terminal_result` (completed), acknowledged each. Stages diagnose / patch / review accepted with schema-validated
  reports in custody (`schema.sdlc-diagnosis-report@1`, `…patch…`, `…review…`); the independent review stage re-ran
  147 focused tests (exit 0) and returned `approve_with_nits`. The gate reviewer was configured as the caller service
  (`service:run2-s0-launcher`, disclosed — not the human owner); the caller read the review report and approved.
  Obligations accepted: diagnosed, verified, reviewed, owner_review; 4 accepted outputs. Receipts `g1/s0-01k/*`
  (`inspect-final.json` `ebb352db…`, `gate-approve.json` `50615cd2…`, `caller-loop.jsonl` `f5abb29e…`).
- Inject on run k: accepted but remained `queued` (its target stage finished before a boundary consumed it) — finding:
  a queued inject for a finished node is neither applied nor refused. Inject delivered + applied (cancel_and_replace,
  native refs) is evidenced on runs b, c, d and j.
- **F1 (representative SDLC) — passed on run k** with the disclosed caller-reviewer gate; the owner-gated original
  (run j `831f33f4…`) awaits the owner's decision. **F3** (cognition/environment composition) — partly evidenced:
  repository AGENTS.md preserved, plugin cognition delivered and the `mc-cognition-diagnosing-bugs` skill invoked
  (runs b–k), additive mission overlay, disallowed tools absent; negative composition controls (conflicting skill,
  hook removal, overwritten AGENTS) not run. **F4** (controls/restart/accounting) — partly evidenced: inject applied,
  typed approval allow/deny, immediate clean cancel, Temporal retry/redelivery after a worker restart (P5d attempt 50),
  in-doubt create parked for reconciliation; usage/cost disposition `unknown` on every run (no actual figure).
- **S0-01** (Claude Code caller × claude_agent_sdk × local Temporal): wait/wake/ack, completion with accepted outputs,
  clean cancel (run b), typed tool deny/allow (c/d/e/f), skill exercised, custody before cleanup — evidenced across runs;
  the completion run's own inject was not applied and usage is unknown → **not promoted** (recorded as partial).
- G1 stopped (API/worker by exact PID); local Temporal containers stopped (they were stopped before this session).

## P7 — Documentation reconciled in place

- `FINAL-CAPABILITY-S0-18-CELLS.json`: every cell carries `close_out_2026_10_19` (S0-01 partial-not-promoted;
  S0-03/06/07/09 blocked on host commit headroom for cursor-agent; S0-02/04/05/08 and S0-10..18 unrun with named gates);
  `qualified_complete_cells` remains 0.
- `FINAL-CAPABILITY-ISSUE-ACCEPTANCE-APPENDIX.json`: all 21 Gate L issues carry `close_out_2026_10_19` with
  `status_unchanged: true` — no receipt satisfies a full issue's clauses this session. Counts remain
  38 done / 41 implemented-unqualified / 18 blocked / 12 not started / 1 active.
- New `RUN-2-F5-PROOF-INDEX.md`: fixtures F0 passed, F1 passed (run k, disclosed caller-reviewer gate), F3/F4 partial,
  F2 deferred; 85 SPEC clause rows (23 partial, 55 unrun, 4 held, 3 blocked); 21 Gate L issue rows (11 blocked, 6 unrun,
  4 partial). Evidence-assembly agent: Sonnet 5.5.
- **Gate L disposition (D1):** Run 2 closes this session **without meeting Gate L in full**. Met: P1 config source, D5
  report-schema seed release (live), F0, G1 local serving, F1 representative SDLC workflow (run k), four reviewed
  launch-path defect fixes (P5a–P5d). Not met: 17 of 18 S0 cells (Cursor callers/lane blocked by host memory; Codex lane
  prerequisites; Codex caller; Temporal Cloud variants), LS-07 Cursor cell and LS-08 (Cursor), S0-01 promotion (inject on
  the completing run, unknown usage). R, S1, S2, S3 and funding-held S4 carry forward as decided; F2 deferred.
- Packet `README.md` carries a two-line pointer to the summary, ledger and F5 index.

## P8 — Final checks, wheel, reconciliation (complete)

- Commits: overlay `57b91dd8`, owner TODO `2e659579` (wrapped to the line limit; wording kept),
  P7 `eb36f3f6`, hash-seed-independent P5d test `6fcb4f82`, canonical drafts `970de73b` on
  `mo/run2-integration`, ours merge `de792e8b` (tree unchanged).
- Checks (guarded, serial, logs in private `p8/final-checks/`): lock, ruff, format, mypy (822 files),
  ty (exit 0), deptry, architecture 12, conformance 149, manifest schemas, seeds (176), skills all passed.
  Unit first pass 5,174 passed / 38 failed: 2 P5d tests failed under the process hash seed (fixed in
  `6fcb4f82`; `run_control` 177 passed; 12 fixed seeds passed); 6 pre-existing (also fail on baseline
  `1d081297`); 30 environment-only (PowerShell 7 absent for the deploy-script tests; Biotech SDL absent
  outside the BellLabs layout). Integration tests unrun.
- Wheel `mission_control-0.1.0-py3-none-any.whl` SHA256 `c0cd2300abfe4722127274aae4cb5599c493d290b78d108200a1525664d615fc`
  at `6fcb4f82`, not installed.
- Canonical drafts: 65 of 72 identical to `main`; the rest superseded or adopted. Side worktrees retired
  (record `p8/retire-record.json`); only the offline worktree is retained.
- Completion summary: [RUN-2-COMPLETION-SUMMARY-2026-10.md](RUN-2-COMPLETION-SUMMARY-2026-10.md).

## Finish (2026-10-19, per RUN-2-FINISH-INSTRUCTIONS-2026-10-19)

Lead: Claude Code on `claude-opus-5-5`, working in MAIN on `main` (`f71d3d11` at start).
Private receipts are under `run2-close-20261018/w1/` (and later `w2/`…`w5/`); tooling is in
`run2-close-20261018/g1/`. The sprint harness is the only caller (E1).

### W1 — Park and record (complete; MR-01 passed)

- **E9 / MO-70.** The owner-approved operator key is an ES256 P-256 pair, generated locally by
  `g1/operator_key.py`. The private key is `private/operator-es256.pem`: 0600 was requested, and
  NTFS inheritance was removed so only the owner account has access. It was never printed or
  committed. The public JWK (kid `run2-operator-es256-20261019`, thumbprint
  `mDi9LUNF2idZuzT3zjumjtO1IQduF3cjJRcWounwDto`) was appended to G1's **local** pinned
  `config/public-jwks.json`, which now holds 2 keys; the previous file is kept as
  `public-jwks.prev.json`. No Supabase change was made. `g1/mint_token.py` runs
  `missionctl token mint` with these settings:
  - the launcher grant only: subject = the grant whose actor is `service:run2-s0-launcher`;
  - that grant's 9 permissions;
  - ES256, `--expires-in 3600`.

  The helper verified each token against the JWKS before writing it. The first authenticated
  read used a minted token: the G1 preflight and `prereq verify` (A8 and M4 → 0), then
  `run inspect` of run j. Every later W1 call used minted tokens (one is minted per runner
  invocation). `restart_g1.py` now mints the launcher token, and `launcher_token.py` (Supabase)
  signs in only the observer identity. **MO-70 clause met by receipt.**
- **G1 restart at `f71d3d11`.** The first attempt was aborted by the guard at 595 MB available:
  the attestor's file hashing inflated the WSL page cache. The private attestor now releases
  the cache for each file with `posix_fadvise(DONTNEED)`; the hashes are unchanged. The rerun
  passed (199 s, minimum 778 MB available). Results:
  - package digest `sha256:a47bcf13…`, A8 `claude_agent_sdk.owner.a8.ca77021f0084e6ebdcaa95da`;
  - identity `sha256:f55e1ca6…` matches the preflight `why`;
  - A8 and M4 verified; preflight ready. Local Temporal containers `mc-run2-s0-temporal{,-postgres}-1` were started for this work.
- **Host resources.** The owner said only this Claude Code session is needed and authorized the
  cleanup. Four other idle Claude Code process trees were stopped, raising available memory
  from 0.69 GB to 1.9 GB and commit headroom from 2.5 GB to 7.4 GB. Cursor was not touched.
- **E4.**
  - Run j `831f33f4…`: normal cancel accepted (request `b0bd0919-fff9-4c29-86d3-ea890b9d234e`,
    v22 `cancelling`). It is now terminal, lifecycle `completed`, outcome **`cancelled`** (v24;
    `w1/runj-inspect-after.json` sha256 `f815e7f9…`). It was superseded by run k.
  - Run `ec193a1e…`: still parked **`cancelling`** (v7, `w1/ec193a1e-inspect.json`
    `8fb2b5ea…`), recorded for the consolidation recovery program.
- **MR-01 assembly from runs k and b.** Clauses 1–3 and 5 were evidenced. Run k's transcript,
  fetched now, shows `claude-sonnet-5-5` in its native `session_init`, the
  `mc-cognition-diagnosing-bugs` Skill and Bash use. Run k's three leases were `lane.cleanup`
  `removed`. The stored frames, receipts and logs gave 0 sentinel hits.

  Not shown: a transcript peek *during* run k, and any child-environment receipt. Run b also
  has no process-absence receipt. The transcript and frame bodies are 2 KB excerpts, so the
  advertised tool list cannot be read through Mission Control. One fresh run was therefore
  done, plus a cancel variant.
- **Fresh MR-01.** Manifest `g1/mr-claude.mission.yml` is f1k with these changes:
  - a new key, `mr-01-claude-l`;
  - test files named in the instruction, because config values are not delivered to the
    runtime;
  - one `ToolSearch select:WebFetch` probe that is kept out of the report.

  Run `e7d24a4b-2e5f-557b-8aa9-b941fce57441`:
  1. Compile ok with 0 blockers (`compile.json` `ccdc68ee…`). Preflight ready (`4e615b44…`).
  2. Native session model `claude-sonnet-5-5`. The Skill `mc-cognition-diagnosing-bugs` was
     invoked. Bash, Read and Write were used. `ToolSearch select:WebFetch` →
     "No matching deferred tools found", and WebFetch/WebSearch were never used. The
     `.mission/context.md` mission packet was read in each stage. The fixture's `AGENTS.md` is
     tracked and unchanged, with fixture status clean. Three reports were accepted against the
     SDLC schemas.
  3. diagnose → patch → review were accepted. Obligations diagnosed, verified, reviewed and
     owner_review are met, with 4 accepted outputs. Terminal **`completed`**
     (`inspect-final.json` `98f44545…`). The gate reviewer is the harness service (disclosed),
     which read the `approve_with_nits` review report first.
  4. The wait was registered before start (inbox `01a15667-13be…`). The harness was woken by
     `review_required` and then `terminal_result`, with acknowledgement. Five peeks were taken
     (inspect + transcript), three of them while the run was active.
  5. Cancel run `cc6d5594-33b5-5953-a219-bafa86705b82`: `--urgency immediate` was sent once the
     native child was seen. Terminal **`cancelled`** within 46 s, and **0** native processes
     afterwards.
  6. `lane.cleanup` `removed` ×3. Sentinel search: 13 sentinels, 51 files (both runs and the
     API/worker logs), **0 hits**. Child-environment names (values never read):
     - inherited names, and the admitted `ANTHROPIC_API_KEY`;
     - the broker-delivered `MISSION_CONTROL_{TOKEN,URL,APPLICATION_ID}` (binding `secret_refs`,
       the read-only observer identity);
     - `CLAUDE_CONFIG_DIR`, and the SDK-set `CLAUDE_AGENT_SDK_VERSION`,
       `CLAUDE_CODE_ENTRYPOINT` and `CLAUDE_CODE_SDK_READS_SESSION_STATE`.

     No DSN, Temporal, AWS or other provider key appears.

  **MR-01 passed** (`w1/MR-01-receipt.json` sha256 `23390b9a…`).
- Observations (not fixed, E6/E7):
  - The cancelled run's lease `claude/79/81edfb…` is retained, with no `lane.cleanup` on the
    cancel path (as in run b).
  - The accepted diagnosis report has disposition `unknown`.
  - Usage projection is `unknown` (E8). The native result frames report 0.41 USD for run
    `e7d24a4b` (list basis). The cancel run reported no result frame.
- Spend W1: about 0.45 USD Anthropic API (native-reported 0.41 plus a short cancelled
  session). Cap 10 USD.

### W2 — Codex lane MR-02 (complete; MR-02 passed)

- **Tooling**, all private under `g1/`:
  - `serve.py` now gives the API `OPENAI_API_KEY`, which the M4 `broker_names` check needs.
  - `restart_g1.py` was generalized. It takes one manifest per lane, measures each lane's host
    closure into its binding workspace, selects prerequisites by lane from each preflight (a8/m4
    and x4/x6/m4), merges every binding into one `owner-probes.json`, and verifies all of them.
  - `policy.py` holds the caller policy as an importable module for the runner. For Codex:
    - `commandExecution`: the command (`bash -lc` unwrapped) goes through the same classifier,
      and any `networkApprovalContext` is denied;
    - `fileChange`: approved only for a `grantRoot` under a lease root, otherwise denied;
    - `permissions`: denied when it asks for network, otherwise manual review.
  - `reverify.py` re-verifies items whose standing is not current (M4 lapses after 1 h).
  - `mr_run.py` is the resumable MR driver (each slice under 10 min). It takes a peek and a
    child-environment name capture on every poll.
- **X4/X6 host proof.** `g1/attest_codex_host.py` uses the repository's own
  `SubprocessAppServerLauncher` and protocol models, with an isolated temporary `CODEX_HOME` and
  `cli_auth_credentials_store="ephemeral"`. The key arrives over stdin only. Results:
  - `codex-cli 0.162.1` on the exact nvm path, CLI sha256 `61b0194f…`;
  - `account/login/start` and `account/read` both return `apiKey`;
  - `model/list` includes `gpt-6-luna`;
  - no `auth.json`, no thread, no turn. This was a metadata-only OpenAI call.

  Observation `mc-close-attest/codex/native-codex-observation.json`: `sha256:3971adff…`,
  identity `sha256:917ebf63…`, which equals the preflight `why`. The Codex workspace was
  measured on this host (package `sha256:3336a6f4…`). Verified in one restart: A8 and M4
  (Claude), and **M4, X4 and X6 (Codex)**. Both preflights were ready.
- **Manifest** `g1/mr-codex.mission.yml`, derived from the MR-01 manifest:
  - lane `codex`, auth `codex-api-configured` (E10), model profile `codex.default` →
    `gpt-6-luna`;
  - the same `plugin.cognition-sdlc` pin and `reuse: none`, Codex `workspace-write` /
    `on-request` from the binding;
  - mission network `none`, tokens 3,000,000;
  - each stage says "work alone, no sub-agents; keep command output short".

  It compiled with 0 blockers on every version.
- **Attempts**:
  - **l** `05ab6f57…`: **failed**. Diagnose was accepted. The patch admission was rejected with
    `budget_hard_cap_exceeded` (`record_admission_rejection`), because diagnose alone used
    675,746 tokens (585,722 cached) against the f1k 400k budget. Claude runs never meet the cap
    because their usage projects as `unknown`; Codex settles usage per turn, so the cap
    applies. This was an authoring correction, not a defect.
    **Finding:** with the binding's allowlist network, the Codex `workspace-write` projection
    turns `network_access` on and marks it `advisory` (`application/environments/network.py`).
    `curl https://example.com` succeeded with no approval. Allowlisted egress is not enforced
    on this lane (by design, recorded), so for an enforced refusal the mission must declare
    `network: none`.
  - **m** `eaa586c3…`: diagnose and patch were accepted. The review stage spawned 2 Codex
    sub-agent threads, whose usage frames carry no `codex_usage_provenance`. The unit settled
    **`in_doubt`** (`codex_usage_requires_reconciliation`, `lane_turns.py:2864`, by design:
    root-thread usage cannot attest a child thread). `reconciliation_incident_id` is null and
    the launcher grant lacks `workflow_run.reconcile_unit`, so the run is **left parked**
    (`active`/in_doubt) for the consolidation recovery and usage work, like `ec193a1e`.
  - **n** `a901422d-a65b-5d51-8b08-3827993a683e`: **completed**. The owner approved this
    rerun; the owner pre-approved the lead's decisions for the rest of the finish.
- **MR-02 clauses** (run n; cancel run `235fcc73-70ee-509a-8fe6-fe99dee936da`):
  1. Compile ok with 0 blockers (`582740…`). Preflight ready with M4, X4 and X6 (`95b760…`).
  2. The model `gpt-6-luna` was reported in native frames and in each stage's closing facts.
     The agent read the `mc-cognition-diagnosing-bugs`, `tdd` and `code-review` `SKILL.md`
     files. It used shell `commandExecution` in the sandbox. Network was refused: with
     `network_access=false`, `curl` exited 6 "Could not resolve host". The mission developer
     instruction was delivered, and the fixture's `AGENTS.md` is unchanged. Three schema-valid
     reports were accepted.
  3. diagnose → patch → review were accepted, plus `owner_review`, with 4 accepted outputs.
     Terminal **`completed`** (`inspect-final.json` `c71cb392…`). The harness reviewer read the
     `approve` review report.
  4. The wait was registered before start (inbox `01a156af-8a96…`). The harness was woken by
     `review_required` and then `terminal_result`, with acknowledgement. 14 peeks were taken,
     13 of them while the run was active.
  5. Immediate cancel → terminal **`cancelled`** in about 2 min (Codex interrupt waits for
     `turn/completed`). 0 native processes afterwards.
  6. `lane.cleanup` `removed` ×3. Sentinel search: 13 sentinels over 159 files (all W2 runs,
     logs, the attestor output), **0 hits**.
     - App-server child environment: `OPENAI_API_KEY` (admitted), `CODEX_HOME`, the npm
       wrapper's `CODEX_MANAGED_*`, and the broker-delivered `MISSION_CONTROL_*`.
     - Tool-shell allowlist `shell_environment_policy.include_only` = HOME, LANG, LOGNAME,
       MISSION_CONTROL_{APPLICATION_ID,TOKEN,URL}, PATH, SHELL, TERM, USER. No provider key.

  **MR-02 passed** (`w2/MR-02-receipt.json` sha256 `966dba2d…`). **MO-71 (Codex manifest
  compiles with 0 blockers) met.**
- Observations:
  - Two Codex worktrees are retained (the parked in-doubt unit of m and the cancelled unit).
  - No Codex hook-trust evidence was examined (MO-03 moved, E-table).
  - A preflight that is not ready makes `mr_run.py` stop before submit, as intended. M4 lapsed
    once and was re-verified (`w2/reverify-1.json`).
- **Spend W2.** OpenAI API, `gpt-6-luna`, over attempts l, m and n and the cancel run:
  - uncached input 563,056 tokens;
  - cached input 5,880,836 tokens;
  - output 79,654 tokens.

  The provider reported no cost in-session (`cost_micros_usd` null). The estimate is
  **2–8 USD**, depending on the model's rate, against a 10 USD cap.

### W3 — Cursor lane MR-03, one attempt (E2): blocked by a lane observation defect, not by memory

- **Memory gate** (`w3/memory-gate-1.json`): Windows 2,996 MB free physical, 6,129 MB commit
  headroom; WSL 3,878 MB available (VM capped at 6 GB, `autoMemoryReclaim=gradual`). Only the
  two local Temporal containers were running. The WSL page cache was dropped.
- **Configuration** (private `g1/config`; earlier files kept as `*.pre-cursor.json`):
  - new `providers.cursor_local` binding:
    - queue `mc-run2-close-lane-cursor`, model `cursor.default` → `default` (Cursor Auto, R22);
    - auth `cursor-local-key` (API), repository `/home/overton/mc-fixtures/mc-close-f1` at
      base ref `c49862bf…`;
    - `REQUIRED_CURSOR_PINS`, published `agent-profile.local-cursor-auto` rev 1
      (`sha256:8e116c69…`);
    - hook callback `127.0.0.1:47561`, `disallowed_tools` [webSearch, webFetch], lease root
      `~/mc-leases/cursor`.
  - new auth profile `cursor-local-key` (`env:CURSOR_API_KEY`, `api_key`, `api`).
  - `CURSOR_API_KEY` goes to both API and worker, the Cursor lane queue is served, and
    `CURSOR_LEASE_ROOT` is set.
- **C9 host proof** by `g1/attest_cursor_host.py`, with zero provider calls and no session:
  - identity derived with the repository's own `BoundCursorPrerequisiteIdentity`;
  - bridge runtime `cursor_sdk/_vendor/bridge/bin/node` reports `v24.5.0`; archive 1.0.0 with
    `@cursor/sdk` 1.0.37 and protocol `sdk.v1`; SDK, bridge and loader closure digests
    recorded;
  - cleanup fixture: `git worktree add --detach` of the fixture under the lease root, snapshot,
    `git worktree remove`, root unchanged. This is attestor-owned git, not the production
    allocator.

  Observation `mc-close-attest/cursor/native-cursor-observation.json` `sha256:b83c0d5d…`,
  selected identity `sha256:68db372b…`, which equals the preflight `why`. **C9 and M4
  verified** through `prereq verify` (C9 includes the live-filesystem cleanup checks).
  Preflight ready.
- **Manifest** `g1/mr-cursor.mission.yml` (f1k/MR-01 shape: lane `cursor_local`, auth
  `cursor-local-key`, a web-fetch probe, "work alone"): compile ok, **0 blockers**
  (`sha256:a13b30d5…`). **MO-71 met for all three MR manifests.**
- **The single attempt**, run `7132d2de-88f2-5c20-9b57-58a183dd6424`, under a WSL memory watch
  (`g1/mem_watch.py`, floor 500 MB, owned-bridge-only stop):
  1. Compile and preflight were ready. The wait was registered before start (inbox
     `01a156dc-d1bb…`), and start was accepted. The Cursor bridge started, and its environment
     holds no credential (the key goes in agent options) and no forbidden names.
  2. Six seconds into the first `lane.turn`, the SDK's `observe_run` raised a configuration or
     bad-request error. The adapter maps it to `ProviderConfigurationRejected` without
     provider text. The activity failed with `lane_turn_rejected: Cursor SDK configuration
     rejected`, and the diagnose operation workflow **FAILED**.
  3. The native agent nevertheless ran on unobserved, to `stop: completed` and
     `sessionEnd: completed`, writing `outputs/diagnosis.json` (hook frames only reached
     Mission Control).
  4. The family's `stagegraph.decide_result` then retried at least 33 times on "operation usage
     reservation is not authoritatively settled".
  5. A normal cancel was accepted. The run is **parked `cancelling`** on that unsettled
     reservation and is recorded for consolidation recovery, like `ec193a1e`.
  6. The owned bridge and watch were stopped by exact PID afterwards. Sentinel search: 59 files,
     **0 hits**.
- **Measurements** (`w3/mr03-memwatch.jsonl`, 698 samples over 23 min): bridge peak RSS
  **199 MB**, minimum WSL available **3,344 MB**, worker peak 439 MB, Windows guard minimum
  2,418 MB. The host held the bridge easily. The 3.6 GB figure was the Windows `cursor-agent`
  CLI, and memory is **not** the Cursor blocker on this host.
- **MR-03: blocked.** The blocker is a lane defect: `observe_run` is rejected by the SDK while
  the native run proceeds. The SDK error class and text are not retained, because the adapter
  copies no provider text; the bridge stderr shows only readiness. E2 allows one attempt, so it
  was not retried and is not fixed here (root cause unknown, not small and local). **It moves to
  the Cursor provider sprint**, together with the unsettled-reservation liability it leaves.
  **MR-13 is not run** (needs MR-03).

### W4 — Temporal Cloud MR-11 and MR-12 (complete; both passed). MR-13 not run (MR-03 blocked)

- **Search attributes.** `scripts/temporal_cloud/configure_search_attributes --plan` was run
  read-only through Cloud Ops, with the key from AWS `mission-control/ai-engineer/TEMPORAL_CLOUD_API_KEY`
  in the child environment only (`g1/cloud_exec.py`). Result: namespace
  `mission-control-dev.ih0e7`, `aws-us-east-1`, active, resource version `7bb2e41e…`, spec
  sha256 `97a31d68…`, **additions `{}`**: all 14 attributes are present (`w4/search-attributes-plan.json`).
  `register_belllabs_search_attributes.py` was not used.
- **Re-point**, all changed together. The local copies are kept as `config/*.local.json`, and
  removing `temporal-active.json` returns to local.
  - `deployment.json` Temporal block: address `us-east-1.aws.api.temporal.io:7233`, namespace
    `mission-control-dev.ih0e7`, fresh private queues `mc-run2-finish-cloud-coordinator-family-{stagegraph,goal-directed}`;
  - binding `task_queue`s `mc-run2-finish-cloud-lane-{claude,codex,cursor}`;
  - `serve.py` reads `config/temporal-active.json` (target `cloud`) and gives
    `TEMPORAL_CLOUD_API_KEY` to API and worker.

  Startup verified the attributes through Cloud Ops. A8/M4 (Claude) and M4/X4/X6 (Codex) were
  re-verified, and both Cloud preflights were ready.
- **Tooling note**, not a defect of the cell. On Cloud, `missions:preflight` takes more than
  the CLI's fixed 30 s client timeout (`interfaces/cli/main.py:1027`, `min(30, …)`): the API
  logs 200 after `missionctl` has reported `service_unavailable`. The runner now calls the same
  `missions:{preflight,submit,start}` routes with the CLI's bodies and a 240 s timeout. The
  CLI's 30 s cap is recorded for the consolidation tooling.
- **MR-11** (claude_agent_sdk on Cloud), run `37ce4f20-ca35-54e9-9cf5-f16040cf5df7`, manifest
  `g1/mr-claude-cloud.mission.yml` (MR-01's, key `mr-11-claude-cloud`):
  - compile ok with 0 blockers; preflight 200 ready; submit 201; the wait registered before
    start 202;
  - Skills `mc-cognition-diagnosing-bugs` and `mc-cognition-tdd`; `ToolSearch select:WebFetch`
    → "No matching deferred tools found"; Bash, Read and Write used;
  - obligations diagnosed, verified, reviewed and owner_review, 4 outputs, terminal
    **`completed`** (`inspect-final.json` `47647e39…`);
  - woken by `review_required` and `terminal_result`; 5 peeks; harness reviewer approved
    `approve_with_nits`;
  - `lane.cleanup` `removed` ×3, read from the **Cloud namespace** history;
  - native-reported cost 0.41 USD.

  **MR-11 passed** (`w4/MR-11-receipt.json` `01cd0ccf…`).
- **MR-12** (codex on Cloud), run `60cca228-bcd7-5cbe-8013-ba30e892c927`, manifest
  `g1/mr-codex-cloud.mission.yml` (MR-02's, key `mr-12-codex-cloud`):
  - preflight ready after an M4 re-verify; compile, submit, wait-before-start and start as
    above;
  - `gpt-6-luna` in every stage's closing facts (Cloud history); the plugin `SKILL.md` files
    were read; curl refused with exit 6 (network none);
  - diagnose, patch and review accepted. The independent review verdict was
    **`changes_required`**, so the runner stopped the gate for manual review. The lead, as the
    disclosed harness reviewer, read the findings and **accepted the reports as evidence, not
    the code**:
    - Linux `mypy` flags three Windows-only modules. This is environment-specific; the P8
      Windows `mypy` passed.
    - The operator guide lacks `MISSION_CONTROL_INSTALLATION_CONFIG_PATH`. That is a real gap,
      fixed in the W6 documentation pass under MO-07.
  - terminal **`completed`** (`inspect-final.json` `35902af7…`); `lane.cleanup` `removed` ×3
    on Cloud.

  **MR-12 passed** (`w4/MR-12-receipt.json` `0b41bf14…`).
- Sentinel search over W4 receipts and logs (13 sentinels, including the Cloud key): 113 files,
  **0 hits**. No cancel variant on Cloud (not required).
- **Spend W4.** Anthropic 0.41 USD (native-reported). OpenAI `gpt-6-luna`: 215,923 uncached
  input, 2,426,911 cached input, 35,102 output tokens, an estimate of 0.8–3 USD. Temporal Cloud
  actions are negligible. Total within the 10 USD Cloud cap.
- **MO-67 Temporal Cloud qualification (reframed, E3): met for the lanes that passed locally**
  (MR-11, MR-12). MR-13 is not applicable, because MR-03 is blocked.

### W5 — LS-08 substitute demo (E5): complete

- **Router and jobs.** `.agents/skills/coding-cli-jobs` (router; the provider caveats come from
  `codex-exec` and `claude-code-headless`) with the runner `scripts/agentjob.py`. Both jobs run
  on the retained disposable fixture `run2-close-20261018/ls/fixture` (`380accb`), with fresh
  ids. Both use the API-key route under E10; no ChatGPT or subscription login.
  - `ls/ls08-codex-fix-finish.yaml`: `cli codex`, `permissions edit`, verify
    `python -m unittest test_arithmetic`;
  - `ls/ls08-claude-review-finish.yaml`: `cli claude`, `permissions read-only`, verify
    `python verify_readonly.py`, `max_usd 1.0`.

  Credential names are loaded from CANON `.env` into the runner's child only, by the private
  `ls/run_agentjob.py`.
- **Doctor**, read-only (`w5/doctor-{codex,claude}.json`): `codex-cli 0.162.1` (native
  `codex.exe`, API) and Claude Code `2.1.304` (native, API), both on the native default model.
- **Launch.** From this Claude Code session, in a Bash call with `run_in_background: true`,
  through the memory guard: `agentjob.py run ls08-codex-fix-finish.yaml ls08-claude-review-finish.yaml
  --max-parallel 2 --allow-live`. It started at 02:27:12Z and ended at 02:27:35Z (23 s, both
  in parallel). **The session was woken by the background-task completion notification** and
  then read both result files.
- **Codex fix**, `.tmp/agent-jobs/ls08-codex-fix-finish/result.json` (sha256 `933d8517…`):
  - status **`done`**; runner verify `python -m unittest test_arithmetic` exit **0**;
  - 137,522 tokens, cost unknown;
  - the retained worktree `.worktrees/ls08-codex-fix-finish` (branch
    `agentjob/ls08-codex-fix-finish`) holds exactly `-    return a - b` → `+    return a + b`
    in `arithmetic.py`, checked independently. The tests were unchanged.
- **Claude review**, `.tmp/agent-jobs/ls08-claude-review-finish/result.json` (sha256 `399267c0…`):
  - the report is `done`; it quotes `PROBE_MARKER = "LS07-2144-70c5b4b7"` and names the real
    defect (`arithmetic.py:4` returns `a - b`);
  - model `claude-opus-5-5` (native default), 0.139 USD.

  Runner status is **`budget_exhausted`**, because verify `python verify_readonly.py` exited 1.
  Independent check: this checkout has `core.autocrlf=true`, so the worktree's `arithmetic.py`
  is CRLF, while `verify_readonly.py` pins the LF content hash. The check cannot pass on this
  checkout whatever the agent does. The review edited nothing: `keep: on_change` found its
  worktree clean and removed it with its branch. This is a **fixture defect, recorded** (pin
  `.gitattributes eol=lf` or hash normalized content), not an agent violation.
- Sentinel search over both job directories and the W5 receipts: 19 files, **0 hits**. Raw
  `run.jsonl` was not read into the caller context; only the model fields were grepped.
- **LS-08 (substitute, E5): met.** The router launched two background jobs, a Codex fix and a
  Claude review, from a Claude Code session; the session was woken on completion and read both
  result files. The review's verify failure is disclosed above. **LS-05: met by receipt.** The
  router and the per-CLI adapters (codex and claude) are what ran.
- **LS-07 split (E5).** The Claude and Codex items are answered by these receipts plus the
  doctor outputs: native binary and version, API auth route, read-only versus edit, verify
  ownership and clean-worktree removal. The Cursor CLI items move to the Cursor provider sprint.
- Spend W5: Anthropic 0.139 USD (provider-reported); OpenAI 137,522 tokens (cost unknown,
  small). Cap 5 USD.

### W6 — Close-out (records, checks, wheel; reconciliation follows the commit)

- **Records**, receipt-only:
  - `FINAL-CAPABILITY-S0-18-CELLS.json`: a `finish_2026_10` block holds the MR matrix with run
    ids and private receipt digests. The 18 original cells are kept and each is marked
    `superseded_by_owner_decision: E1`.
  - `FINAL-CAPABILITY-ISSUE-ACCEPTANCE-APPENDIX.json`: `finish_2026_10` on all 21 Gate L issues.
    8 are closed by receipt and changed to `fully done`: LS-05, LS-08, MO-08, MO-67, MO-68,
    MO-70, MO-71, MO-72. LS-07 is split, MO-07 is recorded with its exact remaining clauses, and
    11 are moved by E-decision. Counts, recounted from the records: before 37 done / 42
    implemented-unqualified / 18 blocked / 12 not started / 1 active; after 45 / 38 / 14 / 12 / 1.
    The stored before-counts (38 / 41) were off by one, which is recorded. `issues.json` was not
    edited.
  - New `runs/RUN-2-FINISH-DISPOSITION-2026-10.md`. `RUN-2-F5-PROOF-INDEX.md` gained a Finish
    section.
  - MO-07/MO-08 documentation: a new `docs/WSL2_WORKER_RUNBOOK.md`; the operator guide now
    documents `MISSION_CONTROL_INSTALLATION_CONFIG_PATH`; docs README entry; the AGENTS.md docs
    index was regenerated.
- **Checks**, guarded and serial, logs in private `w6/final-checks/`. Source is unchanged since
  `6fcb4f82`; the finish changed no source.
  - lock passed;
  - `ruff check` passed; `ruff format --check` passed (1889 files);
  - `deptry src` passed;
  - `mypy` passed (822 files); `ty check` passed (exit 0, 11 non-blocking diagnostics);
  - architecture 12 passed; conformance 149 passed;
  - manifest schemas, seeds (176) and skills passed;
  - docs index current; links 448 files with 0 broken; OKF valid (45).
  - unit tests, per directory (44 directories): **5,176 passed, 36 failed**, 31 skipped,
    2 xfailed. The failing set is identical, test by test, to P8's:
    - 6 pre-existing: 2 `control_plane` digest-guard tests and 4 `harness`
      `test_closing_facts_map_every_run_result_status`;
    - 30 environment-only: 22 `runtime` deploy-script tests need PowerShell 7, and 8 `schema`
      tests need the Biotech SDL.
  - Integration tests unrun (compose services), as in P8.
- **Wheel**, rebuilt and not installed: `mission_control-0.1.0-py3-none-any.whl`, sha256
  `c0cd2300abfe4722127274aae4cb5599c493d290b78d108200a1525664d615fc`, 2,754,836 bytes. It is
  byte-identical to the P8 wheel. Private `w6/wheel/`.
- **Processes.** G1 API (pid 70580) and worker (pid 70626) were stopped by exact command match,
  each within 2 s. No native Claude, Codex or Cursor process or watch remains. G1 config was
  restored to local (`config/*.cloud.json` and `temporal-cloud.json` hold the Cloud set). The
  local Temporal containers `mc-run2-s0-temporal{,-postgres}-1` were stopped (started by W1;
  data retained). Docker Desktop was already running before this work and is left running.
- **Spend, finish total** (caps: 10 USD per lane slice, 10 Cloud, 5 LS):
  - Anthropic about 1.0 USD (native-reported: 0.41 MR-01, 0.41 MR-11, 0.14 LS-08, plus one
    short cancelled session unreported);
  - OpenAI `gpt-6-luna`: 779k uncached input, 8.31M cached input and 115k output tokens over
    MR-02 (three attempts plus cancel) and MR-12, plus the LS-08 Codex job (137,522 tokens).
    No cost is reported in-session; the estimate is **3–11 USD** depending on the rate. The X4
    metadata calls made no inference.
  - Cursor: one MR-03 attempt (diagnose ran unobserved), usage unknown;
  - Temporal Cloud: negligible.
- **Reconciliation** (section 7.4), after commit `152a3dcb`:
  - MAIN was clean, including untracked files and the consolidation draft.
  - G1 and the native processes were stopped.
  - The MAIN `.venv` junction was unlinked (canonical `.venv` intact), and `git worktree remove`
    of MAIN ran without `--force`.
  - The canonical folder `git checkout main`, then `git branch -d mo/run2-integration` (was
    `970de73b`).

  Verified: worktrees are canonical `main` plus the retained offline worktree; `--no-merged
  main` is empty; status clean; `git fsck --no-dangling` passes. **Run 2 is finished.**
  The canonical folder is the live `main` checkout. The G1 WSL venv was an editable install of
  MAIN; reinstall it from the canonical checkout before serving again.
