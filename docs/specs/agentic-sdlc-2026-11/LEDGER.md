---
type: Program Ledger
title: "Agentic SDLC ledger: where the interview, the specification, the hooks and the audits stand"
description: "The pointer and progress register of the agentic-sdlc program (fact placement and information categories across the four codebases, git-lifecycle documentation hooks, retrieval fixtures as quality gates, the idea-to-Linear provenance chain, and the Claude Code cloud environment). One row per document or work item; convention in docs/agents/program-workspace.md, verified by docs/tools/program_ledger.py."
tags: [mission-control, agents, process, documentation, sdlc, ledger]
---

# Agentic SDLC ledger

Last reconciled **2026-11-01**. Active. The convention, status words and closing checklist are in
[docs/agents/program-workspace.md](../../agents/program-workspace.md); check with
`python docs/tools/program_ledger.py check --program docs/specs/agentic-sdlc-2026-11`.

**Next step of the program:** read [HANDOFF-2026-11-02](HANDOFF-2026-11-02.md). Sitting II is in progress
(AS-D21..AS-D39): the Mission Control truth pass is done and measured (screening recall@3 0.48 → 1.00,
critical 7 → 12 of 15; task fixtures T001-T003 still fail on tooling); module guides are generated from
`.sdlc/modules.json`; the `sdlc-docs` skill lives upstream in `platform/agentic-sdlc` and is pinned in MC.
Next: Mission Control experimentation with real tasks, then the Knowledge Services truth pass, then BKS
and AI Engineer; `NAVIGATION-DESIGN.md` and S1 (OVE-207) follow. Everything runs on `sprint-oc`.

**Linear.** Every item that will be built gets an `OVE` issue before work starts (rule 1 of the
convention). Nothing earlier is back-filled.

Status words: `planned` · `draft` · `open` (waiting for an owner decision) · `accepted` · `active` ·
`done` · `archived`.

## Proposals

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| PR-01 | [The agentic SDLC system (2026-11-01)](SDLC-SYSTEM-PROPOSAL-2026-11-01.md) | accepted | - | Accepted as final (AS-D9); §5 rewritten for the Cursor-first provider adapter (AS-D10); §9 ideas workspace and §10 mirror considerations adopted (AS-D13, AS-D14). Carried by SP-01 and ADR-0064..0067. |

