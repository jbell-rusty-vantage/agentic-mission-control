---
type: Interview Answers
title: "AGENTIC-SDLC, sitting IX: the owner's answers"
description: "The decisions the owner took in sitting IX of SPEC-02-PROVENANCE-CHAIN.md on 2026-11-18, each with its id, the owner's words, what it changes, what it becomes (ADR, spec section, glossary term, Linear issue) and where it was folded in. Open while the sitting runs; final when every decision has a destination."
tags: [mission-control, interview, answers]
id: AS-S9
family: AS
harness_session: claude-code:b6a98e84-f9c8-4287-8b60-a9ea1585f3ac
interview: ../SPEC-02-PROVENANCE-CHAIN.md
sitting: "IX"
date: 2026-11-18
status: open
---

# AGENTIC-SDLC, sitting IX: answers

Instruction: `SPEC-02-PROVENANCE-CHAIN.md` (front matter `interview:`). Recorded by the interviewing agent on
2026-11-18. **Status `open`** while the sitting runs; set `final` when every decision below has a
**Becomes** and a **Folded** entry, which `program_ledger.py check` then enforces.

Context: the owner read the Mission Control checkpoint page (private Artifact, 2026-11-17) and the agent's answer on
where the AI Engineer and Mission Control schemas stand (remote `aieng-db` read-only: AIDB 0.6.0, 187 migrations, head
`20261031010000`, against local 0.10.0 with 203; Mission Control component 1.13.0 against local 1.16.0). The agent
proposed eight steps (1 push and green, 2 one kit per repo, 3 schema close-out, 4 remote migration, 5 the schema
mutation procedure, 6 the schema navigation workspace, 7 real missions, 8 Mission Control web).

How to fill it: one row per decision, in the order asked. Quote the owner's words in **Answer**; put
the agent's reading in **What it changes**, never in **Answer**. A decision the owner did not answer
goes under *Assumptions*, not in the table.

## Decisions

| ID | Source | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AS-D67 | - | Do the Mission Control tenets apply to the other codebases? | "The same tenants apply to the other codebases. interview -> commit provenance. cli runners. feature map. okf documentation (slim and purposeful) . Database access and knowledge and slim purposeful AGENTS.md WITH retrieval evaluation testing for feedback loops." | 2026-11-18 | One kit, copied from Mission Control (canonical since AS-D65), goes to Knowledge Services, the AIDB contract and the AI Engineer service: provenance trace and hook, `./dev` runners, a feature map, slim OKF docs, the data-plane registry and `./dev db`, an `AGENTS.md` of at most 60 lines, and a retrieval bench in each gate | spec SPEC-03-REPO-KIT.md §1; OVE-243 | [SPEC-03](../SPEC-03-REPO-KIT.md#parts) |
| AS-D68 | - | In what order? | "I say let's do our best to integrate our strategies and set up and document. Then let's return to ai engineer schema development. Fly through that. Encode how to mutate the schema when and if we do change it once migrated . Then we run real missions on that schema with the most mature deep agents. We can move to mission control web soon therafter" and, on the eight-step proposal, "Yes that sounds good." | 2026-11-18 | Steps 1-8 as proposed: push and green CI, the kit, schema close-out, migration to `aieng-db`, the written mutation procedure, the schema navigation workspace, real Deep Agents missions on the remote through `missionctl` and MCP, then Mission Control web. Consistent with AS-D66: the schema still comes before the feature-map session | OVE-243 (steps 1-2); schema brief NEXT-SESSION-OFFICIAL-SCHEMA.md (steps 3-8) | [SPEC-03](../SPEC-03-REPO-KIT.md#parts) |
| AS-D69 | - | Who runs the schema development? | "I need to conduct the schema development process with Fable 5.2 and make sure it is exactly as I desire and envision." | 2026-11-18 | Steps 3-6 run in a session the owner conducts on Fable 5.2, under the review workspace protocol. This session completes steps 1-2 and prepares 3-8. AS-D51 (Opus 5.5 agents only) stays the rule for the test-suite program and does not bind the schema session | | |
| AS-D70 | - | Where does Mission Control web live on GitHub? | "mission-control-web remote https://github.com/jbell-rusty-vantage/mission-control-web" | 2026-11-18 | `platform/mission-control-web` gets that `origin` and its first push | | |

`Source`: the idea `ID-n` the sitting serves, or `-`.
`Becomes`: `ADR-NNNN`, `spec <file> §n`, `GLOSSARY <term>`, `OVE-n`, or `none (reason)`.
`Folded`: the link to the document edited to carry the decision, or `n/a`.

## Mental model restated

What the system does after these answers, in the owner's terms: a manifest fragment, a command, what
they will see. Record the owner's correction if they gave one.

## Assumptions (asked, not answered)

| ID | Question | Assumption taken | Risk if wrong |
| --- | --- | --- | --- |
| A1 | Where do unshaped ideas go now that `ideas/` is gone? | Not answered. Nothing moves; the schema brief and kit carry the question | `ID-1` stays a dangling hub in the trace |
| A2 | Wipe and reinstall `aieng-db`, or upgrade it in place? | Not answered here. Step 4 still needs the owner's explicit go at S3 of the schema brief, after the current remote contents are listed | A destructive reinstall without a listing loses data |

## Parking lot

Items raised that belong to another round or sitting, with the round that takes them.

## Conversion checklist

- [ ] Decisions folded into the decision logs of the specification and supplements (links in **Folded**)
- [ ] ADR candidates written for decisions with a lasting reason
- [ ] Glossary terms added through `domain-modeling`
- [ ] Linear: a comment on each decided issue; an issue filed for each accepted piece of work, ids in **Becomes**
- [ ] Ledger: this file's row and the instruction's row updated
