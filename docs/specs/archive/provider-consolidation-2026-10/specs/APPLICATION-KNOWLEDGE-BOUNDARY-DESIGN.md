---
type: Architecture Projection
title: "Application knowledge to agent context: explicit storage-extension projection"
description: "Deep-module projection of the Mission Control <-> application knowledge boundary as decided in the prerequisite interview of 2026-10-24 (OC-D79..102): the Knowledge Operation Protocol, trusted invocation origin, the one agent act submit_output, qualified handles, seven provenance roles, one evidence-backed report core with PostgreSQL and Neo4j bindings, the common storage-extension port with one ReportPackageExtension, resolution, representation, delivery into context window and sandbox, the prerequisite migration map A0/A/B/C/D, failure matrix and the delta to the accepted checkpoint."
tags: [mission-control, architecture-projection, application-boundary, provenance, context-transfer, knowledge-services]
date: 2026-10-24
prepared_by_model: "GPT-6-Astra (starter, 2026-10-24); completed by Claude Fable 5.1 in the prerequisite interview sitting of 2026-10-24"
source_commit: 8de6fab94fd5d17d79f2ecfd92e55329bb282a36
inspected_commits: "knowledge-services 28c4422; biotech-knowledge-services d042678; ai-engineer-db-contract c809a11 (working copy 0.4.16)"
answers: answers/application-knowledge-boundary/claude-fable-5-1-2026-10-24/ANSWERS.md
projection_stage: interview-complete-pending-owner-confirmation
status: archived
archived: 2026-11-02
archived_from: APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md
archived_reason: "converted into OUTPUT-CONTRACTS, ADR-0059 and ADR-0060; built by OVE-204"
---

> **Archived 2026-11-02** (converted into OUTPUT-CONTRACTS, ADR-0059 and ADR-0060; built by OVE-204). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Application knowledge to agent context: explicit storage-extension projection

**Status:** interview complete 2026-10-24; owner confirmed the walkthrough and frontier (OC-D105) and
the module depth (OC-D103) and reading levels (OC-D104). Decisions OC-D79..105 folded; accepted
checkpoint OC-D27..78 preserved. Answers: [ANSWERS.md](../answer-sets/application-knowledge-boundary/claude-fable-5-1-2026-10-24/ANSWERS.md).
Nothing here is built. No conformance claim belongs here until implementation is checked against it.

**Stance (OC-D81).** This is the target system. The current code is the migration baseline and is
cited as such; it does not constrain the design. Where the target differs from today, §7 names the
migration. Where a claim rests on current code it carries a `file:line` anchor; where it is a design
choice it carries a decision id; where it is still engineering judgement it is labelled **assumption**
and listed in §10.

**Labels.** **existing** has a source anchor; **accepted** has an OC-D/DP-D id; **proposed** is
engineering design under those decisions; **assumption** is open and listed in §10.3.

## 1. Goal, the three surfaces and the decisions

Owner's goal, verbatim:

> We're trying to avoid giving mission agents any mission control storage responsibility.

> We need beautiful, effective deep modules for output contract verification, retrieval, materialization and conversion AND transmission into AGENT CONTEXT (The context window) AND (special transmission of artifact to sandbox and sandbox location reference to agent context)

> It's looking like a lot of this hinges on Agents faithfully providing refs to outputs. That is ok. This is an agentic system. Let's just do the best we can.

Happy path, verbatim: a GoalDirected workflow with an output contract for assertions and a report; the
agent is instructed to return a structured output with a file reference and application-specific
entity ids. After OC-D83 that structured output is the payload of one tool call, `submit_output`,
not the final message.

### 1.1 The three surfaces of one contract

| Surface | What they see | What is behind it |
| --- | --- | --- |
| Mission author | Obligations (`report`, `assertions`), the application binding, the five guarantees, the receiving form for the next agent | Compiled pins, the registered storage extension, the credential audience, the transfer profile |
| Working agent | Domain tools per binding (`knowledge_read`, `knowledge_apply`, `report_publish`), qualified handles in tool results, one act `submit_output` | Invocation origin, per-invocation credential, effect keys, knowledge-operation observations, candidate capture, lineage |
| Coordinator / operator | Fulfilled and missing obligations, seven-role provenance per deliverable, the exact packet the next agent received | Assessments, retained observations, representations, transfer plan, delivery and readiness receipts, native receipts |

### 1.2 Decisions this projection rests on

| Theme | Ids |
| --- | --- |
| Checkpoint baseline | OC-D38..44, D45..52, D54..61, D64..70, D71..77, D78; DP-D3/D5/D6/D14 (open proposals, consistent with below) |
| Agent duty and submission | **OC-D83** (one act `submit_output`), **OC-D89** (qualified handles, scoped completion, narrow auto-association) |
| Trusted origin | **OC-D79** (admitted boundary; untracked standalone), **OC-D84** (KS-native protocol), **OC-D85** (bind before seal; migrate schema), **OC-D87** (child origins; `origin_unproven`) |
| Provenance | **OC-D80** (seven roles), **OC-D90** (file vs native report are distinct until lineage relates them) |
| Results and recovery | **OC-D88** (effect-key correlation, reconcile before retry), **OC-D101** (keys, retained sources, sealed packets) |
| Report and verification core | **OC-D82**, **OC-D86** (one report module, two bindings; pipeline generalized), **OC-D95** (one VerificationRun), **OC-D96** (`research-report.v2`), **OC-D97** (ports in KS; SQL binding; Biotech protocol adapter), **OC-D98** (step contracts; semantic steps hostable by KS or MC) |
| Fulfilment and delivery | **OC-D91** (five guarantees), **OC-D92** (exact body + assertions + evidence handles), **OC-D93** (state and assertions inline, body as indexed file), **OC-D94** (named read-only inputs, mount index, probe), **OC-D99** (readiness receipt), **OC-D100** (same module per boundary) |
| Migration | **OC-D102** (map A0/A/B/C/D and order), **OC-D81** (target first) |

## 2. Module map

Few entry points, much behind them. Layer rule: interfaces call application; application uses domain
and ports; adapters implement ports; bootstrap wires; domain imports no I/O (`AGENTS.md` Invariants).

**Two categories of depth (owner, OC-D103).** The *agent-facing representation*: a handful of tools per
binding, qualified handles in their results, one act `submit_output`, files under `/inputs` and
`/outputs`, and the mount index. The *codebase modules* below. A change that deepens one must not
shallow the other: a new kernel module never adds an agent-visible step, and a new agent-visible tool
is a projection of an existing module, not a new authority.
Knowledge Services modules follow its own layering (contracts ← verification/preparation/knowledge-db ←
application ← host/executors) with one addition: a `bindings/` layer under the store ports.

### 2.1 Knowledge Services (shared package, used by both executors) — OC-D84, D95..98

| Module | Layer | Interface (one line) | Hides | Refuses |
| --- | --- | --- | --- | --- |
| `@aiengineer/knowledge-operation-protocol` (new contracts package) | contracts | `OperationEnvelope<Op>`, `OriginEnvelope`, `OriginCredentialClaims`, `QualifiedHandle`, `EffectKey`, `OperationReceipt`, typed refusals | Nothing: it is the published wire shape both executors and Mission Control compile against | A payload origin that disagrees with the credential (`ORIGIN_MISMATCH`); an unknown issuer; an expired audience |
| `@aiengineer/research-core` (new) | application-neutral domain | `ReportRevision` (v2), `Assertion`, `VerificationRun`, `Assessment`, `StepContract<I,O>`, `renderReport`, `mechanicalGates`, `sealManifest` | Stage semantics, verdict lattice, offsets, ledger derivation | A report whose assertion is unbound; a step whose inputs are not pinned by digest |
| `research-core/ports` | ports | `EvidenceStore`, `ClaimStore`, `VerificationStore`, `ReportStore`, `Custody`, `EvidenceOracle` | Where rows live | - |
| `bindings/aiengineer-postgres` | adapter | implements the six ports over `research.*`, `evidence.*`, `corpus.*` | SQL, roles, tenant GUCs | A write outside the credential's tenant |
| `bindings/biotech-graph` | adapter | implements the six ports by compiling to intent-v2 proposals and read-v2 operations against the Biotech executor | Cypher, labels, markers, graph revisions | A guarantee the Biotech surface cannot give (historical traversal, uniform PostgreSQL consistency) |
| `knowledge-origin` (in `host`/executor auth) | application | `bindOrigin(credential, payload) -> BoundOrigin` | JWKS lookup per issuer, audience and grant checks | Unsigned, foreign-audience or expired credentials; standalone `system = mission-control` |
| Executor operations (both) | interface | `POST /knowledge/:op`, MCP, CLI take `OperationEnvelope` | Transport | Anything not admitted by the catalog |

