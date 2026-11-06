---
type: Working Draft
title: "Concept lists per codebase: every concept by category, its live status and its first question"
description: "Input 4 for sitting II (Q3 to Q7): for Mission Control, Knowledge Services, Biotech Knowledge Services and AI Engineer, one row per existing and proposed concept with its category, status against the live sprint-oc tree (covered, partial, missing), proposed questions[0], aliases and the documents it would fold in; plus merge candidates, oversized concepts, categories over twelve and a depth note for Q7."
tags: [agents, sdlc, knowledge, categories, draft]
date: 2026-11-01
status: draft
---

# Concept lists per codebase

Prepared from [DOC-01](INFORMATION-CATEGORIES-DRAFT-2026-11-01.md) for
[sitting II](INTERVIEW-NAVIGATION-AND-KNOWLEDGE-2026-11-02.md) item 4, so that Q3 to Q6 are edits.
The frontmatter rule is SPEC-01 §3.3 rule 1 (`SPEC-01-AGENTIC-SDLC.md:125-127`): `type: Concept`,
`category`, `title`, `description`, `tags`, `aliases`, `questions`; at most 160 lines; a Citations
section. Read on 2026-11-01 from the `sprint-oc` checkouts of Mission Control, Knowledge Services,
Biotech Knowledge Services and `ai-engineer-db-contract`, and the `main` checkouts of
`research_starter_pre_research_agent` and `ai-engineer-meta`. Nothing was edited except this file.

**Status.** **covered**: the concept file exists and cites source (the cell gives its line count
and the line of its Citations heading or `sources:` key). **partial**: the facts exist in the
named documents but not as a concept. **missing**: nothing authored. **n/a**: the index carries a
`not applicable` line. Where this draft disagrees with DOC-01's placement, the row says so.

