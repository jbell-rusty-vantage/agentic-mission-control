---
type: Agent Configuration
title: "Run 2 close-out with Claude Code (Opus 5.5): recorded decisions, lead prompt, phase procedures, worktree reconciliation and completion summary"
description: "Owner decisions D1-D7 as taken on 2026-10-18, the copy-paste lead prompt for a Claude Code session on claude-opus-5-5, how to run each phase with Claude Code's own tools, how to reconcile every worktree into main, and what the completion summary must contain."
---

# Run 2 close-out instructions for Claude Code on Opus 5.5

Companion to the [close-out sequence](RUN-2-EXECUTION-SEQUENCE-2026-10-18.md)
and the [2026-10-17 handoff](RUN-2-AGENT-TEAM-HANDOFF-2026-10-17.md). The
sequence says *what* and in which order; this file says *how* a Claude Code lead
does it, and records the owner's decisions so the lead does not ask again.
Nothing here changes a SPEC, an issue or an acceptance count.

## 1. Owner decisions recorded 2026-10-18

| ID | Decision | Effect on the work |
| --- | --- | --- |
| D1 | **Run 2 closes at Gate L.** Local fundamentals (F0, F1, F3, F4), LS-07/08 and all 18 S0 cells on local and Cloud Temporal. R, S1, S2, S3 and funding-held S4 carry into the next capability-proof program as explicit open streams. | Record the boundary as a disposition in the close-out status and final summary. Do not edit original criteria; do not run anything that needs a Vercel/AWS deployment. |
| D2 | **Implementer: Claude Code on `claude-opus-5-5`** for lead, every implementer subagent and every reviewer. | Section 3 is the operating contract. The lead session is also the native "Claude Code Windows" caller. |
| D3 | **Native local-lane fixture runs are authorized** on claude_agent_sdk, codex and cursor_local on the WSL worker, local then Cloud Temporal, within the fresh category ceilings and 10 USD slice caps, one bounded owned job at a time. | No further permission request for an in-envelope run. Ask only for a concrete scope, funding, publication or deployment barrier. |
| D4 | **Release the stale 10 USD Cursor LS reservation** on the recorded dashboard evidence (zero usage events for 2026-10-17 to 18). | Record the release in the budget ledger with its evidence reference; LS-08's Cursor review job draws from the LS Cursor slice again. The consumed Cursor native attempt stays consumed. |
| D5 | **Report-schema seed release approved end to end, no owner go required (amended 2026-10-18 for unattended execution).** If the installed app-scoped catalog lacks usable diagnosis/patch/review report schemas, prepare the additive artifact-schema seed release and apply it live to the AI Engineer project **provided every one of these holds**: the read-only catalog check shows absence; the release is additive only in a new slot and changes no applied migration/seed bytes; disposable fresh, upgrade, repeat, drift, refusal and role proofs pass; the exact scoped dry-run diff and a backup/restore record are written before apply; the apply is idempotent and is read back with the 1.4.x fingerprint and receipt count recorded. Biotech is untouched. | Do the catalog check first in P2. If any condition fails, do not apply; record the release as blocked with the failing condition, run F1 with output validation against the disposable target only, and mark the affected criteria "blocked on schema release" in the summary. |
| Unattended | **The owner is away for the whole run.** No question to the owner may block progress. | Where a decision not covered by this table is genuinely required, write it as a blocked item with the exact question in the status file and the summary, then continue unaffected work. |
| Authentication | **No interactive authentication will be available.** Claude Code and Codex are already authenticated on this machine. The installation environment file `C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control/.env` (git-ignored; MAIN has none) carries `CURSOR_API_KEY`, `CURSOR_EMAIL`, `CURSOR_PASSWORD`, `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`. | Read variable **names** from that file; pass values only into the environment of owned child processes through the existing bootstrap or broker paths. Never print, log, copy or commit a value; never paste one into a brief. Use the Cursor API key route for Cursor native work (it is the route already observed authenticated); use the email/password only if a supported, non-interactive, pinned-CLI or SDK login path exists, and record which route was used. **If any authentication fails or needs a browser, 2FA or a human, do not retry in a loop: record the exact surface, error class and affected criteria as an authentication deficiency, mark those cells/criteria blocked, and move on to the next lane or phase.** |
| Subagent models | **Permitted subagent models: `claude-sonnet-5-5` and `claude-opus-5-5`. Choose for efficiency.** | Opus 5.5 for any agent that writes or reviews application source, SQL, seeds, release files, manifests or the merge resolution; Sonnet 5.5 for read-only exploration, evidence-file assembly, receipt and log parsing, documentation tables, three-way file classification in P8, and running bounded test commands and reporting results. Record the model used in each agent's deliverable. |
| D6 | **F2 (knowledge workflow) is deferred** to the Knowledge Services program. | Record F2 as deferred with reason "owner-deferred 2026-10-18"; do not substitute a public search tool; do not count it against the sprint. |
| D7 | **Local commits of reviewed owned paths and ancestry-preserving merges into local `main` are authorized. No push, no deployment, no S4 release.** | Commit at the end of each phase. Section 5 defines the final merged state. |
| Implementation choice | **Implement the installation-configuration source directly (P1), then make fixture F1 the review of that real diff.** | P1 is ordinary leased implementation; F1's mission reviews the P1 diff. |
| Final state | **All worktrees reconciled and merged into `main`; conflicts resolved; completion summary written.** | Section 5 and section 6. |

