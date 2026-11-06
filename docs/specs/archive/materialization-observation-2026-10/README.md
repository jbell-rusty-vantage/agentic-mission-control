---
type: Specification
title: "Materialization, observation and hosted-lane packet: environment, cognition and watcher control, API-billed hosted lanes, Cursor maturity and local CLI skills"
description: "Gap report, primary-source research, owner decisions, eleven specifications, an implementation plan and 110 generated issues for materializing environments and cognition into Cursor, Claude Code, Codex, Anthropic Managed Agents and OpenAI Agents missions, remote operation on a thin AWS Temporal worker, formal watchers and callbacks, Cursor full maturity, and local skills that drive the three CLIs."
tags: [mission-control, specifications, environments, materialization, observation, providers, skills]
status: archived
archived: 2026-10-23
archived_from: docs/specs/materialization-observation-2026-10
archived_reason: "Run 2 finished 2026-10-20 and integrated on main; owner archived it whole 2026-10-23"
---

> **Archived 2026-10-23** (Run 2 finished 2026-10-20 and integrated on main; owner archived it whole 2026-10-23). Kept for provenance; see the [archive index](../README.md).

# Materialization, observation and hosted-lane packet — 2026-10-12

**Status: FINISHED (2026-10-20).** Run 2 is closed and integrated on `main`; this packet is now a historical record.
- Outcome: MR-01/MR-11 (`claude_agent_sdk`, local and Temporal Cloud) and MR-02/MR-12 (`codex`) passed. MR-03 (`cursor_local`) is blocked by an SDK `observe_run` rejection, and MR-13 was not run. Eight Gate L issues closed by receipt, so 45 of 110 issues are `fully done`.
- Read the [completion summary](runs/RUN-2-COMPLETION-SUMMARY-2026-10.md) ("Finish (2026-10-20)"), then the [finish disposition](runs/RUN-2-FINISH-DISPOSITION-2026-10.md).
- Everything left open is in the [Run 2 carry-forward register](../../provider-consolidation-2026-10/RUN-2-CARRY-FORWARD.md): parked runs, findings, and the 64 open issues by destination sprint.
- The next program is [provider consolidation](../../provider-consolidation-2026-10/README.md), one provider at a time.

The banners below are dated and historical.

**Run 2 finish (historical instructions, 2026-10-19):** [RUN-2-FINISH-INSTRUCTIONS-2026-10-19.md](RUN-2-FINISH-INSTRUCTIONS-2026-10-19.md) reframes the remaining work as materialize-and-run per provider lane, with the sprint harness as the caller.

**Run 2 close-out result (2026-10-19):** read [the completion summary](runs/RUN-2-COMPLETION-SUMMARY-2026-10.md), the in-place ledger [RUN-2-CLOSE-STATUS.md](runs/RUN-2-CLOSE-STATUS.md) and [the F5 proof index](runs/RUN-2-F5-PROOF-INDEX.md).
Gate L is not fully met: F0 and F1 passed, S0-01 is partial, 17 S0 cells and LS-07/08 remain blocked or unrun with named gates.

**Close-out (historical, 2026-10-18):** the owner decided Run 2 closes at **Gate L** (local fundamentals, LS-07/08, all 18 S0 cells); R/S1/S2/S3 and funding-held S4 carry into the next capability-proof program; F2 is deferred. Read [RUN-2-MISSION.md](RUN-2-MISSION.md), then [the Claude Code instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md), [the sequence](RUN-2-EXECUTION-SEQUENCE-2026-10-18.md), [the Gate L disposition](runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md) and the 2026-10-18 handoff below. Live progress is kept in one file, `runs/RUN-2-CLOSE-STATUS.md`.

**Formal fixture handoff (historical, 2026-10-18 UTC):** [Fundamental capabilities, provider configurations and control proofs](runs/RUN-2-FUNDAMENTAL-CAPABILITIES-HANDOFF-2026-10-18.md). The owner has paused live execution for this handoff and one scoped clean-code pass. Fundamentals remain explicitly unfinished; current-build Vercel/AWS deployment is reserved for the next session. Original acceptance and issue statuses remain unchanged.

**Execution record (historical, 2026-10-17):** [Integrated main, completed R2A and remaining acceptance](runs/RUN-2-CURRENT-INTEGRATION-2026-10-17.md), with the [human permissions and action record](runs/RUN-2-PERMISSIONS-AND-ACTIONS-2026-10-17.md). All ten original worktree heads are integrated locally. The owned R2B host now has real read-only role/contract/replay qualification, a full timeout proof and independent executable review; automatic approval review rejected live delivery before process creation. Exact action approval, full G1 and original native/remote/data/release acceptance remain open. [Independent progress and dependencies](runs/RUN-2-INDEPENDENT-GATES-2026-10-17.md) records the joined synthetic G1 proof, available SDL,85 passing schema units and exact historical artifact recovery.

