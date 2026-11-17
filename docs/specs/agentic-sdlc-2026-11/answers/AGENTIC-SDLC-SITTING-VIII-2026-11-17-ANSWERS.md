---
type: Interview Answers
title: "AGENTIC-SDLC, sitting VIII: the owner's answers"
description: "The owner's direction of 2026-11-17 that finishing the AI Engineer schema development process and fully migrating it comes before the Mission Control feature-map session, because the missing official schema is what is causing problems for Mission Control, research and ingestion."
tags: [mission-control, interview, answers, ai-engineer, schema]
id: AS-S8
family: AS
harness_session: claude-code:b6a402b2-f9e7-48f9-bbe7-764d5e829252
interview: ../SESSION-FEATURE-MAPS-AND-RUNNERS.md#goal
sitting: "VIII"
date: 2026-11-17
status: final
---

# AGENTIC-SDLC, sitting VIII: answers

Given while the feature-map session (SE-02, OVE-240) was being written. The schema work itself runs under the AI
Engineer review workspace's own protocol (recommend, John approves, trial on the lab, determine, promote, record), whose
records live in `BellLabs/platform/ai-engineer-research-2026-11-02/10-review-workspace/`; this row only records the
change of order on the Mission Control side.

## Decisions

| ID | Source | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AS-D66 | - | What comes before the feature-map session? | "Slightly new plan. It doesn't upend this one but it probably defers it .  We need to finish the ai engineer schema development process and fully migrate it so we have the official schema to use in mission control and for research and ingestion. That is what is really causing problems" | 2026-11-17 | SE-02 and OVE-240 are deferred, not cancelled; the next session finishes the AI Engineer schema and migrates it to the official target so Mission Control, research and ingestion bind to one schema | OVE-240 (deferred) | [LEDGER SE-02](../LEDGER.md#sessions) |

## Mental model restated

The feature maps and runners wait. The AI Engineer schema is finished under its own process and migrated, and then
Mission Control and Knowledge Services use that one official schema for research and ingestion.

## Assumptions (asked, not answered)

| ID | Question | Assumption taken | Risk if wrong |
| --- | --- | --- | --- |

## Parking lot

- SE-02 resumes after the schema is official (its §3 answers must be re-verified then).

## Conversion checklist

- [x] Linear: OVE-240 deferral comment
- [x] Ledger: this file's row; SE-02 set to parked
