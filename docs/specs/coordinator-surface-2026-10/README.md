---
type: Specification
title: "Coordinator surface: making the agent skill, the CLI and the API represent what Mission Control is (advanced workflows with advanced cognitive configuration on industry frameworks, direct provider and tool access, compaction and continuation, lifecycle streaming, real knowledge and software work), starting with Goal Directed and Stage Graph on Deep Agents"
description: "The packet for the session that critiques the mission-control skill family and missionctl against the real system and starts representing it piece by piece. Written 2026-10-21 by the owner's brief: the vision in the owner's words, what the skill and CLI say today, the Deep Agents feature inventory with its honest status, the critique the next agent must deliver, the representation principles, the decisions to ask and the first piece to implement. Scope is the coordinator surface only."
tags: [mission-control, coordinator, skills, cli, api, deep-agents, representation, program]
---

# Coordinator surface: represent the real system

**Status: packet for the next agent session (2026-10-21).** It starts a line of work that is
distributed progressively through the application while functionality keeps landing. The first
session critiques and proposes; it implements the first piece only after the owner confirms.

## 1. The vision, in the owner's words

Mission Control is an advanced workflow control system. It composes powerful workflow
architectures (Goal Directed, Stage Graph, and the others the workflow types describe) with
cutting-edge agent protocols (MCP servers, agent skills, A2A in the future), context compaction
and continuation behaviour, lifecycle publisher-subscriber handlers that stream granular agent
workflow activity, and, most importantly, **real knowledge work and real software work**. It
supports the top industry frameworks (Deep Agents first, Anthropic Managed Agents, the Claude
and Codex and Cursor lanes) and gives direct provider access and access to many external tools.

Coordinator agents drive it through an agent skill and `missionctl`. Those two surfaces must
represent that system: not prose about workflows, but a precise way to seed each provider's
cognitive configuration inside a workflow structure (for example, a Deep Agents node inside a
Stage Graph stage with the todo-list middleware that only Deep Agents has), to choose the
tools and protocols a node reaches, to set compaction and continuation behaviour, and to
observe and intervene through the lifecycle stream. The guidance evolves with the providers,
so an agent with a training cutoff must read it from the system, never recall it.

We start with Goal Directed and Stage Graph on Deep Agents, with **only the Deep Agents
features that actually exist**, document the larger vision, and implement piece by piece.

**Out of scope for this line of work**: an evidence-backed report production service (the
owner wrote that for another service), output obligations and final artifact collection for
knowledge work (open elsewhere; see §6), provider documentation research missions.

## 2. What the surfaces say today (audited 2026-10-21)

### 2.1 The skill family (`skills/`, ADR 0033)

| Bundle | Lines | What it teaches | Stale or thin against the real system |
| --- | --- | --- | --- |
| `mission-control` (router) | short | scope, env, the route table | routes by task (author, catalog, observe, intervene, compose); says nothing about *what kind of system* the agent is driving: workflow families, cognitive configuration, lanes and their native forms |
| `mission-control-author` | ~100 + cheatsheet | interview → manifest → compile → submit → start | lane list is `deep_agents, cursor_local, cursor_cloud` (nine profiles exist, ADR 0050); `agents:`, `hooks:`, `plugins:` in one sentence; no `provider_options` (turn 2), no subagent `kind`/`capabilities: inherit \| seeded`/`seeds` (turn 3), no `continuation`, no `requires`, no cognition profiles, no `governors.transfers` (K02); the cheatsheet is the only manifest reference |
| `mission-control-catalog` | 87 | search, inspect, pin, publish | `--host deep_agents` appears once; nothing on which kinds each lane materializes natively (the describe, `subagents.fields`) |
| `mission-control-observe` | 97 | wait, inspect, transcript, watchers | no cognition points, no `state-as-of`, no lifecycle stream (Socket.IO) semantics, no per-lane frame vocabulary |
| `mission-control-intervene` | 96 | queue, inject, cancel, snapshot, fork, reconcile | per-lane delivery semantics are there (good); no fork from a point (`cognitive_seed`), no `run points` as the coordinate to act on |
| `mission-control-compose` | 70 | chains | — |
| `mc-cognition-*` (research, ingest, tdd, pr, code-review, diagnosing-bugs, knowledge-services, cite-and-verify) | 1 paragraph each | a cognition profile's prose | prose only; nothing about the provider-specific configuration a profile should seed (middleware, subagents, skills, tools, compaction) |