**Earlier handoff (2026-10-14):** Specs 1–6 implementation is merged into `main`. Read the [Run 1 integration report](runs/RUN-1-REPORT.md) for executed checks and remaining qualification blockers, then the [Specs 7–11 team handoff](runs/RUN-2-HANDOFF.md) for the next dispatch, dependencies, release boundaries and recovery archive. Read the [approved Run 2 amendments](runs/RUN-2-PLANNING-AMENDMENTS.md), [OpenAI product evidence](runs/RUN-2-OPENAI-ARCHITECTURE.md) and [Codex team kickoff](runs/RUN-2-AGENT-TEAM-KICKOFF.md) before dispatch. The following kickoff summary is historical.

**Historical kickoff status:** ready for the agent team (2026-10-12), **sharpened the same day** (DECISIONS R27–R33): remote operation on a thin AWS ECS Fargate worker (slice R), `claude_managed` first then `codex_agents`, S2/S3 decoupled from S1, S4 funding-gated. The owner's readiness decisions R16–R26 are recorded. The tree is checkpointed on `origin/main`, the Temporal Cloud namespaces exist, and the live database upgrade is approved (see [SPRINT](SPRINT.md#owner-inputs-done-and-needed)). Nothing has been implemented or published to Linear, and no paid provider calls were made. Done on the machine: Codex CLI 0.162.1, the official Codex plugin for Claude Code, and the Vercel plugin (enabled).

