---
type: Agent Configuration
title: "Agent team workspace: ownership, frozen paths, migration slots, claims, handoffs and kickoff for the materialization-observation sprint"
description: "How the owner's agent team executes SPRINT.md: roles and writable regions, integrator-only shared paths, allocated SQL migration slots, worktree and branch rules, claim and handoff records, dispatch order by slice, authorization boundaries and a tool-neutral kickoff prompt."
tags: [mission-control, agents, implementation, sprint]
---

# Agent team workspace

**Run 2 authority:** the original dispatch/migration prose below is historical. Use [RUN-2-HANDOFF](runs/RUN-2-HANDOFF.md), [approved amendments](runs/RUN-2-PLANNING-AMENDMENTS.md) and [Codex kickoff](runs/RUN-2-AGENT-TEAM-KICKOFF.md); do not redispatch completed Run 1 issues or reuse occupied migration slots.

The team executes [SPRINT.md](SPRINT.md) using the issues marked `sprint: in` in [ISSUES.md](ISSUES.md). This document does not launch the team.

## Reading order for every agent

1. Root and scoped `AGENTS.md` (the closest one before editing). `GLOSSARY.md`.
2. This packet: [README](README.md), [SPRINT](SPRINT.md), [DECISIONS](DECISIONS.md), the spec named by the issue, and the research files that spec cites.
3. The issue file. Its `Blocked by` list is authoritative; "ready-for-agent" does not override blockers.
4. Recheck `git status` and HEAD. The owner's tree was checkpointed to `origin/main` on 2026-10-12 (R19). Never reset, stash, clean or overwrite someone else's changes.

## Roles and writable regions

There is one writable owner per region. Shared paths are integrator-only unless the integrator leases them in a claim.

| Role | In-sprint issues (owner field in `issues.json`) | Writable region |
| --- | --- | --- |
| **Integrator** (20) | HL-05, HL-06, HL-18, HL-20, HL-24, HL-25, MO-01, MO-07, MO-10, MO-16, MO-21, MO-67 to MO-72, MO-74, MO-77, MO-78 | Shared contracts and enums, manifest v2, bindings, bootstrap composition, preflight, CLI, migrations and release metadata, schemas, docs index, `deployments/ingress-vercel/`, `deployments/worker-aws/`, `deployments/hosted-packs/`, `scripts/temporal_cloud/`, `docs/qualification/hosted/`, AWS resources of SPEC-11 §4 |
| **Runtime** (26): local lanes and Cursor | CM-01 to 05, CM-07 to 10, CM-13, CM-18, CM-19, CM-21, MO-03 to 06, MO-13, MO-31, MO-34, MO-52, MO-63 to 66, MO-73 | `adapters/{claude,codex,cursor}/`, harness services they own, worker roles, Temporal activities they own |
| **Hosted** (14): API lanes and sandboxes | HL-02, HL-04, HL-07 to 16, HL-21, HL-23 (HL-02, HL-10, HL-14 to 16 are funding-gated) | `adapters/{remote_session,anthropic_managed,openai_agents,sandboxes}/`, new lane composition modules (shared registrations go through the integrator), `scripts/provider_smoke/`, pack-file schemas (pack contents in `deployments/hosted-packs/` are leased from the integrator) |
| **Environment** (17) | HL-01, HL-03 (both funding-gated), HL-19, MO-02, MO-08, MO-11, MO-12, MO-14, MO-15, MO-20, MO-22, MO-30, MO-32, MO-33, MO-35, MO-50, MO-51 | `application/{secrets,environments,prerequisites,agentic_components}/`, `adapters/secrets/`, `domain/capabilities/layouts.py`, catalog seeds, the Model Gateway, WSL toolchain scripts |
| **Events** (12) | HL-17, MO-40 to 47, MO-75, MO-76, MO-79 | `application/{signals,watchers,subscriptions}/`, `interfaces/http/ingress.py`, `interfaces/mcp/` (wait tools), the drainer, skills `mc-signals` and `mission-control-observe` |
| **Skills** (8) | LS-01 to LS-08 | `.agents/skills/{coding-cli-jobs,claude-code-headless,codex-exec,cursor-agent-headless}/` only. **No imports from `mission_control`.** |

