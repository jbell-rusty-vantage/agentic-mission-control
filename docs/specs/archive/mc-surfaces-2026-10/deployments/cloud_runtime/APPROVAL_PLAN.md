# Concrete deployment proposal requiring owner approval

Prepared 2026-10-11 for account `298199649527`, **us-east-2 (Ohio)**. Nothing in this
document authorizes execution. Local image build is proven; production deployment
is not. All resource names below are proposed names, not existing resources.

**Minimum AWS candidate for approval:** Biotech only on one new **Lightsail Linux/amd64
host in Ohio, 2 vCPU / 4 GiB / 80 GB, $24/month**, running the API and a separately
supervised Temporal worker. Propose a **$40/month AWS planning ceiling**: $24 host,
$4 for an assumed 80 GB-month of retained snapshots at $0.05/GB-month, and $12
contingency. This is an estimated approval request, not an approved or enforced cap;
snapshot growth and excess transfer can exceed it. Managed databases, Temporal,
LangSmith, models, tools, sandboxes, tax and domain costs are separate. The 4 GiB size
requires a memory/concurrency qualification before production use; no measured capacity
or availability guarantee is claimed. [Official bundle and snapshot prices](https://aws.amazon.com/lightsail/pricing/).

Proposed scope: one host named `mission-control-biotech`, one bounded local artifact
volume, retained instance snapshots, bounded local container logs, restart supervision,
and one API process plus one worker process from the verified image. Keep API ingress
on loopback for initial qualification; review owner-selected SSH source CIDRs and the
existing approved administrative key before creation. Remote API access initially uses
an explicitly approved administrative tunnel; public TLS ingress is a separate approval.
Use the existing external application PostgreSQL, separate graph checkpointer and
Temporal namespace only after their exact production bindings and credential recipients
are approved. No local production database, new Agent Server, ALB, NAT, ECS cluster,
ECR, runtime IAM role or copied operator AWS credentials are included in this minimum.
Filesystem artifact custody requires disk limits and a restore-qualified snapshot policy;
it does not provide S3 availability. The host remains a single point of failure.

**Still blocked:** numeric AWS and separate managed/provider limits; secure host access
and secret handoff; exact production service bindings; supervised host configuration;
artifact retention/restore qualification; finite paid workflow qualification budget.
Any live migration needs separate approval. The existing renderer prepares ECS inputs,
not a Lightsail installation: after these decisions, host-specific configuration must be
completed and reviewed before creation. Nothing has been deployed and no AWS endpoint exists.

**Local alternative, not fulfillment of the requested AWS deployment:** the existing
Docker host can run one application with loopback access for $0 new AWS compute.
It still needs production bindings, supervision, secure secret recipients and an awake
host. The local image and disposable-service proofs do not constitute this installation
or the AWS deployment. LangSmith entitlement and async-child hosting remain account gates.

The retained **ECS/Fargate alternative** uses private tasks, one public TLS API load balancer
and one NAT gateway. Its two-app AWS
operating estimate is **$166–185/month**, or approximately **$185–205 with 10%
planning contingency**. A first-app rollout removes one worker and is approximately
**$130–149/month**, or **$145–165 with contingency**. These are conditional estimates,
not spending caps. Temporal, LangSmith, Supabase and provider usage are additional.
The account-specific all-in total remains unresolved; do not promise a single
all-in price before the managed-service gates below are settled.

## Retained ECS alternative: exact proposed AWS scope

| Resource | Proposed configuration | Existing versus new |
| --- | --- | --- |
| ECS cluster | `mission-control-prod`, Fargate on-demand Linux/amd64, ECS Exec disabled | New; cluster object has no allocated compute itself |
| API service | `mission-control-api`, one task, **0.5 vCPU / 2 GiB**, port 8000 internal | New billed compute |
| Biotech worker | `mission-control-biotech-worker`, one task, **1 vCPU / 2 GiB**, no inbound port | New billed compute |
| AI Engineer worker | `mission-control-ai-engineer-worker`, same size, own binding/roles/secrets | New billed compute; omit during first-app stage |
| Networking | Dedicated `mission-control-prod` VPC, proposed `10.42.0.0/20`; public subnets `10.42.0.0/24` and `10.42.1.0/24`; private subnets `10.42.8.0/24` and `10.42.9.0/24`, across two Ohio AZs | New; CIDR/AZ final collision/availability check required |
| Placement/egress | Tasks initially in first private subnet; one zonal NAT gateway and one Elastic IP in same AZ; S3 gateway endpoint | New NAT/IP charges; S3 gateway endpoint has no hourly/data-processing charge |
| API ingress | `mission-control-api` internet-facing ALB in both public subnets, TLS 443 only, target group HTTP 8000 to private API | New ALB/LCU/public IPv4 charges and public exposure |
| DNS/TLS | Owner-selected hostname, DNS-validated nonexportable ACM public certificate in Ohio, DNS record to ALB | No existing ACM cert or Route53 zone observed; domain/DNS provider must be selected; no domain purchase proposed |
| Registry | Private ECR `mission-control/runtime`; immutable release tags, keep three reviewed images | New storage; no reuse of scraper or CDK repositories |
| Artifact bytes | Private versioned S3 buckets `mc-298199649527-use2-biotech-artifacts` and `mc-298199649527-use2-ai-engineer-artifacts`; block public access, SSE-S3, TLS-only policy | New storage/requests; names require availability check; app metadata remains in Supabase |
| Logs/alarms | `/mission-control/prod/runtime`, separate service stream prefixes, 14-day log retention; ten ordinary metric alarms | New logs/alarms; no enhanced Container Insights or metered synthetic canaries |
| Credentials | Three execution roles + three task roles; up to 16 named Secrets Manager entries | New persistent permissions/secret storage; must be separately approved |

One NAT and one task per service limit cost but create single-AZ/process availability
constraints. An ALB spanning two AZs does not make one API task highly available.
No autoscaling or rolling surge is proposed. Deployment update can briefly interrupt
API service; Temporal resumes worker processing from durable state. Do not label
this topology highly available or silently add replicas/NAT gateways.

The renderer currently prepares **task definitions and inert private service inputs**.
It does not provision this VPC, ALB, bucket, IAM, DNS or secret plan, nor attach ALB
target groups. After approval, infrastructure templates and final service inputs
must be completed against exact resource IDs and reviewed before application.

## Public exposure and network permissions to approve

- ALB security group: inbound TCP 443 from `0.0.0.0/0`; IPv6 disabled initially.
  Outbound TCP 8000 to API security group only. No public port 80 or database port.
  This is a **new public endpoint** and requires explicit approval. If the owner
  chooses fixed client CIDRs, replace the source before deployment; that is a
  different access decision, not an implicit restriction already configured.
- API security group: inbound TCP 8000 from ALB security group only. Worker security
  groups: no inbound rules. Every task has `assignPublicIp=DISABLED`.
- Task egress: TCP 443 to internet through NAT for approved provider/Agent Server,
  registry, secrets and logs APIs; TCP 7233 for configured Temporal Cloud gRPC.
  PostgreSQL TCP 5432, or 6543 only if the reviewed binding uses it, is restricted
  to the selected Supabase route's verified destination CIDRs. Resolve these before
  deployment; do not invent CIDRs or allow broad database egress as a fallback.
- Standard security groups do not enforce DNS host allowlists. Broad HTTPS/gRPC
  egress is an explicit part of this proposal; adding a filtering proxy/firewall is
  a separate resource/cost/security decision. DNS uses the VPC resolver.
- ALB forwards approved `/v1/*` and admitted MCP paths only. Default response is 404;
  do not expose `/docs`, `/openapi.json` or health-details paths through the public
  listener. ALB health checks use internal `/health/ready`; also inspect its
  `production_ready` body operationally, because HTTP 200 alone is insufficient.
- App endpoints require current issuer/JWKS verification, subject/tenant grants and
  app binding checks. TLS terminates at ALB; ALB-to-task traffic is HTTP inside the
  private VPC. WebSockets/Socket.IO routing is a separate reviewed enablement if
  needed. No provider callback ingress or worker hook listener is exposed.
- No WAF, VPN, bastion, new OAuth grant, public S3 access or remote shell is included.
  Any such addition changes this approval scope. JWT auth is not a DDoS cost cap.

## IAM and persistent credential boundary

Each role trusts `ecs-tasks.amazonaws.com`, with `aws:SourceAccount=298199649527`
and `aws:SourceArn=arn:aws:ecs:us-east-2:298199649527:*`. Proposed names are
`mc-prod-api-execution`, `mc-prod-biotech-execution`, `mc-prod-ai-engineer-execution`
and matching `mc-prod-*-task` roles. Runtime roles receive no IAM mutation, ECS
control, database administrator or migration authority.

| Principal | Exact action set and resource restriction |
| --- | --- |
| Each ECS execution role | `ecr:GetAuthorizationToken` on `*` (API requires it); `ecr:BatchCheckLayerAvailability`, `ecr:GetDownloadUrlForLayer`, `ecr:BatchGetImage` on `mission-control/runtime` only |
| Each ECS execution role | `logs:CreateLogStream`, `logs:PutLogEvents` on its service prefix in the precreated `/mission-control/prod/runtime` group; no create-log-group permission |
| Each ECS execution role | `secretsmanager:GetSecretValue` on exactly the secret version references that its task injects; no List/Get on unrelated secrets |
| API task role | `s3:GetObject`, `s3:GetObjectVersion`, `s3:PutObject` on reviewed content prefixes in both app buckets, because app-authorized reads/authoring use both; no delete/bucket-policy actions |
| Each worker task role | Same object actions on its own app bucket/prefix only; never the other application's objects |
| Conditional customer-managed key | `kms:Decrypt` only if selected existing secret encryption requires it, scoped by key and `kms:ViaService`; no new customer-managed KMS key proposed |

Use AWS-managed Secrets Manager encryption and SSE-S3 for the baseline. Secrets
are injected by ECS execution identity; application code uses task-role S3
credentials via the standard AWS chain. Do not copy `overtonadmin` credentials or
grant `iam:PassRole` to runtime code. A human-approved deployment identity may need
`iam:PassRole` on these six exact roles, with `iam:PassedToService=ecs-tasks.amazonaws.com`,
plus explicitly reviewed resource-create/update permissions. No new broad operator
role is proposed. [AWS execution-role contract](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_execution_IAM_role.html).

Proposed secret **names**, not values or existing ARNs:

| Secret path beneath `mission-control/prod/` | Injected variable / recipients |
| --- | --- |
| `{biotech,ai-engineer}/runtime-dsn` (2) | App binding's `MC_*_RUNTIME_DSN`; API and matching worker |
| `{biotech,ai-engineer}/family-dsn` (2) | `MC_*_FAMILY_DSN`; matching worker and API only where reviewed launch composition requires family writer |
| `{biotech,ai-engineer}/checkpoint-dsn` (2) | `LANGGRAPH_CHECKPOINT_DATABASE_DIRECT`; matching worker only |
| `temporal-cloud-api-key` (1) | `TEMPORAL_CLOUD_API_KEY`; API/workers scoped to the approved namespace(s) |
| `runtime-checkpoint-signing-key` (1) | `RUNTIME_CHECKPOINT_SIGNING_KEY`; consistent API/workers; distinct from Supabase service-role credentials |
| `inspection-cursor-key` (1, optional) | `INSPECTION_CURSOR_KEY`; shared API pagination key; otherwise derived by existing code from checkpoint key |
| `providers/openai`, `providers/anthropic`, `providers/cursor` (up to 3) | Existing approved provider credentials; only workers actually admitting those provider lanes |
| `langsmith-api-key` (1) | Only roles needing trace/sandbox/managed access, according to existing scoped credential permissions |
| `{biotech,ai-engineer}/agent-server-token` (up to 2) | `AGENT_SERVER_API_KEY` or exact existing child-auth reference per reviewed server binding |
| `trace-pseudonym-key` (1) | `BELL_LABS_TRACE_PSEUDONYM_KEY` where required for stable trace attribution |

At most 16 secrets are costed; unused providers/async routes are not provisioned.
Do not create new provider credentials or move raw existing keys until the owner
approves the recipients, storage and secure handoff. No migration DSN, Supabase
owner/service-role fallback, local CLI OAuth cache or user browser credential is
injected. API receives no provider model key by default. Exact ARNs and runtime
composition still need per-app verification; table names do not constitute bindings.

## Verified regional AWS estimate

730 hours/month, on-demand Linux/x86, no free-tier/credit/Savings Plan assumption,
three tasks, three public IPv4 addresses (two ALB + one NAT), 16 secrets, 3 GB ECR,
20 GB total artifact storage including versions, 10,000 S3 writes and 100,000 reads,
10,000 secret reads, ten standard alarms. Low/high traffic assumptions are explicit.

| Meter | Rate | Monthly low–high USD |
| --- | --- | ---: |
| API 0.5 vCPU/2 GiB | $0.04048/vCPU-hour + $0.004445/GiB-hour | 21.2649 |
| Two workers, each 1 vCPU/2 GiB | same | 72.0802 |
| One ALB + 0.1–1 average LCU | $0.0225/hour + $0.008/LCU-hour | 17.009–22.265 |
| One NAT + 10–50 GB processed | $0.045/hour + $0.045/GB | 33.30–35.10 |
| Three public IPv4 addresses | $0.005/address-hour | 10.95 |
| 16 secrets + 10k reads | $0.40/secret-month + $0.05/10k requests | 6.45 |
| Logs: 5–20 GB ingest, 1–10 GB-month archive | $0.50/GB + $0.03/GB-month | 2.53–10.30 |
| Ten standard alarms | $0.10/alarm-month | 1.00 |
| ECR 3 GB | $0.10/GB-month | 0.30 |
| S3 20 GB + stated requests | $0.023/GB-month; $0.005/1k writes; $0.0004/1k reads | 0.55 |
| Internet transfer planning allowance | 0–50 GB at $0.09/GB, credits ignored | 0–4.50 |
| **AWS subtotal** | No tax or domain purchase | **165.4341–184.7601** |

Official regional JSON read directly on 2026-10-11:
[ECS](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECS/current/us-east-2/index.json),
[ALB](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSELB/current/us-east-2/index.json),
[CloudWatch](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonCloudWatch/current/us-east-2/index.json),
[S3](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonS3/current/us-east-2/index.json).
Other official rates: [VPC/NAT/IP](https://aws.amazon.com/vpc/pricing/),
[Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/),
[ECR](https://aws.amazon.com/ecr/pricing/).

Tasks stay in the NAT's AZ to avoid the ordinary cross-AZ NAT charge in this
baseline. Traffic, retries, retained object versions, ALB address scaling and log
volume can exceed assumptions. Existing domain DNS is assumed; a new hosted zone,
registration, additional NAT/replicas, custom metrics, scanning or WAF needs a
revised estimate. Nonexportable public ACM certs used with ALB have no extra
certificate charge under the documented model; do not choose a paid exportable
certificate. [ACM pricing](https://aws.amazon.com/certificate-manager/pricing/).

## Managed components and conditional total

### Smaller single-application starter

The smallest available host verified here is the existing local Docker host. Run
one API process and one Temporal worker process there, keeping API access on
loopback: **$0 additional cloud compute**, with host power, connectivity and uptime
remaining the operator's responsibility. This is a topology assessment, not a
running production installation. Disposable proof databases must not become the
production targets. The current ECS renderer still creates separate tasks; it
does not implement host supervision. API and worker require separate supervised
processes, shutdown handling and health checks. Four GiB is a qualification
candidate, not a measured memory requirement.

| Single-app option | Fixed compute baseline | Additional usage and qualification |
| --- | --- | --- |
| Existing local Docker host | $0 new cloud compute | Existing managed subscriptions, traffic, models and tools; host must stay awake |
| New Lightsail Linux host | $24/month for 2 vCPU, 4 GB RAM, 80 GB SSD and public IPv4; $44 for 8 GB | Snapshots, excess transfer, secrets/logs and managed usage; new resource approval and runtime identity required |
| Earlier single-app Fargate plan | About $130–149/month AWS under this document's assumptions, $145–165 with reserve | ALB/NAT dominate its fixed overhead; usage can exceed assumptions |

Lightsail's listed 4 GB bundle includes 4 TB transfer. Its AWS identity arrangement
needs qualification: ECS task roles cannot simply be copied to Lightsail, and the
current S3 adapter requires credentials. Do not substitute long-lived operator keys.
[AWS Lightsail pricing](https://aws.amazon.com/lightsail/pricing/) and
[IAM support](https://docs.aws.amazon.com/lightsail/latest/userguide/security_iam_service-with-iam.html).

One included LangSmith deployment may host the selected application's child graphs
only after account access verifies plan eligibility, the unused slot, region and
persistence isolation. Public Plus pricing lists $39/seat/month and one free Small
Serverless deployment. Small Serverless has 1 vCPU/2 GiB, a shared database and
scale-to-zero behavior. Hosting Mission Control's continuously polling Temporal
worker there is unqualified; custom lifespan support does not establish supervision
or availability. No entitlement has been confirmed for this account.
[Pricing](https://www.langchain.com/pricing),
[deployment behavior](https://docs.langchain.com/langsmith/cloud-platform-features),
[custom lifespan](https://docs.langchain.com/langsmith/custom-lifespan).

For this starter, approve the application and exact production PostgreSQL/checkpointer,
Temporal namespace and artifact-store targets; persistent secret references and
production worker startup; model/tool/sandbox limits; and any migration separately.
Worker startup can promote worker versions and update retention schedules. A new
host additionally needs region, monthly cap, runtime identity, administration,
backup and resource-creation approval. Hostname/TLS/public ingress requires its own
concrete approval. These approvals and LangSmith account facts remain missing.
Managed-service subscriptions and action/history/runtime/trace/model/sandbox meters
remain separate from every fixed compute figure above.

Existing Supabase applications remain the mission ledger; no new AWS RDS or
self-hosted Temporal is proposed. Existing subscriptions are not assumed free or
sufficient for incremental load. Agent Server native persistence stays separately
qualified; do not place it in the business database or combine both app authorities
to exploit one included deployment slot.

Temporal's current public pay-as-you-go page states no monthly base fee:
$50/million actions, $0.042/GB-hour active history, $0.00105/GB-hour retained history
and developer support at 10% of usage. A hypothetical 100,000 actions, 0.1 GB
average active history and 1 GB retained for 730 hours is **$9.71575/month including
10% support**. It is a workload example, not measured usage or this account's
contract. [Temporal pricing](https://temporal.io/pricing).

Fresh LangSmith public rates use **LSU = $1**: runtime $0.0675/vCPU-hour and
$0.009/GiB-hour; database $0.177/vCPU-hour and $0.025/GiB-hour. One continuously
provisioned 1-vCPU/2-GiB runtime is $62.415/month before database/storage or
allowances. Plus publicly lists $39/seat and one included Small Serverless
deployment. Sandbox rates are $0.0576/vCPU-hour, $0.01845/GiB-hour and
$0.000123/GiB-hour storage, with an advertised 8 LSU monthly sandbox allowance.
These current LSU terms replace earlier LCU notation in the research handoff.
No account credit, free slot or shared database isolation was verified.
[LangSmith pricing](https://www.langchain.com/pricing).

Consequently a planning example is **$166–185 AWS + about $9.72 Temporal = $176–195**,
**plus** applicable LangSmith seat/runtime/database/trace/sandbox charges, existing
Supabase charges/overages, model/tool charges and tax. If an existing eligible
LangSmith subscription and unused slot cover one app's async runtime, that one
runtime's incremental charge could be zero; do not apply that assumption to both
apps. For the second app, native isolation and managed cost remain quote/account
gates. An all-in production approval cannot be inferred from the AWS-only envelope.

No usable LangSmith account connector was exposed. Two attempts to inspect existing
browser tabs failed immediately because the browser tool's trusted Node process
exited/reset. No login, cookie extraction, new credential or account grant was
attempted. Needed account evidence: organization plan/region, current deployment
list and resource class, included-slot consumption, actual usage billing agreement,
and app-isolated deployment/native persistence eligibility.

## Migration, release and exact approvals still required

1. **Budget:** numeric AWS monthly limit, separate managed/model/tool/sandbox ceiling
   and finite live-proof allocation. AWS budget alarms are notifications, not a
   hard spending cutoff; do not claim the estimate enforces a cap.
2. **Security/resources:** explicit approval of the named new resources, public
   HTTPS exposure, broad provider HTTPS/gRPC egress, six roles, exact secret
   recipients/storage, object-store choice and domain/TLS changes.
3. **Missing selections:** hostname/DNS owner, exact AZs/CIDR collision check,
   Supabase destination routes, existing Temporal namespace(s), actual secret ARNs,
   managed Agent Server app isolation/entitlement and source/image release digest.
4. **Schema:** no live schema migration is in this proposal. Read-only `mission-db`
   inspection must identify exact installed release versus runtime requirements.
   Any required migration needs a separate generated plan, target identities,
   before fingerprints, backup/recovery proof and explicit approval; startup never
   fixes this automatically. Current local proof is not a live schema attestation.
   The prepared runtime requires common component **1.3.0**, including additive
   migration `0034_provider_frame_lifecycle_body.sql`, and catalog seed
   `mc.catalog.workflow-parity@1.0.2` (workflow-family asset version 3). Existing
   app release locks were preserved and do not authorize those installation changes.
5. **Release:** approve image publication and the reviewed infrastructure changes
   only after the above inputs exist. The locally built image is not yet a complete
   operator image. Configure auth, pins, admitted providers and durable storage;
   validate actual startup and run a bounded representative/cancel/restart proof.

Nothing reuses or modifies `hu-cluster-dev`, scraper task definitions/ECR, existing
unrelated secrets, either existing VPC, or domain application resources. No paid
resource, persistent grant, hosted endpoint or migration was created during this
planning work.
