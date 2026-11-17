---
type: Interview Answers
title: "AGENTIC-SDLC, sitting III: the owner's answers"
description: "The decisions the owner took in sitting III on 2026-11-17: approval of the provenance chain v1 plan for Mission Control (work items U1-U7 now, U8 push on a separate go) and its six recommendations: tool home, Refs grammar, completion record, surface, parent issue and enforcement."
tags: [mission-control, interview, answers, provenance]
id: AS-S3
family: AS
harness_session: claude-code:b6a402b2-f9e7-48f9-bbe7-764d5e829252
idea: ID-1
interview: ../SPEC-02-PROVENANCE-CHAIN.md#decisions
sitting: "III"
date: 2026-11-17
status: final
---

# AGENTIC-SDLC, sitting III: answers

Instruction: the plan presented in the session, recorded as [SPEC-02 §7](../SPEC-02-PROVENANCE-CHAIN.md#decisions)
(front matter `interview:`). Recorded by the interviewing agent on 2026-11-17. The owner's opening request, verbatim:
"I'm sure we can construct a interview -> spec -> issues -> completion provenance chain that we can surface and we will
start operating like going forward." and "REMEMBER we need to get back to developing the features as soon as possible."

## Decisions

| ID | Source | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AS-D40 | ID-1 | Approve the Mission Control provenance plan (U1-U8)? | "approve. All recommendations approved." | 2026-11-17 | U1-U7 are built now in Mission Control only; U8 (push of the 19 laptop-only commits plus this work) waits for a separate "go". Every other handoff fast win stays deferred | OVE-225 | [SPEC-02](../SPEC-02-PROVENANCE-CHAIN.md#chain) |
| AS-D41 | ID-1 | Where does the trace tool live? Recommended: "build it in Mission Control now as Python, and move it upstream when KS adopts it" | "approve. All recommendations approved." | 2026-11-17 | `docs/tools/trace.py`, standard library only; not `trace.mjs` in agentic-sdlc yet. ADR-0064's vendored-toolchain rule holds: MC is the first copy | spec SPEC-02-PROVENANCE-CHAIN.md §4 | [SPEC-02 §4](../SPEC-02-PROVENANCE-CHAIN.md#trace) |
| AS-D42 | ID-1 | What does `Refs:` accept? Recommended: "both issue ids and record ids such as AS-S3 or B08-S29" | "approve. All recommendations approved." | 2026-11-17 | Amends SPEC-01 §7.2: a commit cites `OVE-n` or a registered record id; the `(OVE-n)` suffix still counts; `Refs: none <reason>` for chores | spec SPEC-02-PROVENANCE-CHAIN.md §3 | [SPEC-01 §7.2](../SPEC-01-AGENTIC-SDLC.md#72-commit-message-contract) |
| AS-D43 | ID-1 | Where does the completion record live? Recommended: "a Linear comment with fixed keys" | "approve. All recommendations approved." | 2026-11-17 | A `## Completion` comment (Commits, Checks, Evidence, Level, Verified-by) closes each issue; trace reads it from the snapshot | spec SPEC-02-PROVENANCE-CHAIN.md §2 | [issue-tracker.md](../../../agents/issue-tracker.md#completion) |
| AS-D44 | ID-1 | Surface? Recommended: "Linear plus the CLI now" | "approve. All recommendations approved." | 2026-11-17 | The owner reads the chain per thread in Linear and with `./dev trace show <id>`; the mission-control-web `/provenance` page is deferred | spec SPEC-02-PROVENANCE-CHAIN.md §6 | [SPEC-02 §6](../SPEC-02-PROVENANCE-CHAIN.md#out) |
| AS-D45 | ID-1 | Parent issue? Recommended: "reuse OVE-207" | "approve. All recommendations approved." | 2026-11-17 | The work is OVE-225, a child of OVE-207 (S1, the sdlc CLI) | OVE-225 | [LEDGER IS-11](../LEDGER.md#issues) |
| AS-D46 | ID-1 | Enforcement? Recommended: "warn for two weeks, then block on your yes" | "approve. All recommendations approved." | 2026-11-17 | The commit-msg hook and the CI step run with `SDLC_TRACE=warn`; switching to `block` is a separate owner yes, due 2026-12-01 | spec SPEC-02-PROVENANCE-CHAIN.md §5 | [SPEC-02 §5](../SPEC-02-PROVENANCE-CHAIN.md#check) |

## Mental model restated

From today a piece of work starts with an answers file like this one, becomes a spec section and a Linear issue whose
`## Provenance` names the session and decisions, is built in commits whose trailers cite the issue or the session, and ends
with a `## Completion` comment on the issue. `./dev trace show OVE-225` prints all of it.

## Assumptions (asked, not answered)

| ID | Question | Assumption taken | Risk if wrong |
| --- | --- | --- | --- |
| AS-A10 | The goal anchor for SDLC work | A `SDLC` vision id is added to `goals.md` for agent-operability work | Low: the anchor can be renamed |

## Parking lot

- The mission-control-web `/provenance` page (AS-D44), after the first feature thread produces a real chain.
- The Mission Brief's session id (handoff S1): a candidate first feature thread through this chain.

## Conversion checklist

- [x] Decisions folded into SPEC-02 and SPEC-01 §7.2 (links in **Folded**)
- [x] ADR candidates: none; ADR-0064 and ADR-0065 already carry the reasons
- [x] Glossary terms: none needed
- [x] Linear: OVE-225 filed under OVE-207 with `## Provenance`
- [x] Ledger: this file's row, SP-02 and IS-11 added
