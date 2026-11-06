# The lifecycle of a fact

Companion to [SKILL.md](SKILL.md). Every fact Mission Control relies on starts as something the
owner said or something an agent read, and ends in exactly one canonical home. This file is the
route between the two, and the test for whether a plan is "consolidated".

## The route

```text
owner's words ──► answers file row ──► GLOSSARY term │ ADR │ spec section │ OVE issue
   (interview)      (working, dated)        (canonical)   (canonical)  (working)    (working)
                                                                           │
provider source ──► supplement finding ──► IP register row ──► ledger proposal ──► ADR or OVE
   (research)        (working, dated)      (working)         (working)         (via the interview)

decision + spec ──► architecture projection ──► code written test-first ──► CHANGES.md entry
                     (working, kind specs)        (canonical)                 (working)
                                                       │
                                                       └──► knowledge concept + log.md ──► index
                                                             (canonical, cites source and tests)

question on paper ──► prototype branch ──► verdict (answers row or issue) ──► projection section
                       (evidence)            (working)                          (working)
```

Arrows only point from working to canonical. A canonical document never cites a working one as
its authority; it cites the code, the tests, an ADR or another canonical document. A
working document may cite anything.

## Promotion table

| Working record | Canonical home | Through | Done when |
| --- | --- | --- | --- |
| A decision row in an `answers/` file | `GLOSSARY.md` (term), `docs/adr/` (decision with a lasting reason), a spec section, an `OVE` issue | the conversion checklist of `grill-with-answers`; `domain-modeling` for terms and ADRs | the row has **Becomes** and **Folded**; the file is `status: final`; `program_ledger.py check` passes |
| A proposal the owner accepted | an ADR for the decision; the ledger row goes `accepted`; an `OVE` issue for the work | the interview; `ADR-FORMAT.md` in `domain-modeling` | the ADR exists with `status: accepted`; the proposal row names it |
| An architecture projection | the code at the projected shape; the knowledge concept cites the as-built modules | `architecture-projection` conformance step | every projected module exists as projected or has a dated deviation row |
| A provider finding | a register row `IP-n`, then a ledger proposal row, then an ADR or `OVE` | `provider-research`; the owner decides at the promotion gate | the finding carries citation, version, date, label and impact; the register row names where it lands |
| A prototype verdict | a decision row and a projection section; the real code is written test-first | `prototype`; the branch `prototype/<name>` is pushed, never merged | the issue or answers row links the branch and states the verdict |
| A built change | `docs/knowledge/<concept>.md` with a dated `log.md` line, ADR status moved if the build settled it, glossary terms, the compiled index | PROCESS step 7 by hand | `validate_okf.py` and `agents_docs_index.py --check` pass; the concept cites source and tests |
| A finished working document | `docs/specs/archive/<program>/<kind>/` | `program_ledger.py archive` (rewrites links) | the ledger row says `archived`; `check` passes |
| A repeatable job done twice by hand | a skill of ours under `.agents/skills/` | `writing-for-agents` | its description names the trigger branches; it is wired for the three harnesses |

## Running documents and consolidation

While a plan is still forming, the owner's instruction is **running**: edit the register, not the
history. A running proposal or sprint sequence grows between sittings and is never the authority
for anything. It is **consolidated** when, for the slice at hand:

1. every decision it needed has an answers row with the owner's words and a destination;
2. the language it introduced is in `GLOSSARY.md` and the lasting decisions are ADRs;
3. the code shape is an architecture projection the owner confirmed;
4. each unit of work is an `OVE` issue with `## Provenance`, id in the ledger;
5. the documents it superseded are archived by the tool.

Until all five hold, the slice is "developing" and the ledger row says so. Consolidation is per
slice (a sprint card, a decision family), never a big bang at the end.

## Where a reader starts

| A reader wants | Start |
| --- | --- |
| The current truth about a mechanism | `docs/knowledge/index.md`, or `python docs/tools/okf_search.py "<terms>"` |
| Why it is that way | the ADR the concept cites |
| The word for it | `GLOSSARY.md` |
| What is being built now and what is decided | the program's `LEDGER.md`, then the answers files |
| What is left open | the ledger rows `open` and the answers files' *Assumptions* tables |
| What was tried and discarded | the archive README and `prototype/*` branches |
