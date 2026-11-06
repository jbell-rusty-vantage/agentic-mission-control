---
type: Glossary
title: Mission Control
description: "Mission Control is the shared control service that turns a human's research, ingestion, content or coding outcome into an admitted, durably scheduled mission for one of two applications, and computes whether the result…"
tags: [mission-control, language]
---
# Mission Control

Mission Control is the shared control service that turns a human's research, ingestion, content or coding outcome into an admitted, durably scheduled mission for one of two applications, and computes whether the result is accepted. This glossary is the language used in specs, code, issues and conversation. Seeded 2026-10-07 from the accepted specification and the code; sharpened in interview.

## Language

### Applications and identity

**Application**:
A registered product served by Mission Control through its own Application Binding.
_Avoid_: app, product, tenant

**Installation**:
The identity of one common schema release living inside one application's database.

**Application Binding**:
The immutable, operator-managed registry entry that ties an application to its installation, database, storage, auth issuers, Temporal queues and runtime persistence.
_Avoid_: deployment config, registry row

**Application Profile**:
What may differ per application, declared as data in `deployments/<app>/application.toml` (ADR-0063): the knowledge binding, apply contract and payload layout, storage class, write atomicity, readback, Data Class ceiling, output-contract minimums and transfer defaults. It also declares `hosted_session_retention_days`, which nothing reads yet: the hosted session retention in force is the 7-day default (`DEFAULT_SESSION_RETENTION_POLICY`), because the hosted lane composition passes no policy. The installation's application id selects it; the Application Registry validates it; the kernel names no application.
_Avoid_: application config, app settings

**Tenant**:
A grant boundary inside an application.

**Actor**:
The authenticated human or service principal acting inside an application and tenant.

**Scope**:
The installation, application, tenant and actor that every request and record carries.
_Avoid_: context (overloaded), request context

**Grant**:
Authority an actor holds in a scope. Effective authority is always the intersection of grants, application policy, mission action space and node scope; no tool, skill text or model output widens it.
_Avoid_: permission, role

### Missions and programs

**Mission**:
A durable statement of goals, success criteria and a recursive program, with exactly one scheduling head.

**Mission Definition**:
The typed document a mission is authored as: goals, objectives, criteria, inputs, program, policies, budget and completion contract.
_Avoid_: mission spec, mission contract

**Mission Manifest**:
The YAML authoring surface (`mission.yml`) a human or coordinator writes: goals, criteria, a mission-level environment with per-node overlays, and the program. It compiles into a Mission Definition; it is never the committed revision.
_Avoid_: mission YAML, mission contract, mission config

**Environment**:
The bundle a manifest gives a node to run in: lane, model profile, sandbox profile, workspace context and skills, capabilities, budget and governors. Nodes inherit the mission-level environment and may overlay it.
_Avoid_: config, settings, runtime

**Goal**:
An outcome the mission exists to reach, weighted by importance.

**Objective**:
A step toward a goal, optionally nested under another objective.

**Success Criterion**:
A checkable condition on a goal, naming the evidence it requires and how it is accepted.

**Program**:
The recursive tree of program nodes that realizes a mission.

**Program Node**:
One unit of the program with a single behavior, its own inputs, outputs, policies, budget and completion contract.

**Behavior**:
The kind of a program node: a workflow system, an executor, a durable control or a child mission invocation.

