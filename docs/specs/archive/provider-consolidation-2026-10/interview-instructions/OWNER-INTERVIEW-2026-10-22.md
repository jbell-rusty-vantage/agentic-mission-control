---
type: Session Instruction
title: "Owner interview: the sequence that completes Deep Agents support (obligations, subagents, capability language, transfer, linked workflows, parallelism, lifecycle, retrieval surface)"
description: "A contextualized interview for the owner and an interviewer agent, prepared at the end of tracing Stage 3 (2026-10-22): the goal statement verbatim, the owner's considerations verbatim, the cited state of the system on every topic, a strawman sequence of sprints mapped to the capability catalog C01-C16, nine interview rounds with numbered questions, options, recommendations and what each answer changes, the strawman answers to 'how do we describe this to a coordinator agent' and 'what is the Mission Control workspace', the decision log and parking lot to fill, and the interviewer's session instruction."
tags: [mission-control, providers, consolidation, deep-agents, interview, planning, obligations, subagents, capabilities, parallelism, retrieval, P1]
status: archived
archived: 2026-11-02
archived_from: OWNER-INTERVIEW-2026-10-22.md
archived_reason: "retired with the sitting I track; superseded by Sprint OC"
---

> **Archived 2026-11-02** (retired with the sitting I track; superseded by Sprint OC). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Owner interview: completing Deep Agents support

**Status.** Prepared 2026-10-22 at the end of tracing Stage 3, for an interview the owner runs
with an agent (§4). Nothing here is decided. Every recommendation is a strawman for the owner
to accept, amend or reject. The answers become the decision log (§8), the confirmed sequence
(§3) and one session instruction per sprint. The output-contracts specification
([SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md](../specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md),
decisions OC-D1..D18) and the coordinator-surface proposal
([PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md](../../../coordinator-surface-2026-10/PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md),
CS-D1..D14) are inputs, and so is the
[human review gates and steering supplement](../../../proposals-2026-10/HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md) written the same day in a parallel session
(Review Gates, Steering Resolutions, decisions HG-D1..D24, its own interviews HR0..HR9; it is meant
to move beside the output-contracts specification). This document does not replace them; it orders
them and adds the questions they do not ask.

**Revision 2026-10-23.** The owner's architecture call of 2026-10-23 added three rounds and split this
interview into three sittings so that building can start after the first. The order, the sittings,
the per-sprint cards and the first session instruction are in
[SPRINT-SEQUENCE-2026-10-23.md](../proposals/SPRINT-SEQUENCE-2026-10-23.md); the new rounds are **RA** (architecture
and state) and **RD** (domain provenance) in the
[domain-provenance supplement](../proposals/DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md) §8,
**RS** (the service map) and **RP** (proof and refinement scope) in the sequence document §2. Sitting I runs
R0, RA, R1, R1b and R3.8; sitting II runs R2, R3, RD, RS; sitting III runs R5, R6, R7 with HR0..HR9, RP,
R8, R9. The rounds below are unchanged.

Labels on facts: **[T]** tested (a named test exists), **[I]** implemented but unproven,
**[D]** documented only, **[R]** from the dated research sheet
[DEEP-AGENTS-SURFACE-2026-10-22.md](../../../provider-consolidation-2026-10/providers/deep_agents/DEEP-AGENTS-SURFACE-2026-10-22.md).
Paths are under `src/mission_control/` unless they start with `tests/`, `docs/` or `skills/`.

---

## 0. The goal (verbatim, 2026-10-22)

This is the test every decision in this interview answers to.

> *"Advanced extremely customizable workflow and agent cognition (Through multiple industry
> grade providers and direct api providers) that brings together all the cutting edge tools and
> strategies in ai agents, compute environments, sandboxes and context management so that
> systems can create, monitor and analyze long running tasks that complete real knowledge work
> and real codebase work."*

> *"We are like a specialized wrapper on top that integrates providers, innovations in context
> and ai agent workflow engineering, capability selection (mcp servers, agent skills, plugins),
> provider specific capability selection (think the todo list middleware from deep agents. This
> will be selectable), deep agent and subagent configuration. Right now we have advanced goal
> directed and stage graph (where stages can have cycles). We will be adding other workflow
> types later on."*

> *"THE GOAL IS TO BE AS COMPREHENSIBLE as possible."*

Restated as five properties the finished Deep Agents support must have (the interviewer
confirms this restatement in round R0):

1. **Customizable cognition**: every agent and subagent is configured from the manifest with
   general capabilities and the provider's native ones, each selection observed and receipted.
2. **Obligations**: every agent-bearing unit (stage, iteration role, subagent) declares what it
   must produce and communicate; Mission Control checks it mechanically and records the result.
3. **Transfer**: what one unit produced reaches the next unit precisely (the most important
   outputs) and deeply (everything else reachable), at every transfer point.
4. **Long-running control**: tracing, inspection, intervention, fork and parallel execution on
   durable Temporal workers, for knowledge work and codebase work alike.
5. **Comprehensibility**: one language across manifest, CLI, API, skill and docs, and a
   navigable, searchable surface generated from the code so it never goes stale.

## 1. The owner's considerations (verbatim, 2026-10-22)

> *"Tracing, observability and lifecycle inspection and controls. I suspect there is still some
> more work to be done here in order for us to have the fully capable workflows + cognition that
> we have set out to create. I tried to split forking, intervention, tracing + observability and
> lifecycle domain modeling and writing and reading from the output contracts and context
> transfer rules but I think we might have to create our next plan in light of output contracts
> and context transfer functionality."*

> *"I need to interview about obligation contracts, obligation verification and context
> transfer where context transfers should happen. [...] This is an extremely critical part of
> our service. How should we model output / obligation contracts? How flexible and customizable
> should they be? Should they be from a pre-defined catalog? Should number of distinct outputs be
> limited? Let's think about codebases from the start so we don't overlook that even though deep
> agents isn't our preferred codebase tool (it is more for knowledge work)."*

> *"This brings up subagent context transfer / inheritance / viewing behavior. We haven't
> created our own custom subagent tool. We use deepagents async subagent and sync subagent
> interfaces. Deep agents also has dynamic subagents with the quickjs middleware. We are going to
> support that as well. You see if agents have subagents and we create these upon mission
> contract compilation then shouldn't we have output obligations or communication obligations
> for the subagent. I think the async subagent from deep agents is quite advanced in that it
> supports two-way communication and a tool to check in on a task. The ability to check in on a
> task is not a callback or a hook though."*

