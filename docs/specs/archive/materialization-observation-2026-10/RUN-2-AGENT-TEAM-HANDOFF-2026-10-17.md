---
type: Agent Session Handoff
title: "Mission Control Run 2: complete the current sprint with a GPT-6.1 Sol or Claude Opus 5.5 team"
description: "Standalone startup instructions, current acceptance map, protected residual recovery (now complete), exact local dependencies, inclusive budgets and completion gates; implementer-neutral since 2026-10-18."
---

# Mission Control Run 2 — fresh agent-team handoff

Prepared **2026-10-17 UTC** for a new user-created session on Pinda's Windows
machine. This is the requested single new canonical handoff, not a commit or a
retry of the rejected multi-document publication. It is an instruction and
evidence map, not a portable archive, credential, billing balance or permission
to override the host's approval policy. A fresh agent does not need the prior
conversation, but it needs access to the verified local dependencies below.

**Update 2026-10-18 (read first).** Three things changed after this file was written:

1. **Section 6 is historical.** The residual delivery (package A1) completed on
   2026-10-18 at 00:35:07 UTC: root history 33 Completed with the normal typed
   result, family 58 unchanged, independent post-reap observer passed. All four
   terminal/residual/manual fences are consumed. Nothing in section 6 or 7 is to
   be executed; preserve every path it names.
2. **The current continuation entrypoint is the
   [fundamental-capabilities handoff of 2026-10-18](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-FUNDAMENTAL-CAPABILITIES-HANDOFF-2026-10-18.md)**
   in MAIN, ordered for execution by the
   [close-out sequence](RUN-2-EXECUTION-SEQUENCE-2026-10-18.md) beside this file.
   MAIN now has 3 modified and 16 untracked paths, not one and nine; one of the
   modified paths is a reviewed source overlay (`cursor_bridge_recovery.py`).
3. **The team is implementer-neutral.** Wherever this file says "gpt-6.1-sol",
   "Sol" or "Sol-only" about the lead, workers or reviewers, read "the implementer
   selected by the owner: Codex `gpt-6.1-sol` or Claude Code `claude-opus-5-5`".
   The resource rules (lead plus one active worker, one heavy lease, fresh-context
   independent review, no nested delegation, memory floors) apply to both. The
   mapping for each implementer is in the close-out sequence, section 4. Product
   drill models (Sonnet 5.5, gpt-6-luna, Cursor Auto/grok-4.7) are unchanged.

## 1. Start here: task and authority

Complete the **current materialization/observation Run 2 sprint**, using **one
implementer model for the lead, every implementer, reviewer and replacement:
Codex `gpt-6.1-sol` or Claude Code `claude-opus-5-5`, as the owner selects**. The
owner wants substantial forward progress, low resource use, preservation of
concurrent work, and main fully merged/up to date. “Clean” does not mean deleting
other worktrees or discarding dirty files. No push or unrelated deployment is
requested. Broad CLI/MCP/agent-skill refinement and AF-FOLLOWON-01 are later manual
work. Complete only the existing accepted scope and demonstrated remaining gaps.

Use this short user-session prompt if useful. The authorization sentences are
proposed text for the human to send **only if they express the intended scope**;
their presence in this file is not itself a new grant. **Since 2026-10-18 the
residual-delivery sentences in it are spent and must be omitted; prefer the
kickoff text in the close-out sequence, section 6.**

~~~text
Complete the current Mission Control Run 2 sprint following this handoff. I authorize
in-scope implementation/tests/docs, normal local commits and ancestry-preserving
main merges, and exclusive new-report publication that preserves existing files.
Subject to fresh state/source/resource checks and an unused residual fence, I
authorize one bounded residual delivery for run60f44a50-c0e4-5edb-ac13-0fb0436aaedb:
route only its two existing workflows, replay the committed completion read-only,
insert the normal typed result at most once, let family/root finish and verify
cleanup. Do not repeat terminal SQL, call a provider, create a child/operation or
change default routing/shared service as part of that residual action. Renew stale
packet expiry/document pins only after review; never reset a consumed intent.
Use one
implementer model (Codex gpt-6.1-sol or Claude Code claude-opus-5-5) for the lead
and all workers/reviewers, low concurrency, one owned heavy
job at a time, preserving all existing dirty work and running sessions. Establish
the exact current Git/source/runtime state first. Work from the integrated
run2-final-main checkout, not the older canonical branch. Follow retained-result
delivery, prerequisites/cost reconciliation and CLI smokes, G1/S0, applicable
remote/Cursor Cloud joins, Anthropic S2, OpenAI S3, then final source/data/release
and cleanup gates. Preserve the original acceptance and explicitly held scope.
Do not repeat any consumed terminal-closure action, provider attempt or intent.
The terminal cancellation is committed; only the separately bounded residual
typed-result/two-workflow delivery remains. Unknown spend stays unknown. Use the
existing budgets/infrastructure and exact authority available in this new session;
prepare concrete bounded actions and consolidate only genuinely missing owner
decisions. This file does not override an approval rejection. No push, unrelated
deployment, S4 funding release or later manual follow-on is implied.
~~~

**Authority provenance:** earlier human instructions approved current-sprint
implementation, local commits/main integration and ordinary eligible work within
existing budgets/infrastructure, and at19:24 UTC explicitly approved the bounded
residual delivery. These are recorded below. In the prior delegated executor,
automatic approval review nevertheless rejected commit/canonical publication and
the final live dispatch because it did not accept forwarded assistant/tool
transcript evidence as trusted user-authored authorization. Both commands are
stopped. Do not retry them merely because this file quotes the history. Establish
the direct user authority actually available in the new session; ask one precise
consolidated question only where the approval system or changed scope requires
it. Ordinary unchanged work already authorized in that session should proceed.
No document creates a permanent policy/account grant or bypass.

## 2. Exact roots and source of truth

