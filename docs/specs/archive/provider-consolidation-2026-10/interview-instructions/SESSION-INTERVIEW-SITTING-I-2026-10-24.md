---
type: Session Instruction
title: "Interview sitting I (revised 2026-10-24): obligations and transfer first, then the built capability slice, fault-tolerance splicing and the sequence; builds nothing"
description: "The instruction for the next session, an owner interview run with grill-with-answers into one answers file: rounds R0, RA, R1, R1b (output contracts and context transfer, the critical rounds), R3' (the capability language confirmed against the sprint B slice built 2026-10-23 and the catalog proposal AC-D1..D12), FT (where fault tolerance is spliced into the sprints, incrementally), RQ (the sequence: A, OC-1, OC-2, OC-3, the FT increments, the coordinator search-and-selection sprint, WC-D14) and R3.8; what to read, what to re-verify, how each round ends in a scenario, and what the sitting leaves behind (answers file, folds, session files, issues). Supersedes SPRINT-SEQUENCE §7."
tags: [mission-control, providers, consolidation, interview, session, output-contracts, sequence]
status: archived
archived: 2026-11-02
archived_from: SESSION-INTERVIEW-SITTING-I-2026-10-24.md
archived_reason: "retired with the sitting I track; superseded by Sprint OC"
---

> **Archived 2026-11-02** (retired with the sitting I track; superseded by Sprint OC). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Interview sitting I (revised 2026-10-24)

