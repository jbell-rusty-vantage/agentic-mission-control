---
type: Working Draft
title: "Phase B brief: ADRs, spec-pack deletion, programs, other surfaces, AGENTS.md, fixtures and bench"
description: "The sequential Phase B of the Mission Control truth pass, run by one Sonnet 5.5 agent after Phase A's concepts are committed: ADR acceptance and ADR-0068, deletion of mission-control-general, link rewrites from RENAMES.md, program archiving and the NEXT-SESSION split, other surfaces and .scratch untracking, the compressed AGENTS.md with its generator, the retrieval fixtures, the before/after bench, and verification."
tags: [mission-control, truth-pass, sdlc, refactor]
date: 2026-11-01
status: draft
---

# Phase B brief

Repository `platform/mission-control`, branch `sprint-oc`; `P/` = `docs/specs/agentic-sdlc-2026-11/`.
Contract: `P/truth-pass/mission-control/REFACTOR-PLAN.md` §4 Phase B, §5, §6. Read it, the
`PHASE-A-BRIEF.md` rules (formats, evidence, `.scratch` rule), `C-PROGRAMS-ADRS-ARCHIVE.md`,
`D-OTHER-SURFACES.md`, `P/AGENTS-MD-MISSION-CONTROL-DRAFT-2026-11.md` (DOC-08; G1-G16 accepted),
`P/RETRIEVAL-AUDIT-BASELINE-2026-11.md` §4 (miss cases), `TASK-FIXTURE-T001-SANDBOX-PROVIDER.md`,
and the Phase A agents' reports in `PHASE-A-REPORTS.md` (same folder).

You are the only writer in the repository now: commit as you go, one logical commit per step,
`<type>(<scope>): <subject> (OVE-206)`, ending `Co-Authored-By: Claude Sonnet 5.5
<noreply@anthropic.com>`; stage explicit paths only (never `git add -A`; this session's own program
files under `P/` are committed by the coordinator). Do not push. No paid runs, no remote operations,
no source behaviour changes (test files only where a hard-coded document path moves).

## Step 0: the "before" bench (first, before any other change)

The documentation before the refactor is commit `66185d2e` (`BEFORE_COMMIT`; Phase A's changes
are committed after it). `git worktree add <a temp dir outside the repo>/mc-bench-before 66185d2e`.
Write the fixtures first (Step 6 format) into a temporary file, run each case
through that worktree's `python docs/tools/okf_search.py "<query or task>" --limit 10 --json`, score
recall@3, recall@10, MRR and set recall per `expect` field, save as `baseline-before.json`. Remove
the worktree afterwards (`git worktree remove`).

## Steps 1-7

Exactly REFACTOR-PLAN §4 Phase B steps 1-7, with these specifics:

1. ADR-0068 from `P/truth-pass/mission-control/ADR-0068-DRAFT.md` into `docs/adr/0068-*.md`.
2. Before `git rm -r mission-control-general`, confirm with A's harvest notes that nothing still
   un-propagated remains (A-MISSION-CONTROL-GENERAL §3 rows each have a destination or a recorded
   reason). Rewrite every inbound link (grep the whole repo, including `src/`, `tests/`, `skills/`,
   `.agents/skills/` only where MC-specific). Apply every line of `RENAMES.md` the same way.
3. Programs: follow C §3 and §8; keep `docs/specs/agentic-sdlc-2026-11/` untouched.
5. `AGENTS.md`: the root file ≤14 KiB; the generated block is produced by your updated
   `docs/tools/agents_docs_index.py` and `--check` passes. `docs/knowledge/index.md` is rebuilt by
   the same or the existing generator with the nine categories; `log.md` gets one entry for this
   refactor.
6. Fixtures: `.sdlc/fixtures/retrieval/queries.json` and `baseline.json` (after), plus
   `baseline-before.json` from Step 0; a short `README.md` there explaining kinds, partitions,
   `critical`, and the rule that baselines move only with a concept change in the same PR.
7. Verification commands and their results go into your report verbatim (pass/fail counts).

## Report (≤350 words)

Commits (hash, subject); before/after bench table (per partition: recall@3, recall@10, MRR; T001
set recall per field; critical pass/fail); `AGENTS.md` byte counts; files archived/deleted/untracked
counts; checks with results; anything left undone and why; code issues to file.