| Name used below | Absolute path / role |
| --- | --- |
| MAIN | `C:\Users\Pinda\Documents\Codex\2026-10-16\task\run2-final-main` — Integrated local main; use this source checkout |
| CANON | `C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control` — Usual repository folder; older branch with preserved dirty work |
| PACK | `C:\Users\Pinda\Documents\Codex\2026-10-16\task\run2-final-main\docs\specs\materialization-observation-2026-10` — Actual current sprint specifications, issues and plans |
| RUNS | `C:\Users\Pinda\Documents\Codex\2026-10-16\task\run2-final-main\docs\specs\materialization-observation-2026-10\runs` — Latest uncommitted reports and dated execution records |
| OFFLINE | `C:\Users\Pinda\Documents\Codex\2026-10-16\task\run2-completion-offline` — Retained assessment checkout and ignored private evidence |
| RECOVERY | `C:\Users\Pinda\Documents\Codex\2026-10-16\task\run2-completion-offline\.scratch\run2-completion-20261017\continuation-v8\recovery` — Frozen operator hosts/proofs; preserve all versions |
| HANDOFFS | `C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control\.scratch\materialization-observation-2026-10\run2\resumed` — Original October16 session-end handoffs and retained evidence |
| LOCAL-EVIDENCE | `C:\Users\Pinda\Documents\Codex\2026-10-16\task\completion-replay-evidence` — Task-local qualification, refusal, review and preservation receipts |

At handoff inspection, MAIN is branch `main` at
`1d081297bde6fd74e9276df45102eef3c0dc746d`, ahead of local origin/main by60 commits.
Its ten pending paths are planning documents: one modified navigation report and
nine untracked reports/evidence files. They are intentional, not scratch to clean.
The two named SPEC reports are physically in MAIN and have **not** been copied to
CANON or committed. A clone/reset/clean/new worktree from HEAD alone can omit them.

CANON is `mo/run2-integration` at
`a8d69c5b48506c6babcd7f3f74f0b92716423091`. The last exact preservation snapshot
had21 modified tracked +46 untracked files; all67 files (1,786,333 bytes, none
omitted), status, branch and HEAD were unchanged between18:24 and19:50 UTC.
This new canonical handoff adds only its own new path. Reinspect live metadata
before acting; another session can legitimately change the tree after this check.

MAIN is a **linked Git worktree**, not a self-contained repository: its `.git`
points into CANON's `.git/worktrees/run2-final-main`. Its `.venv` is a junction to
CANON's `.venv`. Preserve both roots, the common Git metadata and the junction.
Do not remove/recreate the virtualenv or assume its existence proves a test ran.

## 3. Mandatory read order and precedence

Read these exact files, rather than guessing which dated state is latest:

1. **Repository/scoped rules and accepted architecture:** [MAIN AGENTS.md](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/AGENTS.md); [documentation rules](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/AGENTS.md); [accepted general specification](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/mission-control-general/general-mission-control/SPECIFICATION.md); [runtime contracts](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/mission-control-general/general-mission-control/RUNTIME-CONTRACTS.md).
2. **Latest navigation, merge state and check provenance:** [CURRENT-INTEGRATION](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-CURRENT-INTEGRATION-2026-10-17.md); [integration evidence](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-CURRENT-INTEGRATION-EVIDENCE-2026-10-17.json).
3. **Latest execution/approval disposition:** [RESIDUAL-DELIVERY-REVIEW-HOLD](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-RESIDUAL-DELIVERY-REVIEW-HOLD-2026-10-17.md); [hold evidence](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-RESIDUAL-DELIVERY-REVIEW-HOLD-EVIDENCE-2026-10-17.json).
4. **Actual committed cancellation and canonical read-only replay:** [PARTIAL-CLOSURE-DIAGNOSIS](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-PARTIAL-CLOSURE-DIAGNOSIS-2026-10-17.md); [partial-closure evidence](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-PARTIAL-CLOSURE-EVIDENCE-2026-10-17.json).
5. **Current SPEC/issue acceptance and narrow latest correction:** [SPEC-STATUS](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-SPEC-STATUS-2026-10-17.md); [SPEC-ISSUE-APPENDIX](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-SPEC-ISSUE-APPENDIX-2026-10-17.md); [machine acceptance ledger](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-SPEC-STATUS-EVIDENCE-2026-10-17.json); [MO-78 own-acceptance closeout](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-MO78-ACCEPTANCE-2026-10-17.md); [MO-78 evidence](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-MO78-ACCEPTANCE-EVIDENCE-2026-10-17.json).
6. **Prerequisites, cost unknowns, existing authority and finite envelopes:** [PREREQUISITE-CLOSURE](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-PREREQUISITE-CLOSURE-2026-10-17.md); [prerequisite/cost evidence](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-PREREQUISITE-EVIDENCE-2026-10-17.json); [PERMISSIONS-AND-ACTIONS](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-PERMISSIONS-AND-ACTIONS-2026-10-17.md); [QUALIFICATION-ENVELOPES](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-QUALIFICATION-ENVELOPES-2026-10-16.md).
7. **Original completion contract and narrow amendments:** [SPRINT](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/SPRINT.md); [PLANNING-AMENDMENTS](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-PLANNING-AMENDMENTS.md); [DECISIONS](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/DECISIONS.md); [PLAN](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/PLAN.md); [TEAM-WORKSPACE](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/TEAM-WORKSPACE.md); [issues.json](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/issues.json).
8. **Detailed work packages, file leases, test entrypoints and Sol team contracts:** [COMPLETION-PLAN](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-COMPLETION-PLAN-2026-10-16.md); [SOL-EXECUTION](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-SOL-EXECUTION-2026-10-16.md).
9. **Original handoff provenance, after the current state above:** [SESSION-END MISSION-HANDOFF](C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control/.scratch/materialization-observation-2026-10/run2/resumed/SESSION-END-2026-10-16-MISSION-HANDOFF.md); [SESSION-END MULTI-PROVIDER-SURVEY](C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control/.scratch/materialization-observation-2026-10/run2/resumed/SESSION-END-2026-10-16-MULTI-PROVIDER-SURVEY.md).

Then read the exact assigned SPEC and issue Markdown, including original
checkboxes and the Run2 additions, plus the closest source/test AGENTS.md and
applicable local skill. The appendix covers110 unique IDs,103 direct primary
SPEC references +7 deliberately non-SPEC-primary/crosscutting records; do not
invent a SPEC assignment for MO-07. The machine ledger preserves205 effective
current-issue checkbox clauses and source hashes. Prefer its `current_status`
and `current_status_counts`; `audit_status` preserves the older immutable audit.

**Important supersession traps:** the original AGENT-TEAM-KICKOFF instructs an
Astra lead and is obsolete for this Sol-only team. SOL-EXECUTION/COMPLETION-PLAN
retain October16 planning-only and now-completed W1/W2/source statements; their
remaining criteria and file boundaries remain useful, not a reason to redo fixes.
PREREQUISITE-CLOSURE's old P3/final recovery paragraphs predate the committed
terminal cancellation. Use its cost/setup/data sections, but CURRENT + REVIEW-HOLD
+ PARTIAL-CLOSURE control the recovery frontier. A later line number in an old
report is not a newer observation. Do not execute old R2A/R2B plans or packets.

