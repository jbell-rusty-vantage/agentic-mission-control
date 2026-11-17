---
type: Interview Answers
title: "AGENTIC-SDLC, sitting VI: the owner's answers"
description: "The owner's direction of 2026-11-17 after the dollar-budget finding: hold dollar budgets with no placeholder enforcement, put context-window optimization of every agent instance first, and move from Mission Control to Knowledge Services and then the AI Engineer service features and schema, running real missions on one provider."
tags: [mission-control, interview, answers, budgets, context]
id: AS-S6
family: AS
harness_session: claude-code:b6a402b2-f9e7-48f9-bbe7-764d5e829252
interview: ../SPEC-02-PROVENANCE-CHAIN.md#decisions
sitting: "VI"
date: 2026-11-17
status: final
---

# AGENTIC-SDLC, sitting VI: answers

A direction given in the same session as [sitting IV](AGENTIC-SDLC-SITTING-IV-2026-11-17-ANSWERS.md), after the agent
showed how budgets are computed per provider (each lane's `LaneUsage` declaration; only Cursor charges the run's
currency dimension; `budget.usd` is a cap nothing enforces on the reference lane). Ids start at AS-D60: sitting V
(the test-suite review, another session) is still open and keeps AS-D52..AS-D59 free.

## Decisions

| ID | Source | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AS-D60 | - | Make the template's dollar budget bind now (one rule for every lane)? | "Exactly as I suspected so let's hold off on that. Also I don't want some placeholder enforcement live. When we do it we will do it well and put it together properly." | 2026-11-17 | No dollar enforcement is added, partial or otherwise; tokens, turns and tool calls stay the enforced limits; the design starts later with an interview. OVE-229 is the template launch only | OVE-229 (rescoped) | n/a (Linear) |
| AS-D61 | - | What matters more than budgets now? | "Optimizing the context window of every agent instance from coordinator through agents within missions is more important." | 2026-11-17 | A measured, per-instance-kind context baseline (coordinator, mission nodes) comes first, Deep Agents lane first, then an owner interview before changes ship | OVE-239 | n/a (Linear) |
| AS-D62 | - | What comes after Mission Control? | "I want to move on to work on knowledge-services and then get us back to developing the ai engineer service features and schema so we can get out of this and start building all the features AND start running real missions AND get to the other agent providers. We don't need every agent provider fully functional to run research as long as we have one technically." | 2026-11-17 | Sequence: Knowledge Services next, then the AI Engineer service features and schema, then real missions; Deep Agents alone is enough to run research; other providers follow | none (sequence; carried by the ledger's next step and the handoff) | [LEDGER](../LEDGER.md) |

## Mental model restated

Mission Control stops here for now with its tooling in place. Dollar budgets wait for a proper design. The next
Mission Control work, when it resumes, is measuring and trimming what every agent carries in its context. The next
sessions are Knowledge Services, then the AI Engineer service, then real research missions on Deep Agents.

## Assumptions (asked, not answered)

| ID | Question | Assumption taken | Risk if wrong |
| --- | --- | --- | --- |

## Parking lot

- Dollar budgets across lanes (AS-D60): design interview when the owner reopens it.

## Conversion checklist

- [x] Linear: OVE-229 rescoped, OVE-239 filed
- [x] Ledger: this file's row and the next step
