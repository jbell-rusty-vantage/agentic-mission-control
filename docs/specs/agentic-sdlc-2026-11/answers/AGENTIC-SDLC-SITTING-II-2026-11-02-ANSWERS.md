---
type: Interview Answers
title: "AGENTIC-SDLC, sitting II: the owner's answers"
description: "The decisions the owner took in sitting II of INTERVIEW-NAVIGATION-AND-KNOWLEDGE-2026-11-02.md on 2026-11-02, each with its id, the owner's words, what it changes, what it becomes (ADR, spec section, glossary term, Linear issue) and where it was folded in. Open while the sitting runs; final when every decision has a destination."
tags: [mission-control, interview, answers]
interview: ../INTERVIEW-NAVIGATION-AND-KNOWLEDGE-2026-11-02.md
sitting: "II"
date: 2026-11-02
status: open
---

# AGENTIC-SDLC, sitting II: answers

Instruction: `INTERVIEW-NAVIGATION-AND-KNOWLEDGE-2026-11-02.md` (front matter `interview:`). Recorded by the interviewing agent on
2026-11-02. **Status `open`** while the sitting runs; set `final` when every decision below has a
**Becomes** and a **Folded** entry, which `program_ledger.py check` then enforces.

How to fill it: one row per decision, in the order asked. Quote the owner's words in **Answer**; put
the agent's reading in **What it changes**, never in **Answer**. A decision the owner did not answer
goes under *Assumptions*, not in the table.

## Decisions

| ID | Source | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AS-D21 | ID-1 | May the sitting also finish code work the state inventories expose? | "Finishing some codework (eg migrations, stale documentation, incorrectly tracked or untracked, and in the case of a glaring logical flaw or error) can be part of the work we construct in this session" | 2026-11-01 | Scope widens from design-only to design plus repair: the doc-vs-code discrepancies, version/migration gaps, untracked or wrongly tracked files and glaring defects found by STATE-*.md are fixed and committed on `sprint-oc` in this session (startup delivery mode). Sprint OC W1 qualification and S1 stay out of scope. First act: the syntax-breaking edit in `cursor_native.py:60` restored to `HEAD`. | none (session scope; repair log in the STATE inventories) | [STATE-mission-control-2026-11.md](../STATE-mission-control-2026-11.md) |