**Compiled Program**:
The deterministic compiler output for a definition: canonical digests, capability attachment plan, expansion limits and validation report.
_Avoid_: ERC, effective run configuration (the code's name for the same thing)

**Revision**:
An immutable compiled version of a mission's definition.

**Revision Proposal**:
A submitted candidate revision awaiting validation, review and activation.

**Scheduling Head**:
The single active revision a mission schedules from.

**Transition Impact**:
The recorded effect of activating a successor revision on each in-flight activation.

**Carry-Forward**:
Reuse of completed work across revisions, decided by digest equality, never by assumption.

**Run**:
One durable execution of a mission from a starting revision with immutable inputs and bindings.
_Avoid_: job, execution, workflow instance

**Activation**:
One scheduled instance of a program node inside a run.

**Attempt**:
One try at an activation, with its own execution outcome and failure class.

**Agent Session**:
A runtime-owned conversation identity mapped to one attempt. It carries no acceptance authority.

**Session Turn**:
One exchange inside an agent session.

**Lifecycle, Phase, Terminal Outcome**:
The three separate fields that describe any record's state: where it is in its life, what it is doing now, and how it ended. A terminal outcome is absent until completion.

**Child Mission**:
An independently admitted mission started by another mission through a child mission invocation.

**Mission Relationship**:
A recorded link between missions: parent and child, chained, linked or superseded.

**Portal**:
The admitted way one mission invokes another.

**Spawn Grant**:
The bounded authority to create child missions or subordinates.

**Mission Chain**:
An ordered set of missions authored together and linked by `supplies` and `depends_on` relationships, each with its own run, budget and acceptance.
_Avoid_: linked workflows, multi-workflow, pipeline of missions

**Chain Link**:
One `supplies` or `depends_on` relationship inside a mission chain, with its typed output binding and the acceptance condition that releases the consumer.

### Workflow systems

**Workflow System**:
One of the program behaviors Stage Graph, Goal Loop or Evaluator Optimizer. Parallel Swarm is a
Stage Graph composition/profile (OC-D204); its behavioral proof remains required.
_Avoid_: workflow type, family (the code's word)

**Stage Graph**:
Dependency-driven release of typed stages through gates.
_Avoid_: DAG, pipeline, StageGraph (in prose)

**Stage**:
A node of a stage graph that releases when its dependencies, typed inputs and gates are satisfied.

**Goal Loop**:
The workflow system that iterates observe, propose, authorize, act, assess, decide until a goal is met or a governor stops it.
_Avoid_: GoalDirected (today's code family implementing a subset of it), agent loop

**Loop Journal**:
The sealed, append-only record of a goal loop's observations, actions, receipts and reviews.

**Loop State**:
The bounded, typed working state a goal loop carries between iterations.

**Action Space**:
The committed set of actions a goal loop may choose from. New capabilities need a revision.

**Progress Review**:
The assessment at the end of an iteration that decides whether the loop continues.

**Parallel Swarm**:
A reusable Stage Graph composition/profile that runs bounded, isolated member variants and
converges selected exact results. Group identity, budgets, selection and surplus settlement remain
profile policies over common scheduling/transfer (OC-D204; [approved contract](docs/knowledge/parallel-swarm.md)).

**Member Variant**:
One declared member of a swarm.

**Convergence**:
The separate subprogram that turns swarm member results into one outcome.

**Evaluator Optimizer**:
The workflow system where an independent evaluator scores a producer's output against a rubric over
bounded rounds. It reuses GoalDirected machinery while preserving distinct node/execution/session
identities, exact sealed evaluator context, full typed prior reports to the next producer and host
decisions (OC-D205; [owner provenance](docs/specs/provider-consolidation-2026-10/answers/SPRINT-OC-RECOVERY-SITTING-1-2026-10-29-ANSWERS.md)).

**Optimization Round**:
One produce-and-evaluate cycle.

**Rubric**:
The typed scoring contract an evaluator applies.

**Executor**:
A program behavior that performs work directly: an Agent Executor (bounded cognition) or a Deterministic Executor (a registered executor kind with no model judgment).

**Durable Control**:
A program behavior that waits rather than works: Event Wait, Timer, Human Gate, Proof Gate.

**Human Gate**:
The durable control that opens exactly one Human Task per activation attempt and waits on its resolution or deadline; approve, reject and request-changes release, close or route the node. Timeout is never approval.
_Avoid_: approval node, checkpoint (the LangGraph word)

**Human Task**:
The durable record of a decision only a human can make, resolved by an attributed action: approved, denied, answered, selected, review_accept, review_reject or overridden.
_Avoid_: approval request, HITL item

**Review Decision**:
The payload of a review-kind human task: approve, reject, request_changes or abstain. It is not a second state machine.

**Approval Binding**:
The correlation of one Human Task with the native provider request it answers: origin, generation, session, turn, request, tool name, input digest and policy digest. The decision applies to that digest only.
_Avoid_: permission callback, approval handle

**Governed Effect**:
A Mission Control-owned tool effect that the governed MCP gateway admits in three steps: prepare without executing, review as a Human Task, execute the bound intent once.
_Avoid_: gated tool, protected call

**Approval Correlation**:
One expiring native request handle bound to an approval Human Task, held by one worker connection; closed exactly once as answered, expired, superseded or lost, and never reused for a later request.
_Avoid_: approval ledger, callback id

**Governed Effect Intent**:
The approval-bound, digest-pinned intent of a Mission Control-owned tool call; executed at most once into one immutable receipt, or settled denied, cancelled, expired, fenced, stale or in doubt.
_Avoid_: approval ledger, pending call

**Completion Candidate**:
An executor's submitted claim that its activation is done, with evidence.

**Completion Contract**:
The closed, typed expression that says what makes a node or mission accepted.

**Output Contract**:
The declared form, content and conditions an output or related set of outputs must satisfy. It can describe general outputs or application-specific content, including outputs that reference other deliverables.

**Output Obligation**:
A declared requirement for a program node or mission to deliver outputs satisfying an output contract. Producing those outputs does not by itself establish domain ingestion or publication.

**Output Form**:
The representation and handling category of an output, distinct from its application meaning or purpose. Content and authority requirements belong to its output contract.

**Obligation Fulfillment**:
The recorded determination of which exact eligible outputs satisfy a declared obligation at an evaluated point, including unmet quantity, coverage or guarantee requirements. It is distinct from submitting outputs or finishing execution.

**Inline Output Contract**:
An output contract authored directly for a mission's needs rather than selected unchanged from a reusable definition. It remains an exact contract for the outputs submitted against it.

**Output Guarantee**:
A condition an output contract promises about its submitted content, referenced deliverables or recorded effects. A layered contract requires each guarantee it declares.

**Completion Decision**:
Mission Control's computed verdict on a candidate. Execution success never implies acceptance.

**Evidence Assessment**:
A registered capability's attributable judgment about evidence, returned as a disposition.

**Disposition**:
The typed result of an assessment that a completion contract can reference.

### Execution, effects and settlement

**Harness**:
The provider-neutral protocol every execution lane implements: describe, then prepare, start, reattach, send_turn, cancel_turn, observe, snapshot, usage, end_session.
_Avoid_: adapter (the code's word), driver

**Lane**:
One harness implementation. Deep Agents and Cursor exist; Claude Agent SDK, Codex and Direct Model are specified only. A lane runs unqualified work only under an explicit local-proof policy.
_Avoid_: runtime kind, provider, host

**Agent Host**:
A tool a human or coordinator works in that reads generated configuration: Cursor, Codex, Claude Code. A host is where authoring happens; a lane is where mission work executes.

**Execution Binding**:
The exact pinned set an attempt runs with: packages, model route, prompts, tools, skills, workspace, sandbox profile, budgets and side-effect allowances.
_Avoid_: config, settings

**Materialization**:
Turning an execution binding into a real session and workspace, recording intended and actual versions and refusing mismatches.

**Operation**:
A journaled unit of externally visible work with an intent before and a settlement after.

**Operation Intent**:
The durable record written before an operation acts.

**Settlement**:
The recorded outcome of an operation or effect, including its cost.

**Effect**:
An external side effect with its own identity. Infrastructure retries keep the identity; new logical actions get a new one.

**Effect Ledger**:
The record of every effect's identity, claim and settlement.

**Side-Effect Class**:
A capability's declared kind of external impact, which decides what review and receipt it needs.

**Uncertain Effect**:
An effect whose outcome is unknown. It is reconciled before anything is re-executed.

**Budget**:
The admitted ceiling for money, tokens, duration, tools and sandboxes, reserved before work and settled after.

**Governor**:
A hard bound that stops work: depth, fan-out, rounds, iterations, patience or budget.

**Technical Retry**:
Re-running the same attempt after a transient infrastructure failure, with the same effect identities.

**Semantic Retry**:
New work with changed instructions, inputs or capabilities. It is never disguised as a technical retry.

**Workspace**:
The owned filesystem an attempt works in, with read-only mission context, skill bundles, inputs and declared writable paths.

**Workspace Closure**:
The evidence of what an attempt's agent could see when it settled (`attempt_settled`, `attempt_failed`, `attempt_cancelled`): every reachable file with its raw-byte digest, slot and destination, and its bytes within the Application Profile's caps; an attribute of the result checkpoint point (`workspace-closure://`), never a point of its own. Capture degrades past its caps and never fails the attempt.
_Avoid_: workspace snapshot (a git capture of a lease), workspace candidates (only writable-slot outputs)

**Workspace Lease**:
The fenced, time-bounded ownership of a workspace by one attempt generation; a stale lease cannot write or publish results.

**Mission Branch**:
The `mc/{run}/{unit}` branch one writable unit of a run publishes. A lease's worktree may push only its run's mission branches, and the `repo_pr` Governed Effect opens pull requests only from one; its observed head SHA is recorded as an immutable artifact.
_Avoid_: agent branch, PR branch

**Workspace Snapshot**:
The immutable capture of a workspace's base commit, staged, unstaged and included untracked content with a manifest digest, produced by one lease generation. A `git diff` is not one.
_Avoid_: patch, diff

**Environment Binding**:
The immutable resolution of where an attempt executes: a local workspace profile, or a provider-hosted environment with its revision, setup pins, network and secret policy and readiness evidence.
_Avoid_: environment config, provider settings

**Environment Kit**:
A pinned catalog bundle of toolchains, base install, mission setup steps and the variables, secrets, egress and git dependencies it requires; a manifest environment pins one as its setup pin.
_Avoid_: setup script, base image

**Base Layer**:
The rarely changing half of an Environment Kit (toolchains, system packages, long-lived services, egress, the bootstrap entrypoint), installed by Mission Control through a provider API where one exists and otherwise as an owner prerequisite.
_Avoid_: image, snapshot

**Mission Layer**:
The per-run half of an Environment Kit: its setup steps and health checks rendered into `.mission/setup/run`, which never contains a secret and writes `.mission/setup/receipt.json`.
_Avoid_: setup prompt, install instructions

**Bootstrap Entrypoint**:
The one guarded command per lane that runs the Mission Layer before agent work: the worker's prepare step on local lanes, the base layer's start hook on hosted ones.
_Avoid_: first-prompt setup

**Discovery Proof**:
The provider's own report of the cognition it loaded (`mc.discovery_report.v1`), gathered by mechanism and never by asking the model: Claude `system/init`, the Codex app-server lists, the Cursor SDK read-back, the `materialization.observed` signal, a hosted agent API read-back. It raises Readiness to discovered only when it names every item and reads every digest the prepare expected.
_Avoid_: discovery (that is finding external candidates), loaded (unproven)

**Provider Environment Strategy**:
How a hosted lane gets its Base Layer: `sync` (Mission Control creates or reuses `mc-<kit id>-<digest8>`, one per kit, policy and target repository, through the provider's environments API; Cursor only), `bind` (an existing environment or committed file, read but never written) or `generate` (the owner applies generated content). A committed provider file that overrides saved environments is checked first: mc-owned, foreign (refused unless bound) or absent.
_Avoid_: environment sync (unqualified), provider settings

**Readiness Level**:
How far an attempt's environment preparation is proven: declared, rendered, delivered, prepared (a passing setup receipt for the exact kit pin), discovered, exercised. A written file is delivered, never prepared. Each `mc.environment_preparation.v1` record holds the highest level with evidence and never regresses; a launch policy names the minimum a session may start at.
_Avoid_: ready (unqualified), ready flag, health status

**Owner Prerequisite**:
A human-only step a lane needs before a mission spawns (`mc.owner_prerequisite.v1`): ordered steps, generated paste-ready content rendered from the binding's Environment Kit and network policy, a verification method (api_probe, probe_mission, file_check, or the weakest, attestation) and freshness. The store keeps it per installation scope as unmet, attested or verified.
_Avoid_: setup checklist, manual step, TODO

**Prerequisite Standing**:
What a preflight reports for one Owner Prerequisite at a moment: met, expiring or stale (warnings), drifted (its generated content no longer matches the binding, or it changed since it was proven), expired or unmet (both block launch).
_Avoid_: prerequisite status (the stored state is separate)

**Task Token**:
A short-lived credential bound to one attempt, generation and permitted action that a hook or sandbox CLI uses to call the service. The Secret Broker mints them (`mint:<purpose>`) and stores only their digest.
_Avoid_: API key, session token

**Secret Broker**:
The port that resolves secret references from the installation's sources and delivers each value through one lane channel; a binding, frame, log or commit never holds a value.
_Avoid_: secret manager, vault (a vault is one of its sources)

**Signal**:
An observation sent from inside an environment or by a provider (a hook event, a milestone, a webhook). Evidence for reducers and watchers, never authority over lifecycle or settlement.
_Avoid_: event (a mission event is authoritative), status update

**Signal Ingress**:
The public endpoint that verifies who sent a signal, gate call, artifact upload or launch request and records it through one SQL function call into the ingress inbox, which only the worker drains.
_Avoid_: webhook server, callback endpoint (the loopback Kernel Hook callback is one mount of it)

**Provider Wake**:
A verified provider webhook reduced to the event type and the id of the resource it names, recorded once per delivery id. It tells the worker to re-read that resource from the provider and carries no state.
_Avoid_: webhook event, status callback

**Telemetry Hook Pack**:
What a lane's projection places so the environment reports to the Signal Ingress: the spooling `signal` hook script on the lane's native hook events, the `mc-signal` command, the signal policy and the `mc-signals` skill. It observes and never blocks an action.
_Avoid_: status file, watcher script, callback hook

**Trust Tier**:
How an ingress caller was verified (`run_token`, `provider_oidc`, `environment_key`, `provider_signed`, `launch_token`), recorded on every accepted message; it bounds what the message may drive.

**Sandbox Profile**:
The pinned image, limits, lifetime, egress and cleanup rules for a workspace.

**Artifact**:
An immutable, digest-registered output. A file becomes an artifact only after registration.

**Subordinate**:
Bounded sync or async work delegated by an activation, with a dependency class of required_blocking, degradable_blocking, nonblocking or advisory.
_Avoid_: subagent (the runtime's word), child (that is a child mission)

**Subordinate Lineage**:
The recorded graph that attaches a subordinate's harness execution to its parent by stable native references, with its kind (provider subagent, Agent Server child or linked mission) and how much of it is visible.
_Avoid_: agent tree, call stack

**Context Packet**:
The sealed, budgeted bundle an attempt receives to start or continue work: inline facts, references with retrieval instructions and files materialized into the workspace.
_Avoid_: prompt, context dump, handoff blob

**Context Transfer Contract**:
The declared agreement for moving selected outputs, state and history into receiving work, including required access, acceptable forms and governing conditions. It applies within a mission and between missions without transferring authority implicitly. It is distinct from an agent discovering additional knowledge through Knowledge Services.

**Application Context Adapter**:
An application-bound module that implements common, versioned contracts for resolving and exporting selected application content for deterministic context materialization and transfer. It owns the mapping to native storage identities and representations; canonical application content remains with its owning service.

**Application Content Reference**:
A typed, scoped reference to an exact application entity revision or retained result, resolved through its bound Application Context Adapter. It preserves native identity and version semantics rather than treating a URL or byte digest as the entity's identity.

**Content Representation**:
An exported or rendered form of selected content, with its own identity and a recorded relationship to the exact source and transformation. Producing a representation does not by itself create or ingest a new canonical domain entity.

**Ingestion Lineage**:
The receipt-backed mapping from original source artifacts to the application entities and revisions produced or affected by ingestion. It preserves both source and native result identities, including normalization or splitting.

**Invocation Origin**:
The host-constructed identity of one live attempt's call into an application knowledge service: issuer, scope, run, mission, activation, attempt, operation and invocation. It is bound by the service from a per-invocation credential, never taken from the model. Its mission is the run's ledger `mission_run.mission_id` and its activation the `activation.activation_id` that attempt admission recorded for the attempt's runtime unit (none without a runtime unit), both resolved by the host's invocation locator; an attempt whose mission cannot be resolved builds no origin. The runtime unit key is recorded beside it on Mission Control's journal, handle and submission rows, never inside the origin or on the wire.
_Avoid_: mission header, caller context, run context (the Biotech intent's word)

**Knowledge Handle Record**:
The durable host copy of one remote knowledge operation handle: its K01 status with a monotonic remote revision, the first cancel request id, the pending review, the result reference and unresolved effects. A restart finds an invocation's open handles here.
_Avoid_: job, task, operation row

**Effect-Scoped Recovery**:
The explicit host authority with which a new attempt re-dispatches one exact uncertain effect: the attempt is the credential origin and the grant names the effect key and bound digest; the envelope keeps the originating origin and identical bytes. Read-only recovery is the separate receipt-lookup authority after an invocation ended.
_Avoid_: retry token, impersonation

**Knowledge Operation**:
One admitted call from a mission into an application knowledge service, keyed by a semantic effect key, journaled before dispatch and settled by the service's receipt.
_Avoid_: tool call, ingestion request

**Qualified Handle**:
An opaque reference a knowledge tool returns to an agent, naming the binding, native kind, native identity and exact revision or retained read, resolvable by exactly one Source Binding.
_Avoid_: entity id, URI, ref

**Submission**:
An attributable offer of exact candidate outputs against a named obligation, made progressively or finally through the authoritative submission protocol. It is distinct from assessment, fulfillment and invocation settlement.
_Avoid_: final message, output_refs, declaration

**Provenance Role**:
One of seven separable facts about a deliverable: producer, caller, receipt, revision, adopter, assessor, consumer. Adopting is not producing.
_Avoid_: author, owner, origin (that is Invocation Origin)

**Source Binding**:
The pinned, operator-admitted registration of an application storage extension for one application and content core, with the facets it has proven it supports.
_Avoid_: plugin, connector, adapter config

**Retained Observation**:
The exact result of one admitted application read, kept with its digest, consistency facts and availability commitment so later transfers reuse it without a fresh query until an explicit refresh.
_Avoid_: cache, snapshot (the Biotech read's word), copy

**Read Intent**:
One bounded, recorded discovery read of an application knowledge store through the knowledge gateway (`knowledge.read_intent`): allowlisted named queries and schema reads answered from one snapshot with a content digest each, every answered read kept as a Retained Observation. It is never a use decision, verified evidence or a Source Binding.
_Avoid_: query, SQL read, lookup

**Step Contract**:
One stage of the research pipeline (discover, capture, prepare, assert, verify, report, assess, ingest) as a contract: inputs pinned by digest, pinned method and policy, a sealed output with provenance. Deterministic steps run only in Knowledge Services; semantic steps may be hosted by a Knowledge Services executor or a mission agent.
_Avoid_: task, phase, job

**Report Core**:
The one storage-neutral model of an evidence-backed report revision (`research-report.v2`) that Knowledge Services verifies, renders and reads, bound to each application's store by a binding.
_Avoid_: report package (the PostgreSQL binding's word), report.publish (the Biotech proposal's word)

**Readiness Receipt**:
The recorded proof, before a receiving invocation starts, that mandatory state is present under budget, every required file was delivered and probed readable, every required access handle is currently valid and the lane's delivery is qualified. It proves delivery facts, not attention.
_Avoid_: preflight, health check

**Transfer Profile**:
A reusable, versioned set of context-transfer requirements and defaults that an author can apply and specialize within applicable policy.

**Transfer Plan**:
The resolved selection of exact inputs and their delivery forms under a context transfer contract and applicable constraints. It is distinct from evidence that those inputs were actually delivered.

**Expansion Tier**:
How one item of a context packet reaches the agent: inline (bytes in the prompt), reference (identity, summary and how to fetch), materialize (a file in the workspace) or workspace (a restored snapshot).

**Context Packer**:
The deterministic function that builds a context packet from accepted outputs, state, checkpoints and selected context under a model profile's budget.

**Lane Profile**:
One placement of a lane with its own qualified control matrix and workspace contract: `deep_agents`, `cursor_local`, `cursor_cloud`, `claude_agent_sdk` (Claude Code Local), `claude_cloud`, `codex` (Codex Local) or `codex_cloud`.
_Avoid_: runtime mode, deployment target

**Placement**:
Where a lane profile's agent loop runs: worker-hosted (a process on a Mission Control worker) or cloud (the provider's own hosted product). Our own remote worker is never a cloud placement.
_Avoid_: deployment, hosting mode

**Harness Execution**:
The recorded native identity of one lane run of an attempt generation: provider session and turn refs, provider cursor and usage disposition. Provider frames are keyed by it.
_Avoid_: run (that is a mission run), job

**Lane Describe**:
A lane profile's declared control matrix (`mc.lane_describe.v1`, or `.v2` for the four profiles added for Claude Code and Codex): each control native, emulated, unsupported or unqualified, the delivery semantics per command, hooks, identity map and placement. Tests hold each lane to it.
_Avoid_: capability list, feature flags

**Lane Qualification**:
The recorded evidence, from a live drill, that flips a lane profile's `qualified` flag through a reviewed release. Offline fixtures never flip it.
_Avoid_: certification, approval

**Resolution Seam**:
The one call that turns a node's selection (lane profile, model profile, family, node role, application and agent configuration) into a Resolved Runtime or a typed refusal (ADR-0063; `application/resolution/resolver.py::RuntimeResolver.resolve`). It reads only the Lane Registry, the Application Registry, the Model Catalog and the lane's pure compile. Only Deep Agents compiles through it today; the other lanes are admitted describe-only (`RuntimeResolver.admit`).
_Avoid_: router, provider strategy, dispatcher

**Lane Registration**:
What one lane package exports (`adapters/<lane>/lane.py::LANE` or `LANES`; `application/resolution/ports.py::LaneRegistration`): its Lane Declaration, pure compile adapter and harness factory. Bootstrap lists the registrations once (`bootstrap/lanes.py`); the seam refuses a profile without one as `LANE_UNKNOWN`.
_Avoid_: plugin, provider adapter

**Lane Declaration**:
The data a lane registers beside its Lane Describe: one model route per vendor, support per configuration item kind, support per workflow family and runtime pins (`domain/resolution/profiles.py::LaneDeclaration`). The resolver reads each fact from this one place.
_Avoid_: capability list, feature matrix

**Sealed Lane Binding**:
A lane's typed binding as canonical UTF-8 JSON under its raw SHA-256 digest (`domain/resolution/sealed.py`). The operation request carries it in its one `lane_binding` slot; the core moves it by digest and only the producing lane unseals it.
_Avoid_: provider payload, opaque blob

**Resolved Runtime**:
The seam's result for one node (`domain/resolution/resolved.py::ResolvedRuntime`): the selection digest, agent configuration, Sealed Lane Binding, the application's knowledge, output and transfer sides, the materialization receipt and the Application Profile revision, under one runtime digest.
_Avoid_: runtime config, resolved provider

**Selection Workspace**:
The read-only place a coordinator chooses a node's lane, model profile, capabilities, sandbox profile and Workflow Type before writing a manifest (`application/selection/workspace.py`): one faceted search over Capability Search, the Lane Registry and the Model Catalog, and one check of a draft selection against the seam's admission, host support and the Workflow Type's authority ceiling. It never compiles, seals or launches. It is not a Workspace (an attempt's filesystem).
_Avoid_: workspace (bare), selection service, router

**Catalog Workspace**:
A generated, read-only filesystem rendering of the catalog (workflow types, lanes and providers with their lifecycles and describe matrices, models, capabilities, sandbox profiles, configuration items, worked examples, task pages), pinned to a release and mounted into a sandboxed agent's Workspace so the agent navigates Mission Control by reading files, the way the AI Engineer schema workspace is navigated. Additional to the MCP tools and `missionctl`; shares its registries with the Selection Workspace; not the codebase documentation. Not built (AS-D38).
_Avoid_: mission control workspace, docs workspace

**Session Owner**:
The one worker process allowed to drive a worker-hosted provider session at a time, holding a renewable lease; a takeover after expiry fences the previous owner out, and a fenced owner can neither send nor settle.
_Avoid_: session holder, sticky worker

**Remote Session Lane**:
A lane profile whose agent loop the provider runs behind a session API (`cursor_cloud`, `claude_managed`, `codex_agents`): Mission Control creates the session, streams its events, reconciles from the provider's records and keeps custody of what it produced, but runs neither the harness nor the sandbox. They share one base (ADR-0052).
_Avoid_: managed lane, cloud lane, hosted harness

**Dispatch Journal**:
The durable record of every native session create and turn send, written before the provider is called and resolved as acknowledged, declined, not received or in doubt. A dispatch the provider may have accepted is reconciled or parked in doubt, never sent again blindly.
_Avoid_: send log, retry queue

### Control and recovery

**Command**:
An admitted, ordered instruction to a run. Lifecycle: accepted, queued, delivered, observed, completed.
_Avoid_: signal, message

**Delivery Report**:
What a lane actually did with a command, reported separately from what was requested.

**Command Mailbox**:
The durable, per-run and per-generation holding area for queued instructions and added context, consumed once at the next safe boundary.
_Avoid_: queue (ambiguous with Temporal task queues), inbox

**Stop Fence**:
The persisted, insert-only marker written before any provider cancel of an immediate cancel; every later effect admission for that run and generation is denied. It does not halt a tool already dispatched.

**Intervention**:
A privileged operator command: cancel, resume, satisfy a wait, fork from a checkpoint or reconcile.

**Reducer**:
The deterministic function that owns lifecycle transitions and settlement. Nothing else changes lifecycle.

**Outbox**:
The transactional relay from the application database to Temporal.

**Checkpoint**:
A sealed, digest-verified manifest of a run's state that continuation resumes from. Its full name is Continuation Checkpoint.
_Avoid_: LangGraph checkpoint (that is runtime persistence), snapshot

**Checkpoint Lineage**:
The ordered ancestry of checkpoints a run has sealed.

**Snapshot**:
A read-only capture of a run at a safe boundary, used to inspect or fork.

**Fork**:
A new run or mission created from a snapshot. It never clones in-flight commands or active children.

**Continuation**:
Resuming work after a checkpoint, in a fresh session or workspace when needed.

**Compaction**:
Reducing carried context before continuation under a context health policy.

**Runtime Unit**:
The smallest provider-neutral unit of execution the kernel tracks and reconciles.

**Generation**:
A monotonically increasing number that fences stale results from an earlier launch.

**In Doubt**:
A unit whose provider state cannot be confirmed; it is reconciled, never duplicated.

**Provider Frame**:
One raw event a lane observed from its provider or from a hook, persisted verbatim before any derivation.
_Avoid_: trace event, log line

**Closing Frame**:
A provider frame that states a settled fact (a tool call completed, a turn ended, a result arrived); the reducer reads only closing frames.

**Usage Disposition**:
Whether a usage dimension is settled, estimated or unknown. Unknown is never counted as zero.

**Native Event Store**:
The bounded-retention store of provider frames keyed by harness execution. Mission events point into it; it never enters the mission stream.

**Transcript**:
The materialized, read-only view that joins a run's mission events, provider frames and artifact references in order. It is evidence for humans and agents, never state.
_Avoid_: trace (LangSmith's word), chat log, history

**Subscription**:
A durable registration to receive selected mission events by webhook, stream or agent notification, delivered at least once from the outbox.
_Avoid_: callback hook, listener, watcher

**Watcher**:
A declared, bounded reaction of a mission to an observed fact: one trigger (event, signal, absence or schedule), a closed condition, typed actions that are admitted Commands or an inbox notification, and mandatory limits. Compiled into the definition as a watcher descriptor; a reusable body is the Capability Kind `watcher`.
_Avoid_: callback, supervisor, poll loop, hook (a Hook Script runs inside a lane); a Subscription only delivers events

**Durable Transition Reaction**:
A declared, bounded reaction to one durable transition of a run (an output submitted, an assessment recorded, a fulfillment decided, a delivery recorded or a saved result settled) that runs an ordinary admitted operation started by Temporal: one logical activation per binding and transition, admitted with its outbox dispatch intent under recursion, rate, activation, time and spend limits; a stale generation or a fenced run cancels it before dispatch.
_Avoid_: hook, trigger job, reaction scheduler; a Watcher issues admitted Commands, not operations

**Watcher Evaluator**:
The one deterministic evaluation of a run's watchers, scheduled only by Temporal (`mc.watchers.v1`): it plans firings from the journal, signals and clock, issues their actions and records each firing once as `watcher.fired` or `watcher.failed`.
_Avoid_: watcher loop, relay

**Stream Subscription**:
A connection-scoped registration on the mission stream that names its target, streams, filters and cursors and lives only as long as the socket; it is not a Subscription and confers no authorization.
_Avoid_: room, channel, listener

### Catalog and capabilities

**Catalog**:
The per-application set of admitted, versioned assets.

**Capability**:
An installed, digest-pinned, admitted asset that a mission may bind. Its kind is one of the catalog's recorded kinds.

**Capability Kind**:
The category of a capability. The canonical list lives in the catalog, not in a document.

**Capability Pin**:
The exact version and digest a binding references.

**Capability Search**:
Semantic and filtered selection of catalog assets before compiling exact bindings.

**Search Projection**:
The read-only index built from the catalog for search. It is never an authorization store.

**Discovery**:
Finding external candidate assets. Candidates are quarantined until inspected and approved.

**Skill Bundle**:
A packaged, pinned skill directory a lane can materialize.

**Environment Profile**:
A catalog asset that pins a workspace and sandbox shape.

**Model Profile**:
One row of an installation's Model Catalog (`deployments/<app>/models.toml`): the name a manifest writes in `model.profile`, its vendor, exact model id, context window, list prices, supports and Data Class ceiling. It names no lane; a lane runs it only if its declared model routes route the vendor.
_Avoid_: model (bare), provider model, the AI Engineer knowledge schema's model entities (knowledge, not workflow seeding)

**Workflow Template**:
A reusable, versioned program fragment.

**MCP Server**:
A capability that declares a Model Context Protocol server: transport, launch or endpoint identity, secret references and the tools it exposes.
_Avoid_: tool server, integration

**Plugin**:
A pinned composition of other capabilities (skill bundles, MCP servers, hook scripts, subagent profiles, prompts and resources) admitted and bound as one unit.
_Avoid_: extension, marketplace plugin, package

**Hook Script**:
A capability that runs at a declared hook event before or after an agent action and returns a typed decision or added context.
_Avoid_: middleware (the Deep Agents word), callback, interceptor

**Hook Event**:
One of the provider-neutral points in an agent session's lifecycle at which a hook script may run.

**Kernel Hook**:
A hook Mission Control attaches to every session for fences, intents, usage and frame capture, running in process or as a command hook that calls the worker back with a task token. It is not a catalog item and no manifest can remove it.

**Subagent Profile**:
A capability describing a delegable agent (purpose, instructions, tools, model, mode) that a lane projects into its native subagent format.
_Avoid_: subagent file, agent definition, persona

**Host Projection**:
Rendering a capability into one lane profile's native configuration files and formats.
_Avoid_: install, export, sync

**Lane Layout**:
One lane profile's row of the layout table a Host Projection follows: how its cognition is delivered, the native roots and files it lands in, which subagent profile fields the provider can carry, the provider's limits, and for a hosted agent API the API field each capability kind travels through.
_Avoid_: path map, provider config

**Overlay**:
The few lane-profile-specific fields a capability row carries beside its provider-neutral core, applied only when projected to that profile.
_Avoid_: override, variant

**Instruction Overlay**:
The mission's operating contract added through a lane's additive instruction channel (an always-apply rule, a system-prompt append, developer instructions or a delimited section), so the repository's own instruction files load unchanged.
_Avoid_: CLAUDE.md shim, AGENTS.md rewrite

**Layering**:
Placing a Host Projection over the repository it lands in: shared config files are merged with provenance markers, conflicts resolve by the manifest's materialization policy, and local lanes restore the repository's bytes after the run.
_Avoid_: overwrite, sync

**Hybrid Search**:
Capability search that fuses full-text, name-trigram and vector rankings after grant and compatibility filtering, and falls back to lexical-only when no embedding route works.

### Authoring and coordination

**Coordinator**:
The API client with authoring capabilities that talks with the human and drives a mission from draft to start. Its chat is not execution authority.

**Authoring Session**:
The bounded, budgeted coordinator conversation that produces a mission draft. The interview is its question-asking mode.
_Avoid_: interview session

**Interview**:
The question-asking mode of an authoring session, used before research, ingestion, content and coding missions alike.

**Draft**:
An editable, not yet compiled mission definition.

**Validation Report**:
The typed result of validating a draft: errors with pointers, missing capabilities, policy conflicts and warnings. Validation launches nothing.

**Launch Ticket**:
The prepared, admitted request that starts a run.

### Knowledge and domain

**Knowledge Services**:
The shared contracts for evidence, source identity, provenance, governed domain writes and retrieval that applications implement in their own adapters.

**Domain Service**:
An application-owned service that judges evidence and performs entity writes. The kernel never writes entities.

**Intent**:
An immutable, digest-pinned request for a domain effect, applied only through its receipt contract.

**Receipt**:
The durable proof that a domain effect happened, with its idempotency identity.

**Advisory Memory**:
Recalled, attributable references that inform work and grant nothing until revalidated.

**Context Selection**:
The reproducible choice of what an attempt gets to read, captured as candidate identities, ranking and configuration.

**State Handoff**:
A typed delta plus base version and digest that moves state between activations through a deterministic reducer.

### Platform

**Common Component**:
The versioned schema release every application database installs identically.

**Release Attestation**:
The recorded proof that an installation holds a complete, fingerprint-matched release.

**Runtime Persistence**:
The subordinate, recoverable state of the agent runtime. It is never mission truth.

**Agent Server**:
The required execution host for bounded asynchronous subordinate graphs. It schedules nothing.

**Deep Agents**:
The first execution lane: bounded operation cognition on LangGraph.

**Cursor**:
The second lane family, with two lane profiles: Cursor Local (the agent loop in a bridge process on a worker) and Cursor Cloud (a Cursor-hosted machine driven through its API).

**Claude Code**:
The third lane family, with two lane profiles: Claude Code Local (`claude_agent_sdk`, the Python Agent SDK client on a worker) and Claude Cloud (`claude_cloud`, Anthropic's hosted product).

**Codex**:
The fourth lane family, with two lane profiles: Codex Local (`codex`, the app-server protocol on a worker) and Codex Cloud (`codex_cloud`, OpenAI's hosted product).

**Temporal**:
The only mission scheduler.

**Cluster Binding**:
The write-once record of the Temporal cluster and namespace a run was first launched in. A run never starts in another cluster; a cluster outage lets new runs target another binding but never moves an active run.
_Avoid_: failover, cluster affinity

**LangSmith**:
The sandbox and tracing provider. Traces are not the ledger.

**Current Accepted Set**:
The exact versioned set of currently eligible deliverable revisions at an evaluation frontier. Earlier accepted successes remain members until an attributable replacement or eligibility change.

**Submitted Not Accepted** (`SUBMITTED_NOT_ACCEPTED`):
A promise's finalized submission that no passing assessment or accepting verdict has made an accepted head; reported as such, never as missing.

**Sealed Transfer Plan**:
The immutable authority for one receiver's selected exact inputs, boundary state, purpose, representations and resource plan. New delivery attempts append evidence without changing the selection.

**Delivery Receipt**:
An attempt-specific record of actual input materialization, integrity, access and backend readiness under a sealed transfer plan. It proves delivery facts, not understanding.

**Invocation Settlement**:
Resolution of a completed invocation's required output, review, effect and accounting barriers. Completed cognition can be retained while settlement waits.

**Group Closure Witness**:
Evidence that a reduction group's contributor population is complete at an exact frontier. Closure does not waive missing required contributions.

**Partition Successor**:
An admitted replacement work plan with exact membership, coverage and lineage to its predecessor. It is new work rather than a retry with changed inputs.

**Preservation Proposal**:
A bounded attributable candidate note or exact reference offered for host validation at compaction. It cannot replace mandatory authoritative state.

**Coordinator Acknowledgment**:
An attributable confirmation by the receiving coordinator of a specific model-visible delivery. Transport success alone is not acknowledgment.

### Agentic SDLC (2026-11-01, SPEC-01)

**Agentic SDLC**:
The documentation and lifecycle system in which agents are the primary developers: one contract enforced by a vendored CLI, triggered by git events, with the owner's subscriptions behind a provider adapter. Program `docs/specs/agentic-sdlc-2026-11`.
_Avoid_: docs pipeline, CI bot

**Information Category**:
One of the nine parts of a service every repository's knowledge bundle must cover (boundaries, surfaces, domain-model, persistence, execution, qualification, operations, decisions, goals), carried as `category:` on a concept.
_Avoid_: tag, topic

**Vendored Upstream**:
The pinned copy of the SDLC CLI, skills and hook templates inside a repository (`.sdlc/`, `.agents/skills/`, their lock files), pulled by decision from `platform/agentic-sdlc`, so the repository works alone.
_Avoid_: shared dependency, submodule

**Drift**:
A registered module whose source hash changed since the last documentation build while no concept associated with it changed; exempted only by a `Docs: none <reason>` commit trailer.
_Avoid_: stale docs, outdated

**Provider Adapter**:
The one interface through which the model-driven SDLC steps (`propose`, review) run, implemented for the Cursor CLI (default) and the Claude Code CLI, selected in `.sdlc/config.json`.
_Avoid_: model backend, LLM integration

**Idea**:
An owner-written file in `platform/agentic-sdlc/ideas/` with an `ID-n`, a status and the itch paragraph agents never edit; the first link of the provenance chain.
_Avoid_: ticket, backlog item, note

**Provenance Chain**:
The resolvable links from an Idea through the interview instrument, answers rows, spec sections, ADRs and glossary terms to Linear issues and commits, printed by `sdlc trace`.
_Avoid_: audit trail, history

**Retrieval Fixture**:
A frozen set of concepts with labelled queries (`expected`, `critical`, `partition`) and a recorded baseline that `bench --gate` must not fall below.
_Avoid_: test data, golden set
