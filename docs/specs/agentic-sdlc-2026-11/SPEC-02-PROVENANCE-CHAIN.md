---
type: Specification
title: "SPEC-02 Provenance chain v1: interview to completion, in Mission Control"
description: "The lean provenance chain the owner approved on 2026-11-17 (AS-S3, AS-D40..AS-D46): the six record types and their fixed keys, the commit trailer grammar, the Completion comment, the trace tool's commands, graph and check rules, the warn-then-block enforcement, and what was left out. Mission Control first; with platform/agentic-sdlc deleted (AS-D65), this copy is the one other repositories take."
tags: [mission-control, agents, process, sdlc, provenance, spec]
date: 2026-11-17
status: accepted
decisions: [AS-D40, AS-D41, AS-D42, AS-D43, AS-D44, AS-D45, AS-D46]
linear: [OVE-225, OVE-207]
source: answers/AGENTIC-SDLC-SITTING-III-2026-11-17-ANSWERS.md
---

# SPEC-02 Provenance chain v1

Supersedes nothing; it narrows SPEC-01 §6.1 and amends its §7.2 (AS-D42). Source of the design: the BellLabs handoff of
2026-11-17 (`docs/state/2026-11-17/HANDOFF.md` §3.6, at the workspace root, which is not a repository) and its deep report
`PROVENANCE-AND-SDLC.md` §4. Scope is this repository only (AS-D41).

<a id="chain"></a>
## 1. The chain

```text
Interview   answers file, id <FAM>-S<n>      the owner's words verbatim; harness session id
  → Decision   a row <FAM>-D<n>               Becomes / Folded name where it goes
  → Spec       a repo file                    frontmatter decisions: [...] and linear: [...]
  → Issue      Linear OVE-n                   Goal: line, then ## Provenance with fixed keys
  → Commit     trailers                       Refs: / Decisions: / Docs:
  → Completion Linear comment ## Completion   Commits / Checks / Evidence / Level / Verified-by
```

Links point backwards in time only: a later record cites earlier ones. Git and Markdown are canonical; Linear is the queue;
the trace is derived and never edited.

<a id="records"></a>
## 2. Record formats

| Record | Where | Id | Fixed fields |
| --- | --- | --- | --- |
| Session | `docs/specs/<program>/answers/*-ANSWERS.md`, always committed (never `.scratch/`) | `<FAM>-S<n>` | Frontmatter `id`, `family`, `harness_session` (`claude-code:<uuid>`, `codex:<id>`, `cursor:<id>`), `idea` (optional), plus the template's fields |
| Decision | A row of the session's *Decisions* table | `<FAM>-D<n>` | The template columns; *Answer* is verbatim; accepting a recommendation quotes it |
| Spec | Any Markdown file in the repository | path + explicit anchor | Frontmatter `decisions: [..]`, `linear: [..]` |
| ADR | `docs/adr/NNNN-*.md` | `ADR-NNNN` | As today |
| Issue | Linear team OVE | `OVE-n` | Line 1 `Goal: platform/mission-control/goals#<anchor>[, <anchor>]`; a `## Provenance` section of `Key: value` lines with keys `Session`, `Decisions`, `Spec` (`mission-control:<path>#<anchor>`), `ADR`, `Idea`, `Conversation`, `Terms` |
| Completion | A Linear comment on the issue, posted when the work is done | — | `## Completion`, then `Commits:` (`mission-control@<sha>`, ...), `Checks:` (command and passed/failed/blocked/unrun), `Evidence:` (path, run id or `none <reason>`), `Level:` (`implemented`, `tested`, `integrated` or `qualified`), `Verified-by:` (`self` or a session/person) |

Session ids are numbered per family in sitting order; the existing sittings were given ids on 2026-11-17 (`AS-S1`, `AS-S2`,
`OC-S1`). Goal anchors are the `goals.md` headings and its vision ids (`S0`..`S5`, `P`, `L1`, `L3`, `SDLC`).

<a id="trailers"></a>
## 3. Commit trailers (AS-D42)

```text
feat(trace): <subject>

Refs: OVE-225, AS-S3
Decisions: AS-D40, AS-D44
Docs: docs/agents/issue-tracker.md
Co-Authored-By: ...
```