## 4. Current acceptance map and exact scope

The current partition is **38 own-issue done /41 implemented but unqualified /
18 blocked /12 genuinely not started /1 active documentation issue**. No whole
SPEC is fully qualified: seven in progress, four blocked. “Done” means the issue's
own source/fixture acceptance, not an inferred native/provider/release pass.
MO-78 is now done from an actual retained completed no-op and exact setup/docs
join, independently reviewed; SPEC-11, MO-67 and MO-77 remain open.

| Actual SPEC and state | Unfinished current primary issues | Remaining acceptance emphasis |
| --- | --- | --- |
| [SPEC-01: Environment materialization — variables, secrets, runtimes, network, git and provider environments](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/SPEC-01-environments.md) — **in progress** | MO-11, MO-12, MO-13, MO-14 | Section 10 still needs the actual Cursor sync/prepared-signal/unchanged-kit reuse drill, actual prepared local receipts and the required secret-free end-to-end evidence. Delivery, API readback and a prepared/discovered/exercised receipt are distinct. MO-11/12/13/14 remain implemented but unqualified; MO-06 meets its own production-composition fixture acceptance. |
| [SPEC-02: Cognition materialization — skills, subagents, hooks, instructions, MCP and plugins per provider](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/SPEC-02-cognition.md) — **in progress** | MO-03, MO-31, MO-33, MO-34 | Section 2 matching bundle/hook production-composition fixture proof is already delivered by MO-01. Section 9 still requires all-three-local-lane launches preserving repository bytes, actual discovery of repo and mission items, native Codex hook deny with trust, and Cursor inline MCP/rules/materialization.observed signals. Rendered files do not prove discovery or exercise. MO-03/31/33/34 remain implemented but unqualified; MO-01/02 meet their own production-custody and layering fixture acceptance. |
| [SPEC-03: Workspaces, worktrees and parallel placement for SDLC and knowledge missions](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/SPEC-03-workspaces-and-placement.md) — **in progress** | MO-08, MO-51 | Section 7 requires actual three-local-lane isolation/dirty-input refusal/cleanup after custody, five Cursor cloud members with distinct branches/head artifacts throttled at three, and a knowledge mission fetching an input and producing an accepted artifact. MO-05 and MO-51 retain native gaps; CM-10 supplies crosscutting parallel isolation evidence. |
| [SPEC-04: Watchers, signals and callbacks — formal observation from provider environments to the orchestrating agent](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/SPEC-04-watchers-and-callbacks.md) — **in progress** | MO-41, MO-42 | Section 8 original deterministic watcher/replay/limit proof and original real coordinator-wake acceptance are delivered by MO-44 and MO-43. Remaining native evidence is the exact Cursor started/observed/stop signal/transcript join and real one-tool stop in MO-41/42, both implemented/unqualified. The wider current S0 three-caller wake/resume remains separate under MO-72. These completed original issues do not qualify the deployed ingress or every caller/lane cell. |
| [SPEC-05: Owner prerequisites and pre-spawn preflight — what only the owner can do, surfaced before a mission spawns](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/SPEC-05-owner-prerequisites.md) — **in progress** | MO-22 | Section 4 requires generated instructions, verified probes/attestations and expiry returning a lane to blocked, with the same PREREQUISITES_UNMET payload at launch. Current selected Cursor/Anthropic setup and exact probe freshness must be demonstrated; old owner setup is insufficient. |
| [SPEC-06: API-billed hosted lanes — Anthropic Managed Agents, OpenAI Agents API (Codex harness) and Sandbox Host placement](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/SPEC-06-hosted-api-lanes.md) — **blocked** | HL-01, HL-02, HL-03, HL-07, HL-08, HL-09, HL-10, HL-11, HL-12, HL-13, HL-14, HL-15, HL-16, HL-18, HL-20, HL-21, MO-73 | Section 11 requires native cloud knowledge/SDLC missions accepted through the remote path, genuine Managed Agents budget-gate pause/resume and interrupt, OpenAI function-tool approval/cancel/steer and killed-worker item recovery, actual usage/cost/custody, and the full selected projection reruns. Integrated budget wiring and controlled replay do not establish native hold/resume. HL-24 precedes HL-25. The self-hosted/SandboxHost acceptance remains funding-held. |
| [SPEC-07: Cursor lanes to full maturity — lifecycle, control, accounting and portability for cursor_local and cursor_cloud](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/SPEC-07-cursor-maturity.md) — **blocked** | CM-01, CM-02, CM-04, CM-05, CM-07, CM-08, CM-09, CM-10, CM-21 | Sections 1/5 require honest exact-placement native drill records before qualified changes. CM-01/02 still need attributable all-turn usage and actual cost settlement, CM-05 killed-worker reattach, CM-09 immutable output/PR custody and CM-10 parallel isolation. Current Cursor CLI authentication is absent; this alone does not prove an SDK/Cloud denial. |
| [SPEC-08: Local CLI job skills — teaching any agent to drive Claude Code, Codex and Cursor CLIs headlessly, outside Mission Control](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/SPEC-08-local-cli-skills.md) — **blocked** | LS-05, LS-07, LS-08 | Section 9 requires actual authorized cheap CLI smokes and the background Claude caller launching a Codex fix plus Cursor review in parallel, runner-owned verification, wake, and both result files. Supported Codex sandbox non-inference marker/write-denial proof and 15 resource utility tests do not prove paid Codex completion or LS-08. |
| [SPEC-09: Local harness path (slice S0) — Claude Code, Codex and Cursor harnesses through Mission Control on a WSL2 worker with local or Cloud Temporal](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/SPEC-09-local-harness-path.md) — **blocked** | MO-63, MO-64, MO-67, MO-68, MO-69, MO-70, MO-71, MO-72 | Section 9 requires all three local harnesses from all three Windows callers, each real wake/inject/cancel-or-completion/custody/cleanup, then the same three-lane probe set on Temporal Cloud. The issue audit reports complete cells 0/18. MO-67/72 remain open; native G1 supervision, exact current bindings and category budgets are required. |
| [SPEC-10: Signal Ingress on Vercel — routes, authentication, database functions, drainer, artifacts and deployment](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/SPEC-10-ingress-on-vercel.md) — **in progress** | MO-74, MO-75, MO-76, MO-79 | Section 10 still needs deployed exact signal ordering, gate p99 and one-tool stop, plus a greater-than-4.5MB signed upload verified into custody. MO-40 own local SQL/function/route proof is delivered. MO-74/75/76/79 still need their exact deployed/remote/crash/custody acceptance joins, not only source tests, deployment or 202 acknowledgements. |
| [SPEC-11: Remote operation (slice R): thin Temporal worker on AWS ECS Fargate and the remote launch path](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/SPEC-11-remote-worker-on-aws.md) — **in progress** | MO-77 | Section 10 requires one-task readiness, actual laptop-off accepted hosted mission with Postgres/S3 evidence, mid-session service restart with no duplicate frames, secret sentinel, repeatable redeploy and a 24-hour CPU/memory/cost record. MO-79's launch route and HL-24's remote missions explicitly cross this boundary. |

