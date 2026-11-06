---
type: Concept
category: operations
title: Deployment
description: Where Mission Control runs today (an owner Windows host with a WSL2 worker, Temporal Cloud, two Supabase projects, a Vercel ingress edge) against what is only proposed (AWS API and workers, Agent Server hosting, sandboxes), the local and cloud split, and the goal of moving one session between local and cloud across providers; deployment is at proposal stage.
tags: [mission-control, deployment, operations, vercel, temporal, aws, local-cloud, goal]
aliases: [hosting, local cloud split, Vercel ingress, remote readiness, deployment proposal]
questions:
  - Where does Mission Control run today and what is only proposed?
  - What is deployed on Vercel and what is proven about it?
  - How would one session move between local and cloud?
  - Which deployment decisions are still open?
updated: 2026-11-01
---

# Deployment

**Deployment is at proposal stage.** The owner's words: "deployment is in proposal stage. We have a vercel ingress server up."
Nothing below a Vercel edge has been deployed for production. This concept separates what runs now, what is packaged but not
deployed, and what is a goal. It is the operations view; the reasoning and options are in the two documents it points at:
[DEPLOYMENT_OPTIONS_2026-10-12](../DEPLOYMENT_OPTIONS_2026-10-12.md) (assessment of accounts, process roles, Managed Deep
Agents and a staged path; an assessment, not an authorization) and the
[cloud environments roadmap](../specs/provider-consolidation-2026-10/sprint-oc/CLOUD-ENVIRONMENTS-AND-DEEP-AGENTS-DEPLOYMENT-2026-10-31.md)
(owner direction of 2026-10-31: candidates, not selections; it inherits no spending authority).

## What runs today (local and cloud split)

| Piece | Where | State |
| --- | --- | --- |
| API, MCP, worker | owner Windows host; worker in WSL2 for `claude_agent_sdk`, `codex`, `cursor_local` ([WSL2 runbook](../WSL2_WORKER_RUNBOOK.md)) | runs; the only worker host |
| Temporal | local dev server for tests and the offline stack; Temporal Cloud namespaces `mission-control-dev` and `-prod` (account `ih0e7`) | Run 2 ran missions on both |
| Application databases | two disposable Supabase projects with the common component ([database component](database-component.md)) | MC 1.8.0 recorded on both; locks name older releases |
| Redis | local compose `redis` (`REDIS_URL`); a remote Upstash instance exists ([mission stream](mission-stream.md)) | Upstash not read by name in code, not run |
| Signal Ingress edge | Vercel project `mission-control-ingress` from `deployments/ingress-vercel` (team `overtons-projects`, region `iad1`) | live: startup, liveness and unauthenticated refusal passed; accepted launches, callbacks, latency and custody unqualified ([signal ingress](signal-ingress.md)) |
| Agent Server | local, for async children | deterministic-model proofs only; a hosted Agent Server is unevaluated |
| Coding agents (Cursor, Claude Code, Codex) | the user's agent tools, calling `missionctl` and MCP; Cursor Cloud agents via `.cursor/environment.json` | cloud coding environments are being prepared ([roadmap](../specs/provider-consolidation-2026-10/sprint-oc/CLOUD-ENVIRONMENTS-AND-DEEP-AGENTS-DEPLOYMENT-2026-10-31.md) section 3) |

## Packaged, not deployed

`deployments/cloud_runtime` (image, plan renderer, [approval plan](../specs/archive/mc-surfaces-2026-10/deployments/cloud_runtime/APPROVAL_PLAN.md): one API and one
long-lived ECS Fargate worker per application; a $24 per month Lightsail host with a proposed $40 planning ceiling, "prepared,
not deployed") and `deployments/worker-aws` (ECR, a private payload bucket, roles, empty secrets, logs, a $40 budget alert; the
supporting stack was created under Run 2 authority and the worker service is not deployed). Neither is approved as a target.

## The architecture still to decide

The roadmap section 4 lists the service roles whose state ownership must stay distinct: MC API and MCP, Temporal service and
workers, the Deep Agents runtime, Agent Server (async children only; ADR-0006, ADR-0017), KS API and workers, parser services,
databases and object storage, and a sandbox or compute provider that is never the mission ledger. Open choices: Temporal Cloud
workers on EC2/Lightsail versus ECS/Fargate; Agent Server on LangSmith managed versus licensed standalone; sandbox provider
(Daytona has a contract slot but no materializer factory); region, monthly ceiling and backup objectives; and reconciling the KS
Vercel API plus AWS worker baseline before moving transports. Fargate offers no privileged containers, so nested Docker sandboxes
are not assumed. Two remote Deep Agents arrangements exist: a cloud MC worker running the existing adapter in-process (the closest
first deployment) or parent cognition dispatched to a separately hosted runtime (needs a host integration; not evidenced).

## Goal: one session, local and cloud, across providers

The owner wants agent sessions to "move to and fro local and cloud, transferring files, context and switching runtimes as needed",
with granular control, "where possible" across providers. **Today there is a local and a cloud split; session movement is not built.**
The roadmap section 5 states what a move must preserve or reconcile: mission authority, native cognition (never relabel
reconstructed context as native), workspace and compute, context and outputs, capabilities, pending work and effects, and
re-authorized credentials. Start at settled recorded boundaries; a running transfer needs quiesce or interrupt, fencing the source,
verified capture, restore, recorded ownership and receipt reconciliation, with no two active owners. Host choice is admitted and
pinned before execution (placement admission selects among qualified configurations; it is not relocation of a running session).
Proof matrix: local to cloud to local across StageGraph, GoalDirected, nested and linked workflows and subordinate sessions, with
fork-at-point, queued message, interrupt and inject, worker and client loss, unreachable custody and an uncertain effect.
Related existing mechanics: cluster binding ([operations](operations.md)), [recovery](recovery.md), [precise fork](precise-fork.md),
[environments](environments.md), [placement admission](placement-admission.md). See [goals](goals.md#goal-local-cloud-one-session).

Built / specified / goal: local operation, Temporal Cloud missions and the Vercel edge are implemented (edge liveness-checked);
AWS hosting, hosted Agent Server and sandboxes are proposals; local-to-cloud session movement is a goal.

## Citations

- Reports: [deployment options](../DEPLOYMENT_OPTIONS_2026-10-12.md),
  [cloud environments roadmap](../specs/provider-consolidation-2026-10/sprint-oc/CLOUD-ENVIRONMENTS-AND-DEEP-AGENTS-DEPLOYMENT-2026-10-31.md),
  [Deep Agents topology note](../specs/provider-consolidation-2026-10/providers/deep_agents/TOPOLOGY-NOTE.md),
  [infrastructure map](../specs/agentic-sdlc-2026-11/INFRASTRUCTURE-MAP-DRAFT-2026-11.md).
- ADR: [0006](../adr/0006-agent-server-required-execution-host-not-scheduler.md),
  [0017](../adr/0017-agent-server-runtime-persistence-separate-database.md),
  [0004](../adr/0004-temporal-sole-scheduler-transactional-outbox.md).
- Packages: [ingress edge](../../deployments/ingress-vercel/README.md),
  [cloud runtime](../../deployments/cloud_runtime/README.md), [AWS worker](../../deployments/worker-aws/README.md).
- Code: [cluster binding](../../src/mission_control/application/execution/run_launch.py),
  [ingress routes](../../src/mission_control/interfaces/http/ingress.py).
- Tests: [outage drill](../../tests/integration/temporal/test_mp22_outage_drill.py),
  [ingress drainer](../../tests/integration/postgres/test_run2_ingress_drainer_postgres.py).
