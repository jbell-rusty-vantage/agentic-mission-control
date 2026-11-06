---
type: Specification
title: "SPEC-11: Remote operation (slice R): thin Temporal worker on AWS ECS Fargate and the remote launch path"
description: "Owner decision R28: one small always-on Mission Control worker on AWS ECS Fargate in us-east-1. It serves the base queues, the hosted lane queue and the IngressDrainer, so missions on claude_managed, codex_agents and cursor_cloud progress with the owner's machine off. Covers the platform choice, topology, queue roles, exact AWS resources, image, configuration, deploy procedure, operations, cost and acceptance."
tags: [mission-control, specifications, deployment, temporal, aws, remote]
---

**Run 2 close-out disposition (2026-10-18, Gate L):** Gate L: nothing beyond MO-78 (done). Carried forward in full: one-task readiness, laptop-off proof, restart proof, secret sentinel, redeploy and the 24-hour profile (R), with the next deployment session. Criteria below are unchanged; see [the disposition](runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md) and [close-out instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md).

# SPEC-11: Remote operation on a thin AWS worker

Decisions R27–R33 are in [DECISIONS](DECISIONS.md). The background is in [MANAGED-AGENTS-REMOTE-PATH](MANAGED-AGENTS-REMOTE-PATH.md) and [docs/DEPLOYMENT_OPTIONS_2026-10-12.md](../../../DEPLOYMENT_OPTIONS_2026-10-12.md). Issues: MO-78 (namespace setup), MO-77 (this worker) and MO-79 (launch route).

## 1. Decision: AWS ECS Fargate, us-east-1

Temporal Cloud stores workflow state but never runs workflow or activity code (Temporal Cloud security docs). With managed agents the worker only makes HTTPS calls and waits, so it is small. It still has to be a long-lived process, because the IngressDrainer and the lane reconcilers are loops (SPEC-10 §7).

| Option | Monthly | Why chosen or rejected |
| --- | --- | --- |
| **ECS Fargate, 1 task, 0.5 vCPU / 2 GiB, public subnet, no load balancer, no NAT** | **about $30** (§8) | **Chosen.** The payload store is AWS S3 only (`adapters/storage/s3.py` has no endpoint override), and a Fargate **task role** reaches it with no static keys. The AWS CLI is already authenticated to account `298199649527`. The repo already has a reviewed Fargate image and task renderer (`deployments/cloud_runtime`). Supabase and Temporal Cloud are both in `us-east-1`. There is no OS to patch, and it graduates to the prepared API layout later. |
| Fly.io Machine | about $11 | Rejected. It would add a new vendor, the CLI session has expired, and S3 would still need static AWS keys stored as Fly secrets or a code change for Tigris. The cost saving is smaller than the extra moving parts. |
| Temporal Serverless Worker (Lambda, Cloud Run) | near $0 idle | Rejected for now. Lambda is in public preview with a 15-minute invocation limit and a fresh connection per invocation, which cannot host the drainer's LISTEN loop or reconcilers; Cloud Run's release stage is unconfirmed. Revisit after the sprint for the lane activities alone. |
| Lightsail instance | $12–24 | Rejected. Lightsail cannot attach IAM roles (S3 needs access keys on disk), and you manage the OS. |
| Vercel Functions | — | Impossible. A Temporal worker is a long-polling process (SPEC-10 §7). |

## 2. Topology

```text
 anywhere (phone, curl, Claude Code, Linear)            owner machine (optional)
   │ POST /v1/ingress/ai-engineer/missions:request       Windows API :8000 (local launches, missionctl wait)
   ▼                                                     WSL2 lane-only worker: mc-s0-ai-engineer-lane-wsl
 Vercel (overtons-projects, *.vercel.app, iad1)            (claude_agent_sdk, codex, cursor_local)
   Signal Ingress + launch route + provider webhooks              │
   │ ingress_* rows only (no Temporal credentials)                │
   ▼                                                              │
 Supabase AI Engineer project (us-east-1) ◄────────────────────────┤
   ▲ inbox, frames, mission records                               │
   │                                                              ▼
 AWS us-east-1 · ECS Fargate service mc-worker-ai-engineer ───► Temporal Cloud mission-control-dev.ih0e7
   base queues + mc-ai-engineer-lane-hosted + IngressDrainer      (us-east-1)
   │ HTTPS only
   ▼
 Anthropic Managed Agents · OpenAI Agents API · Cursor cloud     S3 mc-payloads-ai-engineer-298199649527-use1
```

