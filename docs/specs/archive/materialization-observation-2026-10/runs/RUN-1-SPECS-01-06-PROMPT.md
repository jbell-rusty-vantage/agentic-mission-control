ultracode

# Run 1 of 2: implement SPEC-01 to SPEC-06 of the materialization-observation sprint

You are the **lead and integrator** of an agent team. Implement every in-scope issue for specifications SPEC-01 to SPEC-06, verify each one adversarially, integrate them on one branch, and hand a clean, evidenced result back to the owner. Run 2 (SPEC-07 to SPEC-11) starts from your result, so leave its seams exactly as described below.

## 1. Where you are

- **Repository:** `C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control`. This is the Git repo; the parent `BellLabs` folder is an umbrella, not a repo.
- **Machine:** Windows 11, with PowerShell and Git Bash. WSL2 Ubuntu is available for the Linux-only lanes. Docker Desktop runs local PostgreSQL and Temporal.
- **Base commit:** `origin/main` at the commit that added this file (`git log -1 --format=%H -- docs/specs/archive/materialization-observation-2026-10/runs/RUN-1-SPECS-01-06-PROMPT.md`). Fetch first, and confirm the main checkout is clean and equal to that commit.
- **Packet:** `docs/specs/archive/materialization-observation-2026-10/`. Paths below are relative to the repo root unless stated.
- **Secrets:** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CURSOR_API_KEY`, `DAYTONA_API_KEY` and the database DSNs live in `.env`. Load them into process environments when needed. **Never print, cat, echo, log or commit them.**

## 2. Read before dispatching anything

1. `AGENTS.md` (repo root), then the closest scoped `AGENTS.md` before any edit: `src/mission_control/{domain,application,adapters,adapters/temporal,adapters/postgres,adapters/deep_agents,bootstrap,contracts,interfaces}/AGENTS.md`, `packages/mission-control-db-contract/AGENTS.md`, `integrations/biotech/AGENTS.md` and `tests/AGENTS.md`. Also `GLOSSARY.md` and `docs/DEVELOPMENT.md`.
2. The packet, in order:
   - `README.md`
   - `SPRINT.md`: authoritative scope, with the definitions of done for S1, S2 and S3
   - `DECISIONS.md`: R1 to R33, corrections C1 to C3; read R27 to R33 closely
   - `TEAM-WORKSPACE.md`: roles, writable regions, frozen paths, migration slots, claims and handoffs, authorization
   - `PLAN.md`: waves and critical paths
   - `ISSUES.md`
   - `GAP-REPORT.md`: the starting state, gaps G1 to G25
3. **The specifications in scope:**
   - `SPEC-01-environments.md`
   - `SPEC-02-cognition.md`
   - `SPEC-03-workspaces-and-placement.md`
   - `SPEC-04-watchers-and-callbacks.md`
   - `SPEC-05-owner-prerequisites.md`
   - `SPEC-06-hosted-api-lanes.md`
4. **Specifications you touch at a seam:**
   - `SPEC-10-ingress-on-vercel.md` §1–§5 (MO-40 only);
   - `SPEC-09-local-harness-path.md` §2–§3 (worker roles and queues);
   - `SPEC-11-remote-worker-on-aws.md` §3 (queue layout you must not contradict).
5. **Background on the hosted lanes:** `MANAGED-AGENTS-REMOTE-PATH.md` §2–§3. Its request shapes are sketches until HL-23 confirms them.
6. **Evidence:** each issue's spec cites its research. The main files are:
   - `research/anthropic-managed-agents.md`
   - `research/openai-hosted-agents.md`
   - `research/codebase-materialization.md`
   - `research/codebase-observation.md`
   - `research/codebase-new-lanes.md`
   - `research/cursor.md`
   - `research/claude-code.md`
   - `research/codex.md`
   - `research/vercel-ingress.md` (for MO-40's SQL)
7. **Each issue file** in `issues/`. Its `Blocked by` line is authoritative.
8. **Spec precedence on conflict:** `mission-control-general/` spec pack > `docs/adr/` > `docs/knowledge/` > `docs/specs/archive/mc-surfaces-2026-10/docs/MISSION_CONTROL_IMPLEMENTATION_STATUS.md`. Report any conflict. Search concepts with `python docs/tools/okf_search.py "<terms>"`.

## 3. Scope: 49 issues

These are the 47 in-sprint, non-funding-gated issues whose spec is SPEC-01 to SPEC-06, plus two prerequisites from outside that range: **HL-23** (provider smoke) and **MO-40** (Signal Ingress service and SQL). Issue files are `docs/specs/archive/materialization-observation-2026-10/issues/<ID>-*.md`. Waves follow `PLAN.md`; inside a wave, respect `Blocked by`.

### Wave A

| Issue | Title | Stream | Blocked by |
| --- | --- | --- | --- |
| MO-01 | Compose bundle custody into every production capability rows resolver | Integrator | — |
| HL-05 | Lane conformance suite for every lane | Integrator | — |
| HL-06 | Profile vocabulary for claude_managed and codex_agents, data class, ADR-0050 (**slot 0036**) | Integrator | HL-05 |
| MO-04 | Allowlisted child environments for local provider processes | Runtime | — |
| MO-05 | All local lanes use WorkspaceAllocator with manifest policy and cleanup | Runtime | — |
| MO-06 | Compose cursor_cloud with env resolver and workspace lease in production | Runtime | — |
| MO-03 | Back Codex kernel hooks and handle Codex hook trust | Runtime | MO-01 |
| MO-73 | Verify Claude SessionStore restore with the custom transport | Runtime | — |
| MO-02 | Additive instruction layering and structural config merge | Environment | MO-01 |
| MO-08 | WSL2 worker runbook and host preflight for local Claude and Codex lanes | Environment | — |
| HL-04 | Extract the Remote Session Lane base from cursor_cloud | Hosted | — |
| HL-23 | Provider smoke: Managed Agents and Agents API field confirmation (**paid, under $1 each**) | Hosted | — |

### Wave B

| Issue | Title | Stream | Blocked by |
| --- | --- | --- | --- |
| MO-10 | mission/v2 environment additions with validation and binding population | Integrator | MO-01 |
| MO-16 | Persist environment preparation records and readiness levels (**slot 0037**) | Integrator | MO-10 |
| HL-18 | Data-class policy enforcement and session retention | Integrator | HL-06 |
| MO-11 | Secret Broker port, sources, minting, per-lane delivery and redaction (**L; on the critical path, start first**) | Environment | MO-04 |
| MO-12 | Environment Kit capability kind, mission layer and bootstrap entrypoint | Environment | MO-01, MO-10 |
| MO-14 | Git write path: scoped credentials, pre-push guard, repo_pr effect, head SHA artifacts | Environment | MO-05 |
| MO-15 | Network policy resolution and per-lane projection | Environment | MO-10 |
| MO-13 | Cursor environments and secrets REST adapter with environment.json ownership check | Runtime | MO-11, MO-12 |
| MO-40 | Signal Ingress service, SQL functions and migration 0035 (**slot 0035**; see §4) | Events | MO-11 |
| MO-43 | Wake channels: missionctl wait, inbox long-poll, MCP inbox_wait, auto-subscribe | Events | — |
| HL-17 | Provider webhooks into Signal Ingress as wake signals (fixtures only) | Events | MO-40 |
| HL-07 | claude_managed prepare from pack files | Hosted | HL-06, HL-23 |
| HL-08 | claude_managed session lifecycle and frame classifier | Hosted | HL-04, HL-07 |
| HL-09 | claude_managed approvals, Mission Control custom tools and publication | Hosted | HL-08, MO-14 |

### Wave C

| Issue | Title | Stream | Blocked by |
| --- | --- | --- | --- |
| MO-21 | missionctl preflight and PREREQUISITES_UNMET launch refusal | Integrator | MO-20 |
| MO-20 | Owner prerequisite store and generated paste-ready content (**slot 0038**) | Environment | MO-12 |
| MO-22 | missionctl setup wizard, probe missions and attestations | Environment | MO-21 |
| MO-30 | Per-lane layout table and full cognition projection | Environment | MO-01, MO-02 |
| MO-32 | Plugin expansion into constituent kinds for every lane | Environment | MO-30 |
| MO-33 | Ambient cognition inventory and policy | Environment | MO-30 |
| MO-35 | Publish Cognition Profiles for SDLC, knowledge and mixed work | Environment | MO-30 |
| HL-19 | Owner prerequisites and probes for API lanes | Environment | MO-20 |
| MO-31 | Evidence-based hook event mapping and Cursor binding v2 | Runtime | MO-03 |
| MO-34 | Discovery proof per lane | Runtime | MO-30 |
| MO-41 | Telemetry Hook Pack, mc-signal CLI and signal_emit tool | Events | MO-40, MO-30 |
| MO-42 | Gate hooks and remote stop fence | Events | MO-41 |
| MO-44 | Watchers: schema, compiled descriptors, evaluator, actions, boundaries (**slot 0039**, if needed) | Events | MO-43 |
| HL-11 | codex_agents prepare from pack files | Hosted | HL-06, HL-23 |
| HL-12 | codex_agents session lifecycle, recovery recipe and frame classifier | Hosted | HL-04, HL-11 |
| HL-13 | codex_agents function-tool effect gating and custody | Hosted | HL-12, MO-14 |
| HL-21 | Hosted lanes: full Cognition Pack and Secret Broker projection | Hosted | HL-07, HL-11, MO-30, MO-11 |

### Wave D

| Issue | Title | Stream | Blocked by |
| --- | --- | --- | --- |
| MO-50 | Generalised cloud branch preparation with large-input references | Environment | MO-11, MO-12, MO-30 |
| MO-51 | Knowledge workspaces and output channels | Environment | MO-40, MO-50 |
| MO-52 | Placement limits, fan-out admission and lane preference | Runtime | MO-21 |
| MO-45 | External signal sources: GitHub, Cursor v0 webhook, schedules, worker watches (fixtures) | Events | MO-40, MO-44 |
| MO-46 | Standard watcher library | Events | MO-44 |
| MO-47 | Observe skill v2 and router/author skill updates | Events | MO-43, MO-44 |

**Critical path first:** MO-04 → MO-11 → MO-40 → (HL-17, MO-41). HL-05 → HL-06 → HL-07 (with HL-23) → HL-08 → HL-09 (with MO-05 → MO-14). Then HL-11 → HL-12 → HL-13. MO-01 → MO-02 → MO-30 unblocks most of wave C.

## 4. Out of scope, and the seams you leave for run 2

**Do not implement:**

- CM-* (SPEC-07), LS-* (SPEC-08), MO-63 to MO-72 (SPEC-09), MO-74 to MO-76 and MO-79 (SPEC-10), MO-77 and MO-78 (SPEC-11);
- the drills HL-24 and HL-25;
- MO-07;
- HL-20 and every issue marked `Gate: funding`: HL-01, HL-02, HL-03, HL-10, HL-14, HL-15, HL-16;
- everything `sprint: deferred`.

If an in-scope issue truly needs one of these, stop that issue, record the blocker with evidence, and continue elsewhere.

**Seams:**

- **MO-40.** Build the application ingress service, HTTP router, SQL functions and **migration 0035**, with real local PostgreSQL tests. **Do not** create or deploy the Vercel project (MO-74, run 2).
  - Include the **`mission_request` inbox kind and the `mission_request` credential purpose** in 0035 now, so run 2's launch route (MO-79, DECISIONS R29) needs no new SQL.
  - The drainer (MO-75) is run 2. Leave inbox rows consumable by it per SPEC-10 §4.
- **Release 1.4.0.** Slots 0035 (MO-40), 0036 (HL-06), 0037 (MO-16), 0038 (MO-20) and 0039 (MO-44, if needed) all land in this run, in `packages/mission-control-db-contract` only.
  - Prove them on the disposable cluster and on real local PostgreSQL.
  - Build release 1.4.0 at the end of the run.
  - **Do not apply it to the live Supabase projects.** MO-74 does that in run 2 under `docs/specs/archive/mc-surfaces-2026-10/docs/qualification/two-project/LIVE_PLAN.md`.
- **Hosted lanes (HL-07 to HL-13).**
  - Develop against fakes first, and pass the lane conformance suite (HL-05) before merging.
  - Run live drills **from the local worker on local Temporal**. The remote drills through the AWS worker are HL-24 and HL-25 in run 2.
  - Put pack files under `deployments/hosted-packs/ai-engineer/{claude_managed,codex_agents}/` (application **AI Engineer**, data class `internal`).
  - Route both hosted lanes to task queue `mc-ai-engineer-lane-hosted` in bindings, per SPEC-11 §3.
- **HL-17 and MO-45.** Signed fixture deliveries only. No webhook is registered with any provider in this run.
- **Temporal.** All runtime and persistence proofs use **local Temporal** (`make temporal-up`). Temporal Cloud is run 2 (MO-78).

## 5. Engineering rules (from AGENTS.md and the packet)

- **Layering.**
  - Interfaces call application handlers. Application uses domain rules and ports. Adapters implement ports. Bootstrap wires them.
  - The domain imports no database, Temporal, FastAPI or provider SDK.
  - One distribution imports `mission_control` from `src/mission_control`.
- **Runtime authority.**
  - Temporal alone schedules.
  - Reducers own lifecycle and settlement. Signals and provider outcomes are evidence, never authority.
  - Accepted command, delivered signal and applied effect are distinct.
- **Reuse, don't fork:** Host Projection, WorkspaceAllocator, coordinator inbox, frame store, outbox.
- **Shared SQL** lives only in `packages/mission-control-db-contract`, in the allocated slots.
- **Frozen shared paths** (TEAM-WORKSPACE) are integrator-only. Specialists send the integrator a patch.
- **Do not invent** provider bindings, schemas, grants, model ids or environment ids.
- **Lanes.**
  - Every lane passes the lane conformance suite before merge.
  - `qualified=True` needs a cited live record for that exact profile and placement; fake evidence never qualifies.
  - No organisation API key in any sandbox, image or committed file.
- **ADRs.** When an issue starts that implements one of ADR-0042 to ADR-0053 (DECISIONS "Proposed ADRs"), the integrator writes it under `docs/adr/` as `proposed`.
- **Verify.**
  - `make check` (ruff, ty, deptry, architecture and unit tests), or `uv run ruff check .`, `uv run mypy` (authoritative) and the relevant `uv run --group biotech pytest` selections.
  - Persistence and runtime claims use **real local PostgreSQL and Temporal**.
  - Report **passed, failed, blocked and unrun** separately. Never claim a check you did not run.
- **WSL.** Linux-only lanes run from WSL with a separate venv (`UV_PROJECT_ENVIRONMENT=$HOME/.venvs/mission-control`). Never sync into the Windows `.venv` (SPEC-09 §2). Build ids must match.

## 6. How to run the team

1. **Load the `workflow-authoring` skill** before writing any workflow script.
2. **Branches.**
   - Create the integration branch `mo/run1-integration` from the base commit.
   - Every issue gets its own worktree and branch `mo/<issue-id>-<slug>` from the current integration head. Use agent worktree isolation where available, otherwise `git worktree add` under `C:\Users\Pinda\Proyectos\BellLabs\platform\.worktrees\mc-run1\`.
   - Check for branch and worktree collisions first. Never reset, stash or clean someone else's work.
3. **Claims and handoffs.** In the **main checkout** (`.scratch/` is git-ignored):
   - write `.scratch/materialization-observation-2026-10/<ISSUE>/CLAIM.md` before work starts: issue, role, base commit, worktree, writable paths, blockers, planned tests, account dependencies;
   - write `HANDOFF.md` after: changed files and contracts, exact commands with passed, failed, blocked and unrun results, drill records, usage disposition, unresolved facts, follow-ups.
4. **Per wave:**
   - Run one implementing agent per unblocked issue, in parallel, with disjoint writable regions per the TEAM-WORKSPACE roles.
   - Follow each with an **adversarial verification agent**. It re-runs the checks, reads the diff against the issue's acceptance list and the spec, and tries to break the claim.
   - Only verified issues are merged, by you, into `mo/run1-integration`. Run `make check` plus the affected integration tests on the integration head after each merge batch.
   - Fix forward. Do not merge a red integration head.
5. **Conflicts.**
   - Serialize changes to frozen paths through you.
   - Keep the migration slots exactly as allocated: 0035 MO-40, 0036 HL-06, 0037 MO-16, 0038 MO-20, 0039 MO-44.
6. **Push** `mo/run1-integration` (and issue branches if useful) to `origin` at the end of each wave, so progress survives the session.
7. **Owner check-ins.** At the end of each wave, write a short status: issues merged or blocked, spend per budget, anything the owner must do. Continue without waiting unless an owner decision is required.

## 7. Authorization for this run (granted by the owner)

**Allowed without asking:**

- Local code, tests and docs in worktrees.
- Commits on `mo/*` branches, and **pushing `mo/*` branches to `origin`**.
- Local Docker PostgreSQL, Redis and Temporal. The WSL toolchain install for MO-08.
- Read-only provider API calls.
- **Paid calls, stopping at the budget and reporting:**
  - HL-23 smokes: under $1 per provider.
  - `claude_managed` live drills (HL-07 to HL-09): from the **S2 $10** budget, model `claude-sonnet-5-5`.
  - `codex_agents` live drills (HL-11 to HL-13): from the **S3 $10** budget, model `gpt-6-luna`, **only after HL-09's live drill passes** (R27). If the Agents API refuses `gpt-6-luna`, stop and ask; do not substitute.
  - Cursor API calls for MO-13 and MO-34: from the **S1 $10** budget, model `default` (Auto).
- Every created provider resource (agents, environments, vaults, skills, sessions) is labelled with metadata `mc_run` and deleted or archived after custody.

**Ask the owner first:**

- merging or pushing to `main`;
- any Vercel project or deployment;
- any AWS action;
- Temporal Cloud;
- any live Supabase change or migration;
- registering webhooks;
- creating the GitHub App;
- publishing to Linear;
- a different model, or exceeding a budget;
- any funding-gated (S4) issue.

**Never:**

- print or commit secrets;
- forward the Mission Control bearer token;
- put organization API keys into sandboxes, images or pack files;
- run destructive operations on volumes or databases you did not create for this run.

## 8. Definition of done for run 1

1. Each of the 49 issues is either **merged into `mo/run1-integration` with every acceptance item checked and evidenced**, or **explicitly blocked** with the blocker, the evidence and the smallest next step.
2. `make check` passes on the final integration head. The real local PostgreSQL and Temporal suites behind persistence and runtime claims pass. The lane conformance suite passes for every existing lane plus the `claude_managed` and `codex_agents` fakes.
3. Migrations 0035 to 0039 are proven on the disposable cluster and on local PostgreSQL. Release 1.4.0 is built, **not** applied live. 0035 contains the `mission_request` kind and purpose.
4. **Live evidence recorded:**
   - the HL-23 smoke results in `research/provider-smoke-2026-10.md`, with every packet doc corrected where a field differed;
   - the `claude_managed` approval round trip and bundle publication drill;
   - the `codex_agents` function-tool approval and recovery drill, if reached within budget;
   - usage disposition (spent, estimated or unknown) per budget.
5. **A run report, committed on the integration branch** at `docs/specs/archive/materialization-observation-2026-10/runs/RUN-1-REPORT.md`, containing:
   - a per-issue status table (merged or blocked, branch, commit, evidence link);
   - commands and results by category;
   - spend per budget;
   - contracts and schemas changed, and ADRs written;
   - spec corrections made;
   - **what run 2 (SPEC-07 to SPEC-11) must know**: the seams in §4, open questions answered or still open (Q-M1 to Q-M3, Q-O2 to Q-O4), and anything that changes run 2's issues.
6. `mo/run1-integration` is pushed to `origin`. **Do not merge it to `main`.** Tell the owner it is ready for review and merge, with the report link.
