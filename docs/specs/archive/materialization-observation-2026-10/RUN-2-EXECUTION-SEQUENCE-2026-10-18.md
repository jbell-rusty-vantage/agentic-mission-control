---
type: Sprint Execution Sequence
title: "Run 2 close-out: exact sequence, owner decisions and implementer-neutral team contract"
description: "Verified 2026-10-18 frontier, the ordered phases P0-P8 that close the materialization/observation sprint, the decisions only the owner can make, and how a Codex (gpt-6.1-sol) or Claude Code (claude-opus-5-5) lead runs it."
---

# Run 2 close-out sequence — prepared 2026-10-18

This document sits beside the [agent-team handoff of 2026-10-17](RUN-2-AGENT-TEAM-HANDOFF-2026-10-17.md)
and refines it. It does not change any SPEC or issue criterion, promote any
status, or grant authority. It orders the remaining work, names the decisions
that only the owner can make, and makes the team contract implementer-neutral.

Read order for a fresh lead: this file, then the
[fundamental-capabilities handoff of 2026-10-18](C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main/docs/specs/materialization-observation-2026-10/runs/RUN-2-FUNDAMENTAL-CAPABILITIES-HANDOFF-2026-10-18.md)
(sections 1, 5, 7, 8, 12), then the 2026-10-17 handoff for roots, dependencies and
budgets, then the files its section 3 lists. The 2026-10-18 handoff is the current
continuation entrypoint; the 2026-10-17 handoff's section 6 (residual delivery) is
historical.

## 1. Verified frontier at 2026-10-18 (read-only inspection)

| Fact | Verified value | Consequence |
| --- | --- | --- |
| MAIN checkout | `C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-final-main`, branch `main`, HEAD `1d081297bde6fd74e9276df45102eef3c0dc746d`, 60 ahead of local `origin/main` | Still the implementation checkout. |
| MAIN dirty state | 3 modified (`README.md`, `runs/RUN-2-CURRENT-INTEGRATION-2026-10-17.md`, `src/mission_control/application/execution/harness/cursor_bridge_recovery.py`) + 16 untracked planning/evidence files, including `runs/RUN-2-FUNDAMENTAL-CAPABILITIES-HANDOFF-2026-10-18.md` and six `runs/FINAL-CAPABILITY-*.json` | The 2026-10-17 handoff's "ten pending paths" statement is stale. All 19 are intentional and uncommitted. The one source overlay (`cursor_bridge_recovery.py`, expected SHA256 `5280d379279cfddc5999ce3be3a95b6c40ec0e20e7b34ae7fe522452775e49c0`) is reviewed and unit-tested (37 tests) but uncommitted. |
| CANON checkout | `C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control`, `mo/run2-integration` at `a8d69c5b48506c6babcd7f3f74f0b92716423091`, 21 modified tracked files plus untracked reports/source/tests including the 2026-10-17 handoff itself | Older branch with preserved dirty work. The 2026-10-17 handoff and this file exist **only** here until copied. |
| Worktrees | 12 retained, all as listed in the 2026-10-17 handoff section 5 | Preserve all; none is needed for new work. |
| A1 residual delivery | **Complete.** Root history 33 Completed with the normal typed result; family 58 unchanged; independent post-reap observer passed. Four terminal/residual/manual fences consumed. | Section 6 of the 2026-10-17 handoff and package A1 are closed. Never retry, reset or rekey anything there. |
| Current core wheel | `C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-fresh-session-20261017/g1-current-build/artifacts/mission_control-0.1.0-py3-none-any.whl`, SHA256 `7bbe31ac…`, build `0.1.0-1d081297bde6`, predates the overlay | Not in MAIN. Do not deploy it; rebuild at close-out. |
| Acceptance counts | 38 done / 41 implemented-unqualified / 18 blocked / 12 not started / 1 active; whole-SPEC qualified 0/11; S0 complete cells 0/18 | Unchanged by this document. |
| The one known implementation gap | `src/mission_control/bootstrap/manifests.py:129-131` composes `CatalogEnvironmentInputs(EnvironmentKitCatalog(...))` with no installation configuration source, so every `value_ref: config:<key>` is a compile blocker (see `application/environments/kits.py:76-96`, `domain/authoring/mission_environment.py:113-137`) | This is the real SDLC task for F1 and the first implementation item (P1). |
| Native CLI observations | Claude Code 2.1.302: max-turn exit 1, Read+StructuredOutput completion exit 0, schema-failure terminal subtype `success`; Codex 0.162.1: command executed, runner verifier line-ending nonpass retained; Cursor CLI: authenticated, native run produced no frames (consumed, 10 USD LS hold intact) | LS-07 is partly answered; LS-08 unrun. |
| Serving foundations | Current-wheel health-only API (27 s) and protected GET with real 401/401/200 bearer readbacks passed on WSL loopback; registry header initialized once; no worker, mission or inference ran | G1 ordinary launch-enabled composition is still unqualified. |
| Budgets | Fresh category ceilings: Cursor CLI 20, Cursor Cloud 20, Anthropic local 25 (24.6557698 remains on reported-cost basis), Anthropic Managed 25, OpenAI hosted 20, AWS disposable 10 USD. Slice caps of 10 USD apply simultaneously. Old Cursor LS 10 USD hold still held. | Local lanes are fundable now. Remote streams need a deploy session. |

