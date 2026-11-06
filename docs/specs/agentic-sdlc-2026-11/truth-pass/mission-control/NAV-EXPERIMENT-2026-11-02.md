---
type: Implementation Evidence
title: "Navigation experiment 2026-11-02: real Sprint OC tasks against the truth-passed Mission Control docs"
description: "HANDOFF-2026-11-02 §4.1 run as real work instead of synthetic subagent tasks: every documentation lookup made while filing OVE-215..223, fixing OVE-215/216/218 and running W1 session 10, with hops, wrong facts and the fixes made in concepts. Supplements the bench, which cannot measure task navigation."
tags: [mission-control, sdlc, navigation, retrieval, experiment]
date: 2026-11-02
status: active
---

# Navigation experiment 2026-11-02

Two agents did real Sprint OC work (owner, 2026-11-02: "knock two birds with one stone"): the coordinator (Linear filing,
OVE-215/216/218 code fixes, docs) and one W1 runner subagent (session 10). Hops are the documents opened before the fact
was found. Fixes went to concepts and procedures, never to fixtures (handoff rule).

## Lookups

| # | Question | Hops | Found | Wrong or stale fact, and disposition |
| --- | --- | --- | --- | --- |
| N1 | What is next for Sprint OC? | 3 (NEXT-SESSION, SDLC ledger, handoff) | yes | NEXT-SESSION and AGENTS.md said "SESSION-NAVIGATION-QUALITY, then S1"; fixed in `docs/agents/index-notes.toml` and NEXT-SESSION |
| N2 | What remains in W1 (D27-D30)? | 1 + git log | yes | W1-EVIDENCE frontmatter said "session 1, every criterion blocked"; fix commits not cited; fixed |
| N3 | How to file an issue | 3 | yes | `issue-tracker.md` omitted the AS-D23 `Goal:` line; fixed |
| N4 | Where does compile gate behaviour per lane? | 4 (code only) | yes | no concept names `_lanes`/`lane_behaviors`; `mission-manifest` said Swarm/EO "no blocker" (now `behavior_not_built`, OVE-215) |
| N5 | Does Daytona fail at run time? | 5 (code) | yes | **wrong fact** in `deep-agents-lane` and CODE-ISSUES row 2: it is refused at compile (`ITEM_PIN_UNSERVED`); fixed |
| N6 | Why do the owner-manifest goldens fail? | 3 | yes | correct ("stale goldens"); `mission-chains` documents the `continue` default |
| N7 | How is the W1 stack started? | 7 (runner) | yes, late | commands are only in gitignored `.scratch` evidence and memory; `RUNTIME-ENVIRONMENT` §1 gave port 8000 (owner's docling MCP; W1 uses 8010); fixed the port note |
| N8 | Which tests cover D27-D30? | 2 (git) | yes | not cited by W1-EVIDENCE; fixed in its session 10 section |
| N9 | Source of AGENTS.md "Programs in flight" | 2 | yes | not stated anywhere that `docs/agents/index-notes.toml` feeds it |
| N10 | Are operator tokens valid? | 2 (runner) | yes | no document says the bearers expire; noted in `RUNTIME-ENVIRONMENT` §1 |
| N11 | Remote schema vs code | 6 (runner) | yes | NEXT-SESSION said remotes carry 1.8.0 (they carry 1.9.0) and never said the code needs unbuilt 0072 (D31); fixed |
| N12 | Temporal binary and db file for W1 | 3 (runner) | yes | only in a log header |
| N13 | Tenant id for the pack | 3 (runner) | yes | only in a review response |

## Findings

- **Concepts answered code-shaped questions in 1 hop when the fact was there** (N4, N6). The wrong facts came from the truth
  pass's own CODE-ISSUES (N5) and from hand-maintained board numbers (N1, N11), not from the generated index.
- **Operational procedure is the weakest dimension** (N7, N10, N12, N13): the W1 runbook lives in gitignored evidence. A
  tracked W1 runbook (commands, ports, token re-mint, Temporal db, tenant lookup) is the highest-value missing document.
- **Line endings:** many knowledge files are stored CRLF (autocrlf false). Git Bash `sed -i` silently converts a CRLF file to
  LF (a 450-line false diff, twice this session); edit with a tool that preserves the file's line ending.
- Bench after the fixes (`e7615b70`): screening recall@3 1.000 / MRR 0.891, held-out 1.000 / 0.854, critical 12/15
  (T001-T003 still fail), task concept set recall 0.42 / 0.58 (was 0.47 / 0.54).