> *"We need to resolve the language we use as well as the code structure we choose for the
> general + provider specific agent capabilities and configurations. How should we make this
> navigable in an agent skill? How would you describe this to a mission control coordinator agent
> who is reading through mission control and surveying how to put together an advanced StageGraph
> workflow and I the owner told the agent I want to use Deep Agents."*

> *"We are not using the input or output graph schemas or the context schema. I'm wondering if
> this would be useful. One of langgraphs (which backs deep agents) major features is maintaining
> that graph state and reducers of the typed dicts fields throughout the graph lifecycle. Deep
> Agents already comes with the most important fields and reducers like for messages and tool
> calls. You know that we can retrieve the schema inside of middleware. This is something I Need
> to talk about."*

> *"We need to do our research on the latest deep agents version and features, decide on the
> native capabilities only deep agents has that we want, what category it is part of (context
> management, tooling, etc) and include it in our configuration possibilities and use it in our
> deep agents. BUT HOLD ON. There is also Deep Agents OpenAI specific things. They give access to
> the openai web search tool. We want to be able to choose these things!"*

> *"With coding agent frameworks (like cursor) we have the ability to supply hook scripts. You
> write some script usually .sh and upon some lifecycle event the script runs. Now in Deep Agents
> we have middlewares. We could think of an infinite number of missions. Should we allow
> activating or affixing middleware hooks that do something for the mission?"*

> *"I need to interview how linked Workflows are going to work and transfer context and fulfill
> obligations."*

> *"We need to start architecting the best parallelism / concurrency we can. If stages are not
> dependents then they can run in parallel right? All I'm saying is it is time to spin up a
> worker and take advantage of temporal."*

> *"Then we are going to have to circle back on mission control and agent capability and agent
> provider specific retrieval search and usage. [...] Once everything I have stated is architected
> and achieved then we finally have the necessary pieces to build out the mission control agent
> skill and finalize the retrieval surface. You can take inspiration from the schema workspaces we
> created. You see how those become a navigable filesystem with searchable files. We should create
> something similar for mission control. I can imagine a list of cli commands. Workflow documents.
> Agent provider specifics. General capabilities. How to search agent skills and mcp servers? How
> do hooks work?"*

> *"It is very easy to deviate from the goal."*

## 2. Where the system stands (end of tracing Stage 3)

### 2.1 What the tracing sprint delivered (Stages 1-3)

The Mission Transcript v2 and its persisted projection, cognition points written in the
settlement transaction, the precise fork (closure, start position, seed head, Goal Directed
reuse by iteration), the remote saver with typed outcomes, the two in-turn stops (budget, fence),
typed Goal outcomes for unparseable answers, all proven live on GPT-6 Sol and Luna for 0.80 USD
(Stage 2), then reviewed adversarially and fixed (Stage 3). The ledger is
[providers/deep_agents/CHANGES.md](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md); the Stage 3 entry lists
every review finding and its disposition.

### 2.2 The facts the interview turns on

