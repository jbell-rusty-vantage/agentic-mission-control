---
type: Working Draft
title: "Truth pass A: what mission-control-general holds and what has not propagated"
description: "Exploration part A of the Mission Control truth pass: every file under mission-control-general/ with lines, last commit, what it defines, propagation status against GLOSSARY, ADRs and docs/knowledge, claims checked against src/ and packages/, contradictions, owner questions and refactor steps."
tags: [mission-control, truth-pass, sdlc]
date: 2026-11-01
status: draft
---

# Truth pass A: `mission-control-general/`

Read on `sprint-oc` on 2026-11-01. Nothing except this file was written. Paths are relative to
`platform/mission-control/`; `MCG` = `mission-control-general/`, `GMC` = `MCG/general-mission-control/`,
`WT` = `MCG/workflow-types/`, `EXP` = `GMC/expansion/`. Code labels: **implemented** (in source),
**tested** (a test exists; not rerun here), **not built**, **contradicted**. Propagation: **propagated**,
**partial**, **not propagated**, **superseded**.

## 1. What this folder is and how it relates to the repo today

- It is the **origin specification** the rest of the documentation was distilled from. ADR-0001 to
  ADR-0022 cite `GMC/SPECIFICATION.md` or `EXP/` as their source (17 ADRs cite the folder); 26 of 64
  concepts cite it, and `docs/knowledge/index.md:19-25` says concepts "point at the normative
  specification where behavior is specified but not yet built".
- `AGENTS.md:142,145` call it "the owned spec pack (normative)" and rank it **above** ADRs:
  `spec pack > docs/adr > docs/knowledge > IMPLEMENTATION_STATUS`. `AGENTS.md:46` sends every agent to
  `GMC/SPECIFICATION.md` first.
- It has two layers. **Live normative files** (SPECIFICATION, RUNTIME-CONTRACTS, DATABASE,
  OUTPUT-CONTRACTS, `WT/00-09`) received dated amendment banners on 2026-10-26/27/29 (OC-D204, output
  contracts) but their bodies are still the 2026-10-02/03 consolidation. **Historical files** (nine root
  documents, most of `GMC/` besides those, all of `EXP/`, `runtime-facts/`) have not changed since
  2026-10-09 and were already marked superseded by `GMC/DOCUMENTATION-CLEANUP.md` on 2026-10-02.
- Search corpus: `docs/tools/okf_search.py:38-40` indexes `GMC/` (recursively, so `EXP/` and its 44
  stale issue files too), `WT/` and `runtime-facts/`; the nine root files are excluded. The retrieval
  audit found the 2026-10-03 `EXP/KNOWLEDGE-SERVICES.md` outranking the current concept
  (`RETRIEVAL-AUDIT-BASELINE-2026-11.md:180-186`).
- No script consumes `MCG/validate_spec.py` or `EXP/build_packet.py`/`validate_packet.py` (searched
  `docs tests Makefile pyproject.toml .github scripts`); `docs/tools/check_docs.py` replaced them.

## 2. The un-propagated knowledge, ranked by importance to the nearest goal

Goal: complete Deep Agents-first workflow and agent configuration over Stage Graph, Goal Loop,
Parallel Swarm and Evaluator Optimizer.

1. **Swarm is a Stage Graph profile (OC-D204); EO runs on GoalDirected machinery (OC-D205).** Owner-
   approved 2026-10-29 (`docs/specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md:347-348`).
   Carried by `GMC/SPECIFICATION.md:189-201`, `WT/00:9-28`, `WT/01:9`, `WT/03:9`, `GLOSSARY.md:138-181`.
   **Not** carried by: any ADR; `WT/04` (only the 10-26 output banner, no OC-D205);
   `docs/knowledge/workflow-systems.md:17-25,128-137` (still "four workflow systems", Swarm "specified
   only"); `parallel-swarm.md:4` and `evaluator-optimizer.md:4,72` ("specified, not implemented", no
   OC-D205). Code still has four families: `domain/resolution/configuration.py:53-59`,
   `domain/authoring/manifest.py:406-407,986-993`, `application/authoring/manifest_v2_admission.py:86-91`;
   Deep Agents declares both `unqualified` (`adapters/deep_agents/describe.py:139-158`). Runtime homes
   `sprint-oc-wi14`/`wi15` are unreviewed (`STATE-mission-control-2026-11.md:142`). **Partial.**
