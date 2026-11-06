# Read-only infrastructure observations, 2026-10-11

Default AWS CLI identity was verified as account `298199649527`, IAM user
`overtonadmin`; configured region is `us-east-2`. No credentials or secret values
were displayed, read from Secrets Manager, copied into files, or changed.
Initial sandbox network requests could not reach AWS; the authorized read-only
commands succeeded through the approved escalated network route.

| Scope | Observed result |
| --- | --- |
| us-east-2 ECS | One existing unrelated `hu-cluster-dev`, zero services/running/pending tasks, no capacity providers listed |
| us-east-2 ECS definitions | Existing `hu-scraper-task` revisions and `hu-scraper-task-dev`; definition bodies and embedded environment values were not read |
| us-east-2 EC2/RDS/ALB/NAT | No EC2 instances, RDS instances, v2 load balancers or NAT gateways returned |
| us-east-2 ECR | Existing CDK asset repository and `human-upgrade-scraper`; no Mission Control repository verified |
| us-east-2 VPC | Two VPCs, one default and one nondefault; routes/security policies and safe reuse were not qualified |
| us-east-2 Secrets Manager | Names only: two unrelated application secrets; no Mission Control references verified |
| us-east-1 and us-west-2 | No ECS clusters, EC2 instances or RDS instances returned |
| Other AWS regions | Enabled-region list read; resources not inventoried, so absence is not asserted |
| us-east-2 ACM / global Route53 | No certificates / no hosted zones returned by read-only list calls |
| LangSmith | No account-specific billing/deployment inventory available through the exposed connector tools; public entitlement is not account evidence |
| Temporal Cloud/Supabase | Configuration/source inspected, no live namespace or database writes/probes performed by this workstream |

AWS actions: `sts get-caller-identity`, `configure get region`,
`ec2 describe-regions`, `ec2 describe-instances`, `ec2 describe-vpcs`,
`ec2 describe-nat-gateways`, `ecs list-clusters`, `ecs describe-clusters`,
`ecs list-services`, `ecs list-task-definitions`, `rds describe-db-instances`,
`elbv2 describe-load-balancers`, `ecr describe-repositories`, and
`secretsmanager list-secrets` with narrow queries. No Cost Explorer/billing API
calls were made because some account configurations charge per request.

Follow-up read-only actions: `acm list-certificates`, `route53 list-hosted-zones`,
and VPC CIDR metadata. Existing VPCs use `172.31.0.0/16` and `10.0.0.0/16`;
neither was selected for reuse. Public AWS regional price-list JSON and official
vendor pricing pages were read without authenticated billing API calls. Two
attempts at existing-browser inventory failed with a trusted Node process reset;
no LangSmith account screen or entitlement was observed.

Inference: there is no verified running Mission Control compute or freely reusable
capacity in the inspected regions. An ECS cluster object is not allocated compute.
Unrelated scraper/research resources remain unchanged and unselected. This is a
scope-limited inventory, not an account-wide assurance of no infrastructure.

## Local validation

- Passed: 14 focused offline tests, including generated inputs validated against
  the installed botocore ECS `RegisterTaskDefinition` and `CreateService` shapes.
- Passed: Ruff lint/format and mypy for `plan.py`.
- Passed: unresolved example returns blocked exit 2 with no input-value disclosure.
- Environment issue: default `uv` cache and pytest temporary paths were unwritable
  in the sandbox. Used the existing `.venv` interpreter directly and an explicit
  unique directory under the authorized user Temp root; no dependency sync occurred.
- Passed after explicit local-build authorization: official digest-pinned
  Python 3.12.15/uv 0.12.23 Linux/amd64 image build, then cached rebuild with pinned
  Dockerfile defaults and no build warnings. Nonroot API and worker imports passed
  with `--network none --read-only`, no mounts or credentials. The core package
  imported without the optional Biotech adapter distribution. See BUILD_EVIDENCE.json.
- Blocked/unrun: live configuration/persistence/managed endpoint/startup verification;
  provider fixture and restart/cancel proof; deployment. No runtime endpoint exists
  from this workstream. Full repository verification is owned by the integrator.
