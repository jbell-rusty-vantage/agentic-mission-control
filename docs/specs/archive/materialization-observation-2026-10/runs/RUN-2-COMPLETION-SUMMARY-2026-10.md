---
type: Sprint Completion Summary
title: "Run 2 completion summary (Gate L close-out, 2026-10-19)"
description: "Outcome, decisions, acceptance delta, source identity, checks, worktree reconciliation, spend, carried-forward streams and evidence locations for the Run 2 Gate L close-out."
---

# Run 2 completion summary

Lead: Claude Code on `claude-opus-5-5`. Procedure:
[instructions](../RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md) section 6.
The detailed record for each phase is in [RUN-2-CLOSE-STATUS.md](RUN-2-CLOSE-STATUS.md), and the
proof rows are in [RUN-2-F5-PROOF-INDEX.md](RUN-2-F5-PROOF-INDEX.md).

## 1. Outcome

Run 2 closed on `main` at the commit that carries this summary. The last source commit is
`6fcb4f82`, and the reconciliation merge is `de792e8b`. Gate L is **not met in full**.

What passed:
- the installation configuration source for `value_ref: config:<key>` (P1);
- the D5 AI Engineer SDLC report-schema seed release, applied live with readback;
- F0, full configuration compilation with zero native create;
- G1, ordinary local serving;
- F1, the representative SDLC workflow (diagnose → patch → independent review → human gate). It
  completed on run `554d2b2a…` with four accepted outputs. The gate reviewer was the caller
  service, which is disclosed: it was not the human owner.
- four reviewed launch-path defect fixes found by live runs (P5a–P5d).

What did not pass:
- S0-01 is partial and was not promoted, because the completing run's own inject stayed queued
  and usage is unknown.
- 17 of 18 S0 cells did not run. The Cursor CLI commits about 3.6 GB on this host. Codex-lane
  prerequisites and the Temporal Cloud variants were not reached.
- LS-07's Cursor cell is blocked, and LS-08 is blocked or unrun.
- F3 and F4 are partial. F2 is deferred.

No issue status was promoted. Nothing was pushed or deployed, and there was no S4 release.

## 2. Decisions applied

| ID | Decision | Applied |
| --- | --- | --- |
| D1 | Close at Gate L; R, S1, S2, S3, funding-held S4 carry forward | Yes. Gate L recorded as not fully met (section 1) |
| D2 | Claude Code `claude-opus-5-5` implementer/reviewers; Sonnet 5.5 for exploration and evidence | Yes. Every source change had at least one fresh Opus 5.5 review. Sonnet 5.5 did the worktree classification and the F5 assembly |
| D3 | Native local fixtures within fresh ceilings and 10 USD slice caps, one job at a time | Yes. One bounded job at a time through the memory guard |
| D4 | Release the stale 10 USD Cursor LS hold | Yes. Released on the recorded dashboard evidence |
| D5 | Report-schema seed release end to end, including live apply under conditions | Yes. All conditions held, so no further owner go was needed: catalog absence, additive slot, six disposable proofs, dry run plus backup record, one apply, readback |
| D6 | F2 deferred | Yes |
| D7 | Local commits and local `main` merges; no push/deploy/S4 | Yes |

Owner input received during the run: active resource management was directed, and continuing
was approved (2026-10-19). No schema go/no-go was requested, because D5's conditions covered it.

## 3. Acceptance delta

- **Issue counts:** before, 38 done / 41 implemented-unqualified / 18 blocked / 12 not started /
  1 active. After, the same. **No issue changed status.** Every Gate L issue in
  `FINAL-CAPABILITY-ISSUE-ACCEPTANCE-APPENDIX.json` carries a `close_out_2026_10_19` annotation
  with `status_unchanged: true`.
- **S0 cells** (`FINAL-CAPABILITY-S0-18-CELLS.json`, `qualified_complete_cells` = 0):

| Cell | Caller × lane | Local Temporal (01–09) / Cloud (10–18) | Status |
| --- | --- | --- | --- |
| S0-01 | Claude Code × claude_agent_sdk | local | partial (not promoted) |
| S0-02 | Claude Code × codex | local | unrun (Codex-lane prerequisites/attestation) |
| S0-03 | Claude Code × cursor_local | local | blocked (host commit headroom, cursor-agent) |
| S0-04 | Codex × claude_agent_sdk | local | unrun (Codex caller not exercised) |
| S0-05 | Codex × codex | local | unrun (Codex caller and lane prerequisites) |
| S0-06 | Codex × cursor_local | local | blocked (host commit headroom) |
| S0-07 | Cursor × claude_agent_sdk | local | blocked (Cursor caller, host commit headroom) |
| S0-08 | Cursor × codex | local | unrun (Codex lane) |
| S0-09 | Cursor × cursor_local | local | blocked (host commit headroom) |
| S0-10..18 | the nine combinations above | Temporal Cloud | unrun (Cloud namespace, search attributes and worker re-point not done) |

  The ledger file records the exact per-cell gate.