Crosscutting **HL-23/24/25** supply hosted smoke/S2/S3 acceptance; MO-07 is the
cross-packet documentation task. SC-01/02/03 retain explicit SPEC relationships
but are deferred. This table is a navigation summary; the linked actual SPECs,
issue Markdown and ledger define every criterion. Preserve completed MO-06,
MO-01/02, MO-40, MO-43/44 and the MO-78 boundary instead of reopening them.

The packet contains **97 in-sprint +13 deferred** issues:49 Run1,40 nonfunding
Run2 and8 funding-held S4. The older103 count grew historically by seven tracked
additions; this assessment added no tracker IDs. The S4 set
**HL-01/02/03/10/14/15/16/20 is in sprint but funding-held**, not silently deferred.
Do not dispatch it without its release. Deferred: **CM-06/11/12/14/15/16/17/20/22,
MO-53 and SC-01/02/03**. Do not add next-stage capability evolution, maintenance/
batch/new-provider work, broad Deep Agents or AF-FOLLOWON-01. That agent-facing
CLI/MCP/UI consolidation is a separate **manual** follow-on after this work.

Required current streams remain LS, all18 S0 cells, R, Cursor S1, Anthropic S2,
OpenAI S3 and applicable final gates. S1 is a distinct stream, not a blanket
S2/S3 dependency. HL-24 precedes HL-25. Funding-held S4 must remain visible in the
final disposition; do not claim the entire packet complete with required work
silently omitted. Report completed eligible scope and explicit remaining holds.

## 5. Integrated source and worktree reconciliation

Fresh read-only `git worktree list` found12 retained worktrees. Every listed
HEAD passed `merge-base --is-ancestor <head> MAIN/HEAD`, including all eight side
worktrees, canonical/offline, the replay-fix checkout and MAIN itself. Main source
integration is already done locally. The replay repair is
`d106d0c7191d25cda618ebd25fcebfff25aa1120`; current main includes it and the later
resource/documentation commits. No push/deployment follows from this fact.

Side-worktree parent directory:
`C:\Users\Pinda\Proyectos\BellLabs\platform\.worktrees`.
Existing names: `run2-admission-failure`, `run2-claude-host-proof`, `run2-cli`,
`run2-closed-workflow-recovery`, `run2-cursor`, `run2-cursor-c9`, `run2-events`,
`run2-human-control-budget`. The replay-fix checkout is
`C:\Users\Pinda\Documents\Codex\2026-10-16\task\run2-completion-replay-fix`.
Branch ancestry does not prove that another session's uncommitted bytes are
integrated. Inspect each relevant status/source hash before adopting anything.

Use MAIN for new implementation. Do not switch CANON to main, reset/stash/clean
it, copy stale canonical code over MAIN, regenerate issue baselines, remove
worktrees or force a merge merely because a historical plan said “merge pending.”
Reconcile only newly discovered unique commits/approved deltas through ordinary
reviewed merges/patches; preserve other uncommitted work. If directly authorized,
commit only reviewed owned paths with normal hooks. Publishing the ten existing
pending reports to CANON is a separate held action: only exclusive new files may
be copied; never overwrite CANON's dirty CURRENT/REPORT/knowledge files.

## 6. Protected recovery: terminal commit is spent, residual delivery remains (HISTORICAL — completed 2026-10-18, see the update at the top)

**Last actual remote observation:** q2 at
**2026-10-17T19:15:14.974103+00:00**, read-only canonical repository/fixture
qualification. The later Windows/WSL file checks below are not a fresh database
or Temporal observation. Refresh the exact live frontier before any effect.

| Identity or observed fact | Exact value |
| --- | --- |
| Public run | `60f44a50-c0e4-5edb-ac13-0fb0436aaedb` |
| Installation / application | `01a103c0-9a9e-70f3-9398-eb1573a98324` / `ai-engineer` |
| Tenant | `00000000-0000-7000-8000-000000000001` |
| Temporal namespace / address | `mission-control-dev.ih0e7` / `us-east-1.aws.api.temporal.io:7233` |
| Root workflow ID | `mc/01a103c0-9a9e-70f3-9398-eb1573a98324/ai-engineer/run/60f44a50-c0e4-5edb-ac13-0fb0436aaedb` |
| Root run ID | `01a143c9-1e17-72b3-9698-9c3f20a1a12c` |
| Family workflow ID | Root workflow ID plus `/family/1` |
| Family run ID | `01a143c9-1e58-7e14-9d5d-8da6ec22a0ee` |
| Committed database state | run revision9 / terminal / cancelled; family revision3 |
| Original cancellation | `6a5398e3-2a73-4351-a354-a24a9a4ddc4b`, APPLIED with3 receipts |
| Remaining delivery | Family history50 and root history17 were Running; existing `stagegraph.complete` activity4, scheduled event50, pending attempt2; normal typed WorkflowResult row absent |
| Budget / usage | Reservations empty at that observation;252 frames and926070 explicit tokens unchanged; USD unknown |
| Accepted terminal receipt | `sha256:4a5d9842f64f96abbe7a8cbcbcf9efa1840449f43265f6f8ee4e85b2da895dfc` |
| Committed protected snapshot | `sha256:a103263185922b1da2994ac167a8f3d4a692b5dbe4dff9c81cf10f8565050534` |
| Original failed operation run | `01a143c9-295a-7d84-8b47-89e40f34df00`; failed history22 must not be restarted |

**MUST NOT REPEAT THE TERMINAL CLOSURE.** The original cancellation SQL committed
successfully, despite its remaining activity/workflow delivery failing. R2A and
earlier R2B intents are spent. Never run the old closure host, repeat terminal SQL,
resubmit the provider request/public run, reset/rekey/delete a consumed marker,
invent a replacement operation/child, fabricate usage/result rows or undo the
committed cancellation. Native/provider completion, durable SQL settlement,
Temporal workflow completion and normal typed-result persistence are distinct.