**Frozen shared paths (integrator-only):**

- `domain/execution/lanes.py`, `domain/execution/bindings.py`, `domain/capabilities/host_support.py`, `domain/capabilities/hooks.py`;
- `domain/authoring/manifest.py`, `manifest_v2.py`;
- `application/frames/kinds.py`, `application/execution/harness/describe.py`;
- all of `bootstrap/`;
- `pyproject.toml`, `uv.lock`;
- `packages/mission-control-db-contract/**` (release metadata and migrations);
- public schema and SDK generation;
- `AGENTS.md` and the docs index.

Specialists send the integrator a small proposed patch instead of editing these.

**SQL migration slots** (component release **1.4.0**; the integrator owns the release bump):

| Slot | Owner | Content |
| --- | --- | --- |
| 0035 | MO-40 | Signal ingress (SPEC-10 §3) |
| 0036 | HL-06 | Lane profile checks for `claude_managed` and `codex_agents`; data class |
| 0037 | MO-16 | Environment preparation records |
| 0038 | MO-20 | Owner prerequisites |
| 0039 | MO-44 | Watcher descriptors and firing state (if needed) |
| 0040 | MO-79 | Launch-request inbox kind and credential purpose, only if 0035 has already merged (otherwise folded into 0035 through the MO-40 owner) |

Further slots are allocated by the integrator.

## Worktrees, branches and claims

- **Worktrees.** One isolated worktree per active issue, from the current integration base, under a dedicated workspace root. Branch names are `mo/<issue-id>-<slug>` (for example `mo/hl-08-claude-managed-lifecycle`). Verify there is no branch or worktree collision first.
- **Claims** are written to `.scratch/materialization-observation-2026-10/<issue>/CLAIM.md` in the **main checkout** (`.scratch/` is git-ignored, so claims never travel with branches). Each records:
  - the issue and role;
  - the base commit, worktree and writable paths;
  - blockers and their evidence;
  - the planned tests;
  - account or environment dependencies.
- **Handoffs** are written to `…/<issue>/HANDOFF.md`. Each records:
  - changed files and contracts;
  - the exact commands run, with passed, failed, blocked and unrun results;
  - drill records;
  - usage disposition (spent, estimated or unknown);
  - unresolved facts;
  - follow-ups.

  The integrator verifies on the integration branch before marking an issue done.
- **Qualification.** `qualified=True` requires a cited live record for that exact profile and placement. Fake evidence never qualifies.

## Dispatch order

Run these six streams in parallel from day one. They have disjoint regions. **The priority is the remote `claude_managed` path** (SPRINT priority order). When two items compete for a stream, the one on that path goes first.

1. **Skills:** LS-01 → LS-02, LS-03, LS-04 → LS-05, LS-06 → LS-07 (smoke, owner-authorized) → LS-08.
2. **Integrator:** MO-78 (Temporal Cloud setup), HL-05 → HL-06, MO-01, MO-70, MO-68, MO-69 → MO-71, then MO-10, MO-72 → MO-67, then MO-74 (Vercel deploy) and MO-77 (AWS worker).
3. **Runtime:** MO-04, MO-05 (both unblock the remote path), MO-63, MO-64; then CM-10, CM-09, CM-08, CM-18, CM-13, CM-19; MO-03, MO-65, MO-66, MO-73.
4. **Hosted:** HL-23 (provider smoke, paid, under $1 each) and HL-04 first; HL-07 → HL-08 → HL-09 once HL-06 lands; then HL-11 → HL-12 → HL-13 against fakes; HL-21 after MO-30.
5. **Environment:** MO-11 (Secret Broker, on the remote critical path) and MO-14 first; then MO-08 (WSL toolchain), MO-02, MO-12 and the S1 environment items. HL-01 and HL-03 wait for S4's release.
6. **Events:** MO-43 (wake channels), then MO-40 → MO-75 → MO-79 and HL-17; then the S1 signal, gate and watcher items.

