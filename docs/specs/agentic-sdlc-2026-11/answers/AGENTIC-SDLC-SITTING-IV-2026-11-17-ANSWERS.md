---
type: Interview Answers
title: "AGENTIC-SDLC, sitting IV: the owner's answers"
description: "The owner's direction of 2026-11-17 for reconciling Linear: the Mission Control web target (chat threads to a spawned mission, its real-time view and complete search through mission outputs), the mature Deep Agents and Temporal macro-scheduler mechanics applied to every provider with special care for coding harnesses and coding outputs, and a precise, lean reconciliation of the Mission Control and Mission Control web issues."
tags: [mission-control, interview, answers, linear]
id: AS-S4
family: AS
harness_session: claude-code:b6a402b2-f9e7-48f9-bbe7-764d5e829252
interview: ../SPEC-02-PROVENANCE-CHAIN.md#decisions
sitting: "IV"
date: 2026-11-17
status: final
---

# AGENTIC-SDLC, sitting IV: answers

A direction given in the same session as [sitting III](AGENTIC-SDLC-SITTING-III-2026-11-17-ANSWERS.md), not a question
round: the owner's request, verbatim, is split into the three decisions it contains. The reconciliation landed the same day
(an Opus 5.5 subagent, 2026-11-17); each row names its issues.

## Decisions

| ID | Source | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AS-D47 | - | What is Mission Control web for? | "We know for mission-control-web that we want the chat threads -> spawned mission with the real time view of a mission and complete search through outputs of missions." | 2026-11-17 | The web app's first product thread: a chat thread that spawns a mission, the live mission view, and search across every mission's outputs; each piece names the MC surface it consumes | OVE-233 (parent), OVE-234, OVE-235, OVE-236; blocked by OVE-229, OVE-232, OVE-231 | n/a (Linear) |
| AS-D48 | - | Which providers get the mature Deep Agents and Temporal macro-scheduler mechanics? | "The more mature deep agents + workflow temporal macro scheduler will be applied to ALL agent providers with special care for coding agent harnesses and coding outputs." | 2026-11-17 | Lifecycle control, inspection, context transfer and output obligation fulfilment are generalized from the Deep Agents reference lane to every lane; coding-agent harnesses and their coding outputs get their own thread | OVE-224 (parent), OVE-226, OVE-227, OVE-228; lane issues OVE-70, OVE-71, OVE-72, OVE-81, OVE-82 rewritten | n/a (Linear) |
| AS-D49 | - | How is Linear reconciled for Mission Control and Mission Control web? | "fix up our current linear project and issues for mission-control and mission-control-web. [...] You must be very keen about resolving where we are at mission-control so this can be precise. Don't over produce." | 2026-11-17 | Every open issue is dispositioned against live source (implemented / tested / integrated / qualified); new issues are few and carry `Goal:` and the fixed Provenance keys | OVE-226..OVE-236 created; 74 → 50 open MC issues (done, duplicate or canceled with a reason; none deleted); OVE-229, OVE-230 | n/a (Linear) |

## Mental model restated

Mission Control web becomes the place where a chat starts a mission, the mission is watched live, and everything missions
produced can be searched. Under it, every provider lane gets what the Deep Agents lane already has, coding agents first in
care. Linear says precisely what is built and what remains.

## Assumptions (asked, not answered)

| ID | Question | Assumption taken | Risk if wrong |
| --- | --- | --- | --- |

## Parking lot

## Conversion checklist

- [x] Linear: issues created or updated by the reconciliation, ids in **Becomes**
- [x] Ledger: this file's row