### 2.2 Mission Control — OC-D79, D83, D88..94, D99..101

| Module | Layer | Interface (one line) | Hides | Refuses |
| --- | --- | --- | --- | --- |
| `domain/knowledge/origin.py` | domain | `InvocationOrigin`, `ChildOrigin.for_subordinate(parent, child)` | Nothing; pure identity rules | A child origin whose parent is not the current invocation |
| `domain/knowledge/handles.py` | domain | `QualifiedHandle.parse/str`, `EffectKey.mint(origin, capability, native_digest)` | Handle grammar, key canonicalization | A handle naming a binding outside scope |
| `domain/outputs/submission.py` | domain | `Submission`, `Selection`, `reconcile(submissions, candidates, observations) -> CandidateSet` | Auto-association rules (OC-D89) | Two matches for one obligation (ambiguous) |
| `domain/outputs/guarantees.py` | domain | `RequiredGuarantees`, `evaluate(subjects, assessments) -> FulfilmentDecision` | The five-guarantee algebra (OC-D91) | A guarantee without an applicable assessment |
| `domain/knowledge/lineage.py` | domain | `ProvenanceRole`, `LineageFact`, `ContentLineage.add(role, actor, subject)` | Role invariants (OC-D80) | Adoption recorded as production |
| `application/knowledge/gateway.py` | application | `KnowledgeGateway.invoke(call, origin, credential) -> KnowledgeResult`; `.reconcile(effect_key)` | Envelope construction, effect-key minting, observation journal, lost-response reconciliation | A call without a live origin; a native intent already sealed with a different origin |
| `application/knowledge/toolset.py` | application | `build_toolset(binding, origin, credential) -> tuple[Tool, ...]` | Per-binding tool projection (`knowledge_read`, `knowledge_apply`, `report_publish`, `verify_*`) | A binding the attempt's execution binding does not pin |
| `application/outputs/submission_service.py` | application | `SubmissionService.submit(origin, obligation, selection) -> SubmissionRef`; `.finalize(invocation) -> FinalizationReport` | Candidate registration, handle completion, reminder/auto-finalization/repair ladder | Undeclared obligation; unresolvable or out-of-scope ref |
| `application/outputs/acceptance.py` | application | `OutputAcceptance.evaluate(frontier, candidates) -> OutputDecision` | Assessment orchestration per guarantee, reuse (OC-D73), current-set publication | Missing required proof; stale frontier |
| `application/context/source_bindings.py` | application | `SourceBindingRegistry.register(binding, extension, required_facets)`; `.require(pin)` | Admission of extensions at composition, facet qualification | An extension missing a required facet |
| `application/context/resolution.py` | application | `ContentResolutionService.resolve(selection, origin) -> ResolvedSource` | Binding lookup, scoped access, envelope verification, retention | Exact revision unavailable; undeclared expansion |
| `application/context/representation.py` | application | `RepresentationService.ensure(source, form) -> Representation` | Stored-artifact vs pinned-renderer choice, digest/lineage verification | Hidden summarization; omitted required field |
| `application/context/delivery.py` | application | `DeliveryPlanner.plan(bindings, frontier, receiver) -> TransferPlan`; `Readiness.require(plan, receipts) -> ReadinessReceipt` | Budgeting, two destinations, repair ladder (OC-D61/D99) | Mandatory content unavailable; budget conflict |
| `application/ports/application_storage.py` | port | `ApplicationStoragePort` (`describe`, `resolve`, `export`, `resolve_lineage`, `ensure_availability`) | - | - |
| `integrations/knowledge_extensions/report_package.py` | integration (adapter) | `ReportPackageExtension(binding, client, custody)` implements `ApplicationStoragePort` for any `research-report.v2` binding | The protocol client and custody per binding | A binding whose `describe` lacks `report-package-read` |
| `adapters/deep_agents/knowledge_tools.py` | adapter | wraps the toolset as LangChain tools with the origin in the closure | LangGraph `ToolRuntime` | Model-supplied origin fields (ignored, logged) |
| `adapters/deep_agents/materializer.py` (changed) | adapter | `materialize_inputs(plan) -> DeliveryReceipt` with readability probe | StateBackend vs sandbox upload | Binary on text-only backend without authored alternative |
| `adapters/postgres/knowledge/*` | adapter | repositories for `knowledge_operation`, `content_lineage`, `source_binding`, `retained_observation`, `submission`, `transfer_plan`, `delivery_receipt` | SQL | Cross-scope reads |
| `bootstrap/composition.py` (changed) | bootstrap | registers extensions and credential minting per application binding | - | - |

The agent never sees `InvocationOrigin`, `EffectKey`, repositories or custody. It sees tools, handles,
`submit_output` and the files under `/inputs` and `/outputs`.

## 3. File tree

Added (`+`), changed (`~`), removed (`-`). **Proposed placement; reviewed against existing modules in
§2.** No file is created by this document.

```text
platform/knowledge-services/
  packages/
  + knowledge-operation-protocol/src/{origin,envelope,handle,effect-key,receipt,refusals}.ts   OC-D84
  + research-core/src/
  +   report/{revision.ts,render.ts,ledger.ts,gates.ts}        research-report.v2             OC-D96
  +   verification/{run.ts,manifest.ts,seal.ts}                one VerificationRun            OC-D95
  +   steps/{contract.ts,ladder.ts}                            step contracts                 OC-D98
  +   assessment/{kinds.ts,guarantees.ts}                      five guarantees                OC-D91
  +   ports/{evidence,claim,verification,report,custody,oracle}.ts                            OC-D97
  + bindings/aiengineer-postgres/src/*.ts                      today's SQL behind the ports   OC-D97
  + bindings/biotech-graph/src/*.ts                            intent-v2 / read-v2 adapter    OC-D97
  ~ contracts/src/verification/model.ts                        verdict lattice unchanged; imported by core
  ~ knowledge-db/src/ingestion/{executor,plan,receipt}.ts      origin in digest; effect_key; receipt_get(effect_key)   OC-D85/D88
  ~ knowledge-db/src/ingestion/reports/*                       becomes the postgres binding of the core
  ~ knowledge-db/src/ingestion/evidence-admission.ts           oracle over VerificationStore (one sealed manifest)     OC-D95
  - apps/verification-executor/src/intents.ts::ReportIntent    retired                                                  OC-D96
  ~ apps/verification-executor/src/{http,mcp,auth}.ts          OperationEnvelope; credential verification; origin bind  OC-D84
  ~ apps/worker/src/verification-claims-sealer.ts              one sealer with the executor path                        OC-D95

biotech/biotech-knowledge-services/
  ~ packages/contracts/src/intent-v2.ts     origin envelope; report.publish: bodyRef, ledgerRef, item fields, cites assessments  OC-D85/D96
  ~ packages/contracts/src/read-v2.ts       custody read by ref; report traversal includes bodyRef/ledgerRef               OC-D92
  ~ packages/kg-ops/src/write/{compile,proposals}.ts   Activity tenant/issuer/invocations; origin compare; report fields   OC-D85
  ~ packages/kg-ops/src/custody.ts + admission/custody-supabase.ts   report-body/ledger kinds; wired; bucket              B2
  ~ apps/executor/src/{auth,app}.ts        per-invocation credential verification (ADR 0005 §55 implemented)              OC-D84
  (schema: biotech-meta release v2.1 -> pinned here; see §7 B)

aiengineer/ai-engineer-db-contract/
  + supabase/migrations/<ts>_origin_structure.sql ... (see §7 A)

platform/mission-control/
  src/mission_control/
  + domain/knowledge/{origin,handles,lineage}.py
  + domain/outputs/{submission,guarantees}.py
  + application/knowledge/{gateway,toolset}.py
  + application/outputs/{submission_service,acceptance}.py
  + application/context/{source_bindings,resolution,representation,delivery}.py
  + application/ports/application_storage.py
  ~ application/authoring/manifest_launch_inputs.py     per-attempt coordinates; obligations compile; no output_refs prompt   fix
  ~ application/programs/{goal_directed,service}.py     rebind refreshes coordinates; read submissions not output_refs        OC-D83
  ~ domain/programs/{interpreter,goal_directed}.py      output_refs union removed; current set from accepted submissions      OC-D83
  + adapters/deep_agents/knowledge_tools.py
  ~ adapters/deep_agents/{adapter,materializer}.py      submit_output tool; readability probe; readiness; reload after compaction
  + adapters/postgres/knowledge/{operations,lineage,bindings,observations,submissions,transfers}.py
  ~ bootstrap/composition.py                            extension registry; credential minting per application binding
  + integrations/knowledge_extensions/report_package.py   ONE extension, two bindings
  ~ integrations/biotech/...knowledge/adapter.py        becomes a thin client of the protocol (OperationContext -> OriginEnvelope)
  packages/mission-control-db-contract/component/migrations/
  + 0050_knowledge_operations.sql ... 0054_transfer_plans_delivery_receipts.sql   release 1.4.5 (see §7 D)
  tests/
  + unit/domain/{knowledge,outputs}/test_*.py ; unit/application/{knowledge,outputs,context}/test_*.py
  + integration/knowledge/test_gateway_postgres.py ; integration/context/test_delivery_deep_agents_offline.py
  + acceptance/mission_control/test_report_and_assertions_goal_directed.py   (needs local PostgreSQL+Temporal)
```

