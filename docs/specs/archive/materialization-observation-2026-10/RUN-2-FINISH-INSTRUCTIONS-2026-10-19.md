---
type: Sprint Instructions
title: "Run 2 finish: handoff and refined instructions (2026-10-19)"
description: "Instructions for the agent session that finishes Run 2: the owner's 2026-10-19 reframing (the sprint harness is the caller; the proof is materialize-and-run per provider lane), the finish line, the work items in order, the re-slicing of the 21 Gate L issues, what moves to the provider-consolidation program, operating rules and the closing procedure."
---

# Run 2 finish: handoff and refined instructions

**Authority.** These instructions come from the owner's decisions of 2026-10-19 (section 2). Where they
differ from [the 2026-10-18 instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md), the
[execution sequence](RUN-2-EXECUTION-SEQUENCE-2026-10-18.md) or SPEC-09 section 9, these instructions
win. Everything else in those documents still applies, including the security rules, the receipt-only
status rule, no push, no deploy and no S4.

**Starting state.** `main` at `1b22ddab`, or later. The close-out so far is in
[the completion summary](runs/RUN-2-COMPLETION-SUMMARY-2026-10.md) and
[the status ledger](runs/RUN-2-CLOSE-STATUS.md). The owner is present for authentication and decisions.

**Read the [interface map](RUN-2-INTERFACE-MAP-2026-10-19.md) section 0 before W1.** It lists ten verified facts that change the work items
below, and the items have been amended to match.

## 1. Why the plan changed

1. **The caller is the sprint harness.** The original S0 matrix required every caller tool (Claude Code,
   Codex, Cursor) to drive every agent lane: 3 × 3 × 2 schedulers = 18 cells. The owner has removed the
   caller dimension. Whichever harness runs this sprint (here, Claude Code) submits, waits on, peeks into
   and cancels the missions. Proving that other tools can call Mission Control is not a goal.
2. **The proof is "materialize and run".** For each provider lane, a mission that carries that
   provider's specific agent configuration compiles, materializes inside the provider's real harness,
   runs its workflow with its agent cognition to a governed terminal state, and is observed through
   Mission Control. That is what this packet (materialization-observation) exists to prove.
3. **Controls, state and recovery have their own program.** Intervention semantics, approval timing,
   resume/restore, fork and time travel, usage/cost attribution and the Temporal-plus-provider state
   model all belong to the owner's next program: provider consolidation, one provider at a time. Its
   draft is at `docs/specs/provider-consolidation-2026-10/` (`README.md` and `BASELINE-2026-10-19.md`),
   written by another session and committed on `main` at the owner's request (`c6235e5d`, E11). Run 2
   hands these over. It does not finish them.
4. **A natural stopping point.** Run 2 ends when the finish line in section 3 is met or each
   unmet item is recorded with its exact blocker. Then the owner starts the per-provider sprints from
   a clean `main`.

## 2. Owner decisions (2026-10-19)

