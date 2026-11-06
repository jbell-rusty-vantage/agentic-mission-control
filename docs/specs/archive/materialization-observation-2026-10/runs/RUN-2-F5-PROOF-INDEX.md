---
type: Proof Index
title: "Run 2 F5 proof index (close-out 2026-10-19)"
description: "Per-fixture proof index joining each SPEC acceptance clause and each Gate L issue to one evidence source and a status, from the in-place close-out ledger only."
---

# Run 2 F5 proof index

Prepared by Claude Code on Sonnet 5.5 (evidence assembly; the lead is `claude-opus-5-5`). Authority: [close-out status ledger](RUN-2-CLOSE-STATUS.md); clause source: [handoff checklists](RUN-2-FUNDAMENTAL-CAPABILITIES-HANDOFF-2026-10-18.md); issues: [Gate L disposition](RUN-2-GATE-L-DISPOSITION-2026-10-18.md); cells: [S0 cells](FINAL-CAPABILITY-S0-18-CELLS.json); issue records: [appendix](FINAL-CAPABILITY-ISSUE-ACCEPTANCE-APPENDIX.json). Private receipts are under `C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-close-20261018/` (outside the repository). Statuses: passed, partial, failed, blocked, held, deferred, unrun. Nothing is promoted from a diagnostic, an API GET, a provider done or a partial run; "partial" means evidenced in part, not accepted. Evidence names a ledger section (P0 to P5, Stock-take) and, where useful, a private receipt.

## Fixtures and S0

| Row | Evidence source | Status |
| --- | --- | --- |
| F0 configuration compile, zero native create | P2/F0: `p2/f0/compile.positive.json`, `compile.repeat.json` (equal digest), ten negatives refused at the intended stage, `no-effects-observer.json`; P3 live compile `f1-compile.json` ok; same-manifest preflight unrun offline, ready at G1 (`f1-preflight-3.json`) | passed (offline + live compile) |
| F1 real SDLC StageGraph, independent review | P5 outcome: run k `554d2b2a`, `g1/s0-01k/inspect-final.json`, `gate-approve.json`; review approve_with_nits; gate reviewer was the caller service (disclosed, not the human owner); owner-gated run j `831f33f4` awaits owner | passed (run k, disclosed caller-reviewer gate) |
| F2 knowledge research and ingestion chain | D6 owner deferral 2026-10-18 | deferred |
| F3 cognition/environment composition | P5 outcome: AGENTS.md preserved, plugin delivered, skill invoked, additive overlay, disallowed tools absent; negative composition controls not run | partial |
| F4 controls, restart, accounting | P5 outcome: inject applied, typed allow/deny, clean cancel, retry after worker restart (P5d attempt 50), in-doubt create parked; usage/cost unknown on every run | partial |
| S0-01 Claude Code x claude_agent_sdk x local | P5 table runs a-j and run k; not promoted (run k inject never applied, usage unknown, disclosed caller-reviewer gate) | partial |
| S0-02, S0-05, S0-08 (codex lane) | Stock-take: Codex prerequisites/attestation not prepared; WSL login absent, API route unproven | unrun |
| S0-04 Codex caller x claude_agent_sdk | not attempted this session | unrun |
| S0-03, S0-06, S0-07, S0-09 (cursor_local lane or Cursor caller) | P4: cursor-agent commits about 3.6 GB; two attempts aborted by memory guard | blocked |
| S0-10..S0-18 (Temporal Cloud) | Stock-take: `mission-control-dev.ih0e7` not re-pointed | unrun |
| S0 qualified complete cells | `qualified_complete_cells` = 0 | unrun |

## SPEC acceptance clauses (Line = source line in the SPEC file)

### SPEC-01 EnvironmentKit

| Line | Clause | Evidence source | Status |
| --- | --- | --- | --- |
| 230 | One manifest with `kit`, `variables`, `secrets`, `network` and `git` compiles for all six profiles. It yiel... | P2/F0: compile.positive.json ok for claude_agent_sdk only; other profiles not compiled | partial |
| 232 | A missing required secret fails preflight. | P2/F0 negative kit_requirement_unmet; P3 preflight not ready on expired A8/M4 | partial |
| 233 | The child env contains exactly the allowlist. | No receipt in ledger | unrun |
| 234 | A pre-push to a non-`mc/` ref is rejected. | No receipt in ledger | unrun |
| 235 | A receipt with `prepared` is produced. | No receipt in ledger | unrun |
| 237 | A drill creates `mc-<kit>-<digest>` and syncs secret names. | No receipt in ledger | unrun |
| 238 | The launched agent produces a `prepared` receipt signal. | No receipt in ledger | unrun |
| 239 | A second mission with the same kit reuses the environment without an update. | No receipt in ledger | unrun |
| 240 | **No secret value** appears in any committed file, frame, log or binding. A test injects a sentinel secret ... | P2/F0 no-secret-echo.json; no live-run sentinel grep recorded | partial |