| Topic | State today | Label |
| --- | --- | --- |
| Stage outputs | Presence of refs per required slot; bytes and schema only when a schema is bound. A stage with no declared outputs accepts an empty result. Outputs stay `workspace-candidate://` and never become `artifact` rows (AUDIT-OUTPUT-TRANSFER §A1-A4, §D1-D6) | [T] |
| The model's `output_refs` | Replaces the registered refs on the Stage Graph: live in Stage 2, `"output_refs": []` erased S1's outputs; on the Goal Loop the verifier received only a path in the executor's workspace and rejected every iteration (SESSION-STAGE-2 §4b items 2, 4) | [T] live |
| Cycle and iteration transfer | A re-run cycling stage receives only its new objective; iteration N+1 receives only what the handoff lists; verifier findings are never delivered (§4b items 6, 7) | [T] live |
| Subagent outputs | No output declaration anywhere: `mc.subagent_profile.v1` has no result schema (`domain/capabilities/subagents.py:159-203`); a sync child answers in free text (`application/authoring/lanes/deep_agents.py:102-106`); the async child's `result_schema_ref` is stored, never validated (SUBAGENTS.md:98) | [T] |
| Subagent context | Sync children get the parent's tools (narrowed) plus seeded MCP and Skills (`adapters/deep_agents/materializer.py:367-378`); a state slice (`artifact_index`, `child_result_index`, `context_manifest`) is sealed into the binding but nothing reads it; async children receive only the objective string | [T] / [I] |
| What Deep Agents gives subagents natively | Per-child `response_format` (ToolStrategy, ProviderStrategy, schema); state merge-back (children write `files` and custom keys back through reducers); runtime context propagates to sync children; in 0.7.30 fork-mode children and async children that notify the parent, queue follow-ups, report `waiting` | [R] §3 |
| Dynamic subagents | `langchain-quickjs==0.3.5` pinned, never imported. The model writes JavaScript calling `task({description, subagentType, responseSchema})`, fanned out with `Promise.all`; these calls **bypass the parent's HITL** per dispatch | [R] §3.3 |
| Provider options | Only `mc.provider_options.deep_agents.v1`: `sandbox_backend`, `summarization`, `interrupt_on` (degraded) (`domain/authoring/provider_options.py:59-91`) | [T] |
| Middleware selection | Not selectable from a manifest: the stack is fixed (fence stop, hook scripts, observed summarization, the operator scaffold's catalog middleware) (`materializer.py:340-366`) | [I] |
| The todo list | Not in the default Deep Agents stack in 0.7.5 or 0.7.30 (only the Codex harness profile adds it); must be an explicit selection | [R] §2.4 |
| OpenAI built-in tools | Not bindable: the model factory allows eight settings, no tools (`materializer.py:223-236`). In LangChain they are dict tools routed to the Responses API that **never enter the ToolNode**: no `wrap_tool_call`, no hook, no HITL, no tool-call limit sees them | [I] / [R] §6.1 |
| State and context schemas | Both are passed to `create_deep_agent` (`adapters/deep_agents/adapter.py::_compile`), built from the operator scaffold's channels (`materializer.py:939-1015`); a manifest cannot declare them; **no middleware reads `runtime.context`** | [I] |
| Hooks | ADR 0026: one event vocabulary projected per lane; on Deep Agents `HookScriptMiddleware` runs scripts at middleware seams (`adapters/deep_agents/hooks.py`), but a manifest launch with hook scripts is refused `409 start_unavailable` on this lane (`application/authoring/manifest_launch_inputs.py:795-802`); the manifest vocabulary lacks `before_mcp` that the code has | [T] / [I] |
| Linked workflows | Chains (ADR 0029): a released link seeds the downstream's first packet with supplied outputs at `/inputs/<from>.<output>/`, the upstream disposition, a final checkpoint reference and transcript retrieval instructions (`application/chains/packet.py`); undercut by outputs never becoming artifacts | [T] |
| Stage parallelism | The Stage Graph workflow already runs independent stages concurrently (`adapters/temporal/workflows/stagegraph.py:561-730`, `domain/programs/interpreter.py:251,307`; `tests/integration/temporal/test_wp_bp_010_temporal.py`), bounded by `max_concurrency`, but a manifest's `concurrency` **defaults to 1** and is undocumented (`domain/authoring/manifest_lowering.py:388-396`). Goal Directed is serial; `governors.fan_out` is parsed and ignored; `parallel_swarm` compiles and runs as one operation | [T] / [I] |
| Workers | One base worker process hosts the coordinators, the cognitive worker (`operation.execute`) and the maintenance, watchers and linked-runs workers; the `lane` role serves only `lane.*` activities; activity concurrency is left at SDK defaults; there is **no role for extra Deep Agents cognitive capacity** (SPEC-11 allows one base worker per namespace and application) | [I] |
| Temporal and Deep Agents | `temporalio.contrib.deepagents` ships in the installed temporalio 1.34.0 and is unused: it runs the agent loop inside the Workflow with an Activity per model and tool call and advises against durable checkpointers, which conflicts with the Postgres-checkpointed, Activity-wrapped design | [R] §9 |
| Version | deepagents 0.7.5 installed, **0.7.30** latest (langchain 1.4.7, langgraph 1.2.16, langchain-openai 1.7.2); 0.7.25 carries a permission/symlink security fix; LangGraph 1.2.13-1.2.16 fix DeltaChannel forks and resume, which the fork work depends on | [R] §1 |
| Retrieval surface | `missionctl` has `token`, `run`, `command`, `mission`, `chain`, `catalog`, `lane` nouns; no `node`, `outputs`, `inputs`; skills under `skills/` (router plus five bundles plus cognition bundles) lag the system; the coordinator-surface proposal is unbuilt; no generated navigable tree exists for Mission Control | [I] / [D] |
| The model for a navigable surface | Biotech's schema workspace (`biotech/biotech-knowledge-services/workspace/`, generator `packages/schema-workspace`, ADR 0002 there): `START_HERE.md` -> `INDEX.md` -> `domains/`, `modules/` -> typed cards with generated front matter -> source; `search/index.jsonl`, `adjacency.json`, a `bks-schema` CLI (`search`, `get`, `neighbors`, `path`, `slice --max-tokens`), typed id prefixes, byte-identical regeneration, an agent skill. AI Engineer's db-contract `workspace/` is a second variant | [I] |

## 3. The strawman sequence

### 3.1 The order and why

The owner's instinct is right: the next plans must be made in light of output contracts and
context transfer, because obligations attach to **agent configurations** (stage agents,
iteration roles, subagents) and transfer reads **fulfillment facts**. Lifecycle inspection,
linked workflows and the retrieval surface all read those facts. So the order is: the
foundation, then the configuration language obligations attach to, then obligations and
transfer, then everything that reads them.

```text
A  Deep Agents upgrade (0.7.30 stack)                 foundation; DeltaChannel fork fixes; security fix
   │
B  Agent Configuration language and lane features      the nouns obligations attach to; Deep Agents and
   │  (incl. hooks on Deep Agents, state/context policy) OpenAI-native selections; receipts
   │
C  OC-1 Obligations and submission                    stage + iteration + sync-subagent obligations
D  OC-2 Transfer policy, materialization, dependencies  every transfer point incl. subagent views
E  OC-3 Cycles and Goal Loop                          K04/K05/K02
   │
R  Review Gates and steering (the supplement)          T10; HG-1..HG-5 and the revision service RV;
   │                                                    its interviews HR0..HR9 run with R7
F  Lifecycle and observability on obligations         run outputs/inputs, obligation events,
   │  (async-subagent admission and communication)      interventions on obligations, WP-S4
G  Linked workflows on obligations                    C15: GD->GD, SG->GD, release by obligation
H  Parallelism and workers                            concurrency defaults, a cognitive worker role,
   │  (independent of C-G; can start after A)           activity slots, parallel workspaces, live proof
I  Retrieval surface and the Mission Control skill    the generated workspace, the CLI grammar, the
                                                        skill bundles; last, as the owner said
T2 The vision mission, live                           one mission exercising everything, under 15 USD
```

| Sprint | Builds | Closes (C01-C16 of the [program README](../../../provider-consolidation-2026-10/README.md) §3) | Rough size |
| --- | --- | --- | --- |
| A | dependency bump, the 0.7.30 behaviour deltas guarded (stock async middleware never attached, `notify_parent=False`), recovery and fork suites green, describe pins | prerequisite | 1 session |
| B | `mc.agent_configuration.v1`, the lane-feature registry and the first features (todo list, context editing, call limits, summarization knobs, OpenAI built-in tools), hooks on Deep Agents, the state/context schema policy, describe and receipts | C01, C10, C13 | 2 sessions |
| C | OC-1 plus subagent obligations for sync children | C04 (part), C10, C11 | 2 sessions |
| D | OC-2 plus subagent context views and async child inputs | C04, C11 | 2 sessions |
| E | OC-3 | C02, C03, C05 | 1-2 sessions |
| R | the supplement's HG-1..HG-5 and RV: Review Gates that approve, revise, reject or select with riders; context added versus configuration replaced | C08, C09, C16 | per the supplement |
| F | inspection and events on obligations, interventions that target an obligation, async admission and communication obligations (WP-S4) | C07, C11, C14 | 1-2 sessions |
| G | chains on obligations, GD->GD and SG->GD on Deep Agents | C15 | 1 session |
| H | concurrency, worker roles, slots, workspace isolation, a live parallel proof | C12 (part), long-running | 1-2 sessions |
| I | the generated Mission Control workspace, the CLI grammar (CS-D1), the skill bundles (CS-D2..D10) | C14, comprehensibility | 2 sessions |

The interview's last round (R9) confirms or reorders this. Two alternatives worth weighing:
H before C (parallelism is mostly independent and makes every later live proof faster), and B
folded into C (smaller, but the obligation tools then land before the language that names them).

### 3.2 What "complete Deep Agents support" means at the end

A coordinator agent, told "use Deep Agents", reads the generated workspace, writes a Stage Graph
manifest whose stages and subagents declare obligations and native features, launches it, and
watches stages run in parallel on a worker pool; every unit's deliverables are checked,
promoted to artifacts and transferred at the planned tier; cycles and iterations carry their
findings; a fork from any point continues exactly there; the owner reads the transcript and the
fulfillment rows and understands what happened. Then the next provider's sprint starts from the
same language.

## 4. The interview process

### 4.1 Participants and roles

- **The owner** decides. Answers can be an option, an amendment, "defer with this assumption",
  or "park".
- **The interviewer agent** (Opus 5.5 now, Fable 5.1 when the budget resets) prepares, asks,
  restates and records. It does not build during the interview. It runs under
  [PROCESS.md](../../../provider-consolidation-2026-10/PROCESS.md) step 4 ("Confirm with the owner") applied to a whole sequence.

### 4.2 Before the first round (the agent)

1. Read this document whole, then §0 and §8 of the output-contracts specification, the
   coordinator-surface proposal §3-§4 and §7, the research sheet's "Implications" section, the
   ledger's Stage 3 entry, and the human review gates supplement (its interviews join R7).
2. Re-verify the §2.2 rows the first rounds rest on against live code (`file:line`), and mark any
   drift in the table before asking anything.
3. Prepare each round's questions as choices with a recommendation first and "what this changes
   later" for each option (PROCESS §1.2).

### 4.3 How a round runs

1. **Context, two minutes of reading**: the round's section of §5, in the owner's terms.
2. **Questions in batches of at most four** (the question tool), recommendation first. A question
   whose answer the code already gives is not asked; it is cited.
3. **Restate the mental model** after the answers, as a manifest fragment, a command, or "what you
   will see", and ask the owner to confirm or correct it. This is the step that catches
   misunderstanding; it is not optional.
4. **Record** every answer in §8 with the date, the question id and the consequence ("C builds
   X; D drops Y"). An unanswered question becomes a stated assumption, never a silent default.
5. **Drift check**: the agent names which of the five goal properties (§0) the round's decisions
   serve. A decision that serves none is parked (§9), not adopted.

### 4.4 Rules that keep the interview on the goal

- One topic per round; tangents go to the parking lot with the owner's words.
- No new scope without naming what it displaces in the sequence.
- Provider-neutral first: each decision states its general form and then the Deep Agents
  materialization (PROCESS §2, discriminators and routers). A Deep-Agents-only decision says why
  it cannot be general.
- Codebase work is considered in every round, not only R1 (the owner's instruction).
- Evidence over memory: a claim about Deep Agents cites the research sheet or the installed
  source; a claim about Mission Control cites `file:line`.

### 4.5 Exit criteria and outputs

The interview ends when every "must decide" question in §5 is answered or deferred with an
assumption, and R9 has confirmed the sequence. Outputs, committed as docs:

- §8 filled; the answers folded into the output-contracts specification (OC-D*) and the
  coordinator-surface proposal (CS-D*) where they overlap;
- the confirmed sequence in §3 rewritten as decided;
- one `SESSION-<SPRINT>.md` per sprint in its folder, the first one ready to run (goal in the
  owner's words, inputs, decisions it rests on, proofs, non-goals);
- the knowledge concepts and GLOSSARY terms the language round (R0, R3) settled.

Expected length: three to four sittings of about an hour; rounds R1-R3 are the heavy ones.

## 5. The rounds

Question ids are per round (`R1.3`). "Must decide" questions block a sprint; "can defer" ones
have a stated default.

### R0. Alignment and language (15 minutes)

Context: §0 and the vocabulary of the specification §2 (Obligation, Output kind, Deliverable,
Submission, Fulfillment, Mission State Transfer, Depth layer, Transfer tier, Release kind).

- **R0.1 (must)** Is the §0 restatement (five properties) the goal? Amend it.
- **R0.2 (must)** Do we adopt "obligation" for what a unit must produce **and** communicate, with
  "output obligation" and "communication obligation" as its two families? (Recommendation: yes;
  "output contract" stays as the informal name of a node's set of output obligations.)
- **R0.3 (must)** Adopt the two-axis vocabulary of R3 now (lane and model provider) so every later
  round speaks it? (Recommendation: yes, provisionally, confirmed in R3.)

### R1. Output obligations and verification (heavy)

Context: the specification §3 (obligation model, seven kinds, two submission channels, the
fulfillment check, promotion to artifacts) and OC-D1..D7, D14. Stage 2 evidence §2.2 rows 1-3.

The owner's four questions, with strawman answers:

| Question | Strawman |
| --- | --- |
| How should we model obligations? | A named obligation per node: `{name, kind, level, cardinality, accumulation, collect, validators, derives_from, transfer}` (spec §3.1). Kinds are a **closed kernel set**; everything else is open per obligation. |
| How flexible and customizable? | Customization lives in **instances, validators and templates**, not in new kinds: any number of named obligations per node; validators parameterized (`sections`, `min_words`, `json_schema`, `evidence_backed`, `checks_receipt`, `derived_from`); `structured_record` takes any JSON schema in the supported subset. |
| A pre-defined catalog? | Two layers. **Kinds**: fixed in the kernel (adding one is a kernel change with a checker). **Obligation templates**: published to the capability catalog like skills (`obligation_template` kind, digest-pinned): "evidence-backed report", "PR-ready change", "test report", "brief with figures". A manifest uses a template by pin or search, or writes the obligation inline. |
| Limit the number of distinct outputs? | A **soft limit per node** (default 8 obligations, `cardinality.max` ceiling 64 items, both installation settings) with a compile warning above it, and a hard refusal only on the ceiling. The reason is verification and transfer cost, not storage. |

Codebase work from the start (the owner's instruction): `code_change` with `form: branch_head`
(the harness observes base and head SHA, never the model) or `form: patch` (a unified diff, for
lanes without git such as the Deep Agents state backend); validators `paths_within`,
`checks_receipt` (a named check ran and passed, receipted by the harness), `non_empty_diff`; a
code consumer receives a `workspace` transfer (snapshot or branch), a knowledge consumer a
reference with the head. A `test_report` template (a `structured_record` with a fixed schema)
pairs with it.

Questions:

- **R1.1 (must)** Adopt OC-D1..D7 and D14 as recommended in the specification §8? (One answer
  per decision; the agent reads the table aloud.)
- **R1.2 (must)** Closed kinds plus catalog templates, as above? Or (b) open kinds registered in
  the catalog with a checker plugin, or (c) a closed set with no templates.
- **R1.3 (must)** The soft limit and ceiling? Or (b) no limit, or (c) a hard limit.
- **R1.4 (must)** Verification layers: mechanical fulfillment at the reducer (always), plus an
  optional `verify:` on an obligation naming a verifier node, a human review or nothing. Does a
  verifier's verdict about an obligation block acceptance (gate), or annotate it (finding)?
  (Recommendation: the node's author chooses per obligation, default annotate.)
- **R1.5 (can defer)** Partial credit: may a unit be `accepted_with_findings` when an `expected`
  obligation is short? (Spec says yes; confirm.)
- **R1.6 (must)** Enforcement **during** the turn: when the model tries to finish with a `required`
  obligation unsubmitted, does Mission Control push back inside the turn (a stop-condition
  middleware that answers "you have not submitted X" once, like the budget stop's mechanism) or
  only judge at settlement? (Recommendation: one in-turn reminder, then judge at settlement.)
- **R1.7 (can defer)** Codebase: is `code_change` on Deep Agents in v1 (patch form only), or
  deferred to the Cursor/Claude/Codex sprints? (Recommendation: in v1, patch form, so the kernel
  is codebase-ready before those sprints.)

What the answers change: C's scope, the 1.4.5 release (obligation_fulfillment table, artifact
promotion), and the catalog kind list.

### R1b. Where context transfers happen

Context: the specification §4 (three depth layers, the transfer policy with heuristics H1-H9 as
data, dependency kinds, cycles, Goal Loop, the materialization module) and OC-D8..D13, D15, D16.

The transfer points, as a closed list for the owner to confirm or extend:

| Point | From | To | Today | Strawman |
| --- | --- | --- | --- | --- |
| T1 stage start | producer stages' deliverables and state | dependent stage | whole brief inline, live | the policy (spec §4.2) |
| T2 cycle re-run | the stage's own prior cycle | the same stage, next cycle | only the objective string | prior fulfillment, unmet obligations, decision record, findings inline; deliverables by reference (K05) |
| T3 iteration start | executor N and verifier N | executor N+1 | only the handoff's list | handoff, verdict and findings inline, iteration deliverables materialized (K04) |
| T4 executor to verifier | executor N | verifier N | a path the verifier cannot read | the executor's deliverables provisional, plus its fulfillment report |
| T5 session rollover | session g | session g+1 | `pack_for_iteration` reused | seed from the result point plus the handoff (K02) |
| T6 parent to subagent | parent | child at spawn | tools, seeded MCP/Skills; slices unenforced; async: objective only | R2 |
| T7 subagent to parent | child | parent | free-text final message | R2 |
| T8 fork | source point | derived run | the seed head with the message (fixed in Stage 3) | unchanged, plus `transfer.history` at fork time |
| T9 linked run | upstream mission | downstream mission | chain packet | R5 |
| T10 human review | reviewer | consumer | the disposition; `request_changes` replaces the re-run stage's objective | the supplement's Steering Resolution: one verdict plus riders, delivered inline and mandatory ([supplement](../../../proposals-2026-10/HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md)) |

- **R1b.1 (must)** Confirm the list; add or drop points.
- **R1b.2 (must)** Adopt OC-D8 (three layers; history referenced, never materialized unless asked)
  and OC-D15 (heuristics as data)?
- **R1b.3 (must)** OC-D9: the dependency kinds in v1 (`any`, quorum, classes, named outputs,
  Provisional Binding, `conditional`); if one slips, which?
- **R1b.4 (can defer)** Should an author be able to write a transfer override per input
  (`expand: inline | materialize | reference | workspace`) and per node (`transfer: {history:
  materialize}`)? (Spec: yes.)

### R2. Subagents: obligations, communication, inheritance and viewing (heavy)

Context: §2.2 subagent rows; the research sheet §3. The owner's point: subagents are created at
mission compilation, so they are agent-bearing units and owe obligations like stages do.

Three shapes, one model:

| Shape | Native mechanism | Output channel today | Strawman obligation carrier |
| --- | --- | --- | --- |
| Sync (`task`) | in-process child graph, parallel per tool call | free-text final message | per-child `response_format` (`structured_record`) and/or files under `/subagents/<name>/outputs/` registered as candidates of the parent's unit, attributed to the child |
| Async (Agent Server) | `start/check/update/cancel/list_async_task`; 0.7.30 adds notifications, `waiting`, queued follow-ups | the child thread's last message at check | the same obligations, checked at admission (WP-S4: Mission Control admits the result when the parent checks it) |
| Dynamic (QuickJS `task()`) | the model's JavaScript dispatches children with a `responseSchema` | the resolved Promise value | a **profile-level ceiling**: the author lists which subagent types a script may dispatch and their obligations; the script's own `responseSchema` may narrow, never widen |

**Communication obligations** (the owner's new term). Check-in is a pull tool, not a callback;
Mission Control can still make communication an obligation:

- **Child to parent**: `report: on_return | progress(every: N model calls) | on_request`; a
  progress report is a `submit_output(progress)` or a `progress_note` frame (TRACING-PROPOSAL P7),
  so it is durable and visible to the coordinator, not only to the parent model.
- **Parent duties**: `join: all | any | none` before the parent unit may settle (an async child
  still running when the parent finishes is a typed outcome: wait, cancel or detach as
  authored); `must_review: true` makes the parent's own obligation `derives_from` the child's
  deliverable.
- **Coordinator view**: every child's obligations and fulfillment appear in `run outputs` under the
  parent unit, and child points stay nested under the parent's points (exists since WP-TR-2).

**Inheritance and viewing** (T6/T7):

| Axis | Options | Strawman default |
| --- | --- | --- |
| What the child sees at spawn | `isolated` (only the task description) / `fork` (the parent's conversation; 0.7.30, experimental, no nested `task`) / `slice` (named state keys and the parent's input deliverables) | `isolated` plus the parent's `/.mission/state.json` and the inputs the author lists |
| What flows back | the result message / its `response_format` JSON / state merge-back of `files` and custom keys | the typed result plus registered output files; state merge-back only for keys the profile names (0.7.5 merges every key: decide per key) |
| Who can read the child | the parent model (result), the coordinator (transcript, points, outputs), the owner (transcript `--by step` nests children) | all three; the child's full transcript is History layer |

Questions:

- **R2.1 (must)** Subagents declare output obligations on the profile (`outputs:` in the same
  schema as nodes, kinds limited to `structured_record`, `document`, `file_artifact`, `verdict`)?
- **R2.2 (must)** Adopt communication obligations (child `report`, parent `join` and
  `must_review`) as v1? Or only `join` in v1.
- **R2.3 (must)** Dynamic subagents: support in v1 behind an explicit lane feature
  (`deep_agents.code_interpreter`) with an `eval` approval policy (the dispatches bypass HITL),
  or defer to after D? (Recommendation: after D; the obligation model must exist first.)
- **R2.4 (must)** Default inheritance (`isolated` plus state and listed inputs) and per-key state
  merge-back?
- **R2.5 (can defer)** Async: adopt 0.7.30's `update_strategy: enqueue` and `waiting` through the
  governed wrapper; never attach the stock async middleware (its hooks inject child results before
  admission). Confirm.
- **R2.6 (can defer)** Should a child's obligation failure fail the parent unit, or be a finding the
  parent's verifier sees? (Recommendation: a finding unless the parent declared
  `must_review`/`derives_from`.)

### R3. The capability language and code structure (heavy)

Context: PROCESS §2 (discriminators and routers), §2.2 provider-options rows, the research
sheet's catalog and "Implications". The owner's questions: the language, the code structure,
navigability, and how a coordinator agent would read it.

**Strawman language: two axes, three layers.**

- **Axis 1, the lane** (the harness: `deep_agents`, `cursor_local`, `claude_agent_sdk`, ...).
- **Axis 2, the model provider** (the API behind the model: `openai`, `anthropic`, ...). The
  owner's OpenAI web search example lives here: it is a Responses API tool, available on any lane
  that drives an OpenAI model through LangChain, not a Deep Agents feature.
- **Layer 1, Capabilities** (neutral, in the catalog): skills, MCP servers and tools, hook scripts,
  plugins, subagent profiles, environment kits, obligation templates. Every lane materializes,
  emulates, degrades or refuses each, with a receipt.
- **Layer 2, Lane features** (provider-native, by lane): `deep_agents.todo_list`,
  `deep_agents.context_editing`, `deep_agents.summarization`, `deep_agents.call_limits`,
  `deep_agents.filesystem_permissions`, `deep_agents.code_interpreter`,
  `deep_agents.memory`, `deep_agents.rubric`, ... each with a **category** (context management,
  tooling, delegation, control and safety, state, persistence).
- **Layer 3, Model tools** (provider-native, by model provider): `openai.web_search`,
  `openai.file_search`, `openai.code_interpreter`, `openai.image_generation`, `openai.mcp`,
  `openai.compaction`, `anthropic.web_search`, `anthropic.web_fetch`, `anthropic.code_execution`,
  `anthropic.clear_tool_uses`.

Manifest strawman:

```yaml
agents:
  analyst:
    lane: deep_agents
    model: { provider: openai, name: gpt-6-sol }
    capabilities:                      # layer 1, neutral
      skills: [{ search: "evidence-backed report" }]
      mcp_servers: [{ pin: catalog://mcp/pubmed@3 }]
    lane_features:                     # layer 2, keyed by lane
      deep_agents:
        todo_list: {}
        context_editing: { clear_tool_uses: { trigger_tokens: 60000, keep: 4 } }
        call_limits: { model_calls: 40, tool_calls: 120 }
    model_tools:                       # layer 3, keyed by model provider
      openai:
        web_search: { search_context_size: medium }
    subagents:
      - name: fact_checker
        kind: sync
        outputs: [{ name: verdicts, kind: structured_record, schema: catalog://schemas/fact-verdicts@1 }]
    outputs:
      - { name: report, kind: document, template: catalog://obligations/evidence-report@2 }
```

**Strawman code structure** (PROCESS §2.2 made concrete):

```text
domain/capabilities/features/
  registry.py            LaneFeature{id, lane, category, config_model, requires, observes, receipt_fields}
  deep_agents.py         the Deep Agents feature definitions (pure: config models, compile checks)
domain/capabilities/model_tools/
  registry.py            ModelTool{id, model_provider, config_model, observability: tool_node | server_side}
  openai.py, anthropic.py
application/authoring/lanes/deep_agents.py   the lane adapter: reads layer 1 + its own layer-2/3 containers
adapters/deep_agents/features/<feature>.py   one deep module per feature: middleware, receipt, frames
adapters/deep_agents/model_tools.py          binds layer-3 dict tools; records server_tool_call blocks as frames
```

Every registry entry generates its own describe row (`missionctl lane features deep_agents`), its
workspace card (R8) and its skill reference, so the language is defined once in code.

**Hooks and middleware** (the owner's question: should a mission affix middleware?):

| Option | What it is | Cost |
| --- | --- | --- |
| (a) Hook scripts only | ADR 0026's neutral events; scripts run at middleware seams on Deep Agents | already designed; Deep Agents must stop refusing them (`409`) |
| (b) Curated middleware features | Mission Control-authored middleware selected by id with typed config (layer 2) | each is a reviewed deep module with a receipt |
| (c) Arbitrary middleware code | a Python import path in the manifest | unbounded: breaks sealing, digests, step numbering (a `before_model` node shifts positions), security |

Strawman: (a) plus (b), never (c). "An infinite number of missions" is served by scripts on the
neutral vocabulary (portable to every lane) and by a growing curated catalog; anything that must
be middleware becomes a curated feature.

**State and context schemas** (the owner's question):

- **Context schema**: already passed; make it the **only** source of run identity for Mission
  Control middleware (today hooks carry their own `HookContext`), typed and immutable. Strawman:
  adopt; it also reaches sync children.
- **State schema**: a small Mission Control-owned channel set with reducers, private to child I/O
  unless declared: `mc_obligations` (status per obligation, updated by `submit_output`),
  `mc_children` (child results and their fulfillment), `mc_transfer` (the plan digest and the
  materialized inputs). Middleware reads them to enforce R1.6 and R2.2 without a database
  round trip; settlement still reads the durable ledger (the graph state is evidence, never
  authority, ADR 0007). Strawman: adopt the three channels in B or C.
- **Input/output graph schemas**: not author-facing in v1; reconsider when another lane needs them.
- **Author-declared custom state keys**: defer; obligations and transfer cover the cases seen so
  far.

**Durability architecture** (one question, not a build): keep the Activity-wrapped, Postgres-
checkpointed Deep Agents turn (cognition points and the precise fork depend on it) and record
`temporalio.contrib.deepagents` as a watched alternative.

Questions:

- **R3.1 (must)** The two axes and three layers, and the names `capabilities`, `lane_features`,
  `model_tools`? (Alternatives: one `provider_options` container for both axes; or features nested
  under the model.)
- **R3.2 (must)** The code structure above (registries in `domain`, one deep module per feature in
  the adapter, everything generated from the registries)?
- **R3.3 (must)** Hooks: (a)+(b), never (c)? And lift the Deep Agents `409` for hook scripts in B?
- **R3.4 (must)** The first Deep Agents features for B, by category. Strawman: todo list (tooling),
  context editing and summarization knobs (context management), call limits (control),
  filesystem permissions (control), OpenAI `web_search` and `file_search` (model tools). Then in
  OC-4: eviction limits, compact tool, memory, rubric, code interpreter.
- **R3.5 (must)** Model tools bypass the ToolNode: no hook, HITL or call limit sees them. Accept
  them as `observability: server_side` (recorded from the model's content blocks as frames,
  budgeted per call, never approval-gated), or refuse model tools on missions that require
  approvals?
- **R3.6 (must)** State and context: the context schema as the identity source, and the three
  `mc_*` channels?
- **R3.7 (can defer)** Durability: confirm the current architecture and the watch on
  `temporalio.contrib.deepagents`.
- **R3.8 (must)** Sprint A (the 0.7.30 upgrade) first?

(There is no R4: the owner's "where should context transfers happen" is R1b, and subagent
transfer is R2.)

### R5. Linked workflows

Context: §2.2 linked-workflow row; ADR 0029; `docs/knowledge/mission-chains.md`; C15.

Strawman: a chain link is a transfer point (T9) handled by the same transfer policy with
`purpose: chain_link`; the downstream mission declares `requires: <upstream>.<obligation>`
(release on that obligation's fulfillment, not only on run acceptance); supplied deliverables are
the promoted `artifact` rows of OC-1; the upstream's history is referenced; the downstream's
obligations may `derives_from` upstream deliverables, so lineage crosses missions.

- **R5.1 (must)** Release by obligation fulfillment (in addition to `goal_accepted`,
  `mission_accepted`, `execution_complete`)?
- **R5.2 (must)** Same transfer policy and depth layers as within a mission?
- **R5.3 (can defer)** Cross-provider links (`claude_managed` -> `codex_agents`) stay in their
  providers' sprints; G proves GD->GD and SG->GD on Deep Agents only. Confirm.
- **R5.4 (can defer)** The subagent kind `linked_run` (a child that is a whole mission): keep it
  refused on Deep Agents, or make it the way a Deep Agents parent delegates to a codebase lane?

### R6. Parallelism and workers

Context: §2.2 parallelism and worker rows. Stage Graph parallelism exists; what is missing is the
default, the worker capacity and the proof.

Strawman:

- **Concurrency default**: a manifest Stage Graph without `concurrency` runs independent stages in
  parallel up to an installation default (strawman 4), bounded by the authority ceiling; the field
  is documented and receipted.
- **A cognitive worker role**: `MISSION_CONTROL_WORKER_ROLE=cognitive` serves `operation.execute`
  and `operation.cancel` on `<base>-agent-cognitive` only, so Deep Agents capacity scales by
  starting more processes (on this host, WSL2 or a remote machine) without a second base worker.
- **Activity slots**: `max_concurrent_activities` per worker as a setting, sized by host memory
  (a Deep Agents turn holds a model client, a checkpointer pool and a sandbox).
- **Isolation**: parallel stages that write get separate workspaces (exists for worktrees on the
  code lanes; check the Deep Agents state and docker backends); budget reservations are per unit
  already.
- **Goal Directed fan-out**: `governors.fan_out` is parsed and ignored; either implement parallel
  executors per iteration or reject the key. Parallel Swarm stays specified-only.
- **Proof**: a live Stage Graph with two independent stages running at once on two cognitive
  workers, under the Stage 2 budget style.

- **R6.1 (must)** The concurrency default and its value.
- **R6.2 (must)** The `cognitive` worker role.
- **R6.3 (can defer)** `fan_out`: implement, or reject at compile?
- **R6.4 (must)** H's place in the sequence: after A (early, makes live proofs faster) or after G.

### R7. Lifecycle, tracing and controls in light of obligations

Context: the tracing sprint's honest lists (Stage 1-3 in the ledger), the coordinator-surface
proposal §5 (events a dashboard lacks), CS-D10.

Strawman for sprint F: `run outputs --at`, `run inputs --at` (CS-D10); `obligation_fulfilled`,
`output_submitted`, `transfer_planned` as public events with `unit_key`, `point_ref` and location;
`run inspect` shows per unit "2 of 3 obligations fulfilled"; interventions that target an
obligation (`command inject --obligation report "revise section 3"`, a revision request that
re-opens one obligation instead of re-running the stage); fork from a fulfillment row; the async
admission (WP-S4) and child communication obligations; the transcript's stage group shows
released-by, transferred items and fulfillment together.

- **R7.1 (must)** Is that F's scope? What else from "lifecycle domain modeling" belongs here?
- **R7.3 (must)** Review Gates: run the supplement's interviews HR0..HR9 here (or as their own
  sitting), and place its sprints (R in §3.1) before or after F.
- **R7.2 (can defer)** Interventions on an obligation: in F or later?

### R8. The retrieval surface and the Mission Control skill

Context: §2.2 retrieval rows; the schema workspace model; the coordinator-surface proposal §3-§4
(one noun-verb grammar, the skill tree, CS-D1..D14).

**Strawman: the Mission Control workspace**, generated from the code registries and docs,
byte-identical on regeneration, versioned with the release:

```text
workspace/
  START_HERE.md                 what Mission Control is, the five goal properties, the four reads
  INDEX.md                      every card by kind, one line each
  families/                     stage-graph.md, goal-loop.md, (parallel-swarm.md: specified only)
  manifests/                    templates/*.yaml, the field reference per node kind
  obligations/                  kinds/*.md, validators/*.md, templates (from the catalog)
  transfer/                     points/*.md (T1-T10), tiers.md, heuristics.md
  capabilities/                 skills, mcp, hooks, plugins, subagents: how to search and pin each
  lanes/deep_agents/            LANE.md (the describe), features/*.md (one card per lane feature)
  model_tools/openai/*.md       one card per model tool, with its observability class
  hooks/                        events.md (the vocabulary), per-lane projection
  cli/                          one card per missionctl verb (generated from the argument parser)
  api/                          routes and MCP tools
  runs/                         how to read a run: transcript, points, outputs, inputs, fork
  search/index.jsonl            the lexical index; adjacency.json
```

with `missionctl docs search|get|slice --max-tokens` (or a `mc-workspace` CLI like `bks-schema`),
typed ids (`lane-feature:deep_agents.todo_list`, `obligation-kind:document`, `cli:run.fork`), and
a per-run view `missionctl run workspace RUN` that materializes a run's transcript, outputs,
inputs and points as files an agent can grep.

**Strawman: how the skill describes this to a coordinator told "use Deep Agents"** (the owner's
question). The router skill says, in this order:

1. "Read `workspace/START_HERE.md`, then `families/stage-graph.md`."
2. "Shape the graph: stages, dependencies, which can run in parallel (`concurrency`), which cycle
   (`cycle:`), where humans review."
3. "For each stage, write its obligations first (`obligations/kinds/`): what it must produce and
   in which form; pick a template when one fits."
4. "Configure each stage's agent: neutral capabilities first (`capabilities/`), then
   `lanes/deep_agents/features/` for native features, then `model_tools/<provider>/` for the
   model's own tools; every choice you make appears in the materialization receipt."
5. "Declare subagents with their own obligations and communication rules."
6. "Declare inputs: which upstream obligations each stage receives and at which tier
   (`transfer/`)."
7. "Compile, read the receipt and the issues, fix, submit; start only when the human asked."
8. "Watch with `run inspect`, `run outputs`, `run transcript --by stage`; intervene with
   `command inject`; fork with `run fork --at`."

- **R8.1 (must)** The generated workspace (vs. hand-written skill references only)?
- **R8.2 (must)** Its home and CLI (`missionctl docs ...` in this repository, vs. a separate
  package like `schema-workspace`)?
- **R8.3 (must)** The coordinator-surface decisions CS-D1..D14, one answer each (the agent reads the
  proposal's §7 table).
- **R8.4 (can defer)** The per-run workspace view.

### R9. The sequence

- **R9.1 (must)** Confirm or reorder §3.1 (A..I, T2), including the H and B alternatives.
- **R9.2 (must)** The live budget per sprint (the standing rule: at most 15 USD per session) and the
  models (Sol and Luna as in Stage 2?).
- **R9.3 (must)** Which sprint's session instruction the interviewer writes first and in full.

## 6. Known carry-forward the sequence must absorb

From the tracing ledger's honest lists and the Stage 3 review (dispositions in the Stage 3 entry):
the describe matrix cells Stage 2 proved but the SQL-seeded describe cannot change without a
release (cancel enforced at the model call; `usage.cost` is `unknown` on this lane; structured
output through the tool strategy), to ship with release 1.4.5; the `external.openai` budget
dimension never charged by this lane; the Goal Loop derived run's `goal_input` built by the test
fixture; the 30 older disposable databases on the cluster; and every Stage 3 finding marked
"deferred".

## 7. What the interviewer must not do

Build anything; change a sprint claim or an issue status; ask a question the code answers; let
a decision stand without the restated mental model; let a provider-specific decision stand
without its general form; drop the owner's words from §1.

## 8. Decision log (to fill during the interview)

| Date | Id | Question | Answer | Consequence |
| --- | --- | --- | --- | --- |
| | | | | |

## 9. Parking lot

| Date | Raised in | The owner's words | Where it goes |
| --- | --- | --- | --- |
| | | | |

## 10. The interviewer's session instruction (copy into the first message)

We are in the provider consolidation program, after tracing Stage 3 (merged to `main`). This
session is the owner interview in
`docs/specs/archive/provider-consolidation-2026-10/interview-instructions/OWNER-INTERVIEW-2026-10-22.md`. Work in
`platform/mission-control` on `main` or a docs branch `docs/owner-interview`; commit docs only,
when I say.

1. Read that document whole, then the output-contracts specification §2-§4 and §8, the
   coordinator-surface proposal §3, §4 and §7, the research sheet's "Implications" section, the
   ledger's Stage 3 entry, and the human review gates supplement at the platform root (its
   interviews HR0..HR9 join round R7).
2. Re-verify the §2.2 rows against live code and mark drift before the first question.
3. Run the rounds R0, R1, R1b, R2, R3, R5, R6, R7, R8, R9 in order, as §4.3 describes: context, at
   most four questions per batch with the recommendation first, the restated mental model,
   the record in §8, the drift check against §0.
4. After each round, commit nothing; after R9, update §3 to the decided sequence, fold the answers
   into the specification (OC-D*) and the proposal (CS-D*), and write the first sprint's
   `SESSION-<SPRINT>.md` in full.
5. End with the decision log, the sequence, and the first session instruction's path.
