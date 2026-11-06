---
type: Proposal
title: "The coordinator's projection: how a coordinator agent wants workflow and cognition capabilities presented, observed, fed back, remembered and prompted (Deep Agents first, every lane after)"
description: "Written from the stance of the Mission Control coordinator agent, 2026-10-23: the capability card as the unit of presentation (one schema, facets instead of a tree), the categories that emerge once provider middleware, model tools, hooks, memory and dynamic prompts are all selectable, the concept-to-lane-binding rule for things like subagents that are general in idea and specific in instantiation, the three tempos of observation (wake, read, tail) and why the coordinator never polls, what a hook or stream writer may do for a mission and what it may never do, the in-run coordinator communication tool with a reply path, a memory capability kind (semantic and entity, procedural, episodic) distinct from transfer, dynamic prompt sections rendered from state and recorded per model call, the full-control wish list by session phase, the anti-requirements, and decisions CO-D1..D18. Decides nothing; feeds interview sittings II and III and sprints B, F, I."
tags: [mission-control, providers, consolidation, deep-agents, coordinator, capabilities, observability, memory, prompts, proposal]
---

# The coordinator's projection

**Status: proposal, draft (2026-10-23).** This document is written in the voice of the
coordinator agent: the agent that reads Mission Control, surveys what can be configured, authors a
Goal Directed or Stage Graph mission with Deep Agents (or another lane) inside, launches it, waits,
reads, acts and closes. The owner asked that agent what it would want if it could have all the
control in the world, how it would want the information organized, and whether it would poll or
be called back. The answers below transcend the owner's prompts where that helps, and they stay
inside the system's invariants: Temporal alone schedules, reducers own settlement, agents never
write tables (ADR 0056), signals and graph state are evidence and never authority (ADR 0007,
ADR 0045).

It decides nothing. It is grounded in the
[Deep Agents surface sheet](../provider-consolidation-2026-10/providers/deep_agents/DEEP-AGENTS-SURFACE-2026-10-22.md), the
[owner interview](../archive/provider-consolidation-2026-10/interview-instructions/OWNER-INTERVIEW-2026-10-22.md) (rounds R3, R7, R8), the
[output-contracts specification](../archive/provider-consolidation-2026-10/specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md)
(§3.7 communication obligations, §4 transfer points), the
[coordinator-surface proposal](PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md)
(nouns, grammar, events), the review-gates supplement at the platform root, and three concepts
that already exist in the code: [Watchers](../../knowledge/watchers.md),
[Signal Ingress](../../knowledge/signal-ingress.md) with the executor skill `mc-signals`, and the
[wake channels](../../knowledge/wake-channels.md). Where it proposes something those do not have,
it says *proposed*. Where it rests on a fact it could not verify, §12 says so.

| Section | Answers |
| --- | --- |
| §1 | Who I am when I read this, and the one principle: I select, I never compose code |
| §2 | The capability card: the unit of presentation, its fixed fields, two worked examples |
| §3 | The categories that emerge, and why they are facets, not a tree |
| §4 | General concept, specific instantiation: the concept card and its lane bindings (subagents as the hard case) |
| §5 | Where every Deep Agents middleware and model tool lands, with its governance visibility |
| §6 | Observation: wake, read, tail. Why I never poll. What a hook or the stream writer may do for a mission |
| §7 | The coordinator communication tool: from one-way signals to a durable reply path |
| §8 | Memory: a capability kind with scope, kind, write policy and provenance, distinct from transfer |
| §9 | Dynamic prompts: a closed set of sections rendered from state, recorded per model call |
| §10 | All the control in the world: the wish list by session phase, across lanes |
| §11 | What I do not want |
| §12 | Decisions CO-D1..D18, where they land, and the honest list |

---

## 1. Who I am when I read this

I am an agent with a context window, a tool surface (`missionctl`, the operator HTTP API or the
operator MCP) and a human who told me what they want. In one session I do seven things, in this
order, and sometimes loop back:

| Phase | What I do | What I consume |
| --- | --- | --- |
| Survey | Find out what this installation can do: lanes, models, capabilities, lane features, model tools, obligation templates, memory spaces | describe rows, cards, search |
| Author | Write a manifest: program shape, per-agent cognition, subagents, obligations, transfer, controls | cards, templates, the compile result |
| Launch | Submit, preflight, start | receipts |
| Wait | Block on the inbox until something that needs me happens | notifications with a reason and a position |
| Read | Look at exactly the part of the run the notification names | peek, transcript, points, state as of, outputs, inputs |
| Act | Queue, inject, answer, revise, fork, cancel, spawn a linked run | typed receipts naming the point they landed at |
| Close | Accept or reject, promote, record what was learned | fulfillment reports, memory writes with provenance |

Two facts about me shape everything below.

**My context is the scarcest resource in the system.** Every token a notification, a card or a
read costs me is a token I cannot spend on judgment. So I want information that is *dense,
positioned and actionable*: it names the unit and the point it is about, it says what changed,
and it says what I can do. I do not want streams in my context, I do not want to poll, and I do
not want to read a 900-line fact sheet to find out whether the OpenAI web search tool is gated
by approvals (it is not; §5).

**I select, I never compose code.** The owner's rule is right: giving me a code environment and
the deepagents library would be powerful and ungovernable. Nothing I write can be sealed,
digested, receipted or replayed if it is a Python import path. So every lever below is a
*selection with typed configuration*: a card id, a config block the schema validates, and a
receipt that says what the lane actually did with it. Interview R3's answer (hook scripts on the
neutral vocabulary plus curated middleware features, never arbitrary middleware) is the shape of
every lever in this document, including the new ones (observer features §6.4, the communication
tool §7, memory §8, prompt sections §9).

---

## 2. The capability card

### 2.1 The one question

For every selectable thing I ask the same question: **what does it change in what I write, what
will I observe because of it, and what can I do about it later?** A presentation that answers
those three for every item, in the same place and the same order, is one I can search, compare
and trust. A presentation organized by vendor package, by Python class, or by "the docs page it
came from" is one I have to re-derive every session.

So the unit of presentation is a **card**: one record per selectable thing, with fixed fields.
Interview R8 and sprint I already name cards for obligations, transfer points, lane features,
model tools and mission types. This section says what fields every card has, because the fields
are what make cards searchable across kinds.

### 2.2 The fields (proposed `mc.capability_card.v1`)