### 2.2 `missionctl` (`interfaces/cli/main.py`)

```text
token | preflight | setup | prereq
run      inspect admit snapshot reconcile start fork transcript frames list search checkpoint points state-as-of
command  send list queue inject cancel
mission  schema compile submit start
chain    inspect
subscribe (create list close) | events watch | wait | inbox
catalog  list components resolve search discover inspect pin render publish
lane     list describe async-graphs
```

What it reveals: runs, commands, missions, chains, subscriptions, the catalog, lanes. What it
hides: the workflow family as a first-class thing (`stage` and `iteration` are query filters on
`run points`, not nouns), the cognitive configuration of a node (there is no `missionctl node
describe RUN NODE` showing the sealed binding, its receipt, its middleware, subagents, tools
and compaction policy), the lifecycle stream (Socket.IO is reachable only as a socket), and
the provider's native lifecycle (threads, checkpoints, sessions) except through `points`.

### 2.3 The HTTP and MCP surfaces

HTTP mirrors the CLI (`/v1/applications/{app}/...`: runs, commands, snapshots, forks, points,
transcript, frames, lanes, catalog, missions, chains, subscriptions, inbox, human tasks). MCP
exposes `mission_run_*` (start, inspect, list, search, transcript, fork, points, state_as_of),
manifest, catalog, chain, human task and inbox tools. The lane describe (`GET .../lanes/{p}`)
is the one place the system states what a lane does natively; nothing else exposes a node's
resolved cognitive configuration or the materialization receipt.

## 3. Deep Agents: the features that exist (the only ones the first representation may claim)

From the lane describe, the materialization receipt and the P1 ledgers (turns 2–4):

| Shared item | Deep Agents today | Status |
| --- | --- | --- |
| Instructions | `system_prompt` from node `instruction` + operating contract | native |
| Model | pinned model component (OpenAI factory only; no installation default, D5 open) | native, narrow |
| Tools (pinned, schema-digested) | in-process `BaseTool`s | native |
| MCP servers (stdio, remote) with tool subsets and credentials | `MultiServerMCPClient` | native |
| Skills | bundle by digest mounted under `/skills` | native |
| Subagents | `sync` children `inherit \| seeded` (prompt, model, tools, skills, MCP, state slices, budget); `async` children on the Agent Server (fixed technical child until WP-S3) | native; async degraded |
| Provider options (`provider_options.deep_agents`) | sandbox backend, filesystem permissions, summarization trigger and keep window, state and context packs, async subagents, agent server profile | native (typed registry) |
| Sandbox | `state`, `docker` (read-only, no network), `langsmith`; no kits, no `config:` values | partial |
| Compaction | `ObservedSummarizationMiddleware` (frames `before/after_compaction`); trigger from worker settings, manifest `continuation` ignored | observed, not authorable |
| Continuation / rollover | Goal Loop session rollover at the iteration boundary from the handoff packet; cap authorable (`governors.transfers`, K02); mid-iteration transfer not on this lane (K03) | partial |
| Context Packet | `/inputs/**`, `.mission/context.md`, `.mission/inputs.json` seeded before the first model call | native |
| Time travel | cognition points, `state-as-of` at R3, fork from a point (`cognitive_seed`) | native (turn 4) |
| Interventions | queue (boundary), inject (`cancel_and_replace`, points mark it), immediate cancel (Stop Fence), pause at tool gate | native |
| Lifecycle stream | provider frames (LangGraph steps, tool calls, subagent frames, compaction, usage) on Socket.IO and the transcript | native; no `point_ref` on events yet |
| Usage | tokens settled per turn; cost estimated, never computed | partial |
| **Todo list middleware** | the `todos` state channel is reserved (`contracts.py:396`) but the middleware is not configurable from a manifest or profile | **unsupported today** (the owner's example; a candidate first provider-specific piece) |
| Hooks and plugins from manifests, memory channel, `interrupt_on` → Human Task, env kits, `config:` values | — | unsupported or deferred (WP-3, WP-5, K19) |

The representation must say **native, degraded, unsupported** per item in the lane's own
words (the receipt and `subagents.fields` already do), never imply more.

## 4. The critique the next agent delivers

Read the surfaces in §2 and the system behind them (the knowledge concepts, the manifest
contract, the lane describe, the turn 2–4 ledgers), then answer, with `file:line` citations:

1. **Vocabulary.** Does the skill family speak the system's own nouns (mission, run, workflow
   family, stage, iteration, unit, generation, point, lane profile, node, cognition profile,
   capability kinds, packet, receipt)? List every place a coordinator must guess a noun the
   system already has, and every noun the skill invents that the system does not.