## 4. Interfaces and contracts

Types show boundaries and the refusals an implementer must test. Names follow `GLOSSARY.md` where a
term exists; new terms are listed in §10.4.

### 4.0 Identities the whole design hangs on

```python
# domain/knowledge/origin.py  (accepted: OC-D79, D85, D87)
@dataclass(frozen=True)
class InvocationOrigin:
    """Who is calling, constructed by the host from the LIVE attempt; never from model JSON."""
    issuer: str                      # the MC installation's issuer id (ApplicationBinding.issuer)
    scope: RequestScope              # installation / application / tenant
    system: Literal["mission-control"]
    run_id: str
    mission_id: str
    activation_id: str
    attempt: int
    operation_id: str                # the unit's operation, not "manifest-template/..."
    invocation_id: str               # this harness execution
    parent_invocation_id: str | None # set for subordinates (ChildOrigin)

@dataclass(frozen=True)
class EffectKey:
    """Semantic effect identity: 'the world should contain this once'. Stable across retries."""
    value: str  # sha256(canonical{origin.scope, origin.operation_id, capability_pin, native_intent_digest})

@dataclass(frozen=True)
class QualifiedHandle:
    """Opaque to the agent; resolvable by exactly one binding. kh:<binding>/<kind>/<id>@<exact>"""
    binding: str          # "ai-engineer.research@1" | "biotech.reports@1" | ...
    native_kind: str      # "report_revision" | "Report" | "assertion_set" | "operation" ...
    native_id: str
    exact: NativeRevision | RetainedReadRef | ContentAddressedUid
```

Exactness per store: AI Engineer reports have an immutable `report_version_id` (**existing**, AIDB
`20260913010000:23-35,45`); Biotech reports are content-addressed by `uid = hash(reportKind, bodyDigest)`
and immutable by construction, superseded by a new uid (**existing**, BKS `proposals.ts:964-1014`). So
both carry a native exact revision; a retained read is needed only for traversal results and bounded
expansions, not for the report identity itself. This corrects the starter's `bks-snapshot-23` framing.

```typescript
// knowledge-operation-protocol/src/origin.ts  (accepted: OC-D84, D85)
export interface OriginEnvelope {
  issuer: string;                  // "self" for standalone
  system: string;                  // "mission-control" | "ks-verification" | "bks-local" | ...
  runId: string;
  missionId?: string; activationId?: string; attempt?: number;
  operationId?: string; invocationId?: string; parentInvocationId?: string;
  scope: { installationId: string; applicationId: string; tenantId: string };
}
export interface OriginCredentialClaims {   // JWT claims; verified against the issuer's JWKS
  iss: string; aud: string; exp: number; jti: string;
  origin: OriginEnvelope;                   // the authoritative copy
  grants: string[];                         // e.g. ["report.publish", "ingest.apply", "read.internal"]
}
export interface OperationEnvelope<Op> {
  schema: "knowledge-operation-envelope.v1";
  origin: OriginEnvelope;                   // must equal credential.origin or ORIGIN_MISMATCH
  effectKey?: string;                       // required for writes; minted by the caller (OC-D88)
  binding: string;                          // the application binding pin the caller used
  operation: Op;                            // native payload, bytes frozen by the caller
  nativeDigest: string;                     // digest over canonical(origin + operation)   (OC-D85)
}
export type Refusal =
  | { code: "ORIGIN_MISMATCH"; field: string }
  | { code: "ORIGIN_UNPROVEN"; hop: string }        // OC-D87
  | { code: "EFFECT_CONFLICT"; effectKey: string }   // same key, different digest
  | { code: "UNRESOLVED"; effectKey: string; lookup: string }
  | { code: "EXACT_REVISION_UNAVAILABLE"; handle: string }
  | { code: "GUARANTEE_UNSUPPORTED"; guarantee: string; binding: string };
```

### 4.1 The extension seam, both sides named (accepted OC-D65, D68, D97; proposed shape)

```text
MC core                            MC integration                      Knowledge Services (shared)        Store
-------                            --------------                      --------------------------        -----
ContentResolutionService           ReportPackageExtension(binding)     research-core via ports           research.* (PostgreSQL)
  uses ApplicationStoragePort  <-- one class, two instances  -------> bindings/aiengineer-postgres  --->  + orchestration.artifact bytes
                                                                       bindings/biotech-graph  -------->  Biotech executor -> Neo4j
                                                                         (intent-v2 / read-v2)             + content-addressed custody
```

There is **one** MC extension for evidence-backed reports because OC-D96 makes the read shape one
(`research-report.v2` package). What differs per binding is the protocol client, the custody client and
the declared guarantees from `describe`. A third application that binds the report core registers a
third instance, not a third class. Applications with other content (courses) register other
extensions against the same port.

```python
# application/ports/application_storage.py  (proposed)
class ApplicationStoragePort(Protocol):
    async def describe(self) -> SourceCapabilities: ...
    async def resolve(self, request: ResolveSelection, access: ScopedServiceAccess) -> SourceObservation: ...
    async def export(self, source: SourceObservation, request: ExportRequest, access: ScopedServiceAccess) -> RetainedRepresentation: ...
    async def resolve_lineage(self, operation: AdmittedOperationRef, access: ScopedServiceAccess) -> IngestionLineageResult: ...
    async def ensure_availability(self, source: SourceObservation, window: RecoveryWindow, access: ScopedServiceAccess) -> AvailabilityCommitment: ...

@dataclass(frozen=True)
class SourceCapabilities:
    report_package_read: bool            # research-report.v2 package by exact revision
    exact_revision: Literal["native_immutable", "retained_only"]
    body_custody: bool                   # exact body bytes retrievable by ref + digest
    ledger_custody: bool
    retained_read_by_ref: bool           # OC-D66 reuse without a fresh query
    consistency: Literal["snapshot", "read_committed_multi_statement", "graph_read_result"]
    lineage_by_effect_key: bool          # OC-D88
    export_profiles: tuple[str, ...]     # e.g. ("markdown@v2", "assertions-json@v2")

@dataclass(frozen=True)
class SourceObservation:
    subject: QualifiedHandle
    members: tuple[QualifiedHandle, ...]
    native_contract: PinnedNativeContract           # "research-report.v2" + binding guarantees
    read_observation: ReadObservationRef             # MC's own record of the admitted call
    native_read_receipt: str | None                  # if the surface supplies one
    retained_result: RetainedReadRef                 # exact bytes/manifest retained
    actual_consistency: NativeConsistencyFacts
    parts: tuple[ResolvedPart, ...]                  # body, assertions, evidence-index, ledger
    completeness: SelectionCompleteness
    availability: AvailabilityCommitment | None
```

### 4.2 Registration: application choices stay outside the core (proposed)

```python
# bootstrap/composition.py — deployment composition, pinned before admission
report_ext = lambda binding, app, audience: ReportPackageExtension(
    binding=binding,
    client=protocol_client(app, audience=audience),      # OperationEnvelope over the executor transport
    custody=custody_client(app),                          # S3-compatible; Supabase reference impl (DP-D1)
    core_pin=pin("research-report.v2"),
)
source_bindings.register("ai-engineer.research@1", application("ai-engineer"),
    extension=report_ext("ai-engineer.research@1", "ai-engineer", audience="ks-verification-executor"),
    required_facets=["report_package_read", "body_custody", "lineage_by_effect_key"])
source_bindings.register("biotech.reports@1", application("biotech"),
    extension=report_ext("biotech.reports@1", "biotech", audience="bks-executor"),
    required_facets=["report_package_read", "body_custody", "lineage_by_effect_key"])
# A required facet the binding's describe() does not confirm refuses admission of any manifest that names it.
```

