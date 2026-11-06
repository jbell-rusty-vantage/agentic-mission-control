---
type: Program Ledger
title: "Coordinator surface ledger: where the packet, the proposal and the sessions stand"
description: "The pointer and progress register of the coordinator-surface program (one language for the mission-control agent skill, missionctl and the HTTP API, a skill tree that represents Mission Control as a workflow and agent cognition system, and the events a live dashboard needs). One row per document or work item; convention in docs/agents/program-workspace.md, verified by docs/tools/program_ledger.py."
tags: [mission-control, coordinator, skills, cli, api, ledger, process]
---

# Coordinator surface ledger

Last reconciled **2026-11-01** (OVE-206 documentation truth pass). Active. The convention, status words and closing checklist are in
[docs/agents/program-workspace.md](../../agents/program-workspace.md); check with
`python docs/tools/program_ledger.py check --program docs/specs/coordinator-surface-2026-10`.

**Next step of the program:** the owner reads the broader proposal. The focused part (inspection, events, wakes and bounded
coordinator content) shipped as WI-19 / OVE-182 and, with the Selection Workspace (`missionctl search`, `workspace check`), is
described in the [coordinator surface concept](../../knowledge/coordinator-surface.md) and
[coordinator attention](../../knowledge/coordinator-attention.md); PR-01's dated scope notice and the
[final per-decision dispositions](../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) govern. The broader grammar, skill-tree and
dashboard redesign is unbuilt and waits behind the Agentic SDLC program; the coordinator's projection proposal (PR-02, moved here from
provider consolidation on 2026-11-01) stays working. No whole-proposal approval or runtime completion is inferred.

**Linear.** From 2026-10-23 every item that will be built gets an `OVE` issue before work starts (rule 1
of the convention). Nothing earlier is back-filled.

Status words: `planned` · `draft` · `open` (waiting for an owner decision) · `accepted` · `active` ·
`parked` · `done` · `archived`.

## Proposals

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| PR-01 | [Coordinator surface proposal (2026-10-22)](PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md) | open | OVE-182 | Focused inspection/events/wakes and bounded content are finalized in Sprint OC; CS-D1..14 dispositions preserved. Broader grammar/bundle/API proposals remain unadopted; F20-19 extra preflight is unselected. No whole-proposal approval or implementation claim. |
| PR-02 | [The coordinator's projection: cards, categories, observation, communication tool, memory, dynamic prompts (CO-D1..18)](COORDINATOR-PROJECTION-PROPOSAL-2026-10-23.md) | draft | - | Written 2026-10-23 from the coordinator agent's stance; decides nothing. Moved here from the provider consolidation program on 2026-11-01 (its PR-07). Owner reads, then CO-D1..18 are decided. |

## Specs

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| SP-01 | [Coordinator surface packet: the vision, today's surfaces, the critique, the representation principles](README.md) | active | - | The packet the proposal answers. Its §7 questions are carried by the proposal and the interview. |

## Issues

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| IS-01 | Work breakdown of the proposal (skill tree, `missionctl` grammar, dashboard events) | planned | - | File one `OVE` issue per accepted piece after round R8; record the ids here. |

## Interview instructions

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| IQ-01 | [Round R8: the retrieval surface and the Mission Control skill](../archive/provider-consolidation-2026-10/interview-instructions/OWNER-INTERVIEW-2026-10-22.md#r8-the-retrieval-surface-and-the-mission-control-skill) | done | - | Retired 2026-11-01 with the sitting I track; the round R8 questions live in the archived owner interview and the proposal's questions. |

## Interview answers

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| IA-01 | Answers to round R8 | planned | - | Created with `program_ledger.py new-answers` when the sitting runs; link it here. |

## Session instructions

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| SE-01 | [Next session: critique the skill and missionctl, propose the representation](../archive/coordinator-surface-2026-10/sessions/NEXT-SESSION.md) | archived | - | Ran 2026-10-22 and produced PR-01. Archived 2026-10-23. |
