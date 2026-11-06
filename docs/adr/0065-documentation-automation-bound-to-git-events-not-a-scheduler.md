---
type: Decision Record
title: "Documentation automation is bound to git events, not a scheduler"
description: "Accepted 2026-11-01 (owner pre-sitting decision, AS-D7, AS-D8): documentation checks, drift detection and model-driven documentation proposals run from git hooks (pre-commit, commit-msg, post-commit, pre-push, post-merge, post-checkout, post-rewrite) and from GitHub pull request and merge jobs; drift is hash-based with a Docs: none trailer override; no scheduler, queue or watcher."
tags: [mission-control, adr, accepted, documentation, sdlc, hooks]
status: accepted
source: docs/specs/agentic-sdlc-2026-11/INTERVIEW-AGENTIC-SDLC-2026-11-01.md; answers AS-D7, AS-D8; SPEC-01 §7
---

# Documentation automation is bound to git events, not a scheduler

**Status: accepted 2026-11-01.**

## Context

The owner asked whether documentation updates should run at a chosen moment of the work or on a
schedule, and decided before the sitting: "the hooks have to be intertwined with git lifecycle of
this codebase not scheduled." Knowledge Services had piloted a SQLite job queue drained by a local
watcher, which is a scheduler in disguise; the `belllabs-method` skill named a weekly scheduled
run for the full check.

## Decision

Every documentation action has one git event that owns it (SPEC-01 §7.1): fast checks at
pre-commit, the issue key at commit-msg, drift recording at post-commit, the drift and benchmark
gates at pre-push with an on-request model proposal, regeneration after merge, checkout and
rewrite, the provider steps in the pull request job, and indexes, release notes and Linear
transitions in the merge job. Drift is deterministic: a registered module's normalized source hash
changed since the last build and no associated concept changed, unless a commit carries `Docs:
none <reason>`. The installer is stateless; the KS queue and watcher are retired and archived as
evidence. The only time-based mechanism permitted later is a safety net re-running the merge job.

## Consequences

A docs change is always attributable to the commit that caused it. Pushes can be blocked; the
override is explicit and recorded. Model-driven work never runs unattended on a timer.