The model cannot register modules, endpoints or credentials by naming them. `application IDs` are
registry entries (`application/installations/registry.py:58-200`, **existing**), not an enum.

### 4.3 AI Engineer binding: resolution to PostgreSQL

**Existing ingredients.** `report_get` reads the package as `pipeline_agent` in ~11 read-committed
statements and may return an unsealed package (KS `reports/service.ts:134-200`; `role-transaction.ts:52-56`).
Body bytes are artifacts in bucket `research-reports` with roles `structure|markdown|manifest`
(`service.ts:7,70-116`). **Target (A3 in §7):** `report_get` becomes the core's `ReportStore.readPackage`
under one `REPEATABLE READ` transaction, requires a seal for `exact=true`, and returns `research-report.v2`.

```python
class ReportPackageExtension(ApplicationStoragePort):          # ONE class; binding parameterizes it
    async def resolve(self, request, access):
        if isinstance(request.exact, RetainedReadRef):
            return await self.custody.read_verified_selection(request.exact, access)   # OC-D66 reuse
        envelope = self.client.envelope(                       # origin from access.origin, never from the agent
            origin=access.origin, binding=self.binding,
            operation={"op": "report_get", "revision": request.native_id, "require_sealed": True},
        )
        package = await self.client.call(envelope, access.credential)   # v2 package or typed refusal
        self.core.require_identity(package, request.native_id)           # revision == requested
        self.core.require_seal(package)                                   # custody conditions, not semantics
        parts = self.core.select_parts(package, request.selection)        # body | assertions | evidence_index | ledger
        body = await self.custody.get(parts.body.ref, access); verify_digest(body, parts.body.digest)
        retained = await self.custody.retain_selection(package, parts, body, access)   # MC-side exact copy or commitment
        return self.core.to_observation(request, package, retained, parts,
                                        consistency=package.consistency)   # "snapshot" after A3; truthful before
    async def export(self, source, request, access):
        if request.profile == "markdown@v2":                   # stored exact artifact, no regeneration (OC-D92)
            part = source.require_part("body", digest=request.required_source_digest)
            return await self.custody.retain_representation(part, source, request)
        return await self.renderers.pinned(request.profile).render(source, request.required_fields)
```

### 4.4 Biotech binding: resolution to Neo4j plus custody

**Existing ingredients.** read-v2 `report` takes only `reportUid` and returns report properties, cited
assertions/assessments, evidence locators, generating Activity, items and `sentenceTrace` (BKS
`typed.ts:192-212`; `read-v2.ts:124-125,248-265`); `persistSnapshot` writes a `bks-custody-snapshot.v1`
to file custody that cannot be re-read publicly (`read/service.ts:422-443`; `custody.ts:113-150`); there
is **no body custody** (`proposals.ts:968-974`). **Target (B2/B3 in §7):** `Report.bodyRef`/`ledgerRef`
into content-addressed custody, `GET /kg/custody/:ref`, and read-v2 `report` returning the v2 package
through `bindings/biotech-graph`.

The same `ReportPackageExtension.resolve` runs unchanged: `report_get` is dispatched by the protocol
client to the Biotech executor, where `bindings/biotech-graph.ReportStore.readPackage` does:

```typescript
// bindings/biotech-graph/src/report-store.ts  (proposed; runs inside the Biotech executor process)
async readPackage(req: { revision: string; requireSealed: boolean }, ctx: BoundOrigin): Promise<ReportPackageV2> {
  const read = await readV2(ctx.binding, { operations: [{ opId: "r", op: "report", reportUid: req.revision }],
                                          persistSnapshot: true, limits: ctx.limits });   // visibility-filtered traversal
  requireSuccessWithoutRequiredTruncation(read);
  const r = requireSingleReport(read.parts.r);
  const body = await custody.get(r.report.bodyRef); verifyDigest(body, r.report.bodyDigest);   // B2
  const ledger = r.report.ledgerRef ? await custody.get(r.report.ledgerRef) : null;
  return toPackageV2({ report: r, body, ledger,
    consistency: { kind: "graph_read_result", graphRevision: read.consistency.graphRevision,
                   readInterval: read.consistency.readInterval, snapshot: read.snapshot } });
}
```

Report identity is the uid (immutable); the traversal (cited assertions, evidence) is a recorded read
with graph revision and interval; the retained snapshot makes it reusable. A `bodyUri` never becomes a
permission to fetch an arbitrary URL: only `bodyRef` into the binding's custody resolves.

### 4.5 Same common result, native differences preserved

```yaml
ai_engineer_observation:
  subject: kh:ai-engineer.research@1/report_revision/01JB…@rev:01JB…
  native_contract: {schema: research-report.v2, consistency: snapshot, seal: required}
  parts: [{role: body, ref: ai-custody:sha256:…, digest: sha256:…},
          {role: assertions, ref: ai-custody:sha256:…, digest: sha256:…, count: 14},
          {role: evidence_index, handles: [kh:ai-engineer.research@1/locator/…, …]}]
biotech_observation:
  subject: kh:biotech.reports@1/Report/hu:report:7f3a…@uid
  native_contract: {schema: research-report.v2, consistency: graph_read_result, snapshot: rs-…}
  parts: [{role: body, ref: bks-custody:sha256:…, digest: sha256:…},
          {role: assertions, ref: bks-custody:sha256:…, digest: sha256:…, count: 9, graph_revision: 4412},
          {role: evidence_index, handles: [kh:biotech.reports@1/SourceLocator/…, …]}]
```

Both satisfy the same transfer requirement when exact content, proof, access and availability suffice;
the assessment mapping declares compatibility; stricter Biotech policy adds requirements, never a
separate MC algorithm (OC-D44, D75).

### 4.6 The reverse path: origin in, receipt out, lineage recorded

**Who constructs what**, in order:

| Step | Object | Constructed by |
| --- | --- | --- |
| 1 | `InvocationOrigin` | lane adapter at `prepare()`, per attempt, from the execution binding (fix: no template ids) |
| 2 | per-invocation credential (`OriginCredentialClaims`) | secret broker (ADR-0043) at materialization; audience = binding's executor |
| 3 | tool closure `knowledge_apply(binding, native_intent)` | `application/knowledge/toolset.py`; origin and credential in the closure |
| 4 | agent's native proposal (frozen bytes) | the model |
| 5 | `EffectKey` | `KnowledgeGateway` from origin, capability pin, native digest |
| 6 | `OperationEnvelope` + `nativeDigest` over origin+payload | `KnowledgeGateway` (bind before seal, OC-D85) |
| 7 | `knowledge_operation` row (state `dispatched`) | `adapters/postgres/knowledge/operations.py` |
| 8 | `BoundOrigin` | KS `knowledge-origin.bindOrigin(credential, envelope)`; refuses `ORIGIN_MISMATCH` |
| 9 | native plan / admission / apply, marker, receipt | the application binding's canonical writer (unchanged authority) |
| 10 | `OperationReceipt` (origin, effectKey, affected refs, per-item dispositions, native receipt id) | the service |
| 11 | observation update (state `settled` / `unresolved`), `content_lineage` facts (producer = origin; receipt) | `KnowledgeGateway` |
| 12 | handles returned to the agent | `KnowledgeGateway.agent_view(result)` |

```python
# application/knowledge/gateway.py  (proposed; accepted rules OC-D79, D85, D87, D88)
async def invoke(self, call: KnowledgeCall, origin: InvocationOrigin, credential: Credential) -> KnowledgeResult:
    binding = self.bindings.require(call.binding)                        # pinned by the execution binding
    proposal = freeze(call.native_payload)                               # agent bytes, never edited
    self.rules.refuse_if_payload_claims_other_origin(proposal, origin)   # ORIGIN_MISMATCH before anything
    effect_key = EffectKey.mint(origin, binding.capability_pin, proposal.digest) if call.is_write else None
    envelope = OperationEnvelope(origin=origin.as_envelope(), effect_key=effect_key, binding=binding.pin,
                                 operation=proposal, native_digest=digest(origin, proposal))
    op = await self.journal.dispatch(envelope, origin)                   # knowledge_operation row
    try:
        receipt = await self.client(binding).call(envelope, credential)
    except ResponseUncertain:
        receipt = await self.reconcile(binding, effect_key, credential)  # receipt_get(effect_key); may stay UNRESOLVED
    if receipt.unresolved:
        await self.journal.mark_unresolved(op, receipt.lookup)
        return KnowledgeResult.unresolved(handle=op.handle)              # agent sees an operation handle, no success
    await self.journal.settle(op, receipt)                               # idempotent by effect key
    await self.lineage.record(producer=origin, receipt=receipt, subjects=receipt.affected_handles)   # OC-D80
    return KnowledgeResult.ok(handles=receipt.affected_handles, operation=op.handle, items=receipt.items)
```