## 2. Decisions only the owner can make (answer these in the kickoff message)

**Decided 2026-10-18.** The owner took D1 (Gate L), D3 (native local fixtures
authorized), D4 (release the Cursor hold) and D7 (commits/merges) as recommended;
D2 is Claude Code on `claude-opus-5-5`; D5 is approved end to end under its
listed conditions with no owner go (the owner is away for the run); D6 defers F2. The config source is implemented
directly in P1. The recorded decisions, the Claude Code lead prompt and the
worktree merge procedure are in
[RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md).
The table below is kept as the record of what was asked and why.

The lead must not infer any of these. Each is one sentence to include or strike.

| ID | Decision | Recommendation and why |
| --- | --- | --- |
| **D1 Sprint-close boundary** | Does Run 2 close at **Gate L** (local fundamentals: P1–P7 below, all 18 S0 cells on local and Cloud Temporal, LS-07/08) with R, S1, S2, S3 and funding-held S4 carried as explicit open streams into the next capability-proof program? Or must R/S1/S2/S3 complete inside Run 2? | **Recommend Gate L.** R/S1/S2/S3 need a Vercel/AWS deploy session, a 24-hour soak and remote two-mission contracts. You intend to run full real fixtures across every provider afterwards anyway; running them twice is the slowest path. Record the distinction as a disposition, not as an edit to the original criteria (the 2026-10-18 handoff F5 allows exactly this). |
| **D2 Implementer** | Codex with `gpt-6.1-sol`, or Claude Code with `claude-opus-5-5`? | Either works with section 4. Claude Code has one structural advantage for this packet: the lead session *is* the SPEC-08 "Claude Code caller" for LS-08 and the "Claude Code Windows" caller for six S0 cells, so those proofs need no extra tooling. |
| **D3 Native local-lane fixtures** | Confirm that native local-lane runs (claude_agent_sdk, codex, cursor_local on the WSL worker; local then Cloud Temporal) are authorized within the fresh category ceilings and 10 USD slice caps, one bounded owned job at a time. | Say yes once here; the 2026-10-18 handoff otherwise reads as "no new host experiment is authorized". |
| **D4 Cursor LS hold** | The stale 10 USD LS Cursor reservation blocks LS-08's Cursor review job (it exhausts the LS slice). Release it on the evidence that the Cursor dashboard showed zero usage events for Oct 17–18, or keep it and fund LS-08's Cursor job from the Q/S0 slice by explicit amendment. | Recommend release by one explicit sentence; the dashboard evidence is already recorded. |
| **D5 Report schemas** | If the installed app-scoped catalog has no published `diagnosis`/`patch`/`review` report schemas, authorize one additive artifact-schema seed release (new slot, disposable fresh/upgrade/repeat proof, then live apply to AI Engineer 1.4.x) so F1 outputs can validate against registered schemas. | Needed only if P2's read-only catalog check finds them absent. Approve conditionally now to avoid a round trip. |
| **D6 Knowledge Services binding for F2** | Name the actual Knowledge Services MCP server, tool allowlist, secret *refs* and egress hosts the AI Engineer application may use, and the designated input Artifact. | Without this F2 cannot start honestly. If you prefer, defer F2 to the capability-proof program and close Run 2 on F1/F3/F4 plus S0/LS. |
| **D7 Commit and merge** | Confirm local commits of reviewed owned paths and ancestry-preserving merges to local `main` remain authorized (as recorded 2026-10-17); no push. | Already granted; restate so the lead does not stop at the first commit. |