2. **The Goal Loop governance model** (`WT/02` §3-§14): two loops (goal progress and context health),
   Loop Journal entry kinds and sealed segments, Loop State projection, the Loop Operating Contract,
   committed Action Space, Action Proposal, Action Authorization as a Mission Control transition
   (`authorized | denied | pending_human_task`), the five-value Side-Effect Class, iteration phases,
   Cycle Decision, Progress Review, Context Health policy promotion, governors, human input,
   nested loops. Code: GoalDirected is an executor/verifier alternation with convergence patience
   (`domain/programs/goal_directed_runtime.py:39,44,92`); no `ActionProposal`, `ActionAuthorization` or
   `LoopJournal` in `src/` (0 files); Side-Effect Class enum exists (`domain/authoring/manifest.py:356`);
   manifest `action_space` is validated at compile (`application/authoring/manifest_service.py:1636-1656`).
   No concept explains the target vs the built subset (only `execution.md:4`, one line).
   **Not propagated** as a concept; GLOSSARY has the nouns (`GLOSSARY.md:150-164`).
3. **Deep Agents middleware placement and the extension profile** (`EXP/CONTEXT-STATE-AND-CONTROL.md:62-68`):
   required effective order before-model (budget/stop) → wrap-model (reservation/accounting) →
   before-tool (authority/effect admission) → wrap-tool (intent/receipt, offload) → after-tool
   (custody) → after-model (candidate extraction); guards over native default tools, shell and dynamic
   subagent launch; replace stock `task` channel propagation with admitted subordinate graphs; a sealed
   `mc.extension_profile.v1`. Partly **implemented** (`HookScriptMiddleware`, `ObservedSummarizationMiddleware`,
   `BudgetStopMiddleware`/`FenceStopMiddleware`, async subagent middleware: `docs/knowledge/deep-agents-lane.md:46-62`);
   `extension_profile` **not built** (0 src hits) and the order is not stated anywhere current. **Partial.**
4. **Agent Executor contract** (`WT/05` §3.1-§3.4; old `MCG/MISSION_CONTROL_SPEC.md:154-164`): the
   versioned Operating Contract, `missing_output_policy` (default one follow-up turn, then
   `not_accepted(outputs_missing)`), Completion Candidate shape, attempt-outcome mapping, and the
   simple/standard/full **agent binding levels**. Binding itself is **superseded** by the resolution
   seam and Sealed Lane Binding (ADR-0063, `GLOSSARY.md:510-526`). Operating Contract is a context
   packet item (`domain/context/packet.py:86`, `domain/authoring/manifest.py:1011`); missing-output
   follow-up is **implemented for Cursor only** (`adapters/cursor/local.py:207`, `adapters/cursor/kernel_hook_script.py:99`),
   not found for Deep Agents. Binding levels: 0 hits anywhere current. **Partial.**
5. **Context budget, memory namespaces and the parent/child message protocol**
   (`EXP/CONTEXT-STATE-AND-CONTROL.md:21-33,52-60,70-75`): available-input formula and
   `CONTEXT_BUDGET_EXCEEDED` (implemented, 2 src files); merge policies (`replace_if_base_matches`…,
   4 src files); `mc.memory_recall.v1`, four memory namespaces, `mc.message.v1`, `mc.progress.v1`
   (0 src hits). ADR-0007 carries authoritative-vs-advisory only. **Partial.**
