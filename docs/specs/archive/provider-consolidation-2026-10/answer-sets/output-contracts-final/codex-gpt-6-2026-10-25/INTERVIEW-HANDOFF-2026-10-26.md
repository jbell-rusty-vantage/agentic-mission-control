---
type: Session Instruction
title: "IQ-07 detailed interview handoff: workflow context, linked workflows and Deep Agents hooks"
description: "Exact session handoff through OC-D138: last GoalDirected questions answered, accepted decisions, MC/KS/domain ownership, source-backed gaps, deep intra/inter-workflow interview agenda, fixture gates, and remaining specification conversion."
tags: [mission-control, interview, handoff, context-transfer, linked-workflows, knowledge-services, deep-agents]
date: 2026-10-26
status: active
---

# Continue IQ-07 from the workflow-context interview

**Superseded resume entry point:** continue from [FINAL-INTERVIEW-HANDOFF-2026-10-26.md](FINAL-INTERVIEW-HANDOFF-2026-10-26.md),
through OC-D161, next OC-D162. The owner caps the next interview at twenty substantive questions;
none of that instrument has been asked. This document remains the historical detailed source map.
Its old frontier and launch wording do not override the final handoff or latest owner scope.

**Resumed-session update, 2026-10-26:** [ANSWERS](ANSWERS.md) now records through OC-D158.
FC-Q23a..i are answered: first qualifying sealed any/quorum set; unfinished branches continue within
budgets; pending optional inputs visibly omitted; bounded synthesis/report-revision revalidation;
running synthesis finishes on sealed inputs before revalidation unless explicit interruption policy.
Incremental arrivals combine into one pending next synthesis. OC-D146 explicitly includes authored
bounded reassessment of provisional synthesis after exact held-source acceptance. General freshness/
invalidation automation stays deferred; other cases need explicit inclusion.
See [CONTRACTS §16.4–16.7](CONTRACTS.md#164-stage-graph-alternative-selection-and-unfinished-branches).
OC-D147/148 accept unknown/else and frozen expansion defaults. OC-D149 requests routing status and
justification, documented in [CONTRACTS §16.9](CONTRACTS.md#169-conditional-routing-current-state-and-rationale).
General conditional routing is specified but not implemented in the inspected Stage Graph path.
OC-D150 expands Stage Graph questioning to large workloads/map-reduce (FC-Q27; CONTRACTS §17).
FC-Q27a/b/c are accepted (OC-D151..153): transform extensibility, partition accountability and bounded scheduling.
FC-Q27d/e/f are accepted (OC-D154..156): conflict scope, independent group readiness and qualified trees.
OC-D157/158 request a broad coordinator-perspective critique before further feature questions;
see [CONTRACTS §18](CONTRACTS.md#18-coordinator-perspective-critical-review). Its recommendations
are not accepted amendments. No asked question remains pending; next unused ID is OC-D159.
The original handoff/checkpoint below remains historical; consult the
live answer record's Assumptions section for the next asked questions. No runtime implementation claimed.

## 1. Start here: this is an interview handoff, not an implementation kickoff

The owner stopped because the conversation context had become too large and explicitly requested a
new session. **Do not restart the interview, declare it complete, implement runtime changes, or ask
for the fixtures immediately.** Continue with StageGraph context dependencies (§9), then linked/nested
workflow transfer (§10), hooks and coordinator delivery. The two last GoalDirected questions in §4
were answered after this handoff was created; do not re-ask them. The owner explicitly adds
**Linked Workflows** and wants deep
coverage of context passing both **within workflows and between workflows**. GoalDirected and
StageGraph are not the entire remaining scope.

Latest accepted behavioral answers: **OC-D137 and OC-D138**. Owner steering is recorded as
**OC-D135** (linked and intra/inter-workflow scope) and **OC-D136** (this handoff and permission for
next-session discovery subagents). The owner subsequently answered FC-Q22c/d explicitly and asked
that they be documented before moving sessions. **Next unused decision ID: OC-D139.** No already
asked question remains unanswered; the remaining interview agenda is still open.

The active answer file remains [ANSWERS.md](ANSWERS.md), IA-09, `status: open`. Continue this record;
it already spans the 2026-10-25 sitting and its 2026-10-26 continuation. If repository convention
requires a new sitting record, link it explicitly and continue decision numbering; do not duplicate
or overwrite the earlier answers. The current contract is [CONTRACTS.md](CONTRACTS.md), SP-12,
`draft`. The [instrument](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md)
is IQ-07, `open`. This handoff is SE-11. The previous [overnight checkpoint](CHECKPOINT-2026-10-25.md)
is historical; its originally unanswered questions have since been answered.

The owner permits **GPT 6 Astra subagents** for the next session's context discovery, exploration
and/or research. Earlier GPT 6.1 Sol helpers performed source audits. Delegate bounded factual
questions; the primary interviewer integrates findings and asks the owner product decisions.
Do not assume old live agent instances or tool-call question IDs will survive a new session.

Suggested opening, adapted to the owner's actual next message:

> I have the checkpoint through OC-D138, including the accepted progress-note and repair-fork defaults.
> We will now work through StageGraph and linked/nested workflow transfers,
> Deep Agents hooks, and coordinator retrieval/subscriptions. The exact fixtures still come at the end.

Do not send all remaining questions at once. Ask small coherent batches, recommendations first,
with concrete examples and the consequence of each choice.

## 2. Owner intent and the work we are actually finishing

The owner wants a general Mission Control and knowledge-services system for demanding AI engineering,
AI-company research, biotech science and biotech-company work. The concern is long-running coherent
missions: dynamic instructions, durable lifecycle, real context transfer, accumulation, recovery,
independent assessment and actual functional results. A framework's advertised multi-agent support is
not evidence that these requirements work together.

This is the final output-contract/context-transfer interview, following an accepted broad checkpoint,
an application-knowledge-boundary interview, and Sprint V's prerequisite report/verification/ingestion
and port work. "Final" is the instrument's name, not permission to skip unresolved questions.

Standing owner instructions:

> WE MUST stop at certain checkpoints and run real fixtures -> analyze the transcription -> determine if it meets our functional goals -> IF NOT we fix it at every level (That includes database migration, code change, etc)

> I will provide those exact fixtures after the interview and then you can integrate them. They are real world knowledge work fixtures concerning ai engineering / ai companies and biotech science and companies.

Later clarification: those fixtures will be complex, real-world tasks. The six-wave plan is a
capability/proof progression, not six toy scenarios into which the owner must squeeze the work.
Adapt the checkpoint mapping to the actual tasks. Partial slices cannot certify a full task.

Latest steering, retained verbatim in the answers record:

> In addition to goal directed and stage graph we need to resolve this.
>
> How do Linked Workflows pass context ?

> I need you to write an extremely detailed interview handoff file. We need to go deep into how workflows inter and intra pass context as we are doing. The next agent session can use subagents as needed (GPT 6 Astra permitted) to help with context discovery , exploration and/or research.

> Please write that handoff now. Please provide quality context. Remember the difference and porting/extension of knowledge services and mission control .

The current task ends with a usable handoff. Resume interview questions in the new session when the
owner asks. FC-Q22c/d were accepted by explicit answers, not inferred from elapsed time or this stop.

## 3. Workspace, authority and efficient reading order

### 3.1 Checkout snapshot

Root: `C:\Users\Pinda\Proyectos\BellLabs`, PowerShell, America/New_York.
Commands below and all MC-root-relative paths refer to
`C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control` unless stated otherwise.

Read-only Git inspection during this handoff found:

| Repository | Branch / HEAD | State at inspection |
| --- | --- | --- |
| MC | main / `1863017c779a1b138951c19a0abfcadc4f839a84` | One checkout; interview documentation dirty/untracked. Preserve it. |
| Shared KS | main / `b45adf5ac517510c14842d8fd2909fca95ce1e24` | Clean; one registered checkout in the current worktree listing. |
| AI Engineer DB contract | main / `306efd71291ffacd57c6ce698112a213c45621bb` | Clean. |
| Biotech KS | main / `c398177f119d70cdba2606625785e70f780a2dc6` | Clean. |

These are snapshots, not instructions to reset anything. Recheck live state. The older service
inventory/worktree guide describes older pins and retained worktrees; use it for routing, not as
current branch or deployment evidence. No databases, installations or provider runtimes were
requalified during the interview.

MC dirty paths before this handoff: root GLOSSARY; IQ-07; program LEDGER; SPRINT-V-DESIGN and PLAN;
Deep Agents SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER and DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT;
sprint-v/IQ-07-BRIEFING; and the untracked `answers/output-contracts-final/` directory. These are
valuable interview work. This handoff adds to them. Do not stash/reset/clean them or infer that an
untracked file is disposable. No commit or push was requested.

### 3.2 Read in layers, not by dumping the entire repository

1. Root user instructions / AGENTS; `docs/navigation/SERVICE-INVENTORY.md`, RETRIEVAL and WORKTREES;
   `platform/AGENTS.md`; MC `AGENTS.md` and `docs/AGENTS.md`.
2. This handoff; [ANSWERS](ANSWERS.md) latest decisions and assumptions;
   [CONTRACTS](CONTRACTS.md) §§1–5, 7–13 and 16; [workflow/hook audit](WORKFLOW-CONTEXT-HOOKS.md).
3. [IQ-07](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md), especially its
   accepted additions and Round E; [program ledger](../../../../../provider-consolidation-2026-10/LEDGER.md).
4. The relevant source slice for the next question. Use the maps in §§7–12 below. Read the source
   before turning an implementation observation into a claim.
5. Earlier accepted records only as needed:
   [IA-06](../../gpt-6-astra-2026-10-24/ANSWERS.md), OC-D27..78;
   [IA-07](../../application-knowledge-boundary/claude-fable-5-1-2026-10-24/ANSWERS.md), OC-D79..105;
   [application-boundary design](../../../specs/APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md), SP-10;
   [Sprint V design](../../../specs/SPRINT-V-DESIGN.md) and [plan](../../../sessions/SPRINT-V-PLAN.md).

The [earlier context-transfer draft](../../gpt-6-astra-2026-10-24/CONTEXT-TRANSFER.md) is valuable,
especially its boundary matrix and storage-extension design, but later answers supersede specific
wording. In particular do not restore a required boolean, special domain_effect kind, duplicate
canonical transfer plans, blanket judgment exclusion, or two output-submission channels.

Use `rg` with narrow directories and bounded excerpts. The default MC OKF search excludes
`docs/specs`; pass the program as `--root` when searching this interview. Do not search private
catalog notes, secrets, environment-file contents, dependency trees or retained Git internals.

### 3.3 Interview method

The explicitly invoked skill is `.agents/skills/grill-with-answers/SKILL.md`, with `grilling` and
`domain-modeling`. Read them in the next session. Core requirements:

- Every owner decision gets its own row, exact owner words in Answer, interpretation elsewhere.
- Ask at most four independent questions per batch; two or three usually works best here.
- Inspect facts yourself or delegate; do not ask the owner to rediscover source behavior.
- Restate the practical model after each round, ideally using an author/agent/operator example.
- Fold accepted decisions as you go; update glossary only for settled domain language.
- ADRs and work items follow the accepted design; never present a recommendation as an answer.
- Keep the record open until conversion and final model confirmation are complete.

## 4. Last two questions now answered: do not re-ask

These questions were pending when the handoff was created. The owner answered both on 2026-10-26,
then explicitly requested that they be documented before moving to a new session. **Both are now
accepted as OC-D137/138.** Original wording and choices are retained below for fidelity; do not
re-present them as unanswered. Start the next session with StageGraph and linked-workflow detail.

### FC-Q22c — semantic continuity between GoalDirected iterations

> FC-Q22c — For continuing GoalDirected executors, should the default profile explicitly require a compact progress note at each normal iteration handoff? I recommend yes: record work and sources tried, useful findings, unsuccessful approaches worth avoiding, unfinished work and suggested next actions, with exact references. This is a brief, attributed work summary; the host still supplies authoritative goals, accepted outputs, findings, waits and budgets. It cannot rewrite those facts or authorize actions. A crash preserves the host checkpoint and records any missing note; recovery follows the contract. This makes semantic continuity an explicit GoalDirected requirement under our earlier handoff decision, while ordinary helpers remain unaffected.

Choices:

1. Require a compact progress note in the continuing GoalDirected default profile. (Recommended)
2. Keep semantic notes optional unless the mission author explicitly requires them.

**Owner answer / OC-D137:** "Require a compact progress note in the continuing GoalDirected default profile. (Recommended)"

Accepted consequence: this profile explicitly requires the attributed note at each normal iteration
handoff under OC-D119. The host preserves authoritative state and records any missing note on crash
for contract-governed recovery. The existing journal is a foundation, not implementation proof. Do not turn all
helpers into mandatory handoff producers. A work summary is observable work/result explanation,
not a request for private chain-of-thought.

### FC-Q22d — working drafts at an explicitly requested repair fork

> FC-Q22d — When you explicitly create a repair fork—a new run branching from a failed iteration—what should it receive by default? I recommend the accepted-set index and findings plus that point’s exact task-relevant working drafts/files, clearly labelled for repair. This preserves unfinished research and edits. Pin the historical selection, verify receiving access and availability, and never substitute today’s workspace for a missing historical snapshot. Pending effects remain visible records requiring reconciliation; copying context does not adopt obligations, duplicate writes or transfer authority. Broader history stays off. Should the repair profile include those working drafts by default, or require an explicit selection beyond accepted outputs?

Choices:

1. Include the selected exact working drafts and files in the repair-fork default. (Recommended)
2. Default to accepted outputs and findings; select working drafts separately.

**Owner answer / OC-D138:** "Include the selected exact working drafts and files in the repair-fork default. (Recommended)"

Accepted consequence: repair profile includes the selected historical task-relevant drafts/files,
labelled for repair, with accepted-set index and findings. Access/availability and exact historical
selection are checked; current workspace cannot substitute for a missing historical snapshot.
Existing precise-fork identity, seed and historical-state rules remain authoritative. This chooses
a repair profile's content selection, not a new generic fork implementation,
implicit work adoption, copied credentials, effect replay or changed source-run ownership.
Read ADR-0037 and ADR-0057 before refining its mechanics.

## 5. Accepted decisions: do not spend the next session re-asking them

This is a navigation summary of accepted semantics, **not a replacement for verbatim answers**.
The exact quotes and destinations are in IA-06, IA-07 and [IA-09](ANSWERS.md).

### 5.1 Earlier foundation retained

| Decisions | Accepted rule |
| --- | --- |
| OC-D39/75/91 | Named shape, provenance, coherence, coverage and ingestion guarantees remain separate; enforce those the contract promises. |
| OC-D45/46 | Per-cycle and accumulated obligations coexist. Count distinct deliverable identities, not revisions; subject coverage is separate. |
| OC-D47/48 | Producer completion is the default release boundary. Incremental release requires explicit trigger and revision policy. Caps are not success. |
| OC-D49/101 | Track revisions by default with exact consumed versions and staleness/revalidation; pinned snapshots are explicit. No silent native-effect rollback. |
| OC-D50/51/73 | Goal verification covers the current goal-wide set; reuse applicable evidence. Keep current and historical views separate. |
| OC-D52/54–61 | Host boundary state and required representations cannot be dropped by packing heuristics. History is bounded/authorable. |
| OC-D64–70 | Application custody and typed storage extensions can supply retained exact content; no requirement to mirror all native bytes into MC. |
| OC-D71/72 | Ordinary helpers may have no output obligation; responsible workflow promises/child settlement remain explicit. Special helper tools are deferred. |
| OC-D76/77 | Common semantics, versioned provider extensions, Deep Agents first; no new physical-topology decision inferred. |
| OC-D79/84/85/87 | Service-authenticated per-live-invocation origin via KS-native protocol; validated child origins and durable propagation. Direct standalone calls are not attributed mission ingestion. |
| OC-D80 | Original producer, current caller, native receipt, revision, adopter, assessor and consumer are distinct provenance roles. |
| OC-D81/82/86 | Design the coherent target even when substantial migrations are needed; unify evidence/report semantics with application storage bindings. Current code is a baseline, not a product constraint. |
| OC-D83/89 | One progressive/final agent act: submit_output names candidates for obligations. Final prose is not an output_refs channel. Narrow unique auto-association; ambiguous/out-of-scope refs refuse with bounded repair. |
| OC-D88/90 | Mint effect identity before writes; reconcile lost results before retry. Files and native reports are separate revisions unless receipt-backed lineage or admitted deterministic equivalence relates them. |
| OC-D92–99 | Exact body, selected assertions and scoped evidence handles through explicit resolution/export/delivery; current use, exactness and qualified receiving-lane access matter. |
| OC-D102–105 | Prerequisite schema/port/report/verification program adopted; deep modules at both agent-facing and code levels; prior walkthrough accepted, current final interview still required. |

### 5.2 Current sitting: OC-D106..138

| IDs | Accepted decision / steering |
| --- | --- |
| 106–107 | Mandatory real-fixture Transcript/result review, repair at every needed layer, rerun; exact owner tasks supplied after the interview. |
| 108 | Independent judge/auditor first run as separate MC-hosted Deep Agents operations. KS authenticates observations, seals evidence and owns use decisions. |
| 109 | Evaluation timeout/unavailability preserves work, retries within policy, then durable recoverable block. Not an evidence verdict; cancellation fences late reopening. |
| 110 | KS decision binds exact report revision, use, audience and effect. MC owns durable human-review wait; KS owns reviewer authority and successor decisions. |
| 111 | Ungrounded evaluator disagreement holds/disputes; automated rejection needs grounded contradiction or integrity failure. Authorized human adjudication remains. |
| 112 | Explicit judgment contracts allow recommendations/forecasts under use policy, premises/rationale/assumptions/uncertainty/horizon and required independent/human review. Approval is not fact entailment. Revises Sprint V's blanket exclusion. |
| 113 | Mission authors may select permitted admitted review policies or tighten them; application minimums and current revocation remain enforced. No self-granted reviewer role. |
| 114 | Submission, durable obligation fulfillment and invocation finalization are separate. Missing submissions cannot erase promises. |
| 115 | Eight general forms: text, structured, file, collection, reference, code_change, effect_receipt, control_record. Domain types use pinned templates or inline contracts and admitted validators. |
| 116 | One canonical sealed transfer plan, separate per-attempt delivery/readiness receipts. Replace overlapping selection/delivery authorities while preserving new-system replay. |
| 117 | General step outputs/effect receipts replace special domain_effect kind. Report production, permitted use, native commit and readback remain distinct. |
| 118 | Required, expected and optional obligation enforcement; separate from output validity and authorization. |
| 119 | Always host-assemble authoritative handoff state. Agent semantic explanation only where explicitly contracted. OC-D137 now sets the continuing GoalDirected profile default. |
| 120 | Historical tentative profile answer and questions; resolved by 123/124, do not treat it as still open. |
| 121 | Review/repair consumers may receive labelled draft/held content under authority; official-use consumers need exact-use/current eligibility and additional native guarantees where promised. |
| 122 | One host-owned prompt-materialization entry point; boundary-specific builders behind it. No invented predecessor for first invocation. |
| 123 | Common versioned transfer schema; reusable report-review@v1 first profile or inline definitions. Admission pins/compiles, activation binds run revision; preference specialization profile → mission → unit → consumer input, with hard/link constraints retained. Submission does not change policy. |
| 124 | Compact task/state/obligations/assertions/access index inline; exact report bodies in sandbox files; evidence via scoped handles; history off. Explicit consumer placement/alternatives, aggregate prompt/file accounting and generation/tool reserves. Later file reads consume context too. |
| 125 | Focused effective-node/input/output/fulfillment/plan/receipt inspection and attributable events. Broad coordinator redesign deferred. |
| 126 | Durable actionable/checkpoint wake defaults; batch ordinary progress. Prove chosen-host actual wake, reconnect/replay/ack/duplicates/cancellation. |
| 127 | Shared typed output/transfer error envelope and responsible-layer repair; model corrects bounded content errors, host recovers infrastructure/authority/uncertain effects. Not the whole fault-tolerance program. |
| 128 | Explicit real-fixture qualification exception to SV-D12 at progressive checkpoints; routine use still gated. |
| 129–130 | W0–W5 with mandatory evidence checkpoints; independent reviewing agent, coordinator records pass only if all criteria met; unresolved/human-required decisions escalate. Engineering release is separate from KS/scientific review. |
| 131–132 | Adapt waves to actual complex fixtures; deeply interview GoalDirected, StageGraph, hooks and coordinator delivery before final confirmation. |
| 133 | Three GoalDirected views: current accepted work, actionable repair work, optional history. Bounded inline goal/gaps/blockers/repair queue; complete exact accessible current-set index; bodies task-selected under input contracts. |
| 134 | Continue independently runnable work within budget while affected goal-scoped obligations wait. Preserve final acceptance and invocation/global barriers; do not duplicate pending work/effects. |
| 135–136 | Explicit linked/intra/inter-workflow interview expansion and this new-session handoff, with GPT 6 Astra discovery/exploration/research permitted. Scope/process steering, not answers to pending defaults. |
| 137 | Continuing GoalDirected default requires compact attributed progress note at normal iteration handoffs; exact references, authoritative host state preserved, crash records missing note for contract recovery. Ordinary helpers unaffected. |
| 138 | Explicit repair-fork default includes selected exact historical task-relevant drafts/files plus accepted-set index/findings, labelled for repair and access/availability checked. No current-workspace substitution, automatic obligation/effect-authority adoption or broader history. |

Practical latest model: A1 accepted, B1 held for review, C absent. The next executor gets a bounded
goal/gap/wait view and access to the exact accepted-set index. It can research C when independent.
B remains waiting and still blocks final acceptance. B1 enters context only when selected for a
permitted task and is visibly held. Next verification considers the whole applicable accepted set,
not merely the latest iteration's output refs.

## 6. Mission Control versus Knowledge Services: ports, extension and ownership

This distinction is central to the owner's latest instruction. Do not collapse the services into
one database, make the model manage MC storage, or implement domain verification in the MC kernel.
Also do not pretend shared KS is already completely backend-neutral because it lives under platform.

### 6.1 Responsibility matrix

| Owner | Owns | Does not gain merely by seeing context |
| --- | --- | --- |
| Mission Control | Mission/run/revision/activation lifecycle; Temporal scheduling; output obligations, attributable submissions, fulfillment and finalization; sealed transfer plans and delivery receipts; budgets, cancellation, durable review waits, effect reconciliation coordination, transcripts and coordinator events. | Native domain truth, scientific authority, automatic reviewer grants, or a right to ingest/use every referenced item. |
| Shared Knowledge Services | Reusable acquisition/inspection/preparation/retrieval/evidence/report/verification/decision capabilities; KS-native operation protocol and common report/evidence semantics; authenticated semantic results, deterministic assessment/sealing and use decisions. | Mission scheduling or a replacement workflow engine; ability to approve a producer's own work by trusting a role string. |
| AI Engineer domain DB contract | Canonical AI Engineer schema/migrations and native projection/admission constraints; applications consume pinned contracts. | Authority over MC common schema or Biotech graph schema. |
| Biotech Knowledge Services | Native Neo4j domain graph, authored SDL/releases, admitted read/plan/apply and native lineage/readback; product BFF/GraphQL as separate consumer surfaces. | A second shared verification-policy authority or permission to edit generated pinned schema as source. |
| Provider lane / Deep Agents | Bounded cognition, tools, sandbox and provider-specific materialization/continuation capabilities behind MC contracts. | Mission scheduling, canonical acceptance, or direct database authority. |

MC is one general service with two application bindings. The common MC SQL component belongs in
`packages/mission-control-db-contract`; each application's database receives the component under
its own binding. Application PostgreSQL, Temporal persistence, LangGraph saver and Agent Server
storage are distinct. A shared module name does not imply shared tenant/application authority.

Shared KS retains existing `@aiengineer/*` package names and some AI Engineer bindings. BKS is a
different domain service. There is no discovered third "dynamic knowledge service" to route work to.
Do not recreate the retired ai-engineer-mission-control or research_ingestion_systems_agent.

### 6.2 The two-way integration that must survive every transfer

Forward knowledge-operation path:

1. MC admits task/capabilities/contracts and constructs origin for the **live invocation**.
2. An admitted knowledge tool/gateway carries host-minted credential and semantic effect identity.
3. KS validates credential audience and binds origin; model-supplied identity cannot elevate it.
4. Shared semantics execute through the selected native/application binding.
5. The service returns qualified exact handles and authenticated effect/receipt lineage.
6. The agent selects candidates through submit_output. MC validates/resolves, evaluates declared
   guarantees and records fulfillment/finalization. Observed is not selected; selected is not accepted.

Reverse/read/materialization path:

1. Authorized selection chooses exact source revisions under the receiver's input contract.
2. The application storage port resolves qualified native handles and retained observations.
3. One report-package extension is parameterized by binding/custody; report semantics are common.
4. Export exact retained body bytes or an admitted pinned deterministic representation; selected
   assertions preserve schema/lineage; evidence stays behind scoped resolvable handles as contracted.
5. Host materialization seals selection, purpose, required state, placement and resources.
6. The receiving backend stages files/authorized reads and records real delivery/readiness receipts.
7. Later use checks current eligibility. A successful read does not establish official-use approval.

The accepted design names `ApplicationStoragePort` and `ReportPackageExtension(binding, client,
custody)` in SP-10 §§4.1–4.8. Those sections contain proposed interfaces/pseudocode as well as accepted
semantics: inspect current implementation before promising a literal method/tool/path. Do not build
two unrelated report cores for PostgreSQL versus Neo4j. Future domain content such as courses can
use qualified extensions without adding domain-specific kinds to the MC kernel.

The port separates resolution, deterministic representation/export, availability/retention, exact
read and ingestion lineage. Resolving a declared input must not silently launch exploratory research
or model synthesis; those need their own admitted operation. A hook cannot bypass this separation.

### 6.3 What cannot be inherited across a workflow link

An output's bytes, producer identity, assessment and effect receipt may be selected and reused under
their applicability rules. The consumer retains its own actor, authority, audience/use, obligations,
budgets and current eligibility checks. Context transfer does not mint credentials, make the adopter
the author, repeat ingestion, satisfy every receiver obligation, or accept unresolved upstream work.
Explicit obligation adoption and effect ownership are distinct from reading the corresponding records.

Freshness, revocation and exact-use policy can invalidate reuse without changing historical bytes.
Preserve both the historical decision and current refusal. Do not silently reassign source provenance
to the consumer, downgrade required inputs, or substitute the newest native report for a sealed pin.

### 6.4 Extend the runtime through supported seams

ADR-0005 requires Deep Agents extension through public interfaces; a private SDK fork needs its own
minimized failing proof, alternative analysis and owner decision. MC middleware hooks described below
are local MC integration, not a claim about stock SDK shell hooks. Use source-backed lane projection.
Cross-domain reuse belongs in shared KS/common ports; native graph/SQL semantics stay in bindings.
Clean rebuild/schema migration permission does not waive durable recovery for the newly built system.

## 7. A common lens for every intra/inter-workflow boundary

"Context transfer" currently covers several different mechanisms. Keep them explicit in the
interview, the schema and the worked examples:

| Mechanism | What crosses the boundary | What proves it |
| --- | --- | --- |
| Authoritative workflow state | Active objective/configuration, obligations, accepted set, findings, waits, relevant effects and resources. | Host-owned records and exact revision/position, not outgoing-agent prose. |
| Selected content | Exact report/file/collection/member/references under named input contracts. | Sealed selection and lineage, required validation, representation and delivery/readiness receipts. |
| Workspace restoration | Declared exact snapshot/files and supported environment recovery. | As-of identity, retained bytes, backend accessibility; not a path copied into prose. |
| Conversation continuation | Qualified provider checkpoint/summary/history slice for the same logical work. | Lane-specific restoration and continuity checks; no automatic identity/permission change. |
| Semantic work continuity | Attributed summary of work, rationale, unresolved work and next actions. | Explicit profile/workflow requirement and its checks; OC-D137 requires the continuing GoalDirected default note. |
| Hook feedback/preparation | Event-scoped guard, observation, context cue or proposed preparation result. | Admitted capability and event-specific return semantics; not automatic output acceptance. |
| Coordinator observation | Bounded event/notice/status references, then optional selected content reads. | Durable notice/replay/ack and actual host wake/read; not notification equals model comprehension. |

For each boundary, walk all of these questions, using prior accepted answers where applicable:

1. Which logical identities remain the same, and which new run/activation/session/consumer starts?
2. Who selects exactly which revisions, members, state and history, under which activated contract?
3. What releases the receiver: execution completion, accepted goal, satisfied obligation, quorum,
   human decision, external event, published increment or another explicitly authored condition?
4. Which data is required, optional, degradable or prohibited for that purpose? Scheduling release
   and data readiness are different checks. A required draft for repair can be valid input.
5. What is inline, a readable sandbox file, a retrievable exact handle, a workspace snapshot or absent?
6. What access, native-use eligibility and assessment reuse are checked at materialization and use?
7. What consumes prompt/file/tool-result/generation budgets now and when the receiver reads later?
8. What survives crash, compaction, replay, source revocation, stale input, cancellation and restart?
9. What may be repaired deterministically, what needs new cognition, and what requires an authorized
   configuration change or human decision? What successful cognition/effects must not be repeated?
10. What does the coordinator see immediately, inspect on demand, and use to prove functional success?

This is an interview checklist, not a demand for ten owner answers at each boundary. Retrieve facts,
apply accepted defaults, and ask only consequential unsettled choices. Preserve a table showing
accepted, proposed, source-implemented and fixture-proven separately.

## 8. GoalDirected: settled behavior, source gaps and remaining depth

Detailed source map: [WORKFLOW-CONTEXT-HOOKS §2](WORKFLOW-CONTEXT-HOOKS.md#2-goaldirected).
MC source anchors were audited at `1863017c`; recheck when used after code changes.

| Source | What it establishes / does not establish |
| --- | --- |
| `mission-control-general/workflow-types/02-GOAL_LOOP.md:43–79` (deleted 2026-11-01; last at `66185d2e`) | Append-only attributed journal, sealed segments and bounded Loop State including prior summaries, findings, snapshots, blockers, cursor and governors. Raw transcript is not Loop State. |
| `08-CONTINUATION_COMPACTION_AND_TRANSFER.md:80–105` | Typed continuation checkpoint: exact identities/refs, current state, pending work/review, cursor, budgets/capabilities/invariants; deterministic reduction plus admitted semantic synthesis and validation. |
| `adapters/temporal/workflows/goal_directed.py:449–470` | Prepares iteration/session/workspace/latest handoff/feedback. Not full new accepted-set/profile composition. |
| Same `:530–545` | Sends latest executor output_refs to verifier. Gap versus whole current goal-set verification. |
| `application/context/pack_service.py:402–409,431–450` | Current verifier candidates provisional and nonmandatory; does not prove required exact review inputs. |
| Same `:642–658,682–687,690` | Handoff-derived Loop State, optional untrusted Progress Review and blockers. Must not substitute model narrative for canonical host findings/current set. |
| Same `:457–485,1292–1338` | Latest handoff artifact refs; admitted goal state versus untrusted model continuation/tactic suggestions. Preserve that trust boundary. |
| `domain/programs/goal_directed.py:280–281,741–754` | Historical ref union and latest execution terminal refs, not durable distinct accepted heads/count/coverage. |
| Same `:415–453` | Session/token rollover rules; not proof all new required fields survive compaction. |
| Same `:134–175` | Fork start-position validation; not complete new draft/current-set/adoption transfer. |

Already settled: current accepted/repair/history views; complete accessible current-set index;
independent work can continue during affected goal-scoped waits; whole-goal verification; exact
assessment reuse; new drafts do not erase accepted heads; copies/revisions do not multiply counts.

FC-Q22c/d are accepted as OC-D137/138. Continue with StageGraph next. Revisit the following GoalDirected
cases only if a genuine remaining choice arises, without reopening the common model or these defaults:

- Practical knowledge accumulated across iterations: source attempts, negative findings, unfinished
  analysis, semantic notes and journal retrieval. Separate host facts from attributed observations.
- A repaired B2 joins existing A1 and new C1; reassess changed requirements, reuse applicable A1
  evidence. A failed optional improvement may leave a still-valid accepted head; invalidation of the
  earlier head cannot be hidden by falling back to it.
- New authorized instructions change objectives/coverage or policies at a safe boundary. Explain
  which old work remains applicable and which becomes stale or no longer satisfies the revised goal.
- An iteration exhausts budget while one obligation is review-blocked. Preserve completed work and
  distinguish no-progress, unfulfilled goal, pending settlement and actual provider failure.
- Same-session iterations, within-invocation compaction, continuation into a new session and a fork
  are different boundaries/counters. A new session must not manufacture a new logical iteration.

Use a simple A/B/C illustration to expose behavior, clearly labelled as an interview example.
Do not call it the owner's real fixture or prematurely run it.

## 9. StageGraph: dependency-specific context transfer

The user explicitly asked for different dependency types. The next session must go beyond "stage A
passes a report to stage B." Normative source is
`mission-control-general/workflow-types/01-STAGE_GRAPH.md:31–64,85–167` (deleted 2026-11-01; last at `66185d2e`).

### 9.1 Current implementation limits

- Manifest `domain/authoring/manifest.py:707–756` accepts named inputs/outputs and all/any/quorum;
  validation at `:1548–1578` handles sibling/quorum/cycle constraints.
- Blueprint `domain/authoring/contracts.py:317–327,533–599` and interpreter `:163–224` distinguish
  required/degradable/optional/advisory dependency behavior. These are not the same dimension as
  required/expected/optional output obligations.
- Ordinary `domain/authoring/manifest_lowering.py:366–398` passes depends_on to StageGraphStageSpec;
  `stagegraph_builder.py:67–100` chooses the first producer output and hardcodes required/all.
  Parsed syntax therefore does not establish authored end-to-end behavior.
- `domain/authoring/mission_definition.py:621–643` retains named input declarations, but the
  scheduling/data-binding path still needs reconciliation. Verify exact module location if moved.
- Runtime result contracts `domain/programs/contracts.py:489–550` retain binding/release/lineage;
  interpreter `:1190–1201` emits `provisional=False`, not a complete provisional taint pipeline.
- No general typed conditional dependency expression is demonstrated in StageJoin/StageDependency.
  Event/human gates are not proof of the entire conditional branch contract.
- Static cycles are refused (`contracts.py:917–929`); readmission/invalidation
  (`interpreter.py:526–604,673–720`) does not prove arbitrary bounded Revisit Regions.
- Dynamic fan-out templates, stable member identity and bounds are normative requirements, not
  proven ordinary execution. Run-wide KS report selection remains RV-03 independently of scheduling.

### 9.2 Recommended interview progression: FC-Q23 subquestions

These are **proposed topics/recommendations**, not owner decisions yet:

1. **Relationship and mapping.** Separate ordering-only dependency, named data input, evidence/use
   prerequisite, required authoritative state and workspace reuse. Do not invent new enum variants
   merely to name them. A dependency arrow must not implicitly load every upstream output or sandbox.
2. **All / any / quorum.** Which exact eligible members release a consumer, at what cutoff and stable
   order? What happens to slow siblings, their spend and effects, late accepted results and cancellation?
   A quorum over outputs is not necessarily a quorum over branch execution completions.
3. **Optional/degradable/advisory.** What absence/degradation is visible and what can satisfy the input?
   A scheduling fallback cannot waive hard official-use or required-content constraints.
4. **Incremental publication.** Accepted default waits for producer completion. An explicit incremental
   trigger needs count/coverage/publication criteria, exact immutable receiving selection and a rule for
   future increments. Do not mutate a running receiver's sealed selection behind its back.
5. **Revision after consumption.** Tracking/staleness is settled. Determine concrete reaction at a safe
   boundary: bounded revalidation, rerun/successor, or durable review. Preserve exact prior consumption
   and reconcile existing effects. Ask behavior, not whether revision tracking should exist.
6. **Conditional branches.** True/false/unknown, unavailable evidence, no satisfiable branch and else
   behavior. Keep deterministic admitted predicates distinct from an agent's suggested condition.
7. **Provisional/held input.** Explicit repair/review can need required draft bytes. How provisional
   status propagates through derived results, how it clears, and which effects remain forbidden must
   be concrete; "file readable" does not clear the hold.
8. **Collection fan-in and retrieval.** Complete set versus explicitly bounded subset, distinct identity,
   declared coverage, exact accessible membership index and budget failure. No silent truncation of a
   required collection because a first file happened to fit.
9. **Cycles/dynamic expansion.** Scope and identity of revisit regions and fan-out; accumulated versus
   cycle-local obligations; stable lineage, bounded growth and independent branch waits. If the owner
   wants scope different from prior accepted contracts, record an explicit revision, not a silent deferral.

A useful worked chain is multiple company/study investigations → synthesis → review/native ingestion.
Use it only as a discussion aid until the real fixtures arrive. Show the author declarations, next
executor's actual input index/context, and coordinator inspection at each chosen dependency.

## 10. Linked Workflows and nested composition: explicit new frontier FC-Q26

The owner has added this by name. **Do not defer it as an implementation detail or assume StageGraph
answers settle it.** Keep existing question numbers: FC-Q26 covers this new branch; it can be discussed
after StageGraph and before hooks. Final FC-Q15 waits for it.

### 10.1 Six boundaries to disambiguate using existing contracts

| Boundary | Governance and transfer |
| --- | --- |
| Nested ProgramNode/subworkflow | Same mission objectives; each node has typed inputs/outputs. Composite outputs require an explicit projection; nested intermediates are not automatically exported. |
| Child Mission Invocation | Independent mission goals, authority, budget, owner, lineage and completion. Immutable input bindings, explicit await/track/detach. Parent portal exposes bounded identity/status/projected refs/blockers/budget, not full transcript or bodies. |
| Linked run | Runtime composition link involving independently admitted child execution. Classify its intended public semantics; the runtime label is not automatically a new public workflow type or always a Child Mission Invocation. |
| Mission Chain | Independent missions, each revision/run/budget/acceptance; no wrapper mission/shared mutable state. supplies binds named outputs to inputs; depends_on is ordering only. |
| Continuation/fork | Continuation preserves logical execution while changing agent session; fork creates derived identity/lineage. Exact selected checkpoint/artifacts, no automatic history/grant inheritance. |
| Provider subagent | Bounded subordinate of an operation, not automatically an independently governed mission. Scoped binding/grants/budget/cancellation/output/late-result rules; ordinary helper obligations optional. |

Verified source anchors from the handoff's read-only linked-workflow audit:

- `mission-control-general/general-mission-control/SPECIFICATION.md:138–150,218–220` (deleted 2026-11-01; last at `66185d2e`);
  `workflow-types/00-EXECUTION_PROGRAM_MODEL.md:113–117`; `01-STAGE_GRAPH.md:24–27`.
- `workflow-types/06-MISSION_INVOCATION.md:17–35,54–74,90–98`: independent goals, binding, modes and
  bounded portal; child success is evidence for parent acceptance, not automatic parent acceptance.
- `general-mission-control/RUNTIME-CONTRACTS.md:27`: public terminology warning around linked runs.
- `domain/composition/contracts.py:26–62,86–137`: independent request/budget/dependency/authority and
  exact result admission; late results cannot mutate a terminal parent.
- `domain/composition/chain.py:110–165`; accepted ADR-0029: chain kinds, release/cancel and typed binding.
- `workflow-types/08-CONTINUATION_COMPACTION_AND_TRANSFER.md:17–38,80–105`: continuation and checkpoint.
- IA-06 OC-D56: receiving mission keeps authority/goals/budget/obligations, unfinished work needs explicit
  adoption. OC-D100 carries common transfer machinery across linked boundaries.

### 10.2 Fresh source findings: useful mechanisms, important gaps

| Source | Finding and implication |
| --- | --- |
| `application/chains/packet.py:84–95` | match_supplied uses filenames/stems/path segments; a single binding can fall back to every accepted artifact. This is weaker than accepted exact obligation/output selection and can admit unrelated outputs. Repair under existing policy; no new broad-selection approval needed. |
| `domain/composition/chain.py:133–165` | ChainBinding has output/input/schema/expansion; full member/revision/use/readiness/retention/alternative semantics still need canonical profile/plan compilation. |
| `application/chains/packet.py:191–208` | Packet names binding from producer mission key and output name; input_name is not visibly used in that loop. Verify receiver alias mapping before claiming named input delivery. |
| Same `:1–10,212–220,243–270` | Carries supplier disposition and checkpoint/journal refs; not supplier workspace restoration. Registered artifact content remains distinct from authoritative state. |
| Same `:178–197,214` | Execution-complete supply may be provisional; current provisional supplies become nonmandatory. Required repair-input delivery must remain separate from accepted/official-use status in the new contract. |
| `application/programs/linked_runs.py:262–295` | Child compiles/admits independently and gets input manifest. This alone does not prove new receiver transfer-profile resolution/delivery. |
| `bootstrap/worker.py:565–569`; `adapters/temporal/linked_run_activities.py:69` | Linked-run service is wired in worker composition. Older statements that no production caller exists are historical. Wiring is still not functional qualification. |

The audit is source evidence only. No linked workflow was executed during this handoff.

### 10.3 Deep questions to resolve with concrete examples

Do not ask the owner again whether exact revisions, own authority or explicit mappings matter; those
are settled. Use these cases to determine the remaining operational policy and authoring experience:

1. **Composite projection.** A nested GoalDirected unit accumulates three reports but its enclosing
   stage promises a synthesis. Which outputs are exposed as the composite result? Recommend explicit
   projection, with supporting reports available only through declared collection/reference inputs.
2. **Launch versus result readiness.** A parent tracks a child, accepts that it started, and later needs
   its report. Recommend a separate result-ready dependency/wait and exact content transfer; successful
   launch cannot satisfy required content. Walk pending, blocked, cancelled and detached child outcomes.
3. **Cross-family mapping.** GoalDirected → StageGraph, StageGraph → GoalDirected, and nested swarm or
   evaluator/optimizer → enclosing workflow. Which outer obligations receive which exact inner outputs?
   Where are nonterminal progress and the final projected result exposed?
4. **Complete/incremental/repair release.** A chain can release at execution completion even when
   acceptance is held. A repair consumer may require those exact bytes; official-use consumer must
   still wait/refuse. Make authored purpose and delivery necessity explicit rather than discard input.
5. **Any/quorum across linked missions.** Who chooses qualifying outputs and owns slow siblings,
   cancellation and unsettled liabilities? Reuse StageGraph policy where semantically appropriate,
   but preserve independent mission budgets/authority and immutable result admission.
6. **Revisions after receiver starts.** A1 has been consumed when A2 is accepted. Tracking/staleness is
   settled; choose the authored reaction for the example: revalidation, successor run or review wait.
   Do not rewrite A1's run history or silently repeat downstream native effects.
7. **Incomplete upstream mission and adoption.** Valid A1/B1 may be reusable even if C remains missing.
   Exactly which unfinished promise, if any, transfers to the receiver? Record explicit adoption,
   scope/authority/budget, original disposition and liability; a link alone transfers none of these.
8. **Workspace/history.** Does the receiver need only report bodies, a selected source corpus, exact
   working files, journal slice, or qualified cognition restoration? Defaults remain history-off and
   selected content. No automatic copying of source workspace/credentials/transcript.
9. **Dynamic instructions and link revisions.** Which configuration revision applies to an already
   waiting link, an already materialized receiver and a future successor? Preserve sealed plans and
   commands; apply changes through admitted safe-boundary policy, not submit_output or hook text.
10. **Cross-application links.** If desired, determine explicitly whether supported within this sprint.
    Shared code is not cross-application access. Receiving grants, native bindings, use policy and
    provenance need independent admission. Do not presume AI Engineer and Biotech data can freely mix.
11. **Durable release and recovery.** Transactional outbox/replay, duplicate signals, missing retained
    bytes, revoked use, source cancellation and late results. Which affected link waits, which independent
    work proceeds, and how is reconciliation exposed without rerunning successful cognition?

These are a frontier bank, not eleven simultaneously unanswered owner questions. Inspect prerequisites,
reuse settled policies, and ask focused batches. Preserve whatever vocabulary the owner prefers while
mapping it precisely to the six actual boundaries above.

## 11. Deep Agents hooks: exact lifecycle, state access and context effects

The owner believes a script such as .sh can run after selected lifecycle events and wants to know
which events, why, and whether hooks should participate in accumulation/transfer. That is a real
design branch, not a request for a generic hooks tutorial.

### 11.1 Verified current local behavior

Pinned/installed Deep Agents is **0.7.5** in this checkout (`uv.lock:1012–1013`). These are **MC's
middleware hooks**, not a statement about the latest upstream SDK. Read ADR-0026 and
[WORKFLOW-CONTEXT-HOOKS §4](WORKFLOW-CONTEXT-HOOKS.md#4-deep-agents-executable-hooks).

- `domain/authoring/contracts.py:1847–1890`: catalog bundle/digest, entrypoint, interpreter, events,
  matcher, timeout, fail-closed and effect class. sh/bash/Python/Node listed in
  `domain/capabilities/hooks.py:58–62`; a filename extension does not install a shell.
- `adapters/deep_agents/hooks.py:124–180`: subprocess JSON stdin/stdout, scrubbed environment, timeout.
  `materializer.py:554–631`: script bundle verified into private `mc-hooks-*` directory; hook cwd and
  workspace_root point there, **not automatically to agent sandbox or state backend**.
- `contracts/hooks.py:35–77`, adapter `:630–651`: bounded event input with run/activation/attempt/
  generation/execution/session, optional tool args/result/error, event details and callback. No full
  messages, complete ledger, transfer plan or all workspace files by default.
- Four fixed kernel hooks precede user/catalog scripts: stop fence, operation intent, frame capture,
  usage (`domain/capabilities/hooks.py:402–422`, adapter `:664–690`). Denial can short-circuit.

| Event group | Current behavior / limit |
| --- | --- |
| session_start, before_prompt, before_model | Pre-model events inferred from message shape. additional_context appends a HumanMessage (`hooks.py:815–848`). This trust/accounting behavior needs explicit design attention. |
| after_model, stop, session_end | Post-response denial path; additional_context ignored (`:851–888`). stop/session_end are final-response classification, not durable operation settlement or mission completion. |
| before_tool, before_shell, before_mcp, subagent_start | Guard/argument update before tool path. Subagent events wrap task tool (`:776–795`), not all asynchronous child lifecycles. |
| after_tool, after_tool_failure, after_shell, after_file_edit, subagent_stop | Observe completed tool work; cannot undo committed effect. Tool-path additional_context appends ToolMessage (`:902–914`). |
| before_compaction, after_compaction | Observations and summary/cutoff metadata. Returned HookResult discarded (`compaction.py:219–220,240–280,297–298,315–316`); no current summary replacement/transfer rewrite through return. |

Mapped enforceable: session_start, before_prompt, before_model, after_model, before_tool, before_shell,
before_mcp, subagent_start, stop, session_end. The remaining listed events are observe-only
(`domain/capabilities/hooks.py:151–174`). Generic HookResult supports allow/deny/defer, reason,
updated_input, additional_context, message/follow-up; merge deny > defer > allow, bounded concatenation,
last updated_input wins (`contracts/hooks.py:80–166`). **A result field existing does not prove every
event consumes it.** Fail-closed/timeout/malformed output and retained invocation frames must be scoped
to actual consumers. Do not promise defer, context injection or veto uniformly at every event.

### 11.2 Unsettled FC-Q24 branches

Proposed direction to discuss, not accepted design:

1. Separate **in-operation lifecycle hooks** from **durable workflow-boundary reactions** to submitted,
   assessed, fulfilled, delivered, review-resolved and settled events. The latter cannot be implemented
   merely by treating provider stop as completion.
2. Determine permitted jobs: guard/check, log/projection, deterministic preparation, refresh a bounded
   input index, propose semantic-memory update, or schedule an admitted preparation operation.
   Hook-created files/context cannot self-seal a transfer, accept a report or grant official use.
3. Define a bounded versioned event-state projection and scoped read capabilities. If a script needs
   exact workspace files or KS records, specify backend mediation, authorization, budgets and receipts;
   do not quietly give access to private middleware state or assume its temp cwd is the agent sandbox.
4. Context accumulation: which observations become attributed journal entries/candidate artifacts,
   who validates/selects them, when they enter the next receiver and how duplicates/stale generations
   are handled. Distinguish a preparation proposal from a canonical workflow transition.
5. Compaction: observation-only versus an admitted proposal before host validation; required state
   retention and semantic continuity must remain provable. Do not let arbitrary hook prose replace
   authoritative objectives, obligations, pending liabilities or selected revision pins.
6. Event-by-event response semantics and trust: allow/deny/defer/input patch/context payload, size and
   model-context accounting, read-only observer behavior, failure/retry and recursion limits.
7. Side effects: deterministic idempotent local preparation versus admitted external effect, unique
   invocation/effect identity, reconcile-before-retry, cancellation and late hook completion. After-tool
   failures cannot erase a native commit; avoid double-submission or repeated cognition.

Use concrete authored hook examples and show input, output, observed state, timing and resulting
Transcript evidence. Clearly label pseudocode versus actual supported configuration.

## 12. Coordinator: on-demand outputs and subscriptions

The owner explicitly asked whether output submission reaches the coordinator through on-demand tools
and automatically as subscriptions. Broad answer already accepted: **both inspection and durable
notifications**, with actionable changes waking by default and routine traffic batched. Precise
payload/context behavior remains FC-Q25.

Current anchors:

- `application/subscriptions/coordinator.py:68–96`: accepted_output and actionable kinds.
- Same `:122,193–244,692`: scalar classification facts and bounded event references; reference-only
  rendered notification, no full report body. Generic accepted_output does not prove every new
  submission/assessment/fulfillment/transfer transition is wired.
- `application/coordinator/coordinator_results.py:61–180`: terminal typed result read; not complete
  progressive accepted-set/output inspection.
- `application/subscriptions/coordinator_service.py:1–25`: durable inbox machinery. Chosen host must
  prove actual wake, replay, ack, duplicates and cancellation. Do not claim an idle Codex chat will
  wake simply because an inbox row exists. ADR-0049 remains proposed, not accepted by this interview.

Pending detail: subscribable submitted/assessed/fulfilled/use-admitted/delivered transitions; exact
notice IDs/source revisions/status/gaps; explicit body retrieval under coordinator authority and
budgets; admitted inline alternatives; when a wake becomes a model-visible turn; event selection and
ack semantics on reconnect. Preserve persisted notice, wake hint, delivery, acknowledgment, wait
result and content retrieval as separate facts. Avoid implicit full-body expansion on every event.

## 13. Known runtime gaps: keep requirements separate from proof

The readiness review's RV labels are preserved in [CONTRACTS §13](CONTRACTS.md#13-sprint-v-conformance-and-required-proof).
The source findings
below are not instructions to implement during the resumed interview.

| Item | Verified baseline / required consequence |
| --- | --- |
| RV-01 | MC `adapters/deep_agents/adapter.py:280` discards knowledge.complete finalization report. Save successful provider result and durably block/reconcile post-execution settlement before first applicable write fixture; do not replay successful cognition. |
| RV-02 | Bounded repair exists: `application/outputs/submission_service.py:258,477–483` rejects unsupported collection/mixed/duplicate report selection. Full per-member collection assessment/fulfillment remains W3 work. Do not report this as entirely unfixed or fully solved. |
| RV-03 | `application/knowledge/toolset.py:376` selects run-wide finalized reports. Compile exact selected predecessors/output members, excluding unrelated siblings/stale generations. Evaluator isolation needed before W1; full stage transfer before W2. Chain filename fallback is another realization gap. |
| RV-04 | `bootstrap/composition.py:588` in-memory decisions with no production populator found. KS host switch lacks the whole trusted semantic ingress/seal/decision/review route. Interfaces and durability precede report-use claims. |
| RV-05 | `toolset.py:392–405` aggregate file-byte preflight and decreasing allowance repaired a bounded part. `application/context/delivery.py:140` token budget absent. Unified prompt/file/reserve/access/readiness accounting remains. |
| RV-06 | Shared KS `packages/host/src/knowledge-operation/service.ts:606–618` native apply precedes protocol receipt. Prove crash-after-commit recovery by same effect identity without duplicate writes before first native-write claim. |
| RV-07 | Documentation correction only; preserve historical versus fresh evidence and pin inventory. |
| RV-08 | Same KS service `:497–578` operational report read is not native/current official-use proof. Separate permitted review/repair from official eligibility, lineage and required readback. |

Other crucial existing seams:

- MC common release 1.6.0 has output_submission and invocation_finalization, not durable
  obligation_fulfillment. Existing context_selection and delivery plans overlap. New records need
  exact identity/revision/digest joins, receipt replay and schema-fit review.
- Existing MC human_task/human_resolution (`component/migrations/0005_commands_effects_recovery.sql:206–248`)
  and versioned human gates are reused with typed KS decision bindings; no second generic human-task
  system is assumed.
- KS has assertion kinds, observation/seal/use-decision/reviewer grant primitives, but judgment
  contract/policy additions and trusted production composition remain. Current official-use gate
  still follows old fact-entailment exclusion until the new judgment path is implemented.
- AIDB projection/normalized intent guards are in migrations `20261024010100` and `20261025010200`.
  BKS authored v2.2.0 SDL includes recommendation speech act and KS refs. Preserve judgment versus
  verified-fact semantics in both native projections. Edit authored authority, not pinned output.
- Existing source release pins from Sprint V: shared verification component 2.4.0, MC 1.6.0, BKS
  v2.2.0, AIDB migration head above. Recheck installed disposable schemas later; source presence is
  not installation or end-to-end proof. Never reserve a future version from this handoff.

Current detailed schema-fit inventory is CONTRACTS §8. Scope covers MC common SQL, shared KS component
and core, AI Engineer DB contract and BKS native graph. Historical SP-10 migration sections contain
old names/version assumptions; they are provenance, not permission to edit missing biotech-meta or
generated pinned releases.

## 14. Real-fixture qualification and the six-wave scaffold

Accepted OC-D128 explicitly amends SV-D12: bounded real fixture qualification may happen at progressive
checkpoints when prerequisites are ready. Routine research/general use remains gated on all four
workflow systems, output/context contracts and full Deep Agents qualification for both applications.

| Wave | Accepted capability/proof progression |
| --- | --- |
| W0 | Prerequisite schemas, trusted service interfaces, required settlement/recovery barriers. |
| W1 | One GoalDirected report; first real workflow fixture through applicable actual knowledge paths. |
| W2 | Exact two-stage transfer. |
| W3 | Multiple reports, accumulation, collection and synthesis. |
| W4 | Advanced recovery, revisions, review and linked reuse. |
| W5 | Remaining workflow systems/compositions and full Deep Agents qualification. |

This is not a rule that review, native reconciliation or budgets can wait until W4. Basic durability,
access, aggregate budgets, required review and native-effect recovery precede their **first use**.
Expanded linked/hook choices may change the detailed work/dependency mapping. Do not silently change
accepted scope or force actual fixtures into the wave names.

At every applicable checkpoint: AI Engineer first, then Biotech; real agents and actual required
acquisition/ingestion/retrieval; retained Mission Transcript, exact inputs/outputs, receipts, independent
review and declared functional criteria. Missing/ambiguous evidence blocks. Fix schema, code, service,
protocol, prompt/configuration, lifecycle or materialization as necessary and rerun before advancing.
Synthetic/scripted tests diagnose problems; they do not replace the functional gate.

A separate reviewing agent assesses evidence. The implementation coordinator records pass only if
every required criterion is met. Escalate unresolved goals and required human decisions; an individual
fixture may require owner release. This engineering gate does not replace KS permitted-use decisions
or consequential scientific human review. No fixture was executed in this interview/handoff.

## 15. Remaining conversion work after the decision frontier closes

Do not tell the owner the interview is nearly done based solely on answered question count. Shared
foundations are settled; detailed GoalDirected, StageGraph, linked/nested composition, hook and
coordinator branches remain, followed by an integrated worked-model confirmation.

Required completion work:

1. Finish FC-Q22..26 and any genuinely dependent new questions; preserve explicit revisions to older
   answers. Revisit remaining swarm/evaluator-optimizer/subordinate composition boundaries as needed
   for the promised four-workflow scope, without reopening unrelated special-tool design.
2. Update CONTRACTS into one coherent final pack, not a stack of contradictory appended proposals.
   It currently contains §12 records/service/recovery, §13 RV placement, §14 old dispositions,
   §15 illustrative author/agent/operator walkthrough and §16 new detailed round.
3. **WORK-ITEMS.md does not yet exist in this sitting's directory.** Create the complete work/dependency/
   owner/proof matrix after scope settles; include prerequisite schema work and actual runtime gaps.
   Reuse relevant existing accepted work rather than duplicate Sprint V A0/A/B/C/D.
4. Fold CONTRACTS §14's **OC-D1..26** dispositions into the old Deep Agents session document, retaining
   original quotes/history. That full table currently exists only in the new contract.
5. Preserve **CS-D1..14 as coordinator-surface decisions**, not fourteen transfer fields. Focused node,
   output/fulfillment/plan/receipt/events accepted; global CLI grammar, bundles/scripts/provider-sheet
   upkeep/Socket.IO CLI/legacy API retirement/HTTP cleanup deferred. Full disposition is CONTRACTS §14.
6. Disposition/promote/merge the local ADR candidates **DC-OBL, DC-APP, DC-XFER, DC-KOP, DC-ACT, DC-BIND,
   DC-ROLES** from IA-06/IA-07. Highest canonical ADR found was 0057; recheck before allocating. No new
   canonical ADR has yet been created for this sitting. Do not invent acceptance of proposed ADR-0049.
7. Refresh glossary terms where decisions truly settle language; Output Form and Obligation Fulfillment
   were already added. Do not put implementation fields into glossary definitions.
8. Present an integrated **author / agent / operator** worked model, including first invocation,
   accumulation, exact transfers, nested/linked boundaries, review, errors, cancellation/recovery,
   hooks, and coordinator observations. Label proposed syntax. Ask final **FC-Q15** confirmation only
   when the frontier is empty. Existing §15 is expressly a draft, not owner-approved final syntax.
9. Convert accepted work to Linear per the invoked skill and `docs/agents/issue-tracker.md`; inspect
   existing issues/comments/relations first. No issues were created or changed this sitting. Existing
   OVE-160/161 bounded repairs must not be duplicated or closed based on stale summaries.
10. Complete Becomes/Folded destinations and checklist; mark answers final only when actually converted.
    Then integrate the exact owner fixtures as instructed, without invented substitutes.

Potential work groups considered earlier (planning only, not accepted tickets): four-owner schema
fit and migrations; trusted KS semantic/judgment/review interfaces; native effect/receipt recovery;
MC durable settlement/review; independent evaluator operations; submission/fulfillment and accepted
sets; common profile/materializer; StageGraph release/mapping; collections/accumulation; revisions/
reuse/adoption; linked/nested/continuation recovery; focused coordinator inspection/errors/wake;
fixture evidence gates; remaining workflows and full Deep Agents/both-app qualification. The expanded
hook/link discussion may refine these. Do not treat this list as the final sprint scope or issue titles.

Necessary cross-layer fixes remain in scope. Broader coordinator redesign, special helper tools/shape,
physical topology and global refactor remain deferred unless the owner explicitly revises that scope.

## 16. Suggested next-session subagent plan

Owner expressly permits GPT 6 Astra. Use `gpt-6-astra` when available; if the requested model is not
available, disclose that instead of claiming it ran. With three helper slots, keep assignments narrow
and outputs compact. Share the absolute handoff path and exact question, not the whole transcript.

Recommended independent discovery tasks:

- **Workflow boundary explorer:** GoalDirected/StageGraph current code versus accepted contracts;
  exact intra-workflow selection/release/readiness gaps relevant to the imminent question.
- **Linked composition explorer:** nested nodes, Child Mission Invocation, linked-run service, chains,
  input/output projections, outbox release and receiving authority. Start with §10, verify drift.
- **Hook/KS boundary explorer:** pinned event consumers, script state/backend access, proposed context
  preparation seam and which capabilities belong in KS versus MC. Research upstream only when needed.

Ask each for: exact file:line evidence, implemented versus proposed, prior accepted decisions to avoid
re-asking, a small list of genuine unresolved product choices, and proof implications. Read-only unless
the primary explicitly assigns a disjoint documentation edit. Do not let helpers launch fixtures,
create issues, update schemas or ask the owner competing interview questions.

Old agents `accepted_frontier`, `mc_readiness`, `verification_path` were GPT 6.1 Sol source explorers.
Their durable useful findings are in CONTRACTS and WORKFLOW-CONTEXT-HOOKS; the linked audit is now §10.
Their presence/status is not needed to resume. If source research is external, verify primary sources
and version/date applicability; do not mistake latest upstream capabilities for this pinned lane.

## 17. How to maintain the checkpoint without another context blow-up

- Record each answer immediately, fold its normative consequence, update pending assumptions, then
  update the ledger/current checkpoint pointer. Keep the verbatim owner quote separate from your reading.
- Do not dump entire answer tables repeatedly into tool output. Search IDs/headings, read bounded
  slices and use source maps. Delegate discovery, not decision ownership.
- Use one concise progress orientation when asked: foundational contracts/proof policy settled;
  workflow-specific transfer/hook details and final conversion remain. Avoid invented percentages.
- Keep exact task examples separate from the owner's eventual fixtures. Preserve real goals even if
  they require schema migrations or changes across all four owners.
- Recheck accepted versus unresolved before each question. No response, a session change or a code
  default is an owner decision. Do not finalize because the transcript is long.

Documentation checks, run from the MC repository after edits:

```powershell
.venv/Scripts/python.exe docs/tools/agents_docs_index.py
.venv/Scripts/python.exe docs/tools/check_docs.py
git diff --check
```

The index command is required after adding this document. check_docs covers OKF, compiled index,
three program ledgers, links and shipped skill manifests. Documentation-only handoff does not need
runtime tests or provider calls. State actual results; passing docs checks does not qualify behavior.

## 18. Stop/resume state and next-session launch text

This handoff is the requested deliverable. The interview is intentionally open at the owner's request.
FC-Q22c/d are accepted as OC-D137/138; StageGraph details, FC-Q26 Linked Workflows, hooks, coordinator delivery,
integrated confirmation and final conversion remain. Exact fixtures are still owed **after** the
interview. Nothing in this handoff authorizes implementation or claims runtime qualification.

Suggested prompt the owner can use in a new session:

> Continue IQ-07 from platform/mission-control/docs/specs/provider-consolidation-2026-10/answers/output-contracts-final/codex-gpt-6-2026-10-25/INTERVIEW-HANDOFF-2026-10-26.md. Read it and the current answer/contract records through OC-D138. The GoalDirected progress-note and repair-fork questions are answered; do not re-ask them. Begin detailed StageGraph and linked/nested workflow context transfer, then Deep Agents hooks and coordinator retrieval/subscriptions. GPT 6 Astra discovery subagents are permitted. Keep this an interview; preserve MC/KS/domain boundaries and record every answer. I will provide the real fixtures at the end.

Handoff verification, 2026-10-26:

- GPT 6.1 Sol performed a separate read-only review of pending-question fidelity, fixture timing,
  accepted versus proposed claims, linked/intra/inter scope and MC/KS/domain boundaries. Two source
  navigation corrections (mission_definition location and StageGraphStageSpec type name) were applied.
- The compiled AGENTS documentation index was regenerated successfully (16220 bytes).
- `docs/tools/check_docs.py`: **7 passed, 0 failed, 0 unrun**: OKF, compiled index, three program
  ledgers, relative Markdown links and shipped skill manifests.
- `git diff --check` passed. Answers, instrument, contract, prior-checkpoint pointer, source audit
  and ledger point to this handoff. The subsequent OC-D137/138 update records Q22c/d as answered,
  preserves their exact wording and moves the next-session starting point to StageGraph.
- Runtime tests, database migrations, provider calls, real fixtures, issue mutations, commits and
  pushes: **not performed**. This verification covers the documentation handoff only.