| ID | Decision |
| --- | --- |
| E1 | The sprint harness is the only caller. The 18-cell caller × lane × scheduler matrix is superseded by a lane × scheduler matrix (section 3). The "from each tool" clause of SPEC-09 §9 and the "all original caller/lane S0 runs remain required" refinement are withdrawn. |
| E2 | Lane scope: `claude_agent_sdk` and `codex` are required. `cursor_local` gets **one** memory-guarded attempt on the WSL worker. If the host cannot hold it, it is recorded blocked and moves to the Cursor provider sprint. |
| E3 | Temporal Cloud: rerun the same materialize-and-run mission on `mission-control-dev.ih0e7` for every lane that passed locally. |
| E4 | Parked runs: cancel run j `831f33f4-bf57-5b89-831f-1f2e3bd4c5f8` as superseded by run k (record it). Leave run `ec193a1e-9e4f-574f-992d-a6ad16733ff2` parked `cancelling` and record it for the consolidation program (its in-doubt reconciliation is a recovery capability). |
| E5 | CLI delegation skills: close LS-08 with a substitute demo, a Codex fix job plus a Claude review job launched from a Claude Code session. The Cursor CLI questions of LS-07 move to the Cursor provider sprint. |
| E6 | Interject/inject, pause, approval timeout behaviour, recovery, resume, fork, usage/cost attribution and the in-doubt classification are **not** finish-line requirements. Observe and record them if they happen; never block on them. (Derived from the owner's 2026-10-19 guidance; the owner may amend.) |
| E7 | No new kernel or feature work. Code changes are allowed only to fix a defect that blocks a section 3 cell, under the P5 discipline (section 6.3). |
| E8 | Usage reported as `unknown` is recorded and does not block a cell. |
| E9 | Implement the MO-70 token helper path locally. Generate an operator ES256 key pair, with the private key mode 0600 under `run2-close-20261018/private/` and never committed. Add its public key to the **local** pinned JWKS file that G1's `deployment.json` names (`public_jwks_file`; no Supabase change). The harness then mints its launcher tokens with `missionctl token mint`, for subject `service:run2-s0-launcher` only, `--expires-in` ≤ 3600. `launcher_token.py` stays as the fallback. |
| E10 | Codex authenticates with the owner's OpenAI API key (`OPENAI_API_KEY`, profile `codex-api-configured`), billed per token to the API account. The ChatGPT subscription login is not used. |
| E11 | The provider-consolidation draft is committed on `main` (`c6235e5d`). It remains a draft for owner review. Do not edit it in Run 2. |

Earlier decisions D1–D7 (2026-10-18) still apply where these do not override them: D3 ceilings and
10 USD slice caps, D4 release done, D5 done, D6 F2 deferred, D7 local commits only.

## 3. The finish line

### 3.1 The materialize-and-run (MR) cell

One cell = one lane × one scheduler. A cell **passes** when one recorded run shows all of the following:

1. **Compile and preflight.** The lane's MR manifest compiles with 0 blockers and preflight is ready,
   with the lane's own owner prerequisites (host attestation, auth, broker names) verified through the
   normal probe path.
2. **Provider-specific configuration in effect, observed from agent behaviour.** Writing files to disk
   is not enough. All of:
   - repository instructions preserved, plus the additive mission instruction;
   - one plugin or skill actually invoked;
   - the pinned model reported by the native session;
   - one allowed tool family used;
   - one disallowed tool family absent or denied;
   - outputs written to the declared schema.
3. **The workflow runs.** Stage Graph diagnose → patch → review (the F1 run-k shape). Every stage is
   accepted, its reports are schema-valid and in custody, and the run reaches terminal `completed`. The
   human gate's reviewer is the harness service, disclosed as in run k.
4. **Observed through Mission Control.** The harness waited with `missionctl wait` before start, was
   woken and acknowledged. During the run it took at least one peek (`missionctl run inspect` and
   `run transcript`).
5. **Clean cancel.** A second, short run on the same lane is cancelled `--urgency immediate`. It
   reaches terminal `cancelled`, and no native process remains.
6. **Hygiene.** Workspaces are cleaned after custody, a sentinel search finds no secret in frames or
   logs, and the child environment matches the allowlist.

### 3.2 The matrix

| Cell | Lane | Scheduler | Required | Starting point |
| --- | --- | --- | --- | --- |
| MR-01 | claude_agent_sdk | local Temporal | yes | Points 1–4 are mostly evidenced by run k `554d2b2a…`, and point 5 by run b `519816f2…`. Run k has no transcript or model receipt (only run b shows `claude-sonnet-5-5`), and neither run has a sentinel or allowlist receipt. **Fetch the run k transcript and run the hygiene checks now. If any clause cannot be shown, do one fresh MR-01 run.** |
| MR-02 | codex | local Temporal | yes | Not run. Codex prerequisites first. |
| MR-03 | cursor_local | local Temporal (WSL worker) | one attempt (E2) | Not run. Memory gate first. |
| MR-11 | claude_agent_sdk | Temporal Cloud | yes (E3) | After the worker is re-pointed to Cloud. |
| MR-12 | codex | Temporal Cloud | if MR-02 passed | |
| MR-13 | cursor_local | Temporal Cloud | if MR-03 passed | |

### 3.3 Also on the finish line

- **LS-08 substitute demo (E5).** From a Claude Code session, the router skill launches two background
  jobs, a Codex fix and a Claude review. The session is woken on completion and reads both result
  files. This also qualifies LS-05 if the router and per-CLI skills are what ran.
- **Records reconciled** (section 7). Every Gate L issue shows one of three outcomes: closed by receipt,
  recorded with an exact blocker, or moved by an E-decision.
- **Repository closed out.** Final checks and the wheel rebuilt. Worktrees reconciled: the canonical
  folder on `main`, only the offline worktree retained.

Anything not listed in section 3 is not required to finish Run 2.

## 4. Work items, in order

Each item: lease, steps, exit, cost. Run one heavy job at a time (section 6.1).

**W1 — Park and record (no spend).**
Set up E9 (operator key, local JWKS entry, then a test mint with `missionctl token mint` followed by
one authenticated read). Start G1 (section 6.2). Cancel run j with a normal cancel and record the receipt. Record `ec193a1e`
as parked. Assemble MR-01 from run k and run b receipts (`run2-close-20261018/g1/s0-01k/`, `s0-01b/`).
Check each clause in 3.1 against an actual receipt. Fetch run k's transcript and inspection (the
model and the peek clauses). Run the sentinel search over the stored frames and logs, and record
the child-environment allowlist. If a clause still lacks a receipt, do one fresh MR-01 run with
`f1k.mission.yml`. Exit: MR-01 passed or the missing clause named.