The remaining proposal is **residual-only**: canonically replay the already
committed completion **read-only**, serve only the same two existing executions,
enter at most **one normal typed-result INSERT transaction through the existing
materializer/repository**, let family/root complete normally, then independently
read back the genuine persisted row and both final histories. No terminal commit,
provider call, new operation/child, default Current/ramp change or shared-service
activation belongs to this action. At most two targeted workflow overrides are
allowed. Preserve foreign workflow histories and all protected domains/effects.

The normal root workflow returns the original family StageGraph result; the typed
record is its materializer activity's result, not a substitute root final wire.
Do not fabricate timestamps or bypass the normal service to satisfy the guard.
Review the actual implementation before changing it:
[MissionRunWorkflow](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/src/mission_control/adapters/temporal/workflows/mission_run.py).

The frozen reviewed residual v3 action is
`47ae4ac754a72d70d8172c1cb93ce0869dd745803d7cd110695e32865c7934a1`;
private build `run2-residual-delivery-d106d0c7-v1`. It **expired at
19:59:03.884 UTC** and seals an earlier **eight-document** MAIN overlay, whereas
MAIN now has ten pending planning files. **It cannot execute unchanged.** Do not
patch frozen v1/v2/v3 in place. After applicable direct authority, renew only
reviewed expiry/provenance/overlay metadata, or fully requalify any real code
change, preserving the same semantic fence and exact permitted effects. All Linux
host/runtime/guard/application bytes were unchanged in v3; eleven pure provenance
tests plus actual overlay/source checks passed. Q2 transfer is only for those
unchanged bytes, not automatic qualification of a future implementation.

Before claiming the residual intent: fresh physical/commit admission; exact
source/interpreter/operator pins; restricted read-only runtime/family/result
principals and installed AI Engineer1.4.2 contract/37 receipts; committed receipt,
protected before/after images, original cancellation/budget/effects; exact existing
pending request and history prefixes; queue/poller/current-version/service state;
unused semantic residual fence and no concurrent operator. Refuse on drift.
The normal result writer is the only narrow read-write transaction, not a general
SQL-capable repair channel. Readiness checks must precede live effects.

Postconditions: database cancellation remains the same committed version/receipt;
one genuine typed row matches normal derivation; both original workflows complete
with correct genuine SDK/history results; original child/operation/foreign facts
and Current/ramp/service remain unchanged; owned workers/pools/processes stop and
are independently read back after primary reap. An uncertain/consumed residual
intent forbids automatic retry under another build/helper/action hash. Preserve
the incident and stop its dependent progression; do unaffected work.

## 7. Critical external dependencies — verified, not contained in MAIN

The following Windows paths exist; their frozen packet/manifests are the precise
dependency map, not instructions to execute a stale packet:

- [Actual q2 read-only join/cleanup receipt](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261017/continuation-v8/recovery/residual-host-v1/owned-host-q2.json).
- [Frozen v3 proposed packet, all31 operator +325 application pins](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261017/continuation-v8/recovery/residual-host-v3/proposed-action.json).
- [Frozen v3 approved historical packet](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261017/continuation-v8/recovery/residual-host-v3/approved-action.json).
- [v3 native launcher — inspect only](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261017/continuation-v8/recovery/residual-host-v3/residual_bridge.py).
- [v3 document-overlay verifier](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261017/continuation-v8/recovery/residual-host-v3/residual_launch_provenance.py).
- [v3 Linux guardian](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261017/continuation-v8/recovery/residual-host-v3/host_guard.py).
- [v3 application source manifest](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261017/continuation-v8/recovery/residual-host-v3/source-manifest.json).
- [Original closure outcome receipt — never rerun its host](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261017/continuation-v8/recovery/closure-host-r11/owned-host-coordinated1.json).
- [r5 retained genuine completion proof pointer](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261017/continuation-v8/recovery/closure-host-r5/owned-host-joinedproof5.json).
- [r3 retained phase-one source — evidence only](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261017/continuation-v8/recovery/r3/phase_one.py).
- [Historical human/category budget evidence](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261016/qualification-admission/human-authority.json).
- [Existing qualification budget ledger](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261016/qualification-admission/qualification-budget-current.json).
- [Failed Claude native smoke observation](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261016/qualification-admission/ls07-claude-readonly-observation.json).
- [Failed Codex native smoke observation](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261016/qualification-admission/ls07-codex-readonly-observation.json).
- [Sanitized provider catalog receipt](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261016/qualification-admission/provider-catalogs.json).
- [Original integrated check/preservation root](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261017/integration-inventory).
- [Supported Codex setup, billing and selective seed evidence](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-completion-offline/.scratch/run2-completion-20261017/prerequisite-closure).
- [Final ten-report paths/hashes and local validation](C:/Users/Pinda/Documents/Codex/2026-10-16/task/completion-replay-evidence/spec-final-local-v2-validation.json).
- [Final original canonical67-file preservation snapshot](C:/Users/Pinda/Documents/Codex/2026-10-16/task/completion-replay-evidence/final-canonical-readonly-snapshot.json).
- [Exact v3 live/publication rejection record](C:/Users/Pinda/Documents/Codex/2026-10-16/task/completion-replay-evidence/residual-v3-review-rejection.json).
- [Independent v3 review](C:/Users/Pinda/Documents/Codex/2026-10-16/task/residual-resource-proposal/V3-INDEPENDENT-REVIEW-2026-10-17.md).
- [Pure v3 provenance qualification](C:/Users/Pinda/Documents/Codex/2026-10-16/task/residual-resource-proposal/v3-provenance-qualification.json).
- [Independent final hold/metadata review](C:/Users/Pinda/Documents/Codex/2026-10-16/task/residual-resource-proposal/FINAL-HOLD-REVIEW-2026-10-17.md).

All31 v3 operator paths and63 checked links from the current state/report chain
were present. The original two HANDOFFS files above also exist. Keep OFFLINE,
task-local evidence and all referenced scratch; copying MAIN alone loses them.

**Private Ubuntu dependencies were freshly existence/hash checked at20:14:34 UTC**
using bounded read-only filesystem checks after confirming Ubuntu was already
running. No provider/database/Temporal query, payload disclosure or file write
was performed. This is not permission to start/stop an unrelated distribution.

