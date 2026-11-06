---
type: Specification Supplement
title: "Four states, one bridge: how missions relate to application knowledge, what inner agents owe Mission Control, and what a point must answer (supplement to the output-contracts specification)"
description: "Supplement to SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md written 2026-10-23 from the owner's architecture call. Answers four questions with cited state: how Mission Control serves any application (two Postgres databases, an S3-compatible bucket, the Application Binding); which of agent state, sandbox state, mission state and application entity state is authoritative and how the receipt bridges the last two in both directions; whether inner-mission agents write to Mission Control (never a table; two harness-completed acts); and what an operator inspects at a cognition point and how often the sandbox is snapshotted. Adds the domain output family (`domain_effect`), the provenance walk for a mission that produced entities, sources, chunks, embeddings and reports, the snapshot trigger set, decisions DP-D1..DP-D14 and the interview rounds RA and RD."
tags: [mission-control, providers, consolidation, deep-agents, supplement, provenance, knowledge-services, output-contracts, domain-effect, snapshots, state-as-of, application-binding, P1]
companion: SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md
status: archived
archived: 2026-11-02
archived_from: providers/deep_agents/DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md
archived_reason: "disposed in Sprint OC DECISIONS (PR-03)"
---

> **Archived 2026-11-02** (disposed in Sprint OC DECISIONS (PR-03)). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Four states, one bridge

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../sessions/KICKOFF.md); no new interview or runtime completion is implied.


**IQ-07 disposition, 2026-10-26.** Owner quotations, dated audits and original recommendations
below remain history. Current target behavior follows the [accepted answers](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md)
and [integrated contract](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md).
Local notices below supersede conflicting rules; the original “nothing decided” status describes
2026-10-23 only. Final integrated confirmation and conversion remain pending. Proposed syntax,
snapshot policies and historical proof are not implementation evidence for the new version.

**Status.** Proposal, 2026-10-23, for the owner to settle through interview rounds RA and RD
(§8), which the [sprint sequence](SPRINT-SEQUENCE-2026-10-23.md) places in sitting I and
sitting II. Nothing here is decided and nothing was built. It extends the companion
[output-contracts specification](../specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md) (cited
**OC §x**, decisions OC-D1..D26) with one output family and the provenance it needs, and the
[tracing proposal](TRACING-PROPOSAL.md) (cited **TR**) with the snapshot trigger set and the
three-facet point read. The [human review gates supplement](../../../proposals-2026-10/HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md)
at the platform root is its sibling.

**Labels.** **[T]** a named test exists. **[I]** implemented, unproven live. **[D]** documented or
specified only. **[P]** proposed here. Paths without a prefix are under `src/mission_control/`;
`bks/` means `biotech/biotech-knowledge-services/`.

## 0. The owner's call (verbatim, 2026-10-23)

> *"Mission control needs to work with any application which means any two postgres databases
> (one for mission control one for langgraph persistence) and the blob buckets (right now they
> are in supabase. We can just cement supabase as the extensible architecture)."*

> *"I suspect that the output contract obligations will serve in part as a way to 'generalize'
> and make mission 'writing' (by that I mean writing to the tables) accurate, reliable and fully
> functional for any application. [...] Effectively we need a way to write out a transcript and
> mission tables regardless of which application we extend from."*

> *"I'm pretty sure we want to avoid having inner-mission agents (meaning agents that run inside
> the workflow) having to write to mission control. Maybe we do want to give them some mission
> control responsibility. Maybe it's a hybrid effort. If it is a hybrid effort can we make the
> mission control writing responsibility a general contractual behavior of mission control
> itself?"*

> *"I am a bit confused about agent state + sandbox state + mission control state -> application
> specific entities relating to mission control."*