## 2. Starting the session

Start Claude Code in MAIN, not in the canonical folder:

~~~powershell
Set-Location -LiteralPath 'C:\Users\Pinda\Documents\Codex\2026-10-16\task\run2-final-main'
claude
~~~

Then `/model` and select Opus 5.5 before pasting the prompt. Paste section 7 (or
attach `RUN-2-MISSION.md` and say "Complete the mission") as the first message.

**Unattended run.** The owner will not be present to approve tool calls. Start the
session in a mode that does not prompt, for example
`claude --dangerously-skip-permissions` (or the project's permission allowlist if
it already covers shell, file, git and network use). Without this the session
stalls at its first shell prompt. This is the owner's choice at launch; the lead
must never request a permission change and must never ask the owner anything
during the run.

Why MAIN: it is the integrated `main` checkout with the reviewed source overlay.
The canonical folder is on the older `mo/run2-integration` branch. MAIN is a
linked worktree whose `.git` points into the canonical repository's
`.git/worktrees/run2-final-main` and whose `.venv` is a junction into the
canonical `.venv`; both are preserved until section 5 says otherwise.

## 3. Operating contract for Claude Code

| Concern | Rule |
| --- | --- |
| Models | Lead on Opus 5.5. Subagents are Opus 5.5 (no `model` override) or Sonnet 5.5 (`model: "sonnet"`), chosen for efficiency: **Opus** for anything that writes or reviews source, SQL, seeds, release files, manifests or merge resolutions; **Sonnet** for read-only exploration, evidence assembly, receipt/log parsing, documentation tables, three-way file classification and running bounded test commands. Never Haiku. If an Opus subagent is unavailable for a source change, do that work in the lead session rather than downgrading it. Record the model in each deliverable. |
| Concurrency | Lead plus **one** active implementer agent. One read-only reviewer agent may run while no implementer runs. Never launch the `Workflow` tool or any fan-out for this packet: the host has about 15 GB RAM and more than ten concurrent agents running pytest crashed Claude Code twice on 2026-10-13. |
| Independence | Reviewers are **fresh** `general-purpose` agents given the exact diff path, base and overlay hashes, the issue criteria and the files to read. Never use `subagent_type: "fork"` for a review; a fork inherits the lead's conclusions. A changed patch invalidates its review. |
| Isolation | Implementer agents work in a worktree created for the lease (`isolation: "worktree"` on the Agent call, or `EnterWorktree` from the lead). Copy only reviewed planning bytes into it; never hand the live MAIN checkout to a writing agent. The lead integrates the patch into MAIN. |
| Heavy lease | Exactly one test, fixture, build or native process at a time. Run long jobs (pytest selections, native drills, G1 serving) as **one background shell task** and wait for its completion notification; do not poll and do not start a second heavy job meanwhile. |
| Memory floors | Start a heavy job only with at least 1.5 GiB available physical memory and commit headroom; stop below 1 GiB. Never kill by process name or stop editors, MCPs, WSL, Docker, databases, browsers or other sessions to free memory. The `windows-resource-care` skill is for diagnosis only. |
| Native caller | The lead session is the SPEC-08 "Claude Code session" caller for LS-08 and the "Claude Code Windows" caller for S0-01/02/03/10/11/12. Drive the Codex caller with `codex exec` through the `codex-exec` skill and the Cursor caller with `cursor-agent` through the `cursor-agent-headless` skill; record "headless" in each receipt. |
| Cross-provider second opinion | Optional: the `codex:codex-rescue` agent may review a patch or diagnose a failure. It never replaces the fresh-context Opus reviewer. |
| Credentials | Source: the canonical `.env` named in section 1 (MAIN has no `.env`). Names only in any text you write; values only in owned child process environments via existing bootstrap/broker code. On any authentication failure: record the deficiency, mark the dependent cells blocked, continue. No login loops, no browser flows, no credential edits. |
| Writes | Edit with the file tools after reading; keep private receipts in the session directory (`C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-fresh-session-20261017` or a sibling you create and name once). Never write secrets, tokens, DSNs, raw provider payloads or `.env` contents into the repository, a prompt or a brief. |
| Git | Normal hooks on. Commit reviewed owned paths at the end of each phase with a message that names the phase and the evidence file. No `--no-verify`, no amend of someone else's commit, no push. |
| Status | Maintain **one** in-place file, `docs/specs/archive/materialization-observation-2026-10/runs/RUN-2-CLOSE-STATUS.md` in MAIN, appended per phase with: phase, lease taken/released, commands run, passed/failed/blocked/unrun, evidence file paths and hashes, cost actual/estimated/unknown, next lease. Do not create a new dated report per attempt. |
| Reporting | Report to the owner at each phase exit (section 4) and immediately on any stop rule. The final summary follows section 6. |