**Then by slice:**

1. **S0:** MO-72 (local end to end), then MO-67 (Temporal Cloud).
2. **R:** MO-77 live with the laptop-off proof, and MO-79 deployed with MO-74.
3. **S2:** HL-24, the `claude_managed` cloud drill. Integrator-run, paid, $10.
4. **S3:** HL-25, the `codex_agents` hosted drill, after HL-24.
5. **S1:** the `cursor_cloud` vertical, which needs MO-11, MO-12, MO-13, MO-30, MO-41, MO-42, MO-44, MO-21 and the deployed ingress.
6. **S4:** only after the owner releases it: HL-01 → HL-02 → HL-03 → HL-15, HL-16; HL-10; HL-14.
7. **Q:** CM-21, and HL-20 when S4 runs.

Avoid spending a coding window on disconnected stubs: every slice ends in a recorded end-to-end run.

## Authorization boundaries (from the owner, as of 2026-10-12)

- **Allowed:**
  - Local code, tests and docs in worktrees, and commits on `mo/*` issue branches.
  - Read-only provider API calls.
  - Installing the WSL toolchain (MO-08).
  - Deploying the ingress and Model Gateway project to Vercel team `overtons-projects` (MO-74, HL-03), always with `--scope overtons-projects`.
  - Applying release 1.4.0 to both live Supabase projects through `docs/specs/archive/mc-surfaces-2026-10/docs/qualification/two-project/LIVE_PLAN.md`, by the integrator only, after the disposable-cluster and local PostgreSQL proofs pass (R18).
  - Paid drills within each slice's **$10** budget, using the models in [SPRINT.md](SPRINT.md#drill-budgets-and-models) (R22). Stop at the budget and report.
  - Daytona sandboxes inside the S4 budget, using the $200 free credit, with labels `{run, unit, gen}` and the reaper on, **once the owner releases S4** (R31).
  - Temporal Cloud runs in `mission-control-dev.ih0e7` only (R20), including registering the search attributes MO-78 lists.
  - **AWS (R28), account `298199649527`, region `us-east-1` only (always pass `--region us-east-1`):**
    - creating, updating and deleting exactly the resources named in SPEC-11 §4;
    - building and pushing images to `mission-control-worker`;
    - registering task definitions and updating the service `mc-worker-ai-engineer` between `desiredCount` 0 and 1;
    - reading its logs;
    - all inside the $40/month AWS budget. Stop and report if the budget alert fires.
- **Requires explicit owner approval at the time:**
  - merges and pushes to `main`;
  - spend beyond a slice budget, a different model, or the `mission-control-prod` namespace;
  - raising the Daytona tier;
  - starting any funding-gated (S4) issue;
  - any AWS resource, region, account or size beyond SPEC-11 §4, and ECS Exec into the running task;
  - writing secret values into AWS (the owner runs `put-secrets.ps1`);
  - registering provider webhooks;
  - creating the GitHub App;
  - publishing issues to Linear.
- **Never:**
  - print or commit secrets (`.env` values, keys, tokens);
  - put organization API keys in sandboxes;
  - forward the Mission Control bearer token;
  - invent provider bindings, model ids or environment ids.

## Starting the team

1. **Lead session.** Open one agent session (Claude Code recommended) with the working directory `platform/mission-control`, on a clean `main` that matches `origin/main`. It acts as the **integrator and dispatcher**.
2. **Paste the kickoff prompt** below. The lead reads the packet, writes its own CLAIM for MO-78, HL-05 and HL-06, and dispatches one worker agent per stream (Skills, Runtime, Hosted, Environment, Events). Each worker uses its own worktree and branch per TEAM-WORKSPACE.
3. **Workers** can be subagents of the lead, or separate sessions (Claude Code, Codex or Cursor). A separate session gets the same kickoff prompt plus one line: `Your role is <Role>; take the first unblocked issue in your stream from the Dispatch order.`
4. **Check-ins.** The lead reports at the end of each wave:
   - issues done, with HANDOFF links;
   - spend per slice;
   - owner inputs now needed (SPRINT table).

   The owner answers the ⏳ rows when asked. Nothing else needs the owner until wave B.