| AS-D22 | ID-1 | Q8 The long-term goals, in the owner's words | Full text in *Q8 verbatim* below. Opening: "3 years out I envision having a top course platform in ai agent engineer that is fed by mission control and knowledge services recurring deep research and content workloads." Close: "These are goals that inform features. The features haven't been fully developed yet for biotech and ai engineer . Mission control, knowledge services have been main focus. Schema optimizations and service-specific features come after that. (They are fed by missions)" | 2026-11-01 | Four `goals` concepts and `GOALS-CHARTER-2026-11.md` are written from this text (structure in *Mental model restated*). Goals are stated as outcomes, thresholds and architectural requirements, never dates ("We talk in terms of compute, tokens and architectural requirements"). First course named: Agent Engineering, ages 9-15. Biotech deploys as schema slices with entity thresholds. Evidence assertions and source attribution with human and agent judgement become a cross-domain invariant. | spec GOALS-CHARTER-2026-11.md; four `goals` concepts (S2-S4) | pending (charter written after Q9 confirms the restated model) |
| AS-D23 | ID-1 | Q10 Every `OVE` issue names the goal it serves; `trace` prints it? | "Yes that sounds great" | 2026-11-01 | New `OVE` issues carry `Goal: <repo>/goals#<anchor>`; `sdlc check` resolves it against the goals concept; `trace` prints it first; PR bodies repeat it. No back-fill. The anchors are the goal headings of AS-D22. | spec SPEC-01 §6.1, §9; OVE-207 acceptance | pending |
| AS-D24 | ID-1 | Q1 What counts as current truth? | "I need current true state determined and I need help doing it. mission-control-general has concepts and architectures not yet propagated. I think we are going to have to concentrate on one codebase at a time and do exploration looking for current state, documentation that is stale or that hasn't been integrated and is good and worth keeping or reformulating , and then do the documentation and then move on to the next codebase" | 2026-11-01 | Truth is established by a per-codebase **truth pass** (explore current state → triage every document: current / stale / un-integrated-and-worth-keeping / reformulate / archive → write the concepts → next codebase), one codebase at a time, owner decisions taken per codebase. The four-label rule (implemented/tested state; integrated/qualified with proof path) is the classification the pass applies; whether private `.scratch/` paths may be cited is carried to round 2 (see Assumptions AS-A3). `platform/mission-control/mission-control-general/` (99 tracked files: SPEC, SUPPLEMENT, PRESPEC, SYSTEM_PROPOSAL, storage projection, workflow-types, runtime-facts) is named input for the Mission Control pass. | spec SPEC-01 §11 (truth pass inside S2..S4); NAVIGATION-DESIGN.md | pending |
| AS-D25 | ID-1 | Q2 Promote W0/provenance, keep W1 and coordinator proposal working, park fault tolerance, archive Run 2? | "Yes I approve those. Yes already completed need to go to archive. I can provide more decisions when we concentrate on each" | 2026-11-01 | Promote: Sprint OC W0, R0-R7, provenance sprint OVE-204, coordinator OVE-182 into concepts during the MC truth pass. Working: W1 (D1-D30), coordinator proposal beyond OVE-182. Parked: fault tolerance. Archived: everything completed (Run 2 finish material, older handoffs, the provenance packet once its rows are `done`). Further per-program decisions are taken inside each codebase's truth pass. | spec SPEC-01 §11; ledger moves in the MC truth pass | pending |
| AS-D26 | ID-1 | R1 Push the repaired `sprint-oc` branches; apply the ready AIDB migration to the remote? | "Yes we can push to remotes and perform migrations that are ready." | 2026-11-01 | Pushed 2026-11-01: MC `ce9d2f13..c73cb355`, KS `22b47d2..94cbb7d`, BKS `8e8d3d1..ed2859a`, AIDB `74fd2c3..4c4e76d`. AIDB 0.6.0 head `20261031010000` applied to aieng-db `wkythqbofmckbuoothhn` through the contract installer (receipt in the AIDB repo). MC `0071`/`0072` are not "ready" (not in a release) and stay local. | none (operational; receipts in the four repos) | [STATE-ai-engineer-db-contract-2026-11.md](../STATE-ai-engineer-db-contract-2026-11.md) |

| AS-D27 | ID-1 | Q16 Where does the truth pass sit, and in what order? | "Allow me to steer a bit right now. Let's go into each codebase now and resolve these needs. You can then spin up a Sonnet 5.5 agent after clarification is achieved to implement the documentation refactor and perform retrieval. Does that sound good. There are A LOT OF FILES and a lot of drift so it's best to just concentrate one at a time and work this way. Let's start with mission-control" | 2026-11-01 | The sitting turns into per-codebase truth passes now, Mission Control first: agent exploration → owner clarification round(s) → a Sonnet 5.5 agent implements the documentation refactor and runs retrieval checks → next codebase. The MC round also settles the format decisions (Q7, Q13-Q15) with MC as the worked example, so the refactor writes concepts once. Q3-Q6 move into each codebase's round. | spec SPEC-01 §11 (truth pass precedes S2..S4 tooling); NAVIGATION-DESIGN.md | pending |

