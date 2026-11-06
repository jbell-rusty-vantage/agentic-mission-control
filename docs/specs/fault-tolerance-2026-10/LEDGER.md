---
type: Program Ledger
title: "Fault tolerance ledger: where the error module, recovery and precise-messaging proposal stands"
description: "The pointer and progress register of the fault-tolerance program (one fault registry, the vendor error families from Temporal, LangChain, LangGraph, Deep Agents and the provider SDKs, layered recovery and declared fallbacks, coordinator-selectable fault policies, one error envelope across the API, MCP and CLI, and the observability that goes with them). One row per document or work item; convention in docs/agents/program-workspace.md, verified by docs/tools/program_ledger.py."
tags: [mission-control, errors, fault-tolerance, observability, ledger, process]
---

# Fault tolerance ledger

**Parked 2026-11-01 (owner decision AS-D25); resumes on owner request.** Last reconciled 2026-11-01. Nothing is built. The
convention, status words and closing checklist are in [docs/agents/program-workspace.md](../../agents/program-workspace.md); check with
`python docs/tools/program_ledger.py check --program docs/specs/fault-tolerance-2026-10`. It stays in place (the archive is for
completed work). Known code defects that belong to this program are listed in the truth-pass `CODE-ISSUES.md`.

**Next step when resumed:** the owner reads the proposal and answers FT-D1..D22 (§13). If FT-D22 (a) is accepted, FT-0 (registry and
surfaces) and FT-1 (Temporal) run as a short diversion before the next provider sprint; FT-2 rides with the first, FT-3 and FT-4 with
the second and third, FT-6 with the sixth.

**Linear.** From 2026-10-23 every item that will be built gets an `OVE` issue before work starts
(rule 1 of the convention).

Status words: `planned` · `draft` · `open` (waiting for an owner decision) · `accepted` · `active` ·
`parked` · `done` · `archived`.

## Proposals

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| PR-01 | [Fault tolerance and the error contract (2026-10-23)](FAULT-TOLERANCE-PROPOSAL.md) | parked | - | Written 2026-10-23 from a read of `main` (`a7a8b0da`) and the installed packages; decides nothing. Owner answers FT-D1..D22. |

## Issues

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| IS-01 | [Work packages FT-0..FT-7](FAULT-TOLERANCE-PROPOSAL.md#12-work-packages-and-placement) | parked | - | File one `OVE` issue per accepted package, with a `## Provenance` section naming the proposal section; record the ids here. |