Service side, AI Engineer binding (inside the KS executor; the canonical writer is unchanged):

```typescript
async function applyIngestion(env: OperationEnvelope<IngestionIntentV1>, cred: Credential) {
  const origin = bindOrigin(cred, env);                 // JWKS(issuer), aud, exp, grants; ORIGIN_MISMATCH on disagreement
  const intent = freezeWithOrigin(env.operation, origin);   // origin inside the digest (OC-D85); no FK to orchestration (A1)
  return tx(origin.scope, async (db) => {
    const prior = await receipts.byEffectKey(db, origin.scope, env.effectKey);      // A2: effect_key unique per tenant
    if (prior) return prior.digest === intent.digest ? prior.receipt : refuse("EFFECT_CONFLICT");
    const plan = await planner.plan(db, intent);  await admission.require(db, plan, origin);
    const applied = await writer.apply(db, plan);                                    // research/evidence/corpus writes
    return receipts.write(db, { origin, effectKey: env.effectKey, intentDigest: intent.digest,
                                affectedRefs: applied.refs, items: plan.dispositions, nativeReceiptId: applied.receiptId });
  });
}
```

Biotech binding: the same `bindOrigin`, then `compile(intent-v2 with context.run = origin)`; the
Activity is found or created on `(tenantId, originIssuer, externalRunSystem, runId)` (B1), the marker is
`mk-sha256{scope, effectKey}` (**existing**, BKS `apply.ts:64-66`), marker and receipt commit together,
`unresolved` reconciles by effect key (**existing**, `apply.ts:404-501`). Nothing crosses PostgreSQL and
Neo4j in one transaction; MC settles its observation after the receipt.

```python
# domain/knowledge/lineage.py  (accepted OC-D80)
class ProvenanceRole(StrEnum):
    producer = "producer"      # first created the content (an origin, or "external" for pre-existing)
    caller = "caller"          # the invocation performing this operation
    receipt = "receipt"        # the native receipt proving the effect
    revision = "revision"      # the exact revision this fact is about
    adopter = "adopter"        # the obligation that selected existing content as its deliverable
    assessor = "assessor"      # who verified / assessed, under which method
    consumer = "consumer"      # the invocation that received it as input
# Invariants: adopting never writes producer; re-ingesting in another mission writes caller+receipt, not producer;
# cross-store identity joins only by (receipt | effect_key) and content digest (DP-D14).
```

### 4.7 From resolved content to the actual receiver (accepted OC-D92..94, D99)

```python
async def prepare_next(bindings, frontier, receiver, origin) -> ReadyInvocationInput:
    released = releases.select(bindings, frontier)                         # current set or explicit snapshot (OC-D49)
    sources = [await resolution.resolve(sel, origin) for sel in released]  # §4.1-4.4
    reps = [await representation.ensure(s, b.form) for s, b in zip(sources, released)]   # stored body | pinned renderer
    await availability.ensure(reps, bindings.recovery_window)              # commitment or block (OC-D59)
    checks = await acceptance.assessments_for(sources)                     # reuse applicable (OC-D73)
    plan = delivery.plan(inline=[state(frontier), assertions(reps)], files=[body_file(reps)],
                         index=mount_index(sources, reps), limits=bindings.limits, receiver=receiver.capabilities)
    delivery_receipt = await receiver.materialize_inputs(plan)             # upload + readability probe per file (OC-D94)
    ready = readiness.require(plan, delivery_receipt, access=await access.validate_now(plan))   # four checks (OC-D99)
    messages = composer.render(plan.inline, delivery_receipt.verified_index)
    return await transfers.record_ready(seal(plan, messages, delivery_receipt, ready))
```

### 4.8 Adding or changing an application

| Change | Extension / service work | MC core work |
| --- | --- | --- |
| Third application binds evidence-backed reports | Implement the six core ports for its store (a binding in KS, or its own executor speaking the protocol); register `ReportPackageExtension(binding)` | None |
| Application content that is not a report (a course) | New extension implementing `ApplicationStoragePort` for its content core; register | None |
| AI Engineer alters `research.*` | Migrate under its authority; bump `research-report.v2` binding guarantees or refuse | Compatibility admission refuses old pins |
| Biotech adds immutable report revisions beyond uid | Graph release; `describe().exact_revision` stays `native_immutable` | None |
| Stricter purpose policy | New assessment policy pin in the core | Enforce declared guarantees |

### 4.9 Verification core — Sprint V projection, 2026-10-24

The [Sprint V contract projection](SPRINT-V-DESIGN.md) supplies the detailed records, typed ports,
module IDs K01..K09/M01..M06, report compilation/census, one run/sealing authority, exact-use admission
and failure tests. Owner decisions [SV-D1..12](../answer-sets/sprint-v/codex-gpt-6-2026-10-24/ANSWERS.md)
choose a full refactor, both domains in the same sprint, BKS-owned versioned SDL and disposable current
data. The core remains reusable; AI Engineer's knowledge graph is PostgreSQL, Biotech's is Neo4j.

Key signatures: `VerificationStore.load/append/seal(scope, ...)`,
`EvidenceOracle.hydrate/admit(scope, ...)`, `ReportService.register/assess/derive(scope, ...)`,
`KnowledgeGateway.invoke(call, InvocationAccess)` and `.reconcile(effect, RecoveryAccess)`.
The detailed arguments, record bindings and refusals are in design §§3–5; implementation must use
the published wire schemas, not imports of Knowledge Services algorithms into Mission Control.

**Identity clarification proposed for §4.0/4.6:** keep originating origin inside frozen native bytes;
use a host-minted scoped effect key plus bound-effect digest for deduplication. Every retry authenticates
the current caller separately and requires exact-effect recovery authority if that caller differs.
Never rewrite the producer origin or remove it from the native digest to make retry work.

**Usage gate (SV-D12):** the direct pipeline and MC-port fixtures are disposable engineering proof.
Real research, ingestion, retrieval and retrieval experiments wait for all workflow systems, output
contracts/context transfer and full Deep Agents qualification. Sprint V completion does not open it.

## 5. Dependency chain

```text
Knowledge Services
  contracts ◄── knowledge-operation-protocol ◄── research-core ◄── bindings/aiengineer-postgres
                                             ◄── research-core ◄── bindings/biotech-graph ──► (HTTP/MCP) Biotech executor
  application ◄── host / verification-executor / worker       (executors depend on core + one or both bindings)
  Biotech executor (BKS repo) ◄── knowledge-operation-protocol (consumes the contracts package; owns kg-ops)

Mission Control
  interfaces/http, mcp, cli
    └─► application/{knowledge,outputs,context}/*            (interfaces call application)
          ├─► domain/{knowledge,outputs,context}/*             (pure rules)
          └─► ports: ApplicationStoragePort, KnowledgeProtocolClient, Custody, LaneInputMaterializer, repositories
  integrations/knowledge_extensions/report_package.py ──implements──► ApplicationStoragePort
  adapters/deep_agents/{knowledge_tools,materializer}.py ──implements──► LaneInputMaterializer, tool projection
  adapters/postgres/knowledge/* ──implements──► repositories
  bootstrap/composition.py wires bindings, extensions, credential minting
  domain/* imports stdlib, pydantic, mission_control.domain only
```

Data direction is bidirectional; authority is not: the application owns canonical content, native
validation, transaction and receipt; Mission Control owns obligations, observations, lineage facts,
transfer plans and receipts; the lane owns delivery mechanics.

## 6. Worked GoalDirected sequence

### 6.1 Authoring (proposed notation; pins resolve at admission)

```yaml
goal: compare the evidence for a company's technical claim
binding: biotech.reports@1                      # or ai-engineer.research@1; nothing else changes
obligations:
  assertions: {contract: research.assertion-set@v2, min: 1}
  report:     {contract: research.evidence-report@v2, min: 1,
               guarantees: [shape, provenance, coherence, coverage(questions: declared), ingested]}
next_input:                                      # transfer profile report-review@v1 (OC-D93/94)
  report:     {form: sandbox_file, representation: markdown@v2}
  assertions: {form: inline, selection: accepted}
  evidence:   {form: handles, expansion: cited}
```

### 6.2 What the agent is told and gets

