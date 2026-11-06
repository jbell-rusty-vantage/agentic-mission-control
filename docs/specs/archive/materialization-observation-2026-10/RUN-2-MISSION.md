---
type: Agent Mission Brief
title: "Complete the mission: close Mission Control Run 2 at Gate L with a Claude Code Opus 5.5 lead"
description: "Attach this file to a Claude Code session on claude-opus-5-5 and say 'Complete the mission'. It names the goal, the reading order, the recorded owner decisions, the team shape, the non-negotiables and the definition of done. The owner is away for the whole run."
---

# Complete the mission — Run 2 close-out

You are the lead of a Claude Code session on **claude-opus-5-5**. Confirm your
model in your first message; if it is anything else, stop. The owner is away for
many hours: **nothing may wait on the owner.** Every decision you need has been
recorded; anything not recorded is written down as blocked and you move on.

## The goal in one paragraph

Close the materialization/observation Run 2 sprint at **Gate L**: implement the one
known source gap (installation configuration source for `value_ref: config:<key>`),
prove the fundamental configured workflow locally (fixtures F0, F1, F3, F4 from the
2026-10-18 handoff), finish SPEC-08's LS-07 cells and LS-08 end-to-end, run all
**18 S0 cells** (three Windows callers × three local lanes × local and Cloud
Temporal), update the acceptance records from receipts only, reconcile **every
worktree into `main`** with conflicts resolved and the canonical folder checked out
on `main`, and write the completion summary. Slices R, S1, S2, S3 and funding-held
S4 carry forward as explicit open streams; fixture F2 is deferred. No push, no
deployment, no S4 release.

## Read in this order (all paths relative to this packet folder)

1. `RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md` — recorded decisions (section 1), the Claude Code operating contract (3), per-phase procedures (4), the worktree merge procedure (5), the completion summary contract (6), agent briefs (8).
2. `RUN-2-EXECUTION-SEQUENCE-2026-10-18.md` — verified frontier and the phase order with exit evidence.
3. `runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md` — which of the 110 issues close in Run 2 and which carry forward.
4. `runs/RUN-2-FUNDAMENTAL-CAPABILITIES-HANDOFF-2026-10-18.md` — sections 1, 5, 7, 8, 12 (F0–F5 proof procedures) and the eleven SPEC checklists.
5. `RUN-2-AGENT-TEAM-HANDOFF-2026-10-17.md` — roots, dependencies, budgets, read-only startup commands; its section 6 is historical.
6. Repository `AGENTS.md`, `docs/AGENTS.md` and the scoped `AGENTS.md` nearest each file you touch; the SPEC file for each criterion you prove (each SPEC now opens with a one-line Gate L disposition; the criteria text is unchanged).

## Decisions already taken (do not re-ask)

Gate L boundary (D1). Claude Code Opus 5.5 implementer (D2). Native local-lane
fixtures authorized within the fresh ceilings and 10 USD slice caps, one bounded
job at a time (D3). Stale 10 USD Cursor LS hold released on the recorded dashboard
evidence (D4). Report-schema seed release approved end to end **including live
apply to AI Engineer**, strictly under the listed conditions: catalog shows absence,
additive new slot, disposable fresh/upgrade/repeat/drift/refusal/role proofs pass,
dry-run diff and backup record written first, idempotent apply with readback (D5).
F2 deferred (D6). Local commits and local `main` merges authorized (D7). Implement
the config source directly in P1 and make F1 the review of that diff.

**Authentication.** Nobody will be present to log in. Claude Code and Codex are
already authenticated on this machine. The canonical folder's git-ignored `.env`
(`C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control/.env`; MAIN has none)
holds `CURSOR_API_KEY`, `CURSOR_EMAIL`, `CURSOR_PASSWORD`, `ANTHROPIC_API_KEY` and
`OPENAI_API_KEY`. Read names, never print or copy values; pass them only into owned
child processes through the existing bootstrap or broker paths. Prefer the Cursor
API-key route. **If any authentication fails or needs a browser, code or human,
record the deficiency (surface, error class, affected criteria), mark those cells
blocked, and move on.** No login loops, no credential edits.

## Team shape: lower-bound projection, and why

**One Opus 5.5 lead session plus short-lived subagents, never more than two alive
at once.** Projected subagent invocations for the whole close-out: **six to eleven**.