| AS-D28 | ID-1 | (owner addition) Where do research reports and hard-won tooling facts live? | "Hey I forgot to state that research reports (like research I have agents do on certain technologies) and extremely useful tooling information (like say for deep agents that we find out during research that is not easily retrieved or known) should be in their own space. This adds a dimension to knowledge." | 2026-11-01 | A second knowledge dimension beside the nine categories: **research** (external technologies, libraries, providers; dated, versioned, sourced) distinct from **concepts** (how our system works). Shape decided in Q18. Evidence it is needed: `application/environments/network.py:31` cites `research/daytona.md`, which does not exist; `docs/research/` holds one file; the Cursor and Eve fact sheets sit in `mission-control-general/runtime-facts/`. | spec SPEC-01 §5 (amendment); NAVIGATION-DESIGN.md | pending |
| AS-D29 | ID-1 | Q1b May a concept cite a private `.scratch/` path as proof? | "Yes only commited things. Accepted." | 2026-11-01 | Concepts cite committed receipt summaries only; the truth pass writes missing summaries. `check` rule: a concept citation into `.scratch/` fails. Closes AS-A3. | spec SPEC-01 §3.3 rule 1 (amendment) | pending |
| AS-D30 | ID-1 | Q7 Depth: concept explains and cites, module block carries entrypoints/tests, glossary the term; manifest and command examples allowed? | "Yes I like that split and code detail can go into it especially snippets of important deep modules to illustrate." | 2026-11-01 | Accepted split, widened: a concept may carry short snippets of important deep modules' interfaces to illustrate (owner's words). Agent reading: each snippet carries its `file:line` anchor and `check` verifies the snippet still matches the source (digest), so illustrations cannot silently drift. | NAVIGATION-DESIGN.md (concept grammar) | pending |
| AS-D31 | ID-1 | Q13+Q14 Budgets, grammar (DOC-02 with edits G1-G16), sidecars, update rules, migration-key rule, as one block? | "Q13 + 14: Yes approved" | 2026-11-01 | DOC-02 amended by G1-G16 becomes the AGENTS.md section of NAVIGATION-DESIGN.md: 4 KiB hand-written, 8 KiB `sdlc` block, own caps and markers for infra and programs, 14 KiB file; names-only collapse above twelve with Deep Agents pins first; module blocks ≤2 KiB + ≤2 KiB hand-written with `Verify:`/`Program:`; `Tracker:`, `Authority:`, `pending`; programs derived from ledgers; thresholds change by ADR plus `hold` PR; `check` fails on a reused migration key. SPEC-01 §12 item 7's 12 KiB is struck. | NAVIGATION-DESIGN.md; ADR (thresholds) | pending |
| AS-D32 | ID-1 | Q15 Retrieval design as one block; plus task-shaped fixtures, cross-repo, trace | "Q15: Yes approved. And I believe you are stating real fixtures here. Can we please try the beginnings of a real task and see what is retrieved. Like if we said \"Add a new sandbox provider configuration to deep agents and make sure it works across all active workflow types\" We want to see what is retrived. Fixtures like that in addition. And yes the cross repo is important. I love it. REMEMBER the trace too ! That is a major boon for an agent and me to see how specs and issues developed." | 2026-11-01 | Q15 block accepted. Adds a second fixture kind, **task fixtures** (a real engineering task with an expected set of concepts, code entrypoints, research notes and the hidden gap facts), measured by set recall; first case run on 2026-11-01 (results in NAVIGATION-DESIGN.md). Cross-repo pointer concepts plus `search --workspace` confirmed. `trace` stays in S1 and becomes part of retrieval (Q20). | NAVIGATION-DESIGN.md; OVE-207 acceptance | pending |