### SPEC-02 Cognition

| Line | Clause | Evidence source | Status |
| --- | --- | --- | --- |
| 157 | One manifest selecting a skill, a subagent, a catalog hook, an MCP server and a plugin renders golden fixtu... | P2/F0: one lane (claude_agent_sdk) compiled; no six-profile golden fixtures | partial |
| 159 | Launch succeeds on all three local lanes. | P5: launched on claude_agent_sdk only; codex and cursor_local not run | partial |
| 160 | The repo files are byte-identical afterwards. | P5 outcome F3: repository AGENTS.md preserved, additive overlay (claude lane, runs b-k) | partial |
| 161 | The mission overlay is present. | P5 outcome F3: repository AGENTS.md preserved, additive overlay (claude lane, runs b-k) | partial |
| 162 | Discovery reports both the repo and the mission items. | P5 outcome F3: plugin cognition delivered, skill mc-cognition-diagnosing-bugs invoked (runs b-k); mechanism-reported discovery not separately recorded | partial |
| 164 | The kernel `before_tool` hook denies a forbidden command end-to-end on a live CLI drill, with trust handled. | No receipt in ledger (codex/cursor not run) | unrun |
| 165 | The release statement is updated to match the result. | No receipt in ledger (codex/cursor not run) | unrun |
| 167 | Inline `mcpServers` reach the agent. | No receipt in ledger (codex/cursor not run) | unrun |
| 168 | `.cursor/rules/mc-mission.mdc` is honoured. | No receipt in ledger (codex/cursor not run) | unrun |
| 169 | A `materialization.observed` signal arrives (needs SPEC-04 ingress). | No receipt in ledger (codex/cursor not run) | unrun |

### SPEC-03 Workspaces

| Line | Clause | Evidence source | Status |
| --- | --- | --- | --- |
| 124 | The three local lanes run with `policy.reuse: within_run`, a dirty-input refusal and cleanup after registra... | P5: claude_agent_sdk lane only; reuse within_run kept prior outputs (finding); .workspaces cleanup pending (P8) | partial |
| 126 | produces 5 `mc/{run}/m{i}` branches, 5 agents and 5 head-SHA artifacts; | No receipt in ledger | unrun |
| 127 | throttles correctly when `max_active_agents: 3`. | No receipt in ledger | unrun |
| 129 | launches on cursor_cloud against the knowledge workspace repo; | No receipt in ledger | unrun |
| 130 | fetches an Artifact input at run time; | No receipt in ledger | unrun |
| 131 | uploads an output Artifact that satisfies its Completion Contract. | No receipt in ledger | unrun |
| 132 | A forked cloud→local attempt reproduces the cloud head SHA in a local lease. | No receipt in ledger | unrun |

### SPEC-04 Observation and wake

| Line | Clause | Evidence source | Status |
| --- | --- | --- | --- |
| 258 | Run-token, Cursor-OIDC, provider-HMAC and environment-key signals are each accepted at their tier and rejec... | No receipt in ledger | unrun |
| 259 | Duplicates are dropped. | No receipt in ledger | unrun |
| 260 | Payload limits are enforced. | No receipt in ledger | unrun |
| 261 | Frames are persisted and visible in the transcript. | No receipt in ledger | unrun |
| 263 | The Telemetry Hook Pack delivers `session.started`, `materialization.observed` and `stop` signals through t... | No receipt in ledger | unrun |
| 264 | A gate hook enforces a `stop` within one tool call. | No receipt in ledger | unrun |
| 266 | `ci-red-fix`, `stalled` and `artifact-to-ingest` fire deterministically in a Temporal test environment. | No receipt in ledger | unrun |
| 267 | They respect `max_fires`, rate, recursion and budget. | No receipt in ledger | unrun |
| 268 | A replay produces no duplicate actions. | No receipt in ledger | unrun |
| 269 | **Wake:** a Claude Code coordinator using recipe 1 is woken by a real `run.completed` without polling in it... | P5 outcome run k: caller woken by terminal_result and review_required; finding: second review_required did not wake a fresh wait; part of S0-01, not promoted | partial |
| 270 | **No dead fields:** `controls.notifications` is consumed, and `channel: mcp` either works or is rejected by... | No receipt in ledger | unrun |

