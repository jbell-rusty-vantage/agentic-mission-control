---
name: architecture-projection
description: Project the code before writing it - the modules, their interfaces as real signatures, the file tree changes, the dependency chain across layers, the call sequence, migrations and the tests at each seam, in one document the implementation is then checked against. Use when planning any change larger than one module, when a spec or ticket is about to be implemented, when the owner asks to see the functions, classes, files or dependencies before building, and after building to record where the code departed from the projection.
---

# Architecture projection

A projection is the plan written as the code will look: concrete enough that a reader sees the
modules, signatures, files and imports before any of them exist, and that the implementation
can be diffed against it afterwards. It is a **working** document (ledger kind `specs`), and it
is the bridge between Matt's `to-spec` (which keeps file paths and snippets out of the spec on
purpose) and `tdd` (which needs the seams agreed). Vocabulary: `codebase-design` (module,
interface, depth, seam, adapter, leverage, locality); layer rules: the root `AGENTS.md`
*Invariants* (interfaces call application; application uses domain and ports; adapters implement
ports; bootstrap wires; domain imports no I/O).

## 1. Gather the inputs

The decisions it rests on (the answers file rows, the ADRs), the spec or ticket, `GLOSSARY.md`
for every name, and the modules it touches today (open them; cite `file:line`). For a lane
change, the discriminator-and-router rule in the program's `PROCESS.md` §2 decides where new
behaviour may live.

**Done when:** every decision the projection depends on is cited by id, and every existing
module it changes has been read.

## 2. Write the projection

Where: `<TOPIC>-DESIGN.md` in the program (or a dated `## Architecture projection` section of an
existing `DESIGN.md`), with a ledger row; outside a program, `.scratch/<topic>/DESIGN.md` until
promoted. Shape: [PROJECTION-TEMPLATE.md](PROJECTION-TEMPLATE.md). The sections, in order:

1. **Goal** in the owner's words, and the decisions it rests on.
2. **Module map**: one row per module, with its layer, its interface in one line, what it hides,
   what it refuses. Deep modules: few entry points, much behind them.
3. **File tree**: added, changed and removed files as a tree, each with a one-line reason.
4. **Interfaces**: real signatures in the target language (dataclasses, Pydantic models,
   function and method signatures with types, the exceptions or typed refusals), with a
   one-line docstring each. Names from `GLOSSARY.md`.
5. **Dependency chain**: which module imports which, drawn as arrows, with the layer rule each
   arrow obeys; the ports an adapter implements; what the domain must stay free of.
6. **Sequence**: the call chain a request takes through the new parts (for a lane change: HTTP
   verb → service → resolver → adapter → binding → activity → materializer).
7. **Data and migrations**: tables, columns, the component version, the migration file name.
8. **Seams and tests**: the seam each test crosses, the test file, what it catches and what it
   misses. These are the seams `tdd` later asks the owner to agree; agreeing them here is the
   agreement.
9. **Receipts and observability**: what the change records (receipts, frames, ledger rows) so a
   coordinator can see it ran.
10. **Non-goals** and **open questions** (each open question goes back to the interview).

Two designs for the hardest module when the interface is not obvious
(`codebase-design/DESIGN-IT-TWICE.md`); keep the rejected one as a short appendix with the reason.

**Done when:** a reader could write the tests from section 8 and the module skeletons from
sections 3 and 4 without asking anything.

## 3. Confirm

The projection is itself a thing to ask about. Put its choices to the owner through
`grill-with-answers` (the projection is the `--interview` instrument); record the answers; update
the projection; the ledger row goes `accepted`.

**Done when:** every open question in section 10 has an answers row or a stated assumption.

## 4. Implement against it

Each ticket names the projection section it realizes. `tdd` runs at the seams of section 8 and
nowhere else. A module that needs a different shape than projected is a finding, not a silent
change: write the deviation row (step 5) first, then build.

## 5. Record conformance

After the build, append a **Conformance** table: `Projected | As built | Why`, one row per module
and per seam, dated. Mark the document `as built` in its status line; the knowledge concept that
explains the mechanism cites the as-built modules and tests, not the projection.

**Done when:** every projected module either exists as projected or has a dated deviation row,
and the ledger row's status reflects it.
