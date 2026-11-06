---
type: Concept
category: goals
title: Mission Control goals
description: What Mission Control and Knowledge Services are for, in the owner's words, stated as outcomes, thresholds and architectural requirements with stable anchors (the Goal line of an issue resolves here); the unbuilt goals (one local and cloud session, per-policy mutation, provider batch, the human review loop, the dashboard control plane, deployment) each with what exists today and pointers to the AI Engineer and Biotech goals their own repositories carry.
tags: [mission-control, goals, charter, requirements, knowledge-services, roadmap]
aliases: [charter, owner goal, long-term goals, Goal line, nearest goal]
questions:
  - What is Mission Control for, and what is the nearest goal?
  - Which goals are not built and what exists toward each?
  - Which anchor does an issue's Goal line cite?
  - Where are the AI Engineer and Biotech goals?
updated: 2026-11-01
---

# Mission Control goals

Goals are stated as **outcomes, thresholds and architectural requirements, never dates** (owner: "We talk in terms of
compute, tokens and architectural requirements"). Each heading below is a stable anchor: a new `OVE` issue carries
`Goal: platform/mission-control/goals#<anchor>` (AS-D23) and the check resolves it here. Nothing under a goal is claimed
built unless it says so with a proof path; the concepts it links hold the evidence ([qualification](qualification.md)).

**Nearest active goal** (BellLabs `AGENTS.md`, owner directive 2026-10-29): complete workflow and agent configuration logic as
fully as possible, with Deep Agents as the provider and provider extension inside deep modules behind provider-neutral common
contracts; other providers follow the same adapter boundaries. The live checkpoint and its remaining acceptance criteria are
[NEXT-SESSION](../specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md).

## Goal: Mission Control service

Owner, 2026-11-01 (Q8, verbatim): "Mission control and knowledge services are well known knowledge and coding services built on
top of frontier agent frameworks and best practices with llm agents. People use it to create evidence backed reports. People buy
the ability to create reports. Mission control will be loved for it's granular environment control where agent sessions can move
to and fro local and cloud, transferring files, context and switching runtimes as needed. People love the granular control and
intervention possibility of the mission. We are mainly known as a knowledge producer with deep research missions. We are also
known as a great way to put all your coding agent services under one roof and spawn big code work with a mission control agent
skill in their agent platform of choice."

And on the major goal (MC context, verbatim): "The goal of bringing together these powerful agent platforms into a robust
controllable missions and supplying this as a real service is the major goal."

Requirements that follow: one scheduler over every provider lifecycle ([mission control](mission-control.md)); read and write of
mission state snapshots with fork, queue, inject, interrupt ([interventions](interventions.md)); the surfaces
([coordinator surface](coordinator-surface.md)); evidence-backed output contracts ([output contracts](output-contracts.md)).
Built: the scheduling, control and output machinery for Deep Agents, integrated on disposable targets; qualified: W0 only.

## Goal: provider-native macro scheduler

Owner, 2026-11-06: Mission Control uses each agent framework's own mechanics inside a Temporal macro scheduler so that more
agents do more together; for Deep Agents that means LangGraph checkpoints give the fine-grained state inside each scheduled
turn. Direct provider APIs (Cursor local and cloud, Anthropic Managed Agents, the OpenAI Agents API, later Codex and Claude Code)
go into Mission Control **without degrading them, and should be enhanced by it**. The mechanics built for those lanes on
2026-11-05 are to be critiqued against that bar. The product exists when four things work as envisioned on every lane:
**lifecycle control, inspection, context transfer and output obligation fulfillment**.

Interventions (owner, same day) are two, maybe three, kinds, each carrying **context**: a combination of text, images, MCP
servers, agent skills and sandbox materializations, where text can reference a file loaded into the sandbox.
- **Queue context:** delivered at the next boundary.
- **Steer with context:** into the running turn; a gentle injection is preferred over interrupt and inject, and either is
  acceptable.

Evidence: [iteration 3](../specs/provider-consolidation-2026-10/sprint-oc/experiments/ITER-3-2026-11-06.md),
[interventions](interventions.md), [cross-provider control](cross-provider-control.md).

## Goal: Knowledge Services service

The shared knowledge capability Mission Control is "fed by" and feeds: evidence-backed reports whose assertions carry source
attribution and human and agent judgement (Q8: "Evidence assertions, source attribution with human and agent judgement VERY
IMPORTANT"; AS-D22 makes it a cross-domain invariant). Requirements: verification, exact use decisions and review before official
use ([trusted judgment](trusted-judgment.md)); governed domain writes through application bindings
([knowledge services](knowledge-services.md), [applications](applications.md)). Built: gateway, assessment and native writes
integrated on AI Engineer's disposable database; qualified: no (W1 open). The repository's own goals live in `platform/knowledge-services`.

## Goal: workflow mechanics completely known

Owner (MC context, verbatim): "The mechanics of stage graph, goal directed, parallel swarm, evaluator optimizer and linked workflows
at the scheduling, output contract obligation, context transfer and agent runtime and capability configuration should be COMPLETELY
KNOWN." Threshold: an agent with no context reaches the correct current fact for any of those systems at those four levels in one or
two hops, measured by [documentation retrieval fixtures](documentation-retrieval-fixtures.md); Deep Agents is the reference
representation (`deep-agents-lane`, `agent-configuration`). Concepts: [workflow systems](workflow-systems.md).

## Goal: local-cloud one session

Requirement (Q8 and MC context): sessions "move to and fro local and cloud, transferring files, context and switching runtimes",
"local <-> cloud in one session across providers where possible". Today a local and a cloud split exists and movement is not built.
Architecture requirements and the proof matrix: [deployment](deployment.md); mechanics it reuses: [precise fork](precise-fork.md),
[environments](environments.md), [recovery](recovery.md).

## Goal: per-policy mutation

Requirement: mutate a running workflow per policy ("change a workflow mid workflow"). Not built; today forks, queued and injected
instructions and successor revisions only ([revisions](revisions.md)).

## Goal: provider batch

Requirement: a mission makes Anthropic and OpenAI batch requests, and a workflow waits durably on the output and continues. Not
built; a written proposal and its evidence are in the [proposals program](../specs/proposals-2026-10/LEDGER.md) ([provider batch](provider-batch.md)).

## Goal: human review loop

Requirement: mission output reaches the owner, who can review and provide feedback, then continue, reject with feedback and redo, or
start new. Human Gates and request-changes remediation exist; the loop is designed only as a proposal, the
[review gates and steering supplement](../specs/proposals-2026-10/HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md), which [human gates](human-gates.md) compares with what is built.

## Goal: dashboard control plane

Requirement: a control plane over the MCP server, skills with the CLI, and the API that renders a mission live and controls it. No
dashboard exists; the event gaps it would need are listed in [coordinator surface](coordinator-surface.md); the control-plane
contracts are proposed in the [next-stage design](../specs/proposals-2026-10/MISSION-CONTROL-NEXT-STAGE-CONTRACT-DESIGN-2026-10-16.md).

## Goal: deployment

Requirement: Mission Control and Knowledge Services supplied as a real service. Deployment is at proposal stage; a Vercel ingress edge
is up and liveness-checked ([deployment](deployment.md), [signal ingress](signal-ingress.md)).

## Goal: catalog workspace

Requirement (owner, AS-D38): a **Catalog Workspace**, a generated read-only filesystem that renders the
catalog (workflow types, lanes and providers with their lifecycles and describe matrices, models,
capabilities, sandbox profiles, configuration items, worked examples, task pages), pinned to a release and
mounted into a sandboxed agent's Workspace, navigated the way the AI Engineer schema workspace is (a start
page, an index, a search index, at most four reads to an answer). It is for agents *using* Mission Control
from a sandbox, distinct from this codebase documentation and additional to the MCP tools and `missionctl`.
Not built; the [Selection Workspace](selection-workspace.md) is the built API it would share registries with.

## Goal: applications fed by missions

Mission Control and Knowledge Services are the main focus; schema optimization and service-specific features come after, and the
application features "are fed by missions" (Q8). Their goals are carried by their own repositories; pointers only:

- **AI Engineer** (`aiengineer/`): a course platform fed by recurring deep research and content workloads (system courses that update
  with history, student-built courses through long-running missions, multi-modal artifacts, mastery tracking, skills + CLI + MCP + API
  + web/mobile); first course Agent Engineering; the financial and corporate knowledge feature set is a later AI Engineer feature set.
- **Biotech** (`biotech/`): the knowledge graph of the biotech ecosystem as domain slices with entity thresholds, evidence assertions
  and source attribution; the high-level rundown is `biotech/BellLabs/index.md`.
- **Source of both**: [answers file Q8](../specs/agentic-sdlc-2026-11/answers/AGENTIC-SDLC-SITTING-II-2026-11-02-ANSWERS.md); placement
  in [applications](applications.md).

## Citations

- Proposals behind the unbuilt goals: [proposals ledger](../specs/proposals-2026-10/LEDGER.md) (provider batch, human review loop, next-stage
  contracts) and the [spec-pack product ideas](../specs/proposals-2026-10/SPEC-PACK-IDEAS-2026-11.md).
- Owner words: [answers file, Q8 verbatim and MC context verbatim](../specs/agentic-sdlc-2026-11/answers/AGENTIC-SDLC-SITTING-II-2026-11-02-ANSWERS.md)
  (AS-D22, AS-D23, AS-D33).
- Directive: `BellLabs/AGENTS.md`, [AGENTS.md](../../AGENTS.md),
  [REFACTOR-PLAN section 1](../specs/agentic-sdlc-2026-11/truth-pass/mission-control/REFACTOR-PLAN.md).
- Checkpoint: [NEXT-SESSION](../specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md),
  [deployment roadmap](../specs/provider-consolidation-2026-10/sprint-oc/CLOUD-ENVIRONMENTS-AND-DEEP-AGENTS-DEPLOYMENT-2026-10-31.md).
