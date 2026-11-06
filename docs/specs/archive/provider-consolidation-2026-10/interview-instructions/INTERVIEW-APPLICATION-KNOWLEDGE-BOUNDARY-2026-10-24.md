---
type: Interview Instruction
title: "Prerequisite interview: application knowledge, ingestion provenance and agent context delivery"
description: "Run before the final output-contract/context-transfer interview. Resolve the directional application boundary and produce a verbatim answer record plus a concrete deep-module pseudocode projection."
tags: [mission-control, interview, application-boundary, ingestion, provenance, context-transfer]
date: 2026-10-24
prepared_by_model: "GPT-6-Astra"
model_label_source: "Owner-supplied experiment label"
source_commit: 8de6fab94fd5d17d79f2ecfd92e55329bb282a36
prerequisite_checkpoint: answers/gpt-6-astra-2026-10-24/ANSWERS.md
status: archived
archived: 2026-11-02
archived_from: INTERVIEW-APPLICATION-KNOWLEDGE-BOUNDARY-2026-10-24.md
archived_reason: "interview held and converted (AS-D25)"
---

> **Archived 2026-11-02** (interview held and converted (AS-D25)). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Prerequisite interview: application knowledge and agent context

## 1. Purpose and place in the sequence

The owner requested this preparation on **2026-10-24**, after accepting the independent
[GPT-6-Astra checkpoint, OC-D27..78](../answer-sets/gpt-6-astra-2026-10-24/ANSWERS.md).
This instruction prepares the next sitting; it does not conduct it or accept its recommendations.

The requested order for the output/transfer work is:

1. Accepted checkpoint: the existing answers and proposed specifications.
2. **This prerequisite interview:** direction of responsibility between Mission Control, application
   knowledge services/stores, ingestion, output provenance and receiving agent context.
3. **Final output-contract/context-transfer interview:** reconcile this sitting's answers and projection
   into the complete contract/workflow design, then settle the implementation issue breakdown.
4. Create the resulting implementation issues, explicitly separating prerequisite schema work. Complete
   the necessary schema refactors/migrations and compatibility proof **before the output-contract/
   context-transfer implementation sprint starts**, as the owner clarified on 2026-10-24.
5. Implement and qualify the output/transfer work on that baseline. The existing 17 local work items
   are inputs to review, not authorization to file or start them now.

This order applies to this feature thread. It does not silently reschedule unrelated provider work.
Detailed subagent construction/tools and physical database relocation remain deferred unless the owner
explicitly brings them into scope. A provider's tool-call integration may be inspected here because it
determines whether runtime origin can be carried; that does not reopen its complete subagent design.

**Schema migration is not physical database relocation.** The new prerequisite includes logical schema,
identity/provenance and native binding changes where required. OC-D77's physical-topology deferral does
not postpone that work. The broader [BellLabs pathway](../../../../../../../docs/BELLLABS-SEQUENCE.md) records
the owner's sequence through Knowledge Services, another domain-schema pass and product/user services,
with bounded research/ingestion/retrieval experiments starting as soon as their necessary path works.

The owner's central concerns, verbatim excerpts:

> We're trying to avoid giving mission agents any mission control storage responsibility.

> BUT WHAT ABOUT INGESTION and OUTPUT provenance and origin ?

> We need beautiful, effective deep modules for output contract verification, retrieval, materialization and conversion AND transmission into AGENT CONTEXT (The context window) AND (special transmission of artifact to sandbox and sandbox location reference to agent context)

> It's looking like a lot of this hinges on Agents faithfully providing refs to outputs. That is ok. This is an agentic system. Let's just do the best we can.

Follow-up requirements, verbatim excerpts:

> I want to see in the psuedo code the mission control <-> application specific storage extension points and resolution.

> we will have to do schema refactor and migrations before the output contracts and context transfer sprint starts.

> We want to start running deep research and ingestion and retrieval experiments as SOON AS POSSIBLE.

These are desired outcomes and concerns. They do not yet decide the injection mechanism, service
extension shape, automatic candidate selection or missing-reference policy.

## 2. Required session outputs

Produce both artifacts during the interview, updating the projection after each relevant answer:

- **A new `ANSWERS.md`** in a separate model/date-qualified directory under
  `answers/application-knowledge-boundary/<model>-<YYYY-MM-DD>/`. Preserve the accepted checkpoint.
  Include date/timezone, actual available model attribution or explicitly owner-supplied label,
  interview ID, source commits for all inspected repositories, prerequisite checkpoint and status.
  Record the owner's words separately from interpretation, assumptions, destinations and revisions.