| Field | Content | Why I need it |
| --- | --- | --- |
| `id` | Dotted, by axis: `deep_agents.todo_list`, `openai.web_search`, `capability.skill`, `concept.subagent` | One name across manifest, CLI, receipt, frame and skill text |
| `layer` | `capability` (neutral, catalog), `lane_feature` (by lane), `model_tool` (by model provider), `concept` (general idea with bindings, §4) | Tells me which manifest block it goes in |
| `category` | One primary from §3, plus secondary tags | Browse and compare |
| `scope` | Where it may be set: `agent`, `subagent`, `stage`, `goal`, `mission`, `chain_link`, `review_gate` | Stops me putting a mission-level thing on a subagent |
| `axis` | `lane: deep_agents` or `model_provider: openai`, or `any` | The discriminated container it travels in |
| `knobs` | Typed fields with defaults and ranges, each one sentence | The config block I will write |
| `effect` | What it changes in the agent: prompt (which layer), tools added or removed, graph nodes added (a `before_model` node shifts step numbering), state channels, model settings | Lets me predict the Transcript |
| `observed_as` | The frames, events and point roles it produces; `none` is a valid and important value | What I will see |
| `visibility` | `governed` (passes the tool node: hooks, HITL, limits, retries see it), `observed_only` (recorded, not gateable), `server_side` (never enters the tool node), `silent` | Whether approvals and budgets apply |
| `inheritance` | To sync children, async children, dynamic children, forks, linked runs: `inherits`, `copies`, `isolated`, `n/a` | Subagent configuration is mostly this field |
| `transfer` | What of it crosses transfer points T1–T10, and in which depth layer | Keeps transfer precise |
| `governance` | Budget it consumes, approval classes it triggers, permits it needs, egress it implies | Preflight in my head |
| `maturity` | `installed`, `needs_upgrade (vN)`, `beta`, `experimental`, `proposed` | Whether I may rely on it today |
| `requires` / `conflicts` | Other cards, lane version floors, model families | Compile blockers before compile |
| `lane_bindings` | For concepts: the per-lane card ids and a one-line "what differs" | §4 |
| `example` | One manifest fragment that compiles | Copy, then edit |
| `evidence` | The surface-sheet citation and the fixture that proved it | Trust |
| `search` | Tags: synonyms, the vendor's name for it, the lifecycle seam it acts at | Find it by any name |

The schema is generated from the registries interview R3 proposes (`LaneFeature`, `ModelTool`,
the catalog kinds), never hand-written, so a card cannot go stale without the describe row going
stale with it. The `missionctl` form is `card search <terms>`, `card get <id>`,
`card list --category <c> --lane <l> --visibility <v>` (nouns per the coordinator-surface
grammar; CS-D1..D14 own the final spelling).

### 2.3 Two worked cards

**`openai.web_search`** (layer `model_tool`, category *tooling*, secondary *retrieval*):

| Field | Value |
| --- | --- |
| scope | `agent`, `subagent` |
| axis | `model_provider: openai` (any lane that drives an OpenAI model through LangChain; on Deep Agents this means a Responses API call) |
| knobs | `search_context_size: low \| medium \| high` (default `medium`); `user_location` optional |
| effect | A dict tool bound to the model; no tool node, no graph node; the model's reply carries `server_tool_call` and `server_tool_result` content blocks with citations |
| observed_as | *proposed:* a `model_tool_call` frame per call, built from the content blocks, linked to the step's point; today the recorder has no kind for it |
| visibility | **`server_side`**: no hook, HITL gate, call limit or retry sees it. Budgeted per call only. A mission that requires approvals on retrieval must not select it (interview R3.5) |
| inheritance | sync children that inherit tools get it; async and dynamic children do not unless their own graph binds it |
| transfer | results are in the transcript (history layer); a citation the agent used becomes a deliverable only through an obligation |
| governance | provider cost per call; egress to the vendor's search, outside the mission's allowlist |
| maturity | `installed` (langchain-openai 1.3.4) |
| requires | model family `openai:*`; a Responses API profile |
| example | `model_tools: { openai: { web_search: { search_context_size: medium } } }` |
| evidence | surface sheet §6.1 |
| search | web search, Responses API built-in, retrieval, citations |

**`deep_agents.async_subagents`** (layer `lane_feature`, category *delegation*):

| Field | Value |
| --- | --- |
| scope | `agent` (the parent); each child is a subagent profile with `kind: async` |
| axis | `lane: deep_agents` |
| knobs | per child: `graph_id`, `placement: agent_server`, budget slice, `update_strategy: interrupt \| enqueue` (needs upgrade), `notify_parent` (forced `false` while Mission Control owns delivery), `mode: isolated \| fork` (needs upgrade, experimental) |
| effect | Five tools on the parent (`start_async_task`, `check_async_task`, `update_async_task`, `cancel_async_task`, `list_async_tasks`); state channel `async_tasks`; on 0.7.30 the stock middleware would add `before_model`/`after_model` nodes, which Mission Control's governed wrapper deliberately does not attach |
| observed_as | `subagent_started` / `subagent_ended` frames, the `lineage` event, `child_lifecycle` inbox kind; the child's own frames only if the Agent Server frames are mirrored (`lifecycle_only` fidelity today) |
| visibility | `governed`: spawn is fenced and budgeted before any HTTP call; the child's result is revealed to the parent only after admission |
| inheritance | the child gets only the one-sentence description plus what its served graph carries; context forwarding to co-deployed children needs upgrade |
| transfer | T6 (parent to child) and T7 (child to parent) through the transfer policy; the child's obligations are checked at admission (OC §3.7) |
| governance | a budget slice per child; `ASYNC_SUBAGENT_SPAWNING_ENABLED` on the worker; the served graph's revision and binding digest must match the sealed contract |
| maturity | `installed` for spawn, check, update, cancel; the push notifications and `enqueue` are `needs_upgrade (0.7.30)` and `beta` |
| conflicts | the stock 0.7.30 `AsyncSubAgentMiddleware` attached directly (bypasses admission) |
| example | the subagent profile with `kind: async` from SUBAGENTS.md §4 |
| evidence | surface sheet §3.2; ASYNC-SUBAGENTS-EXPLAINED |
| search | async subagent, Agent Server, background task, two-way, check in |

Reading those two cards side by side tells me, without opening a fact sheet, that one of them
is invisible to approvals and the other is fenced before it spends a cent. That contrast is the
whole point of the `visibility` field.

---

## 3. The categories that emerge

### 3.1 The list

Interview R3 names six categories for lane features: context management, tooling, delegation,
control and safety, state, persistence. Once hooks, model tools, memory, prompts and the
communication channel are also selectable, four more emerge from the coordinator's seat, and one
of the six splits. The membership test for each is in the right column; a card belongs to the
category whose test it passes first.

