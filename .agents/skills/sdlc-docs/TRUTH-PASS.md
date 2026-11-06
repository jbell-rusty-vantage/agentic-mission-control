# Truth pass: one codebase

Proven on Mission Control (2026-11-01; screening recall@3 0.48 → 1.00). The owner's method:
"concentrate on one codebase at a time and do exploration looking for current state, documentation
that is stale or that hasn't been integrated and is good and worth keeping or reformulating, and then
do the documentation and then move on to the next codebase."

## 1. Baseline

Write the fixtures first (FORMATS.md): at least 18 screening and 10 held-out query cases over the
concepts, the misses of any retrieval audit, and 5-10 task cases from real near-term work (each with
the concepts, modules, research notes and hidden facts it needs). Run the bench and save
`baseline-before.json`. Record the commit.

## 2. Explore in parallel (read-only agents, one report each)

| Report | Scope |
| --- | --- |
| A | any original spec pack or design folder the concepts were drawn from: what is propagated, partial, not propagated, superseded |
| B | every concept against the code: fresh, minor drift, stale, contradicted, with `path:line` |
| C | program folders, ledgers, ADR statuses, the archive |
| D | every other Markdown surface: READMEs, guides, nested AGENTS.md, tracked private folders |

Also look outside the repository for loose documents about it (folders that are not git repositories).
Each report ends with owner questions, each with a recommendation, and ordered execution steps.

Triage vocabulary for every document: **keep**, **fold into** `<concept>`, **new concept**
`<name, category>`, **ADR** (new or status change), **glossary term**, **stays working** (program),
**archive**, **delete** (fully superseded, nothing unique), **untrack**, **research note**,
**idea** (a product idea, to the ideas workspace).

## 3. Owner round

Merge the reports' questions into one round: the few that need the owner (authority, taxonomy,
the lane or component the goal depends on) asked separately, everything else as one block. Ask the
owner to state the system in their own words; the concept map is built around that model.

## 4. Rewrite

- **Phase A**, parallel agents with disjoint concept sets (for example workflows, runtime, platform).
  They do not commit (the pre-commit hook stashes unstaged work); they append renames to a register
  and report. The coordinator commits each agent's files separately.
- **Phase B**, one agent alone in the repository: ADR statuses, deletions, link rewrites from the
  register, archive moves, the generated AGENTS.md and module guides, fixtures, the bench after,
  and a code-issues list (defects found are filed, not fixed, in a documentation pass).

## 5. Done when

Every concept has the format and no contradicted claim; every harvested item has a home; the
generators and checks pass; the bench is recorded before and after with every critical case listed
pass or fail; the remaining failures are named with their cause (documentation or tooling).
