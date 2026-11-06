# Cloud runtime package

The [concrete approval plan](APPROVAL_PLAN.md) lists exact proposed Ohio resources,
network exposure, IAM/secret boundaries and current regional cost assumptions.
Its verified regional estimate supersedes the illustrative compute-only example below.

Status (2026-10-11): **prepared, not deployed**. No image was published, resource
created, IAM changed, database migrated, provider run started, or endpoint exposed.
The included infrastructure renderer targets one shared Mission Control API and one long-lived ECS
Fargate worker per admitted application, with external Temporal Cloud, the existing
application PostgreSQL databases, and separately qualified Agent Server endpoints.
It needs a numeric monthly ceiling and a concrete resource/security approval before
any deployment. The idle unrelated AWS scraper cluster is not an approved target.

The minimum AWS candidate is one Biotech Lightsail host at **$24/month**, with a proposed
**$40/month AWS planning ceiling** including snapshot and contingency assumptions. It is
not approved, deployed or a hard billing cap. Managed services/provider usage are separate;
capacity, production bindings, secure access and restore policy still need qualification.
The ECS renderer does not install this host. See the approval plan's first decision.

Running on the existing Docker host is a **local alternative**, adding $0 AWS compute;
it does not fulfill the requested AWS deployment. No production local installation or
public endpoint was created by the disposable-service tests or image build.

## What this package implements

- `Dockerfile`: explicit source-only, frozen-lock Python build, nonroot runtime,
  dev dependency group omitted, no copied `.env`, no database initialization.
  Verified Linux/amd64 Python and uv digests are pinned defaults. It is a base image:
  reviewed public configuration, JWKS, runtime-options factory and pinned capability
  assets must be packaged in an operator image before a worker can become ready.
- `plan.py`: offline strict TOML validation and deterministic ECS task/service review
  inputs. No boto client, subprocess, network or deployment path exists. Secret
  values are forbidden; existing same-account/region Secrets Manager ARNs are used.
  Errors omit input values. Unresolved example selections fail with exit 2.
- `plan.example.toml`: one API and one app worker. Add an independently scoped
  AI Engineer worker for two-app rollout. API's deployment registry and secret
  references must contain every app the shared API serves; workers receive only
  their own app registry/credentials and exact binding digest.
- `test_plan.py`: offline negative boundary and inert-plan tests.
- `goal-named-output-binding.json`: exact built-in named executor schema binding fragment
  for Deep Agents multi-output GoalDirected runs. Merge only the executor binding into a
  reviewed operator configuration; retain its verifier and other settings. Both the original
  executor schema and this additive revision are served. No live configuration was changed.

```powershell
uv run --no-sync python deployments/cloud_runtime/plan.py reviewed-plan.toml > reviewed-plan.json
uv run --no-sync pytest deployments/cloud_runtime/test_plan.py -q
docker build --platform linux/amd64 -f deployments/cloud_runtime/Dockerfile -t mission-control:cloud-runtime-check .
```

The Linux base image build and credential-free API/worker import smoke passed.
See [build evidence](BUILD_EVIDENCE.json). The local image ID is not a published
registry manifest digest; publication remains unauthorized. The image does not
include operator assets and has not passed live startup/readiness qualification.
Runtime dependencies currently include pytest transitively through the project's
existing `langsmith[pytest,sandbox]` extra even though the dev group is omitted.

The emitted task-definition objects match `ecs register-task-definition` input
structure. Services deliberately have `desiredCount: 0` and an unresolved exact
task-definition ARN: the document is for review, not unattended application. No
IAM, security group, secret, cluster, log group, NAT, load balancer or database is
created. The renderer validates syntax and separation; it does **not** attest that
resources exist, credentials have least privilege, images contain the claimed
configuration, secrets match bindings, or a budget has been approved.

## Placement and authority

| Component | Placement and responsibility |
| --- | --- |
| Mission Control API | AWS long-lived container; authenticated app/tenant routing, submission, retrieval and durable controls; `/health/live` is process health, `/health/ready` reports installation availability |
| Mission Control app worker | AWS long-lived container; Temporal pollers, bounded Deep Agents execution, provider adapters, persistence and reducers; one explicit application binding per process |
| Temporal Cloud | Durable scheduling, waits, signals, history and worker recovery; no container lifetime assumption; use existing approved namespaces, TLS/API key, explicit `TEMPORAL_TARGET=cloud` |
| App PostgreSQL | Existing app's `mission_control` authority; restricted runtime/family roles and independent `mission_control_runtime` saver/store role; startup validates installation/release, never migrates |
| Deep Agents | Bounded cognition; worker-owned saver/store is subordinate recovery state, not a duplicate mission ledger |
| Agent Server | Only where admitted async child graphs need it; managed endpoint preferred conditionally, with exact revision/auth/native persistence qualification; never the mission scheduler |
| LangSmith | Trace correlation and sandbox execution; neither trace availability nor sandbox existence proves fulfillment |
| Durable object store | Captured bytes and digests outside container/sandbox lifetime; current worker has S3 payload support; API runtime-options factory must use the same authorized store |