Tools: `knowledge_read`, `knowledge_apply`, `report_publish` (for the binding), the filesystem tools,
and `submit_output`. Instruction segment (generated): "Write the report to `/outputs/report/`. Publish
it with `report_publish`; it returns a handle. When done, call `submit_output` once per obligation with
the file path and/or handles. Do not put refs in your final message." No origin, mission id or table is
mentioned.

### 6.3 The chain, every object and its constructor

| # | Stage | Object | Constructed by | Store |
| --- | --- | --- | --- | --- |
| 1 | goal obligation | compiled obligations + guarantees + transfer profile | manifest compiler | execution binding |
| 2 | agent task/tools | `InvocationOrigin`, credential, toolset, `/outputs/report/` slot | lane adapter `prepare()` | `environment_materialized` frame |
| 3 | domain proposal | native report (v2 shape) + assertion proposals | the model | agent files / tool args |
| 4 | trusted operation origin | `OperationEnvelope` with origin, effect key, native digest | `KnowledgeGateway` | `knowledge_operation` (dispatched) |
| 5 | sealed native intent | `BoundOrigin` + frozen intent (origin inside digest) | KS `bindOrigin` + core | native intent artifact |
| 6 | plan / admission / apply | plan, grants check, canonical write, marker | application binding | `research.*` or Neo4j |
| 7 | native receipt + affected refs | `OperationReceipt {origin, effectKey, affected, items}` | the service | native receipt table / marker |
| 8 | MC observation | `knowledge_operation` settled; `content_lineage` producer+receipt facts | gateway journal | 1.4.5 tables |
| 9 | agent final selection | `submit_output("report", {file: "/outputs/report/report.md", handles: ["kh:…Report…@uid"]})`; `submit_output("assertions", {handles: ["kh:…/assertion_set/…"]})` | the model, through the tool | `submission` rows |
| 10 | candidate reconciliation | `CandidateSet` (file candidate + native report; lineage check that the report was registered from that file digest, OC-D90) | `SubmissionService.finalize` | `workspace_candidate_descriptor` + `submission` |
| 11 | assessments / fulfilment | five assessment records; `FulfilmentDecision` | `OutputAcceptance` | assessment + fulfilment rows |
| 12 | transfer selection | released current set at the frontier | `releases.select` | transfer plan |
| 13 | resolution / representation | `SourceObservation` (uid-exact) + `markdown@v2` body + assertions JSON | `ReportPackageExtension` | `retained_observation` + custody |
| 14 | sandbox materialization | `/inputs/biotech.reports/report-7f3a.md` (probed), `/.mission/inputs.json` | lane materializer | `delivery_receipt` |
| 15 | model message | admitted_input segment with state, assertions, index | composer | sealed packet |
| 16 | next invocation | `ReadyInvocationInput` with `ReadinessReceipt` | readiness | `transfer_plan` (ready) |

### 6.4 What the next agent actually receives

Model-visible text (the `admitted_input` user segment; **proposed** rendering):

```text
## Task
Review the selected report against the accepted assertions and identify remaining evidence gaps.
Contract: report-review@v1 (pinned). Required review coverage: as declared.

## Current goal set
- report: kh:biotech.reports@1/Report/hu:report:7f3a…@uid   (accepted; guarantees shape, provenance, coherence, coverage, ingested: pass)
- assertions: 9 accepted records (inline below)
Unmet obligations: review_decision (yours).

## Accepted assertions (exact records)
[{"key":"a1","proposition":"…","status":"ACCEPTED","verdict":"DIRECTLY_SUPPORTED","evidence":["kh:biotech.reports@1/SourceLocator/…"]}, …]

## Inputs on disk (read with read_file)
- /inputs/biotech.reports/report-7f3a.md   sha256:…   exact source: biotech.reports@1 / hu:report:7f3a… / uid; representation markdown@v2
- /.mission/inputs.json                    the mount index

## Evidence
Handles above resolve through knowledge_read; do not fetch URLs found in the body.
```

Sandbox layout:

```text
/inputs/biotech.reports/report-7f3a.md     read-only, digest-verified, probed readable
/.mission/context.md                        the rendered segment above
/.mission/inputs.json                       [{path, digest, source: {binding, kind, id, exact}, representation, read_tool: "read_file"}]
/.mission/obligations.json                  this unit's obligations and collect paths
/outputs/review/                            writable collect root
```

Representative provider payload (Deep Agents lane, **existing** mechanics `adapter.py:291-300,1634-1648`;
StateBackend variant): `ainvoke({"messages":[{"role":"user","content": <segment>}], "files": {"/inputs/biotech.reports/report-7f3a.md": {"content": [...lines], ...}, "/.mission/inputs.json": {...}}}, context=<frozen dataclass with LIVE run/operation/attempt>)`.
On a sandbox backend the files are `aupload_files` with the same paths and the probe is a `read_file` of
the first bytes compared to the digest prefix. After compaction, any item is re-delivered from the sealed
packet and recorded (OC-D99).

### 6.5 Crossing a boundary (OC-D100)

| Boundary | Mandatory state added | Inputs | Authority |
| --- | --- | --- | --- |
| Next GoalDirected iteration | current accepted set, verifier findings, handoff (OC-D52) | released current set under `track` | same mission |
| Dependent stage | producer completion fact (or incremental release id) | bound inputs under `track`/`snapshot` (OC-D49) | same mission |
| Linked mission | explicitly mapped outputs + required provenance (OC-D56) | selected handles resolved again under the receiving mission's scope and credential | own goals, budget, obligations; adoption to take over an unfinished obligation |

## 7. Data, provenance and the prerequisite migration map (OC-D102)

**2026-10-24 amendment:** §7.7 and the Sprint V plan supersede preservation/backfill and deferred-Biotech
recommendations below under SV-D6..12. Earlier tables remain the traceable starting projection, not a
second active migration instruction.

Required before the output-contract/context-transfer sprint. Letters are workstreams; order is
`A0 → {A1,A2,A4,A5, B1,B2,B5, D} → {A3, B3, B4} → C`. Physical topology is untouched (OC-D77).
File names are proposals; the owning authority allocates them. Dates `<ts>` are `YYYYMMDDHHMMSS`.

### 7.1 A0 — AI Engineer authority housekeeping (blocking)

Eleven migrations `20260914010800 … 20261001170000` are untracked while consumers pin a vendored
tarball 0.4.16 (AIDB `git status`; KS `vendor/`). Commit and tag 0.4.16, regenerate `database.generated.ts`,
and pin KS to the git commit as the contract's own `.gitignore` states. Readiness evidence: a fresh
install from git reproduces the workspace fingerprint in `workspace/manifest.json`.

### 7.2 A — AI Engineer DB contract (authority: `aiengineer/ai-engineer-db-contract`)

| Id | Migration (proposed) | Change | Backfill | Compatibility / recovery proof | Unblocks |
| --- | --- | --- | --- | --- | --- |
| A1 | `<ts>_origin_structure.sql` | type `knowledge.origin` (issuer, system, run_id, mission_ref, activation_ref, attempt, operation_ref, invocation_ref, parent_invocation_ref; all text, **no FK**) + `origin_digest`; columns on `orchestration.operation_intent`, `operation_receipt` (+ `tenant_id NOT NULL`), `evidence.claim` (`producer_origin NOT NULL`; `producer_attempt_id` becomes nullable native), `evidence.verification_run` (producer/judge origin), `research.report_package` (`producer_origin` replaces free text), `knowledge_service.operation` (origin replaces `ownership_mode`/`external_run_id`) | existing rows: `issuer='aiengineer'`, `system='ai-engineer'`, `run_id=attempt id`, mission/attempt refs from the FKs | old writer that omits origin refuses (`NOT NULL`); readers tolerate both; receipts for pre-migration intents remain attributable | OC-D79/D85; the first AI Engineer experiment |
| A2 | `<ts>_tenant_scoped_idempotency_and_effect_key.sql` | `operation_intent.idempotency_key` unique **per tenant**; `effect_key text` unique per tenant; index for `receipt_get(effect_key)` | none | duplicate detection unchanged for same-tenant replays; cross-tenant collisions become impossible | OC-D88 |
| A3 | `<ts>_research_report_v2.sql` | `report_package.schema_version='research-report.v2'`; `research.report_item`; assertion `status`/`verdict` from the lattice; artifact role `ledger`; seal guard includes ledger; read function `research.read_package(version)` for one-statement snapshot read | v1 packages re-projected by the core renderer (byte-identical body; derived ledger) | v1 rows readable through the v2 projection; `exact=true` requires seal | OC-D92/D96 |
| A4 | `<ts>_verification_run_manifest.sql` | `evidence.verification_run.manifest_digest`, `manifest_signature`, judge/producer origin; `research.report_assessment.verification_run_id NOT NULL` for new rows (trigger) | executor file-store runs imported once as rows with manifest digests | admission oracle switches to the row; file store becomes cache | OC-D91/D95 |
| A5 | `<ts>_submit_intent_tenant_scope.sql` | `api.submit_intent` tenant-scoped lookup, explicit `tenant_id`, `REVOKE EXECUTE FROM anon, authenticated` (security finding, AIDB `20260826001500:266-319`) | none | callers must present tenant | hygiene |

