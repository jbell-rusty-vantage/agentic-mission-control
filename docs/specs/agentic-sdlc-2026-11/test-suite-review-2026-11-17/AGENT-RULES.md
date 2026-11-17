---
type: Working Notes
title: "Test suite review: shared rules for the implementing agents (OVE-238)"
description: "The rules every agent implementing the 2026-11-17 test-suite review follows: scope boundaries, file hygiene on Windows, verification, commits and reporting."
tags: [mission-control, tests, sdlc, agents]
---

# Shared rules for the agents implementing OVE-238

Read [RECOMMENDATION.md](RECOMMENDATION.md) first: §1 states the rule for test doubles, and §3 names the canonical set. The exact builder names each support module must export are in [REVIEWER-NOTES.md](REVIEWER-NOTES.md#a-fixtures). Per-file verdicts are in [verdicts.tsv](verdicts.tsv), with columns `path, verdict, target, tests, lines, behaviour, doubles, reason`. Read the repository [AGENTS.md](../../../../AGENTS.md) and [tests/AGENTS.md](../../../../tests/AGENTS.md).

## Scope and safety

- Work only on the files your brief names. Never touch these:
  - `docs/specs/archive/fast-track-2026-10/*.py` and `scripts/skills_manifest.py`: their pre-existing uncommitted line-ending changes belong to someone else.
  - `.runtime/`, `docs/specs/production-architecture-2026-11/`, `education prompt.txt`.
- Preserve behaviour. Moving a builder never changes a test's assertions. When a test must change what it asserts, say so in your report.
- Never stage with `git add -A`, `git add .` or `git commit -a`. Stage the exact paths you changed.
- No paid model or web calls, no pushes, no deployment, no destructive database work outside disposable `mct_*` databases.

## Files on Windows

- Python's `Path.write_text` writes CRLF on Windows. Write LF: use `write_bytes(text.encode("utf-8"))` or `open(p, "w", newline="\n")`.
- Before committing, check that `git diff --stat` shows only the lines you meant to change. A whole-file diff means you changed the line endings; fix it.
- Python on Windows prints `\r\n`. Strip it before piping file names into shell commands.

## Verification before every commit

- `.venv/Scripts/ruff.exe check <paths>` and `.venv/Scripts/ruff.exe format <paths>`.
- `.venv/Scripts/ty.exe check` (fast types). Run `make typecheck` (mypy) when you change `src`.
- `.venv/Scripts/python.exe -m pytest tests --collect-only -q -p no:cacheprovider`: report the count before and after, and explain any change.
- Run the affected selection, and before your final commit run `.venv/Scripts/python.exe -m pytest tests/unit tests/architecture tests/conformance -q -n 3 -p no:cacheprovider`.
  - Never more than `-n 3`; the machine has about 3 GB free.
  - The baseline after steps 0 and 1 is green except tests skipped behind environment gates.
- Integration, acceptance and qualification tests need PostgreSQL 17 and Temporal. Without them, at least collect them, and report them as **unrun**.

## Commits

One logical change per commit, on the branch you are given. The message ends with:

```
Refs: OVE-238 | AS-S5
Docs: none (tests only)        (or the doc you changed)
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

The pre-commit hooks (ruff, ty, provenance) run on commit. Fix what they report; never bypass them.

## Report

Your final message is at most 15 lines:
- the commits (sha and subject);
- collected test counts before and after;
- the suites you ran, with passed, failed, skipped and unrun counts;
- anything you could not finish, or changed in behaviour, with the file.