## 3. Phases in order

Compute classes follow the completion plan: **R** read-only, **U** offline unit
process, **D** one disposable PG/Temporal fixture, **L** finite live/native drill.
"Lease" means the single coordinator-owned heavy job. No calendar estimates.

### P0 — Startup and reconciliation (R, no lease)

1. Run the validated read-only commands from the 2026-10-17 handoff section 12 against MAIN. Record HEAD, status, 12 worktrees, `diff --check`, docs index/link/OKF checks.
2. Hash `src/mission_control/application/execution/harness/cursor_bridge_recovery.py` in MAIN and confirm `5280d379…`. If it differs, stop and report; do not "fix" it.
3. Copy this file and the 2026-10-17 handoff from CANON into MAIN's packet root as **exclusive new files** (byte-identical; never overwrite anything in MAIN).
4. Confirm the wheel path above exists; confirm `.agents/skills/{coding-cli-jobs,claude-code-headless,codex-exec,cursor-agent-headless}` exist in MAIN.
5. Verify the actual lead/worker model assignment in the tool UI and report it.
6. First checkpoint to the owner: model assignment, HEAD and dirty set, dependency availability, the D1–D7 answers you received, the first lease you will take (P1).

Exit: the owner can see the exact source identity before any edit.

### P1 — Implement the installation configuration source (U, one lease)

This is ordinary in-scope implementation under existing authority (2026-10-18 handoff section 8 item 3). It is also the subject matter of F1.