### Stop rules (report and hold the dependent step; continue unaffected work)

- HEAD, status or the overlay hash of MAIN differs from what you recorded at P0 and you did not change it.
- Any consumed fence, recovery host, initializer or terminal SQL path would be touched.
- A paid run would exceed its slice or category remainder including a credible overshoot, or cost cannot be attributed.
- A required gate (schema live apply, deployment, push, funding) needs the owner.
- A native job leaves an unreaped child, an unknown effect or missing custody.
- Memory falls below the floor.

## 4. Phase procedures with Claude Code specifics

Each phase has an exit report. Phases are from the sequence document; this
section adds the Claude Code mechanics and exact artifacts.

### P0 — Startup and reconciliation (read-only)

1. Read, in this order: MAIN `AGENTS.md`, `docs/AGENTS.md`, `src/mission_control/AGENTS.md`, `src/mission_control/bootstrap/AGENTS.md`, `src/mission_control/application/AGENTS.md`, `tests/AGENTS.md`; the close-out sequence; the 2026-10-18 handoff sections 1, 5, 7, 8, 12 and the eleven checklists; the 2026-10-17 handoff sections 2, 4, 5, 7, 8; `SPRINT.md`; `runs/RUN-2-COMPLETION-PLAN-2026-10-16.md` (file leases and test entrypoints); `FINAL-CAPABILITY-S0-18-CELLS.json`; `FINAL-CAPABILITY-REPRESENTATIVE-WORKFLOWS.json`; `FINAL-CAPABILITY-EXACT-BINDING-INVENTORY.json`.
2. Run the validated read-only commands (2026-10-17 handoff section 12) from MAIN. Expected: branch `main`, HEAD `1d081297bde6fd74e9276df45102eef3c0dc746d`, 3 modified + 16 untracked, 12 worktrees. Record what you actually see.
3. Hash `src/mission_control/application/execution/harness/cursor_bridge_recovery.py`; expected SHA256 `5280d379279cfddc5999ce3be3a95b6c40ec0e20e7b34ae7fe522452775e49c0`.
4. Verify that `RUN-2-MISSION.md`, `RUN-2-AGENT-TEAM-HANDOFF-2026-10-17.md`, `RUN-2-EXECUTION-SEQUENCE-2026-10-18.md` and `RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md` in MAIN's packet root are byte-identical to the copies in the canonical folder (they were copied on 2026-10-18). If a pair differs, keep MAIN's copy and record the difference; never overwrite an existing MAIN file. Also confirm the eleven SPEC files and `README.md` carry the 2026-10-18 Gate L banner and that `runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md` exists.
5. Confirm the wheel exists at `C:/Users/Pinda/Documents/Codex/2026-10-16/task/run2-fresh-session-20261017/g1-current-build/artifacts/mission_control-0.1.0-py3-none-any.whl` (do not install it) and that `.agents/skills/{coding-cli-jobs,claude-code-headless,codex-exec,cursor-agent-headless}` exist in MAIN.
6. Create `runs/RUN-2-CLOSE-STATUS.md` with the P0 record and the decisions table from section 1.
7. Commit the three copied documents and the status file (D7).

**Exit report:** actual model, HEAD/dirty set, overlay hash match, worktree count, dependency availability, the P1 lease you are about to take.

