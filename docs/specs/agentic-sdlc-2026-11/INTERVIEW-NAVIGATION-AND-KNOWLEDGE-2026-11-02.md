---
type: Interview Instructions
title: "Sitting II instrument: codebase state, the knowledge each codebase represents, long-term goals, obvious infrastructure, the compressed AGENTS.md"
description: "The instrument for the second owner interview of the Agentic SDLC program (run with Opus 5.5): what the interviewing agent must gather and draft before asking (state inventory per repository, infrastructure map, AGENTS.md draft, concept lists), the fifteen questions in five rounds with the recommendation each starts from, and where every answer becomes canonical (NAVIGATION-DESIGN.md, STATE inventories, INFRASTRUCTURE.md, the goals charters, SPEC-01 amendments)."
tags: [mission-control, agents, process, documentation, sdlc, interview]
date: 2026-11-02
status: planned
idea: ID-1
---

# Sitting II: state, knowledge, goals, infrastructure, AGENTS.md

Family `AS-D21` onward; Source `ID-1`. Open the record first:

```text
python docs/tools/program_ledger.py new-answers --topic AGENTIC-SDLC --sitting II \
    --interview docs/specs/agentic-sdlc-2026-11/INTERVIEW-NAVIGATION-AND-KNOWLEDGE-2026-11-02.md \
    --program docs/specs/agentic-sdlc-2026-11
```

The owner's words for this sitting: "The next session needs to ask me more questions because we
have to resolve the knowledge we want to represent in each codebase and also determine the state
that the codebase is in because we have completed some major work (in progress towards our
goals). I also want a chance to state the long term goals. I also want infrastructure locations
and access to be EXTREMELY OBVIOUS. I also want a best effort at the compressed AGENTS.md and rules
for updating, maybe changing thresholds, sidecar files and stuff like that."

## Before the first question (facts are the agent's job)

Gather and draft these, cite `file:line`, and put the drafts in the program as `draft` rows:

1. **State inventory per repository** (`STATE-<repo>-2026-11.md`, kind docs): for Mission
   Control, Knowledge Services, Biotech Knowledge Services, ai-engineer-db-contract, from the live
   `sprint-oc` branch: what the last three programs or sprints built (Sprint OC W0 released and W1
   open, the provenance sprint OVE-204 slices, the Selection Workspace, KS `knowledge.read_intent`,
   BKS schema v2.2.0 pin), each labelled implemented / tested / integrated / qualified with the
   proof path; the programs still `active` in each ledger; the dirty files; the version numbers
   (component, MC release, KS, BKS SDL). Read `NEXT-SESSION.md`, the provenance `REPORT.md`, the
   ledgers, `CHANGES.md` files and `git log` since 2026-10-20. Do not infer qualification from a
   README.
2. **Infrastructure map draft** (`INFRASTRUCTURE-MAP-DRAFT-2026-11.md`): the table of
   `AGENTS-MD-GRAMMAR-DRAFT-2026-11-01.md` §4 filled for the workspace and each repository from
   `docs/navigation/DATA-PLANES-AND-CREDENTIALS.md`, every `.env` variable **name** (never a
   value), the remotes, the MCP servers in `.mcp.json`, the CLIs on the host (`claude`, `agent`,
   `uv`, `node`, `pnpm`, `gh`), Docker and WSL2 services, and the cloud environments that exist.
   Mark unknown or stale entries (the Aura hosts `9c6755c0`, `e40f2c21`) as such.
3. **Compressed AGENTS.md draft for Mission Control** following the grammar draft §1 and §2,
   built by hand from today's `AGENTS.md`, with its byte count per section, so the owner reviews a
   real file, not a rule.
4. **Concept lists per codebase**, taken from `INFORMATION-CATEGORIES-DRAFT-2026-11-01.md`, each
   line marked covered / partial / missing against the live tree and with the `questions[0]` it
   would carry, so Q3 to Q6 are edits, not authoring.
5. The eight-criterion **baseline retrieval audit** of Mission Control and Knowledge Services
   (scores with file-level evidence) as `RETRIEVAL-AUDIT-BASELINE-2026-11.md`.

Spend: the owner's per-session ceiling; this is reading and drafting, no paid model runs.

## The fifteen questions, in five rounds

Batches of at most four; recommendation first; "yes" accepts it; record the owner's words.

### Round 1: the state the codebases are in

**Q1 What counts as current truth.** The state inventories list recent work with four labels.
Which label makes a fact eligible for a knowledge concept, and how is work below that line
represented? Recommendation: `implemented` and `tested` facts may be concepts, stated as such;
`integrated` and `qualified` are claims a concept may only make with the proof path cited;
anything below `implemented` lives in a program document and is linked from the `decisions`
concept as open.

**Q2 Which programs stay working, which promote now.** Provider consolidation (Sprint OC, W1
open), coordinator surface, fault tolerance, the provenance sprint. Which of their documents are
promoted into concepts in slices S2 and S3, which stay in their ledgers, which are archived?
Recommendation: promote what W0 and the provenance sprint built; keep W1 and the coordinator
proposal as working; archive the Run 2 finish material.