| AS-D33 | ID-1 | (owner context for the MC pass) What Mission Control is and what must be completely known | Full text in *MC context verbatim* below. Key lines: "I just deleted most of mission-control-general. We want to delete this folder fully in this process." "The mechanics of stage graph, goal directed, parallel swarm, evaluator optimizer and linked workflows at the scheduling, output contract obligation , context transfer and agent runtime and capbility configuration should be COMPLETELY KNOWN." "The goal of bringing together these powerful agent platforms into a robust controllable missions and supplying this as a real service is the major goal." | 2026-11-01 | `mission-control-general/` is deleted in full (86 files already removed in the working tree; `workflow-types/` and two root files remain until harvested from `HEAD`). MC-1 resolves by deletion: no spec pack, so authority is code (what runs) and ADRs (what was decided). The MC knowledge map is rebuilt around the owner's model (REFACTOR-PLAN §2). New goals recorded: per-policy mid-workflow mutation, local↔cloud in one session across providers, provider batch APIs with workflow waits, the human review loop (continue / reject with feedback and redo / start new). | spec REFACTOR-PLAN; `goals` concept; ADR-0068 | pending |
| AS-D34 | ID-1 | MC-2 ADR-0068 for OC-D204/D205, rewrite the workflow concepts, `goal-loop.md`, code vocabulary as an OVE issue | "MC-2: Yes approved" | 2026-11-01 | ADR-0068; `workflow-systems`, `parallel-swarm`, `evaluator-optimizer` rewritten; new `goal-loop`; four→three family vocabulary filed in Sprint OC. | ADR-0068; OVE issue (to file) | pending |
| AS-D35 | ID-1 | MC-3 Deep Agents group of three plus module block, research folder and two code issues | "MC-3: Yes" | 2026-11-01 | `deep-agents-lane` (absorbs turn-stops; middleware order specified-vs-built; sandbox backends incl. Daytona half-wired), `agent-configuration` (compile path, model bindings), `deep-agents-children`; generated module block; `docs/research/deep-agents/`; issues: Daytona factory, `describe.py:80,113`. | OVE issues (to file); REFACTOR-PLAN | pending |
| AS-D36 | ID-1 | MC-4 the remaining dispositions as one block | "MC-4: Yes." | 2026-11-01 | ADR acceptance (23, hold 0053) and markers; concept fixes (25 contradicted, 7 stale), merges and new concepts; program archive (63 after harvest), NS split, sitting-I track retired, D1-D9 folded, fault tolerance parked; other surfaces (31 archive, 5 delete, `skills/` block); `.scratch` untracked without history rewrite; fixtures (≥18 screening, ≥10 held-out, 34 audit misses, task fixtures). | REFACTOR-PLAN | pending |

| AS-D37 | ID-1 | Launch the MC refactor (REFACTOR-PLAN) with Q18-Q20 as recommended? | "Yes launch them." | 2026-11-01 | Phase A launched: three Sonnet 5.5 agents (workflows, runtime, platform). Q18 (research space), Q19 (task fixtures, code entrypoints as documents) and Q20 (trace block in `context`) taken as recommended. Batch prototype location unanswered: A2 searches the workspace, else writes `provider-batch` as a goal from AS-D33. | spec REFACTOR-PLAN; NAVIGATION-DESIGN.md | [REFACTOR-PLAN](../truth-pass/mission-control/REFACTOR-PLAN.md) |

| AS-D38 | ID-1 | MC-5 What is the materialized filesystem workspace for sandboxed agents called, and how does it relate to the Selection Workspace, MCP and CLI? | "Yes I mean the workspace that is created particularly for mission control agents searching through mission control so they can use it. This is not to be confused with any official codebase documentation. [...] Mission control has an mcp server . Mission control has a cli. We have or will build a mission control workspace that materializes for a sandboxed agent much like the database schema workspaces. It's a filesystem navigation strategy." Then: "Yes sounds good. And the catalog workspace is additional to the mcp and the cli commands you mentioned. I'm not saying we can't have a missionctl search that works with the catalog workspace I'm just saying the catalog workspace is something distinct and is purposed for sandbox agents in a filesystem" | 2026-11-01 | New term **Catalog Workspace**: a generated, read-only filesystem rendering of the catalog (workflow types, lanes and providers with lifecycles and describe matrices, models, capabilities, sandbox profiles, configuration items, worked examples, task pages), pinned to a release and mounted into a sandboxed agent's Workspace, navigated like the AIDB schema workspace (START_HERE, INDEX, search index, ≤4 reads). Distinct from the codebase documentation and from the Selection Workspace (the built API: search + check over HTTP, MCP `mission_search`/`selection_check`, `missionctl search`/`workspace check`, which posts to the API). Additional to MCP and CLI; a `missionctl search` over the Catalog Workspace may come later. Not built. | GLOSSARY Catalog Workspace; OVE issue (to file); `selection-workspace`, `coordinator-surface`, `goals` sections; task fixture | pending |