**W2 — Codex lane (MR-02).**
1. Tooling first (map §0 and §2.4):
   - Give the API process `OPENAI_API_KEY` in `serve.py`; today it has only
     `ANTHROPIC_API_KEY`, so the Codex `broker_names` (M4) check fails.
   - Generalize `restart_g1.py`. Select the prerequisites by lane instead of by `.a8.`, and merge
     all bindings into `owner-probes.json` (a8, x4, x6, one m4 per lane, and c9 later). Re-verify
     each m4 within its 1-hour validity.
   - Extend `caller_loop.py` to decide Codex approval kinds (`commandExecution`, `fileChange`,
     `permissions`) by the same policy. Otherwise the 300 s auto-deny kills the turn.
2. Codex host proof (X4/X6). Write the observer that produces the observation file the verifier
   checks: an app-server API-key login with an ephemeral credential store and no `auth.json`,
   `account/read` reporting `apiKey`, and `model/list` containing `gpt-6-luna`. These calls are
   metadata only, with no inference. The worker runs the nvm `codex` binary, which must be exactly
   0.162.1; the launcher refuses any other version. Only the API-key route can pass the verifier.
   The SPEC-09 "ChatGPT login" selection has no proof path. The owner chose the API key (E10), so
   `codex-api-configured` (`OPENAI_API_KEY`) is the route. Never script a ChatGPT login.
3. Manifest. Derive `mr-codex.mission.yml` from `g1/f1k.mission.yml`: lane `codex`, model `gpt-6-luna`
   (SPEC-09 owner selection R22), the same plugin/skill, Codex sandbox/approval policy, `reuse: none`.
   Compile, then preflight.
4. Run once, with the caller loop handling approvals (section 6.2). Run the cancel variant once.

Exit: MR-02 passed, or the blocker recorded with a receipt. Cap: 10 USD.

**W3 — Cursor lane, one attempt (MR-03).**
1. Memory gate before anything starts. Measure Windows available memory and commit headroom, and WSL
   `free -m`. Stop Docker containers that are not needed. Drop the WSL page cache. The WSL VM is capped
   at 6 GB (`.wslconfig`), and raising it needs an owner decision and a WSL restart.
2. Configuration and prerequisites (map §2.5, §4.3). G1 has no `cursor_local` entry in
   `launch-bindings.json` or `auth-profiles.json`, so author both. Give `CURSOR_API_KEY` to the API
   and the worker, and serve the Cursor lane queue. The C9 host proof (`cursor_native_host`) pins:
   - Node `v24.5.0` from the bridge's own runtime (WSL's v24.21.0 does not count);
   - bridge archive `1.0.0`;
   - a cleanup fixture whose `repo_url` equals the protected root's path.

   The private earlier capture script under
   `run2-fresh-session-20261017/.../native-cursor-observation-v2/capture_host_core.py` shows the
   method. Derive `mr-cursor.mission.yml` from f1k with lane `cursor_local`. Cursor cannot use
   per-command approval; refusing it is correct, not a defect. The bridge's memory use is
   unmeasured (the 3.6 GB figure was the `cursor-agent` CLI), so measure it during the run.