**Q3 The knowledge Mission Control represents.** The prepared list (nine categories, 66 existing
concepts plus the five proposed: coordinator-surface, database-component,
documentation-retrieval-fixtures, decisions, goals). Accept, add, rename, drop? Recommendation:
accept, and merge the Deep Agents lane concepts into one `deep-agents` group under `execution`.

**Q4 The knowledge Knowledge Services represents.** The prepared list (11 existing plus
knowledge-operation, schema-ownership, retrieval-benchmark, operations, decisions, goals).
Recommendation: accept, and add `applications-and-bindings` under `boundaries` for the AI
Engineer and Biotech bindings.

### Round 2: the domains and the depth

**Q5 The knowledge Biotech Knowledge Services represents.** The prepared nine new concepts.
Recommendation: accept; `schema-releases` and `ingestion-and-admission` first because every
Biotech mission depends on them.

**Q6 The knowledge AI Engineer represents.** Per repository (db-contract, pre-research, meta) and
the deferred two. Recommendation: accept DOC-01's defaults; the domain charter in meta carries the
learner-app absence explicitly.

**Q7 Depth and placement.** How much "how the code realizes it" goes in a concept (160 lines) vs a
module `AGENTS.md` block vs the glossary; whether a concept may embed a code excerpt.
Recommendation: a concept explains and cites, never pastes code; module blocks carry entrypoints
and tests; the glossary carries the term only.

### Round 3: long-term goals (the owner speaks)

**Q8 The long-term goals, in your words.** Open question with a scaffold the agent fills from the
answer into four `goals` concepts (Mission Control, Knowledge Services, AI Engineer, Biotech):
what each domain is for in three years; the product surfaces in order (agent skills + CLI, MCP
servers, APIs, web, mobile); the recurring research programs (developing-economy and research
trends; cures; longevity protocols, treatments and machines) and what "human-collaborated,
evidence-backed report" means operationally; the first paying or public surface. No
recommendation; the agent restates the model after the answer.

**Q9 Order and first domain.** Which surface ships first and in which domain (Biotech diagnostics
or AI Engineer), and how Mission Control's Deep Agents focus serves it. Recommendation: agent
skills + CLI first, Biotech first, because its schema, graph and skills already exist.

**Q10 How goals steer the SDLC.** Should every `OVE` issue name the goal it serves (a `Goal:`
line resolved against the goals concept), and should `trace` print it? Recommendation: yes; the
owner reporting directive already asks every report to lead with the gap to the nearest goal.

### Round 4: infrastructure, extremely obvious

**Q11 One infrastructure surface.** `docs/INFRASTRUCTURE.md` per repository generated from
`.sdlc/infrastructure.json`, the same table at the workspace root, linked from line 3 of every
`AGENTS.md`, checked against the `.env` names used in code. Accept the table shape of the grammar
draft §4 and the check? Recommendation: accept; retire `DATA-PLANES-AND-CREDENTIALS.md` into it.

**Q12 Access and credential placement.** Consolidate the `.env` variable names now (the deferred
§3 of the data-planes registry: one name per data plane, e.g. `AIENG_DB_URL`, `BIOTECH_DB_URL`)
and adopt one `.secrets/` plan, or keep today's names and only map them? Recommendation:
consolidate in slice S2 to S3, because the map is only obvious when the names say which plane.

### Round 5: the compressed AGENTS.md and its rules

**Q13 Budgets and gates.** Hand-written ≤ 4 KiB, generated block ≤ 8 KiB, module block ≤ 2 KiB,
whole file ≤ 14 KiB, over budget fails `check`; the concept cap stays 160 lines; a category
collapses above twelve concepts. Recommendation: accept, with the Mission Control draft as the
proof that 29 KiB fits in 13.

**Q14 Block content and order; sidecars and update rules.** The grammar draft §1 to §3 (what the
block holds and in which order; module blocks two levels deep) and §5 to §6 (which files are
hand-maintained, who regenerates and when, thresholds change only by ADR plus a `hold` PR).
Recommendation: accept; `index-notes.toml` folds into `config.json`.

**Q15 Retrieval design in one block.** Ranking (BM25 with the KS field weights as the seed;
identifier tokenization; glossary terms and ADR titles as first-class documents; active-program
specs opt-in), the `context` output (KS shape plus category and glossary terms), the fixture
authoring policy (the author writes three questions per concept; the audit adds misses; baselines
move only with a concept change in the same PR), cross-repository navigation (pointer concepts
plus `search --workspace`). Accept as a block or name the exceptions.

## Conversion

Answers become: `NAVIGATION-DESIGN.md` (Q7, Q13 to Q15, through `architecture-projection`), the
four `STATE-<repo>-2026-11.md` inventories (Q1, Q2), amendments to DOC-01 and SPEC-01 §5 (Q3 to
Q6), the four `goals` concepts and a `GOALS-CHARTER-2026-11.md` in the program (Q8 to Q10),
`INFRASTRUCTURE.md` plus `infrastructure.json` shape and a consolidation issue (Q11, Q12), and the
`AGENTS-MD-GRAMMAR` draft promoted to a section of `NAVIGATION-DESIGN.md` (Q13, Q14). Every
decision is a row with **Source** `ID-1`; the sitting closes `final` with `program_ledger.py
check` green, and S1 (OVE-207) receives its acceptance criteria from the design.