- **Baseline:** the 2026-10-12 checkpoint commit on `main` (previously `2d20f62` plus the owner's uncommitted work).
- **Relationship to the multi-provider packet:** this packet extends [multi-provider-2026-10](../multi-provider-2026-10/README.md). ADR-0035–0041 remain `proposed`. New ADRs 0042–0054 are listed in [DECISIONS](DECISIONS.md).

## Owner goals

1. **Spawn and control missions.** An agent spawns and controls local and cloud coding-agent missions for both knowledge, research, ingestion and content work and codebase SDLC work. Environment and cognition are materialized and controlled for every provider, and watcher and callback scripts are formalized.
2. **Owner decisions** (second brief):
   - API billing is approved.
   - Build Cursor (local and cloud), Anthropic Managed Agents and OpenAI Agents (Codex harness) to full lifecycle maturity.
   - The subscription cloud products come later, as experimental lanes.
   - Separate local skills teach any agent to drive the Cursor, Codex and Claude Code CLIs with the owner's own credentials.

## Read in this order

1. [SPRINT](SPRINT.md): **authoritative scope.** Outcomes, slices LS and S0 to S4, definitions of done, out of scope, owner inputs (done and needed).
2. [DECISIONS](DECISIONS.md): recorded decisions R1 to R15, corrections C1 to C3, open items.
3. [TEAM-WORKSPACE](TEAM-WORKSPACE.md): roles, frozen paths, migration slots, claims and handoffs, dispatch order, authorization boundaries, kickoff prompt.
4. [PLAN](PLAN.md): slices to issues, waves, critical paths, owner inputs in order, verification.
5. [ISSUES](ISSUES.md): 110 issues (97 in sprint, 13 deferred) with 144 blocking relations. The source is `issues.json`, generated by `generate_issues.py`.
6. [GAP-REPORT](GAP-REPORT.md): the state the sprint starts from (G1 to G25).
7. Specifications:
   - [SPEC-01 Environments](SPEC-01-environments.md)
   - [SPEC-02 Cognition](SPEC-02-cognition.md)
   - [SPEC-03 Workspaces and placement](SPEC-03-workspaces-and-placement.md)
   - [SPEC-04 Watchers and callbacks](SPEC-04-watchers-and-callbacks.md)
   - [SPEC-05 Owner prerequisites](SPEC-05-owner-prerequisites.md)
   - [SPEC-06 Hosted API lanes and Sandbox Host](SPEC-06-hosted-api-lanes.md)
   - [SPEC-07 Cursor maturity](SPEC-07-cursor-maturity.md)
   - [SPEC-08 Local CLI skills](SPEC-08-local-cli-skills.md)
   - [SPEC-09 Local harness path](SPEC-09-local-harness-path.md)
   - [SPEC-10 Ingress on Vercel](SPEC-10-ingress-on-vercel.md)
   - [SPEC-11 Remote worker on AWS](SPEC-11-remote-worker-on-aws.md)
   - [Managed agents and the remote path](MANAGED-AGENTS-REMOTE-PATH.md): how managed agents, harnesses, SDKs, Temporal and Vercel fit together (background to R27–R33)
8. Evidence in `research/` (all read 2026-10-12):
   - Providers: [Cursor](research/cursor.md), [Cursor maturity](research/cursor-maturity.md), [Claude Code](research/claude-code.md), [Anthropic Managed Agents](research/anthropic-managed-agents.md), [Codex](research/codex.md), [OpenAI hosted agents](research/openai-hosted-agents.md)
   - Sandboxes, ingress and harnesses: [Daytona](research/daytona.md), [Vercel ingress](research/vercel-ingress.md), [harnesses in sandboxes](research/harness-in-sandbox.md)
   - Local paths: [local CLI skills](research/local-cli-skills.md), [CLI adapters](research/cli-adapters.md), [slice S0 audit](research/s0-local-harness.md)
   - Codebase audits: [materialization](research/codebase-materialization.md), [observation](research/codebase-observation.md), [new lanes](research/codebase-new-lanes.md)

## Lane landscape after this packet

| Profile | Billing | Harness | Status target | Runs on |
| --- | --- | --- | --- | --- |
| `claude_managed` cloud | Anthropic API | Managed Agents | **Qualified first** (S2, HL-24) | Anthropic sandbox; orchestrated by the AWS worker |
| `codex_agents` OpenAI-hosted | OpenAI API | Codex (closed) | **Qualified second** (S3, HL-25) | OpenAI sandbox; orchestrated by the AWS worker |
| `cursor_cloud` | Cursor API key | Cursor | Full maturity (S1, SPEC-07) | Cursor VM; orchestrated by the AWS worker |
| `cursor_local` | Cursor API key | Cursor | Full maturity (S0, SPEC-07) | WSL2 lane worker (Windows after CM-04) |
| `claude_agent_sdk` local | Anthropic API | **Claude Code** (full) | Local proven in S0 | WSL2 lane worker |
| `codex` local | OpenAI API or ChatGPT login | **Codex** (full) | Local proven in S0 | WSL2 lane worker |
| `claude_managed` / `codex_agents` self-hosted; `claude_agent_sdk` / `codex` on Sandbox Host | API | as above | **Funding-gated** (S4, R31) | Daytona or Docker, through the Model Gateway |
| `deep_agents` | per model route | Deep Agents | Owner brief pending (D7) | — |
| `claude_cloud`, `codex_cloud` | Subscription | Provider products | Deferred: next sprint (SC) | — |
| Local CLI job skills (not a lane) | Cursor key, Claude and ChatGPT subscriptions | The CLIs themselves | Wave A (LS) | Owner machine |

**Runtime topology** ([SPEC-11](SPEC-11-remote-worker-on-aws.md)):

- **Temporal Cloud** `mission-control-dev.ih0e7`.
- **AWS ECS Fargate** service `mc-worker-ai-engineer` (`us-east-1`): base queues, hosted lanes and the IngressDrainer.
- **Vercel** `overtons-projects`: Signal Ingress, launch route and webhooks.
- **WSL2 lane worker** for the local harnesses.
- **The Windows API** for local launches.

## Proposed glossary terms

To be added through the domain-modeling skill once accepted.

- **Environment Kit**, **Base Layer**, **Mission Layer**, **Bootstrap Entrypoint**
- **Secret Broker**, **Model Gateway**
- **Readiness Level**
- **Cognition Pack**, **Cognition Profile**, **Ambient Cognition**
- **Mission Branch**, **Knowledge Workspace**
- **Signal**, **Signal Ingress**, **Trust Tier**, **Telemetry Hook Pack**
- **Watcher**, **Wake Channel**
- **Owner Prerequisite**, **Preflight**
- **Sandbox Host**, **Remote Session Lane**, **Lane Conformance Suite**
- **Base Worker**, **Lane Worker**, **Launch Request**, **Pack File**
- **Data Class**
- **CLI Job** (local skills, outside Mission Control)

## Provenance (packet preparation, 2026-10-12)

- **Owner briefs:** this session, 2026-10-12. The first covered environment, cognition and observation across providers. The second approved API billing and covered the hosted API lanes, Cursor maturity and the local CLI skills. The sixth (sharpening) set the hosted-lane order and permitted a thin Temporal worker deployment. AWS ECS Fargate was chosen over Fly.io after checking the S3-only payload store, the authenticated AWS CLI and the prepared `cloud_runtime` image (R27–R33, SPEC-11).
- **Method:** three rounds of five parallel research agents (code audits, primary-source provider surveys, Daytona, Vercel, source-level harness questions, the S0 machine audit, CLI verification), then synthesis.
- **Tests run:** unit suites only, as listed in the gap report. No integration, PostgreSQL, Temporal or live provider runs.
- **Not done:**
  - No deployments, Linear publication or paid calls. The checkpoint commit and push, the Temporal namespaces and the live 1.3.0 upgrade were done on the owner's instruction (R18–R20).
  - `AGENTS.md` docs index not regenerated; run `python docs/tools/agents_docs_index.py` when accepted.
  - The local CLI skills are specified, not yet written.