3. Run once under a WSL-side memory watch that stops only the owned processes. If memory aborts it or
   the host refuses, record MR-03 blocked with the measurements. Do not try again.

Cap: 10 USD.

**W4 — Temporal Cloud (MR-11..13).**
1. Read the namespace, address and API-key secret names from SPEC-09 §9 and the MO-78 evidence. Fetch
   the key into the child environment only.
2. The MO-78 evidence shows all 14 search attributes already present. Re-check them with
   `scripts/temporal_cloud/configure_search_attributes.py --plan`. Do not use
   `register_belllabs_search_attributes.py`; it is for self-hosted servers. Change `deployment.json`'s
   Temporal address and namespace together with the environment variables, or the client refuses
   (map §3.4). Point a fresh worker and the API
   at Cloud with fresh private queue names.
3. Rerun each locally-passed MR manifest once. A cancel variant is not required on Cloud.

Exit: each cell passed or blocked with a receipt. Cap: 10 USD across all Cloud cells.

**W5 — LS-08 substitute demo (E5).**
Use the `.agents/skills` router (`coding-cli-jobs`), not Mission Control. Run one Codex fix job and one
Claude review job on the retained disposable fixture (`run2-close-20261018/ls/fixture`). Record the
session transcript and both result files. Cap: 5 USD.

**W6 — Close-out** (section 7).

## 5. Gate L issue re-slicing

This table records dispositions. It does not edit `issues.json` or any status. A status changes only
from a receipt.