### P1 — Installation configuration source (U, one lease)

**Goal.** A `mission/v2` manifest variable `value_ref: config:<key>` resolves in production composition from a non-secret installation configuration, so the kit/environment side of a workflow is configurable per installation without secrets or code changes.

**Where the gap is.** `src/mission_control/bootstrap/manifests.py:129-131` builds `CatalogEnvironmentInputs(EnvironmentKitCatalog(catalog.definitions))` with no `config` mapping. The port already accepts `config: Mapping[str, str]` (`application/environments/kits.py:76-96`); the domain already validates `config:` refs (`domain/authoring/mission_environment.py:42,113-137`); admission already reports the pointed blocker (`application/authoring/manifest_v2_admission.py:313-341`).

**Design constraints for the implementer brief.**

- Read `src/mission_control/bootstrap/settings.py` (or wherever `Settings` lives) first and reuse its conventions. Prefer a typed, per-application, non-secret source: a checked-in file under `deployments/<app>/` referenced by one Settings field, or an existing installation-config structure if one exists. Do not read secrets, `.env` secret entries or the Secret Broker; do not add a database table (that would be a schema release).
- Keys matching `(?i)(key|token|secret|password|passwd|dsn|credential)` are refused at load **and** at compile with a pointed blocker; unknown keys stay blockers; values never appear in `ValidationReport`, resolution output, templates or logs (only the key name and a digest).
- Identical input gives an identical compile digest.
- Wire it only in the production composition and in the existing test composition helpers; no new fallback path.

**Lease.** `src/mission_control/bootstrap/manifests.py`; one new module `src/mission_control/bootstrap/installation_config.py` (or the Settings module if a field suffices); `tests/unit/authoring/test_manifest_v2_launch.py` (add cases) and one new test file beside it; `docs/knowledge/mission-manifest.md` and `docs/knowledge/environments.md` for the one-paragraph behavior note, then `python docs/tools/agents_docs_index.py` if a document was added. Everything else read-only.

**Tests.** Valid literal resolution; missing key blocker; secret-like key refusal at load and compile; stable digest across two compiles; override/inheritance unchanged; no value in any output. Commands (serial, bounded, from MAIN, existing `.venv`): `uv run --no-sync ruff check <changed files>`, `uv run --no-sync mypy` on the changed modules, `uv run --no-sync pytest tests/unit/authoring/test_manifest_v2_launch.py tests/unit/authoring/<new file>`, and `tests/unit/runtime/test_run2_worker_roles.py` if composition changed.

**Mechanics.** Launch one implementer agent with `isolation: "worktree"` and the brief in section 8. When it returns, read its diff yourself, then launch a fresh reviewer agent (section 8). Apply the reviewed patch to MAIN, rerun the exact tests once in MAIN, commit.

**Exit report:** diff summary, test results, reviewer findings and dispositions, commit hash.

### P2 — F0: full configuration compilation, zero native create (U, one lease)

1. **Catalog check first (read-only).** Through the existing read-only pool helper and principal used by the 2026-10-18 API checks, list the app-scoped published artifact schemas for AI Engineer 1.4.2. Record refs and digests. If no schema fits diagnosis/patch/review outputs, run the D5 seed release now: author the additive seed in a new slot, prove it on a disposable target (fresh, upgrade, repeat, drift, refusal, role), write the dry-run diff and backup/restore record, apply live to AI Engineer once, read back. All of D5's conditions must hold; if one fails, stop the release and mark the dependent criteria blocked. No owner contact.
2. Author the F1 manifest from `tests/fixtures/manifests/multi-provider/codex.stage-graph.mission.yml` (SHA256 `54ca8f2d14ac2977cf2425aabe988df221793988644836b446422df870bc74df`): repository = MAIN source checkpoint at the P1 commit; cognition = `plugin.cognition-sdlc@0.1.0#sha256:a57f772c4cb24e24fc84ae2aa14727a42f97d951aa918d85e8270abdc1216259`; roles = implementer plus `subagent.mc-cognition-reviewer` and `subagent.mc-cognition-test-runner`; one `value_ref: config:<key>` variable; output schemas = the refs from step 1; model/auth/host profiles by name only.
3. Compile and preflight the identical manifest twice through the normal services (an owned offline process is fine; no API startup is required for F0). Compare canonical digests.
4. Negatives, each on a copy: unknown config key; secret-like config key; absent required secret name; stale kit digest; wrong bundle digest; unsupported hook event; nonexistent report schema; required hard pause; provider-wide per-command approval on cursor_local; PHI data class on a hosted lane.
5. Write the F0 evidence rows named in the 2026-10-18 handoff (`configuration.inventory.json`, `compile.positive.json`, `preflight.positive.json`, `compile.repeat.json`, `negative.<case>.json`, `no-effects-observer.json`) into the session evidence directory and record their hashes in the status file.

