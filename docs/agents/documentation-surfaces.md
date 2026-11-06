---
type: Agent Configuration
title: "Documentation surfaces: where a Mission Control fact goes, who keeps it true, how it is found"
description: "The five surfaces that carry what agents and the owner need to know: OKF knowledge concepts, the Matt Pocock language-decision-work flow (GLOSSARY, ADRs, specs, Linear issues), the AGENTS.md files with their compiled index and sidecar notes, provider supplements with improvement proposals, and the agent skills (dev-time skills and shipped bundles); plus the harness adapters that must only point at them."
tags: [mission-control, agents, process, documentation, skills]
---
# Documentation surfaces

Five surfaces, each with one job. Put a fact in the surface that answers its question, once, and point to it from the others.

| # | Surface | Answers | Lives in | Kept true by | Reached through |
| --- | --- | --- | --- | --- | --- |
| 1 | **OKF knowledge** | How does the code realize this? | `docs/knowledge/*.md` (one concept per file: `type`, `title`, `description`, `tags`), plus ADRs, the glossary and research notes, which share the frontmatter | `validate_okf.py`; `log.md`; integrator at sprint end | `python docs/tools/okf_search.py "<terms>"`; the `mission-control-docs` skill |
| 2 | **Language, decisions, work** (Matt Pocock flow) | What do we call it, what did we decide, what are we building and in what order? | `GLOSSARY.md`, `docs/adr/`, program folders under `docs/specs/` with a `LEDGER.md` (including `answers/` and architecture projections), issues in Linear (`OVE`), drafts in `.scratch/` | The skills `grill-with-answers` (ours, over `grilling` and `domain-modeling`), `architecture-projection`, `to-spec`, `to-tickets`, `implement`, `triage`, `wayfinder`; `program_ledger.py check` | The `## Agent skills` block in `AGENTS.md`; the `belllabs-method` skill; `docs/agents/*.md` |
| 3 | **AGENTS.md** | Where is it, what is it for, what do I read before editing? | Root `AGENTS.md` (rules by hand, index compiled), 13 subsystem `AGENTS.md` (navigation by hand) | `agents_docs_index.py` compiles the index; notes come from the sidecar `index-notes.toml`; `--check` fails when stale or a note is missing | Loaded by every harness |
| 4 | **Provider supplements** | What is hard to discern, lesser known or new about provider X, and what should we change because of it? | `providers/<lane>/` in the program (for Deep Agents: `DEEP-AGENTS-SURFACE-<date>.md`), cross-lane research in `docs/research/`; the improvement register in [the running proposal](../specs/provider-consolidation-2026-10/PROVIDER-RESEARCH-RUNNING-PROPOSAL.md) | Dated, with `as_of` and `pins`; refreshed when a pin moves or a sprint on that lane starts by the `provider-research` skill (the running proposal's tier 1); detectors and probes proposed, not built | The ledger (kind `docs`); the index line for the folder |
| 5 | **Agent skills** | How do I do this job? | `.agents/skills/` (dev-time) and `skills/` (shipped bundles) | See below | The skill description is the pointer |

## What each surface may not do

1. **OKF** explains the code and cites source and tests. It does not decide (ADRs do) and does not plan (specs do). Authority on conflict: the code is what runs, `docs/adr` is what was decided, `docs/knowledge` explains both; program ledgers are working.
2. **Matt flow** uses `GLOSSARY.md` for language (upstream renamed the convention from `CONTEXT.md` to `GLOSSARY.md`; this repo already uses the new name). A decision with a lasting reason becomes an ADR; a plan becomes a spec and tickets; the tracker is Linear ([issue-tracker.md](issue-tracker.md)). Program mechanics are in [program-workspace.md](program-workspace.md).
3. **AGENTS.md** is navigation plus the invariants an agent breaks without warning. Explanation goes to surface 1 and a pointer stays in AGENTS.md. The compiled index lists every indexed directory with a one-line note from the sidecar, so a reader learns what a folder is for before opening it.
4. **Provider supplements** are research, not copies of provider documentation: they resolve what is source-only, scattered, contradicted, recent or probed, with a citation and a version for each claim, and link the provider's docs for everything else. Findings feed the improvement register of the running proposal; an accepted entry becomes a ledger row and an `OVE` issue. They do not change contracts; a decision does.
5. **Skills** are programs: they have a trigger (the description), steps, completion criteria and sometimes scripts. They are verified by use, not read for style.

## Canonical and working documents

Two classes cut across the five surfaces. A **canonical** document is true about the system now and has no end date. A **working** document is dated, belongs to a program or a draft, carries a ledger status and exists to change a canonical one. Nothing in a working document is authority; code, the spec pack, ADRs and the glossary are. The `belllabs-method` skill (`.agents/skills/belllabs-method/`, with `FLOW.md`) is the procedure that moves a fact from one class to the other; this table is the reference it reads.

| Class | Documents | Lifecycle | Kept true by |
| --- | --- | --- | --- |
| **Canonical** | `GLOSSARY.md`; `docs/adr/`; `docs/knowledge/`; every `AGENTS.md` and the compiled index; the operator guides under `docs/`; `docs/agents/*.md`; the skills (`.agents/skills/`, `skills/`) | edited in place; an ADR is superseded, never rewritten; `docs/knowledge/log.md` dates every concept change | `validate_okf.py`, `agents_docs_index.py --check`, `check_links.py`, `skills_manifest.py --check`, `check_matt_pocock_skills.py` |
| **Working** | under `docs/specs/<program>/`: proposals, specs and architecture projections (`<TOPIC>-DESIGN.md`), sprint sequences, session instructions, interview instructions, `answers/`, change ledgers (`CHANGES.md`), provider supplements; `docs/research/` notes (dated evidence that stays dated and is never promoted into a contract); `.scratch/` drafts; `prototype/<name>` branches; Linear issues | ledger statuses `planned → … → archived`; archived by `program_ledger.py`; `.scratch/` is disposable; prototype branches are pushed, never merged | `program_ledger.py check` |

### Promotion: how a working record becomes canonical

| Working record | Becomes | Through |
| --- | --- | --- |
| An owner's answer (a row in `answers/`) | a `GLOSSARY.md` term, an ADR, a spec section or an `OVE` issue; the row's **Becomes** and **Folded** cells name them | `grill-with-answers` conversion checklist; `domain-modeling` |
| A proposal the owner accepted | an ADR for the decision, `accepted` on the ledger row, an `OVE` issue for the work | the interview |
| An architecture projection | code at the projected shape; the knowledge concept cites the as-built modules and tests | `architecture-projection` conformance step |
| A provider finding | an `IP-n` register row, then a ledger proposal row, then an ADR or `OVE`; never a contract directly | `provider-research`, then the interview |
| A prototype verdict | a decision row and a projection section; the real code is written test-first | `prototype`; the branch stays as evidence |
| A built change | a `CHANGES.md` entry, then the knowledge concept, `log.md`, ADR status, glossary terms, the recompiled index | PROCESS step 7, by hand |
| A finished working document | `docs/specs/archive/<program>/<kind>/`, row set to `archived` | `program_ledger.py archive` |

One command verifies every surface offline and is the target for a session-close hook or a scheduled run:

```text
python docs/tools/check_docs.py            # make docs-check; --upstream adds the network check; --hook exits 2 for a Stop hook
```

## Skills: two populations, one rule

| | Dev-time skills | Shipped bundles |
| --- | --- | --- |
| Path | `.agents/skills/<name>/` (60 tracked); `.claude/skills/` holds local symlinks onto them and is git-ignored | `skills/<name>/` (15) with a `manifest.json` of file digests |
| Used by | Agents working on this repository (Claude Code, Codex, Cursor) | Missions: seeded into the catalog as `skill_bundle` capabilities and mounted into agents |
| Origin | Matt Pocock's engineering and productivity set (see [matt-pocock-skills.md](matt-pocock-skills.md)); LangChain, LangGraph, LangSmith and Deep Agents references; ours: `belllabs-method` (the map of this system), `grill-with-answers`, `architecture-projection`, `provider-research`, `mission-control-docs`, `mission-control-coordinator`, `mission-control-local-setup`, CLI-job skills, `swarm` | `mission-control` (router) and its five branch bundles, `mc-signals`, eight `mc-cognition-*` ([ADR 0033](../adr/0033-mission-control-skill-is-a-router-over-specific-skill-bundles.md)) |
| Check | `python scripts/dev/check_matt_pocock_skills.py` for the upstream set; `python scripts/dev/link_claude_skills.py --check` for the Claude Code links | `python scripts/skills_manifest.py --check` (part of `make check`) |

Rule: the Matt Pocock skills stay byte-identical to upstream so updates are a copy. Mission Control specifics go in `docs/agents/*.md` (which the skills read) or in skills of our own, never in an edited upstream file. Every skill carries `agents/openai.yaml` so Codex shows it the same way.

## Harness adapters

One skill tree serves three harnesses: Codex and Cursor read `.agents/skills/` natively; Claude Code reads the machine-local links under `.claude/skills/` that `scripts/dev/link_claude_skills.py` creates. The wiring and the hook recipes are in the `belllabs-method` skill's `HARNESSES.md`.

`.cursor/rules/*.mdc` is an adapter, not a surface: it may point at `AGENTS.md`, `GLOSSARY.md` and these documents and must not restate them. `project-organization.mdc` (always on) still restates the invariants of the root `AGENTS.md`; shrinking it to pointers is open. Four rules that only pointed at superseded work packages and at the absent `biotech-meta` repository were retired on 2026-10-23 (`parallel-blueprint-worktrees`, `wp-bp-010-stagegraph`, `wp-bp-020-goal-directed`, `biotech-meta-reference`); `_briefings/` keeps their drafting history.

## Where does this go?

| You have | It goes to |
| --- | --- |
| A term the project uses | `GLOSSARY.md`, via `domain-modeling` |
| The owner's answer in an interview | a row in the sitting's `answers/` file, via `grill-with-answers`; its **Becomes** cell names the canonical home |
| A decision with a reason that would be relitigated | `docs/adr/` |
| The shape of the code before it exists (modules, signatures, file tree, dependency chain, seams) | an architecture projection, `<TOPIC>-DESIGN.md` in the program (kind `specs`), via `architecture-projection` |
| A question only running code can answer | a `prototype/<name>` branch; the verdict in the answers file or the issue |
| How a mechanism works in the code today | `docs/knowledge/` (surface 1) |
| What to build, in contract terms | A spec in the program, row in `LEDGER.md` |
| A piece of work | A Linear issue; the ledger row records `OVE-n` |
| What a provider changed or offers | The provider supplement, then a proposal row |
| A rule an agent breaks without warning | `AGENTS.md` of the closest subsystem |
| A repeatable job | A skill, after it has been done by hand twice |

## Maintaining docs/ (formerly `docs/AGENTS.md`)

Start at `docs/README.md`. Keep accepted external architecture separate from local implementation evidence and blocked production
gates. Update the operator guide when entrypoints or configuration change.

`docs/knowledge/` is an Open Knowledge Format bundle: every concept has `type`, `category`, `title`, `description`, `aliases`,
`questions`, `updated`; `index.md` is generated and `log.md` is dated history. Do not put an `AGENTS.md` inside `knowledge/` (it would
become a concept). One concept per file, citing actual source and tests; do not label explanations accepted specs. Historical subtrees
retain provenance only: preserve prior deletions, private scratch and untracked files, and do not rewrite historical proof as current proof.

Validate with `python docs/tools/validate_okf.py`. After adding or renaming any document run `python docs/tools/agents_docs_index.py`:
it regenerates the marked blocks of the root `AGENTS.md` and `docs/knowledge/index.md` from the concept frontmatter and
`docs/agents/index-notes.toml`, and fails when a concept lacks `category` or `questions`, a nested module guide has no code-map line, or an
active program ledger is not listed. Search with `python docs/tools/okf_search.py` (`--programs` adds active program documents). A program
under `docs/specs/` keeps a `LEDGER.md`; archive finished documents with `python docs/tools/program_ledger.py archive` and verify with
`program_ledger.py check` ([program-workspace.md](program-workspace.md)). The one archive, `docs/specs/archive/`, is inert: nothing in it
is loaded by code or tests (mission manifests used by tests are under `tests/fixtures/manifests/`).

`python docs/tools/check_docs.py` runs every offline check (OKF bundle, index, each program ledger, links, skill manifests; `--bench` adds the
retrieval fixtures in `.sdlc/fixtures/retrieval/`) and reports them separately; run it before closing a session. The method these checks
serve is the `belllabs-method` skill.