| Required private path in Ubuntu | Purpose / integrity boundary |
| --- | --- |
| `/home/overton/.venvs/mc-run2-s0-a8d69c5b4850/bin/python` | Application interpreter SHA256 `ccc93c55c24bb92866cc2f9eff61b124abf5d1ee6c8da0ef9b5eed4d78a21f07` |
| `/usr/bin/python3.10` | Guardian SHA256 `a2f33a6e006989270f4340528eb61f8f97366e00a5d1b602ac8672ea44fc56ae` |
| `/home/overton/.local/state/mission-control/qualification/run2/recovery/remaining-closure-l3brnpgi/` | Original `expected-commit.json`, `seal-stagegraph.complete.json`, `before.json`, `foreign.json`; private UID1000/0600 custody |
| `/home/overton/.local/state/mission-control/qualification/run2/recovery/residual-proof-bgq_2q_w/` | Actual `family-history.bin`, `root-history.bin`, `activity4-payload.bin`; names/bytes sealed by the reviewed fixture |
| `/home/overton/.local/state/mission-control/qualification/run2/recovery/closure-proof-0vjn0g61/` | Genuine `completion-6.bin`, `completion-7.bin`, `completion-12.bin`, `completion-13.bin`; all four matched r5 pointer pins |
| `/home/overton/.local/state/mission-control/qualification/run2/recovery/registry/` | Permanent intent registry; header SHA256 `0387e921e61b2f54e68107784f0df87016285396883649205d81e8feee4798a6` |

**Spent terminal marker, never alter/reuse:**
`/home/overton/.local/state/mission-control/qualification/run2/recovery/registry/r2b-6f2c83986950208017b91aff193ee9f036b78ecf0ea29f5bc9ec8882fec7794b.once.json`
SHA256 `068d1d4057e5a5cfed01f65a820df9db7a98dacf24d607f88d6c1979b85a5e98`,
phase `remaining_closure_uncertain_no_retry`. Its bytes matched at20:14:34 UTC.

**Distinct residual-purpose fence:**
`/home/overton/.local/state/mission-control/qualification/run2/recovery/registry/r2d-741d067af675387cc416e48b55f3042461ad1de95b37c1541b992b86f916cda9.once.json`
was **absent at20:14:34 UTC**; no claim was made. Recheck immediately before an
eligible invocation. Its purpose is
`deliver-existing-committed-cancellation-result-v1`; identity is independent of
build, expiry, helper directory and retry count. New metadata cannot reset it.

Do not recreate missing fixtures from prose or synthetic expected replies. If
any critical path, binary, custody/hash or registry fact is unavailable, retain
the affected recovery gate and identify that exact missing dependency. Do not
inspect/print raw private payloads, credentials, DSNs or provider responses.

Existing Windows runtimes (path existence verified, no implicit install):
- `C:\Users\Pinda\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`
- `C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control\.venv\Scripts\python.exe`
- `C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control\.venv\Scripts\pytest.exe`
- `C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control\.venv\Scripts\ruff.exe`
- `C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control\.venv\Scripts\mypy.exe`

Authentication still depends on the existing owning Windows/WSL profiles,
configured credentials and service principals. Keys are intentionally absent
from this handoff. Locate them through the existing reviewed bootstrap/broker;
do not mint new credentials or copy secrets into prompts, Git or worker briefs.

## 8. Budgets: ceilings exist, remaining dollars are not proved

The later inclusive category ceilings recorded in PERMISSIONS/PREREQUISITE are:

| Category | Inclusive USD ceiling | Attributable spent / committed / remaining USD |
| --- | ---: | --- |
| Cursor CLI |20 | Unknown / Unknown / Unknown |
| Cursor Cloud |20 | Unknown / Unknown / Unknown |
| Anthropic local/API/SDK |25 | Unknown / Unknown / Unknown |
| Anthropic Managed |25 | Unknown / Unknown / Unknown |
| OpenAI Hosted Agents |20 | Unknown / Unknown / Unknown |
| AWS disposable qualification |10 | Unknown / Unknown / Unknown |

These include prior attributable usage and are **not refills**. Original SPRINT
slice ceilings also remain relevant: LS10 of Cursor usage, S0/S1/S2/S3/Q10 each;
Claude/Codex CLI smokes use the declared subscriptions; R uses the existing
AWS40/month ceiling with probe missions charged to S2. S4 remains held. Do not
add slice/category budgets or claim a later category ceiling erased a lower
accepted slice boundary. Reconcile each action against its applicable inclusive
category, slice, account and finite envelope; ask only if a real conflict needs
an explicit amendment.

At04:48 UTC, Cursor spending and Anthropic organization cost reports returned401,
OpenAI organization costs403. Catalog authentication is not billing access and
does not establish invalid inference credentials or zero balance. Obtain scoped
redacted existing-dashboard/export evidence and join account/product/run/cycle,
prior spend, pending liabilities, reserves, releases and credible overshoot.
Do not add keys or make paid cost queries merely to measure the budget.

Retain the unknown926070-token Cursor dollars,112976 settled Anthropic Window2
tokens,41278-token failed Codex smoke dollars and older221222-token missing-ledger
liability. These can overlap other windows; never sum them into invented usage.
The old shared S0 reserves1.35→1.85→2.85→3.85→4.85 USD are successive snapshots
of one10USD pool, not additive spend or current availability. R2A's technical
reservation settlement is not invoice reconciliation. AWS account-wide1.04USD
actual/1.658 forecast against40, recorded October16, has no task cost filters;
do not subtract1.04 from disposable10. Old app quota/credit-email observations
do not convert to USD or refill a category.

No blind paid repeat is eligible on “unknown remaining.” Work on scoped reads,
code, fake tests, data plans and the already bounded no-provider retained-result
obligation while resolving the financial gates. Native/model runs need actual
remaining allowance plus exact current auth/quota/config/serving identity.
The single-implementer rule (Sol or Opus 5.5) applies to implementation/review
agents; it does not silently substitute that model for the separately declared
product-provider drill models. Refresh supported
selected model/prerequisite pins rather than trusting an October12 model list.

## 9. Team, resource and ownership contract

- Verify the actual implementer assignment in the new session/tool UI: Codex
  **gpt-6.1-sol** or Claude Code **claude-opus-5-5**, the same model for lead,
  workers and reviewers. If unavailable, stop that assignment; no Astra/Luna or
  smaller-model fallback worker. Default lead plus one active worker; an optional
  second disjoint static reviewer only with fresh headroom. No nested delegation,
  duplicate broad scans, multi-agent workflow fan-out or simultaneous heavy
  suites/builds. Claude Code specifics (fresh-context reviewer rather than a fork,
  worktree isolation, single background native job) are in the close-out sequence.