| AS-D39 | ID-1 | How does the session close (after the MC truth pass)? | "I removed those originals in /platform already. -- Yes now I want you to finish out this session with these exact tasks. 1. Fix the concept wording 2. The AGENTS.md compressed generated file contains directory (like actual code directory) representations correct with descriptions . Are we creating AGENTS.mds inside of all major directories ? Let's enhance this some. Isn't there suppose to be AGENT.md generator script ? 3. This all has to be wrapped up in an agent skill and shouldn't that be in the agentic-sdlc and pinned in the other repos starting with mission control ? 4. add push and commit everything and write a detailed HANDOFF for the next session to continue the work. Let's perform some more experimentation on mission control and then move to knowledge services" | 2026-11-02 | (1) S07/S21 wording fixed (`760e6a6e`); (2) `.sdlc/modules.json` plus generated module guides in 34 major directories and the root code map from it (`1a395c72`, `da8b4b06`, `b53e81e6`); (3) skill `sdlc-docs` in `platform/agentic-sdlc/skills/` (`a1da6e6`), vendored and pinned in MC; (4) everything committed and pushed, `HANDOFF-2026-11-02.md` written. Next session: MC experimentation, then the KS truth pass. R2 (push) answered yes by this row; R3 (Linear filing) and R5 (originals removed by the owner) closed or carried in the handoff. | none (session close; HANDOFF-2026-11-02.md) | [HANDOFF](../HANDOFF-2026-11-02.md) |

`Source`: the idea `ID-n` the sitting serves, or `-`.
`Becomes`: `ADR-NNNN`, `spec <file> §n`, `GLOSSARY <term>`, `OVE-n`, or `none (reason)`.
`Folded`: the link to the document edited to carry the decision, or `n/a`.

## Mental model restated

What the system does after these answers, in the owner's terms: a manifest fragment, a command, what
they will see. Record the owner's correction if they gave one.

## Q8 verbatim (owner's words, 2026-11-01)

