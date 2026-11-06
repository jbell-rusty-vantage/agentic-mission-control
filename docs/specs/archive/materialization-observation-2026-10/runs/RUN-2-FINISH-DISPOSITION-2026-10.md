---
type: Sprint Disposition
title: "Run 2 finish disposition (2026-10-20)"
description: "Section 5 of the Run 2 finish instructions with its results: the outcome of each of the 21 Gate L issues (closed by receipt, recorded with an exact blocker, or moved by an E-decision), the materialize-and-run matrix, the fixtures and the issue-status delta."
---

# Run 2 finish disposition

Authority: [finish instructions](../RUN-2-FINISH-INSTRUCTIONS-2026-10-19.md), sections 3 and 5
(owner decisions E1 to E11). The evidence is in the [status ledger](RUN-2-CLOSE-STATUS.md),
section "Finish" (W1 to W6). Machine-readable records:
[S0 cells](FINAL-CAPABILITY-S0-18-CELLS.json) (`finish_2026_10`) and the
[issue appendix](FINAL-CAPABILITY-ISSUE-ACCEPTANCE-APPENDIX.json) (`finish_2026_10` on each Gate L
issue). An issue status changed only where a finish receipt satisfies the clause, as reframed by
E1, E3 and E5. `issues.json` was not edited.

## Materialize-and-run matrix (section 3.2)

| Cell | Lane | Scheduler | Result | Run (cancel run) |
| --- | --- | --- | --- | --- |
| MR-01 | claude_agent_sdk | local Temporal | **passed** | `e7d24a4b…` (`cc6d5594…`) |
| MR-02 | codex | local Temporal | **passed** | `a901422d…` (`235fcc73…`) |
| MR-03 | cursor_local | local Temporal (WSL worker) | **blocked** (one attempt, E2) | `7132d2de…` |
| MR-11 | claude_agent_sdk | Temporal Cloud | **passed** | `37ce4f20…` |
| MR-12 | codex | Temporal Cloud | **passed** | `60cca228…` |
| MR-13 | cursor_local | Temporal Cloud | not run (MR-03 blocked) | — |

MR-03's blocker is a lane defect. The Cursor SDK `observe_run` raised a configuration error
6 s into the first turn, so the operation failed with `lane_turn_rejected` while the native agent
ran on unobserved. The run is parked `cancelling` on an unsettled usage reservation. Memory was
not the blocker: the bridge peaked at 199 MB RSS, and WSL availability never fell below 3,344 MB.

## Gate L issues (section 5) and results

| Issue | Disposition | Result |
| --- | --- | --- |
| MO-72 S0 end to end | Finish, reframed (E1) | **Closed by receipt.** MR-01 and MR-02 passed. MR-03 had its one attempt and is blocked, moved to the Cursor sprint (E2) |
| MO-71 S0 probe manifests | Finish | **Closed by receipt.** The three MR manifests compile with 0 blockers (MR-03's included) |
| MO-67 Temporal Cloud qualification | Finish, reframed (E3) | **Closed by receipt.** MR-11 and MR-12 passed on `mission-control-dev.ih0e7`; search-attribute plan additions `{}` |
| MO-68 preflight local deployments root | Finish if a G1 receipt shows it | **Closed by receipt.** G1 preflight was ready with a local deployments root outside version control |
| MO-70 missionctl token mint helper | Finish (E9) | **Closed by receipt.** Operator ES256 key in G1's local JWKS; every W1–W5 launcher token was minted by `missionctl token mint` |
| MO-08 WSL2 worker runbook and host preflight | Finish | **Closed by receipt.** [WSL2 worker runbook](../../../../WSL2_WORKER_RUNBOOK.md); host preflight verified on the WSL2 worker: A8/M4, X4/X6/M4, C9/M4 |
| LS-05 router and per-CLI skills | Finish | **Closed by receipt** for Claude and Codex (W5). Cursor discovery moves with LS-07's Cursor items (E5) |
| LS-08 delegation demo | Finish, substituted (E5) | **Closed by receipt.** Codex fix plus Claude review launched in the background from Claude Code; the session was woken and read both results. The review's verify failed on a CRLF fixture hash (disclosed; nothing edited) |
| LS-07 CLI live smoke | Split (E5) | **Split.** The Claude and Codex items are answered by the W5 receipts and doctor outputs. The Cursor CLI items move to the Cursor sprint |
| MO-07 stale documentation | Finish | **Recorded with blocker.** The operator guide now documents `MISSION_CONTROL_INSTALLATION_CONFIG_PATH`; runbook added; OKF, links and index pass. The remaining clauses move to consolidation Sprint 0: hosted Agents API vs SDK wording, CM-10 closure wording, the managed budget-pause disposition, and the active kickoff |
| CM-01, CM-02, CM-04, CM-05, CM-07, CM-10 | Move | **Moved** to the Cursor provider sprint. New evidence for it: the SDK bridge fits this host; `observe_run` is rejected |
| MO-03 Codex hooks and hook trust | Move | **Moved** to the Codex sprint. No hook evidence was examined in MR-02 |
| MO-73 Claude SessionStore restore | Move | **Moved** to provider consolidation (state/recovery) |
| MO-63 lane-only worker, MO-64 split-host custody | Move | **Moved** to stream R |
| MO-69 binding digest tool | Move | **Moved** to consolidation Sprint 0 tooling |

Issue status delta (appendix, recounted from the records): 8 issues moved to `fully done`.

| Issue | Before |
| --- | --- |
| LS-05, MO-08, MO-68, MO-70 | `implemented but unqualified` |
| LS-08, MO-67, MO-71, MO-72 | `blocked` |

| Count | Before (recount) | After |
| --- | --- | --- |
| fully done | 37 | 45 |
| implemented but unqualified | 42 | 38 |
| blocked | 18 | 14 |
| genuinely not started | 12 | 12 |
| active development | 1 | 1 |

The stored before-counts (38 / 41) differed by one from a recount of the records at `HEAD`; this
is recorded in the appendix.

## Fixtures

- F0 and F1 passed, as recorded on 2026-10-19.
- F3 and F4 close **partial**, with their remainders moved:
  - F3 negative composition controls go to each provider sprint's C01.
  - F4 controls and accounting go to C07, C08 and the usage work.
- F2 stays deferred (D6).

## Runs left for the consolidation program

| Run | State | Why |
| --- | --- | --- |
| `ec193a1e-9e4f-574f-992d-a6ad16733ff2` | `cancelling` | Pre-create secret refusal classified `in_doubt`; needs privileged `reconcile_unit` (E4) |
| `eaa586c3-2fe5-5108-ab51-2de0fab19b1c` | active, unit `in_doubt` | Codex review stage spawned 2 sub-agent threads without usage provenance (`codex_usage_requires_reconciliation`) |
| `7132d2de-88f2-5c20-9b57-58a183dd6424` | `cancelling` | Cursor operation failed (`observe_run` rejected); usage reservation unsettled |

Run j `831f33f4…` was cancelled as superseded by run k (E4) and is terminal `cancelled`.
