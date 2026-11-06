---
type: Decision Record
title: "Auto-merge on green checks during the startup phase, with protected paths and a hold label"
description: "Accepted 2026-11-01 (AS-D16, AS-D18) with a sunset: pull requests whose required checks (check, bench, drift, tests, review-posted) are green squash-merge automatically unless labelled hold or touching a protected path (migrations, workflows, the toolchain locks); docs-only pull requests skip the review check; revisited when the startup delivery mode ends."
tags: [mission-control, adr, accepted, sdlc, process]
status: accepted
source: answers AS-D16, AS-D18; AGENTS.md startup delivery mode (2026-10-31); SPEC-01 §7.5
---

# Auto-merge on green checks during the startup phase, with protected paths and a hold label

**Status: accepted 2026-11-01. Sunset: when the startup delivery mode is replaced by the more robust SDLC.**

## Context

The owner's startup delivery mode says break things and move fast; a human merge on every agent
pull request would make the agents wait on the owner. The owner decided: "we are going to allow
auto merging on remote branches in this start up phase."

## Decision

Branch protection on `main` requires the status checks `check`, `bench`, `drift`, `tests` and
`review-posted`. A pull request with green required checks squash-merges automatically unless it
carries the label `hold` or touches a protected path: `packages/*/migrations/**`,
`supabase/migrations/**`, `.github/workflows/**`, `.sdlc/lock.json`, `skills-lock.json`; those keep
a human merge. Docs-only pull requests (`docs/`, `GLOSSARY.md`, `.sdlc/` except the lock) skip
`review-posted`.

## Consequences

Agents can complete a documentation or code change end to end. Schema, workflow and toolchain
changes still pass through the owner. The rule is recorded here so it can be withdrawn in one place.
