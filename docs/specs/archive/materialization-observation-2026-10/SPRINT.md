---
type: Specification
title: "Sprint scope: CLI skills, local harness path, remote operation on a thin AWS worker, claude_managed then codex_agents, cloud materialization and observation"
description: "Authoritative in/out scope, outcomes, slices, definitions of done, priority order, owner inputs, drill budgets and the issue filter for the sprint the owner's agent team will execute. Sharpened 2026-10-12 (DECISIONS R27-R33)."
tags: [mission-control, specifications, sprint, scope]
---

# Sprint scope

This page is authoritative for *what this sprint delivers*. Specifications define *how*. Issues carry `sprint: in | deferred` and a `slice` in `issues.json`. The agent team works only `in` issues.

## In one paragraph

An agent can start, watch, steer and finish **knowledge and coding missions** on the owner's machine and **remotely**. Remotely means requested from anywhere through the Vercel ingress and orchestrated by **one thin Temporal worker on AWS**, while the work runs inside **Anthropic Managed Agents (`claude_managed`) first and then the OpenAI Agents API (`codex_agents`)**. No agent compute is deployed. Environments and cognition are set up for every provider, and signals, webhooks and watchers feed back into Mission Control. The subscription cloud lanes are deferred. The self-run harnesses on rented sandboxes (S4) stay in the sprint but wait for the owner to release funding.

## Outcomes

1. **Direct-to-provider CLI skills, outside Mission Control** ([SPEC-08](SPEC-08-local-cli-skills.md)). Any agent session hands goal-directed jobs to the Claude Code, Codex and Cursor CLIs with the owner's local credentials, in parallel worktrees, and is woken when they finish.
2. **Local harness path** ([SPEC-09](SPEC-09-local-harness-path.md)). The real Claude Code, Codex and Cursor harnesses run under Mission Control on the WSL2 worker, under local Temporal and then Temporal Cloud.
3. **Remote operation** ([SPEC-11](SPEC-11-remote-worker-on-aws.md), [SPEC-10](SPEC-10-ingress-on-vercel.md)). A thin worker on AWS ECS Fargate serves the base queues, the hosted lanes and the IngressDrainer. A launch-request route on the Vercel ingress admits missions from anywhere. Missions keep progressing with the owner's machine off.
4. **`claude_managed`, then `codex_agents`, at full declared cloud maturity** ([SPEC-06](SPEC-06-hosted-api-lanes.md)). The work runs on Anthropic's and OpenAI's managed harnesses and sandboxes. Capabilities are seeded from pack files, then from the full projection. Mission Control owns gating, publication and acceptance.
5. **Cloud environment and cognition materialization for every provider** ([SPEC-01](SPEC-01-environments.md), [SPEC-02](SPEC-02-cognition.md), [SPEC-03](SPEC-03-workspaces-and-placement.md), [SPEC-05](SPEC-05-owner-prerequisites.md)). Environment Kits, the Secret Broker, Cognition Packs, preflight and knowledge workspaces.
6. **Observation and callbacks** ([SPEC-04](SPEC-04-watchers-and-callbacks.md), [SPEC-10](SPEC-10-ingress-on-vercel.md)). Signal Ingress, the IngressDrainer, provider webhooks as wake-ups, the Telemetry Hook Pack, gate hooks, wake channels and watchers.
7. **Cursor lanes correct and durable** ([SPEC-07](SPEC-07-cursor-maturity.md)). CM P0 and P1.
8. **Funding-gated: real harnesses on rented sandboxes** (SPEC-06 §6–7, §12). Claude Code and Codex on Daytona through the Model Gateway, and both self-hosted placements. Started only when the owner releases slice S4 (R31).

## Slices: the order of proof