6. **Stage Graph dynamic fan-out and provisional bindings** (`WT/01` §9-§10). Only a `fan_out`
   governor (`domain/authoring/manifest.py:587`) and a `provisional` flag (`domain/programs/contracts.py:501`;
   set `False` at `interpreter.py:1311`). Fan-out templates **not built**; no concept says so. Swarm
   fan-out members (`WT/03` §3.1) depend on it. **Not propagated.**
7. **Deterministic Executor Kind registry** (`WT/05` §4.1: `verification_dispatch`, `artifact_register`,
   `git_snapshot`, `schema_validate`, `test_run`, `coalesce`, `agreement_check`, `noop_echo`). **Not built**
   (stated in `workflow-systems.md:131-133`); Swarm convergence (`coalesce`, `agreement_check`) needs it.
   **Propagated as a gap**, no plan home.
8. **Child Mission Invocation, Portals, Spawn Grants** (`WT/06`): invocation modes, definition sources,
   await/cancel cascade, Mission Graph. GLOSSARY has the nouns (`GLOSSARY.md:117-127`); ADR-0029 keeps
   invocation "available"; **no concept cites `WT/06`**; 0 src hits for Portal/SpawnGrant. **Not propagated.**
9. **Composition Manifest / system describe** (old SPEC §8): one read surface listing contract versions,
   behaviors, lanes and their control semantics, models, templates, policy limits. Partly realized by
   lane describe, Model Catalog and Selection Workspace; `system describe` absent (`docs/knowledge/interfaces.md:72`). **Partial.**
10. **Prompt-cache policy as a cost governor** (`MCG/MISSION_CONTROL_SUPPLEMENT.md` §5, old SPEC §12.2).
    Realized only as a Deep Agents feature row `anthropic.prompt_caching` (`adapters/deep_agents/routes.py:143-153`)
    and cache usage in frames; no concept mentions prompt caching. **Partial.**
11. **Product material for the `goals` category and Ideas**: goal families and workflow templates
    (research flywheel, app build loop, course, experiments as swarm variants, RSI optimizer) from old
    SPEC §13.4/§16 and SUPPLEMENT §3/§6; MissionFS and deliverable review (`GMC/MISSION_CONTROL_SYSTEM_PROPOSAL.md` §H);
    narrative/as-of reads and improvement protocol (`MCG/MISSION_STORAGE_AND_RETRIEVAL_PROJECTION.md` §5-§7);
    intra-mission conversation UX (`MCG/2026-09-19_…SEED.md` §2-§3); sandboxed interview sessions
    (`EXP/EXPERIENCE-AND-STREAMS.md:19-47`, not built per `docs/knowledge/authoring.md:118`).
    **Not propagated**; none is near-goal work.
12. **Naming conventions** (`GMC/MISSION_CONTROL_SYSTEM_PROPOSAL.md` §B: `mc.<contract>.v<major>`, CLI
    noun-verb, `mission_<resource>_<verb>` MCP tools, `mc://` refs). Largely followed (MCP tool names,
    `mc://` in `application/streams/service.py:509`) but not written down outside the proposal. **Not propagated.**

## 3. File table

