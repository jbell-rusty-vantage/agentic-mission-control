# AGENTS.md grammar

## Root `AGENTS.md`, in order

1. Title and one-sentence purpose (hand-written).
2. Read before editing: the directive, branch and dirty-work checks, the ideas pointer (hand-written).
3. `<!-- BEGIN:sdlc-infra -->`: the pointer to `docs/INFRASTRUCTURE.md` and the most used commands
   (generated, ≤400 B).
4. Invariants, starting with the **Authority** line: code is the truth for what runs, ADRs for what
   was decided, concepts explain both, programs are working material (hand-written).
5. `<!-- BEGIN:sdlc v=<version> src=<digest> -->` (generated, ≤8 KiB): repository guide; knowledge by
   category (one `- name — questions[0]` line per concept; a category above twelve concepts collapses
   to names only, pinned concepts first); the **code map** (`<dir> — <purpose>`, one line per module
   in `.sdlc/modules.json`); skills by trigger; `Tracker:`; `Verify:` code and docs lines.
6. `<!-- BEGIN:sdlc-programs -->`: one line per active program ledger (generated, ≤1 KiB).

Budgets: hand-written ≤4 KiB, whole file ≤14 KiB. Over budget fails the check; the fix is to move text
into a concept or a module guide. A threshold changes only by ADR.

## Module guides (`<dir>/AGENTS.md`)

One per entry in `.sdlc/modules.json`, at most two levels below the package root. Hand-written text
above the marker is preserved byte for byte (≤2 KiB); the generated block is ≤2 KiB:

```text
<!-- BEGIN:sdlc-module id=<id> -->
# <module>
<purpose>
Entrypoints: <file> — <its docstring's first line> · ...
Tests: <paths> · Verify: <commands> · Program: <ledger or change record>
Explained by: <concepts whose citations link into this directory>
Decided by: <ADRs those concepts cite>
<!-- END:sdlc-module -->
```

## `.sdlc/modules.json`

Hand-maintained, changed in the same commit as the code it describes: `id`, `path`, `purpose`,
`tests`, `verify`, `program`, `invariants`, optional `pin_first`. The purpose is written from the
code, specific enough that an agent picks the right directory from the code map alone.

## Regenerating

Never edit inside markers. Run the repository's generator (COMMANDS.md) after changing a concept's
title, category or questions, a module entry, a ledger status, or the infrastructure sidecar; its
check mode fails when a block is stale or over budget.