- `Refs:` one or more of `OVE-n`, `<FAM>-S<n>`, `<FAM>-D<n>`, `ADR-NNNN`, `ID-n`, comma separated, repeatable; or
  `Refs: none <reason>` for a pure chore. A record id counts as well as an issue: work that ran without an issue stays
  traceable, and `COVERAGE.md` counts the commits whose chain never reaches an issue.
- `Decisions:` optional decision ids. `Docs:` a path, `none <reason>` or `proposed-by <provider> <session>` (SPEC-01 §7.2).
- The legacy subject suffix `(OVE-n)` still counts as a `Refs:`.

<a id="trace"></a>
## 4. The trace tool

`docs/tools/trace.py`, standard-library Python, run as `./dev trace ...` or `python -X utf8 docs/tools/trace.py ...`.

| Command | Does |
| --- | --- |
| `show <id>` | Prints the chain around any id (`OVE-n`, `AS-S3`, `AS-D40`, `ADR-0064`, `ID-1`, a commit SHA or a file path); `--json` |
| `build` | Writes `.sdlc/trace/trace.json` (nodes and edges) and `.sdlc/trace/COVERAGE.md`; prints a JSON summary |
| `check` | Applies §5 to the records, the cached issues and the commits since the cutover; `--message-file F` checks one commit message (the hook); `--range A..B` checks a range (CI) |
| `linear pull` | Writes `.sdlc/trace/linear-snapshot.json` through the Linear GraphQL API; reads `LINEAR_API_KEY` from the environment or the repository `.env` and never prints it. In a session without a key the agent writes the same file from the Linear MCP |

`.sdlc/trace/` is git-ignored: the snapshot holds issue text and this repository is public. Without a snapshot, `OVE-n` ids
are checked for shape only. The graph's edge kinds: `asked_in` (decision → session), `serves` (session → idea), `becomes`
and `folded_into` (decision → target), `decides` and `tracks` (spec → decision, issue), `provenance` (issue → record),
`child_of` (issue → parent), `implements` and `decides` (commit → record), `completes` (issue → commit). `show` does not
walk through hubs (ideas, ADRs, parent issues) unless the walk starts there.

<a id="check"></a>
## 5. Check rules and enforcement (AS-D46)

| Applies to | Rule |
| --- | --- |
| Commit (author date on or after the cutover, 2026-11-17) | Has `Refs:` (or `(OVE-n)`); every id has a known shape; session, decision and ADR ids resolve in the repository; `OVE-n` resolves in the snapshot when one exists |
| Session (dated on or after the cutover) | Has `id`, `family` and `harness_session` |
| Decision | `Becomes: OVE-n` resolves in the snapshot when one exists (the final-file rules stay in `program_ledger.py check`) |
| Issue (created on or after the cutover) | Has a `Goal:` line whose anchors resolve and at least one resolvable `## Provenance` key |
| Issue (completed on or after the cutover) | Has a `## Completion` comment with `Commits:` and `Level:` |

The mode is `SDLC_TRACE=warn` (default: report, exit 0) or `block` (exit 1 on a problem). The commit-msg hook (prek) and the
CI step both run warn-only from 2026-11-17; the switch to `block` waits for the owner's yes, due two weeks later.

<a id="out"></a>
## 6. Not in v1

The surface is Linear and the CLI (AS-D43); a `/provenance` page in mission-control-web comes later. Not in v1: the other
repositories (they copy this tool when they adopt it; there is no upstream since AS-D65), the legacy-bundle and alias
backfill, the Linear reconciliation, the remote mirror (SPEC-01 §6.3), feature maps and `dev drive`.

<a id="decisions"></a>
## 7. Decisions asked (the sitting's instrument)

The plan presented on 2026-11-17 asked these, each with a recommendation: (1) the tool's home, (2) what `Refs:` accepts,
(3) where the completion record lives, (4) the surface, (5) the parent issue, (6) the enforcement mode, under an overall
approval of work items U1-U8. The answers are in the [sitting III answers](answers/AGENTIC-SDLC-SITTING-III-2026-11-17-ANSWERS.md).
