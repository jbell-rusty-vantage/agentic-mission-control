# The session loop

Every working session follows these steps in order. Each ends on a criterion the agent can check.
A program's `PROCESS.md` (provider consolidation:
[PROCESS.md](../../../docs/specs/provider-consolidation-2026-10/PROCESS.md)) adds its specifics
and standing owner rules; it never removes a step.

| # | Step | Done when |
| --- | --- | --- |
| 0 | **Orient.** Read the program `LEDGER.md` first, then its `README.md` and `PROCESS.md`, the lane's `CHANGES.md` and `DESIGN.md`, and the owner's brief. Read live branch state (`git status`, `git log -5`); a previous turn's description of the tree is not evidence | the goal is restated in one paragraph in the owner's words, and the owner accepts it |
| 1 | **Audit.** Establish what the code does today for that goal: open the modules, run the cheapest honest probe (unit tests, the offline stack; never a paid run without authorization), cite `file:line`. Label each fact *tested*, *implemented-unproven* or *documented-only* | every claim the plan will rest on has a label and a citation |
| 2 | **Cross-reference.** Map the audit onto the goals and the program's catalog or decision families. Name each gap *general* (every lane) or *provider-specific* | a gap list with that label on every row |
| 3 | **Plan.** The smallest set of changes that closes the gaps as deep modules, each with its test and its "finished part" pointer. For anything larger than one module, write the **architecture projection** (`architecture-projection`). Decide research, prototype or both for each open mechanism. List every point where the plan chose for the owner | a plan with an explicit **Decisions needed** list and, when it changes code shape, a projection |
| 4 | **Confirm with the owner.** Run the questions through `grill-with-answers`: batches of at most four, recommendation first, what each option changes, the mental model restated after each round. Proceed under a stated assumption only for what does not change the design | every decision that changes the design has an answers row; the rest are *Assumptions* |
| 5 | **Build.** File the `OVE` issue per item first (`## Provenance`). Implement against the projection with `tdd` at the agreed seams. General and provider-specific changes land as separate commits or at least separate ledger rows | the projected modules exist; tests at the agreed seams are green |
| 6 | **Prove.** Run the tiers the change can honestly reach, offline first. Report passed, failed, blocked and unrun separately; name pre-existing failures as such | a "Checks run" entry with the four lists |
| 7 | **Document.** The `CHANGES.md` entry (general vs provider-specific, finished part, proof); the knowledge concept and `log.md`; the ADR status; glossary terms; the projection's conformance table; the ledger rows; archive what is finished with the tool | `python docs/tools/check_docs.py` passes, or each failure is named |
| 8 | **Hand off.** Write the next session's instruction (goal, inputs to read, open questions, non-goals) as `SESSION-<TASK>.md` in the program, with its ledger row and `OVE` issue | the next agent can start from the file alone |

## The final message

Three things, every time, so the owner can see where the new part runs:

1. **one finished part to read**, named by module, in reading order (inputs, the module, its
   output), with the test that proves it;
2. **the sequence it sits in** (for a lane change: HTTP verb → service → resolver → adapter →
   binding → activity → materializer);
3. **how to use it**: a manifest fragment or a command, and what the owner will observe.

Then the checks (passed, failed, blocked, unrun), the decisions recorded and the assumptions taken,
and the next session's file.

## Closing checklist

```text
python docs/tools/check_docs.py                 # OKF bundle, AGENTS.md index, every program ledger, links, skill manifests
python docs/tools/agents_docs_index.py          # when the index is stale: recompile it, then re-run the check
python docs/tools/program_ledger.py check       # alone, when iterating on one ledger
```

Commit and push only when the owner says so. Keep secrets, receipts and private notes out of the
commit; cite credentials by name.