- One coordinator-owned heavy test/fixture/build/native lease total. LS-08's
  required two parallel CLI children are an explicit product acceptance case,
  not permission for unrelated concurrent suites: provision one bounded outer
  job with both children, measured headroom/quota/cost and owned cleanup. Do not
  silently serialize away that concurrency criterion.
- Use the existing task resource admission as a private harness safeguard, not a
  Mission Control product feature. Default start needs>=1.5 GiB available physical
  **and** commit headroom; active physical floor1 GiB. V3 waits at most120 seconds
  with the full execution reserve; hard PIDFD/Windows Job lifetime bounds remain.
  The 19:39/19:45/19:51 samples showed adequate capacity after natural recovery,
  not a permanent guarantee. No process/service/OS setting was changed.
- Prior single-process RSS is not a complete Windows+shared-WSL+primary/observer/
  cleanup peak. No complete measured profile justified lowering the threshold.
  Recheck physical and commit counters, use serial scheduling and bounded useful
  waiting; clean only independently identified task-owned idle resources.
  Never kill by process name or stop live editors, MCPs, WSL/Docker, databases,
  browsers, sync/security services or other chats to free memory.
- Every worker gets exact checkout/HEAD/overlay, issue criteria, dependency evidence,
  individual writable files, command/time/fixture/resource bounds and stop rules.
  Shared contracts/domain/bootstrap/SQL/release locks/public schemas stay lead-owned
  unless expressly leased. Independent Sol review checks exact submitted hashes
  and integrated callers, not just isolated passing tests. Preserve failed evidence.

## 10. Dependency-ordered execution and useful parallel work

| Package / accountable owner | Concrete next result and boundary | Acceptance / stop gate |
| --- | --- | --- |
| A0 lead: establish source + evidence | Read the ordered inputs; Git/status/hash and required-path inventory; reconcile new concurrent work. Preserve the ten pending MAIN docs and all original CANON/OFFLINE work. | Current identities and ownership are known; no stale narrative becomes an executable plan. Re-review changed source/overlay before dependent work. |
| A1 lead + independent Sol: retained result | Prepare the smallest renewed residual-only envelope from the exact existing host/fixtures, with fresh state, source, expiry, authority and semantic-fence checks. No provider work or terminal commit. | One normal typed row and both original workflow completions, unchanged protected state/foreign operations/routing/service, independent readback and exact owned cleanup. Any uncertainty consumes/holds the residual intent and forbids automatic retry. |
| A2 cost/prerequisite owner, parallel static work | Reconcile inclusive category/slice spend/reserves and supported current auth/quota/model/prerequisites. Cursor CLI was unauthenticated in the retained observation; this alone says nothing definitive about current SDK/Cloud access. Codex setup correction already exists; do not redo it. | Fresh exact readiness and actual available allowance for the next selected native action. Owner-only interactive login/admin reporting needs are surfaced once, concretely. No inference merely to probe readiness. |
| A3 CLI owner: LS-05/07 then08 | Inspect existing `.agents/skills/coding-cli-jobs`, selected headless skill/adapters and fake tests. Correct only a demonstrated gap. Finish missing actual smokes, then original caller + Codex fix/Cursor review parallel demo with distinct worktrees/results, verifier and wake. | CLI native/config/edit/custody evidence, runner-owned verification, actual parent resumption, cost/child cleanup; fake runner `done` or sandbox marker is not native completion. |
| A4 lead/native owner: G1 then S0 | Genuine authenticated isolated API serving, exact scoped DB/principal/build/owner/policy/lease and native supervision first. Then MO-72 local Temporal and MO-67 Cloud cells on the current selected manifest/bindings. | All18 original3-caller×3-lane×2-placement cells, real wait/wake/inject/deny/cancel-or-accepted completion, instruction/skill/tool/environment evidence, immutable output/cost/cleanup. Current complete-cell evidence is0/18. No blanket qualification from one cell or cancelled recovery. |
| A5 ingress/remote owner: R, with independent Cursor S1 | Reuse MO-74/75/76/79 ingress/normal admission and MO-77 worker source. Verify current immutable app/build/queues/storage/roles first; run only the authorized exact remote envelope. Cursor S1 may advance on its own applicable readiness. | Outside-network normal admission, one base worker, actual laptop-off progression, mid-session restart/no duplicates, sentinel/redeploy and24-hour resources/cost. S1 requires original knowledge+SDLC contracts, real prepared/discovered/exercised joins, CD controls/reattach/accounting/isolation/custody/wake, gate p99<=400ms and >4.5MB signed byte custody. Do not stop the owner's machine/sessions without coordination or label a simulation laptop-off. |
| A6 hosted owner + lead: Anthropic S2 / HL-24 | After R and HL-09/17/18/23 + applicable MO-74/77/79, use the existing genuine Managed Agents product and selected saved configuration/pack. Budget production callers are already wired; do not reimplement them from stale reports. | Both original remote knowledge and SDLC mission contracts; real native deny/allow/timeout, true budget-boundary hold/readback/resume, restart/ambiguous fanout/cancel handling, invocation proof, settled actual/unknown cost, immutable review/output and separately authorized publication. Accepted cap PATCH or a turn boundary is not native pause. If required enforcement is unavailable, retain the blocker or seek a concrete acceptance amendment. |
| A7 hosted owner + lead: OpenAI S3 / HL-25 | Only after accepted HL-24 and HL-13/17, exact hosted `agents=v1` custom HTTP contract and reconciled prior spend. Preserve declared model/schema/account/agent/environment/skill seals. | Both original mission contracts, genuine function-tool approval roundtrip, current-turn/item visibility, steer/cancel, killed-worker recovery without duplicate frames/effects/charges, downloadable registered immutable bytes, actual/unknown usage/cost and cleanup. No Agents SDK/direct Responses/subscription cloud substitution or fabricated current-turn artifact download. |
| A8 lead + reviewer: final integration/data/release | Review only new demonstrated corrections in exact leased seams; integrate newly unique work normally; run affected checks and required final project gates, update truthful current evidence/navigation. | Every applicable issue criterion and native/remote contract has source-bound evidence, or is explicitly still blocked/held. Current source/installed-data/build/config identities agree; no silent migration/backfill, cost fiction or cleanup-before-custody. No full-completion claim while required unresolved work remains. |