Linear `OVE-149`. This supersedes the prompt in
[SPRINT-SEQUENCE §7](../proposals/SPRINT-SEQUENCE-2026-10-23.md#7-the-first-session-interview-sitting-i-copy-into-the-first-message),
which was written before sprint B's first slice existed. The owner's framing for it
(2026-10-24): *"The interview should center around capability and features but also on sequence.
I think we have output contracts proposals but the output contracts and obligations are extremely
critical."* And: *"Maybe we should splice in fault tolerance and error handling to the next
sprints. Maybe we can incrementally implement it rather than one big sprint."* The coordinator
search-and-selection sprint is the owner's own placement: *"I expect to perform this coordinator
search and selection sprint after we finish the output contracts and context transfer."*

## 1. What stands at the start (2026-10-24)

| Thing | State | Where |
| --- | --- | --- |
| Tracing Stages 1-3 | built, merged, pushed | [CHANGES Turn 7](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md) |
| Sprint B, first slice (agent capability registry, `mc.agent_configuration.v1`, builders, Anthropic model factory) | **built 2026-10-23**, committed at the checkpoint of 2026-10-24; proven live on Haiku 5.5 and GPT-6 Luna (0.002 USD) | [CHANGES Turn 8](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md), [AGENT-CAPABILITY-CATALOG-PROPOSAL](../../../provider-consolidation-2026-10/AGENT-CAPABILITY-CATALOG-PROPOSAL-2026-10-23.md) |
| Output contracts and context transfer | specified (revision 2, OC-D1..D26 recorded as recommendations); **nothing built** | [SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER](../specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md) |
| Domain provenance and state | proposed (DP-D1..D14) | [supplement](../proposals/DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md) |
| Fault tolerance | proposed (FT-D1..D22, packages FT-0..FT-7); own program ledger | [FAULT-TOLERANCE-PROPOSAL](../../../fault-tolerance-2026-10/FAULT-TOLERANCE-PROPOSAL.md) |
| Workflows, compute, communication | proposed (WC-D1..D16); two future programs suggested | [WORKFLOWS-COMPUTE-AND-COMMUNICATION-PROPOSAL](../../../provider-consolidation-2026-10/WORKFLOWS-COMPUTE-AND-COMMUNICATION-PROPOSAL-2026-10-23.md) |
| Deep Agents upgrade (sprint A) | not started; 0.7.5 installed, 0.7.30 latest | [DEEP-AGENTS-SURFACE §1](../../../provider-consolidation-2026-10/providers/deep_agents/DEEP-AGENTS-SURFACE-2026-10-22.md) |
| Search and selection of workflow and agent interfaces by the coordinator | pieces exist (catalog search, cards proposal, the T0 registry search); **no sprint card yet** | [COORDINATOR-PROJECTION-PROPOSAL](../../../coordinator-surface-2026-10/COORDINATOR-PROJECTION-PROPOSAL-2026-10-23.md), [AGENT-CAPABILITY-CATALOG-PROPOSAL §3-§4](../../../provider-consolidation-2026-10/AGENT-CAPABILITY-CATALOG-PROPOSAL-2026-10-23.md) |

Decided already and not re-asked: the three-sitting structure and the card set of the sequence
(open only as to order and splicing), the ledger and Linear conventions, the deep-module and
discriminator rules of [PROCESS §2](../../../provider-consolidation-2026-10/PROCESS.md).

## 2. The interviewer's instruction (copy into the first message)

We are in the provider consolidation program, at the checkpoint commit of 2026-10-24 on `main`.
This session is **interview sitting I (revised)** of
`docs/specs/archive/provider-consolidation-2026-10/interview-instructions/SESSION-INTERVIEW-SITTING-I-2026-10-24.md`. Run it with
the `grill-with-answers` skill (which calls `grilling` and `domain-modeling`), under
`PROCESS.md` §1.2 and `OWNER-INTERVIEW-2026-10-22.md` §4.3, §4.4 and §7. Work in
`platform/mission-control` on a docs branch `docs/interview-sitting-1`; commit docs only, when I
say. **Build nothing. Change no sprint claim and no issue status.**

1. **Read, in this order** (about an hour of agent reading; cite what you rely on):
   - this instruction whole, then `SPRINT-SEQUENCE-2026-10-23.md` §2, §3 and §6;
   - `OWNER-INTERVIEW-2026-10-22.md` §0-§5 (rounds R0, R1, R1b, R3, R3.8, R9) and §7;
   - the output-contracts specification `docs/specs/archive/provider-consolidation-2026-10/specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md`
     §1-§4, §6, §7 and §8 (every OC-D row is a recommendation to confirm, amend or reject);
   - the supplement `docs/specs/archive/provider-consolidation-2026-10/proposals/DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md` §1-§4 and §8;
   - `providers/deep_agents/CHANGES.md` Turn 8 whole and Turn 7's deferred list;
   - `AGENT-CAPABILITY-CATALOG-PROPOSAL-2026-10-23.md` whole (AC-D1..D12);
   - `../fault-tolerance-2026-10/FAULT-TOLERANCE-PROPOSAL.md` §1, §3, §6, §7, §12 and §13;
   - `WORKFLOWS-COMPUTE-AND-COMMUNICATION-PROPOSAL-2026-10-23.md` §1, §7 and §9;
   - `COORDINATOR-PROJECTION-PROPOSAL-2026-10-23.md` §3 (cards) and its decision table;
   - `DEEP-AGENTS-SURFACE-2026-10-22.md` §1.5 (upgrade risks) and "Implications".
2. **Re-verify against live code**, citing `file:line`, before the first question: the
   OWNER-INTERVIEW §2.2 rows that R1 and R1b rest on (stage outputs, `output_refs`, cycle and
   iteration transfer); the supplement's §2 and §3.2 tables; and the sprint B slice as Turn 8
   describes it (the registry rows, `provider_options.deep_agents.lane_features`, the receipt kinds,
   `AnthropicExactModelFactory`). Mark drift in those tables before asking anything.
3. **Open the record first:**
   `python docs/tools/program_ledger.py new-answers --topic DEEP-AGENTS --sitting I --interview docs/specs/archive/provider-consolidation-2026-10/interview-instructions/SESSION-INTERVIEW-SITTING-I-2026-10-24.md`
   and add the row it prints to `LEDGER.md` (row IA-05). Decision ids keep their families
   (`OC-D`, `DP-D`, `AC-D`, `FT-D`, `WC-D`, `R3.n`, `RQ.n`). Nothing is asked before the file exists.
4. **Run the rounds in §3 below, in order.** Each round: two minutes of context in my terms; at
   most four questions per batch, recommendation first, what each option changes later; the
   restated mental model as a **scenario** (a manifest fragment, a command, what I will see in
   `missionctl run transcript` or `run outputs`); the record in the answers file (my words in
   *Answer*, your reading in *What it changes*, the date, *Becomes* and *Folded*); the drift check
   against the five goal properties of OWNER-INTERVIEW §0. If the sitting runs long, split after
   R1b (sitting I-a) and resume with R3' (sitting I-b) in a second answers file.
5. **After the rounds, convert** (grill-with-answers §5): fold each decision, one dated line,
   into OC §8, the supplement §8, the fault-tolerance proposal §13, the capability catalog
   proposal §7, and SPRINT-SEQUENCE §5; point OWNER-INTERVIEW §8 and SPRINT-SEQUENCE §7 to the
   answers file; write `providers/deep_agents/SESSION-A.md` and `providers/deep_agents/SESSION-OC-1.md`
   in full from the cards (goal in my words, inputs, the decisions each rests on with my answers,
   builds, proves, non-goals, host facts), and `../fault-tolerance-2026-10/SESSION-FT-0.md` if
   FT-D22 (a) stands; write the card for the coordinator search-and-selection sprint into
   SPRINT-SEQUENCE §3 where RQ places it; move
   `platform/HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md` to `providers/deep_agents/`
   and correct its links; update `LEDGER.md` (IA-05, IQ-03, IQ-04, SE-04, SE-05, SE-06, PR-05 and
   the fault-tolerance ledger); **offer** to file the `OVE` issues for the accepted sprints with
   a `## Provenance` section (ask me first; nothing earlier is back-filled); run
   `python docs/tools/agents_docs_index.py`, `python docs/tools/program_ledger.py check` and
   `python docs/tools/check_docs.py`.
6. **End with:** the decision log (id, my words, destination), the assumptions taken, the parking
   lot, the session files' paths in the order they run, and the one command I run first.

**Host facts:** Windows 11, one heavy job at a time, the disposable Postgres 17 container
`mc-ft-disposable-pg17`, credentials by name only. **No paid run happens in this session.**

## 3. The rounds of this sitting

Sources are the documents above; "gates" names the sprint that cannot start without the round.
Must-decide questions are those the sources mark *(must)*; the rest have stated defaults.

| Order | Round | Decisions | Gates | Scenario that closes the round |
| --- | --- | --- | --- | --- |
| 1 | **R0** alignment and language (OWNER-INTERVIEW §5) | R0.1-R0.3 | everything | the five goal properties restated in the owner's words |
| 2 | **RA** architecture and state (supplement §8) | DP-D1, D2, D3, D12, D13 | OC-1, P | one run: where its four states live and which one answers `run state-as-of` |
| 3 | **R1** output obligations and verification (OWNER-INTERVIEW §5, OC §3, §8) | OC-D1..D7, D14, D19..D21, D25, D26; CS-D10 (`run outputs`) | **OC-1** | a Stage Graph node with two obligations: what the agent must submit, what the reducer checks, what `run outputs` shows, what happens on a shortfall |
| 4 | **R1b** where context transfers happen (OWNER-INTERVIEW §5, OC §4) | OC-D8..D13, D15, D16, D18 | OC-2, OC-3 | the next stage's `/inputs`: which deliverables arrive materialized, which as references, what a cycle and a Goal Loop iteration carry |
| 5 | **R3'** the capability language against the built slice (OWNER-INTERVIEW §5 R3; Turn 8; AC proposal §7) | R3.1 (spelling: keep under `provider_options.deep_agents` or lift to `agents:`), R3.2 (confirm the code structure as built), R3.3 (hooks (a)+(b), lift the 409), R3.4 (the next rows: AC-D12), R3.5 (server-side observability: AC-D6), R3.6 (context schema as identity, the three `mc_*` channels; OC-D24), R3.7; AC-D1..D5, D7..D11 | B (second slice), the search-and-selection sprint | the Turn 8 manifest fragment as the owner would write it, and the receipt the owner would read |
| 6 | **FT** fault-tolerance splicing (FT proposal §12, §13) | FT-D22 first (program placement); then the decisions that gate A and OC-1: FT-D1, D2, D3, D5, D6, D8, D9, D18, D19; the rest deferred with the proposal's recommendation as the assumption | A, OC-1, F | a provider failure mid-turn: what the transcript records, what `run faults` shows, what retries and what escalates |
| 7 | **RQ** the sequence (OWNER-INTERVIEW §5 R9, limited to what this sitting can order) | RQ.1 the order of A, OC-1, OC-2, OC-3 and the FT increments (FT-0, FT-1 before A or with it); RQ.2 the coordinator search-and-selection sprint ("S"): after OC-2 as the owner expects, its card's goal and inputs (CS-D1..D14, AC-D10, PR-07 cards), and what it displaces; RQ.3 WC-D14 (cooperative inject) placed in F or earlier; RQ.4 which WC-D rows enter sitting II or III | the rest | the sequence table rewritten with dates the owner believes |
| 8 | **R3.8** the upgrade first (OWNER-INTERVIEW §5) | sprint A | A | the one command the owner runs first in A |

Rounds **R2** (subagents), **RD** (domain provenance), **RS** (the service map), **R5-R8**,
**HR0-HR9** and **RP** stay in sittings II and III as SPRINT-SEQUENCE §2 places them. Anything
from them that comes up here goes to the parking lot with the owner's words.

## 4. Rules specific to this sitting

- **Obligations are the critical path.** R1 is not shortened to make room for later rounds; if
  time runs out, the sitting ends after R1b and R3', FT and RQ run as sitting I-b.
- **Scenarios, specs and issues.** Every decision names the spec section it changes (OC §n,
  supplement §n, FT §n, AC §n) and, when it is work, the issue it becomes. A decision that
  changes nothing written is a glossary term or it is parked.
- **The built slice is evidence, not a decision.** Sprint B's first slice used the strawman names
  under `provider_options.deep_agents`; R3.1 may rename or lift them. The interviewer presents
  what moving would cost (one manifest field, the receipt names unchanged) and does not defend
  the built spelling.
- **Fault tolerance is spliced, not re-proposed.** The interviewer asks where each FT package
  rides (FT-0 and FT-1 as a short diversion; FT-2 with A; FT-3 and FT-4 with B's second slice
  and I; FT-6 with F, per the proposal's §12) and takes the proposal's recommendation as the
  assumption for every FT-D row the owner does not reach.
- **Provider-neutral first** (OWNER-INTERVIEW §4.4): each decision states its general form and
  then the Deep Agents materialization; the other provider lanes are behind by choice, and no
  decision here closes a door on them without saying so.

## 5. What the sitting leaves behind

| Output | Where | Ledger row |
| --- | --- | --- |
| The answers file, `final` or `open` with the rows that lack a destination named | `answers/DEEP-AGENTS-SITTING-I-<date>-ANSWERS.md` | IA-05 |
| Folded decision lines | OC §8, supplement §8, FT proposal §13, AC proposal §7, SPRINT-SEQUENCE §5 | IA-03, PR-03, PR-09, fault-tolerance PR-01 |
| `SESSION-A.md`, `SESSION-OC-1.md`, and `SESSION-FT-0.md` if accepted | `providers/deep_agents/`, `../fault-tolerance-2026-10/` | SE-04, SE-05, new rows |
| The search-and-selection sprint card | SPRINT-SEQUENCE §3 | PR-02 |
| `OVE` issues for the accepted sprints, filed only after the owner says so | Linear | the rows above |

## 6. Non-goals

No code, no migration, no paid run, no change to the sprint B slice, no decision on the rounds
of sittings II and III, no Linear status change.
