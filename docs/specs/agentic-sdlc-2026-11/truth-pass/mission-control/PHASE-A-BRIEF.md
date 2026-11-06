---
type: Working Draft
title: "Phase A brief: rules shared by the three concept-refactor agents"
description: "Shared operating rules for the Mission Control truth-pass Phase A agents (A1 workflows, A2 runtime, A3 platform): what to read, the concept format, harvesting from the deleted spec pack, verification against code, file ownership, no-commit rule, renames register, and the report each agent returns."
tags: [mission-control, truth-pass, sdlc, refactor]
date: 2026-11-01
status: draft
---

# Phase A brief (shared by A1, A2, A3)

Repository: `C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control`, branch `sprint-oc`.
All paths below are relative to it. The program folder is `docs/specs/agentic-sdlc-2026-11/`
(`P/` below).

## Read first, in this order

1. `P/truth-pass/mission-control/REFACTOR-PLAN.md`: whole file. §1 is the owner's model, §2 the
   target map (your rows), §3 the formats. This is your contract.
2. `P/answers/AGENTIC-SDLC-SITTING-II-2026-11-02-ANSWERS.md`: the sections *MC context verbatim*
   and *Q8 verbatim* (owner's words), rows AS-D29, AS-D30, AS-D33..AS-D37.
3. `P/truth-pass/mission-control/B-KNOWLEDGE-CONCEPTS.md` (per-concept stale and contradicted
   claims; the Deep Agents group in §4) and `A-MISSION-CONTROL-GENERAL.md` (what the deleted spec
   pack holds and which items are un-propagated).
4. `GLOSSARY.md` (use its terms; honour its Avoid lists), the root `AGENTS.md` Invariants section,
   and `P/CONCEPT-LISTS-DRAFT-2026-11.md` MC section (drafted `questions[0]`, aliases).

## Rules

- **Harvest from `HEAD`.** `mission-control-general/` is mostly deleted in the working tree. Read
  any of its files with `git show HEAD:mission-control-general/<path>`. Never restore them to disk.
  Carry what is still true and un-propagated into your concepts; anything that is a product idea,
  not behaviour, goes to the "ideas" list in your report.
- **Verify against code.** Every load-bearing claim is checked in `src/`, `packages/`, `tests/`,
  `deployments/` and cited `path:line`. Label built behaviour implemented / tested / integrated /
  qualified with a committed proof path (tests, `docs/specs/**/REPORT.md`, `RELEASE-BUNDLE.md`,
  `NEXT-SESSION.md` lines). Never cite a `.scratch/` path alone (AS-D29). Specified-not-built and
  goals are stated as such, never as built.
- **Format (REFACTOR-PLAN §3).** Frontmatter: `type: Concept`, `category`, `title`,
  `description`, `tags`, `aliases`, `questions` (≥3, `questions[0]` ≤70 chars), `updated:
  2026-11-01`. ≤160 lines. Snippets of important deep-module interfaces allowed with a
  `<!-- snippet: path:start-end -->` anchor (keep each under ~15 lines). Entrypoint/file-role
  inventories do not belong in concepts. End with `## Citations`. Where §1.3 applies, cover
  scheduling, output-contract obligations, context transfer, runtime and capability configuration,
  in that order, and end with a one-line "Built / specified / goal" summary.
- **Ownership.** Edit only the concept files your prompt lists (and new files it names). Do not edit
  `docs/knowledge/index.md`, `docs/knowledge/log.md`, `AGENTS.md`, ADR files (A1 may write the
  ADR-0068 *draft* at `P/truth-pass/mission-control/ADR-0068-DRAFT.md`), or other agents'
  concepts. If another agent's concept is wrong, note it in your report.
- **Renames and merges.** When you merge or rename a concept, delete the absorbed file and append
  one line per change to `P/truth-pass/mission-control/RENAMES.md` (`old.md -> new.md (reason)`;
  create the file if absent; append only). Phase B rewrites inbound links repo-wide. Links inside
  your own files must already point at the new names.
- **Do not commit, do not stage.** Other agents are editing the same repository concurrently and
  the pre-commit hook stashes unstaged work. Leave your changes in the working tree; the
  coordinator commits each agent's files after all three finish.
- No source-code behaviour changes. No paid model runs, no network calls to providers, no remote
  databases. Never print `.env` values.
- Check your own files before reporting: frontmatter complete, ≤160 lines (`wc -l`), every
  relative link resolves (a quick script over your files is fine), no `.scratch/`-only proof.

## Report (≤300 words)

Files created / rewritten / deleted (exact paths); line counts; renames appended; un-propagated
spec-pack items you placed and where, and any you deliberately left out (with reason); product ideas
found; code defects found (for OVE issues); claims you could not verify; anything another agent
must fix.