| Slice | Proves | Definition of done |
| --- | --- | --- |
| **LS** | Outcome 1 | A Claude Code session runs `agentjob.py` for a Codex fix job and a Cursor review job in parallel in the background. It is woken on completion and reads both `result.json` files. The verify commands ran in the runner. No API-key fallback happened. |
| **S0** | Outcome 2 | From Claude Code, Codex and Cursor sessions on Windows, one mission each runs on `claude_agent_sdk`, `codex` and `cursor_local` on the WSL2 worker, under local Temporal and then Temporal Cloud. Each run is woken through `missionctl wait`, receives one `interrupt_and_inject`, and ends with a cancel or a completion. |
| **R** | Outcome 3 | The AWS service `mc-worker-ai-engineer` runs with no inbound path and passes readiness against Temporal Cloud, Supabase and S3. A mission requested through `POST /v1/ingress/ai-engineer/missions:request` from outside the owner's network is admitted by the AWS worker. With the owner's machine powered off, a hosted-lane probe mission completes. Restarting the service mid-session reattaches with no duplicate frames. |
| **S2** | Outcome 4, Anthropic | On `claude_managed` cloud, both requested through the launch route and orchestrated by the AWS worker: **(a) a knowledge mission** researches and produces a cited report (session outputs into custody, plus a commit on `mc/{run}/{unit}` in the AI Engineer knowledge repo through `mc_publish`), accepted by its Completion Contract; **(b) an SDLC mission** fixes, tests and publishes through `mc_publish` (bundle → verified push → draft PR through `repo_pr`). The run also shows: a provider webhook waking the workflow through the ingress, one `always_ask` approval round trip, an `interrupt_and_inject`, a budget-gate pause and resume, usage settled from `list_cost`, and the session deleted after custody. |
| **S3** | Outcome 4, OpenAI | The same two missions on `codex_agents` hosted, through the same remote path. It also shows: a function-tool approval round trip through `required_actions`, steer and cancel, and recovery after the AWS task is killed mid-stream (reconcile from items, no duplicate frames). |
| **S1** | Outcomes 5–7 on `cursor_cloud` | One SDLC mission (fix, test, verified branch, draft PR through `repo_pr`) and one knowledge mission (research, then a cited report Artifact accepted by its Completion Contract). Both use a synced Environment Kit, Secret Broker secrets, a Cognition Profile, Telemetry Hook Pack signals through the Vercel ingress, a stall watcher, a gate stop, and a coordinator woken by `missionctl wait`. |
| **S4** (funding-gated) | Outcome 8 | `claude_agent_sdk` and `codex` on the Sandbox Host (Docker on WSL2, then Daytona) through the Model Gateway: hooks fire worker-side, per-command approval works, and resume moves hosts. Both self-hosted placements run a code mission in a lease. |

### Priority order

1. **Now, in parallel:** LS, S0 and the foundations. Slice R's groundwork (MO-78 namespace setup) and the hosted-lane groundwork (HL-04, HL-05, HL-06, and the HL-23 provider smoke).
2. **Slice R** (MO-77 AWS worker, MO-79 launch route), alongside **S2's lane work** (HL-07 to HL-09, HL-17, HL-18).
3. **S2 drill** (HL-24): `claude_managed` qualifies first.
4. **S3** (HL-11 to HL-13, then the HL-25 drill): `codex_agents` follows.
5. **S1** runs in parallel throughout on its own streams (Environment, Events, Runtime). It is not on S2's or S3's critical path any more (R30).
6. **S4** only after the owner releases it.
7. Qualification drills close each slice. A drill flips `qualified` only for the profile and placement it recorded.

## Out of scope (deferred issues)

- **Subscription cloud lanes:** `claude_cloud` and `codex_cloud` (SC-01 to SC-03).
- **Cursor P2 control levers:** CM-11 model params, CM-12 subagent honesty, CM-14 occupancy, CM-15 plan gate, CM-16 custom-tool approvals, CM-17 hygiene sweep, CM-20 images and mode, CM-22 no-repo cloud agents, CM-06 store-copy fork.
- **Cross-lane forks** (MO-53).
- **Deep Agents changes**, awaiting the owner's brief (D7). The Agent Server and Managed Deep Agents are not deployed.
- **Hosting the operator API, relays, streams or MCP publicly.** Vercel hosts the Signal Ingress, the launch route and (S4) the Model Gateway. The operator API stays local. SPEC-10 phases 2 and 3 are later.
- **A Biotech remote worker**, and widening Biotech's data class for hosted lanes. AI Engineer goes first (SPEC-11 §2).
- **`mission-control-prod.ih0e7`.** All sprint work uses `mission-control-dev.ih0e7`.
- **Flipping `qualified` for profiles whose drills are not run.**

## Owner inputs: done and needed

Everything needed to **start** the team is done. The ⏳ rows are needed by the wave named, not before.