| Path (MCG/…) | Lines | Last commit | Holds; key contracts | Propagation (code check) | Disposition |
| --- | --- | --- | --- | --- | --- |
| `README.md`, `index.md` | 17, 5 | 10-09 | Entry; reading order; `index.md` "current owner expansion" | entry still used; `index.md` adds nothing (`GMC/DOCUMENTATION-CLEANUP.md:27`) | README: rewrite as live/historical map; `index.md`: delete |
| `MISSION_CONTROL_SPEC.md` | 923 | 10-09 | Pre-consolidation spec: binding levels, Composition Manifest, peek, goal families, experiments, research zones/clocks, A2A, dashboard | superseded by `GMC/SPECIFICATION.md` (banner :1-5); items 4, 9, 11 above not propagated | archive after harvest (§6 step 4) |
| `MISSION_CONTROL_PRESPEC.md` | 1005 | 10-09 | Product foundation; personal intelligence, course, RSI ideas | superseded; product ideas unpromoted (`DOCUMENTATION-CLEANUP.md:41`) | archive; harvest goals/Ideas |
| `MISSION_CONTROL_SYSTEM_PROPOSAL.md` (root) | 1493 | 10-09 | Old proposal: WebSocket frames, handler catalog, trace digest, deliverable lifecycle | superseded by ADR-0016/0036, `events-and-commands.md:52-53` (SSE implemented) | archive |
| `MISSION_CONTROL_SUPPLEMENT.md` | 446 | 10-09 | Credits ledger, prompt caching, templates, FileEdit harness, inter-agent law, source intelligence, memory manager | superseded 09-07 and 10-02; items 10-11 partial; `apply_patch` in 4 src files | archive; harvest prompt-cache + Ideas |
| `MISSION_STORAGE_AND_RETRIEVAL_PROJECTION.md` | 297 | 10-09 | Relational timeline, point-in-history reads, narrative, improvement loop | partial: `transcript-projection.md`, `precise-fork.md`, ADR-0055; narrative 0 src hits | archive; Idea for narrative |
| `2026-09-19_CONTROL_PLANE_EXPERIENCE_AND_SANDBOX_SEED.md` | 113 | 10-09 | Intra-mission conversation, dashboard lifecycle, sandbox seed | partial: ADR-0027/0037 (seeding); conversation UX not | archive; Idea |
| `ACCEPTED_APPLICATION_AND_STORAGE_ARCHITECTURE.md` | 197 | 10-09 | 2026-10-02 owner approval: apps, Auth, buckets, binding | propagated: ADR-0002/0003/0009/0017/0024 | archive (approval record) |
| `HANDOFF.md` | 384 | 10-09 | Interview log Rounds 1-3, M0-M8 plan | decisions live in `WT/`; M0-M8 obsolete | archive |
| `EXECUTION_DIRECTIVE.md` | 143 | 10-09 | "Code now" directive, clean-break policy | superseded (`DOCUMENTATION-CLEANUP.md:21`); policy in ADR-0001 | delete |
| `validate_spec.py` | 89 | 10-12 | Link/fence checker for `GMC/` | no consumer; `docs/tools/check_docs.py` replaces it | delete |
| `GMC/SPECIFICATION.md` | 344 | 10-29 | System authority: binding registry, authoring flow, `MissionDefinition@1`, compiler, execution semantics, capabilities, harness, Temporal, public surface, scopes, errors | propagated: ADR-0001..0022, 10 concepts; harness **implemented** (`application/execution/harness/protocol.py:72`); `/v1/applications/{app}` **implemented** (`interfaces/http/artifacts.py:53`); `ApplicationBinding` **implemented** (`application/installations/registry.py:83`); `AuthoringSession@1` **not built**; scopes **contradicted** (§4) | stays normative; rewrite contradicted paragraphs (§4) |
| `GMC/RUNTIME-CONTRACTS.md` | 189 | 10-27 | Naming map, canonical JSON, lifecycle IDs, harness, Agent Server protocol, frontier `direct_model` | partial: harness and async children propagated (`lanes-and-harness.md`, `async-children.md`); `mc.mission_run.v1` coexists with `belllabs.*` workflow names (`adapters/temporal/workflows/belllabs_run.py:39`, `goal_directed.py:209`); `direct_model` lane not in `domain/execution/lanes.py:78-88` | stays; amend lane list and names |
| `GMC/DATABASE.md` | 232 | 10-27 | Logical schema, transaction protocols, seeds, runtime persistence | propagated: `persistence.md`, db-contract; §Runtime persistence (:226-232) **contradicted** by ADR-0017 | stays; amend :226-232 |
| `GMC/OUTPUT-CONTRACTS.md` | 599 | 10-31 | Obligations, submission, current sets, sealed transfer, family rules, worked cases | propagated: `output-contracts.md`, ADR-0058..0062, `collections-and-current-sets.md`; 21 src/doc citers | stays normative (the most current file) |
| `GMC/IMPLEMENTATION.md`, `EVIDENCE.md`, `VALIDATION.md`, `DOCUMENTATION-CLEANUP.md` | 114, 76, 25, 68 | 10-09 | 7-phase plan and matrix; source map; 10-02 checks; deletion plan | superseded by `provider-consolidation-2026-10/LEDGER.md` and `release-and-qualification.md`; every `WT/` file still links IMPLEMENTATION in its header | archive; repoint `WT/` headers to the ledger |
| `GMC/CODEBASE-ORGANIZATION.md` | 135 | 10-09 | Repo boundaries, runtime layout, process roles, Biotech installer | propagated: `architecture.md`, `AGENTS.md:53-66`; Biotech installer is the proposed `database-component.md` (`CONCEPT-LISTS-DRAFT-2026-11.md` persistence row) | fold into `database-component.md`; archive |
| `GMC/MISSION_CONTROL_SYSTEM_PROPOSAL.md`, `GMC/README.md` | 173, 23 | 10-09 | Naming conventions (§B), lanes, storage, product §H-§J | §B not propagated (item 12); rest superseded | fold §B into `architecture.md` (or GLOSSARY note); archive |
| `GMC/WORKED-MISSION.md` | 99 | 10-09 | Worked research/ingestion and async-child fixtures | examples predate Manifest v2 (ADR-0022/0034) | archive |
| `EXP/ARCHITECTURE-AND-ADRS.md` | 74 | 10-09 | ADR-X01..X06 | propagated: ADR-0001/0005/0007/0008/0009/0016 | archive |
| `EXP/CONTEXT-STATE-AND-CONTROL.md` | 88 | 10-27 | Context/handoff/memory/message contracts, middleware placement, ordering and urgent stop | partial: items 3, 5; stop fence and queue/inject propagated (ADR-0008/0032, `interventions.md`) | fold into `deep-agents-lane.md`, `agent-configuration.md`, `context-and-continuation.md`; archive |
| `EXP/CATALOG-AND-ENVIRONMENTS.md` | 53 | 10-09 | Catalog interface, workspace manifest, retrieval offload | propagated: ADR-0013/0020/0024/0025, `capabilities.md`, `environments.md` | archive |
| `EXP/KNOWLEDGE-SERVICES.md` | 119 | 10-27 | KS intent artifacts, plan/apply/recover | propagated: `knowledge-services.md`, ADR-0059/0060; outranks the concept in search | archive (remove from corpus) |
| `EXP/EXPERIENCE-AND-STREAMS.md`, `TECHNOLOGY-EVIDENCE.md` | 164, 70 | 10-09 | Interview sessions, review, generative UI/MCP Apps, streams | ADR-0016/0036 propagated; interview and MCP Apps **not built** (0 src hits) | archive; Ideas |
| `EXP/DEPLOYMENT-AND-RELEASE.md` | 71 | 10-09 | Topology, compute allocation, gates | gates in `release-and-qualification.md`; roadmap now `sprint-oc/CLOUD-ENVIRONMENTS-…-2026-10-31.md` | archive |
| `EXP/REQUIREMENTS.md`, `TEAM-WORKSPACE.md`, `CHANGED-PATHS.md`, `VALIDATION.md`, `README.md`, `WORKED-SCENARIOS.md`, `issues/` (44 files, 2851 lines), `issues.json` (2564), `schemas.json` (1376), `build_packet.py` (1294), `validate_packet.py` (250), `validation-results.json` (102) | 87+41+61+21+17+87 | 10-09 (validate 10-12) | 26-requirement map, 44-issue backlog, team protocol, JSON schema seeds | backlog stale since 10-03 (`AGENTS.md:164`); Linear and ledgers replaced it; no consumer of the scripts or schemas | archive whole `expansion/` remainder |
| `WT/index.md` | 28 | 10-09 | Annex map; "all four workflow systems will be implemented" | contradicted by OC-D204 | stays; rewrite to three systems + Swarm profile |
| `WT/00-EXECUTION_PROGRAM_MODEL.md` | 297 | 10-29 | Behavior taxonomy, recursion, nesting matrix, lifecycle/phase/outcome, failure class | propagated: `workflow-systems.md`, `recursive-composition.md`, GLOSSARY; `program_node.behavior_kind` check **implemented** (`component/migrations/0002_authoring.sql:174`) | stays normative |
| `WT/01-STAGE_GRAPH.md` | 206 | 10-29 | Relationships, release, revisit regions, fan-out, outputs, completion | propagated: `workflow-systems.md` (WI-08 routes/revisits **tested**); fan-out and provisional **not built** (item 6) | stays; concept adds gap |
| `WT/02-GOAL_LOOP.md` | 282 | 10-27 | Full Goal Loop (item 2) | partial: GoalDirected subset only | stays; **new concept `goal-loop.md`** (domain-model, workflow-systems group) |
| `WT/03-PARALLEL_SWARM.md` | 197 | 10-29 | Members, variants, completion policy, convergence, governors; OC-D204 banner | GLOSSARY current; concept stale; code four-family | stays; rewrite concept; ADR for OC-D204 |
| `WT/04-EVALUATOR_OPTIMIZER.md` | 161 | 10-27 | Roles, independence, rubric versioning (KS owns rubric schema), rounds | no OC-D205 banner; concept stale | stays; add OC-D205 banner; ADR for OC-D205 |
| `WT/05-EXECUTORS_AND_DURABLE_CONTROLS.md` | 251 | 10-27 | Execution identity, Agent Executor, executor kinds, retry, durable controls | partial: `durable-controls.md` (Timer/Proof Gate not program nodes, `:69`), `completion.md`; binding superseded by ADR-0063; executor kinds **not built** | stays; amend §3.1 and §8 |
| `WT/06-MISSION_INVOCATION.md` | 158 | 10-27 | Invocation modes, child definition source, Portal, Spawn Grant, Mission Graph | not propagated (item 8); **not built** | stays; new concept or fold into `mission-chains.md` (Q6) |
| `WT/07-MISSION_REVISION_AND_RUNTIME_EVOLUTION.md` | 199 | 10-27 | Revision flow, scheduling head, transition impact, carry-forward, state machines | propagated as specified-not-built (`revisions.md:37-52,90`); `run_revision_transition` table **implemented** (`0003_execution.sql:51`) | stays normative |
| `WT/08-CONTINUATION_COMPACTION_AND_TRANSFER.md` | 195 | 10-27 | Checkpoint contract, triggers, failed compaction, transfer | propagated: ADR-0039/0041, `continuation-checkpoint.md`; five open questions (§15) | stays |
| `WT/09-EVENTS_COMMANDS_AND_STREAMS.md` | 159 | 10-27 | Event envelope, Native Event Store, commands, authority | propagated: ADR-0028/0036/0040/0049/0054, `events-and-commands.md` | stays |
| `runtime-facts/CURSOR_SDK_FACTS.md` | 161 | 10-09 | Cursor SDK 1.0.31 facts | superseded by `cursor-lane.md`, `docs/research/2026-10-07-coding-lane-surfaces.md` | archive (remove from corpus) |
| `runtime-facts/EVE_FACTS.md` | 163 | 10-09 | Eve/Vercel facts | ADR-0014 excludes Eve; still in default corpus | archive |