**Exit report:** positive compile blockers = 0, repeat digest equal, negatives refused at the intended stage, schema decision (found / release prepared and awaiting owner go).

### P3 — G1: ordinary local serving without inference (D, one lease)

1. Compose from MAIN source with the P1 commit: API on WSL loopback with the existing sponsored grant; one base worker; one lane worker on private queues with the prepared prefix `mc-run2-g1-ai-engineer-<short HEAD>`; local Temporal (loopback, disposable); checkpoint saver and store verified with noDDL setup only; S3 HeadBucket only if the first mission needs S3.
2. Pre-serving observations: principal identity, queues never used, zero foreign pollers, component 1.4.2 with 37 receipts.
3. Zero-inference smoke: submit the F1 manifest with one deliberately unmet prerequisite and show the same typed `PREREQUISITES_UNMET` at preflight and at start; then submit the valid manifest and stop before any provider turn (controlled provider or no lane worker for that lane).
4. Independent pre/post observer calls; exact shutdown and reap recorded. Run the whole thing as one background shell task with an outer deadline.

**Exit report:** G1 receipt hash with identities, queues, grants, cleanup. S0 and F1 are unlocked.

### P4 — LS-07 remaining cells, then LS-08 (L, one lease)

1. Integrate the prepared Cursor missing-result receipt boundary (fresh-session preparation, seven regressions) under a reviewed lease so a nominal exit 0 with no result is retained truthfully. Then run the missing LS-07 Cursor CLI cell once, inside the LS Cursor slice released by D4.
2. LS-08, lead as caller: author one job set (a Codex fix and a Cursor review of the same small bounded change) in two isolated worktrees, launch `agentjob.py` as **one background shell task**, continue unaffected work, and when the completion notification arrives read both `result.json` files. Record: both results, runner-owned verification output, child cleanup, cost actual/unknown, and that the caller was this interactive Claude Code session.

**Exit report:** LS-07 cells pass/nonpass, LS-08 receipt. Do not retry a paid failure to resolve ambiguity.

### P5 — F1 + F3 + F4 as S0 cells (L, one lease per run)

Design one probe manifest so each run satisfies both the fixture rows and the S0 cell clauses: caller `missionctl wait` registered before terminal; one `interrupt_and_inject`; one forbidden tool path and one allowed test command; terminal completion with accepted output; a separate bounded clean-cancel run when the completion run cannot also supply it.

Run order and caller mechanics:

| Cells | Lane | Caller mechanics |
| --- | --- | --- |
| S0-01, then S0-10 (Cloud) | claude_agent_sdk | Lead session is the caller: register the wait as a background task, then submit/start. F1 mission content: review the P1 diff, run focused tests in the runner, produce diagnosis/patch/review artifacts against registered schemas, open the review gate. F3 observations and one F4 intervention on this run. |
| S0-04, S0-13 | claude_agent_sdk | Codex caller via `codex exec` (headless). Smaller control task is acceptable; lane already exercised. |
| S0-07, S0-16 | claude_agent_sdk | Cursor caller via `cursor-agent` (headless). |
| S0-02, S0-05, S0-08, then S0-11/14/17 | codex | Include the native Codex `before_tool` hook deny with trust (SPEC-02 §9). |
| S0-03, S0-06, S0-09, then S0-12/15/18 | cursor_local | Last. Only within the Q/S0 10 USD slice; preserve requested versus observed model and unknown dollars. |

Cloud cells switch Temporal to `mission-control-dev.ih0e7` with the existing API key; nothing is deployed. Update `FINAL-CAPABILITY-S0-18-CELLS.json` from receipts only. A failed or unrun cell stays failed or unrun.

**Exit report:** cells table (18 rows), F1/F3/F4 evidence rows for S0-01, spend per category.

### P6 — F2

Deferred (D6). Write one line in the status file and the summary; nothing else.

### P7 — Reconcile documentation in place