Start with API 0.5 vCPU/2 GiB and each worker 1 vCPU/2 GiB as **unmeasured sizing
candidates**, one service task each. Two apps total 2.5 vCPU/6 GiB before managed
components. Container sizing is not provider concurrency admission. Configure and
qualify catalog/run budget limits; existing worker poller defaults are not a global
paid-call cap. Swarm, evaluator/optimizer, StageGraph and GoalDirected remain
Mission Control workflow semantics and can share workers if registered/qualified;
multiple Agent Server graphs do not give independent capacity or deployments.

The services have no public IP and no ECS Exec. They require approved private
egress for Temporal/provider/Supabase APIs, ECR image pull and logging, and an
approved authenticated ingress route for the API. No such route was verified in
the inventory. Adding NAT/ALB/VPC endpoints/public access changes both cost and
security scope. Do not change `assignPublicIp` to bypass this gate.

## Agent Server topology and current limits

The public LangSmith plan is called **Plus**, not Pro. Public pricing lists a
$39/seat/month Plus plan with one Small Serverless deployment. This is **not proof
of this account's entitlement or whether its included deployment is already used**.
Source: [official pricing](https://www.langchain.com/pricing).

Small Serverless is documented with 1 vCPU/2 GiB, shared database, scale-to-zero and
cold starts. Multiple graphs share deployment capacity and revision. It is a
candidate for bounded async child graphs after qualification, not a replacement
for always-running Temporal pollers or a guarantee of application database
isolation. Source: [cloud features](https://docs.langchain.com/langsmith/cloud-platform-features).

Deep Agents async subagents need an Agent Protocol-compatible server. The official
guide recommends co-deploying graphs in `langgraph.json`; synchronous local
subagents do not independently require a hosted server. This repo's canonical
`agent_server/langgraph.json` already registers child/qualification graphs and
custom authentication, and its runtime profile restricts exposed graphs. Source:
[async subagents](https://docs.langchain.com/oss/python/deepagents/async-subagents).

**Recorded specification conflict:** the general specification conditionally starts
Agent Server native persistence in private app-local schemas. Accepted ADR-0017 and
the pinned topology audit establish that `langgraph-api==0.12.0` cannot safely use
that topology; native server tables collide with standalone saver/store tables.
The spec's compatibility condition is unmet. Do not use `search_path` or the
business `public` schema as a workaround. Each application's Agent Server native
database needs a qualified isolated placement. The worker's standalone
`mission_control_runtime` saver/store remains in the selected application database;
it is a different persistence subsystem. See
[ADR-0017](../../docs/adr/0017-agent-server-runtime-persistence-separate-database.md)
and [pinned audit](../../packages/mission-control-db-contract/runtime/AGENT_SERVER_TOPOLOGY.md).

Self-hosted Agent Server also requires PostgreSQL, Redis and a production license
decision. Plus is not evidence of a self-hosted production license. No standalone
server service is included in this package. Source:
[standalone deployment](https://docs.langchain.com/langsmith/deploy-standalone-server).

A background run's default timeout is 24 hours; an HTTP/stream limit of one hour
requires reconnecting to durable run identity rather than classifying the mission
as failed. Persist thread/run IDs and checkpoint handles and test native
cancel/restart against the chosen server. Sources:
[Agent Server](https://docs.langchain.com/langsmith/agent-server),
[environment settings](https://docs.langchain.com/langsmith/env-var-cloud).

Sandboxes are disposable: documented defaults include a 10-minute idle stop,
deletion 14 days after stopping, and short command-output retention (5 minutes).
Capture intermediate evidence and final bytes before those limits; an exported
file, metadata snapshot and resumable execution checkpoint are distinct. Sandbox
environment values are plaintext; use an explicitly approved auth proxy rather
than putting provider secrets there. Sources:
[sandbox SDK](https://docs.langchain.com/langsmith/sandbox-sdk),
[auth proxy](https://docs.langchain.com/langsmith/sandbox-auth-proxy).

## Preflight and release procedure

1. Obtain the monthly AWS ceiling plus separate model/sandbox proof allocation.
   Resolve exact target region, resource references, private egress/API ingress,
   IAM principals and managed endpoints. Review their costs and grant changes.
2. Verify existing resource metadata read-only. Confirm both app installation IDs,
   common release locks and native runtime topology. The operator guide previously
   records live common release 1.0.0 and newer scratch-only releases; that historical
   record is **not** a current live schema attestation. Apply no migration here.
   This implementation requires common component **1.3.0** (including migration
   `0034_provider_frame_lifecycle_body.sql`) and the new
   `mc.catalog.workflow-parity@1.0.2` seed (workflow-family asset version 3).
   Existing app release locks and prior seed bytes remain unchanged; reconcile
   them through a separately approved installation plan before starting this runtime.
3. Assemble each app's sealed deployment JSON, public JWKS, exact runtime-options
   module and capability assets. Package only public configuration/source assets.
   Use task-specific secret injection and task-role credentials, never CLI credentials
   or static AWS access keys. No placeholder models, auth grants or providers.
4. Verify frozen dependency resolution and Linux image build with pinned base
   digests; scan image contents for accidental private inputs. Record source/lock,
   image, configuration, schema, graphs and binding digests as the release receipt.
   Build/push and new credential provisioning require their applicable approvals.
5. Run the existing `mission_control.bootstrap.preflight readiness` with the reviewed
   profile. Run full startup preflight only with approved read-only targets and
   inspect its configured composition: API composition may start configured relay
   pumps. Do not assume every full-startup action is read-only. Worker start can
   create/update the retention schedule and promote worker versions.
6. After approval, register reviewed task definitions and start one worker per app
   plus the shared API. Replace the service plan's placeholder with the **exact**
   task definition revision, explicitly review changing desired count to one, and
   wire the already-approved ingress. This package performs none of these writes.
7. Verify `/health/live`, `/health/ready` including `production_ready`, authenticated
   app/tenant reads and cross-app denial. Check Temporal pollers, release identity,
   object retrieval and log access. Process health alone is not execution readiness.
8. Only within a finite proof budget run a representative admitted workflow:
   submit idempotently, observe progress, capture artifacts, verify required outputs,
   cancel another run, restart a worker and reconcile its same native execution.
   A provider success is not mission acceptance. Record passed/failed/blocked evidence.

## Operations and recovery

Logs use existing CloudWatch groups, nonblocking mode and a bounded 5 MiB buffer;
this avoids logging outages stopping the worker but can lose logs. Configure
retention in the approved resource plan. Logs/traces are not the durable ledger.
Propagate application/mission/run/operation/native run IDs; redact credentials,
raw sensitive prompts and content. The API health check deliberately uses liveness;
dependency outages should not cause endless process replacement. Poll detailed
readiness externally and alert on unavailable apps, missing pollers, relay lag,
heartbeat failures, uncertain effects, artifact failures and checkpoint errors.

SIGTERM has a 60-second container stop budget; the current worker graceful shutdown
default is 10 seconds. ECS replacement provides process recovery, Temporal history
and heartbeats provide durable retry, and the dispatch journal/native IDs prevent
blind resubmission. Verify these together before claiming restart reliability.
The service plan prevents rolling surge (`maximumPercent=100`) to constrain cost,
which causes a short single-replica outage. This is not a high-availability layout.

Back up application metadata, object bytes/version IDs, standalone saver/store,
native Agent Server runtime state and retained Temporal histories as separate
authorities. Preserve execution bindings and cryptographic keys needed for reads.
Restore only to disposable targets first; verify artifact hashes and reconcile
uncertain side effects before resume. Neither restarting containers nor a database
backup recreates sandbox files. Use service/API cancellation, not task termination,
for user-requested mission cancellation. Stop new admission before planned outage;
do not shut down a shared managed deployment to stop an individual mission.

Native thread TTL, checkpoint pruning, frame retention, object expiry and trace
retention are separate controls. Set an explicit policy; do not delete artifacts
still referenced by mission evidence. Thread lifetime is not guaranteed by trace
retention. [Official TTL guidance](https://docs.langchain.com/langsmith/configure-ttl).

## Cost model and remaining blockers

No deployment quote is accepted. AWS bills Fargate requested CPU/memory from image
pull until stop, separately from logs, data transfer, networking and storage.
The official N. Virginia Linux/x86 example quotes $0.000011244/vCPU-second and
$0.000001235/GiB-second. At those **illustrative us-east-1** rates, 730 hours of
2.5 vCPU/6 GiB is about **$93.35/month compute only**; one app plus API is about
$57.31. These are not verified us-east-2 prices or spending caps. Add Temporal,
Agent Server, tracing, model/tool calls, sandbox compute/storage, private egress,
ingress, secrets, logs, artifact storage, transfer and taxes. Source:
[AWS Fargate pricing](https://aws.amazon.com/fargate/pricing/).

LangSmith deployment, sandbox and tracing meters are separate. The October 2026
billing transition and any existing account agreement must be checked before
assuming an allowance or zero incremental cost. Source:
[LangSmith billing](https://docs.langchain.com/langsmith/billing).

Blockers: approved numeric spend limit; exact resource/security plan and private
network path; account-specific LangSmith entitlement/available deployment slot;
Agent Server per-app isolation/auth/license decision; verified Temporal namespace;
current common-release/runtime readiness; reviewed Linux capability/config image;
durable object-store binding; authenticated production endpoint and budgeted
provider/restart/cancel qualification. No endpoint was deployed or verified.

## Provenance

Prepared from the accepted spec/runtime operator guide, current source entrypoints,
ADR-0017 and pinned Agent Server topology audit; official vendor documentation
reviewed 2026-10-11, with LangSmith research supplied by the coordinating task.
[Inventory](INVENTORY.md) separates account observations from architecture choices.