## 4. Contradictions between this folder and current code or concepts

1. **Precedence is circular.** `AGENTS.md:145` ranks the spec pack above ADRs;
   `GMC/SPECIFICATION.md:337` says ADR amendments govern the spec prose, and its amendment list stops
   at ADR-0022 although ADR-0023..0067 also amend it (e.g. nine lanes, ADR-0035/0050).
2. **Workflow-system count.** OC-D204/205 (spec, GLOSSARY) vs four families in code
   (`domain/resolution/configuration.py:53`), in `WT/index.md`, `workflow-systems.md` and both
   specified-only concepts (§2 item 1).
3. **Lanes.** `WT/05` §3.1 `agent_runtime_kind: deep_agents | cursor_cloud | direct_model` and §8 "No
   Cursor local lane is required"; `SPECIFICATION.md:40,58-65` (Deep Agents, Cursor Cloud, direct
   provider) vs nine profiles in `domain/execution/lanes.py:78-88` (ADR-0035/0050), no `direct_model`.
4. **Runtime persistence.** `GMC/DATABASE.md:226-232` and `SPECIFICATION.md:44` (private schema in the
   business database) vs ADR-0017 (separate database); only the spec carries the amendment (:339).
5. **Scope vocabulary.** `SPECIFICATION.md:285` (`mission.read`, `mission.author`…) vs code grants
   `workflow_run.*` (≈25 distinct, e.g. `workflow_run.read`, `workflow_run.admit`) with only
   `mission.author` and `catalog.read` from the spec list (`application/authoring/manifest_submit.py:78`).