2. **Workflow structure.** Can a coordinator, from the skill alone, write a Stage Graph with a
   dependent stage, a declared wait and a cycle policy, and a Goal Loop with a verifier,
   rollover cap and iteration governors, and know what each node receives? Name the gaps.
3. **Cognitive configuration.** Can a coordinator seed a Deep Agents node with a model, MCP
   servers with tool subsets, skills, sync and async subagents (inherit or seeded), provider
   options (sandbox, summarization), and read back what was materialized (the receipt)? Where
   does the skill stop short of the manifest contract and the catalog? Where would the
   todo-list middleware go once it exists (profile field, `provider_options.deep_agents`, or a
   catalog middleware kind)?
4. **Protocols and tools.** How does the skill present MCP servers, agent skills, pinned tools
   and the future A2A as the node's reach? Is adding one of them a single lane-neutral act,
   with provider specifics hidden unless a receipt reports a loss? Is "direct provider access"
   (the lane's native form, the Agent Server, the provider's own session) visible where it
   helps a decision and hidden where it does not?
5. **Compaction and continuation.** What does the skill promise (`request_continuation`,
   `continuation` block) versus what the lane does (observed compaction, boundary rollover)?
6. **Lifecycle streaming.** Is the Socket.IO stream, the frame vocabulary per lane, the
   transcript and the coordinator inbox presented as one lifecycle, with the points as the
   coordinate to jump to? What would a coordinator need to subscribe and act?
7. **Knowledge work and software work.** Does the skill distinguish a knowledge mission (a
   research directory, knowledge workspaces, ADR 0048) from a software mission (worktrees,
   branches, outputs), and say what each lane materializes for them?
8. **CLI and API semantics.** Which nouns and verbs are missing or misplaced (proposal: a
   `node` noun with `describe`, the family as a noun, `stream` as a verb, `lane describe`
   promoted into authoring); which existing commands should be renamed, grouped or documented
   differently; what the OpenAPI already says that the skill should point to instead of
   restating.
9. **Honesty.** Where does the skill claim something the receipt would report `degraded` or
   `unsupported` on Deep Agents? Every such line gets an `Availability` or a per-lane note.
10. **Value of each detail.** For every detail the surfaces show today and every detail the
    proposal adds, state whether it passes the value test of §5 (it changes what the
    coordinator writes, chooses or does) or should be hidden; list the provider-specific
    details that can be removed from the coordinator's view entirely.

Deliver the critique as `CRITIQUE.md` in this folder: one table per question, each row a
finding with its citation and a proposed representation (a skill sentence, a CLI noun or verb,
an API field), labelled **general** (every lane) or **deep_agents**.

## 5. Representation principles (apply when proposing)

