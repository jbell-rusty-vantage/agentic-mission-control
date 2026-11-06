---
type: Program Ledger
title: "Proposals ledger (2026-10): provider batches, human review, next-stage contracts and spec-pack ideas"
description: "The pointer register of the Mission Control proposals that were written outside the programs and are not built: provider batch inference, the human review loop supplement, the next-stage capability and contract design with its evidence, the spec-pack product ideas, and the capability evolution research. One row per proposal; every one is open and waits for an owner interview before building. Convention in docs/agents/program-workspace.md."
tags: [mission-control, proposals, ledger, process]
---

# Proposals ledger

Last reconciled **2026-11-01** (OVE-206 documentation truth pass). Status: **open**: these are proposals, not
built behaviour and not decisions. The convention, status words and closing checklist are in
[docs/agents/program-workspace.md](../../agents/program-workspace.md); check with
`python docs/tools/program_ledger.py check --program docs/specs/proposals-2026-10`.

**Next step of the program:** an owner interview per proposal before anything is built. The concepts that
carry each proposal's goal are [provider batch](../../knowledge/provider-batch.md),
[human gates](../../knowledge/human-gates.md) and [goals](../../knowledge/goals.md).

The four platform-level originals sit in `platform/` (outside any repository); these are copies made on
2026-11-01 with their relative links rewritten. The originals stay until the owner confirms their removal.

## Proposals

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| PR-01 | [Provider batch inference for Mission Control and Knowledge Services](PROVIDER-BATCH-INFERENCE-PROPOSAL-2026-10-18.md) | open | - | Written 2026-10-18; recommends a standalone provider-neutral batch module first, then a Mission Control wait. Not built. Owner interview before building. |
| PR-02 | [Human review gates and steering supplement](HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md) | open | - | Written 2026-10-22; the human review loop design (verdict plus typed riders, Review Assistant, persistence, a worked example). The built subset is in [human gates](../../knowledge/human-gates.md). Owner interview HG-D1..D24. |
| PR-03 | [Next-stage capability and contract design](MISSION-CONTROL-NEXT-STAGE-CONTRACT-DESIGN-2026-10-16.md) | open | - | Written 2026-10-16; dashboard control plane, human steering, batches and capability evolution backlog. Not built. |
| PR-04 | [Spec-pack product ideas](SPEC-PACK-IDEAS-2026-11.md) | open | - | Harvested 2026-11-01 from the deleted `mission-control-general/`; fourteen ideas with their source sections at commit 66185d2e. |

## General documentation

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| DOC-01 | [Provider batch inference evidence register](PROVIDER-BATCH-INFERENCE-EVIDENCE-2026-10-18.md) | open | - | 74 rows from the official Anthropic and OpenAI pages of 2026-10-18; distilled into [batch-apis](../../research/provider-batch/batch-apis.md). |
| DOC-02 | [Next-stage evidence register](MISSION-CONTROL-NEXT-STAGE-EVIDENCE-2026-10-16.md) | open | - | Dated evidence behind PR-03. |
| DOC-03 | [Capability evolution research (2026-10-14)](../../research/mission-control/capability-evolution-2026-10-14.md) | open | - | Starting research of PR-03; lives under `docs/research/mission-control/` as a Research note. |