Parallelize **disjoint bounded reads, budget/prerequisite reconciliation, fixture
inspection, documentation and narrowly leased source work** while a runtime gate
is blocked. The lead alone owns shared joins/live recovery. No duplicate provider
experiments, broad speculative rewrite or expensive suite just to keep workers busy.
Use detailed W0-W10 file leases and safe test entrypoints in COMPLETION-PLAN; inspect
the current implementation first because many historical source corrections are done.

## 11. Runtime, data, tests and evidence requirements

Temporal schedules; reducers authorize lifecycle/settlement; provider messages and
webhooks are evidence/wakes, not authority. Preserve accepted/delivered/applied
commands, external job identity/idempotency, generation/revision/owner fences,
sealed approval/configuration, native histories and custody-before-cleanup.
Do not invent optional provider parity or a missing schema from a generic checklist.

**Exact existing targets, refresh before use:** AI Engineer Supabase project
`wkythqbofmckbuoothhn`, application contract1.4.2 with37 receipts; AWS account
`298199649527`, `us-east-1`, cluster `mission-control`, service
`mc-worker-ai-engineer`, S3 bucket `mc-payloads-ai-engineer-298199649527-use1`.
Historical R target is one0.5vCPU/2GiB task; last recovery observation had service
desired/running/pending0. During residual delivery it must remain stopped.
Existing hosted lane queue `mc-ai-engineer-lane-hosted`, separate local lane queue
`mc-s0-ai-engineer-lane-wsl`; residual family queue
`mc-ai-engineer-coordinator-family-stagegraph`, root queue `mc-ai-engineer`.
Last q2 Current was `mission-control.0.1.0-a8d69c5b4850`, revision10, no ramp.
Historical task definition16/build is evidence, not a fresh deployment selection.

Biotech is a separate1.3.0 installation/28-receipt boundary. Retained observation
was12 seed replays/8 pending/1 incompatible; the artifact-schema seed requires
>=1.4.1. Original S0 targets AI Engineer1.4.2, not a blanket Biotech upgrade.
Select only acceptance-required assets and dependency closure. Applied release,
migration and seed bytes remain immutable. Any new schema/backfill needs an exact
scoped dry-run diff, provenance, idempotency/version fences, recovery plan,
disposable fresh/upgrade/repeat/drift/refusal/role proofs and applicable live
authority. No manual accounting insert or fabricated native/legacy identity.

For code changes, use existing installed dependencies, read fixture/conftest first,
scrub credentials/tracing and run the smallest meaningful regression. Database/
Temporal tests require an explicit disposable isolated target; never aim a broad
suite at shared Supabase/Cloud or a real provider. Run repository-required Ruff,
authoritative mypy, ty/deptry, architecture and relevant schema/seed/skill/package/
release checks at the final integrated source, serially. Test paths and W-package
selections are in COMPLETION-PLAN; they are not blanket approval to run them.
Avoid implicit downloads/install, xdist, several clusters or repeat broad passes
without new source changes/failure/concern. Retain earlier nonpasses distinctly.

Known scoped evidence includes149 fake conformance,681 regression and earlier
full typing at their recorded bases,65 focused normal completion-replay memory
checks, actual q2 read-only repository/SDK replay and11 private provenance tests.
These are different boundaries, not a sum proving current native/release acceptance.
The ten pending local reports passed index generation/check, link, OKF and
whitespace checks at the exact final receipt linked above. Commit hooks were not
run for those pending reports because publication was rejected before process
creation. New source invalidates affected historical check/review applicability.

Each acceptance receipt must identify issue/criterion, source HEAD+overlay hashes,
actual interpreter/SDK/CLI/schema/model requested versus observed, account/app/
namespace/queue/build, bindings/config/prerequisite/policy/lease, bounded command,
real native/process/workflow/result/custody state, cost actual/estimated/unknown,
sanitized failure and exact owned cleanup. Distinguish prepared/delivered/read-back/
discovered/exercised, cancellation accepted versus applied, provider done versus
mission accepted, review versus publication. Never promote flags from fakes alone.

## 12. Validated read-only startup commands

These metadata and documentation commands were actually exercised safely. They
do not execute recovery, call a model or mutate Git/runtime state. Run checks
serially with current resource headroom; file existence is not service readiness.

~~~powershell
$mc = 'C:\Users\Pinda\Documents\Codex\2026-10-16\task\run2-final-main'
git --no-optional-locks -C $mc status --short --branch
git --no-optional-locks -C $mc rev-parse HEAD
git --no-optional-locks -C $mc worktree list --porcelain
git --no-optional-locks -C $mc diff --check

$py = 'C:\Users\Pinda\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
Set-Location -LiteralPath $mc
& $py -B docs/tools/agents_docs_index.py --check
& $py -B docs/tools/check_links.py
& $py -B docs/tools/validate_okf.py
~~~

Use `Test-Path -LiteralPath <exact path>` and `Get-FileHash -LiteralPath <exact
file> -Algorithm SHA256` for the listed local dependencies. Do not print secret
contents. No live execute/apply/start/override command is supplied here because
the retained packets are expired and their state/source/overlay must be renewed.

## 13. What is still unavailable or must be refreshed

- No complete joined invoice/reservation history establishes remaining USD in any
  inclusive category. Existing billing exports/access and allocation are needed.
- Auth/quota/model/prerequisite/policy/lease and external service state observations
  are dated. Recheck the exact selected surface; old CLI authentication failure
  alone does not establish SDK/Cloud denial. No broad access/setup change is implied.
- Last database/Temporal recovery frontier is q2, not this document's file audit.
  Residual fence absence at20:14:34 is an observation, not future retry authority.
- Direct trusted user authorization must be available for any action the approval
  system holds. Historical recorded approvals do not overrule that system. The
  stopped live/publication commands were not bypassed or indirectly executed.
- Raw recovery fixtures, Git common metadata, virtualenvs and private evidence are
  outside MAIN. This file maps verified paths but intentionally contains no
  secrets/raw payloads and cannot recreate a missing fixture or credential.
- Native G1/LS/S0/R/S1/S2/S3 acceptance, attributable cost and applicable release/
  data/cleanup gates remain open as mapped. S4 funding release and the later
  manual follow-on remain separate. Report those limits instead of declaring
  completion from source integration or cancelled-run recovery alone.

The new session's first checkpoint should report the verified implementer model
assignment, HEAD/dirty work and dependency availability, the cost/prerequisite
frontier (the residual frontier is closed), the owner's answers to decisions
D1–D7 in the close-out sequence, one smallest next eligible work package (P1:
installation configuration source) and its sole heavy lease. Then continue useful
independent work instead of ending at the first blocked gate.