Update `FINAL-CAPABILITY-S0-18-CELLS.json`, the issue appendix statuses that the receipts actually close, and the F5 index (one row per SPEC/issue criterion to one evidence source with status). Add the Gate L disposition paragraph to `RUN-2-CLOSE-STATUS.md` and a two-line pointer at the top of the packet `README.md`. Run `python docs/tools/agents_docs_index.py --check`, `check_links.py`, `validate_okf.py`.

### P8 — Final checks, worktree reconciliation, merge, summary

Final checks at the integrated source (serial, one lease): `uv run --no-sync ruff check .`, authoritative `uv run --no-sync mypy`, `uv run --no-sync ty check`, `uv run --no-sync deptry src`, architecture tests, schema/seed/skills checks, the docs checks. Then section 5, then section 6. Rebuild the wheel from the final commit through the normal release process and record its identity; do not deploy it.

## 5. Worktree reconciliation and merge into main

**Verified starting facts (2026-10-18).** `git branch --no-merged main` is empty: every branch is already an ancestor of `main`. What remains is uncommitted bytes. Comparing each worktree's dirty files against MAIN's working tree:

| Worktree | Branch | Dirty files | Against MAIN |
| --- | --- | --- | --- |
| `platform/mission-control` (canonical) | `mo/run2-integration` | 69 | 62 identical; 5 differ (`docs/knowledge/index.md`, `src/mission_control/application/programs/service.py`, three dated planning docs); 2 missing in MAIN (the two 2026-10-17/18 documents, copied in P0). In `programs/service.py` MAIN is the newer side (it carries the completion-replay dedupe from commit `d106d0c7`). |
| `task/run2-completion-offline` | `mo/run2-completion-offline-20261016` | 65 | 61 identical; 4 differ (same `service.py` and three planning docs). Holds ignored private recovery evidence; **never remove this worktree.** |
| `task/run2-completion-replay-fix` | `mo/run2-completion-replay-fix-20261017` | 0 | Clean. |
| `.worktrees/run2-cli` | `mo/run2-cli` | 378 | 342 identical; 36 differ (Codex adapter/launcher/protocol, describe, Codex tests, `.agents/skills/coding-cli-jobs/**`, `codex-exec` skill). |
| `.worktrees/run2-cursor` | `mo/run2-cursor` | 29 | 9 identical; 20 differ (Cursor adapters, frames repository, lane_turns, lanes domain, Cursor tests). |
| `.worktrees/run2-events` | `mo/run2-events` | 20 | 3 identical; 17 differ (ingress drainer/launch/bootstrap, cursor_costs, operation workflow, their tests). |
| `.worktrees/run2-admission-failure`, `run2-closed-workflow-recovery`, `run2-human-control-budget` | own branches | 1 each | Only an untracked `.ty-run2-worktree.toml` tooling file. |
| `.worktrees/run2-claude-host-proof`, `run2-cursor-c9` | own branches | 0 | Clean. |

**Procedure (lead-owned, serial, after P7 is committed in MAIN).**

1. **Three-way classify every differing file** in `run2-cli`, `run2-cursor`, `run2-events`, the canonical folder and the offline checkout. For each: `A` = file in that worktree's HEAD, `B` = that worktree's working copy, `C` = MAIN HEAD. Compute `diff A B` (the uncommitted edit) and `diff B C`. Classify:
   - **already integrated**: `B == C`, or `diff A B` is a subset of `diff A C` (main already has the edit). Nothing to do.
   - **main newer**: `C` strictly extends `B` (as in `programs/service.py`). Nothing to adopt; record it.
   - **unique**: the worktree carries an edit that `C` lacks. Produce a patch of exactly that hunk set, review it with a fresh reviewer agent against the owning issue criteria, apply to MAIN, run the leased tests, commit with the originating branch named in the message.
   - **conflicting**: both sides changed the same hunks. Resolve in MAIN by hand, preferring the behavior that has a passing test and a receipt; never delete a test to make it pass; record the resolution in the status file.