## General documentation

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| DOC-01 | [Information categories draft (2026-11-01)](INFORMATION-CATEGORIES-DRAFT-2026-11-01.md) | accepted | - | Accepted with its three defaults (AS-D6); SP-01 §5 points here. Concepts are authored in slices S2..S4. |
| DOC-02 | [Compressed AGENTS.md grammar draft (2026-11-01)](AGENTS-MD-GRAMMAR-DRAFT-2026-11-01.md) | draft | OVE-206 | Best effort for sitting II (Q13, Q14): reading order, budgets and gates, generated block grammar at root and module level, the INFRASTRUCTURE table, sidecar files, update rules, the Mission Control worked example. |
| DOC-03 | [State inventory: Mission Control (2026-11)](STATE-mission-control-2026-11.md) | draft | OVE-206 | Sitting II preparation: versions, recent work labelled implemented/tested/integrated/qualified with proof paths, programs by status, dirty files, discrepancies. Finalized after Q1/Q2. |
| DOC-07 | [Concept lists per codebase (2026-11)](CONCEPT-LISTS-DRAFT-2026-11.md) | draft | OVE-206 | Sitting II preparation for Q3-Q7: every existing and proposed concept per codebase with category, status, `questions[0]`, aliases, sources; merge candidates; depth samples. |
| DOC-08 | [Compressed Mission Control AGENTS.md draft (2026-11)](AGENTS-MD-MISSION-CONTROL-DRAFT-2026-11.md) | draft | OVE-206 | Sitting II preparation for Q13-Q14: the full file built by hand under DOC-02 (10,460 B vs 29,624 B today), byte table, where every removed line went, two module blocks, sixteen grammar edits. |
| DOC-09 | [Baseline retrieval audit, MC and KS (2026-11)](RETRIEVAL-AUDIT-BASELINE-2026-11.md) | draft | OVE-206 | Eight criteria scored 0-10 with file evidence (MC 40/80, KS 43/80); KS bench 17/18 screening (down from 18/18), 6/6 held-out; 62-question log; 34 candidate fixture cases from misses. Baseline for S6. |
| DOC-10 | [Infrastructure map draft (2026-11)](INFRASTRUCTURE-MAP-DRAFT-2026-11.md) | draft | OVE-206 | Sitting II preparation for Q11-Q12: workspace and per-repository tables in the DOC-02 §4 shape, env variable name matrix (names only), naming inconsistencies, stale entries. |
| DOC-11 | [MC truth pass A: mission-control-general](truth-pass/mission-control/A-MISSION-CONTROL-GENERAL.md) | draft | OVE-206 | Propagation map of the original spec pack: un-propagated knowledge (OC-D204/D205, Goal Loop model, middleware order), contradictions, dispositions. |
| DOC-12 | [MC truth pass B: knowledge concepts vs code](truth-pass/mission-control/B-KNOWLEDGE-CONCEPTS.md) | draft | OVE-206 | 64 concepts checked: 13 fresh, 19 minor drift, 7 stale, 25 contradicted; Deep Agents group proposal. |
| DOC-13 | [MC truth pass C: programs, ADRs, archive](truth-pass/mission-control/C-PROGRAMS-ADRS-ARCHIVE.md) | draft | OVE-206 | 63 program documents to archive, 29 working; 23 built-but-proposed ADRs; NS split; reading path. |
| DOC-14 | [MC truth pass D: other surfaces](truth-pass/mission-control/D-OTHER-SURFACES.md) | draft | OVE-206 | 324 Markdown files triaged; 13 module blocks; tracked `.scratch` (101 files); CLAUDE.md added (`66185d2e`). |
| DOC-15 | [Task fixture T001: sandbox provider across workflow types](truth-pass/mission-control/TASK-FIXTURE-T001-SANDBOX-PROVIDER.md) | draft | OVE-206 | First task-shaped fixture (AS-D32): concept recall 1/7, code 0/11, research 0/1; hidden facts (Daytona half-wired). |
| DOC-16 | [MC documentation refactor plan](truth-pass/mission-control/REFACTOR-PLAN.md) | draft | OVE-206 | The owner's model restated, target knowledge map by category, formats, phases A (three parallel Sonnet agents) and B (one sequential), acceptance, code issues. Awaiting owner go. |
| DOC-17 | [Phase A brief](truth-pass/mission-control/PHASE-A-BRIEF.md) | done | OVE-206 | Shared rules for the three concept agents; Phase A committed `6f868a08`, `0c8b80c6`, `4590813e`. |
| DOC-18 | [Phase A reports](truth-pass/mission-control/PHASE-A-REPORTS.md) | active | OVE-206 | A1/A2/A3 outcomes, code defects for OVE issues, Phase B follow-ups, loose `platform/` documents intake. |
| DOC-19 | [Concept renames register](truth-pass/mission-control/RENAMES.md) | active | OVE-206 | Seven renames/merges; Phase B rewrites inbound links from it. |
| DOC-20 | [ADR-0068 draft](truth-pass/mission-control/ADR-0068-DRAFT.md) | draft | OVE-206 | Swarm as Stage Graph profile, Evaluator Optimizer on Goal Loop machinery (AS-D34); Phase B moves it to `docs/adr/`. |
| DOC-21 | [Phase B brief](truth-pass/mission-control/PHASE-B-BRIEF.md) | active | OVE-206 | Sequential Phase B: before-bench at `66185d2e`, ADRs, spec-pack deletion, programs, surfaces, AGENTS.md, fixtures, verification. |
| DOC-22 | [Code issues found by the MC truth pass](truth-pass/mission-control/CODE-ISSUES.md) | draft | OVE-206 | 29 rows from the Phase A and B agents (evidence path:line, suggested owner program); the coordinator files the Linear issues. None was fixed in the refactor. |
| HO-01 | [Handoff 2026-11-02](HANDOFF-2026-11-02.md) | active | OVE-206 | Where the program stands and the exact next steps: MC experimentation, KS truth pass, close S0.5. §4.1 steps 1-3 done 2026-11-02 as real Sprint OC work (DOC-23; Linear OVE-215..223 filed, OVE-149 closed). |
| DOC-23 | [Navigation experiment 2026-11-02](truth-pass/mission-control/NAV-EXPERIMENT-2026-11-02.md) | active | OVE-206 | 13 real lookups, 3 wrong facts fixed in concepts and boards; operational runbooks are the weakest dimension. Next: a tracked W1 runbook. |
| DOC-04 | [State inventory: Knowledge Services (2026-11)](STATE-knowledge-services-2026-11.md) | draft | OVE-206 | Sitting II preparation; same shape as DOC-03. Finalized after Q1/Q2. |
| DOC-05 | [State inventory: Biotech Knowledge Services (2026-11)](STATE-biotech-knowledge-services-2026-11.md) | draft | OVE-206 | Sitting II preparation; same shape as DOC-03. Finalized after Q1/Q2. |
| DOC-06 | [State inventory: ai-engineer-db-contract (2026-11)](STATE-ai-engineer-db-contract-2026-11.md) | draft | OVE-206 | Sitting II preparation; same shape as DOC-03. Finalized after Q1/Q2. |