| Issue | Disposition | Closing evidence or destination |
| --- | --- | --- |
| MO-72 S0 end to end | **Finish, reframed (E1)** | MR-01..03 local cells |
| MO-71 S0 probe manifests | **Finish** | The three MR manifests compile with 0 blockers (MR-03's compile counts even if its run is blocked) |
| MO-67 Temporal Cloud qualification | **Finish, reframed (E3)** | MR-11..13 for the lanes that passed |
| MO-68 preflight local deployments root | **Finish** if a G1 preflight receipt shows it; otherwise record | G1 preflight receipts |
| MO-70 missionctl token mint helper | **Finish (E9)** | W1: operator key added to G1's local JWKS; W2–W4 runs use tokens minted by `missionctl token mint` |
| MO-08 WSL2 worker runbook and host preflight | **Finish** | Write the runbook from the G1 procedure (section 6.2) into the repository docs, with a host-preflight receipt |
| LS-05 router and per-CLI skills | **Finish** | W5 |
| LS-08 delegation demo | **Finish, substituted (E5)** | W5 |
| LS-07 CLI live smoke | **Split (E5)** | The Claude and Codex items are answered from existing receipts or W5. The Cursor items move to the Cursor sprint |
| MO-07 stale documentation | **Finish** | Close-out documentation pass |
| CM-01, CM-02, CM-04, CM-05, CM-07, CM-10 Cursor maturity | **Move** to the Cursor provider sprint | The cursor_local baseline refuses Windows and needs WSL plus headroom. Cost and attribution go to that sprint's usage work |
| MO-03 Codex hooks and hook trust | **Move** to the Codex sprint | Record any hook evidence MR-02 shows; no promotion required |
| MO-73 Claude SessionStore restore | **Move** to provider consolidation (state/recovery) | |
| MO-63 lane-only worker role, MO-64 split-host custody | **Move** to stream R (remote worker topology) | |
| MO-69 binding digest tool | **Move** to consolidation Sprint 0 tooling | |

Fixtures: F0 and F1 passed. F3 and F4 close as **partial**, with their remainders moved:
- F3 negative composition controls go to each provider sprint's C01 (seed and spawn).
- F4 controls and accounting go to C07, C08 and the usage work.

F2 stays deferred (D6).

## 6. Operating rules

### 6.1 Resources (this host: about 15 GB RAM, WSL VM capped at 6 GB)

- Run every heavy command in the **foreground** through `run2-close-20261018/resources/guard.py`. Claude
  Code reaps idle background shells under memory pressure, and that killed a caller loop in run d.
  Keep each command under 10 minutes and make long work resumable (see `p8/unit_batches.sh`).
- Before a live run: stop unneeded Docker containers (starting Docker auto-restarts the Biotech
  containers), drop the WSL page cache, and check commit headroom. Never kill Cursor IDE, MCP or other
  sessions' processes.
- Subagents: no long-running general-purpose agents. Never put `rm` on a variable path in an agent's
  command: the permission prompt stalls it unattended (a 10-hour stall happened). Prefer short agents
  with one bounded job and a written result file.

### 6.2 Serving and calling (G1)

- **Tooling** (private, `run2-close-20261018/g1/`):
  - `restart_g1.py <manifest>` re-measures the host, re-derives and verifies A8/M4, refreshes tokens,
    and starts the API (`127.0.0.1:18090`) and worker detached through `serve.py`.
  - `wsl_ctl.sh stop-api|stop-worker|status` stops them by exact match.
- **Extend for new lanes.** The restart covers the Claude host only. Add the Codex and Cursor host
  attestations in the same pattern; keep secrets in the child environment only.
- **Tokens expire after 1 hour.** Re-mint before each run. The first HTTP call after idle can fail
  client-side; retry it with the same request id.
- **Caller loop** (`caller_loop.py`):
  - register the wait before start;
  - decide provider-permission tasks by the logged policy, and keep the policy reviewed;
  - stop for manual review on anything unlisted;
  - answer approvals within 300 s (an undecided approval auto-denies and kills the turn: a known
    defect, moved to consolidation K12).
- **Disclosed configuration:** the worker's `MISSION_CONTROL_APPROVAL_REVIEWERS` names the harness
  service. Gate reviewers in MR manifests are the harness service.
- **Known workarounds, do not "fix" in Run 2:**
  - `reuse: none` on stages (reused leases re-collect old `outputs/`; K01);
  - inject text must not ask for prose, and the final answer is the JSON contract;
  - one goal per stage.
- **Workspaces:** keep lease roots on the Linux filesystem (`~/mc-close-workspaces`), never under a
  Windows checkout (paths exceed MAX_PATH).
- **Checkout:** the G1 WSL venv is an editable install of the MAIN checkout. **Do not remove MAIN until
  W1–W5 are done**; worktree reconciliation is the last step.

### 6.3 If a cell is blocked by a defect (E7)

Open a lease in an isolated worktree off `main`, with an Opus 5.5 implementer. Get at least one fresh
Opus 5.5 review, then run guarded checks and apply byte-identical to MAIN. Commit with hooks (never
`--no-verify`), then re-attest the host before rerunning. If the fix is not small and local, record the
cell blocked and move the defect to the consolidation program instead.

### 6.4 Carried findings (do not work on them in Run 2)

| Finding | Goes to |
| --- | --- |
| Reused lease keeps prior `outputs/` | Consolidation K01 |
| Undecided approval auto-denies at 300 s; reviewers default to `owner` | K12 |
| Inject aimed at a finished node neither applied nor refused; P5b residual timeout window | K13 / C07 |
| `missionctl wait` does not refresh tokens; second `review_required` not waking a fresh wait | K16 |
| P5c multi-output and Goal Loop output-contract gaps | K02–K04 / C02, C04 |
| Pre-create secret refusal classified `in_doubt`; parked `ec193a1e` | Consolidation recovery (state sprint) |
| Usage `unknown` on every run | Per-provider usage work (C-usage in each sprint) |
| Configuration values not delivered to the lane runtime | Provider sprints C01/C12 |
| Latent frozenset JSON dump `programs/service.py:530`; 6 pre-existing unit failures | Sprint 0 housekeeping |
| Owner TODO: multi-agent on code missions (`anthropic_managed/harness.py`) | claude_managed sprint (C10) |
| First HTTP call after idle fails client-side (WSL forwarding) | Operations note only |

## 7. Closing procedure (W6)

1. **Records**, receipt-only:
   - Append a `finish_2026_10` block to `runs/FINAL-CAPABILITY-S0-18-CELLS.json`: the MR matrix with
     run ids and receipt digests, and the 18 original cells marked `superseded_by_owner_decision: E1`.
     Do not delete the old rows.
   - Update `FINAL-CAPABILITY-ISSUE-ACCEPTANCE-APPENDIX.json` for each issue whose clause a receipt now
     satisfies.
   - Add `runs/RUN-2-FINISH-DISPOSITION-2026-10.md` with the section 5 table and its results.
   - Update `RUN-2-F5-PROOF-INDEX.md` and append a "Finish" section to the ledger.
2. **Summary.** Add a "Finish (2026-10-…)" section to the completion summary using its ten headings, and
   send that section as the final message.
3. **Checks**, guarded and serial, as in the P8 record:
   - lock, ruff, format, mypy, ty, deptry;
   - architecture, conformance and per-directory unit tests;
   - schemas, seeds and skills;
   - docs index, links and OKF.

   Then rebuild the wheel without installing it.
4. **Reconciliation:**
   1. Confirm `git status` in MAIN is clean. The provider-consolidation draft is already committed
      (E11); if its author has added uncommitted changes since, ask the owner before removing MAIN.
   2. Stop G1 and the WSL processes by exact PID.
   3. Unlink MAIN `.venv` (`cmd /c rmdir`), then `git worktree remove` MAIN, without `--force`.
   4. In `platform/mission-control`, run `git checkout main` and `git branch -d mo/run2-integration`.
   5. Verify: the worktree list is canonical (`main`) plus offline, `git branch --no-merged main` is
      empty, status is clean, and `git fsck --no-dangling` passes.
5. Stop the local Temporal containers and Docker Desktop if they were started for this work.

## 8. Read first

1. This page, then the [completion summary](runs/RUN-2-COMPLETION-SUMMARY-2026-10.md) sections 3, 5
   and 8.
2. The [status ledger](runs/RUN-2-CLOSE-STATUS.md): P3 (G1), P5 and the P5 outcome.
3. `g1/f1k.mission.yml`, `g1/restart_g1.py` and `g1/caller_loop.py` (private, `run2-close-20261018/`).
4. [SPEC-09](SPEC-09-local-harness-path.md) §9 owner selections (pins, models, Cloud variant), read with
   E1–E3.
5. Provider-consolidation `README.md` and `BASELINE-2026-10-19.md`, so that nothing is built here that
   the next program owns.

## 9. Copy-paste lead prompt

```text
You are the lead for the Run 2 finish of the Mission Control materialization-observation
sprint, running as Claude Code on claude-opus-5-5. Work in the live checkout
C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main (branch main). Do not work in
platform/mission-control, which is a detached read-only mirror until the final reconciliation.

Read, in order:
1. docs/specs/archive/materialization-observation-2026-10/RUN-2-FINISH-INSTRUCTIONS-2026-10-19.md
   (your authority and plan)
2. docs/specs/archive/materialization-observation-2026-10/RUN-2-INTERFACE-MAP-2026-10-19.md
   (code entry points and gotchas)
3. runs/RUN-2-COMPLETION-SUMMARY-2026-10.md and runs/RUN-2-CLOSE-STATUS.md
4. the private tooling in C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-close-20261018/g1/

Execute W1 to W6 in order. The owner is present for authentication and decisions; ask only
for those.

Rules:
- One heavy job at a time, in the foreground, through
  run2-close-20261018/resources/guard.py. Check memory before every live run.
- No long-running background agents. Never rm a variable path.
- No push, no deploy. Never print secrets or env files.
- Change a status only from a receipt.
- Fix code only for a defect that blocks a cell (instructions section 6.3).
- Leave docs/specs/provider-consolidation-2026-10/ alone; another session owns it.
- Append each work item's result to runs/RUN-2-CLOSE-STATUS.md as you go.

Finish with the section 7 closing procedure. Your final message is the "Finish" section of
the completion summary.
```