### SPEC-05 Owner prerequisites

| Line | Clause | Evidence source | Status |
| --- | --- | --- | --- |
| 115 | Preflight of a manifest that targets claude_cloud on a fresh installation lists A1–A7 and M1–M4 with genera... | P3: F1 preflight lists Claude A8 and M4 expired (not the claude_cloud A1-A7 case) | partial |
| 116 | After the steps and attestations, the probe mission runs and the prerequisites flip to `verified`. | P3: A8/M4 verified via missionctl prereq verify; preflight ready (f1-preflight-3.json); probe-mission flip not shown | partial |
| 117 | An expired A6 turns the lane back to blocked before the next launch. | P3: expired A8/M4 returned preflight to not ready; A6 not exercised | partial |
| 118 | A launch through the API with unmet prerequisites returns `PREREQUISITES_UNMET` with the same list. The coo... | P3: start 422 PREREQUISITES_UNMET with same two items before create (g1-start-unmet.json); coordinator relay not shown | partial |

### SPEC-06 Hosted API lanes

| Line | Clause | Evidence source | Status |
| --- | --- | --- | --- |
| 297 | Both new profiles pass the lane conformance suite against fakes, and describe honestly per §9. | No receipt in ledger (S2/S3 carried forward) | unrun |
| 299 | A knowledge mission uploads skills, runs `mc_prepare`, emits signals, produces an output file, and settles ... | No receipt in ledger (S2/S3 carried forward) | unrun |
| 300 | The budget-gate pause and resume works. | No receipt in ledger (S2/S3 carried forward) | unrun |
| 301 | An interrupt-and-inject works. | No receipt in ledger (S2/S3 carried forward) | unrun |
| 303 | A code mission on a Docker SandboxHost runs in a worktree lease. | Funding-held S4 (D1) | held |
| 304 | The kernel deny works through the tool wrapper. | Funding-held S4 (D1) | held |
| 305 | `mc_publish` pushes a verified bundle and the PR is created through the effect. | Funding-held S4 (D1) | held |
| 307 | Hosted: a knowledge mission with artifacts. | No receipt in ledger (S2/S3 carried forward) | unrun |
| 308 | Self-hosted: a code mission with exec-server in Docker. | No receipt in ledger (S2/S3 carried forward) | unrun |
| 309 | Cancel, steer and the function-tool approval round trip. | No receipt in ledger (S2/S3 carried forward) | unrun |
| 310 | Recovery after killing the worker mid-stream reconciles from items with no duplicate frames. | No receipt in ledger (S2/S3 carried forward) | unrun |
| 311 | **`claude_agent_sdk` @sandbox drill:** the Claude Code CLI in Docker through the Model Gateway; hooks fire ... | Funding-held S4 (D1) | held |
| 313 | A PHI-classed mission is refused on all API lanes. | P2/F0 negative: PHI on a hosted lane refused DATA_CLASS_NOT_ADMITTED (compile only) | partial |
| 314 | No org API key is present in any sandbox env or file (sentinel test). | No receipt in ledger (S2/S3 carried forward) | unrun |

### SPEC-07 Cursor maturity

The handoff extracts no original acceptance clauses for SPEC-07; see Gate L rows CM-01, CM-02, CM-04, CM-05, CM-07, CM-10.

| Clause | Evidence source | Status |
| --- | --- | --- |
| (no extracted clauses) | P4: Cursor cells blocked | blocked |

### SPEC-08 Direct CLI jobs

| Line | Clause | Evidence source | Status |
| --- | --- | --- | --- |
| 170 | Unit tests for the job schema validation, adapter argv construction for every profile and OS, the env allow... | No offline-test receipt recorded in this ledger | unrun |
| 171 | A fake-CLI harness: scripted executables emitting recorded JSONL drive the loop through done, blocked, budg... | No offline-test receipt recorded in this ledger | unrun |
| 173 | Cursor: does `-p` write without `--force`? Does it read the prompt from stdin? | P4: cursor-agent aborted twice by memory guard (host commit headroom about 3.6 GB) | blocked |
| 174 | Codex: exit codes and sandbox on Windows vs WSL. | No receipt in ledger | unrun |
| 175 | Claude: `result.subtype` on max-turns and schema failure. | No receipt in ledger | unrun |
| 176 | Which usage pool `claude -p` draws from after 2026-10-07. | No receipt in ledger | unrun |
| 177 | **End-to-end:** a Claude Code session launches two parallel jobs (a Codex fix and a Cursor review) in the b... | P4: cursor-agent aborted twice by memory guard (host commit headroom about 3.6 GB) | blocked |

