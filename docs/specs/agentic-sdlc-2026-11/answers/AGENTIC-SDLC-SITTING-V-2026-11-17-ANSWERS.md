---
type: Interview Answers
title: "AGENTIC-SDLC, sitting V: the owner's answers"
description: "The owner's go of 2026-11-17 to implement the Mission Control test-suite review (canonical test doubles, a tests/support layer, step 1 deletions, the missing Deep Agents proofs), with Opus 5.5 agents only; the four open choices of the review taken at their recommended defaults."
tags: [mission-control, interview, answers]
id: AS-S5
family: AS
harness_session: claude-code:be854e8a-7732-4f82-ab93-13e494df34b6
interview: ../test-suite-review-2026-11-17/RECOMMENDATION.md
sitting: "V"
date: 2026-11-17
status: final
---

# AGENTIC-SDLC, sitting V: answers

Instruction: `RECOMMENDATION.md` (front matter `interview:`). Recorded by the interviewing agent on
2026-11-17. **Status `open`** while the sitting runs; set `final` when every decision below has a
**Becomes** and a **Folded** entry, which `program_ledger.py check` then enforces.

How to fill it: one row per decision, in the order asked. Quote the owner's words in **Answer**; put
the agent's reading in **What it changes**, never in **Answer**. A decision the owner did not answer
goes under *Assumptions*, not in the table.

## Decisions

| ID | Source | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AS-D50 | - | Implement the test-suite review (RECOMMENDATION.md steps 0-6)? | "Alright let's go. Implement it." | 2026-11-17 | Steps 0-6 run now: defects fixed, step 1 deletions, builders moved to `tests/support/`, doubles collapsed to the canonical set, internal mocks replaced, the missing proofs G1-G5 written, merges and renames | OVE-238 | [RECOMMENDATION.md](../test-suite-review-2026-11-17/RECOMMENDATION.md#5-the-order-to-do-it-in) |
| AS-D51 | - | Which agents may do the work? | "Only use Opus 5.5 agents ." | 2026-11-17 | Every delegated agent of this program runs on Opus 5.5 (`model: opus`) | none (session rule) | n/a |

`Source`: the idea `ID-n` the sitting serves, or `-`.
`Becomes`: `ADR-NNNN`, `spec <file> §n`, `GLOSSARY <term>`, `OVE-n`, or `none (reason)`.
`Folded`: the link to the document edited to carry the decision, or `n/a`.

## Mental model restated

What the system does after these answers, in the owner's terms: a manifest fragment, a command, what
they will see. Record the owner's correction if they gave one.

## Assumptions (asked, not answered)

| ID | Question | Assumption taken | Risk if wrong |
| --- | --- | --- | --- |
| AS-A1 | Decision 1: the Qualia and AI Engineer paid-fixture cluster | Recommended default: move the drivers to `experiments/knowledge_loop/` (scripts keep importing them), delete their self-tests | A wanted self-test is lost; recoverable from git |
| AS-A2 | Decision 2: dead `src` with its tests | Recommended default: delete together (terminal-evidence adoption, linked adoption, Stage 3 recovery services, the Agent Server Stage 3 client, Block C if no deploy uses it) | A planned route loses its code; recoverable from git |
| AS-A3 | Decision 3: paid drills no make target runs | Recommended default: delete the 12; keep one owner-run drill per lane in `make lane-qualify LIVE=1`; wire `deep_agents/test_agent_configuration_live.py` to a target | A drill the owner still runs by hand disappears |
| AS-A4 | Decision 4: report-source foundation fixture | Recommended default: delete its tests with `scripts/report_source_*.py` | The W1/W2 foundation fixture is wanted again |

## Parking lot

Items raised that belong to another round or sitting, with the round that takes them.

## Conversion checklist

- [x] Decisions folded into the decision logs of the specification and supplements (links in **Folded**)
- [ ] ADR candidates written for decisions with a lasting reason
- [ ] Glossary terms added through `domain-modeling`
- [x] Linear: a comment on each decided issue; an issue filed for each accepted piece of work, ids in **Becomes**
- [x] Ledger: this file's row and the instruction's row updated