### 7.3 B — Biotech graph (authority: `biotech-meta` upstream; pinned release here, v2.0.2 → v2.1.0)

Precondition (BellLabs pathway step 2): locate the authoring source; `biotech-meta` is absent locally
and the pin records `biotechMetaReleaseDirClean:false`.

| Id | Release change (proposed) | Change | Backfill | Proof | Unblocks |
| --- | --- | --- | --- | --- | --- |
| B1 | DDL `activity_origin` | `Activity.tenantId`, `originIssuer`, `invocationIds[]`; uniqueness `(tenantId, originIssuer, externalRunSystem, runId)`; compile compares `missionId` on later intents (warning → refusal) | existing Activities: `originIssuer='self'`, tenant from the writer scope | old intents without issuer map to `self`; new MC intents require credential | OC-D79/D85 |
| B2 | custody `report-body`, `report-ledger` kinds; `Report.bodyRef`, `ledgerRef`; `GET /kg/custody/:ref`; Supabase bucket created and wired as default | `custodyArtifactDigest` honoured on snapshots | none (new reports only; old reports keep `bodyDigest` without bytes, labelled `body_unavailable`) | export of a pre-B2 report refuses honestly | OC-D92; the Biotech experiment |
| B3 | `report.publish` fields: items cite assessments, `bodyStart/EndOffset`, `citationCompleteness`, `blockedBy`; the three counts settable | none | v2 package parity with AI Engineer | OC-D96 |
| B4 | `Assessment.rubricVersion`, `policyVersion`; `propositionHash` formula aligned with SDL (recorded drift) | hash recomputed for existing Claims under a new property, old kept | both hashes queryable until cut-over | OC-D95 |
| B5 | executor auth: per-invocation credential (ADR 0005 §55) alongside static tokens; `bindOrigin` | none | static tokens remain for standalone | OC-D84 |

### 7.4 C — shared Knowledge Services (code and contracts; no database authority)

Protocol package; `research-core`; `bindings/`; one sealer and oracle; `receipt_get(effect_key)`;
`research-report.v2`; executor envelope and credential verification; `ReportIntent` retired. Proof:
conformance tests of both bindings against the same core fixtures; the owner's "tidy the worktrees"
happens here.

### 7.5 D — Mission Control common release 1.4.5 (authority: `packages/mission-control-db-contract`)

| Migration (proposed) | Table | Key columns |
| --- | --- | --- |
| `0050_knowledge_operations.sql` | `knowledge_operation` | scope, run/activation/attempt/operation/invocation, binding_pin, capability_pin, effect_key (unique per scope), native_digest, state (`dispatched|settled|unresolved|refused`), receipt_ref, receipt_digest, affected_handles[], items jsonb, created/settled_at; immutable settlement |
| `0051_content_lineage.sql` | `content_lineage` | subject_handle, role (`producer|caller|receipt|revision|adopter|assessor|consumer`), actor_ref (origin or obligation or assessment), fact jsonb, recorded_at; append-only; no `produced_by` on adoption (trigger) |
| `0052_source_bindings_retained_observations.sql` | `source_binding`, `retained_observation` | binding_pin, application, extension_pin, facets jsonb, admitted_at; observation: subject_handle, binding_pin, native_contract, read_observation_ref, retained_ref, digest, consistency jsonb, availability jsonb, invalidated_at |
| `0053_submissions.sql` | `submission` | run/activation/attempt/invocation, obligation, selection jsonb (paths, handles), resolved jsonb (completed coordinates, who completed), status (`registered|refused|auto_finalized`), submission_ref; idempotent by (invocation, obligation, n) |
| `0054_transfer_plans_delivery_receipts.sql` | `transfer_plan`, `delivery_receipt` | boundary, source/target coordinates, effective settings, plan_digest, state; receipt: plan_ref, receiver invocation, per-item path/digest/probe result, access validation, readiness jsonb |