- **Reveal where it matters, hide where it should be hidden (owner directive, 2026-10-21).**
  Every detail the skill, the CLI or the API shows must pass a value test: it changes what the
  coordinator writes, chooses or does. Everything else stays behind the surface. The worked
  example is adding an MCP server: a coordinator declares it once, lane-neutrally
  (`capabilities[kind=mcp_server]` with a tool subset and a credential ref), and the system
  materializes it natively on every lane; nothing provider-specific is surfaced for that
  unless a lane's receipt reports a loss, and then only the loss and its reason. The owner's
  expectation is that for most items there is no helpful provider-specific detail at all; a
  provider-specific surface (a `provider_options` key, a profile override) exists only where
  the provider has a capability the neutral contract cannot express and the coordinator
  gains something by setting it. The critique must apply this test to every finding: "show
  it" needs a reason; "hide it" is the default.
- **One vocabulary, the system's.** The skill, the CLI, the HTTP and MCP surfaces and the
  knowledge concepts use the same nouns; the glossary is the authority.
- **Reveal the structure, not the prose.** A coordinator seeds a node's cognition through
  typed manifest fields and catalog pins; the skill shows the fields and the pins, the
  compiler's blockers and warnings, and the receipt that proves what became native.
- **Provider-specific under discriminated containers** (PROCESS §2.2): `provider_options`,
  `provider_overrides`, `lane_environments`; the skill names the container per lane and
  points to the lane describe for the per-field verdict.
- **Honest per item.** `native`, `degraded`, `unsupported`, `unqualified` are the only words;
  an item the lane cannot do is a refusal when required and a documented loss otherwise.
- **Timely by construction.** Framework facts (versions, middleware, protocols) live in the
  lane describe, the receipts and the provider fact sheets (`providers/<lane>/AUDIT.md`), not in
  skill prose; the skill tells the coordinator to read them.
- **Start with what exists.** The first representation covers Goal Directed and Stage Graph
  on Deep Agents with §3's native rows; every other lane and item is an explicit pointer.

## 6. Related work this line does not own

- Output obligations, final artifact collection and task completion for knowledge work
  (completion concept "Specified only", K01, ADR 0048 output channels): a separate line; the
  owner notes that knowledge work should be versioned too (custody by digest exists; branches
  for knowledge workspaces are proposed).
- The provider consolidation program (P1 turn 5 context transfer is queued after this session;
  `docs/specs/archive/provider-consolidation-2026-10/specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md`).
- Any evidence-backed report production service.

## 7. Decisions the next session asks

| ID | Question | Recommendation |
| --- | --- | --- |
| CS-1 | Where the system's self-description lives: extend the lane describe (`mc.lane_describe.v2`) with the cognitive configuration matrix, or a new `mc.node_configuration` read (`missionctl node describe`) over the sealed binding and receipt | both: describe for the declaration, node read for the resolved run |
| CS-2 | The skill's shape: keep the five task bundles and add a `mission-control-cognition` bundle (how to seed a node per lane), or restructure around workflow family × lane | add the bundle; restructure later |
| CS-3 | The first provider-specific piece to implement: the Deep Agents todo-list middleware as a profile or provider option, or the `node describe` read | the read first (it makes every later piece visible), then the todo middleware |
| CS-4 | CLI nouns: introduce `node` and `stream`, keep `run points` under `run` | yes |
| CS-5 | The value test's boundary: which provider-specific details stay visible to a coordinator at all (candidates: the sandbox backend, the summarization trigger, subagent placement) and which are hidden behind the neutral contract and the receipt | hide by default; keep only what changes a coordinator's choice, named per item |

## 8. The session's order

Orient (this packet, the skill family, the CLI, the ledgers) → audit and critique (§4) →
proposal (`PROPOSAL.md`: the vocabulary, the bundle layout, the CLI and API changes, the
first piece) → **confirm with the owner** (CS-1..4) → implement the first piece behind the
existing routers with its test and ledger row → document (`CHANGES.md` here, the knowledge
concepts, the docs index) → hand off (`NEXT-SESSION.md`).