### SPEC-09 Local harness and S0

| Line | Clause | Evidence source | Status |
| --- | --- | --- | --- |
| 120 | the CLIs found at pinned versions, not Windows shims; | P3: Claude CLI pinned in WSL venv (claude-agent-sdk 0.2.165, Claude Code 2.1.294); codex and cursor not verified | partial |
| 121 | auth per route; | P3: claude-sdk-api auth profile; codex-api-configured unproven; cursor not run | partial |
| 122 | lease roots on the Linux filesystem. | P3: same-host ext4 lease/payload root | partial |
| 124 | the caller is woken by `missionctl wait`; | P5 outcome (S0-01 partial-not-promoted) runs b, c, d, j, k | partial |
| 125 | one inject is delivered and recorded; | P5 outcome (S0-01 partial-not-promoted): inject applied on runs b, c, d, j; run k inject stayed queued | partial |
| 126 | one run is cancelled cleanly; | P5 outcome (S0-01 partial-not-promoted): clean immediate cancel on run b | partial |
| 127 | the worktrees are cleaned after custody. | P5: custody before cleanup on claude lane; .workspaces cleanup pending (P8) | partial |
| 128 | **The same three-lane probe set passes on Temporal Cloud.** | Codex/Cloud cells unrun, Cursor cells blocked (S0 table) | unrun |
| 129 | **No secret appears in frames or logs; the child envs contain only the allowlist.** | P2/F0 no-secret-echo.json; allowlist env not shown on live frames | partial |

### SPEC-10 Vercel ingress

| Line | Clause | Evidence source | Status |
| --- | --- | --- | --- |
| 151 | **Per route:** tier accept and reject tests, dedupe, size and rate limits, and forged or replayed webhook r... | Carried forward (D1, S1); not run | unrun |
| 152 | **The import-closure test passes**; the Vercel build is under the size limit. | Carried forward (D1, S1); not run | unrun |
| 153 | **Real local PostgreSQL tests** for every SQL function, including the gate's intent-before-allow ordering a... | Carried forward (D1, S1); not run | unrun |
| 155 | Cursor cloud hooks deliver ordered signals through the deployed ingress. | Carried forward (D1, S1); not run | unrun |
| 156 | The gate's measured p99 is recorded. | Carried forward (D1, S1); not run | unrun |
| 157 | A stop takes effect within one tool call. | Carried forward (D1, S1); not run | unrun |
| 158 | An artifact over 4.5 MB arrives through the signed upload and is verified into custody. | Carried forward (D1, S1); not run | unrun |

### SPEC-11 AWS worker