- **LS-07:** the Cursor cell is blocked. Two guarded attempts were stopped at 695 MB and 480 MB
  commit headroom with zero frames. **LS-08:** unrun. Its Cursor review half is blocked for the
  same reason.
- **Fixtures:** F0 passed. F1 passed (run k, disclosed caller-reviewer gate); the owner-gated
  original, run j `831f33f4…`, awaits the owner's decision. F3 partial. F4 partial. F2 deferred.

## 4. Source identity

- Final source commit `6fcb4f82e7bd9b4276ed8938d102f71f0802ee16`. Reconciliation merge
  `de792e8b99ab1d0a6cb83a49cfdd1a541f792890` (ours strategy, tree unchanged). This summary is
  committed on top.
- Overlay `cursor_bridge_recovery.py`: SHA256 `5280d379279cfddc…` as reviewed, committed as
  `57b91dd8`. The pre-commit formatter later collapsed one wrapped line, with no semantic change.
- Wheel, rebuilt and not installed: `mission_control-0.1.0-py3-none-any.whl`, SHA256
  `c0cd2300abfe4722127274aae4cb5599c493d290b78d108200a1525664d615fc`, 2,754,836 bytes, built
  by `uv build --wheel` at `6fcb4f82`. It is under the private `p8/wheel/`.
- Commits by phase:

| Commit | Phase | Files |
| --- | --- | --- |
| `af2d24fc` | P0 packet + ledger | 18 |
| `c49862bf` | P1 installation config source | 12 |
| `bb2388b1`, `b9588f44` | D5 seed bundle; frozen bundle + status | 7, 2 |
| `2523c007` | F0 / LS-07 record | 1 |
| `ac9d5e7e` | P5a plugin members pinned once on provider lanes | 2 |
| `aeeda4a4` | P5b applied inject no longer settles the attempt | 5 |
| `c7f79b50` | P5c real lease-relative output/input paths in session packets | 6 |
| `5149bcbb` | P5d set-order independent family mutation fingerprint | 4 |
| `57b91dd8` | reviewed clean-code overlay | 1 |
| `2e659579` | owner's multi-agent TODO preserved | 1 |
| `eb36f3f6` | P7 records, F5 index, planning evidence | 21 |
| `6fcb4f82` | P8 hash-seed-independent P5d test | 1 |
| `970de73b` | canonical draft state preserved on `mo/run2-integration` | 72 |
| `de792e8b` | ours merge into `main` | 0 |

## 5. Checks

All checks ran serially, in the foreground, through the memory guard. Logs are in the private
`p8/final-checks/`. Each one ran at `eb36f3f6`, whose source equals `6fcb4f82` except for one
test file. That file was rerun at `6fcb4f82`.

