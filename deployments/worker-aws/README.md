# AI Engineer worker deployment

The supporting infrastructure and restricted credentials are provisioned and
verified; the worker service is not deployed yet. The selected account is
`298199649527`, region `us-east-1`, namespace `mission-control-dev.ih0e7`.
The owner authorized creation of the standard default VPC on 2026-10-14.
`vpc-04db3b23ff1cee487` is available with six default public subnets, an attached
internet gateway and an active default route. The earlier inventory found no
`mission-control` cluster or `mission-control-worker` ECR repository. Network
creation is complete. Under the owner's Run 2 infrastructure authority, stack
`mission-control-ai-engineer-run2` created the exact supporting resource set.
Private receipts and original failures remain under the sprint's ignored run directory;
the current milestone is recorded in the Run 2 report.

`infrastructure.py --out <ignored-path>` renders the fixed ECR repository, private
S3 payload bucket, roles, local S3 user, empty secret resources, egress-only group,
logs, cluster and $40 budget alerts. It requires the selected VPC and budget email.
It creates no access key or secret value. S3 and secrets have retain policies.
The budget is an alert, not a spending stop. ECS Exec remains disabled until its
separate approval; no SSM session policy is included in the default proposal.

The owner can supply secret values with `put-secrets.ps1 -OwnerExecution -Names ...`
from the process environment. Values are neither printed nor put in command-line
arguments. This script does not parse or echo `.env`. Use the dedicated runtime,
family-writer and checkpoint logins through the session pooler with TLS. The current
three logins passed restricted-role and installation readiness checks, including
LISTEN/NOTIFY on the session pooler; all seven expected secrets have verified custody.
Do not rerun provisioning as password rotation. Bundle the independently verified
public Supabase CA at `/etc/mission-control/supabase-ca.pem`; the worker DSNs use
`sslmode=verify-full` and that `sslrootcert` path. The retained CA SHA256 is
`700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7`.

Build the source-only `deployments/cloud_runtime/Dockerfile` first, then this
directory's operator Dockerfile using `MISSION_CONTROL_BASE_IMAGE` set to its
reviewed immutable image. Supply public operator assets under ignored `config/`:
deployment registry and public JWKS, `target.toml`, `release.lock.json`, exact
capability pins/bundles, trusted manifest files and launch bindings. Resolve and
verify their real digests with preflight. Never copy credentials or `.env` there.
The config must enable hosted lane routes only on `mc-ai-engineer-lane-hosted`.

Render `plan.py --image <ECR-digest> --binding-digest <digest> --build-id <version-sha>
--secret-arns <JSON> --ingress-origin <HTTPS-origin> --manifests <JSON> --out <task.json>`.
The manifests JSON maps reviewed manifest refs to `/etc/mission-control/manifests/<name>.yaml`
in the immutable image. The task uses a role for S3, never a local
AWS profile, and starts the base worker with the ingress drainer. Trusted remote
manifest paths and optional quarantine/custody storage must be supplied through
reviewed settings; absent registrations reject requests rather than bypass admission.
`deploy.ps1 -TaskDefinition <task.json>` validates the entire task offline.
`-Apply` is a separate mutation gate and requires current resource/spending authority.
For the first service, `-CreateService -SecurityGroupId <reviewed-egress-group>` also
requires an absent service in the existing cluster, verifies the selected VPC's six
public subnets and the exact zero-inbound group, then uses `service.py`'s fixed
one-task contract. Offline rendering creates nothing. An uncertain create must be
inspected before retrying. Infrastructure provisioning and owner secret writes
remain separate reviewed steps. Deployments use min 0/max 100 percent.
Updates revalidate the existing topology and network before registering a revision.
They drain the old service to zero, reconcile task identities again after the drain,
and await terminal task states before starting the replacement. A failed drain leaves
the new revision unstarted and requires inspection; STOPPING is not treated as stopped.
Availability Zone rebalancing is explicitly disabled to preserve the single-worker
deployment policy. The circuit breaker cannot roll an initial deployment back to
a completed predecessor that does not exist; inspect a failed first deployment and
stop its desired count rather than treating the rollback flag as recovery evidence.
The request shape follows the [AWS create-service contract](https://docs.aws.amazon.com/cli/latest/reference/ecs/create-service.html)
and [circuit-breaker behavior](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html).

Do not run a second base worker for this application/namespace. Switch WSL to lane
role and the matching build before local lanes participate. Automatic promotion is
disabled: explicitly inspect and promote the reviewed Worker Deployment Version.

Live readiness, immutable asset verification inside the built image, secret-sentinel
inspection, pooler roles/LISTEN, S3 round trip, laptop-off/restart behavior and 24-hour
CPU/memory/spend evidence are required acceptance checks and remain unrun. The
existing account budget reported $0.619 actual spend at inventory time; this is not
remaining authorization or a model/provider spend report. Stop the exact service
with desired count zero to stop compute; storage, retained secrets and provider
sessions can continue to incur charges and must be reconciled separately.