**The first application is AI Engineer.** Biotech would need its Application Binding widened for hosted lanes (SPEC-06 §8), and that is a separate owner decision. A Biotech worker later is a second service with its own secrets, bucket and binding.

## 3. Queues and worker roles

| Worker | Where | Role | Queues | Database logins |
| --- | --- | --- | --- | --- |
| `mc-worker-ai-engineer` | AWS Fargate | base (default) | base queues, `mc-ai-engineer-lane-hosted` (`cursor_cloud`, `claude_managed`, `codex_agents`), IngressDrainer | runtime, family-writer, checkpointer |
| WSL2 worker | owner machine | `MISSION_CONTROL_WORKER_ROLE=lane` (MO-63) | `mc-s0-ai-engineer-lane-wsl` only (`claude_agent_sdk`, `codex`, `cursor_local`) | runtime only |

Rules:

- **One base worker per (namespace, application).** Never run the WSL2 worker in base role against `mission-control-dev.ih0e7` for AI Engineer while the AWS service is live. S0's Cloud variant (MO-67) either runs before MO-77 or uses the WSL2 worker in lane role.
- **Build ids.** The build id is the package version plus the short git sha. The AWS worker and the WSL2 lane worker must run the same build whenever local lanes are used (SPEC-09 §2). Versioning behaviour follows MO-78.
- **Lane routing** is the binding's `providers.<lane>.task_queue` (SPEC-09 §3). The AI Engineer launch-bindings file sets the hosted lanes to `mc-ai-engineer-lane-hosted` and the local lanes to `mc-s0-ai-engineer-lane-wsl`.
- **Activities stay short and idempotent.** Long waits are workflow waits: a webhook-driven `ingress_wake` signal or a reconcile timer (SPEC-06 §3).

## 4. AWS resources (all `us-east-1`)

The CLI default region is `us-east-2`, so **every command passes `--region us-east-1`**. Names are fixed so scripts and the orphan check can find them. Every resource is tagged `app=mission-control`, `application=ai-engineer`, `sprint=materialization-observation-2026-10`.

| Resource | Name | Settings |
| --- | --- | --- |
| ECR repository | `mission-control-worker` | Scan on push; lifecycle keeps the last 10 images |
| S3 bucket | `mc-payloads-ai-engineer-298199649527-use1` | Block all public access, SSE-S3, bucket-owner-enforced, no versioning, no expiry until the retention policy says otherwise |
| Secrets Manager | `mission-control/ai-engineer/<NAME>` (§6.2) | Values written only by the owner's `put-secrets.ps1` |
| IAM execution role | `mc-worker-ai-engineer-exec` | `AmazonECSTaskExecutionRolePolicy`, plus `secretsmanager:GetSecretValue` on `mission-control/ai-engineer/*` only |
| IAM task role | `mc-worker-ai-engineer-task` | `s3:GetObject`, `PutObject`, `DeleteObject` and `ListBucket` on the payload bucket only; the ECS Exec SSM channel permissions |
| IAM user for the local API | `mission-control-local-ai-engineer` | The same S3 policy only. The owner creates its access key into the local profile `mission-control`, which is never printed. |
| Security group | `mc-worker-egress-only` | Default VPC; **no inbound rules**; all outbound |
| CloudWatch log group | `/mission-control/ai-engineer/worker` | 14-day retention |
| ECS cluster | `mission-control` | Fargate capacity provider only |
| ECS service | `mc-worker-ai-engineer` | Launch type FARGATE, `linux/x86_64`, 0.5 vCPU / 2 GiB, `desiredCount` 1, default-VPC public subnets with `assignPublicIp` ENABLED (no NAT), deployment minimum 0 % / maximum 100 % (never two base workers at once), ECS Exec enabled, circuit breaker with rollback |
| AWS Budgets | `mission-control-monthly` | **$40 per month** cost budget (R28), alerts at 80 % actual and 100 % forecast to the account email |