**Questions.** `questions[0]` is the question an agent would type that this concept answers
(70 characters or fewer). Knowledge Services concepts already carry questions; the row keeps the
first one unless a better one is proposed. **Group** is a proposed index sub-heading for a
category over twelve concepts (see [Findings](#findings-for-the-owner)).

## Mission Control (`platform/mission-control/docs/knowledge/`)

The directory holds 66 Markdown files: **64 concepts** plus `index.md` and `log.md`. All 64 cite
source in a `# Citations` section. **None** has `category`, `aliases` or `questions` (every
frontmatter is `type, title, description, tags`, plus `date` on six). Nine have a `type` other
than `Concept`: `architecture.md` and `persistence.md` (Architecture Reference), `capabilities.md`,
`execution.md`, `lifecycle.md`, `precise-fork.md`, `recovery.md` (Workflow), `operations.md`
(Playbook), `qualification.md` (Verification Reference). `placement-admission.md` has no `tags`.
None is over 160 lines; twelve sit exactly at 160. DOC-01 placed 38 of the 64; the other 26 are
placed below for the first time.

| Category | Concept (file) | Status | Proposed `questions[0]` | Aliases | Folds in |
| --- | --- | --- | --- | --- | --- |
| boundaries | `architecture.md` | covered (38; :33); type Architecture Reference | Which module owns this code and where does my change go? | source ownership; module map; layering | `src/mission_control/AGENTS.md` pointers |
| boundaries | `knowledge-services.md` | covered (160; :128) | What does Mission Control own and what does Knowledge Services own? | KS boundary; knowledge gateway; K01 transport | `docs/specs/provider-consolidation-2026-10/sprint-oc/APPLICATION-PORTS.md` |
| boundaries | `application-profile.md` | covered (90; :73); new placement | What may differ per application and where is it declared? | application.toml; Application Registry; per-app profile | — |
| surfaces | `interfaces.md` | covered (160; :135); DOC-01 also listed it under boundaries | Which HTTP routes, CLI verbs and MCP tools exist today? | public API; missionctl; coordinator MCP | — |
| surfaces | **`coordinator-surface.md`** (new) | partial: `docs/specs/coordinator-surface-2026-10/PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md:3-4` (inventory), `:259` (noun-verb grammar), `:445` (router description); `skills/mission-control/SKILL.md:3` | How does a coordinator agent drive Mission Control end to end? | mission-control skill; missionctl grammar; skill router | the proposal; `skills/mission-control/` and the five `skills/mission-control-*` sub-skills; CLI section of `interfaces.md` |
| surfaces | `events-and-commands.md` | covered (159; :133); new placement | How do mission events leave the ledger and reach subscribers? | outbox; SSE subscriptions; command receipt | — |
| surfaces | `mission-stream.md` | covered (160; :154); new placement | How do I subscribe to and replay a mission over Socket.IO? | /missions namespace; realtime stream; replay cursor | — |
| surfaces | `unit-and-point-joinability.md` | covered (56; :44); new placement | How do I join an event to its unit and cognition point? | unit_key; point_ref; resume from point | — |
| surfaces | `wake-channels.md` | covered (79; :75); DOC-01 put it in execution | How is an orchestrating agent woken when its run needs it? | missionctl wait; inbox long-poll; operator MCP | — |
| surfaces | `coordinator-attention.md` | covered (133; :129); new placement | Did the coordinator actually see this notice, and when? | coordinator inbox; delivery stages; notice ack | — |
| surfaces | `signal-ingress.md` | covered (159; :153); new placement | How do external signals and webhooks enter Mission Control? | webhooks; trust tiers; ingress inbox | — |
| surfaces | `selection-workspace.md` | covered (53; :47); new placement | Which lane, model and capabilities should this node use? | selection check; resolution seam; ranked search | — |
| surfaces | `capabilities.md` | covered (148; :133); type Workflow | How do I pin, search or project a skill, MCP server or hook? | capability catalog; bundle custody; host projection | — |
| surfaces | `capability-seeds.md` | covered (89; :71); new placement | Which MCP servers, skills and hooks are seeded today? | seed bundles; router skill bundles; blockers B2-B4 | — |
| domain-model | `mission-manifest.md` | covered (159; :128) | How do I write, compile and start a Mission Manifest? | mission/v2; manifest YAML; compile submit start | — |
| domain-model | `authoring.md` | covered (148; :126); new placement | How does a mission go from description to an explicit start? | launch path; coordinator authoring; start_unavailable | — |
| domain-model | `revisions.md` | covered (115; :103) | How does a definition become an immutable revision? | scheduling head; proposal activation; compiled program | — |
| domain-model | `lifecycle.md` | covered (73; :65); type Workflow | How is a run admitted and its lifecycle controlled? | run admission; request scope; command effects | — |
| domain-model | `mission-chains.md` | covered (126; :102) | How does one mission release the next and transfer state? | chain links; chain reducer; mission chain | — |
| domain-model | `completion.md` | covered (144; :129) | Is this work complete, valid, accepted or admitted? | acceptance; seven completion facts; run settlement | — |
| domain-model | `output-contracts.md` | covered (160; :149) | How are named output promises submitted, assessed and fulfilled? | output promise; exact context transfer; WI-01 | — (the annex `mission-control-general/general-mission-control/OUTPUT-CONTRACTS.md` stays cited) |
| domain-model | `human-gates.md` | covered (160; :129) | How does a Human Gate open, resolve or deny a human task? | human task; approval broker; governed effect | — |
| domain-model | `interventions.md` | covered (140; :109) | How do I queue an instruction, inject, or cancel a run now? | command mailbox; Stop Fence; request_continuation | — |
| domain-model | `model-catalog.md` | covered (132; :116); new placement | Which models exist and which lane can route each one? | Model Profile; models.toml; model routes | — |
| domain-model · group `workflow-systems` | `workflow-systems.md` | covered (160; :140); new placement | Which workflow systems exist and which does the code run? | Stage Graph; Goal Loop; program nodes | — |
| domain-model · group `workflow-systems` | `recursive-composition.md` | covered (138; :127); new placement | How do I nest a Goal Loop inside a Stage Graph stage? | nested body; child run; exports | — |
| domain-model · group `workflow-systems` | `parallel-swarm.md` | covered (96; :89); specified only; DOC-01 put it in execution | How would a Parallel Swarm count members and converge? | swarm; peer variants; swarm governors | — |
| domain-model · group `workflow-systems` | `evaluator-optimizer.md` | covered (97; :87); specified only; new placement | How would an Evaluator Optimizer improve one deliverable? | rubric rounds; evaluator loop; bounded rounds | — |
| persistence | `persistence.md` | covered (150; :132); type Architecture Reference; **stale**: describes the 1.4.0 release (`persistence.md:4`, `:69`) while the component README says newest built is 1.12.0 (`packages/mission-control-db-contract/README.md:12`) | How is the common schema installed and upgraded? | mission-db; release lock; installation | — |
| persistence | **`database-component.md`** (new) | partial: `packages/mission-control-db-contract/README.md:3-13`, `packages/mission-control-db-contract/AGENTS.md:17`, `deployments/<app>/release.lock.json`, `sprint-oc/SCHEMA-AI-ENGINEER.md`, `sprint-oc/SCHEMA-BIOTECH.md` | Which component release is current and who consumes it? | mission-control-db-contract; common component; release numbering | the README release table; the two sprint-oc schema files; release-numbering lines of `persistence.md` |
| persistence | `collections-and-current-sets.md` | covered (127; :119) | How does a report collection build its current accepted set? | aggregate rule; accepted heads; current set | — |
| persistence | `saved-result-settlement.md` | covered (108; :97) | How is a provider result saved and settled without a rerun? | saved result; durable settlement; WI-04 | — |
| persistence | `workspace-closure.md` | covered (102; :91); Deep Agents only today | Which files could the agent see when the attempt settled? | agent-visible files; closure digest; attempt evidence | — |
| persistence | `provider-frames-and-transcript.md` | covered (112; :76); new placement; overlaps `transcript-projection.md` | Where are provider frames stored and how is a transcript read? | Native Event Store; provider frame; run search | — |
| persistence | `transcript-projection.md` | covered (119; :93); new placement | Why is a transcript body expired or missing? | transcript v2; frame-body download; retention | — |
| execution | `execution.md` | covered (137; :122); type Workflow | How do Stage Graph and GoalDirected runs execute on Temporal? | StageGraph family; GoalDirected; operation settlement | — |
| execution | `durable-controls.md` | covered (121; :105) | How does a run wait on an event, a timer or a proof gate? | event wait; timer; proof gate | — |
| execution | `durable-reactions.md` | covered (160; :146) | How do I react durably to an output or settlement transition? | transition reaction; outbox dispatch; WI-22 | — |
| execution | `watchers.md` | covered (160; :157); YAML example `:20-37` | How do I declare a watcher that fires on a signal or a stall? | Watcher Evaluator; notifications; event_wait | — |
| execution | `recovery.md` | covered (147; :119); type Workflow | How do I snapshot, fork or reconcile an uncertain run? | snapshot; fork; reconciliation | — |
| execution | `precise-fork.md` | covered (113; :102); type Workflow; new placement | How do I fork at a cognition point and inject a message? | cognition-point fork; invalidation frontier; seed head | — |
| execution | `context-and-continuation.md` | covered (160; :142); new placement; overlaps `continuation-checkpoint.md` | How is a Context Packet built and handed to the next stage? | Context Packet; state handoff; checkpoint lineage | — |
| execution | `continuation-checkpoint.md` | covered (114; :83); new placement | How is a long session compacted and continued safely? | Continuation Checkpoint; compaction; MP-12 | — |
| execution | `hook-contributions.md` | covered (142; :130); new placement | How can a hook read scopes and stage files for the agent? | hook candidates; safe-boundary install; WI-17 | — |
| execution | `instruction-layering.md` | covered (76; :72); new placement | How does a lane merge its projection into a repo's AGENTS.md? | instruction overlay; structural merge; layering receipt | — |
| execution · group `lanes` | `lanes-and-harness.md` | covered (160; :148); new placement | How does the harness drive a lane turn, and which lanes exist? | AgentHarness; lane.turn; lane registry | — |
| execution · group `lanes` | `session-ownership-and-dispatch.md` | covered (135; :107); new placement | Why was a dispatch parked in doubt instead of resent? | dispatch journal; session fence; capacity wait | — |
| execution · group `lanes` | `placement-admission.md` | covered (62; :57); no `tags`; YAML example `:23-37`; new placement | How are provider capacity and lane alternatives admitted? | placement; capacity reservation; lane alternatives | — |
| execution · group `lanes` | `cursor-lane.md` | covered (155; :140); new placement | How do the Cursor Local and Cursor Cloud lanes run and fork? | cursor_local; cursor_cloud; Cloud Agents API | — |
| execution · group `lanes` | `provider-lanes.md` | covered (158; :125); DOC-01 put it in boundaries, but the file is the Claude/Codex lane as built (`provider-lanes.md:3-4`) | How do the Claude Agent SDK and Codex lanes run on WSL? | claude_agent_sdk; codex lane; native approvals | — |
| execution · group `lanes` | `hosted-api-lanes.md` | covered (48; :41); **absent from the index tables**, listed only under Citations (`index.md:125`) | What do the hosted Managed Agents and Codex lanes support? | Managed Agents; hosted lanes; governed publication | — |
| execution · group `deep-agents` | `deep-agents-lane.md` | covered (160; :126) | How does the Deep Agents lane materialize and run an agent? | DeepAgentRuntimeAdapter; exact materializer; deepagents | — (after Q7: entrypoint inventory moves to `src/mission_control/adapters/deep_agents/AGENTS.md`) |
| execution · group `deep-agents` | `deep-agents-turn-stops.md` | covered (88; :72) | Why did a Deep Agents turn stop before the model answered? | budget stop; fence stop; mc_budget_stop | — (merge target: `deep-agents-lane.md`, see merges) |
| execution · group `deep-agents` | `agent-configuration.md` | covered (85; :70); DOC-01 put it in surfaces | How does a mission select Deep Agents features and model tools? | lane features; model tools; mc.agent_configuration.v2 | — |
| execution · group `deep-agents` | `async-children.md` | covered (125; :121) | How does an async child run and return its result to the parent? | async subagent; sealed child binding; exact adoption | `docs/specs/provider-consolidation-2026-10/providers/deep_agents/ASYNC-SUBAGENTS-EXPLAINED.md` (explainer prose only) |
| qualification | `qualification.md` | covered (87; :76); type Verification Reference; **stale**: "seven lane profiles" (`qualification.md:4`) against nine (`lanes-and-harness.md:4`) | What do local tests prove, and what is still unproved? | proof gates; evidence; lane status | — (merge target: `release-and-qualification.md`) |
| qualification | `release-and-qualification.md` | covered (159; :136) | Which release gates pass and which lanes are qualified? | G0-G7 gates; proof status; compute profiles | `docs/qualification/` index pointers |
| qualification | `evaluator-attempts.md` | covered (107; :101) | Why is an evaluator waiting, and how many runs are billed? | evaluator bound; observation recovery; D22-D24 | — |
| qualification | `trusted-judgment.md` | covered (152; :140) | How do judge and auditor verdicts reach KS and get promoted? | judge; auditor; use review | — |
| qualification | **`documentation-retrieval-fixtures.md`** (new) | missing: Mission Control has no retrieval fixture; `docs/tools/` holds only `okf_search.py` and validators. The model to copy is KS `.agent-docs/fixtures/ks-context-v1/README.md:1-12` | How is documentation retrieval measured and gated here? | retrieval fixture; bench gate; recall@3 | the fixture README once written; SPEC-01 §3.3 rule 8 (`SPEC-01-AGENTIC-SDLC.md:138`) |
| operations | `operations.md` | covered (116; :91); type Playbook | How do I start API workers and Agent Server with real readiness? | preflight; process roles; cluster outage | pointers to `docs/WSL2_WORKER_RUNBOOK.md`, `docs/DEVELOPMENT.md`, `docs/MISSION_CONTROL_LOCAL_API.md` |
| operations | `environments.md` | covered (144; :128) | How do I declare a kit, secrets and network for a mission? | Environment Kit; environment binding; network policy | — |
| operations | `environment-preparation.md` | covered (148; :143) | Why was this session refused as not ready? | readiness level; mission layer; kit provisioning | — |
| operations | `secret-broker.md` | covered (111; :105) | How does a secret reach a lane, and what gets redacted? | secret refs; redaction; minted credentials | — |
| operations | `budgets-and-usage.md` | covered (159; :129) | How is a budget reserved before work and settled after? | budget envelope; usage settlement; capacity limit | — |
| operations | `owner-prerequisites.md` | covered (160; :150) | Which human-only steps must I do before a lane can run? | owner steps; prerequisite record; preflight standing | — |
| operations | `owner-probe-bootstrap.md` | covered (87; :71); PowerShell block `:24-29`; new placement | How do I verify hosted credentials with a bounded probe? | owner probe; credential verification; probe bootstrap | — |
| decisions | **`decisions.md`** (new) | partial: `docs/adr/` (66 files, 0001 to 0067; DOC-01 said 0063, sitting I added 0064-0067), `docs/specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md` (355 lines), the program `LEDGER.md` files, D1-D9, the `answers/` directories | Where is this decided, and which decisions are still open? | ADR index; open decisions; decision map | ADR titles and status; open-decision rows of each ledger |
| goals | **`goals.md`** (new) | missing as a concept; seeds: `BellLabs/AGENTS.md:3-7` (owner goal), `docs/BELLLABS-SEQUENCE.md:28-53` (sequence and real-work gate), SPEC-01 §5 (`SPEC-01-AGENTIC-SDLC.md:166-176`); the owner states the long-term goals at Q8 | What is Mission Control for, and what is the nearest goal? | charter; owner goal; Deep Agents first | those three seeds; `sprint-oc/NEXT-SESSION.md` for the nearest checkpoint |

**Counts.** 64 covered (all lacking `category`, `aliases` and `questions`), 3 partial
(coordinator-surface, database-component, decisions), 2 missing (documentation-retrieval-fixtures,
goals). Per category: boundaries 3, surfaces 11, domain-model 14, persistence 7, execution 20,
qualification 5, operations 7, decisions 1, goals 1.

## Knowledge Services (`platform/knowledge-services/knowledge/`)

Eleven concepts plus a generated `index.md`. **All 11** already carry `aliases` and `questions`
(lines 6-8 of each file). **None** has `category`. **None** has `type: Concept` (types are
`Service Boundary`, `Architecture Concept`, `concept`, `Playbook`), and **none** has a Citations
section: evidence is a `sources:` list in frontmatter. As SPEC-01 §3.3 rule 1 is written, all
eleven fail on `type` and Citations; either the rule accepts `sources:` or each file gains a
`# Citations` section. **Three are over 160 lines.** `aliases` already exceed three on
`service-boundaries.md` (eight) and `schema-read-and-ingestion.md` (six).

| Category | Concept (file) | Status | `questions[0]` (existing unless marked proposed) | Aliases (first three) | Folds in |
| --- | --- | --- | --- | --- | --- |
| boundaries | `service-boundaries.md` | covered (**226 lines, over cap**; `sources:` :18) | Which repository owns a database or verification change? | service ownership; caller contract; application boundary | — (to shrink: "Transport route" `:128-177` moves to `execution-profiles-and-transports.md`; ownership of bindings `:39-80` to `applications-and-bindings.md`) |
| boundaries | **`applications-and-bindings.md`** (new, interview Q4) | partial: `packages/AGENTS.md:28-30` (bindings K05, K06), `packages/bindings/aiengineer-postgres/src/research-binding.ts`, `packages/bindings/biotech-graph/src/index.ts`, `service-boundaries.md:39-80`, MC `sprint-oc/APPLICATION-PORTS.md` | Proposed: Which binding connects KS to AI Engineer or Biotech data? | K05 binding; K06 binding; application binding | the binding rows of `packages/AGENTS.md`; the ownership section of `service-boundaries.md` |
| surfaces | `execution-profiles-and-transports.md` | covered (51; `sources:` :15) | Which commands work offline without a database? | local mode; remote mode; ks commands | the transport section of `service-boundaries.md` |
| surfaces | `agent-skills-and-consumer-readiness.md` | covered (53; `sources:` :15) | Which skills are shipped today and which are only planned? | skill loading; parser conformance; skill bundle | — |
| domain-model | `capture-conversion-and-custody.md` | covered (52; `sources:` :15) | What is the difference between Docling and the verification parser? | source bytes; PDF parsing; document conversion | — |
| domain-model | `preparation-and-publication.md` | covered (129; `sources:` :15) | What does preparation produce before embedding or publication? | prepare preview; document nodes; chunk lineage | — |
| domain-model | `retrieval-and-evidence.md` | covered (126; `sources:` :15) | How does retrieval avoid returning unsupported claims? | evidence packet; citation replay; supported search | — |
| domain-model | **`knowledge-operation.md`** (new) | partial: `packages/knowledge-operation-protocol/src/envelope.ts:30`, `:65-70` (`knowledge.read_intent`), `packages/knowledge-operation-protocol/schemas/`, MC `sprint-oc/provenance-2026-10-31/REPORT.md:33`, `:36`, `:59`, `skills/knowledge-db/SKILL.md:69`, `docs/specs/belllabs-knowledge-platform/DOMAIN-SURFACES.md:122` | Proposed: What is a knowledge operation and how is a read recorded? | K01 protocol; read intent; operation envelope | the protocol package README/schemas index; the OVE-204 report rows |
| persistence | `schema-read-and-ingestion.md` | covered (**176 lines, over cap**; `sources:` :15) | How do I read tenant knowledge before writing an ingestion intent? | database snapshot; named query; ingestion receipt | — (to shrink: "Contract pins" `:43-55` moves to `schema-ownership.md`) |
| persistence | **`schema-ownership.md`** (new) | partial: `docs/architecture/0008-common-operational-schema-ownership.md:11`, `packages/knowledge-db-contract/component/release-spec.json:2-5` (component `knowledge_verification` 2.5.0), `component/UPGRADE-2.5.0.md`, `.agent-docs/config.json:12`, `aiengineer/ai-engineer-db-contract/README.md:19-44`. DOC-01 says "`knowledge_service` schema"; live, the component owns `knowledge_verification`, and `knowledge_service.recovery_*` is named on the AI Engineer side (`README.md:23`) | Proposed: Who owns the KS tables, and which component version is pinned? | knowledge_verification component; KS_COMPONENT_PIN; ADR 0008 | ADR 0008; the component upgrade notes; the pin section of `schema-read-and-ingestion.md` |
| execution | `durable-execution-and-recovery.md` | covered (127; `sources:` :16) | When is a failed step retried, and when is it terminal? | retry; cancellation; worker restart | — |
| execution | `jev-decisions-and-workers.md` | covered (47; `sources:` :15) | When should an agent use Jev instead of an LLM? | System One; typed judgments; taxonomy routing | — |
| qualification | `evaluation-and-publication-gates.md` | covered (51; `sources:` :15) | Does a passing retrieval benchmark authorize publication? | gold dataset; heldout evaluation; release gates | — |
| qualification | `verification-and-admission.md` | covered (**258 lines, over cap**; `sources:` :17) | Can a semantic judgment override a deterministic failure? | deterministic gate; exact-use admission; use class | — (to shrink: "Trusted assessment and review (Sprint OC WI-03)" `:151-193` becomes its own concept or moves to `knowledge-operation.md`) |
| qualification | **`retrieval-benchmark.md`** (new) | partial: `.agent-docs/fixtures/ks-context-v1/README.md:1-12` (18 screening, 6+4 heldout cases), `manifest.json`, `queries.json`, `.agent-docs/retrieval-benchmark.mjs:26` (recall@3) | Proposed: How is concept retrieval benchmarked, and what is the gate? | ks-context-v1 fixture; recall@3; heldout cases | the fixture README. Suggest the name `documentation-retrieval-benchmark.md`, so it is not confused with the product retrieval evaluation in `evaluation-and-publication-gates.md` and matches MC's `documentation-retrieval-fixtures.md` |
| operations | **`operations.md`** (new) | partial: `docs/operations/runbooks.md` (33 lines), `docs/operations/agent-maintenance.md` (135), `docs/operations/code-quality-and-delivery-process.md` (151), `docs/verification/OPERATOR-RUNBOOK.md` | Proposed: How do I run, deploy and repair Knowledge Services? | KS runbook; maintenance; delivery process | those four documents (pointers, not copies) |
| decisions | **`decisions.md`** (new) | partial: `docs/architecture/0001-0015`, `docs/specs/belllabs-knowledge-platform/ADRS.md` (18 lines), the BellLabs Knowledge Platform Linear project; no `DECISIONS*` file exists under `docs/specifications/` or `docs/specs/` | Proposed: Which KS decisions are accepted and which are open? | KS ADRs; decision log; architecture records | ADR titles and status; `ADRS.md` |
| goals | **`goals.md`** (new) | missing; seeds: `service-boundaries.md:33-38` (Purpose), `docs/architecture/current-state.md`, `docs/BELLLABS-SEQUENCE.md`; owner input at Q8 | Proposed: What is Knowledge Services for, and who depends on it? | KS charter; shared foundation; research-report supply | the seeds above |

**Counts.** 11 covered (all lacking `category`; 3 over the cap), 6 partial
(applications-and-bindings, knowledge-operation, schema-ownership, retrieval-benchmark, operations,
decisions), 1 missing (goals). Per category: boundaries 2, surfaces 2, domain-model 4,
persistence 2, execution 2, qualification 3, operations 1, decisions 1, goals 1.

## Biotech Knowledge Services (`biotech/biotech-knowledge-services`, no bundle)

There is no `knowledge/` directory and no `GLOSSARY.md`. SPEC-01 §4.3 names
`biotech/biotech-knowledge-services/GLOSSARY.md` as one of the four glossaries
(`SPEC-01-AGENTIC-SDLC.md:161`), so that file has to be created too. Facts live in `AGENTS.md`
(33 lines), `docs/NAVIGATION.md` (42), ADRs 0001-0005 and the schema-v2 release plan. The order
below follows the recommendation for Q5: **schema-releases and ingestion-and-admission first.**

| Order | Category | Concept (file) | Status | Proposed `questions[0]` | Aliases | Folds in |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | domain-model | `schema-releases.md` | partial: `docs/NAVIGATION.md:20` (authority SV-D10, v2.2.0 pinned), `schema/pinned/PIN.json:4` (release digest), `schema/source/README.md`, `schema/sidecars/README.md`, `AGENTS.md:10-11`, ADR 0002 and 0003 | How do I change the Biotech schema and pin a new release? | schema pin; PIN.json; sidecar authority | `schema/source/README.md`; `docs/plans/schema-v2-service-release/RELEASE-MANIFEST.md`, `STATUS.md` |
| 2 | execution | `ingestion-and-admission.md` | partial: `docs/NAVIGATION.md:10`, `packages/kg-ops/src/write/`, `packages/kg-ops/src/admission/`, `packages/contracts/src/intent-v2.ts`, `AGENTS.md:13-14` (plan determinism, one apply transaction), ADR 0003, 0004, 0005, `.agents/skills/biotech-kg-ingest/SKILL.md` | How does an ingestion intent become one admitted graph write? | intent v2; plan and apply; KsIntentMarker | `docs/plans/schema-v2-service-release/INTERFACES.md`; ADR 0004 run identity |
| 3 | boundaries | `service-boundaries.md` | partial: `docs/NAVIGATION.md:5`, `:24`, `AGENTS.md:3`, ADR 0004 (32 lines) and ADR 0005 (69 lines) | What does BKS own, and what belongs to KS or Mission Control? | domain graph service; BKS boundary; MC adapter | the "Authority" paragraph of `NAVIGATION.md` |
| 4 | surfaces | `surfaces.md` | partial: `docs/NAVIGATION.md:11-16` (executor HTTP/MCP, GraphQL, BFF, client, skills), `apps/executor/capabilities/biotech-knowledge.capability.json`, `python/biotech-knowledge-client/README.md`, `.agents/skills/skill-routing.json`. `NAVIGATION.md:16` names four first-party skills; the live tree has seven `biotech-*` skills plus `fly-ops` | Which BKS endpoint, MCP tool or skill should I call? | executor MCP; GraphQL API; capability catalog | the service table of `NAVIGATION.md` |
| 5 | persistence | `graph-and-postgres.md` | partial: `AGENTS.md:7` (data-plane map), `docs/NAVIGATION.md:10`, `BellLabs/docs/navigation/DATA-PLANES-AND-CREDENTIALS.md`. **Surprise:** `biotech/biotech-postgres-db-contract/` now exists (AGENTS.md, `component.lock.json`, `src/`, `tests/`) but is not a Git repository, while DOC-01 says it is "not yet a repository" (`INFORMATION-CATEGORIES-DRAFT-2026-11-01.md:89`) | Where is Biotech data stored, and which contract owns it? | biotech-graph; Neo4j; biotech-postgres-db-contract | the data-plane registry rows for biotech-db and biotech-graph |
| 6 | qualification | `evals-and-verify.md` | partial: `evals/baseline-comparison/README.md`, `evals/v2/FREEZE.json`, `package.json:15-19` (test, integration, `workspace:verify`), `AGENTS.md:27-33` | How do I prove a schema or ingestion change before handoff? | workspace:verify; kg-ops integration; eval baseline | `evals/baseline-comparison/README.md`; `docs/plans/schema-v2-service-release/VALIDATION.md` |
| 7 | operations | `operations.md` | partial: `docs/deployment/executor.md` (132), `docs/deployment/graphql-api.md` (108), `.agents/skills/fly-ops/SKILL.md`, `AGENTS.md:25` | How do I deploy or repair the executor and GraphQL API? | Fly.io; executor runbook; bks-biotech-graphql-api | both deployment documents |
| 8 | decisions | `decisions.md` | partial: `docs/architecture/0001-0005`, `docs/plans/schema-v2-service-release/DECISIONS.md`, SV-D10 (`NAVIGATION.md:20`) | Which Biotech decisions are settled and which are open? | BKS ADRs; SV-D10; schema v2 decisions | ADR titles; the release `DECISIONS.md` |
| 9 | goals | `goals.md` | missing; seed: `biotech/BellLabs/index.md`; the owner states the programs at Q8 | What is the Biotech knowledge graph for, and who uses it? | Biotech charter; longevity research; diagnostics | `biotech/BellLabs/index.md`; MC `skills/biotech-knowledge-charter/SKILL.md:3` (evidence bar, entity scope) |

**Counts.** 0 covered, 8 partial, 1 missing. Stale facts a concept must not inherit:
`NAVIGATION.md:9` still says "Local release v2.0.2: 69 node types" while `:20` says v2.2.0 is
pinned. `:16` lists four skills.

## AI Engineer (`aiengineer/`, no knowledge bundle)

None of the three repositories has a `knowledge/` directory or a `GLOSSARY.md`. The domain
vocabulary is `ai-engineer-meta/ai-engineer-architecture/CONTEXT.md` (507 lines), to be renamed
per AS-D3. `ai-engineer-db-contract` and the pre-research agent already carry a generated
`agent-docs` block in `AGENTS.md` and an `.agent-docs/` toolchain.

### `ai-engineer-db-contract` (`sprint-oc`)

| Category | Concept (file) | Status | Proposed `questions[0]` | Aliases | Folds in |
| --- | --- | --- | --- | --- | --- |
| boundaries | `schema-authority.md` | partial: `AGENTS.md:4-14` (generated guide rules: one migration and type authority, consumers pin) | Who may change the shared AI Engineer schema, and how? | schema authority; migration owner; type contract | `README.md` ownership section |
| surfaces | `type-contract.md` | partial: `src/AGENTS.md`, `package.json` exports, `AGENTS.md:23` | How do consumers import the generated database types? | aiengineer-database-contract; database.generated.ts; api schema | `src/AGENTS.md` |
| domain-model | `knowledge-model.md` | partial: `docs/knowledge-model/SCHEMA-SUMMARY.md` (54 lines), `AGENTS.md:33` | Which tables hold research, evidence and reports? | knowledge model; schema summary; report tables | `SCHEMA-SUMMARY.md`, `MIGRATION-RESULT.md` |
| persistence | `schema-and-migrations.md` | partial: `supabase/migrations/` (189 entries, latest `20261031010000_operation_receipt_targets.sql`), `README.md:19-44` (KS component dependency). `README.md:20` says the component pin is 2.4.0 and `:42` says 2.5.0 | Which migrations exist, and what must be installed first? | supabase migrations; KS component pin; common component | `supabase/AGENTS.md` |
| execution | n/a | — | — | — | — |
| qualification | `contract-checks.md` | partial: `AGENTS.md:45-48` (typecheck, types:check, workspace:check, workspace:validate), `.github/workflows/contract.yml`, `scripts/reset-disposable-local.test.mjs` | Which checks must pass before a schema change merges? | contract CI; workspace:validate; types:check | `.github/workflows/contract.yml` |
| operations | `install-and-disposable-targets.md` | partial: `AGENTS.md:11-12`, `scripts/install-ai-engineer.mjs`, `README.md:35-76` (install, remote reinstall), `scripts/AGENTS.md` | How do I install or reset a disposable AI Engineer database? | install-ai-engineer; disposable reset; remote reinstall | the README install section |
| decisions | n/a: pointer line to `ai-engineer-meta/ai-engineer-architecture/adr/` | — | — | — | — |
| goals | n/a: pointer line to the meta charter | — | — | — | — |

### `research_starter_pre_research_agent` (`main`, last commit `dc99c8b` 2026-08-25)

`AGENTS.md:1-52` is Eve framework boilerplate ahead of the generated block (`:53-108`), so the
compressed AGENTS.md work applies here too. DOC-01's "HTTP routes" are Eve agent channels and
schedules (`agent/`) in the live tree.

| Category | Concept (file) | Status | Proposed `questions[0]` | Aliases | Folds in |
| --- | --- | --- | --- | --- | --- |
| boundaries | `pre-research-boundary.md` | partial: `README.md:3-7`, `AGENTS.md:57-63` | What does the pre-research agent do, and what is out of scope? | intake agent; pre-research; research slice | `README.md` opening |
| surfaces | `surfaces.md` | partial: `agent/` (Eve host, channels, schedules), `scripts/AGENTS.md`, `apify-transcript-ingest/README.md` | How do I start a pre-research run or intake a transcript? | Eve agent; Apify intake; operator scripts | `scripts/AGENTS.md` |
| domain-model | `packet-and-intent.md` | partial: `contracts/AGENTS.md`, `implementation/goal/PRE_RESEARCH_V2_IMPLEMENTATION_PLAN.md`, `README.md:13-21` | What is a pre-research packet, and what are its stages? | packet stages; ingestion intent; packet schema 2.0.0 | the v2 plan's contract sections |
| persistence | `ledger-and-storage.md` | partial: `executor/AGENTS.md`, `README.md:5` (`research_*` tables), `:17` (storage path) | Where do packets and applied intents land? | research tables; Supabase storage; intent artifacts | `executor/AGENTS.md` |
| execution | `pipeline-controller.md` | partial: `controller/AGENTS.md`, `controller/pre-research-pipeline.ts`, `README.md:15-19` (serial controller, completion rule) | When is a pre-research pipeline finished, and how does it resume? | serial controller; completion rule; durable checkpoints | `README.md` Status section |
| qualification | `evals-and-fixtures.md` | partial: `evals/README.md`, `implementation/goal/EVALUATION_SYSTEM.md`; the 2026-10-31 StageGraph fixture evidence (path not verified in this repository) | How is packet quality evaluated and a change promoted? | golden set; trace evals; promotion gate | `evals/README.md` |
| operations | `run-and-recover.md` | partial: `HANDOFF.md`, `.cursor/skills/run-pre-research/SKILL.md`, `scripts/AGENTS.md` | How do I run, apply and recover a pre-research batch? | operator handoff; apply; recover | `HANDOFF.md` |
| decisions | n/a: pointer line to the meta ADRs | — | — | — | — |
| goals | n/a: pointer line to the meta charter | — | — | — | — |

### `ai-engineer-meta` (`main`)

| Category | Concept (file) | Status | Proposed `questions[0]` | Aliases | Folds in |
| --- | --- | --- | --- | --- | --- |
| boundaries | `domain-charter.md` | partial: `AGENTS.md:13-17` (repositories, learner app absent, retired repos), `CONTEXT-MAP.md`, `docs/agents/workspace/SERVICE-NAVIGATION.md` | Which AI Engineer repositories exist, and which are absent? | AI Engineer map; learner app absent; retired repos | `SERVICE-NAVIGATION.md` |
| surfaces | n/a (documentation only) | — | — | — | — |
| domain-model | the glossary (rename of `ai-engineer-architecture/CONTEXT.md`), not a concept | partial: `CONTEXT.md` 507 lines | — | — | — |
| persistence | n/a | — | — | — | — |
| execution | n/a | — | — | — | — |
| qualification | `documentation-tooling-tests.md` | partial: `tools/agent-docs/cli.test.mjs` (53 `test(` calls; DOC-01's "44" not re-run), `tools/agent-docs/retrieval.test.mjs`, `tools/agent-docs/fixtures/` | How are the documentation generator and retrieval tested? | agent-docs tests; retrieval fixture; generator tests | — |
| operations | `documentation-build.md` | partial: `tools/AGENTS.md`, `docs/agents/workspace/DOCUMENTATION-MAINTENANCE-PLAN.md` | How do I rebuild and check the workspace documentation? | agent-docs build; workspace verify; documentation job | the maintenance plan |
| decisions | `decisions.md` | partial: `ai-engineer-architecture/adr/0001-0005`, `docs/agents/workspace/RESPONSIBILITIES.md` (32 lines, open items) | Which AI Engineer decisions are accepted and which are open? | AIE ADRs; open responsibilities; decision index | ADR titles; `RESPONSIBILITIES.md` |
| goals | `goals.md` | missing; seeds: `docs/product/00-vision.md` (5 lines), `11-north-star-path.md` (22), `12-age-of-ai-agents.md`; the owner states the goals at Q8 | What is AI Engineer for, and which surface ships first? | AI Engineer charter; north star; product surfaces | the three product documents |

**Deferred (one line each).** `agents_dashboard`: one `boundaries` concept (proof UI over the
ledger; the overlap with a Mission Control dashboard is undecided, DOC-01 open item 1) and `n/a`
lines; its `AGENTS.md` opens with Next.js boilerplate. `ai-engineer-industry-cloud-automated-research`:
one `boundaries` concept (cloud research environment, to reconcile with MC) and `n/a` lines;
`ENTITY_TAXONOMY.md` exists at its root for a later domain-model concept.

**Counts (three repositories).** 0 covered. Partial: 6 in db-contract, 7 in pre-research,
5 in meta (counting the glossary rename). Missing: 1 (meta `goals`).

## Findings for the owner

### Merge candidates

1. **Deep Agents group (the interview recommendation for Q3): accept it as a group, not as one
   file yet.** Members are `deep-agents-lane.md` (160), `deep-agents-turn-stops.md` (88),
   `agent-configuration.md` (85) and `async-children.md` (125), 458 lines in total. A single
   concept cannot hold them under the 160-line cap. The lane and turn-stops files overlap:
   `deep-agents-turn-stops.md:10` calls itself "Detail of the Deep Agents lane", and
   `deep-agents-lane.md:61-67` already summarizes the stops. They can merge into one file only
   after the Q7 trim moves the lane's entrypoint inventory into
   `src/mission_control/adapters/deep_agents/AGENTS.md`. `agent-configuration.md` and
   `async-children.md` answer different questions, so they stay separate files in the group.
   `agent-configuration.md` moves from DOC-01's `surfaces` to the group.
   `workspace-closure.md` is Deep-Agents-only today but is an evidence record, so it stays in
   `persistence` with a cross-link. `hook-contributions.md` is provider-neutral and stays in
   `execution`. A group needs either a `group:` frontmatter field or a subdirectory, which is a
   SPEC-01 §3.3 rule 1 amendment.
2. **`context-and-continuation.md` and `continuation-checkpoint.md`.** Both descriptions claim the
   continuation checkpoint, its service and the MP-12 phase machine (`:4` in each). To de-duplicate,
   drop the "Continuation and compaction" section of `context-and-continuation.md` (`:128-141`)
   and point to the checkpoint concept.
3. **`provider-frames-and-transcript.md` and `transcript-projection.md`.** Both describe transcript
   v2, the persisted projection, expired placeholders and frame-body downloads (`:4` in each).
   Keep frames (Native Event Store, closing-frame derivation, usage) in the first and the
   transcript in the second.
4. **`qualification.md` and `release-and-qualification.md`.** Both give per-profile lane
   qualification, and the first is stale (seven profiles against nine). Fold the first into the
   second, rename the result `qualification.md`, and trim to 160.
5. **Keep separate.** `capabilities.md` and `capability-seeds.md` are a deliberate split
   (`capabilities.md:4`). `recovery.md` and `precise-fork.md`, and `durable-controls.md` and
   `human-gates.md`, are summary-plus-detail pairs.
6. **Knowledge Services.** No merges. The three oversized files split outward (see their rows).

### Concepts over 160 lines

Mission Control has none; twelve are exactly 160 (`context-and-continuation`, `deep-agents-lane`,
`durable-reactions`, `human-gates`, `interfaces`, `knowledge-services`, `lanes-and-harness`,
`mission-stream`, `output-contracts`, `owner-prerequisites`, `watchers`, `workflow-systems`), so
any added frontmatter line (`category`, `aliases`, `questions`) pushes them over unless the cap
excludes frontmatter. That is a decision for Q13. Knowledge Services has three:
`verification-and-admission.md` (258), `service-boundaries.md` (226),
`schema-read-and-ingestion.md` (176).

### Categories over twelve (they would collapse in the index)

Mission Control `execution` (20) and `domain-model` (14). With the proposed groups (`lanes` 6,
`deep-agents` 4, `workflow-systems` 4), `execution` shows 12 index entries and `domain-model`
shows 11. Knowledge Services, Biotech and AI Engineer have no category above four.

### Other surprises

- The "66 concepts" in DOC-01 and the interview are 64 concepts plus `index.md` and `log.md`.
- `hosted-api-lanes.md` is not in any index table (`index.md:125`, Citations only).
- `persistence.md` still describes release 1.4.0; the newest built release is 1.12.0.
- `biotech-postgres-db-contract` exists on disk without Git (see Biotech row 5).
- The interview's MC concept list for Q3 (`decisions`, `goals`) counts ADRs up to 0063; sitting I
  added ADR 0064-0067, which the `decisions` concept must route to.

## Depth note for Q7

Three Mission Control samples, measured on the live files:

| Concept | What realization detail it holds now | What would move to a module `AGENTS.md` block | What stays |
| --- | --- | --- | --- |
| `deep-agents-lane.md` (160 lines) | No code blocks, but about 68 `.py` path references and 12 `module::Symbol` references: class and method names (`DeepAgentRuntimeAdapter.execute`, `ExactDeepAgentMaterializer.prepare`, `BudgetStopMiddleware`), file-by-file roles (`frames.py`, `hooks.py`, `compaction.py`, `async_subagents.py`), pinned versions (`:61-67`) | The file-to-role inventory, which `src/mission_control/adapters/deep_agents/AGENTS.md:10-22` already duplicates as a "Where things are" table, plus the verify commands (`:33-37`). That module file is already 2,627 bytes, over the proposed 2 KiB module budget | Why the lane composes this way (exact binding, fail-closed placement, Temporal owns scheduling), the child shapes and the discriminator rule, and the observable lifecycle (frames, compaction, points), with ADR citations. After the move it would fit with turn-stops in 160 lines |
| `watchers.md` (160 lines) | A YAML manifest example (`:20-37`): authored `controls.watchers` spelling, not implementation code. About 20 `.py` references | Evaluator entrypoints and the test selection | The YAML example. It is the authoring contract an agent copies, not code, so Q7's "never pastes code" should exempt authored manifest and command examples |
| `owner-probe-bootstrap.md` (87 lines) | A PowerShell command block (`:24-29`) with the exact `python -m mission_control.bootstrap.owner_probe` invocation; 9 `.py` references | The command line belongs in `src/mission_control/bootstrap/AGENTS.md` (or the `operations` concept), where an operator runs it | Why a bounded probe precedes hosted admission, and what it verifies |

Elsewhere the pattern is the same. No MC concept embeds implementation code (code blocks appear
only in `watchers.md`, `placement-admission.md` and `owner-probe-bootstrap.md`, all as manifest or
command examples), but most concepts carry a dense inventory of paths and symbols: 70 `.py`
references in `lanes-and-harness.md`, 62 in `cursor-lane.md`, 56 each in `interfaces.md` and
`capabilities.md`. That inventory is what Q7's recommendation moves into module blocks. Ten module
`AGENTS.md` files already exist under `src/mission_control/` and one in
`packages/mission-control-db-contract/`. Knowledge Services concepts are leaner (47-258 lines,
with evidence in `sources:`) and keep entrypoints in `packages/AGENTS.md` and
`docs/agents/CODE-MAP.md` already.

## Citations

- [DOC-01](INFORMATION-CATEGORIES-DRAFT-2026-11-01.md), [sitting II instrument](INTERVIEW-NAVIGATION-AND-KNOWLEDGE-2026-11-02.md), [SPEC-01](SPEC-01-AGENTIC-SDLC.md) §3.3 and §4.3.
- Mission Control: [knowledge index](../../knowledge/index.md), the 64 concept files in `docs/knowledge/`, `packages/mission-control-db-contract/README.md`, `src/mission_control/adapters/deep_agents/AGENTS.md`.
- Knowledge Services: `platform/knowledge-services/knowledge/`, `packages/AGENTS.md`, `.agent-docs/fixtures/ks-context-v1/README.md`, `packages/knowledge-db-contract/component/release-spec.json`.
- Biotech: `biotech/biotech-knowledge-services/AGENTS.md`, `docs/NAVIGATION.md`, `docs/architecture/`.
- AI Engineer: `aiengineer/ai-engineer-db-contract/AGENTS.md` and `README.md`, `aiengineer/research_starter_pre_research_agent/AGENTS.md` and `README.md`, `aiengineer/ai-engineer-meta/AGENTS.md`.