| Category | Test: the card primarily... | Examples (Deep Agents first) |
| --- | --- | --- |
| **Context management** | changes what the model sees of its own history | summarization knobs, `compact_conversation`, context editing, filesystem eviction limits, OpenAI and Anthropic server compaction, prompt caching |
| **Prompting** | changes the system prompt or its per-call rendering | instruction layers (ADR 0044), `MemoryMiddleware` (AGENTS.md files), skills frontmatter disclosure, *dynamic prompt sections* (§9) |
| **Tooling** | gives the agent a tool it executes or the provider executes | filesystem tools, `execute`, shell, todo list, code interpreter, OpenAI and Anthropic server tools, MCP servers, catalog tools |
| **Delegation** | lets the agent spawn or hand off cognition | sync, async and dynamic subagents, fork-mode children, linked runs, the general-purpose child |
| **Control and safety** | can stop, gate, limit or alter a model or tool call | HITL `interrupt_on`, filesystem permissions, model and tool call limits, retries and fallbacks, PII, moderation, auto-mode risk gating, rubric |
| **Observation** | produces evidence and changes nothing else | hook scripts in record mode, *observer features* (§6.4), tracing policy, the frame recorder's capture profile, `progress_note` |
| **Communication** | moves a message between an agent and Mission Control, the coordinator, a human or another agent | `mc-signals`, the *coordinator communication tool* (§7), communication obligations (`report`, `join`), review gates, async-task update |
| **Memory** | makes something available to a *later, undirected* reader by relevance | AGENTS.md notes, Store-backed `/memories/`, the Anthropic memory tool, *memory spaces* (§8) |
| **State** | declares typed channels the graph carries and reduces | the context schema, the `mc_*` channels, custom state keys, child merge-back policy |
| **Persistence and environment** | decides where files, checkpoints and processes live | backends (state, store, composite, sandboxes), the saver, environment kits, sandbox profiles, network policy |
| **Obligations and transfer** | declares what a unit owes and what crosses a transfer point | output kinds, obligation templates, transfer tiers, dependency kinds, `inputs:` and `outputs:` |

Memory is split out of persistence because they answer different questions: persistence is
"where does this live", memory is "who may find this later and how". Observation is split out of
control because the first is safe to add to any mission and the second never is. Communication
gets its own row because the owner's three open questions (hooks that send data back, the
check-in tool, a coordinator communication tool) are all communication questions wearing other
clothes.

### 3.2 Categories are a facet, not a tree

I do not browse a tree. I search with several facets at once, because my questions look like
"everything on this lane that is invisible to approvals", "every context-management lever that
survives a fork", or "what will an async child inherit". The card schema (§2.2) gives me the
facets; the category is the first one, not the only one:

| Facet | Values | Typical question |
| --- | --- | --- |
| category | §3.1 | "what can I do about context growth" |
| layer | capability, lane feature, model tool, concept | "is this portable to Claude Agent SDK" |
| lane, model provider | the nine lane profiles; openai, anthropic, google | "what is native here" |
| seam | `before_agent`, `before_model`, `wrap_model_call`, `wrap_tool_call`, `after_model`, `after_agent`, `server_side`, `boundary` | "what runs before every model call" |
| visibility | governed, observed only, server side, silent | "what escapes HITL" |
| maturity | installed, needs upgrade, beta, experimental, proposed | "what can I rely on this week" |
| scope | agent, subagent, stage, goal, mission, chain link, review gate | "what may a subagent have" |
| inheritance | inherits, copies, isolated | "what does the child get" |

The seam facet matters more than it looks. The Transcript is positioned by cognition points, and
a feature that adds a graph node (`before_model`, `after_model`) changes where steps fall. A card
that says "adds a node at `after_model`" tells me that two otherwise identical runs will number
their steps differently, which matters when I fork from "step 14".

---

## 4. General concept, specific instantiation

Subagents are the owner's example: the *idea* is general, the instantiation on Deep Agents is
specific (an in-process `SubAgent` dict, an Agent Server graph, a QuickJS `task()` call), and on
other lanes it is a markdown file, a TOML file or a flag. Hooks, memory, compaction, human
control, prompts and sandboxes all have the same shape. I want that shape made explicit, not
flattened into one list where `deep_agents.sync_subagent` sits beside `openai.web_search` as if
they were the same kind of thing.

### 4.1 The concept card and its bindings

A **concept card** (`layer: concept`, ids `concept.subagent`, `concept.hook`, `concept.memory`,
`concept.compaction`, `concept.human_control`, `concept.prompt`, `concept.sandbox`,
`concept.communication`) carries:

1. the neutral contract I author against (for subagents, `mc.subagent_profile.v1`; for hooks,
   ADR 0026's event vocabulary; for memory and prompts, the contracts §8 and §9 propose);
2. the **common core**: the fields every lane must honour natively or degrade with a receipt;
3. the **binding table**: one row per lane (and per kind inside a lane), each row linking the
   lane-feature card that instantiates it, with the three columns I actually compare on:
   *what differs*, *what is degraded or unsupported*, *what I observe*.

The subagent binding table, from what exists today:

| Binding | Instantiation | What differs | Degraded or unsupported | What I observe |
| --- | --- | --- | --- | --- |
| `deep_agents.sync_subagent` | `SubAgent` dict, nested graph in the parent's `tools` task | shares the parent's state schema and checkpointer; merge-back of `files` and custom keys; per-child `response_format` carries the child's obligation | `sandbox.own` degraded; `max_turns` degraded | `full`: frames with `subordinate_ref`, nested `tools:*` points |
| `deep_agents.async_subagent` | Agent Server graph, governed wrapper | only the description travels; pull-based check-in; admission before reveal | `placement.lane` unsupported | `lifecycle_only` unless server frames are mirrored |
| `deep_agents.dynamic_subagent` | QuickJS `task()` inside `eval` | the model writes the fan-out; typed `responseSchema` per dispatch; bypasses the parent's HITL per dispatch | gate `eval` itself; concurrency cap needs upgrade | `subagent` lifecycle events on the custom stream (proposed as frames) |
| `claude_agent_sdk.subagent` | `.claude/agents/*.md` | file-defined prompt, model, tools | no async, no sandbox | hook frames |
| `codex.subagent` | `.codex/agents/*.toml` | model and read-only only today | threads park units `in_doubt` (RF-14) | events |
| `claude_managed`, `codex_agents` | flag | nothing configurable | all fields degraded | provider events |
| any lane | `linked_run` | a Mission Control run with its own lane and sandbox | none; it is the escape hatch | the full Transcript of the child run |

When I read the concept card I learn the idea once; when I read a binding row I learn exactly
what my manifest line will do *here*. The receipt (`mc.materialization_receipt.v1`) is the
runtime echo of the binding row, so the card, the receipt and the describe matrix say the same
thing in the same words.

### 4.2 The rule

Every lane feature that instantiates a concept names the concept in its card
(`implements: concept.subagent`), and the concept's binding table is generated from those
declarations. A lane feature with no concept is lane-specific by nature (the todo list, the
rubric, QuickJS) and says so. This is PROCESS §2's discriminator-and-router rule, applied to the
documentation: the concept is the neutral contract, the bindings are the per-lane adapters, and
nothing in the skill text branches on the lane outside a binding table.

---

## 5. Where the Deep Agents surface lands

The table below places every selectable item of the surface sheet into §3's categories, with
the two facets I care about most. "Needs upgrade" means 0.7.30 / langchain 1.4.x / quickjs 0.3.9
(sprint A). Nothing here is new; it is the sheet re-cut the way I want to read it.

| Card id (proposed) | Category | Seam | Visibility | Maturity | Note for the coordinator |
| --- | --- | --- | --- | --- | --- |
| `deep_agents.summarization` | context management | `wrap_model_call` | observed only (`before_compaction` / `after_compaction` frames) | installed; `summarizer` needs upgrade | history is offloaded to files, not deleted; a fork from before compaction still sees it |
| `deep_agents.compact_tool` | context management | tool | governed | installed | the agent chooses when; I see a compaction frame either way |
| `deep_agents.context_editing` | context management | `wrap_model_call` | observed only (proposed `mc.context_edited`) | installed | removes from the model's context, not from the Transcript |
| `deep_agents.filesystem_eviction` | context management | `wrap_tool_call` | observed only | installed; binary offload needs upgrade | evicted bodies should become artifacts linked to the point (OC §5) |
| `openai.compaction`, `anthropic.compact`, `anthropic.clear_tool_uses` | context management | server side | **server side** | installed (model settings) | Mission Control must keep the `compaction` blocks |
| `deep_agents.prompt_caching` | context management | `wrap_model_call` | silent | installed, automatic | cost lever, no behaviour change |
| `deep_agents.memory_files` (`MemoryMiddleware`) | prompting (reads), memory (source) | `before_agent` + prompt | observed only | installed | AGENTS.md-style notes into the prompt; see §8 |
| `deep_agents.skills` | prompting + tooling | `before_agent` + prompt | observed only | installed; pinned and lazy tools need upgrade | moves to the tail of the stack in 0.7.30 |
| `deep_agents.todo_list` | tooling | `after_model` node | governed | installed, **not default** | adds a node: shifts step numbering |
| `deep_agents.filesystem_tools` | tooling | tools | governed | installed | per-agent subset |
| `deep_agents.execute` (sandbox backend) | tooling | tool | governed | installed (Docker, read-only today) | hidden when the backend is not a sandbox |
| `deep_agents.shell` (`ShellToolMiddleware`) | tooling | `before_agent`/`after_agent` nodes | governed | installed | Docker or Codex execution policies |
| `deep_agents.code_interpreter` (QuickJS) | tooling + delegation | `before_agent`, `wrap_model_call`, `after_agent` | **governed only at `eval`**; dispatches inside bypass HITL | installed 0.3.5 (beta); caps need upgrade | gate `eval`; after OC-2 |
| `deep_agents.tool_retry`, `tool_error`, `tool_emulator` | tooling | `wrap_tool_call` | governed | installed | emulator for test missions only |
| `openai.web_search`, `file_search`, `code_interpreter`, `image_generation`, `mcp`, `tool_search` | tooling | server side | **server side** | installed | §2.3; `apply_patch` and computer use need client code and are not offered |
| `anthropic.web_search`, `web_fetch`, `code_execution`, `mcp`, `tool_search` | tooling | server side | **server side** | installed | same rule |
| `anthropic.bash`, `text_editor`, `memory_tool` | tooling / memory | client middleware | governed | installed | the memory tool is a §8 binding |
| `deep_agents.tool_selector`, `provider_tool_search` | tooling (context) | `wrap_model_call` | silent | installed | shrink tool payloads; OpenAI and Anthropic only for the provider variant |
| `deep_agents.sync_subagent` | delegation | tool `task` | governed | installed; fork mode needs upgrade | §4.1 |
| `deep_agents.async_subagents` | delegation | tools | governed | installed; push, enqueue, webhook need upgrade | §2.3 |
| `deep_agents.general_purpose_child` | delegation | tool | governed | installed | explicit on or off; it inherits every tool |
| `deep_agents.interrupt_on` (HITL) | control | `after_model` node | governed | installed; **parks `in_doubt`** until the Human Task binding lands | decisions approve, edit, reject, respond |
| `deep_agents.filesystem_permissions` | control | `wrap_tool_call` | governed | installed; symlink fix needs upgrade (0.7.25) | `interrupt` mode auto-installs HITL |
| `deep_agents.call_limits` | control | `before_model`/`after_model` nodes | governed | installed | should surface as a typed `budget_limit_reached` outcome |
| `deep_agents.model_retry`, `model_fallback` | control | `wrap_model_call` | silent | installed | fallback changes the model mid-run: must be receipted and framed |
| `deep_agents.pii`, `openai.moderation`, `openai.auto_mode` | control | nodes / `wrap_tool_call` | governed | installed; auto mode needs langchain-openai 1.7 | |
| `deep_agents.rubric` | control (self-evaluation) | `before_agent`/`after_agent` nodes | observed only | installed | active only when state carries `rubric` |
| `deep_agents.tracing_policy` | observation | class attribute | silent | needs upgrade (langchain 1.4) | payload omission for LangSmith |
| `concept.hook` on Deep Agents | observation / control | middleware seams | governed | **refused today (409)**; sprint B lifts it | §6.4 |
| `deep_agents.context_schema` | state | runtime | silent | installed, unused by middleware | the identity source (R3.6) |
| `deep_agents.state_channels` (`mc_*`) | state | reducers | silent | proposed (OC-D24) | evidence, never authority |
| `deep_agents.backend` (state, store, composite, docker, langsmith, sandbox providers) | persistence | backend | silent | installed subset | a wrong backend is refused at launch, never switched |
| `deep_agents.saver` | persistence | checkpointer | silent | installed (`AsyncPostgresSaver`) | the thing points and forks index |
| `deep_agents.temporal_contrib` | persistence (architecture) | n/a | n/a | installed, unused | an open decision, not a card |

Three things I want said on every card in this table and nowhere else: *does it add a node*,
*does it escape the tool node*, and *does it survive a fork from a point*. The sheet has the
facts; the card puts them where I look.

---

## 6. Observation: wake, read, tail

### 6.1 Would I poll?

No. Polling is the worst use of my context: every empty check costs tokens and teaches me
nothing. The system already knows this and built the right thing: the durable coordinator inbox
with a server-side long-poll (`missionctl wait`, `coordinator_inbox_wait`), classified
notification kinds, and Watchers that turn observed facts into bounded reactions without a
supervisor loop. What I want is to make those two the *only* way I learn things while idle, and
to give them more to say.

Three tempos, each with its own surface, each used for one thing:

| Tempo | Surface | When I use it | What it must carry |
| --- | --- | --- | --- |
| **Wake** | the inbox (`wait`, kinds, ack) | always, while idle | a *reason* (the kind), a *position* (unit key, point ref, stage/cycle/iteration), a *digest of what changed*, and the *verbs that apply* |
| **Read** | peek (`run inspect`), `run transcript --at`, `point state`, `run outputs --at`, `run inputs --at`, `node describe` | after a wake, scoped to the position the wake named | the three depth layers of OC §4.1, with handles to go deeper |
| **Tail** | Socket.IO, SSE, `point frames` | only while I am awake and watching one unit on purpose (a demo, a diagnosis), or for a dashboard that is not me | raw frames; never routed into my context by default |

A callback, in the sense of "run my code when X happens", is the wrong primitive for me: I am
not code, I am a context. What I want is a **wake with a position**. The difference is the
whole design: a wake is delivered durably, acknowledged explicitly, batched and bounded, and it
survives my absence; a callback runs or is lost.

### 6.2 What I want the wake to be able to say

The inbox kinds today are `review_required`, `blocked`, `failed`, `terminal_result`,
`accepted_output`, `child_lifecycle`, `review_closed`, `progress`. Watchers can `notify` with a
kind from declared triggers (events, signals, absence, schedule). To act well I want the wake
vocabulary to grow along the facts the obligations and tracing work are creating:

| Proposed kind or fact | Fired when | Position it carries |
| --- | --- | --- |
| `obligation_fulfilled`, `obligation_unmet` | the reducer records a fulfillment row (sprint F's events) | unit key, obligation name, point ref |
| `budget_threshold_crossed` | a unit crosses a soft threshold of tokens, cost, model calls or wall clock | unit key, which budget, remaining |
| `decision_point` | the agent did something I declared I care about: first use of a tool class, a subagent spawned, a compaction, a model fallback, a context edit, a memory write (§8), a prompt section change (§9) | point ref |
| `question` | an agent asked the coordinator something through the communication tool (§7) | unit key, question id, deadline |
| `transfer_planned` | the transfer policy produced a plan for a consumer | consumer unit, plan digest |
| `point.recorded` | a cognition point was written (coordinator-surface §5.2) | point ref |
| `watch_condition_met` | a coordinator-authored watch condition (§6.3) evaluated true | whatever the condition named |

Every wake carries `unit_key`, `point_ref` and a `location` (the additive envelope fields the
coordinator-surface proposal asks for, CS-D5). Without the position a wake makes me read the
whole run to find what it meant.

### 6.3 Watch conditions I author at run time (proposed extension of Watchers)

Watchers are compiled from the manifest today. As the coordinator I also want to say, *after*
launch and in light of what I have read, "wake me when stage S3 submits its report", "wake me
when any child has used 60% of its slice", "wake me if no obligation progresses for 30 minutes".
Proposed: a run-time `watch` noun whose conditions use the same closed AST as Watchers
(ADR 0010), extended with the new fact roots the obligations and tracing work create
(`obligation`, `budget`, `point`, `child`, `memory`), whose only actions are `notify` and the
already-admitted commands, and which compiles into an `mc.watchers.v1` descriptor attached to
the run with lineage to the coordinator that authored it. It is not a callback; it is a
declaration Mission Control evaluates for me on Temporal with the journal as its state, exactly
as manifest watchers are.

### 6.4 Hooks and the stream writer: what "do something for the mission" may mean

The owner asked whether the coordinator should be able to slot in a hook or callback inside Deep
Agents that sends data back, and whether to architect the stream writer or the middleware
lifecycle hooks so that they (1) do something for the mission and (2) feed information back.
Here is how I would want it to work, by seam and by effect class.

**The channel back is the frame recorder, not me.** Inside the Deep Agents turn, the custom
stream (`get_stream_writer`) is already how Mission Control's kernel hooks and compaction
observer emit `hook_invoked`, `hook_result`, usage and compaction frames; the recorder consumes
`stream_mode=["updates","messages","custom","values","checkpoints"]` and `custom.mc.progress_note`
is already a frame kind. That is the right design, and I want it generalized rather than bypassed:
*anything a hook, middleware or tool wants me to know becomes a typed custom-stream event, which
becomes a frame linked to the current point, from which a significance rule or a watch condition
derives a wake.* Nothing talks to me directly from inside a run. The frame is durable, replayable,
positioned and forkable; a direct message to me is none of those.

**What a hook may do, per seam.** The lifecycle seams are the middleware hooks the surface sheet
maps (§8 there): `before_agent`, `before_model`, `wrap_model_call`, `wrap_tool_call`,
`after_model`, `after_agent`, plus the summarizer seam for compaction and the `task` /
`start_async_task` tools for subagent start and stop. The effect classes I want a curated feature
or a hook script to be allowed, and nothing else:

| Effect class | What it does | Seams | Who may select it |
| --- | --- | --- | --- |
| **Observe** | emit a typed custom-stream event (becomes a frame) | all | any mission, any scope: it is safe |
| **Annotate state** | write to a Mission Control channel (`mc_obligations`, `mc_children`, `mc_transfer`, a proposed `mc_notes`) through its reducer | `after_model`, `wrap_tool_call`, `after_agent` | curated features only |
| **Enforce** | deny or rewrite a tool call, deny a model call, require an approval | `wrap_tool_call`, `before_model` | curated features and hook scripts in gate mode; receipted |
| **Redirect** | `jump_to` the model or end the turn | `after_model` | curated features only; every jump is a frame |
| **Prompt** | contribute a dynamic prompt section (§9) | `wrap_model_call` | curated sections |
| **Submit** | `submit_output(...)` for an obligation, or a progress note | tool | the agent itself (OC §3.3), never a hook on its behalf |
| **Communicate** | post to the coordinator mailbox (§7) | tool | the agent itself |

Two things a hook may never do: call back into me synchronously, and write authoritative state.
Both are already invariants; I am restating them from my side because the owner's intuition that
"peeking into graph state does nothing for writing to it" is correct, and the answer is not to
let hooks write it. The answer is that *writing* happens through typed interventions at
boundaries (queue, inject, add context, revise, resume an interrupt), each with a receipt that
names the point it landed at, and the adapter translates them into the graph (a new message, an
`update_state` on a declared channel, a resume command). I never want raw `update_state`; I want
"re-open obligation `report`", "add this artifact to context", "resume the question with this
answer", and to see where in the Transcript it took effect.

**Observer features** (proposed, category *observation*): curated middleware whose only effect
class is *observe*, selectable by id with a small config, emitting named events. The first set I
would want: `observe.decision_points` (the triggers in §6.2), `observe.tool_class_first_use`,
`observe.context_pressure` (tokens in context per model call, threshold crossings),
`observe.child_status` (async task status changes while the parent is idle),
`observe.prompt_render` (the digest and section list of every rendered system prompt, §9). Each
one is a card with `visibility: observed_only`, adds no node unless the card says so, and is
portable to other lanes as a hook script in record mode where the lane has the seam, with a
receipt saying `native | emulated | degraded`.

### 6.5 Reading the graph state

Peeking is solved in principle: state as of a point exists on this lane, the Transcript is the
replayable record (ADR 0054), and points are the coordinate. What I want added, in the coordinator
surface's words, is the **decision log**: a projection of the Transcript per unit that lists only
the decision points (§6.2) with one line each and the point to jump to. It is what I read first
after a wake, before the full transcript. Sprint F's "per unit: 2 of 3 obligations fulfilled" in
`run inspect` is the first row of it.

---

## 7. The coordinator communication tool

### 7.1 What exists, and the gap

Agents inside a workspace already have a one-way channel: `mc-signals` emits `milestone`,
`blocked`, `needs_input`, `artifact.ready` and `progress` through Signal Ingress, signals are
evidence that can wake me or fire a watcher, and the skill says plainly "nobody replies through
it. Do not wait for an answer." The Deep Agents lane, running in-process, has `progress_note`
frames through the custom stream but no equivalent of the signal tool exposed to the model, and
the output-contracts specification adds `submit_output` and communication obligations
(`report: on_return | progress(every N) | on_request`, `join: all | any | none`).

The gap is the reply. `needs_input` says a decision belongs to a human or the coordinator, and
then the agent has no way to receive the decision except an inject it cannot predict. The async
subagent's check-in is a pull by the parent, not a channel for the child to ask. So yes: agents
running in Mission Control should have a coordinator communication tool, and its defining
feature is a **durable, typed reply path**.

### 7.2 The tool (proposed `mc_coordinator`, one tool, four acts)

| Act | Shape | What Mission Control does | Does the agent wait? |
| --- | --- | --- | --- |
| `report(kind, text, data)` | the five signal types, plus `decision_made` | frame + signal row; significance may wake me | never |
| `ask(question_id, kind, text, options?, deadline?)` | `kind: choice \| confirm \| information \| escalation` | frame; a **Coordinator Task** (the Human Task Service with a coordinator as the reviewer class, ADR 0038's second origin); inbox kind `question`; the unit enters `waiting` through the lane's native interrupt (`interrupt()` on Deep Agents), so the wait is durable and survives a worker restart | yes, unless a standing answer exists |
| `answer_available()` | | reads the task; used only on lanes with no native interrupt | no |
| `handoff(summary, artifacts)` | at a review gate or before a long child | frame + a review packet item | per the gate |

The reply path is the existing intervention machinery: my `command answer RUN --question Q
--choice B` (grammar per CS) resolves the Coordinator Task, which resumes the interrupt with
`Command(resume=...)` on Deep Agents or lands as an inject at the next boundary on lanes without
a mid-turn primitive; the receipt names the point the answer entered at, and the Transcript shows
question and answer as a pair.

**Standing answers.** Blocking on me is expensive for the run and sometimes unnecessary. I want
to pre-authorize answers in the manifest or at run time: `standing_answers: [{match: {kind:
confirm, pattern: "delete generated files"}, answer: approve, max_uses: 5}]`. A question that
matches is answered by Mission Control, recorded as a frame with `answered_by: standing_answer
<id>`, and shows up in my decision log without waking me. A question that does not match wakes
me with the deadline, and the timeout policy is the mission's (K12: keep waiting, deny,
escalate), never a silent default.

**Limits.** Questions are budgeted per unit (`max_questions`, default small) and per child depth;
a child's `ask` routes to its parent first if the parent declared `answers_children: true`, else
to me; an `ask` from a dynamic QuickJS child is refused unless the dispatch declared it. All four
acts are frames before they are anything else, so the Transcript is complete without the mailbox.

**Relation to communication obligations.** The tool is the carrier; the obligation is the
contract. `report: progress(every: 10 model calls)` is enforced by a curated feature that counts
model calls and marks the obligation unmet if no `report` arrived; `must_review` and `join` are
checked at settlement as OC §3.7 says. The tool does not replace `submit_output`: deliverables go
through obligations, messages go through the mailbox, and the card for each says which.

**When I am inside a run.** The scoped `mc.coordinate` credential (README D8) gives an agent in a
run the same verbs over the runs it launched. The same tool chain then works downward: my
children ask me through `mc_coordinator`, I answer them through `command answer`, and my own
coordinator sees it all in my Transcript.

---

## 8. Memory

### 8.1 The distinction that matters

Transfer and memory are different and I need both. **Transfer** is directed and exact: a
producer's deliverables and state reach a named consumer at a transfer point, under a policy,
with digests. **Memory** is undirected and relevance-based: something a unit learned is
available to any later reader that asks the right question, possibly in another mission, another
chain, another month. Short-term memory (the messages list) is standard and out of scope here.
Today the system has transfer, a very good de facto semantic memory (Knowledge Services, queried
through admitted capabilities by the `mc-cognition-knowledge-services` skill), a de facto
procedural memory (AGENTS.md files through `MemoryMiddleware`, skills), and no episodic memory at
all except the Transcript, which nobody later reads by relevance.

### 8.2 A memory space as a catalog capability kind (proposed)

I want memory to be a **capability kind** (`memory_space`) pinned in a manifest like a skill or
an MCP server, so that admission, receipts, custody and retention apply to it, and so that a card
describes it. Its contract (`mc.memory_space.v1`):

| Field | Values | Meaning |
| --- | --- | --- |
| `kind` | `semantic`, `entity`, `procedural`, `episodic` | what it holds: facts and documents; notes about named things (a repository, a dataset, a person's preferences); how-to and conventions; what happened and what it taught |
| `scope` | `agent`, `mission`, `chain`, `application`, `installation` | who may read it later; the Store namespace |
| `read` | `inject` (a prompt section, §9), `tool` (query on demand), `both` | how it enters the agent |
| `write` | `agent` (through a memory tool), `derived` (Mission Control writes at settlement), `curated` (humans, through review) | who may add to it |
| `admission` | reads free within scope; writes are domain writes: admitted capability, receipt, quarantine for `agent` writes until a reviewer or a policy promotes them | ADR 0056: agents never write tables, so a memory write is a receipted effect, not a table write |
| `provenance` | every item carries the run, unit and point it came from | a memory I cannot trace is a rumour |
| `retention` | follows the mission (ADR 0055) or the scope's own class | |
| `binding` | per lane and model provider | §8.3 |

**Episodic memory is derived, not written by the agent.** At settlement of a unit (and at the
close of a run), a curated feature `memory.reflect` produces a small structured record: the
objective, what was tried, what worked, what failed, the obligations' dispositions, the cost, and
a handful of lessons, each linked to points. It is written to the mission's or application's
episodic space with `write: derived`. A later mission's `memory.recall` section (§9) or tool
finds it by relevance. This is the part the owner overlooked, and it is the part only Mission
Control can do well, because only Mission Control has the Transcript, the obligations and the
receipts in one place.

**Entity memory** is the kind codebases need: "this repository's tests need the biotech group",
"this schema's authority is the db contract package", "the owner prefers one provider at a time".
It is small, high-value, and today lives in AGENTS.md files that no mission updates.

### 8.3 Bindings (the concept card's table)

| Binding | Instantiation | Fits | Does not fit |
| --- | --- | --- | --- |
| `deep_agents.store_memory` | `StoreBackend` on the existing `AsyncPostgresStore` in the runtime schema, through a `CompositeBackend` route (`/memories/` by convention), namespace from `scope` | semantic, entity, procedural; `read: tool` through the filesystem tools | relevance search needs an embedding index on the Store; episodic needs the derived writer |
| `deep_agents.memory_files` | `MemoryMiddleware` sources | procedural, `read: inject` | anything written at run time |
| `anthropic.memory_tool` | the client-side memory middleware for Claude models | agent-written notes, `read: tool` | provenance and admission are Mission Control's to add |
| `knowledge_services.*` | an admitted catalog capability | semantic and entity *domain* knowledge; the authority for the domain | operational memory about missions themselves |
| `claude_agent_sdk`, `codex`, `cursor` | CLAUDE.md or AGENTS.md and project memory files; a `memory` MCP server | procedural; `read: inject` | episodic; receipts |

The position I would recommend: **do not build a memory engine.** Bind the LangGraph Store with
an embedding index for the operational kinds, keep Knowledge Services as the authority for domain
knowledge, add the derived episodic writer and the provenance and admission rules, and present the
whole thing as one concept card with those bindings. The owner decides whether operational memory
belongs in Mission Control's runtime schema or in Knowledge Services (CO-D11).

---

## 9. Dynamic prompts

### 9.1 What I want

The system prompt an agent sees at model call N should be able to carry what is true at model
call N: which obligations are still open, how much budget remains, what its children are doing,
what the reviewer said, what memory recalled, where it is in the program. Deep Agents has the
seam (`dynamic_prompt` middleware with access to state and the runtime context). The owner's idea
of accumulating current state into the prompt is the right one; my requirement is that it be
*selectable, bounded and recorded*, not a free template.

### 9.2 Prompt sections (proposed `mc.prompt_section.v1`)

A **section** is a card (category *prompting*) with: an id, the state and context it reads, a
token budget, a position (`head`, after the instructions, `tail`), a refresh rule (`every_call`,
`on_change`, `once`), and whether sync children inherit it. The first set:

| Section id | Renders | Reads |
| --- | --- | --- |
| `prompt.mission_position` | "You are stage S3 (cycle 2) of run R; iteration 3 of 6" | context schema |
| `prompt.obligations` | the open obligations, their kinds and schemas, what was already submitted | `mc_obligations` |
| `prompt.budget` | tokens, cost, model calls and wall clock remaining, with the soft threshold | budget channel |
| `prompt.children` | async children and their status; what each owes | `mc_children`, `async_tasks` |
| `prompt.transfer` | what this unit received and from whom, in one paragraph with handles | `mc_transfer`, the packet |
| `prompt.review_feedback` | the last Steering Resolution's riders | review packet |
| `prompt.memory_recall` | the top-k memory items relevant to the objective, with provenance | a memory space (§8) |
| `prompt.standing_answers` | what the coordinator has pre-authorized | §7 |
| `prompt.coordinator_notes` | free text I inject through `add_context`, persisted as a section rather than a message | `mc_notes` |

The manifest selects and orders sections; it may add static text between them; it may not supply
code or templates with logic. The rendered prompt of every model call is **digest-recorded on the
`model_request` frame with the list of section ids and their token counts** (`observe.prompt_render`,
§6.4), so that "what was the agent told at point P" is answerable, a fork from P reproduces it,
and a diff between two points shows what changed in the prompt and not only in the messages.

### 9.3 Across lanes

The section vocabulary is the concept (`concept.prompt`); the binding differs. Deep Agents
renders per model call. The Claude Agent SDK, Codex and Cursor cannot change a system prompt
mid-session, so the binding renders sections at **session generation boundaries** (continuation,
rollover, stage start) into the instruction layer, and anything that must change mid-session
degrades to an `add_context` message, with the receipt saying `emulated: boundary_only`. Hosted
lanes get the sections at launch only. The card says all of this in its binding table, so I never
assume a per-call refresh on a lane that cannot do it.

---

## 10. All the control in the world

What I would want in each phase of my session, for Deep Agents first and for every lane through
the same cards and receipts. *Existing* means it is there today in some form; everything else is
proposed and is placed in the sprint that fits.

| Phase | I want to | Existing | Proposed, and where |
| --- | --- | --- | --- |
| Survey | search cards by any facet; read a concept and its bindings; see the installation's defaults per lane and role; see what is `installed` versus `needs_upgrade` this week | lane describe, catalog search, the surface sheet | cards and the generated workspace (I); `staying-current` (CS-D9) |
| Author | start from a template; select features and sections by id; declare obligations and transfer; declare standing answers and watch conditions; get a **compile explain**: per node, the receipt preview (native, emulated, degraded, unsupported), the graph nodes added, the visibility summary ("2 server-side tools escape approvals"), the cost envelope | compile, preflight, receipts at admission | explain as a compile output (B); standing answers (F); templates (I) |
| Launch | dry-run on the fake lane with recorded transcripts; start with a spend ceiling | T0 and T1 tiers for fixtures | `mission rehearse` over the fixture harness (P) |
| Wait | block on the inbox with kinds; receive positioned wakes; add a watch condition after launch | inbox wait, Watchers, significance kinds | new kinds and positions (F, CS-D5); run-time `watch` (F) |
| Read | the decision log per unit; outputs and inputs at a position; the rendered prompt at a point; a child's Transcript with its parent's point; a diff between two points (prompt, state, files) | transcript, points, state as of, evidence reads | decision log (F); `run outputs/inputs --at` (CS-W5); prompt at point (B); point diff (P) |
| Act | answer a question; re-open one obligation instead of re-running a stage; adjust a child's budget slice; pin or unpin a skill or a section at a boundary; fork from a point *with a configuration patch* (different model, an added feature) and see the receipt of what the fork changed; mutate in policy at a boundary (K17); retire or detach a child; promote an artifact | queue, inject, cancel, fork from a point, add context, human task resolve | `command answer` (F); obligation-targeted interventions (F, R7.2); fork with patch (P); revisions (K17, later) |
| Close | accept or reject against the fulfillment report; promote deliverables; write the episodic record with provenance; see spend per unit and per feature | completion evidence, artifacts | fulfillment reports (OC-1); `memory.reflect` (a memory sprint, CO-D12); per-feature cost attribution (P) |

Two of these deserve a sentence. **Compile explain** is the single most valuable thing for
comprehensibility: before any token is spent I see, per node, exactly what the lane will do with
every line I wrote, in the receipt's words. **Fork with a patch** turns time travel from a
recovery tool into an experiment tool: same point, one variable changed, two Transcripts to diff.

---

## 11. What I do not want

- **Code as configuration.** No middleware import paths, no templates with logic, no scripts
  that run inside the model loop except hook scripts on the neutral vocabulary with receipts.
- **Raw graph writes.** No `update_state` verb. Typed interventions at boundaries, with the point
  they landed at in the receipt.
- **A push stream into my context.** Frames go to the Transcript and dashboards. I get wakes.
- **Polling loops**, mine or an agent's. Watchers and the inbox exist so that nobody sleeps and
  retries.
- **Unlabelled server-side tools.** Every card that escapes the tool node says so in its
  `visibility`, and a mission that requires approvals on a class refuses them at compile.
- **Silent degradation.** If a lane cannot do what I selected, the receipt says `degraded` or
  `unsupported` with a reason, and `requires:` makes it a compile refusal.
- **Bare "profile"** and the other overloads the coordinator-surface proposal bans; one word per
  thing across manifest, CLI, receipt and skill.
- **Memory without provenance**, prompts I cannot read back, and children whose results reach
  their parent before admission.

---

## 12. Decisions, placement and the honest list

### 12.1 Decisions for the owner (recommendation marked)

| ID | Decision | Recommendation |
| --- | --- | --- |
| CO-D1 | Adopt the capability card (`mc.capability_card.v1`, §2.2) as the generated unit of presentation for capabilities, lane features, model tools and concepts | Adopt; generate from the R3 registries; it is sprint I's card schema |
| CO-D2 | The category set (§3.1): R3's six plus prompting, observation, communication, memory, obligations and transfer; persistence renamed "persistence and environment" | Adopt as the primary facet; categories are tags, not folders |
| CO-D3 | `visibility` (`governed`, `observed_only`, `server_side`, `silent`) and `seam` as mandatory card fields; missions that require approvals on a tool class refuse `server_side` cards of that class at compile | Adopt; it is R3.5 made mechanical |
| CO-D4 | Concept cards with generated lane-binding tables for subagents, hooks, memory, compaction, human control, prompts, sandboxes, communication (§4) | Adopt; `implements:` on each lane feature |
| CO-D5 | The coordinator never polls: the inbox and Watchers are the only idle-time channels; new wake kinds and positions per §6.2 | Adopt; F and CS-D5 |
| CO-D6 | Run-time watch conditions authored by the coordinator, compiled into `mc.watchers.v1` with the extended fact roots (§6.3) | Adopt in F after the obligation events exist |
| CO-D7 | The effect-class table for hooks and curated features (§6.4): observe, annotate state, enforce, redirect, prompt; never call back, never write authority | Adopt as the rule sprint B builds against |
| CO-D8 | Observer features as a curated family (`observe.*`), portable as record-mode hook scripts | Adopt; first five in B or F |
| CO-D9 | The coordinator communication tool `mc_coordinator` with `report`, `ask`, `answer_available`, `handoff`; `ask` as a Coordinator Task over the Human Task Service with a durable interrupt; `command answer` as the reply | Adopt; the Deep Agents binding in F, after OC-1; relation to communication obligations as §7.2 |
| CO-D10 | Standing answers, budgeted questions, child routing (§7.2) | Adopt with small defaults |
| CO-D11 | Memory as a catalog capability kind `memory_space` (§8.2); operational memory in Mission Control's runtime Store, domain knowledge stays with Knowledge Services | Adopt the kind; the owner decides the home of operational memory |
| CO-D12 | Episodic memory is derived at settlement by `memory.reflect`, never agent-written; its own short sprint ("M") after OC-2 | Adopt |
| CO-D13 | Prompt sections (§9.2) as the only dynamic-prompt mechanism; selection and ordering, no logic | Adopt; the first four sections in B, the rest with their sources |
| CO-D14 | Record the rendered system prompt (digest, section ids, token counts) on every `model_request` frame | Adopt in B; it costs one field |
| CO-D15 | Compile explain (per node: receipt preview, nodes added, visibility summary, cost envelope) as a compile output | Adopt in B; it is the receipt, earlier |
| CO-D16 | Fork with a configuration patch, receipted | Adopt in P |
| CO-D17 | The decision log projection per unit (§6.5) | Adopt in F |
| CO-D18 | Cross-lane bindings for prompt sections and observer features degrade to boundaries with an explicit receipt, never silently | Adopt as a standing rule |

### 12.2 Where this lands

| Item | Interview round | Sprint |
| --- | --- | --- |
| Cards, categories, facets, concepts (CO-D1..D4) | R3 (sitting II), R8 (sitting III) | B defines, I generates |
| Wake kinds, positions, watch conditions, decision log (CO-D5, D6, D17) | R7 (sitting III) | F |
| Effect classes, observer features (CO-D7, D8) | R3.3 | B, F |
| Communication tool and standing answers (CO-D9, D10) | R2 and R7 | F, after OC-1 |
| Memory (CO-D11, D12) | a new short round, "RM", in sitting III | a new sprint M after OC-2 |
| Prompt sections and prompt recording (CO-D13, D14) | R3 | B |
| Compile explain, fork with patch (CO-D15, D16) | R3, R7 | B, P |

The sprint sequence's parking lot should receive the memory round and sprint M; nothing here
changes the order I → A → OC-1 → II → B.

### 12.3 Honest list

- I did not run anything. Every "existing" claim rests on the cited documents and a grep of
  `src/`: the custom stream is consumed by the recorder, `custom.mc.progress_note` is a frame
  kind, `get_stream_writer` is used by the kernel hook ports and the compaction observer, an
  `AsyncPostgresStore` is opened beside the saver in the runtime schema. I did not verify that
  the Store is bound to any backend today; the surface sheet and the design say it is not.
- `submit_output`, `mission_fetch`, the `mc_*` channels, the Coordinator Task and every card are
  proposed; none exists in `src/`.
- Whether a Deep Agents `interrupt()` raised from inside a tool (the `ask` act) survives the
  Activity-wrapped turn the same way `interrupt_on` does is the same open question the HITL
  binding has (units park `in_doubt` today). CO-D9 depends on that binding landing first.
- The embedding index on the LangGraph Store and its cost were not researched; CO-D11 is a
  direction, not a sized plan.
- The names (`card`, `watch`, `answer`, `mc_coordinator`, `memory_space`, `prompt.*`,
  `observe.*`) are placeholders until the coordinator-surface grammar and the glossary take them
  (CS-D6).