6. **Temporal names.** `RUNTIME-CONTRACTS.md` and `GMC/MISSION_CONTROL_SYSTEM_PROPOSAL.md` §B require
   `mc.*` registrations; `belllabs.run.v1`, `belllabs.goal-directed`, `belllabs.linked-run` remain
   (`adapters/temporal/workflows/belllabs_run.py:39`, `goal_directed.py:209`, `linked_run_workflow.py:77`).
7. **Repository location.** `SPECIFICATION.md:299` and `EXP/ARCHITECTURE-AND-ADRS.md` ADR-X01 order a
   rename into `Biotech/mission-control/`; the repo is `platform/mission-control` (BellLabs `AGENTS.md`).
8. **Delivery plan.** Every `WT/` header says `GMC/IMPLEMENTATION.md` is "the current delivery plan";
   the live plan is the provider-consolidation ledger and Sprint OC NEXT-SESSION.
9. **Missing-output policy** is a general Agent Executor rule (`WT/05` §3.4) but is realized on the
   Cursor lane only (`adapters/cursor/local.py:207`); not found in the Deep Agents adapter.

## 5. Owner questions

1. **Precedence.** Should ADRs outrank the spec pack for decisions, with the pack as the target-behavior
   contract that ADRs amend? *Recommend yes*: `ADR > spec pack > concepts`, and the spec's amendment
   section becomes a generated list of amending ADRs.