| Line | Clause | Evidence source | Status |
| --- | --- | --- | --- |
| 166 | The service runs one task with no inbound rules, and readiness passes against Temporal Cloud, Supabase (poo... | Carried forward (D1, R); not run | unrun |
| 167 | **Laptop-off proof:** with the owner's machine powered off, a hosted-lane probe mission runs to completion ... | Carried forward (D1, R); not run | unrun |
| 168 | **Restart proof:** stopping and restarting the service mid-session reattaches with no duplicate frames. | Carried forward (D1, R); not run | unrun |
| 169 | **Secret sentinel:** no secret value in the image, task definition, logs, repo or handoff. | Carried forward (D1, R); not run | unrun |
| 170 | `deploy.ps1` redeploys a new build with no console steps. | Carried forward (D1, R); not run | unrun |
| 171 | The 24-hour CPU and memory profile and the cost estimate are recorded in the handoff. | Carried forward (D1, R); not run | unrun |

## Gate L issues (21); issue own-acceptance status unchanged in every row

| Issue | Title | Evidence source | Proof status | Issue status |
| --- | --- | --- | --- | --- |
| CM-01 | Cloud and local cost settlement | P4 Cursor cells blocked; cost unknown | blocked | implemented but unqualified |
| CM-02 | Per-run token attribution across all turns | P4 | blocked | implemented but unqualified |
| CM-05 | Detached bridge and live reattach | P4 | blocked | implemented but unqualified |
| CM-07 | Conversation export for forks and continuations | P4 | blocked | implemented but unqualified |
| CM-10 | Parallel Cursor units in one run get distinct workspaces | P4 | blocked | implemented but unqualified |
| MO-03 | Back Codex kernel hooks and handle Codex hook trust | Stock-take: codex lane unprepared | unrun | implemented but unqualified |
| MO-07 | Reconcile stale documentation and status statements | Stock-take: P7 documentation in progress (this index, S0 cells, appendix) | partial | active development |
| MO-73 | Verify Claude SessionStore restore with the custom transport | No SessionStore restore receipt | unrun | implemented but unqualified |
| LS-05 | Router skill, per-CLI skills, recipes and attributions | P0: skills present only | unrun | implemented but unqualified |
| LS-07 | Live smoke checklist for the CLI open items | P4 attempts 1-2: `ls/ls07-cursor-run.log`, `ls07-cursor-run2.log` | blocked | blocked |
| LS-08 | End-to-end delegation demo from a Claude Code session | Stock-take: Cursor review blocked | blocked | blocked |
| CM-04 | cursor_local on Windows workers | P4 | blocked | implemented but unqualified |
| MO-08 | WSL2 worker runbook and host preflight for local Claude and Codex lanes | P3 Claude host attestation (A8/M4); Claude lane only | partial | implemented but unqualified |
| MO-63 | Lane-only worker role | P3 used role base plus lane queues; no lane-only worker | unrun | implemented but unqualified |
| MO-64 | Split-host payload custody preflight | P3 same-host payload root; no split-host | unrun | implemented but unqualified |
| MO-67 | Temporal Cloud qualification run | Stock-take: Temporal Cloud not re-pointed | blocked | blocked |
| MO-68 | Preflight accepts a local deployments root | P3 normal preflight ready; no dedicated deployments-root receipt | partial | implemented but unqualified |
| MO-69 | Binding digest tool for compose-bindings | Stock-take; no digest-tool receipt | blocked | blocked |
| MO-70 | missionctl token mint helper | P3 sign-in only; no helper receipt | unrun | implemented but unqualified |
| MO-71 | S0 probe manifests for all three local lanes | Claude-lane manifests only (P2/F0, P5) | blocked | blocked |
| MO-72 | Slice S0 end-to-end: local harness path from all three tools | S0-01 partial-not-promoted; 17 other cells unrun/blocked | partial | blocked |

## Counts

SPEC clause rows by status (SPEC-07 counted as one blocked row): blocked 3, held 4, partial 23, unrun 55 (total 85).

Gate L issue rows by status: blocked 11, partial 4, unrun 6 (total 21).

S0 cells: partial-not-promoted 1, blocked 4, unrun 13; qualified complete 0.

## Go/no-go

No-go for the wider Gate L: F0 and F1 passed, F3 and F4 partial, F2 deferred; S0 has no qualified complete cell. Open findings are carried in the ledger Stock-take section.

## Finish (2026-10-20): materialize-and-run cells

Added by the lead (`claude-opus-5-5`) under the [finish instructions](../RUN-2-FINISH-INSTRUCTIONS-2026-10-19.md).
The rows above are kept as recorded on 2026-10-19. Owner decision E1 supersedes the 18 S0 cells
with the lane × scheduler matrix below. Evidence: [ledger](RUN-2-CLOSE-STATUS.md), section
"Finish"; outcomes in the [finish disposition](RUN-2-FINISH-DISPOSITION-2026-10.md).

| Row | Evidence source | Status |
| --- | --- | --- |
| MR-01 claude_agent_sdk × local | W1: run `e7d24a4b`, cancel `cc6d5594`; private `w1/MR-01-receipt.json` | passed |
| MR-02 codex × local | W2: run `a901422d`, cancel `235fcc73`; X4/X6 API-key host proof; `w2/MR-02-receipt.json` | passed |
| MR-03 cursor_local × local (WSL) | W3: run `7132d2de`; C9/M4 verified; `observe_run` rejected (lane defect); bridge 199 MB peak | blocked (moved, E2) |
| MR-11 claude_agent_sdk × Temporal Cloud | W4: run `37ce4f20`; `w4/MR-11-receipt.json` | passed |
| MR-12 codex × Temporal Cloud | W4: run `60cca228`; `w4/MR-12-receipt.json` | passed |
| MR-13 cursor_local × Temporal Cloud | needs MR-03 | unrun |
| LS-08 substitute demo | W5: Codex fix `done` (verify exit 0) and Claude review (report correct; verify failed on a CRLF fixture hash); session woken in the background | passed (substituted, E5) |
| SPEC-01 line 233, child environment allowlist | W1/W2/W3: child-environment name captures for the Claude CLI, the Codex app-server (plus the tool-shell `include_only`) and the Cursor bridge; no worker DSN, Temporal, AWS or foreign provider key | evidenced (claude_agent_sdk, codex, cursor_local bridge) |
| F3 negatives, F4 controls/accounting | moved to provider-sprint C01 / C07, C08 and usage work (finish section 5) | partial (moved) |