| Check | Result |
| --- | --- |
| `uv lock --check` | passed |
| `ruff check .` | passed |
| `ruff format --check .` | passed (1889 files) |
| `mypy` (authoritative) | passed (822 source files) |
| `ty check` | passed (exit 0, 11 non-blocking diagnostics) |
| `deptry src` | passed |
| `pytest tests/architecture` | passed (12) |
| `pytest tests/conformance` | passed (149) |
| `scripts/manifest_schemas.py --check` | passed |
| `scripts/seeds_validate.py` | passed (176 definitions) |
| `scripts/skills_manifest.py --check` | passed |
| seed generator `--check` | passed at `b9588f44` (D5) |
| `pytest tests/unit` (per directory) | First pass: 5,174 passed, 38 failed. P8 found and fixed 2 hash-seed-flaky P5d tests: `run_control` 177 passed at `6fcb4f82`, and 12 fixed seeds passed. That leaves 36 failures. 6 predate the close-out: 2 digest-guard tests and 4 `test_cursor_local` closing-facts tests. Each also fails on the pre-close-out baseline `1d081297`, which fails 5 more digest-guard tests. 30 failures are environment-only: 22 deploy-script tests need PowerShell 7, and 8 schema tests need the Biotech SDL in the BellLabs layout, which this out-of-tree checkout lacks |
| `pytest tests/integration` | unrun (needs compose services). The D5 Postgres proofs ran on a disposable PG17 |
| `docs/tools/agents_docs_index.py --check`, `check_links.py`, `validate_okf.py` | passed at the summary commit (see the ledger's P8 entry) |
| pre-commit hooks on every commit | passed (no `--no-verify`) |

## 6. Worktree reconciliation

The draft-resolution method is in the private `p8/draft-resolution.md`. The classification is
in `p8/worktree-classification.md`.

| Worktree | Branch | Result |
| --- | --- | --- |
| canonical `platform/mission-control` | `mo/run2-integration` | 72 dirty paths: 65 identical to `main`, 2 main-newer (`lane_turns.py`, `programs/service.py`), 3 obsolete run notes, `docs/knowledge/index.md` kept from `main`, and 1 adopted (the owner TODO, `2e659579`). Committed as `970de73b`, merged ours. The branch is fully merged. **Pending:** switch the folder to `main` and delete the branch, once MAIN is removed |
| `run2-final-main` (MAIN) | `main` | Integration checkout. Its `.workspaces` was moved to WSL `~/mc-close-retained/main-workspaces`. **Not yet removed:** another live session (started about 13:01 local) is writing an untracked `docs/specs/provider-consolidation-2026-10/` draft in this checkout. Removing it would need `--force` and would lose that work |
| `run2-completion-offline` | `mo/run2-completion-offline-20261016` | **Retained**. Its drafts are identical, main-newer or obsolete |
| `run2-cli`, `run2-cursor`, `run2-events` | `mo/run2-{cli,cursor,events}` | Drafts are pre-integration copies of `e3999d85`, later hardened. All superseded or obsolete. Dirty files copied to retained evidence (378 / 29 / 20). Removed; branches deleted (each an ancestor of `main`) |
| `run2-claude-host-proof` | `mo/run2-claude-host-proof` | Clean; 1 ignored path moved to retained evidence. Removed; branch deleted |
| `run2-cursor-c9` | `mo/run2-cursor-c9` | Clean; evidence retained. Removed; branch deleted |
| `run2-admission-failure`, `run2-closed-workflow-recovery`, `run2-human-control-budget` | same names | One tooling-only dirty file each, no source. Removed; branches deleted |
| `run2-completion-replay-fix` | `mo/run2-completion-replay-fix-20261017` | Clean, ancestor of `main`. Removed; branch deleted |
| close-out leases `run2-close-{p1,d5,p5a,p5b,p5c,p5d}` | lease branches | Applied byte-identical to `main` after review. Removed |

Evidence was moved to `C:/Users/Pinda/Documents/Codex/2026-10-16/task/retained-worktree-evidence/`,
under `run2-cli/`, `run2-cursor/`, `run2-events/`, `run2-claude-host-proof/` and `run2-cursor-c9/`.

## 7. Spend

| Category / slice | Actual | Disposition |
| --- | --- | --- |
| Anthropic API, local claude_agent_sdk (S0 slice), runs a–k: about 13 short `claude-sonnet-5-5` sessions | not attributable in-session | **unknown**. Every run projection reports usage `unknown`. A planning reservation of 5 USD is still held until the owner reconciles the dashboard |
| Cursor (LS-07) | 0 inference frames observed | unknown, believed nil (both attempts stopped before any frame) |
| Cursor stale LS hold | — | **released** under D4 (10 USD) |
| OpenAI / Codex | none | no Codex inference this session |
| Temporal Cloud | none | not used |
| Database (D5 apply) | none | — |

## 8. Open streams carried forward

| Stream | Gate that blocks it |
| --- | --- |
| R, S1, S2, S3 | D1: carried to the next program |
| S4 (HL-01/02/03/10/14/15/16/20) | funding hold |
| 13 deferred issues | owner deferral (Gate L disposition) |
| F2 | D6 owner deferral |
| AF-FOLLOWON-01 | carried as recorded in the Gate L disposition |
| S0-01 promotion | an inject applied on the completing run, plus attributable usage |
| S0-03/06/07/09, LS-07 Cursor, LS-08 Cursor half | host commit headroom: cursor-agent commits about 3.6 GB. Needs a larger host or WSL-hosted Cursor |
| S0-02/04/05/08 | Codex lane prerequisites/attestation and a Codex caller session |
| S0-10..18 | Temporal Cloud namespace `mission-control-dev.ih0e7`: search attributes, API key and worker re-point |
| F1 run j `831f33f4…` | owner review at `owner_gate` (reviewer `Pinda`) |
| Run `ec193a1e…` parked `cancelling` | privileged `reconcile_unit` (the launcher grant lacks it) |
| F3 negatives, F4 accounting | a further fixture slice |
| Findings | Each of these is a separate defect to fix: a pre-create secret refusal is classified `in_doubt`; `missionctl wait` does not refresh tokens; a second `review_required` does not wake a fresh wait; an undecided approval auto-denies at 300 s and cancels the turn; a reused lease keeps the prior `outputs/`; a queued inject for a finished node is neither applied nor refused; the P5b residual timeout window; P5c multi-output and Goal Loop output-contract gaps; config values are not delivered to a lane's runtime environment; provider-permission reviewers default to `owner`; the latent frozenset dump at `programs/service.py:530`; the first HTTP call after idle fails client-side (WSL forwarding) |
| Pre-existing unit failures | the digest-guard audit list and the `test_cursor_local` closing-facts expectation (section 5) |
| Owner TODO | multi-agent on code missions (`anthropic_managed/harness.py`, R33 refusal) |

## 9. Private evidence locations

These directories are outside the repository. Contents are not reproduced here.
- `C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-close-20261018/`, with subdirectories
  `p0/`, `p1/`, `p2/` (`live/`, `f0/`), `p5d/`, `ls/`, `g1/` (serving tooling, `config/`,
  `s0-01*/` receipts), `resources/` (memory guard), `p8/` (classification, retirement record,
  `final-checks/`, `wheel/`) and `private/` (0600 tokens).
- `C:/Users/Pinda/Documents/Codex/2026-10-16/task/retained-worktree-evidence/`.
- WSL: `~/mc-close-logs`, `~/mc-close-attest`, `~/mc-close-workspaces`,
  `~/mc-close-retained/main-workspaces`.

## 10. What the next program should read first

1. This summary, then [RUN-2-CLOSE-STATUS.md](RUN-2-CLOSE-STATUS.md): the stock-take,
   P5 outcome and P7 sections.
2. [RUN-2-F5-PROOF-INDEX.md](RUN-2-F5-PROOF-INDEX.md) and `FINAL-CAPABILITY-S0-18-CELLS.json`,
   for the exact per-cell gates.
3. [RUN-2-FUNDAMENTAL-CAPABILITIES-HANDOFF-2026-10-18.md](RUN-2-FUNDAMENTAL-CAPABILITIES-HANDOFF-2026-10-18.md)
   and the [Gate L disposition](RUN-2-GATE-L-DISPOSITION-2026-10-18.md).
4. Before any live cell: the host resource limits (15 GB RAM; cursor-agent about 3.6 GB commit)
   and the private `run2-close-20261018/g1/restart_g1.py` serving procedure.

## Finish (2026-10-20)

Lead: Claude Code on `claude-opus-5-5`. Authority: the
[finish instructions](../RUN-2-FINISH-INSTRUCTIONS-2026-10-19.md) (owner decisions E1–E11). The
owner was present for W1 and W2, then pre-approved the lead's decisions and concessions for the
rest. Detail is in [the ledger](RUN-2-CLOSE-STATUS.md) under "Finish"; outcomes are in the
[finish disposition](RUN-2-FINISH-DISPOSITION-2026-10.md).

### 1. Outcome

Run 2 is finished: every finish-line item is met or recorded with its exact blocker.
- **Passed:** MR-01 (claude_agent_sdk, local), MR-02 (codex, local), MR-11 (claude_agent_sdk,
  Temporal Cloud) and MR-12 (codex, Temporal Cloud). Each mission carried its lane's own
  configuration and was compiled and preflighted. It materialized in the provider's real
  harness and ran diagnose → patch → review → harness-reviewed gate to terminal `completed`. It
  was observed through Mission Control: wait before start, wake and acknowledgement, peeks while
  active. Each local cell also has a clean immediate cancel with no native process left, and
  every cell has the hygiene receipts.
- **Blocked:** MR-03 (cursor_local), after its one E2 attempt. The cause is a lane defect: the
  Cursor SDK `observe_run` was rejected while the native agent ran on unobserved. Memory was not
  the cause: the bridge peaked at 199 MB. **MR-13** was not run, because it needs MR-03.
- **LS-08** substitute demo met (E5). The router launched a Codex fix and a Claude review in the
  background from this Claude Code session, and the session was woken and read both results.
- Records reconciled: all 21 Gate L issues have an outcome. Checks passed with only the known
  failures, and the wheel was rebuilt. Worktree reconciliation is in section 6.

No push, no deployment, no S4. No source code changed in the finish.

### 2. Decisions applied

| ID | Applied |
| --- | --- |
| E1 | The harness is the only caller. The 18 S0 cells are marked superseded and the MR matrix recorded |
| E2 | Cursor got exactly one attempt; it was recorded blocked and moved to the Cursor sprint |
| E3 | Both locally passed lanes were rerun on `mission-control-dev.ih0e7` |
| E4 | Run j was cancelled (terminal `cancelled`); `ec193a1e` is left `cancelling` |
| E5 | LS-08 was substituted and LS-07 split |
| E6 | Controls, recovery and usage were observed only, never blocked on |
| E7 | No code changes: no blocking defect was small and local |
| E8 | Unknown usage did not block a cell |
| E9 | The operator ES256 key is in the local JWKS; every finish token came from `missionctl token mint` |
| E10 | Codex used the API key only |
| E11 | The consolidation draft was untouched |

Lead concessions, each disclosed in the ledger:
- MR manifests derived from f1k with fresh keys, a disallowed-family probe and explicit test
  paths;
- Codex `network: none` and a 3M-token budget;
- "work alone" (no sub-agents) for Codex and Cursor;
- for MR-12, the harness reviewer accepted the reports, not the code, after a `changes_required`
  review;
- runner calls to preflight, submit and start with a 240 s HTTP timeout on Cloud;
- the four other Claude Code sessions were stopped at the owner's direction.

### 3. Acceptance delta

- **Issues** (appendix, recounted from the records): eight changed to `fully done` by receipt.
  - LS-05, LS-08, MO-08, MO-67, MO-68, MO-70, MO-71, MO-72 are closed by receipt.
  - LS-07 is split. MO-07 is recorded with its remaining clauses.
  - CM-01/02/04/05/07/10, MO-03, MO-73, MO-63, MO-64 and MO-69 are moved by E-decision.

  | Count | Before | After |
  | --- | --- | --- |
  | fully done | 37 | 45 |
  | implemented but unqualified | 42 | 38 |
  | blocked | 18 | 14 |
  | genuinely not started | 12 | 12 |
  | active development | 1 | 1 |

  The stored before-counts were off by one, which is recorded.
- **MR cells:** MR-01, MR-02, MR-11 and MR-12 passed. MR-03 is blocked. MR-13 was not run.
- **Fixtures:** F0 and F1 passed. F3 and F4 close partial, with the remainder moved to provider
  sprints C01, C07 and C08 and the usage work. F2 stays deferred.
- **Findings recorded, not fixed (E7):**
  - Codex allowlist egress is `advisory`: `curl` to a non-allowlisted host succeeded until the
    mission declared `network: none`.
  - Codex sub-agent threads park a unit `in_doubt`.
  - Codex usage settles, so mission token budgets bind. Claude and Cursor usage stays `unknown`.
  - The CLI's fixed 30 s HTTP timeout is too short for preflight on Cloud.
  - A cancelled unit's lease is retained.
  - Cursor `observe_run` is rejected.
  - The LS fixture's `verify_readonly.py` fails on CRLF checkouts.

### 4. Source identity

`main` at `f71d3d11` plus the finish documentation commit(s); source is unchanged since
`6fcb4f82`. The wheel `mission_control-0.1.0-py3-none-any.whl`, sha256
`c0cd2300abfe4722127274aae4cb5599c493d290b78d108200a1525664d615fc`, is byte-identical to P8's
and was not installed (private `w6/wheel/`). The finish commits documentation only: ledger,
summary, disposition, F5 index, the two capability JSON records, the WSL2 runbook, the operator
guide and README, and the docs index.

### 5. Checks

All guarded and serial (private `w6/final-checks/`). Unit failures are the same 36 as P8.

| Check | Result |
| --- | --- |
| lock | passed |
| `ruff check` | passed |
| `ruff format --check` | passed (1889 files) |
| deptry | passed |
| mypy | passed (822 files) |
| ty | exit 0 |
| architecture | 12 passed |
| conformance | 149 passed |
| schemas, seeds, skills | passed (176 seed definitions) |
| docs index, links, OKF | passed (448 files / 0 broken; 45 concepts) |
| unit, 44 directories | 5,176 passed / 36 failed: 6 pre-existing, 30 environment-only, identical to P8 |
| integration | unrun |

### 6. Worktree reconciliation

Done after the documentation commit `152a3dcb`, as follows:
1. MAIN status was clean, including untracked files. The provider-consolidation draft had no
   uncommitted changes.
2. The G1 API and worker were stopped by exact match. No serve, exec or native process
   referenced MAIN.
3. MAIN's `.venv` junction was unlinked with `cmd /c rmdir`; the canonical `.venv` is intact.
   Then `git worktree remove` of MAIN ran **without `--force`**. Its ignored content was caches
   only.
4. In `platform/mission-control`: `git checkout main`, then `git branch -d mo/run2-integration`
   (it was `970de73b`, merged).

Verified: the worktree list is canonical (`main` at `152a3dcb`) plus the retained offline
worktree (`mo/run2-completion-offline-20261016`); `git branch --no-merged main` is empty; status
is clean; `git fsck --no-dangling` passes. The canonical folder is now the live checkout on
`main`. This reconciliation note is committed from it.

### 7. Spend

| Provider | Spend |
| --- | --- |
| Anthropic | About 1.0 USD (native-reported 0.41 + 0.41 + 0.14, plus one short cancelled session) |
| OpenAI `gpt-6-luna` | 779k uncached input, 8.31M cached input and 115k output tokens, plus the LS-08 Codex job (137,522 tokens). No in-session cost; **estimate 3–11 USD** |
| Cursor | One attempt; usage unknown |
| Temporal Cloud | Negligible |

Everything is within the 10 USD lane, 10 USD Cloud and 5 USD LS caps on the upper estimate per
slice: W2 at most 8, W4 at most 3.5, W5 under 0.5. The owner should reconcile the OpenAI
dashboard for the actual figure.

### 8. Open streams carried forward

| Destination | Items |
| --- | --- |
| Cursor provider sprint | MR-03/MR-13 (`observe_run` rejection, unsettled reservation on run `7132d2de`); CM-01/02/04/05/07/10; LS-07 Cursor items; Cursor skill discovery |
| Codex sprint | MO-03; sub-agent usage provenance (run `eaa586c3`, `in_doubt`); allowlist egress enforcement |
| Consolidation recovery and state | `ec193a1e` (`cancelling`), `eaa586c3`, `7132d2de`; MO-73; retained leases of cancelled units |
| Consolidation Sprint 0 | MO-69; MO-07 remaining clauses; the CLI 30 s timeout; the 6 pre-existing unit failures; the LS fixture CRLF hash; the latent frozenset dump |
| Stream R | MO-63, MO-64 |
| Other carried items | K01, K12, K13, K16; P5c gaps; config values not delivered to the runtime. R, S1, S2, S3 and funding-held S4 carry forward as before; F2 stays deferred |

### 9. Private evidence locations

Outside the repository; contents not reproduced.
- `C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-close-20261018/`:
  - `w1/` to `w6/`: MR receipts, runner directories, sentinel and child-environment captures,
    memory watch, final checks, wheel;
  - `g1/`: generalized tooling, attestors, runner, policy, and config with local/Cloud sets;
  - `ls/`: LS-08 jobs and fixture artifacts;
  - `private/`: operator key, tokens.
- WSL: `~/mc-close-attest/{claude,codex,cursor}` (native observations), `~/mc-close-logs`, and
  `~/mc-leases` (retained leases of parked and cancelled units).
- The G1 WSL venv `~/.venvs/mc-run2-close` was an editable install of MAIN. Reinstall it from
  the canonical checkout before serving again.

### 10. What the next program should read first

1. This section, then the [finish disposition](RUN-2-FINISH-DISPOSITION-2026-10.md) and the
   ledger's "Finish" W1–W6.
2. [WSL2 worker runbook](../../../../WSL2_WORKER_RUNBOOK.md), for the per-lane owner prerequisites
   (A8, X4/X6, C9, M4) and their attestation, Cloud re-pointing and memory.
3. The provider-consolidation [README](../../../provider-consolidation-2026-10/README.md) and
   [baseline](../../provider-consolidation-2026-10/docs/BASELINE-2026-10-19.md) (owner draft), with
   section 8 above as its intake.

Added 2026-10-20 after the finish: every open item from this summary, the ledger and the Gate L
disposition is consolidated in the [Run 2 carry-forward register](../../../provider-consolidation-2026-10/RUN-2-CARRY-FORWARD.md),
grouped by destination sprint. The retained offline worktree was removed on the same day: its
content was already on `main`, and its ignored evidence was moved to
`.scratch/archive/run2-completion-offline-worktree/`.