2. **OC-D204/OC-D205 as ADRs.** Record both as new ADRs (0068 "Swarm is a Stage Graph profile", 0069
   "Evaluator Optimizer reuses GoalDirected machinery") and rewrite the three workflow concepts now,
   leaving code vocabulary consolidation to a tracked Sprint OC item? *Recommend yes.*
3. **Goal Loop concept.** Add `goal-loop.md` that states the target model and the built GoalDirected
   subset side by side, instead of leaving it in `execution.md:4`? *Recommend yes; it is the gap on the
   nearest goal.*
4. **Deep Agents middleware order.** Promote the required middleware order and extension profile
   (item 3) into `deep-agents-lane.md` as specified-vs-built, or into an ADR? *Recommend concept now,
   ADR only when `mc.extension_profile.v1` is built.*
5. **Archive scope.** Move the nine root files (EXECUTION_DIRECTIVE and `validate_spec.py` deleted),
   the historical `GMC/` files, all of `EXP/` and `runtime-facts/` to
   `docs/specs/archive/mission-control-general-2026-10/`, out of the search corpus? *Recommend yes, after
   the harvest in §6 step 4.*
6. **Child Mission Invocation.** New concept `child-missions.md`, or a "not built" section in
   `mission-chains.md`? *Recommend a section in `mission-chains.md`; it is not near-goal work.*
7. **Product ideas.** Harvest goal families, experiments, RSI, MissionFS, narrative, interview UX and
   generative UI as SPEC-01 Ideas (`GLOSSARY.md:846`) rather than concepts? *Recommend Ideas, with a one-
   line pointer from the future `goals.md`.*