> 1. 3 years out I envision having a top course platform in ai agent engineer that is fed by mission control and knowledge services recurring deep research and content workloads. We haven't yet full consolidated the features into a spec. There is documentation I believe that states it. Think of this spectrum of capabilities
>
> System courses produced by us that are based on the latest research and tooling. Courses auto update and we maintain revisions and history. Students can create their own courses by selecting topics, content, libraries, artifacts, challenges etc. They have to deploy a long running mission to do this and it takes time. Multi-modal artifact production and inclusion in courses is a big piece of it. We want images, videos, challenges embedded in artifacts, web artifacts, reports and generally creative content production related to education. Once the slew of features are created I want to try my hand at Virtual/Augmented reality education journeys.
>
> Users will be encouraged to take a typing test , an IQ test and some onboarding exams to know their level.
>
> Think of it like this. We want to be coursera, udemy , deeplearning.ai- like in our standard offerings but the courses are considerably more dynamic, integrated with mission control and knowledge services, portable out of the app with agent skills + cli and mcp servers , much more direct in mastery progress , tracking and assessment, full of guidance and integrations for real world projects that use cloud infrastructure and llm tools and personal learner storage so they can have their second brain. All of these capabilities are packaged into agent skills, mcp servers, api and web/mobile app. I need to bring back up the AR/VR. There is also extreme gamification. We want users to be able to game worlds to learn. That is the age we live in.
>
> The FIRST COURSE WE ARE CREATING is Agent Engineering (For ages 9-15 with starter courses in software engineering, web development, data science, distributed systems, cloud and AI)
>
> In addition to the education platform we have the Ai industry knowledge and financial/corporate knowledge feature set. At its pinnacle we are going to have agents with wallets who can trade financial instruments. We expect this to happen within 6 months maybe a year. I don't like to put timelines. Only accelerated timelines are accepted. We talk in terms of compute, tokens and architectural requirements.
>
> Biotech: This is a much more difficult service than ai engineer. I want to become the semi-analysis of biotech and also the GitHub of biotech and longevity knowledge (protocols). We want to have domain slices. I think we are going to deploy like this at first, using a slice of the graph schema for a specific use case. The first three are definitely supplement and compound intelligence and recommendations (for longevity), diagnostics intelligence and recommendations (like trudiagnostics) and multi-modal longevity machines. We will include case study information here.
>
> We are striving for a longevity management platform that can integrate with top organizations like say trudiagnostics. These features are a bit unresolved. We literally have an entity threshold we need to meet. x amount of organizations, x amount of case studies, x amount of compounds , --> recurring research on specific topics and entities .
>
> I want to give people the informational power of a doctor. I'm not saying they have the skills of a doctor but we deserve to ingest breakthrough biological and biotech science into our own minds. There should be a rundown of this at a high level in biotech-meta in the BellLabs folder in docs.
>
> A good example of the market and science reports would be tracking cancer cure breakthroughs per research lab and companies.
>
> Our biotech schema is sprawling. The point is modeling the ecosystem. We'll find ways of "navigating" the schema efficiently. Meta case study research is a good example too. Take 500 trials for some compound with some conditions and review them.
>
> We also want to codify current medical, biological and biotech sources and services into a powerhouse aggregate service and we will probably roll our own considering the immaturity of medical database tooling for the age of agents.
>
> Evidence assertions, source attribution with human and agent judgement VERY IMPORTANT
>
> 3 years out however I think I want to elevate to real experimental agentic systems that can be used in a laboratory.
>
> Same thing here mcp servers, agent skills, web and mobile app.
>
> In 3 years agent engineer is a top selling course platform and second brain provider. It helps students master subjects extremely fast. We have experiments and case studies proving students learn material very fast and with custom content.
>
> In 3 years biotech is a staple of biotech corporate and science research and people are using our agent skills daily in the web app , mobile app and in their agent tool of choice.
>
> Mission control and knowledge services are well known knowledge and coding services built on top of frontier agent frameworks and best practices with llm agents. People use it to create evidence backed reports. People buy the ability to create reports. Mission control will be loved for it's granular environment control where agent sessions can move to and fro local and cloud, transferring files, context and switching runtimes as needed. People love the granular control and intervention possibility of the mission. We are mainly known as a knowledge producer with deep research missions. We are also known as a great way to put all your coding agent services under one roof and spawn big code work with a mission control agent skill in their agent platform of choice.
>
> In addition to the services being where they are. I myself will be a master agent engineer, software engineer, data analyst and i will be extremely competent in biotech (and in finance)
>
> TO RESTATE:
>
> These are goals that inform features. The features haven't been fully developed yet for biotech and ai engineer . Mission control, knowledge services have been main focus. Schema optimizations and service-specific features come after that. (They are fed by missions)

## MC context verbatim (owner's words, 2026-11-01)

> Let me give you some very important information. I just deleted most of mission-control-general. We want to delete this folder fully in this process. We will most likely have to enhance the documentation after some fixtures so we need to start the best way we can. I think if I explain this to you you will be able to form a coherent picture and can plan out the full refactor. The deep agents current configuration is actually a high quality representation of our agent capability and workflow architecture. Each provider we have has a lifecycle and we synthesize this with a temporal workflow so that we can read and write from mission state snapshots and do things like fork, queue a message, inject context and soon enough mutate per policy (eg change a workflow mid workflow) . The mechanics of stage graph, goal directed, parallel swarm, evaluator optimizer and linked workflows at the scheduling, output contract obligation , context transfer and agent runtime and capbility configuration should be COMPLETELY KNOWN. The mission control schemas are written into the application's postgres database (aiengineer and biotech) and it relates to the knowledge schemas. Right now we have redis and web sockets for publishing and subscribing granular workflow and agent events. I actually put in a remote upstash. Nonetheless the purpose is known. The mission control will be able to search for workflows, agent providers and configuration through keyword, semantic and a workspace navigation based search process. There is the mcp server, agent skills + cli, api and later on the dashboard control plane. Remember I told you we want that local <-> cloud in one session across providers where possible. Right now we have a local and cloud split. deep agents has been refined the most. We are slated to support all those providers in adapters. *** The Provider batch prototype and proposal should be included as well. This includes making batch api requests to anthropic and openai and getting the output. In a workflow the workflow could wait on the output and then continue. Again this is a goal *** *** I don't think the special human in the loop checkpoint has been complete where some mission output gets to me and I can review and provide feedback and continue, reject with feedback and re-do or start new. We haven't yet full architected this. It should be a goal ** [...] The goal of bringing together these powerful agent platforms into a robust controllable missions and supplying this as a real service is the major goal. OH and deployment is in proposal stage. We have a vercel ingress server up.

