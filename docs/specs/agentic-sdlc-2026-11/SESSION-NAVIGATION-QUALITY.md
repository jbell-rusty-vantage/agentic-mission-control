---
type: Session Instructions
title: "Session: navigation and retrieval quality design before the Agentic SDLC implementation"
description: "The instruction for the next session (AS-D20): resolve SPEC-01 §12 to high quality, producing an accepted architecture projection NAVIGATION-DESIGN.md (ranking, AGENTS.md block shapes at root and module level, context output, fixture authoring policy, cross-repository navigation, budgets, measurement, skills routing) and the frozen retrieval fixture format, before slice S1 builds the CLI."
tags: [mission-control, agents, process, documentation, sdlc, session]
date: 2026-11-01
status: planned
---

# Session: navigation and retrieval quality

**What remains to reach the goal.** The Agentic SDLC program (SPEC-01) is specified and converted;
its implementation has not started. The owner named navigation as the most critical thing this
program builds and asked for a dedicated session to work it out before full implementation. This
session closes that gap: it turns SPEC-01 §12 (ten open items) into an accepted architecture
projection and a frozen fixture format. The next blocker after it is slice S1, the CLI.

## Read first

1. `SPEC-01-AGENTIC-SDLC.md` §1, §3, §12 and §13.
2. `SDLC-SYSTEM-PROPOSAL-2026-11-01.md` §2 and §3 (the layout and the CLI).
3. `INFORMATION-CATEGORIES-DRAFT-2026-11-01.md` (what the index must group).
4. The two retrieval lineages as evidence, not as designs: Knowledge Services
   `.agent-docs/knowledge.mjs`, `retrieval-benchmark.mjs`, `fixtures/ks-context-v1/`; Mission
   Control `docs/tools/okf_search.py`, `agents_docs_index.py`, `docs/agents/index-notes.toml`.
5. The owner's retrieval audit rubric (eight criteria) in the interview instrument's request.
6. `BellLabs/docs/navigation/RETRIEVAL.md` and `RETRIEVAL-FOLLOWUP-2026-10-15.md` (prior misses).

## Do

The instrument for this session is [IQ-02](INTERVIEW-NAVIGATION-AND-KNOWLEDGE-2026-11-02.md):
its "Before the first question" list is the preparation, its fifteen questions are the interview,
its conversion section names the deliverables. The owner added on 2026-11-01: resolve the
knowledge each codebase represents, determine the state each codebase is in after the recent
major work, give the owner room to state the long-term goals, make infrastructure locations and
access extremely obvious, and bring a best effort at the compressed `AGENTS.md` with its update
rules, thresholds and sidecars (the draft is [DOC-02](AGENTS-MD-GRAMMAR-DRAFT-2026-11-01.md)).
The steps below are the same work in order.

1. Run the baseline audit on Mission Control and Knowledge Services with the eight criteria, scored
   0 to 10 with file-level evidence, into `RETRIEVAL-AUDIT-BASELINE-2026-11.md` (kind docs). Use the
   existing search tools; record every miss as a candidate fixture case.
2. Interview the owner (`grill-with-answers`, Source `ID-1`, family `AS-D21+`) with the fifteen
   questions of IQ-02 (which fold in the ten items of SPEC-01 §12), at most four per batch, after
   the preparation drafts exist so every question is an edit of something concrete.
3. Write `NAVIGATION-DESIGN.md` with `architecture-projection`: the ranking function and field
   weights, the tokenizer, the corpus rule, the `AGENTS.md` root and module block grammars with
   byte budgets and worked examples from Mission Control and Knowledge Services, the `context`
   output schema, the fixture format (`queries.json`, snapshots, `baseline.json`) and the authoring
   policy, cross-repository resolution through `workspace.json`, the skills routing block, and the
   measurement plan tying bench numbers to the audit.
4. Freeze the fixture format and write the first Mission Control fixture set (at least the
   eighteen screening and ten held-out cases the KS set has, over the 66 concepts).
5. Convert the sitting, update the ledger, file the S1 issues' acceptance criteria from the design.

## Done when

`NAVIGATION-DESIGN.md` is `accepted` on the ledger with every §12 item answered in the owner's
words; the four `STATE-<repo>-2026-11.md` inventories, the infrastructure map, the goals charter
and the Mission Control `AGENTS.md` draft are on the ledger; the fixture format is frozen; the
baseline audit scores are recorded; `program_ledger.py check` passes; the handoff names S1 as the
next slice.

## Constraints

Spend within the owner's per-session ceiling; the Cursor adapter is not yet available, so model
work in this session is the session's own harness. Do not start S1.