## 5. Image

`deployments/worker-aws/Dockerfile` extends the reviewed base `deployments/cloud_runtime/Dockerfile`, which has pinned Python and uv digests, a frozen lock, a non-root user and no `.env`. It adds the following under `/etc/mission-control`:

- `deployments/ai-engineer/target.toml` and `release.lock.json`;
- the capability pins and bundles the bindings reference (digest-verified at build);
- the AI Engineer launch-bindings file with the task-queue routing from §3.

`CMD ["python", "-m", "mission_control.bootstrap.worker"]`. Build with `--platform linux/amd64`. The image contains **no secret values**: a sentinel test greps the image filesystem for every secret name's value pattern.

The repository's runtime dependencies currently pull in pytest transitively (cloud_runtime README). That is accepted for the sprint.

## 6. Configuration

### 6.1 Plain environment (task definition)

| Variable | Value |
| --- | --- |
| `TEMPORAL_TARGET` | `cloud` |
| `TEMPORAL_ADDRESS` | `us-east-1.aws.api.temporal.io:7233` |
| `TEMPORAL_NAMESPACE` | `mission-control-dev.ih0e7` |
| `MISSION_CONTROL_LANE_TASK_QUEUES` | `mc-ai-engineer-lane-hosted` |
| `S3_BUCKET` | `mc-payloads-ai-engineer-298199649527-use1` |
| `AWS_REGION` | `us-east-1` |
| `AWS_PROFILE` | empty string. `settings.aws_profile` defaults to `default`, which does not exist in ECS; empty makes the S3 session use the task role. |
| Drainer and application selectors | as named by MO-75 and the AI Engineer binding |

### 6.2 Secrets (Secrets Manager → `secrets` in the task definition)

Runtime DSN, family-writer DSN, checkpointer DSN, `TEMPORAL_CLOUD_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CURSOR_API_KEY`, and the GitHub App private key once R26 lands. The task's entrypoint writes the GitHub key to a tmpfs file and sets `MC_GITHUB_APP_PRIVATE_KEY_PATH`, because ECS injects secrets as env values only. MO-77 fixes the exact names from `bootstrap/settings.py`. The Secret Broker's env source reads them (MO-11).

### 6.3 Database connectivity

Supabase direct hosts are IPv6 and the default VPC is IPv4, so **all three DSNs use the Supabase session pooler** (`aws-0-us-east-1.pooler.supabase.com:5432`, user `<role>.<project_ref>`, TLS required). MO-77 verifies two things:

- the restricted roles authenticate through the pooler;
- LISTEN works in session mode.

If LISTEN does not work, the drainer runs on its 5-second poll (MO-75 already has the fallback). Startup verification (installation identity, release fingerprint, roles) must pass unchanged.

## 7. Deploy and operate

The owner runs one script, once, and the team runs the rest:

```powershell
# owner, once (values never echoed): writes the named .env keys to Secrets Manager
pwsh deployments/worker-aws/put-secrets.ps1 -Application ai-engineer -Region us-east-1

# team, every release (no GitHub needed; build happens locally)
pwsh deployments/worker-aws/deploy.ps1 -Application ai-engineer -Region us-east-1
#   docker build --platform linux/amd64 -f deployments/worker-aws/Dockerfile -t mission-control-worker:<ver>-<sha> .
#   aws ecr get-login-password | docker login …; docker push …
#   python deployments/cloud_runtime/plan.py <reviewed worker plan> → task definition JSON (secret ARNs only)
#   aws ecs register-task-definition …; aws ecs update-service --cluster mission-control --service mc-worker-ai-engineer …
#   aws ecs wait services-stable …; aws logs tail /mission-control/ai-engineer/worker --since 5m
```