| When | Subagent | Count |
| --- | --- | --- |
| P1 config source | one implementer in an isolated worktree, then one fresh reviewer | 2 |
| P2 schema seed release (only if the catalog lacks report schemas) | one implementer, one reviewer | 0–2 |
| P4 Cursor missing-result receipt boundary integration | one implementer, one reviewer | 2 |
| P8 worktree reconciliation (`run2-cli`, `run2-cursor`, `run2-events` unique hunks) | one reviewer per unique patch set | 0–3 |
| P8 final integrated review | one reviewer | 1 |
| Any phase, read-only code location, evidence assembly, P7 tables, P8 file classification | Sonnet 5.5 `general-purpose` or `Explore` agents at the lead's discretion | 0–6 |

Everything else is lead work: G1 serving, every native run (you are the Claude Code
caller), the Codex and Cursor headless callers, evidence files, status file, merges,
summary. The critical path is native runs under a single heavy lease; extra agents
cannot shorten it and only add memory pressure and integration conflicts.

Rules for spawning:

- Permitted subagent models: **Opus 5.5** (no `model` override) and **Sonnet 5.5** (`model: "sonnet"`). Be efficient: Opus for agents that write or review source, SQL, seeds, release files, manifests or merge resolutions; Sonnet for exploration, evidence-file assembly, receipt and log parsing, documentation tables, three-way file classification and running bounded test commands. Never Haiku. Name the model in each deliverable.
- Implementers get `isolation: "worktree"` and the brief in the instructions file, section 8. Reviewers are **fresh** agents given the diff path and criteria; never `fork` a reviewer.
- At most one implementer running; a reviewer may run only while no implementer runs. One heavy test/native/build job at a time, as a background shell task you wait on.
- **Do not use the `Workflow` tool** and do not fan out. This host has about 15 GB RAM; on 2026-10-13 more than ten concurrent agents running pytest crashed Claude Code twice, and messaging agents inside a workflow spawned duplicate writers in one worktree. Nothing here is parallelizable enough to justify that risk.
- If a subagent fails review twice on the same lease, do the change yourself in the lead session rather than spawning a third.

## Non-negotiables

- Never touch any consumed fence, recovery registry, initializer, closure host or terminal SQL. A1 is complete.
- Never rerun the Cursor login, raise the Cursor on-demand limit, repeat a paid failure to resolve ambiguity, or spend past a slice or category remainder including a credible overshoot.
- Never promote an issue, SPEC or S0 cell from a diagnostic, an API GET or a provider "done"; only from the receipt that satisfies the exact clause.
- Never delete tests to pass, reset/clean/stash any worktree, force-checkout, or remove the offline evidence worktree. Unlink MAIN's `.venv` junction before removing the MAIN worktree.
- Never write secrets, tokens, DSNs, passwords or raw provider payloads into the repository, a brief, the status file or the summary; never print the `.env`.
- Never loop on a failed login or wait for a human to authenticate; document the deficiency and continue.
- Keep one in-place status file (`runs/RUN-2-CLOSE-STATUS.md`); no new dated report per attempt.

## Definition of done

1. P1–P8 of the instructions file executed; each phase's exit report appended to the status file with evidence hashes.
2. `runs/FINAL-CAPABILITY-S0-18-CELLS.json` and the issue appendix updated from receipts; the F5 index written; every unmet criterion recorded as failed, blocked or unrun with its exact gate.
3. Final checks (Ruff, authoritative mypy, ty, deptry, architecture, schema/seed/skills, docs index/link/OKF) passed at the final `main` commit; the wheel rebuilt and identified, not deployed.
4. Every branch an ancestor of `main`; every worktree's uncommitted bytes classified and integrated or recorded; side worktrees and the MAIN worktree removed after zero unique bytes; the canonical folder `C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control` on `main` with a clean status; only `run2-completion-offline` retained.
5. `runs/RUN-2-COMPLETION-SUMMARY-2026-10.md` committed on `main` and sent as your final message, with the ten sections the instructions file requires.

## Your first message

Report: actual model; MAIN HEAD, dirty set and overlay hash; worktree count;
dependency availability; the Gate L counts from the disposition file; the P1 lease
you are about to take. Then proceed without pausing for a reply.
