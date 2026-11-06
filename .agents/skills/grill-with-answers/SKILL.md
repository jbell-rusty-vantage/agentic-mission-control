---
name: grill-with-answers
description: A relentless interview of the owner about a plan, proposal, spec or projection that records every decision separately, in the owner's words, with where it becomes (ADR, glossary term, spec section, Linear issue) and where it was folded; the Mission Control form of grill-with-docs.
disable-model-invocation: true
---

# Grill with answers

The interview is `grilling`; the language and decisions are `domain-modeling`; this skill adds the
**record**: one answers file per sitting, one row per decision, converted before the sitting
ends. The conventions it follows are [program-workspace.md](../../../docs/agents/program-workspace.md)
("Interview answers") and [PROCESS.md §1.2](../../../docs/specs/provider-consolidation-2026-10/PROCESS.md)
("How to ask"); the file shape is the
[template](../../../docs/agents/templates/interview-answers.template).

## 1. Open the record first

Nothing is asked before the file exists.

- **Inside a program** (the topic belongs to a folder under `docs/specs/` with a `LEDGER.md`):

  ```text
  python docs/tools/program_ledger.py new-answers --topic <TOPIC> --sitting <n> \
      --interview <the document under interview> --program docs/specs/<program>
  ```

  The `--interview` file is the instrument: an `INTERVIEW-*.md`, or the proposal, spec or
  projection being grilled. Add the ledger row the tool prints (kind *Interview answers*, status
  `open`).
- **Outside a program:** copy the template to `.scratch/<topic>/ANSWERS.md`, fill the front
  matter by hand. When the decisions turn out to matter, move the file into a program with
  `program_ledger.py move` and add its row.

Decision ids keep a family prefix (`OC-D4`, `DP-D2`, `HG-D7`); start a new family only for a new
topic.

**Done when:** the file exists with its front matter resolved, and its ledger row is in place.

## 1a. Start from an idea when there is one

When the topic comes from the owner's ideas workspace (`platform/agentic-sdlc/ideas/`, guide in
its `README.md`), set the idea's `status: interviewing`, cite its `ID-n` in the instrument's front
matter (`idea:`) and in every answers row's **Source**, and never edit the owner's itch paragraph.
After conversion, write the program and answers file path into the idea's `promoted_to` and the
issue ids into `linear`.

## 2. Read, then re-verify

Facts are the agent's job. Before the first question: `GLOSSARY.md` for the words, the ADRs in
the area, the knowledge concept, the code. Every fact the questions rest on is cited `file:line`
and checked against the live branch; drift in a document's table is marked in that table before
asking.

**Done when:** no question on the frontier needs a fact the owner would have to supply.

## 3. Run the rounds

Call the Skill tool twice, for `grilling` and `domain-modeling`, and hold these house rules on top:

- **Batches of at most four**, recommendation first, and what each option changes later (a
  contract shape, a default, a refusal rule, a tier or a spend).
- Ask only what changes what gets built. What the code already answers is read and cited.
- Use the harness's question tool when it has one, so the answer is recorded verbatim; otherwise
  the round format of `grilling`.
- After each round, **restate the mental model** in the owner's terms: a manifest fragment, a
  command, what they will see. Record the owner's correction if they give one.
- Challenge terms against `GLOSSARY.md` and write resolved terms there as they crystallise;
  offer an ADR only when the decision is hard to reverse, surprising without context and a real
  trade-off.

**Done when:** the frontier is empty and the owner confirms the restated model.

## 4. Record as you go

One table row per decision, in the order asked:

| Column | Holds |
| --- | --- |
| ID | the family id |
| Source | the idea the sitting serves (`ID-n` from `platform/agentic-sdlc/ideas/`), or `-` when the sitting has no idea behind it; one Source per sitting unless the owner names another |
| Question | one line |
| Answer | **the owner's words**, quoted; never the agent's paraphrase |
| Date | the sitting's date |
| What it changes | the agent's reading: which contract, default, module or document moves |
| Becomes | `ADR-NNNN`, `spec <file> §n`, `GLOSSARY <term>`, `OVE-n`, or `none (reason)` |
| Folded | the link to the document edited to carry it, or `n/a` |

A question asked and not answered is a row in *Assumptions* with the assumption taken and the
risk if wrong. Anything raised that belongs to another round goes to the *Parking lot* with the
round that takes it.

**Done when:** every decision the owner voiced is a row, and no row's *Answer* contains agent words.

## 5. Convert before closing

Work the file's *Conversion checklist*:

1. Fold each decision into the document that carries it (the spec's decision log, the
   supplement's §8, the projection): one dated line per decision; link it in **Folded**.
2. Write the ADR candidates through `domain-modeling`; add the glossary terms.
3. Linear: a comment on each issue a decision decides; an `OVE` issue, with `## Provenance`, for
   each accepted piece of work ([issue-tracker.md](../../../docs/agents/issue-tracker.md)); ids in
   **Becomes** and in the ledger rows.
4. Set the file `status: final` when every decision has both **Becomes** and **Folded**, then
   run `python docs/tools/program_ledger.py check --program docs/specs/<program>`.

**Done when:** `check` passes with the file `final`, or the file stays `open` and the final
message names which rows still lack a destination and why.

## 6. End

The final message carries the decision log (id, owner's words, destination), the assumptions
taken, the parking lot, and where the next session starts. Building does not begin in the same
sitting unless the owner says so.
