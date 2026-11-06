---
type: Roadmap
title: "Cloud coding environments and the first Deep Agents deployment"
description: "Owner direction after the Qualia fixtures: local W0/W1 and Mission Control refinement may precede cloud coding environments, deployment architecture and remote readiness."
date: 2026-10-31
status: active
tags: [mission-control, deep-agents, knowledge-services, deployment, cloud, roadmap]
---

# Cloud coding environments and the first Deep Agents deployment

**Sequencing clarification, 2026-10-31:** W0/W1 work and general Mission Control refinement may
run locally before cloud coding-environment setup. The owner will give explicit instructions
next session; the sequence below is provisional.

The broader objective is to prepare cloud development environments for Cursor, Claude Code and Codex,
then bring Mission Control with Deep Agents to its first major local-and-cloud deployment. The
architecture must be understandable before implementation: where each service runs, who owns its
state, how sandboxes are selected, and what survives a change of execution host.

This is the owner's direction recorded on **2026-10-31**, paired with [NEXT-SESSION](NEXT-SESSION.md).
That board remains the checkpoint for implementation and qualification; this companion records
the destination, order of work, decisions to resolve and evidence needed. Infrastructure choices
below are candidates, not deployed services or accepted replacement ADRs.

## 1. Owner intent and order of work

The Qualia work deliberately forced the system through real research mechanics. Its purpose was
workflow and configuration proof. Optimizing the Biotech entity model, biological research process,
capability catalog and source collection is a later, dedicated effort.

The broader sequence, subject to the local-first option above, is:

| Phase | Work | Result needed before moving on |
| --- | --- | --- |
| 1. Cloud coding environments | Prepare MC and KS development environments for Cursor, Claude Code and Codex; evaluate CloudRoom as an optional host and session-transfer mechanism. | Reproducible environments, working repository/service access and bounded proofs for each coding harness. |
| 2. Deployment architecture | Specify Deep Agents, Agent Server, Temporal workers, MC, KS, persistence, networking and sandbox/compute boundaries. Educate the owner through concrete deployment examples. | A service-placement map, state-ownership map, candidate infrastructure bill of materials and explicit decisions. |
| 3. W0/W1 checkpoint | Continue the existing qualification work using the coordinated source and current proof packet. | W1 disposition recorded on the live board; existing release obligations remain explicit. |
| 4. Deployment-readiness coding sprint | Likely another sprint after W0/W1: implement and prove the chosen local/remote execution configuration, state transfer, operating controls and deployment packaging. | Qualified remote execution and recovery under the same Mission Control workflow semantics. |
| 5. First major deployment | Deploy Mission Control and Deep Agents, with the required KS and Agent Server services. Preserve both local and cloud operation. | Actual deployment, restore, lifecycle and workflow evidence; an operational runbook and cost controls. |

Architecture preparation precedes deployment; remote-execution implementation/readiness follows the W0/W1
checkpoint. **W0 is already recorded released; W1 remains open.** The owner's shorthand “W0/W1”
does not restart W0. It also does not waive the applicable W2–W5/release checks in the existing
[proof packet](PROOFS.md); the readiness sprint must map those checks to the first deployment.
This document does not start provisioning or inherit the completed fixture's USD100 spending authority.

## 2. Starting checkpoint

The bounded Qualia fixtures now prove real Deep Agents StageGraph execution, parallel research
branches and a coverage join, exact capabilities and dependent outputs, queue and interrupt/inject
controls, a recorded-point Tavily fork, KS claim verification/repair and acknowledged Biotech Aura
writes. MC commit `0eccfa2d` contains the runtime and fixture changes. The private evidence index is
`.scratch/qualia-stagegraph-2026-10-30/READ-FIRST.md`; the [live board](NEXT-SESSION.md) records the
public summary. Companion KS/BKS fixture changes and their source-custody archives remain local.

That proof does not establish cloud deployment or cross-machine session movement. In particular,
the fixture's standalone authenticated KS roles do not qualify production per-invocation Biotech
authority mapping. The next environment work must consume the actual service contracts rather than
turn the fixture host into a production architecture.

There is already useful deployment preparation to extend:

- MC's [cloud runtime package](../../../../deployments/cloud_runtime/README.md) contains a container
  build and an inert ECS plan renderer. Its dated status is prepared, not deployed. The
  [deployment options report](../../../DEPLOYMENT_OPTIONS_2026-10-12.md) compares a first single-host
  AWS installation, ECS/Fargate and Agent Server hosting; its prices and account assumptions need refreshing.
- KS's accepted [runtime baseline](../../../../../knowledge-services/docs/architecture/0001-runtime-and-deployment.md)
  separates API/MCP transports from durable workers and conversion services. Its
  [AWS template](../../../../../knowledge-services/infra/aws/README.md) prepares ECS/Fargate worker
  and Docling services. Template existence is not a live installation.
- The [application ports map](APPLICATION-PORTS.md) distinguishes MC lifecycle state, KS operational
  reports, native domain knowledge and provider persistence. Use it with the
  [data-plane registry](../../../../../../docs/navigation/DATA-PLANES-AND-CREDENTIALS.md), not a guessed
  interpretation of an environment variable.

Older KS cleanup handoffs and deployment notes contain retired paths and historical harness plans.
Use the current [KS guide](../../../../../knowledge-services/AGENTS.md) and published contracts;
do not recreate `research_ingestion_systems_agent` or `ai-engineer-mission-control`.

## 3. Cloud environments for the coding agents

First establish a development environment specification shared by MC and KS, with per-harness
configuration for Cursor, Claude Code and Codex. The environment should identify repository revisions,
dependency locks, OS/architecture, Python/Node/toolchain versions, build/test commands, reusable
images and required local services. Preserve the independent repositories and their ownership.

Each harness needs its own tested setup for skills, instructions, MCP endpoints, plugins and custom
tools. A shared capability catalog can drive configuration, but identical names do not establish
identical behavior. Record which features are available, unsupported or require an explicit adaptation.
The [existing capability projection and lane boundaries](../../../knowledge/deep-agents-lane.md)
are the starting point, not a reason to maintain three divergent copies of business rules.

Keep development, qualification and production targets explicit. Coding agents need scoped access
to the selected MC/KS services and disposable test resources, with secrets supplied through the
host's credential mechanism. Do not copy a developer home directory, database administrator access
or local `.env` files into a general-purpose cloud image. Cross-repository KS use follows
[KnowledgeClient HTTP and the published MCP/CLI contracts](../../../../../knowledge-services/knowledge/execution-profiles-and-transports.md).

The first environment proof is small: open both repositories, build and run the relevant deterministic
checks, call the intended authenticated service, run one bounded task, retain its artifacts, disconnect
the client, reconnect, and recover the exact session. Then test local→cloud and cloud→local with dirty
workspace state, queued messages and an interrupted tool. These are development-environment proofs;
production workflow qualification remains a separate result.

### CloudRoom evaluation