## Assumptions (asked, not answered)

| ID | Question | Assumption taken | Risk if wrong |
| --- | --- | --- | --- |
| AS-A3 | Q1 sub-question: may a concept cite a private `.scratch/` path as proof? | Re-asked in round 2 (Q1b); until answered, concepts cite only committed receipt summaries | none until the MC truth pass writes concepts |

## Parking lot

Items raised that belong to another round or sitting, with the round that takes them.

- **Q9 revised** (first outside surface: Agent Engineering course, AIE first, skills+CLI dogfood then a
  child-safe web app) and **Q17** (financial knowledge and wallet-holding trading agents as an AIE feature
  set with stated requirements, no repository yet): asked 2026-11-01, unanswered when the owner steered to
  per-codebase passes. Taken in the AI Engineer pass and the goals charter.
- **Q1b** (private `.scratch/` paths as concept proof): taken in the Mission Control round.

- **Migration key reservation** (found by the MC repair, commit `9c0c8b7b`): unreleased candidates are
  "numbered by the integrator", so keys collide across branches (`sprint-oc-wi14`/`wi15` still carry
  `0070`/`0071`). Candidate `check` rule or protected-path rule for S1/S5. Round 5 (Q14) or S1 issue.
- **Duplicate `CURSOR_API_KEY`** in `platform/mission-control/.env` (lines 29 and 147, different values;
  DOC-10). Owner action; the Cursor adapter (S5) must define which wins. Round 4 (Q12).
- **`gh` authenticated as `jbell-rusty-vantage`** while remotes are `Overton77` (DOC-10). Matters for
  `issue`/PR automation in S5. Round 4 (Q11/Q12).
- **BKS Fly executor at v2.0.2 vs graph v2.2.0** (BKS repair `12dbe6c`; inference, not observed): the
  executor's release-marker readiness check likely fails. Deploy decision for the owner; Sprint OC W1.
- **Vacuous test** BKS `release.test.ts:97` returns early (source path no longer resolves). Fixture
  candidate for the S6 audit's "evidence discipline"; small fix in the next BKS commit.
- **KS now refuses the W0 remote with `HEAD_MISMATCH`** (KS `fa737ac` pins AIDB 0.6.0 head
  `20261031010000`; remote is at `20261025010200`). Resolved by R1(b) or by W1's remote reinstall.
- **KS test hygiene** (pre-existing, not caused by the repair): two `current-schema`/`temporal`
  integration files fail `PROMOTION_SELECTION_REQUIRED` (fixture governance selection); executor
  `pnpm test` collects 8 `node:test` files under vitest. AIDB `package-lock.json` stale at 0.3.0.
  Candidates for the next repair pass or S3 (KS vendoring), where `check` should require a green suite.
- **KS protocol package** 2.0.0 → 2.1.0 recommended (additive change; nobody pins the npm version; MC pins
  only the wire id `ks.knowledge_operation.v2`). Not done this session.

## Conversion checklist

- [ ] Decisions folded into the decision logs of the specification and supplements (links in **Folded**)
- [ ] ADR candidates written for decisions with a lasting reason
- [ ] Glossary terms added through `domain-modeling`
- [ ] Linear: a comment on each decided issue; an issue filed for each accepted piece of work, ids in **Becomes**
- [ ] Ledger: this file's row and the instruction's row updated