- Lease (lead-owned bootstrap plus leased files): `src/mission_control/bootstrap/manifests.py`, `src/mission_control/application/environments/kits.py` only if the port needs a second input, a new `src/mission_control/bootstrap/installation_config.py` (or the existing Settings module if a field fits), `tests/unit/authoring/test_manifest_v2_launch.py` (add cases), one new unit test file beside it.
- Behavior: a non-secret installation configuration mapping reaches `CatalogEnvironmentInputs(config=...)` in production composition. Source of values: a typed Settings section or an app-scoped installation-config table that already exists; **not** environment variables marked secret, not `.env` secrets. A key that looks like a secret (contains `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `DSN`) is refused at compile with a pointed blocker. Unknown key stays a blocker. Compile digest is stable across repeated compiles.
- Tests: valid literal resolution, missing key, secret-like key refusal, override/inheritance stability, no value echoed into resolution output or logs.
- Checks: `uv run --no-sync ruff check <files>`, authoritative `uv run --no-sync mypy` on the changed modules, the two authoring test files, `tests/unit/runtime/test_run2_worker_roles.py` if composition changed. Serial, bounded.
- Independent review by a fresh-context reviewer on the exact diff (section 4). Then local commit on MAIN under D7.

Exit: a `mission/v2` manifest with `value_ref: config:<key>` compiles positively in the production composition; negatives refuse with pointed blockers.

### P2 — F0: full configuration compilation with zero native create (U, one lease)

Follow the 2026-10-18 handoff F0 exactly. Concretely:

1. Read-only catalog check first: does the installed AI Engineer 1.4.2 app-scoped catalog publish report schemas usable for diagnosis/patch/review outputs? Record refs and digests. If absent, prepare the additive seed release (D5) now, in a disposable target, so it does not block P5.
2. Author the F1 manifest from `tests/fixtures/manifests/multi-provider/codex.stage-graph.mission.yml` (SHA256 `54ca8f2d…`): real repo = MAIN source checkpoint plus pinned overlay; cognition = `plugin.cognition-sdlc@0.1.0#sha256:a57f772c…`; roles = implementer-reviewer and test-runner subagents from the seed; output schemas = the refs found in step 1; one `config:` variable so P1 is exercised.
3. Compile and preflight through `POST /missions:compile` and `POST /missions:preflight` (or the service calls directly in an offline process). Repeat compile; compare canonical digests.
4. Run every F0 negative against a configuration copy: unknown config key, secret-like key, absent secret name, stale kit digest, wrong bundle digest, unsupported hook event, nonexistent schema, required hard pause, provider-wide per-command approval on cursor_local, PHI data class on a hosted lane.
5. Evidence rows as named in F0 (`configuration.inventory.json`, `compile.positive.json`, `preflight.positive.json`, `compile.repeat.json`, `negative.<case>.json`, `no-effects-observer.json`).

Exit: positive compile has zero unresolved blockers and a stable digest; every negative refuses at the intended stage.

### P3 — G1: ordinary local serving without inference (D, one lease)

Bring up the normal launch-enabled composition locally, from MAIN source with the pinned overlay (not the old wheel): API on WSL loopback with the sponsored grant, one base worker, one lane worker on private queues (`mc-run2-g1-ai-engineer-1d081297-*` prefix is the prepared convention), local Temporal, the real checkpoint saver/store verified with noDDL setup only.

- Before idle serving: existing principal, exact never-used queues, no foreign pollers, component 1.4.2/37 receipts, S3 HeadBucket only if the first mission needs S3.
- Smoke with **zero inference**: submit the F1 manifest with a deliberately unmet prerequisite and show `PREREQUISITES_UNMET` at preflight and at start with the same typed list; submit the valid manifest and stop at `start` returning 202 only if the lane worker is the fake/controlled provider. Do not let a real provider turn happen in P3.
- Concrete pre/post observers must make independent calls. Exact shutdown and reap recorded.

Exit: G1 receipt with identities, queues, grants and cleanup. S0 and F1 can now run.

### P4 — LS-07 remaining cells, then LS-08 (L, one lease; subscriptions plus Cursor per D4)

- LS-07: finish only the missing cells, chiefly the Cursor CLI native run. Integrate the prepared missing-result receipt boundary first (fresh-session preparation, seven regressions passed) under a reviewed lease so a nominal exit 0 with no result is retained truthfully.
- LS-08: one bounded outer job that launches a Codex fix and a Cursor review of the same small bounded change in two isolated worktrees, runner-owned verification, background completion wake, and both `result.json` files read by the caller.
  - If the implementer is Claude Code: the lead session is the caller. Run `agentjob.py` through a background shell task and read both results when the completion notification arrives. That is the SPEC-08 end-to-end clause verbatim.
  - If the implementer is Codex: drive the Claude Code caller headlessly (`claude -p` with the headless skill) and record that the caller was a headless session.

Exit: LS-07 cells recorded pass/nonpass; LS-08 receipt with both results, verifier evidence, cost actual/unknown, child cleanup.

### P5 — F1 + F3 + F4 as S0 cells (L, one lease per run)

Every native run in this phase is designed to be **both** a representative workflow record and an S0 cell record. The probe manifest must therefore include: caller `missionctl wait` registered before terminal, one `interrupt_and_inject`, one forbidden tool path and one allowed test command, and a terminal branch (completion with accepted output or a separate bounded clean cancel).

Order, by expected certainty:

1. `claude_agent_sdk`, local Temporal, Claude Code caller (S0-01). F1 mission: review the P1 diff (diagnose, run focused tests, produce diagnosis/patch/review artifacts validated against registered schemas, review_required gate). F3 observations and one F4 intervention on the same run.
2. Same lane, Codex caller (S0-04) and Cursor caller (S0-07): the mission can be a smaller control task; the lane is already exercised. Record a separate bounded clean-cancel case if the completion runs cannot also supply it.
3. `codex` lane for the three callers (S0-02/05/08). Include the native Codex hook deny with trust (SPEC-02 section 9).
4. `cursor_local` for the three callers (S0-03/06/09), only within the Q/S0 10 USD slice and after Claude/Codex lanes pass. Preserve requested versus observed model and unknown dollars.
5. Repeat the nine cells on Temporal Cloud (`mission-control-dev.ih0e7`) for S0-10..18. This is a Temporal address and credential switch, not a deployment; MO-78 is done and MO-67 depends only on MO-72 and MO-78.

Exit: `FINAL-CAPABILITY-S0-18-CELLS.json` updated from receipts only, each cell passed/failed/blocked/unrun; F1/F3/F4 evidence rows complete for at least the claude_agent_sdk run.

### P6 — F2 knowledge workflow (L, one lease; only with D6)

Follow the 2026-10-18 handoff F2. If D6 is not answered, record F2 as blocked on the named binding and continue; do not substitute a public search tool.

### P7 — Reconcile and document in place (R/U)

- Update `FINAL-CAPABILITY-S0-18-CELLS.json`, the issue appendix statuses that the receipts actually close, and one in-place status ledger (see section 5). Do not create a new dated report per attempt.
- F5 index: one row per SPEC/issue criterion to one evidence source with status.

### P8 — Close-out gates (U, one lease, then commits)

- Final affected checks at the integrated source: Ruff, authoritative mypy, ty, deptry, architecture tests, schema/seed/skills checks, docs index/link/OKF. Serial. No broad suites without a new source change.
- Rebuild the wheel from the final committed source through the normal release process and record its identity; do not deploy.
- Commit reviewed owned paths on MAIN; merge to local `main` is already the branch. No push.
- Final disposition: completed scope, explicit open streams (R, S1, S2, S3, funding-held S4, deferred 13) and the hand-over note to the capability-proof program.

## 4. Implementer-neutral team contract

The 2026-10-17 handoff's "Sol-only" rules are about **resource discipline and
independence**, not about one vendor. The same rules, restated for both:

| Rule | Codex (gpt-6.1-sol) | Claude Code (claude-opus-5-5) |
| --- | --- | --- |
| Lead model | Select `gpt-6.1-sol` in the task UI; prompt text does not select a model. | Start the session on Opus 5.5 (`/model`); report the actual model in the first checkpoint. |
| Worker model | Every worker and reviewer `gpt-6.1-sol`; no Astra/Luna fallback. | Subagents on Opus 5.5 for source/SQL/seed/manifest/merge work and its review; Sonnet 5.5 for exploration, evidence assembly, parsing, documentation tables and bounded test runs (owner permits both, decided 2026-10-18). Never Haiku. If Opus is unavailable for a source change, do it in the lead session rather than downgrading. |
| Concurrency | Lead plus one active worker; optional second disjoint static reviewer only with fresh headroom. No nested delegation. | Same. At most one implementer Agent running plus one read-only reviewer. Never launch a multi-agent Workflow for this packet: the host has about 15 GB RAM and more than ten concurrent agents running pytest crashed Claude Code twice on 2026-10-13. |
| Independence of review | Fresh-context reviewer with the exact diff and criteria; a changed patch invalidates its review. | Spawn the reviewer as a **fresh** `general-purpose` agent with the diff path and criteria, not as a `fork` (a fork inherits the lead's conclusions and anchors on them). |
| Worktrees | Isolated worktree per leased implementation; pin the planning overlay by digest. | Use the Agent tool's `isolation: "worktree"` or `EnterWorktree`; copy only reviewed planning bytes into it; never hand a changing MAIN checkout to a writing agent. |
| Heavy lease | One test/fixture/build/native process at a time; bounded outer deadline. | Run long native jobs as a single background shell task and wait for its completion notification; do not poll. Never start a second pytest/native job while one runs. |
| Memory floors | Start at ≥1.5 GiB available physical and commit headroom; stop below 1 GiB. Never kill by process name. | Same. The `windows-resource-care` skill exists for diagnosis; it does not authorize stopping shared services. |
| Native caller role | Codex is natively the "Codex Windows" caller for S0-04/05/06/13/14/15. Claude Code and Cursor callers run headlessly via the SPEC-08 skills. | Claude Code is natively the "Claude Code Windows" caller for S0-01/02/03/10/11/12 and the LS-08 caller. Codex and Cursor callers run headlessly via `codex exec` and `cursor-agent`. Record headless versus interactive caller in each receipt; the SPEC says "sessions", so a headless session is a session, but say which it was. |
| Cross-provider review | Optional Claude Code headless review of a Codex patch via the headless skill. | Optional Codex review via the `codex:codex-rescue` agent for a second implementation or diagnosis pass. Never let a cross-provider review substitute for the fresh-context same-provider reviewer. |
| Permissions | Host approval policy as configured; no bypass flag. | Run in the configured permission mode; do not request bypass. A denied tool call is a decision, not an error to retry. |
| Worker brief | Model, exact checkout/HEAD/overlay, issue criteria, dependency evidence, individual writable files, bounded commands, stop rules, deliverables. | Identical brief in the Agent prompt. The agent sees only that brief; include file paths, not summaries. |

Where the 2026-10-17 handoff and its linked reports say "Sol" or "gpt-6.1-sol" in
the context of the implementation team, read "the implementer model selected in D2".
Product-provider drill models are separate and unchanged: Claude CLI/SDK
`claude-sonnet-5-5`, Codex CLI `gpt-6-luna` (observed `gpt-6.1-sol` on 2026-10-17),
Cursor Auto plus one `grok-4.7` run.

## 5. Suggestions for finishing fastest

1. **Decide D1 first.** Everything remote (R, S1, S2, S3) is a deploy session plus a 24-hour soak. Closing Run 2 at Gate L and running those streams once, with real fixtures, in the next program avoids running them twice.
2. **Implement the config source directly in P1, then make F1 the review of that diff.** The 2026-10-18 handoff allows either; direct implementation is deterministic and makes F0 positive compile possible, and a review-shaped StageGraph over a real diff is still a real SDLC mission.
3. **Make every native run count twice.** One probe manifest that satisfies F1/F3/F4 observations *and* the S0 cell clauses turns 18 cells plus three fixtures into about two dozen bounded runs instead of forty.
4. **Use the lead as the native caller** (Claude Code for LS-08 and six cells; Codex for six cells). It removes a tooling layer from the hardest acceptance clause in SPEC-08.
5. **Check for report schemas before anything else in P2.** If they are absent, the additive seed release is the one piece of data work on the critical path; start it early under D5.
6. **Resolve the Cursor hold with one sentence (D4).** Otherwise LS-08 stalls on a 10 USD reservation that the dashboard already shows as unspent.
7. **Run cursor_local last.** It has the least certainty (no frames on the last attempt, approval suspension unimplemented) and the smallest slice.
8. **Cloud S0 is cheap.** The nine Cloud cells are a namespace switch to `mission-control-dev.ih0e7`, not AWS. Keep them inside Run 2.
9. **Stop generating a dated report per attempt.** The packet has 66 run files in MAIN. Keep one in-place close-out status file (`runs/RUN-2-CLOSE-STATUS.md`, appended per phase) plus the machine JSONs. Private receipts stay in the session directory as before.
10. **Do not rebuild or install the wheel until P8.** Serve from pinned source; the wheel is a release artifact, not a prerequisite for local proofs.
11. **Never do these again:** rerun the initializer, touch any consumed fence, repeat terminal SQL, open the old recovery hosts, redo A1, repeat the Cursor login, or raise the Cursor 75 USD on-demand limit.

## 6. Copy-paste kickoff for the new session

Replace the bracketed items. The authorization sentences are proposals; include
only those you mean.

~~~text
Close the Mission Control Run 2 sprint following
C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control/docs/specs/materialization-observation-2026-10/RUN-2-EXECUTION-SEQUENCE-2026-10-18.md
and the 2026-10-18 fundamental-capabilities handoff in MAIN. Implementer: [Codex gpt-6.1-sol | Claude Code claude-opus-5-5]
for lead, workers and reviewers; verify and report the actual assignment. Lead plus one
active worker, one heavy lease, fresh-context reviewer, no nested delegation, no multi-agent
workflow fan-out. Preserve all dirty work, worktrees, consumed fences and running sessions.

Decisions: D1 Run 2 closes at Gate L; R, S1, S2, S3 and funding-held S4 carry into the next
capability-proof program as explicit open streams. D3 I authorize native local-lane fixture
runs within the fresh category ceilings and 10 USD slice caps, one bounded job at a time.
D4 [Release the stale 10 USD Cursor LS hold | Keep it and fund LS-08's Cursor job from Q/S0].
D5 If report schemas are absent, prepare the additive seed release and present the exact
plan before live apply. D6 Knowledge Services binding for F2: [server/tools/secret refs/
input artifact | defer F2]. D7 Local commits of reviewed paths and local main merges remain
authorized; no push, no deployment, no S4 release.

Start with P0 and report the first checkpoint before taking the P1 lease.
~~~

## 7. What this document does not do

It does not change `issues.json`, any SPEC, the 110 issue files or the acceptance
counts. It does not authorize paid work, deployment, pushes or funding release;
the owner's kickoff message does that. It does not replace the 2026-10-18 handoff's
F0–F5 procedures; it orders them and names what blocks each one.