The candidate is [davidondrej/cloudroom](https://github.com/davidondrej/cloudroom), an Apache-2.0
project. Source review for this document is pinned to
[`a1fea9f0fe87f132433903d2b6ef8cedd97d9280`](https://github.com/davidondrej/cloudroom/commit/a1fea9f0fe87f132433903d2b6ef8cedd97d9280)
on 2026-10-31. Its README describes a desktop app, a Rust cloud core, per-cloud-thread sandboxes,
self-hosting and “Teleport” between local and cloud. It lists Windows 11 as beta and Linux x64 as
alpha, making Windows behavior a specific proof requirement for this workspace.
[README](https://github.com/davidondrej/cloudroom/blob/a1fea9f0fe87f132433903d2b6ef8cedd97d9280/README.md).

Its harness documentation supports the architectural intuition while revealing limits. Claude Code
uses the native CLI's stream-JSON protocol; its rewind forks conversation history without restoring
files. Cursor is described as an implementation preview: resumable print-mode execution and native
history snapshots, but no advertised manual compaction, rewind or independent subagent controls.
Cursor's synchronization does not include MCP configuration, plugins or credentials. These need
explicit host setup rather than an assumed automatic transfer.
[Harness adapters](https://github.com/davidondrej/cloudroom/blob/a1fea9f0fe87f132433903d2b6ef8cedd97d9280/core/docs/harnesses.md).

CloudRoom records queued requests and native history, distinguishes accepted requests from completed
work, and documents uncertain dispatched work after a crash rather than blindly resending it. Its
self-hosted core can keep history locally; managed history storage does not itself preserve all
workspace files. This is promising infrastructure to evaluate, not proof of Mission Control's
checkpoint, effect or output-contract guarantees.
[Lifecycle](https://github.com/davidondrej/cloudroom/blob/a1fea9f0fe87f132433903d2b6ef8cedd97d9280/core/docs/session-lifecycle.md),
[self-hosted setup](https://github.com/davidondrej/cloudroom/blob/a1fea9f0fe87f132433903d2b6ef8cedd97d9280/core/docs/setup.md).

Evaluate CloudRoom first as a coding-agent environment. A later runtime integration would need a
separate adapter and conformance proof. CloudRoom's native session queue cannot become a second
Mission Control scheduler or a route around admitted effects. If a required capability is unavailable,
use a documented alternative cloud workspace or narrow that harness's supported profile explicitly.

## 4. Deployment architecture to resolve

### Service roles and state ownership

| Component | Responsibility and deployment question |
| --- | --- |
| MC API and MCP surface | Authenticate and admit work; expose inspection, durable controls and transcripts. Specify local and remote endpoints against explicit installation/application/tenant identities. |
| Temporal Service | Durable scheduling, workflow history, signals and timers. Decide managed versus self-hosted service; preserve Temporal as the sole mission scheduler. |
| MC Temporal workers | Execute workflow/activity code, reducers and provider adapters. Package and route workers by application, lane and build compatibility; drain and recover them during updates. |
| Deep Agents runtime | Bounded cognition, exact component materialization and native recovery. Select its execution host through the existing resolution/binding architecture. |
| Agent Server | App-bound hosted asynchronous subordinate graphs under the accepted contract. Determine endpoint, authentication, graph revisions, persistence and hosting entitlement. Remote parent execution is a further design decision. |
| KS API/MCP and workers | Own verification, immutable report/capture custody, policy admission and durable knowledge operations. Keep domain ingestion behind the owning application's adapter. |
| Parser and Docling services | Distinct conversion/execution boundaries with their own images, resource limits and isolation; deploy only the capabilities the selected experiments need. |
| Databases and object storage | Preserve MC authority, KS operational records, native domain data, standalone saver state, Agent Server persistence and Temporal history as distinct owned stores. Captured bodies and snapshots must outlive a container. |
| Sandbox or compute provider | Run agent shell/tools and maintain workspace state with explicit CPU, memory, disk, network, lifetime and snapshot behavior. It is not the mission ledger. |

These boundaries follow [ADR 0006](../../../adr/0006-agent-server-required-execution-host-not-scheduler.md),
[ADR 0017](../../../adr/0017-agent-server-runtime-persistence-separate-database.md),
[the saver topology note](../providers/deep_agents/TOPOLOGY-NOTE.md) and the application ports map.
The standalone LangGraph saver and Agent Server's durable edition must not be conflated merely
because both store checkpoints. A saver-location change is a recovery/migration question, not an
ordinary endpoint substitution.

### Local versus remote Deep Agents

There are two materially different remote arrangements to evaluate:

1. **A cloud MC worker runs the existing Deep Agents adapter in its own process.** Moving the worker
   changes infrastructure placement; it does not by itself require a remote parent-agent protocol.
   This is the closest first-deployment candidate to the existing worker architecture.
2. **An MC worker dispatches parent cognition to a separately hosted agent runtime.** This needs a
   remote host integration that preserves native identity, streaming, cancellation, observation,
   recovery, exact capabilities and governed tool/effect access. Existing Agent Server support for
   asynchronous children is not evidence that this parent path is complete.

The codebase must ultimately expose an explicit local/remote host choice. Its configuration shape
is still to be designed; this document adds no new manifest fields. Extend the
[accepted resolution seam](../../archive/provider-consolidation-2026-10/specs/SELECTION-AND-ROUTING-DESIGN.md) and existing Deep Agents module, keeping
provider details inside deep adapters. Common workflow, output and control contracts remain
provider-neutral. Reuse the existing harness protocol and native lifecycle indexing rather than
inventing a second generic agent lifecycle abstraction.

Host choice must be admitted and pinned before execution. Current
[placement admission](../../../knowledge/placement-admission.md) selects among declared qualified
configurations; it is not transparent relocation of an already running Deep Agents session. A
network failure must not silently start a new paid agent elsewhere. Local and cloud MC processes
also need explicit authority and worker ownership so reconnecting a laptop cannot create two writers.

### AWS and managed-service candidates

This is the initial bill of materials to compare, not an infrastructure selection or current quote:

| Need | Candidate services and decision |
| --- | --- |
| First MC API/worker deployment | A supervised EC2/Lightsail host versus ECS/Fargate services. Reuse the existing cloud-runtime plan, but decide host operations, isolation, drain/rollout and scaling needs first. |
| Image distribution | ECR with immutable image digests, build provenance and matching capability/configuration assets. |
| Durable bytes and backups | S3 for MC payload/snapshot custody where that adapter is selected; retain explicit KS custody backends. Define restore, retention and access separately from database backups. |
| Runtime secrets and identity | IAM task/instance roles and Secrets Manager, with application-scoped credentials. Secret references and native account logins are not portable session content. |
| Networking and ingress | VPC/subnets/security groups; authenticated TLS ingress, with ALB/ACM/Route 53 where appropriate; explicit egress or private endpoints. Include NAT, load balancer and cross-service transfer in the cost model. |
| Logs and operating evidence | CloudWatch for service logs/alarms, correlated with MC transcript/run IDs and optional LangSmith traces. Trace availability is not workflow acceptance. |
| Agent Server hosting | Compare managed LangSmith Deployment with licensed standalone/BYOC options; if self-hosted, budget its own PostgreSQL and Redis. Validate account entitlement and pinned versions before choosing. |
| Tool/sandbox execution | Managed sandbox provider or dedicated EC2-backed isolation where host control is required. Do not assume the worker container can provision nested Docker sandboxes. |

Temporal's service and the workers are different deployments: worker code runs on the infrastructure
chosen by the operator, including when the service is Temporal Cloud. Worker-version compatibility
belongs in the rollout design. [Temporal worker deployments](https://docs.temporal.io/production-deployment/worker-deployments).
LangSmith's deployment options distinguish hosted control/data planes from standalone servers and
their database/license requirements. [LangSmith Deployment](https://docs.langchain.com/langsmith/deployment).
Fargate does not provide privileged containers or underlying host access; Docker-in-Docker is
therefore not an assumed sandbox strategy. [AWS Fargate restrictions](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-security-considerations.html).

Reconcile this with KS's accepted Vercel API/MCP plus AWS worker/conversion baseline before moving
those transports. Do not silently turn an MC hosting choice into a KS architecture change. Choose
region, monthly infrastructure ceiling, model/tool spend controls and backup objectives from a fresh
inventory; the earlier deployment report's illustrative prices are not the new budget.

## 5. What bidirectional session continuity must preserve

“Same chat on another machine” is only one layer of the requirement. The architecture needs a
portable, verifiable description of each layer, with explicit unsupported cases:

| State | Required preservation or reconciliation |
| --- | --- |
| Mission authority | Run/unit identity, application/tenant, operation attempt/generation, stage dependencies and current control receipts. |
| Native cognition | Exact checkpoint/parent lineage, native session identity, model/harness pins and declared restore level. Do not relabel reconstructed context as native continuation. |
| Workspace and compute | Repository revision, dirty/untracked task files, artifact hashes, sandbox image/snapshot, mounts and resource/network policy. A conversation checkpoint is not a filesystem snapshot. |
| Context and outputs | Selected immutable input revisions, sealed transfer plans, readable custody, required output obligations and fulfillment receipts. |
| Capabilities | Exact prompts, MCP servers, skills, plugins, tools and hooks; recheck the receiving host's ability to materialize and execute them. |
| Pending work and effects | Queued messages, interrupts, child sessions and external-effect reconciliation. Completed or uncertain effects must not be blindly replayed after a move. |
| Credentials | Reauthorize the receiving host with scoped credentials; do not serialize secrets into checkpoints or transfer bundles. |

Start with moves at settled, recorded boundaries. A running transfer needs a proven sequence:
quiesce or interrupt the source, fence its ability to perform new work, capture and verify state,
restore on the target, record ownership/lineage and resume only after receipt reconciliation.
Interrupted transfers must remain recoverable without two active owners. Live process-memory
migration is not implied by this target.

Prove local→cloud→local in a matrix covering StageGraph, GoalDirected, admitted nested/linked
workflows and subordinate sessions. For each supported profile, exercise fork-at-point with changed
instructions/capabilities, a queued message during work, interrupt/inject, worker and client loss,
unreachable custody, an incompatible receiving host, duplicate commands and an uncertain external
effect. Swarm/EO or other unqualified profiles keep their existing status; listing them does not
declare them implemented. Publish exact refusal/degradation behavior alongside successful cases.

## 6. Experiments and owner learning

The environment should make controlled experiments easy. Freeze a baseline and change one major
dimension at a time: model, harness/provider, prompt, MCP server, skill, plugin, custom tool, sandbox
image or snapshot. Record the resolved configuration digest, source/input revisions, environment,
lineage, cost, latency, tool/effect receipts and evaluation result. A snapshot must reproduce the
declared starting state, not just reinstall dependencies. Keep infrastructure success separate from
scientific quality and from independent workflow acceptance.

Use the deployment design as a practical learning sequence for the owner:

1. Trace one mission from API admission through Temporal scheduling, a worker activity, Deep Agents,
   KS and an applied native receipt. Identify where each durable state lives.
2. Place the same processes on a single cloud host, then compare an ECS layout. Explain what the
   cloud provider operates and what remains our responsibility.
3. Demonstrate a tool sandbox and its snapshot separately from an agent checkpoint. Disconnect the
   client, stop the worker and restore the workspace as three different events.
4. Walk through TLS, private service access, role-scoped secrets, logs, backups and a restore drill.
5. Compare fixed idle costs with per-run model/tool/compute costs, then rehearse a deployment update
   and rollback while an existing workflow remains recoverable.

## 7. Decisions and next deliverables

| Decision | Method and concrete next deliverable |
| --- | --- |
| CloudRoom or another coding environment | **Research and prototype.** Pin core/desktop/harness versions; test all three coding agents, especially Windows and unsupported feature boundaries. Produce a capability and continuity matrix. |
| Cloud worker versus remotely hosted parent cognition | **Architecture and prototype.** Extend the existing Deep Agents/resolution seams on paper, then prove one bounded remote invocation and recovery before committing to the transport. |
| Agent Server hosting and persistence | **Research and account validation.** Confirm license/plan, separate stores, served graph identity, supported revisions and async-child recovery. |
| AWS service layout and sandbox provider | **Architecture and measured prototype.** Compare the first-host and ECS candidates, including network and storage costs, actual sandbox restrictions and worker resource measurements. |
| Transfer/ownership protocol | **Prototype and conformance.** Define the state bundle and fencing/reconciliation rules; prove both directions with fork, intervention and output obligations. |
| First-deployment acceptance | **Qualification planning.** Reconcile W1 and applicable remaining gates, package coordinated MC/KS builds, define rollout/rollback, restore proof and ongoing operating checks. |

The next working packet should contain the environment manifests, the service/state diagram,
the decision record, the continuity proof matrix, the owner learning walkthrough and the proposed
readiness sprint. Create implementation issues from that agreed scope before coding. Deployment
follows readiness evidence; this roadmap does not substitute for it.

## Provenance

Owner instruction in this chat, 2026-10-31: cloud environments first (possibly CloudRoom), then
architecture for Deep Agents/Agent Server/Temporal and MC deployment; W0/W1 before the likely
remote-readiness coding sprint; then the first major local-and-cloud deployment. Biotech source and
biological-capability optimization is deferred. Existing contracts, code and qualification status
remain authoritative; candidate services and continuity mechanisms here are planning inputs.