2. For the three planning docs that differ in canonical and offline (`RUN-2-COMPLETION-ASSESSMENT`, `RUN-2-COMPLETION-PLAN`, `RUN-2-QUALIFICATION-ENVELOPES`), compare and keep MAIN's version if it is a superset; otherwise merge the missing paragraphs into MAIN's copy. For `docs/knowledge/index.md` keep MAIN's and regenerate the index check.
3. **Commit everything owned in MAIN**, including the 16 planning/evidence files, the `cursor_bridge_recovery.py` overlay (if not committed in P1) and the status file. `git status` in MAIN must show nothing except ignored files.
4. **Side worktrees.** For each worktree whose branch is an ancestor of `main` and whose dirty set is now fully classified as integrated or main-newer: delete the stray `.ty-run2-worktree.toml`, confirm `git status --short --ignored` shows no ignored evidence you need, then `git worktree remove <path>` and `git branch -d <branch>` from the canonical repository. If any ignored evidence exists, move it to `C:/Users/Pinda/Documents/Codex/2026-10-16/task/retained-worktree-evidence/<name>/` first and record the move. Never remove `run2-completion-offline`.
5. **Canonical folder onto `main`.** `main` is checked out in MAIN, so the canonical folder cannot switch until MAIN is removed:
   - Confirm MAIN has zero unique bytes (step 3) and that any ignored evidence in MAIN has been moved out.
   - Remove the `.venv` **junction** in MAIN with `cmd /c rmdir "C:\Users\Pinda\Documents\Codex\2026-10-16\task\run2-final-main\.venv"` (this removes the link only; a recursive delete through the junction would destroy the canonical `.venv`). Verify the canonical `.venv` is intact.
   - `git worktree remove` MAIN from the canonical repository.
   - In the canonical folder: its 69 dirty files are now either identical to `main` or main-newer. Stage nothing; run `git checkout main` only after `git stash list` is empty and `git status` shows only files that are byte-identical to `main` or whose edits are recorded as integrated (checkout will refuse otherwise; resolve by committing the reviewed unique bytes on `mo/run2-integration` and merging them into `main` first, never by `checkout --force`, `reset --hard` or `clean`).
   - Result: canonical folder on `main`, `git status` clean except ignored files, `git log main..mo/run2-integration` empty, then `git branch -d mo/run2-integration`.
6. **Final verification:** `git worktree list` shows the canonical folder on `main` plus `run2-completion-offline`; `git branch --no-merged main` is empty; `git status --short` is empty in both; `git fsck --no-dangling` is clean; the final checks of P8 pass at the final `main` commit; the session evidence directory still contains every receipt referenced by the status file.

No push. `origin/main` stays behind by design until the owner pushes.

## 6. Completion summary (required final message and file)

Write `docs/specs/archive/materialization-observation-2026-10/runs/RUN-2-COMPLETION-SUMMARY-2026-10.md` in the canonical folder on `main`, commit it, and send its content as the final message. It must contain, in this order:

1. **Outcome in one paragraph:** Run 2 closed at Gate L on `main` commit `<hash>`; what passed, what did not.
2. **Decisions applied:** the D1–D7 table from section 1 with any owner go/no-go received during the run (schema live apply).
3. **Acceptance delta:** the 38/41/18/12/1 counts before, the counts after, and the list of issue IDs whose status changed with the evidence file that closed each. S0 cells: 18 rows with passed/failed/blocked/unrun. LS-07/08 disposition. F0/F1/F3/F4 pass/fail; F2 deferred.
4. **Source identity:** final `main` commit, overlay hashes, rebuilt wheel SHA256 and build id (uninstalled), files changed per phase.
5. **Checks:** every check command with passed/failed/blocked/unrun, run at which commit.
6. **Worktree reconciliation:** the table from section 5 updated with what was integrated, main-newer, unique-adopted or conflict-resolved per worktree; which worktrees and branches were removed; where any evidence was moved.
7. **Spend:** per category and slice, actual/estimated/unknown, with the D4 release recorded; reservations still held.
8. **Open streams carried forward:** R, S1, S2, S3, funding-held S4 (HL-01/02/03/10/14/15/16/20), deferred 13, F2, AF-FOLLOWON-01, and anything from P1–P8 that stayed blocked, each with the exact gate that blocks it.
9. **Private evidence locations** by directory, no contents.
10. **What the next program should read first.**

## 7. Copy-paste lead prompt

~~~text
You are the lead for closing the Mission Control Run 2 sprint. Model: you must be Claude Code on
claude-opus-5-5; report the actual model in your first message and stop if it is different.

