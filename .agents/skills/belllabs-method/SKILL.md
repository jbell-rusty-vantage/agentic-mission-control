---
name: belllabs-method
description: How work is done in this repository, end to end - the documentation surfaces (OKF knowledge, GLOSSARY and ADRs, program ledgers, AGENTS.md, provider supplements, skills), canonical versus working documents, the session loop, and which skill runs each phase (interview, domain model, architecture projection, research, prototype, spec, tickets, TDD, review, PR, documentation, retro). Use at the start of a session in platform/mission-control, when deciding where a decision, answer, plan, research note or explanation belongs, before starting an interview, spec, sprint, prototype or research, at session close, or when asked how we work.
---

# The BellLabs method (Mission Control)

Matt Pocock's engineering flow, the Open Knowledge Format bundle under `docs/knowledge/` and the
compiled index in `AGENTS.md` are one system here. This skill is the map of that system: what runs
when, and what each phase leaves behind. The reference tables live in
[documentation-surfaces.md](../../../docs/agents/documentation-surfaces.md) (where a fact goes,
canonical versus working, promotion) and [program-workspace.md](../../../docs/agents/program-workspace.md)
(ledgers, kinds, statuses, the archive, answers files). Read them once per session; this file
does not repeat them.

## Two classes of document

A **canonical** document is true about the system now and has no end date: `GLOSSARY.md`, `docs/adr/`, `docs/knowledge/`, every `AGENTS.md`, the operator guides under
`docs/`, the skills. A **working** document is dated, belongs to a program under `docs/specs/<program>/`
or a draft under `.scratch/`, carries a ledger status, and exists to change a canonical one:
proposals, specs and architecture projections, interview instructions and answers, session
instructions, change ledgers, provider supplements, research notes, prototypes, Linear issues.
Nothing in a working document is authority; the code, the ADRs and the glossary are. How
each working record is **promoted** into its canonical home is [FLOW.md](FLOW.md).

## The phases and the skill that runs each

| Phase | Call the Skill tool with | Working record it leaves | Canonical home it feeds |
| --- | --- | --- | --- |
| Interview the owner | `grill-with-answers` (runs `grilling` and `domain-modeling`) | `answers/<TOPIC>-SITTING-<n>-<date>-ANSWERS.md`, ledger row `IA-n` | GLOSSARY terms, ADRs, spec sections, `OVE` issues |
| Sharpen language, record a decision | `domain-modeling` | none | `GLOSSARY.md`, `docs/adr/NNNN-<slug>.md` |
| Project the code before writing it | `architecture-projection` (speaks `codebase-design`) | `<TOPIC>-DESIGN.md`, ledger row `SP-n` | the code at that shape; the knowledge concept cites the as-built |
| Resolve provider facts | `provider-research` (drives `research`) | `providers/<lane>/<LANE>-SURFACE-<date>.md`, register rows `IP-n`; cross-lane: `docs/research/<date>-<topic>.md` | never a contract directly: a register row becomes a ledger proposal, then an ADR or an `OVE` issue through the interview |
| Research anything else | `research` | a cited note where the repo keeps such notes | an input to the interview |
| Answer a question only running code can answer | `prototype` | branch `prototype/<name>`; the verdict in the answers file or issue | a decision row and a projection section; the real code is written test-first |
| Specify | `to-spec` | the spec in the program (kind `specs`) and its Linear issue | none (what it describes becomes code and knowledge) |
| Ticket | `to-tickets` | `OVE-n` with `## Provenance`; ids in the ledger rows | none |
| Build | `implement` or `implement-spec`, driving `tdd` | code, tests, a `CHANGES.md` entry | `src/`, `tests/`, migrations in `packages/mission-control-db-contract` |
| Review and ship | `code-review`, `pr` | the reviewed diff, the PR body | none |
| Document | by hand, with `mission-control-docs` for lookups | none | `docs/knowledge/<concept>.md` and `log.md`, ADR status, `GLOSSARY.md`, the index (`agents_docs_index.py`) |
| Plan beyond one session | `wayfinder` | a map issue and decision tickets | none |
| Look back | `retro` | proposals for the environment | skills, checks, `AGENTS.md` pointers |

`ask-matt` explains the upstream flow in Matt's words; this table is the same flow with our
records attached. Upstream skills stay byte-identical (`docs/agents/matt-pocock-skills.md`), so
every Mission Control specific lives in `docs/agents/*.md` or in a skill of ours.

## Research, prototype, or both

Decide this at every plan, and write the choice into the plan's **Decisions needed** list:

- **Research** when the question is *what exists*: a provider's behaviour, a library's API, a
  contract, a version. Primary sources, cited with the version read.
- **Prototype** when the question is *how it feels or how hard it is*: a state model, a
  mechanism, an integration whose difficulty cannot be judged on paper. Throwaway code that
  answers one question, kept as a primary source on its branch, never merged.
- **Both** when a documented claim must be observed before a contract rests on it (research
  yields the claim, a probe confirms it: a `[PROBE]` finding), or when the architecture
  projection has a seam nobody can place without trying it.
- **Promote** either by writing the answer where the method keeps answers (a decision row with
  the owner's words, a projection section, a register row), then building the real thing
  test-first. The prototype's code is evidence, never the implementation.

## The session loop

Orient, audit, cross-reference, plan, **confirm with the owner**, build, prove, document, hand off.
Each step with its completion criterion is in [SESSION.md](SESSION.md); a program's `PROCESS.md`
adds its own specifics (provider consolidation: the capability catalog and the
discriminator-and-router rule) and never removes a step. A session closes with

```text
python docs/tools/check_docs.py
```

green, or with each failing check named in the final message. That command is also the target for
a hook or a scheduled run; the recipes per harness are in [HARNESSES.md](HARNESSES.md).

## Rules that hold in every phase

- Read before asserting: `mission-control-docs`, then the file, cited as `file:line`.
- Facts are the agent's job; decisions are the owner's, recorded in their words, dated, each with
  where it becomes and where it was folded.
- An item that will be built gets its `OVE` issue before work starts; nothing earlier is
  back-filled.
- A canonical change cites source and tests. Explanations explain, ADRs decide, specs plan; a
  document that does two of those is split.
- Standing owner rules recorded in the active program's `PROCESS.md` (migrations are part of the
  work, the per-session spend cap, commit and push on the owner's word) hold until the owner
  changes them.