- **[APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md](../specs/APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md):** complete the
  starter into the special pseudocode/example document. Show modules, typed signatures, data shapes,
  dependency direction, happy and failure paths, actual model-facing context and sandbox layout.
  Link every decided choice to its answer ID; leave remaining engineering assumptions visibly labelled.

The projection must be readable from the outside in: small authoring example -> agent's task and
returned result -> runtime behavior -> application effects and receipts -> receiving context/files ->
module internals. Rich internal records are acceptable; do not make the model author runtime bookkeeping.
Functionality, responsibility and behavior come first. Schema compression and syntax polish happen at
the stable point the owner requested, without discarding guarantees to make examples look small.

Also produce a concise delta map to the accepted [CONTRACTS](../answer-sets/gpt-6-astra-2026-10-24/CONTRACTS.md)
and [WORK-ITEMS](../answer-sets/gpt-6-astra-2026-10-24/WORK-ITEMS.md): retained, refined, revised and deferred.
The final output/transfer interview starts from that map. No implementation or external issue filing
in this prerequisite sitting. This explicit sequence overrides the skill's usual immediate issue step.

The projection must include its prerequisite **migration impact map**: current identity/schema coupling,
proposed change, schema owner, native-service/MC versions affected, data/provenance preservation,
compatibility and recovery proof, and which experiment/runtime work the migration unblocks. Exact
migration names are engineering output after inspection; their need is no longer a deferred topic.

## 3. Read first, then verify only the needed facts

Read the relevant ownership guides, the accepted ANSWERS checkpoint and these parts of its companions:

- [SPECIFICATION §11–13](../answer-sets/gpt-6-astra-2026-10-24/SPECIFICATION.md#11-context-transfer-contract-direction):
  transfer, optional subordinate contributions, assurance and provider/topology boundaries.
- [CONTEXT-TRANSFER §11–12](../answer-sets/gpt-6-astra-2026-10-24/CONTEXT-TRANSFER.md#11-application-storage-boundary):
  application custody, discovery separation, typed references, representations and ingestion lineage.
- [CONTRACTS §2–6 and §9–10](../answer-sets/gpt-6-astra-2026-10-24/CONTRACTS.md): proposed identities, records,
  assessment subjects, adapters, workflow semantics and examples. These mechanics remain proposals.
- [Knowledge Services integration annex](../../../../knowledge/knowledge-services.md):
  common/native envelopes, intent/plan/apply/receipt and uncertain effects. Its historical paths and
  implementation limits need live-source checking; its desired interfaces are not installed endpoints.

Preserve these accepted boundaries unless the owner explicitly revises them:

| Checkpoint | Baseline |
| --- | --- |
| OC-D38..44, D75 | Common forms + application/purpose contracts; separate shape, evidence, coverage and ingestion guarantees |
| OC-D45..52 | Stage/cycle obligations, distinct identities, goal-wide accepted set, mandatory handoff and exact revisions |
| OC-D54..61 | Authorable transfer; explicit alternatives, bounded expansion, availability, preparation and repair |
| OC-D64..70 | Application-owned content; selected retained observations; deterministic modules; discovery distinct; typed refs and receipt-backed lineage |
| OC-D71..77 | Optional child contracts, settlement, applicable assessment reuse, governed revisions, qualified extensions, deferred topology |
| OC-D78 | Accepted revisable checkpoint, not permanent closure of the design |

### Fresh source starting points

Inspected read-only on 2026-10-24. MC Python paths start at the Mission Control repository;
KS paths at `platform/knowledge-services`; BKS paths at `biotech/biotech-knowledge-services`.
Recheck source lines/HEAD before relying on them. No runtime or live qualification was performed.

| Owner/source | What exists | What it does not establish |
| --- | --- | --- |
| MC `integrations/biotech/src/biotech_mission_adapters/knowledge/adapter.py:86-135,373-382` | Explicit operation context, optional MissionRef, namespaced standalone run and checks for native/envelope run mismatch | Automatic origin injection for every provider tool path or trusted end-to-end propagation |
| MC `mission-control-general/general-mission-control/expansion/KNOWLEDGE-SERVICES.md:20-35,56-76` (deleted 2026-11-01; last at `66185d2e`) | Specified wrapper/native separation, frozen native bytes, admitted writes and receipt recovery | Implemented general gateway or permission to alter an already-approved native intent |
| KS `packages/knowledge-db/src/ingestion/intent.ts:272-284` | Native intent accepts tenant, mission, attempt, activation and actor context | That an MC identifier fits the native identity namespace or that an agent-supplied ID is authoritative |
| KS `packages/knowledge-db/src/ingestion/executor.ts:272-277,427-449` | Persists native intent and orchestration mission/attempt columns | Full decoupling of application provenance from native orchestration schema |
| KS `packages/knowledge-db/src/ingestion/content-links/executor.ts:116-130,364-375` | Checks host-pinned mission/attempt/policy; requires native attempt-to-mission relationship | That arbitrary MC UUIDs can be injected without an explicit mapping and schema-authority review |
| KS `packages/knowledge-db/src/ingestion/apply.ts:298,619` | Entity/claim writes carry receipt provenance | A universal domain entity -> MC output-obligation mapping |
| BKS `packages/contracts/src/intent-v2.ts:25-45` | Native run system/run/mission/activation/attempt/operation fields | Authentication of an asserted origin or universal required mission association |
| BKS `packages/kg-ops/src/write/compile.ts:195-219` | Native Activity projection includes namespaced run and optional mission | Equivalence of originating producer, later ingester and consumer |
| BKS `packages/contracts/src/apply-v2.ts:93-122` | Receipt has effect/intent/plan identities, graph revisions, Activity, affected effects and recovery coordinates | Semantic report quality or a cross-store atomic transaction |
| MC `src/mission_control/application/context/pack_service.py:107-126` | Artifact capture port separates metadata, custody and optional text | General application-entity resolution already implemented |
| MC `src/mission_control/adapters/postgres/context/artifact_bytes.py:1-13,39-86` | Resolves registered workspace candidates/artifacts; arbitrary model strings do not resolve | Every file path or entity ID returned by an agent is usable automatically |
| MC `src/mission_control/adapters/deep_agents/materializer.py:1237-1263` | Seeds files before model invocation; StateBackend text differs from sandbox uploads; unsupported binary fails | That upload alone injects the file body into the model's context window |

Critical audit before proposing "just inject the mission ID": trace **identity namespace, issuer,
foreign-key expectations, authority and receipt linkage** in each application. Read the actual AI
Engineer database contract where needed. Do not solve a native constraint by fabricating local mission
rows, copying MC tables, weakening foreign keys or moving domain migration authority.

## 4. Directional map the owner must be able to explain

Draw these as separate flows, then connect them with one report/assertion example:

1. **Execution origin -> admitted knowledge operation.** Runtime supplies trusted caller coordinates;
   the application owns native validation, planning and canonical writes.
2. **Domain result -> Mission Control evidence.** Authenticated receipts/native refs and captured
   artifacts become observations/candidates with lineage; requirements determine acceptance.
3. **Selected accepted output -> next agent.** Exact references resolve through modules, representations
   are retained, required checks run and delivery produces both model-visible context and accessible files.

Separate original author/producer, ingester, current caller, reviser, assessor, materializer and consumer.
Reusing an old report must not claim the current mission created it. Saving a transcript/checkpoint proves
neither successful domain ingestion nor that an output satisfies its contract.

## 5. Interview frontier and question bank

Use [grill-with-answers](../../../../../.agents/skills/grill-with-answers/SKILL.md) and
[architecture-projection](../../../../../.agents/skills/architecture-projection/SKILL.md). Ask at most four
questions per batch, recommendation first. This is a dependency-ordered bank, not a script to ask all
at once. Facts belong to inspection; decisions belong to the owner. Skip already resolved choices.
Number question IDs `AK-Q1..21`; allocate new OC-D IDs after the latest verified decision ID (currently
OC-D78). Link any changed decision to the checkpoint it revises; interview IDs disambiguate other models.

### Round A — responsibility and the observation boundary

- **AK-Q1: What must an agent do beyond useful domain work?** Recommend agent-authored content, native
  proposals and intended output selection; runtime owns MC registration, coordinates, receipts and
  delivery bookkeeping. Native tools may return handles for the agent to name. Decide the minimum
  required agent declaration and what happens where automatic capture is unsupported.
- **AK-Q2: Which knowledge calls carry trustworthy mission origin?** Recommend an admitted invocation
  boundary for mission-origin claims, with scoped identity supplied by the host. Inspect tool/MCP/CLI,
  delegated service worker and human/external call paths. Decide whether an unmediated path is prohibited
  for mission effects, allowed as explicitly untracked work, or supported by a qualified integration.
- **AK-Q3: Which provenance identities must remain separate?** Recommend original production, current
  operation/caller, native receipt, revision, adoption and consumption lineage. Decide expectations for
  pre-existing reports, reused assertions, ingestion in another mission and standalone service work.

### Round B — modular trusted origin and native ingestion

Depends on A and the namespace/authority audit.

- **AK-Q4: Where does the optional Mission Control integration live?** Compare a reusable external-run
  provenance contract with an MC adapter against a versioned MC-specific service extension. Recommend
  a small admitted integration boundary; keep knowledge algorithms usable without MC and native schemas
  owned by applications. Choose based on actual native bindings, not a new global orchestration schema.
- **AK-Q5: When can host coordinates enter native payloads?** Recommend deterministic binding before
  native bytes are registered, digested, planned or approved. Agent-supplied conflicting origin is a
  typed failure. Where the native schema cannot accept origin, decide an external receipt-linked bridge
  rather than silent payload mutation. No enrichment after sealing.
- **AK-Q6: How does origin survive durable/delegated knowledge work?** Recommend validated propagation
  across admitted calls, preserving parent/child operation identities and standalone origins. Decide
  the minimum service changes and the explicit behavior when a hop cannot preserve the proof.
- **AK-Q7: How do committed results return reliably?** Recommend correlating native receipts and affected
  revisions to the original operation, retaining source artifact mappings. Lost responses reconcile
  that operation before retry; partial results keep per-item status. Decide limits of automatic recovery.

### Round C — agent output declarations and independent observations

- **AK-Q8: What is the smallest useful final result?** Start with the owner's structured report/assertion
  result containing a file reference and native entity IDs. Recommend qualified handles or an explicitly
  application-bound envelope. Decide whether the host adds missing coordinates and how ambiguous refs fail.
- **AK-Q9: What can be recovered without a faithful final message?** Recommend consulting scoped captured
  workspace candidates and authenticated operation receipts, then bounded agent repair for ambiguous
  obligation mapping. Observed != selected != accepted. Decide exact conditions for automatic association.
- **AK-Q10: What if a file and native report disagree?** Recommend treating them as distinct revisions/
  representations until receipt-backed lineage or an admitted equivalence check relates them. Never
  guess by filename/title or replace the intended output with another report because it exists.
- **AK-Q11: When is a compound report/assertions obligation fulfilled?** Recommend independent shape,
  provenance, assertion/report coherence, declared coverage and ingestion checks. Existing narrower
  verification can be reused only for what it proves. Decide the required guarantees for this example.

### Round D — retrieval, conversion and two delivery destinations

- **AK-Q12: Which data must be resolved/exported?** Recommend bounded explicit reports/assertions/evidence
  selection, retained exact observations and admitted deterministic representations. Discovery and
  meaning-changing preparation remain separate work. Decide the example's required representation.
- **AK-Q13: What must be directly in the context window?** Recommend required task/state/findings plus
  explicitly requested content. Distinguish inline bytes from a file index/reference that allows a tool
  read. Decide whether full report text, assertions or a compact index is required for each consumer.
- **AK-Q14: What must be materialized in the sandbox?** Recommend named read-only inputs, exact digest,
  collision-safe paths and an agent-visible mount index; upload/readability must succeed before the
  pointer is presented as usable. Decide read-tool availability, binary handling and allowed alternatives.
- **AK-Q15: What is required before invocation can begin?** Recommend a readiness check over mandatory
  context, required file/access receipts and qualified provider delivery; token/byte/access failure
  invokes authored repair then blocks. Decide how lazy references and provider compaction can meet the
  promise without asserting that stored bytes were necessarily read or understood.

### Round E — boundaries, recovery and comprehension

- **AK-Q16: How does the example cross a workflow boundary?** Show a next GoalDirected iteration, a
  dependent stage and a linked mission. Recommend explicit binding plus existing tracking/snapshot rules,
  independent authority/budgets and no implicit obligation transfer. Identify actual service/lane gaps.
- **AK-Q17: What survives a crash, refresh or revoked input?** Recommend original operation/receipt keys,
  retained sources and sealed packets; explicit refreshed observations and invalidation; no blind
  duplicate ingestion. Distinguish producer/invocation identity from durable semantic effect identity.
- **AK-Q18: Are the proposed modules deep enough?** Walk one call through each public interface. Recommend
  hiding native mapping, custody and provider mechanics behind few meaningful operations. Decide where
  one module would mix authorities or many wrappers would leave orchestration complexity with the agent.
- **AK-Q19: Can the contracts be understood at three levels?** Require author-facing settings, the
  agent's actual declaration/context, and expanded internal receipts to show the same behavior. Record
  simplification candidates; do not remove necessary guarantees merely to shorten the schema now.
- **AK-Q20: Which schema changes must precede the sprint?** The owner has required prerequisite refactors
  and migrations. Recommend a concrete application/MC impact map and readiness proof; decide native
  identity decoupling, lineage/custody requirements and compatibility sequencing. Preserve separate
  authority for each schema and distinguish this first pass from later domain-use-case optimization.
- **AK-Q21: Does the finished projection resolve the gray area?** Ask the owner to confirm/correct the
  concrete walkthrough and assumption table, then identify the precise remaining final-interview frontier.

## 6. Projection completion requirements

Complete the starter's ten architecture sections. Give each module a small typed interface, ownership,
hidden work, refusal behavior, authority inputs, retry semantics and evidence it records. Compare two
credible designs for the hardest origin/ingestion boundary before choosing. Keep rejected design and
reason. Exact placement/migrations must follow source inspection; unknown paths are labelled proposals.

The central walkthrough must show **all** intermediate objects and who constructs them:

Show extension registration and dispatch, then **both** AI Engineer PostgreSQL and Biotech Neo4j
resolution implementations. The expanded examples in projection §§4.1–4.8 are the starting point:
MC common port -> pinned application binding -> native client operation -> application schema/read ->
native result -> exact retained observation -> representation -> receiving context/sandbox. Show the
reverse origin/ingestion/receipt mapping just as explicitly. Do not leave these arrows hidden behind
an unspecified `fetch()` or assume a common ID means common storage semantics.

`goal obligation -> agent task/tools -> domain proposal -> trusted operation origin -> sealed native
intent -> plan/admission/apply -> native receipt and affected refs -> MC observation -> agent final
selection -> candidate reconciliation -> assessments/fulfillment -> transfer selection -> resolution/
representation -> sandbox materialization -> model message/context -> next invocation`.

Include at least these variations: pre-existing content with no new ingestion; omitted final refs;
wrong/foreign refs; file/entity disagreement; partial or lost ingestion response; missing exact revision;
required binary on text-only backend; context budget overflow; crash between upload and dispatch; later
revision of a tracked source. Each shows state, repair/block behavior and residual agent responsibility.

## 7. Ready-to-use prompt for the next session

```text
Run the prerequisite application-knowledge-boundary interview from
docs/specs/archive/provider-consolidation-2026-10/interview-instructions/INTERVIEW-APPLICATION-KNOWLEDGE-BOUNDARY-2026-10-24.md.

Start from the accepted GPT-6-Astra ANSWERS.md checkpoint linked there. Preserve its decisions unless
I explicitly revise them. Inspect current Mission Control, AI Engineer Knowledge Services/database
contracts and Biotech Knowledge Services where needed; do not ask me for facts the repositories answer.

Use grill-with-answers and architecture-projection. I want to resolve direction and responsibility:
trusted runtime identity into ingestion, native results back into output provenance, and exact selected
content into the agent context window and sandbox. Minimize mission agents' MC storage responsibility
while explicitly handling agent-provided output refs and incomplete declarations.

Create a separate, attributed ANSWERS.md before asking questions. Complete
APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md as the interview proceeds: deep modules, typed pseudocode,
realistic payloads/receipts, the report-and-assertions GoalDirected happy path, actual next-agent context
and sandbox layout, and failures/recovery. Clearly separate existing code, accepted decisions and
proposed mechanics. Functionality first; contract simplification comes at the stable review point.

Show the MC extension registry, the common resolution port, both application-specific implementations,
their actual native storage/custody mapping, and the return path into context and sandbox. Include
the prerequisite schema refactor/migration impact map: those migrations must finish before the
output-contract/context-transfer sprint. Distinguish this from physical topology relocation.

This sitting precedes the final output-contract/context-transfer interview. End with both artifacts
and an exact delta/frontier for that final interview. Do not implement or create external issues yet.
```

## 8. Completion and handoff

This **preparation** is complete when the instruction, projection starter, checkpoint links and ledger
entries are present and document checks run. The **future interview** is complete only after its actual
answers are recorded and folded, its projection visibly traces every responsibility, and the owner
confirms the resulting model. Neither future acceptance nor projected implementation is claimed here.

Preparation checks, 2026-10-24: program ledger passes (50 rows); compiled documentation index and
checkpoint-answer validation pass; 52 prior decision rows are preserved. Link verification after
repairing the new document's section link reports only the three pre-existing missing targets elsewhere
in this program. Whitespace check passes. Source inspection was read-only; no runtime tests, database
access, provider calls, implementation or external issue publication were performed.