> *"Let's say a Report or a group of people or companies is researched and ingested in one
> application space (let's say biotech) -- well then how do we offer something automated or
> extensible that deterministically relates mission control to the entity. [...] I am thinking of
> something like PRODUCED_BY (extrapolate that to all storage models we use (sql, cypher)). Do we
> need some submission protocol / path?"*

> *"What would you WANT TO SEE? What you want to be able to retrieve from a mission? I suppose
> the most granular inspection scenario would be sandbox / filesystem state at time x + agent
> context at time x + mission table state at time x + previous if wanted + possible after [...] I
> wonder what frequency rate of snapshot in this manner would be good?"*

> *"What would a system want to see when some Stage Graph mission produced 30 companies 40
> executives 10 case trials all their relationships and embeddings plus ingested sources with
> chunks relating to structured entities plus some Evidence reports. One mission produced all of
> this. Let's say individual Stages produced the major outputs and there was one final synthesis
> node that looked for missing relationships and underwhelming outputs. [...] What would you want
> the mission control backend and the mission agents (the agents running inside the mission) to
> do so missions can relate to their outputs (the important possibly publishable and retrievable
> 'outputs')."*

## 1. The answers in brief

**Current revision.** ADR-0056 remains proposed. Host-owned persistence and service authority are
retained; “one output-submission act” does not forbid contracted progress notes or admitted native
operations. OC-D117 replaces the special `domain_effect` family with general step-output handles
and `effect_receipt` contracts. The original summary below does not override these distinctions.

1. **Inner agents never write a Mission Control table.** ADR-0056 decides it and OC §3.3 designs
   it. The hybrid the owner senses is real but it is not "the agent writes some rows": the agent
   decides *what* and *when*; the harness decides *how it is recorded*. Two agent-facing acts
   exist, both completed by the harness: submitting an output against a named obligation, and
   performing a domain write through an admitted capability.
2. **A submission protocol is needed and specified** (OC §3.3, two channels). What is missing is
   one more output family for application entities, `domain`, whose submission form is a receipt.
   That family is the generalization the owner is looking for: the mission tables are the same
   for every application; only the custody of a deliverable differs by kind.
3. **PRODUCED_BY is a receipt, not an edge an agent writes.** The bridge from Mission Control to
   any entity store is the effect receipt with its affected refs, landing in Mission Control as an
   external artifact that fulfills an obligation. The bridge back is the run identity the harness
   writes into every intent. Biotech already holds half of this (§3).
4. **The inspection unit is the cognition point, not a timestamp.** Snapshot frequency is a
   trigger set, not a rate. On the Deep Agents state backend the checkpoint already is the
   filesystem snapshot.

## 2. The four states and their authority

The owner's confusion comes from four states having different authority. ADR-0007 draws the
lines; this table names them for the next sprints.

| State | Where | Authority | Who writes it | Today |
| --- | --- | --- | --- | --- |
| Agent context | The LangGraph checkpointer: `langgraph_checkpoint_database_direct`, defaulting to the application DSN (`bootstrap/settings.py::langgraph_checkpoint_dsn`) | Recovery and fork only. Evidence, never authority | The lane runtime | [T] points, seed head, `state-as-of` |
| Sandbox or filesystem | The unit's workspace, or the `files` channel on the state backend | Scratch, until a file is registered by digest | The agent | [T] `files_digest` per step (`adapters/deep_agents/cognition_points.py::_files_digest`); `workspace_checkpoint_ref` on the result point only |
| Mission Control | The common schema in the application's Postgres; bytes in the S3-compatible bucket (`adapters/storage/artifact_payloads.py::S3ArtifactPayloadStore`) | The authoritative ledger: events, points, obligations, effects, artifacts | The harness and the settlement, in one transaction (TR P3.1) | [T] |
| Application entities | Neo4j for biotech, the domain Postgres for AI Engineer | Authoritative for the domain | Only the application's own executor, under an intent and a receipt (KNOWLEDGE-SERVICES.md, "PostgreSQL mission ledger and Neo4j never share one transaction") | [D] in the kernel; [T] in `bks/` |

Two rules follow and hold for every application: the kernel never writes entities, and the
domain executor never writes mission tables.

### 2.1 "Any application" is an Application Binding

The glossary already defines it: the immutable registry entry tying an application to its
installation, database, storage, auth issuers, Temporal queues and runtime persistence. Facts
that bound the design:

- `application_installation.supabase_project_ref` is `NOT NULL` in the foundation migration
  (`packages/mission-control-db-contract/component/migrations/0001_foundation.sql:125`). Supabase
  is already cemented at the installation row.
- The payload store speaks S3 (`S3ArtifactPayloadStore`); Supabase Storage is S3-compatible. The
  interface stays S3; Supabase is the reference implementation.
- The checkpoint DSN is a separate setting that defaults to the application DSN; the two
  databases may be one server or two.

So "work with any application" needs no new abstraction. It needs the binding documented as the
contract (RA.1) and the one output family below, so that what differs per application is the
custody of deliverables, never the mission tables.

## 3. The bridge: receipt out, run identity in

### 3.1 What biotech already holds

| Fact | Where | Label |
| --- | --- | --- |
| One `Activity` node per Mission Control run, unique on `(externalRunSystem, runId)`, accumulating intent, plan and receipt ids | `bks/schema/pinned/release/decisions/DECISIONS.md` OD-07; `COMPATIBILITY.md` `activity_run` | [T] |
| `Activity.generated` edges kept; `WAS_INFORMED_BY` chains runs; an `EVIDENCE_MISSION` Activity `ASSESSES` one Claim; the mission-start lineage intent must be trusted | OD-45, OD-06 | [T] |
| The intent carries `context.run {system, runId, missionId?, operationId?}` and `context.activityKind` | `bks/.agents/skills/biotech-kg-ingest/references/intent-v2-fields.md` | [T] |
| The receipt carries `activityUid`, `effect.effectKey`, `markerKey`, the complete declared `effects {nodes, relationships, total}`, prior and next graph revisions, a witness, and a paged `verify-effects` readback | `bks/packages/contracts/src/apply-v2.ts::IngestionReceiptV2`, `VerifyEffectsPage` | [T] |
| A source snapshot may carry `custodyArtifactDigest`: the digest of bytes held in Mission Control artifact custody; Chunks hang off snapshots with `CHUNK_OF`; embeddings are executor-written properties | `evidence-custody.md`; `ddl.json` `chunk_embedding`, `rel_CHUNK_OF_writer` | [T] |

The join between the two stores is therefore two keys that already exist: the run id and the
content digest. Nothing translates ids.

### 3.2 What Mission Control holds

**Current revision, OC-D79/84/85/87.** Live origin is bound by the receiving service using a
host-minted per-invocation credential before native intent canonicalization/sealing. A checkpoint
or model-supplied context field cannot authenticate origin. Required native schema changes remain
within the owning application's authority and are not prohibited by the earlier snapshot below.

| Fact | Where | Label |
| --- | --- | --- |
| `artifact.storage_kind IN ('object_store', 'external', 'inline_document')` with `external_issuer`, `external_ref` | `0004_capability_artifacts.sql:116-119` | [T] |
| `artifact_relation(source, target, relation_kind, producing_context_ref)`, immutable | `0004_capability_artifacts.sql:138-159` | [T] |
| The effect ledger: `effect_ledger_entry(run_key, effect_key, kind claim/observation/settlement, idempotency_key)`, immutable | `0010_run_control_support.sql:54-78` | [T] |
| Governed effect intents with `input_digest`, `policy_digest`, a human task and a closed state set | `0033_approvals_coordinator_inbox_lane_describes.sql:62-82` | [T] |
| Knowledge Services logical interfaces `knowledge.ingestion_apply` (returns an immutable domain receipt and affected refs), `receipt_get`, `verify_result`; `mc.knowledge_request.v1` wrapper | `mission-control-general/general-mission-control/expansion/KNOWLEDGE-SERVICES.md` (deleted 2026-11-01; last at `66185d2e`) | [D], nothing in `src/` |
| The context schema as the only run-identity source for Mission Control middleware | OC-D24 | [P] |

### 3.3 The two directions

**Current revision, OC-D79/80/83/89/117.** Native receipts are candidate evidence, not automatic
selection or fulfillment. Exact output submission or narrowly unambiguous attributable host
association enters the common protocol; declared guarantees and coverage still require evaluation.
Keep producer, caller, receipt, revision, adopter, assessor and consumer separate. Identity is not
established by a model-provided role, equal bytes or a filename.

- **Mission Control to entity.** The Knowledge Services adapter fills `context.run` from the
  context schema (OC-D24): run id, mission id, and the unit's operation id. The agent never types
  a run id. On the graph side this is PRODUCED_BY: the Activity for the run, `generated` edges,
  and the operation id on each receipt.
- **Entity to Mission Control.** The receipt becomes an `artifact` row: `storage_kind = external`,
  `external_issuer` = the capability pin, `external_ref` = the effect key, `kind = domain_effect`,
  `producer_point_ref` = the result point (OC §3.5), the receipt bytes in the bucket by digest for
  inspection, and one `artifact_relation` of `fulfills(<obligation>)`.

For SQL stores the same shape holds: Mission Control stores issuer, external ref and receipt
digest, never the entity. How the application stamps provenance on its side (a Cypher
relationship, a provenance column) is its own convention driven from the intent context. Both
directions are deterministic because the harness supplies both ends.

## 4. The domain output family

**Superseded family, OC-D117.** Use general forms with native-qualified references and effect
receipts. The table below is historical. Schema-fit review and necessary migrations are mandatory;
the old “no graph schema change” assumption is retired. Count distinct qualified deliverables or
entities and coverage, not summed duplicate/no-op/revised receipts. Native commit, required readback,
semantic assessment and current use eligibility remain separate proofs.

**Final interview revision, 2026-10-25 (OC-D117):** the special `domain_effect` kind proposed below
is retired in favor of general step-output handles with `effect_receipt` contracts. Exact admitted
operation, native results, receipt provenance, outcome and required readback checks are preserved.
Report production and use authorization do not prove a native commit. Historical proposal wording
below remains provenance; see [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md).

OC §3.2 has three families: knowledge (bytes in Mission Control custody), codebase (git custody)
and control. This supplement adds the fourth.

| Kind | Family | Submission form | Mechanical checks at the reducer | Default tier to a consumer |
| --- | --- | --- | --- | --- |
| `domain_effect` | domain | a receipt returned by the admitted capability the obligation names (`via: catalog://capabilities/<pin>`), with a declared side-effect class | the receipt resolves through `receipt_get`; `effect.scope` equals the unit's scope; the intent's `context.run` equals this unit (run id, operation id); affected refs non-empty unless `outcome: noop` is allowed; `verify_result` passes when the obligation declares `verify: readback`; a `partial` outcome is a shortfall unless `partial: accept` is authored | `reference`: effect key, activity uid, counts by node label and relationship type, the created subjects up to a cap with their types and names, and the readback handle |

Rules:

- **Auto-attribution by capability** (channel A's analogue for receipts). Every receipt that the
  named capability returns during the unit is a candidate of that obligation, registered by the
  harness at the tool-call boundary. `submit_output` is needed only to disambiguate when two
  domain obligations share one capability.
- **A domain write outside an admitted capability is not a deliverable.** It is an unattributed
  effect and a finding on the fulfillment report.
- **Granularity rides on the operation id.** One Activity per run stays (OD-07); each receipt's
  `context.run.operationId` resolves in Mission Control to the unit and the point. No graph schema
  change.
- **Accumulation is counted from receipts.** `accumulation: mission` with
  `cardinality {min: 25}` over `Company` nodes is a mechanical sum over receipts' declared
  effects. Whether the graph really holds them is `verify_result`, recorded as a separate
  verification fact, as KNOWLEDGE-SERVICES.md requires ("a pre-write snapshot cannot prove
  application").
- **Obligation templates per application.** "Biotech ingestion batch", "evidence report with graph
  claims": a template carries the capability pin, the verification choice and the transfer cap
  (OC-D19).
- **A thing in both stores joins by digest.** A report that is both a `document` deliverable and a
  graph `report` node carries the artifact digest in the proposal; an ingested source's snapshot
  carries `custodyArtifactDigest`.

## 5. The scenario, read back

**Historical illustration.** Read `domain_effect` examples as the retired proposed family, not an
accepted CLI/API. The current walkthrough is CONTRACTS §15, using exact references/effect receipts,
one submission protocol, separate fulfillment and current receiving readiness.

Thirty companies, forty executives, ten trials, their relationships and embeddings, eighteen
captured sources with chunks, four evidence reports, one synthesis stage. What the operator sees
with one command and no graph access:

```text
run outputs RUN
  S1 companies      domain_effect  receipt r1  applied   30 Company, 12 Organization, 61 rel     readback 103/103 ok
  S2 executives     domain_effect  receipt r2  applied   40 Person, 40 HOLDS_ROLE                 readback 80/80 ok
  S3 trials         domain_effect  receipt r3  partial   10 ClinicalTrial, 2 held                  readback 24/24 ok
  S3 sources        file_artifact  18 captures, 2 rendition-only (OD-08 warning)
  S4 evidence       document       4 reports, evidence_backed ok
  S5 synthesis      domain_effect  receipt r5  applied   12 rel, 3 held for review
  S5 synthesis      verdict        7 findings: 5 shortfall, 2 missing evidence
  mission           companies_covered  28/30 with >=1 evidence   (accumulation: mission)
```

Three drill-downs, each one hop:

| From | To | Through |
| --- | --- | --- |
| a deliverable | the point that produced it and the transcript around it | `artifact.producer_point_ref` (OC §3.5), `run transcript --by step --point` |
| a graph uid | the mission, unit and point | the receipt's `context.run.operationId` resolved in Mission Control |
| a Source in the graph | the bytes | the snapshot's `custodyArtifactDigest` is the artifact key in the bucket |

Mission-to-mission lineage: a chain link in Mission Control (ADR-0029) is the same fact as
`WAS_INFORMED_BY` in the graph. OD-06 requires the mission-start lineage intent to be trusted, so
the chain release writes it, never the agent (DP-D11).

### 5.1 What the backend does

**Current revision.** Bind service-authenticated origin before sealing. KS owns reusable report,
evidence, verification and permitted-use semantics; MC owns orchestration, waits and contract
fulfillment. Consumer contracts select exact representations under current grants/budgets. The
literal `knowledge.run_effects` interface, fixed subject cap and universal disposition ladder below
are unaccepted proposals. Submission, assessment, fulfillment, settlement, authorized use, native
commit/readback and publication are independent facts, not one automatic promotion sequence.

1. Fills `context.run` itself from the context schema, with the unit's operation id.
2. Registers every receipt of a named capability as a deliverable candidate at the tool-call
   boundary; promotes it to an external artifact with `fulfills` at acceptance (OC §3.5).
3. Projects an **effect summary per unit** from receipts: counts by label and relationship type,
   outcome, revisions, readback result. The mission database never queries the graph to render it.
4. Checks mission-level accumulation from receipts; records `verify_result` as a separate fact.
5. Transfers a domain deliverable as a reference carrying created subjects (capped) and the
   readback handle, so the next stage resolves with `mode: resolved` instead of minting duplicates
   (intent v2: "resolve before you create").
6. Gives the synthesis node one admitted read: the subgraph this run's Activity generated, bounded
   and paged (DP-D9).
7. Records a **disposition ladder** per deliverable: `submitted`, `fulfilled`, `verified`,
   `published`. Mission Control owns the first three; publication is the application's gate
   (biotech's SUPPORT and publication gates, OD-08) and Mission Control records its receipt.
8. Reconciles lost receipts by effect key and marker key (KNOWLEDGE-SERVICES.md step 6).

### 5.2 What the agents do

**Current revision, OC-D83/89.** Agents offer progressive/final candidates through `submit_output`;
submission is not needed only when a host is confused. Narrow host auto-association remains possible,
with exact attribution. Qualified degraded files use the same protocol. Admitted domain operations
and required progress notes are compatible with this single output-submission authority.

Four things, none a table write, none an id they invent:

- capture sources through a governed fetch tool that registers the artifact and returns the
  digest, then pass that digest as `custodyArtifactDigest`;
- write entities only through the ingest capability; the skill shapes subjects, proposals and
  evidence; the run context arrives filled in;
- write documents under `/outputs/<obligation>/`; a report that also becomes a graph node carries
  the artifact digest in its proposal;
- call `submit_output` only to disambiguate.

The synthesis agent additionally reads the run subgraph, proposes relationships as a normal
intent, holds anything doubtful with `hold`, and emits a `verdict` whose findings are typed per
obligation (OC §4.5 `Finding`). Those findings are what a cycling stage or a Review Gate receives
inline.

## 6. What a point answers, and when the sandbox is snapshotted

A point is a step boundary with a stable id, a parent, a frame range and a `files_digest`
(`domain/execution/cognition_points.py::CognitionPointRecord`). The owner's "time x" is a point.

| Facet | Today | Proposed |
| --- | --- | --- |
| Agent context at the point | `state-as-of` reads the checkpoint through the lane's `read_as_of` (`application/execution/cognition_point_reads.py`); the `model_request` frame body records what the model saw (ADR-0054) | unchanged; joined into one read |
| Filesystem at the point | state backend: the `files` channel is inside the checkpoint, so it is captured every step; sandbox and remote backends: `files_digest` every step, a full snapshot only at the result point (TR P1.3, TR-D8, K11) | snapshot on **triggers** (below) when the digest changed since the last snapshot |
| Mission tables at the point | events are append-only with ordinals; `unit_key` and `point_ref` on events and frames (TR-D7) | an **as-of projection**: events, fulfillment rows, effects and budget at the end of the point's frame range; a read, not storage |
| Before and after | `parent_point_id`, `parent_coordinate`; the proposed `transferred_from` and `transfer_plan_digest` on input points (OC §4.7) | unchanged; the read returns neighbours |

**The snapshot trigger set** (DP-D12), evaluated by the kernel, executed by the lane's snapshot
primitive: the result point; every `output_submitted`; every governed effect with an external
side-effect class; every transfer point T1 to T10; every Human Gate. Between triggers the frames
and the digest reconstruct what changed. Cost is proportional to meaning, not to wall-clock.

`run state-as-of RUN --point P` then returns the three facets and the neighbours in one document
(`mc.state_as_of.v2`, additive over v1).

## 7. Honest list

**Dated baseline.** The gaps below describe 2026-10-23. Sprint V and the current IQ-07 source audit
supersede that service inventory; the retired special-domain-family/sprint-K path is not the current
implementation plan. Retain unselected snapshot/as-of proposals without promoting them.

- No Neo4j writer, `knowledge.*` binding, `mc.knowledge_request.v1` wrapper or Knowledge Services
  capability exists in this repository (`docs/knowledge/knowledge-services.md`). The domain family
  lands as a kernel kind and is first proven against biotech's live executor
  (`bks/apps/executor`), which is sprint K in the sequence.
- A per-step sandbox snapshot on docker and remote backends is unbuilt (K11); the trigger set is
  the design for it, not a claim it exists.
- `evidence_backed` resolution against Knowledge Services evidence ids depends on the same
  binding (OC §10).
- The Activity's one-per-run rule is biotech's decision; another application may model provenance
  differently. Mission Control's side (external artifact, receipt, operation id) does not depend on
  it.
- The user-facing services the owner listed on 2026-10-23 (user services, content services,
  evidence and report services, the application and product APIs, the assistant's skills) are
  consumers of deliverables through the disposition ladder; their shape is round RS of the
  sequence, not this supplement.

## 8. Decisions (recommendation marked) and the interview rounds

**Current disposition of the original recommendations.** DP-D3/5/6/14 are refined by authenticated
origin, exact common submission, separate provenance roles and required schema-fit work
(OC-D79/80/83/85/89/117). DP-D4's special family is retired under OC-D117. DP-D9's literal interface
and DP-D10's fixed cap are not selected merely by accepting focused inspection. Other original
recommendations retain their independently recorded status; the RA/RD agenda below is historical,
not an instruction to re-ask settled decisions. Shared ports do not adopt cross-application linking.

| Id | Decision | Recommendation | Round |
| --- | --- | --- | --- |
| DP-D1 | "Any application" is the Application Binding (installation, two DSNs that may coincide, S3-compatible bucket, issuers, queues); Supabase is the reference implementation, the S3 store the interface. | **Adopt**; document the binding as a contract card. | RA.1 |
| DP-D2 | The four-state authority table of §2 becomes a knowledge concept and a GLOSSARY cross-reference; no new storage. | **Adopt.** | RA.2 |
| DP-D3 | Inner agents have exactly two Mission Control-facing acts: `submit_output` and a domain write through an admitted capability. No other agent-facing write surface is added. | **Adopt** (ADR-0056 extended). | RA.3 |
| DP-D4 | The `domain` family with one kind `domain_effect` whose submission form is a receipt (§4). | **Adopt** in the kernel kind set; proof in sprint K. | RD.1 |
| DP-D5 | Auto-attribution of receipts by the obligation's named capability; `submit_output` only to disambiguate. | **Adopt.** | RD.2 |
| DP-D6 | Provenance is harness-supplied in both directions: `context.run` from the context schema; receipts to external artifacts with `fulfills`. No agent-authored PRODUCED_BY. | **Adopt.** | RD.3 |
| DP-D7 | Stage granularity through `context.run.operationId`; one Activity per run stays. | **Adopt.** | RD.4 |
| DP-D8 | Effect summaries and accumulation checks derive from receipts only; `verify_result` is a separate verification fact. | **Adopt.** | RD.5 |
| DP-D9 | A run-scoped subgraph read is a required kernel logical interface (`knowledge.run_effects`), bound per application. | **Adopt**; biotech binds it to Activity-generated plus `verify-effects`. | RD.6 |
| DP-D10 | Domain deliverables transfer as references carrying created subjects (cap, default 200) and the readback handle. | **Adopt.** | RD.7 |
| DP-D11 | Deliverable disposition ladder `submitted / fulfilled / verified / published`; Mission Control never publishes; chain releases write the mission-start lineage intent. | **Adopt.** | RD.8 |
| DP-D12 | The snapshot trigger set of §6 as data beside the transfer heuristics; lanes implement the snapshot primitive; state backend needs none. | **Adopt.** | RA.4 |
| DP-D13 | `run state-as-of --point` returns the three facets and neighbours (`mc.state_as_of.v2`). | **Adopt** in sprint P. | RA.5 |
| DP-D14 | A thing present in two stores joins by content digest, never by id translation. | **Adopt** as a standing rule. | RD.3 |

### RA. Architecture and state (sitting I, after R0)

- **RA.1 (must)** DP-D1: the Application Binding as the contract for "any application", Supabase
  cemented, S3 the interface? Or (b) a provider-neutral storage abstraction beyond S3.
- **RA.2 (must)** DP-D2: confirm the four-state authority table in the owner's words.
- **RA.3 (must)** DP-D3: exactly two agent-facing acts? Or (b) also a `progress_note` tool in v1
  (TR P7, reserved), or (c) a general "record fact" tool (rejected by ADR-0056).
- **RA.4 (must)** DP-D12: the trigger set; add or drop triggers; the default cap on snapshot size.
- **RA.5 (can defer)** DP-D13: the three-facet read in sprint P, or later.

### RD. Domain provenance (sitting II, after R2)

- **RD.1 (must)** DP-D4: the `domain` family and `domain_effect` kind in the kernel set now, proven
  in K? Or (b) wait for Knowledge Services architecture.
- **RD.2 (must)** DP-D5: auto-attribution by capability.
- **RD.3 (must)** DP-D6 and DP-D14: harness-supplied provenance both ways; digest joins.
- **RD.4 (must)** DP-D7: operation id granularity; confirm with biotech's OD-07 owner (the same
  person).
- **RD.5 (must)** DP-D8: receipts are the source of summaries; graph truth is a separate fact.
- **RD.6 (must)** DP-D9: `knowledge.run_effects` as a kernel interface.
- **RD.7 (can defer)** DP-D10: the subjects cap.
- **RD.8 (must)** DP-D11: the disposition ladder and who publishes; chain lineage intent.

Restated mental model to confirm at the end of RD (PROCESS §1.2): *"After K, a biotech stage
declares `outputs: [{name: companies, kind: domain_effect, via: catalog://capabilities/biotech-kg-ingest@N}]`;
its agent calls the ingest tool; the harness fills the run and operation ids; the receipt becomes
an external artifact fulfilling `companies`; `run outputs RUN` shows 30 Company and the readback
result; S2 receives the thirty uids as resolved subjects; a uid in Neo4j resolves back to S1's
result point."*