| Operation | Command (always `--region us-east-1`) |
| --- | --- |
| Logs | `aws logs tail /mission-control/ai-engineer/worker --follow` |
| Stop (keeps everything, $0 compute) | `aws ecs update-service --cluster mission-control --service mc-worker-ai-engineer --desired-count 0` |
| Start | the same with `--desired-count 1` |
| Roll back | `deploy.ps1 -TaskDefinitionRevision <n>`, or `update-service --task-definition mc-worker-ai-engineer:<n>` |
| Shell for debugging | `aws ecs execute-command … --interactive --command /bin/sh` (owner-approved at the time) |

**Stopping the service is safe.** Temporal keeps every workflow, and provider sessions keep running at the provider. When the worker returns, lanes reattach and reconcile from provider history.

## 8. Cost (list prices, read 2026-10-12)

| Item | Basis | Monthly |
| --- | --- | --- |
| Fargate compute | x86 us-east-1: $0.000011244 per vCPU-second and $0.000001235 per GB-second; 0.5 vCPU + 2 GiB for 730 h | about $21.30 |
| Public IPv4 address | $0.005 per hour | about $3.65 |
| Secrets Manager | about 9 secrets at $0.40 | about $3.60 |
| CloudWatch logs, ECR storage, S3 | low volume | about $1–2 |
| **Total** | | **about $30**, under the $40 budget |

Temporal Cloud actions, Supabase and model tokens are separate. Fargate Spot and ARM (Graviton, about 20 % cheaper per vCPU) are post-sprint options once a 24-hour CPU and memory profile exists (MO-77 acceptance).

## 9. Security

- **No inbound path.** The security group has no inbound rules, and the worker only dials Temporal Cloud, Supabase, S3 and the provider APIs.
- **Least privilege.** The task role reaches one bucket. The execution role reads one secret prefix. Organisation API keys exist only in Secrets Manager and the running task's environment, never in images, task definitions, logs or sandboxes.
- **Never print secrets.** Neither agents nor scripts print secret values. `put-secrets.ps1` is owner-run, and handoffs cite secret names and ARNs only.
- **Data class.** The worker serves AI Engineer at `internal` or lower (SPEC-06 §8).

## 10. Acceptance (MO-77)

- The service runs one task with no inbound rules, and readiness passes against Temporal Cloud, Supabase (pooler) and S3.
- **Laptop-off proof:** with the owner's machine powered off, a hosted-lane probe mission runs to completion on the AWS worker, and its frames and payloads land in Postgres and S3.
- **Restart proof:** stopping and restarting the service mid-session reattaches with no duplicate frames.
- **Secret sentinel:** no secret value in the image, task definition, logs, repo or handoff.
- `deploy.ps1` redeploys a new build with no console steps.
- The 24-hour CPU and memory profile and the cost estimate are recorded in the handoff.

## 11. Owner steps

| # | Step | When |
| --- | --- | --- |
| AW1 | Approve the $40/month AWS budget (default set by R28; change it if you want a different ceiling) | Before MO-77 creates resources |
| AW2 | Run `put-secrets.ps1` | When MO-77 asks (wave B) |
| AW3 | Create an access key for `mission-control-local-ai-engineer` into profile `mission-control` (`aws configure --profile mission-control`) | Before the Windows API uses S3 (MO-64) |
| AW4 | Make `Overton77/bell-missions-ai-engineer` private, or accept that knowledge outputs there are public (R23) | Before HL-24's knowledge mission |

## Run 2 approved refinements (2026-10-14)

MO-77's laptop-off/restart evidence identifies build, queue role, installed release/fingerprint, exact provider bindings/configuration and immutable frame/output custody. Preserve one base worker, matching local build when participating, lane-only WSL and exact AWS resource/region/size limits. The existing codex_agents lane is the HTTP OpenAI hosted Agents API, not Agents SDK or direct Responses; do not rename wire enums. HL-24 precedes HL-25 and both remain exact-placement qualification with no secret, budget or acceptance shortcuts. Managed Agents budget-gate pause/resume is currently blocked: hold/release helpers have no production control caller and describe declares unsupported. Boundary hold is separate and does not satisfy HL-24's budget-gate requirement; see the shared blocker and proposed escalation.

[Detailed approved rules and issue mapping](runs/RUN-2-PLANNING-AMENDMENTS.md). These refine remaining acceptance and grant no new execution, spending or deployment authority.