8. **Spec rewrite depth.** Fix only the contradicted paragraphs (§4 items 3-8) in the live normative
   files, or rewrite SPECIFICATION wholesale? *Recommend targeted fixes now (startup mode); wholesale
   rewrite only after W1.*

## 6. Proposed execution steps for the refactor agent

1. Wait for answers to Q1, Q2, Q5. Do not change code; this is documentation only.
2. **Decisions.** Write ADR-0068 (OC-D204) and ADR-0069 (OC-D205) citing
   `sprint-oc/DECISIONS.md:347-348` and the answers file; add OC-D205 banner to `WT/04`; rewrite
   `WT/index.md` to three systems plus the Swarm profile; update `AGENTS.md:145` precedence per Q1 and
   regenerate the docs index (`python docs/tools/agents_docs_index.py`; notes in `docs/agents/index-notes.toml`).
3. **Concepts** (each ≤160 lines, `category:` per SPEC-01, cite source and spec sections):
   rewrite `workflow-systems.md`, `parallel-swarm.md`, `evaluator-optimizer.md` (OC-D204/205, code still
   four-family, `describe.py:158` unqualified, wi14/wi15 unreviewed); create `goal-loop.md` (item 2);
   add middleware order and extension profile to `deep-agents-lane.md` (item 3); add Operating Contract,
   missing-output policy (Cursor-only) and binding levels to `agent-configuration.md` (item 4); add
   memory namespaces and message protocol status to `context-and-continuation.md` (item 5); add fan-out,
   provisional bindings and executor kinds as gaps in `workflow-systems.md` (items 6-7); add a Child
   Mission Invocation section to `mission-chains.md` (item 8); add `system describe` status to
   `interfaces.md` and prompt caching to `agent-configuration.md` (items 9-10); add the naming table to
   `architecture.md` (item 12).
4. **Harvest before archive.** Create Idea records (Q7) for: goal families and workflow templates,
   experiments as swarm variants, RSI optimizer, MissionFS/deliverable review, narrative and
   point-in-history reads, intra-mission conversation, sandboxed interview sessions, generative UI/MCP
   Apps, source intelligence, memory manager, FileEdit harness. Cite the source file and section.
5. **Fix live normative files** (§4 items 3-8): `WT/05` §3.1/§8 → point at ADR-0035/0050/0063;
   `GMC/DATABASE.md:226-232` → ADR-0017; `SPECIFICATION.md` lanes, diagram, scopes (mark
   `workflow_run.*` as current), :299 rename, amendment list to ADR-0067; `RUNTIME-CONTRACTS.md` lane list
   and the `belllabs.*` names as known divergence; repoint every `WT/` header from `IMPLEMENTATION.md`
   to `docs/specs/provider-consolidation-2026-10/LEDGER.md`.
6. **Archive** per §3 dispositions into `docs/specs/archive/mission-control-general-2026-10/` with a
   README (source path, date, superseded-by); delete `EXECUTION_DIRECTIVE.md`, `MCG/index.md`,
   `MCG/validate_spec.py`. Update inbound links: `docs/knowledge/index.md:13`, `GLOSSARY.md:169`,
   ADR source lines, `src/` docstrings citing `WT/05,06,08,09` (paths stay valid if `WT/` stays).
7. **Corpus.** Drop `runtime-facts` and `expansion` from `DEFAULT_ROOTS` (`docs/tools/okf_search.py:38-40`)
   by archiving them; rewrite `MCG/README.md` as the map of live files only.
8. **Verify.** `python docs/tools/check_docs.py`, `python docs/tools/validate_okf.py`,
   `python docs/tools/program_ledger.py check`; rerun the retrieval fixtures that hit `EXP/` (FX-MC rows
   in `RETRIEVAL-AUDIT-BASELINE-2026-11.md:363-371`). Add a ledger row for this file and the refactor.

Not verified here: Linear state of any issue; whether Swarm/EO branches `sprint-oc-wi14`/`wi15` change
item 1; test pass status (nothing was run); whether the Deep Agents adapter enforces missing outputs
through another name.