| Input | Needed for | Status |
| --- | --- | --- |
| Sandbox Host approval, Daytona chosen, profile names approved | S4 | ✅ (R8–R10); S4 is funding-gated (R31) |
| `DAYTONA_API_KEY` in `.env` | S4 | ✅ |
| **Daytona tier.** Current tier is enough (R16); Tier 3 later for strict allowlists or larger pools | S4 | ✅ decided |
| **Vercel.** Pro, team `overtons-projects`; CLI and connector authenticated; plugin enabled; `*.vercel.app` host (R17) | R, S1, S2 | ✅ |
| **Supabase live migration.** 1.3.0 applied and verified on both projects; 1.4.0 pre-approved after local proofs (R18) | R, S1 | ✅ |
| **Storage bucket for capability bundles** on both projects | Wave C | ✅ |
| **Checkpoint the tree** (R19) | S0 | ✅ |
| **Claude worker auth route.** `ANTHROPIC_API_KEY` (R21) | S0 | ✅ |
| **Codex.** Pinned 0.162.1 (R21) | S0, LS | ✅ decided |
| **Temporal Cloud.** `mission-control-dev.ih0e7` for the sprint, `mission-control-prod.ih0e7` reserved (R20) | S0, R | ✅ |
| **Thin worker platform.** AWS ECS Fargate, `us-east-1`, AI Engineer first (R28); AWS CLI authenticated as account `298199649527` | R | ✅ decided |
| **AWS budget** $40/month with alerts (SPEC-11 AW1; default set by R28, change it if you want) | R (before MO-77 creates resources) | ✅ default; say if you want another figure |
| **Run `put-secrets.ps1`** to load the worker's secrets into Secrets Manager (SPEC-11 AW2) | R (wave B, when MO-77 asks) | ⏳ |
| **Local S3 profile** `mission-control` for the Windows API (SPEC-11 AW3) | R (MO-64) | ⏳ |
| **Make `Overton77/bell-missions-ai-engineer` private**, or accept public knowledge outputs (R23, SPEC-11 AW4) | S2 knowledge mission | ⏳ |
| **Paid drill budgets and models** (R22, table below) | All slices | ✅ |
| **LS smoke prompts.** SPEC-08's one-turn, read-only smoke prompts on your subscriptions | LS | ✅ defaulted |
| **Knowledge workspace repos** (R23) | S1–S3 | ✅ |
| **Mission Control GitHub App** (R26); until then the fallback is `gh` as `Overton77` | S1–S3 SDLC missions | ⏳ owner creating it |
| **Cursor `.cursor/environment.json`** replaced (R24) | S1 | ✅ |
| **Cursor account checks** C1–C7 (SPEC-05) | S1 | ⏳ preflight lists them |
| **Anthropic Console:** register the webhook endpoint once the ingress deploys (MA2); a read-only fine-grained PAT for the SDLC repo (MA4) | S2 (wave B/C) | ⏳ approval at the time |
| **OpenAI:** dedicated project and restricted key (OA1), webhook secret (OA2) | S3 (wave C) | ⏳ |
| **Environment keys** for self-hosted placements (MA3, OA3) | S4 | ⏳ when S4 is released |

### Drill budgets and models

Each slice's live drills stop at its budget, and the drill record states spent, estimated or unknown usage (TEAM-WORKSPACE). Model ids were verified against the providers' model lists on 2026-10-12.

| Slice | Budget | Models |
| --- | --- | --- |
| LS (CLI skills smoke) | $10 of Cursor usage; the Claude and Codex smokes run on your subscriptions | Cursor `default` (Auto); Claude CLI `claude-sonnet-5-5`; Codex CLI `gpt-6-luna` |
| S0 (local harness path) | $10 | `claude_agent_sdk`: `claude-sonnet-5-5` (API key); `codex`: `gpt-6-luna` (ChatGPT login); `cursor_local`: Auto, plus one run on `grok-4.7` |
| R (remote operation) | AWS within the $40/month budget; probe missions use the S2 budget | — |
| S1 (`cursor_cloud`) | $10 | Auto for the SDLC and knowledge missions; one comparison run on `grok-4.7` |
| S2 (`claude_managed`, including the HL-23 Anthropic smoke) | $10 | `claude-sonnet-5-5` |
| S3 (`codex_agents`, including the HL-23 OpenAI smoke) | $10 | `gpt-6-luna`. HL-23 confirms that the Agents API accepts it; if it is refused, stop and ask the owner rather than substituting a model. |
| S4 (Sandbox Host, when released) | $10 of model usage, plus Daytona compute from the $200 free credit | `claude-sonnet-5-5` through the Model Gateway; `gpt-6-luna` for the Codex executor |
| Q (qualification reruns) | $10 | Same as the slice being qualified |

Cursor model ids come from `GET /v1/models`, the API the `cursor_cloud` adapter uses: Auto is id `default` (alias `auto`) and Grok 4.7 is `grok-4.7`.

## Issue filter

`python generate_issues.py` writes `issues.json`, `issues/*.md` and [ISSUES.md](ISSUES.md). Every issue has `sprint` and `slice`. Funding-gated issues carry `Gate: funding`. The index lists in-sprint issues by wave, then the deferred ones separately.

## Run 2 approved refinements (2026-10-14)

Provider priority follows the approved planning refinements; it does not promote deferred issues. OpenAI agents here means the existing hosted Agents API codex_agents lane. S2 budget-gate pause/resume remains a required, currently blocked acceptance item; boundary pause cannot silently replace it. Inspect/wire only after integrator scoping and separately authorized proof, or obtain an explicit owner requirement amendment. No new paid/deploy permission is granted. Scope counts and dependencies remain unchanged.

[Approved plan](runs/RUN-2-PLANNING-AMENDMENTS.md) · [Codex team kickoff](runs/RUN-2-AGENT-TEAM-KICKOFF.md) · [OpenAI architecture](runs/RUN-2-OPENAI-ARCHITECTURE.md).