Read first, in order:
1. docs/specs/archive/materialization-observation-2026-10/RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md
   in C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control (copy it and the two companions
   it names into this checkout's packet root in P0; they exist only in the canonical folder).
2. docs/specs/archive/materialization-observation-2026-10/RUN-2-EXECUTION-SEQUENCE-2026-10-18.md (same place).
3. runs/RUN-2-FUNDAMENTAL-CAPABILITIES-HANDOFF-2026-10-18.md in this checkout, sections 1, 5, 7, 8, 12
   and the eleven SPEC checklists.
4. The 2026-10-17 handoff for roots, dependencies and budgets; then this repository's AGENTS.md files.

Owner decisions are recorded in the instructions file, section 1: Run 2 closes at Gate L; Claude Code
Opus 5.5 is the implementer; native local-lane fixtures are authorized within the fresh ceilings and
10 USD slice caps; release the stale 10 USD Cursor LS hold on the recorded dashboard evidence; the
report-schema seed release is approved end to end including live apply to AI Engineer, strictly under
the D5 conditions (additive new slot, disposable proofs pass, dry-run diff and backup record first,
idempotent apply, readback); F2 is deferred; local commits and local main merges are authorized; no
push, no deployment, no S4 release. I am away for the whole run: never ask me anything; record any
uncovered decision as blocked and continue. I will not be available for authentication either:
Claude Code and Codex are authenticated on this machine; CURSOR_API_KEY, CURSOR_EMAIL,
CURSOR_PASSWORD, ANTHROPIC_API_KEY and OPENAI_API_KEY are in the canonical folder's git-ignored .env
(read names, never print values). If an authentication blocker appears, document the deficiency,
mark the affected cells blocked and move on. Subagents may be claude-opus-5-5 or claude-sonnet-5-5;
choose for efficiency (Opus for source/SQL/seed/merge work and its review, Sonnet for exploration,
evidence assembly, parsing, doc tables and bounded test runs). Implement the installation
configuration source directly (P1) and make F1 the review of that diff.

Operate exactly per section 3: lead plus one implementer agent, fresh-context Opus reviewer (never a
fork), worktree isolation for writers, one heavy job at a time as a background task, memory floors,
no Workflow fan-out, private receipts outside the repository, one in-place status file. You are the
native Claude Code caller for LS-08 and for S0 cells 01/02/03/10/11/12.

Never touch any consumed fence, recovery host, registry initializer or terminal SQL; A1 is complete.
Never rerun the Cursor login, raise the Cursor on-demand limit, or repeat a paid failure to resolve
ambiguity. Report at each phase exit and on any stop rule, then continue unaffected work.

Finish with section 5 (every worktree reconciled and merged into main, conflicts resolved, canonical
folder on main, only the offline evidence worktree retained) and section 6 (completion summary file
and message). Start with P0 now and give me the first checkpoint before taking the P1 lease.
~~~

## 8. Agent briefs

Model selection per brief: source/SQL/seed/manifest/merge writers and their reviewers run on Opus 5.5 (no override); exploration, evidence assembly, parsing, documentation tables and bounded test execution run on Sonnet 5.5 (`model: "sonnet"`). State the model in the brief's first line.

Implementer (Agent tool, `general-purpose`, `isolation: "worktree"`, Opus 5.5 for source work):

~~~text
Implement <phase/lease name> for Mission Control Run 2. Base: main at <HEAD>; planning overlay
hashes: <list>. Read AGENTS.md at the repository root and the scoped AGENTS.md closest to each
file you touch. Criteria: <issue IDs and exact clauses>. Dependency evidence already present:
<files/tests/receipts>. Already implemented (do not duplicate): <list>.
Writable files: <exact paths>. Everything else is read-only.
Behavior to add: <bounded statement>. Preserve: <invariants>. Exclusions: <non-goals>.
Checks you may run, serially, each with an outer timeout: <exact commands>. No installs, no
network, no provider calls, no database or Temporal, no Git commits.
Deliver: the diff, per-criterion evidence, check results passed/failed/blocked/unrun, anything you
could not resolve. Stop and report if the base changes, the lease is insufficient, or scope grows.
~~~

Reviewer (Agent tool, `general-purpose`, fresh context, read-only, Opus 5.5 for source patches):

~~~text
Review this diff read-only: <patch path> against base <HEAD> with overlay <hashes>, for
criteria <IDs/clauses>. Read the changed files, their callers and tests. Check: scope fits the
lease; production wiring is real (not test-only); negatives exist; no secret value can reach
outputs or logs; digests/idempotency/fences preserved; tests assert behavior, not mocks. Distinguish
defect, missing evidence and suggestion. Report file:line, severity, smallest correction. Do not
edit files, run providers, or trust the author's summary over the code.
~~~

## 9. What this file does not do

It does not authorize pushes, deployments, the schema live apply, S4 funding or
any remote stream. It does not alter SPEC, issue or ledger text. Where it and
the 2026-10-18 handoff disagree on procedure detail, the handoff's F0–F5 text
governs the proof content and this file governs the Claude Code mechanics.