## Kickoff prompt (tool-neutral)

```text
Execute the Mission Control sprint defined in
platform/mission-control/docs/specs/materialization-observation-2026-10/SPRINT.md.

Read root and scoped AGENTS.md, then the packet README, SPRINT, DECISIONS (R1-R33),
TEAM-WORKSPACE, PLAN, ISSUES, and for each issue its spec and the research it cites.
Work only issues with sprint: in, respecting Blocked by. Never start an issue marked
"Gate: funding" (slice S4) until the owner releases it.

You are the integrator and dispatcher. Use disjoint worktree owners per TEAM-WORKSPACE
roles (Skills, Integrator, Runtime, Hosted, Environment, Events). Integrator owns frozen
shared paths, migration slots 0035-0040, release 1.4.0, deployments/ and the AWS resources.
Start the six streams in the Dispatch order. Priority is the remote claude_managed path:
MO-78, HL-23, HL-04..06, MO-04/05, MO-11, MO-40 -> MO-75 -> MO-79, MO-63/64 -> MO-77,
HL-07 -> HL-08 -> HL-09, HL-17, HL-18, then the HL-24 drill (S2), then codex_agents
(HL-11..13, HL-25 drill, S3). LS and S0 run in parallel from day one; S1 runs in parallel
on its own streams.

Keep Temporal the sole scheduler and reducers the acceptance authority. Signals and
provider outcomes are evidence, never authority. Exactly one base worker per (namespace,
application): once the AWS worker serves AI Engineer, the WSL2 worker runs in lane role.
Reuse Host Projection, WorkspaceAllocator, coordinator inbox, frame store and outbox;
extend, don't fork. Every lane passes the lane conformance suite. Local CLI skills must
not import mission_control.

Run make check plus real PostgreSQL/Temporal for persistence claims; remote claims cite
AWS task logs and Temporal Cloud workflow ids. Report passed, failed, blocked and unrun
separately. Write CLAIM.md and HANDOFF.md per issue under
.scratch/materialization-observation-2026-10/<issue>/ in the main checkout.

Pre-approved: commits on mo/* branches; the Vercel deploy (always --scope overtons-projects);
the live 1.4.0 migration after local proofs (integrator only); paid drills within each
slice's $10 budget on the SPRINT models (HL-23 smokes under $1 each); Temporal Cloud
namespace mission-control-dev.ih0e7; the AWS resources and deploys in SPEC-11 §4 in
account 298199649527, region us-east-1 only (always --region us-east-1), within the
$40/month budget. Ask the owner before: merging or pushing to main, exceeding a budget,
changing a model, any S4 issue, any AWS resource beyond SPEC-11 §4 or ECS Exec,
registering webhooks, creating the GitHub App, publishing to Linear. The owner, not you,
runs put-secrets.ps1. Never print or commit secrets; never put org API keys in sandboxes
or images.

Finish each slice with a recorded end-to-end run and its usage disposition. Report to the
owner at the end of each wave: issues done, spend per slice, owner inputs now needed.
```

## Run 2 approved refinements (2026-10-14)

The preceding kickoff/roles/migration table describes the original Run 1 baseline. For Run 2 use RUN-2-HANDOFF and RUN-2-AGENT-TEAM-KICKOFF. In particular, 0035 already includes mission_request; 0040 is lane descriptions, 0041 capacity and 0039 unused. None is free for MO-79. Do not redispatch integrated HL/MO work or recreate retired worktrees. Historical authorization is bounded evidence, not blanket new permission; the kickoff begins offline and checks action-specific gates.

[Approved plan](runs/RUN-2-PLANNING-AMENDMENTS.md) · [Codex team kickoff](runs/RUN-2-AGENT-TEAM-KICKOFF.md) · [OpenAI architecture](runs/RUN-2-OPENAI-ARCHITECTURE.md).