## Specs

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| SP-01 | [SPEC-01 Agentic SDLC](SPEC-01-AGENTIC-SDLC.md) | accepted | OVE-205 | Written 2026-11-01 from AS-D1..D20, PR-01 and DOC-01: principle, architecture, stack, every env var and infrastructure location, git-event table, provider adapter, Linear, slices S0..S8 with acceptance, the ten open items of the navigation-quality session (§12). Linear ids added at conversion. |

## Issues

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| IS-01 | Program parent | planned | OVE-205 | holds the slices; provenance to ID-1, SPEC-01, ADR-0064..0067 |
| IS-02 | S0.5 navigation-quality session | planned | OVE-206 | next; SESSION-NAVIGATION-QUALITY |
| IS-03 | S1 the sdlc CLI | planned | OVE-207 | blocked by S0.5 |
| IS-04 | S2 vendor into Mission Control | planned | OVE-208 | after S1 |
| IS-05 | S3 KS, BKS, AIDB | planned | OVE-209 | after S2 |
| IS-06 | S4 AI Engineer meta and Biotech contract, workspace map | planned | OVE-210 | after S3 |
| IS-07 | S5 provider adapter, CI, auto-merge | planned | OVE-211 | after S2; owner places secrets and enables Bugbot |
| IS-08 | S6 retrieval audits | planned | OVE-212 | after S4 |
| IS-09 | S7 remote mirror | planned | OVE-213 | after trace works |
| IS-10 | S8 cloud environments | planned | OVE-214 | last |

## Interview instructions

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| IQ-01 | [Agentic SDLC interview (2026-11-01)](INTERVIEW-AGENTIC-SDLC-2026-11-01.md) | done | - | Sitting I complete: twenty questions in five rounds, facts F1..F16. |
| IQ-02 | [Sitting II instrument: state, knowledge, goals, infrastructure, AGENTS.md (2026-11-02)](INTERVIEW-NAVIGATION-AND-KNOWLEDGE-2026-11-02.md) | active | OVE-206 | Rounds 1, 3 and 5 asked (with the owner steering into per-codebase truth passes); rounds 2 (Q5, Q6) and 4 (Q11, Q12) and Q9, Q17 open; carried by the handoff. |

## Interview answers

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| IA-01 | [AGENTIC-SDLC sitting I: answers](answers/AGENTIC-SDLC-SITTING-I-2026-11-01-ANSWERS.md) | done | OVE-205 | AS-D1..D20 recorded in the owner's words; converted into SP-01, ADR-0064..0067, glossary terms, the Linear project and issues. |
| IA-02 | [AGENTIC-SDLC sitting II: answers](answers/AGENTIC-SDLC-SITTING-II-2026-11-02-ANSWERS.md) | open | OVE-206 | AS-D21..AS-D39 recorded in the owner's words; conversion pending (NAVIGATION-DESIGN.md, goals charter, Linear issues); see the handoff. |

## Sessions

| ID | Item | Status | Linear | Progress and next step |
| --- | --- | --- | --- | --- |
| SE-01 | [Session: navigation and retrieval quality](SESSION-NAVIGATION-QUALITY.md) | active | OVE-206 | In progress: preparation done (DOC-03..DOC-10), MC truth pass done (DOC-11..DOC-22), KS/BKS/AIDB passes and NAVIGATION-DESIGN.md remain ([handoff](HANDOFF-2026-11-02.md)). |
