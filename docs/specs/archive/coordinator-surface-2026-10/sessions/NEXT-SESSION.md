---
type: Sprint Disposition
title: "Instruction for the next Claude Code session: critique the mission-control skill family and missionctl against the real system, propose how to represent it, and implement the first piece"
description: "The paste-ready instruction for the coordinator-surface session (2026-10-21): orient on the packet, critique the agent skill and the CLI and API semantics with citations, propose the representation (one vocabulary, workflow structure, cognitive configuration per lane, protocols and tools, compaction and continuation, lifecycle streaming, knowledge and software work), confirm the decisions CS-1..4 with the owner, then implement the first piece for Goal Directed and Stage Graph on Deep Agents with only the Deep Agents features that exist."
tags: [mission-control, coordinator, skills, cli, handoff]
status: archived
archived: 2026-10-23
archived_from: NEXT-SESSION.md
archived_reason: "ran 2026-10-22; produced the coordinator surface proposal"
---

> **Archived 2026-10-23** (ran 2026-10-22; produced the coordinator surface proposal). Kept for provenance; see the [ledger](../../../coordinator-surface-2026-10/LEDGER.md) for what replaced it.

# Next session: the coordinator surface

Copy the text below into the session's first message.

---

This session is special: before building anything, you critique how Mission Control presents
itself to the coordinator agents that drive it, and you propose how it should. Work in
`platform/mission-control` on `main` (the P1 turn 4 work is on the working tree, uncommitted;
commit and push only when I say). Follow
`docs/specs/provider-consolidation-2026-10/PROCESS.md` §1 (orient, audit, cross-reference, plan,
**confirm with me**, build, prove, document, hand off) and §2 (discriminators and routers).

**Read first, in this order**

1. `docs/specs/coordinator-surface-2026-10/README.md` (the packet: my vision in my words, what
   the surfaces say today, the Deep Agents feature inventory with its honest status, the
   critique questions, the representation principles, the decisions CS-1..4).
2. `skills/mission-control/SKILL.md` and the five bundles (`mission-control-author` with its
   `references/manifest-cheatsheet.md`, `-catalog`, `-observe`, `-intervene`, `-compose`) and
   the `mc-cognition-*` bundles; ADR 0033.
3. `src/mission_control/interfaces/cli/main.py` (the parsers), `docs/knowledge/interfaces.md`,
   `docs/knowledge/authoring.md`, `docs/knowledge/mission-manifest.md`,
   `docs/knowledge/lanes-and-harness.md`, `docs/knowledge/mission-stream.md`,
   `docs/knowledge/execution.md`, `docs/knowledge/recovery.md`, `GLOSSARY.md`.
4. The manifest contract (`domain/authoring/manifest.py`, `manifest_v2.py`,
   `provider_options.py`), the subagent vocabulary (`domain/capabilities/subagents.py`), the
   Deep Agents lane adapter (`application/authoring/lanes/deep_agents.py`) and describe
   (`application/execution/harness/describe.py`), the materialization receipt
   (`domain/execution/materialization_receipt.py`).
5. The P1 ledgers `docs/specs/provider-consolidation-2026-10/providers/deep_agents/CHANGES.md`
   (turns 2–4) for what exists on Deep Agents and what does not.

**Then**

1. Restate the goal in one paragraph in my words and confirm it with me. My words: *the agent
   skill and the CLI and API semantics must represent BellLabs' real system: advanced Goal
   Directed and Stage Graph workflows with advanced cognitive configurations on top industry
   frameworks, direct provider access and access to many external tools (MCP servers, agent
   skills, A2A in the future), context compaction and continuation, lifecycle publisher and
   subscriber streaming of granular agent activity, and real knowledge work and real software
   work. Start with Deep Agents and only the Deep Agents features we actually have; document
   the larger vision; implement piece by piece. We reveal details only where it matters and
   where it is helpful, and we hide details where they should be hidden: adding an MCP server
   is one lane-neutral act, and there is hopefully no provider-specific detail that helps.*

2. **Critique** (packet §4): answer the nine questions with `file:line` citations and write
   `docs/specs/coordinator-surface-2026-10/CRITIQUE.md` as described there. Label every finding
   general or deep_agents. Do not soften: where the skill is prose about a system it does not
   show, say so.

3. **Propose** (`PROPOSAL.md` in the same folder): the vocabulary (the system's nouns, with the
   glossary as authority), the bundle layout, the CLI and API nouns and verbs to add or change,
   how a node's cognitive configuration is seeded and read back per lane (Deep Agents fully;
   the other lanes as pointers to their describes), how compaction and continuation and the
   lifecycle stream are presented, how knowledge and software missions differ, and the first
   piece to implement. Keep the proposal implementable in slices; name the first slice's
   modules, tests and ledger row.

4. **Ask me** CS-1..5 in one round, as options with your recommendation, and confirm the
   mental model: a sentence like *"after this, a coordinator runs `missionctl node describe RUN
   NODE` and sees the node's lane, model, tools, MCP servers, skills, subagents, provider
   options and the receipt that says what became native"* that I can accept or correct.

5. **Implement the first piece** I confirm, as deep modules behind the existing routers
   (nothing checks the lane outside a router), with its unit test and, where it touches a run,
   a T0 proof on the offline stack (`tests/acceptance/mission_control/test_cognition_points.py`
   shows the harness). Update the skill bundle it affects (and `make skills-manifest`).

6. **Document**: `docs/specs/coordinator-surface-2026-10/CHANGES.md` (the ledger of this line,
   same shape as the P1 ledger: scope, change, finished part, proof), the knowledge concepts
   touched, `python docs/tools/validate_okf.py`, `python docs/tools/agents_docs_index.py`, the
   next `NEXT-SESSION.md`; commit and push when I say.

7. End with: one finished part to read (in reading order), the sequence it sits in, and how I
   use it (a command and what I will see).

**Scope guard**: the coordinator surface only. Not this session: an evidence-backed report
production service, provider documentation research missions, output obligations and final
artifact collection for knowledge work (open elsewhere), and the P1 turn 5 context-transfer
work (`docs/specs/archive/provider-consolidation-2026-10/specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md`, queued
after this session). Claim only Deep Agents features that exist (packet §3); everything else is
an explicit `Availability` pointer.

**Host facts**: Windows 11, about 15 GB RAM; one heavy job at a time. The disposable Postgres
17 container is `mc-ft-disposable-pg17` (`docker start` it; its admin DSN is built from the
container's `POSTGRES_PASSWORD`, never printed; release 1.4.3 is applied per stack by the test
fixture). Kill stale `langgraph_cli dev` and `temporal-sdk-python … server start-dev` processes
after an interrupted stack. Credentials are cited by name only.