Overlaps to settle in the final interview: OC-D6's `obligation_fulfillment` (one row per obligation per
unit result) versus `submission` here (one row per act); `context_selection`/`packet_key`
(**existing**, `0027_provider_frames.sql:247`) versus `transfer_plan`. Code change in the same release:
per-attempt refresh of `cognitive_context_values` (**existing defect**, `manifest_launch_inputs.py:2112-2120`;
`goal_directed.py:1561-1596`; `service.py:1801-1821`), and frames that carry origin, handles and receipt
refs (the owner's tracing housekeeping).

### 7.6 What each step unblocks

- After A0, A1, A2, D and the minimal C (protocol + postgres binding + `receipt_get`): the AI Engineer
  experiment research → assertions → report → ingest → exact retrieval → next agent, with coherence and
  ingestion guarantees; coverage limited to declared assertions until A4.
- After B1, B2, B5: the same experiment on Biotech.
- After A3, A4, B3, B4, full C: the five guarantees on both; assessment reuse across consumers.

### 7.7 Sprint V clean target and exact file reservations

Use [SPRINT-V-PLAN.md §3](../sessions/SPRINT-V-PLAN.md#3-migration-and-version-authority) as the current migration map.
Shared operational SQL is authored once in the proposed KS common component:
`0001_verification_foundation.sql`, `0002_observations_reports_and_custody.sql`,
`0003_admission_revocation_and_outbox.sql` (W1/W2). AIDB owns consumer/domain bindings:
`20261024010000_knowledge_component_binding.sql` (W1),
`20261024010100_research_report_v2_projection.sql` (W2). D retains 0050..0054 reservations for W4;
component version follows the actual breaking-change policy after reconciling stale release source.

BKS owns `schema/source/biotech-schema-v2.1.0/` and generates/verifies/pins its next SDL release (W3).
An incompatible schema must use an explicit major version. Full V07/V08 integration is in this sprint.
The versioned SDL already exists; only its historical authoring checkout was absent. No legacy-data
import, dual writer or old-client compatibility requirement survives SV-D8/SV-D11. These exact names
are reserved proposals until the owning implementation cell claims them against live state.

## 8. Failure examples and test seams

Each row: state, repair/block, residual agent responsibility, seam and test (file names proposed).

| Example | State | Repair / block | Residual agent duty | Seam → test |
| --- | --- | --- | --- | --- |
| Pre-existing report, no new ingestion | `adopter` fact only; producer = external | none; `ingested` guarantee satisfied by existing receipt lineage if present, else unfulfilled | name the handle in `submit_output` | `lineage.add` → `tests/unit/domain/knowledge/test_lineage.py::test_adoption_never_writes_producer` |
| Omitted final refs | required obligation unsubmitted at finish | one reminder; auto-finalize if single candidate/receipt matches; else one repair turn; then block | respond to the reminder | `SubmissionService.finalize` → `test_submission_service.py::test_auto_finalize_single_match_only` |
| Wrong / foreign ref | `submission.status=refused` (`out_of_scope` / `unresolvable` / `ambiguous`) | typed refusal returned; one repair turn | correct the ref | `Selection.resolve` → `test_submission.py::test_bare_id_requires_single_binding` |
| File and native report disagree | two subjects; no lineage edge | repair turn naming the mismatch; `ingested` unfulfilled | republish or resubmit | `reconcile` → `test_submission.py::test_file_and_report_distinct_until_lineage` |
| Host origin differs from payload | `ORIGIN_MISMATCH` before plan | refuse; both versions retained | none (agent cannot fix origin) | gateway → `test_gateway.py::test_payload_origin_conflict_refuses` |
| Native commit, response lost | `knowledge_operation.state=unresolved` | `receipt_get(effect_key)`; settle or stay unresolved; never a second write | wait for handle | gateway + fake service → `test_gateway.py::test_lost_response_reconciles_by_effect_key` |
| Partial native receipt | items `applied|held|rejected` | usable members qualify only under an authored subset policy | address held items | `guarantees.evaluate` → `test_guarantees.py::test_partial_receipt_never_whole_success` |
| Missing exact revision | `EXACT_REVISION_UNAVAILABLE` | allowed retained read or block; never current data silently | none | extension → `test_report_package_extension.py::test_exact_revision_unavailable_blocks` |
| Required binary on text-only backend | materializer refusal | authored alternative or block | none | materializer → `test_materializer.py::test_binary_on_statebackend_refuses` |
| Context budget overflow | plan rejected | authored repair (file instead of inline where allowed) then block | none | `DeliveryPlanner` → `test_delivery.py::test_inline_required_over_budget_blocks` |
| Crash between upload and dispatch | plan `delivering`, no readiness | reconcile destination by plan digest; re-probe; persist ready; retry | none | readiness → `test_delivery_deep_agents_offline.py::test_crash_after_upload_reconciles` |
| Later revision of tracked source | `retained_observation` unchanged; consumer marked stale | explicit refresh = new observation (OC-D49/D66) | none | releases → `test_releases.py::test_refresh_creates_new_observation` |
| Child hop cannot carry proof | `ORIGIN_UNPROVEN` | effect recorded as standalone; cannot fulfil | use an admitted child | subordinate origin → `test_origin.py::test_child_origin_requires_parent_invocation` |
| Schema changes under a pinned mapping | `describe` mismatch | admission refuses binding | none | registry → `test_source_bindings.py::test_missing_facet_refuses` |

Pure fake-port tests prove rules; real local PostgreSQL proves the 1.4.5 tables and replay; the KS
conformance suite proves both bindings; provider realization is proven offline first (QR-1).

## 9. Receipts and observability

Operator traversal (all ids join without translation):

`mission/unit/invocation → knowledge_operation (effect_key) → native receipt (origin, affected) →
content_lineage (producer, receipt, revision) → submission → assessments → fulfilment → transfer_plan →
retained_observation → delivery_receipt (path, digest, probe) → ReadyInvocationInput → next invocation`.

Inspection example (the four questions):

```text
$ missionctl knowledge trace kh:biotech.reports@1/Report/hu:report:7f3a…@uid
produced by   mission m-42 / unit research / attempt 2 / invocation inv-9c   (receipt rcpt-… effect ek-…)
ingested by   the same invocation (Biotech apply, graph revision 4412)
adopted by    mission m-57 obligation prior_report (no production claimed)
assessed by   verification run vr-… (manifest sha256:…) : shape, provenance, coherence, coverage(declared), ingested
received by   mission m-42 / unit review / attempt 1 as /inputs/biotech.reports/report-7f3a.md (sha256:…, probed ok)
```

Frames carry origin, handles and receipt refs (tracing housekeeping, OC-D102); they point to
authoritative rows and are never substitute domain proof.

## 10. Alternatives, assumptions, delta and frontier

### 10.1 Two designs for the hardest boundary (origin into ingestion)

| Design | Strength | Cost | Disposition |
| --- | --- | --- | --- |
| **KS-native Knowledge Operation Protocol, origin bound from a per-invocation credential** | Origin is authenticated where the write happens; standalone and mission paths are one protocol; both executors share it | A new contracts package; both executors change; application schemas gain origin (the migration the owner has accepted anyway) | **Chosen** (OC-D84, D85) |
| MC-side gateway with an external-origin envelope; services unchanged | No KS change now | Origin stays a claim on the service side; the AI Engineer FK problem is worked around by omission; two code paths for standalone vs mission | Rejected: fails OC-D79's "the service validates it" |

### 10.2 Design-it-twice note for the submission act

`submit_output` as the one act (chosen, OC-D83) versus the final structured message as declaration
(the starter's framing): the tool call is harness-completed, idempotent by `(invocation, obligation, n)`,
returns the durable ref, and keeps prose out of the kernel; the message form needs parsing, cannot be
answered to, and survives only as a claim. Kept here as the rejected alternative.

### 10.3 Assumptions (engineering, open)

| # | Assumption | Risk if wrong | Where it is tested |
| --- | --- | --- | --- |
| S1 | A per-invocation JWT (secret broker, ADR-0043) with the origin as a claim is acceptable to both executors' auth models | Biotech's static-token model and KS's shared bearer need a parallel verifier; B5 and C grow | B5, C auth tests |
| S2 | Biotech's content-addressed report uid is the right exact revision for `report` handles | If reports become mutable per uid, a retained read becomes mandatory | `describe().exact_revision` |
| S3 | One `ReportPackageExtension` suffices for both bindings once `research-report.v2` is the read shape | If Biotech cannot reach v2 parity (B3), a Biotech-specific subclass appears | KS conformance suite |
| S4 | The readability probe (`read_file` of a prefix) is available on every byte-capable backend | A backend without read-back needs a different probe | materializer tests per backend |
| S5 | `submission` and OC-D6 `obligation_fulfillment` can be one release | If kept separate, two writes in the settlement transaction | final interview |
| S6 | The 1.4.5 tables fit the common component without per-application variation | A Biotech-specific column would violate ADR-0002 | release authority tests |

### 10.4 Glossary candidates (through `domain-modeling`)

Invocation Origin; Knowledge Operation; Qualified Handle; Submission (the act); Provenance Role;
Source Binding; Retained Observation; Step Contract; Report Core (`research-report.v2`); Readiness
Receipt. Resolved definitions are written to `GLOSSARY.md` at conversion.

### 10.5 Delta map to the accepted checkpoint

| Checkpoint item | Disposition | By |
| --- | --- | --- |
| CONTRACTS §2 identities, digests, `SubjectRef` | retained | - |
| CONTRACTS §3 output records (`mc.output_contract.v1`, obligation, submission/revision) | retained; `submission` record now = the `submit_output` act | OC-D83 |
| CONTRACTS §6.1 adapter operations (`describe/resolve/export/ensure_availability/read_representation/resolve_ingestion_lineage`) | refined into `ApplicationStoragePort` (§4.1) with **one** `ReportPackageExtension` | OC-D96/D97 |
| CONTRACTS §6.2/6.3 transfer, lifecycle, receipts | retained; `boundary` enum and readiness receipt added | OC-D99/D100 |
| CONTRACTS §9.2 example `revision: revision_7` for Biotech | revised: exactness is the content-addressed uid | §4.0 |
| CONTRACTS §10 failure matrix | retained; §8 adds origin, submission and hop rows | - |
| SP-04 OC-D4/D5 (registered candidates; two channels; final message is a claim) | revised wording: one act plus degraded file channel; final message not read | OC-D83 |
| WORK-ITEMS AC-1 (typed selectors) | retained | - |
| AC-2 (adapter registry) | refined: `SourceBindingRegistry` with facets | - |
| AC-3 (retained observations) | retained; table `retained_observation` (D) | - |
| AC-4 (representations) | retained; stored-artifact mode first | OC-D92 |
| AC-5 (sealed transfer plans) | retained; readiness receipt added | OC-D99 |
| AC-6 (receipt-backed lineage) | refined: seven roles, `content_lineage` (D) | OC-D80 |
| OO-1..9 | retained; OO-2 now writes `submission`; OO-3 the five guarantees | OC-D83/D91 |
| QR-1 | retained | - |
| QA-1 (bind actual services) | **split** into the migration letters A0/A/B/C and a per-binding proof | OC-D102 |
| DP-D3/D5/D6/D14 (open proposals) | consistent with and consumed by OC-D83/D89/D80; the final interview can mark them decided | - |
| New (not in checkpoint) | Knowledge Operation Protocol; `research-core`; VerificationRun; step contracts; migration programme; `knowledge_operation`, `content_lineage`, `source_binding`, `submission` tables | OC-D84..98, D102 |
| Deferred, unchanged | physical topology (OC-D77); subagent tools/shape (OC-D71) | - |

### 10.6 Frontier for the final output-contract/context-transfer interview

1. Table consolidation: `submission` vs `obligation_fulfillment` (OC-D6); `transfer_plan` vs
   `context_selection`; `domain_effect` kind (DP-D4) vs step outputs (OC-D98).
2. Output-contract modelling the port needs (owner's "output contracts modeling ?"): kind set (OC-D2)
   versus forms (CONTRACTS §3.1); obligation templates (OC-D19); enforcement levels (OC-D3).
3. CS-D1..14 and the transfer profile fields; `report-review@v1` as the first profile.
4. Accumulation across cycles/iterations against `submission` rows (OC-D45..48 mechanics).
5. Tracing housekeeping items: which frames carry origin, handles, receipt refs, readiness.
6. Issue breakdown: one `OVE` issue per migration letter (A0, A1..A5, B1..B5, C parts, D) plus the
   runtime items, with the prerequisite ones separated.
7. The "other MC table modeling I surely missed" review: a pass over §7.5 against DP-D1..14 and HG-D1..24.
