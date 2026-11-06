---
type: Agent Configuration
title: "Program workspaces and ledgers: kinds, statuses, the one archive, answers and Linear"
description: "How a multi-session program under docs/specs/<program>/ keeps its proposals, general documentation, specs, issues, interview instructions, interview answers and session instructions findable: one LEDGER.md of pointers and progress, a dedicated answers/ structure for interview decisions, finished work moved to the single archive docs/specs/archive/ by docs/tools/program_ledger.py, Linear issues filed forward from 2026-10-23, and the end-of-session checklist."
tags: [mission-control, agents, process, ledger, archive, interview]
---
# Program workspaces and ledgers

A **program** is a folder under `docs/specs/` that several agent sessions work through. Active programs: provider consolidation and the coordinator surface. Its state lives in four places and nowhere else:

| Place | Holds | Edited by |
| --- | --- | --- |
| `LEDGER.md` | One row per document or work item: status, Linear id, next step. It points; it never copies | Every session, in the same commit as the change |
| Live documents (program root, `providers/<lane>/`) | The text a session reads and writes | The session that owns the item |
| `answers/` | One file per interview sitting: the owner's decisions and where each went | The interviewing session |
| `docs/specs/archive/` | Finished programs and finished documents, for the whole repository | `program_ledger.py` only |

What each turn built stays in the program's change ledger (provider consolidation: `providers/deep_agents/CHANGES.md`); `LEDGER.md` links to it.

## Kinds

| Kind (ledger section, id prefix, archive folder) | What it is | Name it |
| --- | --- | --- |
| Proposals (PR, `proposals`) | A design offered for owner decision, including ADR candidates and supplements | `<TOPIC>-PROPOSAL.md`, `<TOPIC>-SUPPLEMENT-<date>.md` |
| General documentation (DOC, `docs`) | Reference that is not a decision: audits, explainers, baselines, provider surfaces, registers | `<TOPIC>-<date>.md` for anything that ages |
| Specs (SP, `specs`) | What to build, in contract terms; and the architecture projection the code is then checked against (modules, signatures, file tree, dependency chain, seams; the `architecture-projection` skill) | `SPEC-<NN>-<topic>.md` or the topic name; projections `<TOPIC>-DESIGN.md` |
| Issues (IS, `issues`) | Work items. The tracker is Linear; the row points to the sprint card or register and records `OVE-n` | rows only |
| Interview instructions (IQ, `interview-instructions`) | How an owner interview runs: rounds, rules, the interviewer prompt | `INTERVIEW-<topic>-<date>.md` |
| Interview answers (IA, `interview-answers`) | The decisions an interview produced | `answers/<TOPIC>-SITTING-<n>-<date>-ANSWERS.md` |
| Session instructions (SE, `sessions`) | The instruction or handoff for one build session | `SESSION-<TASK>.md` |

## Status

`planned` (named, no file yet; the row has no link) → `draft` → `open` (waits on an owner decision) → `accepted` (decided, not built) → `active` (in use or being built) → `done` (complete) → `archived`. `parked` is a side state: the owner paused the item, it stays in place and resumes on request (the ledger header says so); the archive is reserved for completed work.

Archive a document when its work is merged or its decisions are folded into a live document, and no live document needs it as the place to read current facts. A `done` document that many live files cite stays in place until those citations point elsewhere (`TRACING-PROPOSAL.md` is cited from 43 files). Archived files keep their file name, so a bare citation such as "SESSION-STAGE-2 §4b" stays valid. Nothing is deleted.

## The one archive

`docs/specs/archive/` serves every program ([its README](../specs/archive/README.md) is the index).

- A finished document: `archive/<program>/<kind>/<file>.md`, found through the `archived` row of that program's ledger.
- A finished program: `archive/<program>/` with its structure kept, found through the archive README's table.
- It is inert. No test, code path or tool reads it, so anything a test loads (mission manifests) belongs under `tests/fixtures/`.

## Interview answers

An interview leaves two records. The instruction is the instrument; the **answers file** is the record, one per sitting, created with the tool so every one has the same shape:

```text
python docs/tools/program_ledger.py new-answers --topic DEEP-AGENTS --sitting I --interview <instruction.md>
```

It scaffolds `answers/<TOPIC>-SITTING-<n>-<date>-ANSWERS.md` from [the template](templates/interview-answers.template) and prints the ledger row to add. The structure serves three needs:

- **Organization.** One file per sitting, one table of decisions: id, the question, the owner's words, date.
- **Provenance.** *What it changes* is the agent's reading, kept apart from *Answer*, which is the owner's words. The front matter `interview:` links the instruction. Assumptions (asked, not answered) are separate from decisions.
- **Conversion.** Every decision names where it **becomes** (`ADR-NNNN`, `spec <file> §n`, `GLOSSARY <term>`, `OVE-n`, or `none (reason)`) and where it was **folded** (a link, or `n/a`). While `status: open` the table may be incomplete; `status: final` is allowed only when no decision lacks either entry, and `program_ledger.py check` enforces it. The *Conversion checklist* in the file lists the follow-ups: decision logs, ADRs, glossary terms, Linear comments.

Decision ids keep their family prefix (`OC-D4`, `DP-D2`, `HG-D7`). Answers recorded before this structure existed stay where they are, linked from the ledger.

The skill that runs a sitting and fills the file is `grill-with-answers` (`.agents/skills/grill-with-answers/`). An interview held outside any program writes the same template to `.scratch/<topic>/ANSWERS.md`; when its decisions turn out to matter it is moved into a program with `program_ledger.py move` and given a row.

## Rules

1. **Linear, forward only (from 2026-10-23).** Create the `OVE` issue before work on an item starts: project Mission Control, one category label and one state label ([issue-tracker.md](issue-tracker.md), [triage-labels.md](triage-labels.md)), a `## Provenance` section naming the document, section and ADR it comes from. Write the id in the ledger row. Do not back-fill finished work. Claim and handoff comments use the `issue_claim@1` and `issue_handoff@1` shapes in [the fast-track team workspace](../specs/archive/fast-track-2026-10/TEAM-WORKSPACE.md#claim-and-handoff).
2. **One row, one source.** Add the row when you create the document. Change status when the state changes. Put detail in the document or the change ledger and the pointer in the row.
3. **Move with the tool.** `archive <file> --kind <kind> --reason "<why>"` archives one document, `archive-program docs/specs/<program> --reason "<why>"` a whole program, `move <src> <dest>` anything else. All use `git mv`, rewrite every relative link and written path, stamp archived documents, and list code or JSON that still mentions the old path (fix those by hand; checksummed seeds under `packages/` are changed only by a release). Then set the ledger row to `archived`. `--dry-run` shows the plan.
4. **Answers get a file.** After a sitting, summarise the answers as a comment on each Linear issue they decide, set the file to `final` once converted, and link it from the ledger.
5. **Large decision sets use a map.** When a program has dozens of open decisions (D1-D9, DP-D1..14, HG-D1..24), `/wayfinder` keeps them as a map of decision issues in Linear; the ledger row points to the map issue.

## Closing a session

From the repository root, fix what these report:

```text
python docs/tools/program_ledger.py check [--program docs/specs/<program>]
python docs/tools/agents_docs_index.py
python docs/tools/check_links.py
```

The first verifies the ledger, its answers files and the archive against the folder; the second recompiles the index in `AGENTS.md`; the third finds broken links (provider consolidation had three before this convention: two are explained by ledger row PR-05, the third is a stale `NEXT-SESSION.md` link in `CHANGES.md`).
