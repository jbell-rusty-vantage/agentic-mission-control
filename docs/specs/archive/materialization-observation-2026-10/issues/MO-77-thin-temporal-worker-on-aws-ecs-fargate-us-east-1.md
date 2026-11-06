# [MO-77] Thin Temporal worker on AWS ECS Fargate (us-east-1)

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice R (Remote operation: thin Temporal worker on AWS and remote launch)  
**Blocked by:** MO-63, MO-64, MO-78  
**Specification:** [SPEC-11-remote-worker-on-aws.md](../SPEC-11-remote-worker-on-aws.md)

## Problem

Missions stop progressing when the owner's machine is off. Managed agents remove agent compute, but Temporal Cloud never runs workflow code; one small always-on worker must (R28).

## Work

- Operator image deployments/worker-aws/Dockerfile extending the reviewed cloud_runtime base with the AI Engineer deployment files (target.toml, release.lock), capability pins and launch bindings; CMD python -m mission_control.bootstrap.worker; linux/amd64; non-root.
- One-time infrastructure in us-east-1 per SPEC-11 §4 (always pass --region us-east-1; the CLI default is us-east-2): ECR repo, S3 payload bucket, two IAM roles, egress-only security group, log group, ECS cluster and service (0.5 vCPU / 2 GiB, desiredCount 1, min 0 / max 100 percent), AWS Budgets alert.
- deployments/worker-aws/put-secrets.ps1 for the owner to run: reads named keys from mission-control/.env and writes them to Secrets Manager under mission-control/ai-engineer/ without ever echoing values.
- deployments/worker-aws/deploy.ps1: build, tag (version + git sha), push to ECR, render the task definition with plan.py (worker-only service, secrets by ARN, AWS_PROFILE empty), register, update the service, wait for stable, tail readiness from CloudWatch. No GitHub dependency.
- Queue layout per SPEC-11 §3: the AWS worker serves the base queues and the hosted lane queue mc-ai-engineer-lane-hosted (cursor_cloud, claude_managed, codex_agents) plus the IngressDrainer; the WSL2 worker switches to MISSION_CONTROL_WORKER_ROLE=lane for mc-s0-ai-engineer-lane-wsl once this service is live.
- Database connectivity through the Supabase session pooler (IPv4); confirm LISTEN works there, otherwise run the drainer on its 5 s poll.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `deployments/worker-aws/`
- `deployments/cloud_runtime/plan.py`
- `deployments/cloud_runtime/Dockerfile`
- `bootstrap/worker.py`
- `docs/MISSION_CONTROL_LOCAL_API.md`

## Acceptance

- [ ] The service runs one task in us-east-1 with no inbound rules; readiness passes against Temporal Cloud (mission-control-dev.ih0e7), the AI Engineer Supabase project and the S3 payload bucket.
- [ ] With the owner's machine powered off, a probe mission admitted earlier runs a hosted lane turn to completion on the AWS worker; frames and payloads land in Postgres and S3.
- [ ] No secret value appears in the image, task definition, logs, repo or handoff (sentinel check); deploy.ps1 redeploys a new build with no manual console steps.
- [ ] Measured CPU and memory over a 24 h idle-plus-drill window are recorded, with the monthly cost estimate.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

Existing reviewed AWS renderer/image and sealed lane queues remain; current main integration does not prove remote readiness or installed live component.

Bind laptop-off/restart evidence to exact build, queues, installation/release and hosted configuration without widening deployment.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `deployments/worker-aws/`
- `deployments/cloud_runtime/ (reuse)`
- `bootstrap/worker.py (integrator-only)`

### Additional acceptance and negative cases

- [ ] One base worker only; WSL is lane-only after activation, both hosts use matching builds when local lanes participate.
- [ ] Laptop-off and restart receipts identify exact model/auth/config/binding/materialization/describe evidence, frames and S3 content digests with no duplicates.
- [ ] No publication from provider done/review alone; secret sentinel, scoped IAM, retention/cleanup and actual/estimated/unknown cost remain required.

### Minimum verification (future commands, not executed)

- Offline: inspect and use existing deployments/cloud_runtime renderer/image tests; MO-77 creates worker-aws tests, then records exact commands.
- Future runtime proof uses SPEC-11 exact resources/account/us-east-1, verified roles/release/namespace/S3; no deployment is authorized by this amendment.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small receipt refinement; original remote deployment/qualification remains medium.
