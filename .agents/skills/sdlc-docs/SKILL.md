---
name: sdlc-docs
description: Find, keep true and measure a BellLabs repository's documentation. Use when looking up a fact about a codebase, after changing code a concept explains, when writing a concept, research note or retrieval fixture, when regenerating AGENTS.md or module guides, or when running a truth pass on a codebase.
---

# sdlc-docs

Agents are the primary developers here. A fact is useful only if an agent with no context reaches the
correct, current version in one or two hops, so documentation work is navigation work. This skill is
the same in every repository; the commands differ and live in the repository's `AGENTS.md` **Verify**
line ([COMMANDS.md](COMMANDS.md) maps them).

## The surfaces (where a fact belongs)

| Surface | Holds | Truth it carries |
| --- | --- | --- |
| Code | what runs | the final word on behaviour |
| `docs/adr/NNNN-*.md` | what was decided and why; newest wins | the final word on decisions |
| `docs/knowledge/*.md` **concepts** | how the system works: the contract, the lifecycle, the refusals, with `path:line` citations; one of nine **categories** | explains code and ADRs; a mismatch is a concept bug |
| `docs/research/<subject>/*.md` | what we learned about the outside world (libraries, providers), version-pinned | stale when the pin moves |
| `GLOSSARY.md` | the words; `_Avoid_` lists | terms only |
| `docs/specs/<program>/` with `LEDGER.md` | working material: proposals, interviews, answers, plans | not current truth until promoted |
| `AGENTS.md` (root and module guides) | the map: invariants by hand, generated blocks | derived; never edit inside markers |
| `.sdlc/fixtures/retrieval/` | the questions and tasks the docs must answer | the measurement |

The nine categories, in index order: `boundaries`, `surfaces`, `domain-model`, `persistence`,
`execution`, `qualification`, `operations`, `decisions`, `goals`.

Claims carry a **proof label**: implemented, tested, integrated, qualified. Integrated and qualified
cite a committed receipt (a report, a release bundle, a control-board line); a private `.scratch/`
path alone is never proof. Goals and specified-not-built work are labelled as such, never as built.

## Branch 1: navigate (find a fact)

1. Read the root `AGENTS.md`: the **Authority** line, the invariants, the knowledge index by category,
   the code map.
2. Pick the concept whose index line answers your question; open it. For code, open the module guide
   (`<dir>/AGENTS.md`) the code map names: entrypoints, tests, the concepts that explain it.
3. When the index does not name it, search with the repository's search command (COMMANDS.md). For a
   long task, search each facet separately (the lane or component, the configuration, the environment,
   the workflow, the tests) rather than the whole sentence.
4. Verify against the cited `path:line` before asserting; report a mismatch instead of trusting prose.

Done when the fact is confirmed in code or an ADR, or the gap is reported with the query you ran.

## Branch 2: update after a change

1. List the code paths you changed; find the concepts that cite them (module guide **Explained by**,
   or grep `docs/knowledge` for the path).
2. Edit each concept so every claim matches the new code; keep the format in [FORMATS.md](FORMATS.md)
   (frontmatter, ≤160 lines, Citations, proof labels, snippet anchors).
3. A new external fact you relied on becomes a research note; a decision becomes an ADR or an ADR
   status change; a new word becomes a glossary term.
4. Regenerate the derived files and run the checks and the bench (COMMANDS.md). A bench regression
   fails the change; fix the concept, never the fixture.

Done when every concept citing a changed path is true, the generators report current, and the
checks and bench gate pass. If nothing needs a docs change, the commit carries
`Docs: none <reason>`.

## Branch 3: truth pass (a whole codebase)

Run [TRUTH-PASS.md](TRUTH-PASS.md): explore in parallel, triage every document, put the decisions to
the owner, rewrite in disjoint phases, bench before and after. One codebase at a time.

## Reference

- [FORMATS.md](FORMATS.md): concept, research note, fixture case, ADR status.
- [AGENTS-MD.md](AGENTS-MD.md): the root and module guide grammar, markers, budgets, `modules.json`.
- [TRUTH-PASS.md](TRUTH-PASS.md): the per-codebase procedure and its triage vocabulary.
- [COMMANDS.md](COMMANDS.md): the commands per repository today and after the `sdlc` CLI lands.
