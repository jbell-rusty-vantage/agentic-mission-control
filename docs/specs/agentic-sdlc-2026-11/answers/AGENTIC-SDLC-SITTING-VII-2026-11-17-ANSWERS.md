---
type: Interview Answers
title: "AGENTIC-SDLC, sitting VII: the owner's answers"
description: "The owner's go of 2026-11-17 to complete Mission Control's feature maps and ./dev runners, test them, and make their evaluation good enough to serve as a feedback loop; the eleven operability questions that define the first task fixtures; and the deletion of the local platform/agentic-sdlc checkout."
tags: [mission-control, interview, answers, feature-maps, dev-cli, evaluation]
id: AS-S7
family: AS
harness_session: claude-code:b6a402b2-f9e7-48f9-bbe7-764d5e829252
interview: ../SPEC-02-PROVENANCE-CHAIN.md#decisions
sitting: "VII"
date: 2026-11-17
status: final
---

# AGENTIC-SDLC, sitting VII: answers

A direction given in the same session as [sitting VI](AGENTIC-SDLC-SITTING-VI-2026-11-17-ANSWERS.md). The design
sources are the 2026-11-17 handoff §3.1-§3.3 (`./dev`, feature maps, runtime verification) and the 2026-11-15 trust-pyramid
research on Lauren Tan's talk and her pstack plugin (`platform/ai-engineer-research-2026-11-02/14-slop-talk-research/`),
both outside this repository. AS-D52..AS-D59 stay free for the open sitting V.

## Decisions

| ID | Source | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AS-D63 | - | What is the next Mission Control work? | "It's time to fully complete the feature map and the runners for mission-control and then test it and then make that evaluation good enough to be used as a feedback loop. I think it's quite obvious what we need." | 2026-11-17 | One session builds `features/` for Mission Control, the `./dev` groups the features need (`where`, `stack`, `feature`, `drive`, `evidence`), their tests, and an operability evaluation whose score changes when docs or tooling change | OVE-240 | [SESSION-FEATURE-MAPS-AND-RUNNERS](../SESSION-FEATURE-MAPS-AND-RUNNERS.md) |
| AS-D64 | - | Which questions must an agent be able to answer from the runners and feature maps? | "How do you start the apis . How do you start the mcps. How do you use the mission-control cli (coordinator agent). How do use the cli runners for mission-control for [fill in the blanks here] . Where are the workflows . Where are the accepted provider configs. How does the coordinator agent search for workflow and agent \"profiles\" with mcp . Where are the schema workspace materialization algorithms and how do you run them ? How to access supabase per application . How do you run the agent server (langgraph for async subagent) ." | 2026-11-17 | These are the evaluation's first task fixtures (Q1-Q11 in the session instruction); each one is answered by a feature map, reachable from `AGENTS.md` and `./dev`, and checked by running its command | OVE-240 | [SESSION-FEATURE-MAPS-AND-RUNNERS §3](../SESSION-FEATURE-MAPS-AND-RUNNERS.md#questions) |
| AS-D65 | - | What happens to `platform/agentic-sdlc`? | "I deleted agentic-sdlc" | 2026-11-17 | There is no upstream tooling repository: Mission Control's `docs/tools/trace.py`, `./dev` and templates are the copy other repos take; the `AGENTS.md` ideas pointer, `grill-with-answers` §1a and SPEC-02's "moves upstream" lines are corrected | spec SPEC-02-PROVENANCE-CHAIN.md §4 | [SPEC-02 §4](../SPEC-02-PROVENANCE-CHAIN.md#trace) |

## Mental model restated

An agent new to Mission Control reads a short `AGENTS.md`, runs `./dev where <question>` or `./dev feature show <id>`,
and gets the exact command, the code paths and the proof. `./dev drive <feature>` runs it and `./dev evidence check`
says whether it worked. An evaluation asks the eleven questions (and more as features land) and scores the answers, so
a change to the docs or the runners shows up as a number.

## Assumptions (asked, not answered)

| ID | Question | Assumption taken | Risk if wrong |
| --- | --- | --- | --- |
| AS-A11 | Is Mission Control's copy of the shared tooling canonical now that `agentic-sdlc` is deleted? | Yes; Knowledge Services and the AI Engineer repos copy it when they adopt it | Low: a later shared home can take it back |
| AS-A12 | The GitHub repository `jbell-rusty-vantage/agentic-sdlc` (still public) | Left as it is; archiving or deleting it is the owner's call | None until he decides |
| AS-A13 | "[fill in the blanks here]" in Q4 | The blanks are every `./dev` group a feature needs: status, doctor, check, test, trace, where, stack, feature, drive, evidence | The owner meant a specific list |

## Parking lot

- Where unshaped ideas go now that `agentic-sdlc/ideas/` is gone (asked in the next session's decision list).

## Conversion checklist

- [x] Linear: OVE-240 filed
- [x] Session instruction written and linked
- [x] Ledger: this file's row and the session row
